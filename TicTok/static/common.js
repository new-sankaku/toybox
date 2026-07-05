"use strict";

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

async function apiSend(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const payload = await res.json().catch(() => ({}));
    const detail = payload.detail;
    throw new Error(typeof detail === "string" ? detail : "Requestに失敗しました。");
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
  ws.onmessage = (msg) => onMessage(JSON.parse(msg.data));
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
              return r ? `#${r.id}  ${fmtDateTime(r.started_at)}` : "";
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

// ---- Battle cards (shared by /battle page and history detail modal) ----
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

// 敵陣segmentの別色数(c1..cN)。これを超える陣営は循環で色を再利用する。
const SEG_OPP_COLORS = 6;

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
// カード表示「BS」に相当する実効値: 本物のBS(score)があればそれ、無ければ実弾(推測BS)。
// fmtBsCoins の表示と、pkContribCount の100↑判定を同じ基準に揃え、表示と数え方を一致させる。
function effectiveBs(c) {
  const score = c.score || 0;
  return score > 0 ? score : c.diamonds || 0;
}
function fmtBsCoins(c) {
  const score = c.score || 0;
  const dia = c.diamonds || 0;
  // BS未取得(score 0)だが実弾ありの貢献者は、TikTokがPK内訳(armies)を送らなかった人。
  // 実弾を推測BSとして併記し「推測」を明示する。BSと実弾は単位/係数が異なり正確な
  // 換算は不能なため、これは確定値ではなく推測である旨を表示で必ず示す。
  if (score <= 0 && dia > 0) {
    return `BS ${fmtNum(dia)}(推測) / 実弾 ${fmtNum(dia)}`;
  }
  return `BS ${fmtBs(score)} / 実弾 ${fmtBs(dia)}`;
}

// 貢献者テーブルのBS列。本物のBS(score)があればそれ、無ければ実弾からの推測を明示、
// どちらも無ければ—。実弾列は fmtBs(diamonds) で別列に分ける。
function bsCellText(c) {
  const score = c.score || 0;
  const dia = c.diamonds || 0;
  if (score > 0) return fmtNum(score);
  if (dia > 0) return `${fmtNum(dia)}(推測)`;
  return "—";
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
        { label: "自陣", data: ownData, borderColor: "#5d6e4e", backgroundColor: "transparent", borderWidth: 1.5, pointRadius: 0, tension: 0.25 },
        { label: "敵陣", data: oppData, borderColor: "#a4502f", backgroundColor: "transparent", borderWidth: 1.5, pointRadius: 0, tension: 0.25 },
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
  const taskLabel = m.progress_target
    ? `ミッション ${m.task_duration || "?"}s・${m.achieved ? "達成✅" : `${m.progress}/${m.progress_target}`}`
    : `ミッション ${m.task_duration || "?"}s`;
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
  const wrap = document.createElement("span");
  wrap.className = "u" + (opts.stackId ? " u-stack" : "");
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

function renderTableRows(tbodyId, emptyId, rows, toCells, numericCols) {
  const tbody = document.getElementById(tbodyId);
  const empty = document.getElementById(emptyId);
  tbody.innerHTML = "";
  if (empty) empty.classList.toggle("hidden", rows.length > 0);
  rows.forEach((row, i) => {
    const tr = document.createElement("tr");
    if (i === 0) tr.className = "rank-top";
    toCells(row, i + 1).forEach((cell, col) => {
      const td = document.createElement("td");
      if (numericCols.includes(col)) td.className = "num";
      if (cell instanceof Node) td.appendChild(cell);
      else td.textContent = cell;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
}
