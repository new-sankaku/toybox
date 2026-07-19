"use strict";

// job画面: 実行中・待機中・過去のjobを1画面に並べ、取り消しと再実行の導線を持つ。
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
  overlay_preview: "焼き込みプレビュー",
  clip_batch: "clip一括書き出し",
  session_overlay: "Session出力",
  session_upscale: "Session Up出力",
  stt: "文字起こし",
  storage: "容量scan",
  retention: "保持policy",
};

// group(session一括)は個々のjobを畳んだ表示行なので、既定では明細を出さない。
const ACTIVE_STATES = ["pending", "running"];
const FAILED_STATES = ["failed", "interrupted"];

let jobs = [];
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
  const state = document.getElementById("flt-state").value;
  const kind = document.getElementById("flt-kind").value;
  if (state === "active" && !ACTIVE_STATES.includes(job.state)) return false;
  if (state === "failed" && !FAILED_STATES.includes(job.state)) return false;
  if (kind !== "all" && job.domain !== kind) return false;
  return true;
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
  span.textContent = meta.text;
  return span;
}

function progressCell(job) {
  const wrap = document.createElement("span");
  wrap.className = "dl-progress";
  if (job.state !== "running" && job.state !== "pending") {
    wrap.textContent = job.state === "completed" ? "完了 ✓" : "-";
    return wrap;
  }
  wrap.innerHTML = '<span class="dl-bar"><span class="dl-bar-fill"></span></span>'
    + '<span class="dl-pct"></span>';
  const pct = job.state === "pending" ? 0 : Math.max(0, Math.min(100, job.pct || 0));
  wrap.querySelector(".dl-bar-fill").style.inlineSize = `${pct}%`;
  wrap.querySelector(".dl-pct").textContent = job.state === "pending"
    ? "待機中" : `${job.stage || "準備中"} ${pct}%`;
  return wrap;
}

function targetText(job) {
  if (job.total > 1) return `${job.title || "-"}（${job.total}本）`;
  return job.filename || job.title || (job.recording_id ? `#${job.recording_id}` : "-");
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
  if (result.count > 1) return `${result.count}件を切り出し`;
  return result.filename || "";
}

async function sendJobAction(path, job, confirmText) {
  if (confirmText && !window.confirm(confirmText)) return;
  try {
    await apiSend("POST", `/api/jobs/${job.job_id}/${path}`);
    await load();
  } catch (err) {
    window.alert(err.message);
  }
}

function actionsCell(job) {
  const wrap = document.createElement("span");
  wrap.className = "row-actions";
  // 取り消し・再実行が効くのはDBのqueueに載る映像jobだけ。容量scan等のin-process jobは
  // 台帳に行が無いので、押せるように見せない。
  const queued = ["overlay", "upscale", "reprocess", "overlay_preview", "clip_batch",
    "session_overlay", "session_upscale"]
    .includes(job.domain);
  if (!queued) return wrap;
  if (ACTIVE_STATES.includes(job.state)) {
    const cancel = document.createElement("button");
    cancel.className = "btn btn-small";
    cancel.textContent = "取り消し";
    cancel.title = "待機中のjobはqueueから外します。実行中のjobはffmpegを止めて途中のfileを片付けるため、状態が変わるまで少し時間がかかります。";
    cancel.addEventListener("click", () => sendJobAction(
      "cancel", job,
      job.state === "running" ? `実行中の「${job.title}」を取り消しますか？途中までの出力は破棄されます。` : "",
    ));
    wrap.appendChild(cancel);
    return wrap;
  }
  if (job.total > 1) return wrap;
  const retry = document.createElement("button");
  retry.className = "btn btn-small";
  retry.textContent = "再実行";
  retry.title = "同じ内容を新しいjobとしてqueueへ投入し直します。この行は履歴として残ります。";
  retry.addEventListener("click", () => sendJobAction("retry", job, ""));
  wrap.appendChild(retry);
  return wrap;
}

function render() {
  const rows = sortJobs(jobs.filter(matchesFilter));
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
  rows.forEach((job) => {
    const tr = document.createElement("tr");
    const cells = [
      stateCell(job),
      JOB_KIND_LABELS[job.domain] || job.domain,
      targetText(job),
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
    sttEl.textContent = `文字起こしqueue: 実行中 ${running} / 待機中 ${pending}（この一覧には出ません）`;
    sttEl.title = "文字起こしは別queueで動くため、この一覧には行が出ません。配信者動画の画面から投入・取り消しができます。";
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

["flt-state", "flt-kind"].forEach((id) =>
  document.getElementById(id).addEventListener("input", render),
);

setListState(document.getElementById("job-empty"), "loading");
load();
connectWS(onMessage);
