"use strict";

// ---- 画面共通nav ----
// 各HTMLに手書きすると、page追加のたび全fileの編集が要り、抜けても誰も気付かない。
// 実際 /compare はnavへの追加漏れとroute未登録で到達不能なまま残っていた。
// 定義をここ1箇所に集約し、現在地はpathnameから決める。
const NAV_ITEMS = [
  ["/", "監視"],
  ["/overview", "全体監視"],
  ["/history", "履歴"],
  ["/streamers", "配信者"],
  ["/videos", "配信者動画"],
  ["/story", "ストーリー"],
  ["/capacity", "動画容量"],
  ["/fans", "Fan台帳"],
  ["/analytics", "全体解析"],
  ["/jobs", "Job"],
  ["/assets", "素材"],
  ["/ops", "運用log"],
  ["/backup", "バックアップ"],
  ["/settings", "設定"],
];

// 末尾の / を落として現在地・link先を突き合わせる("/history/" でも履歴と見なす)。
function navPath(href) {
  return new URL(href, location.origin).pathname.replace(/\/+$/, "") || "/";
}

// navのlinkはpathで引く。badgeを付ける側が href の文字列そのもの(a[href="/jobs"])で
// 引いていた頃は、誰かがそのhrefへqueryを足した瞬間にlinkが引けなくなり、badgeの数字が
// 更新されないまま固まっていた(実際にJob tabで起きていた)。
function navLink(path) {
  return [...document.querySelectorAll(".a-nav a")]
    .find((a) => navPath(a.getAttribute("href")) === path) || null;
}

function renderNav() {
  const nav = document.querySelector("nav.a-nav");
  if (!nav) return;
  const here = navPath(location.pathname);
  nav.innerHTML = "";
  NAV_ITEMS.forEach(([href, label]) => {
    const a = document.createElement("a");
    a.href = href;
    a.textContent = label;
    if (href === here) a.className = "active";
    nav.appendChild(a);
  });
}

renderNav();

// ---- modal a11y ----
// dialogを開いた時にfocusをmodal内へ移し、閉じた時に呼び出し元へ戻す。
// focus trap(Tab循環の閉じ込め)は張らない。各modalはEsc/backdrop clickでの
// closeを個別に実装しているため、ここはfocusの移動と復帰だけを担う。
const _modalReturnFocus = new WeakMap();
function focusModalOpen(overlay, initialTarget) {
  if (!overlay) return;
  if (!_modalReturnFocus.has(overlay)) {
    const prev = document.activeElement;
    _modalReturnFocus.set(overlay, prev instanceof HTMLElement ? prev : null);
  }
  if (initialTarget && typeof initialTarget.focus === "function") initialTarget.focus();
}
function focusModalClose(overlay) {
  if (!overlay) return;
  const prev = _modalReturnFocus.get(overlay);
  _modalReturnFocus.delete(overlay);
  if (prev && document.contains(prev) && typeof prev.focus === "function") prev.focus();
}

const STATUS_LABELS = {
  idle: { badge: "IDLE", cls: "badge-idle", message: "待機中" },
  waiting: { badge: "WAITING", cls: "badge-waiting", message: "待機中" },
  connecting: { badge: "CONNECTING", cls: "badge-connecting", message: "接続中" },
  connected: { badge: "RECEIVING", cls: "badge-connected", message: "受信中" },
  reconnecting: { badge: "RECONNECTING", cls: "badge-reconnecting", message: "再接続中" },
  disconnected: { badge: "STOPPED", cls: "badge-idle", message: "停止" },
  ended: { badge: "LIVE ENDED", cls: "badge-ended", message: "配信終了" },
  error: { badge: "ERROR", cls: "badge-error", message: "Error" },
  restricted: { badge: "録画不可", cls: "badge-restricted", message: "録画不可（メンバー限定・年齢制限・署名不可のいずれか）" },
};

// Timelineはbucket 1本ごとにlabelを作るので、6時間の配信で数千回通る。
// Date.toLocaleTimeStringは呼ぶ度にformatterを組み直し、実測5,000件で413ms掛かる
// (使い回せば8ms)。時を2桁固定にするのは、既定が1桁で軸labelのHH:MM切り出しが
// "9:00:" と欠けるため。
const TIME_FORMAT = new Intl.DateTimeFormat("ja-JP", {
  hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit",
});

function fmtTime(epochSeconds) {
  return TIME_FORMAT.format(new Date(epochSeconds * 1000));
}

function fmtDateTime(epochSeconds) {
  if (!epochSeconds) return "-";
  return new Date(epochSeconds * 1000).toLocaleString("ja-JP", { hour12: false });
}

// 1行=1件を縦に追う表(運用log・Job)の時刻。toLocaleStringは0埋めをしないため
// 「2026/8/2 9:03:21」と「2026/12/12 14:03:21」で桁が揃わず、行を跨いで時刻を比べられない。
// 年は全行で同じなので落とし、月日以下を0埋めで出す(完全な日時はcellのtooltipで読める)。
function fmtDateTimeShort(epochSeconds) {
  if (!epochSeconds) return "-";
  const d = new Date(epochSeconds * 1000);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}/${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function fmtYmd(epochSeconds) {
  if (!epochSeconds) return "-";
  const d = new Date(epochSeconds * 1000);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}${m}${day}`;
}

// 人が読む日付。fmtYmd は区切りの無い連番(20260617)で、chartのlabelや突合keyのための形。
// 文中に置くと桁の切れ目が読めないので、説明文にはこちらを使う。
function fmtDate(epochSeconds) {
  if (!epochSeconds) return "-";
  const d = new Date(epochSeconds * 1000);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}/${p(d.getMonth() + 1)}/${p(d.getDate())}`;
}

function fmtDuration(seconds) {
  const h = String(Math.floor(seconds / 3600)).padStart(2, "0");
  const m = String(Math.floor((seconds % 3600) / 60)).padStart(2, "0");
  const s = String(Math.floor(seconds % 60)).padStart(2, "0");
  return `${h}:${m}:${s}`;
}

function fmtNum(value) {
  return Number(value || 0).toLocaleString("ja-JP");
}

// 画面に出す番号はSession番号(0埋め5桁)へ一本化する。録画table のPKを混ぜると、同じ録画が
// disk上の 00339_… と画面の #705 という別々の名前で呼ばれ、file名から画面を、画面からfileを
// 引けなくなる。幅は recorder.SESSION_PREFIX_WIDTH と同じ。
const SESSION_NO_WIDTH = 5;

function sessionNo(id) {
  if (id === null || id === undefined || id === "") return "";
  const n = Number(id);
  if (!Number.isFinite(n)) return String(id);
  return String(Math.trunc(n)).padStart(SESSION_NO_WIDTH, "0");
}

// 録画のfile名から拡張子を落としたstem(``00339_user_20260721_144949``)。
function recStem(rec) {
  return String((rec && rec.filename) || "").replace(/\.[^./\\]+$/, "");
}

// 録画の番号。file名の先頭を正とし、session_idはその次に見る — session削除後も行が残る
// 録画(実測136件)はsession_idがNULLだがfile名の番号は生きている。中断録画のようにfile名が
// 規約から外れているものだけがsession_id側へ落ちる。
function recNo(rec) {
  const head = /^(\d{5,})_/.exec(recStem(rec));
  if (head) return head[1];
  return sessionNo(rec && rec.session_id);
}

function recTag(rec) {
  const no = recNo(rec);
  return no ? `#${no}` : "—";
}

// 一覧・通知に出す録画の名前。file名が規約どおり(先頭に番号)ならそれ自体が番号を名乗って
// いるのでそのまま出し、外れている録画(中断時のindex.m3u8など)だけ番号を前に補う。
function recName(rec) {
  const stem = recStem(rec);
  if (/^\d{5,}_/.test(stem)) return stem;
  const tag = recTag(rec);
  if (!stem) return tag;
  return tag === "—" ? stem : `${tag} ${stem}`;
}

// Serverのerror detailは2種類が混ざる。app自身が利用者向けに書いた日本語の説明と、
// FastAPIの既定error(routeが無いときの "Not Found" 等)やPython例外のstr()で出る英語。
// 後者をそのまま画面へ出すと日本語UIの中に意味の取れない生文言が並ぶため、statusから
// 引いた日本語に置き換え、生文言はerrorのdetailに残してtooltip/consoleから辿れるようにする。
const HTTP_ERROR_TEXT = {
  400: "Requestが不正",
  401: "認証が必要",
  403: "許可されていません",
  404: "対象が見つかりません",
  405: "Serverが受け付けない操作",
  409: "他の処理と競合",
  422: "入力値が不正",
  500: "Server内部Error",
  502: "外部からの取得に失敗",
  503: "Serverが応答不能",
  504: "Serverの応答がtimeout",
};

function hasJapanese(text) {
  return /[぀-ヿ㐀-鿿！-ﾟ]/.test(text);
}

function httpError(status, detail) {
  const raw = typeof detail === "string" ? detail.trim() : "";
  const passthrough = raw && hasJapanese(raw);
  const message = passthrough
    ? raw
    : (HTTP_ERROR_TEXT[status] || `Server Error（HTTP ${status}）`);
  // 画面へ出さなかった生文言はconsoleに残す。alertのように後から辿れない出し方をする
  // 呼び出し元でも、原因の特定に必要な情報が消えないようにする。
  if (!passthrough) console.warn(`API error: HTTP ${status}${raw ? ` / ${raw}` : ""}`);
  const err = new Error(message);
  err.status = status;
  err.detail = raw;
  return err;
}

function errorDetailText(err) {
  if (!err) return "";
  const parts = [];
  if (err.status) parts.push(`HTTP ${err.status}`);
  const raw = err.detail || err.message || "";
  if (raw) parts.push(raw);
  return parts.join(" / ");
}

async function apiSend(method, path, body) {
  let res;
  try {
    res = await fetch(path, {
      method,
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    const err = new Error("Server未接続");
    err.status = 0;
    err.detail = String((e && e.message) || e);
    throw err;
  }
  if (!res.ok) {
    const payload = await res.json().catch(() => ({}));
    throw httpError(res.status, payload.detail);
  }
  return res.json();
}

// 画面を開いた直後の接続で最初に届く monitors / jobs は、pageが起動時に自分で引いた
// のと同じ内容を運んでくる。これを合図に取り直すpageは、開くたびに同じrequestを2度出す
// (実測: /api/sessions 256KBが50msと2010msの2回、/api/jobsが97msと1674ms、
//  /api/streamersが134msと2311ms。2回目はいずれもこのsnapshotを受けての再読み込み)。
// 初回接続の初回snapshotにだけ印を付け、pageは印のあるmessageでは取り直さない。
// 再接続時は印を付けない ―― 切れていた間の変化は取り直さないと拾えない。
let wsFirstConnect = true;

function connectWS(onMessage) {
  const firstConnect = wsFirstConnect;
  wsFirstConnect = false;
  const seenSnapshot = new Set();
  const indicators = [
    document.getElementById("ws-indicator"),
    document.getElementById("ws-indicator-foot"),
  ].filter(Boolean);
  const statusEls = [
    document.getElementById("ws-status"),
    document.getElementById("ws-status-foot"),
  ].filter(Boolean);
  const setStatus = (online, text) => {
    indicators.forEach((el) => el.classList.toggle("online", online));
    statusEls.forEach((el) => (el.textContent = text));
  };
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${protocol}://${location.host}/ws`);
  ws.onopen = () => setStatus(true, "Server接続: ONLINE");
  ws.onmessage = (msg) => {
    const data = JSON.parse(msg.data);
    if (firstConnect && !seenSnapshot.has(data.type)
        && (data.type === "monitors" || data.type === "jobs")) {
      seenSnapshot.add(data.type);
      data.initial = true;
    }
    applyJobBar(data);
    onMessage(data);
  };
  ws.onclose = () => {
    setStatus(false, "Server接続: OFFLINE — 再接続中…");
    setTimeout(() => connectWS(onMessage), 2000);
  };
  ws.onerror = () => ws.close();
  return ws;
}

// 色の出処はCSSのtoken(:root)ひとつに固める。canvasにはCSSが効かないので値をJSへ持ち出す
// 必要があるが、hexを書き写すとpaletteを変えた時にchartだけ旧色で取り残される。
const CSS_ROOT_STYLE = getComputedStyle(document.documentElement);
function cssToken(name) {
  return CSS_ROOT_STYLE.getPropertyValue(name).trim();
}
// token(#rrggbb)に透明度を載せる。濃さは呼び出し側の意味(強調の強さ)で決める。
function cssTokenAlpha(name, alpha) {
  const n = parseInt(cssToken(name).slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

// 系列色はこの順で使う。並び順自体が色覚多様性への安全装置なので、途中を飛ばさない。
// 任意の2色が隣り合う面(small multiples)は先頭4色まで。定義と検証値は style.css の :root。
const SERIES = [
  cssToken("--series-1"),
  cssToken("--series-2"),
  cssToken("--series-3"),
  cssToken("--series-4"),
  cssToken("--series-5"),
];
// 量の段。薄→濃で順序を色に出す。段数が5より少ない時は濃い側から採る(薄い端は地に近い)。
const RAMP_STEPS = [
  cssToken("--ramp-1"),
  cssToken("--ramp-2"),
  cssToken("--ramp-3"),
  cssToken("--ramp-4"),
  cssToken("--ramp-5"),
];
function rampOf(count) {
  return RAMP_STEPS.slice(RAMP_STEPS.length - count);
}

const NIER_AXIS_COLOR = cssToken("--chart-ink");
const NIER_GRID_COLOR = cssToken("--chart-grid");
// Timelineに描く範囲。bucketは1本=1点で描く(束ねない)ので、実際の点数は配信の長さが
// 決める。ここで持つのは上限だけで、本数ではなく**時間**で持つ — bucket_secondsは
// session単位で可変なので、本数で持つとbucket幅を変えた瞬間に描く時間の長さが変わる。
const TIMELINE_SPAN_HOURS = 24;
// 点数側の天井。値の札の山探索(prominentPeaks)は最悪形で13ms/panel掛かるのがこの辺り
// (実測)。時間側だけで持つと、bucket幅を細かくしたときに描画点数だけが際限なく増える。
const TIMELINE_MAX_POINTS = 8640;

// そのbucket幅で描く本数の上限。上限に掛かるのは古い側で、新しい側は必ず残る。
function timelineDisplayLimit(bucketSeconds) {
  const bySpan = Math.ceil((TIMELINE_SPAN_HOURS * 3600) / bucketSeconds);
  return Math.min(TIMELINE_MAX_POINTS, bySpan);
}

// chartへ紙の面を敷く。panelの地(中間調)の上に直接描くと、系列色が地に沈んで3:1に届かない。
// canvasにはCSSが効かないので、描画の一番下で塗る。plot領域だけでなくcanvas全面を塗るのは、
// 軸ラベルと凡例がplot領域の外に出るため ―― 紙の外に置くと、その文字だけ中間調の地に載る。
// Chartを読まないpage(videos等)でもcommon.jsは読まれるため、居る時だけ登録する。
const chartSurfacePlugin = {
  id: "chartSurface",
  beforeDraw(chart) {
    const { ctx } = chart;
    ctx.save();
    ctx.fillStyle = cssToken("--chart-surface");
    ctx.fillRect(0, 0, chart.width, chart.height);
    ctx.restore();
  },
};
if (typeof Chart !== "undefined") Chart.register(chartSurfacePlugin);

function nierTooltip() {
  return {
    backgroundColor: cssToken("--invert-bg"),
    titleColor: cssToken("--invert-fg"),
    bodyColor: cssToken("--invert-fg"),
    titleFont: { family: "monospace" },
    bodyFont: { family: "monospace" },
  };
}

function nierTicks() {
  return { color: NIER_AXIS_COLOR, font: { family: "monospace", size: 10 }, precision: 0 };
}

// ---- 横長chartの読み取り支援 ----
// 幅が画面の端まで伸びると、線の右端で高さを見てから左のy軸・系列名まで目線を戻す
// 往復が起きる。値と、その値の意味を決める物(名前・目盛り)を近づける手を2つ置く。
//   (1) 積んだpanelで縦線を共有し、cursorを置いていないpanelは値をその線の脇で名乗る
//   (2) hoverしていない間も、目立つ山にだけ値を撒く(全点に撒くと重なって読めない)
// 既存chartの構成には触れず、外からpluginとして足す。効くかどうかは chart.$xhair /
// chart.$marks の有無で決まるので、登録は全体で1度でよい。
const READOUT_FONT = "10px monospace";
const READOUT_CHIP_H = 15;

// 値の札。地をchart面と同じ不透明色で塗ってから書く ―― 線や棒の上に直接書くと数字が
// 形に食われる。文字は本文と同じ濃さのinkにする。系列色は地に対して3:1(線・塗り向けの
// 下限)しか無く、10pxの文字では読み負けるため、系列の身元は左端のswatchが持つ。
function drawReadoutChip(ctx, { x, y, text, color, bounds }) {
  ctx.font = READOUT_FONT;
  const w = ctx.measureText(text).width + 17;
  let left = x + 6;
  if (bounds && left + w > bounds.right) left = x - 6 - w;
  if (bounds && left < bounds.left) left = x + 6;
  const top = y - READOUT_CHIP_H / 2;
  ctx.fillStyle = cssToken("--chart-surface");
  ctx.fillRect(left, top, w, READOUT_CHIP_H);
  ctx.strokeStyle = color;
  ctx.lineWidth = 1;
  ctx.strokeRect(left + 0.5, top + 0.5, w - 1, READOUT_CHIP_H - 1);
  ctx.fillStyle = color;
  ctx.fillRect(left + 4, top + 4.5, 5, 6);
  ctx.fillStyle = cssToken("--ink-strong");
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  ctx.fillText(text, left + 13, y);
}

// 描いた値と、名乗らせたい値が違うchart(頭打ちで上端に寄せた点など)は
// chart.$readoutValue で実値へ差し替える。tooltipのcallbackと同じ責務。
function readoutValue(chart, di, index, drawn) {
  return chart.$readoutValue ? chart.$readoutValue(di, index, drawn) : drawn;
}

// 札に出す数。桁は落とさず、意味の無い小数だけを畳む ―― 配信時間のような割り算で出た値は
// 3.6865342557430267 のまま持っており、そのまま書くと札が数字の帯になる。
function readoutRound(v) {
  const a = Math.abs(v);
  if (a >= 100 || Number.isInteger(v)) return Math.round(v);
  return Number(v.toFixed(a >= 1 ? 1 : 2));
}

// dataの1点。x軸が実時間のchartは {x, y} で持つので、数値と両方を受ける。
function readoutNumber(data, index) {
  const raw = data[index];
  const v = raw && typeof raw === "object" ? raw.y : raw;
  return typeof v === "number" && !Number.isNaN(v) ? v : null;
}

// 指定indexの描画点(pixel・値・系列色)。値を持たない点はnull。
function readoutPoint(chart, di, index) {
  const meta = chart.getDatasetMeta(di);
  const el = meta && meta.data && meta.data[index];
  if (!el || el.skip) return null;
  const v = readoutNumber(chart.data.datasets[di].data, index);
  if (v == null) return null;
  const o = el.options || {};
  const color = meta.type === "line" ? (o.borderColor || o.backgroundColor) : (o.backgroundColor || o.borderColor);
  return { x: el.x, y: el.y, value: v, color: color || NIER_AXIS_COLOR };
}

// どのindexを指しているかはChart.js自身の当たり判定に任せる。x軸がcategoryか実時間かで
// pixel→値の意味が変わるため、自前でpixelから逆算するとtooltipと違う点を指すことがある。
//
// byValueのgroupは、指した点の**x値**を返す。paneごとに点の数が違う時(推移のコイン段は
// 1日1点・他の段は1配信1点)、indexはpaneを跨いで同じ時点を指さない。
function xhairIndexAt(chart, args) {
  if (!args.inChartArea || args.event.type === "mouseout") return null;
  const hit = chart.getElementsAtEventForMode(args.event, "index", { intersect: false }, true);
  if (!hit.length) return null;
  const g = chart.$xhair;
  if (!g || !g.byValue) return hit[0].index;
  const pt = chart.data.datasets[hit[0].datasetIndex].data[hit[0].index];
  return pt && typeof pt === "object" && Number.isFinite(pt.x) ? pt.x : null;
}

// group が指している所を、このchartの中のindexへ落とす。byValueでは一番近い点を採るが、
// toleranceより離れていたら採らない ―― 段ごとに点の並びが違うので(コインは1日1点・他は
// 1配信1点)、x値が一致する保証は無い。離れすぎた点まで拾うと、その時点には無い値を
// 縦線の上に並べることになる。
function xhairSlot(chart, di, at) {
  const g = chart.$xhair;
  if (!g || !g.byValue) return at;
  const tol = g.tolerance || 0;
  const data = chart.data.datasets[di].data || [];
  let best = -1;
  let bestD = Infinity;
  for (let i = 0; i < data.length; i++) {
    const pt = data[i];
    if (!pt || typeof pt !== "object" || !Number.isFinite(pt.x)) continue;
    const d = Math.abs(pt.x - at);
    if (d < bestD) { bestD = d; best = i; }
  }
  return bestD <= tol ? best : -1;
}

// 縦線を引くx。byValueは軸へ直接x値を渡す ―― その段に点が無くても線は引く(段によって
// 線の位置がずれると、縦に読むための線ではなくなる)。
function xhairPixel(chart, at) {
  const g = chart.$xhair;
  if (g && g.byValue) {
    const x = chart.scales.x ? chart.scales.x.getPixelForValue(at) : null;
    return Number.isFinite(x) ? x : null;
  }
  for (let di = 0; di < chart.data.datasets.length; di++) {
    if (!chart.isDatasetVisible(di)) continue;
    const el = chart.getDatasetMeta(di).data[at];
    if (el && !el.skip && Number.isFinite(el.x)) return el.x;
  }
  return null;
}

// x(時間軸)を共有するchart群を1本の縦線で結ぶ。どのpanelにcursorが在っても全panelの
// 同じ時点に線が落ちる。
// byValue: 共有するのをindexではなくx値にする(paneごとに点の数が違うchart用)。
// tolerance: 縦線から何ぶんまでの点をその時点の値として読むか(byValueのときだけ効く)。
function linkCrosshair(charts, { byValue = false, tolerance = 0 } = {}) {
  const group = { charts, index: null, source: null, byValue, tolerance };
  charts.forEach((c) => { c.$xhair = group; });
  return group;
}

const crosshairPlugin = {
  id: "tictokCrosshair",
  afterEvent(chart, args) {
    const g = chart.$xhair;
    if (!g) return;
    const idx = xhairIndexAt(chart, args);
    if (g.index === idx && (idx === null || g.source === chart)) return;
    g.index = idx;
    g.source = idx === null ? null : chart;
    args.changed = true;
    // 兄弟panelはeventを受け取らないので、こちらから引き直す。draw()は面の塗りと
    // pluginを通す完全な描き直しで、scaleの再計算(update)は要らない。
    g.charts.forEach((c) => { if (c !== chart) c.draw(); });
  },
  afterDraw(chart) {
    const g = chart.$xhair;
    if (!g || g.index == null) return;
    const { ctx, chartArea } = chart;
    const x = xhairPixel(chart, g.index);
    if (x == null || x < chartArea.left || x > chartArea.right) return;
    ctx.save();
    ctx.strokeStyle = cssToken("--chart-ink");
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(x, chartArea.top);
    ctx.lineTo(x, chartArea.bottom);
    ctx.stroke();
    ctx.setLineDash([]);
    // cursorが載っているpanelは標準のtooltipが値と時刻を出す。同じ物を二重に出さない。
    if (g.source !== chart) {
      const picks = [];
      chart.data.datasets.forEach((ds, di) => {
        if (!chart.isDatasetVisible(di)) return;
        const slot = xhairSlot(chart, di, g.index);
        if (slot < 0) return;
        const p = readoutPoint(chart, di, slot);
        if (!p) return;
        const v = readoutValue(chart, di, slot, p.value);
        if (v == null) return;
        picks.push({ ...p, text: `${ds.label ? `${ds.label} ` : ""}${fmtNum(readoutRound(v))}` });
      });
      // 同じ縦線上で札が重なると、どの系列の値か読めなくなる。上から順に最小間隔で開く。
      picks.sort((a, b) => a.y - b.y);
      let floor = chartArea.top + READOUT_CHIP_H / 2;
      picks.forEach((p) => {
        const cy = Math.min(chartArea.bottom - READOUT_CHIP_H / 2, Math.max(floor, p.y));
        floor = cy + READOUT_CHIP_H + 2;
        ctx.fillStyle = p.color;
        ctx.beginPath();
        ctx.arc(x, p.y, 3, 0, Math.PI * 2);
        ctx.fill();
        drawReadoutChip(ctx, { x, y: cy, text: p.text, color: p.color, bounds: chartArea });
      });
    }
    ctx.restore();
  },
};

// 値を撒く点の選び方は「上位N点」ではなく卓越度(prominence)にする。値の大きい順に採ると
// 一番高い山の肩ばかりが並び、離れた場所の小さな山は1つも名乗らない。卓越度は「その点から
// より高い点に出会うまで下った時の、最も高い鞍部との差」で、山ひとつに代表を1点だけ立てる
// (地形図の主峰選定と同じ考え)。系列の振れ幅で正規化するので、単位の違うpanelを同じ閾値で
// 切れる。端の点は外側を-∞と見るため、右肩上がりで終わる系列は終端がそのまま代表になる。
function prominentPeaks(values, limit) {
  const n = values.length;
  if (n < 2) return [];
  const at = (i) => readoutNumber(values, i);
  let vmax = -Infinity;
  let vmin = Infinity;
  for (let i = 0; i < n; i++) {
    const v = at(i);
    if (v == null) continue;
    if (v > vmax) vmax = v;
    if (v < vmin) vmin = v;
  }
  const span = vmax - vmin;
  if (!(span > 0)) return [];
  const peaks = [];
  for (let i = 0; i < n; i++) {
    const v = at(i);
    if (v == null) continue;
    const prev = i > 0 ? at(i - 1) : null;
    const next = i < n - 1 ? at(i + 1) : null;
    // 平坦な頂は左端を代表にする(同じ高さの点が並んだ時に札が増えないように)。
    if ((prev != null && prev >= v) || (next != null && next > v)) continue;
    let saddleL = v;
    let saddleR = v;
    let higherL = false;
    let higherR = false;
    for (let j = i - 1; j >= 0; j--) {
      const w = at(j);
      if (w == null) continue;
      if (w > v) { higherL = true; break; }
      if (w < saddleL) saddleL = w;
    }
    for (let j = i + 1; j < n; j++) {
      const w = at(j);
      if (w == null) continue;
      if (w > v) { higherR = true; break; }
      if (w < saddleR) saddleR = w;
    }
    // 鞍部は「より高い点へ向かう途中の一番低い所」なので、より高い点が無かった側は
    // 鞍部を持たない。両側とも無い点=系列の最大値で、ここは最も低い所からの高さで測る
    // (この扱いをしないと最大値が他の山に順位を譲り、山の代表として名乗らないことがある)。
    let saddle;
    if (higherL && higherR) saddle = Math.max(saddleL, saddleR);
    else if (higherL) saddle = saddleL;
    else if (higherR) saddle = saddleR;
    else saddle = Math.min(saddleL, saddleR);
    const prom = v - saddle;
    if (prom <= 0) continue;
    peaks.push({ index: i, value: v, span, score: prom / span });
  }
  peaks.sort((a, b) => b.score - a.score);
  return peaks.slice(0, limit);
}

// hoverしなくても読める常設の値。opts.topInset は canvas上に重ねたDOMのlabel帯
// (.a-spark-label / .a-spark-peak)の高さで、その帯へ札を出しても隠れて見えない。
function enableValueMarks(chart, opts = {}) {
  chart.$marks = {
    limit: opts.limit || 4,
    minScore: opts.minScore || 0.12,
    topInset: opts.topInset || 0,
    cache: [],
  };
}

const valueMarkPlugin = {
  id: "tictokValueMarks",
  afterDatasetsDraw(chart) {
    const st = chart.$marks;
    if (!st) return;
    // crosshairが出ている間は、そちらが読み取りの主役。撒いた値と札が重なるので伏せる。
    // 指したindexが今のdataに無い時(更新でdataが短くなった等)は線も引けないので、伏せない。
    if (chart.$xhair && chart.$xhair.index != null && xhairPixel(chart, chart.$xhair.index) != null) return;
    // 積み棒は「その系列の値」と「棒の高さ」が一致しない。数字を置くと段の合計と読める。
    const y = chart.options.scales && chart.options.scales.y;
    if (y && y.stacked) return;
    const cands = [];
    chart.data.datasets.forEach((ds, di) => {
      if (ds.noMark || !chart.isDatasetVisible(di)) return;
      // 山の選定はdataの形だけで決まる。描き直す度に走らせると重いので、data配列の
      // 差し替え(=chartのupdate)を境にcacheする。
      let entry = st.cache[di];
      if (!entry || entry.ref !== ds.data) {
        entry = { ref: ds.data, peaks: prominentPeaks(ds.data, st.limit * 3) };
        st.cache[di] = entry;
      }
      entry.peaks.forEach((pk) => { if (pk.score >= st.minScore) cands.push({ ...pk, di }); });
    });
    if (!cands.length) return;
    cands.sort((a, b) => b.score - a.score);
    const { ctx, chartArea } = chart;
    const ceiling = chartArea.top + st.topInset;
    // 札同士が近いと、どの山の値か分からないまま数字だけが並ぶ。矩形の重なりだけでは
    // 隣の山と数px空いた並びを許してしまうので、横の最小間隔も課す。
    const minGap = Math.max(52, (chartArea.right - chartArea.left) / 10);
    const placed = [];
    let drawn = 0;
    ctx.save();
    ctx.font = READOUT_FONT;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    for (const c of cands) {
      if (drawn >= st.limit) break;
      const p = readoutPoint(chart, c.di, c.index);
      if (!p) continue;
      const v = readoutValue(chart, c.di, c.index, p.value);
      if (v == null) continue;
      const text = fmtCompact(readoutRound(v));
      const w = ctx.measureText(text).width + 8;
      // 常に点の上へ置く。上端に余白が無い山(自動scaleの最大点など)は上端で止める ――
      // 下へ回すと山の内側に数字が入り、棒や塗りの中で浮いて見える。
      const box = {
        left: Math.min(Math.max(chartArea.left, p.x - w / 2), chartArea.right - w),
        top: Math.max(ceiling, p.y - READOUT_CHIP_H - 4),
      };
      box.right = box.left + w;
      box.bottom = box.top + READOUT_CHIP_H;
      if (box.bottom > chartArea.bottom) continue;
      // 同じ高さの山が並ぶ系列(Comment等)は、卓越度の上位が全部ほぼ同じ値になる。
      // 「56・56・55」と並べても読み手は何も得ないので、既出と差の無い値は撒かない。
      if (placed.some((q) => Math.abs(q.x - p.x) < minGap
        || (q.di === c.di && Math.abs(q.value - c.value) < c.span * 0.05)
        || (box.right > q.left - 4 && box.left < q.right + 4 && box.bottom > q.top - 2 && box.top < q.bottom + 2))) continue;
      placed.push({ ...box, x: p.x, di: c.di, value: c.value });
      ctx.fillStyle = cssToken("--chart-surface");
      ctx.fillRect(box.left, box.top, w, READOUT_CHIP_H);
      ctx.fillStyle = cssToken("--ink-strong");
      ctx.fillText(text, box.left + w / 2, box.top + READOUT_CHIP_H / 2);
      // どの点の値かは、札と点を結ぶ短い線が示す。色数は系列色のまま増やさない。
      if (p.y - box.bottom > 2) {
        ctx.strokeStyle = p.color;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(p.x, box.bottom);
        ctx.lineTo(p.x, p.y - 2);
        ctx.stroke();
      }
      drawn++;
    }
    ctx.restore();
  },
};

if (typeof Chart !== "undefined") {
  Chart.register(crosshairPlugin);
  Chart.register(valueMarkPlugin);
}

// ---- 尺度の違う指標を積む(二軸の置き換え) ----
// 1枚に2つの目盛を置くと、線と棒の交点や上下関係が、実際には無い意味を持って見える
// (右軸の倍率次第でどうにでも作れる)。尺度ごとにpanelを分け、x軸だけを共有して縦に積む。
//
// 同じ時点が縦に並ぶことがこの形の全てなので、plot領域の左端を揃える。y軸の幅は目盛の
// 桁数で変わる(120 と 120,000 で軸幅が違う)ため、全panelで固定幅にする。
const STACKED_Y_WIDTH = 58;
function stackedYFit(scale) { scale.width = STACKED_Y_WIDTH; }

// container(.x-chartstack)の中にpanelを作り、canvasを返す。leadは主指標のpanelで高さを厚く取る。
// canvasにはcontainerのidから起こした連番idを振る ―― panelは動的に作るので、idが無いと
// 「どのpanelのchartか」を後から指せない(test・debugの取っ掛かりが消える)。
// thinは従属のpanel(移動平均だけを引く段など)。主指標より薄く取る。
function stackPane(container, { lead = false, thin = false } = {}) {
  const pane = document.createElement("div");
  pane.className = `x-cs-pane${lead ? " lead" : ""}${thin ? " thin" : ""}`;
  const canvas = document.createElement("canvas");
  canvas.id = `${container.id}-p${container.children.length + 1}`;
  pane.appendChild(canvas);
  container.appendChild(pane);
  return canvas;
}

// 積んだpanelのx軸。最下段だけが目盛を出す。
function stackedXScale({ bottom, stacked = false, ticks = {} } = {}) {
  return {
    stacked,
    display: true,
    ticks: { ...nierTicks(), maxRotation: 0, autoSkip: true, maxTicksLimit: 24, ...ticks, display: bottom },
    grid: { color: NIER_GRID_COLOR },
  };
}

// x(時間・時刻)を共有するpanelを縦に積んだchart。paneごとに独立した尺度を持つ。
// pane: { type, lead, title, datasets, stacked, max, ticks, tooltip }
// update(labels, perPane) の perPane は pane ごとの data。系列が複数のpaneは配列の配列で渡す。
function createStackedTimeChart(container, { xTicks = {}, panes = [] } = {}) {
  const charts = panes.map((p, i) => new Chart(stackPane(container, { lead: p.lead }), {
    type: p.type || "line",
    data: { labels: [], datasets: p.datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: stackedXScale({ bottom: i === panes.length - 1, stacked: Boolean(p.stacked), ticks: xTicks }),
        y: {
          beginAtZero: true,
          stacked: Boolean(p.stacked),
          afterFit: stackedYFit,
          max: p.max,
          ticks: { ...nierTicks(), ...(p.ticks || {}) },
          grid: { color: NIER_GRID_COLOR },
          title: { display: true, text: p.title, color: NIER_AXIS_COLOR, font: { family: "monospace", size: 10 } },
        },
      },
      plugins: {
        // 1系列のpaneに凡例は要らない。軸のtitleがその指標を名乗っている。
        legend: {
          display: p.datasets.length > 1,
          labels: { color: cssToken("--chart-ink"), font: { family: "monospace", size: 11 }, boxWidth: 12, boxHeight: 8 },
        },
        tooltip: p.tooltip || nierTooltip(),
      },
    },
  }));

  // 積んだpanelは時間軸を共有しているので、読み取りの縦線も共有する。
  linkCrosshair(charts);
  charts.forEach((c) => enableValueMarks(c));

  function update(labels, perPane) {
    charts.forEach((c, i) => {
      c.data.labels = labels;
      const d = perPane[i] || [];
      const cols = Array.isArray(d[0]) ? d : [d];
      c.data.datasets.forEach((ds, j) => { ds.data = cols[j] || []; });
      c.update();
    });
  }

  function clear() {
    charts.forEach((c) => {
      c.data.labels = [];
      c.data.datasets.forEach((ds) => { ds.data = []; });
      c.update();
    });
  }

  return { charts, update, clear };
}

// TIMELINE: 桁の違う4指標を1枚に重ねると小さい系列が潰れて読めない。指標ごとに
// 独立scaleの小型折れ線(small multiples)を縦に並べ、時間軸とLIVE Markerを共有する。
// aggはbucketを束ねる時の集計: countは合計、level(同接)はbucket内の最終値。
// zeroBase: countは0基準で塗りつぶし量を出す。levelの同接は0基準だと微増減が潰れる
// ため自動scale(min..max)で推移を見せる。
// 4枚は隣り合って比べられるので、系列色は先頭4色まで(全対分離を確かめてある範囲)。
// 4色目は分離が floor 帯なので、各panelの見出しに指標名を出すことが前提になっている。
const TIMELINE_SERIES = [
  { key: "diamonds", label: "コイン", color: SERIES[0], fill: cssTokenAlpha("--series-1", 0.16), agg: "sum", zeroBase: true },
  { key: "viewers", label: "同接", color: SERIES[1], fill: false, agg: "last", zeroBase: false },
  { key: "comments", label: "コメント", color: SERIES[2], fill: cssTokenAlpha("--series-3", 0.16), agg: "sum", zeroBase: true },
  { key: "likes", label: "Like", color: SERIES[3], fill: cssTokenAlpha("--series-4", 0.16), agg: "sum", zeroBase: true },
];

// Timeline上のevent marker。backendのlabelは "Battle #<巨大ID>" 等で長く、密集すると
// 数字の羅列が重なって読めなくなるため、kindごとに短tag+色を割当てて表示する。
// markerはtagの文字で身元を名乗るので、色は意味の区別だけを担う。8種に8色を当てると
// 隣り合った時に見分けが付かず、色を数える作業になる。出来事=系列色、接続=良い、
// 切断=危ない、で束ねる。
const MARKER_STYLES = {
  battle: { color: cssToken("--series-1"), short: "PK" },
  collab: { color: cssToken("--series-2"), short: "コラボ" },
  record: { color: cssToken("--series-5"), short: "REC" },
  connect: { color: cssToken("--ok-ink"), short: "接続" },
  video_only: { color: cssToken("--warn-ink"), short: "映像のみ" },
  event_attach: { color: cssToken("--ok-ink"), short: "受信開始" },
  reconnect: { color: cssToken("--chart-ink"), short: "再接続" },
  disconnect: { color: cssToken("--warn-ink"), short: "切断" },
  disconnect_unplanned: { color: cssToken("--warn-ink"), short: "異常切断" },
  live_end: { color: cssToken("--chart-ink"), short: "終了" },
};
const MARKER_DEFAULT = { color: cssToken("--chart-ink"), short: "•" };

function decorateMarkers(raw) {
  let battleNo = 0;
  return (raw || []).map((m) => {
    const style = MARKER_STYLES[m.kind] || MARKER_DEFAULT;
    let tag = style.short;
    if (m.kind === "battle") {
      battleNo += 1;
      tag = `PK${battleNo}`;
    }
    return { time: m.time, kind: m.kind, color: style.color, tag };
  });
}

function createTimelineChart(container) {
  let firstStart = null;
  let stepSeconds = 10;
  let markers = [];
  let battleBands = [];

  // Battle(PK)の時間帯を帯で塗り、その窓で実際に受け取ったコイン量を可視化する。armies由来の
  // スコアではなく、このpanelのコイン系列(=自室受取・statsと同源)の窓内合計を内訳として出す。
  function bandIndexRange(b, n) {
    const s = b.start;
    const e = b.end || b.start;
    let i0 = Math.round((s - firstStart) / stepSeconds);
    let i1 = Math.round((e - firstStart) / stepSeconds);
    if (i1 < 0 || i0 >= n) return null;
    return [Math.max(0, i0), Math.min(n - 1, i1)];
  }

  function makeBandPlugin(showCoins) {
    return {
      id: "tictokBattleBands",
      beforeDatasetsDraw(c) {
        if (!battleBands.length || firstStart === null) return;
        const { ctx, chartArea, scales } = c;
        const n = c.data.labels.length;
        ctx.save();
        battleBands.forEach((b) => {
          const range = bandIndexRange(b, n);
          if (!range) return;
          const x0 = scales.x.getPixelForValue(range[0]);
          const x1 = scales.x.getPixelForValue(range[1]);
          const left = Math.min(x0, x1);
          const width = Math.max(2, Math.abs(x1 - x0));
          ctx.fillStyle = cssTokenAlpha("--warn", 0.12);
          ctx.fillRect(left, chartArea.top, width, chartArea.bottom - chartArea.top);
        });
        ctx.restore();
      },
      afterDatasetsDraw(c) {
        if (!showCoins || !battleBands.length || firstStart === null) return;
        const { ctx, chartArea, scales } = c;
        const data = c.data.datasets[0].data;
        const n = c.data.labels.length;
        ctx.save();
        ctx.font = "9px monospace";
        ctx.textAlign = "center";
        // 帯の下端に置き、上部のPK序数tag(markerplugin)との重なりを避ける。
        ctx.textBaseline = "bottom";
        ctx.fillStyle = cssToken("--warn");
        battleBands.forEach((b) => {
          const range = bandIndexRange(b, n);
          if (!range) return;
          let sum = 0;
          for (let i = range[0]; i <= range[1]; i++) sum += data[i] || 0;
          if (sum <= 0) return;
          const xMid = (scales.x.getPixelForValue(range[0]) + scales.x.getPixelForValue(range[1])) / 2;
          ctx.fillText(fmtCompact(sum), xMid, chartArea.bottom - 1);
        });
        ctx.restore();
      },
    };
  }

  function makeMarkerPlugin(showText, seriesLabel) {
    return {
      id: "tictokMarkers",
      afterDatasetsDraw(c) {
        if (!markers.length || firstStart === null) return;
        const { ctx, chartArea, scales } = c;
        ctx.save();
        const visible = [];
        markers.forEach((m) => {
          const idx = Math.round((m.time - firstStart) / stepSeconds);
          if (idx < 0 || idx >= c.data.labels.length) return;
          const x = scales.x.getPixelForValue(idx);
          ctx.strokeStyle = m.color;
          ctx.setLineDash([4, 3]);
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(x, chartArea.top);
          ctx.lineTo(x, chartArea.bottom);
          ctx.stroke();
          visible.push({ x, m });
        });
        ctx.setLineDash([]);
        if (showText) {
          // 系列名labelは左上に固定表示される。その帯に重なるtag(PK/コラボ等)は
          // 名前と被って読めなくなるため、名前幅を実測し重なる分だけ1段下げる。
          ctx.font = "700 11px monospace";
          const nameZoneRight = chartArea.left + ctx.measureText(seriesLabel || "").width + 8;
          ctx.font = "10px monospace";
          ctx.textAlign = "left";
          ctx.textBaseline = "alphabetic";
          // 重なり防止: x昇順に走査し、段ごとに直前labelの右端と被るものは間引く。
          visible.sort((a, b) => a.x - b.x);
          let lastRightTop = -Infinity;
          let lastRightLow = -Infinity;
          visible.forEach(({ x, m }) => {
            const left = x + 3;
            const low = left < nameZoneRight;
            const lastRight = low ? lastRightLow : lastRightTop;
            if (left < lastRight + 4) return;
            ctx.fillStyle = m.color;
            ctx.fillText(m.tag, left, chartArea.top + (low ? 20 : 9));
            const right = left + ctx.measureText(m.tag).width;
            if (low) lastRightLow = right; else lastRightTop = right;
          });
        }
        ctx.restore();
      },
    };
  }

  // 4panel(コイン/同接/Comment/Like)は時間軸を共有するため、plot領域の左右端を
  // 全panelで揃える必要がある。x軸目盛りは最下段のみ表示だが、その端目盛りlabelの
  // はみ出し分だけChart.jsが左右にpaddingを足すと最下段だけ内側にずれる。全panelに
  // 同じ左右padを固定し、最下段のx scaleにも同padを強制して開始位置を一致させる。
  const EDGE = 16;
  container.classList.add("a-spark-grid");
  const panels = TIMELINE_SERIES.map((s, i) => {
    const isLast = i === TIMELINE_SERIES.length - 1;
    const row = document.createElement("div");
    row.className = "a-spark";
    const head = document.createElement("span");
    head.className = "a-spark-label";
    head.style.color = s.color;
    const name = document.createElement("b");
    name.textContent = s.label;
    head.appendChild(name);
    const peak = document.createElement("span");
    peak.className = "a-spark-peak";
    peak.style.color = s.color;
    const canvas = document.createElement("canvas");
    row.appendChild(head);
    row.appendChild(peak);
    row.appendChild(canvas);
    container.appendChild(row);

    const chart = new Chart(canvas, {
      type: "line",
      data: {
        labels: [],
        datasets: [
          { label: s.label, data: [], borderColor: s.color, backgroundColor: s.fill || "transparent", borderWidth: 1.5, pointRadius: 0, tension: 0.25, fill: Boolean(s.fill), yAxisID: "y" },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        layout: { padding: { top: 2, right: isLast ? 0 : EDGE, bottom: 0, left: isLast ? 0 : EDGE } },
        interaction: { mode: "index", intersect: false },
        scales: {
          x: {
            display: isLast,
            // 最下段だけ端目盛りのはみ出しで内側にずれないよう左右padを他panelと揃える。
            afterFit(scale) { scale.paddingLeft = EDGE; scale.paddingRight = EDGE; },
            ticks: {
              ...nierTicks(),
              maxRotation: 0,
              autoSkip: true,
              maxTicksLimit: 8,
              // tooltipは完全時刻を保持しつつ、軸表示はHH:MMに短縮して端の見切れを抑える。
              callback(value) { const l = this.getLabelForValue(value); return l ? l.slice(0, 5) : l; },
            },
            grid: { color: NIER_GRID_COLOR },
          },
          y: { display: false, beginAtZero: s.zeroBase, grace: "8%" },
        },
        plugins: {
          legend: { display: false },
          tooltip: { ...nierTooltip(), callbacks: { label: (ctx) => `${s.label}: ${fmtNum(ctx.parsed.y)}` } },
        },
      },
      plugins: [makeBandPlugin(s.key === "diamonds"), makeMarkerPlugin(i === 0, s.label)],
    });
    // 段の名前(左上)と最大値(右上)はcanvasの上に重ねたDOM。その帯へ札を出すと隠れる。
    enableValueMarks(chart, { topInset: 18, limit: 3 });
    return { key: s.key, agg: s.agg, chart, peak };
  });
  // 4段は同じ時刻で縦に並ぶことが売りなので、読み取りの縦線も4段で共有する。
  linkCrosshair(panels.map((p) => p.chart));

  function clear() {
    firstStart = null;
    markers = [];
    battleBands = [];
    panels.forEach((p) => {
      p.chart.data.labels = [];
      p.chart.data.datasets[0].data = [];
      p.peak.textContent = "";
      p.chart.update();
    });
  }

  function update(data, battles) {
    const size = data.bucket_seconds;
    markers = decorateMarkers(data.markers);
    // Battle窓(start_time〜end_time)を帯として保持。end欠落(進行中)はstartのみの点として扱う。
    battleBands = (battles || [])
      .filter((b) => b && b.start_time)
      .map((b) => ({ start: b.start_time, end: b.end_time || b.start_time }));
    const raw = data.buckets || [];
    if (!raw.length) {
      clear();
      return;
    }
    const byStart = new Map(raw.map((b) => [b.start, b]));
    const last = raw[raw.length - 1].start;
    const limit = timelineDisplayLimit(size);
    let first = raw[0].start;
    if ((last - first) / size + 1 > limit) {
      first = last - (limit - 1) * size;
    }

    // 欠損bucketを0埋めした連続系列を作る(同接は直前値を持ち越す)。
    const starts = [];
    const full = {};
    TIMELINE_SERIES.forEach((s) => { full[s.key] = []; });
    let viewers = raw[0].viewers;
    for (const b of raw) {
      if (b.start >= first) break;
      viewers = b.viewers;
    }
    for (let s = first; s <= last; s += size) {
      const b = byStart.get(s);
      if (b) viewers = b.viewers;
      starts.push(s);
      TIMELINE_SERIES.forEach((ser) => {
        full[ser.key].push(ser.agg === "last" ? viewers : (b ? b[ser.key] : 0));
      });
    }

    // bucketは束ねずに1本=1点で描く。刻みはbucket_secondsそのもの(marker・Battle帯の
    // index換算もstepSecondsを見る)。
    const n = starts.length;
    stepSeconds = size;
    firstStart = first;
    const labels = new Array(n);
    for (let i = 0; i < n; i++) labels[i] = fmtTime(starts[i]);

    panels.forEach((p) => {
      const values = full[p.key];
      const peak = values.reduce((m, v) => (v > m ? v : m), 0);
      p.chart.data.labels = labels;
      p.chart.data.datasets[0].data = values;
      p.peak.textContent = `最大 ${fmtCompact(peak)}`;
      p.chart.update();
    });
  }

  return { charts: panels.map((p) => p.chart), update, clear };
}

// Per-session trend: diamonds as bars (money, left axis), gift count as a line
// (right axis). Two axes because diamond totals dwarf gift counts; the line keeps
// gift volume legible against the much larger diamond bars.
// 末尾基準の単純移動平均(trailing SMA)。系列の「伸び」を均して見せる。
// 値を持たない点(観測が無くて率を出せない配信など)は窓から外す ―― 0として混ぜると
// 均した線だけが落ち込み、実際には起きていない減少に見える。窓が全部空なら線も引かない。
//
// requireFull:true は窓が埋まるまで線を引かない。窓の違う線を何本も重ねる時に要る ――
// 埋まるまでを「手元にある点だけの平均」で描くと、左端では25日線も7日線も同じ点の平均に
// なり、3本が1本に重なったまま始まる(長い窓ほど本当は遅れて始まる、という形が消える)。
function movingAverage(values, window, requireFull = false) {
  const out = [];
  for (let i = 0; i < values.length; i++) {
    if (requireFull && i < window - 1) { out.push(null); continue; }
    const start = Math.max(0, i - window + 1);
    let sum = 0;
    let count = 0;
    for (let j = start; j <= i; j++) {
      if (values[j] == null) continue;
      sum += values[j];
      count += 1;
    }
    out.push(count ? sum / count : null);
  }
  return out;
}

// 比率の移動平均。率をそのまま平均すると10分の配信と6時間の配信が同じ重みになるため、
// 窓の中の分子・分母をそれぞれ足してから割る(時間加重)。戻り値は率(%)。
// 分母が0の窓(その期間まったく配信していない)は率を持たないのでnull — 0%にすると
// 「共演しなかった」と読めてしまう。
function weightedShareAverage(numerators, denominators, window) {
  const out = [];
  for (let i = 0; i < numerators.length; i++) {
    const start = Math.max(0, i - window + 1);
    let num = 0;
    let den = 0;
    for (let j = start; j <= i; j++) {
      num += numerators[j] || 0;
      den += denominators[j] || 0;
    }
    out.push(den > 0 ? (num / den) * 100 : null);
  }
  return out;
}

// 推移の時間軸は「日」で刻む。どちらもbrowserのlocal時刻 — 画面の他の日付
// (fmtDate・時間帯ヒートマップ・serverが返す日次コインのYYYY-MM-DD)と同じ物差しに揃える。
const TREND_DAY = 86400;
function trendDayStart(epochSeconds) {
  const d = new Date(epochSeconds * 1000);
  d.setHours(0, 0, 0, 0);
  return Math.floor(d.getTime() / 1000);
}
// server(strftime '%Y-%m-%d' localtime)が返す日付を、その日の0時のepochへ戻す。
function trendYmdStart(ymd) {
  const [y, m, d] = String(ymd).split("-").map(Number);
  return Math.floor(new Date(y, m - 1, d).getTime() / 1000);
}

// 期間まとめ(週/月)の刻み。週の起点は月曜0時、月は暦月1日の0時で、どちらもbrowserの
// local時刻で刻む — 画面の他の日付(fmtDate・時間帯ヒートマップ)と同じ物差しに揃える。
function trendPeriodStart(epochSeconds, unit) {
  const d = new Date(epochSeconds * 1000);
  d.setHours(0, 0, 0, 0);
  if (unit === "week") d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  if (unit === "month") d.setDate(1);
  return Math.floor(d.getTime() / 1000);
}

function trendPeriodNext(startSeconds, unit) {
  const d = new Date(startSeconds * 1000);
  if (unit === "month") d.setMonth(d.getMonth() + 1);
  else d.setDate(d.getDate() + 7);
  return Math.floor(d.getTime() / 1000);
}

// 推移paneの定義。1指標=1paneで、x軸(日)だけを共有して縦に積む。
// value(p) がその点の値(無い時はnullを返す ―― spanGapsで線を繋ぎ、棒は空ける)。
// daily:true のpaneは配信ではなく**日(期間)**の点を描く。paneを足すときはここへ1件足す。
//
// 色は指標ごとに1色。同じpaneの複数系列は「同じ量の別の読み方」なので色を変えず、
// 実線(平均)・破線(条件付きの平均)・細い薄線(Peak)で描き分ける。別の色を当てると
// 別の指標に見える。
const TREND_PANES = {
  coins: {
    // コインは配信ごとではなく日ごとに数える。1配信=1本で並べると、同じ配信が
    // reconnectで最大7本のsessionに割れ(実測: 配信者×日の71.7%が2本以上)、さらに
    // sessionの35.6%が日を跨ぐため、棒の1本が「その日いくら出たか」を指さない。
    lead: true, type: "bar", title: "コイン", color: 0, daily: true,
    ticks: { callback: (v) => fmtCompact(v) },
    series: [{ label: "コイン", bar: true, value: (p) => p.coins,
               fmt: (v) => fmtNum(Math.round(v)) }],
  },
  coinsMa: {
    // コインの移動平均。棒と同じ段に重ねると線が棒に埋もれて形を追えない(窓を3本に
    // すると尚更)ので段を分ける。3本は同じ指標の平滑度違いなので色は変えず、量の段
    // (薄→濃 = 短期→長期)で順序を色に出す。
    type: "line", title: "コイン 移動平均", color: 0, daily: true, maLines: 3,
    ticks: { callback: (v) => fmtCompact(v) },
    series: [],
  },
  comments: {
    // 実数のままだと10分の配信と6時間の配信が同じ物差しで並ばない(長く配信した分だけ
    // 棒が伸びる)。分母は名目の配信時間ではなく観測秒 ―― 収集が落ちた区間はコメントも
    // 記録されていないので、名目で割るとその配信だけ率が半分に見える。
    //
    // 棒ではなく線。x軸が実日付になったので、棒の幅は隣の点との実間隔で決まる ――
    // reconnectで割れた配信は3分しか離れておらず(実測)、その日の棒が軒並み1px未満に
    // 潰れる。そもそも率は量ではないので、水準の段(同接)と同じく線で読む。
    type: "line", title: "コメント/分", color: 2,
    series: [{ label: "コメント/分", ma: true, value: (p) => p.commentsPerMin,
               fmt: (v) => v.toFixed(1) }],
  },
  // 平均とPeakは同じ「人」だが桁が違う(実測で平均12〜29に対しPeakは140〜205)。1枚に
  // 収めるとPeakが目盛を決めてしまい、平均が下端の帯へ潰れて伸びが読めない ―― 平均が
  // 2.4倍になった週でも線はほぼ水平に見える。paneを分けて、それぞれの範囲で描く。
  // 平均と「宝箱窓を除く平均」は同じ範囲を動く同じ読み方なので、こちらは1枚に重ねる
  // (2本の差が宝箱ぶんで、それを読むのがこの線の目的である)。
  viewers: {
    lead: true, type: "line", title: "平均同接(人)", color: 1,
    series: [
      { label: "平均同接", value: (p) => p.viewersAvg, fmt: (v) => fmtNum(Math.round(v)) },
      { label: "宝箱窓を除く", dash: true, value: (p) => p.viewersNobox,
        fmt: (v) => fmtNum(Math.round(v)) },
    ],
  },
  peak: {
    // 平均と同じ量の別の読み方なので色は変えない。どちらの読み方かは軸のtitleが名乗る。
    type: "line", title: "Peak同接(人)", color: 1,
    series: [{ label: "Peak同接", value: (p) => p.viewersPeak,
               fmt: (v) => fmtNum(Math.round(v)) }],
  },
  hours: {
    // 隣り合う面なので、色は先頭4色に収める(隣り合う任意の2色の分離が確かめてあるのは
    // そこまで ―― SERIESの定義を参照)。
    type: "line", title: "配信時間(h)", color: 3,
    series: [{ label: "配信時間", value: (p) => p.hours, text: (p) => p.durText }],
  },
};

// opts.panels: 積むpaneのkey(TREND_PANESの見出し)。既定は ["coins", "hours"]。
// opts.movingAvg: ma:true のpaneへ移動平均線を重ねる(成長トレンド可視化)。既定off。
// opts.movingAvgWindow で窓幅(既定5)。containerは .x-chartstack。
// 指標ごとに単位も桁も違うので、二軸で重ねず上下のpanelへ分ける。時間軸は共有する。
//
// x軸は**日**の実数軸(1目盛=1日・0=窓の最初の暦日の0時)。等間隔のcategory軸だと、
// 隣り合う2本の距離が実際に何日離れているかを表さない ―― 1日に2配信あった日と、
// 2週間空いた日が同じ幅で並ぶ。日ごとの段(コイン)と配信ごとの段を縦に読むには、
// 両者が同じ実時間の上に載っている必要がある。
function createSessionTrendChart(container, opts = {}) {
  // 配信ごとの段が読む点。単位が配信ごとなら1配信=1点、週/月なら1期間=1点。
  let points = [];
  // 日ごとの段(コイン)が読む点。単位が配信ごとなら1日=1点、週/月なら1期間=1点。
  // 日を跨いだ配信のコインは翌日へ乗るので、配信の点には載せられない。
  let coinPoints = [];
  // x=0 が指す日の0時(epoch秒)と、軸が覆う日数。
  let origin = 0;
  let span = 1;
  let viewUnit = "session";

  const p2 = (n) => String(n).padStart(2, "0");
  // 日index。DSTのある地域でも日の境目で数えられるよう、時刻の差ではなく「その日の0時」
  // どうしの差で数える。
  const dayNo = (t) => Math.round((trendDayStart(t) - origin) / TREND_DAY);
  const dayX = (t) => dayNo(t) + (t - trendDayStart(t)) / TREND_DAY;
  // 日indexが指す日の0時。境目でぶれないよう正午から日の頭へ丸める。
  const dayAt = (n) => trendDayStart(origin + n * TREND_DAY + TREND_DAY / 2);

  // 率の分母。0で割らないだけでなく、観測秒を持たない配信(bucketが無い)は率そのものを
  // 持たないのでnullを返す。0にすると「コメントが無かった」と読めてしまう。
  const rate = (num, den) => (den > 0 ? num / den : null);
  // 時間加重平均。10分の配信と6時間の配信を同じ重みで平均しない。重みの合計が0の期間は
  // その平均を持たない(宝箱の記録が無い期間の「宝箱窓を除く同接」がこれに当たる)。
  function weightedMean(rows, pick, weigh) {
    let num = 0;
    let den = 0;
    rows.forEach((s) => {
      const v = pick(s);
      const w = weigh(s) || 0;
      if (v == null || w <= 0) return;
      num += v * w;
      den += w;
    });
    return den > 0 ? num / den : null;
  }

  // x目盛に出すのは「いつ頃か」だけ。年は期間が延びるほど幅を食うので、月まとめの時だけ
  // 下2桁を残す。1本の素性はtooltipが名乗る。
  function tickLabel(v) {
    const d = new Date(dayAt(Math.round(v)) * 1000);
    return viewUnit === "month"
      ? `${String(d.getFullYear()).slice(2)}/${p2(d.getMonth() + 1)}`
      : `${p2(d.getMonth() + 1)}/${p2(d.getDate())}`;
  }

  // 目盛の位置。配信ごと(=日)は日index上の等間隔、期間まとめは期間の頭へ置く。
  // Chart.js任せの「きりのいい数」だと、月まとめで月の途中に目盛が立つ。
  function tickValues() {
    if (viewUnit !== "session" && coinPoints.length) {
      const step = Math.max(1, Math.ceil(coinPoints.length / 12));
      return coinPoints.filter((_, i) => i % step === 0).map((p) => p.start);
    }
    const step = Math.max(1, Math.ceil(span / 11));
    const out = [];
    for (let d = 0; d < span; d += step) out.push(d);
    return out;
  }

  // 配信1本=1点。x はその配信が始まった実時刻(日の小数)。
  function sessionPoints(rows) {
    return rows.map((s) => {
      const observed = s.observed_seconds || 0;
      return {
        x: dayX(s.started_at),
        title: `#${sessionNo(s.id)}  ${fmtDateTime(s.started_at)}`,
        // 収集中の配信は終端が無い。0時間として黙って畳むと「短い配信」に見えるので、
        // 尺のかわりに収集中と名乗る(線の高さは0のまま)。
        durText: s.ended_at ? fmtDuration(s.ended_at - s.started_at) : "収集中",
        sub: "",
        hours: s.ended_at ? (s.ended_at - s.started_at) / 3600 : 0,
        commentsPerMin: rate(s.comments || 0, observed / 60),
        viewersAvg: s.viewers_avg == null ? null : s.viewers_avg,
        viewersNobox: s.viewers_avg_nobox == null ? null : s.viewers_avg_nobox,
        viewersPeak: s.viewers || null,
        observedSeconds: observed,
        noboxSeconds: s.nobox_seconds || 0,
      };
    });
  }

  // 窓の中の期間(週/月)を頭から順に並べる。配信の無い期間も残す — 飛ばすと空白期間が
  // 詰まり、離れた2つの週(月)が隣り合っているように読める。
  function periodList(unit) {
    const out = [];
    const last = trendPeriodStart(dayAt(span - 1), unit);
    for (let start = trendPeriodStart(origin, unit); start <= last;
         start = trendPeriodNext(start, unit)) {
      out.push({ start, next: trendPeriodNext(start, unit) });
    }
    return out;
  }

  // 週/月の合計。合計にできるのは量(配信時間)だけ。率(コメント/分)と水準(同接)は期間の
  // 中で足しても意味を持たないので、期間の中の分子・分母をそれぞれ足してから割る。
  function periodPoints(rows, unit, periods) {
    return periods.map(({ start, next }) => {
      const group = rows.filter((s) => s.started_at >= start && s.started_at < next);
      const d = new Date(start * 1000);
      const hours = group.reduce((acc, s) => acc + (s.ended_at ? (s.ended_at - s.started_at) / 3600 : 0), 0);
      const observed = group.reduce((acc, s) => acc + (s.observed_seconds || 0), 0);
      return {
        x: (dayNo(start) + dayNo(next - 1) + 1) / 2,
        title: unit === "month"
          ? `${d.getFullYear()}/${p2(d.getMonth() + 1)}（月合計）`
          : `${fmtDate(start)}〜${fmtDate(next - 1)}（週合計）`,
        durText: fmtDuration(Math.round(hours * 3600)),
        // 1本が何本ぶんの合計かを名乗らないと、1配信の点と区別が付かない。
        sub: `配信 ${fmtNum(group.length)}本`,
        hours,
        commentsPerMin: rate(group.reduce((acc, s) => acc + (s.comments || 0), 0), observed / 60),
        viewersAvg: weightedMean(group, (s) => s.viewers_avg, (s) => s.observed_seconds),
        viewersNobox: weightedMean(group, (s) => s.viewers_avg_nobox, (s) => s.nobox_seconds),
        viewersPeak: group.reduce((acc, s) => Math.max(acc, s.viewers || 0), 0) || null,
        observedSeconds: observed,
        noboxSeconds: group.reduce((acc, s) => acc + (s.nobox_seconds || 0), 0),
      };
    });
  }

  // コインの日次。配信の無い日も0の点として残す ―― 飛ばすと空いた日が詰まるうえ、
  // 移動平均の窓が「配信のあった日」で数えられ、窓の実長が配信頻度で伸び縮みする。
  function dailyCoinPoints(daily, rows) {
    const byDay = new Map();
    (daily || []).forEach((d) => {
      const n = dayNo(trendYmdStart(d.date));
      if (n < 0 || n >= span) return;
      byDay.set(n, (byDay.get(n) || 0) + (d.diamonds || 0));
    });
    const now = Date.now() / 1000;
    const out = [];
    for (let n = 0; n < span; n++) {
      const start = dayAt(n);
      const end = start + TREND_DAY;
      // その日に掛かっていた配信の本数。日を跨いだ配信のコインは翌日へ乗るので、
      // 「その日に始まった配信」ではなく「その日に掛かっていた配信」で数える。
      const live = rows.filter((s) => s.started_at < end && (s.ended_at || now) >= start).length;
      out.push({
        x: n + 0.5,
        start: n,
        lo: n, hi: n + 1,
        live,
        title: fmtDate(start),
        sub: live ? `配信 ${fmtNum(live)}本` : "配信なし",
        coins: byDay.get(n) || 0,
      });
    }
    return out;
  }

  // 日次の点を週/月へ畳む。sessionの合計から作り直さないのは、日を跨いだ配信のコインが
  // 期間の境目でどちらへ入るかを、日次の段と食い違わせないためである。
  function periodCoinPoints(days, unit, periods) {
    return periods.map(({ start, next }) => {
      const group = days.filter((p) => {
        const t = dayAt(p.start);
        return t >= start && t < next;
      });
      const d = new Date(start * 1000);
      return {
        x: (dayNo(start) + dayNo(next - 1) + 1) / 2,
        start: dayNo(start),
        lo: dayNo(start), hi: dayNo(next - 1) + 1,
        title: unit === "month"
          ? `${d.getFullYear()}/${p2(d.getMonth() + 1)}（月合計）`
          : `${fmtDate(start)}〜${fmtDate(next - 1)}（週合計）`,
        sub: `配信のあった日 ${fmtNum(group.filter((p) => p.live > 0).length)}日`,
        coins: group.reduce((acc, p) => acc + p.coins, 0),
      };
    });
  }

  const keys = (opts.panels && opts.panels.length ? opts.panels : ["coins", "hours"])
    .filter((k) => TREND_PANES[k]);

  function paneDatasets(spec) {
    const color = SERIES[spec.color];
    const sets = [];
    if (spec.maLines) {
      // 窓の本数は固定。窓幅とlabelは単位ごとに呼び側が決めるのでupdateで入れる。
      // 同じ指標の平滑度違いなので色は変えず、量の段(薄→濃)で順序を出す。ただしrampの
      // 隣り合う2段は2pxの線では見分けが付かないので、太さも窓の長さに合わせる
      // (長い窓ほど太く・濃く = 均されているほど地に近い動きをする、という読み方に揃う)。
      rampOf(spec.maLines).forEach((c, i) => {
        sets.push({ label: "", type: "line", data: [], borderColor: c,
                    backgroundColor: "transparent", borderWidth: 1.4 + i * 0.7,
                    pointRadius: 0, tension: 0.3, spanGaps: false, noMark: true });
      });
      return sets;
    }
    spec.series.forEach((s) => {
      if (s.bar) {
        // 棒の幅はChart.jsが点の最小間隔(=1日/1期間)から決める。数百日ぶんを1枚に
        // 並べると1本あたりの幅が数pxまで痩せるが、上限だけは抑えて本数が少ない時に
        // 太りすぎないようにする。
        sets.push({ label: s.label, type: "bar", data: [], backgroundColor: color,
                    categoryPercentage: 1, barPercentage: 0.9, maxBarThickness: 64 });
      } else {
        sets.push({
          label: s.label, type: "line", data: [],
          borderColor: color,
          backgroundColor: "transparent",
          borderWidth: 2,
          borderDash: s.dash ? [5, 3] : undefined,
          pointRadius: 3, pointHoverRadius: 4, tension: 0.25, spanGaps: true,
        });
      }
      if (s.ma && opts.movingAvg) {
        // 移動平均はその指標そのものの平滑なので、同じ色の破線にする。別の色を当てると
        // 別の指標に見える。同じ尺度なので同じpanelに重ねてよい。均した派生値なので
        // 常設の値marksは出さない(同じ山に実績と移動平均の2つの数字が並ぶと、どちらが
        // 実績か読めなくなる)。
        sets.push({ label: `${s.label} 移動平均`, type: "line", data: [], borderColor: color,
                    backgroundColor: "transparent", borderWidth: 2, borderDash: [5, 3],
                    pointRadius: 0, tension: 0.3, spanGaps: true, noMark: true });
      }
    });
    return sets;
  }

  // datasetのindexから「どの系列定義か」を引く表。移動平均は元の系列の定義を指す
  // (tooltipの書式を実績と揃えるため)。
  function paneSeriesIndex(spec) {
    if (spec.maLines) {
      return Array.from({ length: spec.maLines }, () => ({ fmt: (v) => fmtNum(Math.round(v)) }));
    }
    const index = [];
    spec.series.forEach((s) => {
      index.push(s);
      if (s.ma && opts.movingAvg) index.push(s);
    });
    return index;
  }

  // その段が読む点の並び。日ごとの段と配信ごとの段で長さが違う。
  const paneRows = (spec) => (spec.daily ? coinPoints : points);

  function tooltipFor(spec, seriesIndex) {
    return {
      ...nierTooltip(),
      callbacks: {
        title: (items) => {
          const p = paneRows(spec)[items[0].dataIndex];
          return p ? p.title : "";
        },
        label: (item) => {
          const p = paneRows(spec)[item.dataIndex];
          // 1系列のpaneはdatasetIndexが無くても引けるようにする(先頭が唯一の系列)。
          const s = seriesIndex[item.datasetIndex || 0];
          if (s && s.text) return `${s.label}: ${p ? s.text(p) : "-"}`;
          const v = item.parsed ? item.parsed.y : null;
          // 値を持たない点は0と書かない。「無かった」と「測れていない」は別のことである。
          if (v == null) return `${item.dataset.label}: —`;
          return `${item.dataset.label}: ${s && s.fmt ? s.fmt(v) : fmtNum(v)}`;
        },
        // 複数行になり得るので常にlistで返す(Chart.jsは1行でもlistを受ける)。
        footer: (items) => {
          const p = paneRows(spec)[items[0].dataIndex];
          if (!p) return [];
          const lines = p.sub ? [p.sub] : [];
          // 宝箱窓を除いた同接は、除いた後に残る時間が短いほど代表性が落ちる。何割を
          // 残した平均なのかを添えないと、窓が配信の8割を占める配信でも同じ重みで読める。
          if (spec.key === "viewers" && p.observedSeconds > 0 && p.viewersNobox != null) {
            lines.push(`宝箱窓の外: 観測時間の ${Math.round((p.noboxSeconds / p.observedSeconds) * 100)}%`);
          }
          return lines;
        },
      },
    };
  }

  const panes = keys.map((key, i) => {
    const spec = { ...TREND_PANES[key], key };
    const datasets = paneDatasets(spec);
    const seriesIndex = paneSeriesIndex(spec);
    const chart = new Chart(
      stackPane(container, { lead: Boolean(spec.lead), thin: Boolean(spec.maLines) }),
      {
        type: spec.type,
        data: { datasets },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: false,
          interaction: { mode: "index", intersect: false },
          scales: {
            // 目盛は日付。本数が増えるほど詰まるので出す数を絞る。
            x: {
              ...stackedXScale({ bottom: i === keys.length - 1,
                                 ticks: { autoSkip: false, callback: (v) => tickLabel(v) } }),
              type: "linear",
              afterBuildTicks: (scale) => { scale.ticks = tickValues().map((v) => ({ value: v })); },
            },
            y: {
              position: "left", beginAtZero: true, afterFit: stackedYFit,
              title: { display: true, text: spec.title, color: NIER_AXIS_COLOR, font: { family: "monospace", size: 10 } },
              // y軸の幅はpanel間で揃えるため固定。桁が伸びると軸titleに被るので、コインは
              // 短縮表記(250k)にして枠に収める。実数はtooltipと山の値marksで読む。
              ticks: { ...nierTicks(), ...(spec.ticks || {}) },
              grid: { color: NIER_GRID_COLOR },
            },
          },
          plugins: {
            // 1系列のpaneに凡例は要らない。軸のtitleがその指標を名乗っている。
            legend: {
              display: datasets.length > 1,
              // 名前の無い系列(窓を渡していない移動平均)は凡例へ出さない。空の札が並ぶ。
              labels: { color: cssToken("--chart-ink"), font: { family: "monospace", size: 11 },
                        boxWidth: 14, boxHeight: 8, filter: (item) => Boolean(item.text) },
            },
            tooltip: tooltipFor(spec, seriesIndex),
          },
        },
      },
    );
    enableValueMarks(chart);
    return { spec, chart };
  });

  // 段ごとに点の数が違う(コインは1日1点・他は1配信1点)ので、縦線が共有するのはindexでは
  // なくx値。読み取る点は「同じ日の中で一番近い点」まで ―― 縦線が指した時刻にコインの棒は
  // 立っていない(棒は日の真ん中に立つ)が、その日の棒がその時点のコインである。
  linkCrosshair(panes.map((p) => p.chart), { byValue: true, tolerance: 0.5 });

  // view.unit: "session"(既定・1配信=1点/コインは1日=1本) / "week" / "month"。
  // view.daily: [{date:"YYYY-MM-DD", diamonds}] — コインの段はここだけを読む。session
  //   合計から作らないのは、日を跨いだ配信のコインが開始日へ寄ってしまうためである。
  // view.movingAvgWindow は点の本数で数える窓幅(単位ごとに呼び側が決める)。
  // view.coinMa: コインの移動平均の窓([7,14,25]など)、view.coinMaText はその単位名。
  // view.coinUnit: コインの段のy軸が名乗る単位("日"/"週"/"月")。
  function update(sessionRows, view = {}) {
    const rows = sessionRows || [];
    const unit = view.unit || "session";
    const daily = (view.daily || []).filter((d) => d && d.date);
    viewUnit = unit;
    // 軸の原点と長さ。sessionの日とコインの日の両方から採る ―― 日を跨いだ配信のコインは
    // 配信の始まった日より後の日へ乗る。
    const marks = [];
    rows.forEach((s) => {
      marks.push(trendDayStart(s.started_at));
      marks.push(trendDayStart(s.ended_at || s.started_at));
    });
    daily.forEach((d) => marks.push(trendYmdStart(d.date)));
    origin = marks.length ? Math.min(...marks) : trendDayStart(Date.now() / 1000);
    // 素材が1つも無ければ日の点も作らない。今日の0本の棒を1本立てると、配信が無いことを
    // 「今日だけ0だった」と名乗ってしまう。
    span = marks.length ? Math.round((Math.max(...marks) - origin) / TREND_DAY) + 1 : 0;

    const periods = unit === "session" ? null : periodList(unit);
    points = unit === "session" || !rows.length
      ? sessionPoints(rows)
      : periodPoints(rows, unit, periods);
    const days = dailyCoinPoints(daily, rows);
    coinPoints = unit === "session" || !periods ? days : periodCoinPoints(days, unit, periods);

    const window = view.movingAvgWindow || opts.movingAvgWindow || 5;
    const coinMa = view.coinMa || [];
    const coinMaText = view.coinMaText || "";
    // 軸の端は棒の端から採る。週/月まとめの端の期間は窓の外まではみ出す(6/29から始まる
    // 窓でも6月の棒は6/1から立つ)ので、日数だけで端を決めると端の棒が切れる。
    const xMin = (coinPoints.length ? Math.min(...coinPoints.map((p) => p.lo)) : 0) - 0.5;
    const xMax = (coinPoints.length ? Math.max(...coinPoints.map((p) => p.hi)) : span) + 0.5;
    panes.forEach(({ spec, chart }) => {
      const rowsFor = paneRows(spec);
      chart.options.scales.x.min = xMin;
      chart.options.scales.x.max = xMax;
      if (spec.maLines) {
        const values = rowsFor.map((p) => p.coins);
        chart.data.datasets.forEach((ds, di) => {
          const w = coinMa[di];
          ds.label = w ? `${w}${coinMaText}` : "";
          ds.hidden = !w;
          // 窓が埋まるまで引かない。埋まるまでを手元の点だけの平均で描くと、左端では
          // 3本が同じ点の平均になって重なり、窓の違いが見えない。
          ds.data = w
            ? movingAverage(values, w, true).map((v, j) => ({ x: rowsFor[j].x, y: v }))
            : [];
          // 窓が埋まる点が1つしか無いと線が引けず、段がまるごと空に見える。手元の履歴が
          // その窓に足りていないだけなので、点で在ることだけは示す。
          ds.pointRadius = ds.data.filter((q) => q.y != null).length > 1 ? 0 : 3;
        });
        chart.update();
        return;
      }
      let di = 0;
      spec.series.forEach((s) => {
        const values = rowsFor.map((p) => s.value(p));
        chart.data.datasets[di].data = values.map((v, j) => ({ x: rowsFor[j].x, y: v }));
        // 点が隣と接し始めたら数珠つなぎの帯になって線の形が読めない。混んだら点を伏せ、
        // 線そのもので推移を見せる(x値で拾うtooltip/crosshairは点が無くても効く)。
        if (!s.bar) chart.data.datasets[di].pointRadius = rowsFor.length > 60 ? 0 : 3;
        di += 1;
        if (s.ma && opts.movingAvg) {
          chart.data.datasets[di].data = movingAverage(values, window)
            .map((v, j) => ({ x: rowsFor[j].x, y: v }));
          di += 1;
        }
      });
      if (spec.daily) chart.options.scales.y.title.text = `${spec.title}/${view.coinUnit || "日"}`;
      chart.update();
    });
  }

  function clear() {
    points = [];
    coinPoints = [];
    panes.forEach(({ chart }) => {
      chart.data.datasets.forEach((ds) => { ds.data = []; });
      chart.update();
    });
  }

  return { chart: panes[0] && panes[0].chart, charts: panes.map((p) => p.chart), update, clear };
}

// ---- Battle cards (shared by history detail modal, monitor, overview, streamers) ----
// A battle is not always 1v1: personal multi (3コラ/4コラ) is an N-host free-for-all
// ranked by score, and team battles are NvM. participants[] holds every host with
// its score/side/team/rank; topology drives which layout the card uses.
function battleParticipants(battle, owner) {
  if (Array.isArray(battle.participants) && battle.participants.length) {
    return battle.participants;
  }
  // Legacy battles stored before participants[] existed: synthesise a 2-host view
  // from the own/opp scalars so old history still renders. The own host is the
  // monitored streamer, so name it from owner rather than a generic placeholder.
  const parts = [{
    user_id: "own",
    nickname: (owner && (owner.nickname || owner.unique_id)) || "",
    unique_id: (owner && owner.unique_id) || "",
    avatar: (owner && owner.avatar) || "",
    is_own: true, side: "own", score: battle.own_score || 0, rank: 1, team_id: null,
  }];
  (battle.opponents || []).forEach((o) =>
    parts.push({ ...o, is_own: false, side: "opp", score: o.score || 0, team_id: null }));
  if (parts.length === 1) {
    parts.push({ user_id: "opp", nickname: "相手", is_own: false, side: "opp", score: battle.opp_score || 0 });
  }
  return parts;
}

// The own host is the monitored streamer; fall back to the owner's name/id/avatar
// rather than a generic "自分" so the streamer's username is shown consistently.
function participantUser(p, owner) {
  return {
    nickname: p.nickname || (p.is_own && owner && (owner.nickname || owner.unique_id)) || p.unique_id || "(unknown)",
    unique_id: p.unique_id || (p.is_own && owner && owner.unique_id) || "",
    avatar: p.avatar || (p.is_own && owner && owner.avatar) || "",
  };
}

// Group participants into teams (own team(s) first). team_id from the proto is the
// authoritative grouping key; side is the fallback for legacy data.
// battle.typeはbackend(tictok/core/battle.py)がparticipantsのteam_idから導出する。
// TikTokは個人マルチ(1:1:1)も「1人陣営×N」のteam構造で送るため、team構造の有無では
// チーム戦と区別できず、typeが"team"なのは実チーム戦(陣営に2人以上)の時だけになる。
function battleTeams(parts) {
  const groups = new Map();
  parts.forEach((p) => {
    const key = p.team_id != null ? `t${p.team_id}` : (p.side === "own" ? "own" : "opp");
    if (!groups.has(key)) groups.set(key, { own: false, members: [], total: 0 });
    const g = groups.get(key);
    g.members.push(p);
    g.own = g.own || p.side === "own";
    g.total = Math.max(g.total, p.team_score || 0);
  });
  const list = [...groups.values()];
  list.forEach((g) => {
    if (!g.total) g.total = g.members.reduce((a, m) => a + (m.score || 0), 0);
  });
  list.sort((a, b) => (a.own === b.own ? 0 : a.own ? -1 : 1));
  let oppN = 0;
  list.forEach((g) => {
    g.label = g.own ? "自チーム" : (list.length > 2 ? `敵チーム${++oppN}` : "敵チーム");
  });
  return list;
}

function battleTopology(battle, owner) {
  const parts = battleParticipants(battle, owner);
  if (battle.type === "team") {
    return { kind: "team", parts, teams: battleTeams(parts), owner };
  }
  const n = parts.length;
  return { kind: n > 2 ? "multi" : "1v1", parts, n, owner };
}

function battleModeLabel(battle) {
  const topo = battleTopology(battle);
  if (topo.kind === "team") {
    return `チーム戦 ${topo.teams.map((t) => t.members.length).join("v")}`;
  }
  if (topo.kind === "multi") return `個人戦 ${topo.n}コラ`;
  return "個人戦 1v1";
}

function battleResultMeta(result) {
  if (result === "win") return { cls: "win", text: "WIN" };
  if (result === "lose") return { cls: "lose", text: "LOSE" };
  if (result === "draw") return { cls: "draw", text: "DRAW" };
  return { cls: "draw", text: "—" };
}

function battleWhenText(battle) {
  const start = fmtTime(battle.start_time);
  const end = battle.end_time ? fmtTime(battle.end_time) : "進行中";
  let text = `${start}〜${end}`;
  if (battle.duration != null) {
    const m = Math.floor(battle.duration / 60);
    const s = Math.floor(battle.duration % 60);
    text += ` (${m}:${String(s).padStart(2, "0")})`;
  }
  return text;
}

function buildBattleHead(battle, ordinal) {
  const head = document.createElement("div");
  head.className = "bh";
  const id = document.createElement("span");
  id.className = "id";
  // Session内での連番(1戦目,2戦目…)を表示。battle.battle_idはTikTokのlink-mic
  // battle ID(巨大なLong値)で人には読めないため、hoverのtitleにのみ残す。
  id.textContent = ordinal ? `BATTLE ${ordinal}` : `BATTLE #${battle.battle_id}`;
  if (battle.battle_id) id.title = `TikTok Battle ID: ${battle.battle_id}`;
  const mode = document.createElement("span");
  mode.className = "mode";
  mode.textContent = battleModeLabel(battle);
  const when = document.createElement("span");
  when.className = "when";
  when.textContent = battleWhenText(battle);
  const meta = battleResultMeta(battle.result);
  const res = document.createElement("span");
  res.className = "res " + meta.cls;
  res.textContent = meta.text;
  // 勝敗はbackend(tictok/core/battle.py)がPK確定時点で判定した値。TikTokから最後に届いた
  // スコアはPK後に相手が枠から抜けた後のもので、勝敗が反転している場合があるため、
  // 食い違うときだけ元の値を注記する(全体解析の勝敗と必ず一致する)。
  if (battle.result_basis === "settled" && battle.result_reported !== battle.result) {
    res.title =
      `報告値 ${fmtNum(battle.own_score_reported || 0)} 対 `
      + `${fmtNum(battle.opp_score_reported || 0)}（${battleResultMeta(battle.result_reported).text}）`;
  }
  head.append(id, mode, when, res);
  return head;
}

// スコアバーを構成する単位(segment): 個人戦は参加者ごと、チーム戦はチームごと。
// これが動画overlay(_personal_lane_order/_battle_mode_label)の分割数と一致する:
// 1v1=2 / 3コラ=3 / 4コラ=4 / チーム戦 NvM=チーム数(通常2)。
function battleBarUnits(topo) {
  if (topo.kind === "team") {
    // チーム合計を1segmentずつ(自チーム→敵チーム順、battleTeamsが整列済み)。
    return topo.teams.map((t) => ({ score: t.total, own: t.own, self: false, label: t.label }));
  }
  // 個人戦: 自分を先頭、相手はscore降順で安定配置(overlayのlane順と一致)。
  const own = topo.parts.filter((p) => p.is_own);
  const opp = topo.parts.filter((p) => !p.is_own).sort((a, b) => (b.score || 0) - (a.score || 0));
  // labelはsegmentのhoverでだけ使う。色は陣営を分けるが「どの色が誰か」は色だけでは
  // 名乗れないので、幅の中に名前を書けない細いsegmentでも誰の分かを引けるようにする。
  return [...own, ...opp].map((p) => ({
    score: p.score || 0, own: p.is_own, self: p.is_own,
    label: participantUser(p, topo.owner).nickname,
  }));
}

// 敵陣segmentの別色数(c1..cN)。これを超える陣営は循環で色を再利用する。動画焼き込みの
// _SCORE_LANE_PALETTE(先頭が自陣roseで、残りが敵陣色)と同じ本数にして割り当てを一致させる。
const SEG_OPP_COLORS = 5;

// Battle chartの自陣/敵陣線。バーの陣営色(rose/cyan)と同系だが、明地の上で線として
// 読める暗さのink側を使う(style.cssの--battle-own-ink/--battle-opp-inkと同値)。
const BATTLE_OWN_LINE = cssToken("--battle-own-ink");
const BATTLE_OPP_LINE = cssToken("--battle-opp-ink");

// 動画overlayの焼き込みと同じ「1本のバーをN分割」スコアバー。各segmentの幅は
// flex-grow=scoreで境界が比率移動し、内側にscoreを描く。色は陣営(segment)ごとに変える:
// 自陣=c-own、敵陣は出現順にc1,c2…と別色。1v1/チーム戦は2分割、個人マルチは参加者数ぶん分割。
function buildBattleScoreBar(topo) {
  const units = battleBarUnits(topo);
  const total = units.reduce((a, u) => a + Math.max(0, u.score || 0), 0);
  const score = document.createElement("div");
  score.className = "score";
  const bar = document.createElement("span");
  bar.className = "bar bar-multi";
  let oppIdx = 0;
  units.forEach((u) => {
    const seg = document.createElement("span");
    // 自陣は常にc-ownで識別、敵陣/敵チームは陣営ごとに別色(c1,c2…)。
    const colorCls = u.own ? "c-own" : `c${(oppIdx++ % SEG_OPP_COLORS) + 1}`;
    seg.className = `seg ${colorCls}` + (u.self ? " self" : "");
    // 全scoreが0(開始直後等)なら均等割りで全segmentを見せる。
    seg.style.flexGrow = total > 0 ? String(Math.max(0, u.score || 0)) : "1";
    if (u.label) seg.title = `${u.label}：${fmtNum(Math.max(0, u.score || 0))}`;
    const v = document.createElement("b");
    v.textContent = fmtNum(Math.max(0, u.score || 0));
    seg.appendChild(v);
    bar.appendChild(seg);
  });
  score.appendChild(bar);
  return score;
}

// 個人マルチ(3コラ/4コラ): 各ホストを順位順に並べ、自分を強調。score barは最大値基準。
function buildBattleRanking(topo) {
  const wrap = document.createElement("div");
  wrap.className = "branks";
  const parts = topo.parts.slice().sort((a, b) => (b.score || 0) - (a.score || 0));
  const max = Math.max(1, ...parts.map((p) => p.score || 0));
  parts.forEach((p, i) => {
    const row = document.createElement("div");
    row.className = "brank" + (p.is_own ? " self" : "");
    const rk = document.createElement("span");
    rk.className = "rk";
    rk.textContent = `${p.rank || i + 1}位`;
    const u = userCell(participantUser(p, topo.owner), { hideId: true });
    u.classList.add("ru");
    const bar = document.createElement("span");
    bar.className = "rbar";
    const fill = document.createElement("span");
    fill.className = p.is_own ? "o" : "e";
    fill.style.width = `${((p.score || 0) / max) * 100}%`;
    bar.appendChild(fill);
    const sc = document.createElement("span");
    sc.className = "rsc";
    sc.textContent = fmtNum(p.score || 0);
    row.append(rk, u, bar, sc);
    wrap.appendChild(row);
  });
  return wrap;
}

// チーム戦 NvM: 各チームのメンバー内訳(チーム合計バーはbuildBattleScoreBarが描く)。人数・チーム数可変。
function buildBattleTeams(topo) {
  const frag = document.createDocumentFragment();
  const teamsWrap = document.createElement("div");
  teamsWrap.className = "bteams";
  topo.teams.forEach((t) => {
    const box = document.createElement("div");
    box.className = "bteam " + (t.own ? "own" : "opp");
    const head = document.createElement("div");
    head.className = "bt-head";
    const lbl = document.createElement("b");
    lbl.textContent = t.label;
    const tot = document.createElement("span");
    tot.className = "bt-total";
    tot.textContent = fmtNum(t.total);
    head.append(lbl, tot);
    box.appendChild(head);
    t.members
      .slice()
      .sort((a, b) => (b.score || 0) - (a.score || 0))
      .forEach((m) => {
        const row = document.createElement("div");
        row.className = "bt-mem" + (m.is_own ? " self" : "");
        const u = userCell(participantUser(m, topo.owner), { hideId: true });
        const sc = document.createElement("span");
        sc.className = "bt-sc";
        sc.textContent = fmtNum(m.score || 0);
        row.append(u, sc);
        box.appendChild(row);
      });
    teamsWrap.appendChild(box);
  });
  frag.appendChild(teamsWrap);
  return frag;
}

function buildBattleVs(owner, battle) {
  const vs = document.createElement("div");
  vs.className = "vs";
  vs.appendChild(userCell(owner, { hideId: true }));
  const sep = document.createElement("b");
  sep.textContent = " vs ";
  vs.appendChild(sep);
  const opp = (battle.opponents || [])[0];
  if (opp) vs.appendChild(userCell(opp, { hideId: true }));
  const diff = battle.own_score - battle.opp_score;
  const diffSpan = document.createElement("span");
  const sign = diff >= 0 ? "+" : "-";
  diffSpan.textContent = ` · 差 ${sign}${fmtNum(Math.abs(diff))}`;
  vs.appendChild(diffSpan);
  return vs;
}

// 貢献を host(宛先配信者) ごとに束ねる。全体監視tile・監視/履歴カードで同じグルーピング
// を共有する。
//
// host_idの無い貢献は __own__ / __opp__ へ寄せ、hostのカードには混ぜない。チーム戦の
// armiesはチーム1つぶんの集約で「誰への貢献か」を名乗らないため、これを自陣hostへ寄せると
// 味方hostを支えた人が自hostの貢献者として並ぶ(実例: BS 46,004の貢献者が味方のものなのに
// 自hostのカードに出ていた)。宛先が確定するのは実測(自室のGift event / 相手Roomのlistener)
// だけなので、判らない分は判らないまま別枠で出す。
function groupContribsByHost(battle) {
  const byHost = new Map();
  (battle.contributions || []).forEach((c) => {
    const key = c.host_id || (c.side === "own" ? "__own__" : "__opp__");
    if (!byHost.has(key)) byHost.set(key, []);
    byHost.get(key).push(c);
  });
  return byHost;
}

// このhostの実弾をどこまで拾えたか。battle.coin_coverage[host_id] は収集側が残す
// {handle, attached_at, attempts, error}。相手/味方hostのコインはそのRoomへ繋いでいた
// 間しか拾えず、繋げなかった分は後から取り戻せない(armiesはコインを持たない)。素性を
// 出さないと欠測が「実弾0」として読まれる。
function coinCoverageNote(battle, host) {
  if (host.is_own) return null;
  const cov = (battle.coin_coverage || {})[host.user_id];
  if (!cov) return null;
  if (!cov.attached_at) {
    return { text: "実弾 未取得", title: cov.error || "" };
  }
  const late = cov.attached_at - (battle.start_time || 0);
  if (late > 1) {
    return { text: `実弾 途中(${fmtDuration(late)}〜)`, title: "" };
  }
  return null;
}

// BS(バトルスコア=PKポイント) と 実弾(コイン) の併記。未取得側は「—」。
// 0は「不明」(相手陣の実弾や、PK内訳が来ていない貢献者)を意味し送信0ではない。
function fmtBs(value) {
  return (value || 0) > 0 ? fmtNum(value) : "—";
}
// カード表示「BS」に相当する実効値。BS(バトルスコア=PKポイント)は倍率で膨らむため実弾(コイン)を
// 必ず上回る。実弾を下回るBSはarmies snapshotの取りこぼし等のデータ欠損なので、実弾をBSとみなす
// (=max)。本物のscoreが無い/実弾未満の代用値は確定BSではないため bsEstimated で(推測)を付す。
function effectiveBs(c) {
  return Math.max(c.score || 0, c.diamonds || 0);
}
// 実弾から代用したBS(=score欠落 or score<実弾)はtrue。表示で(推測)を明示する。
function bsEstimated(c) {
  return (c.score || 0) < (c.diamonds || 0);
}
function fmtBsCoins(c) {
  const dia = c.diamonds || 0;
  const bs = effectiveBs(c);
  const bsText = bs > 0 ? (bsEstimated(c) ? `${fmtNum(bs)}(推測)` : fmtNum(bs)) : "—";
  return `BS ${bsText} / 実弾 ${fmtBs(dia)}`;
}

// 貢献者テーブルのBS列。実弾以上に補正した実効BSを出し、代用値は(推測)を明示、
// どちらも無ければ—。実弾列は fmtBs(diamonds) で別列に分ける。
function bsCellText(c) {
  const bs = effectiveBs(c);
  if (bs <= 0) return "—";
  return bsEstimated(c) ? `${fmtNum(bs)}(推測)` : fmtNum(bs);
}

// 1配信者(host)ぶんの貢献: ヘッダ(配信者 + BS/実弾合計 + 貢献者N人) + 送信者一覧。
// 各送信者は 送信者 / BS(PKポイント) / 実弾(コイン) を列で縦揃えする。
function buildBattleHostContrib(host, byHost, owner, battle) {
  const box = document.createElement("div");
  box.className = "bch-host " + (host.is_own ? "own" : "opp");
  const rows = (byHost.get(host.user_id) || []).slice().sort((a, b) => (b.diamonds || 0) - (a.diamonds || 0));
  const coinsSum = rows.reduce((a, c) => a + (c.diamonds || 0), 0);

  const head = document.createElement("div");
  head.className = "bch-host-head";
  const score = document.createElement("span");
  score.className = "bch-host-score";
  const note = coinCoverageNote(battle, host);
  score.textContent = note
    ? `BS ${fmtBs(host.score)} / ${note.text}`
    : `BS ${fmtBs(host.score)} / 実弾 ${fmtBs(coinsSum)}`;
  if (note) {
    score.classList.add("bch-host-nocoin");
    if (note.title) score.title = note.title;
  }
  const cnt = document.createElement("span");
  cnt.className = "bch-host-cnt";
  cnt.textContent = `${rows.length}人`;
  head.append(userCell(participantUser(host, owner), { hideId: true }), score, cnt);
  box.appendChild(head);

  if (!rows.length) {
    const empty = document.createElement("div");
    empty.className = "bc-empty";
    // 0件の意味は「送られなかった」と「拾えなかった」で違う。取り違えると欠測が実績になる。
    empty.textContent = note ? note.text : "実弾Giftなし";
    box.appendChild(empty);
    return box;
  }
  box.appendChild(buildBattleContribTable(rows));
  return box;
}

// 送信者 / BS(PKポイント) / 実弾(コイン) の3列。hostのカードと宛先不明の枠で共有する。
function buildBattleContribTable(rows) {
  const table = document.createElement("table");
  table.className = "ctab";
  const thead = document.createElement("thead");
  const htr = document.createElement("tr");
  ["送信者", "BS", "実弾"].forEach((label, i) => {
    const th = document.createElement("th");
    th.textContent = label;
    if (i > 0) th.className = "n";
    htr.appendChild(th);
  });
  thead.appendChild(htr);
  table.appendChild(thead);
  const tbody = document.createElement("tbody");
  rows.forEach((c) => {
    const tr = document.createElement("tr");
    const userTd = document.createElement("td");
    userTd.appendChild(userCell(c, { hideId: true }));
    const bsTd = document.createElement("td");
    bsTd.className = "n";
    bsTd.textContent = bsCellText(c);
    const diaTd = document.createElement("td");
    diaTd.className = "n";
    diaTd.textContent = fmtBs(c.diamonds || 0);
    tr.append(userTd, bsTd, diaTd);
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  return table;
}

// 貢献を配信者(host)ごとに表示。個人戦は自陣→相手hostの順、チーム戦はチーム→host。
// 誰がどの配信者へ実弾を送ったかを、全体監視tileと同じ粒度で示す。
function buildBattleContrib(battle, owner) {
  const wrap = document.createElement("div");
  wrap.className = "bcontrib-hosts";
  const topo = battleTopology(battle, owner);
  const byHost = groupContribsByHost(battle);
  if (topo.kind === "team") {
    topo.teams.forEach((team) => {
      const teamBox = document.createElement("div");
      teamBox.className = "bch-team " + (team.own ? "own" : "opp");
      const th = document.createElement("div");
      th.className = "bch-team-head";
      th.textContent = `${team.label} ${fmtNum(team.total)}`;
      teamBox.appendChild(th);
      team.members
        .slice()
        .sort((a, b) => (b.score || 0) - (a.score || 0))
        .forEach((host) => teamBox.appendChild(buildBattleHostContrib(host, byHost, owner, battle)));
      const unattributed = buildBattleUnattributed(byHost, team.own ? "__own__" : "__opp__");
      if (unattributed) teamBox.appendChild(unattributed);
      wrap.appendChild(teamBox);
    });
  } else {
    topo.parts
      .slice()
      .sort((a, b) => (a.is_own === b.is_own ? (b.score || 0) - (a.score || 0) : a.is_own ? -1 : 1))
      .forEach((host) => wrap.appendChild(buildBattleHostContrib(host, byHost, owner, battle)));
    ["__own__", "__opp__"].forEach((key) => {
      const unattributed = buildBattleUnattributed(byHost, key);
      if (unattributed) wrap.appendChild(unattributed);
    });
  }
  return wrap;
}

// 宛先hostの判らない貢献。チーム戦のarmiesはチーム集約で誰への貢献かを名乗らないので、
// 実測(自室のGift event / 相手Roomのlistener)で宛先が付かなかった分がここへ落ちる。
// hostのカードへ勝手に寄せると、その人が支えていない配信者の貢献者として並ぶ。
function buildBattleUnattributed(byHost, key) {
  const rows = (byHost.get(key) || []).slice().sort((a, b) => effectiveBs(b) - effectiveBs(a));
  if (!rows.length) return null;
  const box = document.createElement("div");
  box.className = "bch-host " + (key === "__own__" ? "own" : "opp");
  const head = document.createElement("div");
  head.className = "bch-host-head";
  const label = document.createElement("span");
  label.className = "bch-host-unattr";
  label.textContent = "宛先不明（陣営の合計のみ）";
  const cnt = document.createElement("span");
  cnt.className = "bch-host-cnt";
  cnt.textContent = `${rows.length}人`;
  head.append(label, cnt);
  box.appendChild(head);
  box.appendChild(buildBattleContribTable(rows));
  return box;
}

// Battle中の自陣/敵陣スコアの推移を折れ線で描く。score_series([{t,own,opp}])は
// armies更新ごとにbackendが記録する時系列で、リードの逆転や終盤の競りを可視化する。
// 点が2つ未満、またはChart未読込の画面(全体監視タイル等)では省略する。
// entryのChartは保持し、live更新時はchart.update()でdataのみ差し替える(毎回new Chart()は
// 高コストでcanvasリークの元になる)。カードを作り直してもcanvasは新bodyへ移設する。
function syncBattleScoreChart(entry, battle) {
  const series = battle.score_series || [];
  if (series.length < 2 || typeof Chart === "undefined") {
    if (entry.chart) {
      entry.chart.destroy();
      entry.chart = null;
      entry.chartWrap = null;
    }
    return null;
  }
  const t0 = series[0].t;
  const labels = series.map((p) => {
    const e = Math.max(0, Math.round(p.t - t0));
    return `${Math.floor(e / 60)}:${String(e % 60).padStart(2, "0")}`;
  });
  const ownData = series.map((p) => p.own);
  const oppData = series.map((p) => p.opp);
  if (entry.chart) {
    entry.chart.data.labels = labels;
    entry.chart.data.datasets[0].data = ownData;
    entry.chart.data.datasets[1].data = oppData;
    entry.chart.update();
    return entry.chartWrap;
  }
  const wrap = document.createElement("div");
  wrap.className = "bscore-chart";
  const canvas = document.createElement("canvas");
  wrap.appendChild(canvas);
  entry.chart = new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "自陣", data: ownData, borderColor: BATTLE_OWN_LINE, backgroundColor: "transparent", borderWidth: 1.5, pointRadius: 0, tension: 0.25 },
        { label: "敵陣", data: oppData, borderColor: BATTLE_OPP_LINE, backgroundColor: "transparent", borderWidth: 1.5, pointRadius: 0, tension: 0.25 },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: { ticks: { ...nierTicks(), maxRotation: 0, autoSkip: true, maxTicksLimit: 6 }, grid: { color: NIER_GRID_COLOR } },
        y: { beginAtZero: true, ticks: nierTicks(), grid: { color: NIER_GRID_COLOR } },
      },
      plugins: {
        legend: { labels: { color: cssToken("--chart-ink"), font: { family: "monospace", size: 10 }, boxWidth: 12, boxHeight: 6 } },
        tooltip: { ...nierTooltip(), callbacks: { label: (ctx) => `${ctx.dataset.label}: ${fmtNum(ctx.parsed.y)}` } },
      },
    },
  });
  entry.chartWrap = wrap;
  return wrap;
}

// 倍率タイム(Match Bonus Mission)。Battle中にギフト倍率タイムが発生した場合のみ表示。
// 倍率・発動時間帯・達成可否・獲得ボーナス🪙・後押しした貢献者を1ブロックに集約する。
// bonus_missions[] は発生回数ぶん縦に並べる。発生していないBattleでは何も描かない。
function fmtClock(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;
}

// 倍率・時間帯・進捗・ボーナス・貢献者のいずれも無いmissionは中身が無い(START取りこぼし
// 時のplaceholder等)ため表示対象から除く。
function isMeaningfulMission(m) {
  return Boolean(
    (m.multiplier || 0) ||
      m.task_start_ts ||
      m.reward_start_ts ||
      (m.bonus_sum || 0) ||
      (m.progress || 0) ||
      (m.contributors && m.contributors.length),
  );
}

// ミッション種別の文言。TikTokはStarling key(pm_mt_*)しか配信せず文言自体はeventに載らないため、
// key -> 表示文言をここで持つ(差し込み値は event 実値の progress_target)。焼き込み側の
// video_overlay._BONUS_TASK_TEXT と同一の文言に揃える。
const BONUS_TASK_TEXT = {
  pm_mt_live_match_instructions_2: (n) => `ギフト${n}個`,
  pm_mt_live_match_instructions_gifter_1: (n) => `指定ギフト${n}個`,
  pm_mt_match_sp_team_gifter: (n) => `チーム 指定ギフト${n}個`,
  pm_mt_match_sp_team_point: (n) => `チーム ${n}ポイント`,
};

// 達成条件の文言。種別を運ぶのは prompt key だけなので、key を持たない旧recordや
// 未知keyでは種別を名乗らず空を返す(呼び出し側は条件を伏せた汎用表示へ落とす)。
function bonusTaskLabel(m) {
  for (const p of m.prompts || []) {
    const make = BONUS_TASK_TEXT[p.key];
    if (!make) continue;
    const n = (p.fields || {}).multi;
    return n ? make(n) : "";
  }
  return "";
}

function buildBonusMission(m) {
  const box = document.createElement("div");
  box.className = "dbonus";

  const title = document.createElement("div");
  title.className = "dbonus-t";
  const x = document.createElement("span");
  x.className = "dbonus-x";
  x.textContent = `×${m.multiplier || "?"}`;
  title.append(textSpan("🎁 倍率タイム"), x);
  if (!m.achieved) title.append(textSpan("未達成", "dbonus-miss"));
  box.appendChild(title);

  // フェーズ(予告→ミッション→倍率)を帯で
  const phases = document.createElement("div");
  phases.className = "dbonus-ph";
  const task = bonusTaskLabel(m) || "ミッション";
  const taskLabel = m.progress_target
    ? `${task} ${m.task_duration || "?"}s・${m.achieved ? "達成✅" : `${m.progress}/${m.progress_target}`}`
    : `${task} ${m.task_duration || "?"}s`;
  phases.append(
    phaseSpan(`予告`, "ph-prev"),
    phaseSpan(taskLabel, "ph-task"),
    phaseSpan(`倍率 ${m.reward_duration || "?"}s ×${m.multiplier || "?"}`, "ph-rew"),
  );
  box.appendChild(phases);

  // 実値の行
  const row = document.createElement("div");
  row.className = "dbonus-row";
  const window = m.task_start_ts && m.reward_start_ts
    ? `${fmtClock(m.task_start_ts)}〜${fmtClock((m.reward_start_ts || 0) + (m.reward_duration || 0))}`
    : "";
  if (window) row.appendChild(kv("発動時間帯", window));
  if (m.progress_target) row.appendChild(kv("進捗", `${m.progress}/${m.progress_target}`));
  if (m.bonus_sum) row.appendChild(kv("獲得ボーナス", `🪙 +${fmtNum(m.bonus_sum)}`));
  box.appendChild(row);

  // 後押しした貢献者
  const contribs = m.contributors || [];
  if (contribs.length) {
    const cwrap = document.createElement("div");
    cwrap.className = "dbonus-contribs";
    cwrap.appendChild(textSpan("後押し:", "dbonus-clab"));
    contribs.slice(0, 5).forEach((c) => {
      cwrap.appendChild(userCell({ nickname: c.nickname || "(unknown)", avatar: c.avatar, unique_id: "" }, { hideId: true }));
    });
    if (contribs.length > 5) cwrap.appendChild(textSpan(`＋${contribs.length - 5}名`, "dbonus-clab"));
    box.appendChild(cwrap);
  }
  return box;
}

function textSpan(text, cls) {
  const s = document.createElement("span");
  if (cls) s.className = cls;
  s.textContent = text;
  return s;
}
function phaseSpan(text, cls) {
  const s = document.createElement("span");
  s.className = cls;
  s.textContent = text;
  return s;
}
function kv(label, value) {
  const s = document.createElement("span");
  const b = document.createElement("b");
  b.textContent = value;
  s.append(`${label}: `, b);
  return s;
}

// entry.card(既存DOM)へ1Battleぶんの内容を組み直す。scoreバー/内訳/貢献の中身は
// 都度作り直すが、score推移chartのChart instanceはentryで保持し再利用する(canvasは
// 新bodyへ移設される)。
function buildBattleCardInto(entry, battle, owner, ordinal) {
  const card = entry.card;
  card.className = "bcard";
  const body = document.createElement("div");
  body.className = "bbody";
  // 自陣がどちらかはownerで決まる。履歴のマージ表示は配信者を跨いでBattleを並べるので、
  // 1つに固定できない — その場合はBattleごとに引く関数を受ける。
  const host = typeof owner === "function" ? owner(battle) : owner;
  const topo = battleTopology(battle, host);
  // 形式に応じてN分割したスコアバー(個人=参加者数, チーム=チーム数)。その下に
  // 形式別の内訳(チームbox/順位リスト/対戦表)を描く。
  body.appendChild(buildBattleScoreBar(topo));
  if (topo.kind === "team") {
    body.appendChild(buildBattleTeams(topo));
  } else if (topo.kind === "multi") {
    body.appendChild(buildBattleRanking(topo));
  } else {
    body.appendChild(buildBattleVs(host, battle));
  }
  const chart = syncBattleScoreChart(entry, battle);
  if (chart) body.appendChild(chart);
  // 情報を一切持たない空mission(旧データの取りこぼしplaceholder)は描かない。
  (battle.bonus_missions || []).filter(isMeaningfulMission).forEach((m) => body.appendChild(buildBonusMission(m)));
  body.appendChild(buildBattleContrib(battle, host));
  // 再利用中のchart canvasは上のbodyへ移設済みのため、一括置換してもlive Chartは壊れない。
  card.replaceChildren(buildBattleHead(battle, ordinal), body);
}

function battleSummaryText(battles) {
  const wins = battles.filter((b) => b.result === "win").length;
  const losses = battles.filter((b) => b.result === "lose").length;
  const own = battles.reduce((acc, b) => acc + (b.own_score || 0), 0);
  const opp = battles.reduce((acc, b) => acc + (b.opp_score || 0), 0);
  return `${battles.length} Battle · ${wins}勝${losses}敗 · 自陣計 ${fmtNum(own)} / 敵陣計 ${fmtNum(opp)}`;
}

// container単位でカードDOMとChartをbattle_idキーで保持する。live更新では作り直さず
// 内容とchart dataのみ更新し、無くなったBattleのカードとChartだけ破棄する(全破棄+
// カード毎new Chart()はコスト大でcanvasリークの元)。
const battleCardRegistry = new WeakMap();

// 保持キー。session跨ぎで並べる(履歴のマージ表示)とbattle_idだけでは衝突しうる。
// 衝突すると2戦が同じ要素を指し、並べ直しで1戦ぶん黙って消える。
function battleCardKey(battle, index) {
  const session = battle.session_id == null ? "" : battle.session_id;
  return `${session}:${battle.battle_id || `#${index}`}`;
}

function renderBattleCards(container, battles, owner) {
  let reg = battleCardRegistry.get(container);
  if (!reg) {
    reg = new Map();
    battleCardRegistry.set(container, reg);
  }
  const list = battles || [];
  const seen = new Set();
  list.forEach((b, i) => {
    const key = battleCardKey(b, i);
    seen.add(key);
    let entry = reg.get(key);
    if (!entry) {
      entry = { card: document.createElement("div"), chart: null, chartWrap: null };
      reg.set(key, entry);
    }
    buildBattleCardInto(entry, b, owner, i + 1);
  });
  reg.forEach((entry, key) => {
    if (seen.has(key)) return;
    if (entry.chart) entry.chart.destroy();
    entry.card.remove();
    reg.delete(key);
  });
  // battles順にDOMを整列する(appendChildは既存nodeを移動するため過不足なく並ぶ)。
  list.forEach((b, i) => {
    container.appendChild(reg.get(battleCardKey(b, i)).card);
  });
}

// Gift icon画像。iconはpoolに在るgiftしか出せないので、URLが無ければ何も返さない
// (空の枠も壊れた画像箱も置かない)。iconsはgift_id→URLで、server側が出せる分だけ載せる。
function giftIconNode(giftId, icons) {
  const url = icons && giftId ? icons[String(giftId)] : "";
  if (!url) return null;
  const img = document.createElement("img");
  img.className = "gi-icon";
  img.src = url;
  img.alt = "";
  img.loading = "lazy";
  // proxyが取り込めなかった場合(URL失効・取得失敗)は画像だけ消し、名前は残す。
  img.addEventListener("error", () => img.remove());
  return img;
}

// Gift名の前に置くicon枠。iconを出せないgiftでも枠だけは残す — 有る行だけ名前が右へ
// ずれると、並んだGift名の頭が揃わず縦に読めなくなる。
function giftIconSlot(giftId, icons) {
  const slot = document.createElement("span");
  slot.className = "gi-ic";
  const icon = giftIconNode(giftId, icons);
  if (icon) slot.appendChild(icon);
  return slot;
}

// icon付きのGift名。
function giftNameNode(name, giftId, icons) {
  const wrap = document.createElement("span");
  wrap.className = "gi-label";
  wrap.append(giftIconSlot(giftId, icons), name);
  return wrap;
}

// User単位のGift内訳: Gift種ごとに改行し、個数とコイン数を併記する。
function giftItemsNode(items, icons) {
  const wrap = document.createElement("div");
  wrap.className = "gift-items";
  const entries = Object.entries(items || {});
  if (!entries.length) {
    wrap.textContent = "-";
    return wrap;
  }
  entries.sort((a, b) => (b[1].diamonds || 0) - (a[1].diamonds || 0));
  entries.forEach(([name, info]) => {
    const line = document.createElement("div");
    line.className = "gi-line";
    const n = document.createElement("span");
    n.className = "gi-name";
    n.append(giftIconSlot(info && info.gift_id, icons), name);
    const count = document.createElement("span");
    count.className = "gi-count";
    count.textContent = `×${fmtNum(info.count)}`;
    const coin = document.createElement("span");
    coin.className = "gi-coin";
    coin.textContent = `🪙 ${fmtNum(info.diamonds)}`;
    line.append(n, count, coin);
    wrap.appendChild(line);
  });
  return wrap;
}

function fmtCompact(value) {
  const n = Number(value || 0);
  if (Math.abs(n) >= 1_000_000) return (n / 1_000_000).toFixed(1).replace(/\.0$/, "") + "M";
  if (Math.abs(n) >= 1_000) return (n / 1_000).toFixed(1).replace(/\.0$/, "") + "k";
  return String(n);
}

// 人が読む文字を切るところは全部ここを通す。charAt(0)やslice(n)はUTF-16の単位で切るので、
// 絵文字で始まる名前では上位surrogateだけが残って豆腐(□)が出る ―― 実データの
// 「🟡視聴者G🍑🏌️‍♂️🍔」の頭文字avatarがその形で壊れていた。TikTokの表示名は結合文字を
// 含む絵文字(ZWJ結合の 🐈‍⬛、ZWJ+異体字選択子の 🏌️‍♂️)を普通に含むため、code point単位
// ([...str])でも足りない ―― 1つの絵文字が複数のcode pointに割れる。
// Intl.Segmenterは主要browserに揃っている。持たない環境ではcode point単位まで戻す
// (surrogateを割るよりは正しい)。
const GRAPHEME_SEGMENTER =
  typeof Intl !== "undefined" && typeof Intl.Segmenter === "function"
    ? new Intl.Segmenter(undefined, { granularity: "grapheme" })
    : null;

// 先頭から書記素をcount個。文字の途中で切らない唯一の取り方。
function firstGraphemes(text, count) {
  const value = String(text === undefined || text === null ? "" : text);
  if (!value || count <= 0) return "";
  if (!GRAPHEME_SEGMENTER) return [...value].slice(0, count).join("");
  const out = [];
  for (const { segment } of GRAPHEME_SEGMENTER.segment(value)) {
    out.push(segment);
    if (out.length >= count) break;
  }
  return out.join("");
}

// 書記素の数。長さの判定を .length で行うと、絵文字1つが2にも7にも数えられる。
function graphemeLength(text) {
  const value = String(text === undefined || text === null ? "" : text);
  if (!value) return 0;
  if (!GRAPHEME_SEGMENTER) return [...value].length;
  let n = 0;
  for (const _ of GRAPHEME_SEGMENTER.segment(value)) n += 1;
  return n;
}

// 長い名前を省略する。CSSのtext-overflowが効く場所はCSSに任せ、ここは文字列そのものを
// 短くしたいとき(file名の下見など)に使う。
function truncateGraphemes(text, count) {
  const value = String(text === undefined || text === null ? "" : text);
  if (graphemeLength(value) <= count) return value;
  return `${firstGraphemes(value, count)}…`;
}

function avatarChar(user) {
  const base = (user && (user.nickname || user.unique_id)) || "?";
  return firstGraphemes(base.trim(), 1).toUpperCase() || "?";
}

// TikTok CDN avatars hotlink/Referer-block direct browser loads and their signed
// URLs expire, so route them through the same-origin server proxy. Pass through
// data: URLs and already-proxied URLs untouched.
function avatarSrc(url, id) {
  // URLが無くてもIDが判っていれば、そのID単位のpoolを引く。署名が通らずroom_infoまで
  // 届かなかったsessionのように、その時点のavatar URLを記録できなかった行のため。
  // poolにも無ければ404になり、img errorが頭文字へ落とす。
  if (!url) return id ? `/api/avatar?id=${encodeURIComponent(id)}` : "";
  if (/^(data:|\/api\/avatar\?)/.test(url)) return url;
  let src = `/api/avatar?u=${encodeURIComponent(url)}`;
  // 配信者ID(unique_id)を渡すと、URL期限切れ時にそのID単位の最新アイコンにfallbackする。
  if (id) src += `&id=${encodeURIComponent(id)}`;
  return src;
}

// Avatar pill: shows the CDN image when present, otherwise an initial. The proxy
// can still fail (expiry / removed), so a load error falls back to the initial.
function avatarNode(user, extraClass) {
  const av = document.createElement("span");
  av.className = "av" + (extraClass ? " " + extraClass : "");
  const src = avatarSrc(user && user.avatar, user && user.unique_id);
  if (src) {
    const img = document.createElement("img");
    img.src = src;
    img.alt = "";
    img.loading = "lazy";
    img.addEventListener("error", () => {
      img.remove();
      av.textContent = avatarChar(user);
    });
    av.appendChild(img);
  } else {
    av.textContent = avatarChar(user);
  }
  return av;
}

// "表示名 + @id" with avatar. unique_id identifies; nickname is display-only and
// may change or collide, so both are shown.
// avatarと同じ同一originproxy経由で読む。proxyは取得時にURL path単位でディスクへ
// キャッシュするため、CDNの署名URLが期限切れになっても一度取得済みのバッジはローカルから
// 配信される(=一度取れたものはキャッシュが効く)。未取得で期限切れの時だけ要素ごと消す。
function badgeImg(url, label) {
  const img = document.createElement("img");
  img.className = "u-badge";
  // 期限切れ/未取得のバッジは壊れた画像の箱([])を出さない。読み込み成功まで隠し、
  // 成功時だけ表示、失敗時は要素ごと除去する(数値は残る)。
  // loading="lazy"は付けない: display:noneのlazy画像はviewportに入らず永久に未読込となり、
  // onloadが発火せず表示状態(display:"")に戻らないため、バッジが一切出なくなる。
  img.style.display = "none";
  img.alt = "";
  img.title = label;
  img.onload = () => (img.style.display = "");
  img.onerror = () => img.remove();
  img.src = avatarSrc(url);
  return img;
}

// バッジ画像の直後にLv数値を書いた1組([アイコン]10)。画像だけ/数値だけの片方でも成立する。
function badgeNum(url, num, label) {
  const wrap = document.createElement("span");
  wrap.className = "u-badge-num";
  wrap.title = label;
  if (url) wrap.appendChild(badgeImg(url, label));
  if (num > 0) {
    const n = document.createElement("span");
    n.className = "u-badge-lv";
    n.textContent = num;
    wrap.appendChild(n);
  }
  return wrap;
}

// 配信者リーグ帯(例:A1/B3)。配信者(owner)にだけ付く。デイリー変動するため、その配信
// 時点の値を配信単位で記録している。値が無ければ何も付けない(捏造しない)。
function leagueChip(league) {
  const chip = document.createElement("span");
  chip.className = "u-league";
  chip.title = "配信者リーグ";
  chip.textContent = league;
  return chip;
}

// Battle貢献者など、レベル/バッジdataを持つuserにだけ付く。ギフターLv/メンバーLvを
// [バッジアイコン]数値 の形で併記する(GLvが先、MLvが後)。アイコンと数値は取れた方だけ
// 出す。どちらのdataも無ければnull(ランキング等の素のuserには何も足さない)。
function userBadges(user) {
  if (!user) return null;
  const gifter = user.gifter_badge || "";
  const gifterLv = user.gifter_level || 0;
  const member = user.member_badge || "";
  const level = user.fans_level || 0;
  if (!gifter && !gifterLv && !member && !level) return null;
  const box = document.createElement("span");
  box.className = "u-badges";
  if (gifter || gifterLv > 0) {
    box.appendChild(badgeNum(gifter, gifterLv, "GLv (ギフトレベル/課金グレード)"));
  }
  if (member || level > 0) {
    box.appendChild(badgeNum(member, level, "MLv (メンバーレベル/ファンクラブ)"));
  }
  return box;
}

// GLv/MLvを表の「列」として出すためのcell。userCellの中に混ぜると、名前の長さで
// 横位置が行ごとに動いて縦に読めない。値の無い行にも「-」を置き、列としての縦線を保つ。
function badgeLevelCell(url, num, label) {
  if (!url && !(num > 0)) return "-";
  return badgeNum(url, num, label);
}

function userCell(user, opts = {}) {
  // href付きならlinkにする。名前が出ている場所からその人の画面へ直接飛べないと、
  // nav→検索box→入力→行clickの遠回りになる(Fan台帳と配信者画面が実際そうだった)。
  const wrap = document.createElement(opts.href ? "a" : "span");
  if (opts.href) wrap.href = opts.href;
  wrap.className = "u" + (opts.stackId ? " u-stack" : "") + (opts.href ? " u-link" : "");
  // leagueFirst: リーグchipをアイコンの前に出す(履歴一覧など)。
  if (opts.leagueFirst && user && user.league) wrap.appendChild(leagueChip(user.league));
  wrap.appendChild(avatarNode(user, opts.avatarClass));
  const name = document.createElement("b");
  name.className = "u-name";
  name.textContent = (user && user.nickname) || (user && user.unique_id) || "(unknown)";
  const showId = user && user.unique_id && !opts.hideId;
  let id = null;
  if (showId) {
    id = document.createElement("span");
    id.className = "uid";
    id.textContent = "@" + user.unique_id;
  }
  // stackId: 表示名の後にIDを改行して縦積みする(詳細画面など余白のある場所向け)。
  if (opts.stackId && id) {
    const text = document.createElement("span");
    text.className = "u-text";
    text.append(name, id);
    wrap.appendChild(text);
  } else {
    wrap.appendChild(name);
    if (id) wrap.appendChild(id);
  }
  if (!opts.leagueFirst && user && user.league) wrap.appendChild(leagueChip(user.league));
  // hideBadges: GLv/MLvを別の列(badgeLevelCell)で出す表では、名前の後ろに重ねない。
  if (!opts.hideBadges) {
    const badges = userBadges(user);
    if (badges) wrap.appendChild(badges);
  }
  return wrap;
}

// 表の操作列に入りきらないButtonをまとめるoverflow menu。
// 表は.table-wrap(overflow:auto)の中にあるため、absoluteのmenuはscroll枠でclipされる。
// position:fixedでviewport基準に出し、開いた時のButton位置から座標を決める。
let openRowMenu = null;
// 起点にした要素。開いた元をもう一度押した時にmenuが閉じるのは、この要素の中の
// clickを「外側のclick」と読まないため(toggle以外を起点にできるので、classでは足りない)。
let openRowMenuAnchor = null;
// 閉じる時に呼び戻す。開いた側が持っている状態(起点のaria-expanded)を戻せるようにする。
let openRowMenuOnClose = null;

function closeRowMenu() {
  if (!openRowMenu) return;
  const onClose = openRowMenuOnClose;
  openRowMenu.remove();
  openRowMenu = null;
  openRowMenuAnchor = null;
  openRowMenuOnClose = null;
  if (onClose) onClose();
}

document.addEventListener("click", (ev) => {
  if (!openRowMenu) return;
  if (openRowMenu.contains(ev.target)) return;
  if (ev.target.closest(".row-menu-toggle")) return;
  if (openRowMenuAnchor && openRowMenuAnchor.contains(ev.target)) return;
  closeRowMenu();
});
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") closeRowMenu();
});
window.addEventListener("resize", closeRowMenu);
// 閉じる理由は「起点が動いて、面の居場所が嘘になる」こと。だから閉じるのは起点を載せて
// いる枠(と頁そのもの)がscrollした時だけにする ―― どのscrollでも閉じていた頃は、再生に
// 追従するコメント欄が1行進むたびに、開いている面が黙って消えていた。
// 面の中の一覧が縦へ流れるのは起点と無関係なので、当然そのままにする。
document.addEventListener("scroll", (ev) => {
  if (!openRowMenu) return;
  const target = ev.target;
  // 頁そのもののscrollはdocumentが名乗る。この場合は起点も一緒に動く。
  const node = target instanceof Node ? target : document.documentElement;
  const scrolled = node.nodeType === 9 ? node.documentElement : node;
  if (openRowMenu.contains(scrolled)) return;
  if (openRowMenuAnchor && !scrolled.contains(openRowMenuAnchor)) return;
  closeRowMenu();
}, true);

// 起点の直下(入り切らなければ直上)へ、viewport基準で置く。
function placeFloating(anchor, node) {
  const rect = anchor.getBoundingClientRect();
  const size = node.getBoundingClientRect();
  const left = Math.max(4, Math.min(rect.right - size.width, window.innerWidth - size.width - 4));
  const below = rect.bottom + 2;
  const top = below + size.height > window.innerHeight
    ? Math.max(4, rect.top - size.height - 2)
    : below;
  node.style.left = `${left}px`;
  node.style.top = `${top}px`;
}

// menu以外の浮遊面(選択listなど)も同じ1枚だけを開く。別々の開閉を持つと、2枚が
// 同時に出たまま互いの外側clickを取り合う。
function openPanelAt(anchor, node, onClose) {
  closeRowMenu();
  document.body.appendChild(node);
  placeFloating(anchor, node);
  openRowMenu = node;
  openRowMenuAnchor = anchor;
  openRowMenuOnClose = onClose || null;
  return node;
}

function isPanelOpenFor(anchor) {
  return Boolean(openRowMenu && openRowMenuAnchor === anchor);
}

// items: [{ label, title, danger, disabled, onSelect }]。返り値は操作列へ入れるtoggle Button。
// 任意の要素を起点にmenuを出す。toggle Buttonを介さず「押した場所でそのまま選ばせる」
// 用途(録画が複数あるSessionの字幕化など)にも使う。
function openMenuAt(anchor, items) {
  closeRowMenu();
  const menu = document.createElement("div");
  menu.className = "row-menu";
  menu.dataset.owner = anchor.dataset.menuId || "";
  items.forEach((item) => {
    const btn = document.createElement("button");
    btn.className = "row-menu-item" + (item.danger ? " row-menu-item-danger" : "");
    btn.textContent = item.label;
    if (item.title) btn.title = item.title;
    btn.disabled = Boolean(item.disabled);
    btn.addEventListener("click", () => {
      closeRowMenu();
      item.onSelect();
    });
    menu.appendChild(btn);
  });
  return openPanelAt(anchor, menu);
}

function rowMenu(items, opts) {
  const options = opts || {};
  const toggle = document.createElement("button");
  toggle.className = "btn btn-small row-menu-toggle";
  toggle.textContent = options.label || "その他 ⋯";
  if (options.title) toggle.title = options.title;
  toggle.addEventListener("click", () => {
    const wasOpenFor = openRowMenu && openRowMenu.dataset.owner === String(toggle.dataset.menuId);
    closeRowMenu();
    if (wasOpenFor) return;
    toggle.dataset.menuId = String(Date.now()) + String(Math.random());
    openMenuAt(toggle, items);
  });
  return toggle;
}

// barCols は任意。[{ col, value }] を渡すと、その列のcellの背後へ占有barを敷く。
// value(row) は書式化前の生値を返す(cellの文字列 "12.3 GB" からは量を復元できないため)。
// 割合はその列の最大値を1とする相対で、表を跨いだ比較には使えない。列に負値や非数が
// 混ざる表では長さが意味を持たないので、渡す側で判断する。
function barRatios(rows, barCols) {
  return (barCols || []).map((spec) => {
    const values = rows.map((row) => {
      const v = Number(spec.value(row));
      return Number.isFinite(v) && v > 0 ? v : 0;
    });
    // 行数は数百〜数千になる。Math.max(...values) はspreadの引数上限に触れるので畳む。
    const max = values.reduce((a, b) => (b > a ? b : a), 0);
    return { col: spec.col, values, max };
  });
}

// onRow(tr, row, index) は任意。行に属性やevent(行dblclick等)を付ける用途で呼ぶ。
function renderTableRows(tbodyId, emptyId, rows, toCells, numericCols, onRow, barCols) {
  closeRowMenu();
  const tbody = document.getElementById(tbodyId);
  const empty = document.getElementById(emptyId);
  // dataセルは数値列を右寄せ(num)にするが、headerが左寄せのままだと項目と値が縦に
  // 揃わずズレて見える。numericColsを唯一の根拠に、同じ列のheaderも右寄せへ合わせる。
  const headRow = (() => {
    const table = tbody.closest("table");
    return table && table.tHead ? table.tHead.rows[0] : null;
  })();
  if (headRow) {
    numericCols.forEach((col) => {
      const th = headRow.cells[col];
      if (th) th.classList.add("num");
    });
  }
  tbody.innerHTML = "";
  if (empty) empty.classList.toggle("hidden", rows.length > 0);
  // 行は画面から切り離されたfragmentの上で組む。live tbodyへ1行ずつappendすると、
  // 行数ぶんlayoutが走る(この共通描画は数百行の表でも使われる)。
  const fragment = document.createDocumentFragment();
  const numeric = new Set(numericCols);
  const bars = barRatios(rows, barCols);
  rows.forEach((row, i) => {
    const tr = document.createElement("tr");
    if (i === 0) tr.className = "rank-top";
    toCells(row, i + 1).forEach((cell, col) => {
      const td = document.createElement("td");
      if (numeric.has(col)) td.className = "num";
      if (cell instanceof Node) td.appendChild(cell);
      else td.textContent = cell;
      // 全部0の列にbarを敷くと、長さ0の帯が並ぶだけで読む助けにならない。
      const bar = bars.find((b) => b.col === col);
      if (bar && bar.max > 0) {
        td.classList.add("q");
        td.style.setProperty("--q", (bar.values[i] / bar.max).toFixed(4));
      }
      tr.appendChild(td);
    });
    if (onRow) onRow(tr, row, i);
    fragment.appendChild(tr);
  });
  tbody.appendChild(fragment);
}

// 状態の文言(.form-message)。失敗のときだけ警告色にする。成功・進行中・空文字でも必ず
// classを外すこと。外し忘れると、前の失敗の色が次の成功の文言にそのまま残る。
function setFormMessage(el, text, isError) {
  el.textContent = text;
  el.classList.toggle("is-error", Boolean(isError));
}

// KPIの帯(a-kpibar)へlabel/値のchipを並べる。fans/streamers/videosが同じ物を持って
// いたのでここへ集約した。
function chipBar(containerId, chips) {
  const bar = document.getElementById(containerId);
  bar.innerHTML = "";
  chips.forEach(([label, value, cls, title]) => {
    const chip = document.createElement("div");
    chip.className = "a-chip";
    // 4つ目は任意のtooltip。比率のように「分母が何か」を添えないと読めない項目のため。
    if (title) chip.title = title;
    const l = document.createElement("span");
    l.className = "l";
    l.textContent = label;
    const v = document.createElement("span");
    v.className = "v" + (cls ? " " + cls : "");
    v.textContent = value;
    chip.append(l, v);
    bar.appendChild(chip);
  });
}

// ---- segmented control ----
// 排他選択のうち何度も往復するもの(再生速度など)は<select>だとmenuを開いて狙う手数が
// 要る。全選択肢を並べたbutton群にして1clickで移れるようにする。呼び出し側は既に
// $(id).valueとchange eventで書かれているため、同じI/Fを要素へ生やして置き換えを
// markupだけに留める。
//
// markup:
//   <div id="x" class="seg" role="radiogroup" data-value="1" data-wheel="1" data-revert="1">
//     <button class="seg-item" type="button" data-value="1">1</button>
//   </div>
// data-wheel  … 群の上のwheelで1段ずつ動かす
// data-revert … 選択中をもう一度clickしたときに戻す値
function initSegmented(id) {
  const root = document.getElementById(id);
  const items = Array.from(root.querySelectorAll(".seg-item"));
  const valueAt = (i) => items[i].dataset.value;
  const indexOf = (value) => items.findIndex((b) => b.dataset.value === String(value));
  let index = Math.max(0, indexOf(root.dataset.value ?? valueAt(0)));

  function paint() {
    items.forEach((b, i) => {
      const on = i === index;
      b.classList.toggle("seg-on", on);
      b.setAttribute("aria-checked", on ? "true" : "false");
      // roving tabindex。群全体でtab stopは1つにし、中は矢印keyで移る。
      b.tabIndex = on ? 0 : -1;
    });
  }

  function select(next, emit) {
    if (next < 0 || next >= items.length || items[next].disabled || next === index) return;
    index = next;
    paint();
    if (emit) root.dispatchEvent(new Event("change", { bubbles: true }));
  }

  // disableされた選択肢は飛ばす。素材版は録画によって存在しないことがある。
  function moveTo(start, direction) {
    for (let i = start; i >= 0 && i < items.length; i += direction) {
      if (!items[i].disabled) {
        select(i, true);
        items[i].focus();
        return;
      }
    }
  }

  function step(direction) {
    moveTo(index + direction, direction);
  }

  items.forEach((b, i) => {
    b.setAttribute("role", "radio");
    b.addEventListener("click", (ev) => {
      // ev.detail>0 がmouse click。keyboard(space/enter)由来のclickは0で来る。
      const pointer = ev.detail > 0;
      // 選択中をもう一度押したら既定へ戻す。1x↔倍速の往復をpillの往復移動なしに行う。
      // keyboardのspaceは「選択中の選択肢を選ぶ」が標準の意味なので戻さない。
      if (pointer && i === index && root.dataset.revert !== undefined) {
        select(indexOf(root.dataset.revert), true);
      } else {
        select(i, true);
      }
      // 押したpillにfocusを残すと、直後のspace(再生)や矢印(frame送り)をこの群が
      // 食う。mouseで押したときは画面側のshortcutへ返す。
      if (pointer) b.blur();
    });
  });

  root.addEventListener("keydown", (ev) => {
    const dir = { ArrowLeft: -1, ArrowUp: -1, ArrowRight: 1, ArrowDown: 1 }[ev.key];
    if (dir === undefined && ev.key !== "Home" && ev.key !== "End") return;
    ev.preventDefault();
    if (ev.key === "Home") moveTo(0, 1);
    else if (ev.key === "End") moveTo(items.length - 1, -1);
    else step(dir);
  });

  if (root.dataset.wheel === "1") {
    root.addEventListener("wheel", (ev) => {
      ev.preventDefault();
      step(ev.deltaY > 0 ? 1 : -1);
    }, { passive: false });
  }

  // <select>と同じ読み書きI/F。setterはuser操作でないのでchangeを出さない。
  Object.defineProperty(root, "value", {
    get: () => valueAt(index),
    set: (v) => { const i = indexOf(v); if (i >= 0) select(i, false); },
  });
  Object.defineProperty(root, "selectedIndex", {
    get: () => index,
    set: (i) => select(i, false),
  });
  Object.defineProperty(root, "options", {
    get: () => items.map((b) => ({ value: b.dataset.value, disabled: b.disabled })),
  });

  paint();
  return root;
}

// ---- 目盛りの多い排他選択をbarで出す ----
// 段が9つある再生速度をsegmented controlで並べると、pillだけで行の半分以上を占め、
// 同じ行の他の操作を次の行へ押し出していた。段の意味が「大小」しかない群はbarで出す
// ―― 幅は1/3以下で済み、今どのあたりかは摘みの位置で読める。
// 呼び出し側のI/Fは initSegmented と同じ(.value / .selectedIndex / .options / change)
// なので、置き換えはmarkupの差し替えだけで済む。
//
// markup:
//   <span id="x" class="segbar" data-stops="0.25,0.5,1,2" data-value="1"
//         data-revert="1" data-wheel="1" data-label="再生速度" data-unit="x"></span>
// data-stops  … 段の値(この順に並ぶ)
// data-revert … 数値表示をclickしたときに戻す値
// data-wheel  … barの上のwheelで1段ずつ動かす
function initSegBar(id) {
  const root = document.getElementById(id);
  const stops = (root.dataset.stops || "").split(",").map((s) => s.trim()).filter(Boolean);
  const unit = root.dataset.unit || "";
  const indexOf = (value) => stops.indexOf(String(value));
  let index = Math.max(0, indexOf(root.dataset.value ?? stops[0]));

  const range = document.createElement("input");
  range.type = "range";
  range.className = "segbar-range";
  range.min = "0";
  range.max = String(Math.max(0, stops.length - 1));
  range.step = "1";
  if (root.dataset.label) range.setAttribute("aria-label", root.dataset.label);
  // 今の値そのもの。barだけだと「だいたいこの辺」までしか読めず、1xに戻したいときに
  // 摘みを目で当てる操作になる。
  const out = document.createElement("button");
  out.type = "button";
  out.className = "segbar-out";
  const revert = root.dataset.revert;
  if (revert !== undefined) out.title = `${revert}${unit}へ戻す`;
  root.append(range, out);

  function paint() {
    range.value = String(index);
    out.textContent = `${stops[index] ?? ""}${unit}`;
  }

  function select(next, emit) {
    const at = Math.min(stops.length - 1, Math.max(0, next));
    if (at === index) return;
    index = at;
    paint();
    if (emit) root.dispatchEvent(new Event("change", { bubbles: true }));
  }

  // dragの途中でも音は変わってほしいので input で拾う(change はつまみを離した時だけ)。
  range.addEventListener("input", () => select(Number(range.value), true));
  out.addEventListener("click", () => {
    if (revert === undefined) return;
    select(indexOf(revert), true);
  });
  if (root.dataset.wheel === "1") {
    root.addEventListener("wheel", (ev) => {
      ev.preventDefault();
      // 送る向きはsegmented controlの頃と同じ(下へ回すと次の段=速い側)。barにしたのを
      // 機に反転させると、同じ操作が逆に効くようになる。
      select(index + (ev.deltaY > 0 ? 1 : -1), true);
    }, { passive: false });
  }

  // <select>と同じ読み書きI/F。setterはuser操作でないのでchangeを出さない。
  Object.defineProperty(root, "value", {
    get: () => stops[index],
    set: (v) => { const i = indexOf(v); if (i >= 0) select(i, false); },
  });
  Object.defineProperty(root, "selectedIndex", {
    get: () => index,
    set: (i) => select(i, false),
  });
  Object.defineProperty(root, "options", {
    get: () => stops.map((value) => ({ value, disabled: false })),
  });

  paint();
  return root;
}

// ---- 表示設定の永続化 ----
// 各画面は独立したHTML documentで、nav遷移はフルリロードになる。並べ替え・絞り込み・
// 表示切替のようなuserが選んだ「見せ方」はlocalStorageへ残し、次に開いた時も同じ
// 見え方で始める。残すのは繰り返し同じ値を選ぶcontrolだけで、1回限りの入力(検索語)や
// 実行対象の指定・破壊的操作のoptionは既定値から始める。
// keyは "tictok.<画面>.<control>" で統一する。
const PREF_PREFIX = "tictok.";

function prefKey(name) {
  return name.startsWith(PREF_PREFIX) ? name : PREF_PREFIX + name;
}

// storageはprivate modeやquota超過で例外を投げる。設定が残らないのは許容できるが、
// そこで画面が止まるのは許容できないので読み書きは常に失敗を飲む。
function prefGet(name) {
  try {
    return window.localStorage.getItem(prefKey(name));
  } catch (err) {
    return null;
  }
}

function prefSet(name, value) {
  try {
    if (value == null) window.localStorage.removeItem(prefKey(name));
    else window.localStorage.setItem(prefKey(name), String(value));
  } catch (err) {
    /* 保存できなくても操作は続行する */
  }
}

function prefBool(name, fallback) {
  const stored = prefGet(name);
  if (stored === null) return fallback;
  return stored === "1";
}

function prefIsToggle(el) {
  return el.type === "checkbox" || el.type === "radio";
}

// selectとsegmented controlは、保存時と選択肢が変わっていることがある(配信者一覧や
// 素材版など、中身がdataで決まるもの)。無い値を書くと選択なしの空表示になるため、
// 現存する有効な選択肢だけを復元する。
function prefSelectable(el, value) {
  const options = el.options;
  if (!options) return true;
  return Array.from(options).some((o) => o.value === String(value) && !o.disabled);
}

// 保存値をcontrolへ適用する。選択肢を後から作るcontrolは、埋めた後にもう一度呼ぶ。
// 戻り値は「保存値を実際に適用したか」。
function restorePref(el, name) {
  if (!el) return false;
  const stored = prefGet(name);
  if (stored === null) return false;
  if (el.tagName === "DETAILS") {
    el.open = stored === "1";
    return true;
  }
  if (prefIsToggle(el)) {
    el.checked = stored === "1";
    return true;
  }
  if (!prefSelectable(el, stored)) return false;
  el.value = stored;
  return el.value === stored;
}

function prefCurrent(el) {
  if (el.tagName === "DETAILS") return el.open ? "1" : "0";
  if (prefIsToggle(el)) return el.checked ? "1" : "0";
  return el.value;
}

// 保存値の復元とuser操作の保存をまとめて張る。onChangeはuser操作の時だけ呼ぶ
// (復元は各画面の初期描画に任せ、二重の再取得を起こさない)。
// opts.event で購読するeventを変えられる(text入力を打つ度に残す場合は "input")。
function bindPref(el, name, onChange, opts = {}) {
  if (!el) return false;
  const applied = restorePref(el, name);
  const event = opts.event || (el.tagName === "DETAILS" ? "toggle" : "change");
  el.addEventListener(event, () => {
    prefSet(name, prefCurrent(el));
    if (onChange) onChange();
  });
  return applied;
}

// ---- 一覧placeholderの3状態 ----
// 「読み込み中」「0件」「取得失敗」は必ず描き分ける。取得できなかったものを0件として
// 描くのは、存在しない事実(記録が無かった)の提示にあたる。
// 失敗時の文言は要素の data-label(例: 運用log)から組み立て、生のServer文言はtooltipと
// consoleにだけ残す。
const LIST_LOADING_TEXT = "読み込み中…";

function listStateReset(el) {
  if (el.dataset.emptyText === undefined) el.dataset.emptyText = el.textContent;
  el.classList.remove("list-loading", "list-failed");
  el.removeAttribute("title");
}

function setListState(el, state, err) {
  if (!el) return;
  listStateReset(el);
  if (state === "ok") {
    el.classList.add("hidden");
    return;
  }
  el.classList.remove("hidden");
  if (state === "loading") {
    el.classList.add("list-loading");
    el.textContent = LIST_LOADING_TEXT;
    return;
  }
  if (state === "failed") {
    el.classList.add("list-failed");
    el.textContent = `${el.dataset.label || "Data"}を取得できませんでした`;
    el.title = errorDetailText(err);
    console.warn(`${el.id || "list"}: ${errorDetailText(err)}`, err);
    return;
  }
  el.textContent = el.dataset.emptyText;
}

// 0件の理由が状況で変わる一覧(検索前・対象未選択など)向け。取得失敗ではないので
// 失敗の見た目とtooltipは落とす。
function setListMessage(el, text) {
  if (!el) return;
  listStateReset(el);
  el.classList.remove("hidden");
  el.textContent = text;
}

// ---- 空き容量バー(全画面共通のトップバー) ----
// 出力を拒否する下限を下回ったvolumeは警告表示にする。閾値はserverの設定
// (disk_min_free_gb)が唯一の出所で、画面側は判定を持たない。
const DISK_POLL_MS = 60000;

function fmtGb(bytes) {
  return (Number(bytes || 0) / (1024 * 1024 * 1024)).toFixed(1);
}

// 単位付きのGB。容量の内訳(動画容量)と保持policy(設定)が同じ書式で出すために共通化する。
function fmtBytesGb(bytes) {
  return `${fmtGb(bytes)} GB`;
}

// 単位を跨ぐ一覧(録画本体のGB〜取り残しsidecarのKB)で使う。GB固定だと小さいfileが
// 全部0.0GBに潰れ、消しても減らないように見える。
function fmtBytes(bytes) {
  const n = Number(bytes || 0);
  if (n <= 0) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${units[i]}`;
}

// ---- 再生できなかったときの理由 ----
// 容量整理で動画fileだけを消した録画は行が残るため、再生の入口(検索hit・ハイライト)も
// 残る。srcが404でも<video>はerror eventを出すだけで画面は無言で止まるので、理由を出す。
// 「動画file」ではなく素材とmp4の両方を名乗る。判定(/path の exists)はmp4だけを見ていた
// 頃があり、素材が丸ごと残っている録画にまで「削除されています」と出していた。
const VIDEO_MISSING_TEXT = "動画なし（素材・mp4とも削除済み）";
const VIDEO_ERROR_TEXT = "再生できません";

// error eventはfile削除以外(codec・網)でも飛ぶ。消えたと決め打ちすると、実際は別の
// 原因のときに嘘の説明を出すことになるので、実在をserverに確かめてから文言を選ぶ。
async function videoErrorText(recordingId) {
  try {
    const info = await apiSend("GET", `/api/recordings/${recordingId}/path`);
    return info.exists ? VIDEO_ERROR_TEXT : VIDEO_MISSING_TEXT;
  } catch (err) {
    return VIDEO_ERROR_TEXT;
  }
}

// video要素のerrorを拾い、理由をshow(text)へ渡す。currentRecordingId()で今の対象を
// 引くのは、error到達が非同期で、その間に別の録画へ移っていることがあるため。
function bindVideoError(video, currentRecordingId, show) {
  video.addEventListener("error", async () => {
    // src除去(modalを閉じる/切り替える)でもerrorは飛ぶ。空srcは異常ではない。
    if (!video.getAttribute("src")) return;
    const recordingId = currentRecordingId();
    if (recordingId === null || recordingId === undefined) return;
    const text = await videoErrorText(recordingId);
    if (currentRecordingId() !== recordingId) return;
    show(text);
  });
}

// ---- HLSの再生listが古くなったとき ----
// ts結合(pack)が走ると、録画dirの seg*.ts は pack*.ts へ束ねられ、元のsegmentはfileごと
// 消える。hls.jsは終端済み(VOD)のplaylistを最初の1回しか読み直さないので、結合の最中に
// 開いていたpageは消えたsegmentを指すlistを持ち続け、再生がそこへ届いた瞬間に404で止まる。
// listを引き直せば直るが、hls.js自身は致命的なnetwork errorで読み込みを止めるだけなので、
// そのpageでは以後ずっと同じ位置で止まり続ける(実測: 40:10 = seg01205.ts の開始位置)。
function hlsPlaylistMayBeStale(data) {
  return Boolean(data) && data.fatal === true && data.type === "networkError";
}

// 引き直しは1度きりにする。listを引き直しても直らない失敗(素材そのものが無い・serverが
// 落ちている)で読み直し続けると、理由の出ないloopになる。読み込みが実際に進んだら
// (fragmentが1本bufferへ入ったら)引き直しは効いたので、次の失敗はまた引き直してよい。
function hlsReloadGate() {
  let used = false;
  return {
    take() {
      if (used) return false;
      used = true;
      return true;
    },
    reset() { used = false; },
  };
}

function renderDiskBar(container, data) {
  container.innerHTML = "";
  const volumes = (data && data.volumes) || {};
  const low = new Set((data && data.low_volumes) || []);
  const names = Object.keys(volumes).sort();
  if (!names.length) {
    const empty = document.createElement("span");
    empty.className = "d-empty";
    empty.textContent = "—";
    empty.setAttribute("aria-label", "空き容量 不明");
    container.appendChild(empty);
    return;
  }
  const floorGb = fmtGb((data && data.min_free_bytes) || 0);
  names.forEach((name) => {
    const info = volumes[name];
    const used = info.total_bytes ? (info.total_bytes - info.free_bytes) / info.total_bytes : 0;
    // 空きが減ったと気付く場所と、内訳を見て消す場所を繋ぐ。隣のjob barは既にlinkで、
    // ここだけ押せないのは不揃いだった。
    const item = document.createElement("a");
    item.href = "/capacity";
    item.className = low.has(name) ? "d-vol low" : "d-vol";
    item.title = `${info.path}\n空き ${fmtGb(info.free_bytes)}GB / 全体 ${fmtGb(info.total_bytes)}GB`
      + (Number(data.min_free_bytes) > 0 ? `\n下限 ${floorGb}GB` : "");
    const label = document.createElement("span");
    label.className = "l";
    label.textContent = name;
    const track = document.createElement("span");
    track.className = "track";
    const fill = document.createElement("span");
    fill.className = "fill";
    fill.style.width = `${Math.min(100, Math.max(0, used * 100)).toFixed(1)}%`;
    track.appendChild(fill);
    const value = document.createElement("span");
    value.className = "v";
    value.textContent = `${fmtGb(info.free_bytes)}GB`;
    item.append(label, track, value);
    container.appendChild(item);
  });
}

// ---- 定期取得: 見えていない画面では止める ----
// この画面群は開きっぱなしにして使うので、tabを裏へ回した後も同じ周期でserverを叩き続けて
// いた(実測: 履歴画面の/api/dashboardは41KB・毎回334〜357msで、cacheが効かないまま
// 30秒ごとに焼き続ける)。誰も読んでいない間は呼ばない。表へ戻った時は、隠れている間に
// 周期をまたいでいれば即座に1回引く ―― 戻った瞬間に古い値が出たままにしないため。
// 初回の取得は呼び出し側が自分で行う(この関数は周期だけを持つ)。
function pollWhileVisible(fn, intervalMs) {
  let lastRun = Date.now();
  const run = () => {
    lastRun = Date.now();
    fn();
  };
  setInterval(() => {
    if (document.visibilityState === "hidden") return;
    run();
  }, intervalMs);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && Date.now() - lastRun >= intervalMs) run();
  });
}

function showDiskUnavailable(container) {
  container.innerHTML = "";
  const err = document.createElement("span");
  err.className = "d-empty";
  err.textContent = "?";
  err.setAttribute("aria-label", "空き容量 取得失敗");
  container.appendChild(err);
}

async function loadDiskBar() {
  const container = document.getElementById("disk-bar");
  if (!container) return;
  let data = null;
  try {
    const res = await fetch("/api/disk");
    if (!res.ok) throw new Error(String(res.status));
    data = await res.json();
  } catch (e) {
    showDiskUnavailable(container);
    return;
  }
  renderDiskBar(container, data);
}

if (document.getElementById("disk-bar")) {
  loadDiskBar();
  pollWhileVisible(loadDiskBar, DISK_POLL_MS);
}

// ---- 運用logのerror badge(全画面共通のnav) ----
// 直近の窓(serverの設定が唯一の出所)にerrorが何件あるかをnavの「運用log」へ添える。
// 照会に失敗したときは0件ではなく「?」を出す。取得できていないことを0件として描くと、
// 「何も壊れていない」という嘘の表示になる。
const OPS_BADGE_POLL_MS = 60000;

function opsBadgeElement() {
  const link = navLink("/ops");
  if (!link) return null;
  let badge = link.querySelector(".nav-badge");
  if (!badge) {
    badge = document.createElement("span");
    badge.className = "nav-badge";
    link.appendChild(badge);
  }
  return badge;
}

// navのbadgeと運用log画面の件数欄は同じ /api/ops/summary を出所にする。別々に引くと、
// 運用logを開くたびに同じrequestが2本並ぶ(以降も同じ60秒周期で2本ずつ)。進行中の1本を
// 共有し、直後の呼び出しはその結果へ相乗りさせる。周期が同じでも起動時刻が数ms
// ずれるため、解決済みの結果も短い間だけ持ち回る。
const OPS_SUMMARY_SHARE_MS = 3000;
let opsSummaryShared = null;
function fetchOpsSummary() {
  if (!opsSummaryShared) {
    const promise = apiSend("GET", "/api/ops/summary");
    opsSummaryShared = promise;
    // 失敗は持ち回らない。次の呼び出しには引き直させる。
    promise.then(
      () => setTimeout(() => { if (opsSummaryShared === promise) opsSummaryShared = null; },
                       OPS_SUMMARY_SHARE_MS),
      () => { if (opsSummaryShared === promise) opsSummaryShared = null; },
    );
  }
  return opsSummaryShared;
}

async function loadOpsBadge() {
  const badge = opsBadgeElement();
  if (!badge) return;
  let data;
  try {
    data = await fetchOpsSummary();
  } catch (e) {
    badge.textContent = "?";
    badge.className = "nav-badge unknown";
    badge.setAttribute("aria-label", "運用log 取得失敗");
    badge.removeAttribute("title");
    return;
  }
  badge.removeAttribute("aria-label");
  const errors = Number((data.counts || {}).error || 0);
  const warnings = Number((data.counts || {}).warning || 0);
  badge.title = `直近${Math.round(data.window_hours)}時間: error ${errors} / warning ${warnings}`;
  if (errors > 0) {
    badge.textContent = String(errors);
    badge.className = "nav-badge alert";
    return;
  }
  badge.textContent = "";
  badge.className = "nav-badge";
}

if (navLink("/ops")) {
  loadOpsBadge();
  pollWhileVisible(loadOpsBadge, OPS_BADGE_POLL_MS);
}

// ---- 退避のbadge(全画面共通のnav) ----
// backupが黙って止まるのは、backupの事故のうち最もよくある形である。運用logのerror badgeでは
// 拾えない —— 退避先が外れたまま**録画が1本も終わっていない**時間帯は、失敗の記録がまだ
// 生まれていないのに退避は止まっている。だから件数ではなく、退避そのものの状態を引く。
// 引き先は状況画面(/api/backup/overview)ではなく軽い方(/api/backup/health)にする。あちらは
// 退避先のfolderを開くので、外付けが1台外れているだけで全画面が待たされる。
const BACKUP_BADGE_POLL_MS = 60000;
const BACKUP_BADGE_MARKS = { unreachable: "!", failing: "!", late: "…" };

function backupBadgeElement() {
  const link = navLink("/backup");
  if (!link) return null;
  let badge = link.querySelector(".nav-badge");
  if (!badge) {
    badge = document.createElement("span");
    badge.className = "nav-badge";
    link.appendChild(badge);
  }
  return badge;
}

async function loadBackupBadge() {
  const badge = backupBadgeElement();
  if (!badge) return;
  let data;
  try {
    data = await apiSend("GET", "/api/backup/health");
  } catch (e) {
    // 取得できなかったことを「異常なし」として描かない。退避の話でそれをやると、
    // 止まっていることに誰も気付かないという、この機能が防ごうとしている形そのものになる。
    badge.textContent = "?";
    badge.className = "nav-badge unknown";
    badge.setAttribute("aria-label", "退避 取得失敗");
    badge.removeAttribute("title");
    return;
  }
  badge.removeAttribute("aria-label");
  const alerts = data.alerts || [];
  if (!data.state) {
    badge.textContent = "";
    badge.className = "nav-badge";
    badge.removeAttribute("title");
    return;
  }
  badge.textContent = BACKUP_BADGE_MARKS[data.state] || "!";
  badge.className = data.state === "late" ? "nav-badge unknown" : "nav-badge alert";
  badge.title = alerts.map((item) => item.label).join(" / ");
}

if (navLink("/backup")) {
  loadBackupBadge();
  pollWhileVisible(loadBackupBadge, BACKUP_BADGE_POLL_MS);
}

// ---- 共通UI: 通知toast ----
// window.alertはpageのscript実行ごと止めるため、WSで届く録画状態やjob進捗が、
// 誰かが「OK」を押すまで反映されない。監視画面を開いたまま席を外す使い方をするので、
// 通知は画面内へ出して処理は止めない。
// 情報表示は自動で消すが、errorは消さない。監視画面を開いたまま席を外す使い方なので、
// 録画・出力の失敗が自動消滅すると、戻ってきたときに失敗した事実そのものが残らない。
// 閉じる操作を挟むことで「見た」がユーザーの明示になる(alertの確認強制の代わり)。
const TOAST_MS = 6000;
// 配列で複数行を渡したときに1行ずつ出す間隔。全行を一度に出すと、量の多い通知は
// 塊として目に入って読み飛ばされる。順に増えると視線が最初の行から始まる。
const TOAST_LINE_MS = 50;

function toastLayer() {
  let layer = document.getElementById("toast-layer");
  if (!layer) {
    layer = document.createElement("div");
    layer.id = "toast-layer";
    layer.className = "toast-layer";
    layer.setAttribute("role", "status");
    layer.setAttribute("aria-live", "polite");
    document.body.appendChild(layer);
  }
  return layer;
}

// 消える演出の長さはCSS側の定義をそのまま読む。JSに秒数を持つと二重定義になり、
// animationendに頼ると、演出が無効な環境(reduced motion・CSS未適用)で永久に残る。
function dismissToast(toast) {
  if (!toast.isConnected || toast.classList.contains("toast-out")) return;
  toast.classList.add("toast-out");
  const ms = (parseFloat(getComputedStyle(toast).animationDuration) || 0) * 1000;
  if (ms <= 0) {
    toast.remove();
    return;
  }
  setTimeout(() => {
    if (toast.isConnected) toast.remove();
  }, ms);
}

// 残り時間をbarの幅で見せる。barはtransformで縮めるのでlayoutを再計算しない。
function startToastProgress(toast, duration) {
  const bar = toast.querySelector(".toast-progress-bar");
  if (bar) bar.style.animation = `toast-progress ${duration}ms linear forwards`;
  setTimeout(() => dismissToast(toast), duration);
}

// kindは "error"(失敗の報告) と既定の情報表示。errorは自動で消さず、閉じるまで残す。
// messageは文字列か、1行ずつ順に出す配列。optsは {title, duration}。
function showToast(message, kind, opts) {
  const options = opts || {};
  const toLine = (value) => String(value === undefined || value === null ? "" : value).trim();
  const lines = (Array.isArray(message) ? message : [message]).map(toLine).filter(Boolean);
  if (!lines.length) return null;
  const title = toLine(options.title);
  const duration = Number(options.duration) > 0 ? Number(options.duration) : TOAST_MS;
  const key = title ? `${title}\n${lines.join("\n")}` : lines.join("\n");
  // errorは閉じるまで残るので、同じ失敗が繰り返されると画面が埋まる(録画の再試行や
  // job失敗は同一文面で連続する)。同じ文面は増やさず回数だけ更新する。
  if (kind === "error") {
    const existing = [...toastLayer().querySelectorAll(".toast-error")].find(
      (el) => el.dataset.toastText === key,
    );
    if (existing) {
      const count = Number(existing.dataset.toastCount || "1") + 1;
      existing.dataset.toastCount = String(count);
      existing.querySelector(".toast-count").textContent = `×${count}`;
      return existing;
    }
  }
  const toast = document.createElement("div");
  toast.className = kind === "error" ? "toast toast-error" : "toast";
  toast.dataset.toastText = key;
  const main = document.createElement("div");
  main.className = "toast-main";
  if (title) {
    const head = document.createElement("div");
    head.className = "toast-title";
    head.textContent = title;
    main.appendChild(head);
  }
  const body = document.createElement("div");
  body.className = "toast-body";
  main.appendChild(body);
  const count = document.createElement("span");
  count.className = "toast-count";
  const close = document.createElement("button");
  close.className = "toast-close";
  close.type = "button";
  close.textContent = "✕";
  close.setAttribute("aria-label", "閉じる");
  close.addEventListener("click", () => dismissToast(toast));
  toast.append(main, count, close);
  if (kind !== "error") {
    const progress = document.createElement("div");
    progress.className = "toast-progress";
    const bar = document.createElement("div");
    bar.className = "toast-progress-bar";
    progress.appendChild(bar);
    toast.appendChild(progress);
  }
  toastLayer().appendChild(toast);
  // 出し切ってから残り時間の計測を始める。行を出している途中でbarが減り始めると、
  // 最後の行が出た時点で読める時間が既に目減りしている。
  let index = 0;
  const showNextLine = () => {
    if (!toast.isConnected) return;
    if (index < lines.length) {
      const line = document.createElement("div");
      line.className = "toast-line";
      line.textContent = lines[index];
      body.appendChild(line);
      index += 1;
      setTimeout(showNextLine, TOAST_LINE_MS);
      return;
    }
    if (kind !== "error") startToastProgress(toast, duration);
  };
  showNextLine();
  return toast;
}

// titleは失敗した操作の名前。API由来のmessageは何の操作で出たのかを名乗らないことが
// 多く、errorは閉じるまで積まれるので、後から見たときに出所が分からなくなる。
function showError(err, title) {
  showToast(err && err.message ? err.message : String(err), "error", { title });
}

// ---- 共通UI: 録画の保守操作 ----
// 履歴の詳細と配信者の録画file一覧の両方から使う。片方だけmenuの奥に畳むと、
// 同じ操作が画面ごとに違う深さになる(実際そうなっていた)。

// 保護badge。状態が見えている場所でそのまま切り替える。menuへ畳むと
// 「見えているのに切り替えは2階層下」というちぐはぐが起きる。
function protectBadge(rec, onDone) {
  const badge = document.createElement("button");
  badge.className = "st protect-toggle" + (rec.protected ? " protected" : "");
  badge.type = "button";
  badge.textContent = rec.protected ? "保護中" : "保護";
  badge.setAttribute("aria-pressed", rec.protected ? "true" : "false");
  badge.addEventListener("click", async () => {
    badge.disabled = true;
    try {
      await apiSend("POST", `/api/recordings/${rec.id}/protect`, { protected: !rec.protected });
      if (onDone) onDone();
    } catch (err) {
      badge.disabled = false;
      showError(err, "録画の保護");
    }
  });
  return badge;
}

// 派生物(焼き込み・Up出力・renderの中間file)だけ消す。元録画は残り再出力できる
// 可逆操作なので確認dialogは挟まない(取り消せない削除と同じ重さで出すと、
// 確認dialogそのものが読み飛ばされる)。
async function deleteDerived(rec, onDone) {
  try {
    const res = await apiSend("DELETE", `/api/recordings/${rec.id}/derived`);
    showToast(`派生物 ${fmtBytes(res.freed_bytes)} を削除`);
    if (onDone) onDone();
  } catch (err) {
    showError(err, "派生物の削除");
  }
}

// ---- 共通UI: 確認dialog ----
// 取り消せない操作の前に確認を取る。window.confirmと違い、何を消すのかを複数行で読ませ、
// 破壊的な操作は実行Buttonを危険色にできる。
// 返り値はPromise<boolean>で、Escape・背景click・キャンセルはいずれもfalse。
// 閉じる側は「キャンセル」で固定する。「取消」だと、jobの取り消しのように操作そのものが
// 「取り消し」のとき、実行buttonと同じ意味に読めてどちらが何をするのか分からなくなる。
// 実行側のlabelは呼び出し側が対象まで名乗る(「jobを取り消す」「削除する」)。
function confirmDialog(message, opts) {
  const options = opts || {};
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay confirm-overlay";
    const modal = document.createElement("div");
    modal.className = "modal modal-narrow confirm-modal";
    const head = document.createElement("div");
    head.className = "modal-head";
    const title = document.createElement("h2");
    title.textContent = options.title || "確認";
    head.appendChild(title);
    const body = document.createElement("div");
    body.className = "modal-body confirm-text";
    body.textContent = message;
    const actions = document.createElement("div");
    actions.className = "confirm-actions";
    const cancel = document.createElement("button");
    cancel.className = "btn";
    cancel.textContent = options.cancelLabel || "キャンセル";
    const ok = document.createElement("button");
    ok.className = options.danger === false ? "btn btn-primary" : "btn btn-danger";
    ok.textContent = options.confirmLabel || "実行";
    actions.append(cancel, ok);
    modal.append(head, body, actions);
    overlay.appendChild(modal);

    const finish = (answer) => {
      document.removeEventListener("keydown", onKey, true);
      overlay.remove();
      resolve(answer);
    };
    const onKey = (ev) => {
      if (ev.key !== "Escape") return;
      // 他のmodalのEscape handlerまで届くと、確認を閉じたつもりで背後の画面まで閉じる。
      ev.stopPropagation();
      finish(false);
    };
    cancel.addEventListener("click", () => finish(false));
    ok.addEventListener("click", () => finish(true));
    overlay.addEventListener("click", (ev) => {
      if (ev.target === overlay) finish(false);
    });
    document.addEventListener("keydown", onKey, true);
    document.body.appendChild(overlay);
    ok.focus();
  });
}

// confirmDialogの文字入力版。取消はnull、確定はtrimした文字列を返す(空文字は確定させず
// 入力を促す — 空の名前を受けると、呼び出し側全員が同じ空チェックを持つことになる)。
function promptDialog(message, opts) {
  const options = opts || {};
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay confirm-overlay";
    const modal = document.createElement("div");
    modal.className = "modal modal-narrow confirm-modal";
    const head = document.createElement("div");
    head.className = "modal-head";
    const title = document.createElement("h2");
    title.textContent = options.title || "入力";
    head.appendChild(title);
    const body = document.createElement("div");
    body.className = "modal-body confirm-text";
    const label = document.createElement("div");
    label.textContent = message;
    const input = document.createElement("input");
    input.type = "text";
    input.className = "prompt-input";
    input.value = options.value || "";
    body.append(label, input);
    const actions = document.createElement("div");
    actions.className = "confirm-actions";
    const cancel = document.createElement("button");
    cancel.className = "btn";
    cancel.textContent = options.cancelLabel || "キャンセル";
    const ok = document.createElement("button");
    ok.className = "btn btn-primary";
    ok.textContent = options.confirmLabel || "決定";
    actions.append(cancel, ok);
    modal.append(head, body, actions);
    overlay.appendChild(modal);

    const finish = (answer) => {
      document.removeEventListener("keydown", onKey, true);
      overlay.remove();
      resolve(answer);
    };
    const submit = () => {
      const value = input.value.trim();
      if (!value) {
        input.focus();
        return;
      }
      finish(value);
    };
    const onKey = (ev) => {
      if (ev.key === "Enter" && document.activeElement === input) {
        ev.stopPropagation();
        submit();
        return;
      }
      if (ev.key !== "Escape") return;
      ev.stopPropagation();
      finish(null);
    };
    cancel.addEventListener("click", () => finish(null));
    ok.addEventListener("click", submit);
    overlay.addEventListener("click", (ev) => {
      if (ev.target === overlay) finish(null);
    });
    document.addEventListener("keydown", onKey, true);
    document.body.appendChild(overlay);
    input.focus();
    input.select();
  });
}

// ---- 共通UI: 進捗bar ----
// spinner付きは「今この画面から起動して待っている」操作向け、spinner無しは一覧に並ぶ
// 他所で動いているjobの状態表示向け。
// compactは一覧の操作列(Buttonと同じcell)に出す版。server側のstageは段階名に位置まで
// 含む長文（例:「(4/6) コメント層を描画中（0:12:34 / 4:39:10）＋ 焼き込み合成中（…）」）で、
// 折り返さない表にそのまま出すと操作列だけが数十文字ぶん横へ伸び、一覧全体が読めなくなる。
// compactでは自前の短いlabel(shortLabel)だけを名乗り、barと%を下段へ落として横幅を
// Button1個ぶんに収める。段階の全文と残り時間はtooltipへ、段階を追う画面はJob一覧が持つ。
function makeProgress(opts) {
  const options = opts || {};
  const prog = document.createElement("span");
  prog.className = "dl-progress";
  const stage = document.createElement("span");
  stage.className = "dl-stage";
  stage.textContent = options.label || options.shortLabel || "準備中…";
  const bar = document.createElement("span");
  bar.className = "dl-bar";
  const fill = document.createElement("span");
  fill.className = "dl-bar-fill";
  bar.appendChild(fill);
  const text = document.createElement("span");
  text.className = "dl-pct";
  let spinner = null;
  if (options.spinner !== false) {
    spinner = document.createElement("span");
    spinner.className = "spinner dl-spinner";
    const core = document.createElement("span");
    core.className = "spinner-core";
    spinner.appendChild(core);
  }
  if (options.compact) {
    prog.classList.add("dl-compact");
    if (options.shortLabel) prog.dataset.short = options.shortLabel;
    const head = document.createElement("span");
    head.className = "dl-row";
    if (spinner) head.appendChild(spinner);
    head.appendChild(stage);
    const foot = document.createElement("span");
    foot.className = "dl-row";
    foot.append(bar, text);
    prog.append(head, foot);
    return prog;
  }
  // 段階名(詳細つきで長い)と%は別の要素にする。1要素に混ぜると、段階名の長さで%まで
  // 押し出されるか、cellが横に伸びてtable全体が崩れる。段階名だけを縮める。
  if (spinner) prog.appendChild(spinner);
  prog.append(stage, bar, text);
  return prog;
}

function setProgress(prog, label, pct) {
  const value = Math.max(0, Math.min(100, Math.round(Number(pct) || 0)));
  const short = prog.dataset.short || "";
  prog.querySelector(".dl-bar-fill").style.inlineSize = `${value}%`;
  prog.querySelector(".dl-stage").textContent = short || label;
  prog.querySelector(".dl-pct").textContent = `${value}%`;
  // 短いlabelで名乗った場合でも、段階の全文が読めなくなってはいけない。
  if (short) prog.title = `${label} ${value}%`;
}

// 実行中jobの残り時間。開始からの経過と達成率だけで見積もる(段階ごとの重みはserver側で
// 既に%へ畳まれているため、%は概ね時間に比例する)。序盤の%は分母が小さく見積もりが
// 何倍にも振れるので、一定%に達するまでは出さない — 外れた残り時間は無いより悪い。
const JOB_ETA_MIN_PCT = 5;

function jobEtaText(job) {
  const pct = Number(job.pct) || 0;
  if (!job.started_at || pct < JOB_ETA_MIN_PCT || pct >= 100) return "";
  const elapsed = Date.now() / 1000 - job.started_at;
  if (elapsed <= 0) return "";
  return `残り約 ${fmtDuration((elapsed / pct) * (100 - pct))}`;
}

// job台帳の1行を進捗表示へ写す。待機中はまだ何も進んでいないので%を出さない
// (0%と描くと、動き出したのに止まっているように読める)。
function setJobProgress(prog, job) {
  const short = prog.dataset.short || "";
  if (job.state === "pending") {
    prog.querySelector(".dl-bar-fill").style.inlineSize = "0%";
    // 順番が分かる時は必ず出す。「待機中」だけでは、次に始まるのか3時間jobの後ろに
    // 並んだのかが区別できない。
    const position = Number(job.queue_position) || 0;
    prog.querySelector(".dl-stage").textContent = position > 0
      ? (short ? `待機 ${position}番目` : `待機中（${position}番目）`)
      : "待機中";
    prog.querySelector(".dl-pct").textContent = "";
    if (short) prog.title = short;
    else prog.removeAttribute("title");
    return;
  }
  setProgress(prog, job.stage || "準備中", job.pct);
  const eta = jobEtaText(job);
  // 残り時間も段階名と同じく行を横へ伸ばす。compactでは%だけを出し、残りはtooltipへ回す。
  if (short) {
    if (eta) prog.title += `・${eta}`;
    return;
  }
  if (eta) prog.querySelector(".dl-pct").textContent += `・${eta}`;
  // 段階名は詳細(frame数・encode位置)まで含めると長い。省略表示になっても全文が
  // 読めるよう、tooltipには必ず全文を入れる。
  prog.title = `${job.stage || "準備中"} ${prog.querySelector(".dl-pct").textContent}`;
}

function finishProgress(prog, text) {
  const spinner = prog.querySelector(".dl-spinner");
  if (spinner) spinner.remove();
  prog.querySelector(".dl-bar-fill").style.inlineSize = "100%";
  // compactは段階名の行と bar+% の行が分かれている。完了文言を%側へ入れると段階名の行が
  // 空のまま残り、cellの中で文字が下段だけに沈む。名乗る側(上段)へ入れる。
  const done = text || "完了 ✓";
  const compact = prog.classList.contains("dl-compact");
  prog.querySelector(".dl-stage").textContent = compact ? done : "";
  prog.querySelector(".dl-pct").textContent = compact ? "" : done;
  prog.title = "";
  prog.classList.add("done");
}

// ---- job状況(全画面共通のnav badge) ----
// job台帳のsnapshot(jobs)と更新(job_update)は全pageのWSへ届いているのに、Job画面以外は
// 捨てていた。出力が動いているか・失敗が残っているかはどの画面からでも見えるべきである。
// 出す場所はnavの「Job」1箇所だけにする: topbarに独立した帯を置いていた頃は、行き先
// (Job画面)と数字が別の場所に在り、tabだけを見ても何本走っているのか分からなかった。
const JOB_BAR_FAILED_STATES = ["failed", "interrupted"];
let jobBarState = null;

// session一括投入はgroupの合成行と録画ごとの明細行の両方が流れてくる。合成行はjob_idに
// group_idがそのまま入るので、それ以外のgroup付き行(=明細)を数えると二重に数える。
function jobBarCountable(job) {
  const groupId = job.group_id || "";
  return !groupId || groupId === job.job_id;
}

function jobBarElement() {
  const link = navLink("/jobs");
  if (!link) return null;
  let badge = link.querySelector(".nav-badge");
  if (!badge) {
    badge = document.createElement("span");
    badge.className = "nav-badge";
    link.appendChild(badge);
  }
  return badge;
}

// 帯が数えている失敗・中断の件数。Job画面が「今のfilterでは出ていない失敗」を名乗るのに
// 読む。数え方(group行の畳み込み・対象state)をJob画面へ写すと必ずずれるので、出所は
// この関数1つにする。
function jobBarFailedCount() {
  if (!jobBarState) return 0;
  return [...jobBarState.values()].filter(jobBarCountable)
    .filter((job) => JOB_BAR_FAILED_STATES.includes(job.state)).length;
}

function renderJobBar() {
  if (!jobBarState) return;
  const rows = [...jobBarState.values()].filter(jobBarCountable);
  // Podはnavのbadgeが無い画面でも出す(badgeの有無はnavの作りの話で、jobが動いている
  // かどうかとは関係が無い)。
  reportJobsToPod(rows);
  const badge = jobBarElement();
  if (!badge) return;
  const link = badge.parentElement;
  const running = rows.filter((job) => job.state === "running").length;
  const pending = rows.filter((job) => job.state === "pending").length;
  const failed = jobBarFailedCount();
  // navのtabは行き先が固定の移動手段で、filterを積まない。失敗が在る間ずっと
  // ?state=failed を積んでいた頃は、失敗した履歴が直近に残っているだけで毎回
  // 「失敗・中断のみ」へ着地し、人が選んだ状態filterが押すたびに上書きされていた。
  // 失敗が隠れて見えないことはJob画面側(job-failed-note)が名乗る。
  link.href = "/jobs";
  if (!running && !pending && !failed) {
    badge.textContent = "";
    badge.className = "nav-badge";
    link.removeAttribute("title");
    return;
  }
  // 数字は1つだけ出す。動いている本数(実行中+待機中)と失敗を並べると、tabに2つの数が
  // 付いてどちらが何なのか読めない。失敗が在るときは失敗を出す — 放っておけないのは
  // そちらで、内訳はhoverが持つ。
  badge.textContent = String(failed || running + pending);
  badge.className = failed ? "nav-badge alert" : "nav-badge";
  link.title = failed
    ? `実行中 ${running} / 待機中 ${pending} / 失敗 ${failed}`
    : `実行中 ${running} / 待機中 ${pending}`;
}

// ---- Podへjobの現況を渡す ----
// 台帳はどの画面のWSにも届いているのに、進行はnavの数字にしか出ていなかった。
// 数字は「何本あるか」しか言わず、「今どの段階か」「終わったか」は Job画面を開くまで
// 分からない。Podはその2つだけを、job中に限って言う。
//
// 台詞はすべてjobが持っている値(段階名・失敗message)から作る。飾りの台詞は言わせない
// ―― 出所の無い言葉が混じると、どれがjobの実際の報告なのか区別できなくなる。
const podSeen = new Map();

function podJobLabel(job) {
  // 対象名はjobによって持ち方が違うので、在る物を順に使う。どれも無ければ種別で呼ぶ。
  return job.title || job.target || job.recording_name || job.domain || "job";
}

function reportJobsToPod(rows) {
  const running = rows.filter((job) => job.state === "running");
  // 終わった物の報告。前に実行中として見ていたjobだけを対象にする(画面を開いた時点で
  // 既に終わっていた過去のjobまで報告すると、起動のたびに古い結果を読み上げる)。
  let finished = null;
  rows.forEach((job) => {
    const was = podSeen.get(job.job_id);
    if (was === "running" && job.state !== "running") finished = job;
    if (job.state === "running" || was) podSeen.set(job.job_id, job.state);
  });
  // 台帳から消えた行を覚え続けない。
  const alive = new Set(rows.map((job) => job.job_id));
  [...podSeen.keys()].forEach((id) => { if (!alive.has(id)) podSeen.delete(id); });

  if (finished) {
    const failed = JOB_BAR_FAILED_STATES.includes(finished.state);
    const detail = failed && finished.message ? `：${finished.message}` : "";
    podSay(`${podJobLabel(finished)} ${failed ? "停止" : "完了"}${detail}`,
      failed ? "warn" : null);
    // 続きが在るならそのまま次の報告へ移り、無ければ帰る。
    if (!running.length) podSay("");
    return;
  }
  if (!running.length) { podSay(""); return; }
  const job = running[0];
  const rest = running.length > 1 ? `（ほか ${running.length - 1} 本）` : "";
  const pct = Number.isFinite(Number(job.pct)) ? ` ${Math.round(Number(job.pct))}%` : "";
  podSay(`${podJobLabel(job)}：${job.stage || "実行中"}${pct}${rest}`);
}

function applyJobBar(message) {
  if (message.type === "jobs") {
    jobBarState = new Map((message.data || []).map((job) => [job.job_id, job]));
    renderJobBar();
    return;
  }
  if (message.type === "job_update" && message.job) {
    if (!jobBarState) jobBarState = new Map();
    jobBarState.set(message.job.job_id, message.job);
    scheduleJobBar();
  }
}

// queueは1件が動き出すたび待機列の順番を全件配り直すので、job_updateは数十通が一息に来る。
// 帯の数え直しは全件走査なので、1通ごとにやらず次の描画frameまで畳む。
let jobBarScheduled = false;
function scheduleJobBar() {
  if (jobBarScheduled) return;
  jobBarScheduled = true;
  requestAnimationFrame(() => {
    jobBarScheduled = false;
    renderJobBar();
  });
}

// ---- 全画面共通: 横断jump (Ctrl+K) ----
// 配信者・Session・録画を1つの入力で横断で絞り込み、選んだ対象の画面へ直接飛ぶ。
// 候補の取得は最初にCtrl+Kを押したときだけ行う。全画面のload毎にAPIを3本叩くと、
// 一度も使わない利用者にまで常時cost を払わせることになるため遅延取得にしている。
// 飛び先はいずれも既存の受け口を使う(新しい画面側の対応は不要)。
//   配信者 → /streamers?uid=   (streamers.js が起動時に読む)
//   Session → /history?session= (history.js が起動時に読んで詳細を開く)
//   録画   → /history?session=  (録画は詳細modalの「録画」一覧に並ぶ)
const JUMP_PER_KIND = 8;

let jumpUI = null;
let jumpItems = null;
let jumpState = "idle";
let jumpError = null;
let jumpRows = [];
let jumpActive = 0;

function jumpKindLabel(kind) {
  if (kind === "streamer") return "配信者";
  if (kind === "session") return "Session";
  if (kind === "fan") return "視聴者";
  return "録画";
}

// 検索対象の文字列は候補を作るときに1度だけ組む(打鍵ごとに組み直さない)。
function buildJumpItems(streamers, sessions, recordings, fans) {
  const items = [];
  streamers.forEach((s) => {
    items.push({
      kind: "streamer",
      title: s.nickname || s.unique_id,
      sub: `@${s.unique_id} ・ Session ${fmtNum(s.sessions)} ・ コイン ${fmtNum(s.diamonds)}`,
      search: `${s.unique_id} ${s.nickname || ""}`.toLowerCase(),
      href: `/streamers?uid=${encodeURIComponent(s.unique_id)}`,
    });
  });
  sessions.forEach((s) => {
    const name = s.owner_nickname || s.unique_id;
    items.push({
      kind: "session",
      title: `#${sessionNo(s.id)} ${name}`,
      sub: `@${s.unique_id} ・ ${fmtDateTime(s.started_at)}`,
      // 0埋めの有無どちらで打っても当たるよう、素の番号も検索語に残す。
      search: `${sessionNo(s.id)} ${s.id} ${s.unique_id} ${name} ${fmtYmd(s.started_at)}`.toLowerCase(),
      href: `/history?session=${s.id}`,
    });
  });
  // 視聴者。名前が分かっている人を引くのに /fans へ移動して検索boxへ打ち直す必要が
  // あった。名寄せ済みのidentity_keyで直接その明細を開く。
  (fans || []).forEach((f) => {
    items.push({
      kind: "fan",
      title: f.nickname || f.unique_id,
      sub: `@${f.unique_id} ・ コイン ${fmtNum(f.diamonds)} ・ 配信者 ${fmtNum(f.streamer_count)}人`,
      search: `${f.unique_id} ${f.nickname || ""}`.toLowerCase(),
      href: `/fans?fan=${encodeURIComponent(f.identity_key)}`,
    });
  });
  recordings.forEach((r) => {
    items.push({
      kind: "recording",
      title: r.filename,
      sub: `Session ${recTag(r)} ・ @${r.unique_id} ・ ${r.quality || "-"}`,
      search: `${r.filename} ${r.unique_id} ${recNo(r)} ${r.session_id}`.toLowerCase(),
      href: `/history?session=${r.session_id}`,
    });
  });
  return items;
}

// 空白区切りの語をすべて含むものだけを残す(語順に依存しない)。
function filterJumpItems(query) {
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const kinds = ["streamer", "fan", "session", "recording"];
  const rows = [];
  kinds.forEach((kind) => {
    const hit = (jumpItems || []).filter(
      (item) => item.kind === kind && terms.every((t) => item.search.includes(t)),
    );
    // 種類ごとに上限を設ける。件数の多い録画・Sessionだけで埋まると、配信者が
    // 一覧から押し出されて「無い」ように見えてしまう。
    rows.push(...hit.slice(0, JUMP_PER_KIND));
  });
  return rows;
}

function renderJumpList() {
  const { list, note } = jumpUI;
  list.innerHTML = "";
  if (jumpState === "loading") {
    note.textContent = "候補を読み込み中…";
    return;
  }
  if (jumpState === "failed") {
    note.textContent = "候補を取得できませんでした";
    note.title = errorDetailText(jumpError);
    return;
  }
  note.removeAttribute("title");
  jumpRows = filterJumpItems(jumpUI.input.value);
  // 絞込前に0件なのは候補そのものが無いときだけ。下の「検索対象」が0を名乗る。
  if (!jumpRows.length && jumpUI.input.value.trim()) {
    note.textContent = "一致なし";
    return;
  }
  if (jumpActive >= jumpRows.length) jumpActive = jumpRows.length - 1;
  jumpRows.forEach((item, i) => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "jump-row" + (i === jumpActive ? " active" : "");
    const kind = document.createElement("span");
    kind.className = `jump-kind k-${item.kind}`;
    kind.textContent = jumpKindLabel(item.kind);
    const text = document.createElement("span");
    text.className = "jump-text";
    const title = document.createElement("b");
    title.className = "jump-title";
    title.textContent = item.title;
    const sub = document.createElement("span");
    sub.className = "jump-sub";
    sub.textContent = item.sub;
    text.append(title, sub);
    row.append(kind, text);
    row.addEventListener("click", () => {
      location.href = item.href;
    });
    // mouseで指した行をEnterの対象と一致させる(keyboardとmouseで選択がずれない)。
    row.addEventListener("mousemove", () => {
      if (jumpActive === i) return;
      jumpActive = i;
      renderJumpList();
    });
    list.appendChild(row);
  });
  // 何件の中から探しているのかを出す。/api/recordings はserverの
  // session_list_limit で頭打ちになるため、録画の対象数は実件数とは限らない。
  const counts = ["streamer", "session", "recording"].map(
    (k) => `${jumpKindLabel(k)} ${fmtNum((jumpItems || []).filter((i) => i.kind === k).length)}`,
  );
  note.textContent = `検索対象: ${counts.join(" / ")}`;
}

function buildJumpUI() {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay jump-overlay hidden";
  const modal = document.createElement("div");
  modal.className = "modal jump-modal";
  const head = document.createElement("div");
  head.className = "modal-head";
  const title = document.createElement("h2");
  title.textContent = "横断jump";
  const close = document.createElement("button");
  close.className = "modal-close";
  close.textContent = "✕";
  close.setAttribute("aria-label", "閉じる");
  head.append(title, close);
  const input = document.createElement("input");
  input.type = "text";
  input.className = "jump-input";
  input.placeholder = "🔎 配信者 / Session / 録画";
  input.autocomplete = "off";
  const list = document.createElement("div");
  list.className = "jump-list";
  const note = document.createElement("div");
  note.className = "jump-note";
  modal.append(head, input, list, note);
  overlay.appendChild(modal);
  document.body.appendChild(overlay);

  close.addEventListener("click", closeJump);
  overlay.addEventListener("click", (ev) => {
    if (ev.target === overlay) closeJump();
  });
  input.addEventListener("input", () => {
    jumpActive = 0;
    renderJumpList();
  });
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      if (!jumpRows.length) return;
      ev.preventDefault();
      const step = ev.key === "ArrowDown" ? 1 : -1;
      jumpActive = (jumpActive + step + jumpRows.length) % jumpRows.length;
      renderJumpList();
      const active = jumpUI.list.querySelector(".jump-row.active");
      if (active) active.scrollIntoView({ block: "nearest" });
      return;
    }
    if (ev.key === "Enter") {
      const item = jumpRows[jumpActive];
      if (!item) return;
      ev.preventDefault();
      location.href = item.href;
      return;
    }
    if (ev.key === "Escape") {
      // 背後の画面のEscape handler(modalを閉じる等)まで届かせない。
      ev.stopPropagation();
      closeJump();
    }
  });
  jumpUI = { overlay, input, list, note };
}

async function loadJumpItems() {
  jumpState = "loading";
  renderJumpList();
  try {
    const [streamers, sessions, recordings, fans] = await Promise.all([
      apiSend("GET", "/api/streamers"),
      apiSend("GET", "/api/sessions?limit=0"),
      apiSend("GET", "/api/recordings"),
      // 視聴者は台帳が無い環境もあり得るので、ここだけ失敗を候補なしへ落とす
      // (他の3種のjumpまで巻き添えで死なせない)。
      apiSend("GET", "/api/fans").catch(() => ({ fans: [] })),
    ]);
    jumpItems = buildJumpItems(
      streamers.streamers || [],
      sessions.sessions || [],
      recordings.recordings || [],
      fans.fans || [],
    );
    jumpState = "loaded";
  } catch (err) {
    jumpState = "failed";
    jumpError = err;
  }
  renderJumpList();
}

function openJump() {
  if (!jumpUI) buildJumpUI();
  jumpUI.overlay.classList.remove("hidden");
  jumpUI.input.select();
  jumpUI.input.focus();
  jumpActive = 0;
  if (jumpState === "idle" || jumpState === "failed") loadJumpItems();
  else renderJumpList();
}

function closeJump() {
  if (jumpUI) jumpUI.overlay.classList.add("hidden");
}

// Ctrl+K は入力欄にfocusがあるときも効かせる。修飾key付きの組合せなので通常の打鍵とは
// 衝突せず、絞込欄を触っている最中こそ別の対象へ移りたいことが多い。videos.jsの再生
// shortcutは修飾key付きを自ら除外しているため、こちらと二重に発火することはない。
document.addEventListener("keydown", (ev) => {
  if (ev.key !== "k" && ev.key !== "K") return;
  if (!ev.ctrlKey && !ev.metaKey) return;
  if (ev.altKey || ev.shiftKey) return;
  ev.preventDefault();
  if (jumpUI && !jumpUI.overlay.classList.contains("hidden")) closeJump();
  else openJump();
});

// 入れ子scrollのlatch。外側(modal本文・画面全体)を転がしている最中にpointerが内側の
// scroller(表・card列)へ入ると、以降のwheelが内側へ配送されて外側が止まる。手が動いて
// いる間は最初に動かしたscrollerへ配送し続け、止まったら解除する。page固有のwheel処理
// (videos.jsの拡縮など)はpreventDefault済みなので手を出さない。
const SCROLL_LATCH_MS = 400;
const SCROLL_LINE_PX = 16;
let scrollLatchEl = null;
let scrollLatchAt = 0;

function wheelDeltaPx(ev) {
  const unit = ev.deltaMode === 1 ? SCROLL_LINE_PX : ev.deltaMode === 2 ? window.innerHeight : 1;
  return { x: ev.deltaX * unit, y: ev.deltaY * unit };
}

// 指定方向へまだ動ける余地があるか(どちらかの軸で余地があればtrue)。
function scrollRoom(el, dx, dy) {
  const spanY = el.scrollHeight - el.clientHeight;
  const spanX = el.scrollWidth - el.clientWidth;
  if (dy && spanY > 1 && (dy > 0 ? el.scrollTop < spanY - 1 : el.scrollTop > 1)) return true;
  if (dx && spanX > 1 && (dx > 0 ? el.scrollLeft < spanX - 1 : el.scrollLeft > 1)) return true;
  return false;
}

function scrollerUnder(node, dx, dy) {
  for (let el = node instanceof Element ? node : null; el; el = el.parentElement) {
    if (el === document.body || el === document.documentElement) break;
    const style = getComputedStyle(el);
    const movable =
      (dy && /auto|scroll|overlay/.test(style.overflowY) && scrollRoom(el, 0, dy)) ||
      (dx && /auto|scroll|overlay/.test(style.overflowX) && scrollRoom(el, dx, 0));
    if (movable) return el;
  }
  const root = document.scrollingElement || document.documentElement;
  return scrollRoom(root, dx, dy) ? root : null;
}

window.addEventListener("wheel", (ev) => {
  if (ev.defaultPrevented || ev.ctrlKey) return;
  const { x, y } = wheelDeltaPx(ev);
  if (!x && !y) return;
  const now = performance.now();
  const held =
    scrollLatchEl && scrollLatchEl.isConnected &&
    now - scrollLatchAt < SCROLL_LATCH_MS && scrollRoom(scrollLatchEl, x, y)
      ? scrollLatchEl
      : null;
  const under = scrollerUnder(ev.target, x, y);
  if (held && held !== under) {
    ev.preventDefault();
    held.scrollTop += y;
    held.scrollLeft += x;
    scrollLatchAt = now;
    return;
  }
  scrollLatchEl = held || under;
  scrollLatchAt = now;
}, { passive: false });

// ---- 共通UI: 押下の演出 ----
// 演出が担う仕事は3つだけに絞る。①押下と同時に返す ②結果の場所を指す ③効かなかった事も
// 返す。この3つに当てはまらない動きは、増えるのは見た目だけで読み取れる事は増えないので
// 置かない。動きを減らす設定では、線を飛ばさず結果だけを即座に置く(styleではなくここで
// 分岐するのは、線の生成そのものを止めたいため)。
function motionReduced() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

// ① 押下と同時に「受け付けた」を返す。処理の完了を待って返すと、待っている間は無反応と
// 区別が付かず、人はもう一度押す。
function ackPress(el) {
  if (!el) return;
  el.classList.remove("fx-ack");
  // classを外した直後に付け直すだけでは同じ再描画に畳まれ、2回目以降が走らない。
  void el.offsetWidth;
  el.classList.add("fx-ack");
  el.addEventListener("animationend", () => el.classList.remove("fx-ack"), { once: true });
}

// ② 押した場所から、結果が現れた場所へ線を1本飛ばす。増えた物を人が探し直さずに済むのが
// 目的なので、線は「どこへ行ったか」だけを示して即座に消える。着地してからonArriveを呼び、
// 印はその時に立てる(先に立てると、線が着く前に結果が出て因果が逆に見える)。
const FLY_MS = 220;

function flyTo(fromEl, target, onArrive) {
  const done = () => { if (onArrive) onArrive(); };
  if (!fromEl || !target || motionReduced()) { done(); return; }
  const from = fromEl.getBoundingClientRect();
  const to = target instanceof Element ? target.getBoundingClientRect() : null;
  if (!from.width && !from.height) { done(); return; }
  const x0 = from.left + from.width / 2;
  const y0 = from.top + from.height / 2;
  // 要素を渡された時はその中心へ。着地点を細かく指したい画面(timelineの位置・棚の1行)は
  // {x, y} を直接渡す。
  const x1 = to ? to.left + to.width / 2 : Number(target.x);
  const y1 = to ? to.top + to.height / 2 : Number(target.y);
  if (!Number.isFinite(x1) || !Number.isFinite(y1)) { done(); return; }
  const len = Math.hypot(x1 - x0, y1 - y0);
  const rot = `rotate(${Math.atan2(y1 - y0, x1 - x0)}rad)`;
  const line = document.createElement("div");
  line.className = "fx-fly";
  line.style.insetInlineStart = `${x0}px`;
  line.style.insetBlockStart = `${y0}px`;
  line.style.transform = rot;
  document.body.appendChild(line);
  const anim = line.animate(
    [
      { inlineSize: "0px", transform: rot },
      { inlineSize: `${len}px`, transform: rot, offset: 0.55 },
      { inlineSize: "0px", transform: `${rot} translateX(${len}px)` },
    ],
    { duration: FLY_MS, easing: "cubic-bezier(0.3,0,0.2,1)" },
  );
  const finish = () => { line.remove(); done(); };
  anim.finished.then(finish, finish);
}


// ③ 効かなかった事を返す。文言(toast)だけでは、押した物と返答が離れていて結び付かない。
// 押した物そのものを揺らして「これは効いていない」を押下点で返す。
function denyPress(el) {
  if (!el) return;
  el.classList.remove("fx-deny");
  void el.offsetWidth;
  el.classList.add("fx-deny");
  el.addEventListener("animationend", () => el.classList.remove("fx-deny"), { once: true });
}

// ---- 共通UI: paneのdrag分割 ----
// 触るのはCSS変数1本だけで、寸法は持たせない(固定幅を置くと、窓を狭めた時に片側が
// 潰れる)。比率は画面ごとにbindPrefと同じkeyへ残し、次に開いた時も同じ割り方で出す。
const SPLIT_MIN = 0.18;
const SPLIT_MAX = 0.82;
// 2度押しを「既定へ戻す」と読む間隔。
const SPLIT_DBL_MS = 400;

// varPrefix には列の変数の頭を渡す(例 "--vd-msplit")。両側の取り分をまとめて書くのは、
// 片側だけを書くと残った側の既定値(2.5fr など)がそのまま比の相手になり、55%のつもりが
// 55 : 2.5 になるため。100を分け合う2つの数にして、比を変数の中で閉じる。
function bindSplitter(container, bar, varPrefix, prefName, onDone) {
  if (!container || !bar) return;
  const apply = (ratio, save) => {
    const p = Math.min(SPLIT_MAX, Math.max(SPLIT_MIN, ratio));
    container.style.setProperty(`${varPrefix}-a`, `minmax(0, ${(p * 100).toFixed(1)}fr)`);
    container.style.setProperty(`${varPrefix}-b`, `minmax(0, ${((1 - p) * 100).toFixed(1)}fr)`);
    bar.setAttribute("aria-valuenow", String(Math.round(p * 100)));
    if (save) prefSet(prefName, p.toFixed(3));
    return p;
  };
  const saved = Number(prefGet(prefName));
  if (Number.isFinite(saved) && saved > 0) apply(saved, false);

  let dragging = false;
  let moved = false;
  const ratioAt = (clientX) => {
    const r = container.getBoundingClientRect();
    return r.width ? (clientX - r.left) / r.width : 0.5;
  };
  let lastDown = 0;
  bar.addEventListener("pointerdown", (ev) => {
    // 2度押しは既定へ戻す合図。**dblclickでは受け取れない** ―― 掴んだまま字を選ばせない
    // ための preventDefault が、pointerdown に続く mouse系のeventごと止めるので、この棒に
    // dblclick は最初から届いていなかった(tooltipだけが「ダブルクリックで半々」と
    // 名乗っていた)。押した間隔で自分で数える。
    if (ev.timeStamp - lastDown < SPLIT_DBL_MS) {
      lastDown = 0;
      dragging = false;
      bar.classList.remove("is-drag");
      ev.preventDefault();
      apply(0.5, true);
      if (onDone) onDone();
      return;
    }
    lastDown = ev.timeStamp;
    dragging = true;
    moved = false;
    // captureが取れない環境でもpointerupはbarへ届くので、取れなかった事は失敗にしない。
    try { bar.setPointerCapture(ev.pointerId); } catch (err) { /* noop */ }
    bar.classList.add("is-drag");
    ev.preventDefault();
  });
  bar.addEventListener("pointermove", (ev) => {
    if (!dragging) return;
    moved = true;
    apply(ratioAt(ev.clientX), false);
  });
  ["pointerup", "pointercancel"].forEach((type) => {
    bar.addEventListener(type, (ev) => {
      if (!dragging) return;
      dragging = false;
      bar.classList.remove("is-drag");
      // 動かしていない押下では書き換えない。押した位置と境目には棒の太さぶんのずれが
      // あるので、ただ押しただけで割り方が数px動き、2度押しの2回目が棒から外れる。
      if (!moved) return;
      apply(ratioAt(ev.clientX), true);
      if (onDone) onDone();
    });
  });
  // 掴む操作を持たない人にも同じ割り方ができるようにする。矢印は1押し2%、Homeで既定へ。
  bar.addEventListener("keydown", (ev) => {
    const now = Number(bar.getAttribute("aria-valuenow")) / 100 || 0.5;
    let next = null;
    if (ev.key === "ArrowLeft") next = now - 0.02;
    else if (ev.key === "ArrowRight") next = now + 0.02;
    else if (ev.key === "Home") next = 0.5;
    if (next === null) return;
    ev.preventDefault();
    apply(next, true);
    if (onDone) onDone();
  });
}

// 3つのpaneを2本の棒で割る。比は**左端からの位置2つ**で持つ ―― 取り分3つで持つと、
// 1本の棒を動かすたびに残り2つをどう配分するかが決まらず、触っていない側まで動く。
// 変数は -a/-b/-c の3本ともまとめて書く(理由は上の2分割と同じ)。
const SPLIT3_MIN = 0.12;

function bindSplitter3(container, bars, varPrefix, prefName, defaults, onDone) {
  if (!container || !bars || bars.length !== 2 || !bars[0] || !bars[1]) return;
  const base = defaults && defaults.length === 2 ? defaults : [0.34, 0.5];
  let pos = base.slice();
  const apply = (next, save) => {
    // 左の棒が先、右の棒が後。順が入れ替わらないよう、必ず左から詰める。
    const p1 = Math.min(1 - SPLIT3_MIN * 2, Math.max(SPLIT3_MIN, next[0]));
    const p2 = Math.min(1 - SPLIT3_MIN, Math.max(p1 + SPLIT3_MIN, next[1]));
    pos = [p1, p2];
    const share = [p1, p2 - p1, 1 - p2];
    ["a", "b", "c"].forEach((key, i) => {
      container.style.setProperty(
        `${varPrefix}-${key}`, `minmax(0, ${(share[i] * 100).toFixed(1)}fr)`);
    });
    bars[0].setAttribute("aria-valuenow", String(Math.round(p1 * 100)));
    bars[1].setAttribute("aria-valuenow", String(Math.round(p2 * 100)));
    if (save) prefSet(prefName, `${p1.toFixed(3)},${p2.toFixed(3)}`);
  };
  const saved = String(prefGet(prefName) || "").split(",").map(Number);
  if (saved.length === 2 && saved.every((v) => Number.isFinite(v) && v > 0)) {
    apply(saved, false);
  }

  const ratioAt = (clientX) => {
    const r = container.getBoundingClientRect();
    return r.width ? (clientX - r.left) / r.width : 0.5;
  };
  bars.forEach((bar, which) => {
    // 触っているのはこの1本だけ。もう1本の位置はそのまま持ち越す。
    const at = (ratio) => (which === 0 ? [ratio, pos[1]] : [pos[0], ratio]);
    let dragging = false;
    let moved = false;
    let lastDown = 0;
    bar.addEventListener("pointerdown", (ev) => {
      // 2度押しで3つとも既定へ。dblclickが届かない理由は2分割の方に書いた。
      if (ev.timeStamp - lastDown < SPLIT_DBL_MS) {
        lastDown = 0;
        dragging = false;
        bar.classList.remove("is-drag");
        ev.preventDefault();
        apply(base, true);
        if (onDone) onDone();
        return;
      }
      lastDown = ev.timeStamp;
      dragging = true;
      moved = false;
      try { bar.setPointerCapture(ev.pointerId); } catch (err) { /* noop */ }
      bar.classList.add("is-drag");
      ev.preventDefault();
    });
    bar.addEventListener("pointermove", (ev) => {
      if (!dragging) return;
      moved = true;
      apply(at(ratioAt(ev.clientX)), false);
    });
    ["pointerup", "pointercancel"].forEach((type) => {
      bar.addEventListener(type, (ev) => {
        if (!dragging) return;
        dragging = false;
        bar.classList.remove("is-drag");
        // 理由は2分割の方と同じ(ただ押しただけでは割り方を書き換えない)。
        if (!moved) return;
        apply(at(ratioAt(ev.clientX)), true);
        if (onDone) onDone();
      });
    });
    bar.addEventListener("keydown", (ev) => {
      const now = pos[which];
      let next = null;
      if (ev.key === "ArrowLeft") next = now - 0.02;
      else if (ev.key === "ArrowRight") next = now + 0.02;
      else if (ev.key === "Home") next = base[which];
      if (next === null) return;
      ev.preventDefault();
      apply(at(next), true);
      if (onDone) onDone();
    });
  });
}

// ---- 共通UI: Pod ----
// job中だけ降りてきて、終わったら報告して消える。常駐はさせない ―― 1日見る道具の上に
// 動く物を置き続けると、読む時に必ず視界へ入ってくる。報告の中身はjobの実際の段階名で、
// 出所を持たない台詞は言わせない。
const POD_LEAVE_MS = 2600;
let podEl = null;
let podLeaveTimer = 0;

function podLayer() {
  if (podEl && podEl.isConnected) return podEl;
  podEl = document.createElement("div");
  podEl.className = "pod";
  podEl.setAttribute("aria-hidden", "true");
  podEl.innerHTML = '<div class="pod-say"></div>'
    + '<svg class="pod-body" width="42" height="42" viewBox="0 0 46 46">'
    + '<circle cx="23" cy="23" r="13" fill="var(--sand-panel)" stroke="var(--ink-strong)" stroke-width="1.4" />'
    + '<circle cx="23" cy="23" r="5.2" fill="var(--invert-bg)" stroke="var(--ink-strong)" stroke-width="1" />'
    + '<circle class="pod-eye" cx="23" cy="23" r="2" fill="var(--accent-bright)" />'
    + '<path d="M10 23 L4 19 M10 23 L4 27" stroke="var(--ink-strong)" stroke-width="1.2" fill="none" />'
    + '<path d="M36 23 L42 19 M36 23 L42 27" stroke="var(--ink-strong)" stroke-width="1.2" fill="none" />'
    + '<rect x="19" y="37" width="8" height="2.4" fill="var(--ink-muted)" />'
    + "</svg>";
  document.body.appendChild(podEl);
  return podEl;
}

// text が空の時は「もう報告する事が無い」= 帰る合図。kind は "warn" で失敗を言う。
function podSay(text, kind) {
  const pod = podLayer();
  clearTimeout(podLeaveTimer);
  if (!text) {
    podLeaveTimer = setTimeout(() => { pod.classList.remove("is-in"); }, POD_LEAVE_MS);
    return;
  }
  pod.querySelector(".pod-say").textContent = text;
  pod.classList.toggle("pod-warn", kind === "warn");
  pod.classList.add("is-in");
}
