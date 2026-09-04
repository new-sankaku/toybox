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
  collabVs: document.getElementById("collab-vs"),
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
const EVENT_KINDS = ["gift", "comment", "like", "follow", "share", "join", "subscribe", "super_fan", "battle", "system"];
const activeKinds = new Set(EVENT_KINDS);

const ACTIVE_TAB_KEY = "tictok.activeTab";
const monitors = new Map();
let activeTab = prefGet(ACTIVE_TAB_KEY) || null;
let streakTimer = null;

function setActiveTab(uid) {
  activeTab = uid;
  prefSet(ACTIVE_TAB_KEY, uid || null);
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

    // 表示名だけでは同名の配信者を見分けられないので、@idはhoverに残す。
    tab.title = `@${uid}`;

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
  // tabを跨いだら開いていた相手は畳む(別配信者の対戦履歴が開いたまま残らないように)。
  collabState.peer = null;
  collabState.battleKey = null;
  collabState.sig = null;
  renderCollabVs(monitor);
  refreshAnalytics();
  refreshHistory();
  refreshBattles();
  refreshProfile(activeTab);
}

// 過去対戦勝敗用に配信者profileを取得しcache。過去(persisted)データなのでlive更新は不要、
// tab表示時に一度取れば十分。取得後、進行中PKがあれば対戦勝敗を反映するため再描画する。
async function refreshProfile(uid) {
  const monitor = monitors.get(uid);
  try {
    const res = await fetch(`/api/streamers/${encodeURIComponent(uid)}/profile`);
    if (uid !== activeTab || !monitor) return;
    // 取れなかったことを覚える。コラボ相手の欄が「読み込み中…」のまま止まると、
    // 待てば出るのか出ないのかが画面から読めない。
    monitor.profileFailed = !res.ok;
    if (!res.ok) {
      renderCollabVs(monitor);
      return;
    }
    monitor.profile = await res.json();
    renderPkSupport(monitor.battles, ownerOf(monitor, uid));
    renderCollabVs(monitor);
  } catch (err) {
    console.warn("profile refresh failed", err);
    if (monitor) {
      monitor.profileFailed = true;
      if (uid === activeTab) renderCollabVs(monitor);
    }
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
  els.videoMsg.textContent = "● LIVE Preview";
}

function startPlayer(uid) {
  if (playerUid === uid && hlsInstance) return;
  stopPlayer();
  playerUid = uid;
  els.liveVideo.classList.remove("hidden");
  els.videoMsg.classList.remove("hidden");
  els.videoMsg.textContent = "読み込み中…";
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
        els.videoMsg.textContent = "待機中…";
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
    els.videoMsg.textContent = "HLS非対応のBrowser";
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
    els.recordBtn.classList.remove("rec", "on");
  } else if (recording) {
    els.recordBtn.disabled = rec.state === "stopping";
    els.recordBtn.textContent = "■ 録画停止";
    els.recordBtn.classList.add("rec", "on");
  } else if (state.record_video === false) {
    els.recordBtn.disabled = true;
    els.recordBtn.textContent = "● 録画 (動画保存OFF)";
    els.recordBtn.classList.remove("rec", "on");
  } else {
    els.recordBtn.disabled = !connected;
    els.recordBtn.textContent = "● 録画開始";
    els.recordBtn.classList.remove("rec", "on");
  }

  // 見どころは動画の中の位置を指すので、録画中だけ押せる。録画していない配信に印を
  // 置いても、後から戻る先が無い。
  const canBookmark = !!rec && rec.state === "recording" && !!rec.recording_id;
  els.bookmarkBtn.disabled = !canBookmark;

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
    const apply = () => {
      if (input.checked) activeKinds.add(kind);
      else activeKinds.delete(kind);
      label.classList.toggle("on", input.checked);
      els.feeds.event.list.querySelectorAll(`[data-kind="${kind}"]`).forEach((li) => {
        li.classList.toggle("filtered-out", !input.checked);
      });
    };
    // 絞り込みは画面遷移(フルリロード)で失われるためkindごとに残す。kind単位のkeyに
    // するとEVENT_KINDSに追加されたkindは保存値が無く、markupの既定(表示)で始まる。
    // 復元値をactiveKindsとchip表示へ反映してから初期描画へ入る(feedItemNodeが
    // activeKindsを見るため、順序を逆にすると復元前の絞り込みで描かれる)。
    bindPref(input, `tictok.index.eventKind.${kind}`, apply);
    apply();
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
  prefSet(SEG_PANE_KEY, btn.dataset.pane);
});

applySegPane(prefGet(SEG_PANE_KEY));

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
    // labelを「失敗」のまま置き去りにすると、次に押せる状態なのか読めない。理由はtoastへ出す。
    tag.textContent = "コピー";
    showError(err, "クリップボードへのコピー");
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

// ---- コラボ相手との対戦履歴 ----
// コラボ(非BattleのLinkMic)のpeerは数値user_idしか名乗らない ―― LinkLayerのPlayerが持つのは
// room_idとuidの2 fieldだけで、表示名もavatarも載らないためである。戦績は配信者profileの
// 対戦相手別集計(user_id軸)から解決し、名前は server が相手のroom_infoから解決したもの
// (snapshotのpeer_info)を使う。どちらも無い相手だけIDのまま出す。

const collabState = { peer: null, battleKey: null, sig: null, trend: null, series: null };

function collabPeers(snapshot) {
  const out = [];
  const seen = new Set();
  ((snapshot && snapshot.collab) || []).forEach((w) => {
    (w.peers || []).forEach((id) => {
      const peer = String(id);
      if (seen.has(peer)) return;
      seen.add(peer);
      // peer_infoはserverが解決できた相手だけを持つ(未解決はkeyごと無い)。
      out.push({ user_id: peer, since: w.start, info: (w.peer_info || {})[peer] || null });
    });
  });
  return out;
}

function collabOpponent(peerId, profile) {
  const opps = (profile && profile.battles && profile.battles.opponents) || [];
  return opps.find((o) => String(o.user_id || "") === peerId) || null;
}

// その相手が出た戦だけを新しい順で。代表相手(opponent)ではなく参加者全員(opponent_user_ids)
// に当てる ―― チーム戦・個人マルチで格下だった相手からもその戦へ辿れるようにするため。
function collabHistory(peerId, profile) {
  const hist = (profile && profile.battles && profile.battles.history) || [];
  return hist.filter((h) => (h.opponent_user_ids || []).includes(peerId));
}

// 勝率の母数は決着のついた戦のみ(引分・未確定は除く)。配信者画面の対戦相手別と同じ作法。
// scoreは自陣/敵陣で数える ―― チーム戦のown_scoreはチーム合計、個人マルチのopp_scoreは
// 最強の敵陣であって、どちらも「その相手個人の点」ではない(1戦の曲線側で個人を出す)。
function collabRecord(rows) {
  const wins = rows.filter((r) => r.result === "win").length;
  const losses = rows.filter((r) => r.result === "lose").length;
  const draws = rows.filter((r) => r.result === "draw").length;
  const decided = wins + losses;
  const sum = (key) => rows.reduce((acc, r) => acc + (r[key] || 0), 0);
  return {
    battles: rows.length,
    wins,
    losses,
    draws,
    rate: decided ? (wins / decided) * 100 : null,
    // 平均は整数まで丸めて持つ。pkScoreが略記するのは1000以上だけなので、丸めずに渡すと
    // 千未満の差が「+932.5142857142873」と出る(実dataで出た)。
    avgOwn: rows.length ? Math.round(sum("own_score") / rows.length) : 0,
    avgOpp: rows.length ? Math.round(sum("opp_score") / rows.length) : 0,
    last: rows.length ? rows[0].started_at : null,
  };
}

function collabDestroyCharts() {
  ["trend", "series"].forEach((key) => {
    if (collabState[key]) {
      collabState[key].destroy();
      collabState[key] = null;
    }
  });
}

// 表示する身元。serverが相手のroom_infoから解決した名前(peer.info)を最優先にする ――
// 対戦相手集計の名前は過去の戦の時点のもので、改名/アイコン変更に追随しないためである。
// どちらも無ければ身元を持たないまま返す(名前の位置へIDを置かない)。
function collabPeerIdentity(peer, opponent) {
  const info = peer.info;
  if (info && (info.nickname || info.unique_id)) {
    return {
      nickname: info.nickname || info.unique_id,
      unique_id: info.unique_id || "",
      avatar: info.avatar || (opponent ? opponent.avatar : "") || "",
    };
  }
  if (opponent) {
    return {
      nickname: opponent.nickname || opponent.unique_id || "",
      unique_id: opponent.unique_id || "",
      avatar: opponent.avatar || "",
    };
  }
  return null;
}

function collabPeerName(peerId, identity) {
  if (identity && identity.nickname) return identity.nickname;
  // 名前を解決できていない相手。数値IDを丸ごと出しても読めないので末尾だけ示す。
  return `ID …${peerId.slice(-6)}`;
}

// 記号(●○)は塗りの向きを覚えていないと勝ちと負けを取り違える。文字で名乗らせ、色は
// 履歴表と同じ win=ok / lose=warn に合わせる。
const COLLAB_FORM_LIMIT = 10;

function collabFormMeta(result) {
  if (result === "win") return { cls: "win", text: "勝" };
  if (result === "lose") return { cls: "lose", text: "負" };
  if (result === "draw") return { cls: "draw", text: "分" };
  return { cls: "draw", text: "未" };
}

function collabFormStrip(rows) {
  // 古い→新しいで読めるよう反転する(rowsは新しい順)。
  const strip = document.createElement("span");
  strip.className = "cvs-form";
  rows
    .slice(0, COLLAB_FORM_LIMIT)
    .reverse()
    .forEach((r) => {
      const meta = collabFormMeta(r.result);
      const mark = document.createElement("span");
      mark.className = `cvs-mark ${meta.cls}`;
      mark.textContent = meta.text;
      mark.title =
        `${fmtDateTimeShort(r.started_at)} 自陣 ${pkScore(r.own_score || 0)} / ` +
        `敵陣 ${pkScore(r.opp_score || 0)}`;
      strip.appendChild(mark);
    });
  return strip;
}

function renderCollabVs(monitor) {
  const panel = els.collabVs;
  const peers = collabPeers(monitor && monitor.snapshot);
  const profile = monitor && monitor.profile;
  const segBtn = document.querySelector('#seg-bar button[data-pane="battle"]');
  if (segBtn) segBtn.classList.toggle("collab-live", peers.length > 0);
  // stateは録画開始などでも配られる。顔ぶれもprofileの有無も変わっていないなら描き直さない
  // (描き直すとchartが作り直され、開いていた相手と戦が畳まれる)。名前の解決(peer_info)は
  // 接続の後から届くので、これもsigに入れる ―― 入れないとIDのまま固まる。
  const sig =
    `${peers.map((p) => `${p.user_id}${p.info ? ":n" : ""}`).join(",")}` +
    `|${profile ? "p" : monitor && monitor.profileFailed ? "x" : "-"}`;
  if (!peers.length) {
    collabDestroyCharts();
    collabState.peer = null;
    collabState.battleKey = null;
    collabState.sig = sig;
    panel.classList.add("hidden");
    panel.innerHTML = "";
    return;
  }
  if (sig === collabState.sig && panel.childElementCount) return;
  collabState.sig = sig;
  if (!peers.some((p) => p.user_id === collabState.peer)) {
    collabState.peer = peers.length === 1 ? peers[0].user_id : null;
    collabState.battleKey = null;
  }
  collabRebuild(peers, monitor);
}

function collabRebuild(peers, monitor) {
  const panel = els.collabVs;
  collabDestroyCharts();
  panel.innerHTML = "";

  const head = document.createElement("div");
  head.className = "cvs-head";
  const badge = document.createElement("span");
  badge.className = "cvs-badge";
  badge.textContent = "● コラボ中";
  const count = document.createElement("span");
  count.className = "cvs-mode";
  count.textContent = `${peers.length}名`;
  const since = document.createElement("span");
  since.className = "cvs-time";
  since.textContent = peers[0].since ? `${fmtTime(peers[0].since)}〜` : "";
  head.append(badge, count, since);
  panel.appendChild(head);

  peers.forEach((peer) => {
    panel.appendChild(collabPeerBlock(peer, monitor));
  });

  panel.classList.remove("hidden");
}

function collabPeerBlock(peer, monitor) {
  const profile = monitor && monitor.profile;
  const opponent = collabOpponent(peer.user_id, profile);
  const rows = collabHistory(peer.user_id, profile);
  const rec = collabRecord(rows);
  const block = document.createElement("div");
  block.className = "cvs-peer" + (collabState.peer === peer.user_id ? " open" : "");

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "cvs-toggle";
  const identity = collabPeerIdentity(peer, opponent);
  const name = document.createElement("span");
  name.className = "cvs-name";
  name.appendChild(
    userCell(
      {
        nickname: collabPeerName(peer.user_id, identity),
        unique_id: identity ? identity.unique_id : "",
        avatar: identity ? identity.avatar : "",
      },
      { hideId: true },
    ),
  );
  const score = document.createElement("span");
  score.className = "cvs-rec";
  // profileが未着/取得失敗の間を「対戦履歴なし」と書かない ―― 80戦した相手が未対戦に
  // 見える。待てば出るのか出ないのかも、この一言で分かるようにする。
  score.textContent = profile
    ? rec.battles
      ? `${fmtNum(rec.battles)}戦 ${rec.wins}勝${rec.losses}敗${rec.draws ? `${rec.draws}分` : ""}`
      : "対戦履歴なし"
    : monitor && monitor.profileFailed
      ? "戦績を取得できません"
      : "戦績を読み込み中…";
  const rate = document.createElement("span");
  rate.className = "cvs-rate";
  // 勝率は決着した戦だけが母数。引分/未確定しか無い相手は率を持たない。
  rate.textContent = rec.rate == null ? "" : `${rec.rate.toFixed(1)}%`;
  if (rec.rate != null) rate.classList.add(rec.rate >= 50 ? "up" : "down");
  toggle.append(name, score, rate);
  if (rec.battles) {
    toggle.addEventListener("click", () => {
      collabState.peer = collabState.peer === peer.user_id ? null : peer.user_id;
      collabState.battleKey = null;
      const active = activeTab ? monitors.get(activeTab) : null;
      collabRebuild(collabPeers(active && active.snapshot), active);
    });
  } else {
    toggle.disabled = true;
  }
  block.appendChild(toggle);

  if (rec.battles) {
    const line = document.createElement("div");
    line.className = "cvs-line";
    const formLabel = document.createElement("span");
    formLabel.textContent = `直近${Math.min(rec.battles, COLLAB_FORM_LIMIT)}戦`;
    const stats = document.createElement("span");
    stats.textContent =
      `平均 自陣 ${pkScore(rec.avgOwn)} / 敵陣 ${pkScore(rec.avgOpp)}（${pkSigned(rec.avgOwn - rec.avgOpp)}） · ` +
      `最終 ${fmtDateTimeShort(rec.last)}`;
    line.append(formLabel, collabFormStrip(rows), stats);
    block.appendChild(line);
  }
  if (collabState.peer === peer.user_id && rec.battles) {
    block.appendChild(collabDetail(peer, rows));
  }
  return block;
}

function collabDetail(peer, rows) {
  const wrap = document.createElement("div");
  wrap.className = "cvs-detail";

  const trendHead = document.createElement("p");
  trendHead.className = "cvs-sec";
  trendHead.textContent = "戦ごとのscore推移";
  wrap.appendChild(trendHead);
  const trendBox = document.createElement("div");
  trendBox.className = "cvs-chart";
  const trendCanvas = document.createElement("canvas");
  trendBox.appendChild(trendCanvas);
  wrap.appendChild(trendBox);

  const table = document.createElement("table");
  table.className = "cvs-table";
  const thead = document.createElement("thead");
  thead.innerHTML =
    "<tr><th>日時</th><th>形式</th><th class=\"n\">自陣</th><th class=\"n\">敵陣</th><th class=\"n\">差</th></tr>";
  table.appendChild(thead);
  const tbody = document.createElement("tbody");
  rows.forEach((row) => tbody.appendChild(collabHistoryRow(row)));
  table.appendChild(tbody);
  // 縦scrollは外側のdivが持つ。tableへ overflow を付けると display:block になり、
  // 見出しと値が別々の幅を持って列がずれる。
  const tableWrap = document.createElement("div");
  tableWrap.className = "cvs-tablewrap";
  tableWrap.appendChild(table);
  wrap.appendChild(tableWrap);

  const seriesHead = document.createElement("p");
  seriesHead.className = "cvs-sec";
  seriesHead.textContent = "1戦の中のscore曲線";
  wrap.appendChild(seriesHead);
  const seriesBox = document.createElement("div");
  seriesBox.className = "cvs-chart";
  seriesBox.id = "cvs-series-box";
  // 読み込み中・取得失敗・時系列なしの名乗りに使う。開いた直後は空でよい ―― 行をclickすれば
  // 曲線が出ることは、表と曲線の枠が並んでいれば分かる。
  const seriesMsg = document.createElement("p");
  seriesMsg.className = "cvs-note";
  seriesMsg.id = "cvs-series-msg";
  wrap.append(seriesBox, seriesMsg);

  // chartはcanvasがDOMへ入ってからでないと寸法が0で作られる。
  requestAnimationFrame(() => {
    if (!trendCanvas.isConnected) return;
    collabState.trend = collabTrendChart(trendCanvas, rows.slice().reverse());
  });
  return wrap;
}

function collabHistoryRow(row) {
  const tr = document.createElement("tr");
  const key = `${row.session_id}:${row.battle_id}`;
  tr.className = "cvs-row" + (collabState.battleKey === key ? " picked" : "");
  tr.tabIndex = 0;
  const gap = (row.own_score || 0) - (row.opp_score || 0);
  const meta = battleResultMeta(row.result);
  const cells = [
    { text: fmtDateTimeShort(row.started_at) },
    { text: row.type === "team" ? "チーム" : row.opponent_count > 1 ? "マルチ" : "1v1" },
    { text: pkScore(row.own_score || 0), cls: "n" },
    { text: pkScore(row.opp_score || 0), cls: "n" },
    { text: pkSigned(gap), cls: `n ${meta.cls}` },
  ];
  cells.forEach((c) => {
    const td = document.createElement("td");
    if (c.cls) td.className = c.cls;
    td.textContent = c.text;
    tr.appendChild(td);
  });
  const open = () => collabShowSeries(row, tr);
  tr.addEventListener("click", open);
  tr.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    e.preventDefault();
    open();
  });
  return tr;
}

async function collabShowSeries(row, tr) {
  const key = `${row.session_id}:${row.battle_id}`;
  const msg = document.getElementById("cvs-series-msg");
  const box = document.getElementById("cvs-series-box");
  if (!msg || !box) return;
  document.querySelectorAll(".cvs-row").forEach((el) => el.classList.remove("picked"));
  tr.classList.add("picked");
  collabState.battleKey = key;
  msg.textContent = "読み込み中…";
  let data;
  try {
    data = await apiSend(
      "GET",
      `/api/sessions/${row.session_id}/battle-series/${row.battle_id}`,
    );
  } catch (err) {
    msg.textContent = errorDetailText(err);
    return;
  }
  if (collabState.battleKey !== key) return;
  if (!(data.series || []).length) {
    // 収集が始まる前に終わった戦・旧recordはseriesを持たない。空chartを出すと「0点で
    // 推移した」に見えるので、無いことを名乗る。
    if (collabState.series) {
      collabState.series.destroy();
      collabState.series = null;
    }
    box.innerHTML = "";
    msg.textContent = "この戦にはscoreの時系列が残っていません。";
    return;
  }
  box.innerHTML = "";
  const canvas = document.createElement("canvas");
  box.appendChild(canvas);
  msg.textContent = `${fmtDateTimeShort(row.started_at)} の戦 · 経過秒 × score`;
  requestAnimationFrame(() => {
    if (!canvas.isConnected) return;
    collabState.series = collabSeriesChart(canvas, data, collabState.peer);
  });
}

const COLLAB_OWN_COLOR = cssToken("--series-4");
const COLLAB_OPP_COLOR = cssToken("--series-1");

function collabLineChart(canvas, labels, datasets, xTitle) {
  return new Chart(canvas.getContext("2d"), {
    type: "line",
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          labels: { color: cssToken("--ink-muted"), boxWidth: 10, font: { size: 10 } },
        },
        tooltip: {
          ...nierTooltip(),
          callbacks: {
            title: (items) => `${xTitle} ${items[0].label}`,
            label: (item) => `${item.dataset.label} ${fmtNum(Math.round(item.parsed.y))}`,
          },
        },
      },
      scales: {
        x: { ticks: { ...nierTicks(), maxTicksLimit: 6 }, grid: { display: false } },
        y: {
          beginAtZero: true,
          ticks: { ...nierTicks(), callback: (v) => pkScore(v) },
          grid: { color: cssTokenAlpha("--line", 0.5) },
        },
      },
    },
  });
}

function collabTrendChart(canvas, ordered) {
  return collabLineChart(
    canvas,
    ordered.map((r) => fmtDateTimeShort(r.started_at)),
    [
      {
        label: "自陣",
        data: ordered.map((r) => r.own_score || 0),
        borderColor: COLLAB_OWN_COLOR,
        backgroundColor: COLLAB_OWN_COLOR,
        borderWidth: 2,
        pointRadius: 2,
        tension: 0.15,
      },
      {
        label: "敵陣",
        data: ordered.map((r) => r.opp_score || 0),
        borderColor: COLLAB_OPP_COLOR,
        backgroundColor: COLLAB_OPP_COLOR,
        borderWidth: 2,
        pointRadius: 2,
        tension: 0.15,
      },
    ],
    "",
  );
}

// 1戦の曲線。個人戦(個人マルチ含む)では相手の線をその相手個人(parts)から採る ――
// oppは「最強の敵陣」なので、コラボ相手本人の点ではないことがあるため。
//
// **チーム戦では個人を出さない**: 自陣の線がチーム合計なので、相手だけ1人ぶんを並べると
// 別々の単位を比べることになる(実dataで自陣15.7K対相手4.1Kという絵が出た)。partsに
// 居ない旧recordも同じく敵陣へ落とし、labelでどちらを描いたか名乗る。
function collabSeriesChart(canvas, data, peerId) {
  const start = data.series[0].t;
  const labels = data.series.map((s) => `${Math.round((s.t - start))}s`);
  const peerPart =
    data.type !== "team" &&
    data.series.some((s) => (s.parts || []).some((p) => String(p.id) === peerId));
  const peer = (data.participants || []).find((p) => String(p.user_id) === peerId);
  const oppLabel = peerPart
    ? (peer && peer.nickname) || "相手"
    : "敵陣（最上位）";
  return collabLineChart(
    canvas,
    labels,
    [
      {
        label: "自陣",
        data: data.series.map((s) => s.own || 0),
        borderColor: COLLAB_OWN_COLOR,
        backgroundColor: COLLAB_OWN_COLOR,
        borderWidth: 2,
        pointRadius: 0,
        tension: 0.15,
      },
      {
        label: oppLabel,
        data: data.series.map((s) => {
          if (!peerPart) return s.opp || 0;
          const part = (s.parts || []).find((p) => String(p.id) === peerId);
          return part ? part.score || 0 : 0;
        }),
        borderColor: COLLAB_OPP_COLOR,
        backgroundColor: COLLAB_OPP_COLOR,
        borderWidth: 2,
        pointRadius: 0,
        tension: 0.15,
      },
    ],
    "経過",
  );
}

// ---- ranking + analytics ----
function applySummary(summary) {
  // 前回が取得失敗だった場合の文言を持ち越さない(placeholderの文字はrenderTableRowsで戻らない)。
  setListState(document.getElementById("user-ranking-empty"), "empty");
  setListState(document.getElementById("gift-ranking-empty"), "empty");
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
    if (!timelineRes.ok || !summaryRes.ok) {
      throw new Error(
        `集計を取得できませんでした（HTTP ${timelineRes.ok ? summaryRes.status : timelineRes.status}）。`);
    }
    detailChart.update(await timelineRes.json(), (monitors.get(uid) || {}).battles || []);
    applySummary(await summaryRes.json());
  } catch (err) {
    // 前のtabの数値を残すと、見出しだけ今の配信者になって別人のRankingとtimelineが並ぶ。
    // 取得できなかったものを0件としても描かない(この画面の他の一覧と同じ3状態へ倒す)。
    if (uid === activeTab) {
      detailChart.update({ buckets: [], markers: [] }, []);
      renderTableRows("user-ranking", "user-ranking-empty", [], () => [], []);
      renderTableRows("gift-ranking", "gift-ranking-empty", [], () => [], []);
      setListState(document.getElementById("user-ranking-empty"), "failed", err);
      setListState(document.getElementById("gift-ranking-empty"), "failed", err);
      document.getElementById("rank-gifters").textContent = "";
    }
    console.warn("analytics refresh failed", err);
  } finally {
    analyticsBusy = false;
  }
}

const CMP_METRICS = [
  { key: "gifts", label: "Gift", fmt: fmtNum },
  { key: "diamonds", label: "コイン", fmt: fmtNum },
  { key: "comments", label: "コメント", fmt: fmtNum },
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
    if (uid !== activeTab) return;
    if (!res.ok) throw new Error(`過去配信の比較を取得できませんでした（HTTP ${res.status}）。`);
    const data = await res.json();
    const monitor = monitors.get(uid);
    if (monitor) monitor.history = data;
    renderComparison(monitor);
  } catch (err) {
    // 失敗するとrenderComparisonまで届かず、前のtabの比較表が見出しだけ今の配信者にして
    // 残る。かといって空で描くと「過去の配信履歴がありません」という別の事実になる。
    if (uid === activeTab) {
      els.cmpLabel.textContent = "過去配信との比較";
      els.cmpBody.innerHTML = "";
      setListState(els.cmpEmpty, "failed", err);
    }
    console.warn("history refresh failed", err);
  } finally {
    historyBusy = false;
  }
}

function renderComparison(monitor) {
  const data = monitor && monitor.history;
  els.cmpLabel.textContent = `過去${data ? data.count : 0}配信との比較`;
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
      // コラボの開始/終了・相手の入れ替わりはこのstateで届く(collectorは顔ぶれが変わった
      // ときだけ配る)。変化が無ければrenderCollabVs側が描き直しを見送る。
      renderCollabVs(monitor);
      refreshAnalytics();
      refreshHistory();
    }
  } else if (msg.type === "stats") {
    if (monitor.snapshot) monitor.snapshot.stats = msg.data;
    if (uid === activeTab) applyStats(msg.data);
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
    els.addMessage.textContent = "TikTok IDを入力";
    denyPress(els.addBtn);
    showToast("TikTok IDを入力", "error", { title: "監視開始" });
    return;
  }
  ackPress(els.addBtn);
  els.addBtn.disabled = true;
  els.addMessage.textContent = "開始中…";
  try {
    const recordVideo = els.addRecordVideo ? els.addRecordVideo.checked : true;
    await apiSend("POST", "/api/monitors", { unique_id: uniqueId, record_video: recordVideo });
    setActiveTab(uniqueId);
    els.uniqueId.value = "";
    els.addMessage.textContent = "";
    showToast(`@${uniqueId} の監視を開始しました。`);
  } catch (err) {
    // 停止・再開・録画と同じくtoastで名乗る。#add-messageはtopbarの折返し行にある
    // 小さな文言で、しかも次の成功まで消えないため、失敗がここだけだと気付けない。
    els.addMessage.textContent = err.message;
    denyPress(els.addBtn);
    showError(err, "監視開始");
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
    // status-messageは配信状態のlabelで、WSのstate通知が届くたびapplyStateが上書きする。
    // 失敗をそこへ書くと数秒で消え、表示中は状態labelの意味を潰す。
    showError(err, "監視の停止");
    els.stopBtn.disabled = false;
  }
});

els.restartBtn.addEventListener("click", async () => {
  if (!activeTab) return;
  els.restartBtn.disabled = true;
  try {
    await apiSend("POST", "/api/monitors", { unique_id: activeTab });
  } catch (err) {
    showError(err, "監視の再開");
    els.restartBtn.disabled = false;
  }
});

els.removeBtn.addEventListener("click", async () => {
  if (!activeTab) return;
  const ok = await confirmDialog(
    `@${activeTab} を監視対象から外す`,
    { title: "監視対象から外す", confirmLabel: "外す" },
  );
  if (!ok) return;
  try {
    await apiSend("DELETE", `/api/monitors/${encodeURIComponent(activeTab)}`);
  } catch (err) {
    showError(err, "監視対象から外す");
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
    showError(err, recording ? "録画の停止" : "録画の開始");
    els.recordBtn.disabled = false;
  }
});

// 見どころの登録。押した時刻はServerが打つ(browserの時計ずれを持ち込まない)。
// 登録直後の位置はwall-clock由来の暫定値で、録画のfinalizeでmp4のPTS軸へ載せ直される。
async function markBookmark() {
  if (!activeTab || els.bookmarkBtn.disabled) return;
  // 押した事はServerの応答を待たずに返す。往復を待つと、待っている間は無反応と区別が
  // 付かず、同じ場面へ二重に印を打つことになる。
  ackPress(els.bookmarkBtn);
  els.bookmarkBtn.disabled = true;
  try {
    await apiSend("POST", `/api/monitors/${encodeURIComponent(activeTab)}/bookmark`, { memo: "" });
    flyBookmarkToTimeline();
    flashBookmarkSaved();
  } catch (err) {
    // 効かなかった事は押した物そのもので返す。toastだけでは、押下点と返答が離れている。
    denyPress(els.bookmarkBtn);
    showError(err, "見どころの記録");
  } finally {
    // 状態はWSのsnapshotで戻るが、失敗時に押せないままにしないよう即座に戻す。
    els.bookmarkBtn.disabled = false;
  }
}

// 見どころの印はTIMELINEの右端(=いまの時刻)に立つ。押下点からその位置へ線を飛ばし、
// 「どこに何が増えたか」を人が探し直さずに済むようにする。timelineがまだ描かれていない
// (配信前・chartの高さが0)場合は何も飛ばさない ―― 着地点が無いのに線だけ走らせると、
// 存在しない場所を指すことになる。
function flyBookmarkToTimeline() {
  const chart = document.getElementById("timeline-chart");
  if (!chart) return;
  const box = chart.getBoundingClientRect();
  if (!box.width || !box.height) return;
  flyTo(els.bookmarkBtn, { x: box.right - 4, y: box.top + box.height / 2 });
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
      `@${activeTab} の録画を停止して動画保存をOFFにする`,
      { title: "動画保存をOFFにする", confirmLabel: "OFFにする" },
    );
    if (!ok) return;
  }
  els.recordVideoBtn.disabled = true;
  try {
    await apiSend("POST", `/api/monitors/${encodeURIComponent(activeTab)}/record-video`, { record_video: next });
  } catch (err) {
    showError(err, next ? "動画保存をONにする" : "動画保存をOFFにする");
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
