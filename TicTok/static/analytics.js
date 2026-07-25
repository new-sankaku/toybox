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
let scatterChart = null;
let retentionHourChart = null;
let contextChart = null;
let battleFlowChart = null;
let dwellHourChart = null;
let activationChart = null;
const lorenzCharts = {};

const elPeriod = document.getElementById("an-period");
const elTiMetric = document.getElementById("an-ti-metric");

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

async function fetchJSON(path) {
  const res = await fetch(path);
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

function tiCellHTML(cell, dowLabel, hhmm) {
  if (!cell || cell.index == null || cell.n <= 0) {
    return `<div class="an-hm-cell an-hm-empty" title="${dowLabel} ${hhmm} データなし"></div>`;
  }
  const { bg, fg } = tiColor(cell.index);
  const title = `${dowLabel} ${hhmm} ×${cell.index.toFixed(2)} (観測${cell.n}本=配信×日)`;
  return `<div class="an-hm-cell" style="background:${bg};color:${fg}" title="${title}">${cell.index.toFixed(2)}</div>`;
}

function renderTimeIndex(data) {
  const slotsData = data.slots || [];
  document.getElementById("an-ti-note").innerHTML =
    `指標: <b>${METRIC_LABELS[data.metric] || data.metric}</b>`
    + ` &nbsp;観測 ${fmtNum(data.n_observations)}件 / 配信 ${fmtNum(data.n_sessions)}本`
    + ` &nbsp;<span class="an-hm-legend"><i>平均より少ない</i>`
    + `<span class="an-hm-bar"></span><i>多い</i>&nbsp;(中間=平均1.0)</span>`;

  const head = ['<div class="an-hm-rowh an-hm-corner">時刻</div>']
    .concat(TI_DOW.map((d) => `<div class="an-hm-h"${d.head ? ` style="color:${d.head}"` : ""}>${d.label}</div>`))
    .concat('<div class="an-hm-h an-hm-all">全部</div>')
    .join("");
  const body = slotsData
    .map((s) => {
      const hhmm = tiSlotLabel(s.minute);
      // 毎時(00分)の行だけ罫線で区切り、20分刻みを俯瞰しやすくする。
      const hourStart = s.minute % 60 === 0;
      const rh = hourStart ? "an-hm-rowh an-hm-hour" : "an-hm-rowh an-hm-quarter";
      const cells = TI_DOW.map((d) => tiCellHTML(s.dow && s.dow[d.src], d.label, hhmm)).join("");
      const all = tiCellHTML(s.all, "全曜日", hhmm).replace("an-hm-cell", "an-hm-cell an-hm-all");
      return `<div class="${rh}">${hhmm}</div>${cells}${all}`;
    })
    .join("");
  document.getElementById("an-ti-heatmap").innerHTML = head + body;
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
  if (b.per_min && n.per_min) {
    msg += ` <b>Battle中は平時の ${(b.per_min / n.per_min).toFixed(1)}倍</b>の速さで入室。`
      + `<span class="an-muted">この倍率は「盛り上がる時間帯にバトルをする」影響を含む参考値です。時間帯を補正したバトル自体の効果は③'を参照。</span>`;
  }
  if ((data.n_collabs || 0) === 0) {
    msg += ` <span class="an-warn">コラボ窓はまだ検出なし（収集は有効・コラボ配信の終了後に集計）。</span>`;
  }
  document.getElementById("an-context-note").innerHTML = msg;
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
  return `${p.pct >= 0 ? "+" : ""}${p.pct.toFixed(0)}%`;
}

// ---- ③ シェア→入室 ----
function renderShare(data) {
  const note = document.getElementById("an-share-note");
  if (!data || data.available === false) {
    note.innerHTML = `シェアのサンプルが不足しています（${fmtNum((data && data.n_events) || 0)}件）。`;
    return;
  }
  shareChart = renderPeri("an-share-chart", shareChart, data, "#a4502f");
  let msg =
    `シェア ${fmtNum(data.n_events)}回を集計（比較用 ${fmtNum(data.n_placebo)}件）。`
    + ` 入室はピークで <b>${peakPct(data)}</b>（${data.peak.lag >= 0 ? "+" : ""}${data.peak.lag}s、全期間の平均入室レート比）。`;
  if (data.pre_rise) {
    msg += ` <span class="an-warn">立ち上がりがシェアより前から始まるため、シェアが原因か結果かは断定できません。</span>`;
  }
  note.innerHTML = msg;
}

// ---- ③' バトル→入室(比較帯つき event-study) ----
function renderBattle(data) {
  const note = document.getElementById("an-battle-note");
  if (!data || data.available === false) {
    note.innerHTML = `バトルのサンプルが不足しています（${fmtNum((data && data.n_events) || 0)}件）。`;
    return;
  }
  battleChart = renderPeri("an-battle-chart", battleChart, data, "#4d6e6e");
  const ratio = ((data.ratio_metrics || {}).metrics || {}).joins || {};
  const ratioPct = ratio.median != null ? `${ratio.median >= 1 ? "+" : ""}${((ratio.median - 1) * 100).toFixed(0)}%` : "—";
  // 有意判定は「開始後(lag>0)」かつ「増加」のbinのみ。開始前の上振れは効果でなく
  // 交絡/先行入室であり、含めると効果ゼロでも「明確な入室増あり」と誤断言してしまう。
  const lags = data.lags || [];
  const up = data.uplift || [];
  const anySig = (data.sig || []).some((s, i) => s && lags[i] > 0 && (up[i] || 0) > 0);
  let msg = `バトル ${fmtNum(data.n_events)}回を集計（比較用 ${fmtNum(data.n_placebo)}件）。ピーク <b>${peakPct(data)}</b>（全期間の平均入室レート比）。`;
  msg += anySig
    ? ` 開始後に比較帯を超える明確な入室増あり。`
    : ` <b>比較帯の内側</b>で、入室の明確な増加は見られません。`;
  if (data.pre_rise) {
    msg += ` <span class="an-warn">立ち上がりがバトル開始より前から始まっており、「盛り上がりが先・バトルが後」の可能性があります。バトルが原因とは断定できません。</span>`;
  }
  msg += ` <span class="an-muted">参考: 単純な倍率では入室 ${ratioPct} ですが、盛り上がった時間帯の影響を含むため過大です。</span>`;
  note.innerHTML = msg;
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
  const note = document.getElementById("an-glove-note");
  if (!data.total_gifts) {
    note.innerHTML =
      `自陣(監視配信者)へ届いたグローブ窓中の判定済ギフトはまだありません`
      + `（グローブ窓 ${fmtNum(data.n_windows)}回）。`
      + `この指標は<b>今後のバトル収集から蓄積</b>されます。`;
    return;
  }
  const oc = data.overall_ci;
  note.innerHTML =
    `グローブ窓 ${fmtNum(data.n_windows)}回 / 判定済ギフト ${fmtNum(data.total_gifts)}件 中 ${fmtNum(data.total_crits)}件が5倍(全体 <b>${overall}</b>${oc ? `、95%CI ${oc[0]}〜${oc[1]}%` : ""})。`
    + (data.undecided ? ` 判定不能(5倍か通常か確定できず)で分母から除外 ${fmtNum(data.undecided)}件。` : "")
    + (data.unresolved ? ` 単価不明で除外 ${fmtNum(data.unresolved)}件。` : "")
    + (data.range_out ? ` コイン帯範囲外 ${fmtNum(data.range_out)}件。` : "");

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

// ---- ④ 指標間の関連(相関行列・配信単位) ----
function corrColor(v) {
  if (v == null) return "transparent";
  const a = Math.min(1, Math.abs(v)) * 0.8;
  return v >= 0 ? `rgba(169, 110, 73, ${a})` : `rgba(77, 110, 110, ${a})`;
}
function renderMatrix(data) {
  const metrics = data.metrics || [];
  const table = document.getElementById("an-matrix");
  let html = "<thead><tr><th></th>";
  metrics.forEach((m) => (html += `<th>${METRIC_LABELS[m]}</th>`));
  html += "</tr></thead><tbody>";
  const partial = data.partial || {};
  const sigM = data.sig || {};
  metrics.forEach((row) => {
    html += `<tr><th>${METRIC_LABELS[row]}</th>`;
    metrics.forEach((col) => {
      const v = data.matrix[row][col];
      const txt = v == null ? "-" : v.toFixed(2);
      const p = (partial[row] || {})[col];
      // 対角・同接列以外は偏相関(規模・配信長制御)をかっこ内に併記する。
      const pTxt = row === col || p == null ? "" : `<span class="an-cell-sub">(${p.toFixed(2)})</span>`;
      // 配信本数に対して有意でない相関は、色・強調なしの参考値として出す。
      // 小標本の順位相関は偶然±1近くへ振れやすく、濃色は断定に見えるため。
      const sig = (sigM[row] || {})[col];
      const insig = v != null && sig === false;
      const strong = v != null && !insig && Math.abs(v) >= 0.5 ? " an-strong" : "";
      const title = `${METRIC_LABELS[row]}×${METRIC_LABELS[col]}: 素 ${txt}${p != null ? ` / 規模・配信長制御 ${p.toFixed(2)}` : ""}${insig ? "（配信本数が少なく有意でない・参考値）" : ""}`;
      html += `<td class="an-cell${strong}" style="background:${insig ? "transparent" : corrColor(v)}" title="${title}">${txt}${pTxt}</td>`;
    });
    html += "</tr>";
  });
  html += "</tbody>";
  table.innerHTML = html;
  document.getElementById("an-matrix-note").innerHTML =
    `配信 ${fmtNum(data.n_sessions)}本で集計。<span class="an-sw-pos">■</span>正の相関（一緒に増える） <span class="an-sw-neg">■</span>負の相関（逆）。濃いほど関連が強い。色なしのセルは配信本数に対して<b>有意でない参考値</b>。`
    + ` かっこ内は<b>同接(規模)と配信の長さを制御した偏相関</b>＝「大きい・長い配信は何でも多い」分を除いた値。`;
}

// ---- ⑤ 入室 → 定着 ----
function renderRetention(data) {
  const o = data.overall || {};
  const lift = o.lift_per_join;
  const liftTxt = lift == null ? "-" : `${lift >= 0 ? "+" : ""}${lift.toFixed(2)}`;
  document.getElementById("an-retention-note").innerHTML =
    `配信 ${fmtNum(data.n_sessions || 0)}本・入室 ${fmtNum(o.joins)}件。<b>1入室あたり同接 ${liftTxt}人の押し上げ</b>（入室のない時間の自然な増減を差し引いた推定）。`
    + `<span class="an-muted">入室は同一人物の再入室・TikTok側の間引きを含む概算、同接は匿名視聴者を含むため、厳密な定着率ではありません。</span>`
    + ` 時刻別は入室の速さ(棒・件/分)と平均同接(線)。`;

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
  return v == null ? "-" : `${(v * 100).toFixed(0)}%`;
}

function renderDwell(data) {
  const o = data.overall;
  const kpi = document.getElementById("an-dwell-kpi");
  const cells = o
    ? [
      ["平均滞在(中央値)", dwellSeconds(o.dwell_seconds)],
      ["1時間あたりの入れ替わり", `${o.turnover_per_hour}回`],
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

  const table = document.getElementById("an-dwell-streamers");
  const streamers = data.streamers || [];
  let html = "<thead><tr><th>配信者</th><th class=\"num\">配信数</th><th class=\"num\">滞在時間(中央値)</th>"
    + "<th class=\"num\">平均±95%CI</th><th class=\"num\">入れ替わり/時</th><th class=\"num\">同接(中央値)</th>"
    + "<th class=\"num\">入れ替わりが速い時間</th><th class=\"num\">居座りの時間</th></tr></thead><tbody>";
  if (!streamers.length) {
    html += `<tr><td colspan="8" class="an-muted">推定に足りる配信がまだありません。</td></tr>`;
  }
  streamers.forEach((s) => {
    const mix = s.mix || {};
    html += `<tr><th class="ident">${anEscape(s.unique_id)}</th>`
      + `<td class="num">${fmtNum(s.sessions)}</td>`
      + `<td class="num">${dwellSeconds(s.dwell_seconds)}</td>`
      + `<td class="num">${dwellSeconds(s.mean)}${s.ci == null ? "" : ` ±${s.ci.toFixed(0)}秒`}</td>`
      + `<td class="num">${s.turnover_per_hour == null ? "-" : `${s.turnover_per_hour}回`}</td>`
      + `<td class="num">${s.avg_viewers}</td>`
      + `<td class="num">${dwellPct(mix.churn)}</td>`
      + `<td class="num">${dwellPct(mix.sticky)}</td></tr>`;
  });
  table.innerHTML = `${html}</tbody>`;

  const rejects = data.rejects || {};
  const rejectText = Object.keys(DWELL_REJECT_LABELS)
    .filter((k) => rejects[k])
    .map((k) => `${DWELL_REJECT_LABELS[k]} ${fmtNum(rejects[k])}`)
    .join(" / ") || "なし";
  const cross = data.cross_check || {};
  const eng = data.engagement || {};
  let note = `対象 ${fmtNum(data.n_sessions || 0)}本のうち<b>推定できたのは ${fmtNum(data.n_estimated || 0)}本</b>。`
    + ` 5分窓 ${fmtNum(data.candidates || 0)}個中 ${fmtNum(data.windows || 0)}個を採用し、`
    + `<b>残りは推定不能</b>として除外しました（内訳: ${anEscape(rejectText)}）。`
    + ` <span class="an-muted">時刻別のグラフで<b>薄い棒は窓が${fmtNum(minWindows)}個未満</b>の参考値です（深夜帯は観測そのものが少なく、数本の配信で決まります）。</span>`;
  if (data.crude_dwell_seconds != null) {
    note += ` <span class="an-muted">窓を切らずに配信まるごとで計算した粗い値は ${dwellSeconds(data.crude_dwell_seconds)}（${fmtNum(data.crude_n || 0)}本）で、上の推定と同程度です。</span>`;
  }
  if (cross.ratio != null) {
    // 来場カウンタの正体は非公開のため、独立に届く入室eventとの比を必ず添える。
    note += ` <span class="an-muted">来場カウンタの伸びに対する入室eventの比は中央値 ${cross.ratio.toFixed(2)}（配信間で ${cross.p10.toFixed(2)}〜${cross.p90.toFixed(2)}・${fmtNum(cross.n || 0)}本）。`
      + `比が配信をまたいで揃っているため到着の代理として扱えますが、入室eventを基準に取り直せば滞在時間は約${((1 / cross.ratio - 1) * 100).toFixed(0)}%長く出ます。絶対秒に幅があるのはこのためです。</span>`;
  }
  if (eng.rho != null) {
    note += eng.significant
      ? ` <span class="an-muted">妥当性check: 滞在が長いと推定された配信ほど視聴時間あたりのCommentも多い傾向（同接を統制した偏順位相関 ρ=${eng.rho.toFixed(2)}・n=${fmtNum(eng.n)}・有意）。</span>`
      : ` <span class="an-warn">妥当性check: 視聴時間あたりのCommentとの関連は ρ=${eng.rho.toFixed(2)}（n=${fmtNum(eng.n)}）で有意ではありません。滞在時間の推定が別の指標から裏付けられてはいない点に留意してください。</span>`;
  }
  document.getElementById("an-dwell-note").innerHTML = note;
}

// ---- ⑬ いつもと違う配信(session間の水準比較) ----
// 逸脱の大きさ(z)と有意性は別物として扱う。経験p値の下限はbaseline本数で決まるため、
// 多重検定を通せないことが構造的に確定する。そこを曖昧にすると、ただの重い裾を
// 「統計的に検出された異常」として読ませてしまう。
function anomValue(metric, v) {
  if (v == null) return "-";
  if (metric === "follow_per_join") return `${(v * 100).toFixed(2)}%`;
  if (metric === "viewers_med") return `${v.toFixed(1)}人`;
  return v >= 100 ? v.toFixed(0) : v.toFixed(2);
}

function anomDirection(z) {
  return z >= 0
    ? `<span class="an-warn">▲ 多い</span>`
    : `<span class="an-muted">▼ 少ない</span>`;
}

function renderAnomaly(data) {
  const power = data.power || {};
  const cp = data.changepoints || {};
  const cells = [
    ["対象配信", `${fmtNum(data.n_measured || 0)} / ${fmtNum(data.n_sessions || 0)}本`],
    ["検定数", fmtNum(power.tests || 0)],
    ["統計的に有意", `${fmtNum(data.n_significant || 0)}件`],
    ["水準が変わった配信", `${fmtNum((cp.shifts || []).length)} / ${fmtNum(cp.tested || 0)}本`],
  ];
  document.getElementById("an-anom-kpi").innerHTML = cells
    .map(([k, v]) => `<div class="a-chip"><span class="l">${anEscape(k)}</span><span class="v">${v}</span></div>`)
    .join("");

  const findings = (data.findings || []).slice(0, 20);
  let html = "<thead><tr><th>配信</th><th>配信者</th><th>指標</th><th>向き</th>"
    + "<th class=\"num\">この配信</th><th class=\"num\">いつも(中央値)</th><th class=\"num\">いつもの範囲(P25-P75)</th>"
    + "<th class=\"num\">逸脱(z)</th><th class=\"num\">比較対象</th></tr></thead><tbody>";
  if (!findings.length) {
    html += `<tr><td colspan="9" class="an-muted">比較できる配信がまだありません。</td></tr>`;
  }
  findings.forEach((f) => {
    // session idはdeep link(?session=)が既にあるのに素のtextだった。「いつもと違う」と
    // 分かってもその配信を見に行く手段が画面上に無かったので、実物へ繋ぐ。
    html += `<tr><th>${fmtYmd(f.started_at)} `
      + `<a class="an-muted" href="/history?session=${f.session_id}"`
      + ` title="このSessionの詳細を開きます。">#${f.session_id}</a></th>`
      + `<td class="ident">${anEscape(f.unique_id)}</td>`
      + `<td>${anEscape(f.label || f.metric)}</td>`
      + `<td>${anomDirection(f.z)}</td>`
      + `<td class="num">${anomValue(f.metric, f.value)}</td>`
      + `<td class="num">${anomValue(f.metric, f.typical)}</td>`
      + `<td class="num an-muted">${anomValue(f.metric, f.p25)} 〜 ${anomValue(f.metric, f.p75)}</td>`
      + `<td class="num">${f.z > 0 ? "+" : ""}${f.z}</td>`
      + `<td class="num an-muted">${fmtNum(f.baseline)}本</td></tr>`;
  });
  document.getElementById("an-anom-findings").innerHTML = `${html}</tbody>`;

  // 判定不能の配信者・指標は、件数を0にせず理由付きで出す。
  const short = (data.coverage || []).filter((c) => c.status === "insufficient");
  let note = `<b>逸脱の大きい順</b>に上位${fmtNum(findings.length)}件を出しています。`
    + ` 対象は ${fmtNum(data.n_measured || 0)}本（30分未満の配信、相互作用eventが${fmtNum(100)}件未満の配信は、水準を比べる材料が足りないため除外）。`;
  if (short.length) {
    const names = [...new Set(short.map((c) => c.unique_id))];
    note += ` <span class="an-warn">判定不能: ${anEscape(names.join(" / "))}</span>`
      + ` <span class="an-muted">（比較に必要な過去配信が${fmtNum(data.min_baseline || 0)}本に届かないため、この配信者は一切判定していません）</span>`;
  }
  if (power.tests) {
    note += `<br /><b class="an-warn">なぜ「統計的に有意」が${fmtNum(data.n_significant || 0)}件なのか</b>: `
      + `比較は分布の形を仮定せず、過去の配信のうち何本が同じくらい離れているかで測ります。`
      + `この方法で出せる最小のp値は<b>1÷(比較対象の本数+1)</b>までで、実際の最小値は <b>${power.best_p}</b> でした。`
      + `一方 ${fmtNum(power.tests)}件を同時に検定するため、偽陽性を${((data.fdr_q || 0) * 100).toFixed(0)}%に抑える（Benjamini-Hochberg法）には <b>${power.needed_p}</b> 以下が必要です。`
      + ` つまり有意判定を出すには1配信者あたり<b>${fmtNum(power.needed_baseline)}本</b>の過去配信が要る計算で、<b>現実には到達しません</b>。`
      + ` <span class="an-muted">正規分布を仮定したp値ならいくらでも小さい値を出せますが、この指標の実測の裾は正規より|z|>3で約13倍・|z|>4で約375倍も厚く、当てはめると「ただの重い裾」を有意な異常として大量に報告することになるため採用していません。上の表は探索用の並べ替えとしてお使いください。</span>`;
  }
  document.getElementById("an-anom-note").innerHTML = note;

  const shifts = cp.shifts || [];
  let sh = "<thead><tr><th>配信</th><th>配信者</th><th>変わった時刻</th>"
    + "<th class=\"num\">前</th><th class=\"num\">後</th><th class=\"num\">変化</th><th class=\"num\">p</th><th class=\"num\">観測</th></tr></thead><tbody>";
  if (!shifts.length) {
    sh += `<tr><td colspan="8" class="an-muted">明確な水準shiftのある配信はありません。</td></tr>`;
  }
  shifts.forEach((s) => {
    const pct = s.ratio == null ? "-" : `${(s.ratio * 100).toFixed(0)}%`;
    const dir = s.ratio != null && s.ratio < 1
      ? `<span class="an-warn">▼ ${pct}</span>`
      : `<span class="an-muted">▲ ${pct}</span>`;
    sh += `<tr><th>${fmtYmd(s.started_at)} <span class="an-muted">#${s.session_id}</span></th>`
      + `<td class="ident">${anEscape(s.unique_id)}</td>`
      + `<td>${fmtTime(s.at)}</td>`
      + `<td class="num">${s.before.toFixed(1)}人</td>`
      + `<td class="num">${s.after.toFixed(1)}人</td>`
      + `<td class="num">${dir}</td>`
      + `<td class="num an-muted">${s.p}</td>`
      + `<td class="num an-muted">${fmtNum(s.bins)}区間</td></tr>`;
  });
  document.getElementById("an-anom-shifts").innerHTML = `${sh}</tbody>`;
  document.getElementById("an-anom-shift-note").innerHTML =
    `同接の記録がある ${fmtNum(cp.tested || 0)}本を調べ、統計的に変化点が認められたのは ${fmtNum(cp.significant || 0)}本、`
    + `そのうち<b>水準の変化が実用上はっきりしているものだけ</b>（4分の3以下に下がった、または1.35倍以上に上がった）を ${fmtNum(shifts.length)}本表示しています。`
    + ` <span class="an-muted">${fmtNum(cp.bin_seconds ? cp.bin_seconds / 60 : 0)}分ごとに区切って判定し、比較用の並べ替えは${fmtNum(cp.block_bins || 0)}区間（自己相関がほぼ消える長さ）のかたまり単位で行っています。切断などで観測が途切れた区間は0人で埋めず、その区間ごと判定から外しています（0で埋めると、切断を「同接0への急落」として検出してしまいます）。</span>`;
}

// ---- ⑭ 入室後の初回反応(activation funnel) ----
// 反応率と素通り率は同じ値の裏返しなので、両方を出しつつ「母集団が入室eventの
// 記録された人に限られる」ことを必ず添える。入室の取りこぼしはengaged側へ偏っており、
// 素通り率は上限、反応率は下限として読む必要がある。
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

  let html = "<thead><tr><th>入室からの経過</th><th class=\"num\">反応した割合(いいね含む)</th>"
    + "<th class=\"num\">95%信頼区間</th><th class=\"num\">反応した割合(いいね除く)</th><th class=\"num\">95%信頼区間</th></tr></thead><tbody>";
  const nlByH = {};
  (nl.horizons || []).forEach((h) => { nlByH[h.seconds] = h; });
  (wl.horizons || []).forEach((h) => {
    const n = nlByH[h.seconds] || {};
    const ci = (x) => (x && x.ci ? `${actPct(x.ci[0], 2)} 〜 ${actPct(x.ci[1], 2)}` : "-");
    html += `<tr><th>${actSeconds(h.seconds)}後まで</th>`
      + `<td class="num">${actPct(h.activated, 2)}</td>`
      + `<td class="num an-muted">${ci(h)}</td>`
      + `<td class="num">${actPct(n.activated, 2)}</td>`
      + `<td class="num an-muted">${ci(n)}</td></tr>`;
  });
  document.getElementById("an-act-table").innerHTML = `${html}</tbody>`;

  let note = `対象 ${fmtNum(data.n_sessions || 0)}配信・${fmtNum(data.n_persons || 0)}人`
    + `（1人が同じ配信に入り直した場合は1人として数えます）。`
    + `信頼区間は配信を単位にした再抽出 ${fmtNum(data.bootstrap || 0)}回から求めています。`;
  if (wl.median_latency != null) {
    note += ` <span class="an-muted">反応する人は<b>早い段階で反応します</b>。反応した人に限った中央値は`
      + `${actSeconds(wl.median_latency)}（いいねを除くと${actSeconds(nl.median_latency)}）で、`
      + `最終的な反応の大半は入室から1分以内に起きています。なお<b>全体の中央値は存在しません</b>`
      + `（9割が最後まで反応しないため、曲線が50%に届きません）。</span>`;
  }
  if (cov) {
    // 母集団の欠けは、この指標の最大の弱点なので必ず数値で出す。
    note += `<br /><b class="an-warn">この割合は「入室が記録された人」だけの値です。</b>`
      + ` 実際に反応があった ${fmtNum(cov.actors)}人のうち、入室eventが残っているのは`
      + ` <b>${fmtNum(cov.actors_with_join)}人（${actPct(cov.ratio)}）</b>で、残り ${fmtNum(cov.missing)}人は`
      + `反応しているのに入室が記録されていません。`;
    if (cov.gifter_ratio != null) {
      note += ` しかも<b>ギフトを送った人に限ると入室が残っているのは ${actPct(cov.gifter_ratio)}</b>`
        + `（${fmtNum(cov.gifters_with_join)}/${fmtNum(cov.gifters)}人）にとどまり、`
        + `<b>取りこぼしは熱心な視聴者ほど多い</b>ことが分かります。`;
    }
    note += ` <span class="an-muted">つまり母集団から熱心な層が抜けているため、上の反応率は<b>下限</b>、`
      + `素通り率は<b>上限</b>として読んでください。視聴者全体の反応率はこれより高いはずです。</span>`;
  }
  document.getElementById("an-act-note").innerHTML = note;
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
    .map((t) => `<div class="a-chip"><span class="l">上位${t.pct}%(${fmtNum(t.users)}人)</span><span class="v">${(t.share * 100).toFixed(0)}%</span></div>`)
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
  const pct = (x) => `${((x || 0) * 100).toFixed(0)}%`;
  document.getElementById("an-organic-note").innerHTML =
    `配信 ${fmtNum(data.n_sessions || 0)}本を集計。全入室 ${fmtNum(t.raw || 0)}件 → ノイズ除去後 ${fmtNum(Math.round(t.organic || 0))}件相当。`
    + ` 再訪した人 <b>${pct(data.returning_ratio)}</b> ／ 入室後に反応した人 <b>${pct(data.engaged_ratio)}</b>`
    + ` ／ シェア直後の流入 <b>${pct(data.share_window_ratio)}</b>`
    + (data.stick_rate != null ? ` ／ 定着率 <b>${pct(data.stick_rate)}</b>` : "")
    + `。<span class="an-hm-legend"><i>生の入室</i><span class="an-hm-bar"></span><i>ノイズ除去後</i></span>`;

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

function entryRatio(ratio) {
  return ratio == null ? "-" : `${(ratio * 100).toFixed(1)}%`;
}

function fillEntryTable(id, header, rows, emptyText) {
  const table = document.getElementById(id);
  if (!table) return;
  if (!rows.length) {
    table.innerHTML = `<tbody><tr><td class="an-muted">${anEscape(emptyText)}</td></tr></tbody>`;
    return;
  }
  let html = `<thead><tr><th>${anEscape(header)}</th><th>件数</th><th>構成比</th></tr></thead><tbody>`;
  rows.forEach((r) => {
    html += `<tr><th>${anEscape(r.label)}</th><td>${fmtNum(r.count)}</td><td>${entryRatio(r.ratio)}</td></tr>`;
  });
  table.innerHTML = `${html}</tbody>`;
}

function renderEntrySource(data) {
  const joins = data.joins || {};
  const engaged = data.engaged || {};
  const follow = joins.follow || {};
  fillEntryTable(
    "an-entry-src", "流入元",
    (joins.sources || []).map((r) => ({ label: r.key, count: r.count, ratio: r.ratio })),
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
  document.getElementById("an-entry-note").innerHTML =
    `配信 ${fmtNum(data.n_sessions || 0)}本のうち ${fmtNum(data.n_sessions_measured || 0)}本で値を取得。`
    + ` 入室 ${fmtNum(joins.total || 0)}件中 <b>流入元が届いたのは ${fmtNum(joins.measured || 0)}件（取得率 ${cov(joins.coverage)}）</b>`
    + `、フォロー関係は ${fmtNum(follow.measured || 0)}件（取得率 ${cov(follow.coverage)}）。`
    + ` Comment/Gift ${fmtNum(engaged.total || 0)}件中 ${fmtNum(engaged.measured || 0)}件（取得率 ${cov(engaged.coverage)}）で配信者との関係を取得。`
    + roleText("sub", "うちサブスク") + roleText("mod", "モデレータ") + roleText("gg", "ギフト経験者")
    + ` <span class="an-muted">構成比の分母は値が届いた分のみです。届かなかった分（この機能より前に収集した入室）は構成比に含めていません。</span>`;
}

// ---- ⑦ 入室の質(新規/常連) ----
function renderQuality(data) {
  const byHour = data.hours || [];
  const labels = byHour.map((h) => String(h.hour));
  const news = byHour.map((h) => h.new);
  const rets = byHour.map((h) => h.returning);
  const ratio = byHour.map((h) => (h.total > 0 ? h.new_ratio * 100 : null));
  document.getElementById("an-quality-note").innerHTML =
    `配信 ${fmtNum(data.n_sessions || 0)}本・入室 ${fmtNum(data.total)}人（時間帯ごとのユニーク人数・同一時間帯の再入室は1人と数える）中、新規 ${fmtNum(data.new)}人（新規率 ${((data.new_ratio || 0) * 100).toFixed(0)}%）。`
    + (data.excluded ? ` 識別できない入室 ${fmtNum(data.excluded)}件は除外。` : "")
    + ` <span class="an-muted">「新規」はこの監視で初めて観測した人。監視を始めた直後は以前からの常連も新規に数えられて高めに出ます。他の監視配信者で観測済みの人は常連扱いです。</span>`;

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

// ---- ⑧ 規模 vs 効率(バブル) ----
// 対数軸の既定範囲はdataの両端と一致するため、端の配信者のbubbleが軸線で半分切れる。
// 対数軸なので余白は加算でなく倍率で取る。
const SCATTER_X_MARGIN = 1.25;

function renderScatter(data) {
  const streamers = data.streamers || [];
  const maxSessions = Math.max(1, ...streamers.map((s) => s.sessions));
  const points = streamers.map((s) => ({
    x: s.avg_viewers,
    y: s.coins_per_viewer_hour,
    r: 5 + 14 * Math.sqrt(s.sessions / maxSessions),
    _s: s,
  }));
  const effs = points.map((p) => p.y);
  const effMax = effs.length ? Math.max(...effs) : 0;
  const effMin = effs.length ? Math.min(...effs) : 0;
  document.getElementById("an-scatter-note").textContent =
    `${fmtNum(streamers.length)}配信者。右＝規模が大きい（平均同接・対数軸）、上＝視聴1人・1時間あたりのコインが多い。バブル大＝配信回数が多い。`
    + ` 効率は ${fmtNum(Math.round(effMin))}〜${fmtNum(Math.round(effMax))} と開きがあり、縦軸の上限は最も効率の高い1者が決めています。`
    + ` 配信者が少ないうちは位置関係のばらつきが大きいため、順位ではなく大まかな位置として見てください。`;
  const dataset = {
    label: "配信者",
    data: points,
    backgroundColor: "rgba(169, 110, 73, 0.5)",
    borderColor: "#8e4f2f",
    borderWidth: 1,
  };
  const xs = points.map((p) => p.x);
  const xMin = xs.length ? Math.max(1, Math.floor(Math.min(...xs) / SCATTER_X_MARGIN)) : undefined;
  const xMax = xs.length ? Math.ceil(Math.max(...xs) * SCATTER_X_MARGIN) : undefined;
  if (scatterChart) {
    scatterChart.data.datasets[0].data = points;
    scatterChart.options.scales.x.min = xMin;
    scatterChart.options.scales.x.max = xMax;
    scatterChart.update();
    return;
  }
  scatterChart = new Chart(document.getElementById("an-scatter-chart"), {
    type: "bubble",
    data: { datasets: [dataset] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      scales: {
        // 規模は右歪み(少数の大手が桁違い)のため対数軸。線形だと大多数が原点に潰れる。
        // 効率は0の配信者(コイン0)が入るため対数にできない。対数化すると0が描けず黙って
        // 1者消えるので線形のまま。上部の空白は「1者だけ突出」という実態そのもの。
        x: { type: "logarithmic", min: xMin, max: xMax, ticks: nierTicks(), grid: { color: NIER_GRID_COLOR }, title: { display: true, text: "平均同接(規模・配信ごとの中央値/対数軸)", color: NIER_AXIS_COLOR, font: { family: "monospace", size: 10 } } },
        y: { beginAtZero: true, ticks: nierTicks(), grid: { color: NIER_GRID_COLOR }, title: vAxisTitle("コイン/同接・時間(効率)") },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          ...nierTooltip(),
          callbacks: {
            label: (item) => {
              const s = item.raw._s;
              return `${s.nickname} @${s.unique_id} · 平均同接${fmtNum(s.avg_viewers)} · ${fmtCompact(s.coins)}コイン · 効率${s.coins_per_viewer_hour} · ${fmtNum(s.sessions)}配信`;
            },
          },
        },
      },
    },
  });
}

// ---- ⑩ バトルの展開(残り時間軸) ----
// 除外理由のlabel。相手が一意に定まらない試合を混ぜるとリード交代が無意味になるため、
// 何をどれだけ外したかを必ず見せる。
const BF_EXCLUDE_LABELS = {
  chimera: "相手を特定できない",
  no_series: "得点の推移が無い",
  no_end: "終了時刻が無い",
  short: "短すぎる",
  aborted: "不成立",
  parse: "読めない記録",
};
const BF_FORM_LABELS = { "1v1": "1対1", team: "チーム戦", multi: "個人マルチ(復元)" };

function bfPct(v) {
  return v == null ? "-" : `${(v * 100).toFixed(1)}%`;
}

function bfCi(r) {
  if (!r || !r.n) return "-";
  const ci = r.ci ? `（95%区間 ${r.ci[0]}〜${r.ci[1]}%）` : "";
  return `${bfPct(r.rate)}${ci}`;
}

function renderBattleFlow(data) {
  const cp = data.checkpoint || {};
  const tail = data.tail || {};
  const raw = tail.raw || {};
  const adj = tail.adjusted || {};
  const forms = data.forms || {};
  const excluded = data.excluded || {};
  const lead = data.lead_changes || {};

  const formText = Object.keys(BF_FORM_LABELS)
    .filter((k) => forms[k])
    .map((k) => `${BF_FORM_LABELS[k]} ${fmtNum(forms[k])}戦`)
    .join(" / ") || "対象なし";
  const excludeText = Object.keys(BF_EXCLUDE_LABELS)
    .filter((k) => excluded[k])
    .map((k) => `${BF_EXCLUDE_LABELS[k]} ${fmtNum(excluded[k])}戦`)
    .join("・");
  const typeText = raw.n
    ? `終盤型 ${fmtNum(raw.heavy)}戦 / 平坦 ${fmtNum(raw.flat)}戦 / 序中盤型 ${fmtNum(raw.light)}戦`
    : "-";
  document.getElementById("an-bf-note").innerHTML =
    `バトル ${fmtNum(data.n_battles || 0)}戦のうち <b>${fmtNum(data.n_eligible || 0)}戦</b>を集計（${anEscape(formText)}）。`
    + (excludeText ? ` 対象外 ${fmtNum((data.n_battles || 0) - (data.n_eligible || 0))}戦（${anEscape(excludeText)}）。` : "")
    + ` リードの入れ替わりは中央値 ${lead.median == null ? "-" : lead.median}回（最大 ${lead.max == null ? "-" : lead.max}回・n=${fmtNum(lead.n || 0)}）。`
    + ` <b>最後の${tail.seconds || 0}秒に入った自陣の得点は中央値 ${bfPct(raw.median)}</b>（均等なら ${bfPct(raw.uniform_median)}・n=${fmtNum(raw.n || 0)}）、`
    + `グローブ(5倍)の上乗せを差し引くと ${bfPct(adj.median)}（n=${fmtNum(adj.n || 0)}）。`
    + ` 内訳は ${anEscape(typeText)}。`
    + (tail.unresolved_battles
      ? ` <span class="an-muted">${fmtNum(tail.unresolved_battles)}戦は5倍かどうか判定できないギフトを含むため、差し引き後の値は控えめ（差し引き不足）に出ます。</span>`
      : "")
    + ` <span class="an-muted">${fmtNum(data.min_duration_seconds || 0)}秒未満のバトルは残り時間の区切りが埋まらないため除いています。勝敗は履歴画面と同じ<b>PK確定時点</b>の判定で、TikTokから最後に届いたスコア（PK後に相手が枠から抜けた後の値）とは ${fmtNum(data.result_diff || 0)}戦で食い違いますが、画面間の食い違いはありません。</span>`;

  const leadTable = document.getElementById("an-bf-lead");
  if (leadTable) {
    const rows = [
      [`残り${cp.seconds || 0}秒でリード`, cp.own],
      [`残り${cp.seconds || 0}秒でビハインド`, cp.opp],
      [`残り${cp.seconds || 0}秒で同点`, cp.tie],
    ];
    let html = `<thead><tr><th>残り${cp.seconds || 0}秒の状況</th><th>試合数</th><th>うち勝ち</th><th>勝率</th></tr></thead><tbody>`;
    rows.forEach(([label, r]) => {
      const v = r || {};
      html += `<tr><th>${anEscape(label)}</th><td>${fmtNum(v.n || 0)}</td><td>${fmtNum(v.k || 0)}</td><td>${bfCi(v)}</td></tr>`;
    });
    const cb = cp.comeback || {};
    html += `<tr><th>結果がひっくり返った</th><td>${fmtNum(cb.n || 0)}</td><td>${fmtNum(cb.k || 0)}</td><td>${bfCi(cb)}</td></tr>`;
    leadTable.innerHTML = `${html}</tbody>`;
  }

  // 残り時間は「終盤が右」になるよう反転して並べる(左=序盤・右=終了直前)。
  const bins = (data.bins || []).slice().reverse();
  const labels = bins.map((b) => `残り${b.to}〜${b.from}秒`);
  const pooled = bins.map((b) => (b.share == null ? null : b.share * 100));
  const median = bins.map((b) => (b.median_share == null ? null : b.median_share * 100));
  const datasets = [
    { type: "bar", label: "合計比", data: pooled, backgroundColor: "#a4502f", yAxisID: "y" },
    { type: "line", label: "試合ごとの中央値", data: median, borderColor: "#9b8c52", backgroundColor: "#9b8c52", borderWidth: 2, pointRadius: 2, tension: 0.25, yAxisID: "y", spanGaps: true },
  ];
  if (battleFlowChart) {
    battleFlowChart.data.labels = labels;
    battleFlowChart.data.datasets[0].data = pooled;
    battleFlowChart.data.datasets[1].data = median;
    battleFlowChart.update();
    return;
  }
  battleFlowChart = new Chart(document.getElementById("an-bf-chart"), {
    type: "bar",
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      scales: {
        x: { ticks: { ...nierTicks(), autoSkip: false }, grid: { color: NIER_GRID_COLOR }, title: { display: true, text: "終了までの残り時間", color: NIER_AXIS_COLOR, font: { family: "monospace", size: 10 } } },
        y: { beginAtZero: true, ticks: nierTicks(), grid: { color: NIER_GRID_COLOR }, title: vAxisTitle("自陣得点のシェア(%)") },
      },
      plugins: {
        legend: { labels: { color: "#4d4a3f", font: { family: "monospace", size: 11 }, boxWidth: 14, boxHeight: 8 } },
        tooltip: {
          ...nierTooltip(),
          callbacks: {
            afterBody: (items) => {
              const b = bins[items[0].dataIndex];
              return b ? `対象 ${fmtNum(b.n)}戦` : "";
            },
          },
        },
      },
    },
  });
}

// ---- ⑪ 収集の取得率 ----
// 値が測れない指標は0ではなく「計測不能」と書く(0は「穴が無い」という別の主張になる)。
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
      gaps.n_sessions ? `1配信あたり中央値 ${cvSeconds(gapSec.median)}（配信時間の ${gapRatio.median == null ? "-" : gapRatio.median.toFixed(2)}%・最大 ${cvSeconds(gapSec.max)}）` : cvUnmeasured("切断の記録がある配信がまだありません。"),
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
  const table = document.getElementById("an-coverage");
  if (table) {
    let html = "<thead><tr><th>指標</th><th>値</th><th>対象</th><th>注記</th></tr></thead><tbody>";
    rows.forEach(([label, value, n, note]) => {
      html += `<tr><th>${anEscape(label)}</th><td>${value}</td><td>${n}</td>`
        + `<td class="an-muted">${anEscape(note || "")}</td></tr>`;
    });
    table.innerHTML = `${html}</tbody>`;
  }
  document.getElementById("an-coverage-note").innerHTML =
    `対象 ${fmtNum(data.n_sessions || 0)}本（終了済み ${fmtNum(data.n_sessions_ended || 0)}本）。`
    + ` <b>切断の欠測を測れるのは ${fmtNum(inst.measured || 0)}本のみ</b>で、残り ${fmtNum(inst.unmeasured || 0)}本は計測不能です。`
    + ` <span class="an-muted">計測不能の配信を「欠測0秒」として混ぜていないため、この表の欠測時間は全体の下限ではなく、測れた配信だけの実測値です。</span>`;
}

// ---- ロード ----
async function loadAll() {
  const days = periodDays();
  const metric = elTiMetric.value;
  const q = `days=${days}`;
  document.getElementById("an-auto").textContent = "更新中…";
  // 各エンドポイントを個別に取得し、失敗しても他を描画する。
  const results = await Promise.allSettled([
    fetchJSON(`/api/analytics/summary?${q}`),
    fetchJSON(`/api/analytics/time-index?metric=${metric}&${q}`),
    fetchJSON(`/api/analytics/organic-entries?${q}`),
    fetchJSON(`/api/analytics/join-context?${q}`),
    fetchJSON(`/api/analytics/battle-uplift?${q}`),
    fetchJSON(`/api/analytics/relations?${q}`),
    fetchJSON(`/api/analytics/retention?${q}`),
    fetchJSON(`/api/analytics/concentration?${q}`),
    fetchJSON(`/api/analytics/join-quality?${q}`),
    fetchJSON(`/api/analytics/scale-efficiency?${q}`),
    fetchJSON(`/api/analytics/glove-crit-rate?${q}`),
    fetchJSON(`/api/analytics/share-uplift?${q}`),
    fetchJSON(`/api/analytics/entry-source?${q}`),
    fetchJSON(`/api/analytics/battle-flow?${q}`),
    fetchJSON(`/api/analytics/coverage?${q}`),
    fetchJSON(`/api/analytics/dwell?${q}`),
    fetchJSON(`/api/analytics/anomaly?${q}`),
    fetchJSON(`/api/analytics/activation?${q}`),
  ]);
  const val = (i) => (results[i].status === "fulfilled" ? results[i].value : null);
  safeRender("summary", renderSummary, val(0));
  safeRender("time-index", renderTimeIndex, val(1));
  safeRender("organic", renderOrganic, val(2));
  safeRender("join-context", renderJoinContext, val(3));
  safeRender("battle", renderBattle, val(4));
  safeRender("relations", renderMatrix, val(5));
  safeRender("retention", renderRetention, val(6));
  safeRender("concentration", renderConcentration, val(7));
  safeRender("quality", renderQuality, val(8));
  safeRender("scale", renderScatter, val(9));
  safeRender("glove", renderGloveCrit, val(10));
  safeRender("share", renderShare, val(11));
  safeRender("entry-source", renderEntrySource, val(12));
  safeRender("battle-flow", renderBattleFlow, val(13));
  safeRender("coverage", renderCoverage, val(14));
  safeRender("dwell", renderDwell, val(15));
  safeRender("anomaly", renderAnomaly, val(16));
  safeRender("activation", renderActivation, val(17));
  // 取得に失敗したパネルは前回描画が残る(stale)ため、note側で明示する。期間切替後に
  // 前の期間のグラフを今の期間の結果と誤認させない。
  const NOTE_IDS = [null, "an-ti-note", "an-organic-note", "an-context-note",
    "an-battle-note", "an-matrix-note", "an-retention-note", "an-conc-gift-note",
    "an-quality-note", "an-scatter-note", "an-glove-note", "an-share-note",
    "an-entry-note", "an-bf-note", "an-coverage-note", "an-dwell-note", "an-anom-note", "an-act-note"];
  results.forEach((r, i) => {
    if (r.status !== "rejected" || !NOTE_IDS[i]) return;
    const el = document.getElementById(NOTE_IDS[i]);
    if (el) el.innerHTML = `<span class="an-warn">取得に失敗しました。グラフは前回の表示が残っている場合があります。</span>`;
  });
  const failed = results.filter((r) => r.status === "rejected").length;
  document.getElementById("an-auto").textContent = failed
    ? `一部の取得に失敗（${failed}件）`
    : "選ぶと自動で更新されます";
}

// 時間帯インデックスは指標だけ差し替えれば良いので単独更新。
async function loadTimeIndex() {
  let ti;
  try {
    ti = await fetchJSON(`/api/analytics/time-index?metric=${elTiMetric.value}&days=${periodDays()}`);
  } catch (err) {
    // 失敗を黙って捨てるとグラフは前の指標のまま残り、選び直した指標の結果だと誤読される。
    // loadAllと同じくnote側で明示する。
    console.warn("time-index fetch failed", err);
    document.getElementById("an-ti-note").innerHTML =
      `<span class="an-warn">取得に失敗しました。グラフは前回の表示が残っている場合があります。</span>`;
    return;
  }
  safeRender("time-index", renderTimeIndex, ti);
}

// section目次。番号はDOM順と一致しないので、実在するsectionから組み立てる
// (手書きの目次は追加・削除で必ずずれる)。
function buildSectionIndex() {
  const nav = document.getElementById("an-index");
  if (!nav) return;
  nav.innerHTML = "";
  document.querySelectorAll("section[id^='an-s']").forEach((section) => {
    const heading = section.querySelector(".result-subtitle");
    if (!heading) return;
    const mark = (heading.textContent.match(/■\s*(\S+)/) || [])[1];
    if (!mark) return;
    const link = document.createElement("a");
    link.href = `#${section.id}`;
    link.textContent = mark;
    link.title = heading.textContent.replace(/^\s*■\s*/, "").trim();
    nav.appendChild(link);
  });
}

buildSectionIndex();

elPeriod.addEventListener("change", loadAll);
elTiMetric.addEventListener("change", loadTimeIndex);

// WS接続はServer接続表示の維持のみ(重い集計を毎tick再計算しない)。
connectWS(() => {});
loadAll();
