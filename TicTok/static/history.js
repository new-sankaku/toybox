"use strict";

let detailChart = null;
let currentSessionId = null;
// 開いている詳細modalの配信者ID。収集中Sessionのbattle/stats更新をliveで受け、
// Battleカード(スコア推移chart含む)を貼り替えるために保持する。
let currentSessionUid = null;
let allSessions = [];
let activeIds = new Set();
// 出力中Sessionのprogress要素。WS更新でtableが再描画されても、行のbuttonを
// 作り直す代わりにこの要素を再装着し、spinner/進捗を保持する。
const activeOutputs = new Map();
// 焼き込み(server側ffmpeg)中はHTTP応答待ちでbyteが来ないため、進捗%はWSの
// output_progressで受け取る。recording.id → 進捗を反映する関数。
const encodeProgress = new Map();
// Up出力(AI高画質化)中のSession行のprogress要素と、WS upscale_progressの反映関数。
const activeUpOutputs = new Map();
const upscaleProgress = new Map();

const flt = {
  search: document.getElementById("flt-search"),
  period: document.getElementById("flt-period"),
  status: document.getElementById("flt-status"),
  sort: document.getElementById("flt-sort"),
};

// ---- KPI bar ----
function renderKpi(totals, streamerCount, recordingCount) {
  const bar = document.getElementById("kpi-bar");
  const chips = [
    ["総Session", fmtNum(totals.sessions)],
    ["総Gift", fmtNum(totals.gifts)],
    ["総コイン", fmtNum(totals.diamonds)],
    ["総Comment", fmtNum(totals.comments)],
    ["配信者数", fmtNum(streamerCount)],
    ["録画数", fmtNum(recordingCount)],
  ];
  bar.innerHTML = "";
  chips.forEach(([label, value]) => {
    const chip = document.createElement("div");
    chip.className = "a-chip";
    const l = document.createElement("span");
    l.className = "l";
    l.textContent = label;
    const v = document.createElement("span");
    v.className = "v";
    v.textContent = value;
    chip.append(l, v);
    bar.appendChild(chip);
  });
}

async function loadKpi() {
  const [dashRes, recRes] = await Promise.all([
    fetch("/api/dashboard"),
    fetch("/api/recordings"),
  ]);
  if (!dashRes.ok) return;
  const dash = await dashRes.json();
  const recordingCount = recRes.ok ? (await recRes.json()).recordings.length : 0;
  renderKpi(dash.totals || {}, (dash.streamers || []).length, recordingCount);
}

// ---- session table ----
async function loadSessions() {
  const res = await fetch("/api/sessions");
  if (!res.ok) return;
  const data = await res.json();
  allSessions = data.sessions || [];
  activeIds = new Set(data.active_session_ids || []);
  renderTable();
}

function periodStart(kind) {
  const now = new Date();
  if (kind === "today") {
    return new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() / 1000;
  }
  if (kind === "week") {
    const d = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
    return d.getTime() / 1000;
  }
  if (kind === "month") {
    return new Date(now.getFullYear(), now.getMonth(), 1).getTime() / 1000;
  }
  return 0;
}

function filteredSessions() {
  const q = flt.search.value.trim().toLowerCase();
  const after = periodStart(flt.period.value);
  const statusFilter = flt.status.value;
  let rows = allSessions.filter((s) => {
    if (after && s.started_at < after) return false;
    const isActive = activeIds.has(s.id);
    if (statusFilter === "live" && !isActive) return false;
    if (statusFilter === "ended" && isActive) return false;
    if (q) {
      const hay = `${s.unique_id} ${s.note || ""}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
  const sortKey = flt.sort.value;
  const stat = (s, k) => (s.stats && s.stats[k]) || 0;
  const sorters = {
    started_desc: (a, b) => b.started_at - a.started_at,
    started_asc: (a, b) => a.started_at - b.started_at,
    gifts: (a, b) => stat(b, "gifts") - stat(a, "gifts"),
    diamonds: (a, b) => stat(b, "diamonds") - stat(a, "diamonds"),
    unique_id: (a, b) => a.unique_id.localeCompare(b.unique_id) || b.started_at - a.started_at,
  };
  rows.sort(sorters[sortKey] || sorters.started_desc);
  return rows;
}

function statusCell(session) {
  const isActive = activeIds.has(session.id);
  const span = document.createElement("span");
  if (isActive) {
    span.className = "st live";
    span.textContent = "収集中";
  } else {
    const info = STATUS_LABELS[session.status] || STATUS_LABELS.ended;
    span.className = "st ended";
    span.textContent = info.badge;
  }
  return span;
}

function actionsCell(session) {
  const wrap = document.createElement("span");
  wrap.className = "row-actions";
  const isActive = activeIds.has(session.id);
  const outputting = activeOutputs.has(session.id);
  const upOutputting = activeUpOutputs.has(session.id);

  const showBtn = document.createElement("button");
  showBtn.className = "btn btn-small";
  showBtn.textContent = "詳細";
  showBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    showDetail(session.id);
  });

  // 出力中の行は再描画されても、進行中のprogress要素をそのまま再装着する。
  let outNode;
  if (outputting) {
    outNode = activeOutputs.get(session.id);
  } else {
    const out = document.createElement("button");
    out.className = "btn btn-small";
    // 出力済みでも再出力したいのでButtonは活性のまま、ラベルだけ「(済)」にする。
    out.textContent = session.output_done ? "出力(済)" : "出力";
    const hasVideo = (session.recording_count || 0) > 0;
    out.disabled = isActive || !hasVideo;
    out.title = isActive
      ? "収集中のSessionは出力できません"
      : !hasVideo
        ? "このSessionには出力できる録画がありません（動画保存OFF等で動画が未保存）。"
        : "このSessionの録画にComment/Gift演出を焼き込み、recordings folderへ出力します（再Encodeのため時間がかかります）。完了時にブラウザ通知を出します。";
    out.addEventListener("click", (e) => {
      e.stopPropagation();
      outputSession(session, out);
    });
    outNode = out;
  }

  const del = document.createElement("button");
  del.className = "btn btn-small btn-danger";
  del.textContent = "削除";
  del.disabled = isActive || outputting || upOutputting;
  del.title = isActive
    ? "収集中のSessionは削除できません"
    : outputting || upOutputting
      ? "出力中のSessionは削除できません"
      : "";
  del.addEventListener("click", async (e) => {
    e.stopPropagation();
    if (!window.confirm(`Session #${session.id} (@${session.unique_id}) を削除しますか？この操作は取り消せません。`)) return;
    try {
      await apiSend("DELETE", `/api/sessions/${session.id}`);
      if (currentSessionId === session.id) closeDetail();
      await Promise.all([loadSessions(), loadKpi()]);
    } catch (err) {
      window.alert(err.message);
    }
  });

  wrap.append(showBtn, outNode);

  // Up出力(AI高画質化)。ローカルAIのUpscale設定が有効な場合のみ表示する。
  if (upscaleConfigured) {
    let upNode;
    if (upOutputting) {
      upNode = activeUpOutputs.get(session.id);
    } else {
      const up = document.createElement("button");
      up.className = "btn btn-small";
      // 出力済みでも再出力可能（活性のまま）。ラベルだけ「(済)」にする。
      up.textContent = session.up_output_done ? "Up出力(済)" : "Up出力";
      const hasVideo = (session.recording_count || 0) > 0;
      up.disabled = isActive || !hasVideo;
      up.title = isActive
        ? "収集中のSessionは出力できません"
        : !hasVideo
          ? "このSessionには出力できる録画がありません（動画保存OFF等で動画が未保存）。"
          : "このSessionの録画をローカルAI(超解像model)で高画質化し、.up.mp4としてrecordings folderへ出力します。焼き込みが有効な場合は焼き込み後の動画を高画質化します。GPUでも録画時間の数倍かかります。完了時にブラウザ通知を出します。";
      up.addEventListener("click", (e) => {
        e.stopPropagation();
        upOutputSession(session, up);
      });
      upNode = up;
    }
    wrap.appendChild(upNode);
  }

  // 文字起こし(STT有効時のみ)。録画があるSessionで実行できる。複数録画がある場合は
  // 結果がRecording単位のため詳細へ誘導し、単一録画はその場でModalに表示する。
  if (sttConfigured) {
    const tr = document.createElement("button");
    tr.className = "btn btn-small";
    // 文字起こし済みでも再実行可能（活性のまま）。ラベルだけ「(済)」にする。
    tr.textContent = session.transcript_done ? "文字起こし(済)" : "文字起こし";
    const hasVideo = (session.recording_count || 0) > 0;
    tr.disabled = isActive || !hasVideo;
    tr.title = isActive
      ? "収集中のSessionは文字起こしできません"
      : !hasVideo
        ? "このSessionには文字起こしできる録画がありません。"
        : "このSessionの録画音声をローカルAIで文字起こしします（初回はmodel読み込みで時間がかかります）。結果はキャッシュされます。";
    tr.addEventListener("click", (e) => {
      e.stopPropagation();
      transcribeSession(session, tr);
    });
    wrap.appendChild(tr);
  }

  wrap.appendChild(del);
  return wrap;
}

// 履歴一覧の操作からの文字起こし。SessionのRecordingを取得し、単一なら即表示、
// 複数ならRecording単位で選べるよう詳細を開く（transcriptはRecording単位のため）。
async function transcribeSession(session, btn) {
  const orig = btn.textContent;
  btn.disabled = true;
  try {
    const res = await fetch(`/api/sessions/${session.id}`);
    if (!res.ok) throw new Error("Session情報の取得に失敗しました。");
    const data = await res.json();
    const recs = (data.recordings || []).filter(
      (r) => r.status === "completed" || r.status === "interrupted");
    if (!recs.length) {
      window.alert("文字起こしできる録画がありません。");
      return;
    }
    if (recs.length === 1) {
      await transcribeOrShow(recs[0], btn);
      return;
    }
    window.alert("このSessionには複数の録画があります。詳細から録画ごとに文字起こししてください。");
    showDetail(session.id);
  } catch (err) {
    window.alert(err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = orig;
    // done badge(文字起こし済)をbackendの最新状態で反映する。
    loadSessions();
  }
}

function renderTable() {
  const tbody = document.getElementById("session-rows");
  const rows = filteredSessions();
  tbody.innerHTML = "";
  document.getElementById("session-empty").classList.toggle("hidden", rows.length > 0);
  rows.forEach((s) => {
    const stats = s.stats || {};
    const tr = document.createElement("tr");
    const duration = s.ended_at ? fmtDuration(s.ended_at - s.started_at) : "収集中";

    const cells = [];
    cells.push(textTd(`#${s.id}`));
    const nameTd = document.createElement("td");
    nameTd.appendChild(
      userCell(
        {
          unique_id: s.unique_id,
          nickname: s.owner_nickname || s.unique_id,
          avatar: s.owner_avatar || "",
          league: s.league || "",
        },
        { leagueFirst: true },
      ),
    );
    cells.push(nameTd);
    cells.push(textTd(fmtDateTime(s.started_at)));
    cells.push(textTd(duration));
    const stTd = document.createElement("td");
    stTd.appendChild(statusCell(s));
    cells.push(stTd);
    cells.push(numTd(stats.diamonds));
    cells.push(numTd(stats.comments));
    cells.push(numTd(stats.likes_total));
    cells.push(numTd(stats.follows));
    cells.push(numTd(stats.shares));
    cells.push(numTd(stats.joins));
    cells.push(numTd(stats.battles));
    cells.push(numTd(stats.battle_points));
    cells.push(numTd(stats.viewers_peak));
    const actTd = document.createElement("td");
    actTd.appendChild(actionsCell(s));
    cells.push(actTd);

    cells.forEach((td) => tr.appendChild(td));
    tbody.appendChild(tr);
  });
}

function textTd(text) {
  const td = document.createElement("td");
  td.textContent = text;
  return td;
}

function numTd(value) {
  const td = document.createElement("td");
  td.className = "n";
  td.textContent = fmtNum(value);
  return td;
}

// ---- detail modal ----
async function showDetail(sessionId) {
  const res = await fetch(`/api/sessions/${sessionId}`);
  if (!res.ok) return;
  const data = await res.json();
  const session = data.session;
  currentSessionId = sessionId;
  currentSessionUid = session.unique_id;

  document.getElementById("detail-title").textContent =
    `Session #${session.id} — @${session.unique_id} (${fmtDateTime(session.started_at)})`;
  document.getElementById("detail-csv").href = `/api/sessions/${session.id}/export.csv`;
  document.getElementById("detail-json").href = `/api/sessions/${session.id}/export.json`;
  const stats = session.stats || {};
  const duration = session.ended_at ? fmtDuration(session.ended_at - session.started_at) : "収集中";
  const detailChips = [
    ["収集時間", duration],
    ["Gift合計", fmtNum(stats.gifts)],
    ["コイン合計", fmtNum(stats.diamonds)],
    ["Comment合計", fmtNum(stats.comments)],
    ["Like合計", fmtNum(stats.likes_total)],
    ["最大同接", fmtNum(stats.viewers_peak)],
    ["Battle回数", fmtNum(stats.battles)],
  ];
  if (session.league) detailChips.unshift(["リーグ", session.league]);
  renderChips("detail-totals", detailChips);
  document.getElementById("note-input").value = session.note || "";
  document.getElementById("note-status").textContent = "";
  resetAiResult();

  renderBattles(data.battles || [], data.owner || { unique_id: session.unique_id, nickname: session.unique_id });
  detailChart.update(data.timeline, data.battles || []);

  const summary = data.summary || {};
  renderTableRows(
    "user-ranking",
    "user-ranking-empty",
    summary.users || [],
    (user, rank) => [String(rank), userCell(user, { stackId: true }), fmtNum(user.gifts), fmtNum(user.diamonds), giftItemsNode(user.items)],
    [0, 2, 3],
  );
  renderTableRows(
    "gift-ranking",
    "gift-ranking-empty",
    summary.gifts || [],
    (gift, rank) => [String(rank), gift.name, fmtNum(gift.count), fmtNum(gift.diamonds)],
    [0, 2, 3],
  );

  renderRecordings(data.recordings || []);
  document.getElementById("detail-modal").classList.remove("hidden");
}

function renderBattles(battles, owner) {
  const summary = document.getElementById("battle-summary");
  const cards = document.getElementById("battle-cards");
  const empty = document.getElementById("battle-empty");
  if (!battles.length) {
    summary.textContent = "";
    // 空でもrenderBattleCards経由でclearし、保持中のChart instanceを破棄する。
    renderBattleCards(cards, [], owner);
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");
  summary.textContent = battleSummaryText(battles);
  renderBattleCards(cards, battles, owner);
}

function closeDetail() {
  document.getElementById("detail-modal").classList.add("hidden");
  currentSessionId = null;
  currentSessionUid = null;
}

// 収集中Sessionの詳細を開いている間、Battleカードだけをliveで貼り替える。
// timeline/ranking等はopen時のsnapshotのままにして再fetchの負荷を抑える。
async function refreshOpenBattles() {
  if (currentSessionId === null) return;
  const sessionId = currentSessionId;
  try {
    const res = await fetch(`/api/sessions/${sessionId}/battles`);
    if (!res.ok || currentSessionId !== sessionId) return;
    const data = await res.json();
    renderBattles(data.battles || [], data.owner || { unique_id: currentSessionUid, nickname: currentSessionUid });
  } catch (err) {
    /* 次の更新で再試行されるため握りつぶす */
  }
}

function renderChips(containerId, chips) {
  const container = document.getElementById(containerId);
  container.innerHTML = "";
  chips.forEach(([label, value]) => {
    const chip = document.createElement("div");
    chip.className = "result-chip";
    const l = document.createElement("span");
    l.className = "label";
    l.textContent = label;
    const v = document.createElement("span");
    v.className = "value";
    v.textContent = value;
    chip.append(l, v);
    container.appendChild(chip);
  });
}

const RECORDING_STATUS = {
  recording: "録画中",
  completed: "完了",
  failed: "失敗",
  interrupted: "中断",
  stopping: "停止中",
};

// 出力(録画のComment/Gift焼き込み)は設定により再Encodeが走り時間がかかるため、
// WSで進捗を取得しspinnerと%で可視化する。完了時はブラウザ通知を出す。

// 出力完了をブラウザ通知する。clickのuser gesture内で権限を要求しておく。
async function ensureNotifyPermission() {
  if (!("Notification" in window)) return false;
  if (Notification.permission === "granted") return true;
  if (Notification.permission === "denied") return false;
  try {
    return (await Notification.requestPermission()) === "granted";
  } catch (e) {
    return false;
  }
}

function notifyOutputDone(name) {
  try {
    if ("Notification" in window && Notification.permission === "granted") {
      new Notification("出力が完了しました", { body: name });
    }
  } catch (e) {
    /* 通知不可でも出力自体は完了しているため無視 */
  }
}

function makeOutputProgress() {
  const prog = document.createElement("span");
  prog.className = "dl-progress";
  prog.innerHTML = '<span class="spinner dl-spinner"><span class="spinner-core"></span></span>'
    + '<span class="dl-bar"><span class="dl-bar-fill"></span></span>'
    + '<span class="dl-pct">準備中…</span>';
  return prog;
}

// 1録画の焼き込みをserverに依頼し、recordings folderへ出力する。出力先のfile名を
// 返す。焼き込み(再Encode)段階の%はserverからWSで届くoutput_progressをprogに反映する。
// labelは複数録画時の「(1/2) 」等の接頭辞。
async function outputRecording(rec, prog, label) {
  encodeProgress.set(rec.id, (pct) =>
    renderOutputProgress(prog, `${label}焼き込み `, pct, 100));
  try {
    const res = await fetch(`/api/recordings/${rec.id}/output`, { method: "POST" });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(typeof payload.detail === "string" ? payload.detail : "出力に失敗しました。");
    }
    const name = payload.filename || rec.filename;
    // 同期方式の比較出力(サーバ時刻版)が同時に作られた場合は両file名を知らせる。
    return payload.filename_b ? `${name}（比較: ${payload.filename_b}）` : name;
  } finally {
    encodeProgress.delete(rec.id);
  }
}

function renderOutputProgress(prog, label, received, total) {
  const fill = prog.querySelector(".dl-bar-fill");
  const pct = prog.querySelector(".dl-pct");
  if (total > 0) {
    const p = Math.min(100, Math.round((received / total) * 100));
    fill.style.inlineSize = `${p}%`;
    pct.textContent = `${label}${p}%`;
  } else {
    pct.textContent = `${label}${(received / 1048576).toFixed(1)} MB`;
  }
}

function finishOutputProgress(prog) {
  prog.querySelector(".dl-spinner").remove();
  prog.querySelector(".dl-bar-fill").style.inlineSize = "100%";
  prog.querySelector(".dl-pct").textContent = "完了 ✓";
  prog.classList.add("done");
}

// 録画単体の出力(録画一覧の操作)。
async function downloadRecording(rec, btn) {
  await ensureNotifyPermission();
  const prog = makeOutputProgress();
  btn.replaceWith(prog);
  try {
    const name = await outputRecording(rec, prog, "");
    finishOutputProgress(prog);
    notifyOutputDone(name);
    // done badge(出力済)を反映するため詳細を再描画する。
    if (currentSessionId !== null) showDetail(currentSessionId);
  } catch (err) {
    prog.replaceWith(btn);
    window.alert(err.message);
  }
}

// Session単位の出力(履歴一覧の操作)。そのSessionの完了録画をすべて出力する。
async function outputSession(session, btn) {
  await ensureNotifyPermission();
  const prog = makeOutputProgress();
  btn.replaceWith(prog);
  // 再描画でprogが行から切り離されても進捗を保持できるよう登録する。
  activeOutputs.set(session.id, prog);
  try {
    const res = await fetch(`/api/sessions/${session.id}`);
    if (!res.ok) throw new Error("Session情報の取得に失敗しました。");
    const data = await res.json();
    const recs = (data.recordings || []).filter(
      (r) => r.status === "completed" || r.status === "interrupted");
    if (!recs.length) throw new Error("出力できる録画がありません。");
    let lastName = "";
    for (let i = 0; i < recs.length; i++) {
      const label = recs.length > 1 ? `(${i + 1}/${recs.length}) ` : "";
      lastName = await outputRecording(recs[i], prog, label);
    }
    finishOutputProgress(prog);
    notifyOutputDone(recs.length > 1 ? `${recs.length}件の録画を出力しました` : lastName);
  } catch (err) {
    prog.replaceWith(btn);
    window.alert(err.message);
  } finally {
    activeOutputs.delete(session.id);
    // done badge(出力済)をbackendの最新状態で反映する。
    loadSessions();
  }
}

// 1録画のAI高画質化(Up出力)をserverに依頼する。焼き込みが有効な場合はserver側で
// 先に焼き込みが走り(output_progress)、続いて高画質化(upscale_progress)が届く。
async function upOutputRecording(rec, prog, label) {
  encodeProgress.set(rec.id, (pct) =>
    renderOutputProgress(prog, `${label}焼き込み `, pct, 100));
  upscaleProgress.set(rec.id, (pct) =>
    renderOutputProgress(prog, `${label}高画質化 `, pct, 100));
  try {
    const res = await fetch(`/api/recordings/${rec.id}/upscale-output`, { method: "POST" });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(typeof payload.detail === "string" ? payload.detail : "Up出力に失敗しました。");
    }
    return payload.filename || rec.filename;
  } finally {
    encodeProgress.delete(rec.id);
    upscaleProgress.delete(rec.id);
  }
}

// 録画単体のUp出力(詳細modalの録画一覧の操作)。
async function upDownloadRecording(rec, btn) {
  await ensureNotifyPermission();
  const prog = makeOutputProgress();
  btn.replaceWith(prog);
  try {
    const name = await upOutputRecording(rec, prog, "");
    finishOutputProgress(prog);
    notifyOutputDone(name);
    // done badge(Up出力済)を反映するため詳細を再描画する。
    if (currentSessionId !== null) showDetail(currentSessionId);
  } catch (err) {
    prog.replaceWith(btn);
    window.alert(err.message);
  }
}

// Session単位のUp出力(履歴一覧の操作)。そのSessionの完了録画をすべて高画質化する。
async function upOutputSession(session, btn) {
  await ensureNotifyPermission();
  const prog = makeOutputProgress();
  btn.replaceWith(prog);
  // 再描画でprogが行から切り離されても進捗を保持できるよう登録する。
  activeUpOutputs.set(session.id, prog);
  try {
    const res = await fetch(`/api/sessions/${session.id}`);
    if (!res.ok) throw new Error("Session情報の取得に失敗しました。");
    const data = await res.json();
    const recs = (data.recordings || []).filter(
      (r) => r.status === "completed" || r.status === "interrupted");
    if (!recs.length) throw new Error("出力できる録画がありません。");
    let lastName = "";
    for (let i = 0; i < recs.length; i++) {
      const label = recs.length > 1 ? `(${i + 1}/${recs.length}) ` : "";
      lastName = await upOutputRecording(recs[i], prog, label);
    }
    finishOutputProgress(prog);
    notifyOutputDone(recs.length > 1 ? `${recs.length}件の録画をUp出力しました` : lastName);
  } catch (err) {
    prog.replaceWith(btn);
    window.alert(err.message);
  } finally {
    activeUpOutputs.delete(session.id);
    // done badge(Up出力済)をbackendの最新状態で反映する。
    loadSessions();
  }
}

function recordingActions(rec) {
  const wrap = document.createElement("span");
  wrap.className = "row-actions";
  if (rec.status === "completed" || rec.status === "interrupted") {
    const dl = document.createElement("button");
    dl.className = "btn btn-small";
    // 出力済みでも再出力可能（活性のまま）。ラベルだけ「(済)」にする。
    dl.textContent = rec.has_output ? "出力(済)" : "出力";
    dl.title = "設定でComment/Gift演出が有効な場合、焼き込み済み動画をrecordings folderへ出力します（再Encodeのため時間がかかります）。完了時にブラウザ通知を出します。";
    dl.addEventListener("click", () => downloadRecording(rec, dl));
    wrap.appendChild(dl);

    if (upscaleConfigured) {
      const up = document.createElement("button");
      up.className = "btn btn-small";
      // Up出力済みでも再出力可能（活性のまま）。ラベルだけ「(済)」にする。
      up.textContent = rec.has_up_output ? "Up出力(済)" : "Up出力";
      up.title = "この録画をローカルAI(超解像model)で高画質化し、.up.mp4としてrecordings folderへ出力します。焼き込みが有効な場合は焼き込み後の動画を高画質化します。GPUでも録画時間の数倍かかります。";
      up.addEventListener("click", () => upDownloadRecording(rec, up));
      wrap.appendChild(up);
    }

    if (sttConfigured) {
      const tr = document.createElement("button");
      tr.className = "btn btn-small";
      // 文字起こし済みでも再実行可能（活性のまま）。ラベルだけ「(済)」にする。
      tr.textContent = rec.has_transcript ? "文字起こし(済)" : "文字起こし";
      tr.title = "この録画の音声をローカルAIで文字起こしします（初回はmodel読み込みで時間がかかります）。結果はキャッシュされます。";
      tr.addEventListener("click", async () => {
        await transcribeOrShow(rec, tr);
        // done badge(文字起こし済)を反映するため詳細を再描画する。
        if (currentSessionId !== null) showDetail(currentSessionId);
      });
      wrap.appendChild(tr);
    }
  }
  const del = document.createElement("button");
  del.className = "btn btn-small btn-danger";
  del.textContent = "削除";
  del.disabled = rec.status === "recording";
  del.addEventListener("click", async () => {
    if (!window.confirm(`録画 #${rec.id} (${rec.filename}) を削除しますか？この操作は取り消せません。`)) return;
    try {
      await apiSend("DELETE", `/api/recordings/${rec.id}`);
      if (currentSessionId !== null) showDetail(currentSessionId);
    } catch (err) {
      window.alert(err.message);
    }
  });
  wrap.appendChild(del);
  return wrap;
}

function renderRecordings(recordings) {
  renderTableRows(
    "recording-list",
    "recording-list-empty",
    recordings,
    (rec) => {
      const dur = rec.ended_at ? fmtDuration(rec.ended_at - rec.started_at) : "-";
      const mb = `${(rec.bytes / 1048576).toFixed(1)} MB`;
      return [
        `#${rec.id}`,
        rec.filename,
        rec.quality || "-",
        RECORDING_STATUS[rec.status] || rec.status,
        dur,
        mb,
        recordingActions(rec),
      ];
    },
    [0, 4, 5],
  );
}

// ---- AI コメント分析 ----
let aiConfigured = false;

async function loadAiStatus() {
  try {
    const res = await fetch("/api/ai/status");
    if (!res.ok) return;
    const st = await res.json();
    aiConfigured = Boolean(st.configured);
    const note = document.getElementById("ai-status-note");
    if (st.configured) note.textContent = `model: ${st.model}`;
    else if (st.enabled) note.textContent = "AI有効・model未設定 (TICTOK_AI_MODEL)";
    else note.textContent = "AI無効 (TICTOK_AI_ENABLED=1 で有効化)";
  } catch (e) {
    /* status取得失敗時はAI無効扱いのまま */
  }
}

function resetAiResult() {
  const btn = document.getElementById("ai-analyze-btn");
  btn.disabled = !aiConfigured;
  btn.textContent = "分析する";
  document.getElementById("ai-analyze-status").textContent = aiConfigured
    ? ""
    : "ローカルAIが未設定のため利用できません。";
  const result = document.getElementById("ai-result");
  result.classList.add("hidden");
  result.innerHTML = "";
}

async function runAiAnalysis() {
  if (currentSessionId === null || !aiConfigured) return;
  const btn = document.getElementById("ai-analyze-btn");
  const status = document.getElementById("ai-analyze-status");
  btn.disabled = true;
  btn.textContent = "分析中…";
  status.textContent = "ローカルAIで分析しています（modelにより数十秒かかることがあります）…";
  try {
    const res = await fetch(`/api/sessions/${currentSessionId}/comment-analysis`);
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(typeof payload.detail === "string" ? payload.detail : "分析に失敗しました。");
    }
    renderAiAnalysis(payload);
    status.textContent = `${payload.comment_count}件のCommentを分析しました。`;
  } catch (err) {
    status.textContent = err.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "再分析";
  }
}

function renderAiAnalysis(payload) {
  const a = payload.analysis || {};
  const result = document.getElementById("ai-result");
  result.innerHTML = "";

  if (a.mood) {
    const mood = document.createElement("div");
    mood.className = "ai-mood";
    mood.textContent = a.mood;
    result.appendChild(mood);
  }

  const s = a.sentiment || {};
  const pos = Number(s.positive) || 0;
  const neu = Number(s.neutral) || 0;
  const neg = Number(s.negative) || 0;
  const total = pos + neu + neg || 1;
  const bar = document.createElement("div");
  bar.className = "ai-sent";
  bar.append(
    sentSeg("pos", (pos / total) * 100, `ポジ ${Math.round(pos)}`),
    sentSeg("neu", (neu / total) * 100, `中立 ${Math.round(neu)}`),
    sentSeg("neg", (neg / total) * 100, `ネガ ${Math.round(neg)}`),
  );
  result.appendChild(bar);

  if (Array.isArray(a.topics) && a.topics.length) {
    result.appendChild(aiSubhead("主な話題"));
    a.topics.forEach((t) => {
      const row = document.createElement("div");
      row.className = "ai-topic";
      const lbl = document.createElement("b");
      lbl.textContent = t.label || "-";
      const share = document.createElement("span");
      share.className = "ai-share";
      share.textContent = `${Number(t.share) || 0}%`;
      const ex = document.createElement("span");
      ex.className = "ai-ex";
      ex.textContent = t.example ? `「${t.example}」` : "";
      row.append(lbl, share, ex);
      result.appendChild(row);
    });
  }

  if (Array.isArray(a.highlights) && a.highlights.length) {
    result.appendChild(aiSubhead("ハイライト"));
    const ul = document.createElement("ul");
    ul.className = "ai-hl";
    a.highlights.forEach((x) => {
      const li = document.createElement("li");
      li.textContent = x;
      ul.appendChild(li);
    });
    result.appendChild(ul);
  }
  result.classList.remove("hidden");
}

function aiSubhead(text) {
  const h = document.createElement("div");
  h.className = "ai-sub";
  h.textContent = text;
  return h;
}

function sentSeg(cls, pct, label) {
  const seg = document.createElement("span");
  seg.className = "ai-seg " + cls;
  seg.style.inlineSize = `${pct}%`;
  if (pct >= 12) seg.textContent = label;
  seg.title = label;
  return seg;
}

// ---- AI高画質化(Upscale) ----
let upscaleConfigured = false;

async function loadUpscaleStatus() {
  try {
    const res = await fetch("/api/upscale/status");
    if (!res.ok) return;
    const st = await res.json();
    const prev = upscaleConfigured;
    upscaleConfigured = Boolean(st.configured);
    // status取得はSession一覧loadと並行のため、有効化が後から確定した場合は
    // 操作列のUp出力Buttonを出すため再描画する。
    if (upscaleConfigured !== prev) renderTable();
  } catch (e) {
    /* status取得失敗時はUpscale無効扱い */
  }
}

// ---- 文字起こし(STT) ----
let sttConfigured = false;
// recording.id → 進捗を反映する関数（WS transcribe_progress で更新）。
const transcribeProgress = new Map();

async function loadSttStatus() {
  try {
    const res = await fetch("/api/stt/status");
    if (!res.ok) return;
    const st = await res.json();
    const prev = sttConfigured;
    sttConfigured = Boolean(st.configured);
    // status取得はSession一覧loadと並行のため、有効化が後から確定した場合は
    // 操作列の文字起こしButtonを出すため再描画する。
    if (sttConfigured !== prev) renderTable();
  } catch (e) {
    /* status取得失敗時はSTT無効扱い */
  }
}

// 文字起こし: 既にあれば表示、無ければ実行してから表示。実行中はWS進捗をbtnに反映。
async function transcribeOrShow(rec, btn) {
  const orig = btn.textContent;
  btn.disabled = true;
  try {
    let res = await fetch(`/api/recordings/${rec.id}/transcript`);
    if (res.status === 404) {
      btn.textContent = "文字起こし中… 0%";
      transcribeProgress.set(rec.id, (pct) => {
        btn.textContent = `文字起こし中… ${pct}%`;
      });
      res = await fetch(`/api/recordings/${rec.id}/transcribe`, { method: "POST" });
    }
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(typeof payload.detail === "string" ? payload.detail : "文字起こしに失敗しました。");
    }
    openTranscript(rec, payload);
  } catch (err) {
    window.alert(err.message);
  } finally {
    transcribeProgress.delete(rec.id);
    btn.disabled = false;
    btn.textContent = orig;
  }
}

// 表示中transcriptのsegment要素と開始秒（動画の再生位置と同期させる）。
let transcriptSegEls = [];
let transcriptActiveIdx = -1;

function openTranscript(rec, data) {
  const segs = data.segments || [];
  document.getElementById("transcript-title").textContent =
    `録画 #${rec.id} 文字起こし（${data.language || "?"} · ${data.model || ""} · ${segs.length}行）`;
  const video = document.getElementById("transcript-video");
  // 同録画をRange対応endpointで配信。segmentクリックでその時刻へseekできる。
  video.src = `/api/recordings/${rec.id}/play`;
  const wrap = document.getElementById("transcript-segments");
  wrap.innerHTML = "";
  transcriptSegEls = [];
  transcriptActiveIdx = -1;
  if (!segs.length) {
    wrap.textContent = data.text || "（音声が検出されませんでした）";
  } else {
    segs.forEach((s) => {
      const row = document.createElement("div");
      row.className = "tr-seg";
      row.tabIndex = 0;
      const t = document.createElement("span");
      t.className = "tr-t";
      t.textContent = fmtDuration(s.start);
      const x = document.createElement("span");
      x.className = "tr-x";
      x.textContent = s.text;
      row.append(t, x);
      const seek = () => {
        try { video.currentTime = s.start; } catch (e) { /* seek不可でも続行 */ }
        video.play().catch(() => {});
      };
      row.addEventListener("click", seek);
      row.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); seek(); }
      });
      wrap.appendChild(row);
      transcriptSegEls.push({ start: s.start, el: row });
    });
  }
  document.getElementById("transcript-modal").classList.remove("hidden");
}

// 再生位置に対応するsegment（start<=現在時刻 の最後）を強調し、追従scrollする。
function highlightActiveSegment() {
  if (!transcriptSegEls.length) return;
  const t = document.getElementById("transcript-video").currentTime;
  let idx = -1;
  for (let i = 0; i < transcriptSegEls.length; i++) {
    if (transcriptSegEls[i].start <= t) idx = i;
    else break;
  }
  if (idx === transcriptActiveIdx) return;
  if (transcriptActiveIdx >= 0 && transcriptSegEls[transcriptActiveIdx]) {
    transcriptSegEls[transcriptActiveIdx].el.classList.remove("active");
  }
  transcriptActiveIdx = idx;
  if (idx >= 0) {
    const el = transcriptSegEls[idx].el;
    el.classList.add("active");
    el.scrollIntoView({ block: "nearest" });
  }
}

function closeTranscript() {
  const video = document.getElementById("transcript-video");
  video.pause();
  video.removeAttribute("src");
  video.load();
  document.getElementById("transcript-modal").classList.add("hidden");
}

// ---- CSV of visible table ----
function exportVisibleCsv() {
  const rows = filteredSessions();
  const header = [
    "session_id", "unique_id", "started_at", "ended_at", "status",
    "gifts", "diamonds", "comments", "likes", "follows", "shares", "joins",
    "battles", "battle_points", "peak_viewers", "note",
  ];
  const lines = [header.join(",")];
  rows.forEach((s) => {
    const st = s.stats || {};
    const cells = [
      s.id,
      s.unique_id,
      fmtDateTime(s.started_at),
      s.ended_at ? fmtDateTime(s.ended_at) : "",
      activeIds.has(s.id) ? "収集中" : s.status,
      st.gifts || 0, st.diamonds || 0, st.comments || 0, st.likes_total || 0,
      st.follows || 0, st.shares || 0, st.joins || 0, st.battles || 0,
      st.battle_points || 0, st.viewers_peak || 0,
      (s.note || "").replace(/"/g, '""'),
    ];
    lines.push(cells.map((c) => `"${String(c)}"`).join(","));
  });
  const blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "tictok_sessions.csv";
  a.click();
  URL.revokeObjectURL(url);
}

// ---- ユーザー単位の一括削除 ----
// 配信者を複数選択し、その履歴(Session/録画/分析)をまとめて削除する。対象一覧は
// /api/streamers(owner-identityで集約・正確なSession数)から取り、削除もunique_id
// 単位でserverが@handle変更を辿って束ねるため、表示上限に依らず全履歴を消せる。
let userdelStreamers = [];
const userdelSelected = new Set();

async function openUserDelete() {
  userdelSelected.clear();
  document.getElementById("userdel-search").value = "";
  document.getElementById("userdel-status").textContent = "";
  document.getElementById("userdel-modal").classList.remove("hidden");
  try {
    const res = await fetch("/api/streamers");
    if (!res.ok) throw new Error("配信者一覧の取得に失敗しました。");
    userdelStreamers = (await res.json()).streamers || [];
  } catch (err) {
    userdelStreamers = [];
    document.getElementById("userdel-status").textContent = err.message;
  }
  renderUserDelete();
}

function closeUserDelete() {
  document.getElementById("userdel-modal").classList.add("hidden");
}

function filteredStreamers() {
  const q = document.getElementById("userdel-search").value.trim().toLowerCase();
  if (!q) return userdelStreamers;
  return userdelStreamers.filter((s) =>
    `${s.unique_id} ${s.nickname || ""}`.toLowerCase().includes(q));
}

function renderUserDelete() {
  const rows = filteredStreamers();
  renderTableRows(
    "userdel-rows",
    "userdel-empty",
    rows,
    (s) => {
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = userdelSelected.has(s.unique_id);
      cb.addEventListener("change", () => {
        if (cb.checked) userdelSelected.add(s.unique_id);
        else userdelSelected.delete(s.unique_id);
        syncUserDeleteControls();
      });
      return [
        cb,
        userCell({ unique_id: s.unique_id, nickname: s.nickname || s.unique_id, avatar: s.avatar || "" }),
        fmtNum(s.sessions),
        fmtNum(s.diamonds),
        fmtNum(s.comments),
      ];
    },
    [2, 3, 4],
  );
  syncUserDeleteControls();
}

// 選択数に応じてButton活性・全選択checkboxの状態(全/一部/無)を同期する。
function syncUserDeleteControls() {
  const visible = filteredStreamers();
  const selall = document.getElementById("userdel-selall");
  const selectedVisible = visible.filter((s) => userdelSelected.has(s.unique_id)).length;
  selall.checked = visible.length > 0 && selectedVisible === visible.length;
  selall.indeterminate = selectedVisible > 0 && selectedVisible < visible.length;
  const run = document.getElementById("userdel-run");
  run.disabled = userdelSelected.size === 0;
  run.textContent = userdelSelected.size > 0
    ? `選択した${userdelSelected.size}名を削除`
    : "選択した配信者を削除";
}

async function runUserDelete() {
  const ids = [...userdelSelected];
  if (!ids.length) return;
  const names = userdelStreamers
    .filter((s) => userdelSelected.has(s.unique_id))
    .map((s) => `@${s.unique_id}`)
    .join("\n");
  if (!window.confirm(`次の${ids.length}名の履歴をすべて削除しますか？この操作は取り消せません。\n\n${names}`)) return;
  const run = document.getElementById("userdel-run");
  const status = document.getElementById("userdel-status");
  run.disabled = true;
  status.textContent = "削除中…";
  try {
    const result = await apiSend("POST", "/api/sessions/delete-by-users", { unique_ids: ids });
    if (currentSessionId !== null) closeDetail();
    closeUserDelete();
    await Promise.all([loadSessions(), loadKpi()]);
    // 削除完了はKPI/一覧の更新で分かるが、件数は明示しない(modalは閉じ済)。
    void result;
  } catch (err) {
    status.textContent = err.message;
    run.disabled = false;
  }
}

document.getElementById("bulk-del-users").addEventListener("click", openUserDelete);
document.getElementById("userdel-close").addEventListener("click", closeUserDelete);
document.getElementById("userdel-modal").addEventListener("click", (e) => {
  if (e.target.id === "userdel-modal") closeUserDelete();
});
document.getElementById("userdel-search").addEventListener("input", renderUserDelete);
document.getElementById("userdel-selall").addEventListener("change", (e) => {
  const visible = filteredStreamers();
  if (e.target.checked) visible.forEach((s) => userdelSelected.add(s.unique_id));
  else visible.forEach((s) => userdelSelected.delete(s.unique_id));
  renderUserDelete();
});
document.getElementById("userdel-run").addEventListener("click", runUserDelete);

// ---- events ----
document.getElementById("note-save").addEventListener("click", async () => {
  if (currentSessionId === null) return;
  const status = document.getElementById("note-status");
  try {
    await apiSend("PATCH", `/api/sessions/${currentSessionId}`, {
      note: document.getElementById("note-input").value,
    });
    status.textContent = "保存しました。";
    await loadSessions();
  } catch (err) {
    status.textContent = err.message;
  }
});

document.getElementById("ai-analyze-btn").addEventListener("click", runAiAnalysis);
document.getElementById("transcript-close").addEventListener("click", closeTranscript);
document.getElementById("transcript-modal").addEventListener("click", (e) => {
  if (e.target.id === "transcript-modal") closeTranscript();
});
document.getElementById("transcript-video").addEventListener("timeupdate", highlightActiveSegment);
document.getElementById("detail-close").addEventListener("click", closeDetail);
document.getElementById("detail-modal").addEventListener("click", (e) => {
  if (e.target.id === "detail-modal") closeDetail();
});
document.getElementById("export-csv").addEventListener("click", exportVisibleCsv);
// 検索は1キーストロークごとにtbody全再構築が走るため~200msデバウンスする。
// period/status/sortは離散的な選択のため即時反映でよい。
let searchTimer = null;
flt.search.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(renderTable, 200);
});
[flt.period, flt.status, flt.sort].forEach((el) =>
  el.addEventListener("input", renderTable),
);

function handleMessage(msg) {
  if (msg.type === "output_progress") {
    const update = encodeProgress.get(msg.recording_id);
    if (update) update(msg.pct);
    return;
  }
  if (msg.type === "upscale_progress") {
    const update = upscaleProgress.get(msg.recording_id);
    if (update) update(msg.pct);
    return;
  }
  if (msg.type === "transcribe_progress") {
    const update = transcribeProgress.get(msg.recording_id);
    if (update) update(msg.pct);
    return;
  }
  if (msg.type === "battles" || msg.type === "stats") {
    // 開いている収集中Sessionと同じ配信者の更新だけ、Battleカードをliveで貼り替える。
    if (currentSessionUid && msg.monitor === currentSessionUid) refreshOpenBattles();
    return;
  }
  if (msg.type === "monitors" || msg.type === "state") {
    scheduleReload();
  }
}

// monitors/stateは収集中に高頻度で届く。1件ごとにSession一覧+KPIをフル再取得すると
// 重いため、~1sで合体し最大1回/秒程度に抑える(末尾実行でburstを1回にまとめる)。
let reloadTimer = null;
function scheduleReload() {
  if (reloadTimer) return;
  reloadTimer = setTimeout(() => {
    reloadTimer = null;
    loadSessions();
    loadKpi();
  }, 1000);
}

detailChart = createTimelineChart(document.getElementById("detail-chart"));
loadAiStatus();
loadSttStatus();
loadUpscaleStatus();
loadKpi();
loadSessions();
connectWS(handleMessage);
setInterval(loadKpi, 30000);
