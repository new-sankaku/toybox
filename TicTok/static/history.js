"use strict";

let detailChart = null;
let currentSessionId = null;
// 開いている詳細modalの配信者ID。収集中Sessionのbattle/stats更新をliveで受け、
// Battleカード(スコア推移chart含む)を貼り替えるために保持する。
let currentSessionUid = null;
let allSessions = [];
let activeIds = new Set();
// Session一覧が空に見えるときの理由。取得前(loading)・0件(loaded)・取得失敗(failed)。
// 取得前を「保存されたSessionがありません。」と描くと、上のKPI(総Session)と矛盾した
// 確定的な事実を1秒以上出すことになる。
let sessionsState = "loading";
let sessionsError = null;
// 制限(メンバー限定/年齢制限)で録画できなかった試行のsession status。配信実績では
// ないので「終了」filterからは外し、専用の選択肢で絞り込めるようにする。
const STATUS_RESTRICTED = "restricted";
// 出力中Sessionのprogress要素。WS更新でtableが再描画されても、行のbuttonを
// 作り直す代わりにこの要素を再装着し、spinner/進捗を保持する。Session単位の出力は
// server側のjobが実体なので、この要素はreload後もjob snapshotから復元される。
const activeOutputs = new Map();
// Up出力(AI高画質化)中のSession行のprogress要素。
const activeUpOutputs = new Map();
// 再mp4化(元.tsからのfinalize再実行)中の進捗%はWS reprocess_progressで届く。
const reprocessProgress = new Map();
// 音量正規化(mp4の音声だけ作り直し)中の進捗%はWS audionorm_progressで届く。
const audionormProgress = new Map();
// 単体録画のjob(出力/Up出力/再mp4化)の待受。POSTはjob_idを返すだけで、実処理はserver側の
// 永続queueが行うため、完了/失敗はWSのjob_updateでしか届かない。job_id → {prog,resolve,reject}。
const jobWatchers = new Map();

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
  bar.removeAttribute("title");
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
  let dash;
  try {
    dash = await apiSend("GET", "/api/dashboard");
  } catch (err) {
    // 取得できなかった集計を0で埋めない。まだ一度も描けていないときだけ失敗を明示し、
    // 前回の値が出ているならそれを残す(定期reloadの1回が落ちただけで消さない)。
    const bar = document.getElementById("kpi-bar");
    bar.title = errorDetailText(err);
    if (!bar.childElementCount) {
      bar.textContent = "集計値を取得できませんでした（0件という意味ではありません）。";
    }
    return;
  }
  // 録画数はdashboard totals(非cap COUNT)を使う。旧実装は/api/recordingsの返却件数を
  // 数えていたためsession_list_limit(既定100)で頭打ちになっていた。
  const recordingCount = (dash.totals && dash.totals.recordings) || 0;
  renderKpi(dash.totals || {}, (dash.streamers || []).length, recordingCount);
}

// ---- session table ----
async function loadSessions() {
  // limit=0で全件取得。filter/検索/sortはclient側で全Sessionに対して行うため、最新N件で
  // 頭打ちにするとperiod/検索で古いSessionが不可視になる(session行は軽量なので全件でよい)。
  let data;
  try {
    data = await apiSend("GET", "/api/sessions?limit=0");
  } catch (err) {
    // 既に描けている行はそのまま残す(定期reloadの1回が落ちただけで一覧を空にしない)。
    sessionsState = "failed";
    sessionsError = err;
    renderTable();
    return;
  }
  sessionsState = "loaded";
  sessionsError = null;
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

// ---- 並び替え ----
// 並替selectと列headerのclickは同じsortStateを書き換える。どちらかを別に持つと、
// 片方が実際の並びと違う指定を出したまま残る。
// order は昇降の呼び名(文言を他の選択肢と揃えるため)。
const SESSION_SORT_COLUMNS = {
  id: { label: "#", order: "time", dir: "desc", get: (s) => s.id },
  unique_id: { label: "配信者", order: "text", dir: "asc", get: (s) => s.unique_id },
  started_at: { label: "開始", order: "time", dir: "desc", get: (s) => s.started_at },
  // 収集中Sessionは終了時刻が無いので、表示(「収集中」)と同じく現時点までの経過で並べる。
  duration: {
    label: "時間",
    order: "length",
    dir: "desc",
    get: (s) => (s.ended_at || Date.now() / 1000) - s.started_at,
  },
  gifts: { label: "Gift", dir: "desc", get: (s) => sessionStat(s, "gifts") },
  diamonds: { label: "コイン", dir: "desc", get: (s) => sessionStat(s, "diamonds") },
  comments: { label: "Comment", dir: "desc", get: (s) => sessionStat(s, "comments") },
  likes_total: { label: "Like", dir: "desc", get: (s) => sessionStat(s, "likes_total") },
  follows: { label: "Follow", dir: "desc", get: (s) => sessionStat(s, "follows") },
  shares: { label: "Share", dir: "desc", get: (s) => sessionStat(s, "shares") },
  joins: { label: "入室", dir: "desc", get: (s) => sessionStat(s, "joins") },
  battles: { label: "Battle", dir: "desc", get: (s) => sessionStat(s, "battles") },
  battle_points: { label: "B.Score", dir: "desc", get: (s) => sessionStat(s, "battle_points") },
  viewers_peak: { label: "最大同接", dir: "desc", get: (s) => sessionStat(s, "viewers_peak") },
};

// 並替selectの選択肢が指すsortState。selectのvalueはこのtableの見出しと1対1。
const SESSION_SORT_PRESETS = {
  started_desc: { key: "started_at", dir: "desc" },
  started_asc: { key: "started_at", dir: "asc" },
  gifts: { key: "gifts", dir: "desc" },
  diamonds: { key: "diamonds", dir: "desc" },
  comments: { key: "comments", dir: "desc" },
  likes_total: { key: "likes_total", dir: "desc" },
  battle_points: { key: "battle_points", dir: "desc" },
  unique_id: { key: "unique_id", dir: "asc" },
};
// 列headerからの並びがselectのどの選択肢にも当たらないとき、その並びを表示する行き先。
const SORT_COLUMN_OPTION = "column";

let sortState = { ...SESSION_SORT_PRESETS.started_desc };

function sessionStat(session, key) {
  return (session.stats && session.stats[key]) || 0;
}

function sortOptionLabel(key, dir) {
  const column = SESSION_SORT_COLUMNS[key];
  if (column.order === "time") return `${column.label}(${dir === "desc" ? "新しい順" : "古い順"})`;
  if (column.order === "text") return `${column.label}(${dir === "asc" ? "昇順" : "降順"})`;
  if (column.order === "length") return `${column.label} ${dir === "desc" ? "長い順" : "短い順"}`;
  return `${column.label} ${dir === "desc" ? "多い順" : "少ない順"}`;
}

function filteredSessions() {
  const q = flt.search.value.trim().toLowerCase();
  const after = periodStart(flt.period.value);
  const statusFilter = flt.status.value;
  let rows = allSessions.filter((s) => {
    if (after && s.started_at < after) return false;
    const isActive = activeIds.has(s.id);
    const restricted = s.status === STATUS_RESTRICTED;
    if (statusFilter === "live" && !isActive) return false;
    if (statusFilter === "ended" && (isActive || restricted)) return false;
    if (statusFilter === "restricted" && !restricted) return false;
    if (q) {
      // 一覧に出ているのは表示名(owner_nickname)なので、それで引けなければ
      // 「見えているのに絞り込めない」ことになる。@idとMemoに加えて検索対象にする。
      const hay = `${s.unique_id} ${s.owner_nickname || ""} ${s.note || ""}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
  const column = SESSION_SORT_COLUMNS[sortState.key] || SESSION_SORT_COLUMNS.started_at;
  const sign = sortState.dir === "asc" ? 1 : -1;
  const compare = column.order === "text"
    ? (a, b) => sign * String(column.get(a)).localeCompare(String(column.get(b)))
    : (a, b) => sign * (column.get(a) - column.get(b));
  // 同値の並びが描画ごとに揺れないよう、最後は必ず開始時刻とidで決める。
  rows.sort((a, b) => compare(a, b) || b.started_at - a.started_at || b.id - a.id);
  return rows;
}

function syncSortSelect() {
  const preset = Object.keys(SESSION_SORT_PRESETS).find(
    (name) => SESSION_SORT_PRESETS[name].key === sortState.key
      && SESSION_SORT_PRESETS[name].dir === sortState.dir,
  );
  let extra = flt.sort.querySelector(`option[value="${SORT_COLUMN_OPTION}"]`);
  if (preset) {
    if (extra) extra.remove();
    flt.sort.value = preset;
    return;
  }
  if (!extra) {
    extra = document.createElement("option");
    extra.value = SORT_COLUMN_OPTION;
    flt.sort.appendChild(extra);
  }
  extra.textContent = sortOptionLabel(sortState.key, sortState.dir);
  flt.sort.value = SORT_COLUMN_OPTION;
}

function syncSortHeaders() {
  document.querySelectorAll("#session-table th[data-sort]").forEach((th) => {
    const active = th.dataset.sort === sortState.key;
    th.classList.toggle("sorted", active);
    th.classList.toggle("sorted-asc", active && sortState.dir === "asc");
    th.setAttribute(
      "aria-sort",
      active ? (sortState.dir === "asc" ? "ascending" : "descending") : "none",
    );
  });
}

function applySort(key) {
  const column = SESSION_SORT_COLUMNS[key];
  if (!column) return;
  sortState = sortState.key === key
    ? { key, dir: sortState.dir === "desc" ? "asc" : "desc" }
    : { key, dir: column.dir };
  syncSortSelect();
  renderTable();
}

function bindSortHeaders() {
  document.querySelectorAll("#session-table th[data-sort]").forEach((th) => {
    th.tabIndex = 0;
    th.title = "この列で並べ替えます（もう一度押すと順序が入れ替わります）。";
    th.addEventListener("click", () => applySort(th.dataset.sort));
    th.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      e.preventDefault();
      applySort(th.dataset.sort);
    });
  });
}

function statusCell(session) {
  const isActive = activeIds.has(session.id);
  const span = document.createElement("span");
  if (isActive) {
    span.className = "st live";
    span.textContent = "収集中";
  } else {
    const info = STATUS_LABELS[session.status] || STATUS_LABELS.ended;
    // 制限sessionは配信実績ではなく「録画できなかった試行」なので、通常の終了sessionと
    // 見分けが付く別Classにする。集計からも除外されているため数値は全て0で並ぶ。
    const restricted = session.status === STATUS_RESTRICTED;
    span.className = restricted ? "st restricted" : "st ended";
    span.textContent = info.badge;
    if (restricted) span.title = info.message;
  }
  return span;
}

// 操作Buttonは1つずつ独立したtable列(td.act)に入れる。全行が同じ列構成のため、
// tableの列機構が幅を自動で合わせ、複数行に渡って縦に揃う（幅をnumberで指定しない）。
// 列数は表headerの操作thのcolspan(actionColumnCount)と一致させる。
function actionColumnCount() {
  return 3 + Number(upscaleConfigured) + Number(sttConfigured);
}

function actionCells(session) {
  const isActive = activeIds.has(session.id);
  const outputting = activeOutputs.has(session.id);
  const upOutputting = activeUpOutputs.has(session.id);
  const hasVideo = (session.recording_count || 0) > 0;
  const cells = [];
  const cell = (node) => {
    const td = document.createElement("td");
    td.className = "act";
    td.appendChild(node);
    return td;
  };

  const showBtn = document.createElement("button");
  showBtn.className = "btn btn-small";
  showBtn.textContent = "詳細";
  showBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    showDetail(session.id);
  });
  cells.push(cell(showBtn));

  // 出力中の行は再描画されても、進行中のprogress要素をそのまま再装着する。
  let outNode;
  if (outputting) {
    outNode = activeOutputs.get(session.id);
  } else {
    const out = document.createElement("button");
    out.className = "btn btn-small";
    // 出力済みでも再出力したいのでButtonは活性のまま、ラベルだけ「済」にする。
    out.textContent = session.output_done ? "焼き込み出力済" : "焼き込み出力";
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
  cells.push(cell(outNode));

  // Up出力(AI高画質化)。ローカルAIのUpscale設定が有効な場合のみ列を出す。
  if (upscaleConfigured) {
    let upNode;
    if (upOutputting) {
      upNode = activeUpOutputs.get(session.id);
    } else {
      const up = document.createElement("button");
      up.className = "btn btn-small";
      // 出力済みでも再出力可能（活性のまま）。ラベルだけ「済」にする。
      up.textContent = session.up_output_done ? "AI高画質済" : "AI高画質";
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
    cells.push(cell(upNode));
  }

  // 文字起こし(STT有効時のみ列を出す)。複数録画がある場合は結果がRecording単位のため
  // 詳細へ誘導し、単一録画はその場でModalに表示する。
  if (sttConfigured) {
    const tr = document.createElement("button");
    tr.className = "btn btn-small";
    // 文字起こし済みでも再実行可能（活性のまま）。ラベルだけ「済」にする。
    // 録画が複数ある場合は押すと選択menuが出る。▾でそれを予告する。
    const multi = (session.recording_count || 0) > 1;
    tr.textContent = (session.transcript_done ? "字幕化済" : "字幕化") + (multi ? " ▾" : "");
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
    cells.push(cell(tr));
  }

  const del = document.createElement("button");
  del.className = "btn btn-small btn-danger";
  del.textContent = "削除";
  del.disabled = isActive || outputting || upOutputting;
  del.title = isActive
    ? "収集中のSessionは削除できません"
    : outputting || upOutputting
      ? "出力中のSessionは削除できません"
      : "このSessionの記録(Comment/Gift/分析)と録画をまとめて削除します。取り消せません。";
  del.addEventListener("click", async (e) => {
    e.stopPropagation();
    const ok = await confirmDialog(
      `Session #${sessionNo(session.id)} (@${session.unique_id}) を削除しますか？この操作は取り消せません。`,
      { title: "Sessionの削除", confirmLabel: "削除する" },
    );
    if (!ok) return;
    try {
      await apiSend("DELETE", `/api/sessions/${session.id}`);
      if (currentSessionId === session.id) closeDetail();
      await Promise.all([loadSessions(), loadKpi()]);
    } catch (err) {
      showError(err);
    }
  });
  cells.push(cell(del));

  return cells;
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
      showToast("文字起こしできる録画がありません。");
      return;
    }
    if (recs.length === 1) {
      await transcribeOrShow(recs[0], btn);
      return;
    }
    // 複数録画は「どれを」が決まらない。詳細を開かせてscrollさせ直すのではなく、
    // その場で選ばせる(押した結果が「押せませんでした」になるのを避ける)。
    openMenuAt(btn, recs.map((rec) => ({
      label: `${recName(rec)}${rec.has_transcript ? "（字幕化済）" : ""}`,
      title: rec.has_transcript
        ? "保存済みの文字起こしを表示します。"
        : "この録画の音声をローカルAIで文字起こしします。",
      onSelect: () => transcribeOrShow(rec, btn),
    })));
  } catch (err) {
    showError(err);
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
  syncSortHeaders();
  tbody.innerHTML = "";
  // 操作Buttonは1列ずつ独立tdなので、header操作thをその列数だけ横結合して整合させる。
  const opTh = document.getElementById("op-th");
  if (opTh) opTh.colSpan = actionColumnCount();
  const emptyEl = document.getElementById("session-empty");
  if (rows.length > 0) setListState(emptyEl, "ok");
  else if (sessionsState === "failed") setListState(emptyEl, "failed", sessionsError);
  else if (sessionsState === "loading") setListState(emptyEl, "loading");
  // 保存が0件なのか、filterに一致しないだけなのかは別の状態。後者を「保存が無い」と
  // 描くと、保存済みSessionを取り違えたことになる。
  else if (allSessions.length > 0)
    setListMessage(emptyEl, "条件に一致するSessionがありません。filterを変更してください。");
  else setListState(emptyEl, "empty");
  // 1行あたりavatar・Memo入力・操作button群で30要素前後になる表を、収集中は毎秒
  // 組み直す。live tbodyへ1行ずつappendすると行数ぶんlayoutが走るので、画面から
  // 切り離されたfragmentの上で組んでから1回で挿す。
  const fragment = document.createDocumentFragment();
  rows.forEach((s) => {
    const stats = s.stats || {};
    const tr = document.createElement("tr");
    const duration = s.ended_at ? fmtDuration(s.ended_at - s.started_at) : "収集中";

    const cells = [];
    cells.push(textTd(`#${sessionNo(s.id)}`));
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
    cells.push(noteTd(s));
    actionCells(s).forEach((td) => cells.push(td));

    cells.forEach((td) => tr.appendChild(td));
    fragment.appendChild(tr);
  });
  tbody.appendChild(fragment);
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

// Memoは検索対象(filteredSessionsがs.noteを見る)なのに、絞り込んだ結果の一覧では
// 中身が見えず、確認に詳細modal+scrollが要った。その場で読めて、その場で直せるようにする。
function noteTd(session) {
  const td = document.createElement("td");
  td.className = "note-cell";
  const input = document.createElement("input");
  input.type = "text";
  input.className = "note-inline";
  input.value = session.note || "";
  input.placeholder = "—";
  input.title = "Memo。ここで直接編集でき、離れると保存されます（検索boxの絞込対象です）。";
  input.addEventListener("click", (e) => e.stopPropagation());
  input.addEventListener("change", async () => {
    const value = input.value;
    if (value === (session.note || "")) return;
    try {
      await apiSend("PATCH", `/api/sessions/${session.id}`, { note: value });
      session.note = value;
      // 詳細modalを開いたままなら、そちらの入力欄とも食い違わせない。
      if (currentSessionId === session.id) {
        document.getElementById("note-input").value = value;
      }
    } catch (err) {
      input.value = session.note || "";
      showError(err);
    }
  });
  td.appendChild(input);
  return td;
}

// ---- detail modal ----
async function showDetail(sessionId, fromHistory) {
  let data;
  try {
    data = await apiSend("GET", `/api/sessions/${sessionId}`);
  } catch (err) {
    showToast(`Session詳細を取得できませんでした。\n${errorDetailText(err)}`, "error");
    return;
  }
  const session = data.session;
  const wasClosed = currentSessionId === null;
  currentSessionId = sessionId;
  currentSessionUid = session.unique_id;
  // 開いている詳細をURLに出す。?session= のdeep linkは元々あるのに、画面内で
  // 開いたときだけURLが動かず、戻るButtonも共有もbookmarkも効かなかった。
  // 履歴操作/起動時の復元はURLが既に正しいので、積まずに置き換えるだけにする。
  syncDetailUrl(sessionId, wasClosed && !fromHistory);

  document.getElementById("detail-title").textContent =
    `Session #${sessionNo(session.id)} — @${session.unique_id} (${fmtDateTime(session.started_at)})`;
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
  const detailModal = document.getElementById("detail-modal");
  detailModal.classList.remove("hidden");
  focusModalOpen(detailModal, document.getElementById("detail-close"));
  loadCollabs(sessionId);
}

// ---- コラボ(非BattleのLinkMic)区間 ----
// 区間は別endpointなので、詳細本体を出したあとに追いかけて描く。
// この一覧が持つのは接続の時間窓だけで、共演者が誰かはDBに無い。
async function loadCollabs(sessionId) {
  const empty = document.getElementById("collab-empty");
  const summary = document.getElementById("collab-summary");
  summary.textContent = "";
  renderTableRows("collab-rows", "collab-empty", [], () => [], []);
  setListState(empty, "loading");
  let data;
  try {
    data = await apiSend("GET", `/api/sessions/${sessionId}/collabs`);
  } catch (err) {
    // 別のSessionへ切り替わっていたら、そちらの表示を古い応答で上書きしない。
    if (currentSessionId !== sessionId) return;
    setListState(empty, "failed", err);
    return;
  }
  if (currentSessionId !== sessionId) return;
  const collabs = data.collabs || [];
  renderTableRows(
    "collab-rows",
    "collab-empty",
    collabs,
    (win, rank) => [
      String(rank),
      fmtClock(win.start),
      // 終端が無い窓は収集中に開いたまま。空欄にすると記録漏れと区別できない。
      win.end ? fmtClock(win.end) : "接続中",
      win.end ? fmtDuration(win.end - win.start) : "-",
      // guests_maxは記録されていないSessionが多く、0を「0人」として出すと
      // 人数を数えた結果に見えてしまう。値がある場合だけ人数として扱う。
      win.guests_max > 0 ? fmtNum(win.guests_max) : "記録なし",
    ],
    [0, 4],
  );
  if (!collabs.length) {
    setListState(empty, "empty");
    return;
  }
  setListState(empty, "ok");
  summary.textContent = `${fmtNum(collabs.length)} 区間`;
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

function closeDetail(fromPopState) {
  const detailModal = document.getElementById("detail-modal");
  detailModal.classList.add("hidden");
  focusModalClose(detailModal);
  currentSessionId = null;
  currentSessionUid = null;
  // 戻るButton由来の閉じるでpushBackすると履歴が二重に積まれる。
  if (!fromPopState && new URLSearchParams(location.search).get("session")) {
    history.pushState({}, "", location.pathname);
  }
}

// 詳細を開いた/切り替えたときのURL反映。開く操作は履歴を1段積んで戻るButtonで
// 閉じられるようにし、別Sessionへの切り替えは積まずに置き換える。
function syncDetailUrl(sessionId, pushNew) {
  const url = `${location.pathname}?session=${sessionId}`;
  if (pushNew) history.pushState({ session: sessionId }, "", url);
  else history.replaceState({ session: sessionId }, "", url);
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

// jobをqueueへ投入し、完了(または失敗)まで待つ。応答はjob_idだけで、進捗も結果も
// WSのjob_updateで届くため、待受をjob_idで登録してからPromiseを返す。
async function startRecordingJob(rec, prog, path, failMessage) {
  const res = await fetch(`/api/recordings/${rec.id}/${path}`, { method: "POST" });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(typeof payload.detail === "string" ? payload.detail : failMessage);
  }
  setJobProgress(prog, { state: "pending" });
  return new Promise((resolve, reject) => {
    jobWatchers.set(payload.job_id, { prog, resolve, reject, failMessage });
  });
}

// server側jobの状態を、待受中のprogress要素へ反映する。
function applyRecordingJob(job) {
  const watcher = jobWatchers.get(job.job_id);
  if (!watcher) return false;
  if (job.state === "pending" || job.state === "running") {
    setJobProgress(watcher.prog, job);
    return true;
  }
  jobWatchers.delete(job.job_id);
  if (job.state === "completed") watcher.resolve(job);
  else watcher.reject(new Error(job.message || watcher.failMessage));
  return true;
}

// 1録画の焼き込みをserverに依頼し、recordings folderへ出力する。出力先のfile名を返す。
async function outputRecording(rec, prog) {
  const job = await startRecordingJob(rec, prog, "output", "出力に失敗しました。");
  const result = job.result || {};
  const name = result.filename || rec.filename;
  // 同期方式の比較出力(サーバ時刻版)が同時に作られた場合は両file名を知らせる。
  return result.filename_b ? `${name}（比較: ${result.filename_b}）` : name;
}

// 録画単体の出力(録画一覧の操作)。
async function downloadRecording(rec, btn) {
  // 通知許可は完了時の通知にしか使わないため、awaitで待つとプロンプト応答まで
  // spinner表示(btn.replaceWith)に進めず「無反応」に見える。gesture内で要求だけ行い待たない。
  ensureNotifyPermission();
  const prog = makeProgress();
  btn.replaceWith(prog);
  try {
    const name = await outputRecording(rec, prog);
    finishProgress(prog);
    notifyOutputDone(name);
    // done badge(出力済)を反映するため詳細を再描画する。
    if (currentSessionId !== null) showDetail(currentSessionId);
  } catch (err) {
    prog.replaceWith(btn);
    showError(err);
  }
}

// 録画単体の音量正規化(詳細modalの録画一覧の操作)。映像はstream copyで音声だけを作り直し、
// 元のmp4と差し替える(元は_backup/へ退避)。進捗はWS audionorm_progressで届く。
async function audionormRecording(rec, btn) {
  ensureNotifyPermission();
  const prog = makeProgress();
  btn.replaceWith(prog);
  audionormProgress.set(rec.id, (pct, stage) =>
    setProgress(prog, stage || "音量正規化", pct));
  try {
    const job = await startRecordingJob(rec, prog, "audionorm", "音量正規化に失敗しました。");
    finishProgress(prog);
    notifyOutputDone((job.result || {}).filename || rec.filename);
    if (currentSessionId !== null) showDetail(currentSessionId);
  } catch (err) {
    prog.replaceWith(btn);
    showError(err);
  } finally {
    audionormProgress.delete(rec.id);
  }
}

// 録画単体の再mp4化(詳細modalの録画一覧の操作)。元の.tsから録画時と同一のfinalize
// (concat→timing→単一解像度normalize)を再実行する。単一解像度normalizeの再Encode%は
// serverからWSで届く reprocess_progress をprogに反映する。
async function reprocessRecording(rec, btn) {
  ensureNotifyPermission();
  const prog = makeProgress();
  btn.replaceWith(prog);
  // stageはserverが段階名(セグメントを結合中／単一解像度へ変換中…)を載せてくる。
  // 固定文字列で上書きすると、どの段階で待っているのかが分からなくなる。
  reprocessProgress.set(rec.id, (pct, stage) =>
    setProgress(prog, stage || "再mp4化", pct));
  try {
    const job = await startRecordingJob(rec, prog, "reprocess", "再mp4化に失敗しました。");
    finishProgress(prog);
    notifyOutputDone((job.result || {}).filename || rec.filename);
    if (currentSessionId !== null) showDetail(currentSessionId);
  } catch (err) {
    prog.replaceWith(btn);
    showError(err);
  } finally {
    reprocessProgress.delete(rec.id);
  }
}

// Session単位の出力(履歴一覧の操作)。録画を1本ずつ回すloopはserver側のjobで、ここは
// 起動と進捗表示だけを持つ。以前はこのloopがbrowser側にあったため、tabを閉じると残りの
// 録画は起動すらされず、reloadすると完了も失敗も届かなくなっていた。
async function startSessionOutput(session, btn, path, activeMap, failMessage) {
  // 通知許可は完了時の通知にしか使わないため、awaitで待つとプロンプト応答まで
  // spinner表示(btn.replaceWith)に進めず「無反応」に見える。gesture内で要求だけ行い待たない。
  ensureNotifyPermission();
  const prog = makeProgress();
  btn.replaceWith(prog);
  // 再描画でprogが行から切り離されても進捗を保持できるよう登録する。
  activeMap.set(session.id, prog);
  try {
    const res = await fetch(`/api/sessions/${session.id}/${path}`, { method: "POST" });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(typeof payload.detail === "string" ? payload.detail : failMessage);
    }
    // 以降の進捗・完了・失敗はserverのjob(WS job_update)で届く。
  } catch (err) {
    activeMap.delete(session.id);
    prog.replaceWith(btn);
    showError(err);
  }
}

async function outputSession(session, btn) {
  await startSessionOutput(session, btn, "output", activeOutputs, "出力に失敗しました。");
}

// server側job(session_overlay / session_upscale)の状態を行のprogress要素へ反映する。
// WS接続時のsnapshotからも同じ経路で復元されるため、reload後も進捗へ復帰する。
function applyJob(job) {
  // 単体録画のjobを待っている要素があればそちらが優先(詳細modalのbutton位置に出る)。
  if (applyRecordingJob(job)) return;
  const activeMap = job.domain === "session_upscale" ? activeUpOutputs
    : job.domain === "session_overlay" ? activeOutputs
      : null;
  if (!activeMap || job.session_id === null || job.session_id === undefined) return;
  if (job.state === "running" || job.state === "pending") {
    let prog = activeMap.get(job.session_id);
    if (!prog) {
      // このpageがjobを開始していない場合(reload後・別tabからの開始)はここで作る。
      prog = makeProgress();
      activeMap.set(job.session_id, prog);
      renderTable();
    }
    setJobProgress(prog, job);
    return;
  }
  const prog = activeMap.get(job.session_id);
  if (!prog) return;
  activeMap.delete(job.session_id);
  if (job.state === "completed") {
    finishProgress(prog);
    notifyOutputDone(job.message || job.title);
  } else {
    showToast(job.message || "出力に失敗しました。", "error");
  }
  // done badge(出力済)をbackendの最新状態で反映する。
  loadSessions();
}

// 1録画のAI高画質化(Up出力)をserverに依頼する。焼き込みが有効な場合はserver側で
// 先に焼き込みが走り、続いて高画質化が走る(どちらの段階かはjobのstageで届く)。
async function upOutputRecording(rec, prog) {
  const job = await startRecordingJob(rec, prog, "upscale-output", "Up出力に失敗しました。");
  return (job.result || {}).filename || rec.filename;
}

// 録画単体のUp出力(詳細modalの録画一覧の操作)。
async function upDownloadRecording(rec, btn) {
  // 通知許可は完了時の通知にしか使わないため、awaitで待つとプロンプト応答まで
  // spinner表示(btn.replaceWith)に進めず「無反応」に見える。gesture内で要求だけ行い待たない。
  ensureNotifyPermission();
  const prog = makeProgress();
  btn.replaceWith(prog);
  try {
    const name = await upOutputRecording(rec, prog);
    finishProgress(prog);
    notifyOutputDone(name);
    // done badge(Up出力済)を反映するため詳細を再描画する。
    if (currentSessionId !== null) showDetail(currentSessionId);
  } catch (err) {
    prog.replaceWith(btn);
    showError(err);
  }
}

// Session単位のUp出力(履歴一覧の操作)。そのSessionの完了録画をすべて高画質化する。
// 出力と同じくloopの実体はserver側のjob。
async function upOutputSession(session, btn) {
  await startSessionOutput(session, btn, "upscale-output", activeUpOutputs,
    "Up出力に失敗しました。");
}

function recordingActions(rec) {
  const wrap = document.createElement("span");
  wrap.className = "row-actions";
  // 常用する出力系だけ操作列に出し、稀にしか使わない保守・破壊的操作はmenuへ畳む。
  // Buttonを7個並べると操作列が列幅を食い、#やFile名まで折り返して読めなくなる。
  const menuItems = [];
  // 容量整理でmp4だけ消した録画は行が残る。srcを読む操作(出力・Up出力・再mp4化・
  // 新規の文字起こし)は押しても404になるだけなので出さない。ただし保存済みの転写を
  // 「見る」のはsrc不要で、行を残す意味そのものなので消してはならない。
  const hasSource = rec.file_exists !== false;
  const finished = rec.status === "completed" || rec.status === "interrupted";
  if (hasSource && finished) {
    const dl = document.createElement("button");
    dl.className = "btn btn-small";
    // 出力済みでも再出力可能（活性のまま）。ラベルだけ「済」にする。
    dl.textContent = rec.has_output ? "焼き込み出力済" : "焼き込み出力";
    dl.title = "設定でComment/Gift演出が有効な場合、焼き込み済み動画をrecordings folderへ出力します（再Encodeのため時間がかかります）。完了時にブラウザ通知を出します。";
    dl.addEventListener("click", () => downloadRecording(rec, dl));
    wrap.appendChild(dl);

    if (upscaleConfigured) {
      const up = document.createElement("button");
      up.className = "btn btn-small";
      // Up出力済みでも再出力可能（活性のまま）。ラベルだけ「済」にする。
      up.textContent = rec.has_up_output ? "AI高画質済" : "AI高画質";
      up.title = "この録画をローカルAI(超解像model)で高画質化し、.up.mp4としてrecordings folderへ出力します。焼き込みが有効な場合は焼き込み後の動画を高画質化します。GPUでも録画時間の数倍かかります。";
      up.addEventListener("click", () => upDownloadRecording(rec, up));
      wrap.appendChild(up);
    }
  }

  // 保存済みの転写を開くのはDBだけで完結する。動画fileを消した録画でも、転写を読む
  // 手段は残す(それが行を残す理由そのもの)。新規の文字起こしは音声が要るのでsrc必須。
  if (finished && sttConfigured && (hasSource || rec.has_transcript)) {
    const tr = document.createElement("button");
    tr.className = "btn btn-small";
    // 文字起こし済みでも再実行可能（活性のまま）。ラベルだけ「済」にする。
    tr.textContent = rec.has_transcript ? "字幕化済" : "字幕化";
    tr.title = rec.has_transcript && !hasSource
      ? "保存済みの文字起こしを表示します（素材もmp4も残っていないため再実行はできません）。"
      : "この録画の音声をローカルAIで文字起こしします（初回はmodel読み込みで時間がかかります）。結果はキャッシュされます。";
    tr.addEventListener("click", async () => {
      await transcribeOrShow(rec, tr);
      // done badge(文字起こし済)を反映するため詳細を再描画する。
      if (currentSessionId !== null) showDetail(currentSessionId);
    });
    wrap.appendChild(tr);
  }

  if (hasSource && finished) {
    // 再mp4化は進捗をbutton位置に描くためmenuではなく操作列に残す必要があるが、
    // 常用ではないのでmenuへ入れ、押下時はmenuのtoggle Buttonを進捗表示に使う。
    menuItems.push({
      label: "音量正規化",
      title: "この録画の音量を設定の目標値(既定 -14 LUFS)へ揃えます。映像はそのまま複製し、音声だけを作り直して元のmp4と差し替えます(元は_backupへ退避)。配信ごと・場面ごとの音量差を1本ずつ直す手間が要らなくなります。",
      onSelect: () => audionormRecording(rec, wrap.querySelector(".row-menu-toggle")),
    });

    menuItems.push({
      label: "再mp4化",
      title: "保持している元の.tsセグメントから、録画時と同じ処理でmp4を作り直します。配信中に解像度が変わってPlayerがカクつく録画を1解像度へ正しく直せます。元mp4は_backupへ退避します（.tsが残っていない録画は不可）。再Encodeのため時間がかかります。",
      onSelect: () => reprocessRecording(rec, wrap.querySelector(".row-menu-toggle")),
    });

    // 派生物削除は容量を空ける常用操作。menuの奥に畳むと、同じ目的の操作が
    // 配信者画面(一覧から1 click)と履歴(menu経由)で深さが揃わない。派生物が
    // 実在する行にだけ操作列へ直接出す。
    if (rec.has_output || rec.has_up_output) {
      const der = document.createElement("button");
      der.className = "btn btn-small";
      der.textContent = "派生物削除";
      der.title = "この録画の焼き込み(.overlay.mp4)・Up出力(.up.mp4)・renderの中間fileだけを削除します。元の録画は残るため、必要になれば出力し直せます。";
      der.addEventListener("click", () => deleteDerived(rec, () => {
        if (currentSessionId !== null) showDetail(currentSessionId);
      }));
      wrap.appendChild(der);
    }
  }
  menuItems.push({
    label: "削除",
    title: "この録画のfileとDBの記録を削除します。派生物(焼き込み・Up出力)も一緒に消え、取り消せません。録画中は削除できません。",
    danger: true,
    disabled: rec.status === "recording",
    onSelect: async () => {
      const ok = await confirmDialog(
        `録画 ${recName(rec)} を削除しますか？この操作は取り消せません。`,
        { title: "録画の削除", confirmLabel: "削除する" },
      );
      if (!ok) return;
      try {
        await apiSend("DELETE", `/api/recordings/${rec.id}`);
        if (currentSessionId !== null) showDetail(currentSessionId);
      } catch (err) {
        showError(err);
      }
    },
  });
  // 残るのは音量正規化・再mp4化と削除だけ。「その他」では中身が読めないので用途を名乗らせる。
  wrap.appendChild(rowMenu(menuItems,
    { label: "作り直す/消す ⋯", title: "音量正規化・再mp4化・録画の削除" }));
  return wrap;
}

function renderRecordings(recordings) {
  renderTableRows(
    "recording-list",
    "recording-list-empty",
    recordings,
    (rec) => {
      // 尺はserverが実測したduration_secondsだけを出す。ended_at - started_atは壁時計で、
      // 捕捉の停滞ぶんが載る上、再処理でended_atが潰れた録画では数百時間に化ける。
      const dur = rec.duration_seconds > 0 ? fmtDuration(rec.duration_seconds) : "-";
      const gone = rec.file_exists === false;
      // recordings.bytesは録画完了時の値で、fileを消しても残る。そのまま出すと
      // 消えた容量をまだ持っているように読める。
      const mb = gone ? "—" : `${(rec.bytes / 1048576).toFixed(1)} MB`;
      // 保護はmenuへ畳んだためlabelでは分からない。状態列にbadgeで出して一目で分かるようにする。
      const state = document.createElement("span");
      state.className = "rec-state";
      state.append(RECORDING_STATUS[rec.status] || rec.status);
      if (gone) {
        const g = document.createElement("span");
        g.className = "st file-gone";
        g.textContent = "実体なし";
        g.title = "素材(.ts)もmp4も残っていません。文字起こし・検索index・bookmark・解析は残っています。";
        state.appendChild(g);
      }
      // 保護はbadge自体をtoggleにする。状態が見えている場所でそのまま切り替えられる。
      // 収集中の録画は保持policyの対象外なので出さない(menu時代と同じ条件)。
      if (rec.status === "completed" || rec.status === "interrupted") {
        state.appendChild(protectBadge(rec, () => {
          if (currentSessionId !== null) showDetail(currentSessionId);
        }));
      }
      return [
        recTag(rec),
        rec.filename,
        rec.quality || "-",
        state,
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

// 分析結果はserverのai_analysis表へ保存される。詳細を開いたときはGETで保存済みだけを
// 読み(LLMは走らない)、実行はbutton(POST)でのみ行う。「再分析」は入力が同じでも
// 作り直す(refresh=1)。
function renderAiMeta(payload) {
  const meta = document.getElementById("ai-meta");
  if (!payload || !payload.computed_at) {
    meta.textContent = "";
    return;
  }
  meta.textContent = `分析日時: ${fmtDateTime(payload.computed_at)}`
    + ` / model: ${payload.model || "-"}`
    + ` / prompt版: ${payload.prompt_version}`
    + (payload.comment_count ? ` / ${fmtNum(payload.comment_count)}件のCommentを分析` : "");
}

function resetAiResult() {
  const btn = document.getElementById("ai-analyze-btn");
  btn.disabled = !aiConfigured;
  btn.textContent = "分析する";
  btn.classList.remove("hidden");
  document.getElementById("ai-rerun-btn").classList.add("hidden");
  document.getElementById("ai-analyze-status").textContent = aiConfigured
    ? ""
    : "ローカルAIが未設定のため利用できません。";
  document.getElementById("ai-meta").textContent = "";
  const result = document.getElementById("ai-result");
  result.classList.add("hidden");
  result.innerHTML = "";
  loadStoredAiAnalysis();
}

async function loadStoredAiAnalysis() {
  if (currentSessionId === null) return;
  const sessionId = currentSessionId;
  let payload;
  try {
    const res = await fetch(`/api/sessions/${sessionId}/comment-analysis`);
    if (!res.ok) return;
    payload = await res.json();
  } catch (err) {
    return;
  }
  if (currentSessionId !== sessionId || !payload.analysis) return;
  renderAiAnalysis(payload);
  renderAiMeta(payload);
  document.getElementById("ai-analyze-btn").classList.add("hidden");
  const rerun = document.getElementById("ai-rerun-btn");
  rerun.classList.remove("hidden");
  rerun.disabled = !aiConfigured;
  if (payload.error) document.getElementById("ai-analyze-status").textContent = payload.error;
}

async function runAiAnalysis(refresh) {
  if (currentSessionId === null || !aiConfigured) return;
  const sessionId = currentSessionId;
  const btn = document.getElementById("ai-analyze-btn");
  const rerun = document.getElementById("ai-rerun-btn");
  const status = document.getElementById("ai-analyze-status");
  btn.disabled = true;
  rerun.disabled = true;
  status.textContent = "ローカルAIで分析しています（modelにより数十秒かかることがあります）…";
  try {
    const payload = await apiSend(
      "POST", `/api/sessions/${sessionId}/comment-analysis${refresh ? "?refresh=1" : ""}`);
    if (currentSessionId !== sessionId) return;
    renderAiAnalysis(payload);
    renderAiMeta(payload);
    status.textContent = payload.cached
      ? "前回と同じ入力・同じmodelのため、保存済みの結果を表示しました。"
      : `${fmtNum(payload.comment_count)}件のCommentを分析しました。`;
    btn.classList.add("hidden");
    rerun.classList.remove("hidden");
  } catch (err) {
    status.textContent = err.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "分析する";
    rerun.disabled = false;
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
// 現行の時刻map版。transcript側の版がこれと違うと字幕のtimecodeがズレるため警告する。
let sttTimemapVersion = null;
// recording.id → 進捗を反映する関数（WS transcribe_progress で更新）。
const transcribeProgress = new Map();

async function loadSttStatus() {
  try {
    const res = await fetch("/api/stt/status");
    if (!res.ok) return;
    const st = await res.json();
    const prev = sttConfigured;
    sttConfigured = Boolean(st.configured);
    sttTimemapVersion = st.timemap_version === undefined ? null : st.timemap_version;
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
    showError(err);
  } finally {
    transcribeProgress.delete(rec.id);
    btn.disabled = false;
    btn.textContent = orig;
  }
}

// 表示中transcriptのsegment要素と開始秒（動画の再生位置と同期させる）。
let transcriptSegEls = [];
let transcriptActiveIdx = -1;
// 表示中transcriptの録画。再生errorの理由を問い合わせる間の取り違えを防ぐ。
let transcriptRecordingId = null;

function openTranscript(rec, data) {
  const segs = data.segments || [];
  document.getElementById("transcript-title").textContent =
    `録画 ${recName(rec)} 文字起こし（${data.language || "?"} · ${data.model || ""} · ${segs.length}行）`;
  const video = document.getElementById("transcript-video");
  document.getElementById("transcript-video-message").textContent = "";
  transcriptRecordingId = rec.id;
  // 同録画をRange対応endpointで配信。segmentクリックでその時刻へseekできる。
  // 動画fileを消した録画でも転写は開ける。再生できないことはerror時に文言で伝える。
  video.src = `/api/recordings/${rec.id}/play`;
  // 字幕fileの書き出し。timecodeは元録画mp4のmedia軸基準（hintに明記済み）。
  [["transcript-srt", "srt"], ["transcript-vtt", "vtt"], ["transcript-txt", "txt"]]
    .forEach(([id, fmt]) => {
      const a = document.getElementById(id);
      a.href = `/api/recordings/${rec.id}/transcript/export?format=${fmt}`;
    });
  // 時刻mapの版が現行と違うtranscriptは、書き出した字幕が動画とズレる可能性がある。
  // 版が取れていない場合は判定できないので警告を出さない（推測で出さない）。
  const warn = document.getElementById("transcript-warn");
  const stale = sttTimemapVersion !== null && data.timemap_version !== sttTimemapVersion;
  warn.classList.toggle("hidden", !stale);
  if (stale) {
    warn.textContent =
      `この文字起こしは古い時刻map（版 ${data.timemap_version === null || data.timemap_version === undefined ? "なし" : data.timemap_version}` +
      ` / 現行 ${sttTimemapVersion}）で作られています。書き出した字幕の時刻が動画とズレる場合があります。` +
      "正確な時刻が必要な場合は文字起こしをやり直してください。";
  }
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
  const transcriptModal = document.getElementById("transcript-modal");
  transcriptModal.classList.remove("hidden");
  focusModalOpen(transcriptModal, document.getElementById("transcript-close"));
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
  // src除去自体がerrorを飛ばす。先にidを落とし、閉じただけで理由を出しにいかせない。
  transcriptRecordingId = null;
  video.removeAttribute("src");
  video.load();
  const transcriptModal = document.getElementById("transcript-modal");
  transcriptModal.classList.add("hidden");
  focusModalClose(transcriptModal);
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
  const userdelModal = document.getElementById("userdel-modal");
  userdelModal.classList.remove("hidden");
  focusModalOpen(userdelModal, document.getElementById("userdel-close"));
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
  const userdelModal = document.getElementById("userdel-modal");
  userdelModal.classList.add("hidden");
  focusModalClose(userdelModal);
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
  const ok = await confirmDialog(
    `次の${ids.length}名の履歴をすべて削除しますか？この操作は取り消せません。\n\n${names}`,
    { title: "配信者を削除", confirmLabel: "削除する" },
  );
  if (!ok) return;
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

document.getElementById("ai-analyze-btn").addEventListener("click", () => runAiAnalysis(false));
document.getElementById("ai-rerun-btn").addEventListener("click", () => runAiAnalysis(true));
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
[flt.period, flt.status].forEach((el) =>
  el.addEventListener("input", renderTable),
);
flt.sort.addEventListener("input", () => {
  const preset = SESSION_SORT_PRESETS[flt.sort.value];
  // 列headerが足した選択肢を選び直しただけなら、今の並びがそのまま正。
  if (preset) sortState = { ...preset };
  renderTable();
});
bindSortHeaders();

function handleMessage(msg) {
  // output_progress / upscale_progress はjob_updateのstageと同じ内容をrecording単位で
  // 流す既存message。この画面の進捗はjob_updateへ一本化したので、ここでは扱わない。
  if (msg.type === "transcribe_progress") {
    const update = transcribeProgress.get(msg.recording_id);
    if (update) update(msg.pct);
    return;
  }
  if (msg.type === "reprocess_progress") {
    const update = reprocessProgress.get(msg.recording_id);
    if (update) update(msg.pct, msg.stage);
    return;
  }
  if (msg.type === "audionorm_progress") {
    const update = audionormProgress.get(msg.recording_id);
    if (update) update(msg.pct, msg.stage);
    return;
  }
  // WS接続直後に届くserver側job台帳のsnapshot。reload前から動いているSession出力へ
  // この経路で復帰する。
  if (msg.type === "jobs") {
    (msg.data || []).forEach(applyJob);
    return;
  }
  if (msg.type === "job_update") {
    if (msg.job) applyJob(msg.job);
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

// monitors/stateは収集中に高頻度で届く。1件ごとにSession一覧をフル再取得すると重いため、
// ~1sで合体し最大1回/秒程度に抑える(末尾実行でburstを1回にまとめる)。
//
// KPI帯(/api/dashboard)はここから外してある。あれは全sessionの通算集計で、収集中の
// 1秒で動く量は帯の桁に現れない。1秒ごとに引くと、収集の裏で最も重いqueryを最も高い
// 頻度で回すことになる(下の30秒intervalが引き続き更新する)。
let reloadTimer = null;
function scheduleReload() {
  if (reloadTimer) return;
  reloadTimer = setTimeout(() => {
    reloadTimer = null;
    loadSessions();
  }, 1000);
}

detailChart = createTimelineChart(document.getElementById("detail-chart"));
setListState(document.getElementById("session-empty"), "loading");
bindVideoError(
  document.getElementById("transcript-video"),
  () => transcriptRecordingId,
  (text) => { document.getElementById("transcript-video-message").textContent = text; },
);
loadAiStatus();
loadSttStatus();
loadUpscaleStatus();
loadKpi();
// Session一覧を先に読む。詳細modalは表示名を一覧から補うため、一覧が入ってから開く。
loadSessions().then(() => {
  // 横断jump(Ctrl+K)や他画面からの ?session= 指定でその詳細を開く。
  const wanted = Number(new URLSearchParams(location.search).get("session"));
  if (wanted) showDetail(wanted, true);
});
// 戻る/進むでmodalの開閉を追従させる。URLが状態を持つ以上、browserの履歴操作が
// 効かないと「戻ったのに閉じない」ことになる。
window.addEventListener("popstate", () => {
  const wanted = Number(new URLSearchParams(location.search).get("session"));
  if (wanted && wanted !== currentSessionId) showDetail(wanted, true);
  else if (!wanted && currentSessionId !== null) closeDetail(true);
});
connectWS(handleMessage);
setInterval(loadKpi, 30000);
