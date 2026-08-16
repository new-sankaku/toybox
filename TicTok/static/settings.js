"use strict";

const form = document.getElementById("settings-form");
const statusEl = document.getElementById("settings-status");

function buildOptions(item) {
  const group = document.createElement("div");
  group.className = "radio-group";
  group.setAttribute("role", "radiogroup");
  group.setAttribute("aria-labelledby", `setlbl-${item.key}`);
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

// 選択肢が見本画像を持つ設定(テロップpresetなど)。名前だけでは何が変わるか分からない
// ものは、実物を並べて選べるようにする。画像はserverが本番と同じ経路で焼いたもので、
// 出せない場合(font未取得・ffmpeg無し)はlabelだけのcardへ落ちる — 選択自体は妨げない。
function buildOptionGallery(item) {
  const group = document.createElement("div");
  group.className = "option-gallery";
  group.setAttribute("role", "radiogroup");
  group.setAttribute("aria-labelledby", `setlbl-${item.key}`);
  item.options.forEach((opt) => {
    const card = document.createElement("label");
    card.className = "option-card";

    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = item.key;
    radio.value = opt.value;
    radio.dataset.key = item.key;
    radio.checked = String(opt.value) === String(item.value);

    const img = document.createElement("img");
    img.className = "option-card-img";
    img.setAttribute("loading", "lazy");
    img.alt = `${opt.label} の見本`;
    img.src = item.option_image.replace("{value}", String(opt.value));
    img.addEventListener("error", () => {
      img.remove();
      card.classList.add("option-card-noimg");
    });

    const text = document.createElement("span");
    text.className = "option-card-label";
    text.textContent = opt.label;

    card.append(radio, img, text);
    group.appendChild(card);
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
  input.setAttribute("aria-labelledby", `setlbl-${item.key}`);
  return input;
}

function buildText(item) {
  const input = document.createElement("input");
  input.type = "text";
  input.value = item.value;
  input.dataset.key = item.key;
  input.setAttribute("aria-labelledby", `setlbl-${item.key}`);
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
  // 保存済みの値が現在の定義に適合しないkey。serverはこの値のまま動かし、理由をinvalidで
  // 返してくる(既定値へ黙って差し替えない方針)。選択肢の外の値は該当するradioが無いため
  // 「どれも選ばれていない」状態で描かれ、保存でもそのkeyは送られない — 画面が理由を
  // 出さないと、設定が消えたようにしか見えないまま実際の値は古い値で動き続ける。
  if (item.invalid) {
    const note = document.createElement("span");
    note.className = "s-envnote";
    note.textContent = `保存済みの値「${item.value}」は現在の定義に適合しません（${item.invalid}）。`
      + "この値のまま動いています。選び直して保存してください。";
    row.appendChild(note);
  }
  return row;
}

function buildField(item) {
  const isText = item.kind === "text";
  const hasOptions = Array.isArray(item.options) && item.options.length > 0;

  const label = document.createElement("div");
  label.className = "s-cell s-label";
  label.id = `setlbl-${item.key}`;
  label.textContent = item.label;

  const control = document.createElement("div");
  control.className = "s-cell s-control";
  const hasGallery = hasOptions && Boolean(item.option_image);
  // 選択肢を持つ設定は、値が文字でも選ばせる。serverは選択肢の外を422で拒むので、
  // 自由入力にすると「綴りを外した保存だけが失敗する」欄になる(値の一覧は画面のどこにも
  // 出ていなかった)。自由入力は選択肢を持たないもの(保存先のpath)だけが使う。
  control.appendChild(
    hasGallery
      ? buildOptionGallery(item)
      : hasOptions
        ? buildOptions(item)
        : isText
          ? buildText(item)
          : buildNumber(item),
  );
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
  let data;
  try {
    const res = await fetch("/api/settings");
    if (!res.ok) throw new Error(`設定の取得に失敗しました（HTTP ${res.status}）。`);
    data = await res.json();
  } catch (err) {
    // server停止・網断ではfetchがrejectする。包まないと以降へ進めず、設定表が空のまま
    // 何も出ない(この画面の全操作の前提なので、無反応と取り違えると原因を探せない)。
    statusEl.textContent = "設定の取得に失敗しました。";
    showError(err, "設定の取得");
    return;
  }
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
  const saveBtn = document.getElementById("settings-save");
  saveBtn.disabled = true;
  statusEl.textContent = "保存中…";
  try {
    await apiSend("PUT", "/api/settings", values);
    statusEl.textContent = "保存しました。";
    showToast("設定を保存しました。", null, { title: "設定" });
  } catch (err) {
    // statusElは0.75remのmutedな1行で、成功と失敗が同じ色・同じ大きさで出る。
    // 値を弾かれたのに保存できたと読めてしまうので、失敗はtoastで別に名乗る。
    statusEl.textContent = err.message;
    showError(err, "設定の保存");
  } finally {
    saveBtn.disabled = false;
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
    // 一覧を取れないとselectが空のまま。buttonを押せるままにすると、値が無いので
    // 即returnして完全な無反応になる(0件のときと同じ扱いへ倒す)。
    previewStatusEl.textContent = "録画一覧を取得できませんでした。";
    previewStillBtn.disabled = true;
    previewClipBtn.disabled = true;
    showError(err, "プレビュー用の録画一覧");
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
      + (res.comments_drawn ? "" : " / この時刻に表示中のコメントはありません");
    previewStatusEl.textContent = "生成しました。";
  } catch (err) {
    // 前回の画像を残したまま失敗文言だけ差し替えると、古い絵を新しい結果として読む。
    previewOutputEl.innerHTML = "";
    previewMetaEl.textContent = "";
    previewStatusEl.textContent = err.message;
    showError(err, "静止画プレビュー");
  } finally {
    previewStillBtn.disabled = false;
  }
});

previewClipBtn.addEventListener("click", async () => {
  const id = previewSelect.value;
  if (!id) return;
  previewClipBtn.disabled = true;
  // 投入の成否が確定してから名乗る。応答の前に「投入しました」と書くと、失敗したときに
  // 一度成功を告げてから小さく差し替わることになる。
  previewStatusEl.textContent = "queueへ投入中…";
  try {
    const res = await apiSend("POST", `/api/recordings/${id}/preview/clip`);
    previewJobs.set(res.job_id, id);
    previewStatusEl.textContent = "queueへ投入しました。順番が来ると焼き込みが始まります。";
    showToast("プレビュー動画をqueueへ投入しました。順番が来ると焼き込みが始まります。",
      null, { title: "焼き込みプレビュー" });
  } catch (err) {
    previewStatusEl.textContent = err.message;
    showError(err, "プレビュー動画の生成");
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

// ---- 通知の宛先 ----
// URLはserverがredactした状態で返る(画面に投稿tokenを出さない)。テスト送信は実際にwebhookへ
// 投げた結果をそのまま出す: 「積めた」ではなく「届いた」を確かめるための画面である。
const notifyStatusEl = document.getElementById("notify-status");
const notifySummaryEl = document.getElementById("notify-summary");
const notifyListEl = document.getElementById("notify-target-list");
const notifyTestBtn = document.getElementById("notify-test");

function renderNotifyTargets(targets, results) {
  const byTarget = new Map((results || []).map((r) => [r.target, r]));
  notifyListEl.innerHTML = "";
  document.getElementById("notify-target-empty").classList.toggle("hidden", targets.length > 0);
  targets.forEach((target) => {
    const row = document.createElement("tr");
    const result = byTarget.get(target.url);
    let outcome = "-";
    if (result) {
      outcome = result.ok ? `送信成功 (HTTP ${result.status})` : `失敗: ${result.error || result.status}`;
    }
    [target.url, target.format, outcome].forEach((text) => {
      const cell = document.createElement("td");
      cell.textContent = text;
      row.appendChild(cell);
    });
    notifyListEl.appendChild(row);
  });
}

async function loadNotifyStatus(results) {
  try {
    const res = await fetch("/api/notify/status");
    if (!res.ok) throw new Error("通知状態の取得に失敗しました。");
    const data = await res.json();
    notifySummaryEl.textContent =
      `通知: ${data.enabled ? "有効" : "無効"} / 宛先 ${data.targets.length} 件`
      + ` / 送信 ${fmtNum(data.sent)} 件・失敗 ${fmtNum(data.failed)} 件`
      + ` / 送信待ち ${fmtNum(data.queued)} 件`
      + (data.dropped ? ` / queue溢れで破棄 ${fmtNum(data.dropped)} 件` : "");
    renderNotifyTargets(data.targets, results);
  } catch (err) {
    notifySummaryEl.textContent = err.message;
  }
}

notifyTestBtn.addEventListener("click", async () => {
  notifyTestBtn.disabled = true;
  notifyStatusEl.textContent = "送信中…";
  try {
    const res = await apiSend("POST", "/api/notify/test");
    const failed = (res.results || []).filter((r) => !r.ok).length;
    const text = failed
      ? `${failed} 件の宛先へ送信できませんでした。`
      : "送信しました。宛先側で受信を確認してください。";
    notifyStatusEl.textContent = text;
    // 宛先の一部が落ちるのはこの操作の主たる結果。全成功と同じ色・同じ大きさで出ると
    // 「送れた」と読める。
    showToast(text, failed ? "error" : null, { title: "テスト通知" });
    await loadNotifyStatus(res.results);
  } catch (err) {
    notifyStatusEl.textContent = err.message;
    showError(err, "テスト通知");
    await loadNotifyStatus();
  } finally {
    notifyTestBtn.disabled = false;
  }
});

loadSettings();
loadNotifyStatus();
connectWS((msg) => {
  if (msg.type === "jobs") (msg.data || []).forEach(applyPreviewJob);
  else if (msg.type === "job_update" && msg.job) applyPreviewJob(msg.job);
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
    // 前回のplanを残すと、それを今回の対象と読んだまま「削除する」へ進める動線になる。
    retentionPlanEl.innerHTML = "";
    retentionStatusEl.textContent = err.message;
    showError(err, "削除内容の確認");
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
    const text =
      `${fmtNum(res.result.removed_items)} 件・${fmtBytesGb(res.result.freed_bytes)} を削除しました。`
      + (res.result.stopped_at ? "（空き容量が目標に達したため途中で打ち切りました）" : "");
    retentionStatusEl.textContent = text;
    showToast(text, null, { title: "保持policyの適用" });
    loadDiskBar();
  } catch (err) {
    // 取り消せない削除の失敗を、成功と同色のmutedな1行だけで済ませない。
    // apply側は「削除内容を確認」からやり直す必要があるので、押せないまま残すのが正しい。
    retentionStatusEl.textContent = err.message;
    showError(err, "保持policyの適用");
  } finally {
    retentionPreviewBtn.disabled = false;
  }
});

// ---- DBの保守 ----
// 退避・健全性check・WAL checkpoint・VACUUMの手動導線。実行結果はops_eventsにも残るので、
// 経緯は運用log画面で追える。
const MAINTENANCE_REASONS = { manual: "手動", premigration: "migration前" };

function maintenanceButtons() {
  return ["mnt-backup", "mnt-integrity", "mnt-checkpoint", "mnt-vacuum"]
    .map((id) => document.getElementById(id));
}

function setMaintenanceBusy(busy, text) {
  maintenanceButtons().forEach((btn) => { btn.disabled = busy; });
  const el = document.getElementById("mnt-status");
  el.removeAttribute("title");
  el.textContent = text || "";
}

function renderMaintenance(data) {
  const db = data.db || {};
  const parts = [
    `DB ${fmtGb(db.bytes)}GB / WAL ${fmtGb(db.wal_bytes)}GB`,
    `空き ${fmtGb(db.free_bytes)}GB`,
    `退避先 ${data.backup_dir}`,
    `保持世代 ${data.keep === 0 ? "無制限" : `${fmtNum(data.keep)}世代`}（種別ごと）`,
  ];
  if (!data.before_migration) {
    // 既定はONなので、OFFであることは表示しないと気付けない。
    parts.push("migration前の自動退避: 無効");
  }
  document.getElementById("mnt-summary").textContent = parts.join(" / ");

  const tbody = document.getElementById("mnt-rows");
  tbody.replaceChildren();
  (data.backups || []).forEach((item) => {
    const tr = document.createElement("tr");
    [
      { value: item.name, cls: "ident" },
      { value: MAINTENANCE_REASONS[item.reason] || item.reason },
      { value: fmtDateTime(item.created_at) },
      { value: `${fmtGb(item.bytes)}GB` },
    ].forEach(({ value, cls }) => {
      const td = document.createElement("td");
      if (cls) td.className = cls;
      td.textContent = value;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  setListState(document.getElementById("mnt-empty"),
    tbody.childElementCount === 0 ? "empty" : "ok");
}

async function loadMaintenance() {
  try {
    renderMaintenance(await apiSend("GET", "/api/maintenance/status"));
  } catch (err) {
    // 一覧を空で描くと「退避が1つも無い」と読めてしまう。取得できなかったことを出す。
    setListState(document.getElementById("mnt-empty"), "failed", err);
    document.getElementById("mnt-summary").textContent = "";
  }
}

// labelは操作の名前。保守は完了まで数分かかることがあり、その間に別の画面を見ていても
// 結果はtoastで届く。どの保守の結果なのかを名乗らせないと、戻ってきたとき対応が取れない。
async function runMaintenance(path, body, running, done, label) {
  setMaintenanceBusy(true, running);
  try {
    const result = await apiSend("POST", path, body);
    showToast(done(result), null, { title: label });
  } catch (err) {
    showError(err, label);
    setMaintenanceBusy(false, "");
    await loadMaintenance();
    return;
  }
  setMaintenanceBusy(false, "");
  await loadMaintenance();
}

document.getElementById("mnt-backup").addEventListener("click", () => runMaintenance(
  "/api/maintenance/backup", undefined, "退避中…（DBの大きさに応じて時間がかかります）",
  (data) => `退避しました: ${data.backup.name}（${fmtGb(data.backup.bytes)}GB）`,
  "DBの退避",
));

document.getElementById("mnt-integrity").addEventListener("click", () => runMaintenance(
  "/api/maintenance/integrity-check", undefined, "健全性checkを実行中…",
  (data) => data.ok
    ? "健全性check: 問題は見つかりませんでした。"
    : `健全性check: ${fmtNum(data.problems.length)}件の問題を検出しました。詳細は運用log画面で確認してください。`,
  "健全性check",
));

document.getElementById("mnt-checkpoint").addEventListener("click", () => runMaintenance(
  "/api/maintenance/checkpoint", undefined, "WAL checkpointを実行中…",
  (data) => data.busy === 0
    ? `WALを書き戻しました（WAL ${fmtGb(data.wal_bytes)}GB）`
    : `WALの一部は書き戻せませんでした（読み取り中の処理があります。WAL ${fmtGb(data.wal_bytes)}GB）`,
  "WAL checkpoint",
));

document.getElementById("mnt-vacuum").addEventListener("click", async () => {
  const ok = await confirmDialog(
    "VACUUMはDB fileを作り直します。実行中は収集を含む全ての書き込みが待たされ、"
    + "DBとほぼ同じ大きさの一時領域も必要です。配信の収集中は避けてください。",
    { title: "VACUUMを実行しますか？", confirmLabel: "VACUUMを実行" },
  );
  if (!ok) return;
  await runMaintenance(
    "/api/maintenance/vacuum", { confirm: true }, "VACUUMを実行中…（書き込みは待たされます）",
    (data) => `VACUUMが完了しました（${fmtGb(data.freed_bytes)}GB回収 / ${fmtGb(data.bytes_after)}GB）`,
    "VACUUM",
  );
});

loadMaintenance();

// ===== shortの型 =====
// 型は設定表(settings)ではなく別の表なので、この節だけは値の保存も別経路になる。設定表と
// 同じ格子(.settings-form)を使うのは見た目の統一のためで、保存bottonは型ごとに1つ持つ。

const shortPresetList = document.getElementById("short-preset-list");
const shortPresetStatus = document.getElementById("short-preset-status");
let shortPresetFields = {};

function shortPresetInput(key, spec, value) {
  const input = document.createElement("input");
  input.dataset.presetKey = key;
  if (spec.type === "bool") {
    input.type = "checkbox";
    input.checked = Boolean(Number(value));
    return input;
  }
  input.type = "number";
  // 値域はserverの1箇所(PRESET_FIELDS)から来る。画面が別の範囲を持つと、通したのに
  // 保存で弾かれる項目が生まれる。
  input.min = spec.min;
  input.max = spec.max;
  input.step = "0.05";
  input.value = value;
  return input;
}

function shortPresetValues(block) {
  const values = {};
  block.querySelectorAll("[data-preset-key]").forEach((input) => {
    const key = input.dataset.presetKey;
    values[key] = input.type === "checkbox" ? (input.checked ? 1 : 0) : Number(input.value);
  });
  return values;
}

function renderShortPreset(preset) {
  const block = document.createElement("div");
  block.className = "settings-form";
  block.dataset.presetId = String(preset.id);

  const head = document.createElement("div");
  head.className = "s-section";
  const name = document.createElement("input");
  name.type = "text";
  name.value = preset.name;
  name.setAttribute("aria-label", "型の名前");
  const save = document.createElement("button");
  save.className = "btn btn-small btn-primary";
  save.textContent = "この型を保存";
  const remove = document.createElement("button");
  remove.className = "btn btn-small btn-danger";
  remove.textContent = "削除";
  head.append(name, save, remove);
  block.appendChild(head);

  Object.entries(shortPresetFields).forEach(([key, spec]) => {
    const label = document.createElement("div");
    label.className = "s-cell s-label";
    label.textContent = spec.label;
    const control = document.createElement("div");
    control.className = "s-cell s-control";
    control.appendChild(shortPresetInput(key, spec, preset[key]));
    const note = document.createElement("div");
    note.className = "s-cell s-note";
    note.textContent = spec.note || "";
    block.append(label, control, note);
  });

  save.addEventListener("click", async () => {
    save.disabled = true;
    try {
      await apiSend("PATCH", `/api/clip-presets/${preset.id}`,
        { name: name.value, values: shortPresetValues(block) });
      shortPresetStatus.textContent = `「${name.value}」を保存しました。`;
      // #short-preset-statusはcard冒頭の「型を追加」行にある。型が数個並ぶと押したbuttonと
      // 結果表示が画面外に離れるので、結末はtoastでも名乗る。
      showToast(`「${name.value}」を保存しました。`, null, { title: "shortの型" });
      await loadShortPresets();
    } catch (err) {
      // 弾かれた理由をそのまま出す。丸めて保存されるより、入れた値が残って理由が読める方
      // が直せる(値域を外れた値はserverが丸めずに弾く)。
      shortPresetStatus.textContent = err.message;
      showError(err, `shortの型「${name.value}」の保存`);
    } finally {
      save.disabled = false;
    }
  });
  remove.addEventListener("click", async () => {
    const ok = await confirmDialog(
      `「${preset.name}」を削除します。この型で作った成果物は残ります。`,
      { title: "shortの型を削除しますか？", confirmLabel: "削除" });
    if (!ok) return;
    try {
      await apiSend("DELETE", `/api/clip-presets/${preset.id}`);
      shortPresetStatus.textContent = `「${preset.name}」を削除しました。`;
      await loadShortPresets();
    } catch (err) {
      // 失敗すると型のblockは残る。「消えていない＝押せていない」と読んで押し直すので、
      // 消えなかった理由を押した場所から離れないtoastで出す。
      shortPresetStatus.textContent = err.message;
      showError(err, `shortの型「${preset.name}」の削除`);
    }
  });
  return block;
}

async function loadShortPresets() {
  const empty = document.getElementById("short-preset-empty");
  setListState(empty, "loading");
  let data;
  try {
    data = await apiSend("GET", "/api/clip-presets");
  } catch (err) {
    setListState(empty, "failed", err);
    return;
  }
  shortPresetFields = data.fields || {};
  shortPresetList.innerHTML = "";
  (data.presets || []).forEach((preset) => {
    shortPresetList.appendChild(renderShortPreset(preset));
  });
  setListState(empty, (data.presets || []).length ? "ok" : "empty");
}

document.getElementById("short-preset-add").addEventListener("click", async () => {
  const input = document.getElementById("short-preset-name");
  try {
    // 尺だけは必須なので、新規作成は最初の型の値ではなく素の値で作る。既存の型を写すと
    // 「どの型を写したか」が名前からは読めない複製が増える。
    await apiSend("POST", "/api/clip-presets", {
      name: input.value,
      values: { min_seconds: 15, target_seconds: 30, max_seconds: 60 },
    });
    input.value = "";
    shortPresetStatus.textContent = "型を追加しました。下の欄で値を調整してください。";
    await loadShortPresets();
  } catch (err) {
    shortPresetStatus.textContent = err.message;
    showError(err, "shortの型の追加");
  }
});

loadShortPresets();
