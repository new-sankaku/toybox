"use strict";

let streamers = [];
let selectedUid = null;
let trendChart = null;
let cohortChart = null;
let currentHeatmap = [];
let aiConfigured = false;
// Battle詳細modalが使うowner(自陣host)。renderProfileのidentityを保持する。
let currentIdentity = null;

const elSearch = document.getElementById("sm-search");
const elHmMetric = document.getElementById("sm-hm-metric");

// ---- 左: 配信者リスト ----
async function loadStreamers() {
  let payload;
  try {
    payload = await apiSend("GET", "/api/streamers");
  } catch (err) {
    // 握りつぶすと一覧が空のままになり、placeholderの「配信者がいません。」が
    // 取得失敗を0件として提示してしまう。
    setListState(document.getElementById("sm-list-empty"), "failed", err);
    return;
  }
  streamers = payload.streamers || [];
  renderList();
  // 初期選択: URLの ?uid= があればそれ、無ければ先頭。
  const wanted = new URLSearchParams(location.search).get("uid");
  const target = wanted && streamers.find((s) => s.unique_id === wanted);
  if (!selectedUid) selectStreamer((target || streamers[0] || {}).unique_id);
}

function renderList() {
  const q = elSearch.value.trim().toLowerCase();
  const list = document.getElementById("sm-list");
  const rows = streamers.filter((s) => {
    if (!q) return true;
    return `${s.unique_id} ${s.nickname}`.toLowerCase().includes(q);
  });
  list.innerHTML = "";
  setListState(document.getElementById("sm-list-empty"), rows.length > 0 ? "ok" : "empty");
  rows.forEach((s) => {
    const item = document.createElement("button");
    item.className = "sm-item" + (s.unique_id === selectedUid ? " sel" : "");
    item.appendChild(userCell(s, { stackId: true }));
    const meta = document.createElement("span");
    meta.className = "sm-item-meta";
    meta.innerHTML =
      `<span class="v">${fmtCompact(s.diamonds)}</span><span class="l">コイン</span>`
      + `<span class="v">${fmtNum(s.sessions)}</span><span class="l">配信</span>`;
    item.appendChild(meta);
    item.addEventListener("click", () => selectStreamer(s.unique_id));
    list.appendChild(item);
  });
}

// ---- 右: 配信者プロファイル ----
// light=true は収集中の live 更新で profile だけ貼り替える時。コホート/ハイライトは
// bucket全走査で重く、毎tick再計算は不要なため、手動選択時(light=false)のみ取得する。
async function selectStreamer(uid, light = false) {
  if (!uid) return;
  selectedUid = uid;
  renderList();
  let profile;
  try {
    profile = await apiSend("GET", `/api/streamers/${encodeURIComponent(uid)}/profile`);
  } catch (err) {
    // 一覧の選択は既にuidへ移っているため、握りつぶすと直前の配信者の数値が
    // 新しい選択のものとして残る。表示を畳んで取得失敗だと明示する。
    if (selectedUid !== uid) return;
    document.getElementById("sm-body").classList.add("hidden");
    const ph = document.getElementById("sm-placeholder");
    ph.classList.remove("hidden");
    ph.textContent = `@${uid} のプロファイルを取得できませんでした。${errorDetailText(err)}`;
    return;
  }
  if (selectedUid !== uid) return;
  renderProfile(profile);
  if (!light) {
    resetAiReview();
    loadCohortAndHighlights(uid);
    // 配信者が変わった時点で前の一覧は無効。表示中なら即引き直し、そうでなければ
    // sectionが画面へ入った時点で読む。
    filesLoadedUid = null;
    fileItems = [];
    renderTableRows("sm-files-rows", null, [], () => [], []);
    chipBar("sm-files-summary", []);
    refreshFileSelection();
    // 画面外なら読みにいかないので「読み込み中」とは言わない。
    setListMessage(document.getElementById("sm-files-empty"), "この位置まで表示すると容量を集計します。");
    maybeLoadFiles();
  }
}

// ---- AI 講評（配信者集約→自然言語） ----
async function loadAiStatus() {
  try {
    const res = await fetch("/api/ai/status");
    if (!res.ok) return;
    const st = await res.json();
    aiConfigured = Boolean(st.configured);
    document.getElementById("sm-ai-note").textContent = st.configured
      ? `model: ${st.model}`
      : st.enabled
        ? "model未設定 (TICTOK_AI_MODEL)"
        : "AI無効 (TICTOK_AI_ENABLED=1)";
    // status取得はloadStreamers/初回selectより後に解決し得る。確定後にbutton状態を
    // 同期する（この時点では結果は未生成なので消去の副作用はない）。
    if (selectedUid) resetAiReview();
  } catch (e) {
    /* status取得失敗時はAI無効扱い */
  }
}

// 講評はserverのai_analysis表へ保存される。配信者を選んだときはGETで保存済みだけを読み
// (LLMは走らない)、生成はbutton(POST)でのみ行う。「再講評」は集約dataが同じでも作り直す。
function renderAiMeta(payload) {
  const meta = document.getElementById("sm-ai-meta");
  if (!payload || !payload.computed_at) {
    meta.textContent = "";
    return;
  }
  meta.textContent = `分析日時: ${fmtDateTime(payload.computed_at)}`
    + ` / model: ${payload.model || "-"} / prompt版: ${payload.prompt_version}`;
}

function resetAiReview() {
  const btn = document.getElementById("sm-ai-btn");
  btn.disabled = !aiConfigured;
  btn.textContent = "講評する";
  btn.classList.remove("hidden");
  document.getElementById("sm-ai-rerun").classList.add("hidden");
  document.getElementById("sm-ai-status").textContent = aiConfigured
    ? ""
    : "ローカルAIが未設定のため利用できません。";
  document.getElementById("sm-ai-meta").textContent = "";
  const res = document.getElementById("sm-ai-result");
  res.classList.add("hidden");
  res.innerHTML = "";
  loadStoredAiReview();
}

async function loadStoredAiReview() {
  if (!selectedUid) return;
  const uid = selectedUid;
  let payload;
  try {
    const res = await fetch(`/api/streamers/${encodeURIComponent(uid)}/ai-review`);
    if (!res.ok) return;
    payload = await res.json();
  } catch (err) {
    return;
  }
  if (selectedUid !== uid || !payload.review) return;
  renderAiReview(payload.review);
  renderAiMeta(payload);
  document.getElementById("sm-ai-btn").classList.add("hidden");
  const rerun = document.getElementById("sm-ai-rerun");
  rerun.classList.remove("hidden");
  rerun.disabled = !aiConfigured;
  if (payload.error) document.getElementById("sm-ai-status").textContent = payload.error;
}

async function runAiReview(refresh) {
  if (!selectedUid || !aiConfigured) return;
  const uid = selectedUid;
  const btn = document.getElementById("sm-ai-btn");
  const rerun = document.getElementById("sm-ai-rerun");
  const status = document.getElementById("sm-ai-status");
  btn.disabled = true;
  rerun.disabled = true;
  status.textContent = "ローカルAIで講評を生成しています（modelにより数十秒かかることがあります）…";
  try {
    const payload = await apiSend(
      "POST",
      `/api/streamers/${encodeURIComponent(uid)}/ai-review${refresh ? "?refresh=1" : ""}`,
    );
    if (selectedUid !== uid) return;
    renderAiReview(payload.review || {});
    renderAiMeta(payload);
    status.textContent = payload.cached
      ? "前回と同じ集約data・同じmodelのため、保存済みの講評を表示しました。"
      : "";
    btn.classList.add("hidden");
    rerun.classList.remove("hidden");
  } catch (err) {
    status.textContent = err.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "講評する";
    rerun.disabled = false;
  }
}

function renderAiReview(r) {
  const res = document.getElementById("sm-ai-result");
  res.innerHTML = "";
  if (r.summary) {
    const m = document.createElement("div");
    m.className = "ai-mood";
    m.textContent = r.summary;
    res.appendChild(m);
  }
  [["強み", r.strengths], ["課題", r.issues], ["改善提案", r.advice]].forEach(([label, items]) => {
    if (!Array.isArray(items) || !items.length) return;
    const h = document.createElement("div");
    h.className = "ai-sub";
    h.textContent = label;
    res.appendChild(h);
    const ul = document.createElement("ul");
    ul.className = "ai-hl";
    items.forEach((x) => {
      const li = document.createElement("li");
      li.textContent = x;
      ul.appendChild(li);
    });
    res.appendChild(ul);
  });
  res.classList.remove("hidden");
}

async function loadCohortAndHighlights(uid) {
  const [cRes, hRes] = await Promise.all([
    fetch(`/api/streamers/${encodeURIComponent(uid)}/cohort`),
    fetch(`/api/streamers/${encodeURIComponent(uid)}/highlights`),
  ]);
  if (selectedUid !== uid) return;
  if (cRes.ok) renderCohort(await cRes.json());
  if (hRes.ok) renderHighlights((await hRes.json()).highlights || []);
}

function renderProfile(p) {
  document.getElementById("sm-placeholder").classList.add("hidden");
  document.getElementById("sm-body").classList.remove("hidden");
  currentIdentity = p.identity;
  renderHead(p.identity, p.count);
  renderKpi(p);
  renderEngagement(p.totals);
  renderTrend(p.sessions);
  renderGrowth(p.sessions);
  currentHeatmap = p.heatmap || [];
  renderHeatmap();
  renderConcentration(p.concentration);
  renderGifters(p.gifters);
  renderBattle(p.battles);
  renderBattleTrend(p.battles.history || []);
  renderBattleGifters(p.battles.gifters || []);
  renderOpponents(p.battles.opponents);
  renderBattleHistory(p.battles.history || []);
}

// エンゲージメント正規化: totals から算出(viewers=各SessionのPeak同接の総和、duration=総配信秒)。
// 規模の異なる配信者を「視聴者あたり」「時間あたり」で公平に比較するための指標。
function renderEngagement(t) {
  const hours = t.duration / 3600;
  const perViewer = (v) => (t.viewers > 0 ? v / t.viewers : 0);
  const perHour = (v) => (hours > 0 ? v / hours : 0);
  chipBar("sm-eng", [
    ["コイン / Peak視聴", fmtNum(Math.round(perViewer(t.diamonds)))],
    ["Comment / Peak視聴", perViewer(t.comments).toFixed(2)],
    ["コイン / 時間", fmtNum(Math.round(perHour(t.diamonds)))],
    ["Comment / 時間", fmtNum(Math.round(perHour(t.comments)))],
  ]);
}

// ---- ファン継続率(日次コホート) ----
function renderCohort(data) {
  const days = data.days || [];
  document.getElementById("sm-cohort-empty").classList.toggle("hidden", days.length > 0);
  document.getElementById("sm-cohort-note").textContent = days.length ? `${days.length}日` : "";
  cohortChart.update(days);
  renderTableRows(
    "sm-cohort-rows",
    null,
    days,
    (d) => [
      d.date,
      fmtNum(d.active),
      fmtNum(d.new),
      fmtNum(d.returning),
      `${d.retention.toFixed(0)}%`,
      fmtNum(d.diamonds),
    ],
    [1, 2, 3, 4, 5],
  );
}

// ---- ハイライト(コイン急増点) ----
function renderHighlights(list) {
  renderTableRows(
    "sm-highlight-rows",
    "sm-highlight-empty",
    list,
    (h, rank) => [
      String(rank),
      fmtDateTime(h.time),
      `#${h.session_id}`,
      fmtNum(h.diamonds),
      `×${h.ratio.toFixed(1)}`,
      fmtNum(h.comments),
      highlightRecCell(h),
    ],
    [0, 3, 4, 5],
  );
}

// 録画がこの急増点をカバーしていれば、その時刻へ飛ぶ再生buttonを出す。
function highlightRecCell(h) {
  if (!h.recording_id) return "—";
  const btn = document.createElement("button");
  btn.className = "btn btn-small";
  btn.textContent = "▶ 再生";
  btn.title = `録画 #${h.recording_id} の ${fmtDuration(h.offset || 0)} 付近から再生`;
  btn.addEventListener("click", () =>
    openVideo(h.recording_id, h.offset || 0, `急増点 ${fmtDateTime(h.time)}（録画 #${h.recording_id}）`),
  );
  return btn;
}

// ---- ハイライト録画の再生(deep-link) ----
// 再生中の録画。errorの理由をserverへ問い合わせる間に別の録画へ移ることがあるため、
// 到達時の対象と突き合わせる。
let playingRecordingId = null;

function openVideo(recordingId, offset, label) {
  const box = document.getElementById("sm-video-box");
  const video = document.getElementById("sm-video");
  document.getElementById("sm-video-title").textContent = label;
  document.getElementById("sm-video-message").textContent = "";
  playingRecordingId = recordingId;
  video.src = `/api/recordings/${recordingId}/play`;
  // メタデータ確定後に急増点へseekして再生。Range対応のため部分読み込みでseekできる。
  const seek = () => {
    try { video.currentTime = offset; } catch (e) { /* seek不可でも先頭から再生 */ }
    video.play().catch(() => {});
    video.removeEventListener("loadedmetadata", seek);
  };
  video.addEventListener("loadedmetadata", seek);
  box.classList.remove("hidden");
  box.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function closeVideo() {
  const box = document.getElementById("sm-video-box");
  const video = document.getElementById("sm-video");
  video.pause();
  // src除去より先にidを落とす。除去自体がerrorを飛ばすので、残したままだと
  // 閉じただけで「再生できませんでした」を出しにいく。
  playingRecordingId = null;
  video.removeAttribute("src");
  video.load();
  box.classList.add("hidden");
}

// ---- 録画容量の整理 ----
// 直近に読み込んだ一覧。checkbox選択の集計と確認文の件数/容量に使う。
let fileItems = [];
// この一覧は録画ごとに実fileをstatし、HLSはdirectoryを走査する(server側
// _recording_file_summary)。配信者を選ぶたびに走らせると選択そのものが重くなるので、
// sectionが実際に画面へ入ったときだけ読む。表示は常時そこにあり、click操作は増えない。
let filesLoadedUid = null;
let filesVisible = false;

function maybeLoadFiles() {
  if (!filesVisible || !selectedUid || filesLoadedUid === selectedUid) return;
  loadFiles();
}

function fileSelection() {
  const rows = document.getElementById("sm-files-rows");
  const picked = (kind) =>
    Array.from(rows.querySelectorAll(`input[data-kind="${kind}"]:checked`))
      .map((el) => Number(el.dataset.id));
  return { mp4_ids: picked("mp4"), ts_ids: picked("ts") };
}

function refreshFileSelection() {
  const sel = fileSelection();
  const byId = new Map(fileItems.map((i) => [i.id, i]));
  const bytes =
    sel.mp4_ids.reduce((a, id) => a + byId.get(id).mp4_bytes + byId.get(id).derived_bytes, 0)
    + sel.ts_ids.reduce((a, id) => a + byId.get(id).ts_bytes, 0);
  const count = sel.mp4_ids.length + sel.ts_ids.length;
  document.getElementById("sm-files-selected").textContent =
    count ? `${count}件 / ${fmtBytes(bytes)} を解放` : "";
  document.getElementById("sm-files-run").disabled = count === 0;
  return { ...sel, bytes, count };
}

function fileCheckbox(item, kind) {
  const exists = kind === "mp4" ? item.mp4_exists : item.ts_exists;
  if (!exists) return "—";
  const box = document.createElement("input");
  box.type = "checkbox";
  box.dataset.kind = kind;
  box.dataset.id = String(item.id);
  // busyの判断はserverが返す。理由(録画中/焼き込み中/転写中)をUI側で組み直すと、
  // server側の条件が増えたときに黙って選べてしまう。
  box.disabled = item.busy;
  if (item.busy) box.title = "録画中または処理中のため削除できません。";
  box.addEventListener("change", refreshFileSelection);
  return box;
}

// 状態＋保護toggle。履歴の録画表と同じ見た目・同じ操作にする。
function fileState(item) {
  const wrap = document.createElement("span");
  wrap.className = "rec-state";
  wrap.append(item.status);
  // 収集中の録画は保持policyの対象外なので保護toggleを出さない(履歴側と同条件)。
  if (item.status === "completed" || item.status === "interrupted") {
    wrap.appendChild(protectBadge(item, loadFiles));
  }
  return wrap;
}

// 動画容量の内訳。派生物(焼き込み・Up出力)は元録画を残したまま消せるので、
// 実在するときだけその場に削除buttonを出す。容量整理の主戦場はこの列。
function fileSizeCell(item) {
  const wrap = document.createElement("span");
  wrap.className = "sm-size-cell";
  wrap.append(fmtBytes(item.mp4_bytes + item.derived_bytes));
  if (item.derived_bytes > 0) {
    const note = document.createElement("span");
    note.className = "result-sub-note";
    note.textContent = `内 派生物 ${fmtBytes(item.derived_bytes)}`;
    wrap.appendChild(note);
    const btn = document.createElement("button");
    btn.className = "btn btn-small";
    btn.textContent = "派生物削除";
    btn.title = "焼き込み(.overlay.mp4)・Up出力(.up.mp4)・renderの中間fileだけを削除します。元の録画は残るため、必要になれば出力し直せます。";
    btn.disabled = item.busy;
    if (item.busy) btn.title = "録画中または処理中のため削除できません。";
    btn.addEventListener("click", () => deleteDerived(item, loadFiles));
    wrap.appendChild(btn);
  }
  return wrap;
}

function renderFileRows() {
  renderTableRows(
    "sm-files-rows",
    "sm-files-empty",
    fileItems,
    (item) => [
      fileCheckbox(item, "mp4"),
      fileCheckbox(item, "ts"),
      `#${item.id}`,
      item.filename || "—",
      fileState(item),
      fmtDateTime(item.started_at),
      fileSizeCell(item),
      fmtBytes(item.ts_bytes),
    ],
    [2, 6, 7],
  );
  // renderTableRowsはplaceholderのhiddenを切り替えるだけで文言を戻さない。読み込み中の
  // 表示が0件の結果に残らないよう、状態はここで明示する。
  setListState(document.getElementById("sm-files-empty"), fileItems.length ? "ok" : "empty");
  document.getElementById("sm-files-all-mp4").checked = false;
  document.getElementById("sm-files-all-ts").checked = false;
  refreshFileSelection();
}

async function loadFiles() {
  if (!selectedUid) return;
  const uid = selectedUid;
  filesLoadedUid = uid;
  // 一括処理tabへは配信者を渡す。渡さないと向こうで一覧から選び直すことになる。
  document.getElementById("sm-files-bulk").href =
    `/videos?streamer=${encodeURIComponent(uid)}#bulk`;
  document.getElementById("sm-files-message").textContent = "";
  fileItems = [];
  renderTableRows("sm-files-rows", null, [], () => [], []);
  refreshFileSelection();
  setListState(document.getElementById("sm-files-empty"), "loading");
  let payload;
  try {
    payload = await apiSend("GET", `/api/streamers/${encodeURIComponent(uid)}/recordings`);
  } catch (err) {
    // 取得済み扱いのままだと再scrollしても引き直さない。失敗は未取得へ戻す。
    if (filesLoadedUid === uid) filesLoadedUid = null;
    setListState(document.getElementById("sm-files-empty"), "failed", err);
    return;
  }
  // 読んでいる間に別の配信者へ切り替わっていたら、その一覧を上書きしない。
  if (payload.unique_id !== selectedUid) return;
  fileItems = payload.recordings || [];
  chipBar("sm-files-summary", [
    ["録画数", fmtNum(fileItems.length)],
    ["動画+派生物", fmtBytes(payload.total_mp4_bytes)],
    ["TS(HLS)", fmtBytes(payload.total_ts_bytes)],
    ["合計", fmtBytes(payload.total_mp4_bytes + payload.total_ts_bytes)],
  ]);
  renderFileRows();
}

function toggleAllFiles(kind, checked) {
  const rows = document.getElementById("sm-files-rows");
  rows.querySelectorAll(`input[data-kind="${kind}"]:not(:disabled)`)
    .forEach((el) => { el.checked = checked; });
  refreshFileSelection();
}

async function runFileDelete() {
  const sel = refreshFileSelection();
  if (!sel.count) return;
  const parts = [];
  if (sel.mp4_ids.length) parts.push(`動画 ${sel.mp4_ids.length}件（焼き込み・Up出力・cacheを含む）`);
  if (sel.ts_ids.length) parts.push(`TS ${sel.ts_ids.length}件`);
  const ok = await confirmDialog(
    `@${selectedUid} の ${parts.join(" と ")} をdiskから削除します（${fmtBytes(sel.bytes)}）。\n`
    + "転写・検索index・bookmark・切り出しlist・解析は残りますが、削除したfileは元に戻せません。",
    { title: "録画fileの削除", confirmLabel: "削除する", danger: true },
  );
  if (!ok) return;
  const run = document.getElementById("sm-files-run");
  run.disabled = true;
  try {
    const res = await apiSend(
      "POST", `/api/streamers/${encodeURIComponent(selectedUid)}/recordings/delete-files`,
      { mp4_ids: sel.mp4_ids, ts_ids: sel.ts_ids },
    );
    showToast(`${fmtBytes(res.freed_bytes)} を解放しました。`);
  } catch (err) {
    document.getElementById("sm-files-message").textContent = err.message;
    run.disabled = false;
    return;
  }
  // 実測を取り直す。解放bytesの予測値で表を書き換えると、消せなかったfileが
  // 消えたことになる。
  await loadFiles();
  loadDiskBar();
}

function renderHead(identity, count) {
  const head = document.getElementById("sm-head");
  head.innerHTML = "";
  const cell = userCell(identity, { stackId: true });
  cell.classList.add("sm-head-user");
  const sub = document.createElement("span");
  sub.className = "sm-head-sub";
  sub.textContent = `${fmtNum(count)} Session`;
  head.append(cell, sub);
}

function renderKpi(p) {
  const t = p.totals;
  const a = p.average;
  const b = p.best;
  chipBar("sm-kpi", [
    ["配信回数", fmtNum(p.count)],
    ["総コイン", fmtNum(t.diamonds)],
    ["平均コイン/配信", fmtNum(Math.round(a.diamonds))],
    ["自己Bestコイン", fmtNum(b.diamonds), "ok"],
    ["総配信時間", fmtDuration(t.duration)],
    ["平均同接", fmtNum(Math.round(a.viewers))],
    ["最高同接", fmtNum(b.viewers)],
    ["総Gift", fmtNum(t.gifts)],
    ["総Comment", fmtNum(t.comments)],
    ["総Like", fmtNum(t.likes)],
    ["総B.Score", fmtNum(t.battle_points)],
  ]);
}

// 成長トレンド: 直近7日/30日のコイン合計と、その前の同期間との比(前週比/前月比)。
// 「伸びているか」を一目で。基準は現在時刻(直近に配信が無ければ減少として正直に出る)。
function renderGrowth(sessions) {
  const now = Date.now() / 1000;
  const day = 86400;
  const sumIn = (from, to) =>
    sessions.filter((s) => s.started_at >= from && s.started_at < to)
      .reduce((acc, s) => acc + (s.diamonds || 0), 0);
  const w0 = sumIn(now - 7 * day, now);
  const w1 = sumIn(now - 14 * day, now - 7 * day);
  const m0 = sumIn(now - 30 * day, now);
  const m1 = sumIn(now - 60 * day, now - 30 * day);
  chipBar("sm-growth", [
    ["直近7日コイン", fmtNum(w0)],
    ["前週比", pctText(w0, w1), pctCls(w0, w1)],
    ["直近30日コイン", fmtNum(m0)],
    ["前月比", pctText(m0, m1), pctCls(m0, m1)],
  ]);
}

function pctText(cur, prev) {
  if (prev <= 0) return cur > 0 ? "新規" : "—";
  const p = ((cur - prev) / prev) * 100;
  return (p >= 0 ? "+" : "") + p.toFixed(0) + "%";
}
function pctCls(cur, prev) {
  if (prev <= 0) return "";
  return cur >= prev ? "ok" : "warn";
}

function renderTrend(sessions) {
  // createSessionTrendChart は s.id / s.started_at / s.ended_at / s.stats.diamonds を読む。
  // profile の session 形(diamonds が top-level)を、その想定 shape へ寄せる。
  const rows = sessions
    .slice()
    .sort((x, y) => x.started_at - y.started_at)
    .slice(-24)
    .map((s) => ({
      id: s.session_id,
      started_at: s.started_at,
      ended_at: s.ended_at,
      stats: { diamonds: s.diamonds },
    }));
  document.getElementById("sm-trend-note").textContent = `直近${rows.length}件`;
  trendChart.update(rows);
}

// ---- 時間帯ヒートマップ(曜日×時刻・bucket時系列ベース) ----
// backendの heatmap は (dow, hour) ごとに、配信中に実際発生したコイン/Comment/配信秒数を
// 集計したもの。開始時刻への一括帰属ではなく、長時間配信は各時間帯へ正しく分散される。
const HM_DAYS = ["月", "火", "水", "木", "金", "土", "日"];
const HM_METRICS = {
  diamonds: { label: "コイン", fmt: (v) => fmtNum(v) },
  active_seconds: { label: "配信時間", fmt: (v) => fmtDuration(v) },
  comments: { label: "Comment", fmt: (v) => fmtNum(v) },
};

// 1時間=4 slot(15分刻み)。列数 = 24*4 = 96。
const HM_SLOTS_PER_HOUR = 4;
const HM_SLOT_MIN = 60 / HM_SLOTS_PER_HOUR;
const HM_COLS = 24 * HM_SLOTS_PER_HOUR;

function renderHeatmap() {
  const metric = elHmMetric.value;
  const wrap = document.getElementById("sm-heatmap");
  wrap.innerHTML = "";
  // cell[Mon=0..Sun=6][slot] にbackend集計を展開する(slot = hour*4 + quarter)。
  const cells = Array.from({ length: 7 }, () =>
    Array.from({ length: HM_COLS }, () => ({ diamonds: 0, comments: 0, active_seconds: 0 })),
  );
  let max = 0;
  currentHeatmap.forEach((e) => {
    const day = (e.dow + 6) % 7; // backend: 0=Sun..6=Sat → Mon=0..Sun=6
    const slot = e.hour * HM_SLOTS_PER_HOUR + (e.quarter || 0);
    const cell = cells[day][slot];
    cell.diamonds += e.diamonds || 0;
    cell.comments += e.comments || 0;
    cell.active_seconds += e.active_seconds || 0;
    if (cell[metric] > max) max = cell[metric];
  });

  // ヘッダ行(時刻ラベル: 各hour cellが4 slot分を span、3時間おきに数値表示)
  wrap.appendChild(hmCell("", "hm-corner"));
  for (let h = 0; h < 24; h++) {
    const head = hmCell(h % 3 === 0 ? String(h) : "", "hm-hhead");
    head.style.gridColumn = `span ${HM_SLOTS_PER_HOUR}`;
    wrap.appendChild(head);
  }
  // 曜日 × 15分slot
  for (let day = 0; day < 7; day++) {
    wrap.appendChild(hmCell(HM_DAYS[day], "hm-dhead"));
    for (let slot = 0; slot < HM_COLS; slot++) {
      const c = cells[day][slot];
      const cell = hmCell("", "hm-cell");
      if (slot % HM_SLOTS_PER_HOUR === 0) cell.classList.add("hm-hr"); // hour境界
      // active_seconds>0 = その時間帯に配信実績あり。選択指標が0でも薄く塗る。
      if (c.active_seconds > 0) {
        const ratio = max > 0 ? c[metric] / max : 0;
        cell.style.background = `rgba(169, 110, 73, ${0.12 + 0.8 * ratio})`;
        const hh = Math.floor(slot / HM_SLOTS_PER_HOUR);
        const mm = (slot % HM_SLOTS_PER_HOUR) * HM_SLOT_MIN;
        cell.title =
          `${HM_DAYS[day]} ${hh}:${String(mm).padStart(2, "0")}〜 · 配信 ${fmtDuration(c.active_seconds)}`
          + ` · コイン ${fmtNum(c.diamonds)} · Comment ${fmtNum(c.comments)}`;
        if (ratio > 0.55) cell.classList.add("hot");
      }
      wrap.appendChild(cell);
    }
  }
  renderHeatmapLegend(metric, max);
}

function renderHeatmapLegend(metric, max) {
  const legend = document.getElementById("sm-hm-legend");
  const m = HM_METRICS[metric];
  if (!max) {
    legend.textContent = "この配信者の時間帯データはまだありません（Session終了後に集計されます）。";
    return;
  }
  legend.innerHTML = "";
  const lab = document.createElement("span");
  lab.className = "hm-leg-l";
  lab.textContent = `${m.label} 少`;
  const grad = document.createElement("span");
  grad.className = "hm-leg-grad";
  const labMax = document.createElement("span");
  labMax.className = "hm-leg-l";
  labMax.textContent = `多 (最大 ${m.fmt(max)})`;
  legend.append(lab, grad, labMax);
}

function hmCell(text, cls) {
  const el = document.createElement("span");
  el.className = cls;
  if (text) el.textContent = text;
  return el;
}

// ---- Gifter / 収益分析 ----
function renderConcentration(c) {
  chipBar("sm-conc", [
    ["Gifter数", fmtNum(c.total_gifters)],
    ["固定ファン(2回+)", fmtNum(c.repeat_gifters), "ok"],
    ["一見(1回)", fmtNum(c.once_gifters)],
    ["Top1 比率", `${c.top1.toFixed(1)}%`],
    ["Top5 比率", `${c.top5.toFixed(1)}%`],
    ["Top10 比率", `${c.top10.toFixed(1)}%`],
  ]);
}

function renderGifters(gifters) {
  renderTableRows(
    "sm-gifters",
    "sm-gifters-empty",
    gifters,
    (g, rank) => [
      String(rank),
      // 名前からその人のFan台帳(全配信者横断の実績)へ直接飛べるようにする。
      userCell(g, {
        stackId: true,
        href: g.identity_key ? `/fans?fan=${encodeURIComponent(g.identity_key)}` : "",
        linkTitle: "この視聴者のFan台帳（全配信者横断の実績）を開きます。",
      }),
      fmtNum(g.diamonds),
      fmtNum(g.gifts),
      `${fmtNum(g.sessions)} 回`,
    ],
    [0, 2, 3, 4],
  );
}

// ---- Battle 分析 ----
// チーム戦は自陣=チーム全体なので、Scoreも貢献者も「監視配信者ぶん」と「チーム計」で値が
// 変わる。片方だけ出すと個人戦と桁が揃わず読み違えるため、両方を 自分 / チーム計 で併記する。
function renderBattle(b) {
  chipBar("sm-battle", [
    ["対戦数", fmtNum(b.count)],
    ["勝率", b.count ? `${b.win_rate.toFixed(1)}%` : "—", b.win_rate >= 50 ? "ok" : ""],
    ["戦績", `${b.wins}勝 ${b.losses}敗 ${b.draws}分`],
    [
      "平均自陣Score 自分/陣営",
      `${fmtNum(Math.round(b.avg_own_host_score))} / ${fmtNum(Math.round(b.avg_own_score))}`,
    ],
    ["平均敵陣Score", fmtNum(Math.round(b.avg_opp_score))],
    [
      `貢献者${b.key_contrib_threshold}+/戦 自室/陣営`,
      `${b.avg_key_contributors.toFixed(1)} / ${b.avg_team_key_contributors.toFixed(1)} 人`,
    ],
    ["Battle中コイン比率", `${b.battle_diamond_share.toFixed(1)}%`],
  ]);
  document.getElementById("sm-battle-history-keycontrib").textContent =
    `貢献者${b.key_contrib_threshold}+ 自室/陣営`;
}

function renderOpponents(opponents) {
  renderTableRows(
    "sm-opponents",
    "sm-opponents-empty",
    opponents || [],
    (o, rank) => {
      const decided = o.wins + o.losses;
      const rate = decided ? `${((o.wins / decided) * 100).toFixed(0)}%` : "—";
      return [
        String(rank),
        userCell(o, { stackId: true }),
        fmtNum(o.battles),
        fmtNum(o.wins),
        fmtNum(o.losses),
        rate,
      ];
    },
    [0, 2, 3, 4, 5],
  );
}

// Battle Gifter: Battle時間窓内に自陣へ投げたファンの集計（どんなギフターで出てきたか）。
function renderBattleGifters(gifters) {
  renderTableRows(
    "sm-battle-gifters",
    "sm-battle-gifters-empty",
    gifters,
    (g, rank) => [
      String(rank),
      userCell(g, { stackId: true }),
      fmtNum(g.diamonds),
      fmtNum(g.gifts),
      `${fmtNum(g.battles)} 回`,
    ],
    [0, 2, 3, 4],
  );
}

const BATTLE_TYPE_LABEL = { team: "チーム戦", personal: "個人戦" };

// 「監視配信者ぶん / 陣営計」の併記。個人戦は自陣host=1人で両者一致するため1つだけ出し、
// 差が出るチーム戦だけ併記する。自host分が不明(古いrecordでhostを特定できない)なら —。
function pairValue(own, team) {
  if (own === null || own === undefined) return `— / ${fmtNum(team)}`;
  if (own === team) return fmtNum(own);
  return `${fmtNum(own)} / ${fmtNum(team)}`;
}
const BATTLE_RESULT = { win: ["WIN", "ok"], lose: ["LOSE", "warn"], draw: ["分", ""] };

// Battle 履歴: 1戦ごとのScore/結果/相手/Batt中コイン（新しい順）。
// 「どんなスコアになったか」を過去のBattle全体で一覧できる。
function renderBattleHistory(history) {
  renderTableRows(
    "sm-battle-history",
    "sm-battle-history-empty",
    history,
    (h) => {
      const [label, cls] = BATTLE_RESULT[h.result] || ["—", ""];
      const res = document.createElement("span");
      res.className = "sm-bres" + (cls ? " " + cls : "");
      res.textContent = label;
      let mode = BATTLE_TYPE_LABEL[h.type] || "個人戦";
      // 個人マルチ(3コラ/4コラ)は参加者数を併記。チーム戦は人数が陣営で分かれるため付けない。
      if (h.type !== "team" && h.opponent_count > 1) mode += ` ${h.opponent_count + 1}コラ`;
      const opp = h.opponent ? userCell(h.opponent, { stackId: true }) : "—";
      return [
        fmtDateTime(h.started_at),
        mode,
        opp,
        pairValue(h.own_host_score, h.own_score),
        fmtNum(h.opp_score),
        res,
        pairValue(h.diamonds, h.team_diamonds),
        `${pairValue(h.key_contributors, h.team_key_contributors)} 人`,
      ];
    },
    [3, 4, 6, 7],
    // 行clickでそのBattleの詳細(参加者/貢献者カード)をmodal表示。dblclickは
    // hoverしないと存在に気付けず、row-clickableなのに単clickが無反応で期待を裏切った。
    (tr, h) => {
      tr.classList.add("row-clickable");
      tr.tabIndex = 0;
      tr.title = "clickでBattle結果を表示";
      tr.addEventListener("click", () => showBattleDetail(h));
      tr.addEventListener("keydown", (e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        e.preventDefault();
        showBattleDetail(h);
      });
    },
  );
}

// Battle履歴の1行 → そのSessionのBattleを取得し、該当Battle(battle_id一致、無ければ
// start_time最近)のカードを詳細modalに描画する。カードは/battleページ・履歴詳細と共有の
// renderBattleCardsを使う。
async function showBattleDetail(h) {
  const title = document.getElementById("sm-battle-title");
  const cards = document.getElementById("sm-battle-cards");
  const empty = document.getElementById("sm-battle-empty");
  title.textContent = `Battle結果 — ${fmtDateTime(h.started_at)}`;
  empty.classList.add("hidden");
  renderBattleCards(cards, [], currentIdentity || {});
  const battleModal = document.getElementById("sm-battle-modal");
  battleModal.classList.remove("hidden");
  focusModalOpen(battleModal, document.getElementById("sm-battle-close"));

  const res = await fetch(`/api/sessions/${h.session_id}`);
  if (!res.ok) {
    empty.textContent = "Battle結果の取得に失敗しました。";
    empty.classList.remove("hidden");
    return;
  }
  const data = await res.json();
  const battles = data.battles || [];
  const owner = data.owner || currentIdentity || { unique_id: h.session_id };
  const battle =
    (h.battle_id && battles.find((b) => String(b.battle_id) === String(h.battle_id)))
    || battles.find((b) => b.start_time === h.started_at)
    || null;
  if (!battle) {
    renderBattleCards(cards, [], owner);
    empty.textContent = "このBattleの詳細が見つかりませんでした。";
    empty.classList.remove("hidden");
    return;
  }
  renderBattleCards(cards, [battle], owner);
}

function closeBattleDetail() {
  // renderBattleCardsで保持中のChart instanceを破棄してから閉じる。
  renderBattleCards(document.getElementById("sm-battle-cards"), [], currentIdentity || {});
  const battleModal = document.getElementById("sm-battle-modal");
  battleModal.classList.add("hidden");
  focusModalClose(battleModal);
}

// スコア推移: 過去Battleを古い→新しい順に、自陣/敵陣Scoreの折れ線 + Batt中コインの棒で表示。
// 「過去のBattleでスコアがどう伸びてきたか」の傾向を1枚で俯瞰する。
let battleTrendChart = null;
function renderBattleTrend(history) {
  const ordered = history.slice().reverse(); // backendは新しい順 → 時系列(古い→新しい)へ
  document.getElementById("sm-battle-trend-empty").classList.toggle("hidden", ordered.length > 0);
  document.getElementById("sm-battle-trend-note").textContent = ordered.length ? `${ordered.length} 戦` : "";
  battleTrendChart.update(ordered);
}

function createBattleTrendChart(canvas) {
  let rows = [];
  const chart = new Chart(canvas, {
    type: "bar",
    data: {
      labels: [],
      datasets: [
        { type: "bar", label: "Batt中コイン", data: [], backgroundColor: "rgba(169, 110, 73, 0.35)", yAxisID: "y2" },
        { type: "line", label: "自陣Score", data: [], borderColor: "#5d6e4e", backgroundColor: "#5d6e4e", borderWidth: 2, pointRadius: 2, tension: 0.25, yAxisID: "y" },
        { type: "line", label: "敵陣Score", data: [], borderColor: "#a4502f", backgroundColor: "#a4502f", borderWidth: 2, pointRadius: 2, tension: 0.25, yAxisID: "y" },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: { ticks: { ...nierTicks(), maxRotation: 0, autoSkip: true, maxTicksLimit: 18 }, grid: { color: NIER_GRID_COLOR } },
        y: { position: "left", beginAtZero: true, title: { display: true, text: "Score", color: NIER_AXIS_COLOR, font: { family: "monospace", size: 10 } }, ticks: nierTicks(), grid: { color: NIER_GRID_COLOR } },
        y2: { position: "right", beginAtZero: true, title: { display: true, text: "コイン", color: NIER_AXIS_COLOR, font: { family: "monospace", size: 10 } }, ticks: nierTicks(), grid: { drawOnChartArea: false } },
      },
      plugins: {
        legend: { labels: { color: "#4d4a3f", font: { family: "monospace", size: 11 }, boxWidth: 14, boxHeight: 8 } },
        tooltip: {
          ...nierTooltip(),
          callbacks: {
            title: (items) => {
              const r = rows[items[0].dataIndex];
              if (!r) return "";
              const res = (BATTLE_RESULT[r.result] || ["—"])[0];
              const opp = r.opponent ? ` vs ${r.opponent.nickname || r.opponent.unique_id}` : "";
              return `${fmtDateTime(r.started_at)} · ${res}${opp}`;
            },
            label: (item) => `${item.dataset.label}: ${fmtNum(item.parsed.y)}`,
          },
        },
      },
    },
  });
  function update(orderedRows) {
    rows = orderedRows || [];
    const ymdSeen = {};
    chart.data.labels = rows.map((r) => {
      const ymd = fmtYmd(r.started_at);
      ymdSeen[ymd] = (ymdSeen[ymd] || 0) + 1;
      return ymdSeen[ymd] > 1 ? `${ymd}:${ymdSeen[ymd]}` : ymd;
    });
    chart.data.datasets[0].data = rows.map((r) => r.diamonds || 0);
    chart.data.datasets[1].data = rows.map((r) => r.own_score || 0);
    chart.data.datasets[2].data = rows.map((r) => r.opp_score || 0);
    chart.update();
  }
  return { update };
}

// 日次コホート: 新規/復帰を積み上げ棒(視聴者数, 左軸) + 前日継続率を折れ線(%, 右軸)。
// 「新規がどれだけ定着し、既存ファンがどれだけ視聴に戻るか」を1枚で見る。
function createCohortChart(canvas) {
  const chart = new Chart(canvas, {
    type: "bar",
    data: {
      labels: [],
      datasets: [
        { type: "bar", label: "新規", data: [], backgroundColor: "rgba(169, 110, 73, 0.7)", yAxisID: "y", stack: "g" },
        { type: "bar", label: "復帰/継続", data: [], backgroundColor: "rgba(93, 110, 78, 0.6)", yAxisID: "y", stack: "g" },
        { type: "line", label: "前日継続率", data: [], borderColor: "#8e4f2f", backgroundColor: "#8e4f2f", borderWidth: 2, pointRadius: 3, tension: 0.25, yAxisID: "y2" },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: { stacked: true, ticks: { ...nierTicks(), maxRotation: 0, autoSkip: true, maxTicksLimit: 18 }, grid: { color: NIER_GRID_COLOR } },
        y: { stacked: true, position: "left", beginAtZero: true, title: { display: true, text: "視聴者数", color: NIER_AXIS_COLOR, font: { family: "monospace", size: 10 } }, ticks: nierTicks(), grid: { color: NIER_GRID_COLOR } },
        y2: { position: "right", beginAtZero: true, max: 100, title: { display: true, text: "継続率%", color: NIER_AXIS_COLOR, font: { family: "monospace", size: 10 } }, ticks: nierTicks(), grid: { drawOnChartArea: false } },
      },
      plugins: {
        legend: { labels: { color: "#4d4a3f", font: { family: "monospace", size: 11 }, boxWidth: 14, boxHeight: 8 } },
        tooltip: { ...nierTooltip() },
      },
    },
  });
  function update(days) {
    chart.data.labels = days.map((d) => d.date);
    chart.data.datasets[0].data = days.map((d) => d.new);
    chart.data.datasets[1].data = days.map((d) => d.returning);
    chart.data.datasets[2].data = days.map((d) => d.retention);
    chart.update();
  }
  return { update };
}

// ---- 未監視の配信者の発見 ----
// 候補は過去の全Battleの対戦相手から毎回導出する(保存しない)。順位は「時間減衰つき対戦数」で、
// 閾値・半減期・件数は設定画面の「配信者の発見」で変えられる。
// 昇格は監視画面と同じ POST /api/monitors を呼ぶ。ここ専用の追加経路は作らない。
let discoverMode = "candidates";

function discoverBusy(busy) {
  document.getElementById("sm-discover-tab-candidates").disabled = busy;
  document.getElementById("sm-discover-tab-dismissed").disabled = busy;
}

function openDiscover(mode) {
  discoverMode = mode;
  const discoverModal = document.getElementById("sm-discover-modal");
  discoverModal.classList.remove("hidden");
  focusModalOpen(discoverModal, document.getElementById("sm-discover-close"));
  loadDiscover();
}

function closeDiscover() {
  const discoverModal = document.getElementById("sm-discover-modal");
  discoverModal.classList.add("hidden");
  focusModalClose(discoverModal);
  document.getElementById("sm-discover-message").textContent = "";
}

function discoverHead(labels) {
  const head = document.getElementById("sm-discover-head");
  head.innerHTML = "";
  labels.forEach((label) => {
    const th = document.createElement("th");
    th.textContent = label;
    head.appendChild(th);
  });
}

function actionButton(label, title, onClick, danger) {
  const btn = document.createElement("button");
  btn.className = "btn btn-small" + (danger ? " btn-danger" : "");
  btn.textContent = label;
  btn.title = title;
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    try {
      await onClick();
    } catch (err) {
      document.getElementById("sm-discover-message").textContent = err.message;
      btn.disabled = false;
    }
  });
  return btn;
}

async function loadDiscover() {
  const isCandidates = discoverMode === "candidates";
  const title = document.getElementById("sm-discover-title");
  const note = document.getElementById("sm-discover-note");
  const empty = document.getElementById("sm-discover-empty");
  document.getElementById("sm-discover-message").textContent = "";
  document.getElementById("sm-discover-tab-candidates").classList.toggle("btn-primary", isCandidates);
  document.getElementById("sm-discover-tab-dismissed").classList.toggle("btn-primary", !isCandidates);
  title.textContent = isCandidates ? "未監視の配信者（発見候補）" : "却下した候補";
  empty.dataset.label = isCandidates ? "発見候補" : "却下した候補";
  setListState(empty, "loading");
  document.getElementById("sm-discover-rows").innerHTML = "";
  discoverBusy(true);
  let payload;
  try {
    payload = await apiSend("GET", isCandidates ? "/api/discovery" : "/api/discovery/dismissed");
  } catch (err) {
    // 取得失敗を0件として描くと「候補はいない」という誤った事実の提示になる。
    discoverHead([]);
    note.textContent = "";
    setListState(empty, "failed", err);
    discoverBusy(false);
    return;
  } finally {
    discoverBusy(false);
  }
  if (isCandidates) renderCandidates(payload);
  else renderDismissed(payload.dismissed || []);
}

function renderCandidates(payload) {
  const rows = payload.candidates || [];
  document.getElementById("sm-discover-note").textContent =
    `対戦${payload.min_contacts}回以上の未監視の配信者 ${payload.eligible} 名のうち上位 ${rows.length} 名`
    + `（対戦相手 ${payload.seen} 名を集計・半減期 ${payload.half_life_days} 日`
    + `・却下 ${payload.dismissed} 名を除外）`;
  discoverHead(["#", "配信者", "対戦数", "直近の対戦", "スコア", "当たった監視配信者", "操作"]);
  setListMessage(
    document.getElementById("sm-discover-empty"),
    "条件に合う候補がありません。設定の「候補に出す最小のBattle対戦数」を下げると増えます。",
  );
  renderTableRows(
    "sm-discover-rows",
    "sm-discover-empty",
    rows,
    (c, rank) => {
      const actions = document.createElement("span");
      actions.className = "modal-head-actions";
      actions.appendChild(
        // 監視追加は非破壊で、いつでも外せる。同じ画面の「却下」に確認が無いのに
        // こちらだけ挟むのは重さが逆で、確認dialogそのものが読み飛ばされる。
        actionButton("監視へ追加", `@${c.unique_id} の監視を開始します。（LIVE中なら接続し、設定に従って録画します。あとで監視対象から外せます）`, async () => {
          await apiSend("POST", "/api/monitors", { unique_id: c.unique_id, record_video: true });
          showToast(`@${c.unique_id} の監視を開始しました。`);
          loadDiscover();
          loadStreamers();
        }),
      );
      actions.appendChild(
        actionButton("却下", "この配信者を候補に出さないようにします（後から戻せます）。", async () => {
          await apiSend("POST", `/api/discovery/${encodeURIComponent(c.unique_id)}/dismiss`);
          loadDiscover();
        }, true),
      );
      return [
        String(rank),
        userCell(c, { stackId: true }),
        `${fmtNum(c.contacts)} 戦`,
        fmtDateTime(c.last_contact),
        c.score.toFixed(2),
        c.via.map((v) => `@${v}`).join(" / "),
        actions,
      ];
    },
    [0, 2, 4],
  );
}

function renderDismissed(rows) {
  document.getElementById("sm-discover-note").textContent =
    `候補に出さないようにした配信者 ${rows.length} 名`;
  discoverHead(["配信者", "却下した日時", "操作"]);
  setListMessage(
    document.getElementById("sm-discover-empty"),
    "却下した候補はありません。",
  );
  renderTableRows(
    "sm-discover-rows",
    "sm-discover-empty",
    rows,
    (d) => [
      `@${d.unique_id}`,
      fmtDateTime(d.dismissed_at),
      actionButton("候補へ戻す", "この配信者を再び候補に出します。", async () => {
        await apiSend("DELETE", `/api/discovery/${encodeURIComponent(d.unique_id)}/dismiss`);
        loadDiscover();
      }),
    ],
    [],
  );
}

// ---- WS: 収集中の更新で選択中の配信者を貼り替える ----
function handleMessage(msg) {
  if (msg.type === "monitors" || msg.type === "state") {
    loadStreamers();
  }
  if ((msg.type === "stats" || msg.type === "battles") && msg.monitor === selectedUid) {
    selectStreamer(selectedUid, true);
  }
}

elSearch.addEventListener("input", renderList);
elHmMetric.addEventListener("change", renderHeatmap);
document.getElementById("sm-ai-btn").addEventListener("click", () => runAiReview(false));
document.getElementById("sm-ai-rerun").addEventListener("click", () => runAiReview(true));
document.getElementById("sm-video-stop").addEventListener("click", closeVideo);
document.getElementById("sm-discover-btn").addEventListener("click", () => openDiscover("candidates"));
document.getElementById("sm-discover-tab-candidates").addEventListener("click", () => openDiscover("candidates"));
document.getElementById("sm-discover-tab-dismissed").addEventListener("click", () => openDiscover("dismissed"));
document.getElementById("sm-discover-close").addEventListener("click", closeDiscover);
document.getElementById("sm-discover-modal").addEventListener("click", (e) => {
  if (e.target.id === "sm-discover-modal") closeDiscover();
});
bindVideoError(
  document.getElementById("sm-video"),
  () => playingRecordingId,
  (text) => { document.getElementById("sm-video-message").textContent = text; },
);
// section手前200pxで先読みし、scrollし切る前に表が埋まっているようにする。
new IntersectionObserver((entries) => {
  filesVisible = entries.some((e) => e.isIntersecting);
  maybeLoadFiles();
}, { rootMargin: "200px" }).observe(document.getElementById("sm-files-section"));
document.getElementById("sm-files-run").addEventListener("click", runFileDelete);
document.getElementById("sm-files-all-mp4").addEventListener("change", (e) => toggleAllFiles("mp4", e.target.checked));
document.getElementById("sm-files-all-ts").addEventListener("change", (e) => toggleAllFiles("ts", e.target.checked));
document.getElementById("sm-battle-close").addEventListener("click", closeBattleDetail);
document.getElementById("sm-battle-modal").addEventListener("click", (e) => {
  if (e.target.id === "sm-battle-modal") closeBattleDetail();
});
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (!document.getElementById("sm-discover-modal").classList.contains("hidden")) closeDiscover();
  else if (!document.getElementById("sm-battle-modal").classList.contains("hidden")) closeBattleDetail();
});
trendChart = createSessionTrendChart(document.getElementById("sm-trend"), { movingAvg: true });
cohortChart = createCohortChart(document.getElementById("sm-cohort-chart"));
battleTrendChart = createBattleTrendChart(document.getElementById("sm-battle-trend"));
loadAiStatus();
loadStreamers();
connectWS(handleMessage);
