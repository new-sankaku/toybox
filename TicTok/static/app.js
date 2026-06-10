"use strict";

const els = {
  uniqueId: document.getElementById("unique-id"),
  startBtn: document.getElementById("start-btn"),
  stopBtn: document.getElementById("stop-btn"),
  spinner: document.getElementById("spinner"),
  statusBadge: document.getElementById("status-badge"),
  statusMessage: document.getElementById("status-message"),
  steps: document.getElementById("steps"),
  giftStreak: document.getElementById("gift-streak"),
  wsIndicator: document.getElementById("ws-indicator"),
  wsStatus: document.getElementById("ws-status"),
  feeds: {
    gift: { list: document.getElementById("gift-feed"), empty: document.getElementById("gift-empty") },
    comment: { list: document.getElementById("comment-feed"), empty: document.getElementById("comment-empty") },
    event: { list: document.getElementById("event-feed"), empty: document.getElementById("event-empty") },
  },
  stats: {
    viewers: document.getElementById("stat-viewers"),
    total_viewers: document.getElementById("stat-total-viewers"),
    likes_total: document.getElementById("stat-likes"),
    gifts: document.getElementById("stat-gifts"),
    diamonds: document.getElementById("stat-diamonds"),
    comments: document.getElementById("stat-comments"),
    follows: document.getElementById("stat-follows"),
    shares: document.getElementById("stat-shares"),
    joins: document.getElementById("stat-joins"),
    battles: document.getElementById("stat-battles"),
    events_total: document.getElementById("stat-events"),
  },
  uptime: document.getElementById("stat-uptime"),
  room: document.getElementById("stat-room"),
};

const FEED_LIMIT = 100;

const STATUS_LABELS = {
  idle: { badge: "IDLE", cls: "badge-idle", message: "待機中 — TikTok IDを入力して収集を開始してください。" },
  connecting: { badge: "CONNECTING", cls: "badge-connecting", message: "接続処理を実行中です…" },
  connected: { badge: "RECEIVING", cls: "badge-connected", message: "LIVEに接続済み。Eventを受信しています。" },
  reconnecting: { badge: "RECONNECTING", cls: "badge-reconnecting", message: "接続が不安定なため再接続しています…（収集Dataは保持されます）" },
  disconnected: { badge: "STOPPED", cls: "badge-idle", message: "収集を停止しました。" },
  ended: { badge: "LIVE ENDED", cls: "badge-ended", message: "LIVE配信が終了しました。" },
  error: { badge: "ERROR", cls: "badge-error", message: "Errorが発生しました。" },
};

let connectedAt = null;
let currentStatus = "idle";
let streakTimer = null;

function fmtTime(epochSeconds) {
  return new Date(epochSeconds * 1000).toLocaleTimeString("ja-JP", { hour12: false });
}

function fmtDuration(seconds) {
  const h = String(Math.floor(seconds / 3600)).padStart(2, "0");
  const m = String(Math.floor((seconds % 3600) / 60)).padStart(2, "0");
  const s = String(Math.floor(seconds % 60)).padStart(2, "0");
  return `${h}:${m}:${s}`;
}

setInterval(() => {
  if (currentStatus === "connected" && connectedAt) {
    els.uptime.textContent = fmtDuration(Date.now() / 1000 - connectedAt);
  }
}, 1000);

function applyState(state) {
  currentStatus = state.status;
  const info = STATUS_LABELS[state.status] || STATUS_LABELS.idle;
  els.statusBadge.textContent = info.badge;
  els.statusBadge.className = `badge ${info.cls}`;
  const simulationTag = state.simulation ? " [Simulation mode]" : "";
  const message = state.status === "error" ? state.error_message || info.message : info.message;
  els.statusMessage.textContent = message + simulationTag;

  const active = ["connecting", "connected", "reconnecting"].includes(state.status);
  const busy = state.status === "connecting" || state.status === "reconnecting";
  els.spinner.classList.toggle("hidden", !busy);
  els.startBtn.disabled = active;
  els.stopBtn.disabled = !active;

  if (state.unique_id && !els.uniqueId.value) {
    els.uniqueId.value = state.unique_id;
  }
  els.room.textContent = state.room_id ? String(state.room_id) : "-";

  renderSteps(state.steps || []);
  applyStats(state.stats || {});

  if (Array.isArray(state.recent_events)) {
    clearFeeds();
    state.recent_events.forEach((ev) => addEvent(ev, true));
  }
  refreshAnalytics();
}

function renderSteps(steps) {
  els.steps.innerHTML = "";
  const marks = { pending: "□", active: "◆", done: "■", failed: "✕" };
  steps.forEach((step) => {
    const li = document.createElement("li");
    li.className = `step step-${step.status}`;
    const mark = document.createElement("span");
    mark.className = "mark";
    mark.textContent = marks[step.status] || "□";
    const label = document.createElement("span");
    label.textContent = step.label;
    li.append(mark, label);
    els.steps.appendChild(li);
  });
}

function applyStats(stats) {
  Object.entries(els.stats).forEach(([key, el]) => {
    if (key in stats) {
      el.textContent = Number(stats[key]).toLocaleString("ja-JP");
    }
  });
  if (stats.connected_at) {
    connectedAt = stats.connected_at;
  } else if (!stats.connected_at && currentStatus === "idle") {
    connectedAt = null;
    els.uptime.textContent = "--:--:--";
  }
}

function clearFeeds() {
  Object.values(els.feeds).forEach((feed) => {
    feed.list.innerHTML = "";
    feed.empty.classList.remove("hidden");
  });
}

function addFeedItem(feed, ev, contentText, silent, filterable = false) {
  feed.empty.classList.add("hidden");
  const li = document.createElement("li");
  li.className = `feed-item feed-item-${ev.kind}`;
  if (filterable) {
    li.dataset.kind = ev.kind;
    if (!activeKinds.has(ev.kind)) li.classList.add("filtered-out");
  }
  if (silent) li.style.animation = "none";

  const meta = document.createElement("div");
  meta.className = "meta";
  const kind = document.createElement("span");
  kind.className = "kind";
  kind.textContent = ev.kind;
  const time = document.createElement("span");
  time.textContent = fmtTime(ev.time);
  meta.append(kind, time);

  const body = document.createElement("div");
  body.textContent = contentText;

  li.append(meta, body);
  feed.list.prepend(li);
  while (feed.list.children.length > FEED_LIMIT) {
    feed.list.removeChild(feed.list.lastChild);
  }
}

function addEvent(ev, silent = false) {
  if (ev.kind === "gift_streak") {
    showStreak(ev);
    return;
  }
  addFeedItem(els.feeds.event, ev, ev.text, silent, true);
  if (ev.kind === "gift") {
    addFeedItem(els.feeds.gift, ev, ev.text, silent);
  } else if (ev.kind === "comment") {
    addFeedItem(els.feeds.comment, ev, `${ev.user.nickname}: ${ev.comment}`, silent);
  }
}

function showStreak(ev) {
  els.giftStreak.textContent = `◆ ${ev.text}`;
  els.giftStreak.classList.remove("hidden");
  if (streakTimer) clearTimeout(streakTimer);
  streakTimer = setTimeout(() => els.giftStreak.classList.add("hidden"), 4000);
}

function connectWebSocket() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${protocol}://${location.host}/ws`);

  ws.onopen = () => {
    els.wsIndicator.classList.add("online");
    els.wsStatus.textContent = "Server接続: ONLINE";
  };

  ws.onmessage = (msg) => {
    const { type, data } = JSON.parse(msg.data);
    if (type === "state") applyState(data);
    else if (type === "stats") applyStats(data);
    else if (type === "event") addEvent(data);
  };

  ws.onclose = () => {
    els.wsIndicator.classList.remove("online");
    els.wsStatus.textContent = "Server接続: OFFLINE — 再接続中…";
    setTimeout(connectWebSocket, 2000);
  };

  ws.onerror = () => ws.close();
}

async function post(path, body) {
  const res = await fetch(path, {
    method: "POST",
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

els.startBtn.addEventListener("click", async () => {
  const uniqueId = els.uniqueId.value.trim();
  if (!uniqueId) {
    els.statusMessage.textContent = "TikTok IDを入力してください。";
    return;
  }
  els.startBtn.disabled = true;
  els.spinner.classList.remove("hidden");
  els.statusMessage.textContent = "収集開始をRequest中…";
  try {
    await post("/api/start", { unique_id: uniqueId });
  } catch (err) {
    els.spinner.classList.add("hidden");
    els.startBtn.disabled = false;
    els.statusBadge.textContent = "ERROR";
    els.statusBadge.className = "badge badge-error";
    els.statusMessage.textContent = err.message;
  }
});

els.stopBtn.addEventListener("click", async () => {
  els.stopBtn.disabled = true;
  els.statusMessage.textContent = "停止をRequest中…";
  try {
    await post("/api/stop");
  } catch (err) {
    els.statusMessage.textContent = err.message;
  }
});

els.uniqueId.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !els.startBtn.disabled) {
    els.startBtn.click();
  }
});

const EVENT_KINDS = ["gift", "comment", "like", "follow", "share", "join", "subscribe", "battle", "system"];
const activeKinds = new Set(EVENT_KINDS);

function initEventFilters() {
  const container = document.getElementById("event-filters");
  EVENT_KINDS.forEach((kind) => {
    const label = document.createElement("label");
    label.className = "filter-chip on";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = true;
    input.addEventListener("change", () => {
      if (input.checked) activeKinds.add(kind);
      else activeKinds.delete(kind);
      label.classList.toggle("on", input.checked);
      els.feeds.event.list.querySelectorAll(`[data-kind="${kind}"]`).forEach((li) => {
        li.classList.toggle("filtered-out", !input.checked);
      });
    });
    const text = document.createElement("span");
    text.textContent = kind;
    label.append(input, text);
    container.appendChild(label);
  });
}

const CHART_DISPLAY_LIMIT = 720;
let chart = null;
let chartFirstStart = null;
let chartBucketSeconds = 10;
let chartMarkers = [];

const markerPlugin = {
  id: "tictokMarkers",
  afterDatasetsDraw(c) {
    if (!chartMarkers.length || chartFirstStart === null) return;
    const { ctx, chartArea, scales } = c;
    chartMarkers.forEach((m) => {
      const idx = Math.round((m.time - chartFirstStart) / chartBucketSeconds);
      if (idx < 0 || idx >= c.data.labels.length) return;
      const x = scales.x.getPixelForValue(idx);
      ctx.save();
      ctx.strokeStyle = "#a4502f";
      ctx.setLineDash([4, 3]);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, chartArea.top);
      ctx.lineTo(x, chartArea.bottom);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "#a4502f";
      ctx.font = "10px monospace";
      ctx.textAlign = "left";
      ctx.fillText(m.label, x + 3, chartArea.top + 10);
      ctx.restore();
    });
  },
};

function initChart() {
  const axisColor = "#6f6a59";
  const gridColor = "rgba(143, 136, 113, 0.3)";
  chart = new Chart(document.getElementById("timeline-chart"), {
    type: "bar",
    data: {
      labels: [],
      datasets: [
        { label: "Gift数", type: "bar", data: [], backgroundColor: "#8e4f2f", yAxisID: "y" },
        { label: "Diamonds", type: "bar", data: [], backgroundColor: "rgba(169, 110, 73, 0.55)", yAxisID: "y2" },
        { label: "同接数", type: "line", data: [], borderColor: "#4d4a3f", backgroundColor: "#4d4a3f", borderWidth: 2, pointRadius: 0, tension: 0.25, yAxisID: "y2" },
        { label: "Comment数", type: "line", data: [], borderColor: "#5d6e4e", backgroundColor: "#5d6e4e", borderWidth: 1.5, pointRadius: 0, tension: 0.25, yAxisID: "y" },
        { label: "Like数", type: "line", data: [], borderColor: "#9b8c52", backgroundColor: "#9b8c52", borderWidth: 1.5, pointRadius: 0, tension: 0.25, yAxisID: "y", hidden: true },
        { label: "入室数", type: "line", data: [], borderColor: "#7a7263", backgroundColor: "#7a7263", borderWidth: 1.5, pointRadius: 0, tension: 0.25, yAxisID: "y", hidden: true },
        { label: "Follow", type: "line", data: [], borderColor: "#5d6e4e", backgroundColor: "#5d6e4e", borderDash: [4, 3], borderWidth: 1.5, pointRadius: 0, yAxisID: "y", hidden: true },
        { label: "Share", type: "line", data: [], borderColor: "#a96e49", backgroundColor: "#a96e49", borderDash: [4, 3], borderWidth: 1.5, pointRadius: 0, yAxisID: "y", hidden: true },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: {
          ticks: { color: axisColor, maxRotation: 0, autoSkip: true, maxTicksLimit: 12, font: { family: "monospace", size: 10 } },
          grid: { color: gridColor },
        },
        y: {
          position: "left",
          beginAtZero: true,
          title: { display: true, text: "件数", color: axisColor, font: { family: "monospace", size: 10 } },
          ticks: { color: axisColor, font: { family: "monospace", size: 10 }, precision: 0 },
          grid: { color: gridColor },
        },
        y2: {
          position: "right",
          beginAtZero: true,
          title: { display: true, text: "Diamonds / 同接数", color: axisColor, font: { family: "monospace", size: 10 } },
          ticks: { color: axisColor, font: { family: "monospace", size: 10 }, precision: 0 },
          grid: { drawOnChartArea: false },
        },
      },
      plugins: {
        legend: {
          labels: { color: "#4d4a3f", font: { family: "monospace", size: 11 }, boxWidth: 14, boxHeight: 8 },
        },
        tooltip: {
          backgroundColor: "#4d4a3f",
          titleColor: "#d8d2bc",
          bodyColor: "#d8d2bc",
          titleFont: { family: "monospace" },
          bodyFont: { family: "monospace" },
        },
      },
    },
    plugins: [markerPlugin],
  });
}

function updateTimeline(data) {
  if (!chart) return;
  chartBucketSeconds = data.bucket_seconds;
  chartMarkers = data.markers || [];
  const raw = data.buckets || [];
  if (!raw.length) {
    chartFirstStart = null;
    chart.data.labels = [];
    chart.data.datasets.forEach((ds) => { ds.data = []; });
    chart.update();
    return;
  }
  const size = data.bucket_seconds;
  const byStart = new Map(raw.map((b) => [b.start, b]));
  const last = raw[raw.length - 1].start;
  let first = raw[0].start;
  if ((last - first) / size + 1 > CHART_DISPLAY_LIMIT) {
    first = last - (CHART_DISPLAY_LIMIT - 1) * size;
  }
  chartFirstStart = first;
  const labels = [];
  const series = { gifts: [], diamonds: [], viewers: [], comments: [], likes: [], joins: [], follows: [], shares: [] };
  let viewers = raw[0].viewers;
  for (let s = first; s <= last; s += size) {
    const b = byStart.get(s);
    if (b) viewers = b.viewers;
    labels.push(fmtTime(s));
    series.gifts.push(b ? b.gifts : 0);
    series.diamonds.push(b ? b.diamonds : 0);
    series.viewers.push(viewers);
    series.comments.push(b ? b.comments : 0);
    series.likes.push(b ? b.likes : 0);
    series.joins.push(b ? b.joins : 0);
    series.follows.push(b ? b.follows : 0);
    series.shares.push(b ? b.shares : 0);
  }
  chart.data.labels = labels;
  const order = ["gifts", "diamonds", "viewers", "comments", "likes", "joins", "follows", "shares"];
  order.forEach((key, i) => { chart.data.datasets[i].data = series[key]; });
  chart.update();
}

function applySummary(summary) {
  const totals = summary.totals || {};
  const chips = [
    ["Gift合計", totals.gifts],
    ["Diamonds合計", totals.diamonds],
    ["Gift送信者数", totals.unique_gifters],
    ["Comment合計", totals.comments],
    ["Like合計", totals.likes_total],
    ["Battle回数", totals.battles],
  ];
  const totalsEl = document.getElementById("result-totals");
  totalsEl.innerHTML = "";
  chips.forEach(([label, value]) => {
    const chip = document.createElement("div");
    chip.className = "result-chip";
    const l = document.createElement("span");
    l.className = "label";
    l.textContent = label;
    const v = document.createElement("span");
    v.className = "value";
    v.textContent = Number(value || 0).toLocaleString("ja-JP");
    chip.append(l, v);
    totalsEl.appendChild(chip);
  });

  renderRanking(
    "user-ranking",
    "user-ranking-empty",
    summary.users || [],
    (user, rank) => [
      String(rank),
      user.unique_id ? `${user.nickname} (@${user.unique_id})` : user.nickname,
      Number(user.gifts).toLocaleString("ja-JP"),
      Number(user.diamonds).toLocaleString("ja-JP"),
      topItemText(user.items),
    ],
  );
  renderRanking(
    "gift-ranking",
    "gift-ranking-empty",
    summary.gifts || [],
    (gift, rank) => [
      String(rank),
      gift.name,
      Number(gift.count).toLocaleString("ja-JP"),
      Number(gift.diamonds_each).toLocaleString("ja-JP"),
      Number(gift.diamonds).toLocaleString("ja-JP"),
    ],
  );
}

function topItemText(items) {
  const entries = Object.entries(items || {});
  if (!entries.length) return "-";
  entries.sort((a, b) => b[1] - a[1]);
  const [name, count] = entries[0];
  return `${name} x${count}`;
}

function renderRanking(bodyId, emptyId, rows, toCells) {
  const tbody = document.getElementById(bodyId);
  const empty = document.getElementById(emptyId);
  tbody.innerHTML = "";
  empty.classList.toggle("hidden", rows.length > 0);
  rows.forEach((row, i) => {
    const tr = document.createElement("tr");
    if (i === 0) tr.className = "rank-top";
    toCells(row, i + 1).forEach((cell, col) => {
      const td = document.createElement("td");
      if (col === 0 || col === 2 || col === 3 || col === 4) td.className = "num";
      td.textContent = cell;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
}

let analyticsBusy = false;

async function refreshAnalytics() {
  if (analyticsBusy || !chart) return;
  analyticsBusy = true;
  try {
    const [timelineRes, summaryRes] = await Promise.all([
      fetch("/api/timeline"),
      fetch("/api/summary"),
    ]);
    updateTimeline(await timelineRes.json());
    applySummary(await summaryRes.json());
  } catch (err) {
    console.warn("analytics refresh failed", err);
  } finally {
    analyticsBusy = false;
  }
}

setInterval(() => {
  if (["connecting", "connected", "reconnecting"].includes(currentStatus)) {
    refreshAnalytics();
  }
}, 5000);

initEventFilters();
initChart();
connectWebSocket();
refreshAnalytics();
