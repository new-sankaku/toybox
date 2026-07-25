"use strict";

const monitors = new Map();
const players = new Map(); // uid -> { hls, video }
const audioOn = new Set(); // uids whose audio is enabled (persists across live start/stop)
const grid = document.getElementById("monitor-grid");
const gridEmpty = document.getElementById("grid-empty");
const sortSelect = document.getElementById("sort-select");

const SORT_KEY = "tictok.overviewSort";

function isRecording(snap) {
  const rec = snap && snap.recording;
  return !!rec && (rec.state === "recording" || rec.state === "stopping");
}

function getMonitor(uid) {
  if (!monitors.has(uid)) {
    monitors.set(uid, { snapshot: null, lastGift: null, lastComment: null, battles: [] });
  }
  return monitors.get(uid);
}

// snapshot()にbattlesは含まれないため、接続中monitorは初回表示時に1度だけ取得する。
// 以降は live の battles WS messageで更新される(進行中Battleはarmiesごとに届く)。
async function fetchBattles(uid) {
  try {
    const res = await fetch(`/api/monitors/${encodeURIComponent(uid)}/battles`);
    if (!res.ok || !monitors.has(uid)) return;
    const data = await res.json();
    const monitor = monitors.get(uid);
    monitor.battles = data.battles || [];
    const tile = grid.querySelector(`[data-uid="${CSS.escape(uid)}"]`);
    if (tile) renderBattleBlock(tile, monitor);
  } catch (err) {
    /* live WS messageが追って埋めるため握りつぶす */
  }
}

function syncMonitors(snapshots) {
  const seen = new Set();
  snapshots.forEach((snap) => {
    seen.add(snap.unique_id);
    const isNew = !monitors.has(snap.unique_id);
    const monitor = getMonitor(snap.unique_id);
    monitor.snapshot = snap;
    (snap.recent_events || []).forEach((ev) => rememberEvent(monitor, ev));
    if (isNew && snap.status === "connected") fetchBattles(snap.unique_id);
  });
  [...monitors.keys()].forEach((uid) => {
    if (!seen.has(uid)) {
      monitors.delete(uid);
      destroyPlayer(uid);
    }
  });
  renderGrid();
}

function rememberEvent(monitor, ev) {
  if (ev.kind === "gift") monitor.lastGift = ev;
  else if (ev.kind === "comment") monitor.lastComment = ev;
}

function ownerOf(snap) {
  return (snap && snap.owner) || { unique_id: snap ? snap.unique_id : "" };
}

function kpiCell(label, field) {
  const div = document.createElement("div");
  const l = document.createElement("span");
  l.className = "l";
  l.textContent = label;
  const v = document.createElement("span");
  v.className = "v";
  v.dataset.field = field;
  v.textContent = "-";
  div.append(l, v);
  return div;
}

function buildTile(uid) {
  const tile = document.createElement("div");
  tile.className = "a-tile";
  tile.dataset.uid = uid;

  // Header: avatar + nickname + @uid (link to detail tab) + status
  const th = document.createElement("div");
  th.className = "th";
  const link = document.createElement("a");
  link.href = `/?monitor=${encodeURIComponent(uid)}`;
  link.title = "詳細tabを開く";
  const avatar = document.createElement("span");
  avatar.dataset.field = "avatar";
  const nm = document.createElement("span");
  nm.className = "u-name";
  nm.dataset.field = "nickname";
  const uidSpan = document.createElement("span");
  uidSpan.className = "uid";
  uidSpan.textContent = `@${uid}`;
  const leagueSpan = document.createElement("span");
  leagueSpan.className = "u-league hidden";
  leagueSpan.dataset.field = "league";
  leagueSpan.title = "配信者リーグ";
  link.append(avatar, nm, uidSpan, leagueSpan);
  const status = document.createElement("span");
  status.className = "status";
  const rec = document.createElement("span");
  rec.className = "rec hidden";
  rec.dataset.field = "rec";
  rec.textContent = "● REC";
  const badge = document.createElement("span");
  badge.className = "badge badge-idle";
  badge.dataset.field = "badge";
  badge.textContent = "IDLE";
  status.append(rec, badge);
  th.append(link, status);
  tile.appendChild(th);

  // Video / placeholder
  const vid = document.createElement("div");
  vid.className = "vid";
  vid.dataset.field = "vid";
  const video = document.createElement("video");
  video.className = "hidden";
  video.dataset.field = "video";
  video.muted = true;
  video.autoplay = true;
  video.playsInline = true;
  const ph = document.createElement("div");
  ph.className = "ph";
  ph.dataset.field = "ph";
  ph.textContent = "未接続";
  vid.append(video, ph);
  tile.appendChild(vid);

  // KPI grid
  const kpi = document.createElement("div");
  kpi.className = "a-kpi";
  kpi.append(
    kpiCell("👁", "viewers"),
    kpiCell("コイン", "diamonds"),
    kpiCell("Gift", "gifts"),
    kpiCell("コイン/分", "rate_diamonds"),
    kpiCell("Cmt/分", "rate_comments"),
    kpiCell("接続", "uptime"),
  );
  tile.appendChild(kpi);

  // Controls
  const ctl = document.createElement("div");
  ctl.className = "ctl";
  const recBtn = document.createElement("button");
  recBtn.dataset.field = "record-btn";
  recBtn.textContent = "● 録画開始";
  recBtn.addEventListener("click", () => toggleRecord(uid));
  const audioBtn = document.createElement("button");
  audioBtn.dataset.field = "audio-btn";
  const on = audioOn.has(uid);
  audioBtn.textContent = on ? "🔊" : "🔇";
  audioBtn.classList.toggle("on", on);
  audioBtn.title = "音声のON/OFF";
  audioBtn.setAttribute("aria-label", "音声のON/OFF");
  audioBtn.addEventListener("click", () => toggleAudio(uid));
  const recVideoBtn = document.createElement("button");
  recVideoBtn.dataset.field = "record-video-btn";
  recVideoBtn.textContent = "🎥保存";
  recVideoBtn.addEventListener("click", () => toggleRecordVideo(uid));
  const bookmarkBtn = document.createElement("button");
  bookmarkBtn.dataset.field = "bookmark-btn";
  bookmarkBtn.textContent = "🔖";
  bookmarkBtn.title = "いま見ている場面を見どころとして記録します。録画中のみ押せます。";
  bookmarkBtn.setAttribute("aria-label", "見どころに記録");
  bookmarkBtn.disabled = true;
  bookmarkBtn.addEventListener("click", () => markBookmark(uid));
  ctl.append(recBtn, recVideoBtn, bookmarkBtn, audioBtn);
  tile.appendChild(ctl);

  // Battle block (live; shown only while a battle is in progress)
  const battle = document.createElement("div");
  battle.className = "tile-battle hidden";
  battle.dataset.field = "battle";
  tile.appendChild(battle);

  // Last gift
  const last = document.createElement("div");
  last.className = "last";
  last.dataset.field = "last";
  last.textContent = "待機中…";
  tile.appendChild(last);

  return tile;
}

async function toggleRecord(uid) {
  const monitor = monitors.get(uid);
  const recording = isRecording(monitor && monitor.snapshot);
  const btn = grid.querySelector(`[data-uid="${CSS.escape(uid)}"] [data-field="record-btn"]`);
  if (btn) btn.disabled = true;
  try {
    await apiSend("POST", `/api/monitors/${encodeURIComponent(uid)}/record/${recording ? "stop" : "start"}`);
  } catch (err) {
    showError(err);
    if (btn) btn.disabled = false;
  }
}

// 見どころの登録。押した時刻はServerが打つ。登録位置は録画のfinalizeでmp4のPTS軸へ
// 載せ直されるので、ここでは時刻を送らない。
async function markBookmark(uid) {
  const btn = grid.querySelector(`[data-uid="${CSS.escape(uid)}"] [data-field="bookmark-btn"]`);
  if (btn && btn.disabled) return;
  if (btn) btn.disabled = true;
  try {
    await apiSend("POST", `/api/monitors/${encodeURIComponent(uid)}/bookmark`, { memo: "" });
    if (btn) {
      btn.textContent = "✓";
      clearTimeout(btn._flashTimer);
      btn._flashTimer = setTimeout(() => { btn.textContent = "🔖"; }, 1500);
    }
  } catch (err) {
    showError(err);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function toggleRecordVideo(uid) {
  const monitor = monitors.get(uid);
  const snap = monitor && monitor.snapshot;
  if (!snap) return;
  const next = snap.record_video === false;
  const recording = isRecording(snap);
  if (!next && recording) {
    const ok = await confirmDialog(
      `@${uid} の動画保存をOFFにすると進行中の録画を停止します。よろしいですか？`,
      { title: "動画保存をOFFにする", confirmLabel: "OFFにする" },
    );
    if (!ok) return;
  }
  const btn = grid.querySelector(`[data-uid="${CSS.escape(uid)}"] [data-field="record-video-btn"]`);
  if (btn) btn.disabled = true;
  try {
    await apiSend("POST", `/api/monitors/${encodeURIComponent(uid)}/record-video`, { record_video: next });
  } catch (err) {
    showError(err);
    if (btn) btn.disabled = false;
  }
}

function toggleAudio(uid) {
  const on = !audioOn.has(uid);
  if (on) audioOn.add(uid);
  else audioOn.delete(uid);
  // Apply to the live player when one exists; otherwise the preference is
  // stored and applied as soon as the stream starts (ensurePlayer).
  const player = players.get(uid);
  if (player) {
    player.video.muted = !on;
    if (on) player.video.play().catch(() => {});
  }
  setAudioBtn(uid, !on);
}

function setAudioBtn(uid, muted) {
  const btn = grid.querySelector(`[data-uid="${CSS.escape(uid)}"] [data-field="audio-btn"]`);
  if (!btn) return;
  btn.textContent = muted ? "🔇" : "🔊";
  btn.classList.toggle("on", !muted);
}

function ensurePlayer(uid, tile) {
  if (players.has(uid)) return;
  const video = tile.querySelector('[data-field="video"]');
  const ph = tile.querySelector('[data-field="ph"]');
  video.classList.remove("hidden");
  if (ph) ph.classList.add("hidden");
  video.muted = !audioOn.has(uid);
  const src = `/api/monitors/${encodeURIComponent(uid)}/record/live/index.m3u8`;
  let hls = null;
  if (window.Hls && window.Hls.isSupported()) {
    hls = new window.Hls({ liveSyncDuration: 4, lowLatencyMode: false });
    hls.loadSource(src);
    hls.attachMedia(video);
    hls.on(window.Hls.Events.MANIFEST_PARSED, () => video.play().catch(() => {}));
    hls.on(window.Hls.Events.ERROR, (_e, data) => {
      if (data.fatal && players.has(uid)) setTimeout(() => hls.startLoad(), 2000);
    });
  } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
    video.src = src;
    video.play().catch(() => {});
  }
  players.set(uid, { hls, video });
}

function destroyPlayer(uid) {
  const player = players.get(uid);
  if (!player) return;
  if (player.hls) player.hls.destroy();
  player.video.removeAttribute("src");
  player.video.load();
  players.delete(uid);
  const tile = grid.querySelector(`[data-uid="${CSS.escape(uid)}"]`);
  if (tile) {
    const video = tile.querySelector('[data-field="video"]');
    if (video) video.classList.add("hidden");
    setAudioBtn(uid, !audioOn.has(uid));
  }
}

function sortedUids() {
  const key = sortSelect ? sortSelect.value : "diamonds";
  const statusRank = (snap) => (snap && snap.status === "connected" ? 0 : 1);
  const val = (uid, field) => {
    const snap = monitors.get(uid).snapshot;
    return snap && snap.stats ? Number(snap.stats[field] || 0) : 0;
  };
  const uids = [...monitors.keys()];
  uids.sort((a, b) => {
    if (key === "status") {
      const sa = statusRank(monitors.get(a).snapshot);
      const sb = statusRank(monitors.get(b).snapshot);
      if (sa !== sb) return sa - sb;
      return val(b, "diamonds") - val(a, "diamonds");
    }
    return val(b, key) - val(a, key);
  });
  return uids;
}

function renderGrid() {
  const uids = sortedUids();
  gridEmpty.classList.toggle("hidden", uids.length > 0);
  [...grid.children].forEach((tile) => {
    if (!monitors.has(tile.dataset.uid)) tile.remove();
  });
  uids.forEach((uid) => {
    let tile = grid.querySelector(`[data-uid="${CSS.escape(uid)}"]`);
    if (!tile) {
      tile = buildTile(uid);
      grid.appendChild(tile);
    }
    updateTile(tile, monitors.get(uid));
  });
  // Reorder DOM to match the sort order.
  uids.forEach((uid) => {
    const tile = grid.querySelector(`[data-uid="${CSS.escape(uid)}"]`);
    if (tile) grid.appendChild(tile);
  });
  updateSummary();
}

function updateTile(tile, monitor) {
  const snap = monitor.snapshot;
  if (!snap) return;
  const uid = snap.unique_id;
  const owner = ownerOf(snap);

  // 毎event呼ばれるため、identityが変わった時だけ<img>を作り直す（毎回再生成すると
  // 高トラフィック配信でavatarがちらつき、proxyへの再読込も無駄に走る）。
  const avatarSlot = tile.querySelector('[data-field="avatar"]');
  const avatarKey = `${owner.avatar || ""}|${owner.unique_id || ""}|${owner.nickname || ""}`;
  if (avatarSlot.dataset.avatarKey !== avatarKey) {
    const fresh = avatarNode(owner, "sm");
    fresh.dataset.field = "avatar";
    fresh.dataset.avatarKey = avatarKey;
    avatarSlot.replaceWith(fresh);
  }
  tile.querySelector('[data-field="nickname"]').textContent = owner.nickname || owner.unique_id || uid;
  const leagueSlot = tile.querySelector('[data-field="league"]');
  leagueSlot.textContent = owner.league || "";
  leagueSlot.classList.toggle("hidden", !owner.league);

  const info = STATUS_LABELS[snap.status] || STATUS_LABELS.idle;
  const badge = tile.querySelector('[data-field="badge"]');
  badge.textContent = info.badge;
  badge.className = `badge ${info.cls}`;
  tile.classList.toggle("card-live", snap.status === "connected");

  const recording = isRecording(snap);
  tile.querySelector('[data-field="rec"]').classList.toggle("hidden", !recording);

  updateTileStats(tile, snap.stats || {}, snap.status === "connected");

  updateTileLast(tile, monitor);

  renderBattleBlock(tile, monitor);

  // Video-save toggle (record_video preference)
  const recVideoBtn = tile.querySelector('[data-field="record-video-btn"]');
  const videoOn = snap.record_video !== false;
  recVideoBtn.disabled = false;
  recVideoBtn.textContent = videoOn ? "🎥保存" : "📊dataのみ";
  recVideoBtn.classList.toggle("on", videoOn);
  recVideoBtn.title = videoOn
    ? "動画保存: ON（クリックでデータのみ収集に切替）"
    : "動画保存: OFF（データのみ収集。クリックで録画ONに切替）";

  // Record button
  const recBtn = tile.querySelector('[data-field="record-btn"]');
  const rec = snap.recording;
  if (!snap.ffmpeg_available) {
    recBtn.disabled = true;
    recBtn.textContent = "● ffmpeg無";
    recBtn.classList.remove("on");
  } else if (recording) {
    recBtn.disabled = rec.state === "stopping";
    recBtn.textContent = "■ 録画停止";
    recBtn.classList.add("on");
  } else if (snap.record_video === false) {
    recBtn.disabled = true;
    recBtn.textContent = "● 動画保存OFF";
    recBtn.title = "この監視対象はデータのみ収集（動画保存OFF）です。";
    recBtn.classList.remove("on");
  } else {
    recBtn.disabled = snap.status !== "connected";
    recBtn.textContent = "● 録画開始";
    recBtn.classList.remove("on");
  }

  // 見どころは動画の中の位置を指すので、録画中だけ押せる。
  const bookmarkBtn = tile.querySelector('[data-field="bookmark-btn"]');
  if (bookmarkBtn) {
    const canBookmark = !!rec && rec.state === "recording" && !!rec.recording_id;
    bookmarkBtn.disabled = !canBookmark;
    bookmarkBtn.title = canBookmark
      ? "いま見ている場面を見どころとして記録します。"
      : "録画中のみ記録できます。";
  }

  // Video / placeholder
  const ph = tile.querySelector('[data-field="ph"]');
  // live becomes true once the HLS playlist exists (backend re-notifies then),
  // so the player starts without hitting a 404 on a not-yet-created playlist.
  if (rec && rec.live && rec.state === "recording") {
    ensurePlayer(uid, tile);
  } else {
    destroyPlayer(uid);
    ph.textContent = recording ? "プレビュー準備中…" : snap.status === "connected" ? "録画停止中" : "未接続";
  }
}

// gift/comment受信ごとに更新するのは最終gift行のみ。tile全体やBattleブロックの
// 再構築(高コスト)は state/stats/battles 受信時に限定する。
function updateTileLast(tile, monitor) {
  const lastEl = tile.querySelector('[data-field="last"]');
  if (lastEl) lastEl.textContent = monitor.lastGift ? `GIFT: ${monitor.lastGift.text}` : "待機中…";
}

// 視聴者は「今この瞬間の同時視聴者数」で、切断すると値が来なくなる(statsは切断で
// 0に戻らずSession開始時までの最後の観測値を保持する)。切断中もその値を出すと、
// LIVE中だけを合計する上部のLIVE視聴者と食い違い、「合計0なのにcardには3」に見える。
// 接続中以外は uptime と同じく "-" にして、値が無いことを値の代わりに出さない。
const LIVE_ONLY_STATS = ["viewers"];

function updateTileStats(tile, stats, connected) {
  ["viewers", "diamonds", "gifts", "rate_diamonds", "rate_comments"].forEach((key) => {
    const el = tile.querySelector(`[data-field="${key}"]`);
    if (!el) return;
    const live = connected || !LIVE_ONLY_STATS.includes(key);
    el.textContent = live && key in stats ? fmtNum(stats[key]) : "-";
  });
}

// 高密度tile向けのBattle表示。Sessionで発生した全Battleを新しい順に積み上げて残す
// (終了しても消さない)。各Battleは状態/結果・スコアバー・配信者別の貢献を表示する。
// 共有部品(common.js)を再利用する。
function renderBattleBlock(tile, monitor) {
  const box = tile.querySelector('[data-field="battle"]');
  if (!box) return;
  const battles = monitor.battles || [];
  if (!battles.length) {
    box.classList.add("hidden");
    box.innerHTML = "";
    return;
  }
  box.classList.remove("hidden");
  box.innerHTML = "";
  const owner = (monitor.snapshot && monitor.snapshot.owner) || {};
  // battlesはbackendでstart_time降順。新しいBattleが上に来る。
  battles.forEach((b) => box.appendChild(buildTileBattle(b, owner)));
}

// 1Battleぶんのカード: 状態/結果badge + モード + スコアバー + 配信者別の貢献。
function buildTileBattle(b, owner) {
  const card = document.createElement("div");
  card.className = "tb-card" + (b.ongoing ? " live" : "");

  const head = document.createElement("div");
  head.className = "tb-head";
  const badge = document.createElement("span");
  if (b.ongoing) {
    badge.className = "tb-badge live";
    badge.textContent = "● BATTLE中";
  } else {
    const meta = battleResultMeta(b.result);
    badge.className = "tb-badge res " + meta.cls;
    badge.textContent = meta.text;
  }
  const mode = document.createElement("span");
  mode.className = "tb-mode";
  mode.textContent = battleModeLabel(b);
  head.append(badge, mode);

  const topo = battleTopology(b, owner);
  // スコアバーは形式に応じてN分割(個人=参加者数, チーム=チーム数)。動画overlayと統一。
  card.append(head, buildBattleScoreBar(topo));
  const byHost = groupContribsByHost(b, topo);

  const groups = document.createElement("div");
  groups.className = "tb-groups";
  if (topo.kind === "team") {
    // チーム戦: チーム別 → 配信者別。
    topo.teams.forEach((team) => {
      const teamBox = document.createElement("div");
      teamBox.className = "tb-team " + (team.own ? "own" : "opp");
      const th = document.createElement("div");
      th.className = "tb-team-head";
      th.textContent = `${team.label} ${fmtNum(team.total)}`;
      teamBox.appendChild(th);
      team.members
        .slice()
        .sort((a, c) => (c.score || 0) - (a.score || 0))
        .forEach((host) => teamBox.appendChild(hostGroup(host, byHost, owner)));
      groups.appendChild(teamBox);
    });
  } else {
    // 個人戦(1v1 / Nコラ): 自陣を先頭にhostごと。
    topo.parts
      .slice()
      .sort((a, c) => (a.is_own === c.is_own ? (c.score || 0) - (a.score || 0) : a.is_own ? -1 : 1))
      .forEach((host) => groups.appendChild(hostGroup(host, byHost, owner)));
  }
  card.appendChild(groups);
  return card;
}

// 1配信者ぶんの貢献グループ: ヘッダ(配信者 + score + 貢献者N人) + 貢献者全件。
// 件数制限・内側スクロールは設けず、tileは内容に応じて伸びる。相手陣の実弾内訳は
// 取得できない場合があり、その時はコイン不明として「—」を表示する(0送信ではない)。
function hostGroup(host, byHost, owner) {
  const wrap = document.createElement("div");
  wrap.className = "tb-host " + (host.is_own ? "own" : "opp");
  const contribs = (byHost.get(host.user_id) || [])
    .slice()
    .sort((a, c) => (c.diamonds || 0) - (a.diamonds || 0));
  const coinsSum = contribs.reduce((a, c) => a + (c.diamonds || 0), 0);

  const head = document.createElement("div");
  head.className = "tb-host-head";
  const score = document.createElement("span");
  score.className = "tb-host-score";
  score.textContent = `BS ${fmtBs(host.score)} / 実弾 ${fmtBs(coinsSum)}`;
  const cnt = document.createElement("span");
  cnt.className = "tb-host-cnt";
  cnt.textContent = `貢献者${contribs.length}人`;
  head.append(userCell(participantUser(host, owner), { hideId: true }), score, cnt);
  wrap.appendChild(head);

  contribs.forEach((c) => {
    const row = document.createElement("div");
    row.className = "tb-c";
    const d = document.createElement("span");
    d.className = "tb-d";
    d.textContent = fmtBsCoins(c);
    row.append(userCell(c, { hideId: true }), d);
    wrap.appendChild(row);
  });
  return wrap;
}

function updateSummary() {
  let live = 0;
  let recording = 0;
  let viewers = 0;
  let gifts = 0;
  let diamonds = 0;
  monitors.forEach((monitor) => {
    const snap = monitor.snapshot;
    if (!snap) return;
    const stats = snap.stats || {};
    if (snap.status === "connected") {
      live += 1;
      viewers += Number(stats.viewers || 0);
    }
    if (isRecording(snap)) recording += 1;
    gifts += Number(stats.gifts || 0);
    diamonds += Number(stats.diamonds || 0);
  });
  document.getElementById("sum-monitors").textContent = fmtNum(monitors.size);
  document.getElementById("sum-live").textContent = fmtNum(live);
  document.getElementById("sum-recording").textContent = fmtNum(recording);
  document.getElementById("sum-viewers").textContent = fmtNum(viewers);
  document.getElementById("sum-gifts").textContent = fmtNum(gifts);
  document.getElementById("sum-diamonds").textContent = fmtNum(diamonds);
}

setInterval(() => {
  monitors.forEach((monitor, uid) => {
    const tile = grid.querySelector(`[data-uid="${CSS.escape(uid)}"]`);
    if (!tile) return;
    const el = tile.querySelector('[data-field="uptime"]');
    const snap = monitor.snapshot;
    if (snap && snap.status === "connected" && snap.stats && snap.stats.connected_at) {
      el.textContent = fmtDuration(Date.now() / 1000 - snap.stats.connected_at);
    } else {
      el.textContent = "-";
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
  const tile = grid.querySelector(`[data-uid="${CSS.escape(uid)}"]`);
  if (msg.type === "battles") {
    monitor.battles = (msg.data && msg.data.battles) || [];
    if (tile) renderBattleBlock(tile, monitor);
  } else if (msg.type === "state") {
    monitor.snapshot = msg.data;
    monitor.snapshot.unique_id = uid;
    if (tile) updateTile(tile, monitor);
    updateSummary();
  } else if (msg.type === "stats") {
    if (monitor.snapshot) monitor.snapshot.stats = msg.data;
    if (tile) {
      updateTileStats(tile, msg.data,
        !!monitor.snapshot && monitor.snapshot.status === "connected");
    }
    updateSummary();
  } else if (msg.type === "event") {
    rememberEvent(monitor, msg.data);
    if (tile) updateTileLast(tile, monitor);
  }
}

if (sortSelect) {
  const stored = window.localStorage.getItem(SORT_KEY);
  if (stored) sortSelect.value = stored;
  sortSelect.addEventListener("change", () => {
    window.localStorage.setItem(SORT_KEY, sortSelect.value);
    renderGrid();
  });
}

document.getElementById("video-all-on").addEventListener("click", () => {
  monitors.forEach((monitor, uid) => {
    if (monitor.snapshot && monitor.snapshot.recording && monitor.snapshot.recording.live && monitor.snapshot.recording.state === "recording") {
      const tile = grid.querySelector(`[data-uid="${CSS.escape(uid)}"]`);
      if (tile) ensurePlayer(uid, tile);
    }
  });
});

document.getElementById("audio-all-off").addEventListener("click", () => {
  audioOn.clear();
  players.forEach((player) => {
    player.video.muted = true;
  });
  grid.querySelectorAll("[data-uid]").forEach((tile) => setAudioBtn(tile.dataset.uid, true));
});

connectWS(handleMessage);
