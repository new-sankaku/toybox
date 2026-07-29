// 配信者動画: 複数配信を横断してシーンを探し、素材として切り出す編集アシスト画面。
// 検索hitはvideo_time(mp4のPTS秒)を持つのでそのままseekできる。

const PAGE_SIZE = 200;
const SEARCH_DEBOUNCE_MS = 250;
// IN/OUTを発話境界へ吸着させる許容幅。これを超えて離れていれば手打ちの位置を尊重する。
const SNAP_WINDOW_SECONDS = 1.5;
const FRAME_STEP_SECONDS = 1 / 30;
const FORWARD_RATES = [1, 1.5, 2, 4];
const REWIND_RATES = [2, 4, 8];
const REWIND_TICK_MS = 100;
// bar上端のこの帯だけをIN/OUT操作にあて、それより下は従来通りclick/dragで移動する。
// modifier方式は発見できず、touchでは押せないので採らない。
const RANGE_LANE_PX = 14;
const HANDLE_HIT_PX = 8;
const HANDLE_HIT_TOUCH_PX = 16;
const HANDLE_DRAW_PX = 6;
const PLAYHEAD_KNOB_PX = 5;
// bar下端のこの帯を見どころmarker専用にあてる。波形・heatと重ねると、どちらが記録した
// 位置なのか読めなくなる。
const BOOKMARK_LANE_PX = 8;
// bucket数はwaveform cacheのkeyに含まれる。canvas幅から導出すると窓を変える度に
// 録画全体のdecodeが走るので、固定値1本に統一して描画側で幅へ写像する。
const WAVE_BUCKETS = 2000;
const WAVE_PREF_KEY = "tictok.videos.showWave";
const VOLUME_PREF_KEY = "tictok.videos.volume";
const MUTE_PREF_KEY = "tictok.videos.muted";

const state = {
  query: "",
  offset: 0,
  total: 0,
  // 検索語なしで録画一覧を出している状態。hitsの中身がhitではなく録画になる。
  browsing: false,
  // serverから受け取った録画一覧の全件。hitsは確認状態の絞り込みを掛けた後の表示ぶんで、
  // 絞り込みを変えるたびに引き直さないための元data。
  browseAll: [],
  hits: [],
  hitIndex: -1,
  current: null,
  cutIn: null,
  cutOut: null,
  heat: null,
  wave: null,
  sprite: null,
  variants: [],
  // 開いている録画に実在する素材版のkind。再生できる版とsegmented controlの押せる範囲を
  // これ1つで決める(空 = まだ確定していない)。
  variantKinds: [],
  streamers: [],
  // 一括処理tab: 配信者別の対象数と、確認に出している投入内容。
  bulk: [],
  // これまでに集計を要求した種別。再mp4化は対象判定に録画ごとの.ts走査を伴うので、選ばれて
  // 初めて加える(既定のtab表示で走査を走らせない)。他種別へは常に即時で切り替わる。
  bulkKinds: ["overlay", "upscale", "audionorm"],
  bulkDisk: null,
  bulkPending: null,
  // 配信者画面から渡された絞り込み対象(unique_id)。nullなら全配信者。
  bulkOnly: null,
  // 録画一覧を開いている配信者(1人だけ)と、その録画・選択中のid。展開を複数開けるように
  // しないのは、選択が複数配信者に散らばると「何を投入するのか」が一目で読めなくなるため。
  bulkOpen: null,
  bulkOpenRows: null,
  bulkSelected: new Set(),
  // 投入結果や失敗の文言。空なら対象数の集計文を出す。
  bulkNote: "",
  segments: [],
  segmentIndex: -1,
  chapters: [],
  chapterIndex: -1,
  comments: [],
  commentIndex: -1,
  // 今開いている録画の見どころ(seek barのmarker用)と、全録画分の一覧(見どころtab用)。
  bookmarks: [],
  marks: [],
  selFrom: null,
  selTo: null,
  cuts: [],
  // 今開いている録画の切り出し候補と、その算出元になった録画id。
  candidates: [],
  candidateRecordingId: null,
};

let rewindTimer = null;
let rewindStep = -1;
let forwardStep = 0;

// heat bar上のdrag: null | "seek" | "in" | "out" | "band" | "new"
let dragMode = null;
let dragAnchor = 0;
let dragBandOffset = 0;
let dragBandLength = 0;

let searchTimer = null;

const $ = (id) => document.getElementById(id);

// ===== view切替 =====

const VIEWS = ["search", "marks", "cuts", "jobs", "bulk"];

// 配信者の選択はtabを跨いで引き継ぐ。3つのselectが独立していたため、
// tabを移るたび「今どの配信者の作業をしているか」を選び直す必要があった。
// cuts-streamerだけは候補が実在するcutに限られるので、無ければ「全て」へ落ちる。
const STREAMER_SELECTS = ["flt-streamer", "cuts-streamer"];

function shareStreamerSelection(fromId) {
  const value = $(fromId).value;
  STREAMER_SELECTS.forEach((id) => {
    const select = $(id);
    if (id === fromId) return;
    // 一致するoptionが無ければvalueは""(全て)になる。存在しない配信者は指させない。
    select.value = value;
  });
}

function showView(name) {
  VIEWS.forEach((view) => {
    $(`view-${view}`).classList.toggle("hidden", view !== name);
    $(`tab-${view}`).classList.toggle("active", view === name);
  });
  if (name === "jobs") loadStatus();
  if (name === "cuts") loadCuts();
  if (name === "marks") loadMarks();
  if (name === "bulk") loadBulk();
}

// ===== 検索 =====

function selectedSources() {
  const sources = [];
  if ($("src-stt").checked) sources.push("stt");
  if ($("src-comment").checked) sources.push("comment");
  return sources;
}

function scheduleSearch() {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => runSearch(true), SEARCH_DEBOUNCE_MS);
}

async function runSearch(reset) {
  const query = $("q").value.trim();
  const sources = selectedSources();
  if (reset) {
    state.offset = 0;
    state.hits = [];
  }
  state.query = query;
  // 確認の印は録画1本の属性。語で探している間の行は録画ではなくシーンなので、この
  // 絞り込みは対象を持たない。押せるまま残すと、効いていない指定が効いているように見える。
  const reviewFilter = $("flt-review");
  reviewFilter.disabled = Boolean(query);
  reviewFilter.title = query
    ? "確認状態の絞り込みは、検索語なしの録画一覧でだけ使えます。"
    : "確認状態で録画一覧を絞り込みます。";
  if (!sources.length) {
    state.hits = [];
    state.total = 0;
    state.browsing = false;
    renderHits();
    $("search-summary").textContent = "";
    setListMessage($("hit-empty"), "検索対象（音声／Comment）を選んでください。");
    return;
  }
  // 語が無いときは録画一覧を出す。ここで打ち切ると「当たる語を先に発明しないと
  // 1本も開けない」状態になり、転写が無い録画は永久に開けなくなる。
  if (!query) {
    await loadBrowse();
    return;
  }
  state.browsing = false;
  const params = new URLSearchParams({
    q: query,
    sources: sources.join(","),
    order: $("flt-order").value,
    limit: String(PAGE_SIZE),
    offset: String(state.offset),
  });
  const streamer = $("flt-streamer").value;
  if (streamer) params.set("unique_ids", streamer);

  // 意味検索はpassage単位でscore順に返るため、pagingも並替も持たない別endpoint。
  const semantic = $("flt-mode").value === "semantic";
  const url = semantic
    ? `/api/search/semantic?q=${encodeURIComponent(query)}` +
      (streamer ? `&unique_ids=${encodeURIComponent(streamer)}` : "") +
      `&limit=${PAGE_SIZE}`
    : `/api/search?${params.toString()}`;

  let data;
  try {
    data = await apiSend("GET", url);
  } catch (err) {
    state.hits = [];
    state.total = 0;
    renderHits();
    $("search-summary").textContent = "";
    // 取得失敗を「該当なし」と描かない。検索語が悪いのかserverが落ちているのかが
    // 区別できなくなる。
    setListState($("hit-empty"), "failed", err);
    return;
  }
  if (data.hint) {
    state.hits = [];
    state.total = 0;
    $("search-summary").textContent = "";
    setListMessage($("hit-empty"), data.hint);
    renderHits();
    return;
  }
  state.total = data.total;
  state.hits = state.hits.concat(data.items);
  const mode = data.mode === "semantic"
    ? "（意味が近い順）"
    : data.mode === "like"
      ? "（2文字以下のみのため全走査。3文字以上でindex検索になります）"
      : "";
  $("search-summary").textContent = `${fmtNum(data.total)}件 / 表示${fmtNum(state.hits.length)}件 ${mode}`;
  // ANDは1件(=発話1文かコメント1件)の中で評価される。録画単位の絞り込みではない。
  setListMessage($("hit-empty"), "該当するシーンがありません。複数語のANDは1つの発話・Commentの中で判定されます。");
  $("load-more").classList.toggle(
    "hidden", data.mode === "semantic" || state.hits.length >= state.total);
  renderHits();
}

// snippetはFTS5が\x02..\x03で一致箇所を囲んで返す。HTMLを組み立てずDOMで包むことで、
// コメント本文中の記号がmarkupとして解釈されるのを防ぐ。
function snippetNode(snippet) {
  const wrap = document.createElement("span");
  const parts = String(snippet || "").split(/[\x02\x03]/);
  parts.forEach((part, i) => {
    if (!part) return;
    if (i % 2 === 1) {
      const mark = document.createElement("mark");
      mark.className = "vd-mark";
      mark.textContent = part;
      wrap.appendChild(mark);
    } else {
      wrap.appendChild(document.createTextNode(part));
    }
  });
  return wrap;
}

// 検索語なしの録画一覧。行はhitと同じ形(recording_id/unique_id/started_at/video_time)に
// して先頭から開くだけなので、openHit以下の再生経路は検索hitと完全に共有できる。
async function loadBrowse() {
  state.browsing = true;
  state.total = 0;
  $("load-more").classList.add("hidden");
  setListState($("hit-empty"), "loading");
  const streamer = $("flt-streamer").value;
  let data;
  try {
    data = await apiSend(
      "GET", `/api/recordings/browse${streamer ? `?unique_id=${encodeURIComponent(streamer)}` : ""}`);
  } catch (err) {
    state.browseAll = [];
    state.hits = [];
    renderHits();
    setListState($("hit-empty"), "failed", err);
    return;
  }
  // 待っている間に検索語が入っていたら、その結果を録画一覧で上書きしない。
  if (!state.browsing) return;
  state.browseAll = (data.recordings || []).map((rec) => ({ ...rec, video_time: 0 }));
  applyBrowseFilter();
}

// 確認状態の絞り込みは受け取り済みの一覧の上で行う。serverへ引き直さないのは、絞り込みを
// 変えるたびに全録画の実体走査(mediaの判定)が走るのを避けるため。件数は「絞り込みの結果」と
// 「一覧に載っている総数」の両方を出す(絞った先の件数だけだと、録画そのものが減ったのか
// 印で外れたのかが読めない)。
function applyBrowseFilter() {
  const want = $("flt-review").value;
  state.hits = want
    ? state.browseAll.filter((rec) => reviewStateOf(rec) === want)
    : state.browseAll.slice();
  // 絞り込みで行が入れ替わるとhitIndexは別の録画を指す。開いている録画を追い直し、
  // 一覧から外れたなら選択なしへ戻す(別録画に選択枠が付いたままにしない)。
  const open = state.current ? state.current.recording_id : null;
  state.hitIndex = open === null
    ? -1
    : state.hits.findIndex((rec) => rec.recording_id === open);
  renderHits();
  highlightHitRow();
  setListState($("hit-empty"), state.hits.length ? "ok" : "empty");
  if (!state.hits.length && want && state.browseAll.length) {
    setListMessage($("hit-empty"), `「${REVIEW_LABELS[want]}」の録画はありません。`);
  }
  const total = state.browseAll.length;
  $("search-summary").textContent = total
    ? (want
      ? `${REVIEW_LABELS[want]} ${fmtNum(state.hits.length)}本 / 録画 ${fmtNum(total)}本`
      : `録画 ${fmtNum(total)}本（検索語を入れるとシーンを探せます）`)
    : "";
}

// 実体の種別を名乗るbadge。行に出ている名前(``<stem>.mp4``)は録画の身元でしかなく、
// finalizeはmp4を作らない。名前だけを見せると「mp4というfileが在る」と読めてしまうので、
// 実物が.tsなのかmp4なのかをここで出す。
const MEDIA_BADGE_LABELS = { ts: "TS", mp4: "MP4" };
const MEDIA_BADGE_TITLES = {
  ts: "原本の素材(.ts)が残っています。再生・焼き込み・切り出しはこれを読みます。",
  mp4: "mp4が在ります（再mp4化で作ったもの、または元mp4を持つ旧録画）。",
};

function mediaBadges(media) {
  // 実体が1つも無い録画は行だけが残っている。開けないことをその場で言う(転写・検索・
  // bookmarkは残るので行自体は消さない)。
  if (!media || !media.length) {
    const gone = document.createElement("span");
    gone.className = "vd-src vd-src-none";
    gone.textContent = "実体なし";
    gone.title = "素材(.ts)もmp4も残っていないため再生できません。文字起こし・検索・bookmarkは使えます。";
    return [gone];
  }
  return media.map((kind) => {
    const badge = document.createElement("span");
    badge.className = `vd-src vd-src-${kind}`;
    badge.textContent = MEDIA_BADGE_LABELS[kind] || kind;
    badge.title = MEDIA_BADGE_TITLES[kind] || "";
    return badge;
  });
}

// ===== 確認状態(観たかどうかの印) =====

// 値はserverのRECORDING_REVIEW_STATESと一致させる。既定は未確認で、印は手で付けたときだけ
// 動く(再生や出力では動かさない)。
const REVIEW_LABELS = { unchecked: "未確認", checking: "確認中", checked: "確認済" };
const REVIEW_ORDER = ["unchecked", "checking", "checked"];

function reviewStateOf(rec) {
  const value = rec && rec.review_state;
  return REVIEW_LABELS[value] ? value : "unchecked";
}

// 一覧の行に置く印。行clickは録画を開く操作なので、この操作だけは行へ伝えない
// (印を付け替えるたびに再生が始まると、一覧を眺めながら印を整える作業ができない)。
function reviewSelect(rec) {
  const select = document.createElement("select");
  select.className = "vd-review";
  select.setAttribute("aria-label", "この録画の確認状態");
  select.title = "この録画を観たかどうかの印です。手で付け替えたときだけ変わります。";
  REVIEW_ORDER.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = REVIEW_LABELS[value];
    select.appendChild(option);
  });
  const current = reviewStateOf(rec);
  select.value = current;
  select.dataset.state = current;
  ["click", "mousedown", "keydown"].forEach((type) =>
    select.addEventListener(type, (event) => event.stopPropagation()),
  );
  select.addEventListener("change", () => setReview(rec.recording_id, select.value));
  return select;
}

// 印を1件書き換える。反映先は一覧・再生画面の両方で、どちらから変えても同じ値になる。
// 失敗したら画面上の値も元へ戻す: 保存できていない印を「付いている」ように見せると、
// 次に開いたときに黙って消える。
async function setReview(recordingId, next) {
  const before = state.browseAll.find((rec) => rec.recording_id === recordingId);
  const previous = before ? reviewStateOf(before) : null;
  applyReviewLocally(recordingId, next);
  try {
    await apiSend("PATCH", `/api/recordings/${recordingId}/review`, { state: next });
    if (state.current && state.current.recording_id === recordingId) {
      $("review-note").textContent = `「${REVIEW_LABELS[next]}」にしました。`;
    }
  } catch (err) {
    if (previous) applyReviewLocally(recordingId, previous);
    if (state.current && state.current.recording_id === recordingId) {
      $("review-note").textContent = err.message;
    } else {
      // 一覧だけを触っているときは再生画面の欄が見えていないことがある。行の値を
      // 戻したうえで、失敗そのものはstatus行にも残す。
      $("player-status").textContent = err.message;
    }
  }
}

// 画面上の値を揃える。一覧の元data・表示中の行・再生画面のsegmented controlは同じ録画の
// 同じ印なので、1箇所で書き換えて3つへ配る。
function applyReviewLocally(recordingId, next) {
  [state.browseAll, state.hits].forEach((list) => {
    const rec = list.find((row) => row.recording_id === recordingId);
    if (rec) rec.review_state = next;
  });
  if (state.current && state.current.recording_id === recordingId) {
    state.current.review_state = next;
    syncReviewControl(next);
  }
  const row = $("hit-rows").querySelector(
    `tr[data-recording-id="${recordingId}"] .vd-review`);
  if (row) {
    row.value = next;
    row.dataset.state = next;
  }
  // 絞り込み中は、印を変えた行が対象から外れることがある。表示から外すのは
  // 絞り込みの指定どおりだが、外れた行が残っていると一覧が指定と食い違う。
  if (state.browsing && $("flt-review").value) applyBrowseFilter();
}

function syncReviewControl(value) {
  const control = $("review-state");
  control.value = value;
  control.dataset.state = value;
}

// 録画を開くまでは押せない。開いていない状態で印だけ選べると、どの録画に付くのかを
// 名乗れないまま操作を受け付けることになる。
function setReviewControlEnabled(enabled) {
  $("review-state").querySelectorAll(".seg-item").forEach((item) => {
    item.disabled = !enabled;
  });
}

function browseRowCells(rec) {
  const kind = document.createElement("span");
  kind.className = "vd-kinds";
  const label = document.createElement("span");
  label.className = "vd-src";
  label.textContent = "録画";
  kind.appendChild(label);
  mediaBadges(rec.media).forEach((badge) => kind.appendChild(badge));
  // 中断録画も一覧に出す(素材は揃っていることがある)。ただし確定を跨げていないので、
  // 尺が未測定なことがある事実は行から読めるようにしておく。
  if (rec.status === "interrupted") {
    const note = document.createElement("span");
    note.className = "vd-src vd-src-interrupted";
    note.textContent = "中断";
    note.title = "確定処理を跨げなかった録画です（serverの再起動・crashなど）。素材は残っており再生できます。";
    kind.appendChild(note);
  }
  const body = document.createElement("span");
  // 表示は身元から拡張子を落としたstem。`.mp4`を出すと、実体がmp4だと読めてしまう。
  body.textContent = recName(rec);
  // 転写が無い録画は語で検索しても当たらない。一覧で見分けられるようにしておく。
  if (!rec.has_transcript) {
    const note = document.createElement("span");
    note.className = "vd-score";
    note.textContent = "転写なし";
    note.title = "この録画はまだ文字起こしされていないため、語での検索には出てきません。";
    kind.appendChild(note);
  }
  // 尺はserverが実測した値だけを出す。ended_at - started_atは壁時計で、捕捉の停滞ぶんも
  // 載る上、再処理でended_atが「今」に潰れた録画では数百時間に化ける。測っていなければ
  // それらしい数字を置かず「—」と出す。
  const length = rec.duration_seconds > 0 ? fmtDuration(rec.duration_seconds) : "—";
  return [reviewSelect(rec), kind, rec.unique_id, fmtYmd(rec.started_at), length, body];
}

function renderHits() {
  // 録画一覧では同じ列が「hitの位置」ではなく「録画の尺」になる。
  $("hit-pos-th").textContent = state.browsing ? "尺" : "位置";
  // 確認の印は1行=1録画のときだけ意味を持つ。検索hitは同じ録画の別のシーンが何行も
  // 並ぶので、行ごとに印を出すと同じ印が重複して並ぶだけになる。
  $("hit-review-th").classList.toggle("hidden", !state.browsing);
  // 一覧はfile名だけで横幅を使わないので、左列を中身幅へ詰める(CSS側)。
  document.querySelector(".vd-split").classList.toggle("vd-browse", state.browsing);
  renderTableRows(
    "hit-rows",
    "hit-empty",
    state.hits,
    (hit) => {
      if (state.browsing) return browseRowCells(hit);
      const kind = document.createElement("span");
      kind.className = hit.source === "stt" ? "vd-src vd-src-stt" : "vd-src vd-src-comment";
      kind.textContent = hit.source === "stt" ? "音声" : "Comment";
      const body = document.createElement("span");
      if (hit.nickname) {
        const who = document.createElement("span");
        who.className = "vd-who";
        who.textContent = `${hit.nickname}: `;
        body.appendChild(who);
      }
      body.appendChild(snippetNode(hit.snippet));
      // 意味検索は類似度が判断材料になるので種別欄に併記する(語で一致には無い値)。
      if (hit.score !== undefined) {
        const score = document.createElement("span");
        score.className = "vd-score";
        score.textContent = hit.score.toFixed(2);
        kind.appendChild(score);
      }
      return [kind, hit.unique_id, fmtYmd(hit.started_at), fmtDuration(hit.video_time), body];
    },
    [],
    (tr, hit, index) => {
      tr.classList.add("vd-hit");
      tr.tabIndex = 0;
      // 印を書き換えたとき、一覧を作り直さずにその行だけを追えるようにする。
      if (hit.recording_id !== undefined) tr.dataset.recordingId = hit.recording_id;
      const open = () => openHit(hit, index);
      tr.addEventListener("click", open);
      tr.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          open();
        }
      });
    },
  );
}

// ===== player =====

// 検索hitは当たった発話/コメントの終わり(end_time)も持っている。開いた時点でIN/OUTへ
// 入れておけば、打ち直さずそのまま切り出し・切り出しリストへ回せる。意味検索のhitは
// passage単位(既定25秒)なので、範囲がそのまま素材の候補になる。
function hitCutRange(hit) {
  const end = Number(hit.end_time);
  if (!isFinite(end) || end <= hit.video_time) return null;
  return [hit.video_time, end];
}

async function openHit(hit, index) {
  const video = $("video");
  const sameRecording = state.current && state.current.recording_id === hit.recording_id;
  const range = hitCutRange(hit);
  state.current = hit;
  if (index !== undefined) {
    state.hitIndex = index;
    highlightHitRow();
  }
  $("player-head").textContent =
    `${hit.unique_id} / ${fmtDateTime(hit.started_at)} / ${fmtDuration(hit.video_time)}`;
  $("player-status").textContent = "";

  if (!sameRecording) {
    // 印は録画ごとの値。前の録画のものを残すと、開いた直後の一瞬だけ別録画の印が
    // 出てしまう。確定値はloadPathsがserverから持ってくる(一覧経由なら行の値が既にある)。
    $("review-note").textContent = "";
    setReviewControlEnabled(true);
    syncReviewControl(reviewStateOf(hit));
    // 別録画に移ったらIN/OUTは持ち越さない(別fileの秒数として無意味になるため)。
    setCut(...(range || [null, null]));
    state.heat = null;
    // 別録画の候補は秒数として無意味なので持ち越さない。
    state.candidates = [];
    state.candidateRecordingId = null;
    renderCandidates();
    renderOwnMarks();
    // 算出はserver側のspike解析で重い。開いているときだけ引き、畳んであるなら
    // 開いた時点で引く(tab時代と違い、開くこと自体は再生の邪魔にならない)。
    maybeLoadCandidates();
    // 転写の有無はloadTranscriptが確定させる。それまでは押せない状態にしておく。
    $("do-transcribe").disabled = true;
    setRecordingJobButtons(true);
    $("job-note").textContent = "";
    drawHeat();
    loadHeat(hit.recording_id);
    loadTranscript(hit.recording_id);
    loadChapters(hit.recording_id);
    loadComments(hit.recording_id);
    loadBookmarks(hit.recording_id);
    loadThumbnails(hit.recording_id);
    loadWaveform(hit.recording_id);
    // 素材版の実在を確定させてから読み込む。後追いにすると、選択中の版が在る録画でも
    // 一度元録画を読み込んでから差し替わり、無駄な読み込みと一瞬別の絵が出る。
    await loadPaths(hit.recording_id);
    // 待っている間に別の録画へ移っていたら、こちらは古い。上書きしない。
    if (!state.current || state.current.recording_id !== hit.recording_id) return;
    // 再生経路の確定はserverへ問い合わせる。待たずに下のplay()へ進むと、まだ何も
    // 読み込んでいない<video>を再生しようとして無音のまま止まる。
    await reloadPlayback(false);
  } else {
    video.currentTime = hit.video_time;
    if (range) setCut(range[0], range[1]);
    highlightActiveSegment();
    highlightActiveComment();
  }
  video.play().catch(() => {});
  ["copy-path", "copy-time", "copy-both", "add-mark"].forEach((id) => ($(id).disabled = false));
}

function highlightHitRow() {
  const rows = $("hit-rows").children;
  for (let i = 0; i < rows.length; i += 1) {
    rows[i].classList.toggle("vd-hit-current", i === state.hitIndex);
  }
  const row = rows[state.hitIndex];
  if (row) row.scrollIntoView({ block: "nearest" });
}

function moveHit(delta) {
  if (!state.hits.length) return;
  const next = Math.min(state.hits.length - 1, Math.max(0, state.hitIndex + delta));
  if (next === state.hitIndex) return;
  openHit(state.hits[next], next);
}

// 素材版の呼び名。copy欄(file名寄り)とsegmented control(操作寄り)で語が違うので、
// 出す場所ごとに持つ。segmented側はvideos.htmlのbutton文言と一致させる。
const VARIANT_FILE_LABELS = { source: "録画本体", overlay: "焼き込み済", upscaled: "Up出力済" };
const VARIANT_LABELS = { source: "元録画", overlay: "焼き込み", upscaled: "Up出力" };

// 素材版は録画ごとに在り方が違う(焼き込み出力・Up出力は出したものにしか無い)。押せる状態で
// 並べると、選んでからserverに断られるまで「無い」ことが分からない。実在するものだけを
// 押せるようにし、無いものはその理由をtooltipに書く。
function applyVariantAvailability() {
  const kinds = state.variantKinds;
  Array.from($("clip-variant").querySelectorAll(".seg-item")).forEach((item) => {
    const kind = item.dataset.value;
    const has = kinds.includes(kind);
    item.disabled = !has;
    // 「下の処理から作れます」とだけ案内していたが、全尺の焼き込みは可逆中間がC:を
    // 192GB/時食うため長尺では実行できない。切り出しなら範囲だけを焼けるので、そちらを示す。
    item.title = has
      ? ""
      : `この録画には${VARIANT_LABELS[kind]}がありません。${
          kind === "source"
            ? ""
            : "この版での再生はできませんが、切り出しは範囲だけを焼いて出せます（下の「処理」で全尺を作ることもできます）。"}`;
  });
}

// 実際に再生する版。切り出し素材の指定(clip-variant)は切り出しリストtabと共有していて、
// 録画横断の一括書き出し向けに「この録画には無い版」が入っていることがある。その場合は
// 元録画を再生するが、黙って落とすと出来を誤認するので、下で必ず理由を出す。
function playbackVariant() {
  const want = $("clip-variant").value;
  return state.variantKinds.includes(want) ? want : "source";
}

// 再生経路は録画ごとに違う。素材(.ts)が残っている録画はHLSで直接観て、mp4しか残っていない
// 録画はmp4を観る。どちらになるかはserverが実物を見て決める(画面側は推測しない)。
let hlsPlayer = null;
// 読み込み要求の世代。録画・素材版を速く切り替えると前の要求の応答が後から届くので、
// 最新の要求だけを採用する。
let playbackToken = 0;

function detachHls() {
  if (!hlsPlayer) return;
  hlsPlayer.destroy();
  hlsPlayer = null;
}

// hls.jsのcurrentTimeはplaylistのEXTINF累積(media軸)と一致するため、mp4と同じくvideo_timeを
// そのまま入れられる。位置・音量・倍率の扱いも経路で変えない。
function loadPlayback(playback, at, playing) {
  const video = $("video");
  detachHls();
  if (playback.mode === "hls" && window.Hls && window.Hls.isSupported()) {
    hlsPlayer = new window.Hls();
    hlsPlayer.loadSource(playback.url);
    hlsPlayer.attachMedia(video);
    hlsPlayer.on(window.Hls.Events.ERROR, (_e, data) => {
      // hls.jsが握った失敗は<video>のerror eventにならないので、ここで理由を出す。
      if (data.fatal) $("player-status").textContent = "この録画を再生できませんでした。";
    });
  } else if (playback.mode === "hls" && !video.canPlayType("application/vnd.apple.mpegurl")) {
    $("player-status").textContent = "このBrowserはHLS再生に対応していません。";
    return;
  } else {
    video.src = playback.url;
  }
  video.addEventListener(
    "loadedmetadata",
    () => {
      video.currentTime = at;
      drawHeat();
    },
    { once: true },
  );
  if (playing) video.play().catch(() => {});
}

// 素材版を切り替えても尺と時間軸は同じ(焼き込み・Up出力は元録画と同じmedia軸で作る)ので、
// 見ていた位置とIN/OUTはそのまま持ち越せる。
async function reloadPlayback(keepTime) {
  if (!state.current) return;
  const video = $("video");
  const at = keepTime ? video.currentTime : state.current.video_time;
  const playing = !video.paused;
  const variant = playbackVariant();
  const want = $("clip-variant").value;
  const recordingId = state.current.recording_id;
  const token = (playbackToken += 1);
  let playback;
  try {
    playback = await apiSend(
      "GET",
      `/api/recordings/${recordingId}/playback?variant=${encodeURIComponent(variant)}`,
    );
  } catch (err) {
    $("player-status").textContent = err.message;
    return;
  }
  if (token !== playbackToken) return;
  if (want !== variant) {
    $("player-status").textContent =
      `切り出し素材は「${VARIANT_LABELS[want]}」ですが、この録画にはその出力が無いため元録画を再生しています。`;
  } else if (variant === "source" && playback.mode !== "hls") {
    // 素材から直接観られない録画であることは、出来を見るうえで知っておく必要がある。
    $("player-status").textContent = "この録画は.tsが残っていないため、mp4を再生しています。";
  } else {
    $("player-status").textContent = "";
  }
  loadPlayback(playback, at, playing);
}

async function loadPaths(recordingId) {
  const select = $("path-variant");
  select.innerHTML = "";
  state.variants = [];
  // 実在が確定するまでは全て伏せる。前の録画の在り方を引き継ぐと、無い版を押せる状態で
  // 出してしまう。
  state.variantKinds = [];
  applyVariantAvailability();
  // 選択肢が無い間は空箱を出さない。録画を開く前や派生fileが1つも無いときは、
  // copy対象を選ぶ余地が無いので選択肢欄そのものを出す意味が無い。
  select.classList.add("hidden");
  let data;
  try {
    data = await apiSend("GET", `/api/recordings/${recordingId}/path`);
    state.variants = data.variants || [];
  } catch (err) {
    $("player-status").textContent = err.message;
    return;
  }
  // 印の確定値。検索hit経由で開いた録画は一覧の値を持たないので、ここが唯一の出所になる。
  if (state.current && state.current.recording_id === recordingId) {
    state.current.review_state = reviewStateOf(data);
    syncReviewControl(reviewStateOf(data));
  }
  state.variantKinds = state.variants.filter((v) => v.exists).map((v) => v.kind);
  applyVariantAvailability();
  state.variants.forEach((variant) => {
    const option = document.createElement("option");
    option.value = variant.path;
    // 実体の種別を併記する。素材しか無い録画のsourceはmp4ではなくsession dir(seg*.ts)を
    // 指すので、「録画本体」とだけ出すと何を渡されたのか読めない。
    const media = MEDIA_BADGE_LABELS[variant.media_kind];
    option.textContent = (VARIANT_FILE_LABELS[variant.kind] || variant.kind)
      + (media ? `（${media}）` : "");
    select.appendChild(option);
  });
  select.classList.toggle("hidden", state.variants.length < 2);
}

async function loadHeat(recordingId) {
  try {
    const data = await apiSend("GET", `/api/recordings/${recordingId}/heat`);
    if (state.current && state.current.recording_id === recordingId) {
      state.heat = data.points || [];
      drawHeat();
    }
  } catch {
    state.heat = [];
    drawHeat();
  }
}

// ===== 文字起こしpanel =====
// 切り抜きの実体は「この発言のここからここまで」なので、文を選ぶとIN/OUTが決まる形にする。
// segmentのstart/endは転写時にmedia軸へ再mapされており、そのままvideoの秒として使える。

async function loadTranscript(recordingId) {
  state.segments = [];
  state.segmentIndex = -1;
  state.selFrom = null;
  state.selTo = null;
  $("segments").innerHTML = "";
  $("transcript-note").textContent = "読み込み中…";
  let data;
  try {
    data = await apiSend("GET", `/api/recordings/${recordingId}/transcript`);
  } catch (err) {
    if (state.current && state.current.recording_id === recordingId) {
      // 404だけが「まだ転写されていない」。それ以外は取得失敗であって未処理ではないため、
      // 未処理と描いて再転写を促すと、serverが落ちているだけの録画を転写し直させてしまう。
      if (err.status === 404) {
        $("transcript-note").textContent = "この録画は未処理です。";
        // 未処理のときだけ押せる。既存transcriptの再転写はbackendが受け付けない。
        $("do-transcribe").disabled = false;
      } else {
        $("transcript-note").textContent =
          `文字起こしを取得できませんでした（未処理という意味ではありません）。${errorDetailText(err)}`;
        $("do-transcribe").disabled = true;
      }
    }
    return;
  }
  if (!state.current || state.current.recording_id !== recordingId) return;
  state.segments = data.segments || [];
  $("transcript-note").textContent = `${fmtNum(state.segments.length)}文`;
  $("do-transcribe").disabled = true;
  renderSegments();
  highlightActiveSegment();
}

async function transcribeCurrent() {
  if (!state.current) return;
  const button = $("do-transcribe");
  const recordingId = state.current.recording_id;
  button.disabled = true;
  // 投入結果はbuttonの隣(job-note)に出す。文字起こしpanelのnoteはtranscriptそのものの
  // 状態を持つ欄で、buttonから離れており押した手応えにならない。
  $("job-note").textContent = "文字起こしの順番待ちに入れています…";
  try {
    const result = await apiSend("POST", "/api/transcribe/queue", {
      recording_ids: [recordingId],
    });
    renderQueue(result.queue);
    $("job-note").textContent = result.added
      ? "文字起こしの順番待ちに入れました。終わり次第ここに反映されます。"
      : "文字起こしは既に順番待ちか処理済みです。";
  } catch (err) {
    $("job-note").textContent = `文字起こし: ${err.message}`;
  } finally {
    // 成功時もbuttonを戻す。以前は成功pathだけが戻さず、行が再描画されない限り
    // 理由の説明も無くgrey outされたままだった。
    button.disabled = false;
  }
}

// ===== この録画に対する生成job =====
// 実処理はserverの永続queue。応答はjob_idだけで、進み具合はJob画面とWSのjob_updateで届く。
// 焼き込み・Up出力を出すまで素材版は選べないので、player側から直に投げられるようにする。

const RECORDING_JOBS = {
  overlay: { button: "do-overlay", path: "output", label: "焼き込み出力" },
  reprocess: { button: "do-reprocess", path: "reprocess", label: "再mp4化" },
  audionorm: { button: "do-audionorm", path: "audionorm", label: "音量正規化" },
  pack: { button: "do-pack", path: "pack", label: "ts結合" },
};
// Up出力はplayerからは投げない(単発でも実時間の数倍かかるため、対象を選んでから投げる
// 一括処理tabが投入口)。ここでは出来上がりを再生・切り出しに使えれば足りる。
const RECORDING_JOB_LABELS = { ...Object.fromEntries(
  Object.entries(RECORDING_JOBS).map(([kind, spec]) => [kind, spec.label]),
), upscale: "Up出力" };

function setRecordingJobButtons(enabled) {
  Object.values(RECORDING_JOBS).forEach((spec) => { $(spec.button).disabled = !enabled; });
}

async function startRecordingJob(kind) {
  if (!state.current) return;
  const spec = RECORDING_JOBS[kind];
  const recordingId = state.current.recording_id;
  setRecordingJobButtons(false);
  $("job-note").textContent = `${spec.label}を順番待ちに入れています…`;
  try {
    await apiSend("POST", `/api/recordings/${recordingId}/${spec.path}`);
    // buttonは伏せたままにする。終わるか失敗するまでは同じ録画へ二重に投げても意味が無い。
    $("job-note").textContent =
      `${spec.label}を順番待ちに入れました。進み具合はJob画面に出ます。`;
  } catch (err) {
    $("job-note").textContent = `${spec.label}: ${err.message}`;
    setRecordingJobButtons(true);
  }
}

// 開いている録画のjob。単発・一括・別tab発のどれもこの同じjob_updateで届く。
function onRecordingJobUpdate(job) {
  const label = RECORDING_JOB_LABELS[job.domain] || job.domain;
  if (job.state === "pending") {
    $("job-note").textContent = `${label}: 順番待ち`;
    return;
  }
  if (job.state === "running") {
    $("job-note").textContent = `${label} ${job.stage || ""} ${job.pct}%`.trim();
    return;
  }
  if (job.state === "completed") {
    $("job-note").textContent = `${label}が終わりました。`;
    // 出来た版をその場で選べるようにする。再mp4化と音量正規化は元録画そのものが差し
    // 替わるので、開いているplayerも読み直す(古いfileを再生し続けると直ったか分からない)。
    loadPaths(job.recording_id).then(() => {
      if (job.domain === "reprocess" || job.domain === "audionorm") reloadPlayback(true);
    });
  } else {
    $("job-note").textContent = `${label}: ${job.message || job.state}`;
  }
  setRecordingJobButtons(true);
}

function renderSegments() {
  const container = $("segments");
  container.innerHTML = "";
  const fragment = document.createDocumentFragment();
  state.segments.forEach((segment, index) => {
    const row = document.createElement("div");
    row.className = "vd-seg";
    row.dataset.index = String(index);
    const time = document.createElement("span");
    time.className = "vd-seg-t";
    time.textContent = fmtDuration(segment.start);
    const text = document.createElement("span");
    text.textContent = segment.text;
    row.append(time, text);
    fragment.appendChild(row);
  });
  container.appendChild(fragment);
}

function segmentIndexOf(node) {
  const row = node && node.closest ? node.closest(".vd-seg") : null;
  return row ? Number(row.dataset.index) : null;
}

function paintSelection() {
  const rows = $("segments").children;
  const a = state.selFrom === null ? -1 : Math.min(state.selFrom, state.selTo);
  const b = state.selFrom === null ? -2 : Math.max(state.selFrom, state.selTo);
  for (let i = 0; i < rows.length; i += 1) {
    rows[i].classList.toggle("vd-seg-sel", i >= a && i <= b);
  }
}

function selectSegmentRange(from, to) {
  const a = Math.min(from, to);
  const b = Math.max(from, to);
  state.selFrom = a;
  state.selTo = b;
  paintSelection();
  setCut(state.segments[a].start, state.segments[b].end);
}

// 追従scrollは今の行をpanelの中央へ置く。末尾に貼り付けると前後の文脈のうち「後」が
// 見えず、今どこを読んでいるのかが掴めない。scrollIntoViewは祖先のscroll容器まで動かして
// 画面全体が飛ぶので、この容器のscrollTopだけを直接動かす。
function centerRowIn(container, row) {
  const offset = row.getBoundingClientRect().top - container.getBoundingClientRect().top;
  const target = container.scrollTop + offset - (container.clientHeight - row.offsetHeight) / 2;
  const max = container.scrollHeight - container.clientHeight;
  container.scrollTop = Math.max(0, Math.min(target, max));
}

function highlightActiveSegment() {
  const container = $("segments");
  const rows = container.children;
  if (!rows.length) return;
  const now = $("video").currentTime;
  let active = -1;
  for (let i = 0; i < state.segments.length; i += 1) {
    const segment = state.segments[i];
    if (now >= segment.start && now < (segment.end ?? segment.start)) {
      active = i;
      break;
    }
  }
  if (active === state.segmentIndex) return;
  for (let i = 0; i < rows.length; i += 1) {
    rows[i].classList.toggle("vd-seg-active", i === active);
  }
  state.segmentIndex = active;
  // 追従は既定ON。読み返している最中に勝手に飛ぶのが邪魔な場面もあるので切れるようにする。
  if (active >= 0 && $("transcript-follow").checked) centerRowIn(container, rows[active]);
}

// 発話の途中で切れたclipは素材にならないので、手打ちのIN/OUTを最寄りの発話境界へ寄せる。
function snapToSegments(seconds, kind) {
  if (!$("snap-seg").checked || !state.segments.length) return seconds;
  let best = seconds;
  let bestGap = SNAP_WINDOW_SECONDS;
  state.segments.forEach((segment) => {
    const candidate = kind === "in" ? segment.start : segment.end;
    if (candidate === undefined || candidate === null) return;
    const gap = Math.abs(candidate - seconds);
    if (gap < bestGap) {
      bestGap = gap;
      best = candidate;
    }
  });
  return best;
}

// ===== 章立てpanel =====
// 3時間級の録画を目次から辿るための一覧。表題はLLMが書くので誤りがあり得るうえ、その誤りは
// その位置を見るまで分からない。そこで(1)行clickでその時刻へ必ず飛べるようにし、(2)表題の
// 下にその位置の実際の発話を併記する。表題だけを事実として読ませる形にはしない。

async function loadChapters(recordingId) {
  state.chapters = [];
  state.chapterIndex = -1;
  $("chapters").innerHTML = "";
  ["copy-chapters", "save-chapters"].forEach((id) => ($(id).disabled = true));
  $("do-chapters").disabled = false;
  $("chapter-note").textContent = "読み込み中…";
  let data;
  try {
    data = await apiSend("GET", `/api/recordings/${recordingId}/chapters`);
  } catch (err) {
    if (state.current && state.current.recording_id === recordingId) {
      $("chapter-note").textContent =
        `章立てを取得できませんでした。${errorDetailText(err)}`;
    }
    return;
  }
  if (!state.current || state.current.recording_id !== recordingId) return;
  applyChapters(data);
}

function applyChapters(data) {
  state.chapters = (data && data.chapters) || [];
  state.chapterIndex = -1;
  const enabled = state.chapters.length > 0;
  ["copy-chapters", "save-chapters"].forEach((id) => ($(id).disabled = !enabled));
  if (data && data.error) {
    // 保存済みの行が読めなかった場合。「まだ作っていない」に化けさせない。
    $("chapter-note").textContent = data.error;
  } else if (!enabled) {
    $("chapter-note").textContent = "まだ作っていません。";
  } else {
    // いつ・どのmodelで作ったのかを必ず出す。表題はそのmodelの出力であって録画の事実では
    // ないので、出所の分からない目次として読ませない。
    const when = data.computed_at ? fmtDateTime(data.computed_at) : "";
    const parts = [`${fmtNum(state.chapters.length)}章`];
    if (data.model) parts.push(data.model);
    if (when) parts.push(when);
    $("chapter-note").textContent = parts.join(" / ");
  }
  renderChapters();
  highlightActiveChapter();
}

function renderChapters() {
  const container = $("chapters");
  container.innerHTML = "";
  const fragment = document.createDocumentFragment();
  state.chapters.forEach((chapter, index) => {
    const row = document.createElement("div");
    row.className = "vd-seg";
    row.dataset.index = String(index);
    const time = document.createElement("span");
    time.className = "vd-seg-t";
    time.textContent = fmtDuration(chapter.start);
    const body = document.createElement("span");
    body.className = "vd-cmt-body";
    const title = document.createElement("div");
    title.textContent = chapter.title;
    // 表題の根拠になったその位置の発話。これが表題と噛み合っていなければ、seekする前に
    // 目次が外れていることに気付ける。
    const quote = document.createElement("div");
    quote.className = "vd-summary";
    quote.textContent = chapter.quote || "";
    body.append(title, quote);
    row.append(time, body);
    fragment.appendChild(row);
  });
  container.appendChild(fragment);
}

function highlightActiveChapter() {
  const rows = $("chapters").children;
  if (!rows.length) return;
  const now = $("video").currentTime;
  let active = -1;
  for (let i = 0; i < state.chapters.length; i += 1) {
    if (now >= state.chapters[i].start && now < state.chapters[i].end) {
      active = i;
      break;
    }
  }
  if (active === state.chapterIndex) return;
  const previous = rows[state.chapterIndex];
  if (previous) previous.classList.remove("vd-seg-active");
  state.chapterIndex = active;
  const row = rows[active];
  if (row) row.classList.add("vd-seg-active");
}

async function generateChapters() {
  if (!state.current) return;
  const recordingId = state.current.recording_id;
  const button = $("do-chapters");
  button.disabled = true;
  // 実測で40分の録画に約10分かかる(chunk数に比例)。押した直後に無反応に見えないよう、
  // 待たされることを先に伝える。
  $("chapter-note").textContent = "章立てを作っています。録画の長さに応じて数分〜数十分かかります…";
  try {
    const data = await apiSend("POST", `/api/recordings/${recordingId}/chapters`);
    if (!state.current || state.current.recording_id !== recordingId) return;
    applyChapters(data);
  } catch (err) {
    if (state.current && state.current.recording_id === recordingId) {
      $("chapter-note").textContent = err.message;
    }
  } finally {
    button.disabled = false;
  }
}

function chapterExportUrl(format) {
  return `/api/recordings/${state.current.recording_id}/chapters/export?format=${format}`;
}

// 説明欄用のtextはserverの書き出しをそのまま貼る。同じ整形をJS側にも書くと、timecodeの
// 表記が2箇所に分かれてやがて食い違う。
async function copyChapterText() {
  if (!state.current) return;
  let text;
  try {
    const res = await fetch(chapterExportUrl("txt"));
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    text = await res.text();
  } catch (err) {
    $("player-status").textContent = `章立てを取得できませんでした: ${err.message}`;
    return;
  }
  copyText(text, "説明欄用の章立てをcopyしました。");
}

// ===== コメントpanel =====
// video_timeはindex時にmp4 PTSへ変換済みで、焼き込み・検索hitと同じ軸に載っている。
// heat barの山が何で出来ていたのかをその場で読めるよう、文字起こしの下に時系列で並べる。

async function loadComments(recordingId) {
  state.comments = [];
  state.commentIndex = -1;
  $("comments").innerHTML = "";
  $("comment-note").textContent = "読み込み中…";
  let data;
  try {
    data = await apiSend("GET", `/api/recordings/${recordingId}/comments`);
  } catch (err) {
    if (state.current && state.current.recording_id === recordingId) {
      $("comment-note").textContent = err.message;
    }
    return;
  }
  if (!state.current || state.current.recording_id !== recordingId) return;
  state.comments = data.items || [];
  $("comment-note").textContent = state.comments.length
    ? `${fmtNum(state.comments.length)}件`
    // 「0件」と「未index」はsearch_hits上で区別が付かない(空indexは行を残さない)ので、
    // 断定せずどちらもあり得る文言にする。
    : "Commentがないか、検索indexが未構築です。";
  renderComments();
  highlightActiveComment();
}

function renderComments() {
  const container = $("comments");
  container.innerHTML = "";
  const fragment = document.createDocumentFragment();
  state.comments.forEach((comment, index) => {
    const row = document.createElement("div");
    row.className = "vd-cmt";
    row.dataset.index = String(index);
    const time = document.createElement("span");
    time.className = "vd-seg-t";
    time.textContent = fmtDuration(comment.t);
    const who = document.createElement("span");
    who.className = "vd-who vd-cmt-who";
    who.textContent = comment.nickname || "";
    const body = document.createElement("span");
    body.className = "vd-cmt-body";
    body.textContent = comment.body;
    // 押した/押していないが一目で判るよう、checkboxと同じ行頭に置いて状態で色を変える。
    const mark = document.createElement("button");
    mark.className = "vd-cmt-mark";
    mark.type = "button";
    mark.textContent = "★";
    row.append(mark, time, who, body);
    fragment.appendChild(row);
  });
  container.appendChild(fragment);
  syncCommentMarks();
}

// 記録済みのコメントを★の色で示す。見どころ側のsource_hit_idがコメント行のidなので、
// 時刻の近さで推測せずこの対応だけで判定する。
function markedHitIds() {
  const ids = new Set();
  (state.bookmarks || []).forEach((mark) => {
    if (mark.source_hit_id !== null && mark.source_hit_id !== undefined) {
      ids.add(mark.source_hit_id);
    }
  });
  return ids;
}

// 見どころの追加・削除後に呼ぶ。renderComments()し直すと選択中行やscroll位置が飛ぶので、
// 既にある行のbuttonだけ塗り替える。
function syncCommentMarks() {
  const rows = $("comments").children;
  if (!rows.length) return;
  const ids = markedHitIds();
  for (let index = 0; index < rows.length; index += 1) {
    const button = rows[index].querySelector(".vd-cmt-mark");
    if (!button) continue;
    const comment = state.comments[index];
    const on = comment !== undefined && ids.has(comment.id);
    button.classList.toggle("vd-cmt-mark-on", on);
    button.setAttribute("aria-pressed", on ? "true" : "false");
    button.title = on ? "見どころから外す" : "この位置を見どころに記録";
  }
}

// 再生位置以前で最後のコメント。長時間配信は数万件になるので、timeupdate毎に線形走査
// させず二分探索で引く。
function activeCommentIndex(now) {
  let low = 0;
  let high = state.comments.length - 1;
  let found = -1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (state.comments[mid].t <= now) {
      found = mid;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  return found;
}

function highlightActiveComment() {
  const container = $("comments");
  const rows = container.children;
  if (!rows.length) return;
  const index = activeCommentIndex($("video").currentTime);
  if (index === state.commentIndex) return;
  const previous = rows[state.commentIndex];
  if (previous) previous.classList.remove("vd-cmt-active");
  state.commentIndex = index;
  const row = rows[index];
  if (!row) return;
  row.classList.add("vd-cmt-active");
  // 追従は既定ON。読み返している最中に勝手に飛ぶのが邪魔な場面もあるので切れるようにする。
  if ($("comment-follow").checked) centerRowIn(container, row);
}

// ===== 見どころ(bookmark) =====
// cut listが「書き出す素材」なのに対し、こちらは「後でまた見たい場所」。点でも範囲でも
// 残せて、seek bar上のmarkerとして常に見えることで、同じ録画を開き直した時に辿り着ける。

async function loadBookmarks(recordingId) {
  state.bookmarks = [];
  drawHeat();
  syncCommentMarks();
  let data;
  try {
    data = await apiSend("GET", `/api/bookmarks?recording_id=${recordingId}`);
  } catch (err) {
    $("player-status").textContent = err.message;
    return;
  }
  if (!state.current || state.current.recording_id !== recordingId) return;
  state.bookmarks = data.items || [];
  drawHeat();
  renderOwnMarks();
  syncCommentMarks();
}

// 範囲(IN/OUT)が決まっていればその範囲を、無ければ現在位置を点として残す。
async function addBookmarkHere() {
  if (!state.current) return;
  const video = $("video");
  const hasRange = state.cutIn !== null && state.cutOut !== null && state.cutOut > state.cutIn;
  await saveBookmark(
    hasRange ? state.cutIn : video.currentTime,
    hasRange ? state.cutOut : null,
    $("mark-memo").value.trim(),
    null,
  );
  $("mark-memo").value = "";
}

async function saveBookmark(start, end, memo, sourceHitId) {
  if (!state.current) return;
  try {
    await apiSend("POST", "/api/bookmarks", {
      recording_id: state.current.recording_id,
      start,
      end,
      memo,
      source_hit_id: sourceHitId,
    });
  } catch (err) {
    $("player-status").textContent = err.message;
    return;
  }
  $("player-status").textContent = end === null
    ? `見どころに記録しました（${fmtDuration(start)}）`
    : `見どころに記録しました（${fmtDuration(start)} - ${fmtDuration(end)}）`;
  await loadBookmarks(state.current.recording_id);
}

// コメント行の★。押し間違いをその場で戻せるよう、記録済みなら同じ押下で外す。
async function toggleCommentBookmark(comment, button) {
  if (!state.current) return;
  const existing = (state.bookmarks || []).filter((mark) => mark.source_hit_id === comment.id);
  button.disabled = true;
  try {
    if (!existing.length) {
      // このコメント自体が見どころの根拠なので、本文をそのままmemoにして残す。
      const memo = comment.nickname ? `${comment.nickname}: ${comment.body}` : comment.body;
      await saveBookmark(comment.t, null, memo, comment.id ?? null);
      return;
    }
    // 同じコメントから二重に登録された古い行もまとめて外す(1件だけ残ると★が消えない)。
    for (const mark of existing) {
      await apiSend("DELETE", `/api/bookmarks/${mark.id}`);
    }
    $("player-status").textContent = `見どころから外しました（${fmtDuration(comment.t)}）`;
    await loadBookmarks(state.current.recording_id);
  } catch (err) {
    $("player-status").textContent = err.message;
  } finally {
    button.disabled = false;
  }
}

// heat bar上のmarker。点は逆三角、範囲は下端の帯にして、IN/OUTの緑赤とは別の色で描く。
function drawBookmarks(ctx, width, height, duration) {
  if (!state.bookmarks.length) return;
  const toX = (seconds) => (seconds / duration) * width;
  const top = height - BOOKMARK_LANE_PX;
  state.bookmarks.forEach((mark) => {
    const x = toX(mark.start);
    if (x < 0 || x > width) return;
    ctx.fillStyle = "rgba(169, 110, 73, 0.85)";
    if (mark.end !== null && mark.end !== undefined) {
      ctx.fillRect(x, top, Math.max(2, toX(mark.end) - x), BOOKMARK_LANE_PX);
      return;
    }
    ctx.fillRect(x - 1, top, 2, BOOKMARK_LANE_PX);
    ctx.beginPath();
    ctx.moveTo(x - BOOKMARK_LANE_PX / 2, top);
    ctx.lineTo(x + BOOKMARK_LANE_PX / 2, top);
    ctx.lineTo(x, top + BOOKMARK_LANE_PX);
    ctx.closePath();
    ctx.fill();
  });
}

// ===== 見どころtab =====

async function loadMarks() {
  try {
    const data = await apiSend("GET", "/api/bookmarks");
    state.marks = data.items || [];
  } catch (err) {
    $("marks-summary").textContent = err.message;
    return;
  }
  $("marks-summary").textContent = state.marks.length
    ? `${fmtNum(state.marks.length)}件`
    : "";
  renderMarks();
}

function renderMarks() {
  renderTableRows(
    "mark-rows",
    "mark-empty",
    state.marks,
    (mark) => {
      const memo = document.createElement("input");
      memo.type = "text";
      memo.className = "vd-memo";
      memo.value = mark.memo || "";
      memo.placeholder = "メモ";
      // 打鍵毎に投げず、離れた時に確定させる。値が変わっていなければ何もしない。
      memo.addEventListener("change", async () => {
        const value = memo.value.trim();
        if (value === (mark.memo || "")) return;
        try {
          await apiSend("PATCH", `/api/bookmarks/${mark.id}`, { memo: value });
          mark.memo = value;
        } catch (err) {
          $("marks-summary").textContent = err.message;
        }
      });
      const open = document.createElement("button");
      open.className = "btn btn-small";
      open.textContent = "開く";
      open.addEventListener("click", () => openMark(mark));
      const remove = document.createElement("button");
      remove.className = "btn btn-small btn-danger";
      remove.textContent = "削除";
      remove.addEventListener("click", async () => {
        await apiSend("DELETE", `/api/bookmarks/${mark.id}`);
        if (state.current) loadBookmarks(state.current.recording_id);
        loadMarks();
      });
      const actions = document.createElement("span");
      actions.className = "vd-row";
      actions.append(open, remove);
      const hasRange = mark.end !== null && mark.end !== undefined;
      return [
        mark.unique_id,
        fmtYmd(mark.recording_started_at),
        fmtDuration(mark.start),
        hasRange ? fmtDuration(mark.end - mark.start) : "点",
        memo,
        actions,
      ];
    },
    [2, 3],
  );
}

// 見どころから再生画面へ戻る。範囲付きならIN/OUTも復元して、そのまま切り出しへ回せる。
async function openMark(mark) {
  showView("search");
  await openHit({
    recording_id: mark.recording_id,
    unique_id: mark.unique_id,
    started_at: mark.recording_started_at,
    video_time: mark.start,
  });
  if (mark.end !== null && mark.end !== undefined) setCut(mark.start, mark.end);
}

function updateTimeLabel() {
  const video = $("video");
  const duration = isFinite(video.duration) ? video.duration : null;
  $("time-now").textContent = duration
    ? `${fmtDuration(video.currentTime)} / ${fmtDuration(duration)}`
    : "--:--:-- / --:--:--";
}

// heat barは動画の尺に対する位置で描く。clickとdragでその位置へseekできるようにして、
// 検索語を持たない「何か起きた場所」からも辿れるようにする。
function drawHeat() {
  const canvas = $("heat");
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  // tab非表示のときは実寸が0になる。この状態で描いても捨てるだけなので何もしない。
  if (!width || !height) return;
  // canvas.width/heightへの代入はbacking storeを作り直して全消去する。timeupdate毎に
  // 全幅分を再確保しないよう、寸法が変わったときだけ代入する。
  if (canvas.width !== width) canvas.width = width;
  if (canvas.height !== height) canvas.height = height;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, width, height);
  const points = state.heat;
  const duration = $("video").duration;
  if (!isFinite(duration) || duration <= 0) return;

  // 上端はIN/OUT handleを掴む専用lane、下端は見どころmarker専用lane。波形とheatはその間
  // だけを使う。ここでlaneを差し引かないとheatの山にmarkerが埋もれる。
  const bodyTop = RANGE_LANE_PX;
  const bodyBottom = height - BOOKMARK_LANE_PX;
  const bodyH = bodyBottom - bodyTop;

  // 波形は上段。bucket indexは時間に線形対応する(waveform側がPTS軸へ揃えてある)。
  if (state.wave && state.wave.length) {
    const waveHeight = bodyH * 0.45;
    const step = width / state.wave.length;
    ctx.fillStyle = "rgba(90, 110, 120, 0.55)";
    state.wave.forEach((peak, index) => {
      const barHeight = peak * waveHeight;
      ctx.fillRect(index * step, bodyTop + (waveHeight - barHeight) / 2 + 1,
                   Math.max(1, step), Math.max(1, barHeight));
    });
    ctx.fillStyle = "rgba(143, 136, 113, 0.35)";
    ctx.fillRect(0, bodyTop + waveHeight + 1, width, 1);
  }

  if (points && points.length) {
    const maxComments = Math.max(1, ...points.map((p) => p.comments));
    const maxDiamonds = Math.max(1, ...points.map((p) => p.diamonds));
    // 波形を出しているときは下段だけを使い、2つの情報が重ならないようにする。
    const heatHeight = state.wave && state.wave.length ? bodyH * 0.5 : bodyH - 2;
    const barWidth = Math.max(1, width / Math.max(1, points.length));
    points.forEach((point) => {
      const x = (point.t / duration) * width;
      if (x < 0 || x > width) return;
      const commentH = (point.comments / maxComments) * heatHeight;
      ctx.fillStyle = "rgba(143, 136, 113, 0.55)";
      ctx.fillRect(x, bodyBottom - commentH, barWidth, commentH);
      if (point.diamonds > 0) {
        const giftH = (point.diamonds / maxDiamonds) * heatHeight;
        ctx.fillStyle = "rgba(200, 150, 60, 0.75)";
        ctx.fillRect(x, bodyBottom - giftH, Math.max(1, barWidth * 0.5), giftH);
      }
    });
  }

  drawRangeLane(ctx, width, height, duration);
  drawBookmarks(ctx, width, height, duration);

  const video = $("video");
  if (video.currentTime > 0) {
    drawPlayhead(ctx, (video.currentTime / duration) * width, height);
  }
}

// 再生位置。panelと同系色の細線だと波形にもheatにも沈んで見失うので、暗い実線を
// 明色の縁で挟んでどの背景でも浮かせ、上端のknobで現在地を掴めるようにする。
function drawPlayhead(ctx, x, height) {
  const left = Math.round(x) - 1;
  ctx.fillStyle = "rgba(248, 245, 235, 0.9)";
  ctx.fillRect(left - 1, 0, 4, height);
  ctx.fillStyle = "#1d1b16";
  ctx.fillRect(left, 0, 2, height);
  ctx.beginPath();
  ctx.moveTo(left + 1 - PLAYHEAD_KNOB_PX, 0);
  ctx.lineTo(left + 1 + PLAYHEAD_KNOB_PX, 0);
  ctx.lineTo(left + 1, PLAYHEAD_KNOB_PX);
  ctx.closePath();
  ctx.fill();
}

// IN/OUTで挟んだ範囲を帯で示す。切り出し前にどこを抜くのか目で確かめられる。
// heatより後に描かないと帯のtintにhandleが沈んで掴み所が見えなくなる。
function drawRangeLane(ctx, width, height, duration) {
  const toX = (seconds) => (seconds / duration) * width;
  ctx.fillStyle = "rgba(143, 136, 113, 0.18)";
  ctx.fillRect(0, 0, width, RANGE_LANE_PX);

  const inX = state.cutIn === null ? null : toX(state.cutIn);
  const outX = state.cutOut === null ? null : toX(state.cutOut);
  if (inX !== null && outX !== null && outX > inX) {
    ctx.fillStyle = "rgba(120, 150, 120, 0.28)";
    ctx.fillRect(inX, 0, Math.max(1, outX - inX), height);
    ctx.fillStyle = "rgba(120, 150, 120, 0.6)";
    ctx.fillRect(inX, 0, Math.max(1, outX - inX), RANGE_LANE_PX);
  }
  [[inX, "rgba(90, 130, 90, 0.95)"], [outX, "rgba(150, 90, 70, 0.95)"]].forEach(
    ([x, color]) => {
      if (x === null) return;
      ctx.fillStyle = color;
      ctx.fillRect(x - 1, 0, 2, height);
      ctx.fillRect(x - HANDLE_DRAW_PX / 2, 0, HANDLE_DRAW_PX, RANGE_LANE_PX);
    },
  );
}

// ===== 音声波形 =====
// 無音・BGM・発話が目で分かるので切り所の判断が速くなる。初回生成はcontainerを丸ごと
// 読むため長尺で90秒級かかる。録画を開く度に走らせるとdiskを占有するので、利用者が
// checkboxで求めたときだけ取りに行く。

async function loadWaveform(recordingId) {
  if (!$("show-wave").checked) {
    state.wave = null;
    $("wave-note").textContent = "";
    drawHeat();
    return;
  }
  state.wave = null;
  $("wave-note").textContent = "波形を生成中…（初回は長い録画で90秒程度）";
  drawHeat();
  try {
    const data = await apiSend(
      "GET", `/api/recordings/${recordingId}/waveform?buckets=${WAVE_BUCKETS}`);
    if (!state.current || state.current.recording_id !== recordingId) return;
    state.wave = data.peaks || null;
    $("wave-note").textContent = "";
  } catch (err) {
    if (state.current && state.current.recording_id === recordingId) {
      $("wave-note").textContent = err.message;
    }
  }
  drawHeat();
}

// ===== seek barのサムネイル =====
// spriteは1枚の大画像で、tile i が時刻 i*interval に対応する。background-positionをずらして
// 1枚だけ見せる。初回生成は長尺で十数秒かかるので、hoverの瞬間ではなく録画を開いた時点で頼む。

async function loadThumbnails(recordingId) {
  state.sprite = null;
  try {
    const spec = await apiSend("GET", `/api/recordings/${recordingId}/thumbnails`);
    if (state.current && state.current.recording_id === recordingId) state.sprite = spec;
  } catch {
    state.sprite = null;
  }
}

// bar上のx座標を動画の秒へ写す。thumbnail・seek・range dragが同じ換算を使う。
function secondsFromClientX(clientX) {
  const duration = $("video").duration;
  if (!isFinite(duration) || duration <= 0) return null;
  const rect = $("heat").getBoundingClientRect();
  const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
  return ratio * duration;
}

function showThumb(clientX) {
  const spec = state.sprite;
  const thumb = $("thumb");
  const seconds = secondsFromClientX(clientX);
  if (!spec || seconds === null) {
    thumb.classList.add("hidden");
    return;
  }
  const rect = $("heat").getBoundingClientRect();
  const index = Math.min(spec.count - 1, Math.floor(seconds / spec.interval_seconds));
  const column = index % spec.columns;
  const row = Math.floor(index / spec.columns);
  const image = $("thumb-img");
  image.style.width = `${spec.tile_width}px`;
  image.style.height = `${spec.tile_height}px`;
  image.style.backgroundImage = `url("${spec.url}")`;
  image.style.backgroundPosition = `-${column * spec.tile_width}px -${row * spec.tile_height}px`;
  $("thumb-time").textContent = fmtDuration(seconds);
  thumb.classList.remove("hidden");
  // barの端でthumbが画面外へ出ないよう、wrapper内に収める。
  const wrap = thumb.parentElement.getBoundingClientRect();
  const half = spec.tile_width / 2;
  const left = Math.min(wrap.width - spec.tile_width, Math.max(0, clientX - wrap.left - half));
  thumb.style.left = `${left}px`;
  thumb.style.bottom = `${rect.height + 4}px`;
}

function seekFromHeat(clientX) {
  const seconds = secondsFromClientX(clientX);
  if (seconds === null) return;
  $("video").currentTime = seconds;
}

// 上端laneならIN/OUTの操作、それより下は従来通りseek。laneではhandle近傍・帯の内側・
// それ以外で挙動を分け、範囲未設定なら必ず"new"(押した点から伸ばす)へ落ちる。
function hitTestHeat(clientX, clientY, pointerType) {
  const rect = $("heat").getBoundingClientRect();
  if (clientY - rect.top > RANGE_LANE_PX) return "seek";
  const duration = $("video").duration;
  if (!isFinite(duration) || duration <= 0) return "seek";
  const x = clientX - rect.left;
  const toX = (seconds) => (seconds / duration) * rect.width;
  const tolerance = pointerType === "mouse" ? HANDLE_HIT_PX : HANDLE_HIT_TOUCH_PX;
  if (state.cutIn !== null && Math.abs(x - toX(state.cutIn)) <= tolerance) return "in";
  if (state.cutOut !== null && Math.abs(x - toX(state.cutOut)) <= tolerance) return "out";
  if (state.cutIn !== null && state.cutOut !== null
      && x > toX(state.cutIn) && x < toX(state.cutOut)) return "band";
  return "new";
}

const HEAT_CURSORS = {
  seek: "pointer",
  in: "ew-resize",
  out: "ew-resize",
  band: "grab",
  new: "crosshair",
};

// drag中はhandleの位置へ動画を追従させる。切り所を目で確かめながら詰められる。
function dragRange(event) {
  const seconds = secondsFromClientX(event.clientX);
  if (seconds === null) return;
  const video = $("video");
  if (dragMode === "seek") {
    seekFromHeat(event.clientX);
    return;
  }
  if (dragMode === "new") {
    setCut(Math.min(dragAnchor, seconds), Math.max(dragAnchor, seconds));
  } else if (dragMode === "in") {
    setCut(state.cutOut === null ? seconds : Math.min(seconds, state.cutOut), state.cutOut);
  } else if (dragMode === "out") {
    setCut(state.cutIn, state.cutIn === null ? seconds : Math.max(seconds, state.cutIn));
  } else if (dragMode === "band") {
    // 尺を保ったまま平行移動する。両端が動画の外へ出ないようclampする。
    const limit = isFinite(video.duration) ? video.duration - dragBandLength : seconds;
    const start = Math.max(0, Math.min(limit, seconds - dragBandOffset));
    setCut(start, start + dragBandLength);
  }
  video.currentTime = seconds;
}

// 確定は手打ちのIN/OUTと同じくsnapを通し、I/O keyと結果を一致させる。
// altを押している間はsnapを外す(NLE同様、一時的な微調整のため)。
function finishRangeDrag(event) {
  const mode = dragMode;
  dragMode = null;
  // capture中はpointerleaveが来ないので、bar外で離してもthumbが残らないよう明示的に隠す。
  $("thumb").classList.add("hidden");
  if (!mode || mode === "seek") return;
  if (state.cutIn === null || state.cutOut === null) return;
  if (event.altKey) return;
  setCut(snapToSegments(state.cutIn, "in"), snapToSegments(state.cutOut, "out"));
}

// ===== 切り出し =====

function setCut(inSec, outSec) {
  state.cutIn = inSec;
  state.cutOut = outSec;
  $("cut-in").textContent = inSec === null ? "--:--:--" : fmtDuration(inSec);
  $("cut-out").textContent = outSec === null ? "--:--:--" : fmtDuration(outSec);
  const valid = inSec !== null && outSec !== null && outSec > inSec;
  const reversed = inSec !== null && outSec !== null && outSec <= inSec;
  $("cut-len").textContent = valid
    ? `尺 ${fmtDuration(outSec - inSec)}`
    : (reversed ? "OUTがINより前です" : "-");
  $("do-clip").disabled = !valid || !state.current;
  $("add-cut").disabled = !valid || !state.current;
  drawHeat();
}

// 切り出しの共通指定。単発の切り出しと一括書き出しで同じ値を使う(画面で2箇所に持つと
// 「正規化したつもりの一括が素のまま」という食い違いが起きる)。
// 切り出しの設定はシーン検索と切り出しリストの両方から使う。片方にしかcontrolが無いと、
// もう片方に居る間は現在値が見えないまま一括書き出しが走る。DOMを2組持つが、値は
// この1組で持ち、どちらを操作しても両方へ書き戻す。
const CLIP_CONTROLS = [
  ["variant", "clip-variant", "cuts-variant", "value"],
  ["normalize_audio", "clip-normalize", "cuts-normalize", "checked"],
  ["mode", "clip-mode", "cuts-mode", "value"],
];

function clipOptions() {
  const opts = {};
  CLIP_CONTROLS.forEach(([key, primary, , prop]) => { opts[key] = $(primary)[prop]; });
  return opts;
}

// 一方を変えたら他方へ写す。値の出所は常にシーン検索側(primary)に置く。
function syncClipControls(fromMirror) {
  CLIP_CONTROLS.forEach(([, primary, mirror, prop]) => {
    if (fromMirror) $(primary)[prop] = $(mirror)[prop];
    else $(mirror)[prop] = $(primary)[prop];
  });
}

function bindClipControls() {
  CLIP_CONTROLS.forEach(([, primary, mirror]) => {
    $(primary).addEventListener("change", () => syncClipControls(false));
    $(mirror).addEventListener("change", () => syncClipControls(true));
  });
  syncClipControls(false);
}

async function runClip() {
  if (!state.current || state.cutIn === null || state.cutOut === null) return;
  const button = $("do-clip");
  button.disabled = true;
  $("player-status").textContent = "切り出し中…";
  try {
    const result = await apiSend("POST", `/api/recordings/${state.current.recording_id}/clip`, {
      start: state.cutIn,
      end: state.cutOut,
      label: state.query,
      ...clipOptions(),
    });
    // 実開始を必ず出す。stream copyはkeyframeからしか始まれないので、要求より手前へ
    // 伸びる。serverはずっとこの値を返していたのに画面が使っておらず、「30秒頼んで67秒」の
    // 理由が利用者から見えなかった。
    const lead = result.keyframe_lead_seconds;
    const note = lead
      ? `（実開始 ${fmtDuration(result.actual_start_seconds)} / 要求より ${lead.toFixed(1)}秒手前）`
      : "";
    $("player-status").textContent = `出力: ${result.path}${note}`;
    await copyText(result.path, "切り出しpathをcopyしました。");
  } catch (err) {
    $("player-status").textContent = err.message;
  }
  button.disabled = false;
}

// 今開いている録画の見どころ・切り出しをplayerの直下に出す。data(state.bookmarks /
// state.cuts)は既に読み込み済みで、追加取得は要らない。行clickはその場でseekするので
// view移動が起きない。
function renderOwnMarks() {
  const summary = document.getElementById("own-summary");
  const empty = document.getElementById("own-empty");
  const current = state.current;
  if (!current) {
    renderTableRows("own-rows", null, [], () => [], []);
    setListMessage(empty, "録画を開くとここに出ます。");
    summary.textContent = "";
    return;
  }
  const marks = (state.bookmarks || []).map((m) => ({
    kind: "見どころ", start: m.start, end: m.end, memo: m.memo || "",
  }));
  const cuts = (state.cuts || [])
    .filter((c) => c.recording_id === current.recording_id)
    .map((c) => ({ kind: "切り出し", start: c.start, end: c.end, memo: c.memo || "" }));
  const rows = [...marks, ...cuts].sort((a, b) => a.start - b.start);
  summary.textContent = rows.length
    ? `見どころ ${fmtNum(marks.length)} / 切り出し ${fmtNum(cuts.length)}`
    : "";
  renderTableRows(
    "own-rows", "own-empty", rows,
    (row) => [
      row.kind,
      fmtDuration(row.start),
      row.end === null || row.end === undefined ? "—" : fmtDuration(row.end),
      row.end === null || row.end === undefined ? "点" : fmtDuration(row.end - row.start),
      row.memo || "—",
    ],
    [1, 2, 3],
    (tr, row) => {
      tr.classList.add("vd-hit");
      tr.tabIndex = 0;
      tr.title = "clickでその位置へ移動します（範囲があればIN/OUTも入ります）。";
      const go = () => {
        $("video").currentTime = row.start;
        if (row.end !== null && row.end !== undefined) setCut(row.start, row.end);
      };
      tr.addEventListener("click", go);
      tr.addEventListener("keydown", (e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        e.preventDefault();
        go();
      });
    },
  );
  if (rows.length) setListState(empty, "ok");
}

// ===== 切り出しリスト =====

async function loadCuts() {
  try {
    const data = await apiSend("GET", "/api/cutlist");
    state.cuts = data.items || [];
  } catch (err) {
    $("cuts-summary").textContent = err.message;
    return;
  }
  const total = state.cuts.reduce((sum, cut) => sum + (cut.end - cut.start), 0);
  $("cuts-summary").textContent = state.cuts.length
    ? `${fmtNum(state.cuts.length)}件 / 合計 ${fmtDuration(total)}`
    : "";
  fillCutStreamers();
  renderCuts();
  renderOwnMarks();
}

function renderCuts() {
  renderTableRows(
    "cut-rows",
    "cut-empty",
    state.cuts,
    (cut) => {
      const remove = document.createElement("button");
      remove.className = "btn btn-small btn-danger";
      remove.textContent = "削除";
      remove.addEventListener("click", async (e) => {
        // 行click(再生へ戻る)と重ならないよう、削除は行へ伝播させない。
        e.stopPropagation();
        await apiSend("DELETE", `/api/cutlist/${cut.id}`);
        loadCuts();
      });
      const file = document.createElement("span");
      file.textContent = cut.filename || "-";
      // 解決済みのpathはNLEへ渡す実体そのもの。録画を移動していても今の場所が出る。
      if (cut.path) file.title = cut.path;
      return [
        cut.unique_id,
        fmtYmd(cut.recording_started_at),
        file,
        fmtDuration(cut.start),
        fmtDuration(cut.end),
        fmtDuration(cut.end - cut.start),
        cut.label || "",
        remove,
      ];
    },
    [3, 4, 5],
    (tr, cut) => {
      tr.classList.add("row-clickable");
      tr.tabIndex = 0;
      tr.title = "この範囲を再生画面で開きます（IN/OUTが入った状態になります）。";
      tr.addEventListener("click", () => openCut(cut));
      tr.addEventListener("keydown", (e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        e.preventDefault();
        openCut(cut);
      });
    },
  );
}

// 絞り込みの候補はlistに実際に入っている配信者だけにする。cutが1件も無い配信者を
// 並べても、選んだ先で「対象がありません」になるだけで手掛かりにならない。
function fillCutStreamers() {
  const select = $("cuts-streamer");
  const keep = select.value;
  const first = select.options[0];
  select.innerHTML = "";
  select.appendChild(first);
  [...new Set(state.cuts.map((cut) => cut.unique_id))].sort().forEach((uniqueId) => {
    const option = document.createElement("option");
    option.value = uniqueId;
    option.textContent = uniqueId;
    select.appendChild(option);
  });
  // 選んでいた配信者のcutが無くなった場合、一致するoptionが無いのでvalueは""に戻り、
  // 「全て」が選ばれた状態になる(消えた配信者を指したまま空の書き出しにはならない)。
  select.value = keep || $("flt-streamer").value;
}

// list書き出し。serverのerrorには混在しているfpsと件数が入っていて、それがそのまま
// 次の一手になる。window.location.hrefで遷移させると生のJSONへ飛んで文面が読めないので、
// fetchで受けて画面へ出す。
async function exportCutlist(format, uniqueId) {
  const params = new URLSearchParams({ format });
  if (uniqueId) params.set("unique_ids", uniqueId);
  let res;
  try {
    res = await fetch(`/api/cutlist/export?${params.toString()}`);
  } catch (e) {
    const err = new Error("Serverへ接続できませんでした。");
    err.status = 0;
    err.detail = String((e && e.message) || e);
    throw err;
  }
  if (!res.ok) {
    const payload = await res.json().catch(() => ({}));
    throw httpError(res.status, payload.detail);
  }
  const disposition = res.headers.get("Content-Disposition") || "";
  const named = /filename="([^"]+)"/.exec(disposition);
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = named ? named[1] : `tictok_cutlist.${format}`;
  a.click();
  URL.revokeObjectURL(url);
}

async function runCutlistExport() {
  const button = $("cuts-download");
  const format = $("cuts-fmt").value;
  const uniqueId = $("cuts-streamer").value;
  button.disabled = true;
  $("cuts-status").textContent = "";
  try {
    await exportCutlist(format, uniqueId);
    $("cuts-status").textContent = `${format.toUpperCase()}を書き出しました。`;
  } catch (err) {
    // serverの文面(どのfpsが何件混ざっているか)を置き換えない。独自の文面にすると、
    // 絞り込む相手を選ぶための情報が消える。
    showError(err);
    $("cuts-status").textContent = err.message;
    if (format === "edl") offerFcpxml();
  } finally {
    button.disabled = false;
  }
}

// EDLとFCPXMLの差はframe rateをlistで1つしか持てないかどうかだけ。混在が理由なら
// FCPXMLで出し直せるが、実測できない素材や0件が理由ならFCPXMLも同じく止まる(その場合も
// serverが理由を返す)ため、ここでは「出せます」とは言わない。
// EDLが書き出せなかったときの代案提示。確認ではなく選択肢なので、modalで画面を覆わず
// 失敗理由が既に出ている場所(cuts-status)の隣にそのままbuttonとして出す。
function offerFcpxml() {
  const status = $("cuts-status");
  if (status.querySelector(".vd-fallback")) return;
  const hint = document.createElement("span");
  hint.className = "vd-fallback";
  const btn = document.createElement("button");
  btn.className = "btn btn-small";
  btn.type = "button";
  btn.textContent = "FCPXMLで書き出す";
  btn.title = "FCPXMLは素材ごとにframe rateを持てるため、frame rateの混在が理由であればそのまま書き出せます。";
  btn.addEventListener("click", async () => {
    $("cuts-fmt").value = "fcpxml";
    await runCutlistExport();
  });
  hint.appendChild(btn);
  status.appendChild(hint);
}

// 切り出しリストから再生画面へ戻る。IN/OUTを復元するので、位置を詰めてから
// 出力し直したり、そのまま切り出したりできる。
async function openCut(cut) {
  showView("search");
  await openHit({
    recording_id: cut.recording_id,
    unique_id: cut.unique_id,
    started_at: cut.recording_started_at,
    video_time: cut.start,
  });
  setCut(cut.start, cut.end);
}

async function addCut() {
  if (!state.current || state.cutIn === null || state.cutOut === null) return;
  try {
    await apiSend("POST", "/api/cutlist", {
      recording_id: state.current.recording_id,
      start: state.cutIn,
      end: state.cutOut,
      label: state.query,
    });
    $("player-status").textContent = "切り出しリストに追加しました。";
    loadCuts();
  } catch (err) {
    $("player-status").textContent = err.message;
  }
}

// ===== 切り出し候補 =====
// 判定はserver側でcore.spikeが行う(配信者画面の見どころと同じ関数)。画面は並べるだけで、
// しきい値も窓の長さも持たない。

// 開いていて、かつ今の録画のぶんをまだ持っていないときだけ引く。
function maybeLoadCandidates() {
  if (!$("cand-block").open || !state.current) return;
  if (state.candidateRecordingId === state.current.recording_id) return;
  loadCandidates();
}

async function loadCandidates() {
  const summary = $("cand-summary");
  if (!state.current) {
    state.candidates = [];
    state.candidateRecordingId = null;
    summary.textContent = "";
    renderCandidates();
    return;
  }
  const recordingId = state.current.recording_id;
  summary.textContent = "候補を算出中…";
  try {
    const data = await apiSend("GET", `/api/recordings/${recordingId}/clip-candidates`);
    state.candidates = data.candidates || [];
    state.candidateRecordingId = recordingId;
    summary.textContent = state.candidates.length
      ? `${fmtNum(state.candidates.length)}件 / 窓${data.window_seconds}秒 / 先行${data.lead_seconds}秒 / padding前${data.pad_before_seconds}秒・後${data.pad_after_seconds}秒`
      : "この録画には基準を超える盛り上がりがありません。";
  } catch (err) {
    state.candidates = [];
    summary.textContent = err.message;
  }
  renderCandidates();
}

// 候補の根拠。serverのmetric名をそのまま画面語へ写す。三項演算子で2択にしていたころは
// 音量由来の候補が「Comment」と表示されていた。
const CANDIDATE_METRIC_LABELS = {
  diamonds: "コイン",
  comments: "Comment",
  audio_peak: "音量",
  laugh_comment: "笑い",
  laugh_audio: "笑い声",
  smile: "笑顔",
};

// 素材(録画)の解析から出る指標の列。serverが載せなかった指標はkeyが無く、その録画では
// 判定していないことを意味する — 0と表示すると「検出したが0だった」と読めてしまうので
// 「—」を出す。指標を足すときはここへ1 entryとvideos.htmlへ<th>を1つ足す。
const CANDIDATE_MATERIAL_COLUMNS = [
  { key: "laugh_audio", format: (value) => `${fmtNum(Math.round(value))}秒` },
  { key: "smile", format: (value) => `${fmtNum(Math.round(value))}秒` },
];

function renderCandidates() {
  const empty = $("cand-empty");
  empty.textContent = state.current
    ? "候補がありません。設定でしきい値を下げると増えます。"
    : "録画を開くと候補を出します。";
  renderTableRows(
    "cand-rows",
    "cand-empty",
    state.candidates,
    (candidate) => {
      const open = document.createElement("button");
      open.className = "btn btn-small";
      open.textContent = "開く";
      open.addEventListener("click", () => openCandidate(candidate));
      const add = document.createElement("button");
      add.className = "btn btn-small";
      add.textContent = "リストに追加";
      add.addEventListener("click", async () => {
        add.disabled = true;
        await addCandidate(candidate);
        add.disabled = false;
      });
      const actions = document.createElement("span");
      actions.className = "vd-row";
      actions.append(open, add);
      return [
        fmtDuration(candidate.start),
        fmtDuration(candidate.end),
        fmtDuration(candidate.end - candidate.start),
        CANDIDATE_METRIC_LABELS[candidate.metric] || candidate.metric,
        candidate.zscore.toFixed(1),
        fmtNum(candidate.diamonds),
        fmtNum(candidate.comments),
        fmtNum(candidate.laugh_comment || 0),
        ...CANDIDATE_MATERIAL_COLUMNS.map(({ key, format }) =>
          candidate[key] == null ? "—" : format(candidate[key]),
        ),
        actions,
      ];
    },
    [0, 1, 2, 4, 5, 6, 7, ...CANDIDATE_MATERIAL_COLUMNS.map((_, i) => 8 + i)],
  );
}

async function openCandidate(candidate) {
  if (!state.current) return;
  await openHit({
    recording_id: state.current.recording_id,
    unique_id: state.current.unique_id,
    started_at: state.current.started_at,
    video_time: candidate.start,
  });
  setCut(candidate.start, candidate.end);
}

async function addCandidate(candidate) {
  try {
    await apiSend("POST", "/api/cutlist", {
      recording_id: state.candidateRecordingId,
      start: candidate.start,
      end: candidate.end,
      label: candidate.label,
    });
    $("cand-summary").textContent = "切り出しリストに追加しました。";
  } catch (err) {
    $("cand-summary").textContent = err.message;
  }
}

// ===== 一括書き出し =====
// 実行はserverのqueue。録画ごとに1 jobへ束ねられるので、browserを閉じても続く。

async function exportCuts() {
  if (!state.cuts.length) {
    $("cuts-status").textContent = "切り出しリストが空です。";
    return;
  }
  const button = $("cuts-export");
  button.disabled = true;
  $("cuts-status").textContent = "queueへ投入中…";
  try {
    const result = await apiSend("POST", "/api/clips/batch", {
      items: state.cuts.map((cut) => ({
        recording_id: cut.recording_id,
        start: cut.start,
        end: cut.end,
        label: cut.label || null,
      })),
      ...clipOptions(),
    });
    $("cuts-status").textContent =
      `${fmtNum(result.total)}件を${fmtNum(result.jobs.length)}個のjobで書き出します（Job画面で進み具合を確認できます）。`;
  } catch (err) {
    $("cuts-status").textContent = err.message;
  }
  button.disabled = false;
}

async function makeReel() {
  if (!state.cuts.length) {
    $("cuts-status").textContent = "切り出しリストが空です。";
    return;
  }
  const button = $("cuts-reel");
  button.disabled = true;
  $("cuts-status").textContent = "queueへ投入中…";
  try {
    // 並べ替えない。表示した順と違う順で繋がれる方が、順序を指定できないより悪い誤認を生む。
    const result = await apiSend("POST", "/api/reels", {
      items: state.cuts.map((cut) => ({
        recording_id: cut.recording_id,
        start: cut.start,
        end: cut.end,
        label: cut.label || null,
      })),
      variant: $("cuts-variant").dataset.value || "source",
    });
    $("cuts-status").textContent =
      `${fmtNum(result.parts)}件を1本に連結します（Job画面で進み具合を確認できます）。`;
  } catch (err) {
    $("cuts-status").textContent = err.message;
  }
  button.disabled = false;
}

// ===== keyboard =====
// 5,000時間規模を相手にmouseだけで送るのは現実的でないので、NLE同等の操作を割り当てる。

function stopRewind() {
  if (rewindTimer !== null) {
    clearInterval(rewindTimer);
    rewindTimer = null;
  }
  rewindStep = -1;
}

function shuttleForward() {
  stopRewind();
  const video = $("video");
  forwardStep = video.paused ? 0 : Math.min(FORWARD_RATES.length - 1, forwardStep + 1);
  video.playbackRate = FORWARD_RATES[forwardStep];
  video.play().catch(() => {});
}

function shuttleRewind() {
  const video = $("video");
  video.pause();
  rewindStep = Math.min(REWIND_RATES.length - 1, rewindStep + 1);
  const rate = REWIND_RATES[rewindStep];
  if (rewindTimer !== null) clearInterval(rewindTimer);
  // <video>は逆再生を持たないので、一定間隔で戻すことで逆送りを作る。
  rewindTimer = setInterval(() => {
    video.currentTime = Math.max(0, video.currentTime - (REWIND_TICK_MS / 1000) * rate);
    if (video.currentTime <= 0) stopRewind();
  }, REWIND_TICK_MS);
}

function shuttleStop() {
  stopRewind();
  forwardStep = 0;
  applyRate();
  $("video").pause();
}

// ===== 倍速再生 =====
// J/K/Lのshuttleは「送る」ための一時的な速度。こちらは腰を据えて見る時の固定倍率で、
// 録画を切り替えても(=<video>がrateを1へ戻しても)選択を維持する。

function applyRate() {
  $("video").playbackRate = Number($("play-rate").value);
}

function nudgeRate(direction) {
  const select = $("play-rate");
  const next = Math.min(select.options.length - 1, Math.max(0, select.selectedIndex + direction));
  if (next === select.selectedIndex) return;
  select.selectedIndex = next;
  applyRate();
  $("player-status").textContent = `再生速度 ${select.value}x`;
}

// ===== 音量 =====
// <video>のvolumeは録画を切り替えても保持されるが、tabを開き直すと戻る。長時間の見返しで
// 毎回入れ直すのを避けるため記憶し、外出しのbar/表示を<video>側の変化にも追従させる。

function applyVolume() {
  const video = $("video");
  const value = Number($("volume").value) / 100;
  video.volume = value;
  // barを動かした=聞きたい/黙らせたいという意思なので、ミュート状態もそれに合わせる。
  video.muted = value === 0;
  syncVolumeUi();
}

function toggleMute() {
  const video = $("video");
  video.muted = !video.muted;
  // 0のままミュート解除しても無音で戻らないので、聞こえる位置まで戻す。
  if (!video.muted && video.volume === 0) video.volume = 0.5;
  syncVolumeUi();
}

function syncVolumeUi() {
  const video = $("video");
  const percent = Math.round(video.volume * 100);
  $("volume").value = String(percent);
  $("mute").classList.toggle("is-muted", video.muted || percent === 0);
  $("volume-label").textContent = video.muted ? "ミュート" : `${percent}%`;
  localStorage.setItem(VOLUME_PREF_KEY, String(percent));
  localStorage.setItem(MUTE_PREF_KEY, video.muted ? "1" : "0");
}

function restoreVolume() {
  const video = $("video");
  const saved = Number(localStorage.getItem(VOLUME_PREF_KEY));
  video.volume = Number.isFinite(saved) && saved >= 0 && saved <= 100 ? saved / 100 : 1;
  video.muted = localStorage.getItem(MUTE_PREF_KEY) === "1";
  syncVolumeUi();
}

// IN/OUTの当たりを繰り返し確かめるためのループ。OUTを跨いだらINへ戻す。
function loopRange() {
  if (!$("loop-range").checked) return;
  if (state.cutIn === null || state.cutOut === null || state.cutOut <= state.cutIn) return;
  const video = $("video");
  if (video.currentTime >= state.cutOut || video.currentTime < state.cutIn) {
    video.currentTime = state.cutIn;
  }
}

function stepFrames(event, direction) {
  stopRewind();
  const video = $("video");
  const amount = event.altKey ? 10 : event.shiftKey ? 1 : FRAME_STEP_SECONDS;
  video.currentTime = Math.max(0, video.currentTime + direction * amount);
}

function onKeydown(event) {
  const tag = (event.target.tagName || "").toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select") return;
  // segmented controlにfocusがある間は矢印/spaceはその群のもの。ここで横取りすると
  // 選択肢を移りながらframe送りと再生が同時に走る。
  if (event.target.closest && event.target.closest(".seg")) return;
  if (event.ctrlKey || event.metaKey) return;
  if ($("view-search").classList.contains("hidden")) return;
  const video = $("video");
  const key = event.key.toLowerCase();
  const handlers = {
    " ": () => (video.paused ? video.play().catch(() => {}) : video.pause()),
    j: shuttleRewind,
    k: shuttleStop,
    l: shuttleForward,
    i: () => setCut(snapToSegments(video.currentTime, "in"), state.cutOut),
    o: () => setCut(state.cutIn, snapToSegments(video.currentTime, "out")),
    arrowleft: () => stepFrames(event, -1),
    arrowright: () => stepFrames(event, 1),
    arrowup: () => moveHit(-1),
    arrowdown: () => moveHit(1),
    m: () => addBookmarkHere(),
    ",": () => nudgeRate(-1),
    ".": () => nudgeRate(1),
    // 範囲dragは誤選択しやすい。解除手段が無いと別録画を開くまで消せない。
    escape: () => setCut(null, null),
  };
  const handler = handlers[key];
  if (!handler) return;
  event.preventDefault();
  handler();
}

// ===== copy =====

async function copyText(text, message) {
  try {
    await navigator.clipboard.writeText(text);
    $("player-status").textContent = message;
  } catch {
    // clipboard APIはhttp origin等で拒否されることがある。手動copyできるよう値を出す。
    $("player-status").textContent = `copyできませんでした: ${text}`;
  }
}

function currentPath() {
  const select = $("path-variant");
  if (select.value) return select.value;
  const source = state.variants.find((v) => v.kind === "source");
  return source ? source.path : "";
}

// ===== 一括文字起こし =====

async function loadStatus() {
  let data;
  try {
    data = await apiSend("GET", "/api/search/status");
  } catch (err) {
    $("job-summary").textContent = err.message;
    return;
  }
  state.streamers = data.streamers || [];
  fillStreamerSelects();
  renderStreamers();
  renderQueue(data.queue);
}

function fillStreamerSelects() {
  [$("flt-streamer")].forEach((select) => {
    const keep = select.value;
    const first = select.options[0];
    select.innerHTML = "";
    select.appendChild(first);
    state.streamers.forEach((streamer) => {
      const option = document.createElement("option");
      option.value = streamer.unique_id;
      option.textContent = streamer.unique_id;
      select.appendChild(option);
    });
    select.value = keep;
  });
}

function renderStreamers() {
  renderTableRows(
    "streamer-rows",
    "streamer-empty",
    state.streamers,
    (streamer) => {
      const button = document.createElement("button");
      button.className = "btn btn-small";
      button.textContent = "文字起こし";
      button.disabled = streamer.transcribed >= streamer.recordings;
      button.addEventListener("click", () => enqueue(streamer.unique_id));
      return [
        streamer.unique_id,
        fmtNum(streamer.recordings),
        `${fmtNum(streamer.transcribed)} / ${fmtNum(streamer.recordings)}`,
        `${fmtNum(streamer.comment_indexed)} / ${fmtNum(streamer.recordings)}`,
        fmtDuration(streamer.seconds),
        button,
      ];
    },
    [1, 2, 3, 4],
  );
}

// 文字起こしは映像jobと同じ台帳(kind=stt)で走るので、stateの語彙もそちらに揃える。
// completed/skipped/interrupted はJob画面と同じ言葉で出す(同じ行を2つの名前で呼ばない)。
const QUEUE_LABELS = {
  running: "実行中",
  pending: "待機",
  completed: "完了",
  failed: "失敗",
  cancelled: "取消",
  skipped: "対象外",
  interrupted: "中断",
};

function renderQueue(queue) {
  const items = (queue && queue.items) || [];
  const counts = (queue && queue.counts) || {};
  const parts = Object.keys(QUEUE_LABELS)
    .filter((key) => counts[key])
    .map((key) => `${QUEUE_LABELS[key]} ${fmtNum(counts[key])}`);
  const available = queue && queue.available;
  $("job-summary").textContent = available
    ? parts.join(" / ") || "処理待ちはありません。"
    : "文字起こし機能が無効です。設定を確認してください。";

  renderTableRows(
    "queue-rows",
    "queue-empty",
    items,
    (item) => [
      QUEUE_LABELS[item.state] || item.state,
      item.unique_id,
      item.filename || "-",
      item.state === "running" ? `${item.pct}%` : (item.state === "completed" ? "100%" : "-"),
      item.error || "",
    ],
    [3],
  );
}

// 押せない理由は、押してから初めて分かるのでは遅い。buttonの状態と理由を同じ場所で決める。
function renderSemantic(status) {
  const button = $("semantic-build");
  const note = $("semantic-note");
  // 意味検索を選んでいるときだけ出す。語で一致しか使わない人には無関係な操作。
  $("semantic-inline").classList.toggle("hidden", $("flt-mode").value !== "semantic");
  if (!status) {
    button.disabled = false;
    note.textContent = "";
    button.title = "";
    return;
  }
  let reason = "";
  if (!status.enabled) {
    reason = "意味検索が無効です（TICTOK_SEMANTIC_ENABLED を確認してください）。";
  } else if (!status.available) {
    reason = `埋め込みmodelに接続できません（${status.base_url || "接続先未設定"}）。`;
  } else if (status.building) {
    reason = "意味検索indexを更新中です。完了までお待ちください。";
  }
  button.disabled = Boolean(reason);
  note.textContent = reason;
  button.title = reason;
}

async function loadSemantic() {
  try {
    renderSemantic(await apiSend("GET", "/api/search/semantic/status"));
  } catch (err) {
    // statusが取れないこと自体は操作を止める理由にならない。buildを叩けばserverが弾く。
    $("semantic-note").textContent = err.message;
  }
}

async function enqueue(uniqueId) {
  try {
    const result = await apiSend("POST", "/api/transcribe/queue", { unique_id: uniqueId || null });
    $("job-summary").textContent = `${fmtNum(result.added)}本を処理待ちへ追加しました。`;
    renderQueue(result.queue);
  } catch (err) {
    $("job-summary").textContent = err.message;
  }
}

// ===== 一括処理 =====

// 種別のラベルはserver側のMEDIA_JOB_TITLESと同じ語を使う。画面ごとに言い換えると、
// Job画面に並ぶjob titleと突き合わせられなくなる。
const BULK_LABELS = {
  transcribe: "文字起こし",
  overlay: "焼き込み出力", upscale: "Up出力", reprocess: "再mp4化", audionorm: "音量正規化",
  pack: "ts結合", delete_mp4: "元mp4の削除",
};
const BULK_SKIP_LABELS = {
  recording: "録画中",
  // 実体が何も無い(素材もmp4も)場合と、mp4だけが無い場合は別物。焼き込み・Up出力は素材
  // から出せるので前者でしか外れず、後者は元mp4を要る操作(音量正規化・元mp4の削除)だけの
  // 不足を指す。server側のBULK_SKIP_LABELSと同じ語であること。
  no_source: "素材もmp4も無い",
  no_file: "元mp4が無い",
  no_hls: ".tsが残っていない",
  packed: "結合済み",
  done: "処理済み",
  queued: "既にqueueにある",
  protected: "保護されている",
  busy: "処理中の録画",
  name_mismatch: "行とfile名が一致しない",
  unlink_failed: "削除できなかった",
};
// 作らずに消す種別。queueへは載せず専用APIで即時に実行するので、文言もbuttonも分ける。
const BULK_DELETE_KIND = "delete_mp4";
// 出力を作らない種別。元mp4の容量も所要の実測比も意味を持たないので、見積りの出し方を分ける。
const BULK_PACK_KIND = "pack";
// 走る先がmedia_job_queueではない種別。台帳がJob画面に出ないので、進捗の行き先を分ける。
const BULK_TRANSCRIBE_KIND = "transcribe";
// mp4を作らない種別。元mp4の合計を並べても確かめるべき数字にならないので、chipを分ける。
const BULK_NO_MP4_KINDS = [BULK_PACK_KIND, BULK_TRANSCRIBE_KIND];
// 「作り直す」余地が無い種別。ts結合は冪等(束ね済みは何もしない)で、削除は一方通行。
// 文字起こしは含めない — modelを替えたときや時刻mapの版が上がったときは転写し直す。
const BULK_NO_REDO_KINDS = [BULK_PACK_KIND, BULK_DELETE_KIND];

async function loadBulk() {
  // 集計は録画数ぶんのfile確認を伴うので数秒かかることがある。待っている間に古い/空の表を
  // そのまま出すと「表示しようとしているのか、対象が無いのか」が読めない。先に集計中を出す。
  $("bulk-summary").textContent = "集計中…（録画数が多いと数秒かかります）";
  if (!state.bulk.length) setListState($("bulk-empty"), "loading");
  let data;
  try {
    data = await apiSend(
      "GET", `/api/bulk/status?kinds=${encodeURIComponent(state.bulkKinds.join(","))}`);
  } catch (err) {
    state.bulkNote = err.message;
    setListState($("bulk-empty"), "failed", err);
    return;
  }
  state.bulk = data.streamers || [];
  state.bulkDisk = data.disk || null;
  renderBulk();
}

// 「出力済みも作り直す」を入れると、済んだ本数も対象へ戻る。
function bulkTargetCount(streamer, kind, redo) {
  const targets = (streamer.targets || {})[kind] || 0;
  const done = (streamer.done || {})[kind] || 0;
  return redo ? targets + done : targets;
}

// ---- 録画を選んでの投入 ----
// 可否の判定はserverの_bulk_classifyだけが持つ。画面側で「たぶん対象」を描くと、選べる
// のに投入されない録画が出る。

function closeBulkRows() {
  state.bulkOpen = null;
  state.bulkOpenRows = null;
  state.bulkSelected = new Set();
}

async function loadBulkRecordings(uniqueId) {
  const params = new URLSearchParams({
    kind: $("bulk-kind").value,
    unique_id: uniqueId,
    redo: $("bulk-redo").checked ? "1" : "0",
  });
  const data = await apiSend("GET", `/api/bulk/recordings?${params}`);
  state.bulkOpenRows = data.recordings || [];
  // 種別や再出力の指定を変えると投入できる録画が変わる。選択は残さず、今の条件で投入
  // できるものだけへ絞る(選んだつもりの録画が黙って落ちるより、選び直させる方が安い)。
  const eligible = new Set(state.bulkOpenRows.filter((r) => r.eligible).map((r) => r.id));
  state.bulkSelected = new Set([...state.bulkSelected].filter((id) => eligible.has(id)));
}

async function toggleBulkRows(uniqueId) {
  if (state.bulkOpen === uniqueId) {
    closeBulkRows();
    renderBulk();
    return;
  }
  closeBulkRows();
  state.bulkOpen = uniqueId;
  hideBulkConfirm();
  // 先に開いて「読み込み中」を出す。取得を待ってから開くと、押しても何も起きない間が空く。
  renderBulk();
  try {
    await loadBulkRecordings(uniqueId);
  } catch (err) {
    state.bulkOpenRows = [];
    state.bulkNote = err.message;
  }
  renderBulk();
}

function bulkDetailRow(streamer) {
  const tr = document.createElement("tr");
  tr.className = "bulk-detail";
  const cell = document.createElement("td");
  cell.colSpan = 6;
  tr.appendChild(cell);
  const rows = state.bulkOpenRows;
  if (rows === null) {
    cell.textContent = "録画を読み込み中…";
    return tr;
  }
  if (!rows.length) {
    cell.textContent = "この配信者の録画はありません。";
    return tr;
  }

  const tools = document.createElement("div");
  tools.className = "bulk-detail-tools";
  const selectAll = document.createElement("button");
  selectAll.className = "btn btn-small";
  selectAll.type = "button";
  selectAll.textContent = "投入できる全て";
  const clear = document.createElement("button");
  clear.className = "btn btn-small";
  clear.type = "button";
  clear.textContent = "選択を解除";
  const count = document.createElement("span");
  count.className = "vd-summary";
  const spacer = document.createElement("span");
  spacer.className = "sp";
  const run = document.createElement("button");
  run.className = "btn btn-primary btn-small";
  run.type = "button";
  tools.append(selectAll, clear, count, spacer, run);
  cell.appendChild(tools);

  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  const table = document.createElement("table");
  table.className = "result-table bulk-inner";
  table.innerHTML =
    "<thead><tr><th></th><th>録画</th><th>開始</th>"
    + '<th class="num">尺</th><th class="num">容量</th><th>状態</th></tr></thead>';
  const tbody = document.createElement("tbody");
  table.appendChild(tbody);
  wrap.appendChild(table);
  cell.appendChild(wrap);

  const eligible = rows.filter((r) => r.eligible);
  const paint = () => {
    count.textContent =
      `選択 ${fmtNum(state.bulkSelected.size)} / 投入できる ${fmtNum(eligible.length)}本`;
    run.textContent = $("bulk-kind").value === BULK_DELETE_KIND
      ? `選んだ${fmtNum(state.bulkSelected.size)}本のmp4を削除`
      : `選んだ${fmtNum(state.bulkSelected.size)}本を投入`;
    run.disabled = state.bulkSelected.size === 0;
  };

  rows.forEach((row) => {
    const line = document.createElement("tr");
    if (!row.eligible) line.className = "bulk-skip";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.disabled = !row.eligible;
    box.checked = state.bulkSelected.has(row.id);
    box.addEventListener("change", () => {
      if (box.checked) state.bulkSelected.add(row.id);
      else state.bulkSelected.delete(row.id);
      // 選択のたびに表ごと描き直すとcheckboxからfocusが外れ、連続して選べない。
      paint();
    });
    const statusText = row.eligible
      ? "投入できます"
      : (BULK_SKIP_LABELS[row.reason] || row.reason || "対象外");
    // seconds=0は「尺が0の録画」ではなく未測定。0:00と出すと見積りの母数から抜けている
    // ことが読めなくなるので、測っていないことをそのまま出す。
    [box, recTag(row), fmtDateTime(row.started_at),
     row.seconds > 0 ? fmtDuration(row.seconds) : "—",
     fmtBytes(row.bytes), statusText].forEach((value, col) => {
      const td = document.createElement("td");
      if (col === 3 || col === 4) td.className = "num";
      if (value instanceof Node) td.appendChild(value);
      else td.textContent = value;
      line.appendChild(td);
    });
    tbody.appendChild(line);
  });

  selectAll.addEventListener("click", () => {
    eligible.forEach((row) => state.bulkSelected.add(row.id));
    renderBulk();
  });
  clear.addEventListener("click", () => {
    state.bulkSelected.clear();
    renderBulk();
  });
  run.addEventListener("click", () =>
    askBulk(streamer.unique_id, [...state.bulkSelected]));
  paint();
  return tr;
}

// ---- 投入前の確認 ----
// 押した行の直下へ開く。表の外(toolbarの下)へ出していた頃は、開いた瞬間に配信者一覧が
// まるごと下へ動き、どの行に対する確認なのかも読み取れなかった。

function hideBulkConfirm() {
  state.bulkPending = null;
}

async function askBulk(uniqueId, recordingIds) {
  const kind = $("bulk-kind").value;
  const redo = $("bulk-redo").checked;
  $("bulk-summary").textContent = "見積りを計算中…";
  const params = new URLSearchParams({ kind, redo: redo ? "1" : "0" });
  if (uniqueId) params.set("unique_id", uniqueId);
  (recordingIds || []).forEach((id) => params.append("recording_id", id));
  let estimate;
  try {
    estimate = await apiSend("GET", `/api/bulk/estimate?${params}`);
  } catch (err) {
    state.bulkNote = err.message;
    renderBulk();
    return;
  }
  state.bulkPending = {
    kind, uniqueId: uniqueId || null, redo,
    recordingIds: recordingIds && recordingIds.length ? recordingIds : null,
    estimate,
  };
  state.bulkNote = "";
  renderBulk();
}

function appendBulkConfirm(tbody) {
  const pending = state.bulkPending;
  const estimate = pending.estimate;
  const tr = document.createElement("tr");
  tr.className = "bulk-confirm";
  const cell = document.createElement("td");
  cell.colSpan = 6;
  tr.appendChild(cell);

  const head = document.createElement("div");
  head.className = "bulk-confirm-head";
  // 何を投入しようとしているのかは、確認の見出しで名乗らせる。「この内容で投入」だけが
  // 出ていた頃は、その内容がどこにも書かれていなかった。
  head.textContent = "投入前の確認 — "
    + [BULK_LABELS[estimate.kind],
       estimate.unique_id ? `@${estimate.unique_id}` : "全配信者",
       pending.recordingIds ? `選んだ${fmtNum(pending.recordingIds.length)}本` : "未処理すべて",
       estimate.redo ? "処理済みも作り直す" : null,
      ].filter(Boolean).join(" / ");
  cell.appendChild(head);

  const chips = document.createElement("div");
  chips.className = "a-kpibar";
  chips.id = "bulk-estimate";
  cell.appendChild(chips);

  const skippedList = Object.entries(estimate.skipped || {});
  const skipped = document.createElement("div");
  skipped.className = "result-sub-note";
  skipped.textContent = skippedList.length
    ? "対象外: " + skippedList.map(([k, v]) => `${BULK_SKIP_LABELS[k] || k} ${fmtNum(v)}本`).join(" / ")
    : "";
  cell.appendChild(skipped);

  // 容量は「合計」ではなく空きと突き合わせて出す。jobは同時実行数ぶんしか走らないので、
  // 山になるのは中間fileを抱えるその本数ぶんで、合計値だけ見せると判断を誤らせる。
  const disk = estimate.disk || {};
  const volumes = Object.entries(disk.volumes || {});
  const free = volumes.length ? Math.min(...volumes.map(([, v]) => v.free_bytes)) : null;
  const notes = [];
  // 文字起こしはfileを作らない(書くのはDBのtranscript行だけ)。空き容量を並べると、
  // 確かめる必要の無い数字を確かめさせることになる。
  if (free !== null && estimate.kind !== BULK_TRANSCRIBE_KIND) {
    // ts結合が要るのは素材と同じだけの空きで、元mp4の容量とは関係が無い。ここへ元動画の
    // 合計を並べると、確かめるべき数字を取り違える。
    notes.push(estimate.kind === BULK_PACK_KIND
      ? `書き込み先の最小空き容量は ${fmtBytes(free)} です。`
      : `書き込み先の最小空き容量は ${fmtBytes(free)}、`
        + `同時に走るぶんの元動画は ${fmtBytes(estimate.largest_source_bytes)} です。`);
  }
  if (estimate.kind === BULK_TRANSCRIBE_KIND) {
    notes.push("文字起こしはfileを作らず、結果をDBへ保存して検索indexへ反映します。"
      + "GPUを1本ずつ直列に使うため、所要は本数ぶん積み上がります。"
      + "投入後の進捗と取り消しは「一括文字起こし」tabで行います（Job画面には出ません）。");
  }
  if ((disk.low_volumes || []).length && estimate.kind !== BULK_TRANSCRIBE_KIND) {
    notes.push(`空き容量が下限を下回っているvolumeがあります（${disk.low_volumes.join(", ")}）。`
      + "この状態では投入できません。");
  }
  if (estimate.kind === "overlay" || estimate.kind === "upscale") {
    notes.push("焼き込み・Up出力は再encodeのため、元動画と同程度以上の容量を出力先に使います。"
      + "処理中はそれとは別に中間fileの領域も必要です。");
  }
  if (estimate.kind === "audionorm") {
    notes.push("音量正規化は映像をそのまま複製し、音声だけを作り直して元のmp4と差し替えます。"
      + "元のmp4は_backup/へ退避するので、一時的に2本分の容量を使います。");
  }
  if (estimate.kind === "reprocess") {
    notes.push("再mp4化は保持している.tsから録画を作り直します。"
      + "設定「再mp4化: 元録画の音量も正規化する」がONなら、同時に音量も揃います。");
  }
  if (estimate.kind === BULK_PACK_KIND) {
    notes.push("ts結合は素材の.tsを解像度の切れ目ごとに1 fileへ束ね直します。再encodeしない"
      + "byte連結なので、映像も再生も再mp4化の結果も変わらず、file数だけが減ります。"
      + "束ねる間は元segmentを残したまま検証するため、その録画の素材と同じだけの空きが"
      + "一時的に要ります（足りない録画はjobが空き容量不足として止まります）。");
  }
  if (estimate.kind === BULK_DELETE_KIND) {
    notes.push("録画本体のmp4だけを削除します。焼き込み(.overlay.mp4)・Up出力(.up.mp4)・"
      + "名前を変えたfileは残します。削除後は同じ.tsから再mp4化で作り直せます。");
    // .tsが無い録画は、そのmp4が唯一の再取得不能資産。対象から外していることを、
    // 内訳の1行ではなく警告として名指しで出す。
    const noHls = (estimate.skipped || {}).no_hls || 0;
    if (noHls) {
      notes.push(`⚠ .tsが残っていない録画が${fmtNum(noHls)}本あります。`
        + "これらのmp4は作り直せないため削除しません（対象から外しています）。");
    }
  }
  const warn = document.createElement("div");
  warn.className = "form-message";
  warn.textContent = notes.join(" ");
  cell.appendChild(warn);

  const tools = document.createElement("div");
  tools.className = "vd-cuts-tools";
  const run = document.createElement("button");
  run.className = "btn btn-primary btn-small";
  run.type = "button";
  run.textContent = estimate.kind === BULK_DELETE_KIND
    ? `この内容で${fmtNum(estimate.recordings)}本のmp4を削除`
    : `この内容で${fmtNum(estimate.recordings)}本を投入`;
  if (estimate.kind === BULK_DELETE_KIND) run.className = "btn btn-danger btn-small";
  // 空き容量の下限割れで止めるのは、fileを書く種別だけ。文字起こしはfileを作らないので、
  // 空きが細っている状況でこそ先に回せる(serverの投入APIも同じ理由でdiskを見ない)。
  run.disabled = estimate.recordings === 0
    || (estimate.kind !== BULK_TRANSCRIBE_KIND && (disk.low_volumes || []).length > 0);
  run.addEventListener("click", () => runBulk(run));
  const cancel = document.createElement("button");
  cancel.className = "btn btn-small";
  cancel.type = "button";
  cancel.textContent = "やめる";
  cancel.addEventListener("click", () => { hideBulkConfirm(); renderBulk(); });
  tools.append(run, cancel);
  cell.appendChild(tools);

  tbody.appendChild(tr);
  // chipBarはid解決なので、行を挿してから呼ぶ。
  chipBar("bulk-estimate", estimate.kind === BULK_DELETE_KIND ? [
    ["対象", `${fmtNum(estimate.recordings)}本`],
    ["総録画時間", fmtDuration(estimate.seconds)],
    ["空く容量", fmtBytes(estimate.source_bytes)],
  ] : BULK_NO_MP4_KINDS.includes(estimate.kind) ? [
    // 束ねるのは素材、文字起こしが書くのはDBで、どちらもmp4は触らない。元mp4の容量を
    // 並べると何を処理するのか読み違える。
    ["対象", `${fmtNum(estimate.recordings)}本`],
    ["総録画時間", fmtDuration(estimate.seconds)],
    ["所要(実測比)", estimate.eta_seconds === null
      ? "実績が無いため不明"
      : `約${fmtDuration(estimate.eta_seconds)}（過去${fmtNum(estimate.eta_samples)}件から）`],
  ] : [
    ["対象", `${fmtNum(estimate.recordings)}本`],
    ["総録画時間", fmtDuration(estimate.seconds)],
    ["元mp4の合計", fmtBytes(estimate.source_bytes)],
    ["所要(実測比)", estimate.eta_seconds === null
      ? "実績が無いため不明"
      : `約${fmtDuration(estimate.eta_seconds)}（過去${fmtNum(estimate.eta_samples)}件から）`],
  ]);
}

function renderBulk() {
  const kind = $("bulk-kind").value;
  const redo = $("bulk-redo").checked;
  // 配信者画面から来たときは、その配信者だけを出す。全体を出すと目的の行を探し直す
  // ことになり、渡された選択が無駄になる。
  const rows = state.bulkOnly
    ? state.bulk.filter((s) => s.unique_id === state.bulkOnly)
    : state.bulk;
  // 種別によって「何が起きるか」が違う。作る種別の説明を消す種別にも出すと、
  // queueへ積まれるものと即時に消えるものの区別が付かない。
  // 「作り直す」余地の無い種別では再出力の指定を伏せる。押せる状態で残すと、投入本数の
  // 見え方(済みぶんを足すか)と実際に投入される本数が食い違う。
  const redoBox = $("bulk-redo");
  redoBox.disabled = BULK_NO_REDO_KINDS.includes(kind);
  if (redoBox.disabled) redoBox.checked = false;
  $("bulk-note").textContent = kind === BULK_DELETE_KIND
    ? "録画本体のmp4だけを即座に削除します（queueには載りません）。対象は.tsが残っている録画だけで、"
      + "作り直せない録画は自動で対象から外します。焼き込み・Up出力・名前を変えたfileは残ります。"
      + "削除後は種別を「再mp4化」にして投入すると、同じ.tsから作り直せます。"
    : kind === BULK_TRANSCRIBE_KIND
    ? "録画の音声を文字起こしして、シーン検索の対象にします（字幕の焼き込みにも要ります）。"
      + "配信者名の左の ▶ で録画一覧を開くと、選んだ録画だけを投入できます。"
      + "GPUを1本ずつ直列に使うため、投入後の進捗確認と取り消しは「一括文字起こし」tabで行います"
      + "（Job画面の台帳には出ません）。"
    : kind === BULK_PACK_KIND
    ? "素材の.tsを解像度の切れ目ごとに1 fileへ束ね直します（再encodeしないbyte連結で、映像も"
      + "再生も変わりません）。2秒ごとに刻まれたsegmentが数千本あると、走査・backup・移送の"
      + "すべてがfile数に比例して重くなるのを畳むための処理です。録画1本ごとに1つのjobとして"
      + "queueへ入り、束ね済みの録画は自動で対象から外れます。"
    : "録画1本ごとに1つのjobとしてqueueへ入り、順に処理します。配信者名の左の ▶ で録画一覧を開くと、"
      + "選んだ録画だけを投入できます。所要時間はこのserverで実際に完了した同種jobの実測から出しています"
      + "（実績が無い種別は不明と表示します）。投入後の進捗確認と取り消しはJob画面で行います。";
  // 進捗の行き先は種別で違う。文字起こしはJob画面の台帳に行が出ないので、そこへ誘導すると
  // 「投入したのに何も無い」画面へ送ることになる。
  const jobsLink = $("bulk-jobs-link");
  const toStt = kind === BULK_TRANSCRIBE_KIND;
  jobsLink.textContent = toStt ? "一括文字起こしで進捗を見る" : "Job画面で進捗を見る";
  jobsLink.href = toStt ? "#jobs" : "/jobs";
  $("bulk-filter").classList.toggle("hidden", !state.bulkOnly);
  $("bulk-filter-label").textContent = state.bulkOnly ? `@${state.bulkOnly} だけを表示中` : "";
  const total = rows.reduce((sum, s) => sum + bulkTargetCount(s, kind, redo), 0);
  // 投入結果や失敗の文言(bulkNote)は、次に条件を変えるまで残す。renderのたびに既定の
  // 集計文へ戻していた頃は、投入した瞬間に「入れました」が消えて何も起きていないように
  // 見えていた。
  $("bulk-summary").textContent = state.bulkNote
    || (total
      ? `${BULK_LABELS[kind]}の対象: ${state.bulkOnly ? "この配信者で" : "全体で"}${fmtNum(total)}本`
      : `${BULK_LABELS[kind]}の対象はありません。`);
  // 絞り込み中に「全配信者をまとめて」を押せると、見えている範囲と投入範囲がずれる。
  $("bulk-all").disabled = total === 0 || Boolean(state.bulkOnly);

  const tbody = $("bulk-rows");
  tbody.innerHTML = "";
  $("bulk-empty").classList.toggle("hidden", rows.length > 0);
  const pending = state.bulkPending;
  // 全配信者ぶんの確認だけは掛ける行が無いので表の先頭へ置く。
  if (pending && !pending.uniqueId) appendBulkConfirm(tbody);

  rows.forEach((streamer, index) => {
    const count = bulkTargetCount(streamer, kind, redo);
    const tr = document.createElement("tr");
    if (index === 0) tr.className = "rank-top";

    const name = document.createElement("div");
    name.className = "bulk-name";
    const toggle = document.createElement("button");
    toggle.className = "btn btn-small bulk-toggle";
    toggle.type = "button";
    const open = state.bulkOpen === streamer.unique_id;
    toggle.textContent = open ? "▼" : "▶";
    toggle.title = "録画一覧を開いて、投入する録画を選びます。";
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    toggle.addEventListener("click", () => toggleBulkRows(streamer.unique_id));
    const label = document.createElement("span");
    label.textContent = streamer.unique_id;
    name.append(toggle, label);

    const button = document.createElement("button");
    button.className = "btn btn-small";
    button.textContent = `${BULK_LABELS[kind]} ${fmtNum(count)}本`;
    button.title = "この配信者の対象すべてを投入します。選んで投入するときは ▶ を開いてください。";
    // 対象0本の行は押せない。押してから409で断られるより先に理由を消しておく。
    button.disabled = count === 0;
    button.addEventListener("click", () => askBulk(streamer.unique_id, null));

    [name, fmtNum(streamer.recordings), fmtNum(count),
     fmtNum((streamer.done || {})[kind] || 0), fmtDuration(streamer.seconds), button,
    ].forEach((value, col) => {
      const td = document.createElement("td");
      if (col >= 1 && col <= 4) td.className = "num";
      if (value instanceof Node) td.appendChild(value);
      else td.textContent = value;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);

    if (pending && pending.uniqueId === streamer.unique_id) appendBulkConfirm(tbody);
    if (open) tbody.appendChild(bulkDetailRow(streamer));
  });
}

async function runBulk(button) {
  const pending = state.bulkPending;
  if (!pending) return;
  const deleting = pending.kind === BULK_DELETE_KIND;
  // 削除は取り消せない。確認行だけで実行させず、もう一段だけ明示的に確かめる。
  if (deleting && !await confirmDialog(
    `${fmtNum(pending.estimate.recordings)}本の元mp4を削除します。`
    + "この操作は取り消せません（同じ.tsから再mp4化で作り直せます）。",
    { title: "元mp4の削除", confirmLabel: "削除する" })) return;
  button.disabled = true;
  try {
    const result = deleting
      ? await apiSend("POST", "/api/bulk/delete-mp4", {
        kind: pending.kind, unique_id: pending.uniqueId,
        recording_ids: pending.recordingIds,
      })
      : await apiSend("POST", "/api/bulk/queue", {
        kind: pending.kind, unique_id: pending.uniqueId, redo: pending.redo,
        recording_ids: pending.recordingIds,
      });
    hideBulkConfirm();
    state.bulkSelected = new Set();
    state.bulkNote = deleting
      ? `元mp4を${fmtNum(result.deleted)}本削除しました（${fmtBytes(result.freed_bytes)}）。`
        + "作り直すときは種別を「再mp4化」にして投入してください。"
      : `${BULK_LABELS[pending.kind]} ${fmtNum(result.total)}本をqueueへ入れました。`
        + (pending.kind === BULK_TRANSCRIBE_KIND
          ? "進捗の確認と取り消しは「一括文字起こし」tabで行います。"
          : "進捗の確認と取り消しはJob画面で行います。");
    // 転写queueの現況はtabを跨いで同じ台帳を見ている。投入した直後に「一括文字起こし」を
    // 開いたとき、古い表のままにしない。
    if (result.queue) renderQueue(result.queue);
    // 投入した録画は「既にqueueにある」へ変わる。開いている一覧もその状態へ揃える。
    if (state.bulkOpen) {
      try {
        await loadBulkRecordings(state.bulkOpen);
      } catch (err) {
        state.bulkOpenRows = [];
      }
    }
    loadBulk();
  } catch (err) {
    state.bulkNote = err.message;
    renderBulk();
    button.disabled = false;
  }
}

// ===== 起動 =====

// 排他選択のうち往復の多いものはsegmented controlで出す。listenerを付ける前に生やす
// (initSegmentedが.valueとchange eventを要素へ足すため、以降は<select>と同じに扱える)。
const SEGMENTED = [
  "flt-mode", "flt-order", "clip-variant", "cuts-variant", "clip-mode", "cuts-mode",
  "play-rate", "review-state"];

function bind() {
  SEGMENTED.forEach(initSegmented);
  // 録画を開くまで印は付けられない。
  setReviewControlEnabled(false);
  $("review-state").addEventListener("change", () => {
    if (!state.current) return;
    setReview(state.current.recording_id, $("review-state").value);
  });
  // 絞り込みは受け取り済みの一覧の上で効く。検索語があるときの行は録画ではなくシーンなので
  // 対象にならない — 効かない設定を押せる状態で並べず、その場でdisableして理由を出す。
  $("flt-review").addEventListener("change", () => {
    if (state.browsing) applyBrowseFilter();
  });

  VIEWS.forEach((view) => $(`tab-${view}`).addEventListener("click", () => showView(view)));

  $("q").addEventListener("input", scheduleSearch);
  ["src-stt", "src-comment", "flt-streamer", "flt-order", "flt-mode"].forEach((id) =>
    $(id).addEventListener("change", () => runSearch(true)),
  );
  $("flt-mode").addEventListener("change", () => loadSemantic());
  STREAMER_SELECTS.forEach((id) =>
    $(id).addEventListener("change", () => shareStreamerSelection(id)),
  );
  $("load-more").addEventListener("click", () => {
    state.offset += PAGE_SIZE;
    runSearch(false);
  });

  const video = $("video");
  $("mark-in").addEventListener("click", () =>
    setCut(snapToSegments(video.currentTime, "in"), state.cutOut),
  );
  $("mark-out").addEventListener("click", () =>
    setCut(state.cutIn, snapToSegments(video.currentTime, "out")),
  );
  $("do-clip").addEventListener("click", runClip);
  $("add-cut").addEventListener("click", addCut);
  document.addEventListener("keydown", onKeydown);

  // 文字起こしのdrag選択。mouseupはwindowで拾い、panel外で離しても確定させる。
  const segments = $("segments");
  let dragFrom = null;
  let dragged = false;
  segments.addEventListener("mousedown", (event) => {
    const index = segmentIndexOf(event.target);
    if (index === null) return;
    dragFrom = index;
    dragged = false;
    state.selFrom = index;
    state.selTo = index;
    paintSelection();
    event.preventDefault();
  });
  segments.addEventListener("mouseover", (event) => {
    if (dragFrom === null) return;
    const index = segmentIndexOf(event.target);
    if (index === null || index === state.selTo) return;
    state.selTo = index;
    dragged = true;
    paintSelection();
  });
  window.addEventListener("mouseup", () => {
    if (dragFrom === null) return;
    if (dragged) selectSegmentRange(dragFrom, state.selTo);
    else {
      state.selFrom = null;
      state.selTo = null;
      paintSelection();
      video.currentTime = state.segments[dragFrom].start;
    }
    dragFrom = null;
  });
  segments.addEventListener("dblclick", (event) => {
    const index = segmentIndexOf(event.target);
    if (index !== null) selectSegmentRange(index, index);
  });

  $("chapters").addEventListener("click", (event) => {
    const row = event.target.closest(".vd-seg");
    if (!row) return;
    video.currentTime = state.chapters[Number(row.dataset.index)].start;
  });
  $("do-chapters").addEventListener("click", generateChapters);
  $("copy-chapters").addEventListener("click", copyChapterText);
  $("save-chapters").addEventListener("click", () => {
    if (state.current) location.href = chapterExportUrl("vtt");
  });

  $("comments").addEventListener("click", (event) => {
    const row = event.target.closest(".vd-cmt");
    if (!row) return;
    const comment = state.comments[Number(row.dataset.index)];
    const mark = event.target.closest(".vd-cmt-mark");
    if (mark) {
      toggleCommentBookmark(comment, mark);
      return;
    }
    video.currentTime = comment.t;
  });

  $("add-mark").addEventListener("click", addBookmarkHere);
  // 入力中のEnterで即記録できると、見ながら書いて残す流れが途切れない。
  $("mark-memo").addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    addBookmarkHere();
  });
  $("play-rate").addEventListener("change", applyRate);

  $("volume").addEventListener("input", applyVolume);
  $("mute").addEventListener("click", toggleMute);
  // native controls側でも音量は変えられるので、そちらの変化に外出しbarを追従させる。
  video.addEventListener("volumechange", syncVolumeUi);
  restoreVolume();

  const onTick = () => {
    loopRange();
    drawHeat();
    updateTimeLabel();
    highlightActiveSegment();
    highlightActiveChapter();
    highlightActiveComment();
  };
  video.addEventListener("timeupdate", onTick);
  // 録画を切り替えると<video>はplaybackRateを1へ戻す。選択中の倍率を入れ直す。
  video.addEventListener("loadedmetadata", () => {
    applyRate();
    onTick();
  });
  window.addEventListener("resize", drawHeat);

  $("do-transcribe").addEventListener("click", transcribeCurrent);
  Object.entries(RECORDING_JOBS).forEach(([kind, spec]) =>
    $(spec.button).addEventListener("click", () => startRecordingJob(kind)),
  );
  // 素材版は再生にも効く。切り出しリストtab側から写ってきた値はsetter経由で入るため
  // changeが出ない。あちらにも受け口を置く(syncClipControlsは何度呼んでも同じ)。
  $("clip-variant").addEventListener("change", () => reloadPlayback(true));
  $("cuts-variant").addEventListener("change", () => {
    syncClipControls(true);
    reloadPlayback(true);
  });

  // pointer captureで、bar外へ出てもdragが続く(長時間録画を粗く送るときに切れない)。
  // 波形は初回生成が長いので明示ONのときだけ取りに行く。毎回入れ直す手間を無くすため
  // ON/OFFは記憶する。
  const showWave = $("show-wave");
  showWave.checked = localStorage.getItem(WAVE_PREF_KEY) === "1";
  showWave.addEventListener("change", () => {
    localStorage.setItem(WAVE_PREF_KEY, showWave.checked ? "1" : "0");
    if (state.current) loadWaveform(state.current.recording_id);
    else drawHeat();
  });

  const heat = $("heat");
  heat.addEventListener("pointerdown", (event) => {
    const seconds = secondsFromClientX(event.clientX);
    if (seconds === null) return;
    heat.setPointerCapture(event.pointerId);
    dragMode = hitTestHeat(event.clientX, event.clientY, event.pointerType);
    if (dragMode === "seek") {
      seekFromHeat(event.clientX);
    } else if (dragMode === "new") {
      dragAnchor = seconds;
      setCut(seconds, seconds);
    } else if (dragMode === "band") {
      dragBandOffset = seconds - state.cutIn;
      dragBandLength = state.cutOut - state.cutIn;
    }
  });
  heat.addEventListener("pointermove", (event) => {
    // dragMode自体がdown〜upの間だけ立つので、captureの成否には依存させない。
    if (dragMode) {
      dragRange(event);
    } else {
      heat.style.cursor = HEAT_CURSORS[hitTestHeat(event.clientX, event.clientY, event.pointerType)];
    }
    showThumb(event.clientX);
  });
  heat.addEventListener("pointerleave", () => $("thumb").classList.add("hidden"));
  heat.addEventListener("pointerup", (event) => {
    heat.releasePointerCapture(event.pointerId);
    finishRangeDrag(event);
  });
  heat.addEventListener("pointercancel", () => {
    dragMode = null;
    $("thumb").classList.add("hidden");
  });

  $("copy-path").addEventListener("click", () => copyText(currentPath(), "pathをcopyしました。"));
  $("copy-time").addEventListener("click", () =>
    copyText(fmtDuration(video.currentTime), "時刻をcopyしました。"),
  );
  $("copy-both").addEventListener("click", () => {
    const inSec = state.cutIn === null ? video.currentTime : state.cutIn;
    const outSec = state.cutOut === null ? "" : fmtDuration(state.cutOut);
    copyText(
      `${currentPath()}\tIN ${fmtDuration(inSec)}${outSec ? `\tOUT ${outSec}` : ""}`,
      "path+IN/OUTをcopyしました。",
    );
  });

  $("cuts-download").addEventListener("click", runCutlistExport);
  $("cuts-export").addEventListener("click", exportCuts);
  $("cuts-reel").addEventListener("click", makeReel);
  bindClipControls();
  $("cand-block").addEventListener("toggle", maybeLoadCandidates);
  $("cand-add-all").addEventListener("click", async () => {
    const button = $("cand-add-all");
    button.disabled = true;
    for (const candidate of state.candidates) await addCandidate(candidate);
    $("cand-summary").textContent = `${fmtNum(state.candidates.length)}件を切り出しリストへ追加しました。`;
    button.disabled = false;
  });
  $("cuts-clear").addEventListener("click", async () => {
    const count = (state.cuts || []).length;
    if (!count) return;
    const ok = await confirmDialog(
      `切り出しリストの${fmtNum(count)}件をすべて削除しますか？この操作は取り消せません。`,
      { title: "切り出しリストの全削除", confirmLabel: "すべて削除", danger: true },
    );
    if (!ok) return;
    try {
      await apiSend("DELETE", "/api/cutlist");
    } catch (err) {
      showError(err);
      return;
    }
    loadCuts();
  });

  $("semantic-build").addEventListener("click", async () => {
    const button = $("semantic-build");
    button.disabled = true;
    $("job-summary").textContent = "意味検索indexを更新中…";
    try {
      // serverは受け付けた時点で返す(構築は数時間かかることがある)。完了の件数は
      // WSのsemantic_indexで届くので、ここでは開始したことだけを出す。
      await apiSend("POST", "/api/search/semantic/build");
      $("job-summary").textContent =
        "意味検索indexの構築を開始しました。進捗はJob画面で確認できます。";
    } catch (err) {
      $("job-summary").textContent = err.message;
    } finally {
      // finallyでないと、通信断や画面遷移でbuttonが押せないまま残る。
      // 再有効化の可否はserverのstatusに従う(別のbuildが走っている場合は塞いだまま)。
      button.disabled = false;
      loadSemantic();
    }
  });

  // 種別や再出力の指定を変えたら、見せている見積りは別物になる。出したまま残すと
  // 「確認した内容」と「投入される内容」が食い違う。開いている録画一覧の可否も種別
  // ごとに変わるので、開いたまま条件を変えたら取り直す。
  ["bulk-kind", "bulk-redo"].forEach((id) =>
    $(id).addEventListener("change", async () => {
      hideBulkConfirm();
      state.bulkNote = "";
      // まだ集計していない種別(=再mp4化)を初めて選んだら、その種別ぶんの集計を取りに行く。
      // .ts走査はここで初めて走り、以降その種別へは即時で切り替わる。他種別は読み込み済みで即時。
      const kind = $("bulk-kind").value;
      if (!state.bulkKinds.includes(kind)) {
        state.bulkKinds = [...state.bulkKinds, kind];
        await loadBulk();
      } else {
        renderBulk();
      }
      if (state.bulkOpen) {
        const uniqueId = state.bulkOpen;
        state.bulkOpenRows = null;
        renderBulk();
        try {
          await loadBulkRecordings(uniqueId);
        } catch (err) {
          state.bulkOpenRows = [];
          state.bulkNote = err.message;
        }
        renderBulk();
      }
    }),
  );
  $("bulk-all").addEventListener("click", () => askBulk(null, null));
  // 文字起こしの進捗は同じ画面の別tabにある。/jobsへ飛ばすとJob画面の台帳(転写の行は
  // 出ない)へ送ることになるので、遷移せずtabだけを切り替える。
  $("bulk-jobs-link").addEventListener("click", (event) => {
    if ($("bulk-kind").value !== BULK_TRANSCRIBE_KIND) return;
    event.preventDefault();
    showView("jobs");
  });
  $("bulk-filter-clear").addEventListener("click", () => {
    state.bulkOnly = null;
    hideBulkConfirm();
    closeBulkRows();
    renderBulk();
  });

  $("job-enqueue-all").addEventListener("click", () => enqueue(null));
  $("job-cancel").addEventListener("click", async () => {
    try {
      const result = await apiSend("DELETE", "/api/transcribe/queue", { recording_ids: null });
      $("job-summary").textContent = `${fmtNum(result.cancelled)}本を取り消しました。`;
      renderQueue(result.queue);
    } catch (err) {
      $("job-summary").textContent = err.message;
    }
  });
}

// 切り出しの既定(音量正規化・方式)は設定画面が持つ。画面側にhard-codeしない。
async function loadClipDefaults() {
  try {
    const data = await apiSend("GET", "/api/settings");
    const byKey = new Map((data.settings || []).map((entry) => [entry.key, entry.value]));
    if (byKey.has("clip_normalize_audio")) {
      $("clip-normalize").checked = Boolean(Number(byKey.get("clip_normalize_audio")));
    }
    const mode = byKey.get("clip_default_mode");
    if (mode) {
      ["clip-mode", "cuts-mode"].forEach((id) => { $(id).value = String(mode); });
    }
  } catch (err) {
    $("player-status").textContent = err.message;
  }
}

function onMessage(message) {
  if (message.type === "transcribe_queue") {
    renderQueue(message.status);
    if (message.indexed_recording_id) {
      // 文字起こしが1本終わるたびに検索対象が増えるので、開いている検索結果を追従させる。
      loadStatus();
      if (state.query) runSearch(true);
      // 開いたまま終わった録画は、その場で文字起こしを読み直して反映する。
      if (state.current && state.current.recording_id === message.indexed_recording_id) {
        loadTranscript(message.indexed_recording_id);
      }
    }
  } else if (message.type === "semantic_index") {
    // 別tab/別clientが始めたbuildでも塞がるよう、開始と完了の両方で飛んでくる。
    renderSemantic(message.status);
    // 完了時だけresult、失敗時だけerrorが載る。応答を待たなくなったので、結果も失敗も
    // ここが唯一の出所(押した直後の「開始しました」を上書きしないと、死んでも気付けない)。
    if (message.error) {
      $("job-summary").textContent = `意味検索indexの構築に失敗しました: ${message.error}`;
    } else if (message.result) {
      $("job-summary").textContent =
        `意味検索index: ${fmtNum(message.result.passages ?? 0)} passage / `
        + `${fmtNum(message.result.hits ?? 0)}件から構築しました。`;
    }
  } else if (message.type === "job_update" && message.job.domain === "clip_batch") {
    const job = message.job;
    if (job.state === "running") {
      $("cuts-status").textContent = `一括書き出し ${job.stage || ""} ${job.pct}%`.trim();
    } else if (job.state === "completed") {
      $("cuts-status").textContent = `一括書き出しが終わりました（${fmtNum(job.result.count ?? 0)}件）。`;
    } else if (job.state !== "pending") {
      $("cuts-status").textContent = `一括書き出し: ${job.message || job.state}`;
    }
  } else if (message.type === "job_update" && message.job.domain === "reel") {
    const job = message.job;
    if (job.state === "running") {
      $("cuts-status").textContent = `連結 ${job.stage || ""} ${job.pct}%`.trim();
    } else if (job.state === "completed") {
      const r = job.result || {};
      // 指定尺と前置きを両方出す。実録画では30秒の範囲に37秒の前置きが付いた例があるので、
      // 実尺だけを見せると「90秒のつもりが134秒」の理由が分からない。
      const parts = [`連結しました（${fmtNum(r.parts ?? 0)}件）`];
      if (r.requested_seconds != null && r.lead_seconds != null) {
        parts.push(`指定尺 ${fmtDuration(r.requested_seconds)}`
          + ` ＋ 前置き ${fmtDuration(r.lead_seconds)}`
          + ` ＝ 実尺 ${fmtDuration(r.output_duration_seconds ?? 0)}`);
      }
      $("cuts-status").textContent = `${parts.join(" / ")}: ${r.filename || ""}`;
    } else if (job.state !== "pending") {
      $("cuts-status").textContent = `連結: ${job.message || job.state}`;
    }
  } else if (message.type === "job_update" && BULK_LABELS[message.job.domain]) {
    const job = message.job;
    // 1本終わるたびに対象数が変わる。開いていないtabの引き直しは無駄なので出さない。
    // groupの行(recording_idを持たない集計行)は個別完了の後に来るだけなので無視する。
    if (job.state === "completed" && job.recording_id
        && !$("view-bulk").classList.contains("hidden")) {
      loadBulk();
    }
    // 開いている録画のjobなら、素材版の在り方が変わるのでplayer側にも反映する。
    if (state.current && job.recording_id === state.current.recording_id) {
      onRecordingJobUpdate(job);
    }
  } else if (message.type === "transcribe_progress") {
    // noteは再試行待ちのときだけ載る。%は動かないので、これが無いと固まって見える。
    const label = message.note || `文字起こし中 ${message.pct}%`;
    const summary = $("job-summary");
    if (message.pct < 100 || message.note) summary.textContent = label;
    // 再生中の録画の進捗は、jobs tabを開かなくても分かるようplayer側にも出す。
    if (state.current && state.current.recording_id === message.recording_id
        && (message.pct < 100 || message.note)) {
      $("transcript-note").textContent = label;
    }
  }
}

bind();
bindVideoError(
  $("video"),
  () => (state.current ? state.current.recording_id : null),
  (text) => { $("player-status").textContent = text; },
);
// 運用log画面の「文字起こしqueue」からの遷移先。tabを自分で探させない。
if (location.hash === "#transcribe") showView("jobs");
// 配信者画面からの遷移先。あちらは1人ぶんの容量整理をしている最中なので、同じ配信者を
// 選んだ状態の一括処理へそのまま入れるようにする。
if (location.hash === "#bulk") {
  state.bulkOnly = new URLSearchParams(location.search).get("streamer") || null;
  showView("bulk");
}
loadStatus();
loadSemantic();
loadClipDefaults();
// 開いた時点で録画一覧を出す。語なしの一覧はrunSearchが担うが、起動時は誰も呼ばないため
// 「検索語を入力してください」のまま止まり、当たる語を先に発明しないと1本も開けなかった
// (確認状態の印も、一覧が出ていなければ目に入らない)。
runSearch(true);
// player直下の「この録画の見どころ・切り出し」はcut listを使う。tabを開くまで
// 読まないと、録画を開いた直後だけ切り出しが抜けた一覧になる。
loadCuts();
connectWS(onMessage);
