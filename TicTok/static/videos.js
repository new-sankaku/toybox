// 配信者動画: 複数配信を横断してシーンを探し、素材として切り出す編集アシスト画面。
// 検索hitはvideo_time(mp4のPTS秒)を持つのでそのままseekできる。

const PAGE_SIZE = 200;
const SEARCH_DEBOUNCE_MS = 250;
// window幅が変わるとtimelineは波形の畳み込みからやり直す(列数が畳み込みcacheの一部で、
// 1px動いただけでも作り直しになる)。resizeはdrag中ずっと届くので、手が止まってから
// 1回だけ描き直す。短いのは、掴んで離すまでの間だけbarが引き伸ばされて見えるため。
const RESIZE_DEBOUNCE_MS = 120;
// IN/OUTを発話境界へ吸着させる許容幅。これを超えて離れていれば手打ちの位置を尊重する。
const SNAP_WINDOW_SECONDS = 1.5;
const FRAME_STEP_SECONDS = 1 / 30;
const FORWARD_RATES = [1, 1.5, 2, 4];
const REWIND_RATES = [2, 4, 8];
const REWIND_TICK_MS = 100;
// bar上端のこの帯だけを範囲の新規作成・平行移動にあて、それより下は従来通りclick/dragで
// 移動する。modifier方式は発見できず、touchでは押せないので採らない。
const RANGE_LANE_PX = 14;
const HANDLE_HIT_PX = 8;
const HANDLE_HIT_TOUCH_PX = 16;
// IN/OUT線は帯の全高に描いてあるので、lane内でしか掴めないと「線の上を掴んだのにseekした」
// になる(全尺barは高さの2〜3割しかlaneが無い)。lane外でも掴めるようにし、代わりに許容幅を
// この割合まで絞る — 全尺barは1px≈数秒あり、lane内と同じ幅を全高へ広げるとhandleの周りで
// seekできない帯ができる。
const HANDLE_HIT_BODY_RATIO = 0.5;
const HANDLE_DRAW_PX = 6;
const PLAYHEAD_KNOB_PX = 5;
// bar下端のこの帯を見どころmarker専用にあてる。波形・heatと重ねると、どちらが記録した
// 位置なのか読めなくなる。
const BOOKMARK_LANE_PX = 8;
// 拡大窓下端の時刻ruler。無いと拡大中に「今どの辺りか」が全尺barへ目を往復しないと
// 分からなくなる。
const RULER_LANE_PX = 14;
// 拡大窓の幅の可動域(秒)。下限より詰めても0.1s刻みの波形が箱状になるだけで情報は増えない。
const ZOOM_MIN_SPAN_SECONDS = 8;
const ZOOM_DEFAULT_SPAN_SECONDS = 90;
// wheel1段あたりの拡縮率と、左右移動1段で動く距離(窓幅に対する割合)。
const ZOOM_WHEEL_FACTOR = 1.3;
const ZOOM_PAN_STEP = 0.2;
// 追従が窓外の再生位置を置き直すとき、窓のどこへ置くか(左端からの割合)。左寄せなのは
// 再生が右へ進むため、置いた直後から先の波形が見える。
const ZOOM_FOLLOW_ANCHOR = 0.2;
// 境界確認再生(IN確認/OUT確認)の前後幅。手前を長めに取るのは、切れ目の良し悪しが
// 「入りの文脈」で決まるため。
const PREVIEW_BEFORE_SECONDS = 2;
const PREVIEW_AFTER_SECONDS = 1;
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
  // 波形はserver固定の時間刻み(bucket_seconds)の全尺列1本。全尺bar・拡大窓とも
  // この列を描画時に畳んで使う(解像度別に引き直すと録画全体のdecodeが再走するため)。
  wave: null,
  waveBucketSeconds: 0.1,
  // 無音区間 [{start, end}]。波形と同じresponseで届き、snapとシーン選択の吸着先になる。
  silences: [],
  // 拡大窓の位置(左端の秒)と幅。位置はここだけが持ち、追従はこれを置き直す(followZoom)。
  // nullは「まだ決まっていない」で、最初の描画で再生位置から決まる。
  zoomStart: null,
  zoomSpan: ZOOM_DEFAULT_SPAN_SECONDS,
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
  // グループ(切り抜き動画1本の単位)の一覧と、見どころ・切り出しリストで共有する選択。
  // 値は "":全て / "none":未分類 / "<id>":そのグループ。両tabで同じ値を指すので、
  // 片方で選んだグループの中身をもう片方でもそのまま見ている。
  groups: [],
  groupSel: "",
  // 見どころ・切り出しの記録先グループ。"none":未分類 / "<id>"。localStorageで残す。
  addGroup: "none",
  // 選択中の行id。まとめての付け替え(移動先へ入れる)と削除の対象。
  cutsSelected: new Set(),
  marksSelected: new Set(),
  // shift+クリックの範囲選択の起点(表示順のindex)。表を描き直しても続けて使えるよう
  // 行要素ではなくindexで持つ。
  lastPick: { cuts: null, marks: null },
  // 一括の行き先("none" | "<id>")。表のすぐ上のselectの値で、tabの表示選択とは別物。
  moveTarget: { cuts: "none", marks: "none" },
  // ドラッグ中の行(tabへ放り込む経路)。dataTransferはdragover中に中身を読めないため、
  // 行き先の可否判定に使う情報はここに持つ。
  drag: null,
  // 今開いている録画の切り出し候補と、その算出元になった録画id。
  candidates: [],
  candidateRecordingId: null,
};

let rewindTimer = null;
let rewindStep = -1;
let forwardStep = 0;

// heat bar上のdrag: null | "seek" | "in" | "out" | "band" | "new" | "zoompan"
let dragMode = null;
let dragAnchor = 0;
let dragBandOffset = 0;
let dragBandLength = 0;
// 拡大窓のdrag移動。窓そのものが動くので、x→秒の換算は押した瞬間の値で固定する
// (動いた窓で換算し直すと窓がpointerから加速して逃げる)。
let panStartX = 0;
let panStartSeconds = 0;
let panSecondsPerPx = 0;
// dragが拡大窓上で始まったか。x→秒の換算を全尺barと拡大窓のどちらで行うかを決める。
let dragOnZoom = false;
// drag中に凍結した拡大窓。追従が生きたままだとdrag中に窓が滑り、pointerの下の時刻が
// 動いてhandleが逃げる。
let zoomDragWindow = null;
// 境界確認再生の停止時刻。nullなら確認再生中ではない。
let previewStopAt = null;

let searchTimer = null;
let resizeTimer = null;

const $ = (id) => document.getElementById(id);

// ===== view切替 =====

const VIEWS = ["search", "marks", "cuts", "bulk"];

// 配信者の選択はtabを跨いで引き継ぐ。3つのselectが独立していたため、
// tabを移るたび「今どの配信者の作業をしているか」を選び直す必要があった。
// cuts-streamerだけは候補が実在するcutに限られるので、無ければ「全て」へ落ちる。
const STREAMER_SELECTS = ["flt-streamer", "cuts-streamer", "bulk-streamer"];

function shareStreamerSelection(fromId) {
  const value = $(fromId).value;
  STREAMER_SELECTS.forEach((id) => {
    const select = $(id);
    if (id === fromId) return;
    // 一致するoptionが無ければvalueは""(全て)になる。存在しない配信者は指させない。
    select.value = value;
  });
  // 一括処理の絞り込みはselectを唯一の入力にした。他tabから値が入る経路(programmaticな
  // 代入ではchangeが飛ばない)でも、modelが画面と食い違わないようここで揃える。
  state.bulkOnly = $("bulk-streamer").value || null;
}

function showView(name) {
  VIEWS.forEach((view) => {
    $(`view-${view}`).classList.toggle("hidden", view !== name);
    $(`tab-${view}`).classList.toggle("active", view === name);
  });
  // 画面に無いplayerは止める。鳴り続けると、どこから音が出ているのか分からなくなる
  // (本編と見どころのplayerが二重に鳴る)。shortcutのspaceはシーン検索tabでしか効かない
  // ので、離れた先から本編を止める手段が無い点も同じ理由で塞ぐ。
  pauseInlinePlayers(name);
  if (name !== "search") {
    const video = $("video");
    // 読み込みも位置も捨てない。戻れば続きから再生できる。
    if (video && !video.paused) video.pause();
  }
  if (name === "cuts") loadCuts();
  if (name === "marks") loadMarks();
  if (name === "bulk") {
    loadBulk();
    // 文字起こしのqueueと転写率は一括処理tabの中に畳んである。開いた時点で最新にする。
    if ($("bulk-kind").value === BULK_TRANSCRIBE_KIND) loadStatus();
  }
}

// ===== 検索 =====

function selectedSources() {
  const sources = [];
  if ($("src-stt").checked) sources.push("stt");
  if ($("src-comment").checked) sources.push("comment");
  if ($("src-laugh").checked) sources.push("laugh");
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
  // 意味検索はscore順で返る別endpointで、orderを載せる先が無い。押せるまま残すと、
  // pillは動くのに並びが変わらず「壊れている」と読まれる(#flt-reviewと同じ作法)。
  const bySemantic = $("flt-mode").value === "semantic";
  $("flt-order").querySelectorAll(".seg-item").forEach((item) => {
    item.disabled = bySemantic;
    item.title = bySemantic
      ? "意味検索は「意味が近い順」で返るため、並べ替えは使えません。"
      : "";
  });
  // 語が無いときは録画一覧を出す。ここで打ち切ると「当たる語を先に発明しないと
  // 1本も開けない」状態になり、転写が無い録画は永久に開けなくなる。検索対象(音声/
  // Comment)は「シーンの探し先」であって録画一覧とは無関係なので、その判定より先に置く。
  if (!query) {
    await loadBrowse();
    return;
  }
  if (!sources.length) {
    state.hits = [];
    state.total = 0;
    state.browsing = false;
    renderHits();
    $("search-summary").textContent = "";
    setListMessage($("hit-empty"), "検索対象（音声／Comment）を選んでください。");
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
  // 空振りの理由は方式で違う。意味検索にANDは無いので、語の組み合わせを疑わせる文言を
  // 出すと、実際の原因(index未構築・埋め込みmodel未接続)へ辿り着けない。
  setListMessage($("hit-empty"), data.mode === "semantic"
    ? "近い意味の発話が見つかりません。indexが古い場合は上の「意味検索indexを更新」を実行してください。"
    : "該当するシーンがありません。複数語のANDは1つの発話・Commentの中で判定されます。");
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

// hitの出所を名乗る語。serverのsource名をそのまま画面語へ写す。三項演算子で2択に
// していたころに笑い声を足すと、笑いの行が「Comment」と名乗ってしまった。
const HIT_SOURCES = { stt: "音声", comment: "Comment", laugh: "笑い声" };

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
      kind.className = `vd-src vd-src-${HIT_SOURCES[hit.source] ? hit.source : "comment"}`;
      kind.textContent = HIT_SOURCES[hit.source] || hit.source;
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
  } else {
    // 見どころ・切り出し・候補から開いた場合は一覧の位置を渡されない。前の選択を残すと、
    // 画面には別の録画が出ているのに一覧では前の行が選択中のままになり、↑↓が無関係の
    // 録画を読み込む(波形・転写・コメントを全部取り直す)。同じ録画が一覧に居れば
    // そこへ合わせ、居なければ選択を落とす。
    const found = state.hits.findIndex((row) => row.recording_id === hit.recording_id);
    state.hitIndex = found;
  }
  highlightHitRow();
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
    // 拡大窓も仕切り直す。前の録画で狭めた窓や追従OFFを引き継ぐと、開いた直後に
    // 「どこも映っていない」拡大窓が出る。
    state.zoomStart = null;
    state.zoomSpan = ZOOM_DEFAULT_SPAN_SECONDS;
    $("zoom-follow").checked = true;
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
    drawTimeline();
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
      drawTimeline();
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
      drawTimeline();
    }
  } catch {
    state.heat = [];
    drawTimeline();
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

// 再生位置を含む発話。転写segmentは開始順で重ならない(whisperの出力をそのまま持つ)ため、
// commentと同じく二分探索で引ける。3時間級の録画は1万文に届くので、timeupdate毎の線形走査は
// それだけで再生を鈍らせる。
function activeSegmentIndex(now) {
  const segments = state.segments;
  let low = 0;
  let high = segments.length - 1;
  let found = -1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (segments[mid].start <= now) {
      found = mid;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  if (found < 0) return -1;
  // 発話と発話の間(無音)はどのsegmentにも入らない。直前の発話が終わっているなら
  // 「今の行」は無い — commentと違い、転写は終端を持つのでそこまで見る。
  const segment = segments[found];
  return now < (segment.end ?? segment.start) ? found : -1;
}

function highlightActiveSegment() {
  const container = $("segments");
  const rows = container.children;
  if (!rows.length) return;
  const active = activeSegmentIndex($("video").currentTime);
  if (active === state.segmentIndex) return;
  // 変わった2行だけを塗り替える。全行をtoggleしていた頃は、行数ぶんのstyle書き換えが
  // timeupdate毎に走り、直後のscroll追従が読む位置がそのlayout再計算を待たされていた。
  const previous = rows[state.segmentIndex];
  if (previous) previous.classList.remove("vd-seg-active");
  state.segmentIndex = active;
  const row = rows[active];
  if (row) row.classList.add("vd-seg-active");
  // 追従は既定ON。読み返している最中に勝手に飛ぶのが邪魔な場面もあるので切れるようにする。
  if (row && $("transcript-follow").checked) centerRowIn(container, row);
}

// 発話の途中で切れたclipは素材にならないので、手打ちのIN/OUTを最寄りの発話境界へ寄せる。
// 吸着先は転写segmentの境界と無音の縁の両方。無音の縁は転写していない録画でも波形さえ
// あれば効く。INは無音明け(発話の頭)、OUTは無音入り(発話の尾)へ寄せる。
function snapToSegments(seconds, kind) {
  if (!$("snap-seg").checked) return seconds;
  let best = seconds;
  let bestGap = SNAP_WINDOW_SECONDS;
  const consider = (candidate) => {
    if (candidate === undefined || candidate === null) return;
    const gap = Math.abs(candidate - seconds);
    if (gap < bestGap) {
      bestGap = gap;
      best = candidate;
    }
  };
  state.segments.forEach((segment) =>
    consider(kind === "in" ? segment.start : segment.end));
  state.silences.forEach((span) =>
    consider(kind === "in" ? span.end : span.start));
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
  $("chapter-block").classList.add("vd-block-collapsed");
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
  // 章の無い録画では一覧を出さずに畳む。空欄が高さを取ると文字起こしとコメントが狭くなる。
  $("chapter-block").classList.toggle("vd-block-collapsed", state.chapters.length === 0);
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
  // 行を捨てたら控えも捨てる。取得に失敗してrenderCommentsまで進まなかった場合に、
  // 画面から外れた前の録画のbuttonを掴んだままにしない。
  commentMarkButtons = [];
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

// 行頭の★button。renderCommentsが作った順に控える。見どころが1件増減するたびに
// 行数ぶんのquerySelectorでDOMから引き直すと、コメントの多い録画では★を押すたびに
// 引っかかる。行を作り直すときは必ずここも作り直す(下のrenderComments/loadComments)。
let commentMarkButtons = [];

function renderComments() {
  const container = $("comments");
  container.innerHTML = "";
  commentMarkButtons = [];
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
    // 記録済みかどうかは下のsyncCommentMarksが決める。ここでは「押していない」を
    // 明示しておく(aria-pressedが欠けた行を作らない)。
    paintCommentMark(mark, false);
    commentMarkButtons.push(mark);
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
// 1行の★の見え方。押した/押していないは色・aria-pressed・tooltipの3つで揃えて出す。
function paintCommentMark(button, on) {
  button.classList.toggle("vd-cmt-mark-on", on);
  button.setAttribute("aria-pressed", on ? "true" : "false");
  button.title = on ? "見どころから外す" : "この位置を見どころに記録";
}

function syncCommentMarks() {
  const buttons = commentMarkButtons;
  if (!buttons.length) return;
  const ids = markedHitIds();
  for (let index = 0; index < buttons.length; index += 1) {
    const button = buttons[index];
    const comment = state.comments[index];
    const on = comment !== undefined && ids.has(comment.id);
    // 変わっていない行は触らない。1件の増減で全行を書き換えると、見た目が1つも変わらない
    // のに全行が描き直しの対象になる。行を作る時点で必ず塗ってあるので取りこぼさない。
    if (button.getAttribute("aria-pressed") === (on ? "true" : "false")) continue;
    paintCommentMark(button, on);
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
  drawTimeline();
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
  drawTimeline();
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
  const groupId = currentAddGroupId();
  try {
    await apiSend("POST", "/api/bookmarks", {
      recording_id: state.current.recording_id,
      start,
      end,
      memo,
      source_hit_id: sourceHitId,
      group_id: groupId,
    });
  } catch (err) {
    $("player-status").textContent = err.message;
    showError(err);
    return;
  }
  // どこへ入ったかまで出す。M keyは記録先を選んだ操作から離れて押されるので、時刻だけだと
  // 「入ったが行き先が違う」に気付けない。
  const where = end === null
    ? fmtDuration(start)
    : `${fmtDuration(start)} - ${fmtDuration(end)}`;
  const message = `見どころに記録しました（${where} → ${groupNameOf(groupId) || "未分類"}）`;
  $("player-status").textContent = message;
  showToast(message);
  flashBookmark(start, end);
  await loadBookmarks(state.current.recording_id);
}

// ===== 記録直後の合図 =====
// M keyは動画を見ている最中に押されるので、視線は再生画面かtimelineにある。statusの1行は
// そこから遠く、同じ文面を2度出しても字面が変わらないため「入ったのか」が読めない。
// 画面内notificationに加えて、入った位置そのものをtimeline上で光らせる。
const MARK_FLASH_MS = 1600;
let markFlash = null;
let markFlashFrame = null;

function flashBookmark(start, end) {
  markFlash = { start, end: end === undefined ? null : end, until: performance.now() + MARK_FLASH_MS };
  if (markFlashFrame === null) markFlashFrame = requestAnimationFrame(stepMarkFlash);
}

// 停止中はdrawTimelineを回す者が居ないので、光っている間だけ自前でframeを回す。
function stepMarkFlash() {
  markFlashFrame = null;
  if (!markFlash) return;
  if (performance.now() >= markFlash.until) markFlash = null;
  drawTimeline();
  if (markFlash) markFlashFrame = requestAnimationFrame(stepMarkFlash);
}

// 点滅させると位置より瞬きへ目が行く。明るく出してまっすぐ消す。
function markFlashAlpha() {
  if (!markFlash) return 0;
  return Math.max(0, Math.min(1, (markFlash.until - performance.now()) / MARK_FLASH_MS));
}

// 記録した位置。全尺barでは点のmarkerが数pxしか無いので、光だけは見失わない太さで出す。
// toXは秒→x座標の写像で、全尺barと拡大窓が別の写像を渡してくる。
function drawMarkFlash(ctx, width, height, toX) {
  const alpha = markFlashAlpha();
  if (alpha <= 0) return;
  const x0 = toX(markFlash.start);
  const x1 = markFlash.end === null ? x0 : toX(markFlash.end);
  if (x1 < 0 || x0 > width) return;
  ctx.fillStyle = `rgba(169, 110, 73, ${0.3 * alpha})`;
  ctx.fillRect(x0, 0, Math.max(3, x1 - x0), height);
  ctx.fillStyle = `rgba(214, 138, 74, ${0.95 * alpha})`;
  ctx.fillRect(x0 - 1, 0, 2, height);
  if (x1 > x0) ctx.fillRect(x1 - 1, 0, 2, height);
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
    const message = `見どころから外しました（${fmtDuration(comment.t)}）`;
    $("player-status").textContent = message;
    showToast(message);
    await loadBookmarks(state.current.recording_id);
  } catch (err) {
    $("player-status").textContent = err.message;
    showError(err);
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
  const failure = await refreshGroupData();
  if (failure) $("marks-summary").textContent = failure;
  renderGroupViews();
}

// グループ選択を掛けた表示対象。
function visibleMarks() {
  return (state.marks || []).filter((mark) => matchesGroup(mark, state.groupSel));
}

function renderMarksView() {
  const rows = visibleMarks();
  $("marks-summary").textContent = rows.length ? `${fmtNum(rows.length)}件` : "";
  // グループtabはupdateMarksSelection()から選択件数込みで描き直す。
  renderMoveBar("marks");
  renderMarks();
}

// 選択状況の表示と、選択で決まるbuttonの活性。
function updateMarksSelection() {
  const rows = visibleMarks();
  const count = state.marksSelected.size;
  $("marks-selected").textContent = count ? `選択 ${fmtNum(count)}件` : "";
  $("marks-bulk-delete").disabled = !count;
  $("marks-select-all").checked = rows.length > 0 && count === rows.length;
  updateMoveButtons("marks");
  renderGroupBar("marks-groups", "marks");
}

function renderMarks() {
  const rows = visibleMarks();
  // 表示から消えた行の選択は捨てる(見えない行への一括操作を残さない)。
  const visibleIds = new Set(rows.map((mark) => mark.id));
  state.marksSelected = new Set([...state.marksSelected].filter((id) => visibleIds.has(id)));
  renderTableRows(
    "mark-rows",
    "mark-empty",
    rows,
    (mark, rowNumber) => {
      const pick = pickBoxFor("marks", rows, rowNumber - 1, mark.id, () => renderMarks());
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
          // 成功時に画面が何も変わらないと、保存されたのか離れ方が悪くて捨てられたのかを
          // 判別できず、確かめるために画面を読み込み直すことになる。
          showToast("メモを保存しました。");
        } catch (err) {
          $("marks-summary").textContent = err.message;
        }
      });
      const watch = document.createElement("button");
      watch.className = "btn btn-small";
      watch.textContent = "視聴";
      watch.title = "このtabのまま、この位置から再生します。";
      watch.addEventListener("click", () => markPlayer.play(mark));
      const open = document.createElement("button");
      open.className = "btn btn-small";
      open.textContent = "シーン検索視聴";
      open.title = "シーン検索の再生画面で開きます（波形・IN/OUT・転写つき）。";
      open.addEventListener("click", () => openMark(mark));
      // 範囲付きの見どころはここから直接切り出しリストへ回せる。以前は切り出しリスト
      // tab側の作業台にしか置いておらず、しかもグループを選んだ時だけ現れる場所だった
      // ため、見どころを見ている画面には昇格の経路が1つも出ていなかった。
      const promote = document.createElement("button");
      promote.className = "btn btn-small";
      const ranged = mark.end !== null && mark.end !== undefined;
      // 押しても行の見た目が変わらなかったため、押したかどうかを行から読み取れず、
      // 同じ範囲のcutが何本でも作れていた(書き出して初めて重複に気付く)。
      const promoted = ranged ? promotedCutOf(mark) : null;
      promote.textContent = promoted ? "切り出し済" : "切り出しへ";
      promote.disabled = !ranged || Boolean(promoted);
      promote.title = promoted
        ? `この範囲は既に切り出しリスト（${groupNameOf(promoted.group_id) || "未分類"}）にあります。`
        : (ranged
          ? "この範囲を、この見どころと同じグループの切り出しリストへ入れます。"
          : "範囲がありません。「シーン検索視聴」でIN/OUTを決めてから追加してください。");
      promote.addEventListener("click", () => promoteMark(mark, "marks-status"));
      const remove = document.createElement("button");
      remove.className = "btn btn-small btn-danger";
      remove.textContent = "削除";
      remove.addEventListener("click", async () => {
        // 1件削除は最も高頻度で、しかも「切り出しへ」「視聴」と同じ行に並ぶ。まとめて
        // 削除する側にだけ確認が付いていて、誤clickしやすい方が素通しなのは逆である。
        const ok = await confirmDialog(
          `この見どころを削除します（${fmtDuration(mark.start)}${mark.memo ? ` ${mark.memo}` : ""}）。この操作は取り消せません。`,
          { title: "見どころの削除", confirmLabel: "削除する" },
        );
        if (!ok) return;
        await apiSend("DELETE", `/api/bookmarks/${mark.id}`);
        // 消した見どころを観たまま残さない(実体の無い行を再生し続けることになる)。
        const seen = markPlayer.watching();
        if (seen && seen.id === mark.id) markPlayer.close();
        if (state.current) loadBookmarks(state.current.recording_id);
        loadMarks();
      });
      const actions = document.createElement("span");
      actions.className = "vd-row";
      actions.append(watch, open, promote, remove);
      const hasRange = mark.end !== null && mark.end !== undefined;
      return [
        pick,
        mark.unique_id,
        fmtYmd(mark.recording_started_at),
        fmtDuration(mark.start),
        hasRange ? fmtDuration(mark.end - mark.start) : "点",
        memo,
        groupSelectFor(mark, "marks"),
        actions,
      ];
    },
    [3, 4],
    (tr, mark) => {
      bindRowDrag(tr, "marks", mark.id);
      // 掴める見た目なのにclickは無反応で、切り出し行とは合図と挙動が逆になっていた。
      // 行clickはこのtabの中で再生する(切り出し側のように画面ごと移らないぶん安全)。
      tr.classList.add("row-clickable");
      tr.tabIndex = 0;
      tr.title = "この見どころをこのtabのまま再生します。";
      tr.addEventListener("click", (event) => {
        // 行内のbutton・メモ欄・グループ欄は独自の操作を持つ。素通しすると「視聴」を
        // 押しただけで再生が二重に走り、読み込みも2回投げられる。
        if (event.target.closest("button, input, select, a")) return;
        markPlayer.play(mark);
      });
    },
  );
  updateMarksSelection();
}

// 選択した見どころの削除。所属の付け替えは上段のグループtabから行う。
async function deleteSelectedMarks() {
  const ids = [...state.marksSelected];
  if (!ids.length) return;
  const ok = await confirmDialog(
    `選択した${fmtNum(ids.length)}件の見どころを削除しますか？この操作は取り消せません。`,
    { title: "選択の削除", confirmLabel: "削除", danger: true },
  );
  if (!ok) return;
  try {
    const result = await apiSend("POST", "/api/bookmarks/bulk", { op: "delete", ids });
    $("marks-status").textContent = `${fmtNum(result.affected)}件を削除しました。`;
    const seen = markPlayer.watching();
    if (seen && ids.includes(seen.id)) markPlayer.close();
    state.marksSelected.clear();
  } catch (err) {
    $("marks-status").textContent = err.message;
  }
  if (state.current) loadBookmarks(state.current.recording_id);
  await refreshGroupData();
  renderGroupViews();
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
  inheritAddGroup(mark.group_id);
}

// ===== 一覧tabの中で観るplayer(見どころ・切り出しリスト共用) =====

// 一覧を持つtabの中だけで使うplayer。再生経路(HLS/mp4)の決め方はシーン検索側と同じだが、
// 本編playerとは別の<video>・別のHls instanceで持つ。1つを共有すると、tabを移るたびに
// 相手の位置と読み込みを壊し合う。見どころと切り出しリストも互いに別instanceにするので、
// 片方で観ている録画は、もう片方のtabを触っても読み込み直しにならない。
// prefixはHTML側のid接頭辞("mark" / "cut")、nounは終端で止めた時に名乗る対象。
function createInlinePlayer(prefix, noun) {
  const el = (name) => $(`${prefix}-${name}`);
  const say = (text) => { el("play-status").textContent = text; };
  let hls = null;
  // 読み込み要求の世代。連続で別の行を押すと前の応答が後から届く。
  let token = 0;
  // 今この場で読み込んである録画。同じ録画の別の位置へはseekだけで移る。
  let loadedId = null;
  // 今観ている行。削除された時に画面から下げるための身元。
  let watching = null;
  // 範囲付きの終端。ここで一度止める。nullなら止めない。
  let stopAt = null;

  // 右列は畳まない(畳むと観るたび左の表幅が動き、行を追えなくなる)。playerを下げている
  // 間は同じ場所に案内を出し、列そのものは残す。
  function stage(on) {
    el("play").classList.toggle("hidden", !on);
    el("play-empty").classList.toggle("hidden", on);
  }

  function close() {
    const video = el("video");
    token += 1;
    watching = null;
    stopAt = null;
    loadedId = null;
    video.pause();
    if (hls) {
      hls.destroy();
      hls = null;
    }
    video.removeAttribute("src");
    video.load();
    stage(false);
    say("");
  }

  // 位置決めは尺が分かってからでないと効かない。読み込み途中なら分かった時点で入れる。
  // 待っている間に別の行へ移っていたら、こちらの位置は古いので捨てる。
  function seekTo(at, want) {
    const video = el("video");
    if (video.readyState >= 1) {
      video.currentTime = at;
      video.play().catch(() => {});
      return;
    }
    video.addEventListener(
      "loadedmetadata",
      () => {
        if (want !== token) return;
        video.currentTime = at;
        video.play().catch(() => {});
      },
      { once: true },
    );
  }

  async function play(item) {
    // 本編playerと同時には鳴らさない。画面は別でも音は重なる。
    $("video").pause();
    const video = el("video");
    const hasRange = item.end !== null && item.end !== undefined;
    watching = item;
    stopAt = hasRange ? item.end : null;
    stage(true);
    // 素材版が元録画固定であることを名乗る。シーン検索側で「焼き込み」を選んで作業した後、
    // ここで出来を確かめるつもりで観ると素のままの映像が出て、焼き込みが失敗していると
    // 誤読する。切り替えて確かめる先(シーン検索視聴)も同じ場所で案内する。
    const head = el("play-head");
    head.textContent =
      `${item.unique_id} / ${fmtDateTime(item.recording_started_at)} / ${fmtDuration(item.start)}`
      + (hasRange ? ` - ${fmtDuration(item.end)}` : "")
      + ` / 素材: ${VARIANT_LABELS.source}`;
    head.title = "この場での再生は常に元録画です。焼き込み・Up出力の出来を確かめる場合は"
      + "「シーン検索視聴」で開いてください。";
    // 同じ録画の中を移るだけなら読み込み直さない(HLSを張り直すと数秒待たされる)。
    if (loadedId === item.recording_id) {
      say("");
      seekTo(item.start, (token += 1));
      return;
    }
    say("読み込み中…");
    const want = (token += 1);
    let playback;
    try {
      // 素材版は元録画に固定する。切り出し素材の指定(clip-variant)は出来上がりの確認用で、
      // どの場面かを確かめるのとは目的が違う。
      playback = await apiSend(
        "GET", `/api/recordings/${item.recording_id}/playback?variant=source`);
    } catch (err) {
      if (want === token) say(err.message);
      return;
    }
    if (want !== token) return;
    if (hls) {
      hls.destroy();
      hls = null;
    }
    if (playback.mode === "hls" && window.Hls && window.Hls.isSupported()) {
      hls = new window.Hls();
      hls.loadSource(playback.url);
      hls.attachMedia(video);
      hls.on(window.Hls.Events.ERROR, (_e, data) => {
        // hls.jsが握った失敗は<video>のerror eventにならないので、ここで理由を出す。
        if (data.fatal) say("この録画を再生できませんでした。");
      });
    } else if (playback.mode === "hls" && !video.canPlayType("application/vnd.apple.mpegurl")) {
      say("このBrowserはHLS再生に対応していません。");
      return;
    } else {
      video.src = playback.url;
    }
    loadedId = item.recording_id;
    say(playback.mode === "hls" ? "" : "この録画は.tsが残っていないため、mp4を再生しています。");
    seekTo(item.start, want);
  }

  return {
    play,
    close,
    // tabを移るときは音だけが残らないよう止める。読み込みは捨てない(戻ってきたら続きから)。
    pause() { if (watching) el("video").pause(); },
    // 今観ている行。消えた行を観たまま残さないための身元照合と、「シーン検索視聴」の
    // 対象に使う。
    watching() { return watching; },
    // 範囲付きは終端で一度止める。「どこまでが対象か」を観ているだけで分かるようにする
    // ため。止めた後は解除するので、そのまま再生を押せば続きを観られる。
    onTimeUpdate() {
      if (stopAt === null) return;
      const video = el("video");
      if (video.currentTime < stopAt) return;
      stopAt = null;
      video.pause();
      say(`${noun}の終端です。再生を押すと続きを観られます。`);
    },
    // mp4経路の失敗は<video>のerror eventにしか出ない。小さなplayerなので、browserの
    // 壊れた枠だけだと「押しても何も起きなかった」と読める。src除去(閉じる)でもerrorは
    // 飛ぶので、観ている対象がある時だけ理由を出す。
    onError() { if (watching) say("この録画を再生できませんでした。"); },
  };
}

const markPlayer = createInlinePlayer("mark", "見どころ");
const cutPlayer = createInlinePlayer("cut", "切り出し");

// tabを離れる時は、そのtabのplayerだけを止める。
function pauseInlinePlayers(name) {
  if (name !== "marks") markPlayer.pause();
  if (name !== "cuts") cutPlayer.pause();
}

// player枠のbutton・<video>のevent。toSearchは「シーン検索視聴」の行き先で、観ている
// 対象をそのままシーン検索の再生画面で開く。
function bindInlinePlayer(prefix, player, toSearch) {
  $(`${prefix}-video`).addEventListener("timeupdate", () => player.onTimeUpdate());
  $(`${prefix}-video`).addEventListener("error", () => player.onError());
  $(`${prefix}-play-close`).addEventListener("click", () => player.close());
  $(`${prefix}-play-search`).addEventListener("click", () => {
    const item = player.watching();
    if (item) toSearch(item);
  });
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

  // 波形は上段。時間刻みの全尺列を1pxごとの列へ畳む(bucket i の時刻は i*bucket_seconds で、
  // waveform側がPTS軸へ揃えてある)。
  const folded = foldWaveFull(duration, width);
  if (folded) {
    const waveHeight = bodyH * 0.45;
    ctx.fillStyle = "rgba(90, 110, 120, 0.55)";
    for (let x = 0; x < folded.length; x += 1) {
      const barHeight = folded[x] * waveHeight;
      ctx.fillRect(x, bodyTop + (waveHeight - barHeight) / 2 + 1, 1, Math.max(1, barHeight));
    }
    ctx.fillStyle = "rgba(143, 136, 113, 0.35)";
    ctx.fillRect(0, bodyTop + waveHeight + 1, width, 1);
  }

  if (points && points.length) {
    const { comments: maxComments, diamonds: maxDiamonds } = heatMaxima(points);
    // 波形を出しているときは下段だけを使い、2つの情報が重ならないようにする。
    const heatHeight = folded ? bodyH * 0.5 : bodyH - 2;
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

  drawRangeLane(ctx, width, height, (seconds) => (seconds / duration) * width);
  drawBookmarks(ctx, width, height, duration);
  drawZoomIndicator(ctx, width, height, duration);
  drawMarkFlash(ctx, width, height, (seconds) => (seconds / duration) * width);

  const video = $("video");
  if (video.currentTime > 0) {
    drawPlayhead(ctx, (video.currentTime / duration) * width, height);
  }
}

// 拡大窓が全尺のどこを見ているかの枠。これが無いと、拡大側を動かした後に全体の中の
// 位置関係を見失う。
function drawZoomIndicator(ctx, width, height, duration) {
  const win = zoomDragWindow || zoomWindow(duration);
  if (!win || win.span >= duration) return;
  const x0 = (win.start / duration) * width;
  const x1 = (win.end / duration) * width;
  ctx.strokeStyle = "rgba(29, 27, 22, 0.55)";
  ctx.lineWidth = 1;
  ctx.strokeRect(x0 + 0.5, RANGE_LANE_PX + 0.5,
                 Math.max(2, x1 - x0) - 1, height - RANGE_LANE_PX - BOOKMARK_LANE_PX - 1);
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
// toXは秒→x座標の写像で、全尺barと拡大窓が別の写像を渡してくる。
function drawRangeLane(ctx, width, height, toX) {
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
      if (x === null || x < -HANDLE_DRAW_PX || x > width + HANDLE_DRAW_PX) return;
      ctx.fillStyle = color;
      ctx.fillRect(x - 1, 0, 2, height);
      ctx.fillRect(x - HANDLE_DRAW_PX / 2, 0, HANDLE_DRAW_PX, RANGE_LANE_PX);
    },
  );
}

// ===== 拡大窓 =====
// 全尺barは3時間の録画で1px≈7秒になり、handleのdrag精度が原理的に出ない。細かい操作は
// この窓で行う。窓はwheelで拡縮、下端の目盛りdrag・shift+drag・横wheel・◀▶で左右へ動かす。
// 既定では再生位置に追従するが、追従は窓の外へ出たときだけ置き直す(followZoom)。

function clampZoomStart(start, span, duration) {
  return Math.max(0, Math.min(duration - span, start));
}

// 今の窓幅。state.zoomSpanは操作でそのまま持つので、録画尺と下限へは読み出し時に収める。
function zoomSpanFor(duration) {
  return Math.min(duration, Math.max(ZOOM_MIN_SPAN_SECONDS, state.zoomSpan));
}

// 今の拡大窓 {start, end, span}。位置はstate.zoomStartが唯一の持ち主で、追従はそれを
// 置き直す側に回る(followZoom)。checkboxを見て毎回再生位置から作り直すと、追従を外しても
// 窓が動き続ける — 外した瞬間の位置を誰も覚えていないため。
function zoomWindow(duration) {
  if (!isFinite(duration) || duration <= 0) return null;
  const span = zoomSpanFor(duration);
  const base = state.zoomStart === null
    ? $("video").currentTime - span * ZOOM_FOLLOW_ANCHOR
    : state.zoomStart;
  const start = clampZoomStart(base, span, duration);
  return { start, end: start + span, span };
}

// 追従は「窓の外へ出たら置き直す」page方式。再生位置へ張り付けて窓を滑らせ続けると、
// 波形もrulerも常に流れていて読めず、飛び先を狙う操作もできない。
// 窓の中に居る間は動かさないので、拡大したまま再生しても画面が落ち着く。
function followZoom() {
  const video = $("video");
  const duration = video.duration;
  if (!isFinite(duration) || duration <= 0) return;
  const span = zoomSpanFor(duration);
  const anchor = () => {
    state.zoomStart = clampZoomStart(
      video.currentTime - span * ZOOM_FOLLOW_ANCHOR, span, duration);
  };
  if (state.zoomStart === null) {
    anchor();
    return;
  }
  if (!$("zoom-follow").checked) return;
  const start = clampZoomStart(state.zoomStart, span, duration);
  if (video.currentTime < start || video.currentTime > start + span) anchor();
}

// 窓の左右移動。追従を外すのは「見たい場所を自分で選んだ」からで、切らないと次の
// 置き直しで再生位置へ引き戻される。
function panZoom(direction) {
  const duration = $("video").duration;
  const win = zoomWindow(duration);
  if (!win) return;
  $("zoom-follow").checked = false;
  state.zoomSpan = win.span;
  state.zoomStart = clampZoomStart(
    win.start + direction * win.span * ZOOM_PAN_STEP, win.span, duration);
  drawTimeline();
}

// 窓の拡縮。ratioは窓の中で動かしたくない点(左端からの割合)。追従中は再生位置を動かない
// 点にする — cursorを軸にすると再生位置が窓から出て、直後の置き直しで窓が跳ぶ。
function zoomBy(factor, ratio) {
  const video = $("video");
  const duration = video.duration;
  const win = zoomWindow(duration);
  if (!win) return;
  const span = Math.min(duration, Math.max(ZOOM_MIN_SPAN_SECONDS, win.span * factor));
  const pinned = $("zoom-follow").checked
    ? Math.min(win.end, Math.max(win.start, video.currentTime))
    : win.start + ratio * win.span;
  const pinnedRatio = (pinned - win.start) / win.span;
  state.zoomSpan = span;
  state.zoomStart = clampZoomStart(pinned - pinnedRatio * span, span, duration);
  drawTimeline();
}

// 全尺barの畳み込みは録画全体(3時間で10万点超)を舐める。再生中は毎frame描き直すので、
// 入力が変わらない限り前回の結果を使い回す。拡大窓側は窓の中しか舐めないため素で足りる。
let fullFold = null;

function foldWaveFull(duration, columns) {
  if (fullFold && fullFold.peaks === state.wave
      && fullFold.duration === duration && fullFold.columns === columns) {
    return fullFold.data;
  }
  const data = foldWave(0, duration, columns);
  fullFold = { peaks: state.wave, duration, columns, data };
  return data;
}

// heatの最大値も同じ理由でcacheする。spread(Math.max(...arr))は要素数が多いと引数上限に
// 触れるので、走査で取る。
let heatPeaks = null;

function heatMaxima(points) {
  if (heatPeaks && heatPeaks.points === points) return heatPeaks;
  let comments = 1;
  let diamonds = 1;
  points.forEach((point) => {
    if (point.comments > comments) comments = point.comments;
    if (point.diamonds > diamonds) diamonds = point.diamonds;
  });
  heatPeaks = { points, comments, diamonds };
  return heatPeaks;
}

// 単調な述語(前半がfalseで後半がtrue)が最初にtrueになるindexを返す。無ければlist.length。
// 無音区間も見どころも録画1本ぶんが開始順で届くので、拡大窓の左端をこれで引いて、映る範囲
// だけを回す。窓は再生中ずっと毎frame描き直すため、窓の外を1件ずつ捨てる走査は長尺
// (無音区間は数千件になる)でそのまま効いてくる。
function firstIndexWhere(list, isReached) {
  let low = 0;
  let high = list.length - 1;
  let found = list.length;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (isReached(list[mid])) {
      found = mid;
      high = mid - 1;
    } else {
      low = mid + 1;
    }
  }
  return found;
}

// 波形(時間刻みの全尺列)を[startSec, endSec]の範囲でcolumns本へ畳む。列ごとに担当する
// bucket範囲の最大を取る(平均だと短い発話が消える)。波形が無ければnull。
function foldWave(startSec, endSec, columns) {
  const peaks = state.wave;
  if (!peaks || !peaks.length || !(endSec > startSec) || columns < 1) return null;
  const bucketSeconds = state.waveBucketSeconds;
  const out = new Float32Array(columns);
  const perColumn = (endSec - startSec) / columns;
  for (let c = 0; c < columns; c += 1) {
    let from = Math.floor((startSec + c * perColumn) / bucketSeconds);
    let to = Math.ceil((startSec + (c + 1) * perColumn) / bucketSeconds);
    from = Math.max(0, Math.min(peaks.length - 1, from));
    to = Math.max(from + 1, Math.min(peaks.length, to));
    let peak = 0;
    for (let i = from; i < to; i += 1) if (peaks[i] > peak) peak = peaks[i];
    out[c] = peak;
  }
  return out;
}

// 拡大窓の時刻目盛りの間隔。目盛りが6〜12本になる「切りの良い」秒数を選ぶ。
const RULER_STEPS = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600];

function rulerStep(span) {
  const target = span / 8;
  return RULER_STEPS.find((step) => step >= target) || 7200;
}

// 目盛りは分秒だけで足りる場面が多い。1時間を超える録画だけ時を付ける。
function fmtTick(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const ms = `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return h > 0 ? `${h}:${ms}` : ms;
}

function drawZoom() {
  const canvas = $("zoom");
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (!width || !height) return;
  if (canvas.width !== width) canvas.width = width;
  if (canvas.height !== height) canvas.height = height;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, width, height);
  const video = $("video");
  const duration = video.duration;
  const win = zoomDragWindow || zoomWindow(duration);
  // 毎frame書き戻すとDOMが再計算に入る。値が変わったときだけ触る。
  const note = win ? `窓 ${fmtDuration(win.span)}` : "";
  if ($("zoom-note").textContent !== note) $("zoom-note").textContent = note;
  if (!win) return;
  const toX = (seconds) => ((seconds - win.start) / win.span) * width;

  const bodyTop = RANGE_LANE_PX;
  const bodyBottom = height - RULER_LANE_PX;
  const bodyH = bodyBottom - bodyTop;

  // 無音は面で塗る。切ってよい場所が「線の候補」ではなく「面」として読め、dblclickの
  // シーン選択が何を選ぶのかも見たまま分かる。
  ctx.fillStyle = "rgba(143, 136, 113, 0.16)";
  // 窓に掛かる最初の区間まで飛ばし、窓を出たところで止める(開始順なので以降も全て窓の外)。
  for (let i = firstIndexWhere(state.silences, (span) => span.end > win.start);
       i < state.silences.length; i += 1) {
    const span = state.silences[i];
    if (span.start >= win.end) break;
    const x0 = Math.max(0, toX(span.start));
    const x1 = Math.min(width, toX(span.end));
    ctx.fillRect(x0, bodyTop, Math.max(1, x1 - x0), bodyH);
  }

  // 波形は中央線対称で全高を使う。全尺barより濃くするのは、この窓が波形を読む場所だから。
  const folded = foldWave(win.start, win.end, width);
  if (folded) {
    ctx.fillStyle = "rgba(90, 110, 120, 0.75)";
    for (let x = 0; x < folded.length; x += 1) {
      const barHeight = Math.max(1, folded[x] * bodyH);
      ctx.fillRect(x, bodyTop + (bodyH - barHeight) / 2, 1, barHeight);
    }
  }

  // 見どころは細い柱で出す。全尺barの下端laneと同じ色にして同じ物だと分かるようにする。
  ctx.fillStyle = "rgba(122, 106, 60, 0.85)";
  for (let i = firstIndexWhere(state.bookmarks, (mark) => mark.start >= win.start);
       i < state.bookmarks.length; i += 1) {
    const mark = state.bookmarks[i];
    if (mark.start > win.end) break;
    ctx.fillRect(toX(mark.start) - 1, bodyTop, 2, bodyH * 0.3);
  }

  // 時刻ruler。拡大中に全尺barへ目を往復せず「今どこか」を読めるようにする。
  ctx.fillStyle = "rgba(143, 136, 113, 0.35)";
  ctx.fillRect(0, bodyBottom, width, 1);
  const step = rulerStep(win.span);
  ctx.fillStyle = "rgba(90, 85, 70, 0.9)";
  ctx.font = '9px "JetBrains Mono", monospace';
  ctx.textBaseline = "top";
  for (let t = Math.ceil(win.start / step) * step; t <= win.end; t += step) {
    const x = toX(t);
    ctx.fillRect(x, bodyBottom - 3, 1, 3);
    ctx.fillText(fmtTick(t), Math.min(x + 2, width - 34), bodyBottom + 2);
  }

  drawRangeLane(ctx, width, height - RULER_LANE_PX, toX);
  drawMarkFlash(ctx, width, height - RULER_LANE_PX, toX);
  if (video.currentTime >= win.start && video.currentTime <= win.end) {
    drawPlayhead(ctx, toX(video.currentTime), height - RULER_LANE_PX);
  }
}

// 再生中だけframe毎に描き直すloop。止まっている間は誰かがdrawTimeline()を呼ぶまで
// 描かないので、待機中のCPUは増えない。
let timelineFrame = null;

function drawTimelineFrame() {
  timelineFrame = null;
  drawTimeline();
  const video = $("video");
  if (!video.paused && !video.ended) timelineFrame = requestAnimationFrame(drawTimelineFrame);
}

function startTimelineFrames() {
  if (timelineFrame === null) timelineFrame = requestAnimationFrame(drawTimelineFrame);
}

function stopTimelineFrames() {
  if (timelineFrame !== null) cancelAnimationFrame(timelineFrame);
  timelineFrame = null;
  drawTimeline();
}

// 全尺barと拡大窓は同じ状態を写す2つのviewなので、常に対で描き直す。
// 追従の置き直しはここに置く。seekもdragも再生も最後は必ずここへ来るため、
// 「再生位置が窓の外に出た」判定を書く場所がここ以外に無い。dragで窓を凍結している
// 間だけは触らない(pointerの下の時刻が動いてhandleが逃げる)。
function drawTimeline() {
  if (!zoomDragWindow && dragMode !== "zoompan") followZoom();
  drawHeat();
  drawZoom();
}

// ===== 音声波形 =====
// 無音・BGM・発話が目で分かるので切り所の判断が速くなる。無音snapとシーン選択の土台にも
// なるため既定ON。初回生成はcontainerを丸ごと読むため長尺で90秒級かかるが、起動時sweepと
// 一括処理が先回りで作る(cache済みなら即返る)。不要ならcheckboxで切れる(記憶する)。

async function loadWaveform(recordingId) {
  if (!$("show-wave").checked) {
    state.wave = null;
    state.silences = [];
    $("wave-note").textContent = "";
    drawTimeline();
    return;
  }
  state.wave = null;
  state.silences = [];
  $("wave-note").textContent = "波形を生成中…（初回は長い録画で90秒程度）";
  drawTimeline();
  try {
    // 解像度はserver側の時間刻みで固定(cacheと1対1)。無音区間も同じresponseで届く。
    const data = await apiSend("GET", `/api/recordings/${recordingId}/waveform`);
    if (!state.current || state.current.recording_id !== recordingId) return;
    state.wave = data.peaks || null;
    state.waveBucketSeconds = Number(data.bucket_seconds) || 0.1;
    state.silences = data.silences || [];
    $("wave-note").textContent = "";
  } catch (err) {
    if (state.current && state.current.recording_id === recordingId) {
      $("wave-note").textContent = err.message;
    }
  }
  drawTimeline();
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

// 測ったbarの矩形とx座標から動画の秒を出す。矩形を引数に取るのは、1回の描画で同じbarを
// 何度も測り直さないため(測り直しはstyleを書いた後だとlayoutの再計算を伴う)。
function secondsFromRect(rect, clientX) {
  const duration = $("video").duration;
  if (!isFinite(duration) || duration <= 0) return null;
  const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
  return ratio * duration;
}

// bar上のx座標を動画の秒へ写す。thumbnail・seek・range dragが同じ換算を使う。
function secondsFromClientX(clientX) {
  return secondsFromRect($("heat").getBoundingClientRect(), clientX);
}

function showThumb(clientX) {
  const spec = state.sprite;
  const thumb = $("thumb");
  // 位置決めに要る寸法は、styleを書き始める前にまとめて読む。読みと書きが交互になると
  // そのたびlayoutの再計算を待つことになる。thumbはwrapperに対する絶対配置なので、
  // 先に測っても出し入れの影響を受けない。
  const rect = $("heat").getBoundingClientRect();
  const seconds = secondsFromRect(rect, clientX);
  if (!spec || seconds === null) {
    thumb.classList.add("hidden");
    return;
  }
  const wrap = thumb.parentElement.getBoundingClientRect();
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

// 拡大窓上のx座標を動画の秒へ写す。drag中は凍結した窓で換算する(zoomDragWindow参照)。
function zoomSecondsFromClientX(clientX) {
  const win = zoomDragWindow || zoomWindow($("video").duration);
  if (!win) return null;
  const rect = $("zoom").getBoundingClientRect();
  const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
  return win.start + ratio * win.span;
}

// drag中のpointer位置→秒。dragが始まったbarに応じて換算を切り替える。
function dragSecondsFromClientX(clientX) {
  return dragOnZoom ? zoomSecondsFromClientX(clientX) : secondsFromClientX(clientX);
}

// pointerに一番近いhandleを返す(許容幅の外ならnull)。IN側を先に判定して即returnすると、
// 短い範囲ではOUTがIN側の許容幅に飲まれて永久に掴めない。距離で決める。
function nearestHandle(x, toX, tolerance) {
  let mode = null;
  let best = Infinity;
  if (state.cutIn !== null) {
    best = Math.abs(x - toX(state.cutIn));
    mode = "in";
  }
  if (state.cutOut !== null && Math.abs(x - toX(state.cutOut)) <= best) {
    best = Math.abs(x - toX(state.cutOut));
    mode = "out";
  }
  return best <= tolerance ? mode : null;
}

// IN/OUT線は全高で掴める。範囲の新規作成と平行移動は上端lane限定で、それより下は
// 従来通りseek。範囲未設定ならlane内は必ず"new"(押した点から伸ばす)へ落ちる。
function hitTestHeat(clientX, clientY, pointerType) {
  const rect = $("heat").getBoundingClientRect();
  const duration = $("video").duration;
  if (!isFinite(duration) || duration <= 0) return "seek";
  const x = clientX - rect.left;
  const inLane = clientY - rect.top <= RANGE_LANE_PX;
  const toX = (seconds) => (seconds / duration) * rect.width;
  const base = pointerType === "mouse" ? HANDLE_HIT_PX : HANDLE_HIT_TOUCH_PX;
  const handle = nearestHandle(x, toX, inLane ? base : base * HANDLE_HIT_BODY_RATIO);
  if (handle) return handle;
  if (!inLane) return "seek";
  if (state.cutIn !== null && state.cutOut !== null
      && x > toX(state.cutIn) && x < toX(state.cutOut)) return "band";
  return "new";
}

// 拡大窓のhit判定。handleは縦全域で掴める(拡大側は1px=数十msなので、上端laneに限る
// 理由の「seekと紛れる」が起きない — 近傍ならhandle優先で困らない)。上端laneは全尺barと
// 同じく帯の移動と新規範囲、それ以外はseek。
// 下端の目盛り帯とshift+dragは窓の左右移動にあてる。wheelだけだと移動手段が
// 「押しっぱなしで送る」形しか無く、狙った場所へ一息で寄れない。
function hitTestZoom(event) {
  const rect = $("zoom").getBoundingClientRect();
  const win = zoomDragWindow || zoomWindow($("video").duration);
  if (!win) return "seek";
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  if (event.shiftKey || y > rect.height - RULER_LANE_PX) return "zoompan";
  const toX = (seconds) => ((seconds - win.start) / win.span) * rect.width;
  const tolerance = event.pointerType === "mouse" ? HANDLE_HIT_PX : HANDLE_HIT_TOUCH_PX;
  const handle = nearestHandle(x, toX, tolerance);
  if (handle) return handle;
  if (y <= RANGE_LANE_PX) {
    if (state.cutIn !== null && state.cutOut !== null
        && x > toX(state.cutIn) && x < toX(state.cutOut)) return "band";
    return "new";
  }
  return "seek";
}

const HEAT_CURSORS = {
  seek: "pointer",
  in: "ew-resize",
  out: "ew-resize",
  band: "grab",
  new: "crosshair",
  zoompan: "grab",
};

// 全尺bar上のpointer追従(cursorの形・thumbnail・drag)。pointermoveは1frameに何度も届く
// (高refresh rateのmouseでは桁が違う)一方、出せる絵は1frameに1枚しかない。届いた最後の
// 位置だけをframeの頭で処理する。
let heatMoveEvent = null;
let heatMoveFrame = null;

function applyHeatMove(event) {
  // dragMode自体がdown〜upの間だけ立つので、captureの成否には依存させない。
  if (dragMode) {
    dragRange(event);
  } else {
    $("heat").style.cursor =
      HEAT_CURSORS[hitTestHeat(event.clientX, event.clientY, event.pointerType)];
  }
  showThumb(event.clientX);
}

// 溜めてある位置を今すぐ反映する。dragの終わりは最後の位置まで入れてから確定させないと、
// 離す直前の詰めが1frameぶん捨てられる。
function flushHeatMove() {
  if (heatMoveFrame !== null) {
    cancelAnimationFrame(heatMoveFrame);
    heatMoveFrame = null;
  }
  const event = heatMoveEvent;
  heatMoveEvent = null;
  if (event) applyHeatMove(event);
}

// barから出た/操作が取り消された場合。溜めてある位置は捨てる(thumbを隠した後に
// 積み残しが動くと、離れているのに出たままになる)。
function cancelHeatMove() {
  if (heatMoveFrame !== null) {
    cancelAnimationFrame(heatMoveFrame);
    heatMoveFrame = null;
  }
  heatMoveEvent = null;
}

function scheduleHeatMove(event) {
  heatMoveEvent = event;
  if (heatMoveFrame !== null) return;
  heatMoveFrame = requestAnimationFrame(() => {
    heatMoveFrame = null;
    const latest = heatMoveEvent;
    heatMoveEvent = null;
    if (latest) applyHeatMove(latest);
  });
}

// drag中はhandleの位置へ動画を追従させる。切り所を目で確かめながら詰められる。
function dragRange(event) {
  // 窓の移動だけは再生位置に触らない(掴んだ場所を保ったまま景色を動かす操作のため)。
  if (dragMode === "zoompan") {
    const duration = $("video").duration;
    if (!isFinite(duration) || duration <= 0) return;
    const span = zoomSpanFor(duration);
    state.zoomStart = clampZoomStart(
      panStartSeconds - (event.clientX - panStartX) * panSecondsPerPx, span, duration);
    drawTimeline();
    return;
  }
  const seconds = dragSecondsFromClientX(event.clientX);
  if (seconds === null) return;
  const video = $("video");
  if (dragMode === "seek") {
    video.currentTime = seconds;
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
  if (!mode || mode === "seek" || mode === "zoompan") return;
  if (state.cutIn === null || state.cutOut === null) return;
  if (event.altKey) return;
  setCut(snapToSegments(state.cutIn, "in"), snapToSegments(state.cutOut, "out"));
}

// ===== 切り出し =====

// IN/OUT欄の表示形式。frame単位の微調整([ ]key)が値に見えるよう0.1秒まで出す。
function fmtCutTime(seconds) {
  return `${fmtDuration(seconds)}.${Math.floor((seconds % 1) * 10)}`;
}

// 手打ちの時刻を秒へ。"1:23:45.6"・"23:45"・"45.6"のどれでも読む。読めなければnull。
function parseTimeText(text) {
  const trimmed = text.trim();
  if (!trimmed || !/^[0-9:.]+$/.test(trimmed)) return null;
  const parts = trimmed.split(":");
  if (parts.length > 3 || parts.some((part) => part === "")) return null;
  const nums = parts.map(Number);
  if (nums.some((n) => !isFinite(n) || n < 0)) return null;
  return nums.reduce((acc, n) => acc * 60 + n, 0);
}

// 入力欄への書き戻し。編集中(focus中)の欄はdragが走っていても崩さない。
function writeCutField(id, seconds) {
  const input = $(id);
  if (document.activeElement === input) return;
  input.value = seconds === null ? "" : fmtCutTime(seconds);
}

function setCut(inSec, outSec) {
  state.cutIn = inSec;
  state.cutOut = outSec;
  writeCutField("cut-in", inSec);
  writeCutField("cut-out", outSec);
  const valid = inSec !== null && outSec !== null && outSec > inSec;
  const reversed = inSec !== null && outSec !== null && outSec <= inSec;
  $("cut-len").textContent = valid
    ? `尺 ${fmtDuration(outSec - inSec)}`
    : (reversed ? "OUTがINより前です" : "-");
  $("do-clip").disabled = !valid || !state.current;
  $("add-cut").disabled = !valid || !state.current;
  $("preview-in").disabled = inSec === null || !state.current;
  $("preview-out").disabled = outSec === null || !state.current;
  syncControlGroupNotes(valid);
  drawTimeline();
}

// 押せない理由を群の見出し横に1行で出す。button個々のtitleにしか無いと、hoverして回るまで
// 「今なにができるか」が読めない。
function syncControlGroupNotes(hasRange) {
  const clipNote = $("clip-group-note");
  const outNote = $("output-group-note");
  if (!clipNote || !outNote) return;
  if (!state.current) {
    clipNote.textContent = "録画を開くと使えます";
    outNote.textContent = "録画を開くと使えます";
    return;
  }
  clipNote.textContent = "";
  outNote.textContent = hasRange ? "" : "IN/OUTを決めると切り出しへ回せます";
}

// IN/OUT欄の手打ちを確定する。空にすればその側を解除。読めない入力は元の値へ戻す
// (黙って捨てると「入れたつもり」と実際がずれる)。
function applyCutField(id, kind) {
  const input = $(id);
  const current = kind === "in" ? state.cutIn : state.cutOut;
  if (!input.value.trim()) {
    if (kind === "in") setCut(null, state.cutOut);
    else setCut(state.cutIn, null);
    return;
  }
  let seconds = parseTimeText(input.value);
  if (seconds === null) {
    input.value = current === null ? "" : fmtCutTime(current);
    return;
  }
  const duration = $("video").duration;
  if (isFinite(duration)) seconds = Math.min(seconds, duration);
  if (kind === "in") setCut(seconds, state.cutOut);
  else setCut(state.cutIn, seconds);
  // 打った位置をその場で確かめられるよう再生位置も合わせる(I/O keyやdragと同じ挙動)。
  $("video").currentTime = seconds;
}

// IN/OUTをframe単位で詰める([ ] / shift+[ ] key)。動かした側へ再生位置を合わせ、
// 止めた絵で境界を確かめられるようにする。
function nudgeCut(kind, direction) {
  const video = $("video");
  const step = direction * FRAME_STEP_SECONDS;
  let next;
  if (kind === "in") {
    if (state.cutIn === null) return;
    next = Math.max(0, state.cutIn + step);
    if (state.cutOut !== null) next = Math.min(next, state.cutOut);
    setCut(next, state.cutOut);
  } else {
    if (state.cutOut === null) return;
    next = state.cutOut + step;
    if (isFinite(video.duration)) next = Math.min(next, video.duration);
    if (state.cutIn !== null) next = Math.max(next, state.cutIn);
    setCut(state.cutIn, next);
  }
  video.pause();
  video.currentTime = next;
}

// IN/OUT境界の前後だけを再生して切れ目を確かめる。全体をscrubし直すより速く、
// 聞いて判断できる(境界の良し悪しは絵より音で決まることが多い)。
function previewBoundary(kind) {
  const target = kind === "in" ? state.cutIn : state.cutOut;
  if (target === null) return;
  const video = $("video");
  video.currentTime = Math.max(0, target - PREVIEW_BEFORE_SECONDS);
  previewStopAt = target + PREVIEW_AFTER_SECONDS;
  video.play().catch(() => { previewStopAt = null; });
  requestAnimationFrame(tickPreview);
}

// timeupdateは250ms級の粒度で境界を大きく行き過ぎるため、確認再生の停止だけはrAFで見る。
function tickPreview() {
  if (previewStopAt === null) return;
  const video = $("video");
  if (video.currentTime >= previewStopAt) {
    previewStopAt = null;
    video.pause();
    return;
  }
  requestAnimationFrame(tickPreview);
}

// 押した位置を含む「無音に挟まれた発話塊」。無音の中を押したときは直後の塊(次の発話の
// 頭出し)を返す。
function sceneBounds(seconds, duration) {
  let start = 0;
  const spans = state.silences;
  for (let i = 0; i < spans.length; i += 1) {
    const span = spans[i];
    if (span.end <= seconds) {
      start = span.end;
      continue;
    }
    if (span.start > seconds) return { start, end: span.start };
    const next = spans[i + 1];
    return { start: span.end, end: next ? next.start : duration };
  }
  return { start, end: duration };
}

// dblclickで発話塊をまるごとIN/OUTへ。1シーンの切り出しが1動作になる。
function selectSceneAt(seconds) {
  const duration = $("video").duration;
  if (seconds === null || !isFinite(duration) || duration <= 0) return;
  if (!state.silences.length) {
    $("player-status").textContent =
      "無音区間がまだありません（音声波形を有効にすると使えます）。";
    return;
  }
  const bounds = sceneBounds(seconds, duration);
  if (bounds.end - bounds.start < FRAME_STEP_SECONDS) return;
  setCut(bounds.start, bounds.end);
  $("player-status").textContent =
    `無音間を選択しました（尺 ${fmtDuration(bounds.end - bounds.start)}）`;
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
    kind: "見どころ", start: m.start, end: m.end, memo: m.memo || "", group_id: m.group_id,
  }));
  const cuts = (state.cuts || [])
    .filter((c) => c.recording_id === current.recording_id)
    .map((c) => ({
      kind: "切り出し", start: c.start, end: c.end, memo: c.memo || "", group_id: c.group_id,
    }));
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
      groupNameOf(row.group_id) || "—",
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

// ===== グループ(切り抜き動画1本の単位) =====
// 見どころ・切り出しの項目はグループへ排他で所属し(group_id 1つ)、グループ間で同じ範囲を
// 使う場合は行を複製(copy)する — グループごとにIN/OUTの詰め方が変わるため、所属を共有すると
// 片方の調整が他方を黙って壊す。
// 画面ではselectに畳まず、上段へtabとして常時並べる。「今どこを見ているか」「どこへ
// 入れるか」「そのグループに何が何分あるか」が同時に読めないと、所属の付け替えも
// 書き出しの対象確認も当てずっぽうになる。

const CUT_GROUP_PREF_KEY = "tictok.videos.cutGroup";

function groupNameOf(groupId) {
  if (groupId === null || groupId === undefined) return "";
  const group = (state.groups || []).find((g) => g.id === groupId);
  // 一覧が引けていない瞬間でも所属が消えたように見せない。
  return group ? group.name : `グループ#${groupId}`;
}

// 行(cut/bookmark)が選択値("" 全て / "none" 未分類 / "<id>")に含まれるか。表示・件数・
// 書き出し対象のすべてがこの1つの判定を通るので、見えている物と操作対象がずれない。
function matchesGroup(row, value) {
  if (value === "") return true;
  const id = row.group_id === null || row.group_id === undefined ? null : row.group_id;
  if (value === "none") return id === null;
  return id === Number(value);
}

// 各tabの内訳。server側のcut_count等ではなく手元のlistから数えるので、表に出ている
// 件数と必ず一致する(2つの出所があると、片方だけ古い数字が残る)。
function groupStats(value) {
  const cuts = (state.cuts || []).filter((cut) => matchesGroup(cut, value));
  const marks = (state.marks || []).filter((mark) => matchesGroup(mark, value));
  return {
    cuts: cuts.length,
    marks: marks.length,
    seconds: cuts.reduce((sum, cut) => sum + (cut.end - cut.start), 0),
  };
}

// 書き出し・全削除の対象範囲の文言。buttonを押す前にこの文字列で範囲を読み取れる。
function groupScopeLabel(value) {
  if (value === "") return "切り出しリスト全体";
  if (value === "none") return "未分類";
  return `グループ「${groupNameOf(Number(value))}」`;
}

function isGroupSelected() {
  return state.groupSel !== "" && state.groupSel !== "none";
}

// 上段のグループtab。kindは "cuts" | "marks"。tabは「今どこを見ているか」の選択で
// あり、同時に行のドロップ先でもある。
// 以前は選択行があるとtabごとに「入れる/複製」buttonが生えていたが、選択のたびに
// tab列の高さと位置が変わって行き先を探し直すことになり、離れた表の行を選んでから
// 上まで往復する操作になっていた。行き先の指定は表のすぐ上(移動先select)と行の
// グループ欄へ移し、ここはドラッグの受け皿として常に同じ形で並べる。
function renderGroupBar(hostId, kind) {
  const host = $(hostId);
  if (!host) return;
  const selected = kind === "cuts" ? state.cutsSelected : state.marksSelected;
  const picked = selected.size;
  host.innerHTML = "";

  const label = document.createElement("span");
  label.className = "vd-gbar-label";
  label.textContent = "グループ";
  host.appendChild(label);

  // tabは横に流れる。棚(全て・未分類)と実体のグループを1列に並べたいので、
  // ここだけをscroll領域にして、新規・hintは端に留める。
  const strip = document.createElement("div");
  strip.className = "vd-gbar-strip";
  host.appendChild(strip);

  const entries = [
    { value: "", label: "全て" },
    { value: "none", label: "未分類" },
    ...(state.groups || []).map((group) => ({ value: String(group.id), label: group.name, group })),
  ];
  entries.forEach((entry, index) => {
    // 「全て」「未分類」は集計上の棚で、実体のあるグループとは別物。区切って並べる。
    if (index === 2) {
      const sep = document.createElement("span");
      sep.className = "vd-group-sep";
      strip.appendChild(sep);
    }
    const item = document.createElement("div");
    item.className = "vd-group-item";

    const pick = document.createElement("button");
    pick.type = "button";
    pick.className = "vd-group-pick";
    pick.setAttribute("aria-pressed", String(state.groupSel === entry.value));
    const name = document.createElement("span");
    name.className = "vd-group-name";
    name.textContent = entry.label;
    const meta = document.createElement("span");
    meta.className = "vd-group-meta";
    const stats = groupStats(entry.value);
    // 尺は0件のときに出さない。"0件 00:00:00" は「0秒の素材がある」と読めてしまう。
    meta.textContent =
      `切り出し ${fmtNum(stats.cuts)}件${stats.cuts ? ` ${fmtDuration(stats.seconds)}` : ""}`
      + ` ／ 見どころ ${fmtNum(stats.marks)}件`;
    pick.append(name, meta);
    pick.addEventListener("click", () => selectGroup(entry.value));
    item.appendChild(pick);

    // 行のドロップ先。「全て」は所属の指定にならないので受け取らない。
    if (entry.value !== "") {
      item.classList.add("vd-group-drop");
      item.addEventListener("dragover", (event) => {
        if (!state.drag) return;
        // preventDefaultを呼んだ場所だけがdropを受け取れる。
        event.preventDefault();
        if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
        item.classList.add("vd-drop-over");
      });
      item.addEventListener("dragleave", () => item.classList.remove("vd-drop-over"));
      item.addEventListener("drop", (event) => {
        item.classList.remove("vd-drop-over");
        const drag = state.drag;
        if (!drag) return;
        event.preventDefault();
        assignIds(drag.kind, entry.value, "move", drag.ids);
      });
    }

    const acts = document.createElement("div");
    acts.className = "vd-group-acts";
    if (entry.group && state.groupSel === entry.value) {
      const rename = document.createElement("button");
      rename.className = "btn btn-compact";
      rename.type = "button";
      rename.textContent = "改名";
      rename.addEventListener("click", () => renameGroup(entry.group));
      const remove = document.createElement("button");
      remove.className = "btn btn-danger btn-compact";
      remove.type = "button";
      remove.textContent = "削除";
      remove.title = "グループを削除します。中の項目は消えず未分類へ戻ります。";
      remove.addEventListener("click", () => deleteGroup(entry.group));
      acts.append(rename, remove);
    }
    if (acts.childElementCount) item.appendChild(acts);
    strip.appendChild(item);
  });

  // 新規作成とhintは端に固定する。tabが増えてstripがscrollしても、作る手段と
  // 「今なにが選択中か」が流れて見えなくならないようにする。
  const ops = document.createElement("div");
  ops.className = "vd-gbar-ops";
  const hint = document.createElement("span");
  hint.className = "vd-group-hint";
  hint.textContent = picked
    ? `${fmtNum(picked)}件を選択中 — 表の上の「移動先」で入れるか、行をtabへドラッグしてください。`
    : "グループ＝切り抜き動画1本。tabで表示を絞り、行はここへドラッグして入れられます。";
  const create = document.createElement("button");
  create.className = "btn btn-compact";
  create.type = "button";
  create.textContent = "＋ 新規";
  create.title = "新しいグループを作ります（切り抜き動画1本の単位）。";
  create.addEventListener("click", () => createGroup(false));
  ops.append(hint, create);
  host.appendChild(ops);
}

// 選択の切り替え。表示と操作対象は同じ値を見ているので、ここを変えるだけで
// 書き出し・連結・全削除の範囲も一緒に動く。
function selectGroup(value) {
  if (state.groupSel === value) return;
  state.groupSel = value;
  // 表示の絞り込みと「移動先」は別の値だが、同じ「グループ」の語で隣り合って並ぶ。
  // 実体のあるグループを開いたときは行き先もそこへ寄せる — Aで作業しているつもりで
  // 押した「入れる」が、起動時の既定(未分類)へ落とすのが最も起きやすい事故だった。
  // 「全て」「未分類」は行き先の指定にならないので触らない。
  if (isGroupSelected()) {
    state.moveTarget.cuts = value;
    state.moveTarget.marks = value;
  }
  // 選択そのものは捨てない。表示から外れた行だけが描画時に落ちる(renderCuts/renderMarks)
  // ので、絞り込みを変えても見えている行の選択は続けて使える。
  state.lastPick.cuts = null;
  state.lastPick.marks = null;
  renderCutsView();
  renderMarksView();
}

// 表のすぐ上の「移動先」select。行を選んだ手の位置から動かずに行き先を指せる。
// tabの表示選択とは別の値で、件数を併記して溜まっている先を取り違えないようにする。
function renderMoveBar(kind) {
  const select = $(kind === "cuts" ? "cuts-move-target" : "marks-move-target");
  if (!select) return;
  const entries = [
    { value: "none", label: "未分類" },
    ...(state.groups || []).map((group) => ({ value: String(group.id), label: group.name })),
  ];
  // 消えたグループを指したままにしない。指す先が無ければ未分類へ戻す。
  if (!entries.some((entry) => entry.value === state.moveTarget[kind])) {
    state.moveTarget[kind] = "none";
  }
  select.innerHTML = "";
  entries.forEach((entry) => {
    const option = document.createElement("option");
    option.value = entry.value;
    const stats = groupStats(entry.value);
    const count = kind === "cuts" ? stats.cuts : stats.marks;
    option.textContent = entry.value === "none" ? "未分類" : `${entry.label}（${fmtNum(count)}）`;
    select.appendChild(option);
  });
  select.value = state.moveTarget[kind];
}

// 行き先buttonの活性と件数。選択のたびに呼ぶので、selectの中身とは分けて更新する
// (選択のたびにoptionを組み直すと、開いたままのmenuが閉じる)。
function updateMoveButtons(kind) {
  const picked = (kind === "cuts" ? state.cutsSelected : state.marksSelected).size;
  const move = $(kind === "cuts" ? "cuts-move" : "marks-move");
  if (!move) return;
  const target = state.moveTarget[kind];
  // 行き先はbuttonの文言にも出す。selectの現在値を読み落としたまま押すと、
  // 既定のまま未分類へ落ちる(切り出しは並びも失う)。
  const where = target === "none" ? "未分類" : groupNameOf(Number(target));
  move.disabled = !picked;
  move.textContent = picked ? `${where}へ入れる（${fmtNum(picked)}件）` : "入れる";
  if (kind !== "cuts") return;
  const copy = $("cuts-copy");
  copy.disabled = !picked;
  copy.textContent = picked ? `${where}へ複製` : "複製";
}

function updateSelectionFor(kind) {
  if (kind === "cuts") updateCutsSelection();
  else updateMarksSelection();
}

// 行の選択checkbox。shift+クリックは「直前に触った行からここまで」で、1行ずつ押させると
// 数十行の仕分けがそれだけで数十clickになる。rerenderは範囲選択で複数行のcheckが
// 変わったときだけ呼ぶ(1行の切り替えで表ごと描き直すと、押した位置のfocusが飛ぶ)。
function pickBoxFor(kind, rows, index, id, rerender) {
  const selected = kind === "cuts" ? state.cutsSelected : state.marksSelected;
  const pick = document.createElement("input");
  pick.type = "checkbox";
  pick.checked = selected.has(id);
  pick.setAttribute("aria-label", "まとめて動かす対象に選ぶ");
  pick.title = "shift+クリックで、直前に選んだ行からここまでをまとめて選びます。";
  pick.addEventListener("click", (event) => {
    // 行clickは再生画面へ移る操作なので、選択は行へ伝播させない。
    event.stopPropagation();
    const on = pick.checked;
    const from = state.lastPick[kind];
    const ranged = event.shiftKey && from !== null && from !== index && rows[from];
    if (ranged) {
      const [lo, hi] = from < index ? [from, index] : [index, from];
      for (let i = lo; i <= hi; i += 1) {
        if (on) selected.add(rows[i].id);
        else selected.delete(rows[i].id);
      }
    } else if (on) {
      selected.add(id);
    } else {
      selected.delete(id);
    }
    state.lastPick[kind] = index;
    if (ranged) rerender();
    else updateSelectionFor(kind);
  });
  return pick;
}

// 行をグループtabへ放り込む経路。掴んだ行が選択済みなら選択ぶん全部、そうでなければ
// その行だけを運ぶ(選択があるからと、掴んでいない行まで一緒に動かさない)。
function bindRowDrag(tr, kind, id) {
  tr.draggable = true;
  tr.addEventListener("dragstart", (event) => {
    const selected = kind === "cuts" ? state.cutsSelected : state.marksSelected;
    const ids = selected.has(id) ? [...selected] : [id];
    state.drag = { kind, ids };
    tr.classList.add("vd-dragging");
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", ids.join(","));
    }
  });
  tr.addEventListener("dragend", () => {
    state.drag = null;
    tr.classList.remove("vd-dragging");
  });
}

// 選択行をまとめて移動先へ入れる／複製する。
function assignSelection(kind, op) {
  const selected = kind === "cuts" ? state.cutsSelected : state.marksSelected;
  return assignIds(kind, state.moveTarget[kind], op, [...selected]);
}

// 指定した行をグループへ入れる(move)／複製する(copy)。行のグループ欄・移動先button・
// tabへのドラッグの3経路がすべてここを通るので、どの経路でも結果が同じになる。
async function assignIds(kind, value, op, ids) {
  if (!ids || !ids.length) return;
  const selected = kind === "cuts" ? state.cutsSelected : state.marksSelected;
  const status = $(kind === "cuts" ? "cuts-status" : "marks-status");
  const groupId = value === "none" ? null : Number(value);
  try {
    const result = await apiSend(
      "POST", kind === "cuts" ? "/api/cutlist/bulk" : "/api/bookmarks/bulk",
      { op, ids, group_id: groupId },
    );
    const where = groupId === null ? "未分類" : `グループ「${groupNameOf(groupId)}」`;
    status.textContent = op === "copy"
      ? `${fmtNum(result.affected)}件を${where}へ複製しました。`
      : `${fmtNum(result.affected)}件を${where}へ入れました。`;
    // moveは行が移った時点で選択の意味が変わるので、動かした行だけ選択から外す
    // (行のグループ欄で1件だけ直したときに、残り全部の選択まで消さない)。
    // copyは元の行が残るため選択を保ち、続けて別のグループへも配れるようにする。
    if (op !== "copy") ids.forEach((id) => selected.delete(id));
    state.lastPick[kind] = null;
  } catch (err) {
    status.textContent = err.message;
  }
  // 今開いている録画の見どころ(seek barのmarkerとplayer直下の一覧)は別に持っている。
  // 引き直さないと、所属を変えた行だけ古いグループ名のまま残る。
  if (kind === "marks" && state.current) await loadBookmarks(state.current.recording_id);
  await refreshGroupData();
  renderGroupViews();
}

// 記録先グループは録画を跨いで使い回すものなので記憶する(毎回選び直すと未分類へ落ちる)。
function loadAddGroupPref() {
  try {
    // 旧版は未分類を空文字で持っていた。"none"へ寄せて判定を1本にする。
    return localStorage.getItem(CUT_GROUP_PREF_KEY) || "none";
  } catch {
    return "none";
  }
}

function saveAddGroupPref(value) {
  try {
    localStorage.setItem(CUT_GROUP_PREF_KEY, value);
  } catch {
    /* 記憶できないだけ */
  }
}

function setAddGroup(value) {
  state.addGroup = value || "none";
  saveAddGroupPref(state.addGroup);
  renderDestChips();
}

// 見どころ・切り出しを開いて再生画面へ戻ったとき、記録先をその行の所属へ寄せる。
// 寄せないと、範囲を詰め直して追加した先が記録先chipの記憶値(多くは未分類)になり、
// グループ(=切り抜き1本の単位)から素材が1件ずつ黙って外れる。
function inheritAddGroup(groupId) {
  const value = groupId === null || groupId === undefined ? "none" : String(groupId);
  if (state.addGroup === value) return;
  setAddGroup(value);
  const group = (state.groups || []).find((g) => String(g.id) === value);
  showToast(group
    ? `記録先を「${group.name}」にしました（開いた行の所属）。`
    : "記録先を未分類にしました（開いた行の所属）。");
}

// 見どころ・切り出しの記録先group_id。未分類はnull。
function currentAddGroupId() {
  const value = state.addGroup;
  return !value || value === "none" ? null : Number(value);
}

// 記録先のchip列。選択肢を畳まないので、追加buttonのすぐ隣で「今どこへ入るか」が常に
// 読める。件数も併記して、溜まっている先を取り違えないようにする。
function renderDestChips() {
  const host = $("dest-groups");
  if (!host) return;
  host.innerHTML = "";
  const entries = [
    { value: "none", label: "未分類" },
    ...(state.groups || []).map((group) => ({ value: String(group.id), label: group.name })),
  ];
  entries.forEach((entry) => {
    const stats = groupStats(entry.value);
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "vd-chip";
    chip.setAttribute("role", "radio");
    chip.setAttribute("aria-checked", String(state.addGroup === entry.value));
    chip.textContent = entry.value === "none"
      ? "未分類"
      : `${entry.label}（${fmtNum(stats.cuts + stats.marks)}）`;
    chip.title = entry.value === "none"
      ? "グループに入れずに記録します。後から上のグループtabで仕分けられます。"
      : `以後の「見どころに記録」「切り出しリストに追加」を「${entry.label}」へ入れます。`;
    chip.addEventListener("click", () => {
      setAddGroup(entry.value);
      // 今どこへ入るかはchipの選択状態そのものが常時示している。ここで player-status を
      // 使うと、直前に出した切り出しpathが記録先を変えただけで消える。
      showToast(entry.value === "none"
        ? "記録先を未分類にしました。"
        : `記録先を「${entry.label}」にしました。`);
    });
    host.appendChild(chip);
  });

  const create = document.createElement("button");
  create.type = "button";
  create.className = "vd-chip vd-chip-add";
  create.textContent = "＋ 新規";
  create.title = "新しいグループを作り、そのまま記録先にします。";
  create.addEventListener("click", () => createGroup(true));
  host.appendChild(create);

  const fromQuery = document.createElement("button");
  fromQuery.type = "button";
  fromQuery.className = "vd-chip vd-chip-add";
  fromQuery.textContent = "＋ 検索語で作る";
  fromQuery.title = "今の検索語を名前にしたグループを作って記録先にします（同名があればそれを選びます）。";
  fromQuery.addEventListener("click", groupFromQuery);
  host.appendChild(fromQuery);
}

// 「検索語で作る」: 今の検索語を名前にしたグループを作り(同名があればそれ)、記録先にする。
// 「XXXという発言を集める」流れでは検索語=グループ名になるのが最短のため。
async function groupFromQuery() {
  const name = (state.query || "").trim();
  if (!name) {
    $("player-status").textContent = "検索語が空です。シーン検索の検索語がグループ名になります。";
    return;
  }
  try {
    const group = await apiSend("POST", "/api/groups", { name });
    await refreshGroupData();
    setAddGroup(String(group.id));
    renderGroupViews();
    $("player-status").textContent = `記録先を「${group.name}」にしました。`;
  } catch (err) {
    $("player-status").textContent = err.message;
  }
}

// asDestinationは記録先chipの「＋ 新規」から。作ってすぐ記録先にしないと、
// 作った直後の1件を取りこぼす。
async function createGroup(asDestination) {
  const name = await promptDialog("新しいグループの名前", {
    title: "新しいグループ", confirmLabel: "作成",
  });
  if (!name) return;
  const status = $(asDestination ? "player-status" : "cuts-status");
  let group;
  try {
    group = await apiSend("POST", "/api/groups", { name });
  } catch (err) {
    status.textContent = err.message;
    return;
  }
  await refreshGroupData();
  if (asDestination) setAddGroup(String(group.id));
  else state.groupSel = String(group.id);
  renderGroupViews();
  status.textContent = asDestination
    ? `記録先を「${group.name}」にしました。`
    : `グループ「${group.name}」を作りました。`;
}

async function renameGroup(group) {
  const name = await promptDialog("グループの新しい名前", {
    title: "グループの改名", value: group.name, confirmLabel: "改名",
  });
  if (!name) return;
  try {
    await apiSend("PATCH", `/api/groups/${group.id}`, { name });
  } catch (err) {
    $("cuts-status").textContent = err.message;
  }
  await refreshGroupData();
  renderGroupViews();
}

async function deleteGroup(group) {
  const stats = groupStats(String(group.id));
  const count = stats.cuts + stats.marks;
  const ok = await confirmDialog(
    `グループ「${group.name}」を削除しますか？中の${fmtNum(count)}件は消えず未分類へ戻ります。`,
    { title: "グループの削除", confirmLabel: "削除", danger: true },
  );
  if (!ok) return;
  try {
    await apiSend("DELETE", `/api/groups/${group.id}`);
    state.groupSel = "";
  } catch (err) {
    $("cuts-status").textContent = err.message;
  }
  await refreshGroupData();
  renderGroupViews();
}

// 表のグループ列。その場で選び直せるselectにする — 1件だけ直すのが最も多い操作で、
// 「選択してから上のtabまで往復する」経路しか無いとそれだけで4手掛かる。
// 選んだ瞬間に移動まで済ませる(適用buttonを挟むと、押し忘れた行が黙って元のまま残る)。
const NEW_GROUP_VALUE = "__new__";

function groupSelectFor(row, kind) {
  const id = row.group_id === null || row.group_id === undefined ? null : row.group_id;
  const current = id === null ? "none" : String(id);
  const select = document.createElement("select");
  select.className = "vd-gsel" + (id === null ? " vd-gsel-none" : "");
  // 欄の幅には上限があり長い名前は省略される。今の所属はhoverでも読めるようにする。
  select.title = `所属: ${id === null ? "未分類" : groupNameOf(id)}（選ぶとその場で移ります）`;
  select.setAttribute("aria-label", "この行の所属グループ");
  const entries = [
    { value: "none", label: "未分類" },
    ...(state.groups || []).map((group) => ({ value: String(group.id), label: group.name })),
  ];
  // 一覧が引けていない瞬間でも所属が消えたように見せない(選択肢に無い所属を補う)。
  if (!entries.some((entry) => entry.value === current)) {
    entries.push({ value: current, label: groupNameOf(id) });
  }
  entries.push({ value: NEW_GROUP_VALUE, label: "＋ 新しいグループ…" });
  entries.forEach((entry) => {
    const option = document.createElement("option");
    option.value = entry.value;
    option.textContent = entry.label;
    select.appendChild(option);
  });
  select.value = current;
  // 行clickは再生画面へ移る操作なので、この列の操作は行へ伝播させない。
  ["click", "mousedown", "keydown", "dragstart"].forEach((type) => {
    select.addEventListener(type, (event) => event.stopPropagation());
  });
  select.addEventListener("change", async () => {
    const value = select.value;
    if (value === current) return;
    if (value === NEW_GROUP_VALUE) {
      // 作れなかった/やめた場合に、行が入っていない先を名乗ったままにしない。
      select.value = current;
      const group = await createGroupFor(kind);
      if (group) await assignIds(kind, String(group.id), "move", [row.id]);
      return;
    }
    await assignIds(kind, value, "move", [row.id]);
  });
  return select;
}

// 行のグループ欄の「＋ 新しいグループ…」から作る。作るだけで、入れるのは呼び出し側。
async function createGroupFor(kind) {
  const name = await promptDialog("新しいグループの名前", {
    title: "新しいグループ", confirmLabel: "作成",
  });
  if (!name) return null;
  try {
    return await apiSend("POST", "/api/groups", { name });
  } catch (err) {
    $(kind === "cuts" ? "cuts-status" : "marks-status").textContent = err.message;
    return null;
  }
}

// tabの内訳も、グループ内の見どころも、両方のlistが揃っていないと出せない。
// どちらのtabから入っても同じ物が見えるよう、3つまとめて引く。
// 戻り値は最初に失敗したものの文面(空なら成功)。
async function refreshGroupData() {
  let failure = "";
  // 失敗しても手元のlistは捨てない。空にすると「0件」「グループが無い」という
  // 取得できていない事実とは別の内容を画面が名乗ることになる(消えたと誤認して
  // 作り直される)。理由は呼び出し側がstatusへ出す。
  const fetchInto = async (path, key) => {
    try {
      const data = await apiSend("GET", path);
      state[key] = data.items || [];
      return true;
    } catch (err) {
      if (!failure) failure = err.message;
      return false;
    }
  };
  const gotGroups = await fetchInto("/api/groups", "groups");
  await fetchInto("/api/cutlist", "cuts");
  await fetchInto("/api/bookmarks", "marks");
  // 消えたグループを指したまま操作させない(選択も記録先も、指す先が無ければ戻す)。
  // 一覧を引けなかったときは判定しない — 引けていないことを「消えた」と読み替えない。
  if (!gotGroups) return failure;
  const exists = (value) => (state.groups || []).some((group) => String(group.id) === value);
  if (isGroupSelected() && !exists(state.groupSel)) state.groupSel = "";
  if (state.addGroup !== "none" && !exists(state.addGroup)) setAddGroup("none");
  return failure;
}

function renderGroupViews() {
  renderDestChips();
  renderCutsView();
  renderMarksView();
  renderOwnMarks();
}

// ===== 切り出しリスト =====

async function loadCuts() {
  const failure = await refreshGroupData();
  if (failure) $("cuts-summary").textContent = failure;
  renderGroupViews();
}

function renderCutsView() {
  // グループtabはupdateCutsSelection()から選択件数込みで描き直す。
  renderMoveBar("cuts");
  renderCutsHead();
  fillCutStreamers();
  renderCuts();
  renderGroupMarks();
  updateCutsSummary();
}

// グループ選択を掛けた表示対象。グループを選んでいる間はposition順(=書き出し順)で並べる。
function visibleCuts() {
  const rows = (state.cuts || []).filter((cut) => matchesGroup(cut, state.groupSel));
  if (!isGroupSelected()) return rows;
  return rows.sort(
    (a, b) =>
      (a.position === null) - (b.position === null) ||
      (a.position ?? 0) - (b.position ?? 0) ||
      a.start - b.start ||
      a.id - b.id,
  );
}

// 選択中のグループの見出しと、書き出し・連結・全削除が効く範囲。buttonを押す前に
// 対象がこの2箇所で読めるようにする(絞り込みの副作用として決まると、見えていない
// 行がqueueへ入る)。
function renderCutsHead() {
  const grouped = isGroupSelected();
  const group = grouped
    ? (state.groups || []).find((g) => String(g.id) === state.groupSel)
    : null;
  const rows = visibleCuts();
  const total = rows.reduce((sum, cut) => sum + (cut.end - cut.start), 0);
  $("cuts-group-head").classList.toggle("hidden", !group);
  if (group) {
    $("cuts-group-title").textContent = `■ ${group.name}`;
    $("cuts-group-stats").textContent =
      `切り出し ${fmtNum(rows.length)}件 / 完成尺 ${fmtDuration(total)}`
      + `・見どころ ${fmtNum(groupStats(state.groupSel).marks)}件`;
    const memo = $("cuts-group-memo");
    // 入力中の値は上書きしない(引き直しのたびに自分の入力が消える)。
    if (document.activeElement !== memo) memo.value = group.memo || "";
    memo.dataset.groupId = String(group.id);
  }
  $("cuts-scope").textContent = `対象: ${groupScopeLabel(state.groupSel)}`;
  $("cuts-list-title").textContent = grouped ? "■ 切り出し（書き出し順）" : "■ 切り出しリスト";
  // 「1本に繋ぐ」順序はpositionで、それを決められるのはグループを選んでいるときだけ
  // (「全て」「未分類」では順・頭出し列も↑↓も出ない)。押せるまま残すと、順序を確認も
  // 変更もできない状態のまま数十分の連結jobが走り、出来上がってから気付くことになる。
  const reel = $("cuts-reel");
  reel.disabled = !grouped || rows.length === 0;
  reel.title = grouped
    ? "表示順（書き出し順）のまま1本のmp4へ繋ぎます。"
    : "グループを選ぶと並び順を決められます。「全て」「未分類」では順序を指定できません。";
}

// 同じグループの見どころ。まだIN/OUTを詰めていない素材で、範囲付きならそのまま
// 同じグループの切り出しへ回せる。
function renderGroupMarks() {
  const grouped = isGroupSelected();
  $("cuts-marks-block").classList.toggle("hidden", !grouped);
  if (!grouped) return;
  const rows = (state.marks || [])
    .filter((mark) => matchesGroup(mark, state.groupSel))
    .sort((a, b) => (a.recording_id - b.recording_id) || (a.start - b.start));
  renderTableRows(
    "cuts-mark-rows",
    "cuts-mark-empty",
    rows,
    (mark) => {
      const hasRange = mark.end !== null && mark.end !== undefined;
      const open = document.createElement("button");
      open.className = "btn btn-small";
      open.type = "button";
      open.textContent = "開く";
      open.addEventListener("click", () => openMark(mark));
      const promote = document.createElement("button");
      promote.className = "btn btn-small";
      promote.type = "button";
      const done = hasRange ? promotedCutOf(mark) : null;
      promote.textContent = done ? "切り出し済" : "切り出しへ";
      promote.disabled = !hasRange || Boolean(done);
      promote.title = done
        ? `この範囲は既に切り出しリスト（${groupNameOf(done.group_id) || "未分類"}）にあります。`
        : (hasRange
          ? "この範囲を同じグループの切り出しリストへ入れます。"
          : "範囲がありません。「開く」でIN/OUTを決めてから追加してください。");
      promote.addEventListener("click", () => promoteMark(mark));
      const actions = document.createElement("span");
      actions.className = "vd-row";
      actions.append(open, promote);
      return [
        mark.unique_id,
        fmtYmd(mark.recording_started_at),
        fmtDuration(mark.start),
        hasRange ? fmtDuration(mark.end - mark.start) : "点",
        mark.memo || "—",
        actions,
      ];
    },
    [2, 3],
  );
}

// cutのラベル欄。表示専用だった頃は、見どころのメモを引き継いだまま直す手段が無く、
// 直すには行を消して作り直すしかなかった(labelは書き出しfile名とEDL/FCPXMLのclip名に
// なるので、綴りの誤りがそのまま最終成果物に残る)。見どころのメモ欄と同じ作法にする。
function cutLabelInput(cut) {
  const input = document.createElement("input");
  input.type = "text";
  input.className = "vd-memo";
  input.value = cut.label || "";
  input.placeholder = "ラベル";
  input.setAttribute("aria-label", "この切り出しのラベル");
  // 行clickは再生画面へ移る操作なので、この欄の操作は行へ伝播させない。
  ["click", "mousedown", "keydown", "dragstart"].forEach((type) => {
    input.addEventListener(type, (event) => event.stopPropagation());
  });
  input.addEventListener("change", async () => {
    const value = input.value.trim();
    if (value === (cut.label || "")) return;
    try {
      await apiSend("PATCH", `/api/cutlist/${cut.id}`, { label: value });
      cut.label = value;
      showToast("ラベルを保存しました。");
    } catch (err) {
      $("cuts-status").textContent = err.message;
    }
  });
  return input;
}

// 見どころ(素材候補)を同じグループの切り出しへ。範囲の無い点はIN/OUTが決まっていない
// ので昇格させない(0秒のcutを作っても書き出せない)。
// statusIdは押したtab側の表示先。切り出しリストtabのstatusへ書くと、見どころtabから
// 押した時に結果が見えない画面に出る。
// 同じ見どころから作った切り出しが既に在るか。押した後も行の見た目が変わらないため、
// 押したかどうかを行から読み取れず、二重に入れたcutは書き出して初めて分かる
// (一括書き出しでは2 file、連結では同じ場面が2回続く動画になる)。
function promotedCutOf(mark) {
  return (state.cuts || []).find((cut) => cut.recording_id === mark.recording_id
    && cut.start === mark.start && cut.end === mark.end);
}

async function promoteMark(mark, statusId = "cuts-status") {
  if (mark.end === null || mark.end === undefined) return;
  const existing = promotedCutOf(mark);
  if (existing) {
    $(statusId).textContent =
      `この範囲は既に切り出しリスト（${groupNameOf(existing.group_id) || "未分類"}）にあります。`;
    return;
  }
  const groupName = groupNameOf(mark.group_id === undefined ? null : mark.group_id);
  try {
    await apiSend("POST", "/api/cutlist", {
      recording_id: mark.recording_id,
      start: mark.start,
      end: mark.end,
      label: mark.memo || "",
      group_id: mark.group_id === undefined ? null : mark.group_id,
    });
    $(statusId).textContent = groupName
      ? `切り出しリスト（グループ: ${groupName}）へ入れました。`
      : "切り出しリスト（未分類）へ入れました。";
  } catch (err) {
    $(statusId).textContent = err.message;
  }
  await refreshGroupData();
  renderGroupViews();
}

function updateCutsSummary() {
  const rows = visibleCuts();
  const total = rows.reduce((sum, cut) => sum + (cut.end - cut.start), 0);
  $("cuts-summary").textContent = rows.length
    ? `${fmtNum(rows.length)}件 / 合計 ${fmtDuration(total)}`
    : "";
}

// 選択状況の表示と、選択で決まるbuttonの活性。
function updateCutsSelection() {
  const rows = visibleCuts();
  const count = state.cutsSelected.size;
  $("cuts-selected").textContent = count ? `選択 ${fmtNum(count)}件` : "";
  $("cuts-bulk-delete").disabled = !count;
  $("cuts-select-all").checked = rows.length > 0 && count === rows.length;
  updateMoveButtons("cuts");
  renderGroupBar("cuts-groups", "cuts");
}

// グループ内の並び入れ替え。並びはEDL/FCPXMLの書き出し順(=NLEのtimeline順)になるため、
// server側のpositionを振り直してから引き直す(画面だけ入れ替えると書き出しとずれる)。
async function nudgeCutOrder(rows, index, delta) {
  const target = index + delta;
  if (target < 0 || target >= rows.length) return;
  const ids = rows.map((cut) => cut.id);
  [ids[index], ids[target]] = [ids[target], ids[index]];
  try {
    await apiSend("POST", `/api/groups/${state.groupSel}/order`, { cut_ids: ids });
  } catch (err) {
    $("cuts-status").textContent = err.message;
  }
  loadCuts();
}

// 選択した切り出しの削除。所属の付け替えは上段のグループtabから行う。
async function deleteSelectedCuts() {
  const ids = [...state.cutsSelected];
  if (!ids.length) return;
  const ok = await confirmDialog(
    `選択した${fmtNum(ids.length)}件を削除しますか？この操作は取り消せません。`,
    { title: "選択の削除", confirmLabel: "削除", danger: true },
  );
  if (!ok) return;
  try {
    const result = await apiSend("POST", "/api/cutlist/bulk", { op: "delete", ids });
    $("cuts-status").textContent = `${fmtNum(result.affected)}件を削除しました。`;
    const seen = cutPlayer.watching();
    if (seen && ids.includes(seen.id)) cutPlayer.close();
    state.cutsSelected.clear();
  } catch (err) {
    $("cuts-status").textContent = err.message;
  }
  loadCuts();
}

function renderCuts() {
  const rows = visibleCuts();
  const grouped = isGroupSelected();
  // 表示から消えた行の選択は捨てる(見えない行への一括操作を残さない)。
  const visibleIds = new Set(rows.map((cut) => cut.id));
  state.cutsSelected = new Set([...state.cutsSelected].filter((id) => visibleIds.has(id)));
  // 完成尺のどこから始まるか。書き出し順に尺を積み上げた値で、「この切り出しが
  // 出来上がりの何分頃に来るか」を並び替えながら読めるようにする。
  let elapsed = 0;
  const heads = rows.map((cut) => {
    const at = elapsed;
    elapsed += cut.end - cut.start;
    return at;
  });
  renderTableRows(
    "cut-rows",
    "cut-empty",
    rows,
    (cut, rowNumber) => {
      const pick = pickBoxFor("cuts", rows, rowNumber - 1, cut.id, () => renderCuts());
      const groupSelect = groupSelectFor(cut, "cuts");
      const order = document.createElement("span");
      order.className = "vd-row";
      if (grouped) {
        const index = rowNumber - 1;
        [["↑", -1], ["↓", 1]].forEach(([label, delta]) => {
          const button = document.createElement("button");
          button.className = "btn btn-small";
          button.type = "button";
          button.textContent = label;
          button.title = "グループ内の並び（＝listの書き出し順）を入れ替えます。";
          button.disabled = index + delta < 0 || index + delta >= rows.length;
          button.addEventListener("click", (e) => {
            e.stopPropagation();
            nudgeCutOrder(rows, index, delta);
          });
          order.appendChild(button);
        });
      }
      // 中身を確かめるための2経路。この場で観る(視聴)か、道具付きで観る(シーン検索視聴)。
      // 以前は行clickでシーン検索へ移るしか無く、詰めた範囲を1件確かめるたびtabを往復して
      // 並び順と選択を見失っていた。見どころtabと同じ並び・同じ文言にする。
      const watch = document.createElement("button");
      watch.className = "btn btn-small";
      watch.type = "button";
      watch.textContent = "視聴";
      watch.title = "このtabのまま、この範囲を再生します（OUTで一度止まります）。";
      watch.addEventListener("click", (e) => {
        e.stopPropagation();
        cutPlayer.play(cut);
      });
      const open = document.createElement("button");
      open.className = "btn btn-small";
      open.type = "button";
      open.textContent = "シーン検索視聴";
      open.title = "シーン検索の再生画面で開きます（IN/OUTが入った状態になります）。";
      open.addEventListener("click", (e) => {
        e.stopPropagation();
        openCut(cut);
      });
      const remove = document.createElement("button");
      remove.className = "btn btn-small btn-danger";
      remove.textContent = "削除";
      remove.addEventListener("click", async (e) => {
        // 行click(この場で再生)と重ならないよう、削除は行へ伝播させない。
        e.stopPropagation();
        // 詰めたIN/OUTと並び順は復元できない。まとめて削除する側と同じ扱いにする。
        const ok = await confirmDialog(
          `この切り出しを削除します（${fmtDuration(cut.start)}〜${fmtDuration(cut.end)}${cut.label ? ` ${cut.label}` : ""}）。詰めたIN/OUTと並び順は戻せません。`,
          { title: "切り出しの削除", confirmLabel: "削除する" },
        );
        if (!ok) return;
        await apiSend("DELETE", `/api/cutlist/${cut.id}`);
        // 消した切り出しを観たまま残さない(実体の無い行を再生し続けることになる)。
        const seen = cutPlayer.watching();
        if (seen && seen.id === cut.id) cutPlayer.close();
        loadCuts();
      });
      // 「観る」2つは同じ段に置く。列は中身が要求する幅で決まるので、buttonを平らに並べると
      // 要求がbutton1つぶんになり、3つが縦に積まれて1行が動画1本ぶんの高さになる。
      const views = document.createElement("span");
      views.className = "vd-row vd-row-pair";
      views.append(watch, open);
      const actions = document.createElement("span");
      actions.className = "vd-row";
      actions.append(views, remove);
      const file = document.createElement("span");
      file.className = "vd-file";
      file.textContent = cut.filename || "-";
      // 解決済みのpathはNLEへ渡す実体そのもの。録画を移動していても今の場所が出る。
      // 1行へ収めて省略するので、省略された分もここから読めるようにfile名を控えに置く。
      file.title = cut.path || cut.filename || "";
      return [
        pick,
        grouped ? String(rowNumber) : "—",
        cut.unique_id,
        fmtYmd(cut.recording_started_at),
        file,
        fmtDuration(cut.start),
        fmtDuration(cut.end),
        fmtDuration(cut.end - cut.start),
        grouped ? fmtDuration(heads[rowNumber - 1]) : "—",
        cutLabelInput(cut),
        groupSelect,
        order,
        actions,
      ];
    },
    [1, 5, 6, 7, 8],
    (tr, cut) => {
      bindRowDrag(tr, "cuts", cut.id);
      tr.classList.add("row-clickable");
      tr.tabIndex = 0;
      // 行clickはこのtabの中で再生する(画面ごと移らないぶん安全で、見どころtabと同じ)。
      tr.title = "この切り出しをこのtabのまま再生します。";
      tr.addEventListener("click", (event) => {
        // 行内のbutton・ラベル欄・グループ欄は独自の操作を持つ。素通しすると「視聴」を
        // 押しただけで再生が二重に走り、読み込みも2回投げられる。
        if (event.target.closest("button, input, select, a")) return;
        cutPlayer.play(cut);
      });
      tr.addEventListener("keydown", (e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        e.preventDefault();
        cutPlayer.play(cut);
      });
    },
  );
  updateCutsSelection();
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
async function exportCutlist(format, uniqueId, group) {
  const params = new URLSearchParams({ format });
  if (uniqueId) params.set("unique_ids", uniqueId);
  if (group) params.set("group", group);
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
  // グループ単位の書き出しはfile名がグループ名(日本語)になるため、RFC 5987のfilename*を先に読む
  // (filename=はASCIIのfallback名)。
  const starNamed = /filename\*=UTF-8''([^;\s]+)/i.exec(disposition);
  const named = /filename="([^"]+)"/.exec(disposition);
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = starNamed
    ? decodeURIComponent(starNamed[1])
    : named
      ? named[1]
      : `tictok_cutlist.${format}`;
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
    await exportCutlist(format, uniqueId, state.groupSel);
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
  inheritAddGroup(cut.group_id);
}

async function addCut() {
  if (!state.current || state.cutIn === null || state.cutOut === null) return;
  try {
    await apiSend("POST", "/api/cutlist", {
      recording_id: state.current.recording_id,
      start: state.cutIn,
      end: state.cutOut,
      label: state.query,
      group_id: currentAddGroupId(),
    });
    const groupName = groupNameOf(currentAddGroupId());
    $("player-status").textContent = groupName
      ? `切り出しリスト（グループ: ${groupName}）に追加しました。`
      : "切り出しリストに追加しました。";
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
      // 同じ行為を「リストに追加」「切り出しへ」「切り出しリストに追加」の3語で呼んでいた。
      // 押すまで同じ結果か判断できないので、追加する操作は再生画面のbuttonと同じ語に揃える。
      add.textContent = "切り出しリストに追加";
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
      group_id: currentAddGroupId(),
    });
    $("cand-summary").textContent = "切り出しリストに追加しました。";
  } catch (err) {
    $("cand-summary").textContent = err.message;
  }
}

// ===== 一括書き出し =====
// 実行はserverのqueue。録画ごとに1 jobへ束ねられるので、browserを閉じても続く。

async function exportCuts() {
  // 対象は表示中(=グループで絞った後)のlist。表と違う中身を書き出すと、見えていない行が
  // 黙ってqueueへ入る。
  const cuts = visibleCuts();
  if (!cuts.length) {
    $("cuts-status").textContent = "表示中の切り出しがありません。";
    return;
  }
  const button = $("cuts-export");
  button.disabled = true;
  $("cuts-status").textContent = "queueへ投入中…";
  try {
    const result = await apiSend("POST", "/api/clips/batch", {
      items: cuts.map((cut) => ({
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
  // 対象は表示中のlist。グループを選んでいればposition順に繋がるので、並び=完成の構成になる。
  const cuts = visibleCuts();
  if (!cuts.length) {
    $("cuts-status").textContent = "表示中の切り出しがありません。";
    return;
  }
  const button = $("cuts-reel");
  button.disabled = true;
  $("cuts-status").textContent = "queueへ投入中…";
  try {
    // 並べ替えない。表示した順と違う順で繋がれる方が、順序を指定できないより悪い誤認を生む。
    const result = await apiSend("POST", "/api/reels", {
      items: cuts.map((cut) => ({
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
  // player-statusは切り出しpathやerrorの置き場。速度のような「操作したことの確認」で
  // 上書きすると、復元できない出力pathが無害なkey操作で消える。
  showToast(`再生速度 ${select.value}x`);
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
    // IN/OUTのframe単位の詰め。shiftで同じkeyがOUT側({ })になる。
    "[": () => nudgeCut("in", -1),
    "]": () => nudgeCut("in", 1),
    "{": () => nudgeCut("out", -1),
    "}": () => nudgeCut("out", 1),
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

// 配信者の絞り込みに出すのは「選ぶと何かが出てくる」配信者だけ。実体(素材/mp4)が1本も
// 残っておらず、転写もコメント索引も無い配信者は、選んでも空の一覧が出るだけの選択肢に
// なる(retentionで素材が消えた配信者が実測13名居た)。逆に実体が無くても転写・索引が在れば
// 残す — その録画へ辿る道はここしかない(録画一覧が「実体なし」の行を残しているのと同じ理由)。
function hasSomethingToShow(streamer) {
  return Boolean(streamer.playable || streamer.transcribed || streamer.comment_indexed);
}

// 一括処理の配信者select。候補は一括処理の対象表そのもの(検索側の「何かが出てくる配信者」
// とは母集合が違う — 転写が無くても焼き込みの対象にはなる)。
function fillBulkStreamerSelect() {
  const select = $("bulk-streamer");
  const want = state.bulkOnly || "";
  const first = select.options[0];
  select.innerHTML = "";
  select.appendChild(first);
  state.bulk.forEach((streamer) => {
    const option = document.createElement("option");
    option.value = streamer.unique_id;
    option.textContent = streamer.unique_id;
    select.appendChild(option);
  });
  select.value = want;
  // 候補に無い配信者を指したまま「@X だけを表示中」にすると、表が空のまま戻せなくなる。
  state.bulkOnly = select.value || null;
}

function fillStreamerSelects() {
  [$("flt-streamer")].forEach((select) => {
    const keep = select.value;
    const first = select.options[0];
    select.innerHTML = "";
    select.appendChild(first);
    state.streamers.filter(hasSomethingToShow).forEach((streamer) => {
      const option = document.createElement("option");
      option.value = streamer.unique_id;
      option.textContent = streamer.unique_id;
      select.appendChild(option);
    });
    // 選択中の配信者が候補から外れた(素材が消えた)場合は「全て」へ戻す。valueを代入しても
    // 一致するoptionが無ければselectは先頭を指すが、絞り込みの状態が画面と食い違わないよう
    // 明示的に戻す。
    select.value = keep;
    if (keep && select.value !== keep) select.value = "";
  });
}

// 配信者名のcell。実体(素材/mp4)が1本も残っていない配信者はここで名乗らせる — 表からは
// 消さない。「録画5本・転写0本」の行が理由も無く消えるより、なぜ進まないのかが読める方がよい。
function streamerNameCell(streamer) {
  if (streamer.playable) return streamer.unique_id;
  const wrap = document.createElement("span");
  wrap.className = "vd-kinds";
  wrap.appendChild(document.createTextNode(streamer.unique_id));
  const gone = document.createElement("span");
  gone.className = "vd-src vd-src-none";
  gone.textContent = "実体なし";
  gone.title = "素材(.ts)もmp4も残っていないため、文字起こしも再生もできません。";
  wrap.appendChild(gone);
  return wrap;
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
      // 投入できる録画(実体があって未転写)が1本も無ければ押させない。「転写済 < 録画数」を
      // 根拠にすると、実体の無い録画がその差を永久に埋めないので、押しても0件投入のbuttonが
      // 有効なままになる(投入側は実体の無い録画を弾く)。
      // STTが無効なときも押させない — 押してから503で分かるのでは遅い。
      const sttOff = state.sttAvailable === false;
      button.disabled = !streamer.transcribable || sttOff;
      button.title = sttOff
        ? "文字起こし機能が無効です。設定を確認してください。"
        : (streamer.transcribable ? "" : "未転写で実体の残っている録画がありません。");
      button.addEventListener("click", () => enqueue(streamer.unique_id));
      return [
        streamerNameCell(streamer),
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
  // 取り消しの確認文で「何本を捨てるか」を名乗るために最新の内訳を控える。
  state.queueCounts = counts;
  const parts = Object.keys(QUEUE_LABELS)
    .filter((key) => counts[key])
    .map((key) => `${QUEUE_LABELS[key]} ${fmtNum(counts[key])}`);
  const available = queue && queue.available;
  // 行buttonのdisable判定に使う。押してから503で知るのでは遅い。
  state.sttAvailable = Boolean(available);
  $("job-summary").textContent = available
    ? parts.join(" / ") || "queueに行がありません。"
    : "文字起こし機能が無効です。設定を確認してください。";
  // 表には完了・失敗・取消も並ぶ。既定は「まだ終わっていないもの」に絞る — 見出しどおりの
  // 中身にしないと、終わったのか消えたのか積まれていないのかが読み分けられない。
  const activeOnly = $("queue-active-only");
  const visible = activeOnly && activeOnly.checked
    ? items.filter((item) => item.state === "running" || item.state === "pending")
    : items;

  renderTableRows(
    "queue-rows",
    "queue-empty",
    visible,
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
  button.title = reason;
  // 押せない理由が無いときは「押す理由」を出す。indexが取り残されたぶんは検索結果から
  // 落としているので、更新しない限り出てこないことがuserに見えていないと押されない。
  const stale = status.stale_passages || 0;
  const unindexed = status.unindexed_groups || 0;
  if (reason) {
    note.textContent = reason;
  } else if (stale || unindexed) {
    const parts = [];
    if (stale) parts.push(`${fmtNum(stale)}件が張り直し後で検索から除外中`);
    if (unindexed) parts.push(`${fmtNum(unindexed)}件が未index`);
    note.textContent = `${parts.join(" / ")}。indexを更新すると検索対象に戻ります。`;
  } else {
    note.textContent = "";
  }
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
    // 同じ行為を「投入」「追加」「queueへ入れる」の3語で呼んでいた。語は「投入」に揃える。
    $("job-summary").textContent = `${fmtNum(result.added)}本を投入しました。`;
    renderQueue(result.queue);
  } catch (err) {
    $("job-summary").textContent = err.message;
  }
}

// ===== 一括処理 =====

// 種別のラベルはserver側のMEDIA_JOB_TITLESと同じ語を使う。画面ごとに言い換えると、
// Job画面に並ぶjob titleと突き合わせられなくなる。
const BULK_LABELS = {
  transcribe: "文字起こし", laugh: "笑い声分析",
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
// 音声から笑い声を検出してシーン検索へ載せる種別。出力fileを作らないので、
// 文字起こしと同じくdiskの見積りもmp4のchipも意味を持たない。
const BULK_LAUGH_KIND = "laugh";
// mp4を作らない種別。元mp4の合計を並べても確かめるべき数字にならないので、chipを分ける。
const BULK_NO_MP4_KINDS = [BULK_PACK_KIND, BULK_TRANSCRIBE_KIND, BULK_LAUGH_KIND];
// 出力fileを作らない種別。disk空きの警告で投入を止める意味が無い。
const BULK_NO_DISK_KINDS = [BULK_TRANSCRIBE_KIND, BULK_LAUGH_KIND];
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
    line.classList.toggle("bulk-picked", box.checked);
    box.addEventListener("change", () => {
      if (box.checked) state.bulkSelected.add(row.id);
      else state.bulkSelected.delete(row.id);
      // 選択のたびに表ごと描き直すとcheckboxからfocusが外れ、連続して選べない。
      // 行の背景だけその場で追従させる。
      line.classList.toggle("bulk-picked", box.checked);
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
  if (free !== null && !BULK_NO_DISK_KINDS.includes(estimate.kind)) {
    // ts結合が要るのは素材と同じだけの空きで、元mp4の容量とは関係が無い。ここへ元動画の
    // 合計を並べると、確かめるべき数字を取り違える。
    notes.push(estimate.kind === BULK_PACK_KIND
      ? `書き込み先の最小空き容量は ${fmtBytes(free)} です。`
      : `書き込み先の最小空き容量は ${fmtBytes(free)}、`
        + `同時に走るぶんの元動画は ${fmtBytes(estimate.largest_source_bytes)} です。`);
  }
  if (estimate.kind === BULK_TRANSCRIBE_KIND) {
    // 恒常的な説明はbulk-note側が持つ。確認行に再掲すると、毎回同じ長文を読み飛ばす
    // 習慣が付き、ここで本当に読むべき数字(本数・空き容量・⚠の行)が埋もれる。
    notes.push("GPUを1本ずつ直列に使うため、所要は本数ぶん積み上がります。");
  }
  if ((disk.low_volumes || []).length && !BULK_NO_DISK_KINDS.includes(estimate.kind)) {
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
    || (!BULK_NO_DISK_KINDS.includes(estimate.kind) && (disk.low_volumes || []).length > 0);
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
  fillBulkStreamerSelect();
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
  // 理由の無いgrey outは「壊れている」と読まれる。押せない理由をその場に置く。
  redoBox.title = redoBox.disabled
    ? `${BULK_LABELS[kind]}には「作り直す」余地がありません（済んだ録画は対象から外れます）。`
    : "出力済みの録画も対象に含めて投入し直します。";
  $("bulk-note").textContent = kind === BULK_DELETE_KIND
    ? "録画本体のmp4だけを即座に削除します（queueには載りません）。対象は.tsが残っている録画だけで、"
      + "作り直せない録画は自動で対象から外します。焼き込み・Up出力・名前を変えたfileは残ります。"
      + "削除後は種別を「再mp4化」にして投入すると、同じ.tsから作り直せます。"
    : kind === BULK_TRANSCRIBE_KIND
    ? "録画の音声を文字起こしして、シーン検索の対象にします（字幕の焼き込みにも要ります）。"
      + "配信者名の左の ▶ で録画一覧を開くと、選んだ録画だけを投入できます。"
      + "GPUを1本ずつ直列に使います。進捗と取り消しは下の「文字起こしのqueue」で、"
      + "1本単位の取り消し・再試行はJob画面（種別「文字起こし」）で行えます。"
    : kind === BULK_LAUGH_KIND
    ? "録画の音声から笑い声を検出して、シーン検索の「笑い声」で引けるようにします"
      + "（転写に「笑」と書かれていなくても当たります — 文字起こしは笑い声を文字にしません）。"
      + "配信者名の左の ▶ で録画一覧を開くと、選んだ録画だけを投入できます。"
      + "解析済みの録画も検索indexへ入っていなければ対象になり、その場合は数十msで終わります。"
      + "切り出し候補の「笑い声」列にも同じ結果を使います。"
    : kind === BULK_PACK_KIND
    ? "素材の.tsを解像度の切れ目ごとに1 fileへ束ね直します（再encodeしないbyte連結で、映像も"
      + "再生も変わりません）。2秒ごとに刻まれたsegmentが数千本あると、走査・backup・移送の"
      + "すべてがfile数に比例して重くなるのを畳むための処理です。録画1本ごとに1つのjobとして"
      + "queueへ入り、束ね済みの録画は自動で対象から外れます。"
    : "録画1本ごとに1つのjobとしてqueueへ入り、順に処理します。配信者名の左の ▶ で録画一覧を開くと、"
      + "選んだ録画だけを投入できます。所要時間はこのserverで実際に完了した同種jobの実測から出しています"
      + "（実績が無い種別は不明と表示します）。投入後の進捗確認と取り消しはJob画面で行います。";
  // 文字起こしも映像jobと同じ台帳(kind=stt)に載る。種別で行き先を分けていた頃は、
  // 1本単位の取り消し・再試行を持つJob画面から遠ざける結果になっていた。
  const jobsLink = $("bulk-jobs-link");
  jobsLink.textContent = "Job画面で進捗を見る";
  jobsLink.href = kind === BULK_TRANSCRIBE_KIND ? "/jobs?kind=stt"
    : kind === BULK_LAUGH_KIND ? "/jobs?kind=laugh" : "/jobs";
  // 文字起こしのqueueと転写率は、この種別のときだけ意味のある表。
  const toStt = kind === BULK_TRANSCRIBE_KIND;
  $("bulk-stt-queue").hidden = !toStt;
  $("bulk-stt-coverage").hidden = !toStt;
  const total = rows.reduce((sum, s) => sum + bulkTargetCount(s, kind, redo), 0);
  // 投入結果や失敗の文言(bulkNote)は、次に条件を変えるまで残す。renderのたびに既定の
  // 集計文へ戻していた頃は、投入した瞬間に「入れました」が消えて何も起きていないように
  // 見えていた。
  $("bulk-summary").textContent = state.bulkNote
    || (total
      ? `${BULK_LABELS[kind]}の対象: ${state.bulkOnly ? "この配信者で" : "全体で"}${fmtNum(total)}本`
      : `${BULK_LABELS[kind]}の対象はありません。`);
  // 最も広い範囲に効くbuttonだけが種別も本数も名乗らず、消す種別でも作る種別と同じ色を
  // していた。効く範囲は絞り込みに追従させる(絞り込み中に押せないと、渡された選択を
  // 解除してからでないと投入できず、見えている範囲と投入範囲がずれる回避策になっていた)。
  const all = $("bulk-all");
  const scope = state.bulkOnly ? `@${state.bulkOnly}` : "全配信者";
  all.textContent = `${BULK_LABELS[kind]} ${scope} ${fmtNum(total)}本`;
  all.className = kind === BULK_DELETE_KIND
    ? "btn btn-danger btn-small"
    : "btn btn-primary btn-small";
  all.title = kind === BULK_DELETE_KIND
    ? `${scope}の元mp4を削除します（queueには載らず即座に消えます）。押す前に規模を確認できます。`
    : `${scope}の未処理をまとめてqueueへ入れます。押す前に規模を確認できます。`;
  all.disabled = total === 0;

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
      : `${BULK_LABELS[pending.kind]} ${fmtNum(result.total)}本を投入しました。`
        + (pending.kind === BULK_TRANSCRIBE_KIND
          ? "進捗と取り消しは下の「文字起こしのqueue」で確認できます。"
          : "進捗の確認と取り消しはJob画面で行います。");
    // 投入した直後に下の表が古いままにならないよう、返ってきた現況で描き直す。
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
    drawTimeline();
    updateTimeLabel();
    highlightActiveSegment();
    highlightActiveChapter();
    highlightActiveComment();
  };
  video.addEventListener("timeupdate", onTick);
  // timeupdateは約250ms間隔でしか来ない。拡大窓では1秒が数十pxあるので、再生線がその
  // 間隔で飛び飛びに描かれて「再生が滑らかでない」ように見える。線の描き直しだけをframeに
  // 載せる(行のhighlight等はDOMを触るのでtimeupdateのまま — 60Hzで回すと逆に重い)。
  video.addEventListener("play", startTimelineFrames);
  video.addEventListener("playing", startTimelineFrames);
  video.addEventListener("pause", stopTimelineFrames);
  video.addEventListener("ended", stopTimelineFrames);
  // 録画を切り替えると<video>はplaybackRateを1へ戻す。選択中の倍率を入れ直す。
  video.addEventListener("loadedmetadata", () => {
    applyRate();
    onTick();
  });
  // 幅が1px変わるだけで波形の畳み込みcacheが外れ、全尺(0.1秒刻みで3時間なら10万点超)を
  // 畳み直すことになる。掴んで動かしている間ずっとそれを繰り返さないよう、手が止まってから
  // 1回だけ描き直す。
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(drawTimeline, RESIZE_DEBOUNCE_MS);
  });

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
  // 波形は初回生成が長いが、無音snap・シーン選択の土台なので既定ON(明示的に切れば記憶する)。
  const showWave = $("show-wave");
  showWave.checked = localStorage.getItem(WAVE_PREF_KEY) !== "0";
  showWave.addEventListener("change", () => {
    localStorage.setItem(WAVE_PREF_KEY, showWave.checked ? "1" : "0");
    if (state.current) loadWaveform(state.current.recording_id);
    else drawTimeline();
  });

  const heat = $("heat");
  heat.addEventListener("pointerdown", (event) => {
    const seconds = secondsFromClientX(event.clientX);
    if (seconds === null) return;
    heat.setPointerCapture(event.pointerId);
    dragOnZoom = false;
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
  heat.addEventListener("pointermove", scheduleHeatMove);
  heat.addEventListener("pointerleave", () => {
    cancelHeatMove();
    $("thumb").classList.add("hidden");
  });
  heat.addEventListener("pointerup", (event) => {
    // 溜めてある最後の位置を入れてから確定する(離す直前の詰めを捨てない)。
    flushHeatMove();
    heat.releasePointerCapture(event.pointerId);
    finishRangeDrag(event);
  });
  heat.addEventListener("pointercancel", () => {
    cancelHeatMove();
    dragMode = null;
    $("thumb").classList.add("hidden");
  });
  heat.addEventListener("dblclick", (event) =>
    selectSceneAt(secondsFromClientX(event.clientX)));

  // 拡大窓。drag中は窓を凍結する(追従が生きたままだとpointerの下の時刻が滑る)。
  const zoom = $("zoom");
  zoom.addEventListener("pointerdown", (event) => {
    const win = zoomWindow(video.duration);
    if (!win) return;
    const mode = hitTestZoom(event);
    // 窓の移動は窓自体を凍結しない(凍結すると動かした結果が描かれない)。掴んだ時点の
    // 換算だけを控える。
    if (mode === "zoompan") {
      zoom.setPointerCapture(event.pointerId);
      dragMode = "zoompan";
      dragOnZoom = true;
      panStartX = event.clientX;
      panStartSeconds = win.start;
      panSecondsPerPx = win.span / Math.max(1, zoom.getBoundingClientRect().width);
      $("zoom-follow").checked = false;
      state.zoomSpan = win.span;
      zoom.style.cursor = "grabbing";
      return;
    }
    zoomDragWindow = win;
    dragOnZoom = true;
    const seconds = zoomSecondsFromClientX(event.clientX);
    if (seconds === null) {
      zoomDragWindow = null;
      dragOnZoom = false;
      return;
    }
    zoom.setPointerCapture(event.pointerId);
    dragMode = mode;
    if (dragMode === "seek") {
      video.currentTime = seconds;
    } else if (dragMode === "new") {
      dragAnchor = seconds;
      setCut(seconds, seconds);
    } else if (dragMode === "band") {
      dragBandOffset = seconds - state.cutIn;
      dragBandLength = state.cutOut - state.cutIn;
    }
  });
  zoom.addEventListener("pointermove", (event) => {
    if (dragMode && dragOnZoom) {
      dragRange(event);
    } else if (!dragMode) {
      zoom.style.cursor = HEAT_CURSORS[hitTestZoom(event)];
    }
  });
  zoom.addEventListener("pointerup", (event) => {
    zoom.releasePointerCapture(event.pointerId);
    finishRangeDrag(event);
    zoomDragWindow = null;
    dragOnZoom = false;
    zoom.style.cursor = HEAT_CURSORS[hitTestZoom(event)];
    drawTimeline();
  });
  zoom.addEventListener("pointercancel", () => {
    dragMode = null;
    zoomDragWindow = null;
    dragOnZoom = false;
    zoom.style.cursor = "pointer";
  });
  zoom.addEventListener("dblclick", (event) =>
    selectSceneAt(zoomSecondsFromClientX(event.clientX)));
  // 縦wheelで拡縮、横wheel(とshift+wheel)で左右移動。横成分を拡縮に混ぜていたため、
  // 横scrollできるdeviceでは「押しただけで勝手に拡縮する」挙動になっていた。
  // shift+wheelはbrowserによって横成分で届く(Chrome)ぶんも拾う。
  zoom.addEventListener("wheel", (event) => {
    if (!zoomWindow(video.duration)) return;
    event.preventDefault();
    const pan = event.shiftKey ? (event.deltaY || event.deltaX) : event.deltaX;
    if (pan) {
      panZoom(pan > 0 ? 1 : -1);
      return;
    }
    if (!event.deltaY) return;
    const rect = zoom.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    zoomBy(event.deltaY > 0 ? ZOOM_WHEEL_FACTOR : 1 / ZOOM_WHEEL_FACTOR, ratio);
  }, { passive: false });
  $("zoom-follow").addEventListener("change", drawTimeline);
  $("zoom-left").addEventListener("click", () => panZoom(-1));
  $("zoom-right").addEventListener("click", () => panZoom(1));
  $("zoom-in").addEventListener("click", () => zoomBy(1 / ZOOM_WHEEL_FACTOR, 0.5));
  $("zoom-out").addEventListener("click", () => zoomBy(ZOOM_WHEEL_FACTOR, 0.5));

  // IN/OUTの手打ちと境界確認。
  ["cut-in", "cut-out"].forEach((id) => {
    const kind = id === "cut-in" ? "in" : "out";
    $(id).addEventListener("change", () => applyCutField(id, kind));
    $(id).addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      $(id).blur();
    });
  });
  $("preview-in").addEventListener("click", () => previewBoundary("in"));
  $("preview-out").addEventListener("click", () => previewBoundary("out"));
  // 手動で止めたら確認再生の停止予約も解除する(残すと次の再生が境界で勝手に止まる)。
  video.addEventListener("pause", () => { previewStopAt = null; });

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
  // グループの選択・一括操作。行き先は表のすぐ上の「移動先」で指す。
  $("cuts-select-all").addEventListener("change", () => {
    if ($("cuts-select-all").checked) {
      visibleCuts().forEach((cut) => state.cutsSelected.add(cut.id));
    } else {
      state.cutsSelected.clear();
    }
    state.lastPick.cuts = null;
    renderCuts();
  });
  $("cuts-move-target").addEventListener("change", () => {
    state.moveTarget.cuts = $("cuts-move-target").value;
    updateMoveButtons("cuts");
  });
  $("cuts-move").addEventListener("click", () => assignSelection("cuts", "move"));
  $("cuts-copy").addEventListener("click", () => assignSelection("cuts", "copy"));
  $("cuts-bulk-delete").addEventListener("click", deleteSelectedCuts);
  $("marks-select-all").addEventListener("change", () => {
    if ($("marks-select-all").checked) {
      visibleMarks().forEach((mark) => state.marksSelected.add(mark.id));
    } else {
      state.marksSelected.clear();
    }
    state.lastPick.marks = null;
    renderMarks();
  });
  $("marks-move-target").addEventListener("change", () => {
    state.moveTarget.marks = $("marks-move-target").value;
    updateMoveButtons("marks");
  });
  $("marks-move").addEventListener("click", () => assignSelection("marks", "move"));
  $("marks-bulk-delete").addEventListener("click", deleteSelectedMarks);
  // 見どころtab・切り出しリストtabのplayer。範囲の終端で止めるのはtimeupdateで見る
  // (seek済みの位置から飛び越えることがあるので、等号ではなく通過で判定する)。
  bindInlinePlayer("mark", markPlayer, (mark) => openMark(mark));
  bindInlinePlayer("cut", cutPlayer, (cut) => openCut(cut));
  // グループのメモ。入力欄から離れた時点で確定する(打鍵ごとには投げない)。
  $("cuts-group-memo").addEventListener("change", async () => {
    const memo = $("cuts-group-memo");
    const groupId = Number(memo.dataset.groupId || 0);
    if (!groupId) return;
    try {
      await apiSend("PATCH", `/api/groups/${groupId}`, { memo: memo.value.trim() });
      showToast("メモを保存しました。");
    } catch (err) {
      $("cuts-status").textContent = err.message;
    }
    await refreshGroupData();
    renderGroupViews();
  });
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
    // 消すのは表示中(=グループで絞った後)の範囲だけ。全てを消すつもりのない操作で
    // 他グループの行まで消えるのが最悪の事故になる。
    const count = visibleCuts().length;
    if (!count) return;
    const scope = groupScopeLabel(state.groupSel);
    const ok = await confirmDialog(
      `${scope}の${fmtNum(count)}件をすべて削除しますか？この操作は取り消せません。`,
      { title: `${scope}の全削除`, confirmLabel: "すべて削除", danger: true },
    );
    if (!ok) return;
    // 消える範囲を観たまま残さない(実体の無い行を再生し続けることになる)。
    const seen = cutPlayer.watching();
    const gone = seen && visibleCuts().some((cut) => cut.id === seen.id);
    try {
      const suffix = state.groupSel ? `?group=${encodeURIComponent(state.groupSel)}` : "";
      await apiSend("DELETE", `/api/cutlist${suffix}`);
    } catch (err) {
      showError(err);
      return;
    }
    if (gone) cutPlayer.close();
    loadCuts();
  });

  $("semantic-build").addEventListener("click", async () => {
    const button = $("semantic-build");
    button.disabled = true;
    // 押した本人が見ているのはシーン検索tabなので、結果もここへ出す。別tabの欄へ書くと
    // 成功も失敗も画面に現れず、数時間かかる処理が始まったかどうかも判らない。
    $("semantic-result").textContent = "意味検索indexを更新中…";
    try {
      // serverは受け付けた時点で返す(構築は数時間かかることがある)。完了の件数は
      // WSのsemantic_indexで届くので、ここでは開始したことだけを出す。
      await apiSend("POST", "/api/search/semantic/build");
      $("semantic-result").textContent =
        "意味検索indexの構築を開始しました。進捗はJob画面で確認できます。";
    } catch (err) {
      $("semantic-result").textContent = err.message;
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
  // 絞り込みに追従する。button文言に効く範囲が出ているので、取り違えは起きない。
  $("bulk-all").addEventListener("click", () => askBulk(state.bulkOnly, null));
  $("bulk-streamer").addEventListener("change", () => {
    hideBulkConfirm();
    closeBulkRows();
    renderBulk();
  });
  $("queue-active-only").addEventListener("change", () => loadStatus());
  $("job-cancel").addEventListener("click", async () => {
    // serverは pending だけでなく running も止める。実行中の転写は数十分走っていることが
    // あり、捨てた分は取り戻せないので、名前どおりの範囲だと思って押させない。
    const counts = state.queueCounts || {};
    const running = counts.running || 0;
    const pending = counts.pending || 0;
    if (!running && !pending) {
      $("job-summary").textContent = "取り消せる文字起こしはありません。";
      return;
    }
    const ok = await confirmDialog(
      `実行中 ${fmtNum(running)}本・待機中 ${fmtNum(pending)}本を取り消します。`
      + "実行中の1本もその場で止まり、そこまでの処理は破棄されます。",
      { title: "文字起こしの取り消し", confirmLabel: "取り消す" },
    );
    if (!ok) return;
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
      $("semantic-result").textContent = `意味検索indexの構築に失敗しました: ${message.error}`;
    } else if (message.result) {
      $("semantic-result").textContent =
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
// 他画面からの遷移先。tabを自分で探させない。#transcribe は「一括文字起こし」tabが
// 独立していた頃の名前で、Job画面などの外部linkが今も使うので別名として残す。
const HASH_VIEWS = { "#transcribe": "bulk", "#jobs": "bulk", "#bulk": "bulk",
  "#marks": "marks", "#cuts": "cuts", "#search": "search" };
const bootView = HASH_VIEWS[location.hash];
if (bootView) {
  // #transcribe は「文字起こしの様子を見に来た」という意味なので、種別もそこへ合わせる。
  if (location.hash === "#transcribe" || location.hash === "#jobs") {
    $("bulk-kind").value = BULK_TRANSCRIBE_KIND;
  }
  // 配信者画面からの遷移は1人ぶんの容量整理の最中なので、同じ配信者を選んだ状態で入れる。
  // 解除しても同じ画面のselectで戻せる(以前は配信者画面へ戻り直すしかなかった)。
  // 表示の前に決める — showViewが走らせるloadBulkが、この値で絞った表を描く。
  if (location.hash === "#bulk") {
    state.bulkOnly = new URLSearchParams(location.search).get("streamer") || null;
  }
  showView(bootView);
}
loadStatus();
loadSemantic();
loadClipDefaults();
// 開いた時点で録画一覧を出す。語なしの一覧はrunSearchが担うが、起動時は誰も呼ばないため
// 「検索語を入力してください」のまま止まり、当たる語を先に発明しないと1本も開けなかった
// (確認状態の印も、一覧が出ていなければ目に入らない)。
runSearch(true);
// 記録先は録画を跨いで使い回す。読み直す前に入れておかないと、起動直後の1件だけが
// 前回のグループではなく未分類へ落ちる。
state.addGroup = loadAddGroupPref();
// 一括の行き先の初期値は記録先に合わせる。今作っている切り抜きが行き先になることが
// 多く、既定が常に未分類だと毎回選び直しになる。
state.moveTarget.cuts = state.addGroup;
state.moveTarget.marks = state.addGroup;
// player直下の「この録画の見どころ・切り出し」と記録先chipはcut list/グループ一覧を
// 使う。tabを開くまで読まないと、録画を開いた直後だけ切り出しが抜けた一覧になる。
loadCuts();
connectWS(onMessage);
