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

// ---- マージ表示の選択 ----
// checkを付けたSessionを1つの詳細としてまとめて見る。合算はserver側(GROUP BY)でしか
// 行わない — client側で各Sessionの結果を足すと、top100で切られたギフターが落ち、
// 改名したuserが別人に割れる(tictok/store/sessions.py の sessions_summary を参照)。
const mergeSelected = new Set();
// マージ表示中のSession id列(表示していなければnull)。単体詳細のcurrentSessionIdとは
// 排他で、どちらか一方だけがnull以外になる。
let currentMergeIds = null;

// ---- KPI bar ----
function renderKpi(totals, streamerCount, recordingCount) {
  const bar = document.getElementById("kpi-bar");
  const chips = [
    ["総Session", fmtNum(totals.sessions)],
    ["総Gift", fmtNum(totals.gifts)],
    ["総コイン", fmtNum(totals.diamonds)],
    ["総コメント", fmtNum(totals.comments)],
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
      bar.textContent = "集計値を取得できません";
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
  // 消えたSessionを選択に残さない。残すとマージ要求がそのidで404になる。
  const alive = new Set(allSessions.map((s) => s.id));
  mergeSelected.forEach((id) => { if (!alive.has(id)) mergeSelected.delete(id); });
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
  comments: { label: "コメント", dir: "desc", get: (s) => sessionStat(s, "comments") },
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

// 並びは画面を離れても残す。残すのはselectのvalueではなくsortState(列+昇降)。列header
// からの並びはselectの選択肢に無い(SORT_COLUMN_OPTION)ため、selectのvalueを残すと
// header由来の並びだけ復元できない。どちらの操作も同じ1つの値で表す。
const SORT_PREF_KEY = "tictok.history.sort";

let sortState = { ...SESSION_SORT_PRESETS.started_desc };

function persistSort() {
  prefSet(SORT_PREF_KEY, `${sortState.key}:${sortState.dir}`);
}

// 保存値は現存する列と昇降だけ受ける。読めない値のときは既定(markupのstarted_desc)で
// 始める。selectの表示はsyncSortSelectがsortStateから作り直す。
function restoreSort() {
  const stored = prefGet(SORT_PREF_KEY);
  if (!stored) return;
  const [key, dir] = stored.split(":");
  if (!SESSION_SORT_COLUMNS[key] || (dir !== "asc" && dir !== "desc")) return;
  sortState = { key, dir };
  syncSortSelect();
}

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
  persistSort();
  syncSortSelect();
  renderTable();
}

function bindSortHeaders() {
  document.querySelectorAll("#session-table th[data-sort]").forEach((th) => {
    th.tabIndex = 0;
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
// 列は2群に分ける。行を開く「詳細」と本命の「焼き込み出力」は#と配信者の間(lead)、
// 時間のかかる派生出力(AI高画質/字幕化)と削除は数値列の後ろ(rest)。
// 各群の列数は表headerの操作thのcolspanと一致させる。
const ACTION_LEAD_COLUMNS = 2;

function actionRestColumnCount() {
  return 1 + Number(upscaleConfigured) + Number(sttConfigured);
}

function actionColumnCount() {
  return ACTION_LEAD_COLUMNS + actionRestColumnCount();
}

// 返り値は {lead, rest}。行の組み立て(buildSessionRow)と差分更新(patchSessionRow)は
// どちらも lead→rest の順で1本に均すので、群の分け方は1箇所にしか無い。
function actionCells(session) {
  const isActive = activeIds.has(session.id);
  const outputting = activeOutputs.has(session.id);
  const upOutputting = activeUpOutputs.has(session.id);
  const hasVideo = (session.recording_count || 0) > 0;
  const lead = [];
  const rest = [];
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
  lead.push(cell(showBtn));

  // 出力中の行は再描画されても、進行中のprogress要素をそのまま再装着する。
  let outNode;
  if (outputting) {
    outNode = activeOutputs.get(session.id);
  } else {
    const out = document.createElement("button");
    out.className = "btn btn-small";
    // 出力済みでも再出力したいのでButtonは活性のまま、ラベルに ✓ を付ける。
    out.textContent = session.output_done ? "焼き込み ✓" : "焼き込み";
    out.disabled = isActive || !hasVideo;
    out.addEventListener("click", (e) => {
      e.stopPropagation();
      outputSession(session, out);
    });
    outNode = out;
  }
  lead.push(cell(outNode));

  // Up出力(AI高画質化)。ローカルAIのUpscale設定が有効な場合のみ列を出す。
  if (upscaleConfigured) {
    let upNode;
    if (upOutputting) {
      upNode = activeUpOutputs.get(session.id);
    } else {
      const up = document.createElement("button");
      up.className = "btn btn-small";
      // 出力済みでも再出力可能（活性のまま）。ラベルに ✓ を付ける。
      up.textContent = session.up_output_done ? "AI高画質 ✓" : "AI高画質";
      up.disabled = isActive || !hasVideo;
      up.addEventListener("click", (e) => {
        e.stopPropagation();
        upOutputSession(session, up);
      });
      upNode = up;
    }
    rest.push(cell(upNode));
  }

  // 文字起こし(STT有効時のみ列を出す)。複数録画がある場合は結果がRecording単位のため
  // 詳細へ誘導し、単一録画はその場でModalに表示する。
  if (sttConfigured) {
    const tr = document.createElement("button");
    tr.className = "btn btn-small";
    // 文字起こし済みでも再実行可能（活性のまま）。ラベルに ✓ を付ける。
    // 録画が複数ある場合は押すと選択menuが出る。▾でそれを予告する。
    const multi = (session.recording_count || 0) > 1;
    tr.textContent = (session.transcript_done ? "字幕化 ✓" : "字幕化") + (multi ? " ▾" : "");
    tr.disabled = isActive || !hasVideo;
    tr.addEventListener("click", (e) => {
      e.stopPropagation();
      transcribeSession(session, tr);
    });
    rest.push(cell(tr));
  }

  const del = document.createElement("button");
  del.className = "btn btn-small btn-danger";
  del.textContent = "削除";
  del.disabled = isActive || outputting || upOutputting;
  del.addEventListener("click", async (e) => {
    e.stopPropagation();
    const ok = await confirmDialog(
      `Session #${sessionNo(session.id)} (@${session.unique_id}) を削除`,
      { title: "Sessionの削除", confirmLabel: "削除する" },
    );
    if (!ok) return;
    try {
      await apiSend("DELETE", `/api/sessions/${session.id}`);
      mergeSelected.delete(session.id);
      if (currentSessionId === session.id) closeDetail();
      await Promise.all([loadSessions(), loadKpi()]);
    } catch (err) {
      showError(err, `Session #${sessionNo(session.id)} の削除`);
    }
  });
  rest.push(cell(del));

  return { lead, rest };
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
      showToast("録画がありません", null,
        { title: `Session #${sessionNo(session.id)} の文字起こし` });
      return;
    }
    if (recs.length === 1) {
      await transcribeOrShow(recs[0], btn);
      return;
    }
    // 複数録画は「どれを」が決まらない。詳細を開かせてscrollさせ直すのではなく、
    // その場で選ばせる(押した結果が「押せませんでした」になるのを避ける)。
    openMenuAt(btn, recs.map((rec) => ({
      label: `${recName(rec)}${rec.has_transcript ? "（字幕化 ✓）" : ""}`,
      onSelect: () => transcribeOrShow(rec, btn),
    })));
  } catch (err) {
    showError(err, `Session #${sessionNo(session.id)} の文字起こし`);
  } finally {
    btn.disabled = false;
    btn.textContent = orig;
    // done badge(文字起こし済)をbackendの最新状態で反映する。
    loadSessions();
  }
}

// 数値列の並び。全再構築と差分更新が同じ順で同じ値を出すよう、順序をここ1箇所で持つ。
const SESSION_NUM_FIELDS = [
  "diamonds", "comments", "likes_total", "follows", "shares",
  "joins", "battles", "battle_points", "viewers_peak",
];

function sessionDurationText(s) {
  return s.ended_at ? fmtDuration(s.ended_at - s.started_at) : "収集中";
}

function sessionNameCell(s) {
  return userCell(
    {
      unique_id: s.unique_id,
      nickname: s.owner_nickname || s.unique_id,
      avatar: s.owner_avatar || "",
      league: s.league || "",
    },
    { leagueFirst: true },
  );
}

// 配信者cell・操作buttonを作り直すかどうかの判定材料。cellの中身を決める値を漏れなく
// 並べ、1つでも変われば作り直す。差分更新が「変わったのに古いまま」を出さないための、
// この2つのcellにおける唯一の根拠。
function sessionNameSig(s) {
  return [s.unique_id, s.owner_nickname || "", s.owner_avatar || "", s.league || ""].join(" ");
}

function sessionActionSig(s) {
  return [
    s.id, s.unique_id, s.recording_count || 0,
    s.output_done ? 1 : 0, s.up_output_done ? 1 : 0, s.transcript_done ? 1 : 0,
    activeIds.has(s.id) ? 1 : 0,
    activeOutputs.has(s.id) ? 1 : 0,
    activeUpOutputs.has(s.id) ? 1 : 0,
    upscaleConfigured ? 1 : 0, sttConfigured ? 1 : 0,
  ].join(" ");
}

// 描画済みの行。id → 差分更新で触るcellへの参照。並びが変わらない更新(収集中の数値だけが
// 動く1秒ごとのreload)で、行を作り直さずに済ませるために持つ。
let sessionRows = new Map();
// 前回描いた行のidを並び順のまま。これが一致する間は差分更新でよい。
let sessionRowOrder = [];
// 前回描いたときの操作列の数。Up出力・文字起こしの設定が届くと列そのものが増減するので、
// 並びが同じでも作り直す。
let sessionRowColumns = -1;

function buildSessionRow(s) {
  const tr = document.createElement("tr");
  tr.dataset.sessionId = String(s.id);
  // 行を作り直しても開いているSessionの印は残す(renderTableは並びが変わると全行を作り直す)。
  if (currentSessionId === s.id) tr.classList.add("sel");
  // dockは一覧と並んで出ているので、行そのものが詳細への入口になる。Button/入力欄は
  // それぞれstopPropagationしており、ここへは届かない。
  tr.addEventListener("click", () => showDetail(s.id));
  const nameTd = document.createElement("td");
  nameTd.appendChild(sessionNameCell(s));
  const durationTd = textTd(sessionDurationText(s));
  const statusTd = document.createElement("td");
  statusTd.appendChild(statusCell(s));
  const numTds = SESSION_NUM_FIELDS.map((key) => numTd(sessionStat(s, key)));
  const note = noteTd(s);
  const { lead, rest } = actionCells(s);
  const actionTds = [...lead, ...rest];
  const selTd = mergeTd(s);
  [
    selTd, textTd(`#${sessionNo(s.id)}`), ...lead, nameTd, textTd(fmtDateTime(s.started_at)),
    durationTd, statusTd, ...numTds, note, ...rest,
  ].forEach((td) => tr.appendChild(td));
  return {
    tr, nameTd, durationTd, statusTd, numTds, actionTds,
    noteInput: note.querySelector(".note-inline"),
    mergeInput: selTd.querySelector("input"),
    nameSig: sessionNameSig(s), actionSig: sessionActionSig(s),
  };
}

// 行はそのままに、変わった値だけを書き戻す。収集中に動くのは数値・経過時間・状態だけで、
// 行ごと作り直すとMemoの入力途中の値まで巻き添えで消える(1秒ごとに書きかけが飛んでいた)。
function patchSessionRow(record, s) {
  const duration = sessionDurationText(s);
  if (record.durationTd.textContent !== duration) record.durationTd.textContent = duration;
  SESSION_NUM_FIELDS.forEach((key, i) => {
    const text = fmtNum(sessionStat(s, key));
    if (record.numTds[i].textContent !== text) record.numTds[i].textContent = text;
  });
  const nameSig = sessionNameSig(s);
  if (record.nameSig !== nameSig) {
    record.nameTd.replaceChildren(sessionNameCell(s));
    record.nameSig = nameSig;
  }
  // 状態badgeはclassと文言の組み。個別に比べるより作り直す方が食い違わない(1要素)。
  const status = statusCell(s);
  const shown = record.statusTd.firstElementChild;
  if (!shown || shown.className !== status.className || shown.textContent !== status.textContent) {
    record.statusTd.replaceChildren(status);
  }
  // 入力中の欄は上書きしない。打っている最中に値が戻ると、書きかけが消える。
  if (record.noteInput && document.activeElement !== record.noteInput) {
    const note = s.note || "";
    if (record.noteInput.value !== note) record.noteInput.value = note;
  }
  // 選択の正はmergeSelected。行を作り直さない更新でも、選択解除や全選択と食い違わせない。
  if (record.mergeInput) record.mergeInput.checked = mergeSelected.has(s.id);
  const actionSig = sessionActionSig(s);
  if (record.actionSig !== actionSig) {
    const { lead, rest } = actionCells(s);
    const next = [...lead, ...rest];
    record.actionTds.forEach((td, i) => record.tr.replaceChild(next[i], td));
    record.actionTds = next;
    record.actionSig = actionSig;
  }
}

function renderTable() {
  const tbody = document.getElementById("session-rows");
  const rows = filteredSessions();
  syncSortHeaders();
  syncMergeControls(rows);
  // 操作Buttonは1列ずつ独立tdなので、header操作thをその列数だけ横結合して整合させる。
  // 先頭群(詳細/焼き込み出力)は設定に依らず固定なのでmarkupのcolspanのまま。
  const opTh = document.getElementById("op-th");
  const columns = actionColumnCount();
  if (opTh) opTh.colSpan = actionRestColumnCount();
  const emptyEl = document.getElementById("session-empty");
  if (rows.length > 0) setListState(emptyEl, "ok");
  else if (sessionsState === "failed") setListState(emptyEl, "failed", sessionsError);
  else if (sessionsState === "loading") setListState(emptyEl, "loading");
  // 保存が0件なのか、filterに一致しないだけなのかは別の状態。後者を「保存が無い」と
  // 描くと、保存済みSessionを取り違えたことになる。
  else if (allSessions.length > 0)
    setListMessage(emptyEl, "条件に一致しません");
  else setListState(emptyEl, "empty");

  // 並びも列数も変わっていないなら、行はそのまま使って中身だけ入れ替える。収集中は
  // WS更新で1秒ごとにここへ来るので、1行30要素前後の表を作り直し続けると、その間ずっと
  // 生成と破棄に時間を取られる(行が増えるほど比例して重くなる)。
  const order = rows.map((s) => s.id);
  const sameOrder = columns === sessionRowColumns
    && order.length === sessionRowOrder.length
    && order.every((id, i) => id === sessionRowOrder[i]);
  if (sameOrder) {
    rows.forEach((s) => {
      const record = sessionRows.get(s.id);
      if (record) patchSessionRow(record, s);
    });
    return;
  }

  tbody.innerHTML = "";
  sessionRows = new Map();
  sessionRowOrder = order;
  sessionRowColumns = columns;
  // live tbodyへ1行ずつappendすると行数ぶんlayoutが走るので、画面から切り離された
  // fragmentの上で組んでから1回で挿す。
  const fragment = document.createDocumentFragment();
  rows.forEach((s) => {
    const record = buildSessionRow(s);
    sessionRows.set(s.id, record);
    fragment.appendChild(record.tr);
  });
  tbody.appendChild(fragment);
  // 作り直した行はscroll位置を失う。dockで一覧が数行に畳まれている間は、開いている
  // Sessionが帯の外へ出たままになるので連れ戻す。
  if (currentSessionId !== null) markSelectedRow(currentSessionId);
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

// 行頭の選択check。マージ表示の対象を選ぶだけの列で、行clickでの詳細表示とは別の操作
// なのでclickは行へ伝えない。
function mergeTd(session) {
  const sessionId = session.id;
  const td = document.createElement("td");
  td.className = "sel-cell";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = mergeSelected.has(sessionId);
  input.setAttribute("aria-label", `Session #${sessionNo(sessionId)} を選択`);
  input.addEventListener("click", (e) => e.stopPropagation());
  input.addEventListener("change", () => {
    if (input.checked) mergeSelected.add(sessionId);
    else mergeSelected.delete(sessionId);
    syncMergeControls();
  });
  td.appendChild(input);
  return td;
}

// 選択数に応じて操作帯を合わせる。マージは2件以上でしか意味を持たないので1件では押せない。
// rowsは今の絞込結果(renderTableが既に持っているものを渡し、二度並べ替えない)。
function syncMergeControls(rows) {
  const open = document.getElementById("merge-open");
  const clear = document.getElementById("merge-clear");
  const selall = document.getElementById("merge-selall");
  const count = mergeSelected.size;
  open.textContent = count ? `マージ表示 (${count})` : "マージ表示";
  open.disabled = count < 2;
  clear.classList.toggle("hidden", count === 0);
  const visible = rows || filteredSessions();
  const shown = visible.reduce((n, s) => n + (mergeSelected.has(s.id) ? 1 : 0), 0);
  selall.checked = visible.length > 0 && shown === visible.length;
  selall.indeterminate = shown > 0 && shown < visible.length;
}

// Memoは検索対象(filteredSessionsがs.noteを見る)なのに、絞り込んだ結果の一覧では
// 中身が見えず、確認に詳細modal+scrollが要った。その場で読めて、その場で直せるようにする。
function noteTd(session) {
  const sessionId = session.id;
  const td = document.createElement("td");
  td.className = "note-cell";
  const input = document.createElement("input");
  input.type = "text";
  input.className = "note-inline";
  input.value = session.note || "";
  input.placeholder = "—";
  input.setAttribute("aria-label", "Memo");
  input.addEventListener("click", (e) => e.stopPropagation());
  input.addEventListener("change", async () => {
    // 行は再取得を跨いで生き残るので、掴んだ時点のsessionではなく今の一覧から引く。
    // 古い方へ書き戻すと、検索(noteを見る)の対象と画面の値が食い違う。
    const current = allSessions.find((s) => s.id === sessionId);
    if (!current) return;
    const value = input.value;
    if (value === (current.note || "")) return;
    try {
      await apiSend("PATCH", `/api/sessions/${sessionId}`, { note: value });
      current.note = value;
      // 詳細modalを開いたままなら、そちらの入力欄とも食い違わせない。
      if (currentSessionId === sessionId) {
        document.getElementById("note-input").value = value;
      }
    } catch (err) {
      // 入力欄は元の値へ戻している。戻した理由を出さないと、打ち直しが消えたようにしか見えない。
      input.value = current.note || "";
      showError(err, `Session #${sessionNo(sessionId)} のMemo保存`);
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
    showToast(["Session詳細を取得できません", errorDetailText(err)], "error",
      { title: `Session #${sessionNo(sessionId)} の詳細` });
    return;
  }
  const session = data.session;
  const wasClosed = currentSessionId === null && currentMergeIds === null;
  currentSessionId = sessionId;
  currentSessionUid = session.unique_id;
  currentMergeIds = null;
  // Timeline区画はchart更新より前に出す。display:noneのまま更新させると、Chart.jsが
  // 幅0で組んだ状態から描き直す機会を待つことになる(マージ表示から単体へ移る経路)。
  document.getElementById("detail-dock").classList.remove("merged");
  // 開いている詳細をURLに出す。?session= のdeep linkは元々あるのに、画面内で
  // 開いたときだけURLが動かず、戻るButtonも共有もbookmarkも効かなかった。
  // 履歴操作/起動時の復元はURLが既に正しいので、積まずに置き換えるだけにする。
  syncDockUrl(`session=${sessionId}`, wasClosed && !fromHistory);

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
    ["コメント合計", fmtNum(stats.comments)],
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

  renderSummaryTables(data.summary || {});

  renderRecordings(data.recordings || []);
  openDock(false);
  markSelectedRow(sessionId);
  loadCollabs(sessionId);
}

// ---- 詳細のカテゴリ(左の縦pane) ----
// 表示するのは常に1カテゴリだけ。85%の領域を段で分け合って各段に内側scrollerを置くと、
// wheelを始める位置がほぼ内側になり、外側へ手が届かなくなる。「1つの領域にscrollerは
// 1つ、入れ子にするなら外は転がさない」を構造で守るための形(style.cssの.detail-grid参照)。
const DETAIL_CATEGORY_PREF = "tictok.history.detailcat";
const DETAIL_CATEGORIES = ["gift", "battle", "collab", "rec", "memo", "ai", "timeline"];
// マージ表示では出せないカテゴリ。合算できない値をマージの見出しの下に置かないため
// (Timeline=絶対時刻の軸が別日で繋がらない / AI=保存済みの文章は足せない /
//  Memo=どのSessionへ書くか決まらない)。
const MERGED_HIDDEN_CATEGORIES = new Set(["timeline", "ai", "memo"]);
let detailCategory = "gift";

function detailTabs() {
  return Array.from(document.querySelectorAll("#detail-rail .dk-tab"));
}

// 選べるカテゴリか。可否の根拠はMERGED_HIDDEN_CATEGORIESの1箇所だけに置く
// (CSSの見え方から判定すると、畳んだはずのカテゴリを開いたままにできてしまう)。
function detailCategoryAvailable(cat) {
  if (!DETAIL_CATEGORIES.includes(cat)) return false;
  const merged = document.getElementById("detail-dock").classList.contains("merged");
  return !(merged && MERGED_HIDDEN_CATEGORIES.has(cat));
}

function setDetailCategory(cat, remember) {
  if (!detailCategoryAvailable(cat)) cat = "gift";
  detailCategory = cat;
  detailTabs().forEach((tab) => {
    const on = tab.dataset.cat === cat;
    tab.setAttribute("aria-current", on ? "true" : "false");
    tab.classList.toggle("hidden", !detailCategoryAvailable(tab.dataset.cat));
  });
  let shown = null;
  document.querySelectorAll("#detail-dock .dk-pane").forEach((pane) => {
    const on = pane.dataset.cat === cat;
    pane.classList.toggle("on", on);
    if (on) shown = pane;
  });
  resizeChartsIn(shown);
  if (remember !== false) prefSet(DETAIL_CATEGORY_PREF, cat);
}

// display:noneのcanvasは幅0のまま組まれる。Chart.jsのresize観測だけに任せると
// 0×0から戻らないことがあるので、表に出た瞬間に測り直させる(Timelineとscore推移)。
function resizeChartsIn(pane) {
  if (!pane || typeof Chart === "undefined" || typeof Chart.getChart !== "function") return;
  // 表示切替のlayoutをここで確定させてから測り直させる。rAFに逃がしてはならない —
  // 背面tabではrAFが回らず、戻ってきた時にchartが0×0のままになる。
  void pane.offsetHeight;
  pane.querySelectorAll("canvas").forEach((canvas) => {
    const chart = Chart.getChart(canvas);
    if (chart) chart.resize();
  });
}

// カテゴリの中に何件あるかを縦paneへ出す。開かずに中身の有無が分かる。
// 0件も「0」として出す — 空欄だと「まだ読んでいない」と見分けが付かない。
function setRailCount(cat, count) {
  const tab = document.querySelector(`#detail-rail .dk-tab[data-cat="${cat}"] .dk-n`);
  if (tab) tab.textContent = fmtNum(count);
}

// dockを開く。mergedはマージ表示かどうかで、合算できない区画(Session Timeline・
// AIコメント分析・Memo)をその間だけ畳む。
function openDock(merged) {
  const dock = document.getElementById("detail-dock");
  dock.classList.toggle("merged", Boolean(merged));
  dock.classList.remove("hidden");
  // 畳んだカテゴリを開いたままにしない。マージへ移った時は選び直す。
  setDetailCategory(detailCategory, false);
  // 一覧を畳むのはdockが開いている間だけ。閉じている間は一覧が画面いっぱいに戻る。
  document.body.classList.add("detail-docked");
  focusModalOpen(dock, document.getElementById("detail-close"));
}

// ---- マージ表示 ----
// 選択したSessionを1つの詳細として開く。合算はserver側が済ませてあり、ここは並べるだけ。
// Session Timelineは出さない — bucketは絶対時刻を持つので、別日のSessionを1本の軸へ
// 並べても大半が空白になる。平均同接も同じ理由で出さない(階段保持積分をやり直さないと
// 出せない値で、Sessionごとの平均を平均すると長さの違うSessionが同じ重みで混ざる)。
async function showMerged(ids, fromHistory) {
  const list = [...new Set(ids)].filter((id) => Number.isFinite(id) && id > 0).sort((a, b) => a - b);
  if (list.length < 2) {
    showToast("2件以上を選択", "error", { title: "マージ表示" });
    return;
  }
  const query = `ids=${list.join(",")}`;
  let data;
  try {
    data = await apiSend("GET", `/api/sessions/merged?${query}`);
  } catch (err) {
    showToast(["マージ表示を取得できません", errorDetailText(err)], "error",
      { title: `${list.length} Sessionのマージ表示` });
    return;
  }
  const wasClosed = currentSessionId === null && currentMergeIds === null;
  currentSessionId = null;
  currentSessionUid = null;
  currentMergeIds = list;
  syncDockUrl(`merge=${list.join(",")}`, wasClosed && !fromHistory);

  const sessions = data.sessions || [];
  const stats = data.stats || {};
  const handles = [...new Set(sessions.map((s) => `@${s.unique_id}`))];
  const who = handles.length <= 3
    ? handles.join(", ")
    : `${handles.slice(0, 3).join(", ")} ほか${handles.length - 3}人`;
  document.getElementById("detail-title").textContent =
    `${fmtNum(sessions.length)} Session マージ — ${who}`;
  document.getElementById("detail-csv").href = `/api/sessions/merged/export.csv?${query}`;
  document.getElementById("detail-json").href = `/api/sessions/merged/export.json?${query}`;
  renderChips("detail-totals", [
    ["Session数", fmtNum(sessions.length)],
    ["配信者数", fmtNum(handles.length)],
    ["収集時間合計", fmtDuration(stats.duration || 0)],
    ["Gift合計", fmtNum(stats.gifts)],
    ["コイン合計", fmtNum(stats.diamonds)],
    ["コメント合計", fmtNum(stats.comments)],
    ["Like合計", fmtNum(stats.likes_total)],
    // 同時に居た人数は足し算にならない。合算ではなく各Sessionの最大値であることを名乗る。
    ["最大同接(最大のSession)", fmtNum(stats.viewers_peak)],
    ["Battle回数", fmtNum(stats.battles)],
  ]);

  // 自陣はSessionごとに違いうる(配信者を跨いだ選択)。Battleごとにその配信者を引く。
  renderBattles(data.battles || [], (battle) => battle.owner || { unique_id: "", nickname: "" });
  renderSummaryTables(data.summary || {});
  renderCollabRows(data.collabs || []);
  renderRecordings(data.recordings || []);
  openDock(true);
  markSelectedRow(null);
}

// 貢献ranking(UserごとのGift・Gift種類別)。単体のSession詳細もマージ表示も同じ表を
// 使う。合算はserver側のGROUP BYが済ませてあり、ここは並べるだけ
// (client側で足してはならない理由はstorage.sessions_summaryのdocstringにある)。
function renderSummaryTables(summary) {
  // gift_idごとのicon URL。serverが出せるgiftだけが載る(載らないgiftは名前だけで並ぶ)。
  const giftIcons = summary.gift_icons || {};
  setRailCount("gift", (summary.users || []).length);
  renderTableRows(
    "user-ranking",
    "user-ranking-empty",
    summary.users || [],
    (user, rank) => [
      String(rank),
      // GLv/MLvは名前の後ろに付けず独立した列にする。名前の長さで横位置が動くと、
      // 行をまたいでLvを読み比べられない。
      userCell(user, { stackId: true, hideBadges: true }),
      badgeLevelCell(user.gifter_badge, user.gifter_level, "GLv (ギフトレベル/課金グレード)"),
      badgeLevelCell(user.member_badge, user.fans_level, "MLv (メンバーレベル/ファンクラブ)"),
      fmtNum(user.gifts),
      fmtNum(user.diamonds),
      giftItemsNode(user.items, giftIcons),
    ],
    [0, 4, 5],
  );
  renderTableRows(
    "gift-ranking",
    "gift-ranking-empty",
    summary.gifts || [],
    (gift, rank) => [
      String(rank),
      giftNameNode(gift.name, gift.gift_id, giftIcons),
      fmtNum(gift.count),
      fmtNum(gift.diamonds),
    ],
    [0, 2, 3],
  );
}

// 開いているSessionの行に印を付け、畳んだ帯の中へscrollして見せる。dockは一覧を
// 数行まで押し込むので、印だけ付けても選択行が帯の外にあると何も見えない。
function markSelectedRow(sessionId) {
  sessionRows.forEach((record, id) => {
    record.tr.classList.toggle("sel", id === sessionId);
  });
  const record = sessionId === null ? null : sessionRows.get(sessionId);
  if (record) record.tr.scrollIntoView({ block: "nearest" });
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
  renderCollabRows(data.collabs || []);
}

// コラボ区間の表。単体詳細(loadCollabs)とマージ表示(まとめて受け取る)で共用する。
function renderCollabRows(collabs) {
  const empty = document.getElementById("collab-empty");
  setRailCount("collab", collabs.length);
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
  const summary = document.getElementById("collab-summary");
  if (!collabs.length) {
    summary.textContent = "";
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
  setRailCount("battle", battles.length);
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
  const detailDock = document.getElementById("detail-dock");
  detailDock.classList.add("hidden");
  detailDock.classList.remove("merged");
  // マージ中に畳んだカテゴリをそのまま畳んだ状態で残さない。
  setDetailCategory(detailCategory, false);
  document.body.classList.remove("detail-docked");
  focusModalClose(detailDock);
  markSelectedRow(null);
  currentSessionId = null;
  currentSessionUid = null;
  currentMergeIds = null;
  // 戻るButton由来の閉じるでpushBackすると履歴が二重に積まれる。
  const params = new URLSearchParams(location.search);
  if (!fromPopState && (params.get("session") || params.get("merge"))) {
    history.pushState({}, "", location.pathname);
  }
}

// 詳細を開いた/切り替えたときのURL反映。開く操作は履歴を1段積んで戻るButtonで
// 閉じられるようにし、別Sessionへの切り替えは積まずに置き換える。
// queryは "session=12" か "merge=1,2,3"。
function syncDockUrl(query, pushNew) {
  const url = `${location.pathname}?${query}`;
  if (pushNew) history.pushState({ dock: query }, "", url);
  else history.replaceState({ dock: query }, "", url);
}

// URLが指しているものを開く。?merge= を先に見るのは、両方在るときに指定が新しい方
// (最後にsyncDockUrlが書いた方)を選ぶのではなく、常に同じ解釈にするため。
function openDockFromUrl(fromHistory) {
  const params = new URLSearchParams(location.search);
  const merge = params.get("merge");
  if (merge) {
    const ids = merge.split(",").map(Number).filter((n) => Number.isFinite(n) && n > 0);
    if (ids.length >= 2) {
      showMerged(ids, fromHistory);
      return true;
    }
  }
  const wanted = Number(params.get("session"));
  if (wanted) {
    showDetail(wanted, fromHistory);
    return true;
  }
  return false;
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

// labelは終わった操作の名前。行に出る「完了 ✓」は、直後のshowDetail/loadSessionsが
// 操作cellごと差し替えるためAPI往復1回ぶんで消える。数十分待つ処理で、しかも失敗側は
// showError/showToastで必ず残るので、成功だけ残らないと「終わったのか落ちたのか」が
// 画面から読めない。browser通知は許可が要るので、画面内のtoastを唯一の確実な合図にする。
function notifyOutputDone(name, label) {
  const title = `${label || "出力"}が完了しました`;
  showToast(name, null, { title });
  try {
    if ("Notification" in window && Notification.permission === "granted") {
      new Notification(title, { body: name });
    }
  } catch (e) {
    /* 通知不可でも出力自体は完了しているため無視 */
  }
}

// 一覧の操作列に出す進捗。押したButtonと同じcellに収まるよう、名乗るのは短い操作名と%
// だけにする。serverのstageは「(4/6) コメント層を描画中（0:12:34 / 4:39:10）＋ 焼き込み
// 合成中（…）」のような長文で、折り返さない表にそのまま出すと操作列が横へ大きく伸び、
// 一覧の他の列が押し出される。段階の全文と残り時間はtooltipに残し、段階を追う場所は
// Job画面が持つ。
function rowProgress(label) {
  return makeProgress({ compact: true, shortLabel: label });
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
    // 進捗要素を持たない待受(文字起こしはbutton文言へ出す)もあるため、どちらか一方でよい。
    if (watcher.prog) setJobProgress(watcher.prog, job);
    if (watcher.onState) watcher.onState(job);
    return true;
  }
  jobWatchers.delete(job.job_id);
  if (job.state === "completed") watcher.resolve(job);
  // 取り消しは人が止めた正常な終わり方。失敗と同じ文言で出すと、自分で止めたjobが
  // 不具合に見える。
  else if (job.state === "cancelled") watcher.reject(new Error("取り消しました。"));
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
  const prog = rowProgress("焼き込み中");
  btn.replaceWith(prog);
  try {
    const name = await outputRecording(rec, prog);
    finishProgress(prog);
    notifyOutputDone(name, `${recName(rec)} の焼き込み出力`);
    // done badge(出力済)を反映するため詳細を再描画する。
    if (currentSessionId !== null) showDetail(currentSessionId);
  } catch (err) {
    prog.replaceWith(btn);
    showError(err, `${recName(rec)} の出力`);
  }
}

// 録画単体の音量正規化(詳細modalの録画一覧の操作)。映像はstream copyで音声だけを作り直し、
// 元のmp4と差し替える(元は_backup/へ退避)。進捗はWS audionorm_progressで届く。
async function audionormRecording(rec, btn) {
  ensureNotifyPermission();
  const prog = rowProgress("音量正規化中");
  btn.replaceWith(prog);
  audionormProgress.set(rec.id, (pct, stage) =>
    setProgress(prog, stage || "音量正規化", pct));
  try {
    const job = await startRecordingJob(rec, prog, "audionorm", "音量正規化に失敗しました。");
    finishProgress(prog);
    notifyOutputDone((job.result || {}).filename || rec.filename, `${recName(rec)} の音量正規化`);
    if (currentSessionId !== null) showDetail(currentSessionId);
  } catch (err) {
    prog.replaceWith(btn);
    showError(err, `${recName(rec)} の音量正規化`);
  } finally {
    audionormProgress.delete(rec.id);
  }
}

// 録画単体の再mp4化(詳細modalの録画一覧の操作)。元の.tsから録画時と同一のfinalize
// (concat→timing→単一解像度normalize)を再実行する。単一解像度normalizeの再Encode%は
// serverからWSで届く reprocess_progress をprogに反映する。
async function reprocessRecording(rec, btn) {
  ensureNotifyPermission();
  const prog = rowProgress("再mp4化中");
  btn.replaceWith(prog);
  // stageはserverが段階名(セグメントを結合中／単一解像度へ変換中…)を載せてくる。行では
  // 名乗りを短く保つため、段階名はtooltipへ回す(setProgressがshortLabel側を優先する)。
  reprocessProgress.set(rec.id, (pct, stage) =>
    setProgress(prog, stage || "再mp4化", pct));
  try {
    const job = await startRecordingJob(rec, prog, "reprocess", "再mp4化に失敗しました。");
    finishProgress(prog);
    notifyOutputDone((job.result || {}).filename || rec.filename, `${recName(rec)} の再mp4化`);
    if (currentSessionId !== null) showDetail(currentSessionId);
  } catch (err) {
    prog.replaceWith(btn);
    showError(err, `${recName(rec)} の再mp4化`);
  } finally {
    reprocessProgress.delete(rec.id);
  }
}

// Session単位の出力(履歴一覧の操作)。録画を1本ずつ回すloopはserver側のjobで、ここは
// 起動と進捗表示だけを持つ。以前はこのloopがbrowser側にあったため、tabを閉じると残りの
// 録画は起動すらされず、reloadすると完了も失敗も届かなくなっていた。
// labelは操作の名前("出力"/"Up出力")。失敗文言とtoastの見出しの両方をここから作り、
// 二重に持たない。runningは行に出す短い名乗り(「焼き込み中」等)。
async function startSessionOutput(session, btn, path, activeMap, label, running) {
  // 通知許可は完了時の通知にしか使わないため、awaitで待つとプロンプト応答まで
  // spinner表示(btn.replaceWith)に進めず「無反応」に見える。gesture内で要求だけ行い待たない。
  ensureNotifyPermission();
  const prog = rowProgress(running);
  btn.replaceWith(prog);
  // 再描画でprogが行から切り離されても進捗を保持できるよう登録する。
  activeMap.set(session.id, prog);
  try {
    const res = await fetch(`/api/sessions/${session.id}/${path}`, { method: "POST" });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(typeof payload.detail === "string" ? payload.detail : `${label}に失敗しました。`);
    }
    // 以降の進捗・完了・失敗はserverのjob(WS job_update)で届く。
  } catch (err) {
    activeMap.delete(session.id);
    prog.replaceWith(btn);
    showError(err, `Session #${sessionNo(session.id)} の${label}`);
  }
}

async function outputSession(session, btn) {
  await startSessionOutput(session, btn, "output", activeOutputs, "出力", "焼き込み中");
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
      prog = rowProgress(job.domain === "session_upscale" ? "AI高画質中" : "焼き込み中");
      activeMap.set(job.session_id, prog);
      renderTable();
    }
    setJobProgress(prog, job);
    return;
  }
  const prog = activeMap.get(job.session_id);
  const label = job.domain === "session_upscale" ? "Up出力" : "出力";
  // progが無いのは、この画面が進捗を出していないjobが終わったとき(別画面で始めた・
  // 一覧の絞込で行が出ていない)。以前はここで捨てていたので、失敗が誰にも届かなかった。
  if (!prog) {
    if (job.state !== "completed" && job.state !== "cancelled") {
      showToast(job.message || `${label}に失敗しました。`, "error",
        { title: `Session #${sessionNo(job.session_id)} の${label}` });
      loadSessions();
    }
    return;
  }
  activeMap.delete(job.session_id);
  if (job.state === "completed") {
    finishProgress(prog);
    notifyOutputDone(job.message || job.title,
      `Session #${sessionNo(job.session_id)} の${label}`);
  } else {
    // 一覧には複数のSessionが並ぶ。どのSessionのどちらの出力が落ちたのかを名乗らないと、
    // 行のprogressが消えただけになって対象が辿れない。
    showToast(job.message || `${label}に失敗しました。`, "error",
      { title: `Session #${sessionNo(job.session_id)} の${label}` });
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
  const prog = rowProgress("AI高画質中");
  btn.replaceWith(prog);
  try {
    const name = await upOutputRecording(rec, prog);
    finishProgress(prog);
    notifyOutputDone(name, `${recName(rec)} のUp出力`);
    // done badge(Up出力済)を反映するため詳細を再描画する。
    if (currentSessionId !== null) showDetail(currentSessionId);
  } catch (err) {
    prog.replaceWith(btn);
    showError(err, `${recName(rec)} のUp出力`);
  }
}

// Session単位のUp出力(履歴一覧の操作)。そのSessionの完了録画をすべて高画質化する。
// 出力と同じくloopの実体はserver側のjob。
async function upOutputSession(session, btn) {
  await startSessionOutput(session, btn, "upscale-output", activeUpOutputs, "Up出力", "AI高画質中");
}

function recordingActions(rec) {
  const wrap = document.createElement("span");
  wrap.className = "row-actions";
  // 常用する出力系だけ操作列に出し、稀にしか使わない保守・破壊的操作はmenuへ畳む。
  // Buttonを7個並べると操作列が列幅を食い、#やFile名まで折り返して読めなくなる。
  const menuItems = [];
  // 容量整理でmp4だけ消した録画は行が残る。srcを読む操作(出力・Up出力・再mp4化・
  // 新規の文字起こし)は押しても404になるだけなので出さない。ただし保存済みの文字起こしを
  // 「見る」のはsrc不要で、行を残す意味そのものなので消してはならない。
  const hasSource = rec.file_exists !== false;
  const finished = rec.status === "completed" || rec.status === "interrupted";
  if (hasSource && finished) {
    const dl = document.createElement("button");
    dl.className = "btn btn-small";
    // 出力済みでも再出力可能（活性のまま）。ラベルに ✓ を付ける。
    dl.textContent = rec.has_output ? "焼き込み ✓" : "焼き込み";
    dl.addEventListener("click", () => downloadRecording(rec, dl));
    wrap.appendChild(dl);

    if (upscaleConfigured) {
      const up = document.createElement("button");
      up.className = "btn btn-small";
      // Up出力済みでも再出力可能（活性のまま）。ラベルに ✓ を付ける。
      up.textContent = rec.has_up_output ? "AI高画質 ✓" : "AI高画質";
      up.addEventListener("click", () => upDownloadRecording(rec, up));
      wrap.appendChild(up);
    }
  }

  // 保存済みの文字起こしを開くのはDBだけで完結する。動画fileを消した録画でも、文字起こしを読む
  // 手段は残す(それが行を残す理由そのもの)。新規の文字起こしは音声が要るのでsrc必須。
  if (finished && sttConfigured && (hasSource || rec.has_transcript)) {
    const tr = document.createElement("button");
    tr.className = "btn btn-small";
    // 文字起こし済みでも再実行可能（活性のまま）。ラベルに ✓ を付ける。
    tr.textContent = rec.has_transcript ? "字幕化 ✓" : "字幕化";
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
      onSelect: () => audionormRecording(rec, wrap.querySelector(".row-menu-toggle")),
    });

    menuItems.push({
      label: "再mp4化",
      onSelect: () => reprocessRecording(rec, wrap.querySelector(".row-menu-toggle")),
    });

    // 派生物削除は容量を空ける常用操作。menuの奥に畳むと、同じ目的の操作が
    // 配信者画面(一覧から1 click)と履歴(menu経由)で深さが揃わない。派生物が
    // 実在する行にだけ操作列へ直接出す。
    if (rec.has_output || rec.has_up_output) {
      const der = document.createElement("button");
      der.className = "btn btn-small";
      der.textContent = "派生物削除";
      der.addEventListener("click", () => deleteDerived(rec, () => {
        if (currentSessionId !== null) showDetail(currentSessionId);
      }));
      wrap.appendChild(der);
    }
  }
  menuItems.push({
    label: "削除",
    danger: true,
    disabled: rec.status === "recording",
    onSelect: async () => {
      const ok = await confirmDialog(
        `録画 ${recName(rec)} を削除`,
        { title: "録画の削除", confirmLabel: "削除する" },
      );
      if (!ok) return;
      try {
        await apiSend("DELETE", `/api/recordings/${rec.id}`);
        if (currentSessionId !== null) showDetail(currentSessionId);
      } catch (err) {
        showError(err, `${recName(rec)} の削除`);
      }
    },
  });
  // 残るのは音量正規化・再mp4化と削除だけ。「その他」では中身が読めないので用途を名乗らせる。
  // rowMenuはtitle未指定だと既定文を入れるので、付いたものを外す。
  const menuToggle = rowMenu(menuItems, { label: "作り直す/消す ⋯" });
  menuToggle.removeAttribute("title");
  wrap.appendChild(menuToggle);
  return wrap;
}

function renderRecordings(recordings) {
  setRailCount("rec", recordings.length);
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
    else if (st.enabled) note.textContent = "model未設定";
    else note.textContent = "AI無効";
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
  meta.textContent = `${fmtDateTime(payload.computed_at)}`
    + ` / ${payload.model || "-"}`
    + ` / prompt版 ${payload.prompt_version}`
    + (payload.comment_count ? ` / ${fmtNum(payload.comment_count)}件` : "");
}

function resetAiResult() {
  const btn = document.getElementById("ai-analyze-btn");
  btn.disabled = !aiConfigured;
  btn.textContent = "分析する";
  btn.classList.remove("hidden");
  document.getElementById("ai-rerun-btn").classList.add("hidden");
  document.getElementById("ai-analyze-status").textContent = aiConfigured ? "" : "AI未設定";
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
  status.textContent = "分析中…";
  try {
    const payload = await apiSend(
      "POST", `/api/sessions/${sessionId}/comment-analysis${refresh ? "?refresh=1" : ""}`);
    if (currentSessionId !== sessionId) return;
    renderAiAnalysis(payload);
    renderAiMeta(payload);
    status.textContent = payload.cached
      ? "保存済みの結果"
      : `${fmtNum(payload.comment_count)}件を分析`;
    btn.classList.add("hidden");
    rerun.classList.remove("hidden");
  } catch (err) {
    // 数十秒待つ操作で、待つ間にmodalの別の場所を読んでいると実行中文言の差し替えは
    // 目に入らない。成功は結果bodyが現れて明白なので、失敗だけtoastで拾う。
    status.textContent = err.message;
    showError(err, "AIコメント分析");
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

// 文字起こしをqueueへ投入し、完了まで待つ。進捗要素の代わりにbutton文言へ出すため、
// 待受にprogは持たせない(%はWSのtranscribe_progressが、待機中の順番はjob_updateが書く)。
function startTranscribeJob(rec, btn, failMessage) {
  return new Promise((resolve, reject) => {
    fetch(`/api/recordings/${rec.id}/transcribe`, { method: "POST" })
      .then(async (res) => {
        const payload = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(typeof payload.detail === "string" ? payload.detail : failMessage);
        }
        // job_idが無いと完了を待つ相手が居ない。待受を張らずに黙って待つと、押した側が
        // 永久に「待機中…」のまま止まる。
        if (!payload.job_id) throw new Error(failMessage);
        jobWatchers.set(payload.job_id, {
          resolve, reject, failMessage,
          // GPUを1本ずつ直列に使うので、投入直後は前のjobの後ろで待つ。「0%」のまま
          // 動かないと止まって見えるため、待機中は順番を名乗る。
          onState: (job) => {
            if (job.state !== "pending") return;
            // 文言は列幅ぶんに収める。Buttonの幅は表が全行で揃えるので、実行中だけ長い
            // 文言に差し替えると操作列が横へ広がって一覧が押し出される。
            btn.textContent = job.queue_position
              ? `待機 ${job.queue_position}番目`
              : "待機中";
          },
        });
      })
      .catch(reject);
  });
}

// 文字起こし: 既にあれば表示、無ければqueueへ積んで完了を待ってから表示。実処理はJob台帳
// (種別「文字起こし」)で走るので、Job画面から取り消し・再実行ができる。
async function transcribeOrShow(rec, btn) {
  const orig = btn.textContent;
  const failMessage = "文字起こしに失敗しました。";
  btn.disabled = true;
  try {
    let res = await fetch(`/api/recordings/${rec.id}/transcript`);
    if (res.status === 404) {
      btn.textContent = "待機中";
      transcribeProgress.set(rec.id, (pct) => {
        btn.textContent = `字幕化 ${pct}%`;
      });
      await startTranscribeJob(rec, btn, failMessage);
      // 文字起こしの保存はjobの完了より前に終わっている(worker側で保存→検索index→完了)。
      res = await fetch(`/api/recordings/${rec.id}/transcript`);
    }
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(typeof payload.detail === "string" ? payload.detail : failMessage);
    }
    openTranscript(rec, payload);
  } catch (err) {
    showError(err, `${recName(rec)} の文字起こし`);
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
  // 動画fileを消した録画でも文字起こしは開ける。再生できないことはerror時に文言で伝える。
  video.src = `/api/recordings/${rec.id}/play`;
  // 字幕fileの書き出し。timecodeは元録画mp4のmedia軸基準（hintに明記済み）。
  [["transcript-srt", "srt"], ["transcript-vtt", "vtt"], ["transcript-txt", "txt"]]
    .forEach(([id, fmt]) => {
      const a = document.getElementById(id);
      a.href = `/api/recordings/${rec.id}/transcript/export?format=${fmt}`;
    });
  // 書き出した字幕が使い物にならない理由は2つあり、どちらも再文字起こしでしか直らない。
  // 判定できない材料（版が取れていない等）では警告を出さない（推測で出さない）。
  const warn = document.getElementById("transcript-warn");
  const reasons = [];
  if (sttTimemapVersion !== null && data.timemap_version !== sttTimemapVersion) {
    reasons.push(
      `古い時刻map（版 ${data.timemap_version === null || data.timemap_version === undefined ? "なし" : data.timemap_version}` +
      ` / 現行 ${sttTimemapVersion}）`);
  }
  if (data.word_times === 0) {
    // 語ごとの時刻が無いとcueを語の端で締められず、segmentの終端が次のsegmentの開始まで
    // 伸びる。実測でSRTが録画の97.7%を覆う（実際の発話は約30%）ため、無音の上に関係のない
    // 字幕が出続ける。
    reasons.push("語ごとの時刻なし（無音にも字幕）");
  }
  warn.classList.toggle("hidden", reasons.length === 0);
  if (reasons.length) warn.textContent = reasons.join(" / ");
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
  const empty = document.getElementById("userdel-empty");
  try {
    const res = await fetch("/api/streamers");
    if (!res.ok) throw new Error("配信者一覧を取得できません");
    userdelStreamers = (await res.json()).streamers || [];
    setListState(empty, "empty");
  } catch (err) {
    // 取得できなかったものを「配信者がいません。」と描くと、消す相手が居ないという
    // 別の事実の提示になる。この画面の他の一覧と同じ3状態へ揃える。
    userdelStreamers = [];
    setListState(empty, "failed", err);
    document.getElementById("userdel-status").textContent = err.message;
    showError(err, "配信者一覧の取得");
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
  run.textContent = userdelSelected.size > 0 ? `${userdelSelected.size}名を削除` : "削除";
}

async function runUserDelete() {
  const ids = [...userdelSelected];
  if (!ids.length) return;
  const names = userdelStreamers
    .filter((s) => userdelSelected.has(s.unique_id))
    .map((s) => `@${s.unique_id}`)
    .join("\n");
  const ok = await confirmDialog(
    `次の${ids.length}名の履歴を削除\n\n${names}`,
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
    // modalが閉じる見た目は中止と同じなので、消えた量はtoastで名乗る。取り消せない削除で
    // 「何名ぶん・何Session消えたか」がどこにも残らないと、対象を間違えても気付けない。
    showToast(
      `${fmtNum(ids.length)}名を削除（Session ${fmtNum(result.deleted_sessions ?? 0)}件）`,
      null, { title: "配信者を削除" });
  } catch (err) {
    status.textContent = err.message;
    showError(err, "配信者の削除");
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
    // 一覧の行内編集(noteTd)は既にshowErrorで名乗る。同じMemo保存が経路によって
    // 失敗の出方を変えると、modal側だけ「押したのに何も起きない」に見える。
    status.textContent = err.message;
    showError(err, `Session #${currentSessionId} のMemo保存`);
  }
});

document.getElementById("ai-analyze-btn").addEventListener("click", () => runAiAnalysis(false));
document.getElementById("ai-rerun-btn").addEventListener("click", () => runAiAnalysis(true));
document.getElementById("transcript-close").addEventListener("click", closeTranscript);
document.getElementById("transcript-modal").addEventListener("click", (e) => {
  if (e.target.id === "transcript-modal") closeTranscript();
});
document.getElementById("transcript-video").addEventListener("timeupdate", highlightActiveSegment);
// closeDetailの引数はfromPopState。listenerへ直接渡すとMouseEventがそこへ入り、
// 「戻る由来」と誤認してURLの?session=を消し損ねる。
document.getElementById("detail-close").addEventListener("click", () => closeDetail());
document.getElementById("detail-rail").addEventListener("click", (e) => {
  const tab = e.target.closest(".dk-tab");
  if (tab) setDetailCategory(tab.dataset.cat);
});
// 前回見ていたカテゴリで開く。Sessionを渡り歩くたびにGiftへ戻ると、同じ区画を
// 見比べる操作が毎回2手になる。
setDetailCategory(prefGet(DETAIL_CATEGORY_PREF) || "gift", false);
document.getElementById("export-csv").addEventListener("click", exportVisibleCsv);
document.getElementById("merge-open").addEventListener("click", () => showMerged([...mergeSelected]));
document.getElementById("merge-clear").addEventListener("click", () => {
  mergeSelected.clear();
  renderTable();
});
document.getElementById("merge-selall").addEventListener("change", (e) => {
  // 対象は「表示中」だけ。絞込で見えていないSessionまで巻き込むと、押した本人には
  // 何を選んだのか分からない選択になる(配信者削除の全選択と同じ扱い)。
  const visible = filteredSessions();
  if (e.target.checked) visible.forEach((s) => mergeSelected.add(s.id));
  else visible.forEach((s) => mergeSelected.delete(s.id));
  renderTable();
});
// 検索は1キーストロークごとにtbody全再構築が走るため~200msデバウンスする。
// period/status/sortは離散的な選択のため即時反映でよい。
// 検索語は1回限りの入力なので残さない(period/status/並びは次に開いた時も同じ見え方で始める)。
let searchTimer = null;
flt.search.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(renderTable, 200);
});
bindPref(flt.period, "tictok.history.period", renderTable);
bindPref(flt.status, "tictok.history.status", renderTable);
flt.sort.addEventListener("input", () => {
  const preset = SESSION_SORT_PRESETS[flt.sort.value];
  // 列headerが足した選択肢を選び直しただけなら、今の並びがそのまま正。
  if (preset) sortState = { ...preset };
  persistSort();
  renderTable();
});
// 並びの復元は最初のrenderTableより前。後にすると復元前の並びで一度描いてしまう。
restoreSort();
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
    // 画面を開いた直後の1通目は、下のloadSessions()と同じ内容を運んでくるだけなので
    // 取り直さない(印はcommon.jsのconnectWSが付ける)。
    if (!msg.initial) scheduleReload();
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
  // 横断jump(Ctrl+K)や他画面からの ?session= / ?merge= 指定でそれを開く。
  openDockFromUrl(true);
});
// 戻る/進むでmodalの開閉を追従させる。URLが状態を持つ以上、browserの履歴操作が
// 効かないと「戻ったのに閉じない」ことになる。
window.addEventListener("popstate", () => {
  const params = new URLSearchParams(location.search);
  const merge = params.get("merge");
  const wanted = Number(params.get("session"));
  if (merge) {
    if (merge !== (currentMergeIds || []).join(",")) openDockFromUrl(true);
  } else if (wanted) {
    if (wanted !== currentSessionId) showDetail(wanted, true);
  } else if (currentSessionId !== null || currentMergeIds !== null) {
    closeDetail(true);
  }
});
connectWS(handleMessage);
// KPI帯は全sessionの通算集計で、warmでも毎回0.35秒かかる。開きっぱなしにする画面なので、
// 見えていない間は引かない(pollWhileVisibleが表へ戻った時にまとめて1回引き直す)。
pollWhileVisible(loadKpi, 30000);
