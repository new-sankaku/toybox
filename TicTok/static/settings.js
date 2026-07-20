"use strict";

const form = document.getElementById("settings-form");
const statusEl = document.getElementById("settings-status");

function buildOptions(item) {
  const group = document.createElement("div");
  group.className = "radio-group";
  item.options.forEach((opt) => {
    const option = document.createElement("label");
    option.className = "radio-option";

    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = item.key;
    radio.value = opt.value;
    radio.dataset.key = item.key;
    radio.checked = String(opt.value) === String(item.value);

    const text = document.createElement("span");
    text.textContent = opt.label;

    option.append(radio, text);
    group.appendChild(option);
  });
  return group;
}

function buildNumber(item) {
  const input = document.createElement("input");
  input.type = "number";
  input.min = item.min;
  input.max = item.max;
  input.step = item.step;
  input.value = item.value;
  input.dataset.key = item.key;
  return input;
}

function buildText(item) {
  const input = document.createElement("input");
  input.type = "text";
  input.value = item.value;
  input.dataset.key = item.key;
  return input;
}

function buildHeader() {
  ["項目", "設定値", "説明"].forEach((text) => {
    const head = document.createElement("div");
    head.className = "s-cell s-head";
    head.textContent = text;
    form.appendChild(head);
  });
}

function buildSection(item) {
  const head = document.createElement("div");
  head.className = "s-section";
  head.dataset.category = item.category;
  head.textContent = item.category_label;
  form.appendChild(head);
}

// 「既定値へ戻す」。defaultはserverが解決した「今この環境での既定値」で、環境変数で
// 上書きされていればその値が入る(built-in定数を出すとenv運用時に嘘の既定値になる)。
// 押しても保存はせず入力欄へ入れるだけなので、「設定を保存」を押すまで確定しない。
function applyDefault(item, control) {
  const value = String(item.default);
  const input = control.querySelector("input[type=number],input[type=text]");
  if (input) {
    input.value = value;
    return;
  }
  control.querySelectorAll("input[type=radio]").forEach((radio) => {
    radio.checked = radio.value === value;
  });
}

function buildDefaultRow(item, control) {
  const row = document.createElement("div");
  row.className = "s-default";
  const button = document.createElement("button");
  button.type = "button";
  button.className = "btn btn-small";
  button.textContent = "既定値へ戻す";
  button.title = `既定値: ${item.default}`;
  button.addEventListener("click", () => applyDefault(item, control));
  row.appendChild(button);
  if (item.default_source === "env") {
    const note = document.createElement("span");
    note.className = "s-envnote";
    note.textContent = `環境変数 ${item.env} で上書き中（本来の既定値: ${item.builtin_default}）`;
    row.appendChild(note);
  }
  return row;
}

function buildField(item) {
  const isText = item.kind === "text";
  const hasOptions = Array.isArray(item.options) && item.options.length > 0;

  const label = document.createElement("div");
  label.className = "s-cell s-label";
  label.textContent = item.label;

  const control = document.createElement("div");
  control.className = "s-cell s-control";
  control.appendChild(isText ? buildText(item) : hasOptions ? buildOptions(item) : buildNumber(item));
  control.appendChild(buildDefaultRow(item, control));

  const note = document.createElement("div");
  note.className = "s-cell s-note";
  note.textContent =
    isText || hasOptions ? item.note : `${item.note}（${item.min}〜${item.max}）`;

  [label, control, note].forEach((cell) => {
    cell.dataset.key = item.key;
    cell.dataset.category = item.category;
    cell.dataset.search = `${item.key} ${item.label} ${item.note}`.toLowerCase();
  });
  form.append(label, control, note);
}

// 絞り込み。畳まないのでbrowserのCtrl+Fは全項目に効いたまま、こちらは上乗せ。
// 一致0件のsectionはheaderごと隠す(見出しだけが残ると項目が消えたように見える)。
function applyFilter() {
  const query = document.getElementById("settings-filter").value.trim().toLowerCase();
  const counter = document.getElementById("settings-filter-count");
  const cells = form.querySelectorAll(".s-cell[data-search]");
  let visible = 0;
  const matchedCategories = new Set();
  cells.forEach((cell) => {
    const hit = !query || cell.dataset.search.includes(query);
    cell.classList.toggle("hidden", !hit);
    if (hit && cell.classList.contains("s-label")) {
      visible += 1;
      matchedCategories.add(cell.dataset.category);
    }
  });
  form.querySelectorAll(".s-section").forEach((section) => {
    section.classList.toggle("hidden", Boolean(query) && !matchedCategories.has(section.dataset.category));
  });
  counter.textContent = query ? `${visible} 件が一致` : "";
}

async function loadSettings() {
  const res = await fetch("/api/settings");
  if (!res.ok) {
    statusEl.textContent = "設定の取得に失敗しました。";
    return;
  }
  const data = await res.json();
  form.innerHTML = "";
  buildHeader();
  let category = null;
  data.settings.forEach((item) => {
    if (item.category !== category) {
      category = item.category;
      buildSection(item);
    }
    buildField(item);
  });
  applyFilter();
}

document.getElementById("settings-filter").addEventListener("input", applyFilter);

document.getElementById("settings-save").addEventListener("click", async () => {
  const values = {};
  form.querySelectorAll("input[type=number][data-key]").forEach((input) => {
    values[input.dataset.key] = input.value;
  });
  form.querySelectorAll("input[type=text][data-key]").forEach((input) => {
    values[input.dataset.key] = input.value;
  });
  form.querySelectorAll("input[type=radio][data-key]:checked").forEach((input) => {
    values[input.dataset.key] = input.value;
  });
  statusEl.textContent = "保存中…";
  try {
    await apiSend("PUT", "/api/settings", values);
    statusEl.textContent = "保存しました。";
  } catch (err) {
    statusEl.textContent = err.message;
  }
});

// ---- 容量の内訳 ----
// 判定と文言はserverが持つ(種別labelも再生成可否もAPI応答のまま描画する)。
const usageStatusEl = document.getElementById("usage-status");
const usageSummaryEl = document.getElementById("usage-summary");
const usageScanBtn = document.getElementById("usage-scan");

function fmtBytesGb(bytes) {
  return `${fmtGb(bytes)} GB`;
}

function renderUsage(payload) {
  const scan = payload && payload.scan;
  const hasScan = Boolean(scan && scan.usage);
  document.getElementById("usage-category-empty").classList.toggle("hidden", hasScan);
  document.getElementById("usage-streamer-empty").classList.toggle("hidden", hasScan);
  if (!hasScan) {
    document.getElementById("usage-category-list").innerHTML = "";
    document.getElementById("usage-streamer-list").innerHTML = "";
    usageSummaryEl.textContent = `対象folder: ${(payload.roots || []).join(" / ") || "-"}`;
    return;
  }
  const usage = scan.usage;
  const regenerable = new Set(usage.regenerable_categories || []);
  const errors = (usage.errors || []).length;
  usageSummaryEl.textContent =
    `最終scan: ${fmtDateTime(scan.scanned_at)}（${Math.round(scan.duration_ms / 1000)}秒）`
    + ` / 合計 ${fmtBytesGb(usage.total_bytes)}・${fmtNum(usage.total_files)} file`
    + ` / 対象folder: ${(usage.roots || []).join(" / ")}`
    + (errors ? ` / 読めなかった場所 ${fmtNum(errors)} 件（合計に含みません）` : "");

  const rows = (usage.category_labels || [])
    .map((entry) => ({ ...entry, ...(usage.categories[entry.key] || { bytes: 0, files: 0 }) }))
    .filter((row) => row.files > 0);
  renderTableRows(
    "usage-category-list",
    null,
    rows,
    (row) => [
      row.label,
      fmtBytesGb(row.bytes),
      fmtNum(row.files),
      regenerable.has(row.key) ? "作り直せる" : "作り直せない",
    ],
    [1, 2],
  );

  renderTableRows(
    "usage-streamer-list",
    null,
    usage.streamers || [],
    (row) => {
      const cat = (key) => fmtBytesGb((row.categories[key] || {}).bytes || 0);
      return [
        row.label,
        fmtBytesGb(row.bytes),
        cat("source"),
        cat("overlay"),
        cat("up"),
        cat("ts"),
        cat("transient"),
      ];
    },
    [1, 2, 3, 4, 5, 6],
  );
}

async function loadUsage() {
  try {
    const res = await fetch("/api/storage/usage");
    if (!res.ok) throw new Error(String(res.status));
    renderUsage(await res.json());
  } catch (err) {
    usageStatusEl.textContent = "容量の内訳を取得できませんでした。";
  }
}

usageScanBtn.addEventListener("click", async () => {
  usageScanBtn.disabled = true;
  usageStatusEl.textContent = "走査中…（数TB規模では数分かかります）";
  try {
    renderUsage(await apiSend("POST", "/api/storage/scan"));
    usageStatusEl.textContent = "走査しました。";
  } catch (err) {
    usageStatusEl.textContent = err.message;
  } finally {
    usageScanBtn.disabled = false;
  }
});

// ---- 保持policy ----
// dry-runの結果を持っていない限りapplyできない。planはserverが組み直すため、画面が持つのは
// 「確認済みかどうか」だけにする。
const retentionStatusEl = document.getElementById("retention-status");
const retentionPlanEl = document.getElementById("retention-plan");
const retentionPreviewBtn = document.getElementById("retention-preview");
const retentionApplyBtn = document.getElementById("retention-apply");
const RETENTION_SAMPLE = 20;

function retentionItemLabel(item) {
  if (item.filename) {
    return `${item.filename}（${item.age_days}日前 / ${fmtBytesGb(item.bytes)}）`;
  }
  return `${item.name}（${item.age_hours}時間前 / ${fmtBytesGb(item.bytes)}）`;
}

function renderRetentionPlan(plan) {
  retentionPlanEl.innerHTML = "";
  (plan.phases || []).forEach((phase) => {
    const block = document.createElement("div");
    block.className = "chart-note";
    const head = document.createElement("div");
    head.textContent = phase.enabled
      ? `${phase.label}: ${fmtNum(phase.items.length)} 件 / ${fmtBytesGb(phase.bytes)}`
      : `${phase.label}: ${phase.reason}`;
    block.appendChild(head);
    if (phase.enabled && phase.items.length) {
      const list = document.createElement("ul");
      phase.items.slice(0, RETENTION_SAMPLE).forEach((item) => {
        const li = document.createElement("li");
        li.textContent = retentionItemLabel(item);
        list.appendChild(li);
      });
      if (phase.items.length > RETENTION_SAMPLE) {
        const li = document.createElement("li");
        li.textContent = `ほか ${fmtNum(phase.items.length - RETENTION_SAMPLE)} 件`;
        list.appendChild(li);
      }
      block.appendChild(list);
    }
    retentionPlanEl.appendChild(block);
  });
  const total = document.createElement("div");
  total.className = "chart-note";
  total.textContent = `合計 ${fmtNum(plan.total_items)} 件 / ${fmtBytesGb(plan.total_bytes)} を削除できます。`
    + (plan.protected_count ? ` 保護中の録画 ${fmtNum(plan.protected_count)} 件は対象外です。` : "")
    + (plan.free_target_bytes
      ? ` 空き容量が ${fmtGb(plan.free_target_bytes)} GB に達した時点で打ち切ります。`
      : "");
  retentionPlanEl.appendChild(total);
}

retentionPreviewBtn.addEventListener("click", async () => {
  retentionPreviewBtn.disabled = true;
  retentionApplyBtn.disabled = true;
  retentionStatusEl.textContent = "確認中…";
  try {
    const res = await apiSend("POST", "/api/storage/retention", { apply: false });
    renderRetentionPlan(res.plan);
    retentionApplyBtn.disabled = res.plan.total_items === 0;
    retentionStatusEl.textContent = res.plan.total_items
      ? "削除内容を確認してください。まだ何も削除していません。"
      : "削除対象はありません。";
  } catch (err) {
    retentionStatusEl.textContent = err.message;
  } finally {
    retentionPreviewBtn.disabled = false;
  }
});

retentionApplyBtn.addEventListener("click", async () => {
  const ok = await confirmDialog(
    "確認した内容を削除します。生録画を含む場合、この操作は取り消せません。実行しますか？",
    { title: "保持policyの適用", confirmLabel: "削除する" },
  );
  if (!ok) return;
  retentionApplyBtn.disabled = true;
  retentionPreviewBtn.disabled = true;
  retentionStatusEl.textContent = "削除中…";
  try {
    const res = await apiSend("POST", "/api/storage/retention", { apply: true, confirm: true });
    renderRetentionPlan(res.plan);
    retentionStatusEl.textContent =
      `${fmtNum(res.result.removed_items)} 件・${fmtBytesGb(res.result.freed_bytes)} を削除しました。`
      + (res.result.stopped_at ? "（空き容量が目標に達したため途中で打ち切りました）" : "");
    loadDiskBar();
    loadUsage();
  } catch (err) {
    retentionStatusEl.textContent = err.message;
  } finally {
    retentionPreviewBtn.disabled = false;
  }
});

// ---- 焼き込みプレビュー ----
// 静止画はserverが同期で返す(数秒)。動画は永続queueへ載るので、job_updateで完了を待つ。
const previewStatusEl = document.getElementById("preview-status");
const previewMetaEl = document.getElementById("preview-meta");
const previewOutputEl = document.getElementById("preview-output");
const previewSelect = document.getElementById("preview-recording");
const previewStillBtn = document.getElementById("preview-still-btn");
const previewClipBtn = document.getElementById("preview-clip-btn");
// job_id -> 完了待ちのpromise resolver。reloadで失われるが、成果物はserverに残るので
// 「動画で確認」を押し直せば cache hit で即座に表示できる。
const previewJobs = new Map();

function previewWindowText(result) {
  if (!result) return "";
  const from = fmtDuration(result.window_start_seconds);
  const to = fmtDuration(result.window_end_seconds);
  const how = result.window_auto ? "自動選定" : "指定";
  return `切り出し区間: ${from} 〜 ${to}（${how}）`;
}

function fillPreviewRecordings(recordings) {
  previewSelect.innerHTML = "";
  const usable = (recordings || []).filter(
    (rec) => rec.session_id !== null && rec.session_id !== undefined && rec.status === "completed",
  );
  if (!usable.length) {
    const opt = document.createElement("option");
    opt.textContent = "プレビューできる録画がありません";
    opt.value = "";
    previewSelect.appendChild(opt);
    previewStillBtn.disabled = true;
    previewClipBtn.disabled = true;
    return;
  }
  usable.forEach((rec) => {
    const opt = document.createElement("option");
    opt.value = String(rec.id);
    opt.textContent = `${rec.unique_id || ""} ${fmtDateTime(rec.started_at)}`.trim();
    previewSelect.appendChild(opt);
  });
}

async function loadPreviewRecordings() {
  try {
    const res = await fetch("/api/recordings");
    if (!res.ok) throw new Error(String(res.status));
    const data = await res.json();
    fillPreviewRecordings(data.recordings);
  } catch (err) {
    previewStatusEl.textContent = "録画一覧を取得できませんでした。";
  }
}

previewStillBtn.addEventListener("click", async () => {
  const id = previewSelect.value;
  if (!id) return;
  previewStillBtn.disabled = true;
  previewStatusEl.textContent = "静止画を生成中…";
  try {
    const res = await apiSend("POST", `/api/recordings/${id}/preview/still`);
    previewOutputEl.innerHTML = "";
    const img = document.createElement("img");
    img.src = res.url;
    img.alt = "焼き込みプレビュー(静止画)";
    previewOutputEl.appendChild(img);
    previewMetaEl.textContent =
      `表示time刻: ${fmtDuration(res.at_seconds)}（${res.window_auto ? "自動選定" : "指定"}）`
      + (res.comments_drawn ? "" : " / この時刻に表示中のCommentはありません");
    previewStatusEl.textContent = "生成しました。";
  } catch (err) {
    previewStatusEl.textContent = err.message;
  } finally {
    previewStillBtn.disabled = false;
  }
});

previewClipBtn.addEventListener("click", async () => {
  const id = previewSelect.value;
  if (!id) return;
  previewClipBtn.disabled = true;
  previewStatusEl.textContent = "queueへ投入しました。順番が来ると焼き込みが始まります。";
  try {
    const res = await apiSend("POST", `/api/recordings/${id}/preview/clip`);
    previewJobs.set(res.job_id, id);
  } catch (err) {
    previewStatusEl.textContent = err.message;
    previewClipBtn.disabled = false;
  }
});

function applyPreviewJob(job) {
  const recordingId = previewJobs.get(job.job_id);
  if (recordingId === undefined) return;
  if (job.state === "pending") {
    previewStatusEl.textContent = "queueで待機中…";
    return;
  }
  if (job.state === "running") {
    previewStatusEl.textContent = `${job.stage || "準備中"} ${job.pct}%`;
    return;
  }
  previewJobs.delete(job.job_id);
  previewClipBtn.disabled = false;
  if (job.state !== "completed") {
    previewStatusEl.textContent = job.message || "プレビュー動画を生成できませんでした。";
    return;
  }
  const result = job.result || {};
  previewOutputEl.innerHTML = "";
  const video = document.createElement("video");
  video.src = `/api/recordings/${recordingId}/preview/clip.mp4?v=${Date.now()}`;
  video.controls = true;
  previewOutputEl.appendChild(video);
  previewMetaEl.textContent = previewWindowText(result);
  previewStatusEl.textContent = result.cached ? "生成済みのプレビューを表示しました。" : "生成しました。";
}

loadPreviewRecordings();

loadSettings();
loadUsage();
connectWS((msg) => {
  if (msg.type === "jobs") (msg.data || []).forEach(applyPreviewJob);
  else if (msg.type === "job_update" && msg.job) applyPreviewJob(msg.job);
});
