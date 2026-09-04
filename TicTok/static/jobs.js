"use strict";

// Job画面: 実行中・待機中・過去のjobを1画面に並べ、取り消しと再実行の導線を持つ。
// 運用log(ops_events)は「もう起きたこと」を遡る画面で、こちらは「これから終わること」を
// 待つ画面。更新のされ方(行の書き換え vs 追記)も見る目的も違うので、pageを分けている。
// 一覧の出所はHTTPの /api/jobs で、filter(状態・種別)はserverが台帳全体へ当てる。実行中の
// 行はWSのjob_updateがその場で書き換えるが、WSのsnapshot(type=jobs)はfilterを通っていない
// ので、届いたら置き換えではなく同じfilterで取り直す。

const JOB_STATE_LABELS = {
  pending: { text: "待機中", cls: "badge-idle" },
  running: { text: "実行中", cls: "badge-connected" },
  completed: { text: "完了", cls: "badge-idle" },
  failed: { text: "失敗", cls: "badge-error" },
  cancelled: { text: "取り消し", cls: "badge-idle" },
  // 作る物が無くて何も出力しなかった終わり方。失敗ではないので赤badgeにしない。
  skipped: { text: "対象なし", cls: "badge-idle" },
  interrupted: { text: "中断", cls: "badge-error" },
};

// 種別(domain)→日本語label。Server側(core/ops_labels.py)が唯一の出所で、画面は受け取って
// 引くだけにする。同じ訳語をここにも置くと、運用logのmessage文と種別labelが必ずずれる
// (実際「Up出力」と「AI高画質化」、「焼き込み」と「コメント焼き込み」がずれていた)。
let kindLabels = {};

// 取り消し・再実行が効くdomain。これもserver(api/media_jobs.QUEUED_JOB_DOMAINS)が唯一の
// 出所。ここに同じ一覧を書いていた頃は、台帳へ種別が増えても画面が黙って古いままで、
// 文字起こし(stt)・笑い声分析(laugh)のjobだけbuttonが出ず取り消せなかった。
// 取得前は空 = buttonを出さない(押せない物を押せるように見せるより、出ない方が実態に近い)。
let queuedKinds = new Set();

// 状態filterの値 → 対象のstate。server側の同じ表(record/media_queue.STATE_FILTERS)が台帳を
// 絞り、ここはWSで届いた行に同じ判定を当てるために持つ(訳語ではなくstate keyなので二重に
// 持っても語がずれることはない)。
const ACTIVE_STATES = ["pending", "running"];
const FAILED_STATES = ["failed", "interrupted"];

// 1回に読み込む台帳の行数。これを超える分はserverが切るので、切れたことを画面が名乗る。
const JOB_PAGE_LIMIT = 200;

let jobs = [];
// filterに一致する台帳の全行数と、実際に読み込んだ上限。total > limit のとき、この一覧は
// 「全部」ではない。
let jobTotal = 0;
let jobLimit = JOB_PAGE_LIMIT;
// 列clickでの並べ替え。nullの間は既定の並び(実行中→待機中→その他、以降時刻降順)。
let sortState = null;
// ?kind= で来た種別。種別の選択肢はserverの応答から作るため、選択肢が揃うまで預かる。
let pendingKind = "";
// ?job= で名指しされたjob。台帳から直接引かせるためserverへ渡す — 指されたjobが古くて
// 直近200件の外に居ても着地できるようにする。絞込入力を人が触った時点で外す。
let pinnedJob = "";
// 明細を開いているgroup_id。groupの合成行はjob_idにgroup_idがそのまま入るため、
// 「group_idを持ち、かつjob_idと一致しない」行がsession一括の明細にあたる。
const expandedGroups = new Set();
// 段階の経過を開いているjob_id。終わったjobの進捗列は「完了 ✓」しか出せず、どの段階に
// 何秒かかったか・どこで落ちたかを辿る先が無かった。既定で畳むのは、一覧の主目的が
// 「いま何が動いているか」で、全行を段階listで埋めるとその見通しが失われるため。
const expandedStages = new Set();
// 実行中のjobは既定で開いているので、「畳んだ」の方を覚える。
const collapsedStages = new Set();
let gpu = null;
// 文字起こしの台帳(kind=stt)をstate別に数えた値。この一覧はlimitで切れるので、件数だけは
// 全体を名乗れるようにする(GPU現況と一覧の食い違いを説明するために読む)。
let stt = null;
// 一覧が空に見えるときの理由。取得前(loading)・0件(ok)・取得失敗(failed)を取り違えると、
// 落ちているだけのserverを「jobが無い」と読み違える。
let loadState = "loading";
let loadError = null;

function jobKey(job) {
  return job.job_id;
}

function upsertJob(job) {
  const index = jobs.findIndex((item) => jobKey(item) === jobKey(job));
  if (index >= 0) jobs[index] = job;
  else jobs.push(job);
  scheduleRender();
}

// job_updateは1件ずつ届くが、queueは1つのjobが動き出すたび待機列の順番を全件配り直すため、
// 数十通が一息に来る。1通ごとにrender()すると同じ表を数十回組み直すことになるので、
// 次の描画frameまで畳んで1回にする。
let renderScheduled = false;
function scheduleRender() {
  if (renderScheduled) return;
  renderScheduled = true;
  requestAnimationFrame(() => {
    renderScheduled = false;
    render();
  });
}

// 現在のfilter条件。行ごとにDOMを引き直さないよう、判定の前に1度だけ読む。
function currentFilter() {
  return {
    state: document.getElementById("job-flt-state").value,
    // 種別の選択肢はserverの応答から作るので、初回は ?kind= がまだselectに入っていない。
    // requestには先に載せる(選択肢が揃うのを待って読み直すと2往復になる)。
    kind: pendingKind || document.getElementById("job-flt-kind").value,
    text: document.getElementById("job-flt-text").value.trim().toLowerCase(),
  };
}

// 絞込入力が当たる文字列。画面に出ている「対象」に加えてjob idも見るのは、運用logの
// 「このjobを見る」が ?job=<job_id> でここへ飛ばしてくるため。
function jobSearchText(job) {
  return [jobTargetText(job), job.title, job.job_id, job.group_id]
    .filter(Boolean).join(" ").toLowerCase();
}

function matchesFilter(job, filter) {
  if (filter.state === "active" && !ACTIVE_STATES.includes(job.state)) return false;
  if (filter.state === "failed" && !FAILED_STATES.includes(job.state)) return false;
  if (filter.kind !== "all" && job.domain !== filter.kind) return false;
  if (filter.text && !jobSearchText(job).includes(filter.text)) return false;
  return true;
}

function isGroupRow(job) {
  return !!job.group_id && job.group_id === job.job_id;
}

function isGroupMember(job) {
  return !!job.group_id && job.group_id !== job.job_id;
}

// 表示順: group行の直後に、開いているgroupの明細だけを差し込む。
// filterでgroup行が落ちたときは明細を畳む相手がいないので、その明細は単独行として出す
// (畳んだまま隠すと、filterに一致したjobが一覧から消える)。
function visibleRows() {
  const filter = currentFilter();
  const matched = sortJobs(jobs.filter((job) => matchesFilter(job, filter)));
  const groupIds = new Set(matched.filter(isGroupRow).map((job) => job.job_id));
  const members = new Map();
  const tops = [];
  matched.forEach((job) => {
    if (isGroupMember(job) && groupIds.has(job.group_id)) {
      if (!members.has(job.group_id)) members.set(job.group_id, []);
      members.get(job.group_id).push(job);
      return;
    }
    tops.push(job);
  });
  const rows = [];
  tops.forEach((job) => {
    const list = (isGroupRow(job) && members.get(job.job_id)) || [];
    rows.push({ job, members: list.length });
    if (expandedGroups.has(job.job_id)) {
      list.forEach((member) => rows.push({ job: member, members: 0, sub: true }));
    }
  });
  return rows;
}

// 列clickでの並べ替え。値は画面に出ている物と同じ物を使う(表示は「復帰待ち」なのに
// 並びは"pending"、のように見えている語と順序の根拠が食い違わないようにする)。
const JOB_SORT_COLUMNS = {
  state: { dir: "asc", value: (job) => stateText(job) },
  kind: { dir: "asc", value: (job) => kindText(job) },
  target: { dir: "asc", value: (job) => jobTargetText(job) },
  pct: { dir: "desc", value: (job) => job.pct || 0 },
  queued: { dir: "desc", value: (job) => job.queued_at || job.started_at || 0 },
  // 待機中など未実行のjobは所要が「無い」ので、0秒のjobより後ろへ置く(待機の長さを
  // ここへ混ぜると、順番待ちが長いだけのjobが最も時間を食ったjobとして先頭に来る)。
  elapsed: { dir: "desc", value: (job) => (elapsedSeconds(job) === null ? -1 : elapsedSeconds(job)) },
  result: { dir: "asc", value: (job) => resultText(job) },
};

function jobRecency(job) {
  return job.finished_at || job.started_at || job.queued_at || 0;
}

function sortJobs(list) {
  const rank = (job) => (job.state === "running" ? 0 : job.state === "pending" ? 1 : 2);
  const column = sortState && JOB_SORT_COLUMNS[sortState.key];
  return list.slice().sort((a, b) => {
    if (column) {
      const av = column.value(a);
      const bv = column.value(b);
      let diff = typeof av === "number" && typeof bv === "number"
        ? av - bv
        : String(av).localeCompare(String(bv), "ja");
      if (sortState.dir === "desc") diff = -diff;
      // 同値どうしは既定と同じく新しい順。行が毎回入れ替わると読み直せない。
      return diff || jobRecency(b) - jobRecency(a);
    }
    if (rank(a) !== rank(b)) return rank(a) - rank(b);
    return jobRecency(b) - jobRecency(a);
  });
}

// 押すたび 降順 → 昇順 → 既定 と回す。既定(実行中→待機中→その他)はこの画面の主目的
// なので、列で並べ替えた後に戻す手段をreload以外に残す。
function applySort(key) {
  const column = JOB_SORT_COLUMNS[key];
  if (!column) return;
  if (!sortState || sortState.key !== key) sortState = { key, dir: column.dir };
  else if (sortState.dir === column.dir) sortState = { key, dir: column.dir === "desc" ? "asc" : "desc" };
  else sortState = null;
  prefSet(JOB_SORT_PREF, sortState ? `${sortState.key}:${sortState.dir}` : null);
  render();
}

function syncSortHeaders() {
  document.querySelectorAll("#job-table th[data-sort]").forEach((th) => {
    const active = Boolean(sortState) && th.dataset.sort === sortState.key;
    th.classList.toggle("sorted", active);
    th.classList.toggle("sorted-asc", active && sortState.dir === "asc");
    th.setAttribute(
      "aria-sort",
      active ? (sortState.dir === "asc" ? "ascending" : "descending") : "none",
    );
  });
}

function bindSortHeaders() {
  document.querySelectorAll("#job-table th[data-sort]").forEach((th) => {
    th.tabIndex = 0;
    th.addEventListener("click", () => applySort(th.dataset.sort));
    th.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      e.preventDefault();
      applySort(th.dataset.sort);
    });
  });
}

// 順番待ちと、前提(保存先volume)の復帰待ちは進まない理由が違う。同じ「待機中」で並べると
// queueが詰まっているようにしか見えない。
function stateWaiting(job) {
  return job.state === "pending" && job.not_before && job.not_before * 1000 > Date.now();
}

function stateText(job) {
  const meta = JOB_STATE_LABELS[job.state] || { text: job.state };
  return stateWaiting(job) ? "復帰待ち" : meta.text;
}

function stateCell(job) {
  const meta = JOB_STATE_LABELS[job.state] || { text: job.state, cls: "badge-idle" };
  const span = document.createElement("span");
  span.className = `badge ${meta.cls}`;
  span.textContent = stateText(job);
  if (stateWaiting(job)) span.title = job.stage || "前提が整うまで待っています。";
  return span;
}

// 段階1件ぶんの所要秒。次の段階へ入った時刻との差で、最後の段階だけは終了時刻(実行中なら
// 現在時刻)まで。段階の終了時刻を別に記録しないのは、段階が途切れず続くものだからで、
// 両端を持つと「前の段階の終わり」と「次の段階の始まり」がずれ得る記録になる。
function stageSeconds(job, stages, index) {
  const start = stages[index].at;
  const next = index + 1 < stages.length
    ? stages[index + 1].at
    : (job.finished_at || Date.now() / 1000);
  if (!start || !next) return null;
  return Math.max(0, next - start);
}

// 段階の経過を、通った順に横へ並べた鎖で出す。縦に積むと段階の数だけ行が伸び、
// 「どこまで来たか」を読むのに目が縦へ往復する。横に並べれば、通った所と今いる所が
// 1本の並びとして一度に読める。
//
// 段階は「通った所」しか記録に無い(先の段階は起きるまで台帳に載らない)。そのため
// 鎖は右端が開いたままで、この先いくつ残っているかは描かない ―― 残りの段数を描くと、
// 記録に無い事を画面が知っているように見える。
// 段の間の線が流れるのは実行中の1本だけで、これは「今ここが動いている」という意味。
// 速さは持たせない(段ごとの処理速度をserverが返していないので、速さを付けると
// 出所の無い数字を動きで語る事になる)。
function stageList(job) {
  const stages = job.stages || [];
  const chain = document.createElement("ol");
  chain.className = "job-chain";
  stages.forEach((stage, index) => {
    const item = document.createElement("li");
    const box = document.createElement("span");
    box.className = "jc-box";
    const label = document.createElement("span");
    label.className = "s-label";
    label.textContent = stage.label;
    const seconds = stageSeconds(job, stages, index);
    const time = document.createElement("span");
    time.className = "s-time";
    time.textContent = seconds === null ? "-" : fmtDuration(seconds);
    const last = index === stages.length - 1;
    // 最後の段階に印を付ける。終わり方によって意味が違う(実行中なら現在地、失敗なら
    // 落ちた場所)ので、印そのものを言い分ける。
    if (last && FAILED_STATES.includes(job.state)) {
      item.className = "s-failed";
      time.title = "この段階で終わっています。";
    } else if (last && job.state === "running") {
      item.className = "s-current";
      time.title = "この段階の途中です（経過時間）。";
    }
    box.append(label, time);
    item.appendChild(box);
    chain.appendChild(item);
  });
  return chain;
}

function progressCell(job) {
  const cell = document.createElement("span");
  cell.className = "job-progress";
  if (job.state !== "running" && job.state !== "pending") {
    const wrap = document.createElement("span");
    wrap.className = "dl-progress";
    wrap.textContent = job.state === "completed" ? "完了 ✓" : "-";
    cell.appendChild(wrap);
  } else {
    // 一覧は他所で動いているjobの状態表示なのでspinnerは付けない。
    const prog = makeProgress({ spinner: false });
    setJobProgress(prog, job);
    cell.appendChild(prog);
  }
  const stages = job.stages || [];
  if (!stages.length) return cell;
  // 実行中のjobだけは初めから開く。「今どこにいるか」は開いてから読む物ではない。
  // 畳んだ事は別に覚える(実行中を開いた状態が既定なので、開いた印では畳めない)。
  const open = job.state === "running"
    ? !collapsedStages.has(job.job_id)
    : expandedStages.has(job.job_id);
  const toggle = document.createElement("button");
  toggle.className = "btn btn-small job-stage-toggle";
  toggle.textContent = `${open ? "▼" : "▶"} 経過 ${stages.length}段階`;
  toggle.setAttribute("aria-expanded", open ? "true" : "false");
  toggle.addEventListener("click", () => {
    const set = job.state === "running" ? collapsedStages : expandedStages;
    // 実行中は「畳んだ」を覚え、それ以外は「開いた」を覚える。持つ意味が逆なので、
    // 開いているかどうかで足し引きの向きも入れ替わる。
    const remember = job.state === "running" ? open : !open;
    if (remember) set.add(job.job_id);
    else set.delete(job.job_id);
    render();
  });
  cell.appendChild(toggle);
  if (open) cell.appendChild(stageList(job));
  return cell;
}

function jobTargetText(job) {
  if (job.total > 1) return `${job.title || "-"}（${job.total}本）`;
  return recStem(job) || job.title || (job.session_id ? recTag(job) : "-");
}

function targetCell(row) {
  const wrap = document.createElement("span");
  wrap.className = "job-target";
  if (row.members > 0) {
    const open = expandedGroups.has(row.job.job_id);
    const toggle = document.createElement("button");
    toggle.className = "btn btn-small job-toggle";
    toggle.textContent = `${open ? "▼" : "▶"} 明細 ${row.members}件`;
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    toggle.addEventListener("click", () => {
      if (open) expandedGroups.delete(row.job.job_id);
      else expandedGroups.add(row.job.job_id);
      render();
    });
    wrap.appendChild(toggle);
  }
  const label = document.createElement("span");
  label.textContent = jobTargetText(row.job);
  wrap.appendChild(label);
  return wrap;
}

// 所要は「実行にかかった時間」。始まっていないjobには存在しないので、投入からの経過で
// 代用しない — 順番待ちの時間をここへ積むと、まだ1秒も動いていないjobが3時間かかったよう
// に読め、待機列が詰まっているのか本当に重いjobなのかを取り違える。
function elapsedSeconds(job) {
  if (!job.started_at) return null;
  const end = job.finished_at || Date.now() / 1000;
  return Math.max(0, end - job.started_at);
}

// 投入からの経過(順番待ちの長さ)。所要とは別物なので、名乗りも別にする。
function waitSeconds(job) {
  if (job.state !== "pending" || !job.queued_at) return null;
  return Math.max(0, Date.now() / 1000 - job.queued_at);
}

// 待機中は所要の代わりに「待機 hh:mm:ss」を出す。ここを "-" だけにすると、詰まったjobが
// いつから並んでいるのかを投入時刻から暗算するしかなくなる。
function elapsedCell(job) {
  const seconds = elapsedSeconds(job);
  if (seconds !== null) return fmtDuration(seconds);
  const waiting = waitSeconds(job);
  if (waiting === null) return "-";
  const span = document.createElement("span");
  span.className = "job-wait";
  span.textContent = `待機 ${fmtDuration(waiting)}`;
  return span;
}

function resultText(job) {
  if (job.message) return job.message;
  const result = job.result || {};
  if (result.count > 1) return `${result.count}件を切り出し`;
  return result.filename || "";
}

// 出来上がったfileの置き場。成果物を作るjobは全てpathを返しているのに、この列は
// file名しか出しておらず「どこに出来たのか分からない」ままだった。成果物は配信者folderの
// 下(動画は<配信者>/_clips/・静止画は<配信者>/_screenshots/)へ出るうえ、保存先も2箇所ある
// ので、dirまで出さないと探せない。
function resultLocation(job) {
  const result = job.result || {};
  if (result.output_dir) return result.output_dir;
  const path = result.output_path || result.path || "";
  const cut = Math.max(path.lastIndexOf("\\"), path.lastIndexOf("/"));
  return cut > 0 ? path.slice(0, cut) : "";
}

// 失敗jobのmessageはffmpeg由来の長文が入る。以前は行内を1行で切ってtooltipへ逃がして
// いたが、肝心の失敗理由が読めるのはhoverした時だけで、実際「見切れて分からない」まま
// だった。全文を折り返して出し、列幅の上限(.job-result)で隣の進捗barを守る。
// 改行はffmpegのlogの区切りなので潰さない(CSSはpre-wrap)。
function resultCell(job) {
  const text = resultText(job);
  const span = document.createElement("span");
  span.className = "job-result";
  span.textContent = text;
  // 失敗messageが入っている行には足さない。理由と場所が1つの塊になって読めなくなる。
  const dir = job.message ? "" : resultLocation(job);
  if (dir) {
    const where = document.createElement("span");
    where.className = "job-result-path";
    where.textContent = dir;
    where.title = dir;
    span.appendChild(where);
  }
  return span;
}

// 実行側のbuttonは何を取り消すのかまで名乗らせる(dialogを閉じる側は「キャンセル」)。
async function sendJobAction(path, job, confirmText, confirmOpts) {
  const opts = confirmOpts || { title: "jobの取り消し", confirmLabel: "jobを取り消す" };
  if (confirmText && !await confirmDialog(confirmText, opts)) return;
  const label = path === "cancel" ? "取り消し" : "再投入";
  try {
    await apiSend("POST", `/api/jobs/${job.job_id}/${path}`);
    await load();
    // 状態の絞り込みが掛かっていると、再投入した行はpendingになって一覧から外れる。
    // 押した結果が「行の消滅」に見えるので、何をしたのかは行の外に残す。
    showToast(`「${job.title}」を${label}しました。`, null, { title: `jobの${label}` });
  } catch (err) {
    // 一覧には多数のjobが並ぶ。どのjobのどの操作かまで名乗らないと対象が辿れない。
    showError(err, `「${job.title}」の${label}`);
  }
}

// 表に無いdomainは生値をそのまま出す。それらしいラベルを組み立てると、記録に無い名前が
// 画面に出て運用logと突き合わせられなくなる(ops_labels.pyのdocstringと同じ約束)。
function kindLabel(domain) {
  return kindLabels[domain] || domain;
}

// sweepが自動で積んだjobは、人が投げた覚えが無いまま並ぶ。種別だけを出すと「頼んで
// いない処理が動いている」としか読めないので、出所を名乗らせる。
function kindText(job) {
  const label = kindLabel(job.domain);
  return job.sweep ? `${label}（自動）` : label;
}

// 種別filterの選択肢。labelと同じくserverの応答から作り、画面に一覧を持たない
// (画面側の一覧は、serverへ種別が増えたときに黙って古いままになる)。
function renderKindOptions() {
  const select = document.getElementById("job-flt-kind");
  const wanted = pendingKind || select.value;
  // 先頭の「全て」は残し、それ以降を作り直す。
  [...select.options].slice(1).forEach((option) => option.remove());
  Object.entries(kindLabels).forEach(([domain, label]) => {
    const option = document.createElement("option");
    option.value = domain;
    option.textContent = label;
    select.appendChild(option);
  });
  // 知らない値でselectを空にしない(既定のfilterが外れて全件が出る方が読み違えを生む)。
  if ([...select.options].some((option) => option.value === wanted)) select.value = wanted;
  pendingKind = "";
}

function actionsCell(job) {
  const wrap = document.createElement("span");
  wrap.className = "row-actions";
  // 取り消し・再実行が効くのはDBのqueueに載る映像jobだけ。容量scan等のin-process jobは
  // 台帳に行が無いので、押せるように見せない。判定の元はserverが返す(queuedKinds)。
  if (!queuedKinds.has(job.domain)) return wrap;
  if (ACTIVE_STATES.includes(job.state)) {
    const cancel = document.createElement("button");
    cancel.className = "btn btn-small";
    cancel.textContent = "取り消し";
    // group行の取り消しは1本ではなくgroupの未終了ぶん全部に効く。配信者まるごとの一括は
    // 数百本になるので、待機中でも件数を言わずに消してはいけない。
    const confirmText = job.total > 1
      ? `「${job.title}」の未終了 ${fmtNum(job.total)}本を取り消しますか？`
      : (job.state === "running"
        ? `実行中の「${job.title}」を取り消しますか？` : "");
    cancel.addEventListener("click", () => sendJobAction("cancel", job, confirmText));
    wrap.appendChild(cancel);
    return wrap;
  }
  // group行は「失敗したぶんだけ」を戻せる。ここを1本ずつ探して押させていたため、一括の
  // 途中で落ちた録画は気付かれないまま残っていた。
  if (job.total > 1) {
    if (job.state !== "failed") return wrap;
    const resume = document.createElement("button");
    resume.className = "btn btn-small";
    resume.textContent = "失敗ぶんを再投入";
    resume.addEventListener("click", () => sendJobAction("retry", job, ""));
    wrap.appendChild(resume);
    return wrap;
  }
  const retry = document.createElement("button");
  retry.className = "btn btn-small";
  retry.textContent = "再実行";
  // 完了済みからのretryは同じ行の再開ではなく新規投入で、GPUを長時間占有する。隣の
  // 「取り消し」には確認があるのに、始める側が無警告なのは誤爆のcostが釣り合わない。
  // 失敗・中断・取り消しからの再開は同じ行が待機へ戻るだけなので、従来どおり無確認。
  const retryConfirm = job.state === "completed"
    ? `完了済みの「${job.title}」を再実行しますか？出力は上書きされます。`
    : "";
  retry.addEventListener("click", () => sendJobAction("retry", job, retryConfirm,
    { title: "完了済みの再実行", confirmLabel: "再実行する", danger: false }));
  wrap.appendChild(retry);
  return wrap;
}

// 右寄せ(tabular)にする列: 投入・所要。headerのclassもここを根拠に揃うので、
// 数字だけが右へ寄って項目名と縦がずれる状態にはならない(renderTableRows)。
const JOB_NUMERIC_COLS = [4, 5];

// 一覧が空に見える理由を言い分ける。取得前・取得失敗・0件・filterで落ちただけ、は別物。
function renderEmptyState(visible) {
  const emptyEl = document.getElementById("job-empty");
  if (visible > 0) {
    setListState(emptyEl, "ok");
    return;
  }
  if (loadState === "failed") {
    setListState(emptyEl, "failed", loadError);
    return;
  }
  if (loadState === "loading") {
    setListState(emptyEl, "loading");
    return;
  }
  const filter = currentFilter();
  const filtering = filter.state !== "all" || filter.kind !== "all" || Boolean(filter.text);
  if (!filtering) {
    setListState(emptyEl, "empty");
    return;
  }
  // 状態・種別はserverが台帳全体から絞っているので「該当なし」と言い切ってよい。ただし
  // limitで切れている場合だけは、見えていない行の存在を先に名乗る。
  setListMessage(emptyEl, jobTotal > jobLimit
    ? `直近${fmtNum(jobLimit)}件に該当なし（台帳 ${fmtNum(jobTotal)}件）`
    : "条件に一致するjobがありません。");
}

// limitで切れているとき、一覧を「これが全部」と読ませない。
function renderLimitNote() {
  const el = document.getElementById("job-limit-note");
  el.removeAttribute("title");
  if (loadState !== "loaded" || jobTotal <= jobLimit) {
    el.textContent = "";
    return;
  }
  el.textContent = `直近${fmtNum(jobLimit)}件 / 該当 ${fmtNum(jobTotal)}件`;
}

// 状態filterで失敗・中断を落としているとき、その存在をこの画面が名乗る。navのtabは
// filterを積まない移動手段なので、隠れた失敗を知らせる口はここにしかない。
//
// 名乗れるのは「隠しているのが状態filterだけ」のときに限る。種別・対象で絞っている
// 一覧に全種別の件数を並べると、今見ている範囲の失敗として読まれる(outsideLedgerと同じ理由)。
function renderFailedNote() {
  const el = document.getElementById("job-failed-note");
  el.textContent = "";
  el.removeAttribute("title");
  const filter = currentFilter();
  if (loadState !== "loaded" || filter.state !== "active") return;
  if (filter.kind !== "all" || filter.text || pinnedJob) return;
  const failed = jobBarFailedCount();
  if (!failed) return;
  const link = document.createElement("a");
  link.href = "/jobs?state=failed";
  link.textContent = `失敗・中断 ${fmtNum(failed)}件`;
  el.appendChild(link);
}

function render() {
  const rows = visibleRows();
  renderTableRows("job-rows", null, rows, (row) => [
    stateCell(row.job),
    kindText(row.job),
    targetCell(row),
    progressCell(row.job),
    fmtDateTimeShort(row.job.queued_at || row.job.started_at),
    elapsedCell(row.job),
    resultCell(row.job),
    actionsCell(row.job),
  ], JOB_NUMERIC_COLS, (tr, row) => {
    // rank-topは順位表の1位を塗るclass。この一覧の先頭は「いま動いているjob」であって
    // 順位ではないので落とす。
    tr.classList.remove("rank-top");
    if (row.sub) tr.classList.add("job-subrow");
  });
  renderEmptyState(rows.length);
  syncSortHeaders();
  renderFailedNote();
  renderLimitNote();
  renderGpu();
}

// 台帳に無いGPU実行(例: 単発の文字起こしAPI)は、gpu.activeにだけ現れる。台帳0行で
// 「実行中 stt」とだけ出すと『GPUは動いているのにjobは無い』と読めるため、その旨を明記する。
// 文字起こしのqueue自体は同じ台帳(kind=stt)に載るので、この一覧に行として出る。
//
// ただしこの指摘ができるのは、一覧が実行中の行を1つも隠していないときだけ。失敗のみ・
// 特定の種別で絞った状態で「一覧に出ない」と言うと、filterで隠しただけのjobを別queueの
// 実行として名指しすることになる。
function outsideLedger() {
  const filter = currentFilter();
  if (filter.state === "failed" || filter.kind !== "all" || filter.text || pinnedJob) return [];
  const running = new Set(
    jobs.filter((job) => job.state === "running").map((job) => job.domain),
  );
  return (gpu.active || []).filter((label) => !running.has(label));
}

function renderGpu() {
  const el = document.getElementById("gpu-summary");
  const sttEl = document.getElementById("stt-summary");
  el.removeAttribute("title");
  sttEl.textContent = "";
  sttEl.removeAttribute("title");
  if (loadState === "failed") {
    el.textContent = "GPUの実行状況を取得できませんでした。";
    el.title = errorDetailText(loadError);
    return;
  }
  if (!gpu) {
    el.textContent = "";
    return;
  }
  const active = gpu.active && gpu.active.length ? gpu.active.join(" / ") : "なし";
  const parts = [`GPU ${active} / 上限 ${gpu.limit} / 待ち ${gpu.waiting}`];
  const outside = outsideLedger();
  if (outside.length) {
    const names = outside.map(kindLabel).join(" / ");
    parts.push(`別queue: ${names}`);
  }
  el.textContent = parts.join(" ");

  const counts = (stt && stt.counts) || {};
  const running = counts.running || 0;
  const pending = counts.pending || 0;
  if (running || pending) {
    // 文字起こしはこの一覧の1種別(kind=stt)なので、行き先は別画面ではなくこの一覧の
    // 絞り込みである。別画面へ送っていた頃は、取り消しも進捗も向こうに縮小版があり、
    // どちらが今の状態なのか読み分けられなかった。
    sttEl.innerHTML = "";
    const link = document.createElement("a");
    link.href = "/jobs?kind=stt";
    link.textContent = `文字起こし 実行中 ${running} / 待機 ${pending}`;
    sttEl.appendChild(link);
  }
}

// 状態・種別はserverが台帳全体から絞る。画面側だけで絞っていた頃は、一括投入が台帳の
// 新しい200行を埋めた日に、その前に失敗したjobが応答へ入らないまま「該当なし」と断定して
// いた。対象の絞込(text)は手元の行に当てるだけなのでrequestには載せない。
async function load() {
  const filter = currentFilter();
  const params = new URLSearchParams({
    state: filter.state, kind: filter.kind, limit: String(JOB_PAGE_LIMIT),
  });
  if (pinnedJob) params.set("job", pinnedJob);
  try {
    const data = await apiSend("GET", `/api/jobs?${params}`);
    jobs = data.jobs || [];
    gpu = data.gpu || null;
    stt = data.stt || null;
    kindLabels = data.kind_labels || {};
    queuedKinds = new Set(data.queued_kinds || []);
    jobTotal = data.total || 0;
    jobLimit = data.limit || JOB_PAGE_LIMIT;
    loadState = "loaded";
    loadError = null;
    renderKindOptions();
  } catch (err) {
    jobs = [];
    gpu = null;
    stt = null;
    jobTotal = 0;
    loadState = "failed";
    loadError = err;
  }
  render();
}

function onMessage(message) {
  if (message.type === "jobs") {
    // WSのsnapshotはfilterを通っていない直近ぶん。これで置き換えると、serverへ渡した
    // filterで拾い直した古い行が接続のたびに消える。行の出所を1つに保つため取り直す
    // (取り直しが終わるまでは今の一覧をそのまま出しておく)。
    // ただし画面を開いた直後の1通目は、下のload()と同じ台帳を運んでくるだけなので
    // 取り直さない(印はcommon.jsのconnectWSが付ける)。
    if (!message.initial) load();
    return;
  }
  if (message.type === "job_update" && message.job) {
    upsertJob(message.job);
  }
}

// ---- 表示設定の永続化 ----
// 画面ごとに独立したdocumentで、nav遷移はフルリロードになる。状態・種別・並べ替えは
// 毎回同じ値を選び直すものなので残す。対象の絞込(自由入力)と明細・段階の開閉(特定のjobを
// 指した一時的な指定)は残さない。
const JOB_STATE_PREF = "tictok.jobs.state";
const JOB_KIND_PREF = "tictok.jobs.kind";
const JOB_SORT_PREF = "tictok.jobs.sort";

// 状態は選択肢がmarkupに揃っているのでこの場で戻る。onChangeは渡さない — 取り直しは
// 下のchange listenerが行うので、ここでも呼ぶと初回に同じrequestを2度出す。
bindPref(document.getElementById("job-flt-state"), JOB_STATE_PREF);
// 種別の選択肢はserverの応答から作るため、この時点ではselectへ当てられない。?kind=と
// 同じ経路(pendingKind)へ預け、requestには先に載せてから選択肢が揃った時点で当てる。
// 保存値がuser操作で変わったときは預かりを解く(選択肢が揃う前の操作でも今の選択が勝つ)。
bindPref(document.getElementById("job-flt-kind"), JOB_KIND_PREF, () => { pendingKind = ""; });
pendingKind = prefGet(JOB_KIND_PREF) || "";

// 並べ替えは列clickで、対応するcontrolが無い。列と向きを1つの値にして残す。
(function restoreSort() {
  const stored = prefGet(JOB_SORT_PREF);
  if (!stored) return;
  const [key, dir] = stored.split(":");
  // 消えた列・読めない向きの保存値は捨てて既定の並び(実行中→待機中→その他)で始める。
  if (!JOB_SORT_COLUMNS[key] || (dir !== "asc" && dir !== "desc")) return;
  sortState = { key, dir };
})();

// 状態・種別はserver側の絞り込みが変わるので取り直す。対象の絞込は手元の行に効くだけ
// なので描き直しで足りる(1文字ごとにserverを叩かない)。
["job-flt-state", "job-flt-kind"].forEach((id) =>
  document.getElementById(id).addEventListener("change", load),
);

// 種別の絞り込みと同じ範囲の未終了jobをまとめて取り消す。範囲は必ずserverが決める
// (手元の行だけを対象にすると、limitで切れた古い行が黙って残る)。
document.getElementById("job-cancel-all").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const kind = document.getElementById("job-flt-kind").value || "all";
  const scope = kind === "all" ? "全種別" : kindLabel(kind);
  const ok = await confirmDialog(
    `${scope}の待機中・実行中のjobをすべて取り消します。`,
    { title: "未終了jobの取り消し", confirmLabel: "まとめて取り消す", danger: true },
  );
  if (!ok) return;
  button.disabled = true;
  try {
    const result = await apiSend(
      "POST", `/api/jobs/cancel-matching?kind=${encodeURIComponent(kind)}`);
    // 0件でも黙らない。「押したのに何も起きない」と「取り消せるものが無かった」は別。
    showToast(result.cancelled
      ? `${fmtNum(result.cancelled)}件のjobを取り消しました。`
      : "取り消せるjobはありませんでした。");
  } catch (err) {
    showError(err, "jobの一括取り消し");
  } finally {
    button.disabled = false;
    load();
  }
});
document.getElementById("job-flt-text").addEventListener("input", () => {
  // ?job= で1件に固定したまま別の語で探させると、いくら打っても0件になる。人が入力へ
  // 触った時点で名指しを解き、台帳から取り直す。
  if (pinnedJob) {
    pinnedJob = "";
    load();
    return;
  }
  render();
});

// 他画面からの誘導(topbarの「失敗 N」・一括処理の「Job画面で進捗を見る」・運用logの
// 「このjobを見る」)は、目的の行が見えるfilterで着地しないと「押したのに空の表」になる。
// queryで初期値を受ける。
(function applyQueryFilters() {
  const params = new URLSearchParams(location.search);
  const state = params.get("state");
  const kind = params.get("kind");
  const job = (params.get("job") || "").trim();
  if (state) {
    const select = document.getElementById("job-flt-state");
    // 知らない値でselectを空にしない(既定のfilterが外れて全件が出る方が読み違えを生む)。
    if ([...select.options].some((opt) => opt.value === state)) select.value = state;
  }
  // 種別の選択肢はserverの応答から作るため、値はここでは当てられない。預けて後で入れる。
  if (kind) pendingKind = kind;
  if (job) {
    document.getElementById("job-flt-text").value = job;
    pinnedJob = job;
    // 運用logから指されたjobは大抵もう終わっている。既定の「実行中・待機中」で着地すると
    // 空の表になるので、状態の指定が無いときは全件から探す。
    if (!state) document.getElementById("job-flt-state").value = "all";
  }
})();

bindSortHeaders();
setListState(document.getElementById("job-empty"), "loading");
load();
connectWS(onMessage);
