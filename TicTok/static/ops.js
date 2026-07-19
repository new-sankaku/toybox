"use strict";

// 運用log画面: ops_events表を時系列で読む。録画失敗・接続断・設定変更・jobの開始完了が
// この表に貯まっている唯一の読み出し口で、text logをgrepせずに「昨夜なにが壊れたか」を
// 追うための画面。
// ページングはkeyset(最後の行のts+id)で行う。この表は末尾に行が増え続けるため、offsetでは
// 読み込み中に新しい行が入るたび境界の行が重複・欠落する。

const SEVERITY_LABELS = {
  error: { text: "error", cls: "badge-error" },
  warning: { text: "warning", cls: "badge-idle" },
  info: { text: "info", cls: "badge-idle" },
};

const OPS_KIND_WINDOW_HOURS = 24 * 30;

let nextPage = null;
let settingsOnly = false;
let detailMaxChars = 0;
let settingsKind = "";

function opsFilters() {
  const params = new URLSearchParams();
  const severity = document.getElementById("flt-severity").value;
  const kind = document.getElementById("flt-kind").value;
  const unique = document.getElementById("flt-unique").value.trim();
  const job = document.getElementById("flt-job").value.trim();
  const since = document.getElementById("flt-since").value;
  const until = document.getElementById("flt-until").value;
  if (severity) params.set("severity", severity);
  if (settingsOnly) params.set("kind_prefix", settingsKind);
  else if (kind) params.set("kind_prefix", kind);
  if (unique) params.set("unique_id", unique.replace(/^@/, ""));
  if (job) params.set("job_id", job);
  if (since) params.set("since", String(new Date(`${since}T00:00:00`).getTime() / 1000));
  if (until) params.set("until", String(new Date(`${until}T23:59:59`).getTime() / 1000));
  return params;
}

function severityCell(event) {
  const meta = SEVERITY_LABELS[event.severity] || { text: event.severity, cls: "badge-idle" };
  const span = document.createElement("span");
  span.className = `badge ${meta.cls}`;
  span.textContent = meta.text;
  return span;
}

function targetText(event) {
  const parts = [];
  if (event.unique_id) parts.push(`@${event.unique_id}`);
  if (event.session_id) {
    // ops_eventsはFKを張らずsession削除後も残る。sessionが消えた行はunique_idが引けない
    // ので、そのことを明示する(空欄にすると記録漏れと見分けが付かない)。
    parts.push(event.session_unique_id
      ? `session #${event.session_id}`
      : `session #${event.session_id}（削除済み）`);
  }
  if (event.recording_id) {
    parts.push(event.recording_filename || `録画 #${event.recording_id}`);
  }
  return parts.join(" / ") || "-";
}

function durationText(event) {
  if (event.duration_ms === null || event.duration_ms === undefined) return "-";
  return fmtDuration(event.duration_ms / 1000);
}

function settingsDiffNode(detail) {
  // 設定変更は「時刻・項目・旧値→新値」の3点だけを持つ(本toolは無認証の単一operator toolで
  // actor列が無く、誰が変えたかは原理的に記録できない)。
  const changes = detail && detail.changes;
  if (!changes || typeof changes !== "object") return null;
  const list = document.createElement("ul");
  list.className = "ops-diff";
  Object.keys(changes).sort().forEach((key) => {
    const pair = changes[key];
    const li = document.createElement("li");
    li.textContent = Array.isArray(pair)
      ? `${key}: ${pair[0]} → ${pair[1]}`
      : `${key}: ${pair}`;
    list.appendChild(li);
  });
  return list;
}

function detailNode(event) {
  const wrap = document.createElement("div");
  wrap.className = "ops-detail";
  const diff = settingsDiffNode(event.detail);
  if (diff) wrap.appendChild(diff);
  const pre = document.createElement("pre");
  pre.textContent = JSON.stringify(event.detail || {}, null, 2);
  wrap.appendChild(pre);
  if (event.detail && event.detail.truncated_chars) {
    const note = document.createElement("div");
    note.className = "chart-note";
    note.textContent =
      `詳細は保存時に ${fmtNum(detailMaxChars)} 文字で切られています（残り ${fmtNum(event.detail.truncated_chars)} 文字）。`
      + ` 全文は logs folder のtext log（ops_id: ${event.ops_id}）を参照してください。`;
    wrap.appendChild(note);
  }
  const ids = document.createElement("div");
  ids.className = "chart-note";
  ids.textContent = `ops_id: ${event.ops_id}` + (event.job_id ? ` / job_id: ${event.job_id}` : "");
  wrap.appendChild(ids);
  return wrap;
}

function appendRow(tbody, event) {
  const tr = document.createElement("tr");
  const detailTr = document.createElement("tr");
  detailTr.className = "hidden";
  const detailTd = document.createElement("td");
  detailTd.colSpan = 7;
  detailTd.appendChild(detailNode(event));
  detailTr.appendChild(detailTd);

  const toggle = document.createElement("button");
  toggle.className = "btn btn-small";
  toggle.textContent = "詳細";
  toggle.addEventListener("click", () => detailTr.classList.toggle("hidden"));

  const cells = [
    { value: fmtDateTime(event.ts) },
    { value: severityCell(event), cls: "ident" },
    { value: event.kind, cls: "ident" },
    { value: targetText(event) },
    { value: event.message || "" },
    { value: durationText(event) },
    { value: toggle },
  ];
  cells.forEach(({ value, cls }) => {
    const td = document.createElement("td");
    if (cls) td.className = cls;
    if (value instanceof Node) td.appendChild(value);
    else td.textContent = value;
    tr.appendChild(td);
  });
  tbody.append(tr, detailTr);
}

async function loadEvents(append) {
  const params = opsFilters();
  if (append && nextPage) {
    params.set("before_ts", String(nextPage.before_ts));
    params.set("before_id", String(nextPage.before_id));
  }
  const statusEl = document.getElementById("ops-status");
  const emptyEl = document.getElementById("ops-empty");
  statusEl.removeAttribute("title");
  statusEl.textContent = LIST_LOADING_TEXT;
  if (!append) setListState(emptyEl, "loading");
  let data;
  try {
    data = await apiSend("GET", `/api/ops/events?${params.toString()}`);
  } catch (err) {
    if (append) {
      // 既に読めている行は残っているので、失敗しているのは続きの取得だけ。
      // 「さらに読み込む」は再試行の導線として残す。
      statusEl.textContent = "続きを取得できませんでした（この先に記録が無いという意味ではありません）。";
      statusEl.title = errorDetailText(err);
    } else {
      // 表示中の行は前のfilterの結果。今のfilterのものとして残すと、取得できていない
      // 条件の記録を出しているように見える。
      document.getElementById("ops-rows").replaceChildren();
      nextPage = null;
      statusEl.textContent = "";
      setListState(emptyEl, "failed", err);
      document.getElementById("ops-more").classList.add("hidden");
    }
    return;
  }
  detailMaxChars = data.detail_max_chars || 0;
  settingsKind = data.settings_kind || settingsKind;
  nextPage = data.next;
  const tbody = document.getElementById("ops-rows");
  if (!append) tbody.replaceChildren();
  (data.events || []).forEach((event) => appendRow(tbody, event));
  setListState(emptyEl, tbody.childElementCount === 0 ? "empty" : "ok");
  document.getElementById("ops-more").classList.toggle("hidden", !nextPage);
  statusEl.textContent = `保持期間: ${data.retention_days}日`;
}

async function loadKinds() {
  const select = document.getElementById("flt-kind");
  let data;
  try {
    data = await apiSend("GET", `/api/ops/kinds?hours=${OPS_KIND_WINDOW_HOURS}`);
  } catch (err) {
    // 候補が引けないだけで一覧は読める。選択肢を捏造せず「全て」のままにする。
    return;
  }
  (data.kinds || []).forEach((entry) => {
    const option = document.createElement("option");
    option.value = entry.kind;
    option.textContent = `${entry.kind}（${fmtNum(entry.count)}）`;
    select.appendChild(option);
  });
}

async function loadSummary() {
  const el = document.getElementById("ops-summary");
  try {
    const data = await apiSend("GET", "/api/ops/summary");
    const counts = data.counts || {};
    el.textContent = `直近${Math.round(data.window_hours)}時間: error ${fmtNum(counts.error)}`
      + ` / warning ${fmtNum(counts.warning)} / info ${fmtNum(counts.info)}`;
    el.removeAttribute("title");
  } catch (err) {
    el.textContent = "件数を取得できませんでした（0件という意味ではありません）。";
    el.title = errorDetailText(err);
  }
}

document.getElementById("flt-apply").addEventListener("click", () => {
  settingsOnly = false;
  loadEvents(false);
});

document.getElementById("flt-settings").addEventListener("click", () => {
  settingsOnly = true;
  document.getElementById("flt-kind").value = "";
  document.getElementById("flt-severity").value = "";
  loadEvents(false);
});

document.getElementById("flt-reset").addEventListener("click", () => {
  settingsOnly = false;
  ["flt-severity", "flt-kind", "flt-unique", "flt-job", "flt-since", "flt-until"]
    .forEach((id) => { document.getElementById(id).value = ""; });
  loadEvents(false);
});

document.getElementById("ops-more").addEventListener("click", () => loadEvents(true));

loadKinds();
loadSummary();
loadEvents(false);
connectWS(() => {});
