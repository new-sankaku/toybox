"use strict";

// 運用log画面: ops_events表を時系列で読む。録画失敗・接続断・設定変更・jobの開始完了が
// この表に貯まっている唯一の読み出し口で、text logをgrepせずに「昨夜なにが壊れたか」を
// 追うための画面。
// ページングはkeyset(最後の行のts+id)で行う。この表は末尾に行が増え続けるため、offsetでは
// 読み込み中に新しい行が入るたび境界の行が重複・欠落する。

const SEVERITY_LABELS = {
  error: { text: "error", cls: "ops-sev-error" },
  warning: { text: "warning", cls: "ops-sev-warning" },
  info: { text: "info", cls: "ops-sev-info" },
};

let nextPage = null;
let detailMaxChars = 0;
// kind(collector.disconnected)→日本語ラベルの対応表。Server側(core/ops_labels.py)が唯一の
// 出所で、画面は受け取って引くだけにする。同じ訳語をFrontendにも置くと必ずずれる。
let kindLabels = {};

// 表に無いkindは生値をそのまま出す。それらしいラベルを組み立てると、記録に無い名前が画面に
// 出て、text logと突き合わせられなくなる。
function kindText(kind) {
  return kindLabels[kind] || kind;
}

function opsFilters() {
  const params = new URLSearchParams();
  const severity = document.getElementById("flt-severity").value;
  const kind = document.getElementById("flt-kind").value;
  const unique = document.getElementById("flt-unique").value;
  const job = document.getElementById("flt-job").value.trim();
  const since = document.getElementById("flt-since").value;
  const until = document.getElementById("flt-until").value;
  // 閾値での絞り込み。1段だけを見るseverityとは別のparameterで、Server側が順序を持つ。
  if (severity) params.set("min_severity", severity);
  if (kind) params.set("kind_prefix", kind);
  if (unique) params.set("unique_id", unique);
  if (job) params.set("job_id", job);
  if (since) params.set("since", String(new Date(`${since}T00:00:00`).getTime() / 1000));
  if (until) params.set("until", String(new Date(`${until}T23:59:59`).getTime() / 1000));
  return params;
}

function severityCell(event) {
  const meta = SEVERITY_LABELS[event.severity] || { text: event.severity, cls: "ops-sev-info" };
  const span = document.createElement("span");
  span.className = `ops-sev ${meta.cls}`;
  span.textContent = meta.text;
  return span;
}

// 時刻は月日から出す。この画面は1行=1件のlogを縦に追う表で、全行に同じ年が並ぶと
// 桁が増えるだけで読む助けにならない。年を含む完全な日時はcellのtooltipで読める。
function opsTimeText(ts) {
  if (!ts) return "-";
  const d = new Date(ts * 1000);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}/${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
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
  // 重要度は色でも読めるようにする。error/warningを本文の中から目で拾うのは、
  // 数十行が並ぶ表では現実的でない。
  tr.className = `sev-${event.severity}`;
  // 1件=2行(本体+詳細)で組むため、縞はCSSのnth-childでは付けられない(本体行が常に奇数
  // 番目になり全行が同じ色になる)。件数から数えてclassで付ける。
  if (Math.floor(tbody.childElementCount / 2) % 2 === 1) tr.classList.add("ops-row-alt");

  const detailTr = document.createElement("tr");
  detailTr.className = "ops-detail-row hidden";
  const detailTd = document.createElement("td");
  detailTd.colSpan = 7;
  detailTd.appendChild(detailNode(event));
  detailTr.appendChild(detailTd);

  // 行あたりの高さがそのまま1画面に入る件数になるので、開閉は1文字ぶんに収める。
  // 何のButtonかは列header(詳細)が示し、開いている行はaria-expandedのstyleで判る。
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "btn btn-compact ops-toggle";
  toggle.textContent = "▸";
  toggle.title = "詳細を開く";
  toggle.setAttribute("aria-expanded", "false");
  toggle.addEventListener("click", () => {
    const open = !detailTr.classList.toggle("hidden");
    toggle.textContent = open ? "▾" : "▸";
    toggle.title = open ? "詳細を閉じる" : "詳細を開く";
    toggle.setAttribute("aria-expanded", String(open));
  });

  const cells = [
    // 開閉は左端。行の先頭に置くと、開いている行と閉じている行が縦一列で見分けられる。
    { value: toggle, cls: "act" },
    { value: opsTimeText(event.ts), cls: "ops-ts", title: fmtDateTime(event.ts) },
    { value: severityCell(event), cls: "ident" },
    // 種別は日本語で出し、記録上のkey(collector.disconnected)はtooltipに残す。
    { value: kindText(event.kind), cls: "ident ops-kind", title: event.kind },
    // 対象は識別子(＠id・session・File名)の列。語中で割ると別のFile名に読めるうえ、
    // 内容列が余りを取る組み方では1文字ずつの縦棒まで潰れる。
    { value: targetText(event), cls: "ident ops-target" },
    { value: event.message || "", cls: "ops-msg" },
    { value: durationText(event), cls: "num ops-dur" },
  ];
  cells.forEach(({ value, cls, title }) => {
    const td = document.createElement("td");
    if (cls) td.className = cls;
    if (title) td.title = title;
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
  // 一覧のkindは保持期間ぶん(候補より広い)あり得るので、こちらの表も取り込んでおく。
  if (data.kind_labels) kindLabels = data.kind_labels;
  nextPage = data.next;
  const tbody = document.getElementById("ops-rows");
  if (!append) tbody.replaceChildren();
  (data.events || []).forEach((event) => appendRow(tbody, event));
  setListState(emptyEl, tbody.childElementCount === 0 ? "empty" : "ok");
  document.getElementById("ops-more").classList.toggle("hidden", !nextPage);
  statusEl.textContent = `保持期間: ${data.retention_days}日`;
}

// 種別・配信者の候補。観測窓は指定しない(全期間)。窓を切ると、保持期間内に記録がある
// のに候補に出ないkind/配信者が生まれ、「表に居るのに絞り込めない」状態になる。
// ops_eventsは状態遷移だけの表なので、全期間のGROUP BYでも軽い。
async function loadFilterOptions() {
  const kindSelect = document.getElementById("flt-kind");
  const uniqueSelect = document.getElementById("flt-unique");
  let data;
  try {
    data = await apiSend("GET", "/api/ops/kinds");
  } catch (err) {
    // 候補が引けないだけで一覧は読める。選択肢を捏造せず「すべて」のままにする。
    return;
  }
  kindLabels = data.kind_labels || {};
  (data.kinds || []).forEach((entry) => {
    const option = document.createElement("option");
    option.value = entry.kind;
    option.textContent = `${kindText(entry.kind)}（${fmtNum(entry.count)}）`;
    // 種別を日本語にすると記録上のkeyが画面から消える。text logと突き合わせられるよう残す。
    option.title = entry.kind;
    kindSelect.appendChild(option);
  });
  (data.unique_ids || []).forEach((entry) => {
    const option = document.createElement("option");
    option.value = entry.unique_id;
    option.textContent = `@${entry.unique_id}（${fmtNum(entry.count)}）`;
    uniqueSelect.appendChild(option);
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

document.getElementById("flt-apply").addEventListener("click", () => loadEvents(false));
// 選択式の条件は選んだ時点で意図が確定する。「絞り込む」を押し忘れて古い結果を今の条件の
// ものとして読む事故を防ぐ(自由入力のjob IDと期間は打ち終わりが判らないのでButton側)。
["flt-severity", "flt-kind", "flt-unique"].forEach((id) => {
  document.getElementById(id).addEventListener("change", () => loadEvents(false));
});

document.getElementById("flt-reset").addEventListener("click", () => {
  ["flt-severity", "flt-kind", "flt-unique", "flt-job", "flt-since", "flt-until"]
    .forEach((id) => { document.getElementById(id).value = ""; });
  loadEvents(false);
});

document.getElementById("ops-more").addEventListener("click", () => loadEvents(true));

loadFilterOptions();
loadSummary();
loadEvents(false);
// jobの進捗はJob画面が持つ。この画面はWSを接続表示とtopbarのjob badgeのためだけに使う。
connectWS(() => {});
