"use strict";

const els = {
  uniqueId: document.getElementById("unique-id"),
  addBtn: document.getElementById("add-btn"),
  addMessage: document.getElementById("add-message"),
  tabBar: document.getElementById("tab-bar"),
  detailArea: document.getElementById("detail-area"),
  noMonitor: document.getElementById("no-monitor"),
  detailTitle: document.getElementById("detail-title"),
  spinner: document.getElementById("spinner"),
  statusBadge: document.getElementById("status-badge"),
  statusMessage: document.getElementById("status-message"),
  stopBtn: document.getElementById("stop-btn"),
  restartBtn: document.getElementById("restart-btn"),
  removeBtn: document.getElementById("remove-btn"),
  steps: document.getElementById("steps"),
  giftStreak: document.getElementById("gift-streak"),
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
    battle_points: document.getElementById("stat-battle-points"),
    events_total: document.getElementById("stat-events"),
    rate_gifts: document.getElementById("stat-rate-gifts"),
    rate_diamonds: document.getElementById("stat-rate-diamonds"),
    rate_comments: document.getElementById("stat-rate-comments"),
    rate_likes: document.getElementById("stat-rate-likes"),
  },
  uptime: document.getElementById("stat-uptime"),
};

const FEED_LIMIT = 100;
const EVENT_KINDS = ["gift", "comment", "like", "follow", "share", "join", "subscribe", "battle", "system"];
const activeKinds = new Set(EVENT_KINDS);

const monitors = new Map();
let activeTab = null;
let streakTimer = null;
const detailChart = createTimelineChart(document.getElementById("timeline-chart"));

function getMonitor(uid) {
  if (!monitors.has(uid)) {
    monitors.set(uid, { snapshot: null, events: [] });
  }
  return monitors.get(uid);
}

function pushEvent(monitor, ev) {
  monitor.events.push(ev);
  if (monitor.events.length > FEED_LIMIT * 2) {
    monitor.events.splice(0, monitor.events.length - FEED_LIMIT * 2);
  }
}

function syncMonitors(snapshots) {
  const seen = new Set();
  snapshots.forEach((snap) => {
    seen.add(snap.unique_id);
    const monitor = getMonitor(snap.unique_id);
    monitor.snapshot = snap;
    if (Array.isArray(snap.recent_events) && snap.recent_events.length) {
      monitor.events = snap.recent_events.slice(-FEED_LIMIT * 2);
    }
  });
  [...monitors.keys()].forEach((uid) => {
    if (!seen.has(uid)) monitors.delete(uid);
  });
  if (!monitors.has(activeTab)) {
    activeTab = monitors.size ? [...monitors.keys()][0] : null;
  }
  renderTabs();
  renderDetail();
}

function renderTabs() {
  els.tabBar.innerHTML = "";
  monitors.forEach((monitor, uid) => {
    const tab = document.createElement("button");
    tab.className = `tab${uid === activeTab ? " tab-active" : ""}`;
    const dot = document.createElement("span");
    const status = monitor.snapshot ? monitor.snapshot.status : "idle";
    dot.className = `tab-dot dot-${status}`;
    dot.textContent = "●";
    const label = document.createElement("span");
    label.textContent = `@${uid}`;
    tab.append(dot, label);
    tab.addEventListener("click", () => {
      activeTab = uid;
      renderTabs();
      renderDetail();
    });
    els.tabBar.appendChild(tab);
  });
  const has = monitors.size > 0;
  els.detailArea.classList.toggle("hidden", !has);
  els.noMonitor.classList.toggle("hidden", has);
}

function renderDetail() {
  if (!activeTab) return;
  const monitor = monitors.get(activeTab);
  if (!monitor || !monitor.snapshot) return;
  els.detailTitle.textContent = `@${activeTab} の監視状況`;
  applyState(monitor.snapshot);
  rebuildFeeds(monitor);
  refreshAnalytics();
}

function applyState(state) {
  const info = STATUS_LABELS[state.status] || STATUS_LABELS.idle;
  els.statusBadge.textContent = info.badge;
  els.statusBadge.className = `badge ${info.cls}`;
  const simulationTag = state.simulation ? " [Simulation mode]" : "";
  const message = state.status === "error" ? state.error_message || info.message : info.message;
  els.statusMessage.textContent = message + simulationTag;

  const active = ["waiting", "connecting", "connected", "reconnecting"].includes(state.status);
  const busy = ["waiting", "connecting", "reconnecting"].includes(state.status);
  els.spinner.classList.toggle("hidden", !busy);
  els.stopBtn.disabled = !active;
  els.restartBtn.disabled = active;

  renderSteps(state.steps || []);
  applyStats(state.stats || {});
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
    if (key in stats) el.textContent = fmtNum(stats[key]);
  });
}

setInterval(() => {
  if (!activeTab) return;
  const monitor = monitors.get(activeTab);
  const snap = monitor && monitor.snapshot;
  if (snap && snap.status === "connected" && snap.stats && snap.stats.connected_at) {
    els.uptime.textContent = fmtDuration(Date.now() / 1000 - snap.stats.connected_at);
  } else {
    els.uptime.textContent = "--:--:--";
  }
}, 1000);

function clearFeeds() {
  Object.values(els.feeds).forEach((feed) => {
    feed.list.innerHTML = "";
    feed.empty.classList.remove("hidden");
  });
}

function rebuildFeeds(monitor) {
  clearFeeds();
  monitor.events.slice(-FEED_LIMIT).forEach((ev) => addEventToDOM(ev, true));
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

function addEventToDOM(ev, silent = false) {
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
    v.textContent = fmtNum(value);
    chip.append(l, v);
    totalsEl.appendChild(chip);
  });

  renderTableRows(
    "user-ranking",
    "user-ranking-empty",
    summary.users || [],
    (user, rank) => [
      String(rank),
      user.unique_id ? `${user.nickname} (@${user.unique_id})` : user.nickname,
      fmtNum(user.gifts),
      fmtNum(user.diamonds),
      topItemText(user.items),
    ],
    [0, 2, 3],
  );
  renderTableRows(
    "gift-ranking",
    "gift-ranking-empty",
    summary.gifts || [],
    (gift, rank) => [
      String(rank),
      gift.name,
      fmtNum(gift.count),
      fmtNum(gift.diamonds_each),
      fmtNum(gift.diamonds),
    ],
    [0, 2, 3, 4],
  );
}

let analyticsBusy = false;

async function refreshAnalytics() {
  if (analyticsBusy || !activeTab) return;
  const uid = activeTab;
  analyticsBusy = true;
  try {
    const [timelineRes, summaryRes] = await Promise.all([
      fetch(`/api/monitors/${encodeURIComponent(uid)}/timeline`),
      fetch(`/api/monitors/${encodeURIComponent(uid)}/summary`),
    ]);
    if (uid !== activeTab) return;
    if (timelineRes.ok) detailChart.update(await timelineRes.json());
    if (summaryRes.ok) applySummary(await summaryRes.json());
  } catch (err) {
    console.warn("analytics refresh failed", err);
  } finally {
    analyticsBusy = false;
  }
}

setInterval(() => {
  if (!activeTab) return;
  const monitor = monitors.get(activeTab);
  const status = monitor && monitor.snapshot ? monitor.snapshot.status : null;
  if (["connecting", "connected", "reconnecting"].includes(status)) {
    refreshAnalytics();
  }
}, 5000);

function handleMessage(msg) {
  if (msg.type === "monitors") {
    syncMonitors(msg.data);
    return;
  }
  const uid = msg.monitor;
  if (!uid || !monitors.has(uid)) return;
  const monitor = monitors.get(uid);
  if (msg.type === "state") {
    monitor.snapshot = msg.data;
    monitor.snapshot.unique_id = uid;
    if (Array.isArray(msg.data.recent_events) && msg.data.recent_events.length) {
      monitor.events = msg.data.recent_events.slice(-FEED_LIMIT * 2);
    }
    renderTabs();
    if (uid === activeTab) {
      applyState(monitor.snapshot);
      rebuildFeeds(monitor);
      refreshAnalytics();
    }
  } else if (msg.type === "stats") {
    if (monitor.snapshot) monitor.snapshot.stats = msg.data;
    if (uid === activeTab) applyStats(msg.data);
  } else if (msg.type === "event") {
    if (msg.data.kind !== "gift_streak") pushEvent(monitor, msg.data);
    if (uid === activeTab) addEventToDOM(msg.data);
  }
}

els.addBtn.addEventListener("click", async () => {
  const uniqueId = els.uniqueId.value.trim().replace(/^@/, "");
  if (!uniqueId) {
    els.addMessage.textContent = "TikTok IDを入力してください。";
    return;
  }
  els.addBtn.disabled = true;
  els.addMessage.textContent = "監視開始をRequest中…";
  try {
    await apiSend("POST", "/api/monitors", { unique_id: uniqueId });
    activeTab = uniqueId;
    els.uniqueId.value = "";
    els.addMessage.textContent = "";
  } catch (err) {
    els.addMessage.textContent = err.message;
  } finally {
    els.addBtn.disabled = false;
  }
});

els.uniqueId.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !els.addBtn.disabled) els.addBtn.click();
});

els.stopBtn.addEventListener("click", async () => {
  if (!activeTab) return;
  els.stopBtn.disabled = true;
  try {
    await apiSend("POST", `/api/monitors/${encodeURIComponent(activeTab)}/stop`);
  } catch (err) {
    els.statusMessage.textContent = err.message;
  }
});

els.restartBtn.addEventListener("click", async () => {
  if (!activeTab) return;
  els.restartBtn.disabled = true;
  try {
    await apiSend("POST", "/api/monitors", { unique_id: activeTab });
  } catch (err) {
    els.statusMessage.textContent = err.message;
    els.restartBtn.disabled = false;
  }
});

els.removeBtn.addEventListener("click", async () => {
  if (!activeTab) return;
  if (!window.confirm(`@${activeTab} を監視対象から外しますか？（収集済みSessionは履歴に残ります）`)) return;
  try {
    await apiSend("DELETE", `/api/monitors/${encodeURIComponent(activeTab)}`);
  } catch (err) {
    els.statusMessage.textContent = err.message;
  }
});

initEventFilters();
const params = new URLSearchParams(location.search);
if (params.get("monitor")) activeTab = params.get("monitor");
connectWS(handleMessage);
