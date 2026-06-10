"use strict";

const monitors = new Map();
const grid = document.getElementById("monitor-grid");
const gridEmpty = document.getElementById("grid-empty");

function getMonitor(uid) {
  if (!monitors.has(uid)) {
    monitors.set(uid, { snapshot: null, lastGift: null, lastComment: null });
  }
  return monitors.get(uid);
}

function syncMonitors(snapshots) {
  const seen = new Set();
  snapshots.forEach((snap) => {
    seen.add(snap.unique_id);
    const monitor = getMonitor(snap.unique_id);
    monitor.snapshot = snap;
    (snap.recent_events || []).forEach((ev) => rememberEvent(monitor, ev));
  });
  [...monitors.keys()].forEach((uid) => {
    if (!seen.has(uid)) monitors.delete(uid);
  });
  renderGrid();
}

function rememberEvent(monitor, ev) {
  if (ev.kind === "gift") monitor.lastGift = ev;
  else if (ev.kind === "comment") monitor.lastComment = ev;
}

function cardRow(label, valueId) {
  const row = document.createElement("div");
  row.className = "card-row";
  const l = document.createElement("span");
  l.className = "card-label";
  l.textContent = label;
  const v = document.createElement("span");
  v.className = "card-value";
  v.dataset.field = valueId;
  v.textContent = "0";
  row.append(l, v);
  return row;
}

function buildCard(uid) {
  const card = document.createElement("a");
  card.className = "monitor-card";
  card.href = `/?monitor=${encodeURIComponent(uid)}`;
  card.dataset.uid = uid;

  const head = document.createElement("div");
  head.className = "card-head";
  const name = document.createElement("span");
  name.className = "card-name";
  name.textContent = `@${uid}`;
  const badge = document.createElement("span");
  badge.className = "badge badge-idle";
  badge.dataset.field = "badge";
  badge.textContent = "IDLE";
  head.append(name, badge);
  card.appendChild(head);

  const rows = document.createElement("div");
  rows.className = "card-rows";
  rows.append(
    cardRow("視聴者数", "viewers"),
    cardRow("Gift数", "gifts"),
    cardRow("Diamonds", "diamonds"),
    cardRow("累計Like", "likes_total"),
    cardRow("Gift/分", "rate_gifts"),
    cardRow("Diamonds/分", "rate_diamonds"),
    cardRow("Comment/分", "rate_comments"),
    cardRow("Like/分", "rate_likes"),
    cardRow("接続時間", "uptime"),
  );
  card.appendChild(rows);

  const lastGift = document.createElement("div");
  lastGift.className = "card-last card-last-gift";
  lastGift.dataset.field = "last_gift";
  lastGift.textContent = "GIFT: -";
  const lastComment = document.createElement("div");
  lastComment.className = "card-last";
  lastComment.dataset.field = "last_comment";
  lastComment.textContent = "COMMENT: -";
  card.append(lastGift, lastComment);
  return card;
}

function renderGrid() {
  const uids = [...monitors.keys()];
  gridEmpty.classList.toggle("hidden", uids.length > 0);
  [...grid.children].forEach((card) => {
    if (!monitors.has(card.dataset.uid)) card.remove();
  });
  uids.forEach((uid) => {
    let card = grid.querySelector(`[data-uid="${CSS.escape(uid)}"]`);
    if (!card) {
      card = buildCard(uid);
      grid.appendChild(card);
    }
    updateCard(card, monitors.get(uid));
  });
}

function updateCard(card, monitor) {
  const snap = monitor.snapshot;
  if (!snap) return;
  const info = STATUS_LABELS[snap.status] || STATUS_LABELS.idle;
  const badge = card.querySelector('[data-field="badge"]');
  badge.textContent = info.badge;
  badge.className = `badge ${info.cls}`;
  card.classList.toggle("card-live", snap.status === "connected");
  updateCardStats(card, snap.stats || {});
  const giftEl = card.querySelector('[data-field="last_gift"]');
  giftEl.textContent = `GIFT: ${monitor.lastGift ? monitor.lastGift.text : "-"}`;
  const commentEl = card.querySelector('[data-field="last_comment"]');
  commentEl.textContent = `COMMENT: ${monitor.lastComment ? monitor.lastComment.text : "-"}`;
}

function updateCardStats(card, stats) {
  ["viewers", "gifts", "diamonds", "likes_total", "rate_gifts", "rate_diamonds", "rate_comments", "rate_likes"].forEach(
    (key) => {
      const el = card.querySelector(`[data-field="${key}"]`);
      if (el && key in stats) el.textContent = fmtNum(stats[key]);
    },
  );
}

setInterval(() => {
  monitors.forEach((monitor, uid) => {
    const card = grid.querySelector(`[data-uid="${CSS.escape(uid)}"]`);
    if (!card) return;
    const el = card.querySelector('[data-field="uptime"]');
    const snap = monitor.snapshot;
    if (snap && snap.status === "connected" && snap.stats && snap.stats.connected_at) {
      el.textContent = fmtDuration(Date.now() / 1000 - snap.stats.connected_at);
    } else {
      el.textContent = "--:--:--";
    }
  });
}, 1000);

function handleMessage(msg) {
  if (msg.type === "monitors") {
    syncMonitors(msg.data);
    return;
  }
  const uid = msg.monitor;
  if (!uid || !monitors.has(uid)) return;
  const monitor = monitors.get(uid);
  const card = grid.querySelector(`[data-uid="${CSS.escape(uid)}"]`);
  if (msg.type === "state") {
    monitor.snapshot = msg.data;
    monitor.snapshot.unique_id = uid;
    if (card) updateCard(card, monitor);
  } else if (msg.type === "stats") {
    if (monitor.snapshot) monitor.snapshot.stats = msg.data;
    if (card) updateCardStats(card, msg.data);
  } else if (msg.type === "event") {
    rememberEvent(monitor, msg.data);
    if (card) updateCard(card, monitor);
  }
}

connectWS(handleMessage);
