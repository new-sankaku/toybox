"use strict";

// Job画面: 実行中・待機中・過去のjobを1画面に並べ、取り消しと再実行の導線を持つ。
// 運用log(ops_events)は「もう起きたこと」を遡る画面で、こちらは「これから終わること」を
// 待つ画面。更新のされ方(行の書き換え vs 追記)も見る目的も違うので、pageを分けている。
// 一覧はWSのjob_update/jobsで更新するが、pageを開いた直後だけはHTTPで取り直す
// (WSのsnapshotが届く前の空表示を避けるため)。

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

const JOB_KIND_LABELS = {
  overlay: "焼き込み",
  upscale: "Up出力",
  reprocess: "再mp4化",
  audionorm: "音量正規化",
  overlay_preview: "焼き込みプレビュー",
  clip_batch: "clip一括書き出し",
  session_overlay: "Session 焼き込み",
  session_upscale: "Session Up出力",
  bulk_overlay: "一括 焼き込み出力",
  bulk_upscale: "一括 Up出力",
  bulk_reprocess: "一括 再mp4化",
  bulk_audionorm: "一括 音量正規化",
  stt: "文字起こし",
  storage: "容量scan",
  retention: "保持policy",
  semantic: "意味検索index",
  cutlist: "cut list書き出し",
};

// group(session一括)は個々のjobを畳んだ表示行なので、既定では明細を出さない。
const ACTIVE_STATES = ["pending", "running"];
const FAILED_STATES = ["failed", "interrupted"];

let jobs = [];
// 明細を開いているgroup_id。groupの合成行はjob_idにgroup_idがそのまま入るため、
// 「group_idを持ち、かつjob_idと一致しない」行がsession一括の明細にあたる。
const expandedGroups = new Set();
let gpu = null;
// 台帳外(transcribe_queue)の実状。GPU現況と台帳の食い違いを説明するためだけに読む。
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
  render();
}

function matchesFilter(job) {
  const state = document.getElementById("job-flt-state").value;
  const kind = document.getElementById("job-flt-kind").value;
  if (state === "active" && !ACTIVE_STATES.includes(job.state)) return false;
  if (state === "failed" && !FAILED_STATES.includes(job.state)) return false;
  if (kind !== "all" && job.domain !== kind) return false;
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
  const matched = sortJobs(jobs.filter(matchesFilter));
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

function sortJobs(list) {
  const rank = (job) => (job.state === "running" ? 0 : job.state === "pending" ? 1 : 2);
  return list.slice().sort((a, b) => {
    if (rank(a) !== rank(b)) return rank(a) - rank(b);
    const at = a.finished_at || a.started_at || a.queued_at || 0;
    const bt = b.finished_at || b.started_at || b.queued_at || 0;
    return bt - at;
  });
}

function stateCell(job) {
  const meta = JOB_STATE_LABELS[job.state] || { text: job.state, cls: "badge-idle" };
  const span = document.createElement("span");
  span.className = `badge ${meta.cls}`;
  // 順番待ちと、前提(保存先volume)の復帰待ちは進まない理由が違う。同じ「待機中」で並べると
  // queueが詰まっているようにしか見えない。
  const waiting = job.state === "pending" && job.not_before && job.not_before * 1000 > Date.now();
  span.textContent = waiting ? "復帰待ち" : meta.text;
  if (waiting) span.title = job.stage || "前提が整うまで待っています。";
  return span;
}

function progressCell(job) {
  if (job.state !== "running" && job.state !== "pending") {
    const wrap = document.createElement("span");
    wrap.className = "dl-progress";
    wrap.textContent = job.state === "completed" ? "完了 ✓" : "-";
    return wrap;
  }
  // 一覧は他所で動いているjobの状態表示なのでspinnerは付けない。
  const prog = makeProgress({ spinner: false });
  setJobProgress(prog, job);
  return prog;
}

function jobTargetText(job) {
  if (job.total > 1) return `${job.title || "-"}（${job.total}本）`;
  return job.filename || job.title || (job.recording_id ? `#${job.recording_id}` : "-");
}

function targetCell(row) {
  const wrap = document.createElement("span");
  wrap.className = "job-target";
  if (row.members > 0) {
    const open = expandedGroups.has(row.job.job_id);
    const toggle = document.createElement("button");
    toggle.className = "btn btn-small job-toggle";
    toggle.textContent = `${open ? "▼" : "▶"} 明細 ${row.members}件`;
    toggle.title = "この一括出力に含まれる録画ごとのjobを開閉します。";
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

function elapsedText(job) {
  const start = job.started_at || job.queued_at;
  if (!start) return "-";
  const end = job.finished_at || Date.now() / 1000;
  return fmtDuration(Math.max(0, end - start));
}

function resultText(job) {
  if (job.message) return job.message;
  const result = job.result || {};
  const done = result.count > 1 ? `${result.count}件を切り出し` : result.filename || "";
  // 切り抜きmp4はvideo+audioのstream copyで字幕もcommentも入らない。隣へ何件出たのか
  // (出なかったならなぜか)を結果に出さないと、編集ソフトへ渡すまで気付けない。
  if (result.sidecar_skipped) return `${done} / ${result.sidecar_skipped}`;
  if (result.sidecar_count) return `${done} / 字幕・comment ${result.sidecar_count}件`;
  return done;
}

async function sendJobAction(path, job, confirmText) {
  if (confirmText && !await confirmDialog(confirmText, { title: "jobの取り消し", confirmLabel: "取り消す" })) return;
  try {
    await apiSend("POST", `/api/jobs/${job.job_id}/${path}`);
    await load();
  } catch (err) {
    showError(err);
  }
}

function actionsCell(job) {
  const wrap = document.createElement("span");
  wrap.className = "row-actions";
  // 取り消し・再実行が効くのはDBのqueueに載る映像jobだけ。容量scan等のin-process jobは
  // 台帳に行が無いので、押せるように見せない。
  const queued = ["overlay", "upscale", "reprocess", "audionorm", "overlay_preview", "clip_batch",
    "session_overlay", "session_upscale",
    "bulk_overlay", "bulk_upscale", "bulk_reprocess", "bulk_audionorm"]
    .includes(job.domain);
  if (!queued) return wrap;
  if (ACTIVE_STATES.includes(job.state)) {
    const cancel = document.createElement("button");
    cancel.className = "btn btn-small";
    cancel.textContent = "取り消し";
    cancel.title = "待機中のjobはqueueから外します。実行中のjobはffmpegを止めて途中のfileを片付けるため、状態が変わるまで少し時間がかかります。";
    // group行の取り消しは1本ではなくgroupの未終了ぶん全部に効く。配信者まるごとの一括は
    // 数百本になるので、待機中でも件数を言わずに消してはいけない。
    const confirmText = job.total > 1
      ? `「${job.title}」の未終了のjobをまとめて取り消しますか？（全${fmtNum(job.total)}本）`
        + (job.state === "running" ? " 実行中の1本は途中までの出力を破棄します。" : "")
      : (job.state === "running"
        ? `実行中の「${job.title}」を取り消しますか？途中までの出力は破棄されます。` : "");
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
    resume.title = "この一括投入のうち、失敗・中断した録画だけをqueueへ戻して続きから処理します。"
      + "完了済みの録画はやり直しません。";
    resume.addEventListener("click", () => sendJobAction("retry", job, ""));
    wrap.appendChild(resume);
    return wrap;
  }
  const retry = document.createElement("button");
  retry.className = "btn btn-small";
  retry.textContent = "再実行";
  retry.title = "この録画をもう一度処理します。失敗・中断・取り消しならこの行がそのまま待機へ戻り、"
    + "完了済みなら新しいjobとして投入し直します。";
  retry.addEventListener("click", () => sendJobAction("retry", job, ""));
  wrap.appendChild(retry);
  return wrap;
}

function render() {
  const rows = visibleRows();
  const tbody = document.getElementById("job-rows");
  tbody.replaceChildren();
  const emptyEl = document.getElementById("job-empty");
  if (rows.length > 0) setListState(emptyEl, "ok");
  else if (loadState === "failed") setListState(emptyEl, "failed", loadError);
  else if (loadState === "loading") setListState(emptyEl, "loading");
  // jobが1件も無いのか、filterに一致しないだけなのかは別の状態。
  else if (jobs.length > 0)
    setListMessage(emptyEl, "条件に一致するjobがありません。filterを変更してください。");
  else setListState(emptyEl, "empty");
  rows.forEach((row) => {
    const job = row.job;
    const tr = document.createElement("tr");
    if (row.sub) tr.className = "job-subrow";
    const cells = [
      stateCell(job),
      JOB_KIND_LABELS[job.domain] || job.domain,
      targetCell(row),
      progressCell(job),
      fmtDateTime(job.queued_at || job.started_at),
      elapsedText(job),
      resultText(job),
      actionsCell(job),
    ];
    cells.forEach((cell) => {
      const td = document.createElement("td");
      if (cell instanceof Node) td.appendChild(cell);
      else td.textContent = cell;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  renderGpu();
}

// 文字起こしは media_job_queue ではなく transcribe_queue で動くので、この一覧には行が
// 出ない。一方でGPUの枠は同じなのでgpu.activeには出る。台帳0行で「実行中 stt」とだけ
// 出すと『GPUは動いているのにjobは無い』と読めるため、台帳に無いGPU実行はその旨を明記し、
// 実際の待ち行列を別queueの数字としてそのまま併記する(この一覧に偽の行は足さない)。
function outsideLedger() {
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
  const parts = [`GPU: 実行中 ${active}（同時実行上限 ${gpu.limit} / 順番待ち ${gpu.waiting}）`];
  const outside = outsideLedger();
  if (outside.length) {
    const names = outside.map((label) => JOB_KIND_LABELS[label] || label).join(" / ");
    parts.push(`※ ${names}は下の一覧に出ない別queueで実行中です。`);
  }
  el.textContent = parts.join(" ");

  const counts = (stt && stt.counts) || {};
  const running = counts.running || 0;
  const pending = counts.pending || 0;
  if (running || pending) {
    // 状況を見る場所と操作する場所が分かれていた。待機が詰まっているのを見つけても
    // その場で取り消せないので、操作できる画面へ直接繋ぐ。
    sttEl.innerHTML = "";
    const link = document.createElement("a");
    link.href = "/videos#transcribe";
    link.textContent = `文字起こしqueue: 実行中 ${running} / 待機中 ${pending}`;
    link.title = "文字起こしは別queueで動くため、この一覧には行が出ません。clickで投入・取り消しができる画面へ移動します。";
    sttEl.appendChild(link);
  }
}

async function load() {
  try {
    const data = await apiSend("GET", "/api/jobs");
    jobs = data.jobs || [];
    gpu = data.gpu || null;
    stt = data.stt || null;
    loadState = "loaded";
    loadError = null;
  } catch (err) {
    jobs = [];
    gpu = null;
    stt = null;
    loadState = "failed";
    loadError = err;
  }
  render();
}

function onMessage(message) {
  if (message.type === "jobs") {
    jobs = message.data || [];
    loadState = "loaded";
    loadError = null;
    render();
    return;
  }
  if (message.type === "job_update" && message.job) {
    upsertJob(message.job);
  }
}

["job-flt-state", "job-flt-kind"].forEach((id) =>
  document.getElementById(id).addEventListener("input", render),
);

setListState(document.getElementById("job-empty"), "loading");
load();
connectWS(onMessage);
