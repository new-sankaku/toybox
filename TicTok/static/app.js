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
  els.statusMessage.textContent = state.error_message || info.message;

  const busy = state.status === "connecting";
  els.spinner.classList.toggle("hidden", !busy);
  els.startBtn.disabled = state.status === "connecting" || state.status === "connected";
  els.stopBtn.disabled = !(state.status === "connecting" || state.status === "connected");

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

function addFeedItem(feed, ev, contentText, silent) {
  feed.empty.classList.add("hidden");
  const li = document.createElement("li");
  li.className = `feed-item feed-item-${ev.kind}`;
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
  addFeedItem(els.feeds.event, ev, ev.text, silent);
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

connectWebSocket();
