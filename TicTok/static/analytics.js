"use strict";

// 全体解析(配信者横断)。既存DBの再集約APIを描画する読み取り専用ページ。
// 統計方針: 中央値・Spearman順位相関・レート正規化で一時的なノイズに左右されない。

const METRIC_LABELS = {
  joins: "入室",
  comments: "Comment",
  diamonds: "コイン",
  likes: "Like",
  follows: "Follow",
  viewers: "同接",
};

let battleChart = null;
let shareChart = null;
let gloveChart = null;
let organicChartWd = null;
let organicChartHe = null;
let qualityChart = null;
let retentionHourChart = null;
let contextChart = null;
let dwellHourChart = null;
let activationChart = null;
const lorenzCharts = {};

// 直前の応答。見せ方だけを変えるcontrol(①の数値表示・空行表示)が再取得せずに
// 描き直すために保持する。
let lastTimeIndex = null;

const elPeriod = document.getElementById("an-period");
const elTiMetric = document.getElementById("an-ti-metric");
const elTiNumbers = document.getElementById("an-ti-numbers");
const elTiEmpty = document.getElementById("an-ti-empty");

const PERIOD_KEY = "tictok.analytics.days";
const TI_NUMBERS_KEY = "tictok.analytics.timeIndexNumbers";
const TI_EMPTY_KEY = "tictok.analytics.timeIndexEmptyRows";

// x値(value軸)へ縦の基準線を引く共有plugin。時間帯index/Battle影響の「1.0」を明示。
const vLinePlugin = {
  id: "vline",
  afterDraw(chart, _args, opts) {
    if (!opts || opts.value == null) return;
    const xScale = chart.scales.x;
    if (!xScale) return;
    const px = xScale.getPixelForValue(opts.value);
    const { top, bottom } = chart.chartArea;
    const ctx = chart.ctx;
    ctx.save();
    ctx.strokeStyle = opts.color || "#8a4b4b";
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 3]);
    ctx.beginPath();
    ctx.moveTo(px, top);
    ctx.lineTo(px, bottom);
    ctx.stroke();
    ctx.restore();
  },
};

// 縦軸(Y/右Y)タイトルを日本語で正立させた縦書きで描画するplugin。
// Chart.js標準はタイトル全体を90°回転させ文字が横倒しになり読みにくいため、
// 標準タイトルは場所確保のみ(色を透明)に残し、本pluginで文字を上→下へ正立して積む。
const vAxisTitlePlugin = {
  id: "vaxistitle",
  afterDraw(chart) {
    const ctx = chart.ctx;
    Object.values(chart.scales).forEach((scale) => {
      if (scale.isHorizontal()) return;
      const t = scale.options.title;
      if (!t || !t.display || !t.text) return;
      const chars = [...String(t.text)];
      const size = (t.font && t.font.size) || 10;
      const family = (t.font && t.font.family) || "monospace";
      const lineH = size + 1;
      const totalH = chars.length * lineH;
      const band = size * 1.2 + 2 * (typeof t.padding === "number" ? t.padding : 0) + 4;
      const cx = scale.position === "right" ? scale.right - band / 2 : scale.left + band / 2;
      let y = (scale.top + scale.bottom) / 2 - totalH / 2 + lineH / 2;
      ctx.save();
      ctx.font = `${size}px ${family}`;
      ctx.fillStyle = NIER_AXIS_COLOR;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      for (const ch of chars) {
        ctx.fillText(ch, cx, y);
        y += lineH;
      }
      ctx.restore();
    });
  },
};
Chart.register(vAxisTitlePlugin);

// 縦軸タイトルは標準の横倒し描画を透明で隠して場所だけ確保し、vAxisTitlePluginで正立描画する。
function vAxisTitle(text) {
  return { display: true, text, color: "rgba(0,0,0,0)", font: { family: "monospace", size: 10 }, padding: 4 };
}

async function fetchJSON(path, signal) {
  const res = await fetch(path, signal ? { signal } : undefined);
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

function periodDays() {
  return Number(elPeriod.value || 0);
}

// 1つの描画が失敗しても他を巻き込まないよう個別に囲う。
function safeRender(label, fn, data) {
  try {
    if (data) fn(data);
  } catch (err) {
    console.error(`render ${label} failed`, err);
  }
}

// 注記は「1行の結論」と「統計の作法・但し書き」に分けて置く。作法まで常時表示すると
// 17section合計で約3,900字が図と図の間に挟まり、次の図まで届かなくなる。文章は消さず
// 同じsectionの折りたたみ(<noteId>-more)へ移し、結論だけを図の直下に残す。
function setNote(noteId, line, detail) {
  const el = document.getElementById(noteId);
  if (el) el.innerHTML = line;
  const more = document.getElementById(`${noteId}-more`);
  if (!more) return;
  const body = more.querySelector(".an-help-body");
  if (body) body.innerHTML = detail || "";
  more.hidden = !detail;
  if (!detail) more.open = false;
}

// 表の描画。数値列は header と値の両方へ .num を付ける(片側だけだと項目と値が縦に
// 揃わない)。numericColsを唯一の根拠にする点は common.js の renderTableRows と同じ
// 契約だが、この画面のcellはlinkや色付きspanのHTMLを含み、先頭行へ rank-top が
// 付くと「1位」の意味が乗ってしまうため、ここでは自前で組む。
function anTable(tableId, headers, rows, numericCols, emptyText) {
  const table = document.getElementById(tableId);
  if (!table) return;
  const numeric = new Set(numericCols || []);
  const head = headers
    .map((h, i) => `<th${numeric.has(i) ? ' class="num"' : ""}>${anEscape(h)}</th>`)
    .join("");
  let html = `<thead><tr>${head}</tr></thead><tbody>`;
  if (!rows.length) {
    html += `<tr><td colspan="${headers.length}" class="an-muted">${anEscape(emptyText)}</td></tr>`;
  }
  rows.forEach((cells) => {
    html += "<tr>"
      + cells.map((c, i) => {
        const cell = typeof c === "object" && c !== null ? c : { html: c };
        // 先頭列は行の見出し。tbodyへ<th>を置くと.result-table thのsticky反転色が
        // 当たって黒帯になるため、classだけで見出しらしさを持たせる。
        const cls = [numeric.has(i) ? "num" : "", i === 0 && !numeric.has(i) ? "an-rowhead" : "", cell.cls || ""]
          .filter(Boolean).join(" ");
        return `<td${cls ? ` class="${cls}"` : ""}${cell.title ? ` title="${anEscape(cell.title)}"` : ""}>${cell.html}</td>`;
      }).join("")
      + "</tr>";
  });
  table.innerHTML = `${html}</tbody>`;
}

// ---- 母集団サマリ ----
function renderSummary(s) {
  const el = document.getElementById("an-summary");
  const hours = Math.round((s.active_seconds || 0) / 3600);
  const range = s.first_at && s.last_at ? `${fmtYmd(s.first_at)}〜${fmtYmd(s.last_at)}` : "-";
  const cells = [
    ["配信者", fmtNum(s.streamers)],
    ["配信数", fmtNum(s.sessions)],
    ["集計bucket", fmtCompact(s.buckets)],
    ["総配信時間", `${fmtNum(hours)}h`],
    ["総入室", fmtCompact(s.joins)],
    ["期間", range],
  ];
  el.innerHTML = cells
    .map(([l, v]) => `<div class="a-chip"><span class="l">${l}</span><span class="v">${v}</span></div>`)
    .join("");
}

// ---- ① 時間帯インデックス(数値付きheatmap: 縦=20分slot × 横=曜日) ----
// 色で熱い時間帯を俯瞰し、各マスに実数(倍率)を書いて詳細も同時に読ませる。
// 曜日は月始まりで表示。src=backendのdow配列index(0=日..6=土)。土=青/日=赤はJP暦慣習。
const TI_DOW = [
  { src: 1, label: "月" },
  { src: 2, label: "火" },
  { src: 3, label: "水" },
  { src: 4, label: "木" },
  { src: 5, label: "金" },
  { src: 6, label: "土", head: "#3f6aa0" },
  { src: 0, label: "日", head: "#b0453f" },
];

// 発散配色: 倍率をlog2で対数対称に見て 0.5x(寒)〜1.0x(中間)〜2.0x(暖) へmap。
// 比率dataなので0.5と2.0が1.0から等距離になる対数軸が正しい。
const TI_COLD = [111, 147, 168]; // 平均未満(steel blue)
const TI_MID = [233, 227, 207]; // 平均近傍(pale parchment)
const TI_HOT = [184, 90, 47]; // 平均超(rust)
function tiColor(ratio) {
  const t = (Math.max(-1, Math.min(1, Math.log2(ratio))) + 1) / 2; // 0..1
  const [a, b, u] = t < 0.5 ? [TI_COLD, TI_MID, t / 0.5] : [TI_MID, TI_HOT, (t - 0.5) / 0.5];
  const c = a.map((v, i) => Math.round(v + (b[i] - v) * u));
  // 相対輝度で文字色を切替え、どのマスでも数値が読めるようにする。
  const lum = (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) / 255;
  return { bg: `rgb(${c[0]}, ${c[1]}, ${c[2]})`, fg: lum < 0.5 ? "#f0ead6" : "#2f2b22" };
}

// 20分slot(0..71)を "HH:MM" へ。
function tiSlotLabel(minute) {
  const h = Math.floor(minute / 60);
  const m = minute % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

// 648マス全部に小数2桁を書くと、数字が色の濃淡を覆って「どの帯が熱いか」が読めなく
// なる。既定は色とtooltipだけにし、数値はcheckboxで任意に出す。
function tiCellHTML(cell, dowLabel, hhmm, showNumber) {
  if (!cell || cell.index == null || cell.n <= 0) {
    return `<div class="an-hm-cell an-hm-empty" title="${dowLabel} ${hhmm} データなし"></div>`;
  }
  const { bg, fg } = tiColor(cell.index);
  const title = `${dowLabel} ${hhmm} ×${cell.index.toFixed(2)} (観測${cell.n}本=配信×日)`;
  const text = showNumber ? cell.index.toFixed(2) : "";
  return `<div class="an-hm-cell" style="background:${bg};color:${fg}" title="${title}">${text}</div>`;
}

// 観測が1マスも無い行(深夜帯が延々と続く)は既定で畳む。空行を並べても読む物が無く、
// 実データのある帯が画面外へ押し出されるだけなので、件数だけ注記に出して隠す。
function tiSlotHasData(slot) {
  const cells = TI_DOW.map((d) => slot.dow && slot.dow[d.src]).concat([slot.all]);
  return cells.some((c) => c && c.index != null && c.n > 0);
}

function renderTimeIndex(data) {
  // 数値表示・空行表示のcheckboxは見せ方だけを変える。再取得せず直前の応答から描き直す。
  lastTimeIndex = data;
  const slotsData = data.slots || [];
  // 見出しも指標に追従させる。heatmapが1画面ぶんの高さなので、scrollすると下の注記行が
  // 視界から外れ、見出しだけが残って別の指標の図として読まれる。
  const metricLabel = METRIC_LABELS[data.metric] || data.metric;
  document.getElementById("an-ti-title-metric").textContent = metricLabel;

  const emptyMsg = document.getElementById("an-ti-emptymsg");
  const heatmap = document.getElementById("an-ti-heatmap");
  // 集計が空のときheaderの1行だけが残ると、集計に失敗したように見える。他sectionと
  // 同じ「まだありません」を出して、heatmapそのものを消す。
  if (!slotsData.length) {
    if (emptyMsg) emptyMsg.hidden = false;
    heatmap.innerHTML = "";
    setNote("an-ti-note", `指標: <b>${metricLabel}</b>`);
    return;
  }
  if (emptyMsg) emptyMsg.hidden = true;

  const showNumber = !!(elTiNumbers && elTiNumbers.checked);
  const showEmptyRows = !!(elTiEmpty && elTiEmpty.checked);
  const visible = showEmptyRows ? slotsData : slotsData.filter(tiSlotHasData);
  const hiddenRows = slotsData.length - visible.length;

  setNote("an-ti-note",
    `指標: <b>${metricLabel}</b> ／ 20分×曜日、各配信の平均を1.0とした倍率`
    + ` &nbsp;観測 ${fmtNum(data.n_observations)}件 / 配信 ${fmtNum(data.n_sessions)}本`
    + (hiddenRows ? ` &nbsp;<span class="an-muted">観測のない ${fmtNum(hiddenRows)}行は非表示</span>` : "")
    + ` &nbsp;<span class="an-hm-legend"><i>平均より少ない</i>`
    + `<span class="an-hm-bar"></span><i>多い</i>&nbsp;(中間=平均1.0)</span>`);

  const head = ['<div class="an-hm-rowh an-hm-corner">時刻</div>']
    .concat(TI_DOW.map((d) => `<div class="an-hm-h"${d.head ? ` style="color:${d.head}"` : ""}>${d.label}</div>`))
    .concat('<div class="an-hm-h an-hm-all">全部</div>')
    .join("");
  const body = visible
    .map((s) => {
      const hhmm = tiSlotLabel(s.minute);
      // 毎時(00分)の行だけ罫線で区切り、20分刻みを俯瞰しやすくする。
      const hourStart = s.minute % 60 === 0;
      const rh = hourStart ? "an-hm-rowh an-hm-hour" : "an-hm-rowh an-hm-quarter";
      const cells = TI_DOW.map((d) => tiCellHTML(s.dow && s.dow[d.src], d.label, hhmm, showNumber)).join("");
      const all = tiCellHTML(s.all, "全曜日", hhmm, showNumber).replace("an-hm-cell", "an-hm-cell an-hm-all");
      return `<div class="${rh}">${hhmm}</div>${cells}${all}`;
    })
    .join("");
  heatmap.innerHTML = head + body;
}

// ---- ② 入室のコンテキスト別(Battle/コラボ/平時) ----
function renderJoinContext(data) {
  const b = data.battle || { joins: 0, per_min: null };
  const c = data.collab || { joins: 0, per_min: null };
  const n = data.normal || { joins: 0, per_min: null };
  const rate = (x) => (x.per_min == null ? "-" : x.per_min.toFixed(1));
  let msg =
    `Battle中 ${fmtNum(b.joins)}件 (${rate(b)}件/分) ／ `
    + `コラボ中 ${fmtNum(c.joins)}件 (${rate(c)}件/分) ／ `
    + `平時 ${fmtNum(n.joins)}件 (${rate(n)}件/分)。`;
  let detail = "";
  if (b.per_min && n.per_min) {
    msg += ` <b>Battle中は平時の ${(b.per_min / n.per_min).toFixed(1)}倍</b>の速さで入室。`;
    detail += `この倍率は「盛り上がる時間帯にバトルをする」影響を含む参考値です。時間帯を補正したバトル自体の効果は<a href="#an-s3d">③'</a>を参照してください。`;
  }
  if ((data.n_collabs || 0) === 0) {
    msg += ` <span class="an-warn">コラボ窓はまだ検出なし（収集は有効・コラボ配信の終了後に集計）。</span>`;
  }
  setNote("an-context-note", msg, detail);
  const labels = ["Battle中", "コラボ中", "平時"];
  const vals = [b.per_min, c.per_min, n.per_min];
  if (contextChart) {
    contextChart.data.labels = labels;
    contextChart.data.datasets[0].data = vals;
    contextChart.update();
    return;
  }
  contextChart = new Chart(document.getElementById("an-context-chart"), {
    type: "bar",
    data: { labels, datasets: [{ label: "入室/分", data: vals, backgroundColor: ["#a4502f", "#7a6a8e", "#4d4a3f"], borderWidth: 0 }] },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      scales: {
        x: { beginAtZero: true, ticks: nierTicks(), grid: { color: NIER_GRID_COLOR }, title: { display: true, text: "入室速度(件/分)", color: NIER_AXIS_COLOR, font: { family: "monospace", size: 10 } } },
        y: { ticks: nierTicks(), grid: { display: false } },
      },
      plugins: { legend: { display: false }, tooltip: { ...nierTooltip() } },
    },
  });
}

// ---- ③/③' event-study(peri-event): 入室の増減カーブ(95%CI帯 + 比較帯) ----
// share/battle共通。生joinを固定binへ再構築しbaseline差分した窓の平均を、比較(帰無)帯と
// 重ねて描く。暖色が比較帯を超える所が本物の反応。0秒より手前の上振れは因果方向の警告。
function _rgba(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}
function periDatasets(data, hex) {
  const lags = data.lags || [];
  const up = data.uplift || [];
  const ci = data.ci || [];
  const pl = data.placebo || [];
  const pci = data.placebo_ci || [];
  const sig = data.sig || [];
  const pts = (f) => lags.map((l, i) => ({ x: l, y: f(i) }));
  const hidden = { borderColor: "rgba(0,0,0,0)", pointRadius: 0, tension: 0.25, fill: false };
  // placebo帯は背景(砂色)と同系色で塗りだけでは埋もれるため、破線の輪郭で境界を明示する。
  const plEdge = { borderColor: "rgba(111,106,89,0.85)", borderWidth: 1, borderDash: [4, 3], pointRadius: 0, tension: 0.25, fill: false };
  return [
    // placebo帯(灰): 下限→上限をfillで塗る。
    { ...plEdge, label: "_pl_lo", data: pts((i) => pl[i] - pci[i]) },
    { ...plEdge, label: "placebo", data: pts((i) => pl[i] + pci[i]), fill: "-1", backgroundColor: "rgba(111,106,89,0.3)" },
    // 実uplift 95%CI帯(暖色)。
    { ...hidden, label: "_ci_lo", data: pts((i) => up[i] - ci[i]) },
    { ...hidden, label: "95%CI", data: pts((i) => up[i] + ci[i]), fill: "-1", backgroundColor: _rgba(hex, 0.2) },
    // 増減平均線。有意binは点を大きく。
    {
      label: "入室の増減", data: pts((i) => up[i]), borderColor: hex, backgroundColor: hex,
      borderWidth: 2.4, tension: 0.25, fill: false,
      pointRadius: (c) => (sig[c.dataIndex] ? 3.2 : 0),
      pointBackgroundColor: hex,
    },
  ];
}
function renderPeri(canvasId, chart, data, hex) {
  if (chart) chart.destroy();
  return new Chart(document.getElementById(canvasId), {
    type: "line",
    data: { datasets: periDatasets(data, hex) },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      parsing: false,
      scales: {
        x: { type: "linear", ticks: { ...nierTicks(), callback: (v) => (v > 0 ? "+" : "") + v + "s" }, grid: { color: NIER_GRID_COLOR }, title: { display: true, text: "基準時点からの秒（0=発生の瞬間）", color: NIER_AXIS_COLOR, font: { family: "monospace", size: 10 } } },
        y: { ticks: nierTicks(), grid: { color: NIER_GRID_COLOR }, title: vAxisTitle("入室数の増減（平常比）") },
      },
      plugins: {
        legend: { display: false },
        vline: { value: 0, color: "#6f6a59" },
        tooltip: {
          ...nierTooltip(),
          filter: (item) => item.dataset.label === "入室の増減",
          callbacks: { label: (i) => `${i.raw.x > 0 ? "+" : ""}${i.raw.x}s: 平常比 ${i.raw.y >= 0 ? "+" : ""}${i.raw.y.toFixed(2)}` },
        },
      },
    },
    plugins: [vLinePlugin],
  });
}

function peakPct(data) {
  const p = data.peak || {};
  if (p.pct == null) return "—";
  return `${p.pct >= 0 ? "+" : ""}${p.pct.toFixed(1)}%`;
}

// ---- ③ シェア→入室 ----
function renderShare(data) {
  if (!data || data.available === false) {
    setNote("an-share-note", `シェアのサンプルが不足しています（${fmtNum((data && data.n_events) || 0)}件）。`);
    return;
  }
  shareChart = renderPeri("an-share-chart", shareChart, data, "#a4502f");
  let msg =
    `入室はシェア後ピークで <b>${peakPct(data)}</b>（${data.peak.lag >= 0 ? "+" : ""}${data.peak.lag}s）。`;
  if (data.pre_rise) {
    msg += ` <span class="an-warn">立ち上がりがシェアより前から始まるため、シェアが原因か結果かは断定できません。</span>`;
  }
  setNote("an-share-note", msg,
    `シェア ${fmtNum(data.n_events)}回を集計（比較用 ${fmtNum(data.n_placebo)}件）。`
    + `ピーク%は全期間の平均入室レート比です。`);
}

// ---- ③' バトル→入室(比較帯つき event-study) ----
function renderBattle(data) {
  if (!data || data.available === false) {
    setNote("an-battle-note", `バトルのサンプルが不足しています（${fmtNum((data && data.n_events) || 0)}件）。`);
    return;
  }
  battleChart = renderPeri("an-battle-chart", battleChart, data, "#4d6e6e");
  const ratio = ((data.ratio_metrics || {}).metrics || {}).joins || {};
  const ratioPct = ratio.median != null ? `${ratio.median >= 1 ? "+" : ""}${((ratio.median - 1) * 100).toFixed(1)}%` : "—";
  // 有意判定は「開始後(lag>0)」かつ「増加」のbinのみ。開始前の上振れは効果でなく
  // 交絡/先行入室であり、含めると効果ゼロでも「明確な入室増あり」と誤断言してしまう。
  const lags = data.lags || [];
  const up = data.uplift || [];
  const anySig = (data.sig || []).some((s, i) => s && lags[i] > 0 && (up[i] || 0) > 0);
  let msg = `入室はバトル開始後ピークで <b>${peakPct(data)}</b>。`;
  msg += anySig
    ? ` 開始後に比較帯を超える明確な入室増あり。`
    : ` <b>比較帯の内側</b>で、入室の明確な増加は見られません。`;
  if (data.pre_rise) {
    msg += ` <span class="an-warn">立ち上がりがバトル開始より前から始まっており、「盛り上がりが先・バトルが後」の可能性があります。バトルが原因とは断定できません。</span>`;
  }
  setNote("an-battle-note", msg,
    `バトル ${fmtNum(data.n_events)}回を集計（比較用 ${fmtNum(data.n_placebo)}件）。ピーク%は全期間の平均入室レート比です。`
    + ` 参考: 単純な倍率では入室 ${ratioPct} ですが、盛り上がった時間帯の影響を含むため過大です。`);
}

// 各coin帯の棒へ「Y件中X件 rate%」を直接描く。棒端の外側に置き、右端に収まらない場合は
// 棒内側へ右寄せで描く。件数0の帯は「窓中0件」をくすませて明示する。
const gloveLabelPlugin = {
  id: "glovelabels",
  afterDatasetsDraw(chart) {
    const buckets = (chart.data.datasets[0] || {})._an || [];
    if (!buckets.length) return;
    const meta = chart.getDatasetMeta(0);
    const ctx = chart.ctx;
    ctx.save();
    ctx.font = "10px monospace";
    ctx.textBaseline = "middle";
    const area = chart.chartArea;
    const PAD = 3;
    meta.data.forEach((bar, i) => {
      const b = buckets[i];
      if (!b) return;
      const txt = b.gifts ? `${b.gifts}件中${b.crits}件 ${b.rate.toFixed(1)}%` : "サンプルなし";
      const w = ctx.measureText(txt).width;
      // バー右外に収まれば外側(左寄せ)、無理ならバー先端の内側(右寄せ)に置く
      const outside = bar.x + 4 + w + PAD * 2 <= area.right;
      const tx = outside ? bar.x + 4 + PAD : bar.x - 4 - PAD;
      const align = outside ? "left" : "right";
      // バーやグリッドに重なっても読めるよう背景チップを敷いてから描く
      const chipX = outside ? tx - PAD : tx - w - PAD;
      ctx.fillStyle = "rgba(205, 198, 174, 0.9)";
      ctx.fillRect(chipX, bar.y - 8, w + PAD * 2, 16);
      ctx.fillStyle = b.gifts ? "#403d33" : "rgba(64, 61, 51, 0.5)";
      ctx.textAlign = align;
      ctx.fillText(txt, tx, bar.y);
    });
    ctx.restore();
  },
};

// ---- ⑨ グローブ(5倍)のcoin帯別 発動率 ----
function renderGloveCrit(data) {
  const buckets = data.buckets || [];
  const labels = buckets.map((b) => b.label);
  const vals = buckets.map((b) => (b.rate == null ? null : b.rate));
  // 抽選率(20〜30%)付近=暖色、それ未満=くすませる。件数0はtransparent。
  const colors = buckets.map((b) =>
    b.gifts === 0 ? "rgba(0,0,0,0)" : b.rate >= 20 ? "rgba(164, 80, 47, 0.8)" : "rgba(169, 110, 73, 0.45)"
  );
  const overall = data.overall_rate == null ? "—" : `${data.overall_rate.toFixed(1)}%`;
  if (!data.total_gifts) {
    setNote("an-glove-note",
      `自陣(監視配信者)へ届いたグローブ窓中の判定済ギフトはまだありません`
      + `（グローブ窓 ${fmtNum(data.n_windows)}回）。`
      + `この指標は<b>今後のバトル収集から蓄積</b>されます。`);
    return;
  }
  const oc = data.overall_ci;
  setNote("an-glove-note",
    `判定済ギフト ${fmtNum(data.total_gifts)}件中 ${fmtNum(data.total_crits)}件が5倍。全体 <b>${overall}</b>${oc ? `（95%CI ${oc[0]}〜${oc[1]}%）` : ""}。`,
    `グローブ窓 ${fmtNum(data.n_windows)}回を集計。`
    + (data.undecided ? ` 判定不能(5倍か通常か確定できず)で分母から除外 ${fmtNum(data.undecided)}件。` : "")
    + (data.unresolved ? ` 単価不明で除外 ${fmtNum(data.unresolved)}件。` : "")
    + (data.range_out ? ` コイン帯範囲外 ${fmtNum(data.range_out)}件。` : ""));

  if (gloveChart) {
    gloveChart.data.labels = labels;
    gloveChart.data.datasets[0].data = vals;
    gloveChart.data.datasets[0].backgroundColor = colors;
    gloveChart.data.datasets[0]._an = buckets;
    gloveChart._an = buckets;
    gloveChart.update();
    return;
  }
  gloveChart = new Chart(document.getElementById("an-glove-chart"), {
    type: "bar",
    data: { labels, datasets: [{ label: "発動率%", data: vals, backgroundColor: colors, borderWidth: 0, _an: buckets }] },
    plugins: [gloveLabelPlugin],
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      scales: {
        x: { beginAtZero: true, ticks: { ...nierTicks(), callback: (v) => `${v}%` }, grid: { color: NIER_GRID_COLOR }, title: { display: true, text: "発動率% (5倍が乗った割合)", color: NIER_AXIS_COLOR, font: { family: "monospace", size: 10 } } },
        y: { type: "category", ticks: nierTicks(), grid: { display: false }, title: vAxisTitle("ギフト単価(coin)") },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          ...nierTooltip(),
          callbacks: {
            label: (item) => {
              const b = (gloveChart._an || [])[item.dataIndex];
              if (!b) return "";
              if (!b.gifts) return `${b.label}コイン: 判定済サンプルなし`;
              const ci = b.ci ? ` / 95%CI ${b.ci[0]}〜${b.ci[1]}%` : "";
              return `${b.label}コイン: ${b.crits}/${b.gifts}件が5倍 (${b.rate.toFixed(1)}%${ci})`;
            },
          },
        },
      },
    },
  });
  gloveChart._an = buckets;
}

// ---- ⑤ 入室 → 定着(同接として残るか) ----
function renderRetention(data) {
  const o = data.overall || {};
  const lift = o.lift_per_join;
  const liftTxt = lift == null ? "-" : `${lift >= 0 ? "+" : ""}${lift.toFixed(2)}`;
  setNote("an-retention-note",
    `配信 ${fmtNum(data.n_sessions || 0)}本・入室 ${fmtNum(o.joins)}件。<b>1入室あたり同接 ${liftTxt}人の押し上げ</b>。`,
    `押し上げは入室のない時間の自然な増減を差し引いた推定です。`
    + `入室は同一人物の再入室・TikTok側の間引きを含む概算、同接は匿名視聴者を含むため、厳密な定着率ではありません。`
    + ` 時刻別のグラフは入室の速さ(棒・件/分)と平均同接(線)です。`);

  const byHour = data.by_hour || [];
  const labels = byHour.map((h) => String(h.hour));
  const joins = byHour.map((h) => h.join_rate);
  const viewers = byHour.map((h) => h.viewers);
  if (retentionHourChart) {
    retentionHourChart.data.labels = labels;
    retentionHourChart.data.datasets[0].data = joins;
    retentionHourChart.data.datasets[1].data = viewers;
    retentionHourChart.update();
  } else {
    retentionHourChart = new Chart(document.getElementById("an-retention-hour"), {
      data: {
        labels,
        datasets: [
          { type: "bar", label: "入室(件/分)", data: joins, backgroundColor: "rgba(164, 80, 47, 0.55)", borderWidth: 0, yAxisID: "y" },
          { type: "line", label: "平均同接", data: viewers, borderColor: "#5d6e4e", backgroundColor: "#5d6e4e", borderWidth: 2, pointRadius: 2, tension: 0.25, yAxisID: "y2", spanGaps: true },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        scales: {
          x: { ticks: { ...nierTicks(), autoSkip: false, maxTicksLimit: 24 }, grid: { color: NIER_GRID_COLOR }, title: { display: true, text: "時刻", color: NIER_AXIS_COLOR, font: { family: "monospace", size: 10 } } },
          y: { beginAtZero: true, position: "left", ticks: nierTicks(), grid: { color: NIER_GRID_COLOR }, title: vAxisTitle("入室(件/分)") },
          y2: { beginAtZero: true, position: "right", ticks: nierTicks(), grid: { drawOnChartArea: false }, title: vAxisTitle("平均同接(人)") },
        },
        plugins: { legend: { display: true, labels: { ...nierTicks(), boxWidth: 12 } }, tooltip: { ...nierTooltip() } },
      },
    });
  }
}

// ---- ⑫ 滞在時間と入れ替わり(Little則) ----
// 推定できなかった窓は0や近似値で埋めず、理由別の件数として出す。埋めた値は実測と
// 見分けが付かず、定常でない区間へLittle則を当てた結果が実測のように読まれてしまう。
const DWELL_REJECT_LABELS = {
  unstable: "来場の速さが窓内で動いていた",
  drift: "同接の水準が窓内で動いていた",
  cover: "観測に穴が多い",
  noarr: "来場が少なく速さを出せない",
  short: "窓の長さが足りない",
  gap: "観測が大きく途切れた",
  reset: "累積カウンタが巻き戻った",
};

function dwellSeconds(v) {
  if (v == null) return "-";
  return v < 90 ? `${v.toFixed(0)}秒` : `${(v / 60).toFixed(1)}分`;
}

function dwellPct(v) {
  return v == null ? "-" : `${(v * 100).toFixed(1)}%`;
}

function renderDwell(data) {
  const o = data.overall;
  const kpi = document.getElementById("an-dwell-kpi");
  const cells = o
    ? [
      ["平均滞在(中央値)", dwellSeconds(o.dwell_seconds)],
      ["1時間あたりの入れ替わり", `${fmtNum(o.turnover_per_hour)}回`],
      ["配信ごとのばらつき", `${dwellSeconds(o.p25)}〜${dwellSeconds(o.p75)}`],
      ["推定できた配信", `${fmtNum(o.n_sessions)}本`],
      ["推定に使えた窓", `${fmtNum(data.windows || 0)} / ${fmtNum(data.candidates || 0)}`],
    ]
    : [["平均滞在(中央値)", "推定不能"]];
  kpi.innerHTML = cells
    .map(([k, v]) => `<div class="a-chip"><span class="l">${anEscape(k)}</span><span class="v">${anEscape(v)}</span></div>`)
    .join("");

  const hours = data.hours || [];
  const labels = hours.map((h) => String(h[0]));
  const values = hours.map((h) => h[1]);
  const counts = hours.map((h) => h[2]);
  // 窓の少ない時刻は棒を薄くする。消すと「その時刻は配信が無い」に読めてしまうため、
  // 残したうえで参考値だと見て分かるようにする。
  const minWindows = data.hour_min_windows || 0;
  const colors = counts.map((n) => (n >= minWindows ? "rgba(93, 110, 78, 0.6)" : "rgba(93, 110, 78, 0.18)"));
  if (dwellHourChart) {
    dwellHourChart.data.labels = labels;
    dwellHourChart.data.datasets[0].data = values;
    dwellHourChart.data.datasets[0].backgroundColor = colors;
    dwellHourChart.$counts = counts;
    dwellHourChart.update();
  } else {
    dwellHourChart = new Chart(document.getElementById("an-dwell-hour"), {
      type: "bar",
      data: {
        labels,
        datasets: [{ label: "滞在時間の中央値(秒)", data: values, backgroundColor: colors, borderWidth: 0 }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        scales: {
          x: { ticks: { ...nierTicks(), autoSkip: false, maxTicksLimit: 24 }, grid: { color: NIER_GRID_COLOR }, title: { display: true, text: "時刻", color: NIER_AXIS_COLOR, font: { family: "monospace", size: 10 } } },
          y: { beginAtZero: true, ticks: nierTicks(), grid: { color: NIER_GRID_COLOR }, title: vAxisTitle("滞在時間(秒)") },
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            ...nierTooltip(),
            callbacks: {
              // nは推定に使えた窓の数。少ない時刻の棒を実勢と読ませないため必ず併記する。
              afterLabel: (ctx) => `n=${(dwellHourChart.$counts || [])[ctx.dataIndex] || 0} 窓`,
            },
          },
        },
      },
    });
    dwellHourChart.$counts = counts;
  }

  // 単位はheaderに書かず、下の注記へまとめる。headerが長いほど列幅の下限が上がり、
  // 8列の表が横scrollへ落ちる(.result-table thはnowrap)。
  const streamers = data.streamers || [];
  anTable("an-dwell-streamers",
    ["配信者", "配信数", "滞在(中央値)", "平均±95%CI", "入れ替わり/時", "同接", "速い窓", "居座り窓"],
    streamers.map((s) => {
      const mix = s.mix || {};
      return [
        { html: anEscape(s.unique_id), cls: "ident" },
        fmtNum(s.sessions),
        dwellSeconds(s.dwell_seconds),
        `${dwellSeconds(s.mean)}${s.ci == null ? "" : ` ±${s.ci.toFixed(0)}秒`}`,
        s.turnover_per_hour == null ? "-" : `${fmtNum(s.turnover_per_hour)}回`,
        fmtNum(s.avg_viewers),
        dwellPct(mix.churn),
        dwellPct(mix.sticky),
      ];
    }),
    [1, 2, 3, 4, 5, 6, 7],
    "推定に足りる配信がまだありません。");

  const rejects = data.rejects || {};
  const rejectText = Object.keys(DWELL_REJECT_LABELS)
    .filter((k) => rejects[k])
    .map((k) => `${DWELL_REJECT_LABELS[k]} ${fmtNum(rejects[k])}`)
    .join(" / ") || "なし";
  const cross = data.cross_check || {};
  const eng = data.engagement || {};
  const line = `対象 ${fmtNum(data.n_sessions || 0)}本のうち<b>推定できたのは ${fmtNum(data.n_estimated || 0)}本</b>。`
    + ` 表の滞在・平均は秒/分、同接は人、速い窓・居座り窓はその配信者の窓に占める割合です。`;
  let detail = `5分窓 ${fmtNum(data.candidates || 0)}個中 ${fmtNum(data.windows || 0)}個を採用し、`
    + `<b>残りは推定不能</b>として除外しました（内訳: ${anEscape(rejectText)}）。`
    + ` 時刻別のグラフで<b>薄い棒は窓が${fmtNum(minWindows)}個未満</b>の参考値です（深夜帯は観測そのものが少なく、数本の配信で決まります）。`;
  if (data.crude_dwell_seconds != null) {
    detail += ` 窓を切らずに配信まるごとで計算した粗い値は ${dwellSeconds(data.crude_dwell_seconds)}（${fmtNum(data.crude_n || 0)}本）で、上の推定と同程度です。`;
  }
  if (cross.ratio != null) {
    // 来場カウンタの正体は非公開のため、独立に届く入室eventとの比を必ず添える。
    detail += ` 来場カウンタの伸びに対する入室eventの比は中央値 ${cross.ratio.toFixed(2)}（配信間で ${cross.p10.toFixed(2)}〜${cross.p90.toFixed(2)}・${fmtNum(cross.n || 0)}本）。`
      + `比が配信をまたいで揃っているため到着の代理として扱えますが、入室eventを基準に取り直せば滞在時間は約${((1 / cross.ratio - 1) * 100).toFixed(0)}%長く出ます。絶対秒に幅があるのはこのためです。`;
  }
  if (eng.rho != null) {
    detail += eng.significant
      ? ` 妥当性check: 滞在が長いと推定された配信ほど視聴時間あたりのCommentも多い傾向（同接を統制した偏順位相関 ρ=${eng.rho.toFixed(2)}・n=${fmtNum(eng.n)}・有意）。`
      : ` <span class="an-warn">妥当性check: 視聴時間あたりのCommentとの関連は ρ=${eng.rho.toFixed(2)}（n=${fmtNum(eng.n)}）で有意ではありません。滞在時間の推定が別の指標から裏付けられてはいない点に留意してください。</span>`;
  }
  setNote("an-dwell-note", line, detail);
}

function actSeconds(v) {
  if (v == null) return "-";
  if (v < 60) return `${v.toFixed(0)}秒`;
  if (v < 3600) return `${(v / 60).toFixed(0)}分`;
  return `${(v / 3600).toFixed(1)}時間`;
}

function actPct(v, digits = 1) {
  return v == null ? "-" : `${(v * 100).toFixed(digits)}%`;
}

function renderActivation(data) {
  const wl = (data.series || {}).wl || {};
  const nl = (data.series || {}).nl || {};
  const cov = data.coverage;

  const cells = [
    ["対象(入室が記録された人)", `${fmtNum(data.n_persons || 0)}人`],
    ["反応した割合(いいね含む)", actPct(wl.activated_ratio)],
    ["反応した割合(いいね除く)", actPct(nl.activated_ratio)],
    ["素通り(いいね含む)", actPct(wl.activated_ratio == null ? null : 1 - wl.activated_ratio)],
    ["反応した人の中央値", actSeconds(wl.median_latency)],
  ];
  document.getElementById("an-act-kpi").innerHTML = cells
    .map(([k, v]) => `<div class="a-chip"><span class="l">${anEscape(k)}</span><span class="v">${v}</span></div>`)
    .join("");

  const edges = data.bin_edges || [];
  const mk = (s, color) => ({
    label: s.label || "",
    data: (s.curve || []).slice(0, edges.length).map((v, i) => ({ x: edges[i], y: v * 100 })),
    borderColor: color,
    backgroundColor: color,
    borderWidth: 2,
    pointRadius: 0,
    tension: 0.1,
    fill: false,
  });
  const datasets = [mk(wl, "#a4502f"), mk(nl, "#5d6e4e")];
  if (activationChart) {
    activationChart.data.datasets = datasets;
    activationChart.update();
  } else {
    activationChart = new Chart(document.getElementById("an-act-chart"), {
      type: "line",
      data: { datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        parsing: false,
        scales: {
          x: {
            type: "logarithmic",
            ticks: { ...nierTicks(), callback: (v) => actSeconds(v) },
            grid: { color: NIER_GRID_COLOR },
            title: { display: true, text: "入室してからの経過時間(対数軸)", color: NIER_AXIS_COLOR, font: { family: "monospace", size: 10 } },
          },
          y: {
            beginAtZero: true,
            ticks: { ...nierTicks(), callback: (v) => `${v}%` },
            grid: { color: NIER_GRID_COLOR },
            title: vAxisTitle("反応した割合(累積)"),
          },
        },
        plugins: {
          legend: { display: true, labels: { ...nierTicks(), boxWidth: 12 } },
          tooltip: { ...nierTooltip() },
        },
      },
    });
  }

  const nlByH = {};
  (nl.horizons || []).forEach((h) => { nlByH[h.seconds] = h; });
  const ci = (x) => (x && x.ci ? `${actPct(x.ci[0])} 〜 ${actPct(x.ci[1])}` : "-");
  anTable("an-act-table",
    ["入室からの経過", "反応(いいね含む)", "95%CI", "反応(いいね除く)", "95%CI"],
    (wl.horizons || []).map((h) => {
      const n = nlByH[h.seconds] || {};
      return [
        `${actSeconds(h.seconds)}後まで`,
        actPct(h.activated),
        { html: ci(h), cls: "an-muted" },
        actPct(n.activated),
        { html: ci(n), cls: "an-muted" },
      ];
    }),
    [1, 2, 3, 4],
    "反応を追える入室がまだありません。");

  const line = `対象 ${fmtNum(data.n_sessions || 0)}配信・${fmtNum(data.n_persons || 0)}人。`
    + (wl.median_latency != null
      ? ` 反応した人の中央値は <b>${actSeconds(wl.median_latency)}</b>（いいねを除くと ${actSeconds(nl.median_latency)}）。`
      : "")
    + (cov ? ` <span class="an-warn">この割合は「入室が記録された人」だけの値です。</span>` : "");
  let detail = `1人が同じ配信に入り直した場合は1人として数えます。`
    + `信頼区間は配信を単位にした再抽出 ${fmtNum(data.bootstrap || 0)}回から求めています。`;
  if (wl.median_latency != null) {
    detail += ` 反応する人は<b>早い段階で反応します</b>。最終的な反応の大半は入室から1分以内に起きています。`
      + `なお<b>全体の中央値は存在しません</b>（9割が最後まで反応しないため、曲線が50%に届きません）。`;
  }
  if (cov) {
    // 母集団の欠けは、この指標の最大の弱点なので必ず数値で出す。
    detail += `<br />実際に反応があった ${fmtNum(cov.actors)}人のうち、入室eventが残っているのは`
      + ` <b>${fmtNum(cov.actors_with_join)}人（${actPct(cov.ratio)}）</b>で、残り ${fmtNum(cov.missing)}人は`
      + `反応しているのに入室が記録されていません。`;
    if (cov.gifter_ratio != null) {
      detail += ` しかも<b>ギフトを送った人に限ると入室が残っているのは ${actPct(cov.gifter_ratio)}</b>`
        + `（${fmtNum(cov.gifters_with_join)}/${fmtNum(cov.gifters)}人）にとどまり、`
        + `<b>取りこぼしは熱心な視聴者ほど多い</b>ことが分かります。`;
    }
    detail += ` つまり母集団から熱心な層が抜けているため、上の反応率は<b>下限</b>、`
      + `素通り率は<b>上限</b>として読んでください。視聴者全体の反応率はこれより高いはずです。`;
  }
  setNote("an-act-note", line, detail);
}

// ---- ⑥ 集中度(Lorenz曲線) ----
function renderConcentration(data) {
  renderLorenz("gift", "an-lorenz-gift", "an-conc-gift-note", "an-conc-gift-top", "コイン", data.gifts, "#a96e49");
  renderLorenz("comment", "an-lorenz-comment", "an-conc-comment-note", "an-conc-comment-top", "Comment", data.comments, "#5d6e4e");
}
function renderLorenz(key, canvasId, noteId, topId, unit, c, color) {
  if (!c) return;
  // Gini(母集団式)の上限は人数nに依存して(n-1)/n。少人数だと1に届かないため上限を併記する。
  const giniMax = c.n_users > 1 ? (c.n_users - 1) / c.n_users : 0;
  document.getElementById(noteId).innerHTML =
    `<b>${unit}</b>: 貢献 ${fmtNum(c.n_users)}人（無言の視聴者は含まない） / Gini <b>${c.gini.toFixed(3)}</b>（0=均等、この人数での上限は約${giniMax.toFixed(2)}）`;
  const top = c.top || [];
  document.getElementById(topId).innerHTML = top
    .map((t) => `<div class="a-chip"><span class="l">上位${t.pct}%(${fmtNum(t.users)}人)</span><span class="v">${(t.share * 100).toFixed(1)}%</span></div>`)
    .join("");
  const pts = (c.lorenz || []).map((p) => ({ x: p.p, y: p.share }));
  const equality = [{ x: 0, y: 0 }, { x: 1, y: 1 }];
  const datasets = [
    { label: "実際", data: pts, borderColor: color, backgroundColor: color, borderWidth: 2, pointRadius: 0, tension: 0.1, fill: false },
    { label: "全員均等", data: equality, borderColor: "#6f6a59", borderWidth: 1, borderDash: [4, 3], pointRadius: 0, fill: false },
  ];
  if (lorenzCharts[key]) {
    lorenzCharts[key].data.datasets[0].data = pts;
    lorenzCharts[key].update();
    return;
  }
  lorenzCharts[key] = new Chart(document.getElementById(canvasId), {
    type: "line",
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      scales: {
        x: { type: "linear", min: 0, max: 1, ticks: { ...nierTicks(), callback: (v) => Math.round(v * 100) + "%" }, grid: { color: NIER_GRID_COLOR }, title: { display: true, text: "人数(下位から累積)", color: NIER_AXIS_COLOR, font: { family: "monospace", size: 10 } } },
        y: { min: 0, max: 1, ticks: { ...nierTicks(), callback: (v) => Math.round(v * 100) + "%" }, grid: { color: NIER_GRID_COLOR }, title: vAxisTitle(`${unit}累積シェア`) },
      },
      plugins: {
        legend: { labels: { color: "#4d4a3f", font: { family: "monospace", size: 10 }, boxWidth: 12, boxHeight: 8 } },
        tooltip: { ...nierTooltip(), callbacks: { label: (i) => `下位${Math.round(i.parsed.x * 100)}%の人で ${unit}の${Math.round(i.parsed.y * 100)}%` } },
      },
    },
  });
}

// ---- ①' organic入室(ノイズ除去した時間帯の関心) ----
// slot(0..95)を HH:MM へ。x軸は:00のみ表示し過密を避ける。
function organicLabels(bySlot) {
  return bySlot.map((s) => {
    const m = s.minute != null ? s.minute : s.slot * 15;
    return String(Math.floor(m / 60)).padStart(2, "0") + ":" + String(m % 60).padStart(2, "0");
  });
}

// 平日/休日それぞれのlineグラフを生成・更新する(生 vs ノイズ除去後)。yは各自auto。
function organicChartFor(canvasId, existing, bySlot) {
  const labels = organicLabels(bySlot);
  // 配信のない時刻(raw=0)は線を切る。実数(件)で生とノイズ除去後の差を見る。
  const rawCnt = bySlot.map((h) => (h.raw > 0 ? h.raw : null));
  const orgCnt = bySlot.map((h) => (h.raw > 0 ? Math.round(h.organic) : null));
  if (existing) {
    existing.data.labels = labels;
    existing.data.datasets[0].data = rawCnt;
    existing.data.datasets[1].data = orgCnt;
    existing.update();
    return existing;
  }
  const datasets = [
    { type: "line", label: "生の入室数", data: rawCnt, borderColor: "#918b78", backgroundColor: "#918b78", borderWidth: 2, pointRadius: 2, tension: 0.25, spanGaps: false },
    { type: "line", label: "ノイズ除去後", data: orgCnt, borderColor: "#a4502f", backgroundColor: "#a4502f", borderWidth: 2.6, pointRadius: 2, tension: 0.25, spanGaps: false },
  ];
  return new Chart(document.getElementById(canvasId), {
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      scales: {
        x: { ticks: { ...nierTicks(), autoSkip: false, callback: (v, i) => (i % 4 === 0 ? labels[i] : "") }, grid: { color: NIER_GRID_COLOR }, title: { display: true, text: "時刻(15分)", color: NIER_AXIS_COLOR, font: { family: "monospace", size: 10 } } },
        y: { beginAtZero: true, ticks: { ...nierTicks() }, grid: { color: NIER_GRID_COLOR }, title: vAxisTitle("入室数(件)") },
      },
      plugins: {
        legend: { labels: { color: "#4d4a3f", font: { family: "monospace", size: 11 }, boxWidth: 14, boxHeight: 8 } },
        tooltip: { ...nierTooltip() },
      },
    },
  });
}

function renderOrganic(data) {
  const t = data.totals || {};
  const pct = (x) => `${((x || 0) * 100).toFixed(1)}%`;
  setNote("an-organic-note",
    `全入室 ${fmtNum(t.raw || 0)}件 → ノイズ除去後 <b>${fmtNum(Math.round(t.organic || 0))}件</b>相当（配信 ${fmtNum(data.n_sessions || 0)}本）。`
    + `<span class="an-hm-legend"><i>生の入室</i><span class="an-hm-bar"></span><i>ノイズ除去後</i></span>`,
    `重みの内訳: 再訪した人 <b>${pct(data.returning_ratio)}</b> ／ 入室後に反応した人 <b>${pct(data.engaged_ratio)}</b>`
    + ` ／ シェア直後の流入 <b>${pct(data.share_window_ratio)}</b>`
    + (data.stick_rate != null ? ` ／ 定着率 <b>${pct(data.stick_rate)}</b>` : "")
    + `。重みは常に1以下のため、ノイズ除去後の線はどの時間帯も生の線より低く出ます。`);

  document.getElementById("an-organic-wd-head").textContent =
    `平日（月〜金）· 入室 ${fmtNum(data.weekday_raw || 0)}件`;
  document.getElementById("an-organic-he-head").textContent =
    `休日（土日）· 入室 ${fmtNum(data.holiday_raw || 0)}件`;

  organicChartWd = organicChartFor("an-organic-chart-wd", organicChartWd, data.weekday || []);
  organicChartHe = organicChartFor("an-organic-chart-he", organicChartHe, data.holiday || []);
}

// ---- ②' 入室の流入元とフォロー関係 ----
// 流入元の文字列はTikTokが送ってきた値をそのまま出すため、HTMLへ埋める前に必ず退避する。
function anEscape(text) {
  return String(text == null ? "" : text)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

const FOLLOW_LABELS = {
  following: "フォロー中",
  mutual: "相互フォロー",
  not_following: "フォローなし",
  unknown: "不明（値が届かず）",
};

// 流入元keyはTikTokの生値 "<画面>-<導線>"。表示時だけ日本語へ写像し、
// 未知のtokenは生のまま出す。元の生値はtooltip(title)で確認できる。
const ENTRY_TOKEN_LABELS = {
  homepage_hot: "おすすめフィード",
  homepage_follow: "フォロー中フィード",
  homepage_friends: "友達タブ",
  homepage_mall: "ショップタブ",
  live_merge: "LIVE一覧タブ",
  live_detail: "他のLIVE視聴画面",
  live_end: "LIVE終了画面",
  message: "メッセージ",
  chat: "チャット",
  chat_live: "チャット(LIVE)",
  others_homepage: "他ユーザーのプロフィール",
  personal_homepage: "自分のプロフィール",
  follow_recommend: "フォロー関連のおすすめ",
  general_search: "検索",
  search_result: "検索結果",
  push: "プッシュ通知",
  inner_push: "アプリ内通知",
  ug_task_page: "ミッション/報酬ページ",
  h5: "アプリ内Webページ",
  webview: "アプリ内ブラウザ",
  share: "シェア",
  following_list: "フォロー中リスト",
  follower_list: "フォロワーリスト",
  following: "フォロー中",
  ranking_league: "ランキングリーグ",
  daily_rank: "デイリーランキング",
  daily_rank_notice: "デイリーランキング通知",
  hourly_rank: "時間別ランキング",
  weekly_game_rank: "週間ゲームランキング",
  sale_rank: "セールランキング",
  hall_of_fame_rank: "殿堂入りランキング",
  fans_team_rank: "ファンチームランキング",
  friends_ranking: "友達ランキング",
  draw_loadmore: "ランキングの続きを表示",
  story_live: "ストーリーのLIVE",
  notification_page: "通知ページ",
  notification_page_bb_card: "通知ページのカード",
  notification_page_bb_bar: "通知ページのバー",
  activity_message_page_bb_card: "アクティビティ通知のカード",
  recommend: "おすすめ",
  balance: "コイン残高画面",
  balance_rec_watch: "コイン残高画面のおすすめ視聴",
  balance_non_rec_watch: "コイン残高画面の視聴導線",
  balance_rec_explore: "コイン残高画面のおすすめ探索",
  gift_panel: "ギフトパネル",
  gift_message: "ギフトメッセージ",
  fans_club_list_page: "ファンクラブ一覧",
  click_fans_team: "ファンチームをタップ",
  app_intent: "外部リンクから起動",
  order_center: "注文履歴",
  post: "投稿",
  collection_video: "保存した動画",
  bulletin_board_page: "掲示板ページ",
  music_spotlight_live_cell: "楽曲スポットライトのLIVE枠",
  inner_flow_live_cover: "縦スワイプのLIVEフィード",
  follow_widget: "フォローウィジェット",
  live_cell: "LIVE枠",
  live_cover: "LIVEサムネイル",
  toplive_live_cover: "人気LIVEのサムネイル",
  nearby_tab_live_cover: "近くタブのLIVEサムネイル",
  hangout_cover: "ハングアウトのサムネイル",
  video_head: "投稿動画のアイコン",
  video_cell: "動画枠",
  right_anchor: "画面右の配信者アイコン",
  others_photo: "投稿",
  suggested_others_photo: "おすすめ投稿",
  dm_head: "DMのアイコン",
  portal: "ポータル",
  live_incentive: "LIVE報酬",
  action_bar: "アクションバー",
  chat_head: "チャットのアイコン",
  next_icon_click: "「次へ」ボタン",
  watch_later: "あとで見る",
  live_head: "LIVEアイコン",
  live_entrance_head: "LIVE入口のアイコン",
  live_entrance_hover_list: "LIVE入口の一覧",
  live_bottom_bar: "画面下のLIVEバー",
  live_info_button: "LIVE情報ボタン",
  top_cell: "上部の枠",
  head: "アイコン",
  new_activities: "新着アクティビティ",
  from: "不明",
  others: "その他",
  unknown: "不明（値が空）",
};

function entryToken(token) {
  return ENTRY_TOKEN_LABELS[token]
    || ENTRY_TOKEN_LABELS[token.toLowerCase()]
    || token;
}

function entrySourceLabel(key) {
  const raw = String(key == null ? "" : key);
  const sep = raw.indexOf("-");
  if (sep < 0) return entryToken(raw);
  const surface = entryToken(raw.slice(0, sep));
  const component = raw.slice(sep + 1).split("+").map(entryToken).join("＋");
  return surface === component ? surface : `${surface} › ${component}`;
}

function entryRatio(ratio) {
  return ratio == null ? "-" : `${(ratio * 100).toFixed(1)}%`;
}

function fillEntryTable(id, header, rows, emptyText) {
  anTable(id, [header, "件数", "構成比"],
    rows.map((r) => [
      // 流入元は「おすすめフィード › 縦スワイプのLIVEフィード」のように長い。tbodyを
      // <td>にしてあるので折り返しが効く(<th>はnowrapで1行に伸びて表が横scrollになる)。
      { html: anEscape(r.label), title: r.title && r.title !== r.label ? r.title : null },
      fmtNum(r.count),
      entryRatio(r.ratio),
    ]),
    [1, 2], emptyText);
}

function renderEntrySource(data) {
  const joins = data.joins || {};
  const engaged = data.engaged || {};
  const follow = joins.follow || {};
  fillEntryTable(
    "an-entry-src", "流入元",
    (joins.sources || []).map((r) => ({
      label: entrySourceLabel(r.key), title: r.key, count: r.count, ratio: r.ratio,
    })),
    "流入元が届いた入室はまだありません。",
  );
  fillEntryTable(
    "an-entry-follow", "関係",
    (follow.breakdown || []).map((r) => ({
      label: FOLLOW_LABELS[r.key] || r.key, count: r.count, ratio: r.ratio,
    })),
    "フォロー関係が届いた入室はまだありません。",
  );
  const cov = (v) => (v == null ? "-" : `${(v * 100).toFixed(1)}%`);
  const roles = engaged.roles || {};
  const roleText = (key, label) => {
    const r = roles[key] || {};
    if (!r.measured) return "";
    return ` ${label} ${fmtNum(r.count)}件(${entryRatio(r.ratio)})`;
  };
  setNote("an-entry-note",
    `入室 ${fmtNum(joins.total || 0)}件中 <b>流入元が届いたのは ${fmtNum(joins.measured || 0)}件（取得率 ${cov(joins.coverage)}）</b>`
    + `、フォロー関係は ${fmtNum(follow.measured || 0)}件（取得率 ${cov(follow.coverage)}）。`,
    `配信 ${fmtNum(data.n_sessions || 0)}本のうち ${fmtNum(data.n_sessions_measured || 0)}本で値を取得。`
    + ` Comment/Gift ${fmtNum(engaged.total || 0)}件中 ${fmtNum(engaged.measured || 0)}件（取得率 ${cov(engaged.coverage)}）で配信者との関係を取得。`
    + roleText("sub", "うちサブスク") + roleText("mod", "モデレータ") + roleText("gg", "ギフト経験者")
    + ` 構成比の分母は値が届いた分のみです。届かなかった分（この機能より前に収集した入室）は構成比に含めていません。`
    + `流入元の表示名はTikTokが送る生値からの推定和訳で、生値は行にマウスを乗せると確認できます。`);
}

// ---- ⑦ 入室の質(新規/常連) ----
function renderQuality(data) {
  const byHour = data.hours || [];
  const labels = byHour.map((h) => String(h.hour));
  const news = byHour.map((h) => h.new);
  const rets = byHour.map((h) => h.returning);
  const ratio = byHour.map((h) => (h.total > 0 ? h.new_ratio * 100 : null));
  setNote("an-quality-note",
    `入室 ${fmtNum(data.total)}人中、新規は ${fmtNum(data.new)}人（<b>新規率 ${((data.new_ratio || 0) * 100).toFixed(1)}%</b>・配信 ${fmtNum(data.n_sessions || 0)}本）。`,
    `人数は時間帯ごとのユニーク人数で、同一時間帯の再入室は1人と数えます。`
    + (data.excluded ? ` 識別できない入室 ${fmtNum(data.excluded)}件は除外しています。` : "")
    + ` 「新規」はこの監視で初めて観測した人。監視を始めた直後は以前からの常連も新規に数えられて高めに出ます。他の監視配信者で観測済みの人は常連扱いです。`);

  const datasets = [
    { type: "bar", label: "新規", data: news, backgroundColor: "#a4502f", stack: "j", yAxisID: "y" },
    { type: "bar", label: "常連", data: rets, backgroundColor: "#4d4a3f", stack: "j", yAxisID: "y" },
    { type: "line", label: "新規率", data: ratio, borderColor: "#9b8c52", backgroundColor: "#9b8c52", borderWidth: 2, pointRadius: 2, tension: 0.25, yAxisID: "y2", spanGaps: true },
  ];
  if (qualityChart) {
    qualityChart.data.labels = labels;
    qualityChart.data.datasets[0].data = news;
    qualityChart.data.datasets[1].data = rets;
    qualityChart.data.datasets[2].data = ratio;
    qualityChart.update();
    return;
  }
  qualityChart = new Chart(document.getElementById("an-quality-chart"), {
    type: "bar",
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      scales: {
        x: { stacked: true, ticks: { ...nierTicks(), autoSkip: false, maxTicksLimit: 24 }, grid: { color: NIER_GRID_COLOR }, title: { display: true, text: "時刻", color: NIER_AXIS_COLOR, font: { family: "monospace", size: 10 } } },
        y: { stacked: true, beginAtZero: true, position: "left", ticks: nierTicks(), grid: { color: NIER_GRID_COLOR }, title: vAxisTitle("入室数(人)") },
        y2: { beginAtZero: true, max: 100, position: "right", ticks: nierTicks(), grid: { drawOnChartArea: false }, title: vAxisTitle("新規率(%)") },
      },
      plugins: {
        legend: { labels: { color: "#4d4a3f", font: { family: "monospace", size: 11 }, boxWidth: 14, boxHeight: 8 } },
        tooltip: { ...nierTooltip() },
      },
    },
  });
}

// ---- ⑪ 収集カバレッジ ----
function cvUnmeasured(text) {
  return `<span class="an-warn">計測不能</span>${text ? ` <span class="an-muted">${text}</span>` : ""}`;
}

function cvSeconds(v) {
  if (v == null) return "-";
  if (v < 90) return `${v.toFixed(1)}秒`;
  return `${(v / 60).toFixed(1)}分`;
}

function renderCoverage(data) {
  const inst = data.instrumented || {};
  const delay = data.start_delay || {};
  const gaps = data.gaps || {};
  const gapSec = gaps.seconds || {};
  const gapRatio = gaps.ratio || {};
  const sampling = data.sampling || {};
  const sMed = sampling.median || {};
  const sP95 = sampling.p95 || {};
  const rec = data.recording || {};
  const recRatio = rec.ratio || {};
  const stt = data.transcript || {};

  const rows = [
    ["切断の記録がある配信",
      `${fmtNum(inst.measured || 0)}本 / ${fmtNum(data.n_sessions || 0)}本`,
      fmtNum(inst.measured || 0),
      "切断の記録を始める前の配信は、欠測を測る材料そのものがありません。"],
    ["収集開始の遅れ（配信開始→接続）",
      delay.n ? `中央値 ${cvSeconds(delay.median)}（最大 ${cvSeconds(delay.max)}）` : cvUnmeasured("配信そのものの開始時刻が取れた配信がまだありません。"),
      fmtNum(delay.n || 0),
      "配信側が返す開始時刻と、実際に接続できた時刻の差。この間の入室・ギフトは記録にありません。"],
    ["切断でつながっていなかった時間",
      gaps.n_sessions ? `1配信あたり中央値 ${cvSeconds(gapSec.median)}（配信時間の ${gapRatio.median == null ? "-" : gapRatio.median.toFixed(1)}%・最大 ${cvSeconds(gapSec.max)}）` : cvUnmeasured("切断の記録がある配信がまだありません。"),
      fmtNum(gaps.n_sessions || 0),
      `再接続で閉じた切断 ${fmtNum(gaps.count || 0)}回（うち異常切断 ${fmtNum(gaps.unplanned || 0)}回）。切断したまま配信が終わった回（${fmtNum(gaps.open_end || 0)}回）は欠測に数えていません。`],
    ["同接の取得間隔",
      sMed.n ? `中央値 ${cvSeconds(sMed.median)}・p95 ${cvSeconds(sP95.median)}（最悪 ${cvSeconds(sampling.worst)}）` : cvUnmeasured("同接のサンプルが足りません。"),
      fmtNum(sampling.n_sessions || 0),
      "配信ごとに求めた間隔の中央値／p95を、さらに配信間で中央値にした値です。"],
    ["録画できていた割合",
      recRatio.n ? `中央値 ${recRatio.median == null ? "-" : recRatio.median.toFixed(1)}%（全区間録画 ${fmtNum(rec.full || 0)}本・録画なし ${fmtNum(rec.none || 0)}本）` : cvUnmeasured("尺の確定した録画がまだありません。"),
      fmtNum(rec.n_sessions || 0),
      rec.unmeasured_sessions ? `録画の尺が確定していない配信 ${fmtNum(rec.unmeasured_sessions)}本は対象外です。` : ""],
    ["文字起こし済みの録画",
      stt.recordings ? `${fmtNum(stt.transcribed || 0)}本 / ${fmtNum(stt.recordings)}本（${stt.ratio == null ? "-" : (stt.ratio * 100).toFixed(1)}%）` : cvUnmeasured("完了した録画がまだありません。"),
      fmtNum(stt.recordings || 0),
      "完了した録画のみが対象です。"],
  ];
  anTable("an-coverage", ["指標", "値", "対象(本)", "注記"],
    rows.map(([label, value, n, note]) => [
      anEscape(label), value, n, { html: anEscape(note || ""), cls: "an-muted" },
    ]),
    [2],
    "集計できた配信がまだありません。");
  setNote("an-coverage-note",
    `対象 ${fmtNum(data.n_sessions || 0)}本（終了済み ${fmtNum(data.n_sessions_ended || 0)}本）。`
    + ` <b>切断の欠測を測れるのは ${fmtNum(inst.measured || 0)}本のみ</b>で、残り ${fmtNum(inst.unmeasured || 0)}本は計測不能です。`,
    `計測不能の配信を「欠測0秒」として混ぜていないため、この表の欠測時間は全体の下限ではなく、測れた配信だけの実測値です。`);
}

// ---- ロード ----
// 18本のAPIをPromise.allSettledで束ねると、一番遅い1本が全体の待ちになり、先に返った
// 17本も画面に出ない。1本ずつ投げて到着順にそのsectionだけ描く。
const SECTIONS = [
  { key: "summary", api: "summary", render: renderSummary },
  { key: "time-index", api: "time-index", note: "an-ti-note", render: renderTimeIndex,
    extra: () => `&metric=${encodeURIComponent(elTiMetric.value)}` },
  { key: "organic", api: "organic-entries", note: "an-organic-note", render: renderOrganic },
  { key: "join-context", api: "join-context", note: "an-context-note", render: renderJoinContext },
  { key: "entry-source", api: "entry-source", note: "an-entry-note", render: renderEntrySource },
  { key: "share", api: "share-uplift", note: "an-share-note", render: renderShare },
  { key: "battle", api: "battle-uplift", note: "an-battle-note", render: renderBattle },
  { key: "retention", api: "retention", note: "an-retention-note", render: renderRetention },
  { key: "concentration", api: "concentration", note: "an-conc-gift-note", render: renderConcentration },
  { key: "quality", api: "join-quality", note: "an-quality-note", render: renderQuality },
  { key: "glove", api: "glove-crit-rate", note: "an-glove-note", render: renderGloveCrit },
  { key: "coverage", api: "coverage", note: "an-coverage-note", render: renderCoverage },
  { key: "dwell", api: "dwell", note: "an-dwell-note", render: renderDwell },
  { key: "activation", api: "activation", note: "an-act-note", render: renderActivation },
];

// section単位の世代番号。期間selectを連打すると、前の期間の応答が後から着いて新しい
// 期間のグラフを上書きしうる。応答を描く前に「自分が最後に投げた要求か」を確かめる。
const sectionGen = new Map();
let loadGen = 0;
let loadController = null;

function beginSection(key) {
  const gen = (sectionGen.get(key) || 0) + 1;
  sectionGen.set(key, gen);
  return gen;
}

function setStatus(text) {
  const el = document.getElementById("an-auto");
  if (el) el.textContent = text;
}

function finishedStatus(failed) {
  const at = new Date().toLocaleTimeString("ja-JP", { hour12: false });
  return `最終更新 ${at}` + (failed ? ` ／ 取得失敗 ${failed}件` : "");
}

// 取得中のsectionは注記を「取得中…」へ差し替える。前の期間の数字を残したままだと、
// どのsectionがまだ更新されていないのか画面から読めない。
function markLoading(section) {
  if (section.note) setNote(section.note, `<span class="an-muted">取得中…</span>`);
}

function requestSection(section, q, signal) {
  const gen = beginSection(section.key);
  return fetchJSON(`/api/analytics/${section.api}?${q}${section.extra ? section.extra() : ""}`, signal)
    .then((data) => {
      if (sectionGen.get(section.key) !== gen) return true;
      safeRender(section.key, section.render, data);
      return true;
    })
    .catch((err) => {
      if (sectionGen.get(section.key) !== gen) return true;
      // 取得失敗はcode不良ではなくserver側の状態。console.errorにするとpageの
      // 組み立てcheckが「JS error」として拾ってしまうためwarnに留め、画面へ出す。
      console.warn(`fetch ${section.key} failed`, err);
      // 失敗したpanelは前回描画が残る(stale)ため、note側で明示する。期間切替後に
      // 前の期間のグラフを今の期間の結果と誤認させない。
      if (section.note) {
        setNote(section.note, `<span class="an-warn">取得に失敗しました。グラフは前回の表示が残っている場合があります。</span>`);
      }
      return false;
    });
}

function loadAll() {
  const gen = (loadGen += 1);
  // 期間を変えた時点で古い要求は要らない。中断しないとserver側の重い集計を18本ぶん
  // 走らせたまま、次の18本を積み増すことになる。
  if (loadController) loadController.abort();
  loadController = new AbortController();
  const { signal } = loadController;
  const q = `days=${periodDays()}`;
  const total = SECTIONS.length;
  let done = 0;
  let failed = 0;
  setStatus(`更新中… 0/${total}`);
  SECTIONS.forEach(markLoading);
  SECTIONS.forEach((section) => {
    requestSection(section, q, signal).then((ok) => {
      if (gen !== loadGen) return;
      done += 1;
      if (!ok) failed += 1;
      setStatus(done < total ? `更新中… ${done}/${total}` : finishedStatus(failed));
    });
  });
}

// 時間帯インデックスは指標だけ差し替えれば良いので単独更新。
function loadTimeIndex() {
  const section = SECTIONS.find((s) => s.key === "time-index");
  markLoading(section);
  requestSection(section, `days=${periodDays()}`);
}

// section目次。本文が他sectionを番号で名指しするので、実在するsectionから組み立てる
// (手書きの目次は追加・削除で必ずずれる)。
const HEADING_CONTROL_TAGS = /^(SELECT|OPTION|INPUT|BUTTON|LABEL)$/;

// 見出しの文字。<select>を含むとoption文字列(「入室」「Comment」…)まで連結され、
// chipのtitleが選択肢の羅列になる。form controlだけを外し、見出しの一部であるspan
// (①の指標名)は残す。
function headingText(heading) {
  return Array.from(heading.childNodes)
    .filter((node) => node.nodeType === 3
      || (node.nodeType === 1 && !HEADING_CONTROL_TAGS.test(node.nodeName)))
    .map((node) => node.textContent)
    .join("")
    .replace(/\s+/g, " ")
    .trim();
}

function buildSectionIndex() {
  const nav = document.getElementById("an-index");
  if (!nav) return;
  nav.innerHTML = "";
  document.querySelectorAll("section[id^='an-s']").forEach((section) => {
    const heading = section.querySelector(".result-subtitle");
    if (!heading) return;
    const text = headingText(heading);
    const mark = (text.match(/■\s*(\S+)/) || [])[1];
    if (!mark) return;
    const link = document.createElement("a");
    link.href = `#${section.id}`;
    link.textContent = mark;
    link.title = text.replace(/^\s*■\s*/, "").trim();
    nav.appendChild(link);
  });
}

// 但し書き(#an-caveats)は畳んである。本文のlinkで飛ぶと閉じたsummary 1行に着地して
// 「何も無い」ように見えるため、飛ぶ前に開く。
function openDetailsTarget(hash) {
  if (!hash || hash.length < 2) return;
  const target = document.getElementById(hash.slice(1));
  if (target && target.tagName === "DETAILS") target.open = true;
}

document.addEventListener("click", (event) => {
  const el = event.target;
  const link = el && el.closest ? el.closest("a[href^='#']") : null;
  if (!link) return;
  openDetailsTarget(link.getAttribute("href"));
});
window.addEventListener("hashchange", () => openDetailsTarget(location.hash));

// ---- 期間・表示controlの永続化 ----
// 期間はURL(?days=)とlocalStorageの両方に残す。URLは貼ったlinkが同じ期間で開くため、
// localStorageは次に開いたときの既定値のため。他画面(overview/videos)と同じ作法。
function hasOption(select, value) {
  return Array.from(select.options).some((o) => o.value === String(value));
}

function syncPeriodUrl() {
  const url = new URL(location.href);
  // 既定(全期間)はURLへ書かない。navのlinkを踏んだだけでURLが書き換わると、
  // 「どこを開いているか」がlink先と一致しなくなる。選んだ期間だけを載せる。
  if (elPeriod.value === elPeriod.options[0].value) url.searchParams.delete("days");
  else url.searchParams.set("days", elPeriod.value);
  history.replaceState(history.state, "", `${url.pathname}${url.search}${location.hash}`);
}

function initPeriod() {
  const fromUrl = new URLSearchParams(location.search).get("days");
  const stored = localStorage.getItem(PERIOD_KEY);
  const wanted = [fromUrl, stored].find((v) => v != null && hasOption(elPeriod, v));
  if (wanted != null) elPeriod.value = String(wanted);
  syncPeriodUrl();
}

function bindViewToggle(el, key, rerender) {
  if (!el) return;
  el.checked = localStorage.getItem(key) === "1";
  el.addEventListener("change", () => {
    localStorage.setItem(key, el.checked ? "1" : "0");
    rerender();
  });
}

initPeriod();
buildSectionIndex();
openDetailsTarget(location.hash);

elPeriod.addEventListener("change", () => {
  localStorage.setItem(PERIOD_KEY, elPeriod.value);
  syncPeriodUrl();
  loadAll();
});
elTiMetric.addEventListener("change", loadTimeIndex);
document.getElementById("an-reload").addEventListener("click", loadAll);

// 見せ方だけのcontrolは再取得しない。直前の応答から描き直す。
bindViewToggle(elTiNumbers, TI_NUMBERS_KEY, () => {
  if (lastTimeIndex) safeRender("time-index", renderTimeIndex, lastTimeIndex);
});
bindViewToggle(elTiEmpty, TI_EMPTY_KEY, () => {
  if (lastTimeIndex) safeRender("time-index", renderTimeIndex, lastTimeIndex);
});
// WS接続はServer接続表示の維持のみ(重い集計を毎tick再計算しない)。
connectWS(() => {});
loadAll();
