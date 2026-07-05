"use strict";

// 全体解析(配信者横断)。既存DBの再集約APIを描画する読み取り専用ページ。
// 統計方針: 中央値・Spearman順位相関・レート正規化で一時的なノイズに左右されない。

const METRIC_LABELS = {
  joins: "入室",
  comments: "Comment",
  diamonds: "コイン",
  likes: "いいね",
  follows: "フォロー",
  viewers: "同接",
};

let battleChart = null;
let shareChart = null;
let gloveChart = null;
let organicChart = null;
let qualityChart = null;
let scatterChart = null;
let retentionHourChart = null;
let contextChart = null;
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

// ---- ① 時間帯インデックス(数値付きheatmap: 縦=24時刻 × 横=曜日) ----
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

function tiCellHTML(cell, dowLabel, hour) {
  if (!cell || cell.index == null || cell.n <= 0) {
    return `<div class="an-hm-cell an-hm-empty" title="${dowLabel} ${hour}:00 データなし"></div>`;
  }
  const { bg, fg } = tiColor(cell.index);
  const title = `${dowLabel} ${hour}:00 ×${cell.index.toFixed(2)} (n=${cell.n})`;
  return `<div class="an-hm-cell" style="background:${bg};color:${fg}" title="${title}">${cell.index.toFixed(2)}</div>`;
}

function renderTimeIndex(data) {
  const hoursData = data.hours || [];
  document.getElementById("an-ti-note").innerHTML =
    `指標: <b>${METRIC_LABELS[data.metric] || data.metric}</b>`
    + ` &nbsp;観測 ${fmtNum(data.n_observations)}件 / 配信 ${fmtNum(data.n_sessions)}本`
    + ` &nbsp;<span class="an-hm-legend"><i>平均より少ない</i>`
    + `<span class="an-hm-bar"></span><i>多い</i>&nbsp;(中間=平均1.0)</span>`;

  const head = ['<div class="an-hm-rowh an-hm-corner">時刻</div>']
    .concat(TI_DOW.map((d) => `<div class="an-hm-h"${d.head ? ` style="color:${d.head}"` : ""}>${d.label}</div>`))
    .concat('<div class="an-hm-h an-hm-all">全部</div>')
    .join("");
  const body = hoursData
    .map((h) => {
      const hh = String(h.hour).padStart(2, "0");
      const cells = TI_DOW.map((d) => tiCellHTML(h.dow && h.dow[d.src], d.label, hh)).join("");
      const all = tiCellHTML(h.all, "全曜日", hh).replace("an-hm-cell", "an-hm-cell an-hm-all");
      return `<div class="an-hm-rowh">${hh}</div>${cells}${all}`;
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
  if (b.per_min && n.per_min) msg += ` <b>Battle中は平時の ${(b.per_min / n.per_min).toFixed(1)}倍</b>の速さで入室。`;
  if (!("collab" in data)) {
    msg += ` <span class="an-warn">コラボ分類はサーバ再起動後に有効になります。</span>`;
  } else if ((data.n_collabs || 0) === 0) {
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
    + ` 入室はピークで <b>${peakPct(data)}</b>（${data.peak.lag >= 0 ? "+" : ""}${data.peak.lag}s、平常比）。`;
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
  const anySig = (data.sig || []).some(Boolean);
  let msg = `バトル ${fmtNum(data.n_events)}回を集計（比較用 ${fmtNum(data.n_placebo)}件）。ピーク <b>${peakPct(data)}</b>。`;
  msg += anySig
    ? ` 比較帯を超える明確な入室増あり。`
    : ` <b>比較帯の内側</b>で、入室の明確な増加は見られません。`;
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
    meta.data.forEach((bar, i) => {
      const b = buckets[i];
      if (!b) return;
      if (!b.gifts) {
        ctx.fillStyle = "rgba(111, 106, 89, 0.45)";
        ctx.textAlign = "left";
        ctx.fillText("窓中0件", bar.base + 4, bar.y);
        return;
      }
      const txt = `${b.gifts}件中${b.crits}件 ${b.rate.toFixed(1)}%`;
      const w = ctx.measureText(txt).width;
      ctx.fillStyle = NIER_AXIS_COLOR;
      if (bar.x + 4 + w <= chart.chartArea.right) {
        ctx.textAlign = "left";
        ctx.fillText(txt, bar.x + 4, bar.y);
      } else {
        ctx.textAlign = "right";
        ctx.fillText(txt, bar.x - 4, bar.y);
      }
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
      `自陣(監視配信者)へ届いたグローブ窓中のギフトはまだ集計対象がありません`
      + `（グローブ窓 ${fmtNum(data.n_windows)}回）。この指標は<b>今後のバトル収集から蓄積</b>されます。`;
    return;
  }
  note.innerHTML =
    `グローブ窓 ${fmtNum(data.n_windows)}回 / 窓中ギフト ${fmtNum(data.total_gifts)}件 中 ${fmtNum(data.total_crits)}件が5倍(全体 <b>${overall}</b>)。`
    + (data.unresolved ? ` 単価不明で除外 ${fmtNum(data.unresolved)}件。` : "");

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
              if (!b.gifts) return `${b.label}コイン: 窓中サンプルなし`;
              return `${b.label}コイン: ${b.crits}/${b.gifts}件が5倍 (${b.rate.toFixed(1)}%)`;
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
  metrics.forEach((row) => {
    html += `<tr><th>${METRIC_LABELS[row]}</th>`;
    metrics.forEach((col) => {
      const v = data.matrix[row][col];
      const txt = v == null ? "-" : v.toFixed(2);
      const p = (partial[row] || {})[col];
      // 対角・同接列以外は偏相関(規模制御)をかっこ内に併記する。
      const pTxt = row === col || p == null ? "" : `<span class="an-cell-sub">(${p.toFixed(2)})</span>`;
      const strong = v != null && Math.abs(v) >= 0.5 ? " an-strong" : "";
      const title = `${METRIC_LABELS[row]}×${METRIC_LABELS[col]}: 素 ${txt}${p != null ? ` / 同接制御 ${p.toFixed(2)}` : ""}`;
      html += `<td class="an-cell${strong}" style="background:${corrColor(v)}" title="${title}">${txt}${pTxt}</td>`;
    });
    html += "</tr>";
  });
  html += "</tbody>";
  table.innerHTML = html;
  document.getElementById("an-matrix-note").innerHTML =
    `配信 ${fmtNum(data.n_sessions)}本で集計。<span class="an-sw-pos">■</span>正の相関（一緒に増える） <span class="an-sw-neg">■</span>負の相関（逆）。濃いほど関連が強い。`
    + ` かっこ内は<b>同接(規模)を制御した偏相関</b>＝「大きい配信は何でも多い」分を除いた値。`;
}

// ---- ⑤ 入室 → 定着 ----
function renderRetention(data) {
  const o = data.overall || {};
  const stick = o.retained_per_join;
  document.getElementById("an-retention-note").innerHTML =
    `全体: 入室 ${fmtNum(o.joins)}件 → 同接の純増 ${fmtNum(o.net_change)} = <b>1入室あたり ${stick == null ? "-" : stick.toFixed(2)}人が定着</b>`
    + `（残りは入れ替わり）。時刻別に入室数(棒)と平均同接(線)を並べた。入室が伸びても同接の線が上がらない時間帯は「入っても抜けている」。`;

  const byHour = data.by_hour || [];
  const labels = byHour.map((h) => String(h.hour));
  const joins = byHour.map((h) => h.joins);
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
          { type: "bar", label: "入室数", data: joins, backgroundColor: "rgba(164, 80, 47, 0.55)", borderWidth: 0, yAxisID: "y" },
          { type: "line", label: "平均同接", data: viewers, borderColor: "#5d6e4e", backgroundColor: "#5d6e4e", borderWidth: 2, pointRadius: 2, tension: 0.25, yAxisID: "y2", spanGaps: true },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        scales: {
          x: { ticks: { ...nierTicks(), autoSkip: false, maxTicksLimit: 24 }, grid: { color: NIER_GRID_COLOR }, title: { display: true, text: "時刻", color: NIER_AXIS_COLOR, font: { family: "monospace", size: 10 } } },
          y: { beginAtZero: true, position: "left", ticks: nierTicks(), grid: { color: NIER_GRID_COLOR }, title: vAxisTitle("入室数(人)") },
          y2: { beginAtZero: true, position: "right", ticks: nierTicks(), grid: { drawOnChartArea: false }, title: vAxisTitle("平均同接(人)") },
        },
        plugins: { legend: { display: true, labels: { ...nierTicks(), boxWidth: 12 } }, tooltip: { ...nierTooltip() } },
      },
    });
  }
}

// ---- ⑥ 集中度(Lorenz曲線) ----
function renderConcentration(data) {
  renderLorenz("gift", "an-lorenz-gift", "an-conc-gift-note", "an-conc-gift-top", "コイン", data.gifts, "#a96e49");
  renderLorenz("comment", "an-lorenz-comment", "an-conc-comment-note", "an-conc-comment-top", "Comment", data.comments, "#5d6e4e");
}
function renderLorenz(key, canvasId, noteId, topId, unit, c, color) {
  if (!c) return;
  document.getElementById(noteId).innerHTML =
    `<b>${unit}</b>: ${fmtNum(c.n_users)}人 / Gini <b>${c.gini.toFixed(3)}</b>（1に近いほど偏り大）`;
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
        x: { type: "linear", reverse: true, min: 0, max: 1, ticks: { ...nierTicks(), callback: (v) => Math.round(v * 100) + "%" }, grid: { color: NIER_GRID_COLOR }, title: { display: true, text: "人数(下位から累積)", color: NIER_AXIS_COLOR, font: { family: "monospace", size: 10 } } },
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
function renderOrganic(data) {
  const byHour = data.hours || [];
  const t = data.totals || {};
  const labels = byHour.map((h) => String(h.hour));
  // 配信のない時刻(raw=0)は線を切る。実数(件)で生とノイズ除去後の差を見る。
  const rawCnt = byHour.map((h) => (h.raw > 0 ? h.raw : null));
  const orgCnt = byHour.map((h) => (h.raw > 0 ? Math.round(h.organic) : null));
  const pct = (x) => `${((x || 0) * 100).toFixed(0)}%`;
  document.getElementById("an-organic-note").innerHTML =
    `全入室 ${fmtNum(t.raw || 0)}件 → ノイズ除去後 ${fmtNum(Math.round(t.organic || 0))}件相当。`
    + ` 再訪した人 <b>${pct(data.returning_ratio)}</b> ／ 入室後に反応した人 <b>${pct(data.engaged_ratio)}</b>`
    + ` ／ シェア直後の流入 <b>${pct(data.share_window_ratio)}</b>`
    + (data.stick_rate != null ? ` ／ 定着率 <b>${pct(data.stick_rate)}</b>` : "")
    + `。<span class="an-hm-legend"><i>生の入室</i><span class="an-hm-bar"></span><i>ノイズ除去後</i></span>`;

  const datasets = [
    { type: "line", label: "生の入室数", data: rawCnt, borderColor: "#918b78", backgroundColor: "#918b78", borderWidth: 2, pointRadius: 2, tension: 0.25, spanGaps: false },
    { type: "line", label: "ノイズ除去後", data: orgCnt, borderColor: "#a4502f", backgroundColor: "#a4502f", borderWidth: 2.6, pointRadius: 2, tension: 0.25, spanGaps: false },
  ];
  if (organicChart) {
    organicChart.data.labels = labels;
    organicChart.data.datasets[0].data = rawCnt;
    organicChart.data.datasets[1].data = orgCnt;
    organicChart.update();
    return;
  }
  organicChart = new Chart(document.getElementById("an-organic-chart"), {
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      scales: {
        x: { ticks: { ...nierTicks(), autoSkip: false, maxTicksLimit: 24 }, grid: { color: NIER_GRID_COLOR }, title: { display: true, text: "時刻", color: NIER_AXIS_COLOR, font: { family: "monospace", size: 10 } } },
        y: { beginAtZero: true, ticks: { ...nierTicks() }, grid: { color: NIER_GRID_COLOR }, title: vAxisTitle("入室数(件)") },
      },
      plugins: {
        legend: { labels: { color: "#4d4a3f", font: { family: "monospace", size: 11 }, boxWidth: 14, boxHeight: 8 } },
        tooltip: { ...nierTooltip() },
      },
    },
  });
}

// ---- ⑦ 入室の質(新規/常連) ----
function renderQuality(data) {
  const byHour = data.hours || [];
  const labels = byHour.map((h) => String(h.hour));
  const news = byHour.map((h) => h.new);
  const rets = byHour.map((h) => h.returning);
  const ratio = byHour.map((h) => (h.total > 0 ? h.new_ratio * 100 : null));
  document.getElementById("an-quality-note").innerHTML =
    `全入室 ${fmtNum(data.total)}件中、新規 ${fmtNum(data.new)}件（新規率 ${((data.new_ratio || 0) * 100).toFixed(0)}%）。`;

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
function renderScatter(data) {
  const streamers = data.streamers || [];
  const maxSessions = Math.max(1, ...streamers.map((s) => s.sessions));
  const points = streamers.map((s) => ({
    x: s.avg_viewers,
    y: s.coins_per_viewer,
    r: 5 + 14 * Math.sqrt(s.sessions / maxSessions),
    _s: s,
  }));
  document.getElementById("an-scatter-note").textContent =
    `${fmtNum(streamers.length)}配信者。右＝規模が大きい、上＝1視聴あたりよく稼ぐ。バブル大＝配信回数が多い。`;
  const dataset = {
    label: "配信者",
    data: points,
    backgroundColor: "rgba(169, 110, 73, 0.5)",
    borderColor: "#8e4f2f",
    borderWidth: 1,
  };
  if (scatterChart) {
    scatterChart.data.datasets[0].data = points;
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
        x: { beginAtZero: true, ticks: nierTicks(), grid: { color: NIER_GRID_COLOR }, title: { display: true, text: "平均同接(規模)", color: NIER_AXIS_COLOR, font: { family: "monospace", size: 10 } } },
        y: { beginAtZero: true, ticks: nierTicks(), grid: { color: NIER_GRID_COLOR }, title: vAxisTitle("同接あたりコイン(効率)") },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          ...nierTooltip(),
          callbacks: {
            label: (item) => {
              const s = item.raw._s;
              return `${s.nickname} @${s.unique_id} · 同接${fmtNum(s.avg_viewers)} · ${fmtCompact(s.coins)}コイン · ${fmtNum(s.sessions)}配信`;
            },
          },
        },
      },
    },
  });
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
  const failed = results.filter((r) => r.status === "rejected").length;
  document.getElementById("an-auto").textContent = failed
    ? `一部の取得に失敗（${failed}件）`
    : "選ぶと自動で更新されます";
}

// 時間帯インデックスは指標だけ差し替えれば良いので単独更新。
async function loadTimeIndex() {
  const ti = await fetchJSON(`/api/analytics/time-index?metric=${elTiMetric.value}&days=${periodDays()}`).catch(() => null);
  safeRender("time-index", renderTimeIndex, ti);
}

elPeriod.addEventListener("change", loadAll);
elTiMetric.addEventListener("change", loadTimeIndex);

// WS接続はServer接続表示の維持のみ(重い集計を毎tick再計算しない)。
connectWS(() => {});
loadAll();
