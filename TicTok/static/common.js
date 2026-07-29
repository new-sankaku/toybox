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
  ["/capacity", "動画容量"],
  ["/fans", "Fan台帳"],
  ["/analytics", "全体解析"],
  ["/jobs", "Job"],
  ["/ops", "運用log"],
  ["/settings", "設定"],
];

function renderNav() {
  const nav = document.querySelector("nav.a-nav");
  if (!nav) return;
  // 末尾の / は落とす("/history/" でも履歴を現在地と見なす)。
  const here = location.pathname.replace(/\/+$/, "") || "/";
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
  waiting: { badge: "WAITING", cls: "badge-waiting", message: "LIVE配信の開始を待っています…（開始を検出すると自動で収集を始めます）" },
  connecting: { badge: "CONNECTING", cls: "badge-connecting", message: "接続処理を実行中です…" },
  connected: { badge: "RECEIVING", cls: "badge-connected", message: "LIVEに接続済み。Eventを受信しています。" },
  reconnecting: { badge: "RECONNECTING", cls: "badge-reconnecting", message: "接続が不安定なため再接続しています…（収集Dataは保持されます）" },
  disconnected: { badge: "STOPPED", cls: "badge-idle", message: "収集を停止しました。" },
  ended: { badge: "LIVE ENDED", cls: "badge-ended", message: "LIVE配信が終了しました。" },
  error: { badge: "ERROR", cls: "badge-error", message: "Errorが発生しました。" },
  restricted: { badge: "録画不可", cls: "badge-restricted", message: "メンバー限定または年齢制限のため録画できません。通常配信の開始を監視継続中です。" },
};

function fmtTime(epochSeconds) {
  return new Date(epochSeconds * 1000).toLocaleTimeString("ja-JP", { hour12: false });
}

function fmtDateTime(epochSeconds) {
  if (!epochSeconds) return "-";
  return new Date(epochSeconds * 1000).toLocaleString("ja-JP", { hour12: false });
}

function fmtYmd(epochSeconds) {
  if (!epochSeconds) return "-";
  const d = new Date(epochSeconds * 1000);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}${m}${day}`;
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
  400: "Requestの内容が不正です。",
  401: "この操作には認証が必要です。",
  403: "この操作は許可されていません。",
  404: "対象が見つかりませんでした（Serverのcodeが古い可能性があります）。",
  405: "この操作をServerが受け付けていません。",
  409: "他の処理と競合したため実行できませんでした。",
  422: "入力値をServerが受け付けませんでした。",
  500: "Server内部でErrorが発生しました。",
  502: "外部からの取得に失敗しました。",
  503: "Serverが一時的に応答できません。",
  504: "Serverの応答が時間内に返りませんでした。",
};

function hasJapanese(text) {
  return /[぀-ヿ㐀-鿿！-ﾟ]/.test(text);
}

function httpError(status, detail) {
  const raw = typeof detail === "string" ? detail.trim() : "";
  const passthrough = raw && hasJapanese(raw);
  const message = passthrough
    ? raw
    : (HTTP_ERROR_TEXT[status] || `Serverが処理できませんでした（HTTP ${status}）。`);
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
    const err = new Error("Serverへ接続できませんでした。");
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

function connectWS(onMessage) {
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

const NIER_AXIS_COLOR = "#6f6a59";
const NIER_GRID_COLOR = "rgba(143, 136, 113, 0.3)";
const CHART_DISPLAY_LIMIT = 720;

function nierTooltip() {
  return {
    backgroundColor: "#4d4a3f",
    titleColor: "#d8d2bc",
    bodyColor: "#d8d2bc",
    titleFont: { family: "monospace" },
    bodyFont: { family: "monospace" },
  };
}

function nierTicks() {
  return { color: NIER_AXIS_COLOR, font: { family: "monospace", size: 10 }, precision: 0 };
}

// TIMELINE: 桁の違う4指標を1枚に重ねると小さい系列が潰れて読めない。指標ごとに
// 独立scaleの小型折れ線(small multiples)を縦に並べ、時間軸とLIVE Markerを共有する。
// aggはbucketを束ねる時の集計: countは合計、level(同接)はbucket内の最終値。
// zeroBase: countは0基準で塗りつぶし量を出す。levelの同接は0基準だと微増減が潰れる
// ため自動scale(min..max)で推移を見せる。
const TIMELINE_SERIES = [
  { key: "diamonds", label: "コイン", color: "#a96e49", fill: "rgba(169, 110, 73, 0.16)", agg: "sum", zeroBase: true },
  { key: "viewers", label: "同接", color: "#4d4a3f", fill: false, agg: "last", zeroBase: false },
  { key: "comments", label: "Comment", color: "#5d6e4e", fill: "rgba(93, 110, 78, 0.16)", agg: "sum", zeroBase: true },
  { key: "likes", label: "Like", color: "#9b8c52", fill: "rgba(155, 140, 82, 0.18)", agg: "sum", zeroBase: true },
];
// 配信が長くなると点が密集して読めなくなるため、表示点数に上限を設けて
// 超過時はbucketを束ねて間引く(stepSecondsは束ねた後の実効bucket幅)。
const TIMELINE_MAX_POINTS = 180;

// Timeline上のevent marker。backendのlabelは "Battle #<巨大ID>" 等で長く、密集すると
// 数字の羅列が重なって読めなくなるため、kindごとに短tag+色を割当てて表示する。
const MARKER_STYLES = {
  battle: { color: "#a4502f", short: "PK" },
  collab: { color: "#7a6a8e", short: "コラボ" },
  record: { color: "#5d6e4e", short: "REC" },
  connect: { color: "#4d4a3f", short: "接続" },
  reconnect: { color: "#9b8c52", short: "再接続" },
  disconnect: { color: "#8a4b4b", short: "切断" },
  disconnect_unplanned: { color: "#7a2f2f", short: "異常切断" },
  live_end: { color: "#8a4b4b", short: "終了" },
};
const MARKER_DEFAULT = { color: "#a4502f", short: "•" };

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
          ctx.fillStyle = "rgba(164, 80, 47, 0.12)";
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
        ctx.fillStyle = "#a4502f";
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
    return { key: s.key, agg: s.agg, chart, peak };
  });

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
    let first = raw[0].start;
    if ((last - first) / size + 1 > CHART_DISPLAY_LIMIT) {
      first = last - (CHART_DISPLAY_LIMIT - 1) * size;
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

    // 表示点数の上限を超えたらbucketを束ねて間引く。
    const n = starts.length;
    const group = Math.max(1, Math.ceil(n / TIMELINE_MAX_POINTS));
    stepSeconds = size * group;
    firstStart = first;
    const labels = [];
    const out = {};
    TIMELINE_SERIES.forEach((s) => { out[s.key] = []; });
    for (let i = 0; i < n; i += group) {
      const end = Math.min(i + group, n);
      labels.push(fmtTime(starts[i]));
      TIMELINE_SERIES.forEach((ser) => {
        if (ser.agg === "last") {
          out[ser.key].push(full[ser.key][end - 1]);
        } else {
          let sum = 0;
          for (let j = i; j < end; j++) sum += full[ser.key][j];
          out[ser.key].push(sum);
        }
      });
    }

    panels.forEach((p) => {
      const values = out[p.key];
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
function movingAverage(values, window) {
  const out = [];
  for (let i = 0; i < values.length; i++) {
    const start = Math.max(0, i - window + 1);
    let sum = 0;
    for (let j = start; j <= i; j++) sum += values[j];
    out.push(sum / (i - start + 1));
  }
  return out;
}

// opts.movingAvg: コインの移動平均線(左軸)を追加で重ねる(成長トレンド可視化)。既定off
// なので履歴ページ等の既存呼び出しには影響しない。opts.movingAvgWindow で窓幅(既定5)。
function createSessionTrendChart(canvas, opts = {}) {
  let rows = [];
  const datasets = [
    { label: "コイン", type: "bar", data: [], backgroundColor: "rgba(169, 110, 73, 0.55)", yAxisID: "y" },
    { label: "配信時間", type: "line", data: [], borderColor: "#8e4f2f", backgroundColor: "#8e4f2f", borderWidth: 2, pointRadius: 3, tension: 0.25, yAxisID: "y2" },
  ];
  if (opts.movingAvg) {
    datasets.push({ label: "コイン移動平均", type: "line", data: [], borderColor: "#5d6e4e", backgroundColor: "transparent", borderWidth: 2, borderDash: [5, 3], pointRadius: 0, tension: 0.3, yAxisID: "y" });
  }
  const chart = new Chart(canvas, {
    type: "bar",
    data: {
      labels: [],
      datasets,
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: { ticks: { ...nierTicks(), maxRotation: 0, autoSkip: true, maxTicksLimit: 24 }, grid: { color: NIER_GRID_COLOR } },
        y: { position: "left", beginAtZero: true, title: { display: true, text: "コイン", color: NIER_AXIS_COLOR, font: { family: "monospace", size: 10 } }, ticks: nierTicks(), grid: { color: NIER_GRID_COLOR } },
        y2: { position: "right", beginAtZero: true, title: { display: true, text: "配信時間(h)", color: NIER_AXIS_COLOR, font: { family: "monospace", size: 10 } }, ticks: nierTicks(), grid: { drawOnChartArea: false } },
      },
      plugins: {
        legend: { labels: { color: "#4d4a3f", font: { family: "monospace", size: 11 }, boxWidth: 14, boxHeight: 8 } },
        tooltip: {
          ...nierTooltip(),
          callbacks: {
            title: (items) => {
              const r = rows[items[0].dataIndex];
              return r ? `#${sessionNo(r.id)}  ${fmtDateTime(r.started_at)}` : "";
            },
            label: (item) => {
              if (item.dataset.label === "配信時間") {
                const r = rows[item.dataIndex];
                const dur = r && r.ended_at ? fmtDuration(r.ended_at - r.started_at) : "収集中";
                return `配信時間: ${dur}`;
              }
              return `${item.dataset.label}: ${fmtNum(item.parsed.y)}`;
            },
          },
        },
      },
    },
  });

  function update(sessionRows) {
    rows = sessionRows || [];
    const ymdSeen = {};
    chart.data.labels = rows.map((s) => {
      const ymd = fmtYmd(s.started_at);
      ymdSeen[ymd] = (ymdSeen[ymd] || 0) + 1;
      return ymdSeen[ymd] > 1 ? `${ymd}:${ymdSeen[ymd]}` : ymd;
    });
    const coins = rows.map((s) => (s.stats && s.stats.diamonds) || 0);
    chart.data.datasets[0].data = coins;
    chart.data.datasets[1].data = rows.map((s) => (s.ended_at ? (s.ended_at - s.started_at) / 3600 : 0));
    if (opts.movingAvg) {
      chart.data.datasets[2].data = movingAverage(coins, opts.movingAvgWindow || 5);
    }
    chart.update();
  }

  function clear() {
    rows = [];
    chart.data.labels = [];
    chart.data.datasets.forEach((ds) => { ds.data = []; });
    chart.update();
  }

  return { chart, update, clear };
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
      `PK確定時点（${fmtNum(battle.own_score || 0)} 対 ${fmtNum(battle.opp_score || 0)}）の判定です。`
      + ` TikTokから最後に届いたスコアは ${fmtNum(battle.own_score_reported || 0)} 対 `
      + `${fmtNum(battle.opp_score_reported || 0)}（${battleResultMeta(battle.result_reported).text}）ですが、`
      + `これはPK終了後に相手が枠から抜けた後の値です。`;
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
    return topo.teams.map((t) => ({ score: t.total, own: t.own, self: false }));
  }
  // 個人戦: 自分を先頭、相手はscore降順で安定配置(overlayのlane順と一致)。
  const own = topo.parts.filter((p) => p.is_own);
  const opp = topo.parts.filter((p) => !p.is_own).sort((a, b) => (b.score || 0) - (a.score || 0));
  return [...own, ...opp].map((p) => ({ score: p.score || 0, own: p.is_own, self: p.is_own }));
}

// 敵陣segmentの別色数(c1..cN)。これを超える陣営は循環で色を再利用する。動画焼き込みの
// _SCORE_LANE_PALETTE(先頭が自陣roseで、残りが敵陣色)と同じ本数にして割り当てを一致させる。
const SEG_OPP_COLORS = 5;

// Battle chartの自陣/敵陣線。バーの陣営色(rose/cyan)と同系だが、明地の上で線として
// 読める暗さのink側を使う(style.cssの--battle-own-ink/--battle-opp-inkと同値)。
const BATTLE_OWN_LINE = "#b3123f";
const BATTLE_OPP_LINE = "#0b6478";

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

// 貢献を host(宛先配信者) ごとに束ねる。host_idが空の自陣Giftは自陣hostへ寄せる。
// 全体監視tile・監視/履歴カードで同じグルーピングを共有する。
function groupContribsByHost(battle, topo) {
  const ownHostId = (topo.parts.find((p) => p.is_own) || {}).user_id;
  const byHost = new Map();
  (battle.contributions || []).forEach((c) => {
    let key = c.host_id;
    if (!key && c.side === "own") key = ownHostId;
    if (!key) key = c.side === "own" ? "__own__" : "__opp__";
    if (!byHost.has(key)) byHost.set(key, []);
    byHost.get(key).push(c);
  });
  return byHost;
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
function buildBattleHostContrib(host, byHost, owner) {
  const box = document.createElement("div");
  box.className = "bch-host " + (host.is_own ? "own" : "opp");
  const rows = (byHost.get(host.user_id) || []).slice().sort((a, b) => (b.diamonds || 0) - (a.diamonds || 0));
  const coinsSum = rows.reduce((a, c) => a + (c.diamonds || 0), 0);

  const head = document.createElement("div");
  head.className = "bch-host-head";
  const score = document.createElement("span");
  score.className = "bch-host-score";
  score.textContent = `BS ${fmtBs(host.score)} / 実弾 ${fmtBs(coinsSum)}`;
  const cnt = document.createElement("span");
  cnt.className = "bch-host-cnt";
  cnt.textContent = `貢献者${rows.length}人`;
  head.append(userCell(participantUser(host, owner), { hideId: true }), score, cnt);
  box.appendChild(head);

  if (!rows.length) {
    const empty = document.createElement("div");
    empty.className = "bc-empty";
    empty.textContent = "実弾Giftなし";
    box.appendChild(empty);
    return box;
  }
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
  box.appendChild(table);
  return box;
}

// 貢献を配信者(host)ごとに表示。個人戦は自陣→相手hostの順、チーム戦はチーム→host。
// 誰がどの配信者へ実弾を送ったかを、全体監視tileと同じ粒度で示す。
function buildBattleContrib(battle, owner) {
  const wrap = document.createElement("div");
  wrap.className = "bcontrib-hosts";
  const topo = battleTopology(battle, owner);
  const byHost = groupContribsByHost(battle, topo);
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
        .forEach((host) => teamBox.appendChild(buildBattleHostContrib(host, byHost, owner)));
      wrap.appendChild(teamBox);
    });
  } else {
    topo.parts
      .slice()
      .sort((a, b) => (a.is_own === b.is_own ? (b.score || 0) - (a.score || 0) : a.is_own ? -1 : 1))
      .forEach((host) => wrap.appendChild(buildBattleHostContrib(host, byHost, owner)));
  }
  return wrap;
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
        legend: { labels: { color: "#4d4a3f", font: { family: "monospace", size: 10 }, boxWidth: 12, boxHeight: 6 } },
        tooltip: { ...nierTooltip(), callbacks: { label: (ctx) => `${ctx.dataset.label}: ${fmtNum(ctx.parsed.y)}` } },
      },
    },
  });
  entry.chartWrap = wrap;
  return wrap;
}

// 倍率タイム(Match Bonus Mission)。Battle中にギフト倍率タイムが発生した場合のみ表示。
// 倍率・発動時間帯・達成可否・獲得ボーナス💎・後押しした貢献者を1ブロックに集約する。
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
  if (m.bonus_sum) row.appendChild(kv("獲得ボーナス", `+${fmtNum(m.bonus_sum)} 💎`));
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
  const topo = battleTopology(battle, owner);
  // 形式に応じてN分割したスコアバー(個人=参加者数, チーム=チーム数)。その下に
  // 形式別の内訳(チームbox/順位リスト/対戦表)を描く。
  body.appendChild(buildBattleScoreBar(topo));
  if (topo.kind === "team") {
    body.appendChild(buildBattleTeams(topo));
  } else if (topo.kind === "multi") {
    body.appendChild(buildBattleRanking(topo));
  } else {
    body.appendChild(buildBattleVs(owner, battle));
  }
  const chart = syncBattleScoreChart(entry, battle);
  if (chart) body.appendChild(chart);
  // 情報を一切持たない空mission(旧データの取りこぼしplaceholder)は描かない。
  (battle.bonus_missions || []).filter(isMeaningfulMission).forEach((m) => body.appendChild(buildBonusMission(m)));
  body.appendChild(buildBattleContrib(battle, owner));
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

function renderBattleCards(container, battles, owner) {
  let reg = battleCardRegistry.get(container);
  if (!reg) {
    reg = new Map();
    battleCardRegistry.set(container, reg);
  }
  const list = battles || [];
  const seen = new Set();
  list.forEach((b, i) => {
    const key = String(b.battle_id || `#${i}`);
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
    const key = String(b.battle_id || `#${i}`);
    container.appendChild(reg.get(key).card);
  });
}

// User単位のGift内訳: Gift種ごとに改行し、個数とコイン数を併記する。
function giftItemsNode(items) {
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
    n.textContent = name;
    const count = document.createElement("span");
    count.className = "gi-count";
    count.textContent = `×${fmtNum(info.count)}`;
    const coin = document.createElement("span");
    coin.className = "gi-coin";
    coin.textContent = `コイン ${fmtNum(info.diamonds)}`;
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

function avatarChar(user) {
  const base = (user && (user.nickname || user.unique_id)) || "?";
  return base.trim().charAt(0).toUpperCase() || "?";
}

// TikTok CDN avatars hotlink/Referer-block direct browser loads and their signed
// URLs expire, so route them through the same-origin server proxy. Pass through
// data: URLs and already-proxied URLs untouched.
function avatarSrc(url, id) {
  if (!url || /^(data:|\/api\/avatar\?)/.test(url)) return url;
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
  const url = user && user.avatar;
  if (url) {
    const img = document.createElement("img");
    img.src = avatarSrc(url, user && user.unique_id);
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

function userCell(user, opts = {}) {
  // href付きならlinkにする。名前が出ている場所からその人の画面へ直接飛べないと、
  // nav→検索box→入力→行clickの遠回りになる(Fan台帳と配信者画面が実際そうだった)。
  const wrap = document.createElement(opts.href ? "a" : "span");
  if (opts.href) {
    wrap.href = opts.href;
    if (opts.linkTitle) wrap.title = opts.linkTitle;
  }
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
  const badges = userBadges(user);
  if (badges) wrap.appendChild(badges);
  return wrap;
}

// 表の操作列に入りきらないButtonをまとめるoverflow menu。
// 表は.table-wrap(overflow:auto)の中にあるため、absoluteのmenuはscroll枠でclipされる。
// position:fixedでviewport基準に出し、開いた時のButton位置から座標を決める。
let openRowMenu = null;

function closeRowMenu() {
  if (!openRowMenu) return;
  openRowMenu.remove();
  openRowMenu = null;
}

document.addEventListener("click", (ev) => {
  if (openRowMenu && !openRowMenu.contains(ev.target) && !ev.target.closest(".row-menu-toggle")) {
    closeRowMenu();
  }
});
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") closeRowMenu();
});
window.addEventListener("resize", closeRowMenu);
document.addEventListener("scroll", closeRowMenu, true);

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
  document.body.appendChild(menu);
  const rect = anchor.getBoundingClientRect();
  const size = menu.getBoundingClientRect();
  const left = Math.max(4, Math.min(rect.right - size.width, window.innerWidth - size.width - 4));
  const below = rect.bottom + 2;
  const top = below + size.height > window.innerHeight ? Math.max(4, rect.top - size.height - 2) : below;
  menu.style.left = `${left}px`;
  menu.style.top = `${top}px`;
  openRowMenu = menu;
  return menu;
}

function rowMenu(items, opts) {
  const options = opts || {};
  const toggle = document.createElement("button");
  toggle.className = "btn btn-small row-menu-toggle";
  toggle.textContent = options.label || "その他 ⋯";
  toggle.title = options.title || "その他の操作";
  toggle.addEventListener("click", () => {
    const wasOpenFor = openRowMenu && openRowMenu.dataset.owner === String(toggle.dataset.menuId);
    closeRowMenu();
    if (wasOpenFor) return;
    toggle.dataset.menuId = String(Date.now()) + String(Math.random());
    openMenuAt(toggle, items);
  });
  return toggle;
}

// onRow(tr, row, index) は任意。行に属性やevent(行dblclick等)を付ける用途で呼ぶ。
function renderTableRows(tbodyId, emptyId, rows, toCells, numericCols, onRow) {
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
  rows.forEach((row, i) => {
    const tr = document.createElement("tr");
    if (i === 0) tr.className = "rank-top";
    toCells(row, i + 1).forEach((cell, col) => {
      const td = document.createElement("td");
      if (numeric.has(col)) td.className = "num";
      if (cell instanceof Node) td.appendChild(cell);
      else td.textContent = cell;
      tr.appendChild(td);
    });
    if (onRow) onRow(tr, row, i);
    fragment.appendChild(tr);
  });
  tbody.appendChild(fragment);
}

// KPIの帯(a-kpibar)へlabel/値のchipを並べる。fans/streamers/videosが同じ物を持って
// いたのでここへ集約した。
function chipBar(containerId, chips) {
  const bar = document.getElementById(containerId);
  bar.innerHTML = "";
  chips.forEach(([label, value, cls]) => {
    const chip = document.createElement("div");
    chip.className = "a-chip";
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
    el.textContent =
      `${el.dataset.label || "Data"}を取得できませんでした（0件という意味ではありません）。`;
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
const VIDEO_MISSING_TEXT =
  "この録画は素材(.ts)もmp4も残っていません。文字起こし・検索・bookmarkは引き続き使えます。";
const VIDEO_ERROR_TEXT = "この録画を再生できませんでした。";

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

function renderDiskBar(container, data) {
  container.innerHTML = "";
  const volumes = (data && data.volumes) || {};
  const low = new Set((data && data.low_volumes) || []);
  const names = Object.keys(volumes).sort();
  if (!names.length) {
    const empty = document.createElement("span");
    empty.className = "d-empty";
    empty.textContent = "空き容量: 不明";
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
      + (Number(data.min_free_bytes) > 0 ? `\n出力を拒否する下限 ${floorGb}GB` : "")
      + "\nclickで容量の内訳と整理へ";
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

function showDiskUnavailable(container) {
  container.innerHTML = "";
  const err = document.createElement("span");
  err.className = "d-empty";
  err.textContent = "空き容量: 取得失敗";
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
  setInterval(loadDiskBar, DISK_POLL_MS);
}

// ---- 運用logのerror badge(全画面共通のnav) ----
// 直近の窓(serverの設定が唯一の出所)にerrorが何件あるかをnavの「運用log」へ添える。
// 照会に失敗したときは0件ではなく「?」を出す。取得できていないことを0件として描くと、
// 「何も壊れていない」という嘘の表示になる。
const OPS_BADGE_POLL_MS = 60000;

function opsBadgeElement() {
  const link = document.querySelector('.a-nav a[href="/ops"]');
  if (!link) return null;
  let badge = link.querySelector(".nav-badge");
  if (!badge) {
    badge = document.createElement("span");
    badge.className = "nav-badge";
    link.appendChild(badge);
  }
  return badge;
}

async function loadOpsBadge() {
  const badge = opsBadgeElement();
  if (!badge) return;
  let data;
  try {
    const res = await fetch("/api/ops/summary");
    if (!res.ok) throw new Error(String(res.status));
    data = await res.json();
  } catch (e) {
    badge.textContent = "?";
    badge.className = "nav-badge unknown";
    badge.title = "運用logの件数を取得できませんでした（0件という意味ではありません）。";
    return;
  }
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

if (document.querySelector('.a-nav a[href="/ops"]')) {
  loadOpsBadge();
  setInterval(loadOpsBadge, OPS_BADGE_POLL_MS);
}

// ---- 共通UI: 通知toast ----
// window.alertはpageのscript実行ごと止めるため、WSで届く録画状態やjob進捗が、
// 誰かが「OK」を押すまで反映されない。監視画面を開いたまま席を外す使い方をするので、
// 通知は画面内へ出して処理は止めない。
// 情報表示は自動で消すが、errorは消さない。監視画面を開いたまま席を外す使い方なので、
// 録画・出力の失敗が自動消滅すると、戻ってきたときに失敗した事実そのものが残らない。
// 閉じる操作を挟むことで「見た」がユーザーの明示になる(alertの確認強制の代わり)。
const TOAST_MS = 6000;

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

// kindは "error"(失敗の報告) と既定の情報表示。errorは自動で消さず、閉じるまで残す。
function showToast(message, kind) {
  const text = String(message === undefined || message === null ? "" : message).trim();
  if (!text) return null;
  // errorは閉じるまで残るので、同じ失敗が繰り返されると画面が埋まる(録画の再試行や
  // job失敗は同一文面で連続する)。同じ文面は増やさず回数だけ更新する。
  if (kind === "error") {
    const existing = [...toastLayer().querySelectorAll(".toast-error")].find(
      (el) => el.dataset.toastText === text,
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
  toast.dataset.toastText = text;
  const body = document.createElement("span");
  body.className = "toast-body";
  body.textContent = text;
  const count = document.createElement("span");
  count.className = "toast-count";
  const close = document.createElement("button");
  close.className = "toast-close";
  close.textContent = "✕";
  close.title = "この通知を閉じる";
  const dismiss = () => {
    if (toast.isConnected) toast.remove();
  };
  close.addEventListener("click", dismiss);
  toast.append(body, count, close);
  toastLayer().appendChild(toast);
  if (kind !== "error") setTimeout(dismiss, TOAST_MS);
  return toast;
}

function showError(err) {
  showToast(err && err.message ? err.message : String(err), "error");
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
  badge.title = rec.protected
    ? "保持policyの自動削除から除外されています。押すと解除します。"
    : "押すと保持policyの自動削除から除外します。手動の削除は保護中でも実行できます。";
  badge.addEventListener("click", async () => {
    badge.disabled = true;
    try {
      await apiSend("POST", `/api/recordings/${rec.id}/protect`, { protected: !rec.protected });
      if (onDone) onDone();
    } catch (err) {
      badge.disabled = false;
      showError(err);
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
    showToast(`録画 ${recName(rec)} の派生物 ${fmtBytes(res.freed_bytes)} を削除しました。`);
    if (onDone) onDone();
  } catch (err) {
    showError(err);
  }
}

// ---- 共通UI: 確認dialog ----
// 取り消せない操作の前に確認を取る。window.confirmと違い、何を消すのかを複数行で読ませ、
// 破壊的な操作は実行Buttonを危険色にできる。
// 返り値はPromise<boolean>で、Escape・背景click・取消はいずれもfalse。
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
    cancel.textContent = options.cancelLabel || "取消";
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

// ---- 共通UI: 進捗bar ----
// spinner付きは「今この画面から起動して待っている」操作向け、spinner無しは一覧に並ぶ
// 他所で動いているjobの状態表示向け。
function makeProgress(opts) {
  const options = opts || {};
  const prog = document.createElement("span");
  prog.className = "dl-progress";
  if (options.spinner !== false) {
    const spinner = document.createElement("span");
    spinner.className = "spinner dl-spinner";
    const core = document.createElement("span");
    core.className = "spinner-core";
    spinner.appendChild(core);
    prog.appendChild(spinner);
  }
  // 段階名(詳細つきで長い)と%は別の要素にする。1要素に混ぜると、段階名の長さで%まで
  // 押し出されるか、cellが横に伸びてtable全体が崩れる。段階名だけを縮める。
  const stage = document.createElement("span");
  stage.className = "dl-stage";
  stage.textContent = options.label || "準備中…";
  const bar = document.createElement("span");
  bar.className = "dl-bar";
  const fill = document.createElement("span");
  fill.className = "dl-bar-fill";
  bar.appendChild(fill);
  const text = document.createElement("span");
  text.className = "dl-pct";
  prog.append(stage, bar, text);
  return prog;
}

function setProgress(prog, label, pct) {
  const value = Math.max(0, Math.min(100, Math.round(Number(pct) || 0)));
  prog.querySelector(".dl-bar-fill").style.inlineSize = `${value}%`;
  prog.querySelector(".dl-stage").textContent = label;
  prog.querySelector(".dl-pct").textContent = `${value}%`;
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
  if (job.state === "pending") {
    prog.querySelector(".dl-bar-fill").style.inlineSize = "0%";
    // 順番が分かる時は必ず出す。「待機中」だけでは、次に始まるのか3時間jobの後ろに
    // 並んだのかが区別できない。
    const position = Number(job.queue_position) || 0;
    prog.querySelector(".dl-stage").textContent =
      position > 0 ? `待機中（${position}番目）` : "待機中";
    prog.querySelector(".dl-pct").textContent = "";
    prog.title = position > 1
      ? `順番待ちです。前に${position - 1}件あります。終わり次第、自動で始まります。`
      : "順番待ちです。前のjobが終わり次第、自動で始まります。";
    return;
  }
  setProgress(prog, job.stage || "準備中", job.pct);
  const eta = jobEtaText(job);
  if (eta) prog.querySelector(".dl-pct").textContent += `・${eta}`;
  // 段階名は詳細(frame数・encode位置)まで含めると長い。省略表示になっても全文が
  // 読めるよう、tooltipには必ず全文を入れる。
  prog.title = `${job.stage || "準備中"} ${prog.querySelector(".dl-pct").textContent}`;
}

function finishProgress(prog, text) {
  const spinner = prog.querySelector(".dl-spinner");
  if (spinner) spinner.remove();
  prog.querySelector(".dl-bar-fill").style.inlineSize = "100%";
  prog.querySelector(".dl-stage").textContent = "";
  prog.querySelector(".dl-pct").textContent = text || "完了 ✓";
  prog.title = "";
  prog.classList.add("done");
}

// ---- job状況(全画面共通のトップバー) ----
// job台帳のsnapshot(jobs)と更新(job_update)は全pageのWSへ届いているのに、Job画面以外は
// 捨てていた。出力が動いているか・失敗が残っているかはどの画面からでも見えるべきなので、
// トップバーへ集約する。数はWSが唯一の出所で、届く前は何も出さない(0件と描かない)。
const JOB_BAR_FAILED_STATES = ["failed", "interrupted"];
let jobBarState = null;

// session一括投入はgroupの合成行と録画ごとの明細行の両方が流れてくる。合成行はjob_idに
// group_idがそのまま入るので、それ以外のgroup付き行(=明細)を数えると二重に数える。
function jobBarCountable(job) {
  const groupId = job.group_id || "";
  return !groupId || groupId === job.job_id;
}

function jobBarElement() {
  const topbar = document.querySelector(".a-topbar");
  if (!topbar) return null;
  let el = document.getElementById("job-bar");
  if (!el) {
    el = document.createElement("a");
    el.id = "job-bar";
    el.className = "a-jobs";
    el.href = "/jobs";
    const disk = document.getElementById("disk-bar");
    topbar.insertBefore(el, disk || null);
  }
  return el;
}

function renderJobBar() {
  const el = jobBarElement();
  if (!el || !jobBarState) return;
  const rows = [...jobBarState.values()].filter(jobBarCountable);
  const running = rows.filter((job) => job.state === "running").length;
  const pending = rows.filter((job) => job.state === "pending").length;
  const failed = rows.filter((job) => JOB_BAR_FAILED_STATES.includes(job.state)).length;
  el.replaceChildren();
  if (!running && !pending && !failed) {
    el.removeAttribute("title");
    return;
  }
  const active = document.createElement("span");
  active.className = "j-active";
  active.textContent = `job: 実行中 ${running} / 待機中 ${pending}`;
  el.appendChild(active);
  if (failed) {
    const bad = document.createElement("span");
    bad.className = "j-failed";
    bad.textContent = `失敗 ${failed}`;
    el.appendChild(bad);
  }
  el.title = failed
    ? `直近のjob履歴に失敗・中断が${failed}件あります。Job画面の「失敗・中断のみ」で確認できます。`
    : "焼き込み・Up出力などのjobの実行状況です。押すとJob画面へ移動します。";
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
    note.textContent = "候補を取得できませんでした（0件という意味ではありません）。";
    note.title = errorDetailText(jumpError);
    return;
  }
  note.removeAttribute("title");
  jumpRows = filterJumpItems(jumpUI.input.value);
  if (!jumpRows.length) {
    note.textContent = jumpUI.input.value.trim()
      ? "一致する配信者・Session・録画がありません。"
      : "配信者名・Session番号・録画file名で絞り込めます。";
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
  close.textContent = "閉じる ✕";
  head.append(title, close);
  const input = document.createElement("input");
  input.type = "text";
  input.className = "jump-input";
  input.placeholder = "🔎 配信者 / Session / 録画 を横断で絞込";
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
