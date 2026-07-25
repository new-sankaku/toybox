"use strict";

const els = {
  uniqueId: document.getElementById("unique-id"),
  addBtn: document.getElementById("add-btn"),
  addMessage: document.getElementById("add-message"),
  tabBar: document.getElementById("tab-bar"),
  mainArea: document.getElementById("main-area"),
  noMonitor: document.getElementById("no-monitor"),
  liveOwner: document.getElementById("live-owner"),
  statusBadge: document.getElementById("status-badge"),
  statusMessage: document.getElementById("status-message"),
  stopBtn: document.getElementById("stop-btn"),
  restartBtn: document.getElementById("restart-btn"),
  removeBtn: document.getElementById("remove-btn"),
  recordBtn: document.getElementById("record-btn"),
  bookmarkBtn: document.getElementById("bookmark-btn"),
  recordVideoBtn: document.getElementById("record-video-btn"),
  addRecordVideo: document.getElementById("add-record-video"),
  recBadge: document.getElementById("rec-badge"),
  recBadgeText: document.getElementById("rec-badge-text"),
  liveVideo: document.getElementById("live-video"),
  videoMsg: document.getElementById("video-msg"),
  audioBtn: document.getElementById("audio-btn"),
  steps: document.getElementById("steps"),
  giftStreak: document.getElementById("gift-streak"),
  battleList: document.getElementById("battle-list"),
  battleEmpty: document.getElementById("battle-empty"),
  pkSupport: document.getElementById("pk-support"),
  cmpBody: document.getElementById("cmp-body"),
  cmpEmpty: document.getElementById("cmp-empty"),
  cmpLabel: document.getElementById("cmp-label"),
  counts: {
    gift: document.getElementById("cnt-gift"),
    comment: document.getElementById("cnt-comment"),
    event: document.getElementById("cnt-event"),
    battle: document.getElementById("cnt-battle"),
  },
  feeds: {
    gift: { list: document.getElementById("gift-feed"), empty: document.getElementById("gift-empty") },
    comment: { list: document.getElementById("comment-feed"), empty: document.getElementById("comment-empty") },
    event: { list: document.getElementById("event-feed"), empty: document.getElementById("event-empty") },
    // Ranking paneに出す直近gift。Gift feedとはDOM nodeを共有できない(prependは移動に
    // なる)ので、同じeventからnodeを2つ作る。
    giftRecent: {
      list: document.getElementById("rank-recent-gift"),
      empty: document.getElementById("rank-recent-gift-empty"),
      limit: 6,
    },
  },
  stats: {
    viewers: document.getElementById("stat-viewers"),
    anonymous: document.getElementById("stat-anonymous"),
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

const ACTIVE_TAB_KEY = "tictok.activeTab";
const monitors = new Map();
let activeTab = localStorage.getItem(ACTIVE_TAB_KEY) || null;
let streakTimer = null;

function setActiveTab(uid) {
  activeTab = uid;
  if (uid) localStorage.setItem(ACTIVE_TAB_KEY, uid);
  else localStorage.removeItem(ACTIVE_TAB_KEY);
}
const detailChart = createTimelineChart(document.getElementById("timeline-chart"));

function getMonitor(uid) {
  if (!monitors.has(uid)) {
    monitors.set(uid, { snapshot: null, events: [], battles: [], history: null, profile: null });
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
    setActiveTab(monitors.size ? [...monitors.keys()][0] : null);
  }
  renderTabs();
  renderDetail();
}

function ownerOf(monitor, uid) {
  const owner = monitor && monitor.snapshot && monitor.snapshot.owner;
  if (owner && (owner.nickname || owner.unique_id)) return owner;
  return { unique_id: uid, nickname: uid, avatar: "" };
}

function tabTooltip(monitor, uid) {
  const snap = monitor.snapshot || {};
  const status = snap.status || "idle";
  const stats = snap.stats || {};
  const owner = ownerOf(monitor, uid);
  const rec = snap.recording;
  const recording = !!rec && (rec.state === "recording" || rec.state === "stopping");
  const label = (STATUS_LABELS[status] || STATUS_LABELS.idle).badge;
  const dataOnly = snap.record_video === false ? " · データのみ" : "";
  let tip = `${owner.nickname || uid}  @${uid}\n${label}${recording ? " · ●REC" : ""}${dataOnly}`;
  if (["connected", "reconnecting"].includes(status)) {
    tip += `\n視聴 ${fmtCompact(stats.viewers)} · コイン ${fmtCompact(stats.diamonds)}`;
  }
  return tip;
}

// stats受信のたびに変わるのはtooltipの数値だけなので、tab自体（avatar含む）は
// 作り直さずtitle/aria-labelのみ書き換える（毎回再構築するとavatarがちらつく）。
function updateTabTooltips() {
  els.tabBar.querySelectorAll(".a-tab").forEach((tab) => {
    const uid = tab.dataset.uid;
    const monitor = uid ? monitors.get(uid) : null;
    if (!monitor) return;
    const tip = tabTooltip(monitor, uid);
    tab.title = tip;
    tab.setAttribute("aria-label", tip);
  });
}

function renderTabs() {
  els.tabBar.innerHTML = "";
  monitors.forEach((monitor, uid) => {
    const snap = monitor.snapshot || {};
    const status = snap.status || "idle";
    const owner = ownerOf(monitor, uid);

    const tab = document.createElement("button");
    tab.className = `a-tab st-${status}${uid === activeTab ? " on" : ""}`;
    tab.dataset.uid = uid;

    // アバター + 配信者名を表示。状態はアバターを囲む status ring / spinner で表す。
    const ring = document.createElement("span");
    ring.className = `a-tab-ring ring-${status}`;
    ring.appendChild(avatarNode(owner, "tab"));

    const rec = snap.recording;
    const recording = !!rec && (rec.state === "recording" || rec.state === "stopping");
    if (recording) {
      const recDot = document.createElement("span");
      recDot.className = "a-tab-rec";
      ring.appendChild(recDot);
    }
    tab.appendChild(ring);

    const name = document.createElement("span");
    name.className = "a-tab-name";
    name.textContent = owner.nickname || uid;
    tab.appendChild(name);

    // @id / 数値 / 詳細な状態は hover の tooltip に退避して横幅を抑える。
    const tip = tabTooltip(monitor, uid);
    tab.title = tip;
    tab.setAttribute("aria-label", tip);

    tab.addEventListener("click", () => {
      setActiveTab(uid);
      renderTabs();
      renderDetail();
    });
    els.tabBar.appendChild(tab);
  });
  const has = monitors.size > 0;
  els.mainArea.classList.toggle("hidden", !has);
  els.noMonitor.classList.toggle("hidden", has);
}

function renderDetail() {
  if (!activeTab) return;
  const monitor = monitors.get(activeTab);
  if (!monitor || !monitor.snapshot) return;
  const owner = ownerOf(monitor, activeTab);
  els.liveOwner.innerHTML = "";
  els.liveOwner.appendChild(userCell(owner));
  applyState(monitor.snapshot);
  rebuildFeeds(monitor);
  renderBattles(monitor.battles);
  refreshAnalytics();
  refreshHistory();
  refreshBattles();
  refreshProfile(activeTab);
}

// 過去対戦勝敗用に配信者profileを取得しcache。過去(persisted)データなのでlive更新は不要、
// tab表示時に一度取れば十分。取得後、進行中PKがあれば対戦勝敗を反映するため再描画する。
async function refreshProfile(uid) {
  try {
    const res = await fetch(`/api/streamers/${encodeURIComponent(uid)}/profile`);
    if (!res.ok || uid !== activeTab) return;
    const monitor = monitors.get(uid);
    if (!monitor) return;
    monitor.profile = await res.json();
    renderPkSupport(monitor.battles, ownerOf(monitor, uid));
  } catch (err) {
    console.warn("profile refresh failed", err);
  }
}

async function refreshBattles() {
  if (!activeTab) return;
  const uid = activeTab;
  try {
    const res = await fetch(`/api/monitors/${encodeURIComponent(uid)}/battles`);
    if (!res.ok || uid !== activeTab) return;
    const data = await res.json();
    const monitor = monitors.get(uid);
    if (monitor) {
      monitor.battles = data.battles || [];
      renderBattles(monitor.battles);
    }
  } catch (err) {
    console.warn("battles refresh failed", err);
  }
}

function applyState(state) {
  const info = STATUS_LABELS[state.status] || STATUS_LABELS.idle;
  els.statusBadge.textContent = info.badge;
  els.statusBadge.className = `badge ${info.cls}`;
  const simulationTag = state.simulation ? " · simulation" : "";
  const message = state.status === "error" ? state.error_message || info.message : info.message;
  els.statusMessage.textContent = message + simulationTag;

  const active = ["waiting", "connecting", "connected", "reconnecting", "restricted"].includes(state.status);
  els.stopBtn.disabled = !active;
  els.restartBtn.disabled = active;

  applyRecording(state);
  updateRecordVideoToggle(state);
  renderSteps(state.steps || []);
  applyStats(state.stats || {});
}

function updateRecordVideoToggle(state) {
  if (!els.recordVideoBtn) return;
  const on = state.record_video !== false;
  els.recordVideoBtn.textContent = on ? "🎥 動画保存: ON" : "🚫 動画保存: OFF";
  els.recordVideoBtn.classList.toggle("on", on);
  els.recordVideoBtn.title = on
    ? "この監視対象の配信を録画します。OFFにするとデータのみ収集します。"
    : "この監視対象はデータのみ収集し、動画は保存しません。";
}

let hlsInstance = null;
let playerUid = null;
let audioEnabled = false;

function stopPlayer() {
  if (hlsInstance) {
    hlsInstance.destroy();
    hlsInstance = null;
  }
  if (els.liveVideo) {
    els.liveVideo.removeAttribute("src");
    els.liveVideo.load();
  }
  playerUid = null;
  els.liveVideo.classList.add("hidden");
  els.videoMsg.classList.remove("hidden");
  els.videoMsg.textContent = "● LIVE Preview（録画中に表示）";
}

function startPlayer(uid) {
  if (playerUid === uid && hlsInstance) return;
  stopPlayer();
  playerUid = uid;
  els.liveVideo.classList.remove("hidden");
  els.videoMsg.classList.remove("hidden");
  els.videoMsg.textContent = "映像を読み込み中…（数秒の遅延があります）";
  const src = `/api/monitors/${encodeURIComponent(uid)}/record/live/index.m3u8`;
  const video = els.liveVideo;
  video.muted = !audioEnabled;
  updateAudioButton();
  if (window.Hls && window.Hls.isSupported()) {
    hlsInstance = new window.Hls({ liveSyncDuration: 4, lowLatencyMode: false });
    hlsInstance.loadSource(src);
    hlsInstance.attachMedia(video);
    hlsInstance.on(window.Hls.Events.MANIFEST_PARSED, () => {
      els.videoMsg.classList.add("hidden");
      video.play().catch(() => {});
    });
    hlsInstance.on(window.Hls.Events.ERROR, (_e, data) => {
      if (data.fatal) {
        els.videoMsg.classList.remove("hidden");
        els.videoMsg.textContent = "映像を待機中…";
        setTimeout(() => {
          if (playerUid === uid && hlsInstance) hlsInstance.startLoad();
        }, 2000);
      }
    });
  } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
    video.src = src;
    video.addEventListener("loadedmetadata", () => video.play().catch(() => {}));
    els.videoMsg.classList.add("hidden");
  } else {
    els.videoMsg.textContent = "このBrowserはHLS再生に対応していません。";
  }
}

function updateAudioButton() {
  els.audioBtn.textContent = audioEnabled ? "🔊 音声ON" : "🔇 音声OFF";
}

els.audioBtn.addEventListener("click", () => {
  audioEnabled = !audioEnabled;
  els.liveVideo.muted = !audioEnabled;
  if (audioEnabled) els.liveVideo.play().catch(() => {});
  updateAudioButton();
});

function applyRecording(state) {
  const rec = state.recording;
  const recording = !!rec && (rec.state === "recording" || rec.state === "stopping");
  const finalizing = !!rec && rec.state === "finalizing";
  const connected = state.status === "connected";

  if (rec && rec.live && rec.state === "recording") {
    startPlayer(state.unique_id);
  } else {
    stopPlayer();
  }

  if (!state.ffmpeg_available) {
    els.recordBtn.disabled = true;
    els.recordBtn.textContent = "● 録画 (ffmpeg未install)";
    els.recordBtn.title = "録画にはサーバーにffmpegのinstallが必要です。";
    els.recordBtn.classList.remove("rec", "on");
  } else if (recording) {
    els.recordBtn.disabled = rec.state === "stopping";
    els.recordBtn.textContent = "■ 録画停止";
    els.recordBtn.classList.add("rec", "on");
    els.recordBtn.title = "";
  } else if (state.record_video === false) {
    els.recordBtn.disabled = true;
    els.recordBtn.textContent = "● 録画 (動画保存OFF)";
    els.recordBtn.title = "この監視対象は動画保存OFF（データのみ収集）です。動画保存をONにすると録画できます。";
    els.recordBtn.classList.remove("rec", "on");
  } else {
    els.recordBtn.disabled = !connected;
    els.recordBtn.textContent = "● 録画開始";
    els.recordBtn.classList.remove("rec", "on");
    els.recordBtn.title = connected ? "" : "配信に接続中のみ録画できます。";
  }

  // 見どころは動画の中の位置を指すので、録画中だけ押せる。録画していない配信に印を
  // 置いても、後から戻る先が無い。
  const canBookmark = !!rec && rec.state === "recording" && !!rec.recording_id;
  els.bookmarkBtn.disabled = !canBookmark;
  if (!canBookmark) {
    els.bookmarkBtn.title = "録画中のみ記録できます。";
  } else {
    els.bookmarkBtn.title = "いま見ている場面を見どころとして記録します（キー: B）。";
  }

  if (rec && (recording || finalizing || rec.state === "completed" || rec.state === "failed")) {
    els.recBadge.classList.remove("hidden");
    const mb = (rec.bytes / 1048576).toFixed(1);
    if (recording) {
      const secs = rec.started_at ? Math.floor(Date.now() / 1000 - rec.started_at) : 0;
      els.recBadgeText.textContent = `REC [${rec.quality || "-"}] ${fmtDuration(secs)} / ${mb}MB`;
    } else if (finalizing) {
      els.recBadgeText.textContent = `保存中… (${mb}MB)`;
    } else if (rec.state === "completed") {
      els.recBadgeText.textContent = `完了 ${rec.filename || "-"} (${mb}MB)`;
    } else {
      els.recBadgeText.textContent = `失敗: ${rec.error || "不明なError"}`;
    }
  } else {
    els.recBadge.classList.add("hidden");
  }
}

const STEP_MARKS = { pending: "□", active: "◆", done: "■", failed: "✕" };

function renderSteps(steps) {
  els.steps.innerHTML = "";
  steps.forEach((step) => {
    const li = document.createElement("li");
    li.className = `step-${step.status}`;
    const mark = document.createElement("span");
    mark.className = "mark";
    mark.textContent = STEP_MARKS[step.status] || "□";
    const label = document.createElement("span");
    label.textContent = step.label;
    li.append(mark, label);
    els.steps.appendChild(li);
  });
}

function applyStats(stats) {
  Object.entries(els.stats).forEach(([key, el]) => {
    if (el && key in stats) el.textContent = fmtNum(stats[key]);
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
  updateCounts();
}

function feedItemNode(ev, contentNodes, filterable) {
  const li = document.createElement("li");
  li.className = `it feed-item-${ev.kind}`;
  if (filterable) {
    li.dataset.kind = ev.kind;
    if (!activeKinds.has(ev.kind)) li.classList.add("filtered-out");
  }
  const meta = document.createElement("div");
  meta.className = "meta";
  const kind = document.createElement("span");
  kind.className = "kind";
  kind.textContent = ev.kind;
  const time = document.createElement("span");
  time.textContent = fmtTime(ev.time);
  meta.append(kind, time);
  const body = document.createElement("div");
  contentNodes.forEach((n) => body.append(n));
  li.append(meta, body);
  return li;
}

function giftContent(ev) {
  const nodes = [userCell(ev.user)];
  const tail = document.createElement("span");
  tail.textContent = ev.gift_name
    ? ` → ${ev.gift_name} ×${ev.repeat_count || 1} (${fmtNum(ev.diamonds)}コイン)`
    : ` ${ev.text || ""}`;
  nodes.push(tail);
  return nodes;
}

function addToFeed(feed, node, silent) {
  feed.empty.classList.add("hidden");
  if (silent) node.style.animation = "none";
  feed.list.prepend(node);
  while (feed.list.children.length > (feed.limit || FEED_LIMIT)) {
    feed.list.removeChild(feed.list.lastChild);
  }
}

function addEventToDOM(ev, silent = false) {
  if (ev.kind === "gift_streak") {
    showStreak(ev);
    return;
  }
  // Event log (all kinds)
  let eventNodes;
  if (ev.kind === "gift") {
    eventNodes = giftContent(ev);
  } else if (ev.user) {
    const wrap = [userCell(ev.user)];
    const tail = document.createElement("span");
    tail.textContent = ev.comment ? `: ${ev.comment}` : ` ${stripUser(ev)}`;
    wrap.push(tail);
    eventNodes = wrap;
  } else {
    const span = document.createElement("span");
    span.textContent = ev.text || "";
    eventNodes = [span];
  }
  addToFeed(els.feeds.event, feedItemNode(ev, eventNodes, true), silent);

  if (ev.kind === "gift") {
    addToFeed(els.feeds.gift, feedItemNode(ev, giftContent(ev), false), silent);
    addToFeed(els.feeds.giftRecent, feedItemNode(ev, giftContent(ev), false), silent);
  } else if (ev.kind === "comment") {
    const nodes = [userCell(ev.user)];
    const tail = document.createElement("span");
    tail.textContent = `: ${ev.comment}`;
    nodes.push(tail);
    addToFeed(els.feeds.comment, feedItemNode(ev, nodes, false), silent);
  }
}

function stripUser(ev) {
  // Event text already embeds nickname; for the event feed we render the user
  // chip separately, so show only the action remainder when possible.
  const nick = ev.user && ev.user.nickname;
  if (nick && ev.text && ev.text.startsWith(nick)) return ev.text.slice(nick.length).trim();
  return ev.text || "";
}

function updateCounts() {
  els.counts.gift.textContent = fmtCompact(els.feeds.gift.list.children.length);
  els.counts.comment.textContent = fmtCompact(els.feeds.comment.list.children.length);
  els.counts.event.textContent = fmtCompact(els.feeds.event.list.children.length);
  const monitor = activeTab && monitors.get(activeTab);
  els.counts.battle.textContent = fmtCompact(monitor && monitor.battles ? monitor.battles.length : 0);
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

// ---- segmented activity pane ----
// 選択paneは画面遷移(全体監視→監視はフルリロード)で失われるため、localStorageに保持し
// 復元する。存在しないpane値だった場合はHTML既定(gift)のまま据え置く。
const SEG_PANE_KEY = "tictok.activePane";

function applySegPane(pane) {
  const btn = document.querySelector(`#seg-bar button[data-pane="${pane}"]`);
  if (!btn) return false;
  document.querySelectorAll("#seg-bar button").forEach((b) => b.classList.toggle("on", b === btn));
  document.querySelectorAll(".seg-pane").forEach((p) => p.classList.toggle("hidden", p.dataset.pane !== pane));
  return true;
}

document.getElementById("seg-bar").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-pane]");
  if (!btn) return;
  applySegPane(btn.dataset.pane);
  localStorage.setItem(SEG_PANE_KEY, btn.dataset.pane);
});

applySegPane(localStorage.getItem(SEG_PANE_KEY));

// ---- battles ----
// 履歴詳細と同じ共有Battleカード(renderBattleCards)で描画し、スコア推移chartまで
// liveに表示する。owner(自陣の表示名/avatar)は対象monitorのsnapshotから取る。
function renderBattles(battles) {
  const list = battles || [];
  els.battleEmpty.classList.toggle("hidden", list.length > 0);
  const monitor = activeTab ? monitors.get(activeTab) : null;
  const owner = monitor ? ownerOf(monitor, activeTab) : {};
  renderBattleCards(els.battleList, list, owner);
  renderPkSupport(list, owner);
  updateCounts();
}

// ---- PK応援 (Phase 1: 受信専用・loginなし) ----
// 進行中PKのスコア差/残り時間や状態を、機械的(状態読み上げ型)のセリフ候補として出す。
// 投稿は一切自動化せず、本人がコピーしてTikTokのコメント欄へ貼る前提(規約risk回避)。

// 進行中Battleの局面(phase)を実数から判定する。残り時間はBattleSetting由来の予定終了
// (end_time)が来ている場合のみ算出し、無ければnull(countdownを出さない=捏造しない)。
function pkSituation(b) {
  const own = b.own_score || 0;
  // 個人マルチ(Nコラ)は各参加者が独立し、opp_scoreは敵陣全員の合算になる。差は合算ではなく
  // 直近のrival(自分が首位なら2位、それ以外は一つ上位)との対比で見るべきなので置き換える。
  const rival = pkNearestRival(b);
  const opp = rival ? rival.score || 0 : b.opp_score || 0;
  const gap = own - opp;
  const now = Date.now() / 1000;
  // 終了後(ongoing=false)は残り時間/勢い/マイルストーンを出さず、結果(ended)として扱う。
  const remaining = b.ongoing && b.end_time ? Math.max(0, b.end_time - now) : null;
  const elapsed = b.start_time ? Math.max(0, now - b.start_time) : 0;
  let phase;
  if (!b.ongoing) phase = "ended";
  else if (remaining != null && remaining <= 10) phase = "last10";
  else if (remaining != null && remaining <= 60) phase = "last60";
  else if (elapsed <= 20) phase = "start";
  else phase = "mid";
  // 残り時間が分かる時の「残りN分」マイルストーン(N=ceil)。残り4分/3分… の時点を表す。
  const minuteMark = phase !== "ended" && remaining != null ? Math.ceil(remaining / 60) : null;
  const momentum = b.ongoing ? pkMomentum(b, gap) : "stable";
  return { own, opp, gap, remaining, phase, minuteMark, momentum };
}

// 個人マルチ(Nコラ)で自分の直近の競争相手。首位なら2位、それ以外は一つ上位(rank-1)。
// rankはbackendがscore降順で1始まりに付与する。参加者2人以下(1v1)や自分が居なければnull。
function pkNearestRival(b) {
  if (b.type === "team") return null;
  const parts = b.participants || [];
  if (parts.length <= 2) return null;
  const own = parts.find((p) => p.is_own);
  if (!own) return null;
  const targetRank = (own.rank || 1) === 1 ? 2 : (own.rank || 1) - 1;
  return parts.find((p) => p.rank === targetRank) || null;
}

// score_series([{t,own,opp}])の直近〜25秒前との符号反転(逆転)だけを見る。優勢/劣勢に
// 転じた瞬間のみ通知し、差の拡大/縮小は出さない。点が足りない序盤はstable(表示なし)。
function pkMomentum(b, curGap) {
  // 個人マルチはscore_seriesのoppが首位の敵1人ぶんで、直近rival(rank-1)との逆転は
  // 判定できない。誤認を避けるため勢い(逆転)は出さない。
  if (pkNearestRival(b)) return "stable";
  const series = b.score_series || [];
  if (series.length < 2) return "stable";
  const last = series[series.length - 1];
  let prev = series[0];
  for (let i = series.length - 1; i >= 0; i--) {
    if (last.t - series[i].t >= 25) {
      prev = series[i];
      break;
    }
  }
  const prevGap = (prev.own || 0) - (prev.opp || 0);
  if (prevGap >= 0 && curGap < 0) return "flipLose";
  if (prevGap < 0 && curGap >= 0) return "flipWin";
  return "stable";
}

// side側の貢献者数。minScore指定時は「N コイン(実弾)以上」を投げた人を数える。100↑=100コイン
// 以上、というuserの読み(実弾列)と数え方を揃える。自陣は実弾を実測できるので実弾で判定し、
// 相手陣は別Roomで実弾が取れないため、その場合のみBS(score)を代用する。
function contribCoins(c) {
  const dia = c.diamonds || 0;
  return dia > 0 ? dia : c.score || 0;
}
function pkContribCount(b, side, minScore) {
  const min = minScore || 0;
  return (b.contributions || []).filter((c) => c.side === side && contribCoins(c) >= min).length;
}

// スコアの簡易表記: xxx / xx.xK / xxxM(千=K, 百万=M, 小数1桁・末尾.0は省く)。
function pkScore(n) {
  const v = Number(n || 0);
  const a = Math.abs(v);
  if (a >= 1_000_000) return (v / 1_000_000).toFixed(1).replace(/\.0$/, "") + "M";
  if (a >= 1_000) return (v / 1_000).toFixed(1).replace(/\.0$/, "") + "K";
  return String(v);
}

// リード=+、ビハインド=- 付きの差(簡易表記)。
function pkSigned(gap) {
  return (gap >= 0 ? "+" : "-") + pkScore(Math.abs(gap));
}

// 対戦形式別のスコア実況。表記は自/敵に統一。差(signed)は全形式で「自(自チーム) vs 直近の敵」。
// 1v1/チーム=自/敵/差。個人マルチは全参加者のScoreを順位順に列挙し、自分を(自)で示す。
function pkScoreLine(b, s) {
  const parts = b.participants || [];
  if (b.type !== "team" && parts.length > 2) {
    return parts
      .slice()
      .sort((a, c) => (a.rank || 99) - (c.rank || 99))
      .map((p) => `${p.rank || "—"}位${p.is_own ? "(自)" : ""} ${pkScore(p.score || 0)}`)
      .join(" / ");
  }
  return `自 ${pkScore(s.own)} / 敵 ${pkScore(s.opp)} / 差 ${pkSigned(s.gap)}`;
}

// 過去(persisted)のこの相手との対戦勝敗。profile.battles.opponents を相手unique_id/nicknameで
// 突合。1v1のみ(マルチ/チームは「相手」が一意でないため出さない)。未対戦/0戦はnull。
function pkVsRecord(b, profile) {
  if (b.type === "team" || (b.participants || []).length > 2) return null;
  const opps = profile && profile.battles && profile.battles.opponents;
  if (!opps || !opps.length) return null;
  const opp = (b.opponents || [])[0];
  if (!opp) return null;
  const found = opps.find(
    (o) =>
      (opp.unique_id && o.unique_id === opp.unique_id) ||
      (opp.nickname && o.nickname === opp.nickname),
  );
  if (!found || found.wins + found.losses === 0) return null;
  return { wins: found.wins, losses: found.losses };
}

// 局面/残り分/勢いが変わった時だけコメントを作り直すための識別子(秒tickでの無駄な再構築を防ぐ)。
function pkSig(b, s) {
  return `${b.battle_id}|${s.phase}|${s.minuteMark}|${s.momentum}`;
}

function pkTimeText(s) {
  if (s.phase === "ended") return "終了";
  if (s.remaining == null) return "進行中";
  const sec = Math.ceil(s.remaining);
  if (sec >= 60) return `残り ${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
  return `残り ${sec}秒`;
}

// 機械的(状態読み上げ型)のセリフ。煽り/呼びかけ/絵文字は使わず、実数のみを差し込む。
// 表記は自/敵に統一。差はsigned(+/-)で全形式共通の意味(自 vs 直近の敵)。
function pkComments(b, s, vs) {
  const sg = pkSigned(s.gap);
  const sec = s.remaining != null ? Math.ceil(s.remaining) : null;
  const out = [];

  // 勢い: 優勢/劣勢に転じた瞬間(逆転)のみ。
  if (s.momentum === "flipWin") out.push(`優勢（${sg}）`);
  else if (s.momentum === "flipLose") out.push(`劣勢（${sg}）`);

  // 終了: 結果を先頭に。個人マルチは最終順位、1v1/チームは勝敗で示す(差は直近rival基準)。
  if (s.phase === "ended") {
    const parts = b.participants || [];
    const ownPart = parts.find((p) => p.is_own);
    if (b.type !== "team" && parts.length > 2 && ownPart) {
      out.push(`PK終了（${parts.length}人中 ${ownPart.rank}位 / 差 ${sg}）`);
    } else {
      const label = b.result === "win" ? "PK勝利" : b.result === "lose" ? "PK敗北" : "PK引き分け";
      out.push(`${label}（差 ${sg}）`);
    }
  }

  // 局面: 開始は形式(過去対戦があれば勝敗併記)、終盤は残り秒+差。
  if (s.phase === "start") {
    out.push(
      vs
        ? `PK開始（${battleModeLabel(b)} / 過去 ${vs.wins}勝${vs.losses}敗）`
        : `PK開始（${battleModeLabel(b)}）`,
    );
  } else if (s.phase === "last10" || s.phase === "last60") {
    out.push(`残り ${sec}秒（差 ${sg}）`);
  }

  // 残りN分マイルストーン(最後の1分は局面が担う)。
  if (s.minuteMark != null && s.remaining > 60) out.push(`残り ${s.minuteMark}分（差 ${sg}）`);

  // 実況(形式別: 1v1/チーム=自/敵, 個人マルチ=全参加者Score)。
  out.push(pkScoreLine(b, s));

  // 貢献者数(自/敵)。敵はOpponentRoomListenerが拾えた分のみ(0人あり)。
  out.push(`貢献 自 ${pkContribCount(b, "own")}人 / 敵 ${pkContribCount(b, "opp")}人`);
  // 100コイン(実弾)以上を投げた貢献者数。
  out.push(`100↑貢献 自 ${pkContribCount(b, "own", 100)}人 / 敵 ${pkContribCount(b, "opp", 100)}人`);

  return out.slice(0, 7);
}

async function pkCopy(text, btn) {
  const tag = btn.querySelector(".pk-copy");
  try {
    await navigator.clipboard.writeText(text);
    btn.classList.add("copied");
    tag.textContent = "コピー✓";
    setTimeout(() => {
      tag.textContent = "コピー";
      btn.classList.remove("copied");
    }, 1500);
  } catch (err) {
    tag.textContent = "失敗";
    console.warn("clipboard write failed", err);
  }
}

const pkState = { battleId: null, sig: null };
let pkTicker = null;

function ongoingBattle(battles) {
  return (battles || [])
    .filter((b) => b.ongoing)
    .sort((a, c) => (c.start_time || 0) - (a.start_time || 0))[0];
}

// バトル終了後もコピペ文を残すため、進行中が無ければ直近(start_time最新)のバトルを返す。
function latestBattle(battles) {
  return (battles || [])
    .slice()
    .sort((a, c) => (c.start_time || 0) - (a.start_time || 0))[0];
}

function renderPkSupport(battles, owner) {
  const panel = els.pkSupport;
  const segBtn = document.querySelector('#seg-bar button[data-pane="battle"]');
  const live = ongoingBattle(battles);
  // 進行中があればそれを、無ければ直近の終了済みバトルを表示し続ける(コピペは消さない)。
  const b = live || latestBattle(battles);
  if (segBtn) segBtn.classList.toggle("pk-live", Boolean(live));
  if (!b) {
    panel.classList.add("hidden");
    panel.innerHTML = "";
    pkState.battleId = null;
    pkState.sig = null;
    return;
  }
  const s = pkSituation(b);
  pkState.battleId = b.battle_id;
  pkState.sig = pkSig(b, s);
  panel.innerHTML = "";

  const head = document.createElement("div");
  head.className = "pk-head";
  const badge = document.createElement("span");
  badge.className = "pk-badge" + (b.ongoing ? "" : " ended");
  badge.textContent = b.ongoing ? "● PK中" : "PK終了";
  const mode = document.createElement("span");
  mode.className = "pk-mode";
  mode.textContent = battleModeLabel(b);
  const time = document.createElement("span");
  time.className = "pk-time";
  time.textContent = pkTimeText(s);
  head.append(badge, mode, time);
  panel.appendChild(head);

  const score = document.createElement("div");
  score.className = "pk-score";
  const ownEl = document.createElement("span");
  ownEl.className = "pk-own";
  ownEl.textContent = `自 ${pkScore(s.own)}`;
  const gapEl = document.createElement("span");
  gapEl.className = "pk-gap " + (s.gap > 0 ? "up" : s.gap < 0 ? "down" : "even");
  gapEl.textContent = pkSigned(s.gap);
  const oppEl = document.createElement("span");
  oppEl.className = "pk-opp";
  oppEl.textContent = `敵 ${pkScore(s.opp)}`;
  score.append(ownEl, gapEl, oppEl);
  panel.appendChild(score);

  const list = document.createElement("div");
  list.className = "pk-comments";
  const monitor = activeTab ? monitors.get(activeTab) : null;
  const vs = pkVsRecord(b, monitor && monitor.profile);
  pkComments(b, s, vs).forEach((text) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "pk-c";
    const t = document.createElement("span");
    t.className = "pk-t";
    t.textContent = text;
    const tag = document.createElement("span");
    tag.className = "pk-copy";
    tag.textContent = "コピー";
    btn.append(t, tag);
    btn.addEventListener("click", () => pkCopy(text, btn));
    list.appendChild(btn);
  });
  panel.appendChild(list);

  const note = document.createElement("p");
  note.className = "pk-note";
  note.textContent = "タップでコピー → TikTokのコメント欄に貼り付け";
  panel.appendChild(note);

  panel.classList.remove("hidden");
  ensurePkTicker();
}

// 残り時間のcountdownと、局面遷移(last60/last10入りなど)の追従。スコア更新はWS battlesで
// 全体再描画されるため、tickでは時間表示の更新と局面変化時の作り直しだけ行う。
function ensurePkTicker() {
  if (pkTicker) return;
  pkTicker = setInterval(() => {
    if (!activeTab) return;
    const monitor = monitors.get(activeTab);
    if (!monitor) return;
    const live = ongoingBattle(monitor.battles);
    const b = live || latestBattle(monitor.battles);
    const owner = ownerOf(monitor, activeTab);
    if (!b) {
      if (pkState.battleId) renderPkSupport(monitor.battles, owner);
      return;
    }
    const s = pkSituation(b);
    if (b.battle_id !== pkState.battleId || pkSig(b, s) !== pkState.sig) {
      renderPkSupport(monitor.battles, owner);
      return;
    }
    // 終了後は残り時間表示が無く、局面も変わらないのでcountdown更新は進行中のみ。
    if (live) {
      const t = els.pkSupport.querySelector(".pk-time");
      if (t) t.textContent = pkTimeText(s);
    }
  }, 1000);
}

// ---- ranking + analytics ----
function applySummary(summary) {
  renderTableRows(
    "user-ranking",
    "user-ranking-empty",
    summary.users || [],
    (user, rank) => [String(rank), userCell(user), fmtNum(user.gifts), fmtNum(user.diamonds)],
    [0, 2, 3],
  );
  renderTableRows(
    "gift-ranking",
    "gift-ranking-empty",
    summary.gifts || [],
    (gift, rank) => [String(rank), gift.name, fmtNum(gift.count), fmtNum(gift.diamonds)],
    [0, 2, 3],
  );
  const gifters = (summary.totals || {}).unique_gifters;
  document.getElementById("rank-gifters").textContent =
    gifters ? `Gifter ${fmtNum(gifters)}人` : "";
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
    if (timelineRes.ok) detailChart.update(await timelineRes.json(), (monitors.get(uid) || {}).battles || []);
    if (summaryRes.ok) applySummary(await summaryRes.json());
  } catch (err) {
    console.warn("analytics refresh failed", err);
  } finally {
    analyticsBusy = false;
  }
}

const CMP_METRICS = [
  { key: "gifts", label: "Gift", fmt: fmtNum },
  { key: "diamonds", label: "コイン", fmt: fmtNum },
  { key: "comments", label: "Comment", fmt: fmtNum },
  { key: "viewers", label: "視聴Peak", fmt: fmtNum },
  { key: "duration", label: "配信時間", fmt: fmtDurMin },
];

function fmtDurMin(seconds) {
  const s = Math.max(0, Math.floor(seconds || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${h}:${String(m).padStart(2, "0")}`;
}

let historyBusy = false;

async function refreshHistory() {
  if (historyBusy || !activeTab) return;
  const uid = activeTab;
  historyBusy = true;
  try {
    const res = await fetch(`/api/monitors/${encodeURIComponent(uid)}/history-stats`);
    if (!res.ok || uid !== activeTab) return;
    const data = await res.json();
    const monitor = monitors.get(uid);
    if (monitor) monitor.history = data;
    renderComparison(monitor);
  } catch (err) {
    console.warn("history refresh failed", err);
  } finally {
    historyBusy = false;
  }
}

function renderComparison(monitor) {
  const data = monitor && monitor.history;
  els.cmpLabel.textContent = `過去配信との比較（@${activeTab} · 直近${data ? data.count : 0}配信）`;
  els.cmpBody.innerHTML = "";
  if (!data || data.count === 0) {
    els.cmpEmpty.classList.remove("hidden");
    return;
  }
  els.cmpEmpty.classList.add("hidden");
  const snap = monitor.snapshot || {};
  const stats = snap.stats || {};
  const current = {
    gifts: stats.gifts || 0,
    diamonds: stats.diamonds || 0,
    comments: stats.comments || 0,
    viewers: stats.viewers_peak || stats.viewers || 0,
    duration: stats.connected_at ? Date.now() / 1000 - stats.connected_at : 0,
  };
  CMP_METRICS.forEach((m) => {
    const tr = document.createElement("tr");
    const cells = [
      { cls: "k", text: m.label },
      { cls: "now", text: m.fmt(current[m.key]) },
      { cls: "", text: data.last ? m.fmt(data.last[m.key]) : "-" },
      { cls: "", text: m.fmt(data.average[m.key]) },
      { cls: "best", text: m.fmt(data.best[m.key]) },
    ];
    cells.forEach((c) => {
      const td = document.createElement("td");
      if (c.cls) td.className = c.cls;
      td.textContent = c.text;
      tr.appendChild(td);
    });
    els.cmpBody.appendChild(tr);
  });
}

setInterval(() => {
  if (!activeTab) return;
  const monitor = monitors.get(activeTab);
  const status = monitor && monitor.snapshot ? monitor.snapshot.status : null;
  if (["connecting", "connected", "reconnecting"].includes(status)) {
    refreshAnalytics();
    renderComparison(monitor);
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
    const prevStatus = monitor.snapshot ? monitor.snapshot.status : null;
    monitor.snapshot = msg.data;
    monitor.snapshot.unique_id = uid;
    if (Array.isArray(msg.data.recent_events) && msg.data.recent_events.length) {
      monitor.events = msg.data.recent_events.slice(-FEED_LIMIT * 2);
    }
    renderTabs();
    if (uid === activeTab) {
      const owner = ownerOf(monitor, uid);
      els.liveOwner.innerHTML = "";
      els.liveOwner.appendChild(userCell(owner));
      applyState(monitor.snapshot);
      // フィード全再構築は初回接続時(タブ/監視切替はrenderDetailが担当)のみ。通常の
      // state更新では個別eventの増分追加に任せ、stats/状態表示のみ更新する。
      const wasConnected = ["connected", "reconnecting"].includes(prevStatus);
      const nowConnected = ["connected", "reconnecting"].includes(msg.data.status);
      if (nowConnected && !wasConnected) rebuildFeeds(monitor);
      refreshAnalytics();
      refreshHistory();
    }
  } else if (msg.type === "stats") {
    if (monitor.snapshot) monitor.snapshot.stats = msg.data;
    if (uid === activeTab) {
      applyStats(msg.data);
      updateTabTooltips();
    }
  } else if (msg.type === "battles") {
    monitor.battles = (msg.data && msg.data.battles) || [];
    if (uid === activeTab) renderBattles(monitor.battles);
  } else if (msg.type === "event") {
    if (msg.data.kind !== "gift_streak") pushEvent(monitor, msg.data);
    if (uid === activeTab) {
      addEventToDOM(msg.data);
      updateCounts();
    }
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
    const recordVideo = els.addRecordVideo ? els.addRecordVideo.checked : true;
    await apiSend("POST", "/api/monitors", { unique_id: uniqueId, record_video: recordVideo });
    setActiveTab(uniqueId);
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
  const ok = await confirmDialog(
    `@${activeTab} を監視対象から外しますか？（収集済みSessionは履歴に残ります）`,
    { title: "監視対象から外す", confirmLabel: "外す" },
  );
  if (!ok) return;
  try {
    await apiSend("DELETE", `/api/monitors/${encodeURIComponent(activeTab)}`);
  } catch (err) {
    els.statusMessage.textContent = err.message;
  }
});

els.recordBtn.addEventListener("click", async () => {
  if (!activeTab) return;
  const monitor = monitors.get(activeTab);
  const rec = monitor && monitor.snapshot && monitor.snapshot.recording;
  const recording = rec && (rec.state === "recording" || rec.state === "stopping");
  els.recordBtn.disabled = true;
  try {
    const action = recording ? "stop" : "start";
    await apiSend("POST", `/api/monitors/${encodeURIComponent(activeTab)}/record/${action}`);
  } catch (err) {
    els.statusMessage.textContent = err.message;
    els.recordBtn.disabled = false;
  }
});

// 見どころの登録。押した時刻はServerが打つ(browserの時計ずれを持ち込まない)。
// 登録直後の位置はwall-clock由来の暫定値で、録画のfinalizeでmp4のPTS軸へ載せ直される。
async function markBookmark() {
  if (!activeTab || els.bookmarkBtn.disabled) return;
  els.bookmarkBtn.disabled = true;
  try {
    await apiSend("POST", `/api/monitors/${encodeURIComponent(activeTab)}/bookmark`, { memo: "" });
    flashBookmarkSaved();
  } catch (err) {
    els.statusMessage.textContent = err.message;
  } finally {
    // 状態はWSのsnapshotで戻るが、失敗時に押せないままにしないよう即座に戻す。
    els.bookmarkBtn.disabled = false;
  }
}

function flashBookmarkSaved() {
  const btn = els.bookmarkBtn;
  const original = "🔖 見どころ";
  btn.textContent = "🔖 記録しました";
  clearTimeout(btn._flashTimer);
  btn._flashTimer = setTimeout(() => { btn.textContent = original; }, 1500);
}

els.bookmarkBtn.addEventListener("click", markBookmark);

// 「見ている最中に1押し」が目的なので、入力欄にいるとき以外はBキーでも打てるようにする。
document.addEventListener("keydown", (ev) => {
  if (ev.key !== "b" && ev.key !== "B") return;
  if (ev.ctrlKey || ev.altKey || ev.metaKey) return;
  const el = document.activeElement;
  if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable)) return;
  ev.preventDefault();
  markBookmark();
});

els.recordVideoBtn.addEventListener("click", async () => {
  if (!activeTab) return;
  const monitor = monitors.get(activeTab);
  const snap = monitor && monitor.snapshot;
  if (!snap) return;
  const next = snap.record_video === false;
  const rec = snap.recording;
  const recording = rec && (rec.state === "recording" || rec.state === "stopping");
  if (!next && recording) {
    const ok = await confirmDialog(
      `@${activeTab} の動画保存をOFFにすると進行中の録画を停止します。よろしいですか？`,
      { title: "動画保存をOFFにする", confirmLabel: "OFFにする" },
    );
    if (!ok) return;
  }
  els.recordVideoBtn.disabled = true;
  try {
    await apiSend("POST", `/api/monitors/${encodeURIComponent(activeTab)}/record-video`, { record_video: next });
  } catch (err) {
    els.statusMessage.textContent = err.message;
  } finally {
    els.recordVideoBtn.disabled = false;
  }
});

setInterval(() => {
  if (!activeTab) return;
  const monitor = monitors.get(activeTab);
  const rec = monitor && monitor.snapshot && monitor.snapshot.recording;
  if (rec && rec.state === "recording") applyRecording(monitor.snapshot);
}, 1000);

initEventFilters();
const params = new URLSearchParams(location.search);
if (params.get("monitor")) setActiveTab(params.get("monitor"));
connectWS(handleMessage);
