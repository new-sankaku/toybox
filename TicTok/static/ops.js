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
// 表に出ている一番新しい行と、それを描いたときの条件。新着の数え合わせに使う。
// 0件の一覧でもidはnullのまま条件だけ控える(「まだ読んでいない」と「読んだが0件だった」は
// 別物で、後者では次に入った記録がすべて新着になる)。
let topEventId = null;
let topEventFilter = null;
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
  // 種別・配信者は選択肢がserverの応答から生えるまでselectへ入れられない。まだ預かって
  // いる保存値(pendingKind/pendingUnique)は、selectより先にこちらを条件へ載せる。
  const kind = pendingKind || document.getElementById("flt-kind").value;
  const unique = pendingUnique || document.getElementById("flt-unique").value;
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
// 実装はcommon.jsのfmtDateTimeShortが持つ(Job画面と同じ書式であることが要件なので、
// 同じ物を2箇所に置かない)。

// 対象は「何が起きたか」の次に辿る先でもある。文字列だけだと、番号を控えて履歴画面で
// 探し直すことになるので、飛べるものはlinkにする。
function targetNode(event) {
  const parts = [];
  if (event.unique_id) parts.push(document.createTextNode(`@${event.unique_id}`));
  if (event.session_id) {
    // ops_eventsはFKを張らずsession削除後も残る。sessionが消えた行はunique_idが引けない
    // ので、そのことを明示する(空欄にすると記録漏れと見分けが付かない)。飛び先が無い
    // 削除済みsessionはlinkにしない(押して空の画面へ着くのは「消えた」より読みにくい)。
    const label = `session #${sessionNo(event.session_id)}`;
    if (event.session_unique_id) {
      const link = document.createElement("a");
      link.href = `/history?session=${event.session_id}`;
      link.textContent = label;
      parts.push(link);
    } else {
      parts.push(document.createTextNode(`${label}（削除済み）`));
    }
  }
  if (event.recording_id) {
    // 録画行が消えていればfile名は引けない。sessionと同じく「削除済み」と名乗る(番号が
    // 出せないからと空欄にすると、録画の記録が無かったのと見分けが付かない)。
    const name = recName({ filename: event.recording_filename, session_id: event.session_id });
    parts.push(document.createTextNode(name === "—" ? "録画（削除済み）" : `録画 ${name}`));
  }
  if (!parts.length) return document.createTextNode("-");
  const wrap = document.createElement("span");
  parts.forEach((node, i) => {
    if (i) wrap.append(document.createTextNode(" / "));
    wrap.append(node);
  });
  return wrap;
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
    note.textContent = `切り詰め +${fmtNum(event.detail.truncated_chars)} 文字`;
    wrap.appendChild(note);
  }
  const ids = document.createElement("div");
  ids.className = "chart-note";
  ids.append(document.createTextNode(`ops_id: ${event.ops_id}`));
  if (event.job_id) {
    // job_idは1回の処理に紐づく記録を束ねる唯一のkey。表示するだけだと、手で写して
    // job IDの条件へ貼ることになる。同じ画面で完結する絞り込みと、jobそのものの
    // 状態を見るJob画面の両方へ出す。
    ids.append(document.createTextNode(` / job_id: ${event.job_id} `));
    const only = document.createElement("button");
    only.type = "button";
    only.className = "btn btn-compact";
    only.textContent = "このjobだけ";
    only.addEventListener("click", () => {
      document.getElementById("flt-job").value = event.job_id;
      loadEvents(false);
    });
    ids.append(only, document.createTextNode(" "));
    const link = document.createElement("a");
    link.href = `/jobs?job=${encodeURIComponent(event.job_id)}`;
    link.textContent = "Job画面で開く";
    ids.append(link);
  }
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
    { value: fmtDateTimeShort(event.ts), cls: "ops-ts", title: fmtDateTime(event.ts) },
    { value: severityCell(event), cls: "ident" },
    // 種別は日本語で出し、記録上のkey(collector.disconnected)はtooltipに残す。
    { value: kindText(event.kind), cls: "ident ops-kind", title: event.kind },
    // 対象は識別子(＠id・session・File名)の列。語中で割ると別のFile名に読めるうえ、
    // 内容列が余りを取る組み方では1文字ずつの縦棒まで潰れる。
    { value: targetNode(event), cls: "ident ops-target" },
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
      statusEl.textContent = "続きを取得できませんでした。";
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
  // 一覧のkindは保持期間ぶん(候補より広い)あり得るので、こちらの表も取り込んでおく。
  if (data.kind_labels) kindLabels = data.kind_labels;
  nextPage = data.next;
  const tbody = document.getElementById("ops-rows");
  if (!append) {
    tbody.replaceChildren();
    // 新着の基準は「今この条件で描いた最新の行」。条件も一緒に控えておかないと、
    // 条件を変えた直後の数え合わせが別の一覧との比較になる。
    const events = data.events || [];
    topEventId = events.length ? events[0].id : null;
    topEventFilter = params.toString();
    setNewEventCount(0, false);
  }
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
    // 預かっている保存値も当てる先が無いので解く(条件だけが効いた状態を残さない)。
    applyPendingSelects();
    return;
  }
  kindLabels = data.kind_labels || {};
  // 種別は数十件ある。1枚のflatな一覧から目で拾うのは現実的でないので、kindの前半
  // (collector / overlay …)でまとめ、groupごとに「すべて」を置く。groupの見出しは
  // kindのそのままの前半にする: 日本語のgroup名をここで作ると、Server(core/ops_labels)が
  // 持たない訳語を画面が名乗ることになり、text logとの突き合わせもできなくなる。
  // APIの受け口は kind_prefix(前方一致)なので、値は "overlay." をそのまま渡せばよい。
  const groups = new Map();
  (data.kinds || []).forEach((entry) => {
    const domain = String(entry.kind).split(".")[0];
    const group = groups.get(domain) || { count: 0, kinds: [] };
    group.count += entry.count || 0;
    group.kinds.push(entry);
    groups.set(domain, group);
  });
  groups.forEach((group, domain) => {
    const optgroup = document.createElement("optgroup");
    optgroup.label = domain;
    const all = document.createElement("option");
    all.value = `${domain}.`;
    all.textContent = `${domain} すべて（${fmtNum(group.count)}）`;
    all.title = `${domain}. で始まる種別すべて`;
    optgroup.appendChild(all);
    group.kinds.forEach((entry) => {
      const option = document.createElement("option");
      option.value = entry.kind;
      option.textContent = `${kindText(entry.kind)}（${fmtNum(entry.count)}）`;
      // 種別を日本語にすると記録上のkeyが画面から消える。text logと突き合わせられるよう残す。
      option.title = entry.kind;
      optgroup.appendChild(option);
    });
    kindSelect.appendChild(optgroup);
  });
  (data.unique_ids || []).forEach((entry) => {
    const option = document.createElement("option");
    option.value = entry.unique_id;
    option.textContent = `@${entry.unique_id}（${fmtNum(entry.count)}）`;
    uniqueSelect.appendChild(option);
  });
  applyPendingSelects();
}

async function loadSummary() {
  const el = document.getElementById("ops-summary");
  try {
    // navのbadgeと同じ1本へ相乗りする(fetchOpsSummaryはcommon.js)。別々に引くと、
    // この画面を開くたびに同じrequestが2本並ぶ。
    const data = await fetchOpsSummary();
    const counts = data.counts || {};
    el.textContent = `${Math.round(data.window_hours)}h error ${fmtNum(counts.error)}`
      + ` / warn ${fmtNum(counts.warning)} / info ${fmtNum(counts.info)}`;
    el.removeAttribute("title");
  } catch (err) {
    el.textContent = "件数を取得できませんでした。";
    el.title = errorDetailText(err);
  }
}

// ---- 自動での数え直し --------------------------------------------------------------
// 件数(navのbadgeと同じAPI)は60秒ごとに増えるのに、一覧と画面上の件数は起動時のまま
// だった。同じ画面の中で「badgeは増えているのに表は増えない」状態を残さないよう、
// 件数はbadgeと同じ周期で取り直し、表は新着の数だけを出して押した時に入れ替える。

function setNewEventCount(count, atLeast) {
  const btn = document.getElementById("ops-reload");
  btn.textContent = count
    ? `最新にする（新着 ${fmtNum(count)}件${atLeast ? "以上" : ""}）`
    : "最新にする";
  btn.classList.toggle("btn-primary", count > 0);
}

async function pollOpsUpdates() {
  await loadSummary();
  const params = opsFilters();
  // 条件を変えた直後(まだ絞り込んでいない)は数え合わせの相手が居ない。前の条件の一覧と
  // 今の条件の件数を突き合わせると、出てもいない行を新着として数えることになる。
  if (topEventFilter === null || params.toString() !== topEventFilter) return;
  let data;
  try {
    data = await apiSend("GET", `/api/ops/events?${params.toString()}`);
  } catch (err) {
    // 取れなかっただけで「新着なし」ではない。数を作らず、前の表示のままにする。
    console.warn(`ops-reload: ${errorDetailText(err)}`, err);
    return;
  }
  const events = data.events || [];
  const index = topEventId === null
    ? -1
    : events.findIndex((event) => event.id === topEventId);
  if (index >= 0) {
    setNewEventCount(index, false);
    return;
  }
  // 基準の行が1ページに入っていない。ページを埋め切っているならこの先にも在り得るので
  // 「以上」と断る(ちょうどの数は1ページでは分からない)。
  setNewEventCount(events.length, events.length >= (data.limit || 0));
}

// ---- API所要時間 ------------------------------------------------------------------
// 「どの画面が重いか」はbrowserのdev toolでも見えるが、その時間がserverの中でDB照会・
// file走査・子processのどこへ消えたかはserver側にしか無い。ここはその内訳を読む口。

// msは桁が3つに跨る(0.4ms〜30,000ms)。同じ書式で並べると読めないので桁ごとに変える。
function fmtMs(ms) {
  const value = Number(ms || 0);
  if (value >= 10000) return `${(value / 1000).toFixed(1)}s`;
  if (value >= 100) return `${Math.round(value)}ms`;
  if (value >= 10) return `${value.toFixed(1)}ms`;
  return `${value.toFixed(2)}ms`;
}

// 内訳は合計時間の大きい順に上位だけ出す。全部並べるとcellが折り返して表が読めなくなる
// (計装の名前は増える一方で、割合の小さいものは判断に効かない)。
const PERF_BREAKDOWN_TOP = 4;

function perfBreakdownText(row) {
  const entries = Object.entries(row.phases || {})
    .map(([name, slot]) => [name, slot.ms])
    .filter(([, ms]) => ms > 0);
  const other = Math.max(0, row.total_ms - entries.reduce((sum, [, ms]) => sum + ms, 0));
  if (other > 0) entries.push(["other", other]);
  if (!entries.length) return "-";
  entries.sort((a, b) => b[1] - a[1]);
  return entries.slice(0, PERF_BREAKDOWN_TOP)
    .map(([name, ms]) => `${name} ${fmtMs(ms)}`).join(" / ");
}

async function loadPerf() {
  const note = document.getElementById("perf-note");
  const empty = document.getElementById("perf-empty");
  setListState(empty, "loading");
  let data;
  try {
    data = await apiSend("GET", "/api/perf");
  } catch (err) {
    document.getElementById("perf-rows").replaceChildren();
    setListState(empty, "failed", err);
    note.textContent = "";
    return;
  }
  const lag = data.loop_lag || {};
  const parts = [
    `計測 ${fmtDuration(data.window_seconds)}`,
    `${fmtNum(data.request_count)} request / 合計 ${fmtMs(data.total_ms)}`,
    // loopの遅れはrouteに紐付かない。1本のcoroutineがloopを握ると全画面が同時に遅く
    // なるので、route表とは別に出す。
    `loop停止 max ${fmtMs(lag.max_ms)} / 警告 ${fmtNum(lag.warned)}`,
  ];
  if (!data.enabled) parts.unshift("計測は無効");
  if ((data.inflight || []).length) parts.push(`処理中 ${fmtNum(data.inflight.length)}件`);
  note.textContent = parts.join(" / ");
  // renderTableRowsは表示/非表示しか触らないので、loading文言のまま0件になるのを戻す。
  setListState(empty, (data.routes || []).length ? "ok" : "empty");
  renderTableRows(
    "perf-rows", "perf-empty", data.routes || [],
    (row) => [
      row.route,
      fmtNum(row.count) + (row.failed ? `（失敗 ${fmtNum(row.failed)}）` : ""),
      fmtMs(row.total_ms),
      `${(row.share * 100).toFixed(1)}%`,
      fmtMs(row.avg_ms),
      fmtMs(row.p50_ms),
      fmtMs(row.p95_ms),
      fmtMs(row.max_ms),
      perfBreakdownText(row),
    ],
    [1, 2, 3, 4, 5, 6, 7],
  );
}

document.getElementById("perf-reload").addEventListener("click", () => loadPerf());
document.getElementById("perf-reset").addEventListener("click", async () => {
  const note = document.getElementById("perf-note");
  try {
    await apiSend("DELETE", "/api/perf");
  } catch (err) {
    note.textContent = "計測をresetできませんでした。";
    note.title = errorDetailText(err);
    showError(err, "API計測のreset");
    return;
  }
  note.removeAttribute("title");
  loadPerf();
});

// ---- 表示設定の永続化 ----
// 画面ごとに独立したdocumentで、nav遷移はフルリロードになる。重要度・種別・配信者は
// 毎回同じ値を選び直すものなので残す。job IDと期間(日付)は残さない — job IDは1回の処理を
// 指した一時的な対象指定で、日付は絶対値なので、残すと翌日には「新しい記録が出てこない
// 一覧」を今の全件として読むことになる。この画面の目的は新しい失敗に気付くことなので、
// 気付けない条件を既定にはしない。
const OPS_SEVERITY_PREF = "tictok.ops.severity";
const OPS_KIND_PREF = "tictok.ops.kind";
const OPS_UNIQUE_PREF = "tictok.ops.unique";
// 種別・配信者の選択肢は /api/ops/kinds から生えるので、この時点ではselectへ当てられない。
// 保存値を預かってopsFilters()へ先に載せる(選択肢が揃うのを待って当てると、初回の一覧を
// 条件無しで取ってから同じ物を絞り込みで取り直すことになる)。
let pendingKind = prefGet(OPS_KIND_PREF) || "";
let pendingUnique = prefGet(OPS_UNIQUE_PREF) || "";

// 預かった保存値をselectへ当てる。選択肢が消えていた場合(保持期間を過ぎて記録が無くなった
// 種別・監視から外れた配信者)は復元せず、その条件で取ってしまった一覧を取り直す。
// selectが「すべて」を指しているのに一覧だけが絞られている状態を残すと、条件に一致しなかった
// だけの空の表を「記録が無い」と読むことになる。
function applyPendingSelects() {
  const stale = [
    [document.getElementById("flt-kind"), OPS_KIND_PREF, pendingKind],
    [document.getElementById("flt-unique"), OPS_UNIQUE_PREF, pendingUnique],
  ].filter(([el, key, pending]) => pending && !restorePref(el, key));
  pendingKind = "";
  pendingUnique = "";
  if (stale.length) loadEvents(false);
}

// 保存はuser操作の時だけ。下のloadEvents側のlistenerより先に張って、預かりの解除が
// 取り直しより前に済むようにする。
bindPref(document.getElementById("flt-severity"), OPS_SEVERITY_PREF);
bindPref(document.getElementById("flt-kind"), OPS_KIND_PREF, () => { pendingKind = ""; });
bindPref(document.getElementById("flt-unique"), OPS_UNIQUE_PREF, () => { pendingUnique = ""; });

document.getElementById("flt-apply").addEventListener("click", () => loadEvents(false));
// 選択式の条件は選んだ時点で意図が確定する。「絞り込む」を押し忘れて古い結果を今の条件の
// ものとして読む事故を防ぐ(自由入力のjob IDと期間は打ち終わりが判らないのでButton側)。
["flt-severity", "flt-kind", "flt-unique"].forEach((id) => {
  document.getElementById(id).addEventListener("change", () => loadEvents(false));
});
// 自由入力もEnterで確定できるようにする。打ち終わりが判らないのでchangeでは走らせないが、
// 打ったあとmouseへ持ち替えさせる理由も無い(「絞り込む」は残す)。
["flt-job", "flt-since", "flt-until"].forEach((id) => {
  document.getElementById(id).addEventListener("keydown", (ev) => {
    if (ev.key !== "Enter") return;
    ev.preventDefault();
    loadEvents(false);
  });
});

document.getElementById("flt-reset").addEventListener("click", () => {
  ["flt-severity", "flt-kind", "flt-unique", "flt-job", "flt-since", "flt-until"]
    .forEach((id) => { document.getElementById(id).value = ""; });
  // 残している条件の保存値も一緒に落とす。値だけ戻して保存を残すと、次に開いた時に
  // 「条件をclear」したはずの絞り込みが復活する。
  pendingKind = "";
  pendingUnique = "";
  [OPS_SEVERITY_PREF, OPS_KIND_PREF, OPS_UNIQUE_PREF].forEach((key) => prefSet(key, null));
  loadEvents(false);
});

document.getElementById("ops-more").addEventListener("click", () => loadEvents(true));
document.getElementById("ops-reload").addEventListener("click", () => loadEvents(false));

loadFilterOptions();
loadSummary();
loadEvents(false);
loadPerf();
pollWhileVisible(pollOpsUpdates, OPS_BADGE_POLL_MS);
// jobの進捗はJob画面が持つ。この画面はWSを接続表示とtopbarのjob badgeのためだけに使う。
connectWS(() => {});
