// 配信者動画: 複数配信を横断してシーンを探し、素材として切り出す編集アシスト画面。
// 検索hitはvideo_time(mp4のPTS秒)を持つのでそのままseekできる。

const PAGE_SIZE = 200;
const SEARCH_DEBOUNCE_MS = 250;
// 「queueへ載った」を告げるtoastの表示時間。受け取った合図なので短くてよい(完了の
// toastはWSのjob_updateが既定の長さで別に出す)。
const JOB_TOAST_MS = 3000;
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
// timelineへ載せるgift iconの一辺(px)。全尺barは縦を波形とheatで使い切っているので、
// そちらは更に小さくする。横に重なるiconは高額なものだけ残す(pickGiftIcons)。
const GIFT_ICON_PX = 28;
const GIFT_ICON_FULL_PX = 20;
// icon同士の最小間隔(px)。詰めて並べると連投されたgiftで帯が埋まり、
// どこで何が飛んだのかがかえって読めなくなる。
const GIFT_ICON_GAP_PX = 2;
// 送り主。iconだけでは「何が飛んだか」しか読めないので、拡大窓ではavatarを重ね、名前の
// 頭を添える。名前を丸ごと出すと1件が横に伸び、その幅のぶんだけ隣のgiftが落ちる。
const GIFT_NAME_CHARS = 3;
const GIFT_NAME_FONT_PX = 9;
// 名前1行ぶんの高さ(iconの下)。
const GIFT_NAME_LANE_PX = 11;
// 送り主avatarの直径(iconの一辺に対する割合)。iconの左下へ重ねるので、これ以上大きくすると
// giftの絵そのものが読めなくなる。
const GIFT_AVATAR_RATIO = 0.5;
// 名前まで載せると1件の幅が2〜3倍になり、同じ列へ並べられる件数が落ちる。縦へ段を足して
// 拾い直す(実際の段数は帯の高さが許すぶんだけ)。段を積み過ぎると波形が残らない。
const GIFT_MAX_ROWS = 3;
const GIFT_ROW_GAP_PX = 2;
// gift側が使ってよい拡大窓の高さの割合。ここを越えて段を足さない — この窓は波形を読む
// 場所で、giftはその上に載る注記に留める。段は詰まったときだけ使われる(空いていれば
// 全て最上段に載る)ので、この上限は「混んだ場面でどこまで下へ伸ばすか」を決める。
const GIFT_LANE_RATIO = 0.85;
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
// 表示設定の永続化key(読み書きはcommon.jsのpref API)。画面は独立したHTML documentで
// nav遷移はフルリロードになるため、繰り返し同じ値を選ぶcontrolはここへ残して次も同じ
// 見え方で始める。既存の3つはkeyを変えない — 変えると保存済みの値が捨てられる。
const WAVE_PREF_KEY = "tictok.videos.showWave";
const GIFT_PREF_KEY = "tictok.videos.showGifts";
const VOLUME_PREF_KEY = "tictok.videos.volume";
const MUTE_PREF_KEY = "tictok.videos.muted";
const VIEW_PREF_KEY = "tictok.videos.view";
const PLAY_RATE_PREF_KEY = "tictok.videos.playRate";
// 配信者の絞り込みは3つのselectが同じ値を指す(STREAMER_SELECTS)ので、keyも1つにする。
const STREAMER_PREF_KEY = "tictok.videos.streamer";
// 「表示するグループ」は見どころtabの絞り込み(state.groupSel)。
const GROUP_FILTER_PREF_KEY = "tictok.videos.groupFilter";
// 自動生成(shortの書き戻し)の行を一覧に出すか。既定は出さない。
const SHOW_AUTO_PREF_KEY = "tictok.videos.showAutoMarks";
// 切り出しの設定。シーン検索側(primary)と見どころtab側(mirror)は同じ値を指すので、
// keyはCLIP_CONTROLSの項目ごとに1つ。
const CLIP_PREF_KEYS = {
  variant: "tictok.videos.clipVariant",
  normalize_audio: "tictok.videos.clipNormalize",
  remove_bgm: "tictok.videos.clipRemoveBgm",
  subtitles: "tictok.videos.clipSubtitles",
  mode: "tictok.videos.clipMode",
};

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
  // 飛んだgift 1件ずつ [{t, gift_id, name, count, diamonds, nickname, uid}]と、
  // gift_id(文字列)→icon URL。heatの山が「何だったのか」をiconで、「誰が送ったか」を
  // uid(avatar poolのkey)とnicknameで読めるようにする。
  gifts: [],
  giftIcons: {},
  // 再生位置以前で最後のgift(PK・ギフトpanelの帯)。ギフト欄に出しているのは今のPKの分
  // だけなので、これはstate.giftsではなくpkGiftItems/pkGiftRows上のindex。
  giftIndex: -1,
  // この録画に掛かったPK(Battle)。[{battle_id, ordinal, start, end, result, own_score,
  // opp_score, participants:[...], series:[{t, own, opp, parts:[...]}], ...}] で、
  // 時刻はどれも動画の秒。partsは再生位置での陣営別score(スコアバーの分割)。
  battles: [],
  // 拡大窓の位置(左端の秒)と幅。位置はここだけが持ち、追従はこれを置き直す(followZoom)。
  // nullは「まだ決まっていない」で、最初の描画で再生位置から決まる。
  zoomStart: null,
  zoomSpan: ZOOM_DEFAULT_SPAN_SECONDS,
  sprite: null,
  variants: [],
  // 開いている録画に実在する素材版のkind。再生できる版とsegmented controlの押せる範囲を
  // これ1つで決める(空 = まだ確定していない)。
  variantKinds: [],
  // 一括処理tab: 配信者×種別の対象数と、確認に出している投入内容。配信者selectの選択肢も
  // この一覧から作る(実体の有無まで含んだ、配信者の唯一の名簿)。
  bulk: [],
  bulkDisk: null,
  // 文字起こしが使えるか。使えないときは押させない(押してから503で知るのでは遅い)。
  sttAvailable: null,
  bulkPending: null,
  // 配信者画面から渡された絞り込み対象(unique_id)。nullなら全配信者。
  bulkOnly: null,
  // 開いているcell({uniqueId, kind})と、その録画・選択中のid。展開を複数開けるようにしない
  // のは、選択が複数配信者・複数種別に散らばると「何を投入するのか」が一目で読めなくなるため。
  bulkOpen: null,
  bulkOpenRows: null,
  bulkSelected: new Set(),
  // 投入結果や失敗の文言。空なら対象数の集計文を出す。
  bulkNote: "",
  segments: [],
  segmentIndex: -1,
  // segmentIndexが「今まさに喋っている行」か「直前に喋り終えた行」か。無音でも行の帯は
  // 残す(消すと一文ごとに点滅する)ので、太字の付け外しをこれで決める。
  segmentLive: false,
  chapters: [],
  chapterIndex: -1,
  comments: [],
  commentIndex: -1,
  // 今開いている録画の見どころ(seek barのmarker用)と、全録画分の一覧(見どころtab用)。
  // 見どころは印であり素材の候補でもある(尺を持つ行がmp4にできる)ので、listは1本しかない。
  bookmarks: [],
  marks: [],
  selFrom: null,
  selTo: null,
  // 出力済みclip: serverが走査したfileの実物と、保存先ごとの内訳。DBには行が無いので、
  // ここが持つのは常に「開いた時点でディスクに在ったもの」である。
  clipFiles: [],
  clipRoots: [],
  // 今この場で観ているfileのpath(一覧でその行に印を付けるため)。DBの行ではないので
  // idが無く、実体そのものであるpathを身元にする。
  clipPlaying: null,
  // グループ(切り抜き動画1本の単位)の一覧と、見どころtabの絞り込み。
  // 値は "":全て / "none":未分類 / "<id>":そのグループ。
  groups: [],
  groupSel: "",
  // 見どころの記録先グループ。"none":未分類 / "<id>"。localStorageで残す。
  addGroup: "none",
  // shortの自動生成が書き戻した行(origin=auto)も一覧に出すか。
  showAuto: false,
  // 選択中の行id。まとめての付け替え(移動先へ入れる)と削除の対象。
  marksSelected: new Set(),
  // shift+クリックの範囲選択の起点(表示順のindex)。表を描き直しても続けて使えるよう
  // 行要素ではなくindexで持つ。
  lastPick: { marks: null, "gops:left": null, "gops:right": null },
  // グループ操作tab: 左右のpaneが指すグループ("":全て / "none":未分類 / "<id>")と、
  // pane別の選択(見どころのid)。見どころtabの選択(marksSelected)とは別物 — 同じ行を
  // 別の目的で選んでいる場所なので、共有すると片方の仕分けの途中で対象が入れ替わる。
  gops: {
    left: "",
    right: "none",
    selected: { left: new Set(), right: new Set() },
  },
  // ドラッグ中の行(tabへ放り込む経路)。dataTransferはdragover中に中身を読めないため、
  // 行き先の可否判定に使う情報はここに持つ。
  drag: null,
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

const VIEWS = ["search", "marks", "groups", "clips", "bulk"];

// 配信者の選択はtabを跨いで引き継ぐ。2つのselectが独立していたため、
// tabを移るたび「今どの配信者の作業をしているか」を選び直す必要があった。
const STREAMER_SELECTS = ["flt-streamer", "bulk-streamer"];

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
  // 次に開いた時も同じtabで始める。nav遷移はフルリロードなので、残さないと作業の途中で
  // 他画面を見に行くたびシーン検索へ戻される。
  prefSet(VIEW_PREF_KEY, name);
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
  // 時間軸は隠れている間の描画要求を全て捨てる(実寸が0になるため drawHeat/drawZoom が
  // 即returnする)。離れている間に届いた波形・heat・giftは描かれないまま残り、再描画の口は
  // timeupdateとresizeしか無いのに、離れる時にvideoを止めているので誰も回さない。
  // 戻った時点で1回描き直す(隠れている間のresizeで寸法がずれた絵も、ここで作り直る)。
  if (name === "search") drawTimeline();
  // 実物を見に行く画面なので、開くたびに走査し直す(消したり増えたりするのはserver側)。
  if (name === "clips") loadClipFiles();
  if (name === "marks") loadMarks();
  if (name === "groups") loadGroupOps();
  if (name === "bulk") loadBulk();
}

// ===== 検索 =====

// 語をどこから探すか。笑い声はここに居ない — 音が根拠で当たる語を持たないため、
// 検索対象として並べると「笑い声」と打ったときだけ出る隠しmodeになる。探し方
// (#flt-mode の laugh)が受け持つ。
function selectedSources() {
  const sources = [];
  if ($("src-stt").checked) sources.push("stt");
  if ($("src-comment").checked) sources.push("comment");
  return sources;
}

// 語を使わない探し方(#flt-mode)。語での検索(keyword / semantic)と違い、検索語も検索対象も
// 受け取らず、検出した窓をそのまま並べる。
const LAUGH_MODE = "laugh";

function scheduleSearch() {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => runSearch(true), SEARCH_DEBOUNCE_MS);
}

// 探し方によって「効く操作」が変わる。押せるまま残すと、効いていない指定が効いている
// ように見える(語の欄・検索対象・並替のいずれも、笑い声では判断材料にならない)。
function syncSearchControls(mode, query) {
  const byLaugh = mode === LAUGH_MODE;
  const bySemantic = mode === "semantic";
  const box = $("q");
  // 語の構文の説明はmarkupが唯一の出所。同じ文をここにも書くと、片方だけ直された説明が
  // hoverで出る。最初の1回だけ退避して、笑い声から戻ったときに書き戻す。
  if (box.dataset.help === undefined) box.dataset.help = box.title;
  box.disabled = byLaugh;
  box.title = byLaugh
    ? "笑い声は音そのものが根拠で、当たる語を持ちません。語で絞るには「語で一致」か「意味で近い」を選んでください。"
    : box.dataset.help;
  ["src-stt", "src-comment"].forEach((id) => {
    $(id).disabled = byLaugh;
    $(id).closest(".vd-chk").title = byLaugh
      ? "検索対象は語を探す先です。笑い声は語を持たないため、この指定は効きません。"
      : "";
  });
  // 確認の印は録画1本の属性。シーンが並んでいる間(語での検索・笑い声の一覧)は対象を持たない。
  const reviewFilter = $("flt-review");
  reviewFilter.disabled = Boolean(query) || byLaugh;
  reviewFilter.title = reviewFilter.disabled
    ? "確認状態の絞り込みは、検索語なしの録画一覧でだけ使えます。"
    : "確認状態で録画一覧を絞り込みます。";
  // 並替は探し方ごとに選択肢が違う。語の一致度(関連度順)は笑い声には無く、強さ・長さは
  // 語での検索には無く、録画1本ごとの値(笑い声の合計)はシーンの一覧には無い。同じ群を
  // 出しっぱなしにせず、その探し方の選択肢だけを出す。
  const byBrowse = !byLaugh && !query;
  $("order-field").classList.toggle("hidden", byLaugh || byBrowse);
  $("laugh-order-field").classList.toggle("hidden", !byLaugh);
  $("browse-order-field").classList.toggle("hidden", !byBrowse);
  // 意味検索はscore順で返る別endpointで、orderを載せる先が無い。押せるまま残すと、
  // pillは動くのに並びが変わらず「壊れている」と読まれる。
  $("flt-order").querySelectorAll(".seg-item").forEach((item) => {
    item.disabled = bySemantic;
    item.title = bySemantic
      ? "意味検索は「意味が近い順」で返るため、並べ替えは使えません。"
      : "";
  });
}

async function runSearch(reset) {
  const mode = $("flt-mode").value;
  const byLaugh = mode === LAUGH_MODE;
  // 笑い声は語で絞らない。欄に前の検索語が残っていても読まない(disableした入力を
  // 条件に混ぜると、見えている文字と結果が食い違う)。
  const query = byLaugh ? "" : $("q").value.trim();
  const sources = selectedSources();
  if (reset) {
    state.offset = 0;
    state.hits = [];
  }
  state.query = query;
  // labelは書き出しfile名になるので、検索語を黙って使わず欄へ書き込む(見えていれば直せる)。
  // 新しい検索のときだけ入れ替える — 続きの読み込みで、打ち直したlabelを奪わない。
  // 笑い声には名前にできる語が無いので、打ってあるlabelを空で上書きしない。
  const labelInput = $("clip-label");
  if (reset && !byLaugh && labelInput && document.activeElement !== labelInput) {
    labelInput.value = query;
  }
  syncSearchControls(mode, query);
  if (byLaugh) {
    await loadLaughs();
    return;
  }
  // 語が無いときは録画一覧を出す。ここで打ち切ると「当たる語を先に発明しないと
  // 1本も開けない」状態になり、文字起こしが無い録画は永久に開けなくなる。検索対象(音声/
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
    setListMessage($("hit-empty"), "検索対象（音声／コメント）を選んでください。");
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

  // 読み込み中を出す(loadLaughs/loadBrowseと同じ)。resetでstate.hitsを空にした後は
  // renderHitsを通らないため、これが無いと待つ間ずっと前の検索結果の行が並んだままになる。
  if (!state.hits.length) setListState($("hit-empty"), "loading");
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
  // 待っている間に探し方が変わっていたら、その結果を語検索で上書きしない(loadLaughs/
  // loadBrowseと同じ)。無いと、語検索の応答が笑い声一覧に混ざって並ぶ。
  if ($("flt-mode").value !== mode || state.query !== query) return;
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
  const note = data.mode === "semantic"
    ? "（意味が近い順）"
    : data.mode === "like"
      ? "（2文字以下のみのため全走査。3文字以上でindex検索になります）"
      : "";
  $("search-summary").textContent = `${fmtNum(data.total)}件 / 表示${fmtNum(state.hits.length)}件 ${note}`;
  // 空振りの理由は方式で違う。意味検索にANDは無いので、語の組み合わせを疑わせる文言を
  // 出すと、実際の原因(index未構築・埋め込みmodel未接続)へ辿り着けない。
  setListMessage($("hit-empty"), data.mode === "semantic"
    ? "近い意味の発話が見つかりません。indexが古い場合は上の「意味検索indexを更新」を実行してください。"
    : "該当するシーンがありません。複数語のANDは1つの発話・コメントの中で判定されます。");
  $("load-more").classList.toggle(
    "hidden", data.mode === "semantic" || state.hits.length >= state.total);
  renderHits();
}

// 音声から検出した笑い声の窓を、語で絞らずに並べる。行の形は検索hitと同じなので、
// 表もopenHit以下の再生経路もそのまま共有できる(録画一覧と同じ作法)。
// state.offsetは呼ぶ側(runSearch / さらに読み込む)が動かす。
async function loadLaughs() {
  state.browsing = false;
  const params = new URLSearchParams({
    order: $("flt-laugh-order").value,
    limit: String(PAGE_SIZE),
    offset: String(state.offset),
  });
  const streamer = $("flt-streamer").value;
  if (streamer) params.set("unique_ids", streamer);
  // 続きの読み込みでは出さない(表には既に行が並んでおり、その下に読み込み中が出るだけ)。
  if (!state.hits.length) setListState($("hit-empty"), "loading");
  let data;
  try {
    data = await apiSend("GET", `/api/search/laughs?${params.toString()}`);
  } catch (err) {
    state.hits = [];
    state.total = 0;
    renderHits();
    $("search-summary").textContent = "";
    setListState($("hit-empty"), "failed", err);
    return;
  }
  // 待っている間に探し方が変わっていたら、その結果を笑い声で上書きしない(loadBrowseと同じ)。
  if ($("flt-mode").value !== LAUGH_MODE) return;
  state.total = data.total;
  state.hits = state.hits.concat(data.items);
  $("search-summary").textContent =
    `${fmtNum(data.total)}件 / 表示${fmtNum(state.hits.length)}件 ${LAUGH_ORDER_NOTES[$("flt-laugh-order").value] || ""}`;
  // 0件の理由は「笑っていない」ではなく「まだ解析していない」ことがほとんどなので、
  // 対処(一括処理の笑い声分析)まで書く。ここで「該当なし」とだけ出すと、解析が要ることに
  // 辿り着けない。
  setListMessage($("hit-empty"),
    "笑い声が見つかりません。一括処理の「笑い声分析」を実行すると、解析した録画から並びます。");
  $("load-more").classList.toggle("hidden", state.hits.length >= state.total);
  renderHits();
}

// 並替の値 → 要約欄に添える語。何順で並んでいるかが表からは読めない(強さも長さも
// 同じ列に文字で出るため)。
const LAUGH_ORDER_NOTES = {
  time: "（配信が新しい順）",
  strength: "（強い順）",
  length: "（長い順）",
};

// snippetはServerが\x02..\x03で一致箇所を囲んで返す(囲みは重ならない=入れ子にならない)。
// HTMLを組み立てずDOMで包むことで、コメント本文中の記号がmarkupとして解釈されるのを防ぐ。
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
  sortBrowseRows(state.hits);
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
  const note = browseOrderNote();
  $("search-summary").textContent = total
    ? (want
      ? `${REVIEW_LABELS[want]} ${fmtNum(state.hits.length)}本 / 録画 ${fmtNum(total)}本${note}`
      : `録画 ${fmtNum(total)}本${note || "（検索語を入れるとシーンを探せます）"}`)
    : "";
}

// 録画一覧の並べ替え。serverへ引き直さないのは絞り込みと同じ理由(全録画の実体走査が
// 走る)で、並べる値は一覧と一緒に届いている。
function sortBrowseRows(rows) {
  if ($("flt-browse-order").value !== "laugh") return;
  // 未解析(null)は0ではない。0秒として混ぜると「笑いの無かった配信」と並んで見分けが
  // 付かなくなるので、値を持つ録画の後ろへまとめて落とす(笑い声一覧の強さ順と同じ扱い)。
  rows.sort((a, b) => {
    const x = typeof a.laugh_seconds === "number" ? a.laugh_seconds : -1;
    const y = typeof b.laugh_seconds === "number" ? b.laugh_seconds : -1;
    if (x !== y) return y - x;
    return (b.started_at || 0) - (a.started_at || 0);
  });
}

// 何順で並んでいるか、その並びで何本が値を持たないか。笑い声順は「解析していない録画が
// 末尾に溜まる」並びなので、その本数を出さないと「下の方は笑っていない配信」と読める。
function browseOrderNote() {
  if ($("flt-browse-order").value !== "laugh") return "";
  const pending = state.hits.filter((rec) => typeof rec.laugh_seconds !== "number").length;
  return pending
    ? `（笑い声が多い順・未解析 ${fmtNum(pending)}本は末尾）`
    : "（笑い声が多い順）";
}

// 実体の種別を名乗る語。録画の身元(``<stem>.mp4``)は名前でしかなく、finalizeはmp4を
// 作らない。名前だけを見せると「mp4というfileが在る」と読めてしまうので、実物が.tsなのか
// mp4なのかを併せて出す。
const MEDIA_BADGE_LABELS = { ts: "TS", mp4: "MP4" };

// 実体が1つも無い録画は行だけが残っている。開けないことは名乗る(文字起こし・検索・bookmarkは
// 残るので行自体は消さない)。
function mediaText(media) {
  if (!media || !media.length) return "実体なし（再生できません。文字起こし・検索・bookmarkは使えます）";
  return media.map((kind) => MEDIA_BADGE_LABELS[kind] || kind).join("・");
}

// ===== 確認状態(観たかどうかの印) =====

// 値はserverのRECORDING_REVIEW_STATESと一致させる。既定は未確認で、印は手で付けたときだけ
// 動く(再生や出力では動かさない)。
const REVIEW_LABELS = { unchecked: "未確認", checking: "確認中", checked: "確認済" };

function reviewStateOf(rec) {
  const value = rec && rec.review_state;
  return REVIEW_LABELS[value] ? value : "unchecked";
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
    // 印が元へ戻る動きは見えるが、戻った理由はどちらの欄も見ていない可能性がある。
    showError(err, "確認状態の変更");
  }
}

// 画面上の値を揃える。一覧の元dataと再生画面のsegmented controlは同じ録画の同じ印なので、
// 1箇所で書き換えて両方へ配る。
function applyReviewLocally(recordingId, next) {
  [state.browseAll, state.hits].forEach((list) => {
    const rec = list.find((row) => row.recording_id === recordingId);
    if (rec) rec.review_state = next;
  });
  if (state.current && state.current.recording_id === recordingId) {
    state.current.review_state = next;
    syncReviewControl(next);
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

// ===== 同じ配信の畳み込み =====
// 検索hitも見どころも切り出しも、1つの配信から何行も出る。行ごとに配信者と配信日を
// 繰り返すと、読みたい差分(位置・内容)が同じ文字列の柱に埋もれる。並びの上で同じ配信が
// 続く間は先頭行だけが名乗り、続く行は「〃」にする。「—」は値が無い印として既に使って
// いるので、同じ物の意味には使わない。
//
// 畳む単位はrecording_idだけにする。日付で畳むと同じ日の別配信が1つに見え、身元を
// 持たない行が並ぶと全部が同じ配信に化ける。
function recordingKeyOf(row) {
  const id = row ? row.recording_id : null;
  return id === undefined || id === null ? null : String(id);
}

// 直前の行と同じ配信か。隣り合ったときだけ畳むので、並びが配信ごとに固まっていない表
// (グループ内はposition順)でも、離れた同じ配信はそれぞれが名乗る。pickは行から
// 録画を持つ実体を取り出す(グループ操作の行は見どころ/切り出しを包んでいる)。
function continuesRecording(rows, index, pick) {
  if (index <= 0) return false;
  const keyAt = (i) => recordingKeyOf(pick ? pick(rows[i]) : rows[i]);
  const key = keyAt(index);
  return key !== null && key === keyAt(index - 1);
}

// 身元の欄(配信者・配信日)。続きの行では「〃」へ落とすが、行を単体で読むときに迷わない
// よう実際の値はtitleへ残す。
function identityCell(text, continued) {
  const span = document.createElement("span");
  if (!continued) {
    span.textContent = text;
    return span;
  }
  span.className = "vd-ditto";
  span.textContent = "〃";
  span.title = text;
  return span;
}

function browseRowCells(rec) {
  // 尺はserverが実測した値だけを出す。ended_at - started_atは壁時計で、捕捉の停滞ぶんも
  // 載る上、再処理でended_atが「今」に潰れた録画では数百時間に化ける。測っていなければ
  // それらしい数字を置かず「—」と出す。
  const length = rec.duration_seconds > 0 ? fmtDuration(rec.duration_seconds) : "—";
  return [rec.unique_id, fmtYmd(rec.started_at), length, laughText(rec)];
}

// 録画1本の笑い声。未解析は0秒ではないので「—」と出す ―― 0秒と同じ顔で並べると、
// 笑い声順の末尾が「笑わなかった配信」と「まだ数えていない配信」の混ざった塊になる。
function laughText(rec) {
  if (typeof rec.laugh_seconds !== "number") return "—";
  return fmtDuration(rec.laugh_seconds);
}

// 一覧の行が名乗らなくなった事実(file名・実体・中断・文字起こしの有無)。列を1つずつ立てると
// 身元3つを読むのに横が要るので、行そのもののhoverへまとめる。行は開く操作を持つので、
// 開く前に「開けるのか・語で検索に出るのか」をここで確かめられる。
function browseRowTitle(rec) {
  // 表示は身元から拡張子を落としたstem。`.mp4`を出すと、実体がmp4だと読めてしまう。
  const parts = [`${recName(rec)}（${mediaText(rec.media)}）`];
  // 中断録画も一覧に出す(素材は揃っていることがある)。ただし確定を跨げていないので、
  // 尺が未測定なことがある事実は行から読めるようにしておく。
  if (rec.status === "interrupted") {
    parts.push("中断: 確定処理を跨げなかった録画です（serverの再起動・crashなど）。素材は残っており再生できます。");
  }
  // 文字起こしが無い録画は語で検索しても当たらない。開く前に見分けられるようにしておく。
  if (!rec.has_transcript) {
    parts.push("文字起こしなし: まだ文字起こしされていないため、語での検索には出てきません。");
  }
  parts.push(laughTitle(rec));
  return parts.join("\n");
}

// 笑い声の欄が何を名乗っているか。秒だけを出すと、0秒が「笑わなかった」なのか「共演で
// 埋まっていた」なのか「まだ数えていない」なのか読めない。
function laughTitle(rec) {
  if (typeof rec.laugh_seconds !== "number") {
    return "笑い声: 未解析（一括処理の「笑い声分析」で数えられます）。";
  }
  const parts = [`笑い声: ${fmtDuration(rec.laugh_seconds)}（${fmtNum(rec.laugh_windows)}区間）`];
  if (!rec.laugh_exclude) {
    // 共演を外す前に張ったindex。行はそのまま残っているので、値は出るが意味が違う。
    parts.push("※コラボ・Battle中を外す前に数えた値です。一括処理の「笑い声分析」で数え直せます。");
  } else if (rec.laugh_exclude === "none") {
    parts.push("※共演中も数えた値です（設定 TICTOK_LAUGH_INDEX_EXCLUDE_COOP）。");
  } else if (!rec.laugh_collab_observed) {
    parts.push("※この配信はコラボ窓の記録が無い時期のため、コラボ中は外れていません。");
  } else if (rec.laugh_excluded_seconds) {
    const kinds = rec.laugh_exclude === "coop" ? "コラボ・Battle" : "コラボ";
    parts.push(`${kinds}中の ${fmtDuration(rec.laugh_excluded_seconds)} は数えていません。`);
  }
  return parts.join("\n");
}

// hitの出所を名乗る語。serverのsource名をそのまま画面語へ写す。三項演算子で2択に
// していたころに笑い声を足すと、笑いの行が「コメント」と名乗ってしまった。
const HIT_SOURCES = { stt: "音声", comment: "コメント", laugh: "笑い声" };

function renderHits() {
  // 種別(出所)と内容(本文)はhitの中身。1行=1録画の一覧では、種別は全行「録画」で
  // 内容はfile名しか無く、読む値を持たない列が2本増えるだけになる。
  $("hit-kind-th").classList.toggle("hidden", state.browsing);
  $("hit-body-th").classList.toggle("hidden", state.browsing);
  // 尺と笑い声は録画1本の値。検索hitの行に秒を出しても、その行を開くかどうかの判断には
  // 効かない(開いた先の見出しと時間軸がその秒を名乗る)ので、一覧では列を持たせない。
  $("hit-len-th").classList.toggle("hidden", !state.browsing);
  $("hit-laugh-th").classList.toggle("hidden", !state.browsing);
  // 一覧は身元と尺だけで横幅を使わないので、左列を中身幅へ詰める(CSS側)。
  document.querySelector(".vd-split").classList.toggle("vd-browse", state.browsing);
  renderTableRows(
    "hit-rows",
    "hit-empty",
    state.hits,
    (hit, rowNumber) => {
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
      // 語での検索は同じ録画の別のシーンが何行も続く。身元は塊の先頭だけが名乗る。
      const cont = continuesRecording(state.hits, rowNumber - 1);
      return [
        kind,
        identityCell(hit.unique_id, cont),
        identityCell(fmtYmd(hit.started_at), cont),
        body,
      ];
    },
    [],
    (tr, hit, index) => {
      if (!state.browsing && continuesRecording(state.hits, index)) tr.classList.add("vd-cont");
      tr.classList.add("vd-hit");
      tr.tabIndex = 0;
      // 一覧の行は列を持たない事実(file名・実体・中断・文字起こしの有無)をhoverで名乗る。
      if (state.browsing) {
        tr.title = browseRowTitle(hit);
        // 数値列(尺・笑い声)の右寄せ。renderTableRowsのnumericColsを使わないのは、
        // この表が探し方で列を出し入れするため — headerの列番号(隠し列を含む)とdataの
        // 列番号がずれ、値と見出しが別々の列で右寄せになる。
        [2, 3].forEach((col) => {
          if (tr.cells[col]) tr.cells[col].classList.add("num");
        });
      }
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
// 入れておけば、打ち直さずそのまま切り出し・見どころへ回せる。意味検索のhitは
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
    // 録画を読み込む(波形・文字起こし・コメントを全部取り直す)。同じ録画が一覧に居れば
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
    // 文字起こしの有無はloadTranscriptが確定させる。それまでは押せない状態にしておく。
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
    loadGifts(hit.recording_id);
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
    syncPkPanel();
  }
  video.play().catch(() => {});
  // スクショは範囲を要らない(今の1 frameが成果物)ので、IN/OUTの有無に関わらず押せる。
  ["add-mark", "do-still"].forEach((id) => ($(id).disabled = false));
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

// 素材版の呼び名。videos.htmlのsegmented control(clip-variant)のbutton文言と一致させる。
const VARIANT_LABELS = { source: "元録画", overlay: "焼き込み", upscaled: "Up出力" };

// 素材版は録画ごとに在り方が違う(焼き込み出力・Up出力は出したものにしか無い)。押せる状態で
// 並べると、選んでからserverに断られるまで「無い」ことが分からない。実在するものだけを
// 押せるようにし、無いものはその理由をtooltipに書く。
// 素材版の一覧を引けたか。引けていない状態を「その版が無い」と名乗ると、必ず在るはずの
// 元録画まで「ありません」と断定することになる。
let variantsKnown = false;

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
      : !variantsKnown
        ? "素材版の一覧を取得できませんでした（この版が無いという意味ではありません）。"
        : `この録画には${VARIANT_LABELS[kind]}がありません。${
            kind === "source"
              ? ""
              : "この版での再生はできませんが、切り出しは範囲だけを焼いて出せます（下の「処理」で全尺を作ることもできます）。"}`;
  });
}

// 実際に再生する版。切り出し素材の指定(clip-variant)は見どころtabと共有していて、
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
  state.variants = [];
  // 実在が確定するまでは全て伏せる。前の録画の在り方を引き継ぐと、無い版を押せる状態で
  // 出してしまう。
  state.variantKinds = [];
  variantsKnown = false;
  applyVariantAvailability();
  let data;
  try {
    data = await apiSend("GET", `/api/recordings/${recordingId}/path`);
    state.variants = data.variants || [];
  } catch (err) {
    $("player-status").textContent =
      `素材版の一覧を取得できませんでした（版が無いという意味ではありません）: ${err.message}`;
    showError(err, "素材版の取得");
    return;
  }
  variantsKnown = true;
  // 印の確定値。検索hit経由で開いた録画は一覧の値を持たないので、ここが唯一の出所になる。
  if (state.current && state.current.recording_id === recordingId) {
    state.current.review_state = reviewStateOf(data);
    syncReviewControl(reviewStateOf(data));
  }
  state.variantKinds = state.variants.filter((v) => v.exists).map((v) => v.kind);
  applyVariantAvailability();
}

async function loadHeat(recordingId) {
  try {
    const data = await apiSend("GET", `/api/recordings/${recordingId}/heat`);
    if (state.current && state.current.recording_id === recordingId) {
      state.heat = data.points || [];
      $("heat-note").textContent = "";
      drawTimeline();
    }
  } catch (err) {
    // nullは「まだ引けていない」、[]は「盛り上がりが無かった」。失敗を[]にすると、
    // 取得できなかった配信を「静かだった配信」として描くことになる。
    // 録画Aの失敗がその時点で開いている録画Bのheatを消さないよう照合する(成功path同様)。
    // 描画はnullも[]も「柱が1本も無い」同じ絵になるので、失敗はheat専用の欄に残す
    // (toastは消えるが、この欄は次に開き直すまで残る)。wave-noteは波形loaderの欄。
    if (state.current && state.current.recording_id === recordingId) {
      state.heat = null;
      drawTimeline();
      $("heat-note").textContent = "盛り上がりを取得できませんでした（0件という意味ではありません）。";
      showError(err, "盛り上がりの取得");
    }
  }
}

// ===== 文字起こしpanel =====
// 切り抜きの実体は「この発言のここからここまで」なので、文を選ぶとIN/OUTが決まる形にする。
// segmentのstart/endは文字起こし時にmedia軸へ再mapされており、そのままvideoの秒として使える。

async function loadTranscript(recordingId) {
  state.segments = [];
  state.segmentIndex = -1;
  state.segmentLive = false;
  state.selFrom = null;
  state.selTo = null;
  $("segments").innerHTML = "";
  // 前の録画の高さを引き継がない。中身が確定するまでは見出し1行に畳んでおき、
  // 文字起こしが無い録画ではそのまま畳んだまま(コメントが残り高さを全部取る)。
  $("transcript-block").classList.add("vd-block-collapsed");
  $("transcript-note").textContent = "読み込み中…";
  let data;
  try {
    data = await apiSend("GET", `/api/recordings/${recordingId}/transcript`);
  } catch (err) {
    if (state.current && state.current.recording_id === recordingId) {
      // 404だけが「まだ文字起こしされていない」。それ以外は取得失敗であって未処理ではないため、
      // 未処理と描いて再文字起こしを促すと、serverが落ちているだけの録画を文字起こしをやり直させてしまう。
      if (err.status === 404) {
        $("transcript-note").textContent = "この録画は未処理です。";
        // 未処理のときだけ押せる。既存transcriptの再文字起こしはbackendが受け付けない。
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
  $("transcript-block").classList.toggle(
    "vd-block-collapsed",
    state.segments.length === 0,
  );
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
    const text = result.added
      ? "文字起こしの順番待ちに入れました。終わり次第ここに反映されます。"
      : "文字起こしは既に順番待ちか処理済みです。";
    $("job-note").textContent = text;
    showToast(text, null, { title: "文字起こし", duration: JOB_TOAST_MS });
  } catch (err) {
    $("job-note").textContent = `文字起こし: ${err.message}`;
    showError(err, "文字起こし");
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
    const text = `${spec.label}を順番待ちに入れました。進み具合はJob画面に出ます。`;
    $("job-note").textContent = text;
    showToast(text, null, { title: spec.label, duration: JOB_TOAST_MS });
  } catch (err) {
    // 失敗するとbuttonが押せる状態へ戻るだけで、押していないのと同じ見た目になる。
    $("job-note").textContent = `${spec.label}: ${err.message}`;
    showError(err, spec.label);
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

// 再生位置を含む発話。文字起こしsegmentは開始順で重ならない(whisperの出力をそのまま持つ)ため、
// commentと同じく二分探索で引ける。3時間級の録画は1万文に届くので、timeupdate毎の線形走査は
// それだけで再生を鈍らせる。
// 発話と発話の間(無音)はどのsegmentにも入らない。実データでは無音が再生時間の3〜5割・
// 1録画あたり数百〜3000箇所に達する(whisperのword_timestampsでsegment端の水増しを
// 止めたため、無音が正直に隙間として残る)ので、そこで行の帯を消すと一文ごとに点滅する。
// 帯は直前の発話に残したまま、liveで「今まさに喋っている」かどうかだけを分ける。
function activeSegmentAt(now) {
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
  if (found < 0) return { index: -1, live: false };
  const segment = segments[found];
  return { index: found, live: now < (segment.end ?? segment.start) };
}

function highlightActiveSegment() {
  const container = $("segments");
  const rows = container.children;
  if (!rows.length) return;
  const { index: active, live } = activeSegmentAt($("video").currentTime);
  if (active === state.segmentIndex && live === state.segmentLive) return;
  // 変わった2行だけを塗り替える。全行をtoggleしていた頃は、行数ぶんのstyle書き換えが
  // timeupdate毎に走り、直後のscroll追従が読む位置がそのlayout再計算を待たされていた。
  const previous = rows[state.segmentIndex];
  if (previous) previous.classList.remove("vd-seg-active", "vd-seg-prev");
  state.segmentIndex = active;
  state.segmentLive = live;
  const row = rows[active];
  if (row) row.classList.add(live ? "vd-seg-active" : "vd-seg-prev");
  // 追従は既定ON。読み返している最中に勝手に飛ぶのが邪魔な場面もあるので切れるようにする。
  if (row && $("transcript-follow").checked) centerRowIn(container, row);
}

// 発話の途中で切れたclipは素材にならないので、手打ちのIN/OUTを最寄りの発話境界へ寄せる。
// 吸着先は文字起こしsegmentの境界と無音の縁の両方。無音の縁は文字起こしが無い録画でも波形さえ
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
    // 数分〜数十分待たされた末の失敗。buttonが押せる状態へ戻るだけだと、押していないのと
    // 同じ見た目になる。
    if (state.current && state.current.recording_id === recordingId) {
      $("chapter-note").textContent = err.message;
    }
    showError(err, "章立ての作成");
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
    // 押したbuttonは章立てblock側にあり、player-statusはそこから離れている。
    $("player-status").textContent = `章立てを取得できませんでした: ${err.message}`;
    showError(err, "章立てのcopy");
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
    // panelは空のまま残るので、生のerror文言だけだと成功時の「コメントがないか、検索
    // indexが未構築です。」と見分けにくい。loadTranscriptと同じ文型で0件と区別する。
    if (state.current && state.current.recording_id === recordingId) {
      $("comment-note").textContent =
        `コメントを取得できませんでした（0件という意味ではありません）: ${err.message}`;
    }
    return;
  }
  if (!state.current || state.current.recording_id !== recordingId) return;
  state.comments = data.items || [];
  $("comment-note").textContent = state.comments.length
    ? `${fmtNum(state.comments.length)}件`
    // 「0件」と「未index」はsearch_hits上で区別が付かない(空indexは行を残さない)ので、
    // 断定せずどちらもあり得る文言にする。
    : "コメントがないか、検索indexが未構築です。";
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

// ===== PK・ギフトpanel =====
// 切り所の材料は「何を喋ったか」だけではない。どのPKで誰が何を投げたかは、これまで全尺barの
// iconでしか読めず、送り主も金額もhoverしないと判らなかった。ギフトもスコアもこの録画の秒に
// 載っている(serverが同じmapperを通す)ので、行はclickでその瞬間へ飛べる。
//
// 出すのは**再生位置が入っているPK 1戦だけ**にする。全戦を縦に積んでいた頃は、PKの外を
// 観ている間も全戦の見出しと曲線が並び、今どの戦のスコアを読めばいいのかを目で探すことに
// なった。スコアは曲線ではなくバー1本で出す(推移そのものより「今どちらが勝っているか」が
// 要る)。ギフトはその戦の窓に飛んだ分だけで、PKの外では両方とも空になる。

// 今出しているもの。同じ物を映している間はDOMを作り直さない — 毎tick作り直すと、
// ギフト欄のscroll位置と選択が飛ぶ。keyは「今の戦」または「PK外で案内している行き先」。
let pkPanelKey = null;
// ギフト欄の行と、その元(state.gifts上のindexも持つ。seekと二分探索に使う)。持つのは
// 今の戦の窓に飛んだ分だけなので、state.giftsとは並びも件数も違う。行は全部作っておき、
// DOMへ入れるのは再生位置まで届いた分(pkGiftShown件)だけ ―― 観ている時と同じ順で下へ
// 積んでいく。
let pkGiftRows = [];
let pkGiftItems = [];
let pkGiftShown = 0;
// 件数・コインの見出しと、1件目が出るまでの名乗り。行の増減に合わせて書き換える。
let pkGiftHead = null;
let pkGiftEmpty = null;
// 再生位置で値が変わる所(スコアバーとリード差)。同じ戦の中ではここだけを書き換える。
let pkLiveNodes = null;

function buildGiftRow(gift, index) {
  const row = document.createElement("div");
  row.className = "vd-gift";
  row.dataset.index = String(index);
  const time = document.createElement("span");
  time.className = "vd-seg-t";
  time.textContent = fmtDuration(gift.t);
  const who = document.createElement("span");
  who.className = "vd-who vd-gift-who";
  who.textContent = gift.nickname || gift.uid || "";
  const name = document.createElement("span");
  name.className = "vd-gift-name";
  name.textContent = gift.count > 1 ? `${gift.name}×${fmtNum(gift.count)}` : gift.name;
  const diamonds = document.createElement("span");
  diamonds.className = "vd-gift-dia";
  diamonds.textContent = fmtNum(gift.diamonds);
  row.append(time);
  // iconを出せるgiftだけ絵を添える。出せないgiftに別の絵を当てると、実際には飛んで
  // いないgiftが飛んだように読める(全尺barのiconと同じ約束)。
  const url = state.giftIcons[String(gift.gift_id)];
  if (url) {
    const icon = document.createElement("img");
    icon.className = "vd-gift-icon";
    icon.src = url;
    icon.alt = "";
    icon.loading = "lazy";
    row.appendChild(icon);
  }
  row.append(who, name, diamonds);
  row.title = `${gift.nickname || gift.uid || ""}：${gift.name}×${fmtNum(gift.count)}`
    + `（${fmtNum(gift.diamonds)}コイン）`;
  return row;
}

// 再生位置が入っているPK。窓は重ならない(serverが次の戦の開始で閉じる)ので最初の1つで
// 決まる。戦数は多くて数十なので、二分探索にはしない。
function battleAtTime(now) {
  return (state.battles || []).find(
    (battle) => now >= battle.start && now <= battle.end) || null;
}

// 再生位置以前で最後のscore sample。seriesは時刻順で、窓の頭(battle.start)が最初の点
// なので、窓の中に居る限り必ず1つ見つかる。1点も無いのは推移の記録が録画の窓に掛から
// なかった戦だけで、その時はnull(最終スコアで代替し、その旨を欄に書く)。
function battleSampleAt(battle, now) {
  const series = battle.series || [];
  let low = 0;
  let high = series.length - 1;
  let found = null;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (series[mid].t <= now) {
      found = series[mid];
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  return found;
}

// 再生位置でのスコアバー。分割は履歴画面・動画焼き込みと同じ(1v1=2、個人マルチ=人数、
// チーム戦=チーム数)ので、common.jsの組み立てをそのまま使う。
function buildPkScoreBar(battle, sample) {
  const names = new Map((battle.participants || []).map(
    (part) => [part.user_id, part.nickname || part.unique_id || ""]));
  // sampleのpartsがその時刻の陣営別score。partsを持たない古い記録では陣営に割れないので
  // participantsを渡さず、own/oppの2分割に落とす(common.jsのbattleParticipantsの経路)。
  // 確定scoreで埋めることはしない — 終わった後の値を再生位置の値として見せることになる。
  const parts = ((sample && sample.parts) || []).map((part) => ({
    user_id: part.user_id,
    nickname: names.get(part.user_id) || "",
    is_own: part.side === "own",
    side: part.side,
    team_id: part.team_id,
    score: part.score,
  }));
  const view = {
    type: battle.type,
    participants: parts,
    own_score: sample ? sample.own : battle.own_score,
    opp_score: sample ? sample.opp : battle.opp_score,
    // 名前だけのopponentsはbattleParticipantsが参加者objectとして読むので渡さない。
    opponents: [],
  };
  return buildBattleScoreBar(battleTopology(view));
}

// PK外の案内。次のPKが無ければ直前のPKを指す(戻って見返す口が無いと、終わったPKへは
// 全尺barから探し直すことになる)。
function pkOutsideTarget(now) {
  const battles = state.battles || [];
  return battles.find((battle) => battle.start > now)
    || [...battles].reverse().find((battle) => battle.end < now)
    || null;
}

function buildPkOutside(now) {
  const box = document.createElement("div");
  box.className = "vd-pk-empty";
  if (!(state.battles || []).length) {
    box.textContent = "この録画にPKはありません";
    return box;
  }
  const label = document.createElement("div");
  label.textContent = "PK中ではありません";
  box.appendChild(label);
  const target = pkOutsideTarget(now);
  if (target) {
    const button = document.createElement("button");
    button.className = "btn btn-small";
    button.type = "button";
    const forward = target.start > now;
    button.textContent =
      `${forward ? "次" : "直前"}のPK ${target.ordinal}戦目 ${fmtDuration(target.start)} へ`;
    button.addEventListener("click", () => { $("video").currentTime = target.start; });
    box.appendChild(button);
  }
  return box;
}

// PK欄。高さは固定で、中身がPK・PK外のどちらでも変わらない。
function renderPkNow(battle, now) {
  const box = $("pk-now");
  box.innerHTML = "";
  pkLiveNodes = null;
  if (!battle) {
    box.appendChild(buildPkOutside(now));
    return;
  }
  const head = document.createElement("div");
  head.className = "vd-pk-now-head";
  const time = document.createElement("span");
  time.className = "vd-seg-t";
  time.textContent = fmtDuration(battle.start);
  const name = document.createElement("span");
  name.className = "vd-pk-name";
  name.textContent = `PK ${battle.ordinal}戦目`;
  const meta = battleResultMeta(battle.result);
  const result = document.createElement("span");
  // 不成立(aborted)は勝敗ではない。WIN/LOSEの枠で「—」を出すと、判定できなかった戦と
  // 見分けが付かないので言葉で名乗る。
  result.className = battle.aborted || battle.ongoing ? "vd-summary" : `res ${meta.cls}`;
  result.textContent = battle.aborted ? "不成立" : (battle.ongoing ? "進行中" : meta.text);
  head.append(time, name, result);
  if (battle.partial) {
    // 録画を跨いだPK。この録画には片側しか映っていないことを名乗らないと、途中から
    // 始まるスコアがそのPKの全体に見える。
    const partial = document.createElement("span");
    partial.className = "vd-pk-partial";
    partial.textContent = "一部のみ";
    partial.title = "このPKはこの録画に一部だけ入っています。";
    head.appendChild(partial);
  }
  const gap = document.createElement("span");
  gap.className = "vd-pk-gap";
  head.appendChild(gap);
  head.title = "clickでこのPKの頭へ移動";
  const body = document.createElement("div");
  body.className = "vd-pk-now-body";
  const barHost = document.createElement("div");
  barHost.className = "vd-pk-bar";
  const foot = document.createElement("div");
  foot.className = "vd-pk-foot";
  const opponents = (battle.opponents || []).filter(Boolean).join("・");
  // 形式(1v1 / Nコラ / NvM)は参加者の並びから決まる。参加者を持たない古い記録は人数を
  // 名乗れないので、判っている所(個人戦かチーム戦か)までにする。opponentsは名前の列で
  // 参加者objectではないので、battleModeLabelには渡さない(人数を誤って数える)。
  const parts = battle.participants || [];
  const mode = parts.length
    ? battleModeLabel({ type: battle.type, participants: parts })
    : (battle.type === "team" ? "チーム戦" : "個人戦");
  foot.textContent = `${mode}`
    + `${opponents ? ` / 相手: ${opponents}` : ""}`
    + ` / 尺 ${fmtDuration(Math.max(0, battle.end - battle.start))}`
    // 推移の記録がこの録画の窓に1点も無い戦。バーが動かない理由を名乗らないと、
    // 最後の値が再生位置の値に見える。
    + ((battle.series || []).length ? "" : " / 推移の記録なし（最終スコア）");
  foot.title = foot.textContent;
  body.append(barHost, foot);
  box.append(head, body);
  pkLiveNodes = { battle, barHost, gap, sample: undefined };
}

// 再生位置で変わる所だけを書き換える。timeupdateは毎秒4回来るので、値が動いていない
// 間(同じsampleの間)は何もしない。
function paintPkLive() {
  if (!pkLiveNodes) return;
  const battle = pkLiveNodes.battle;
  const sample = battleSampleAt(battle, $("video").currentTime);
  if (sample === pkLiveNodes.sample) return;
  pkLiveNodes.sample = sample;
  pkLiveNodes.barHost.replaceChildren(buildPkScoreBar(battle, sample));
  const own = sample ? sample.own : battle.own_score;
  // opp(敵陣)は個人マルチでも最上位1陣の値。勝敗の判定と同じ相手で差を出す。
  const opp = sample ? sample.opp : battle.opp_score;
  const gap = own - opp;
  pkLiveNodes.gap.textContent =
    gap === 0 ? "互角" : (gap > 0 ? `+${fmtNum(gap)} リード` : `${fmtNum(gap)} ビハインド`);
  pkLiveNodes.gap.title = gap === 0 ? "自陣と敵陣が同点です。"
    : `自陣と敵陣（最上位）の差です。`;
}

// ギフト欄。出すのはこの戦の窓に飛んだ味方陣のギフトだけ(相手陣のコインは相手Roomの
// listenerが拾ってスコアに入るが、1件ずつのeventは持たない)。
function renderPkGifts(battle) {
  const head = $("pk-gift-head");
  const list = $("pk-gift-list");
  head.innerHTML = "";
  list.innerHTML = "";
  pkGiftRows = [];
  pkGiftItems = [];
  pkGiftShown = 0;
  pkGiftHead = null;
  pkGiftEmpty = null;
  state.giftIndex = -1;
  if (!battle) {
    head.textContent = "ギフト";
    const empty = document.createElement("div");
    empty.className = "vd-pk-empty";
    empty.textContent = "—";
    list.appendChild(empty);
    return;
  }
  state.gifts.forEach((gift, index) => {
    // 帰属はserverが貢献集計と同じ窓で決めている(画面とBattle cardで同じgiftが別のPKへ
    // 数えられないようにするため)。ここで時刻から引き直さない。
    if (gift.battle === battle.ordinal) pkGiftItems.push({ gift, index });
  });
  const count = document.createElement("span");
  const coin = document.createElement("span");
  coin.className = "vd-pk-coin";
  head.append(count, coin);
  head.title = "この配信者の枠へ飛んだギフトです（相手の枠のギフトは含みません）。"
    + "「ここまで / この戦の合計」で数えています。";
  // 行は先に全部作っておき、DOMへは再生位置まで届いた分だけを入れる(下のsyncPkGiftFeed)。
  // 作るのを都度にすると、巻き戻しのたびに同じ行を作り直すことになる。
  pkGiftItems.forEach((item) => pkGiftRows.push(buildGiftRow(item.gift, item.index)));
  pkGiftHead = {
    count,
    coin,
    // その戦の合計。行が増えていく間、あと何件・いくら来るのかがこれで読める。
    totalCoins: pkGiftItems.reduce((sum, item) => sum + item.gift.diamonds, 0),
  };
  paintPkGiftHead(0);
  const empty = document.createElement("div");
  empty.className = "vd-pk-empty";
  // 「この戦には無い」と「まだ来ていない」は別の話。0件の戦でだけ前者を出す。
  empty.textContent = pkGiftItems.length
    ? "この時点ではまだ飛んでいません"
    : "この戦に飛んだギフトはありません";
  list.appendChild(empty);
  pkGiftEmpty = empty;
}

// 再生位置まで届いたギフトを下へ積んでいく。配信を観ている時と同じ順で流れ、
// 追従ONなら常に最新の行が見えるよう下端に貼り付く。
// 先の分まで並べてしまうと、まだ飛んでいないギフトが今の盛り上がりとして読める。
function syncPkGiftFeed() {
  if (!pkGiftRows.length) return;
  const list = $("pk-gift-list");
  const index = activeGiftIndex($("video").currentTime);
  const want = index + 1;
  if (want === pkGiftShown) {
    // 位置が動いても行が増えていない間は触らない(timeupdateは毎秒4回来る)。
    stickPkGiftsToBottom();
    return;
  }
  // 巻き戻し。先の行を残すと、まだ観ていない時間のギフトが並んだままになる。
  while (pkGiftShown > want) {
    list.removeChild(list.lastChild);
    pkGiftShown -= 1;
  }
  if (want > pkGiftShown) {
    const fragment = document.createDocumentFragment();
    for (let i = pkGiftShown; i < want; i += 1) fragment.appendChild(pkGiftRows[i]);
    list.appendChild(fragment);
    pkGiftShown = want;
  }
  // 空の名乗りは1件目が出るまで。行が入ったら外し、巻き戻して0件へ戻れば戻す。
  if (pkGiftEmpty) {
    const show = pkGiftShown === 0;
    if (show !== (pkGiftEmpty.parentNode === list)) {
      if (show) list.insertBefore(pkGiftEmpty, list.firstChild);
      else list.removeChild(pkGiftEmpty);
    }
  }
  const previous = pkGiftRows[state.giftIndex];
  if (previous) previous.classList.remove("vd-gift-active");
  state.giftIndex = index;
  const row = pkGiftRows[index];
  if (row) row.classList.add("vd-gift-active");
  paintPkGiftHead(want);
  stickPkGiftsToBottom();
}

// 見出しは「ここまで / この戦の合計」。合計を落とすと、あと何件来るのかが読めない。
function paintPkGiftHead(shown) {
  if (!pkGiftHead) return;
  const coins = pkGiftItems.slice(0, shown)
    .reduce((sum, item) => sum + item.gift.diamonds, 0);
  pkGiftHead.count.textContent =
    `味方へのギフト ${fmtNum(shown)} / ${fmtNum(pkGiftItems.length)}件`;
  pkGiftHead.coin.textContent =
    `${fmtNum(coins)} / ${fmtNum(pkGiftHead.totalCoins)} コイン`;
}

// 追従ONの間は下端に貼り付ける。積み上がる一覧では「今の行」は常に一番下で、
// 中央へ寄せると最新の行の下に空白が出る。
function stickPkGiftsToBottom() {
  if (!$("pk-follow").checked) return;
  const list = $("pk-gift-list");
  list.scrollTop = list.scrollHeight;
}

// 今出す物が変わったときだけ作り直す。forceは録画の切り替え(中身ごと入れ替わる)。
function renderPkPanel(force) {
  const now = $("video").currentTime;
  const battle = battleAtTime(now);
  const target = battle ? null : pkOutsideTarget(now);
  const key = battle ? `b${battle.ordinal}` : `o${target ? target.ordinal : ""}`;
  if (force || key !== pkPanelKey) {
    pkPanelKey = key;
    renderPkNow(battle, now);
    renderPkGifts(battle);
  }
  paintPkLive();
  syncPkGiftFeed();
}

function syncPkPanel() {
  renderPkPanel(false);
}

// 再生位置以前で最後のgift(ギフト欄に出ている分の中)。長時間配信は数千件になるので
// 二分探索で引く(コメントと同じ)。
function activeGiftIndex(now) {
  let low = 0;
  let high = pkGiftItems.length - 1;
  let found = -1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (pkGiftItems[mid].gift.t <= now) {
      found = mid;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  return found;
}

// ===== 見どころ(bookmark) =====
// cut listが「書き出す素材」なのに対し、こちらは「後でまた見たい場所」。点でも範囲でも
// 残せて、seek bar上のmarkerとして常に見えることで、同じ録画を開き直した時に辿り着ける。

// 先に空にするのは録画を跨ぐため(前の録画のmarkerを新しい録画のbarに残さない)。その代わり
// 失敗すると「見どころが1件も無い録画」に見えるので、失敗は必ず名乗る — 記録に成功した
// 直後の引き直しが落ちると、今入れた見どころが目の前で消えたように見える。
async function loadBookmarks(recordingId) {
  state.bookmarks = [];
  drawTimeline();
  syncCommentMarks();
  let data;
  try {
    data = await apiSend("GET", `/api/bookmarks?recording_id=${recordingId}`);
  } catch (err) {
    // 別の録画へ移った後に古い失敗が届くことがある。今開いている録画の欄を潰さない。
    if (state.current && state.current.recording_id === recordingId) {
      $("player-status").textContent =
        `見どころを取得できませんでした（0件という意味ではありません）: ${err.message}`;
    }
    showError(err, "見どころの取得");
    return;
  }
  if (!state.current || state.current.recording_id !== recordingId) return;
  state.bookmarks = data.items || [];
  drawTimeline();
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
  // 尺のある行はそのまま書き出しの素材になる。同じ範囲を二度足すと、一括書き出しで
  // 同じmp4が2本出るまで重複に気付けない。
  if (end !== null && end !== undefined) {
    const twin = existingMarkFor(state.current.recording_id, start, end);
    if (twin) {
      const dup = `この範囲は既に見どころ（${groupNameOf(twin.group_id) || "未分類"}）にあります。`;
      $("player-status").textContent = dup;
      showToast(dup, "error", { title: "見どころの記録" });
      syncAddMarkButton();
      return;
    }
  }
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
    showError(err, "見どころの記録");
    return;
  }
  // どこへ入ったかまで出す。M keyは記録先を選んだ操作から離れて押されるので、時刻だけだと
  // 「入ったが行き先が違う」に気付けない。
  const where = end === null
    ? fmtDuration(start)
    : `${fmtDuration(start)} - ${fmtDuration(end)}`;
  const message = end === null
    ? `見どころに記録しました（点 ${where} → ${groupNameOf(groupId) || "未分類"}）`
    : `見どころに記録しました（${where} → ${groupNameOf(groupId) || "未分類"}・mp4にできます）`;
  $("player-status").textContent = message;
  showToast(message);
  flashBookmark(start, end);
  await loadBookmarks(state.current.recording_id);
  // 一覧はこの行を素材として数える。手元のlistを更新しないと、同じ範囲をもう一度足せる
  // (二重登録の関門がstate.marksだけを見ているため)。
  await loadMarks();
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
    showError(err, "コメントからの見どころ操作");
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
// 印であり、同時に切り出しの素材でもある1つの表。尺(end)を持つ行だけがmp4にでき、
// 点は「後でまた見たい場所」として残る。以前は同じ範囲を見どころと切り出しリストの
// 2つの表・2つのtabで持ち、範囲付きの見どころを「昇格」させて写していたが、写した先で
// 範囲もグループもラベルも変わらなかった(実データ21件中20件が完全一致)ので畳んだ。

async function loadMarks() {
  const failure = await refreshGroupData();
  // placeholderの文字はここで決める(hiddenの制御は後のrenderTableRowsが行数で行うので、
  // 描画の前に置く)。初回の取得に失敗すると手元のlistは空のままで、そこへ「まだありません。」
  // を出すと取得できなかったことが0件として提示される。2回目以降は前回のlistが残る。
  if (failure && !(state.marks || []).length) {
    setListState($("mark-empty"), "failed", new Error(failure));
  } else if (!failure) {
    setListState($("mark-empty"), "empty");
  }
  renderGroupViews();
  // renderGroupViewsの後に書く。marks-summaryは件数欄で、renderMarksViewが必ず上書き
  // するため、先に書くと同じtickで失敗の痕跡が消えて「前回のdata＋辻褄の合った件数」だけ
  // が残る(refreshGroupDataは意図的に手元のlistを捨てないので、表は前回のまま)。
  if (failure) {
    $("marks-status").textContent = failure;
    showToast(failure, "error", { title: "見どころの取得" });
  }
}

// 尺のある行だけがmp4にできる。判定はこの1箇所で行う。
function isRanged(mark) {
  return mark.end !== null && mark.end !== undefined;
}

// shortの自動生成が書き戻した行。人が付けた印と混ぜて並べると、覚えの無い行が一覧を
// 埋めるので既定では出さない(消えているのではなく隠れているだけ)。
function isAutoMark(mark) {
  return mark.origin === "auto";
}

// グループ選択と「自動生成も出す」を掛けた表示対象。グループを選んでいる間はposition順
// (=書き出し順)で並べる。選んでいない間(「全て」「未分類」)は配信日順にする — そこに
// 並ぶのは書き出し順を持たない行なので、並べる根拠になるのは素材そのものの時間軸しかない。
// 配信者ごとに固めると、同じ日の別配信者がlistの端と端へ離れ、「いつの配信を触っているか」
// が読めなくなる。同じ配信の中は開始位置順で、隣り合った同じ配信は「〃」に畳まれる。
function visibleMarks() {
  const rows = (state.marks || []).filter((mark) => matchesGroup(mark, state.groupSel)
    && (state.showAuto || !isAutoMark(mark)));
  if (!isGroupSelected()) {
    return rows.sort(
      (a, b) =>
        (a.recording_started_at ?? 0) - (b.recording_started_at ?? 0) ||
        a.recording_id - b.recording_id ||
        a.start - b.start ||
        a.id - b.id,
    );
  }
  return rows.sort(
    (a, b) =>
      (a.position === null || a.position === undefined)
        - (b.position === null || b.position === undefined) ||
      (a.position ?? 0) - (b.position ?? 0) ||
      a.start - b.start ||
      a.id - b.id,
  );
}

// 書き出し・連結が実際に流す対象。行を選んでいればその選択、1件も選んでいなければ表示中の
// 全件で、いずれも**尺のある行だけ**を採る。点はmp4にできないので、混ぜると件数だけが
// 合わない結果になる(scopeがその内訳を名乗る)。
// 選択は描画のたび表示中のidへ絞られる(renderMarks)ので、ここは表示順のまま拾えばよい。
function targetMarks() {
  const rows = visibleMarks();
  const picked = rows.filter((mark) => state.marksSelected.has(mark.id));
  // 先に「どの行が対象か」を決め、その後で尺の有無を見る。順序が逆だと、点だけを選んだ
  // ときに選択が空と見なされ、表示中の全件が黙って書き出される。
  return (picked.length ? picked : rows).filter(isRanged);
}

function hasMarkSelection() {
  return visibleMarks().some((mark) => state.marksSelected.has(mark.id));
}

function renderMarksView() {
  // グループtabはupdateMarksSelection()から選択件数込みで描き直す。
  renderMarksHead();
  renderMarks();
  updateMarksSummary();
}

function bindGroupMemo(inputId, statusId) {
  const memo = $(inputId);
  if (!memo) return;
  memo.addEventListener("change", async () => {
    const groupId = Number(memo.dataset.groupId || 0);
    if (!groupId) return;
    try {
      await apiSend("PATCH", `/api/groups/${groupId}`, { memo: memo.value.trim() });
      showToast("メモを保存しました。", null, { title: "グループのメモ" });
    } catch (err) {
      $(statusId).textContent = err.message;
      showError(err, "グループのメモ保存");
    }
    await refreshGroupData();
    renderGroupViews();
  });
}

// 表の名乗りと、書き出し・連結・作品が効く範囲。見出し帯を廃したので、今どのグループの
// 何を並べているかはこの1行が持つ(棚の反転だけでは、表の側から読めない)。
function renderMarksHead() {
  const grouped = isGroupSelected();
  const group = selectedGroup();
  const rows = visibleMarks();
  const ranged = rows.filter(isRanged);
  // 対象は「選択があれば選択・無ければ表示中の全件」で切り替わるので、どちらで走るかを
  // 押す前にこの1行で読み取れるようにする(件数まで出す — 「選択中」とだけ出しても、
  // 選んだつもりの件数と合っているかはここで確かめられない)。
  // 点は対象に入らない。黙って落とすと、表の件数と書き出される本数が食い違う。
  const selected = rows.filter((mark) => state.marksSelected.has(mark.id));
  const scope = selected.length ? selected : rows;
  const picked = targetMarks();
  const points = scope.length - picked.length;
  const excluded = points ? `／点 ${fmtNum(points)}件は対象外` : "";
  $("cuts-scope").textContent = hasMarkSelection()
    ? `対象: 選択中の${fmtNum(picked.length)}件（${groupScopeLabel(state.groupSel)}${excluded}）`
    : `対象: ${groupScopeLabel(state.groupSel)}の${fmtNum(picked.length)}件${excluded}`;
  $("marks-list-title").textContent = group
    ? `■ ${group.name} ／ 見どころ（書き出し順）`
    : "■ 見どころ";
  const exportButton = $("cuts-export");
  exportButton.disabled = picked.length === 0;
  // 「1本に繋ぐ」順序はpositionで、それが定まるのはグループを選んでいるときだけ
  // (「全て」「未分類」では順の列も出ない)。押せるまま残すと、順序を確認できない
  // まま数十分の連結jobが走り、出来上がってから気付くことになる。
  const reel = $("cuts-reel");
  reel.disabled = !grouped || picked.length === 0;
  reel.title = grouped
    ? "表示順（書き出し順）のまま1本のmp4へ繋ぎます。行を選んでいれば選択した分だけを、その表示順で繋ぎます。尺の無い行は対象に入りません。"
    : "グループを選ぶと書き出し順が定まります。「全て」「未分類」では順序が決まりません。";
  // 作品はグループ1件が単位で、行の選択には従わない。同じ帯に並ぶ「1本に連結」は選択に
  // 従うので、その違いはtitleで名乗る(押してから気付く形にしない)。
  // 型(作り方)が1つも無ければ作品は作れないので、そちらの可否も併せて見る — ここで
  // グループの有無だけを見ると、型の読み込みが立てた無効化をこの再描画が毎回消してしまう。
  const work = $("cuts-work");
  work.disabled = !grouped || ranged.length === 0 || !workPresetsReady;
  work.title = !workPresetsKnown
    ? "作品の型を取得できませんでした（型が無いという意味ではありません）。"
    : !workPresetsReady
      ? "作品の型がありません。設定画面の「shortの型」で作成してください。"
      : grouped
        ? `「${group.name}」の尺のある${fmtNum(ranged.length)}件を、テロップを焼いて間を詰めた1本の作品にします`
          + "（行の選択には従いません）。連結と違い全編を焼き直すので時間がかかります。"
        : "グループを選んでください。作品はグループ1件が単位です。";
}

function updateMarksSummary() {
  const rows = visibleMarks();
  const ranged = rows.filter(isRanged);
  const total = ranged.reduce((sum, mark) => sum + (mark.end - mark.start), 0);
  // グループを選んでいる間の合計尺は、そのまま切り抜き1本の完成尺になる。
  $("marks-summary").textContent = rows.length
    ? `${fmtNum(rows.length)}件（尺あり ${fmtNum(ranged.length)}・点 ${fmtNum(rows.length - ranged.length)}）`
      + ` / ${isGroupSelected() ? "完成尺" : "合計"} ${fmtDuration(total)}`
    : "";
}

// 選択状況の表示と、選択で決まるbuttonの活性。
function updateMarksSelection() {
  const rows = visibleMarks();
  const count = state.marksSelected.size;
  $("marks-selected").textContent = count ? `選択 ${fmtNum(count)}件` : "";
  $("marks-bulk-delete").disabled = !count;
  const extras = extraMarksInView().length;
  const dup = $("cuts-dup-select");
  dup.disabled = !extras;
  dup.title = extras
    ? `表示中に同じ範囲の余りが${fmtNum(extras)}件あります。各組の先頭を残して余りだけを選びます`
      + "（削除は「選択を削除」で行います）。"
    : "同じグループの中に同じ範囲が2行在る状態はありません"
      + "（グループを跨いだ複製は意図した操作なので対象にしません）。";
  $("marks-select-all").checked = rows.length > 0 && count === rows.length;
  renderGroupBar("marks-groups", "marks");
  // 選択は書き出し・連結の対象そのものなので、見出しの「対象:」も一緒に描き直す
  // (選択を変えても対象の表示が前のままだと、押す直前に読んだ範囲と実際が食い違う)。
  renderMarksHead();
}

// 同じ録画の同じ範囲を指す行の束。鍵は**表に出ている値**で作る — 表示が同じ2行こそが、
// 行だけを読んでも見分けの付かない行そのものである。数えるのはlist全体で、表示中の
// グループに限らない(別のグループへ入っていても、書き出せば同じmp4が2本出る)。
function markRangeKey(mark) {
  return `${mark.recording_id}:${fmtCutTime(mark.start)}:${fmtCutTime(mark.end)}`;
}

function markRangeTwins() {
  const twins = new Map();
  (state.marks || []).filter(isRanged).forEach((mark) => {
    const key = markRangeKey(mark);
    if (!twins.has(key)) twins.set(key, []);
    twins.get(key).push(mark);
  });
  return twins;
}

// 表示中の行から拾う「消してよい余り」。印(重複n)はlist全体・範囲だけで数えるが、消す側は
// **同じグループの中の同じ範囲**しか対象にしない: グループ間の複製は意図した操作(グループ
// ごとにIN/OUTを詰めるために行ごと複製する)で、片割れを消すと人が組んだ棚が崩れる。
// 同じ棚に同じ範囲が2行在る状態だけが、書き出せば同じmp4が2本出る余りである。
// 各組の先頭(表示順で最初の1件)は残す — 消すのは余りであって、場面そのものではない。
function extraMarksInView() {
  const seen = new Set();
  const extras = [];
  visibleMarks().filter(isRanged).forEach((mark) => {
    const key = `${mark.group_id === null || mark.group_id === undefined ? "none" : mark.group_id}`
      + `:${markRangeKey(mark)}`;
    if (seen.has(key)) extras.push(mark);
    else seen.add(key);
  });
  return extras;
}

// 重複の余りを選ぶだけで、消しはしない。どちらを残すかは中身を観て決める物なので、
// 選んだ状態で一度手を止められるようにする(削除は「選択を削除」が確認を取って行う)。
function selectExtraMarks() {
  const extras = extraMarksInView();
  if (!extras.length) return;
  state.marksSelected = new Set(extras.map((mark) => mark.id));
  state.lastPick.marks = null;
  $("marks-status").textContent =
    `同じ範囲の余り${fmtNum(extras.length)}件を選びました（各組の先頭は残しています）。`
    + "中身を確かめてから「選択を削除」を押してください。";
  renderMarks();
}

// 位置・尺の欄が受ける刻み。↑↓で秒を動かす — 1秒詰めるのに `1:23:45.6` を打ち直させない。
const TIME_NUDGE_SECONDS = 0.1;
const TIME_NUDGE_SHIFT_SECONDS = 1;
const TIME_NUDGE_ALT_SECONDS = 10;

// 時刻欄の入力を秒へ。先頭に符号があれば「今の値からの増減」として読む。絶対時刻しか
// 受けないと、2秒後ろへ動かすのにも終端の絶対時刻を数えて打ち直すことになる。
// 戻り値は秒、読めなければ null。
function parseTimeInput(text, current) {
  const raw = String(text).trim();
  const signed = /^[+-]/.test(raw);
  const seconds = parseTimeText(signed ? raw.slice(1) : raw);
  if (seconds === null) return null;
  if (!signed) return seconds;
  if (current === null || current === undefined) return null;
  return raw[0] === "-" ? current - seconds : current + seconds;
}

// 見どころの位置・尺の欄。2つの欄は独立に効く — 位置は窓ごと動かして尺を保ち、尺は位置を
// 据えたまま終端だけを動かす。尺の欄を空にすると範囲を捨てて点へ戻る(点の行は空欄で
// 「点」と名乗る)。逆に点の行の尺へ長さを入れれば、そのままmp4にできる素材になる。
function markRangeInput(mark, kind) {
  const span = isRanged(mark) ? mark.end - mark.start : null;
  const noun = kind === "span" ? "見どころの尺" : "見どころの位置";
  const value = () => (kind === "span" ? span : mark.start);
  const shown = () => (kind === "span"
    ? (span === null ? "" : fmtCutTime(span))
    : fmtCutTime(mark.start));
  const input = document.createElement("input");
  input.type = "text";
  input.className = "vd-memo vd-time";
  // 桁数(1:23:45.6)ぶんだけを要求させる。既定のsize(20文字)のままだと、表の列幅は
  // 中身の要求で決まるため位置と尺の2列が要る幅の倍を取る。
  input.size = 10;
  input.value = shown();
  input.setAttribute("aria-label", noun);
  if (kind === "span") {
    input.placeholder = "点";
    // 尺の候補は作品の型(clip_presets)が持つ目標秒。投稿先ごとの狙いはそこで決めてある
    // ので、ここで別の数字を持つと2箇所が別々の「よくある尺」を名乗ることになる。
    input.setAttribute("list", "span-presets");
  }
  // 配信中に押した見どころのstartは暫定値で、録画の確定(finalize)でPTS軸へ載せ直される。
  // 今直しても再mapに上書きされるので、その前に触らせない(理由は欄の上で名乗る)。
  if (mark.pts_mapped === 0) {
    input.disabled = true;
    input.title = "配信中に記録した見どころです。位置は録画の確定後に定まります。";
  } else {
    input.title = (kind === "span"
      ? "空にすると点へ戻ります。尺を入れるとmp4にできる素材になります。"
      : "尺は保ったまま窓ごと動きます。")
      + "\n1:23:45.6 / 23:45 / 45.6 のどれでも入力できます。"
      + "\n+2 / -1.5 のように符号を付けると、今の値からの増減になります。"
      + "\n↑↓ で 0.1秒ずつ（shiftで1秒・altで10秒）動かせます。"
      + (kind === "span" && span !== null
        ? `\n終端: ${fmtCutTime(mark.end)}`
        : "");
  }
  // 行clickはこの見どころを再生する操作なので、この欄の操作は行へ伝播させない。
  ["click", "mousedown", "keydown", "dragstart"].forEach((type) => {
    input.addEventListener(type, (event) => event.stopPropagation());
  });
  const fail = (message) => {
    // 読めない値・保存できなかった値で欄を残さない。元へ戻したぶん、理由は必ず名乗る
    // (戻すだけだと打った値が黙って消えたように見える)。
    input.value = shown();
    $("marks-status").textContent = message;
    showToast(message, "error", { title: noun });
  };
  const commit = async (seconds) => {
    let body;
    let message;
    if (kind === "span") {
      if (seconds === span) return;
      body = { end: seconds === null ? null : mark.start + seconds };
      message = seconds === null
        ? "範囲を外して点に戻しました。"
        : `尺を ${fmtCutTime(seconds)} にしました。`;
    } else {
      if (seconds === mark.start) return;
      // 尺は据え置く。位置の欄で頭を直したときに終端が動かないと、直した秒数ぶん
      // 尺が伸び縮みして、2つの欄が互いの値を変え合うことになる。
      body = span === null ? { start: seconds } : { start: seconds, end: seconds + span };
      message = `位置を ${fmtCutTime(seconds)} にしました。`;
    }
    try {
      await apiSend("PATCH", `/api/bookmarks/${mark.id}`, body);
    } catch (err) {
      fail(err.message);
      return;
    }
    $("marks-status").textContent = message;
    showToast(message, null, { title: noun });
    // seek barのmarkerも位置で描いている。今その録画を開いていれば併せて引き直す。
    if (state.current && state.current.recording_id === mark.recording_id) {
      await loadBookmarks(mark.recording_id);
    }
    // 尺は位置との差で決まり、件数の内訳(尺あり・点)も書き出しの対象も変わる。
    // 行だけ直すと表の中で辻褄が合わなくなる。
    await loadMarks();
  };
  input.addEventListener("change", async () => {
    const raw = input.value.trim();
    const seconds = raw === "" ? null : parseTimeInput(raw, value());
    if (raw !== "" && seconds === null) {
      fail("時刻を読めません（例: 1:23:45.6 / +2 / -1.5）。");
      return;
    }
    if (kind !== "span" && seconds === null) {
      fail("位置は空にできません。");
      return;
    }
    if (seconds !== null && seconds < 0) {
      fail(kind === "span" ? "尺は0より長くしてください。" : "位置は0秒以降にしてください。");
      return;
    }
    await commit(seconds);
  });
  // 打ち直しではなく刻む。範囲を詰める作業は「あと少し」の繰り返しなので、1回の調整に
  // 時刻を丸ごと入力させるのは道具として重い。
  input.addEventListener("keydown", async (event) => {
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    if (input.disabled) return;
    event.preventDefault();
    const step = (event.altKey ? TIME_NUDGE_ALT_SECONDS
      : event.shiftKey ? TIME_NUDGE_SHIFT_SECONDS : TIME_NUDGE_SECONDS)
      * (event.key === "ArrowUp" ? 1 : -1);
    const base = value();
    // 点の尺欄には動かす元が無い。0からの刻みで範囲を作れるようにする(1回目の↑で0.1秒)。
    const next = Math.round(((base === null ? 0 : base) + step) * 1000) / 1000;
    if (next < 0) return;
    input.value = fmtCutTime(next);
    await commit(next);
  });
  return input;
}

// メモ欄と、同じ範囲が並んでいるときの印。印が要るのは、shortの自動生成が作った行が
// 範囲しか持たない(メモが空)ため、同じ場面の行が2つ並ぶと行だけを読んでも区別が
// 付かないからである。どちらを残すかは中身で決めるしかないので、印は「消せ」ではなく
// 「同じ物がもう1件在る」という事実だけを名乗り、確かめる手(視聴)は1列目に置く。
function markMemoCell(mark, twins) {
  const memo = document.createElement("input");
  memo.type = "text";
  memo.className = "vd-memo";
  memo.value = mark.memo || "";
  memo.placeholder = "メモ";
  memo.setAttribute("aria-label", "この見どころのメモ");
  memo.title = "覚え書きであり、mp4を書き出すときのfile名にもなります。";
  // 行clickはこの見どころを再生する操作なので、この欄の操作は行へ伝播させない。
  ["click", "mousedown", "keydown", "dragstart"].forEach((type) => {
    memo.addEventListener(type, (event) => event.stopPropagation());
  });
  // 打鍵毎に投げず、離れた時に確定させる。値が変わっていなければ何もしない。
  memo.addEventListener("change", async () => {
    const next = memo.value.trim();
    if (next === (mark.memo || "")) return;
    try {
      await apiSend("PATCH", `/api/bookmarks/${mark.id}`, { memo: next });
      mark.memo = next;
      // 成功時に画面が何も変わらないと、保存されたのか離れ方が悪くて捨てられたのかを
      // 判別できず、確かめるために画面を読み込み直すことになる。
      showToast("メモを保存しました。", null, { title: "見どころのメモ" });
    } catch (err) {
      // メモは書き出しfile名にもなる。保存できなかった値を欄に残すと、それが付くものと
      // して書き出しへ進める。保存済みの値へ戻し、理由をtoastで出す。
      memo.value = mark.memo || "";
      $("marks-status").textContent = err.message;
      showError(err, "見どころのメモ保存");
    }
  });
  if (twins.length < 2) return memo;
  const badge = document.createElement("span");
  badge.className = "vd-src vd-src-dup";
  badge.textContent = `重複${fmtNum(twins.length)}`;
  const where = [...new Set(twins.map((twin) => groupNameOf(twin.group_id) || "未分類"))];
  badge.title = `同じ録画の同じ範囲を指す見どころが${fmtNum(twins.length)}件あります`
    + `（${where.join("・")}）。書き出すとその件数ぶん同じmp4が出ます。`;
  // 印とメモ欄は同じ段に置く(折り返させると重複の在る行だけ背が2倍になり、
  // 一覧を目で追う手掛かりだった行の高さが揃わなくなる)。狭い時は欄の方が縮む。
  const wrap = document.createElement("span");
  wrap.className = "vd-row vd-row-pair";
  wrap.append(badge, memo);
  return wrap;
}

function renderMarks() {
  const rows = visibleMarks();
  const grouped = isGroupSelected();
  const twins = markRangeTwins();
  // 順はグループ内でしか、出所は自動生成を出している間でしか意味を持たない。
  // 中身が「—」の列に幅を割かない。
  const table = $("mark-table");
  table.classList.toggle("vd-cutlist-flat", !grouped);
  table.classList.toggle("vd-hide-origin", !state.showAuto);
  // 表示から消えた行の選択は捨てる(見えない行への一括操作を残さない)。
  const visibleIds = new Set(rows.map((mark) => mark.id));
  state.marksSelected = new Set([...state.marksSelected].filter((id) => visibleIds.has(id)));
  // shift+クリックの範囲選択はこの表示順の識別子列の上で効く。
  const markIds = rows.map((mark) => mark.id);
  renderTableRows(
    "mark-rows",
    "mark-empty",
    rows,
    (mark, rowNumber) => {
      const pick = pickBoxFor("marks", markIds, rowNumber - 1, () => renderMarks());
      const ranged = isRanged(mark);
      const watch = document.createElement("button");
      watch.className = "btn btn-small";
      watch.textContent = "視聴";
      watch.title = ranged
        ? "このtabのまま、この範囲を再生します（終端で一度止まります）。"
        : "このtabのまま、この位置から再生します。";
      // 「観る」は1列目に据える。同じ範囲が2行並んだとき、どちらが何かを決められるのは
      // 中身だけなので、表を読む起点をその手に置く。
      watch.addEventListener("click", () => markPlayer.play(mark));
      const open = document.createElement("button");
      open.className = "btn btn-small";
      open.textContent = "シーン検索視聴";
      open.title = "シーン検索の再生画面で開きます（波形・IN/OUT・文字起こしつき）。";
      open.addEventListener("click", () => openMark(mark));
      const remove = document.createElement("button");
      remove.className = "btn btn-small btn-danger";
      remove.textContent = "削除";
      remove.addEventListener("click", async () => {
        // 1件削除は最も高頻度で、しかも「視聴」と同じ行に並ぶ。まとめて削除する側にだけ
        // 確認が付いていて、誤clickしやすい方が素通しなのは逆である。
        const ok = await confirmDialog(
          `この見どころを削除します（${fmtDuration(mark.start)}`
          + `${ranged ? `〜${fmtDuration(mark.end)}` : ""}`
          + `${mark.memo ? ` ${mark.memo}` : ""}）。`
          + `${ranged ? "詰めたIN/OUTと並び順は戻せません。" : "この操作は取り消せません。"}`,
          { title: "見どころの削除", confirmLabel: "削除する" },
        );
        if (!ok) return;
        // 確認まで取った削除が失敗したとき、捕まえないと行が残るだけで理由が出ない
        // (async handlerの中なのでrejectは誰にも届かない)。
        try {
          await apiSend("DELETE", `/api/bookmarks/${mark.id}`);
        } catch (err) {
          showError(err, "見どころの削除");
          return;
        }
        // 消した見どころを観たまま残さない(実体の無い行を再生し続けることになる)。
        const seen = markPlayer.watching();
        if (seen && seen.id === mark.id) markPlayer.close();
        if (state.current) loadBookmarks(state.current.recording_id);
        loadMarks();
      });
      // 2つは同じ段に置く。折り返しを許すと、狭い時に操作列が2段になって行の背が倍になる
      // (行の高さは一覧を目で追う手掛かりなので、行ごとに変わらない方を採る)。
      const actions = document.createElement("span");
      actions.className = "vd-row vd-row-pair";
      actions.append(open, remove);
      const cont = continuesRecording(rows, rowNumber - 1);
      return [
        watch,
        pick,
        grouped ? String(rowNumber) : "—",
        isAutoMark(mark) ? "自動" : "—",
        identityCell(mark.unique_id, cont),
        identityCell(fmtYmd(mark.recording_started_at), cont),
        markRangeInput(mark, "start"),
        markRangeInput(mark, "span"),
        markMemoCell(mark, twins.get(markRangeKey(mark)) || []),
        groupSelectFor(mark, "marks"),
        actions,
      ];
    },
    [2, 6, 7],
    (tr, mark, index) => {
      if (continuesRecording(rows, index)) tr.classList.add("vd-cont");
      tr.dataset.playKey = String(mark.id);
      bindRowDrag(tr, "marks", mark.id);
      // 並べ替えはグループを選んでいる間だけ。「全て」「未分類」では順が定まらないので、
      // 掴めても落とす先の意味が無い(棚へのドロップ=所属の付け替えはどちらでも効く)。
      if (grouped) bindRowReorder(tr, mark, rows);
      // 掴める見た目なのにclickは無反応だと、合図と挙動が食い違う。
      // 行clickはこのtabの中で再生する(画面ごと移らないぶん安全)。
      tr.classList.add("row-clickable");
      tr.tabIndex = 0;
      // 元録画のpathと最後の書き出し日時は列を持たないぶんここで読ませる。どちらも普段の
      // 作業(範囲を詰める・並べる)では読まないが、失われると実体を辿る手が画面から消える
      // (書き出し日時は「今もそのfileが在る」という意味ではない — 在るかは
      // 「出力済みclip」tabが答える)。
      tr.title = [
        "この見どころをこのtabのまま再生します。",
        `元録画: ${mark.path || mark.filename || "-"}`,
        isRanged(mark) ? null : "尺がありません（mp4にはできません）。",
        mark.exported_at
          ? `最後の書き出し: ${fmtDateTimeShort(mark.exported_at)}`
            + `${mark.exported_path ? ` → ${mark.exported_path}` : ""}`
          : "まだmp4を書き出していません。",
      ].filter(Boolean).join("\n");
      tr.addEventListener("click", (event) => {
        // 行内のbutton・メモ欄・グループ欄は独自の操作を持つ。素通しすると「視聴」を
        // 押しただけで再生が二重に走り、読み込みも2回投げられる。
        if (event.target.closest("button, input, select, a")) return;
        markPlayer.play(mark);
      });
      tr.addEventListener("keydown", (e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        e.preventDefault();
        markPlayer.play(mark);
      });
    },
  );
  // 描き直した行にはclassが残らない。観ている行の印はここで付け直す(絞り込みやメモの保存で
  // 表を引き直すたび、再生は続いているのに印だけが消えていた)。
  paintPlayingMarks();
  updateMarksSelection();
}

// 選択した見どころの削除。所属の付け替えは行のグループ欄と上段tabへのドラッグが持つ。
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
    showError(err, "見どころの削除");
  }
  if (state.current) loadBookmarks(state.current.recording_id);
  await refreshGroupData();
  renderGroupViews();
}

// 表示中の全件削除。選択の有無に関わらず、表示中の絞り込みに従う(全てを消す操作ではない)。
async function clearVisibleMarks() {
  const rows = visibleMarks();
  if (!rows.length) {
    $("marks-status").textContent = "表示中の見どころがありません。";
    return;
  }
  const ok = await confirmDialog(
    `${groupScopeLabel(state.groupSel)}の${fmtNum(rows.length)}件を削除しますか？`
    + "この操作は取り消せません。",
    { title: "表示中をすべて削除", confirmLabel: "削除", danger: true },
  );
  if (!ok) return;
  try {
    // 「全て」を選んでいる間はgroup指定を付けない(=絞り込み無しの全件)。表示中と対象が
    // 一致することがこの操作の唯一の約束なので、絞り込みはそのままserverへ渡す。
    const query = state.groupSel ? `?group=${encodeURIComponent(state.groupSel)}` : "";
    const result = await apiSend("DELETE", `/api/bookmarks${query}`);
    $("marks-status").textContent = `${fmtNum(result.deleted)}件を削除しました。`;
    markPlayer.close();
    state.marksSelected.clear();
  } catch (err) {
    $("marks-status").textContent = err.message;
    showError(err, "表示中をすべて削除");
  }
  if (state.current) loadBookmarks(state.current.recording_id);
  loadMarks();
}

// 見どころから再生画面へ戻る。尺があればIN/OUTも復元して、そのまま切り出せる。
async function openMark(mark) {
  showView("search");
  await openHit({
    recording_id: mark.recording_id,
    unique_id: mark.unique_id,
    started_at: mark.recording_started_at,
    video_time: mark.start,
  });
  if (isRanged(mark)) setCut(mark.start, mark.end);
  inheritAddGroup(mark.group_id);
}

// 観ている位置で端を決める。時刻を打ち直すより観ながら決める方が速くて正しい
// (何秒かは覚えていないが、ここから、というのは見れば判る)。
// kind="in" は頭を今の位置へ(尺は保つ)、kind="out" は頭から今までを尺にする。
async function setMarkEdgeFromPlayer(kind) {
  const mark = markPlayer.watching();
  if (!mark) return;
  const say = (text, level) => {
    $("mark-play-status").textContent = text;
    if (level) showToast(text, level, { title: "見どころの範囲" });
  };
  if (mark.pts_mapped === 0) {
    say("配信中に記録した見どころです。位置は録画の確定後に定まります。", "error");
    return;
  }
  const now = $("mark-video").currentTime;
  let body;
  let message;
  if (kind === "in") {
    const span = isRanged(mark) ? mark.end - mark.start : null;
    body = span === null ? { start: now } : { start: now, end: now + span };
    message = `頭を ${fmtCutTime(now)} にしました。`;
  } else {
    if (now <= mark.start) {
      say("今の再生位置が頭より前です。頭より後ろで押してください。", "error");
      return;
    }
    body = { end: now };
    message = `尺を ${fmtCutTime(now - mark.start)} にしました（mp4にできます）。`;
  }
  try {
    await apiSend("PATCH", `/api/bookmarks/${mark.id}`, body);
  } catch (err) {
    say(err.message);
    showError(err, "見どころの範囲");
    return;
  }
  showToast(message, null, { title: "見どころの範囲" });
  if (state.current && state.current.recording_id === mark.recording_id) {
    await loadBookmarks(mark.recording_id);
  }
  await loadMarks();
  // 観ている対象の範囲が変わった。手元のitemは古い値のままなので、引き直したlistの行で
  // 観直す(終端で止まる位置が古いままだと、直したはずの尺で再生が止まらない)。
  const fresh = (state.marks || []).find((row) => row.id === mark.id);
  if (fresh) await markPlayer.play(fresh);
  // 名乗りは観直した後に置く。playが読み込みの状態でこの欄を書き直すので、先に書くと
  // 直した結果が同じtickで消える。
  say(message);
}


// ===== 一覧tabの中で観るplayer(見どころtab) =====

// 一覧を持つtabの中だけで使うplayer。再生経路(HLS/mp4)の決め方はシーン検索側と同じだが、
// 本編playerとは別の<video>・別のHls instanceで持つ。1つを共有すると、tabを移るたびに
// 相手の位置と読み込みを壊し合う。本編playerとは別instanceにするので、
// 片方で観ている録画は、もう片方のtabを触っても読み込み直しにならない。
// prefixはHTML側のid接頭辞("mark" / "cut")、nounは終端で止めた時に名乗る対象。
// onWatchは観ている行が入れ替わった時に呼ぶ(一覧側で今の行に印を付け直すため)。
function createInlinePlayer(prefix, noun, onWatch) {
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
    if (onWatch) onWatch();
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
    // 印は読み込みの前に移す。HLSを張り直す数秒のあいだ前の行が「今の行」を名乗ったままだと、
    // 見出し(play-head)と表の印が別々の行を指す。
    if (onWatch) onWatch();
    // 素材版が元録画固定であることを名乗る。シーン検索側で「焼き込み」を選んで作業した後、
    // ここで出来を確かめるつもりで観ると素のままの映像が出て、焼き込みが失敗していると
    // 誤読する。切り替えて確かめる先(シーン検索視聴)も同じ場所で案内する。
    const head = el("play-head");
    head.textContent =
      `${item.unique_id} / ${fmtDateTime(item.recording_started_at)} / ${fmtDuration(item.start)}`
      + (hasRange ? ` - ${fmtDuration(item.end)}` : "")
      + ` / 素材: ${VARIANT_LABELS.source}`;
    head.title = "この場での再生は常に元録画です（焼き込み・Up出力の出来は確かめられません）。";
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
      // 見出し(play-head)は既に新しい行を名乗っている。前の録画の映像を残すと、見出しと
      // 映像が別の場面を指したままになり、どの場面を観ているのか読めなくなる。
      if (want === token) {
        video.pause();
        if (hls) {
          hls.destroy();
          hls = null;
        }
        video.removeAttribute("src");
        video.load();
        loadedId = null;
        say(err.message);
      }
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

// 今この場で再生している行に印を付ける。表を描き直すと編集中の欄やscroll位置が飛ぶので、
// classだけを差し替える(行の身元は描画時にdata属性へ入れてある)。行が入れ替わる経路は
// 「視聴」button・行click・閉じる・削除と複数あるので、印はここ1箇所で付け直す。
function paintPlayingRows(tbodyId, key) {
  const tbody = $(tbodyId);
  if (!tbody) return;
  const want = key === null || key === undefined ? null : String(key);
  Array.from(tbody.children).forEach((tr) => {
    tr.classList.toggle("vd-playing", want !== null && tr.dataset.playKey === want);
  });
}

function paintPlayingMarks() {
  const seen = markPlayer.watching();
  paintPlayingRows("mark-rows", seen ? seen.id : null);
}

const markPlayer = createInlinePlayer("mark", "見どころ", paintPlayingMarks);

// tabを離れる時は、そのtabのplayerだけを止める。
function pauseInlinePlayers(name) {
  if (name !== "marks") markPlayer.pause();
  if (name !== "clips") {
    const video = $("clip-file-video");
    if (video && !video.paused) video.pause();
  }
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
  // ここのplayerは常に元録画を再生する(createInlinePlayer参照)ので、素材版もsourceで固定
  // する。file名のラベルは観ている行のメモ/ラベルをそのまま使う — 撮った1枚がどの行の
  // ものか、後からfile名だけで読めるようにするため。
  $(`${prefix}-play-shot`).addEventListener("click", () => {
    const item = player.watching();
    if (!item) return;
    saveStill(
      item.recording_id, $(`${prefix}-video`).currentTime, "source",
      item.label || item.memo || "",
      (text) => { $(`${prefix}-play-status`).textContent = text; },
    );
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
    ctx.fillStyle = cssTokenAlpha("--line", 0.35);
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
      ctx.fillStyle = cssTokenAlpha("--line", 0.55);
      ctx.fillRect(x, bodyBottom - commentH, barWidth, commentH);
      if (point.diamonds > 0) {
        const giftH = (point.diamonds / maxDiamonds) * heatHeight;
        ctx.fillStyle = "rgba(200, 150, 60, 0.75)";
        ctx.fillRect(x, bodyBottom - giftH, Math.max(1, barWidth * 0.5), giftH);
      }
    });
  }

  // giftのiconはheatの山より後に描く。金色の柱は「どれだけ来たか」で、iconはその山が
  // 何だったのかなので、柱に隠れると読む意味が無くなる。
  if (giftIconsShown()) {
    // 波形を出している間はその真下(heat帯の上端)へ載せる。上へ寄せると波形が潰れる。
    const top = folded ? bodyTop + bodyH * 0.45 + 2 : bodyTop + 1;
    const size = Math.max(6, Math.min(GIFT_ICON_FULL_PX, bodyBottom - top - 2));
    drawGiftIcons(ctx, giftIconsFull(ctx, duration, width, size),
                  { top, size, rowH: size, tickBottom: bodyBottom, names: false });
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
  ctx.fillStyle = cssTokenAlpha("--line", 0.18);
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
  ctx.fillStyle = cssTokenAlpha("--line", 0.16);
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

  // giftのicon。窓の中は件数が少ないので全尺barより大きく置け、送り主(avatarと名前の頭)
  // まで添えられる。名前のぶん1件が横に広がるので、同じ列に置けないものは段を下ろして
  // 拾う — 帯の高さが許すぶんだけ段を作り、残りは高額なものから残す。
  if (giftIconsShown()) {
    const size = Math.max(10, Math.min(GIFT_ICON_PX, bodyH * 0.45));
    const rowH = size + GIFT_NAME_LANE_PX + GIFT_ROW_GAP_PX;
    const rows = Math.max(1, Math.min(GIFT_MAX_ROWS,
                                      Math.floor((bodyH * GIFT_LANE_RATIO) / rowH)));
    drawGiftIcons(ctx, giftIconsInWindow(ctx, win, toX, width, size, rows),
                  { top: bodyTop + 1, size, rowH, tickBottom: bodyBottom, names: true });
  }

  // 時刻ruler。拡大中に全尺barへ目を往復せず「今どこか」を読めるようにする。
  ctx.fillStyle = cssTokenAlpha("--line", 0.35);
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

// ===== ギフトicon =====
// heatの山は「どれだけ来たか」しか表さない。何が飛んだのかはiconでしか読めないので、
// gift 1件ずつを時間軸へ小さく載せる。画像が無いgiftは描かない(別の絵で代用すると、
// 実際には飛んでいないgiftが飛んだように読める)。

// 全尺barのiconと「PK・ギフト」panelは同じ1回のresponseで賄う。表示checkbox(show-gifts)は
// 時間軸へiconを載せるかどうかだけを決め、取得そのものは切らない — panelはcheckboxと
// 無関係に中身を出す場所で、切っている間だけ空になるとdataが無いのと区別が付かない。
async function loadGifts(recordingId) {
  state.gifts = [];
  state.giftIcons = {};
  state.battles = [];
  giftLayout = null;
  // 行は先に捨てる。前の録画の行を残したまま中身だけ空にすると、その数百msの間に押した行が
  // 「もう手元に無いgift」を指してseekが落ちる。
  renderPkPanel(true);
  $("pk-note").textContent = "読み込み中…";
  let data;
  try {
    data = await apiSend("GET", `/api/recordings/${recordingId}/gifts`);
  } catch (err) {
    // iconが1つも載らない状態は「ギフトが飛ばなかった配信」と見分けが付かない。
    // wave-noteは波形loaderの欄なので割り込まず、panelのnoteとtoastで名乗る。
    if (state.current && state.current.recording_id === recordingId) {
      renderPkPanel(true);
      $("pk-note").textContent =
        `ギフトとPKを取得できませんでした（0件という意味ではありません）。${errorDetailText(err)}`;
      drawTimeline();
      showError(err, "ギフト・PKの取得");
    }
    return;
  }
  if (!state.current || state.current.recording_id !== recordingId) return;
  state.gifts = data.items || [];
  state.giftIcons = data.icons || {};
  state.battles = data.battles || [];
  preloadGiftIcons(state.giftIcons);
  $("pk-note").textContent = pkNoteText();
  renderPkPanel(true);
  drawTimeline();
}

// panelの見出しに出す集計。PKの有無で読む物が変わるので、戦数と勝敗を先に出す。
function pkNoteText() {
  const battles = state.battles || [];
  const gifts = `ギフト${fmtNum(state.gifts.length)}件`;
  if (!battles.length) return `PKなし / ${gifts}`;
  const wins = battles.filter((b) => !b.aborted && b.result === "win").length;
  const losses = battles.filter((b) => !b.aborted && b.result === "lose").length;
  return `${fmtNum(battles.length)}戦 ${wins}勝${losses}敗 / ${gifts}`;
}

// iconはgift_id別の不変な画像なので、録画を跨いで使い回す(同じgiftは配信を跨いで飛ぶ)。
const giftIconImages = new Map();

// 読み込みが終わったiconを載せるための描き直し。1件ずつ描き直すと、開いた直後に
// 数十回の再描画が並ぶので1 frameへまとめる。
let giftIconRedraw = false;

function scheduleGiftRedraw() {
  if (giftIconRedraw) return;
  giftIconRedraw = true;
  requestAnimationFrame(() => {
    giftIconRedraw = false;
    drawTimeline();
  });
}

function preloadGiftIcons(icons) {
  Object.keys(icons).forEach((giftId) => {
    if (giftIconImages.has(giftId)) return;
    const img = new Image();
    // 取れなかったiconは描かないだけにする(errorでもcompleteは立つので、
    // 描く側はnaturalWidthで実体の有無を見る)。
    img.addEventListener("load", scheduleGiftRedraw);
    img.src = icons[giftId];
    giftIconImages.set(giftId, img);
  });
}

function giftIconImage(giftId) {
  const img = giftIconImages.get(String(giftId));
  return img && img.complete && img.naturalWidth > 0 ? img : null;
}

// 描ける(server側がURLを出せた)giftだけを残す。iconを出せないgiftを場所取りに
// 使うと、そこに描けるはずだった隣のgiftまで消える。
function giftsWithIcons() {
  return state.gifts.filter((gift) => state.giftIcons[String(gift.gift_id)]);
}

// 送り主の表示名。頭からGIFT_NAME_CHARS文字だけを採る。code point単位で数えるのは、
// 名前の先頭が絵文字やサロゲートペアであることが珍しくないため — sliceで切ると壊れた
// 1文字が出る。@handleしか無い相手はそれを名乗る(数値IDは名前の位置へ出さない)。
function giftSenderName(gift) {
  const base = String(gift.nickname || gift.uid || "").trim();
  if (!base) return "";
  return Array.from(base).slice(0, GIFT_NAME_CHARS).join("");
}

// 1件が時間軸上で占める幅。名前を出すときは名前の幅も含める — iconの幅だけで場所を
// 取ると、iconは離れているのに名前どうしが重なる。
function giftEntryWidth(ctx, gift, size, withName) {
  if (!withName) return size;
  const label = giftSenderName(gift);
  if (!label) return size;
  return Math.max(size, ctx.measureText(label).width + 2);
}

// [from, to)の秒範囲のgiftを、重ならない位置へ間引いて返す。残すのは高額なものから
// (盛り上がりの主因が先に見える)。同じ列に置けないものはrowsで許した段まで下ろし、
// どの段にも入らないものだけを捨てる。返り値は描画順に並べ替えた [{gift, x, row, label, w}]。
function pickGiftIcons(ctx, gifts, toX, width, size, rows, withName) {
  // 幅の実測に使うfontは、実際に名前を描くときと同じものにする(違うfontで測ると、
  // 測った幅より広い名前が並んで重なる)。
  ctx.font = giftNameFont();
  const ranked = gifts
    .map((gift) => ({
      gift,
      x: toX(gift.t),
      label: withName ? giftSenderName(gift) : "",
      w: giftEntryWidth(ctx, gift, size, withName),
    }))
    .filter((item) => item.x >= -item.w && item.x <= width + item.w)
    .sort((a, b) => b.gift.diamonds - a.gift.diamonds);
  const lanes = [];
  for (let i = 0; i < Math.max(1, rows); i += 1) lanes.push([]);
  const kept = [];
  ranked.forEach((item) => {
    const row = lanes.findIndex((lane) => lane.every(
      (other) => Math.abs(other.x - item.x)
        >= (other.w + item.w) / 2 + GIFT_ICON_GAP_PX));
    if (row < 0) return;
    item.row = row;
    lanes[row].push(item);
    kept.push(item);
  });
  return kept.sort((a, b) => a.x - b.x);
}

// 全尺barの間引きは録画1本分のgiftを毎frame舐めることになる。窓も列数も変わらない
// 限り結果は同じなので、波形の畳み込みと同じく前回の結果を使い回す。
let giftLayout = null;

function giftIconsFull(ctx, duration, width, size) {
  if (giftLayout && giftLayout.gifts === state.gifts
      && giftLayout.duration === duration && giftLayout.width === width
      && giftLayout.size === size) {
    return giftLayout.picked;
  }
  // 全尺barは1px≈数秒で、送り主の名前を足しても隣のgiftが落ちるばかりで読めるように
  // はならない。誰が送ったかは拡大窓で読む。
  const picked = pickGiftIcons(
    ctx, giftsWithIcons(), (seconds) => (seconds / duration) * width, width, size, 1, false);
  giftLayout = { gifts: state.gifts, duration, width, size, picked };
  return picked;
}

// 拡大窓に映るぶんだけを間引く。窓は再生中ずっと毎frame描き直すので、窓の外のgiftは
// 走査ごと飛ばす(giftは開始順に並んでいる)。件数が少ないのでcacheは持たない。
function giftIconsInWindow(ctx, win, toX, width, size, rows) {
  const visible = [];
  for (let i = firstIndexWhere(state.gifts, (gift) => gift.t >= win.start);
       i < state.gifts.length; i += 1) {
    const gift = state.gifts[i];
    if (gift.t > win.end) break;
    if (state.giftIcons[String(gift.gift_id)]) visible.push(gift);
  }
  return pickGiftIcons(ctx, visible, toX, width, size, rows, true);
}

function giftIconsShown() {
  return $("show-gifts").checked && state.gifts.length > 0;
}

function giftNameFont() {
  return `${GIFT_NAME_FONT_PX}px "JetBrains Mono", monospace`;
}

// 送り主のavatar。gift iconと違い人数ぶん在るので、実際に描く物だけを引く(窓に映って
// いないgiftまで先に引くと、1配信で数百件の要求になる)。URLはeventに無いので、avatar
// poolのkey(uid)だけで引く同一originの口を叩く — 期限切れの署名URLを追わずに済む。
const giftSenderImages = new Map();

function giftSenderImage(uid) {
  if (!uid) return null;
  let img = giftSenderImages.get(uid);
  if (img === undefined) {
    img = new Image();
    // poolに無ければ404で終わる。errorでもcompleteは立つので、描く側はnaturalWidthで
    // 実体の有無を見て頭文字へ落とす(別人の絵を代わりに置かない)。
    img.addEventListener("load", scheduleGiftRedraw);
    img.src = avatarSrc("", uid);
    giftSenderImages.set(uid, img);
  }
  return img.complete && img.naturalWidth > 0 ? img : null;
}

// iconを段へ並べ、そこから真下へ細い線を落とす。iconは横に広く、絵の中心がそのまま
// 時刻には読めないため、線が無いと「いつ飛んだか」が数秒ぶれる。
// 線を先に全部引いてからiconを載せるのは、上の段から落ちる線が下の段のiconを横切る
// ため — 絵の側が勝つ順に描く。
// layout: {top, size, rowH, tickBottom, names}
function drawGiftIcons(ctx, picked, layout) {
  const { top, size, rowH, tickBottom, names } = layout;
  const entryH = size + (names ? GIFT_NAME_LANE_PX : 0);
  ctx.fillStyle = "rgba(122, 106, 60, 0.35)";
  picked.forEach((item) => {
    if (!giftIconImage(item.gift.gift_id)) return;
    const bottom = top + (item.row || 0) * rowH + entryH;
    if (tickBottom > bottom) {
      ctx.fillRect(Math.round(item.x), bottom, 1, tickBottom - bottom);
    }
  });
  // tokenの読み出しは1回の描画につき1度だけ。窓は再生中ずっと毎frame描き直すので、
  // 1件ずつ:rootを読むと件数ぶんのstyle参照が毎frame走る。
  const ink = names ? {
    disc: cssTokenAlpha("--line", 0.9),
    discInk: cssToken("--sand-panel"),
    edge: cssTokenAlpha("--sand-panel", 0.95),
    chip: cssTokenAlpha("--sand-panel", 0.85),
    name: cssToken("--ink-strong"),
  } : null;
  picked.forEach((item) => {
    const img = giftIconImage(item.gift.gift_id);
    if (!img) return;
    const y = top + (item.row || 0) * rowH;
    ctx.drawImage(img, item.x - size / 2, y, size, size);
    if (names) drawGiftSender(ctx, item, y, size, ink);
  });
}

// 送り主をgiftの絵に添える。avatarはiconの左下へ重ねて1件ぶんの幅を増やさず、名前の頭は
// icon幅に収まらないぶんだけ横へ出す(その幅は間引き側が場所として数えてある)。
function drawGiftSender(ctx, item, top, size, ink) {
  // 送り主が判らない行(名前もidも残っていない)は何も添えない。頭文字の「?」だけを
  // 置くと、誰かが居るのに読めていないように見える。
  if (!item.label && !item.gift.uid) return;
  const d = Math.max(8, Math.round(size * GIFT_AVATAR_RATIO));
  drawSenderAvatar(ctx, item, item.x - size / 2, top + size - d, d, ink);
  if (item.label) drawSenderName(ctx, item.label, item.x, top + size, ink);
}

function drawSenderAvatar(ctx, item, x, y, d, ink) {
  const img = giftSenderImage(item.gift.uid);
  const cx = x + d / 2;
  const cy = y + d / 2;
  ctx.save();
  ctx.beginPath();
  ctx.arc(cx, cy, d / 2, 0, Math.PI * 2);
  if (img) {
    ctx.clip();
    ctx.drawImage(img, x, y, d, d);
  } else {
    // 取れていないavatarは頭文字の円へ落とす。ここで誰かの絵を代わりに置くと、
    // 送っていない人が送ったように読める。
    ctx.fillStyle = ink.disc;
    ctx.fill();
    ctx.fillStyle = ink.discInk;
    ctx.font = `${Math.round(d * 0.62)}px "JetBrains Mono", monospace`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(Array.from(item.label || "?")[0] || "?", cx, cy + 0.5);
  }
  ctx.restore();
  // 縁。giftの絵の上にも地の上にも載るので、これが無いとavatarの輪郭が溶ける。
  ctx.strokeStyle = ink.edge;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.arc(cx, cy, d / 2, 0, Math.PI * 2);
  ctx.stroke();
}

function drawSenderName(ctx, label, cx, top, ink) {
  ctx.save();
  ctx.font = giftNameFont();
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  // 名前は波形の上に載る。字だけだと線に紛れて読めないので、地色を敷いてから置く。
  const w = ctx.measureText(label).width;
  ctx.fillStyle = ink.chip;
  ctx.fillRect(cx - w / 2 - 1, top, w + 2, GIFT_NAME_LANE_PX);
  ctx.fillStyle = ink.name;
  ctx.fillText(label, cx, top + 1);
  ctx.restore();
}

// ===== seek barのサムネイル =====
// spriteは1枚の大画像で、tile i が時刻 i*interval に対応する。background-positionをずらして
// 1枚だけ見せる。初回生成は長尺で十数秒かかるので、hoverの瞬間ではなく録画を開いた時点で頼む。

async function loadThumbnails(recordingId) {
  state.sprite = null;
  try {
    const spec = await apiSend("GET", `/api/recordings/${recordingId}/thumbnails`);
    if (state.current && state.current.recording_id === recordingId) state.sprite = spec;
  } catch (err) {
    // 成功pathと同じく録画を照合する。録画Aの失敗で、その時点で開いている録画Bの
    // preview画像まで消えていた。
    if (state.current && state.current.recording_id === recordingId) state.sprite = null;
    console.warn("thumbnail load failed", err);
  }
}

// 測ったbarの矩形とx座標から動画の秒を出す。矩形を引数に取るのは、1回の描画で同じbarを
// 何度も測り直さないため(測り直しはstyleを書いた後だとlayoutの再計算を伴う)。
// 基準はcontent box(clientLeft/clientWidth)にする。描画側は canvas.clientWidth を全尺として
// 描くので、border込みのrectで換算すると描いてある絵と当たる場所が最大1pxずれる。
// 全尺barは3時間×1600pxで1px≒6.7秒あり、端では「山を押したのに数秒ずれた所へ飛ぶ」になる。
function secondsFromRect(el, rect, clientX) {
  const duration = $("video").duration;
  if (!isFinite(duration) || duration <= 0) return null;
  const width = el.clientWidth || rect.width;
  const ratio = Math.min(1, Math.max(0, (clientX - rect.left - el.clientLeft) / width));
  return ratio * duration;
}

// bar上のx座標を動画の秒へ写す。thumbnail・seek・range dragが同じ換算を使う。
function secondsFromClientX(clientX) {
  const heat = $("heat");
  return secondsFromRect(heat, heat.getBoundingClientRect(), clientX);
}

function showThumb(clientX) {
  const spec = state.sprite;
  const thumb = $("thumb");
  // 位置決めに要る寸法は、styleを書き始める前にまとめて読む。読みと書きが交互になると
  // そのたびlayoutの再計算を待つことになる。thumbはwrapperに対する絶対配置なので、
  // 先に測っても出し入れの影響を受けない。
  const heat = $("heat");
  const rect = heat.getBoundingClientRect();
  const seconds = secondsFromRect(heat, rect, clientX);
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
  // 全尺bar(secondsFromRect)と同じくcontent boxを基準にする。拡大窓は1px≒数十msなので
  // 実害は小さいが、2つのbarで基準が違うと直した側だけが正しいという状態になる。
  const zoom = $("zoom");
  const rect = zoom.getBoundingClientRect();
  const width = zoom.clientWidth || rect.width;
  const ratio = Math.min(1, Math.max(0, (clientX - rect.left - zoom.clientLeft) / width));
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
  // 等値は逆転ではない。上端laneをdragせずclickすると pointerdown が IN=OUT を置くので、
  // ここに等値を含めると seek のつもりで押しただけで「OUTがINより前です」と出る。
  const reversed = inSec !== null && outSec !== null && outSec < inSec;
  const empty = inSec !== null && outSec !== null && outSec === inSec;
  $("cut-len").textContent = valid
    ? `尺 ${fmtDuration(outSec - inSec)}`
    : reversed ? "OUTがINより前です" : empty ? "範囲が0です" : "-";
  $("do-clip").disabled = !valid || !state.current;
  $("preview-in").disabled = inSec === null || !state.current;
  $("preview-out").disabled = outSec === null || !state.current;
  syncAddMarkButton();
  syncControlGroupNotes(valid);
  drawTimeline();
}

// 同じ範囲の見どころが既に在るか。IN/OUTはframe未満のずれで入ることがあるので、1 frame
// 以下の差は同じ範囲として扱う(厳密一致だけを見ると、詰め直した拍子に同じ場面の行が
// 2つ作れる)。
function existingMarkFor(recordingId, start, end) {
  if (recordingId === null || recordingId === undefined) return null;
  if (start === null || start === undefined || end === null || end === undefined) return null;
  return (state.marks || []).find((mark) => mark.recording_id === recordingId
    && mark.end !== null && mark.end !== undefined
    && Math.abs(mark.start - start) <= FRAME_STEP_SECONDS
    && Math.abs(mark.end - end) <= FRAME_STEP_SECONDS) || null;
}

// 記録の口は1つで、入力の状態によって入る物が変わる。何が入るのかをbutton自身に言わせる
// —— 「見どころに記録」とだけ書いてあると、IN/OUTを引いた状態で押した人は点が入ったのか
// 範囲が入ったのかを、押した後に一覧を見に行くまで確かめられない。
// 既に同じ範囲が在るときは押せなくする。押しても成功と出るだけで、重複は一括書き出しで
// 同じmp4が2本出るまで見えなかった。
function syncAddMarkButton() {
  const button = $("add-mark");
  if (!button) return;
  const ranged = state.cutIn !== null && state.cutOut !== null && state.cutOut > state.cutIn;
  const twin = ranged && state.current
    ? existingMarkFor(state.current.recording_id, state.cutIn, state.cutOut)
    : null;
  button.disabled = !state.current || Boolean(twin);
  button.textContent = twin
    ? "記録済"
    : (ranged ? "見どころに記録（尺あり）" : "見どころに記録（点）");
  button.title = twin
    ? `この範囲は既に見どころ（${groupNameOf(twin.group_id) || "未分類"}）にあります。`
    : (ranged
      ? "今のIN/OUTを見どころに記録します。尺があるのでそのままmp4にできます（mp4はまだ作りません）。"
      : "今の再生位置を点として記録します。尺が無いのでmp4にはできません（一覧の尺の欄で後から与えられます）。");
}

// 見どころのメモ。書き出しfile名にもなるので、入力欄の値をそのまま使う
// (以前は最後の検索語を黙って使っており、無関係な語のfileが数十件できていた)。
function currentClipLabel() {
  const input = $("mark-memo");
  return input ? input.value.trim() : "";
}

// 押せない理由を群の見出し横に1行で出す。button個々のtitleにしか無いと、hoverして回るまで
// 「今なにができるか」が読めない。
function syncControlGroupNotes(hasRange) {
  // 拡大窓の操作は尺が決まるまで何も起こせない(panZoom/zoomByが無言でreturnする)。
  // 押せるまま残すと、押しても何も起きないbuttonになる。
  ["zoom-left", "zoom-right", "zoom-out", "zoom-in"].forEach((id) => {
    const button = $(id);
    if (!button) return;
    button.disabled = !state.current;
  });
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
    // 黙って巻き戻すと、打った値が消えただけに見える(一覧側の位置・尺の欄は
    // 同じ場面で理由を出しており、経路によって作法が違っていた)。
    input.value = current === null ? "" : fmtCutTime(current);
    $("player-status").textContent = "時刻を読めません（例: 1:23:45.6）。";
    showToast("時刻を読めません（例: 1:23:45.6）。", "error",
      { title: kind === "in" ? "IN" : "OUT" });
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
  // 再生が弾かれたら状態を戻すだけでなく理由も出す。黙って戻すと、押しても何も起きない
  // buttonになる(素材が無い録画・autoplay policyのどちらでも同じ見た目になる)。
  video.play().catch((err) => {
    previewStopAt = null;
    $("player-status").textContent =
      `${kind === "in" ? "IN" : "OUT"}の確認再生を始められませんでした: ${err.message || err}`;
  });
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
    // 空になる経路は3つあり、対処が違う。一律に「有効にすると使えます」と案内すると、
    // 既にONの状態(生成中・取得失敗)では案内どおり操作しても何も起きない。
    const waveOn = $("show-wave").checked;
    const note = $("wave-note").textContent;
    $("player-status").textContent = !waveOn
      ? "無音区間がまだありません（音声波形を有効にすると使えます）。"
      : note.includes("生成中")
        ? "波形を生成中です。終わると無音区間で選べるようになります。"
        : "無音区間を取得できていません（無音が無いという意味ではありません）。";
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
// 切り出しの設定はシーン検索と見どころtabの両方から使う。片方にしかcontrolが無いと、
// もう片方に居る間は現在値が見えないまま一括書き出しが走る。DOMを2組持つが、値は
// この1組で持ち、どちらを操作しても両方へ書き戻す。
const CLIP_CONTROLS = [
  ["variant", "clip-variant", "cuts-variant", "value"],
  ["normalize_audio", "clip-normalize", "cuts-normalize", "checked"],
  ["remove_bgm", "clip-nobgm", "cuts-nobgm", "checked"],
  ["subtitles", "clip-subs", "cuts-subs", "checked"],
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
  CLIP_CONTROLS.forEach(([key, primary, mirror, prop]) => {
    const name = CLIP_PREF_KEYS[key];
    // 切り出しの指定は録画を跨いで使い回すので残す。値の出所はprimary側なので復元も
    // そこへ当て、mirrorへは末尾のsyncClipControlsが写す。
    restorePref($(primary), name);
    $(primary).addEventListener("change", () => syncClipControls(false));
    $(mirror).addEventListener("change", () => syncClipControls(true));
    // mirror側の操作はsetter経由でprimaryへ入るためchangeが出ない。どちらのchangeでも、
    // 写し終えたprimaryの値を1つのkeyへ残す。
    const save = () =>
      prefSet(name, prop === "checked" ? ($(primary).checked ? "1" : "0") : $(primary).value);
    $(primary).addEventListener("change", save);
    $(mirror).addEventListener("change", save);
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
      label: currentClipLabel(),
      ...clipOptions(),
    });
    // 全尺の焼き込み出力が無い録画で「焼き込み」を選ぶと、serverはその場で切らずにGPUの
    // queueへ載せ、job行だけを返す(route="render")。ここを見ずにresult.pathを読んでいたため、
    // 画面は「出力: undefined」と言い、その後の完了もどこにも出ないままだった。
    if (result.route === "render") {
      const queued = "この範囲だけを焼き込みます（順番待ちに入れました）。進み具合はJob画面と、"
        + "出来上がりは「出力済みclip」tabに出ます。";
      $("player-status").textContent = queued;
      showToast(queued, null, { title: "切り出し", duration: JOB_TOAST_MS });
      button.disabled = false;
      return;
    }
    // 実開始を必ず出す。stream copyはkeyframeからしか始まれないので、要求より手前へ
    // 伸びる。serverはずっとこの値を返していたのに画面が使っておらず、「30秒頼んで67秒」の
    // 理由が利用者から見えなかった。
    const lead = result.keyframe_lead_seconds;
    const note = lead
      ? `（実開始 ${fmtDuration(result.actual_start_seconds)} / 要求より ${lead.toFixed(1)}秒手前）`
      : "";
    // pathはNLEへ渡す実体なのでcopyの経路は要るが、押していないcopyでclipboardを奪わない
    // (直前に控えていた内容が黙って消える)。次のstatus更新でbuttonごと消える。
    // 字幕fileを頼んだのに出ていないときは理由まで出す。黙って0件だと、利用者は切り出し
    // ごとやり直すしかない(理由は録画側の事情なので、やり直しても同じ結果になる)。
    const subs = result.subtitles || {};
    const subNote = (subs.files || []).length
      ? ` / 字幕: ${subs.files.join("・")}`
      : (subs.message ? ` / ${subs.message}` : "");
    const status = $("player-status");
    status.textContent = `出力: ${result.path}${note}${subNote} `;
    const copy = document.createElement("button");
    copy.className = "btn btn-small";
    copy.type = "button";
    copy.textContent = "pathをcopy";
    copy.addEventListener("click", () => copyText(result.path, "切り出しpathをcopyしました。"));
    status.appendChild(copy);
  } catch (err) {
    $("player-status").textContent = err.message;
    showError(err, "切り出し");
  }
  button.disabled = false;
}

// ===== スクショ =====
// 押した位置の1 frameをserverが原寸のpngで出す。browserのcanvasで撮らないのは、画面に
// 出ている絵は<video>の表示寸法・素材版・読み込み済みの範囲に左右される一時的な物で、
// 成果物としては録画の実体から抜いた方が確かなため(置き場も切り出しと同じになる)。
// 実行はqueueへ載る。応答はjob_idだけで、出力pathは完了時のjob_updateで届く。

// 押した場所の状態欄。3つのtabのどこから撮ったかをclient側で覚えておくと、その間に別の
// 録画を開かれたときに古い場所へ書き戻すことになる。押した直後の文面が残っている欄だけを
// 結末で置き換える(押していない欄は触らない)。
const STILL_STATUS_IDS = ["player-status", "mark-play-status", "cut-play-status"];

function setStillStatus(text) {
  STILL_STATUS_IDS.forEach((id) => {
    const el = $(id);
    if (el && el.textContent.startsWith("スクショ")) el.textContent = text;
  });
}

async function saveStill(recordingId, at, variant, label, say) {
  if (recordingId === null || recordingId === undefined) return;
  // 秒はplayerの現在位置そのまま。再生経路(HLS/mp4)によって軸が違うが、serverは同じ
  // 経路の素材から抜くので、画面で止めている絵と同じ位置になる。
  say("スクショを保存しています…");
  try {
    await apiSend("POST", `/api/recordings/${recordingId}/still`, {
      at, variant, label: label || null,
    });
    // 出来上がりの報せはjob_updateが持つ(押した直後は順番待ちで、まだfileは無い)。
  } catch (err) {
    say(`スクショ: ${err.message}`);
    showToast(err.message, "error", { title: "スクショ" });
  }
}

// シーン検索tab。素材版は**今再生している版**を渡す(選択中の版がこの録画に無ければ元録画を
// 再生しているので、その場合は元録画から抜く — 画面に出ている絵と一致させる)。
function runStill() {
  if (!state.current) return;
  saveStill(
    state.current.recording_id, $("video").currentTime, playbackVariant(),
    currentClipLabel(), (text) => { $("player-status").textContent = text; },
  );
}

// ===== グループ(切り抜き動画1本の単位) =====
// 見どころはグループへ排他で所属し(group_id 1つ)、グループ間で同じ範囲を使う場合は行を
// 複製(copy)する — グループごとにIN/OUTの詰め方が変わるため、所属を共有すると片方の
// 調整が他方を黙って壊す。
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

// 行(見どころ)が選択値("" 全て / "none" 未分類 / "<id>")に含まれるか。表示・件数・
// 書き出し対象のすべてがこの1つの判定を通るので、見えている物と操作対象がずれない。
function matchesGroup(row, value) {
  if (value === "") return true;
  const id = row.group_id === null || row.group_id === undefined ? null : row.group_id;
  if (value === "none") return id === null;
  return id === Number(value);
}

// 棚の内訳。server側の集計ではなく手元のlistから数えるので、表に出ている件数と必ず
// 一致する(2つの出所があると、片方だけ古い数字が残る)。合計尺は尺のある行だけの和で、
// 点は素材にならないので入らない。
function groupStats(value) {
  const marks = (state.marks || []).filter((mark) => matchesGroup(mark, value)
    && (state.showAuto || !isAutoMark(mark)));
  const ranged = marks.filter(isRanged);
  return {
    marks: marks.length,
    ranged: ranged.length,
    seconds: ranged.reduce((sum, mark) => sum + (mark.end - mark.start), 0),
  };
}

// 書き出し・全削除の対象範囲の文言。buttonを押す前にこの文字列で範囲を読み取れる。
function groupScopeLabel(value) {
  if (value === "") return "見どころ全体";
  if (value === "none") return "未分類";
  return `グループ「${groupNameOf(Number(value))}」`;
}

function isGroupSelected() {
  return state.groupSel !== "" && state.groupSel !== "none";
}

// 左の縦paneに置くグループ棚。kindは "marks"。棚は「今どこを見ているか」の選択であり、
// 同時に行のドロップ先でもある。
// 以前は選択行があると棚ごとに「入れる/複製」buttonが生えていたが、選択のたびに
// 棚の高さと位置が変わって行き先を探し直すことになり、離れた表の行を選んでから
// 往復する操作になっていた。行き先の指定は行のグループ欄へ移し、ここはドラッグの
// 受け皿として常に同じ形で並べる。
function renderGroupBar(hostId, kind) {
  const host = $(hostId);
  if (!host) return;
  const picked = selectionSetOf(kind).size;
  // 静的な子(メモの入力欄)は残す。innerHTMLで消すと、打鍵中の値とfocusが毎回飛ぶ。
  [...host.children].forEach((el) => { if (!el.dataset.keep) el.remove(); });

  // 「グループ」を指す欄は画面に3つある(この表示切り替え・行のグループ欄・再生画面の
  // 記録先)。どれも同じ語で名乗ると、どれが何に効くのかがtitleを読むまで分からない。
  const label = document.createElement("span");
  label.className = "vd-gbar-label";
  label.textContent = "表示するグループ";
  host.appendChild(label);

  // 棚(全て・未分類)と実体のグループを1列に並べる。棚が増えたときに縦へ流れるのは
  // ここだけで、新規・hint・メモは足元に留める。
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
    // 全件と、そのうちmp4にできる件数(=尺のある行)の合計時間。尺は0件のときに出さない
    // ("0件 00:00:00" は「0秒の素材がある」と読めてしまう)。
    meta.textContent = `${fmtNum(stats.marks)}件`
      + (stats.ranged ? `（尺あり ${fmtNum(stats.ranged)} ${fmtDuration(stats.seconds)}）` : "");
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
        assignIds(drag.kind, entry.value, drag.ids);
      });
    }

    // tabは選択とドロップ先だけを担う。選んだtabにだけbuttonが生えると、選ぶたびに
    // tab列の幅と高さが動いて隣のtabの位置が変わる(選び直しのたびに狙い直しになる)。
    strip.appendChild(item);
  });

  // 新規作成とhintは足元に固定する。棚が増えてstripがscrollしても、作る手段と
  // 「今なにが選択中か」が流れて見えなくならないようにする。
  const ops = document.createElement("div");
  ops.className = "vd-gbar-ops";
  const hint = document.createElement("span");
  hint.className = "vd-group-hint";
  hint.textContent = picked ? `${fmtNum(picked)}件を選択中` : "グループ＝切り抜き動画1本";
  const create = document.createElement("button");
  create.className = "btn btn-compact";
  create.type = "button";
  create.textContent = "＋ 新規";
  create.title = "新しいグループを作ります（切り抜き動画1本の単位）。";
  create.addEventListener("click", () => createGroup(false));
  ops.append(create, hint);
  host.appendChild(ops);

  renderGroupMemo(host);
}

// 選択中のグループのメモ。棚と同じ列の足元に置く(このために上段のグループ見出し帯を
// 1本まるごと畳んでいる)。入力欄はHTML側の静的な要素で、ここでは名乗りと値だけを直す。
// 「どのグループのメモか」を添えるのは、棚の足元は選択中のtabから離れているため。
function renderGroupMemo(host) {
  const memo = host.querySelector("[data-keep='memo']");
  if (!memo) return;
  const group = selectedGroup();
  memo.classList.toggle("hidden", !group);
  if (!group) return;
  const cap = document.createElement("span");
  cap.className = "vd-gbar-label vd-gside-memocap";
  cap.textContent = `${group.name} のメモ`;
  host.appendChild(cap);
  // 入力中の値は上書きしない(引き直しのたびに自分の入力が消える)。
  if (document.activeElement !== memo) memo.value = group.memo || "";
  memo.dataset.groupId = String(group.id);
}

// 選択中のグループ。棚・表の見出し・メモが同じ1件を指していることを1箇所で決める。
function selectedGroup() {
  if (!isGroupSelected()) return null;
  return (state.groups || []).find((g) => String(g.id) === state.groupSel) || null;
}

// 「表示するグループ」は録画を跨いで使い回す絞り込みなので、値を変えたところで残す。
// 次に開いた時も同じグループの中身を見ている状態で始める。
function setGroupFilter(value) {
  state.groupSel = value;
  prefSet(GROUP_FILTER_PREF_KEY, value);
}

// 選択の切り替え。表示と操作対象は同じ値を見ているので、ここを変えるだけで
// 書き出し・連結・全削除の範囲も一緒に動く。
function selectGroup(value) {
  if (state.groupSel === value) return;
  setGroupFilter(value);
  // 選択そのものは捨てない。表示から外れた行だけが描画時に落ちる(renderMarks)ので、
  // 絞り込みを変えても見えている行の選択は続けて使える。
  state.lastPick.marks = null;
  // 落ちる件数は描画前にしか数えられない。黙って落とすと、選択した分だけ書き出すつもりの
  // 操作が「表示中の全件」へ戻ったことに気付けないまま次のbuttonを押すことになる。
  const dropped = droppedSelectionCount("marks");
  renderMarksView();
  if (dropped) {
    $("marks-status").textContent =
      `別のグループへ移ったので選択（${fmtNum(dropped)}件）を解除しました。`
      + "書き出し・連結の対象は表示中の全件に戻ります。";
  }
}

// 今の絞り込みでは表示されない選択の件数。
function droppedSelectionCount(kind) {
  const selected = selectionSetOf(kind);
  if (!selected.size) return 0;
  const visible = new Set(visibleMarks().map((row) => row.id));
  return [...selected].filter((id) => !visible.has(id)).length;
}

// 選択の置き場。見どころtabは行id、グループ操作tabは左右paneごとに別の集合を持つ
// (同じ行を別の目的で選んでいる場所なので、共有すると仕分けの途中で対象が入れ替わる)。
function selectionSetOf(kind) {
  if (kind === "marks") return state.marksSelected;
  return state.gops.selected[GOPS_SIDE_OF[kind]];
}

function updateSelectionFor(kind) {
  if (kind === "marks") updateMarksSelection();
  else updateGopsSelection(GOPS_SIDE_OF[kind]);
}

// 行の選択checkbox。shift+クリックは「直前に触った行からここまで」で、1行ずつ押させると
// 数十行の仕分けがそれだけで数十clickになる。rerenderは範囲選択で複数行のcheckが
// 変わったときだけ呼ぶ(1行の切り替えで表ごと描き直すと、押した位置のfocusが飛ぶ)。
// idsは表示順の識別子列。
function pickBoxFor(kind, ids, index, rerender) {
  const selected = selectionSetOf(kind);
  const id = ids[index];
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
    const ranged = event.shiftKey && from !== null && from !== index
      && ids[from] !== undefined;
    if (ranged) {
      const [lo, hi] = from < index ? [from, index] : [index, from];
      for (let i = lo; i <= hi; i += 1) {
        if (on) selected.add(ids[i]);
        else selected.delete(ids[i]);
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
    const selected = selectionSetOf(kind);
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

// 指定した行をグループへ入れる。行のグループ欄とtabへのドラッグの2経路がここを通るので、
// どちらの経路でも結果が同じになる。複製はグループ操作tabが持つ(gopsAssign)。
async function assignIds(kind, value, ids) {
  if (!ids || !ids.length) return;
  const selected = selectionSetOf(kind);
  const status = $("marks-status");
  const groupId = value === "none" ? null : Number(value);
  try {
    const result = await apiSend(
      "POST", "/api/bookmarks/bulk", { op: "move", ids, group_id: groupId },
    );
    const where = groupId === null ? "未分類" : `グループ「${groupNameOf(groupId)}」`;
    status.textContent = `${fmtNum(result.affected)}件を${where}へ入れました。`;
    // 行が移った時点で選択の意味が変わるので、動かした行だけ選択から外す
    // (行のグループ欄で1件だけ直したときに、残り全部の選択まで消さない)。
    ids.forEach((id) => selected.delete(id));
    state.lastPick[kind] = null;
  } catch (err) {
    // 直後のrefreshGroupData/renderGroupViewsが<select>を元のグループへ描き直す。
    // 選んだ値が黙って戻るので、戻った理由を押した場所から離れないtoastで出す。
    status.textContent = err.message;
    showError(err, "グループへの割り当て");
  }
  // 今開いている録画の見どころ(seek barのmarkerとplayer直下の一覧)は別に持っている。
  // 引き直さないと、所属を変えた行だけ古いグループ名のまま残る。
  if (state.current) await loadBookmarks(state.current.recording_id);
  await refreshGroupData();
  renderGroupViews();
}

// 記録先グループは録画を跨いで使い回すものなので記憶する(毎回選び直すと未分類へ落ちる)。
function loadAddGroupPref() {
  // 旧版は未分類を空文字で持っていた。"none"へ寄せて判定を1本にする。
  return prefGet(CUT_GROUP_PREF_KEY) || "none";
}

function saveAddGroupPref(value) {
  prefSet(CUT_GROUP_PREF_KEY, value);
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
      : `${entry.label}（${fmtNum(stats.marks)}）`;
    chip.title = entry.value === "none"
      ? "グループに入れずに記録します。後から上のグループtabで仕分けられます。"
      : `以後の「見どころに記録」を「${entry.label}」へ入れます。`;
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
    const empty = "検索語が空です。シーン検索の検索語がグループ名になります。";
    $("player-status").textContent = empty;
    showToast(empty, "error", { title: "検索語でグループを作る" });
    return;
  }
  try {
    const group = await apiSend("POST", "/api/groups", { name });
    await refreshGroupData();
    setAddGroup(String(group.id));
    renderGroupViews();
    // 記録先を変える操作はinheritAddGroupがtoastで名乗る。同じ事実をここだけ別の流儀で
    // 出すと、記録先が変わったかどうかを経路ごとに確かめ直すことになる。
    $("player-status").textContent = `記録先を「${group.name}」にしました。`;
    showToast(`記録先を「${group.name}」にしました。`);
  } catch (err) {
    $("player-status").textContent = err.message;
    showError(err, "検索語でグループを作る");
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
    showError(err, "グループの作成");
    return;
  }
  await refreshGroupData();
  if (asDestination) setAddGroup(String(group.id));
  else setGroupFilter(String(group.id));
  renderGroupViews();
  const text = asDestination
    ? `記録先を「${group.name}」にしました。`
    : `グループ「${group.name}」を作りました。`;
  status.textContent = text;
  showToast(text);
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
      if (group) await assignIds(kind, String(group.id), [row.id]);
      return;
    }
    await assignIds(kind, value, [row.id]);
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
    // nullを返すと呼び出し側は<select>を元へ戻す。作れなかったことを名乗らないと、
    // 打った名前も選んだ値も黙って消えたように見える。
    $(kind === "cuts" ? "cuts-status" : "marks-status").textContent = err.message;
    showError(err, "グループの作成");
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
  await fetchInto("/api/bookmarks", "marks");
  // 消えたグループを指したまま操作させない(選択も記録先も、指す先が無ければ戻す)。
  // 一覧を引けなかったときは判定しない — 引けていないことを「消えた」と読み替えない。
  if (!gotGroups) return failure;
  const exists = (value) => (state.groups || []).some((group) => String(group.id) === value);
  if (isGroupSelected() && !exists(state.groupSel)) setGroupFilter("");
  if (state.addGroup !== "none" && !exists(state.addGroup)) setAddGroup("none");
  // 統合・削除で消えたグループをpaneが指したまま残さない(空の表を「0件」として名乗る)。
  GOPS_SIDES.forEach((side) => {
    if (isRealGroup(state.gops[side]) && !exists(state.gops[side])) setGopsSide(side, "none");
  });
  return failure;
}

function renderGroupViews() {
  renderDestChips();
  renderMarksView();
  renderGopsView();
  // listが変われば「記録済」かどうかも変わる(別tabで消した範囲は再び記録できる)。
  syncAddMarkButton();
}

// ===== グループ操作tab =====
// 見どころtabは「選んだ1つのグループの中で」作業する場所で、グループを跨ぐ仕分けは
// そこでは行えない。ここは左右2つのグループを並べて突き合わせる場所。
//
// 行き先は常に「もう片方のpane」に固定する。移動先selectを別に置くと、画面の3箇所
// (左pane・右pane・移動先)が同時に別のグループを名乗り、どこからどこへ動くのかを
// 押す前に読み取れなくなる。

const GOPS_PREF_KEYS = { left: "tictok.videos.gopsLeft", right: "tictok.videos.gopsRight" };
const GOPS_SIDES = ["left", "right"];
const GOPS_LABELS = { left: "左", right: "右" };
const GOPS_OTHER = { left: "right", right: "left" };
// pickBoxFor/updateSelectionFor が受け取るkindからpaneを引く。
const GOPS_SIDE_OF = { "gops:left": "left", "gops:right": "right" };

// 実体のあるグループを指しているか。"":全て と "none":未分類 は移動の行き先にはなるが
// (未分類はnull所属という実体のある行き先)、"全て"は所属の指定にならない。
function isRealGroup(value) {
  return value !== "" && value !== "none";
}

function gopsFilter() {
  const seg = $("gops-filter");
  return seg ? seg.value : "all";
}

function setGopsSide(side, value) {
  state.gops[side] = value;
  prefSet(GOPS_PREF_KEYS[side], value);
}

// グループ(または全て・未分類)の内訳。全件・尺のある件数・点の件数と、合計尺。
// 合計尺は尺のある行だけの和である(点は素材にならないので入らない)。
function gopsStats(value) {
  const marks = (state.marks || []).filter((mark) => matchesGroup(mark, value));
  const ranged = marks.filter(isRanged);
  return {
    marks: marks.length,
    ranged: ranged.length,
    points: marks.length - ranged.length,
    seconds: ranged.reduce((sum, mark) => sum + (mark.end - mark.start), 0),
  };
}

// paneに出す行。録画→位置の順で並べる。左右の表を突き合わせる画面なので、並びは
// グループ内の書き出し順ではなく素材の時間軸で揃える(同じ場面が縦に揃う)。
function gopsRows(value, filter) {
  return (state.marks || [])
    .filter((mark) => matchesGroup(mark, value))
    .filter((mark) => (filter === "ranged" ? isRanged(mark)
      : filter === "point" ? !isRanged(mark) : true))
    .slice()
    .sort((a, b) => {
      const left = a.unique_id || "";
      const right = b.unique_id || "";
      if (left !== right) return left < right ? -1 : 1;
      const at = a.recording_started_at || 0;
      const bt = b.recording_started_at || 0;
      if (at !== bt) return at - bt;
      if (a.start !== b.start) return a.start - b.start;
      return a.id - b.id;
    });
}

async function loadGroupOps() {
  const failure = await refreshGroupData();
  renderGroupViews();
  // 棚と左右paneは前回のdataを表示し続ける(refreshGroupDataは手元のlistを捨てない)。
  // gops-statusは帯の右端なので、そこだけだと前回の内容を今の内容として読むことになる。
  if (failure) {
    $("gops-status").textContent = failure;
    showToast(failure, "error", { title: "グループの取得" });
  }
}

function renderGopsView() {
  if (!$("gops-rows")) return;
  renderGopsShelf();
  GOPS_SIDES.forEach((side) => {
    renderGopsGroupSelect(side);
    renderGopsHead(side);
    renderGopsRows(side);
  });
  updateGopsMerge();
  renderGopsDiff();
}

// 左右のpaneが指しているものの食い違いを1行で出す。表を2つ読み比べる前に、
// 「同じ範囲が両方に在る」「片方にしか無い」の件数を先に読めるようにする。
function renderGopsDiff() {
  const note = $("gops-diff");
  if (!note) return;
  const say = (key) => {
    const stats = gopsStats(state.gops[key]);
    return `${GOPS_LABELS[key]}: ${fmtNum(stats.marks)}件`
      + `（尺あり ${fmtNum(stats.ranged)}・点 ${fmtNum(stats.points)}）`
      + ` ${stats.ranged ? fmtDuration(stats.seconds) : "—"}`;
  };
  note.textContent = `${say("left")} ／ ${say("right")}`;
}

// 棚(グループ一覧)。ここが改名・メモ・並べ替え・削除の唯一の口で、以前はどれも画面から
// 行えなかった(メモだけが見どころtabの見出しに在った)。
// 1件=1枚の札を左の縦paneへ積む。10列の表を上段の帯に敷いていた頃は、グループが増える
// ぶんだけ下の対比(この画面の主役)が浅くなり、しかも名前・メモの入力欄と6つの数字と
// 5つのbuttonを横一列に詰めるため、どの列も中身なりの幅まで痩せていた。縦なら札が
// 何枚になっても対比の縦は削られず、1枚の中では身元(名前・メモ)・内訳・操作を
// 段で分けて置ける。
function renderGopsShelf() {
  const host = $("gops-rows");
  const empty = $("gops-empty");
  if (!host) return;
  const groups = state.groups || [];
  if (empty) empty.classList.toggle("hidden", groups.length > 0);
  host.innerHTML = "";
  const fragment = document.createDocumentFragment();

  groups.forEach((group, index) => {
    const value = String(group.id);
    const stats = gopsStats(value);

    const card = document.createElement("div");
    card.className = "vd-gcard";
    card.dataset.groupId = value;
    // 今どちらのpaneに出しているか。対比buttonのaria-pressedだけだと札の中の1点でしか
    // 名乗らず、積んだ札の中から「今読み比べている2枚」を目で拾えない。
    const sides = GOPS_SIDES.filter((side) => state.gops[side] === value);
    if (sides.length) card.dataset.side = sides.map((side) => GOPS_LABELS[side]).join("");

    const head = document.createElement("div");
    head.className = "vd-gcard-head";
    const no = document.createElement("span");
    no.className = "vd-gcard-no";
    no.textContent = String(index + 1);
    no.title = "棚の表示順です（グループ内の書き出し順とは別物です）。";

    const name = document.createElement("input");
    name.type = "text";
    name.className = "vd-memo vd-gcard-name";
    name.value = group.name;
    name.setAttribute("aria-label", "グループの名前");
    name.addEventListener("change", () => renameGroup(group, name));
    head.append(no, name);

    const memo = document.createElement("input");
    memo.type = "text";
    memo.className = "vd-memo vd-gcard-memo";
    memo.value = group.memo || "";
    memo.placeholder = "狙い・投稿先など";
    memo.setAttribute("aria-label", "グループのメモ");
    memo.addEventListener("change", () => saveGroupMemo(group.id, memo.value.trim()));

    // 内訳。0の項目は薄くする(0とそうでないものが同じ濃さで並ぶと、札を積むほど
    // 手を入れる先が拾えなくなる)。
    const statsRow = document.createElement("div");
    statsRow.className = "vd-gcard-stats";
    const stat = (key, label, text, muted) => {
      const cell = document.createElement("span");
      cell.className = "vd-gstat";
      cell.dataset.stat = key;
      if (muted) cell.dataset.zero = "true";
      const k = document.createElement("span");
      k.className = "vd-gstat-k";
      k.textContent = label;
      const v = document.createElement("span");
      v.className = "vd-gstat-v num";
      v.textContent = text;
      cell.append(k, v);
      statsRow.appendChild(cell);
    };
    stat("marks", "見どころ", fmtNum(stats.marks), !stats.marks);
    stat("ranged", "尺あり", fmtNum(stats.ranged), !stats.ranged);
    stat("points", "点", fmtNum(stats.points), !stats.points);
    stat("seconds", "完成尺", stats.ranged ? fmtDuration(stats.seconds) : "—", !stats.ranged);

    const ops = document.createElement("div");
    ops.className = "vd-gcard-ops";

    // 左右どちらのpaneへ出すかは、この札で決める。selectを探しに行かずに、
    // 一覧で見比べている札をそのまま対比へ載せられる。
    const compare = document.createElement("span");
    compare.className = "vd-row vd-gcard-cmp";
    const cmpLabel = document.createElement("span");
    cmpLabel.className = "vd-gbar-label";
    cmpLabel.textContent = "対比";
    compare.appendChild(cmpLabel);
    GOPS_SIDES.forEach((side) => {
      const button = document.createElement("button");
      button.className = "btn btn-small";
      button.type = "button";
      button.textContent = GOPS_LABELS[side];
      button.title = `このグループを${GOPS_LABELS[side]}のpaneに出します。`;
      button.setAttribute("aria-pressed", String(state.gops[side] === value));
      button.disabled = state.gops[side] === value;
      button.addEventListener("click", () => {
        setGopsSide(side, value);
        state.gops.selected[side].clear();
        state.lastPick[`gops:${side}`] = null;
        renderGopsView();
      });
      compare.appendChild(button);
    });

    const actions = document.createElement("span");
    actions.className = "vd-row vd-gcard-act";
    [["↑", -1], ["↓", 1]].forEach(([label, delta]) => {
      const button = document.createElement("button");
      button.className = "btn btn-small";
      button.type = "button";
      button.textContent = label;
      button.title = "棚の表示順を入れ替えます（グループ内の書き出し順とは別物です）。";
      button.disabled = index + delta < 0 || index + delta >= groups.length;
      button.addEventListener("click", () => nudgeGroupOrder(index, delta));
      actions.appendChild(button);
    });
    const remove = document.createElement("button");
    remove.className = "btn btn-small btn-danger";
    remove.type = "button";
    remove.textContent = "削除";
    remove.title = "グループだけを消します。中の見どころは未分類へ戻ります。";
    remove.addEventListener("click", () => deleteGroup(group));
    actions.appendChild(remove);

    ops.append(compare, actions);
    card.append(head, memo, statsRow, ops);
    fragment.appendChild(card);
  });

  host.appendChild(fragment);
}

async function renameGroup(group, input) {
  const name = input.value.trim();
  if (!name) {
    input.value = group.name;
    $("gops-status").textContent = "グループ名は空にできません。";
    return;
  }
  if (name === group.name) return;
  try {
    await apiSend("PATCH", `/api/groups/${group.id}`, { name });
    $("gops-status").textContent = `「${group.name}」を「${name}」に変えました。`;
  } catch (err) {
    // 入力欄が元の名前へ戻るので、失敗を出さないと「打った名前が黙って消えた」になる。
    input.value = group.name;
    $("gops-status").textContent = err.message;
    showError(err, "グループ名の変更");
  }
  await refreshGroupData();
  renderGroupViews();
}

async function saveGroupMemo(groupId, memo) {
  try {
    await apiSend("PATCH", `/api/groups/${groupId}`, { memo });
    showToast("メモを保存しました。", null, { title: "グループのメモ" });
  } catch (err) {
    $("gops-status").textContent = err.message;
    showError(err, "グループのメモ保存");
  }
  await refreshGroupData();
  renderGroupViews();
}

// 棚の並べ替え。1つ動かすたびに全体の並びを送る(部分的な指定だと、並行して増えた
// グループの位置がserver側とここで食い違う)。
async function nudgeGroupOrder(index, delta) {
  const groups = [...(state.groups || [])];
  const target = index + delta;
  if (target < 0 || target >= groups.length) return;
  const [moved] = groups.splice(index, 1);
  groups.splice(target, 0, moved);
  try {
    await apiSend("POST", "/api/groups/order", { group_ids: groups.map((g) => g.id) });
  } catch (err) {
    // 直後のrefreshGroupDataが元の順で描き直す。札が理由なく戻って見えるので名乗る。
    $("gops-status").textContent = err.message;
    showError(err, "グループの並べ替え");
  }
  await refreshGroupData();
  renderGroupViews();
}

async function deleteGroup(group) {
  const stats = gopsStats(String(group.id));
  const inside = stats.marks;
  const ok = await confirmDialog(
    inside
      ? `グループ「${group.name}」を削除します。中の見どころ ${fmtNum(inside)}件は消えず、`
        + "未分類へ戻ります（書き出し順は失われます）。"
      : `グループ「${group.name}」を削除します。`,
    { title: "グループの削除", confirmLabel: "削除する", danger: true },
  );
  if (!ok) return;
  try {
    await apiSend("DELETE", `/api/groups/${group.id}`);
    $("gops-status").textContent = inside
      ? `グループ「${group.name}」を削除し、${fmtNum(inside)}件を未分類へ戻しました。`
      : `グループ「${group.name}」を削除しました。`;
  } catch (err) {
    // 札は残るので、理由を出さないと「押せなかった」に見える。
    $("gops-status").textContent = err.message;
    showError(err, "グループの削除");
    return;
  }
  await refreshGroupData();
  renderGroupViews();
}

// paneの行き先select。「全て」も選べる(どのグループに在るか分からない行を探して、
// もう片方のグループへ入れる作業がこの画面の主目的の1つ)。
// 選択肢は名前だけにする。内訳を括弧で足していた頃は、名前の長いグループを選ぶと
// 閉じたselectの中で名前そのものが切れ、どのグループを指しているのか読めなかった
// (件数は左右まとめて対比帯の#gops-diffが出している)。
function renderGopsGroupSelect(side) {
  const select = $(`gops-${side}-group`);
  if (!select) return;
  const entries = [
    { value: "", label: "全て" },
    { value: "none", label: "未分類" },
    ...(state.groups || []).map((group) => ({ value: String(group.id), label: group.name })),
  ];
  if (!entries.some((entry) => entry.value === state.gops[side])) setGopsSide(side, "none");
  select.innerHTML = "";
  entries.forEach((entry) => {
    const option = document.createElement("option");
    option.value = entry.value;
    option.textContent = entry.label;
    select.appendChild(option);
  });
  select.value = state.gops[side];
}

function renderGopsHead(side) {
  const value = state.gops[side];
  const stats = gopsStats(value);
  $(`gops-${side}-stats`).textContent =
    `尺あり ${fmtNum(stats.ranged)}・点 ${fmtNum(stats.points)}`
    + ` / 完成尺 ${stats.ranged ? fmtDuration(stats.seconds) : "—"}`;
  const memo = $(`gops-${side}-memo`);
  const group = isRealGroup(value)
    ? (state.groups || []).find((g) => String(g.id) === value)
    : null;
  // 「全て」「未分類」はグループの実体が無いのでメモを持てない。書ける欄を出したまま
  // 保存先が無い状態にしない。
  memo.disabled = !group;
  memo.placeholder = group ? "このグループのメモ（狙い・投稿先など）" : "グループを選ぶと書けます";
  if (document.activeElement !== memo) memo.value = group ? (group.memo || "") : "";
  memo.dataset.groupId = group ? String(group.id) : "";
}

function renderGopsRows(side) {
  const rows = gopsRows(state.gops[side], gopsFilter());
  const selected = state.gops.selected[side];
  // 表示から消えた行の選択は捨てる(見えない行への一括操作を残さない)。
  const visible = new Set(rows.map((mark) => mark.id));
  state.gops.selected[side] = new Set([...selected].filter((id) => visible.has(id)));
  const ids = rows.map((mark) => mark.id);
  const kind = `gops:${side}`;
  renderTableRows(
    `gops-${side}-rows`,
    `gops-${side}-empty`,
    rows,
    (mark, rowNumber) => {
      const pick = pickBoxFor(kind, ids, rowNumber - 1, () => renderGopsRows(side));
      // 列幅に収めるため1行で省略する。全文はhoverで引けるようにする。
      const note = document.createElement("span");
      note.textContent = mark.memo || "";
      note.title = note.textContent;

      const actions = document.createElement("span");
      actions.className = "vd-row";
      const other = GOPS_OTHER[side];
      const send = document.createElement("button");
      send.className = "btn btn-small";
      send.type = "button";
      send.textContent = `${GOPS_LABELS[other]}へ`;
      // 「全て」は所属の指定にならない。押せる形で残すと、押しても何も起きない
      // buttonが並ぶことになる。
      send.disabled = state.gops[other] === "";
      send.title = send.disabled
        ? `${GOPS_LABELS[other]}が「全て」なので行き先になりません。グループか未分類を選んでください。`
        : `この1件を${gopsTargetName(other)}へ入れます。`;
      send.addEventListener("click", () => gopsAssign(side, "move", [mark.id]));
      actions.appendChild(send);
      // 身元は配信者と配信日で1つ。左右2つの表を並べる画面なので、突き合わせに要る
      // 「順」「位置」「尺」「操作」を押し出さないよう列を1つに畳む。
      const identity = `${mark.unique_id} ${fmtYmd(mark.recording_started_at)}`;
      const who = identityCell(identity, continuesRecording(rows, rowNumber - 1));
      who.title = identity;

      // 突き合わせに要る列(順・位置・尺)を左へ寄せ、身元とメモを右へ回す。左右2つの表を
      // 並べるので幅が足りずに横へ流れるが、隠れるのは identity 側だけで、この画面の目的
      // (どちらのグループに何が在るか)は常に見える。
      return [
        pick,
        mark.position === null || mark.position === undefined
          ? "—" : String(mark.position + 1),
        fmtDuration(mark.start),
        isRanged(mark) ? fmtDuration(mark.end - mark.start) : "点",
        who,
        note,
        actions,
      ];
    },
    [1, 2, 3],
    (tr, mark, index) => {
      if (continuesRecording(rows, index)) tr.classList.add("vd-cont");
      // 観るのは行click(この画面にplayerは置かない — 範囲を詰め直す作業はシーン検索側の
      // 仕事なので、そちらの再生画面へ移す)。
      tr.classList.add("row-clickable");
      tr.tabIndex = 0;
      tr.title = isRanged(mark)
        ? "シーン検索の再生画面で開きます（波形・IN/OUT・文字起こしつき）。"
        : "シーン検索の再生画面で開きます（尺がありません。IN/OUTは入りません）。";
      tr.addEventListener("click", (event) => {
        if (event.target.closest("button, input, select, a")) return;
        openMark(mark);
      });
    },
  );
  updateGopsSelection(side);
}

// 行き先の名乗り。buttonの文言に出すのは、選んだ覚えのないグループへ入るのが
// この画面で最も起きやすい事故だから(左右のselectは表2つ分離れた場所にある)。
function gopsTargetName(side) {
  const value = state.gops[side];
  if (value === "none") return "未分類";
  if (value === "") return "全て";
  return `「${groupNameOf(Number(value))}」`;
}

function updateGopsSelection(side) {
  const rows = gopsRows(state.gops[side], gopsFilter());
  const selected = state.gops.selected[side];
  const count = selected.size;
  $(`gops-${side}-selected`).textContent = count ? `選択 ${fmtNum(count)}件` : "";
  $(`gops-${side}-all`).checked = rows.length > 0 && count === rows.length;
  const other = GOPS_OTHER[side];
  const blocked = state.gops[other] === "";
  const where = gopsTargetName(other);
  const move = $(`gops-${side}-move`);
  move.disabled = !count || blocked;
  move.textContent = count ? `${where}へ移動（${fmtNum(count)}件）` : `${GOPS_LABELS[other]}へ移動`;
  move.title = blocked
    ? `${GOPS_LABELS[other]}が「全て」なので行き先になりません。グループか未分類を選んでください。`
    : `選んだ行を${where}へ入れます。`;
  const copy = $(`gops-${side}-copy`);
  // 複製は「同じ場面をグループごとに別々の詰め方で持つ」ための操作。所属は排他なので、
  // 共用ではなく行ごと複製することでしか表せない。
  copy.disabled = !count || blocked;
  copy.textContent = count ? `${where}へ複製（${fmtNum(count)}件）` : `${GOPS_LABELS[other]}へ複製`;
  copy.title = blocked
    ? `${GOPS_LABELS[other]}が「全て」なので行き先になりません。グループか未分類を選んでください。`
    : `選んだ行を複製して${where}へ入れます（元は残ります。書き出しの記録は複製しません）。`;
  $(`gops-${side}-delete`).disabled = !count;
  $(`gops-${side}-delete`).textContent = count ? `削除（${fmtNum(count)}件）` : "削除";
}

function updateGopsMerge() {
  const button = $("gops-merge");
  if (!button) return;
  const left = state.gops.left;
  const right = state.gops.right;
  const ready = isRealGroup(left) && isRealGroup(right) && left !== right;
  button.disabled = !ready;
  button.textContent = ready
    ? `「${groupNameOf(Number(left))}」を「${groupNameOf(Number(right))}」へ統合`
    : "左を右へ統合";
  button.title = ready
    ? "左の中身を全て右へ移し、左のグループを削除します。"
    : "左右それぞれに別の実体のあるグループを選んでください（「全て」「未分類」は統合できません）。";
}

// paneからもう片方のpaneへ移す／複製する。idsを渡せばその行だけ、省略すれば選択ぶん。
async function gopsAssign(side, op, ids) {
  const target = state.gops[GOPS_OTHER[side]];
  if (target === "") return;
  const picked = ids || [...state.gops.selected[side]];
  if (!picked.length) return;
  const groupId = target === "none" ? null : Number(target);
  const where = target === "none" ? "未分類" : `グループ「${groupNameOf(groupId)}」`;
  const status = $("gops-status");
  let affected = 0;
  try {
    const result = await apiSend("POST", "/api/bookmarks/bulk",
      { op, ids: picked, group_id: groupId });
    affected = result.affected;
  } catch (err) {
    // 失敗すると行も選択も動かない＝押す前と同じ画面になる。
    status.textContent = err.message;
    showError(err, op === "copy" ? "選択の複製" : "選択の移動");
    return;
  }
  status.textContent = `${fmtNum(affected)}件を${where}へ`
    + `${op === "copy" ? "複製しました" : "入れました"}。`;
  // moveは行が移った時点で選択の意味が変わるので外す。copyは元が残るので選択を保つ。
  if (op !== "copy") picked.forEach((id) => state.gops.selected[side].delete(id));
  state.lastPick[`gops:${side}`] = null;
  if (state.current) await loadBookmarks(state.current.recording_id);
  await refreshGroupData();
  renderGroupViews();
}

async function gopsDeleteSelected(side) {
  const picked = [...state.gops.selected[side]];
  if (!picked.length) return;
  const ok = await confirmDialog(
    `${GOPS_LABELS[side]}で選んだ見どころ ${fmtNum(picked.length)}件を削除しますか？`
    + "この操作は取り消せません。",
    { title: "選択の削除", confirmLabel: "削除", danger: true },
  );
  if (!ok) return;
  const status = $("gops-status");
  try {
    await apiSend("POST", "/api/bookmarks/bulk", { op: "delete", ids: picked });
  } catch (err) {
    // 消えなかった行はそのまま残る。理由が帯の右端の薄字だけだと「buttonが効かなかった」
    // と読んで押し直すことになる(確認dialogまで取った操作なので、なおさら)。
    status.textContent = err.message;
    showError(err, "選択の削除");
    return;
  }
  status.textContent = `見どころ ${fmtNum(picked.length)}件を削除しました。`;
  // 消えた範囲を別tabのplayerが観たまま残さない。
  const seen = markPlayer.watching();
  if (seen && picked.includes(seen.id)) markPlayer.close();
  state.gops.selected[side].clear();
  state.lastPick[`gops:${side}`] = null;
  if (state.current) await loadBookmarks(state.current.recording_id);
  await refreshGroupData();
  renderGroupViews();
}

async function mergeGopsGroups() {
  const left = state.gops.left;
  const right = state.gops.right;
  if (!isRealGroup(left) || !isRealGroup(right) || left === right) return;
  const from = groupNameOf(Number(left));
  const into = groupNameOf(Number(right));
  const stats = gopsStats(left);
  const ok = await confirmDialog(
    `グループ「${from}」の見どころ ${fmtNum(stats.marks)}件を「${into}」へ移し、`
    + `「${from}」を削除します。`
    + `「${into}」の並びの後ろへ順番を保ったまま付きます。`,
    { title: "グループの統合", confirmLabel: "統合する", danger: true },
  );
  if (!ok) return;
  try {
    const result = await apiSend("POST", `/api/groups/${left}/merge`, { into: Number(right) });
    $("gops-status").textContent =
      `「${from}」を「${into}」へ統合しました（見どころ ${fmtNum(result.bookmarks)}件）。`;
  } catch (err) {
    $("gops-status").textContent = err.message;
    showError(err, "グループの統合");
    return;
  }
  // 統合元は消えている。指したまま残すと空の表を「0件」として名乗る。
  setGopsSide("left", right);
  state.gops.selected.left.clear();
  state.gops.selected.right.clear();
  if (state.current) await loadBookmarks(state.current.recording_id);
  await refreshGroupData();
  renderGroupViews();
}

function bindGroupOps() {
  if (!$("gops-rows")) return;
  $("gops-reload").addEventListener("click", loadGroupOps);
  $("gops-new").addEventListener("click", async () => {
    const name = await promptDialog("新しいグループの名前", {
      title: "新しいグループ", confirmLabel: "作成",
    });
    if (!name) return;
    let group;
    try {
      group = await apiSend("POST", "/api/groups", { name });
    } catch (err) {
      $("gops-status").textContent = err.message;
      showError(err, "グループの作成");
      return;
    }
    await refreshGroupData();
    // 作った直後は「入れる先」として使うことが多い。右のpaneへ載せて、そのまま
    // 左から流し込めるようにする。
    setGopsSide("right", String(group.id));
    state.gops.selected.right.clear();
    const text = `グループ「${group.name}」を作り、右のpaneに出しました。`;
    $("gops-status").textContent = text;
    showToast(text);
    renderGroupViews();
  });
  $("gops-filter").addEventListener("change", () => {
    // 絞り込みで見えなくなった行の選択は、描画時に落ちる。
    renderGopsView();
  });
  $("gops-merge").addEventListener("click", mergeGopsGroups);
  GOPS_SIDES.forEach((side) => {
    $(`gops-${side}-group`).addEventListener("change", () => {
      setGopsSide(side, $(`gops-${side}-group`).value);
      state.gops.selected[side].clear();
      state.lastPick[`gops:${side}`] = null;
      renderGopsView();
    });
    $(`gops-${side}-memo`).addEventListener("change", () => {
      const memo = $(`gops-${side}-memo`);
      const groupId = Number(memo.dataset.groupId || 0);
      if (!groupId) return;
      saveGroupMemo(groupId, memo.value.trim());
    });
    $(`gops-${side}-all`).addEventListener("change", () => {
      const selected = state.gops.selected[side];
      if ($(`gops-${side}-all`).checked) {
        gopsRows(state.gops[side], gopsFilter())
          .forEach((mark) => selected.add(mark.id));
      } else {
        selected.clear();
      }
      state.lastPick[`gops:${side}`] = null;
      renderGopsView();
    });
    $(`gops-${side}-move`).addEventListener("click", () => gopsAssign(side, "move"));
    $(`gops-${side}-copy`).addEventListener("click", () => gopsAssign(side, "copy"));
    $(`gops-${side}-delete`).addEventListener("click", () => gopsDeleteSelected(side));
  });
}

// ===== 出力済みclip =====
// 切り出したmp4はDBに行を持たない。ここが並べるのはfile systemの実物そのもので、一覧も
// 削除もserverの走査結果に従う。画面側でcacheしないのは、消えたfileが残って見える方が
// 走査し直すcostより高くつくため(件数は録画数ではなく人が切った回数で、桁が小さい)。

const CLIP_KIND_LABELS = {
  clip: "切り出し", overlay: "焼き込み切り抜き", nobgm: "BGM除去", reel: "連結",
  work: "作品", still: "スクショ", subtitle: "字幕file", unknown: "規約外の名前",
};

// 素材版の印を持つのはスクショだけ(切り出しは種別そのものが版を名乗る)。どの版から撮った
// 1枚かはfile名にしか無いので、種別の欄で名乗る。
const STILL_VARIANT_LABELS = { overlay: "焼き込み", upscaled: "Up出力" };

function clipFileKindLabel(item) {
  const label = CLIP_KIND_LABELS[item.kind] || CLIP_KIND_LABELS.unknown;
  // 繋いだ物(連結・作品)は件数まで名乗る。1本のfileの中に何シーン入っているかは、
  // 名前を読まないと分からない唯一の情報である。
  if (item.parts) {
    return `${label}（${fmtNum(item.parts)}${item.kind === "work" ? "シーン" : "件"}）`;
  }
  // 字幕fileは書式で使い道が違う（SRTは装飾なし・ASSは焼き込みと同じテロップの装飾つき）。
  if (item.kind === "subtitle" && item.subtitle_format) {
    return `${label}（${item.subtitle_format.toUpperCase()}）`;
  }
  const variant = STILL_VARIANT_LABELS[item.variant];
  return item.kind === "still" && variant ? `${label}（${variant}）` : label;
}

async function loadClipFiles() {
  const empty = $("clips-empty");
  setListState(empty, "loading");
  try {
    const data = await apiSend("GET", "/api/clips");
    state.clipFiles = data.items || [];
    state.clipRoots = data.roots || [];
    fillClipFilters();
    renderClipRoots();
    renderClipFiles();
  } catch (err) {
    state.clipFiles = [];
    state.clipRoots = [];
    renderTableRows("clips-rows", null, [], () => [], []);
    // 保存先chipも描き直す。呼ばないと「取得できませんでした」の直下に、前回成功時の
    // 「保存先: N件 X GB」が残り続ける。
    renderClipRoots();
    setListState(empty, "failed", err);
    $("clips-summary").textContent = "";
  }
}

// 絞り込みの候補は実在するものだけにする。1本も無い配信者・保存先を並べても、選んだ先が
// 必ず空になるだけで手掛かりにならない。
function fillClipFilters() {
  const roots = $("clips-root");
  const keptRoot = roots.value;
  roots.replaceChildren(new Option("全て", ""));
  (state.clipRoots || []).forEach((root) => {
    roots.appendChild(new Option(root.label, root.key));
  });
  roots.value = keptRoot;
  const streamers = $("clips-streamer");
  const keptStreamer = streamers.value;
  streamers.replaceChildren(new Option("全て", ""));
  [...new Set((state.clipFiles || []).map((item) => item.unique_id).filter(Boolean))]
    .sort()
    .forEach((id) => streamers.appendChild(new Option(id, id)));
  streamers.value = keptStreamer;
}

// 保存先ごとの内訳。「2箇所に散らばる」ことがこの画面の前提なので、どちらに何本・何GB
// 在るかを表の前に出す。残骸(落ちた回の中間dir)も同じ場所に溜まるため件数だけ添える。
function renderClipRoots() {
  const bar = $("clips-roots");
  bar.replaceChildren();
  (state.clipRoots || []).forEach((root) => {
    const chip = document.createElement("span");
    chip.className = "vd-summary";
    const leftover = root.leftover_count
      ? ` ／ 中間fileの残骸 ${fmtNum(root.leftover_count)}件 ${fmtBytes(root.leftover_bytes)}`
      : "";
    // 数えるのは切り出し(mp4)とスクショ(png)の両方なので「本」では名乗れない。
    chip.textContent =
      `${root.label}: ${fmtNum(root.count)}件 ${fmtBytes(root.bytes)}${leftover}`;
    chip.title = root.path;
    bar.appendChild(chip);
  });
}

function visibleClipFiles() {
  const root = $("clips-root").value;
  const streamer = $("clips-streamer").value;
  const kind = $("clips-kind").value;
  return (state.clipFiles || []).filter((item) => (
    (!root || item.root === root)
    && (!streamer || item.unique_id === streamer)
    && (!kind || item.kind === kind)
  ));
}

function renderClipFiles() {
  const rows = visibleClipFiles();
  // 「読み込み中」の見た目を残したまま0件を描かない(取得できた0件と区別が付かなくなる)。
  setListState($("clips-empty"), rows.length ? "ok" : "empty");
  const rootLabels = Object.fromEntries(
    (state.clipRoots || []).map((root) => [root.key, root.label]));
  renderTableRows(
    "clips-rows",
    "clips-empty",
    rows,
    (item) => {
      const name = document.createElement("span");
      name.className = "vd-file";
      name.textContent = item.filename;
      // 実pathはNLEへ渡す実体そのもの。1行へ収めて省略するので、全体はここから読ませる。
      name.title = item.path;
      const where = document.createElement("span");
      where.className = "vd-file";
      where.textContent = rootLabels[item.root] || item.root;
      where.title = item.path;
      const actions = document.createElement("span");
      actions.className = "vd-row";
      // 字幕fileは観る物ではないので、この列は保存(download)になる。<video>へ渡しても
      // 壊れた枠が出るだけで、中身は編集ソフトやplayerへ渡して初めて意味を持つ。
      const subtitle = item.kind === "subtitle";
      const watch = document.createElement(subtitle ? "a" : "button");
      watch.className = "btn btn-small";
      if (subtitle) {
        watch.href = item.url;
        watch.download = item.filename;
      } else {
        watch.type = "button";
        watch.addEventListener("click", (e) => {
          e.stopPropagation();
          playClipFile(item);
        });
      }
      watch.textContent = subtitle ? "保存" : (item.kind === "still" ? "表示" : "視聴");
      const copy = document.createElement("button");
      copy.className = "btn btn-small";
      copy.type = "button";
      copy.textContent = "pathをcopy";
      copy.addEventListener("click", (e) => {
        e.stopPropagation();
        copyText(item.path, "切り出しpathをcopyしました。");
      });
      const remove = document.createElement("button");
      remove.className = "btn btn-small btn-danger";
      remove.type = "button";
      remove.textContent = "削除";
      remove.addEventListener("click", (e) => {
        e.stopPropagation();
        deleteClipFile(item);
      });
      actions.append(watch, copy, remove);
      // 元録画が既に消えている成果物もある(切り出しは録画の削除に道連れされない)。
      // 素性が引けない行はIN/OUTも「—」で、名前だけが手掛かりになる。
      return [
        item.unique_id || "—",
        name,
        clipFileKindLabel(item),
        item.start === null ? "—" : fmtDuration(item.start),
        item.end === null ? "—" : fmtDuration(item.end),
        item.start === null || item.end === null ? "—" : fmtDuration(item.end - item.start),
        fmtBytes(item.bytes),
        fmtDateTimeShort(item.modified_at),
        where,
        actions,
      ];
    },
    [3, 4, 5, 6],
    (tr, item) => {
      tr.dataset.playKey = item.path;
      // 字幕fileの行は押しても再生する物が無いので、押せる行にしない(押せる見た目にして
      // 何も起きないのは、壊れているのと見分けが付かない)。
      if (item.kind === "subtitle") {
        tr.title = "この切り抜きに添えた字幕fileです。「保存」で取り出せます。";
        return;
      }
      tr.classList.add("row-clickable");
      tr.tabIndex = 0;
      tr.title = item.kind === "still"
        ? "このスクショをこのtabのまま表示します。"
        : "この切り出しをこのtabのまま再生します。";
      tr.addEventListener("click", (event) => {
        if (event.target.closest("button, input, select, a")) return;
        playClipFile(item);
      });
      tr.addEventListener("keydown", (e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        e.preventDefault();
        playClipFile(item);
      });
    },
  );
  // 描き直した行にはclassが残らない。観ている行の印はここで付け直す。
  paintPlayingRows("clips-rows", state.clipPlaying);
  const total = rows.reduce((sum, item) => sum + item.bytes, 0);
  $("clips-summary").textContent =
    `${fmtNum(rows.length)}件 / ${fmtBytes(total)}`;
}

function playClipFile(item) {
  state.clipPlaying = item.path;
  paintPlayingRows("clips-rows", state.clipPlaying);
  $("clip-file-play").classList.remove("hidden");
  $("clip-file-empty").classList.add("hidden");
  $("clip-file-head").textContent = item.filename;
  $("clip-file-status").textContent = item.path;
  const video = $("clip-file-video");
  const image = $("clip-file-image");
  // 静止画を<video>へ渡しても壊れた枠が出るだけなので、種別で出す要素を変える。前に観て
  // いた方は必ず止めて外す(音だけが残る・前の絵が残る、のどちらも起きないように)。
  const still = item.kind === "still";
  video.pause();
  if (still) {
    video.removeAttribute("src");
    video.load();
    image.src = item.url;
  } else {
    image.removeAttribute("src");
    video.src = item.url;
  }
  video.classList.toggle("hidden", still);
  image.classList.toggle("hidden", !still);
  if (still) return;
  video.play().catch(() => {
    // autoplay policyで拒まれることがある。再生自体はcontrolsから始められるので、
    // 失敗を理由に閉じない。
  });
}

function closeClipFilePlayer() {
  state.clipPlaying = null;
  paintPlayingRows("clips-rows", null);
  const video = $("clip-file-video");
  video.pause();
  video.removeAttribute("src");
  video.load();
  const image = $("clip-file-image");
  image.removeAttribute("src");
  image.classList.add("hidden");
  video.classList.remove("hidden");
  $("clip-file-play").classList.add("hidden");
  $("clip-file-empty").classList.remove("hidden");
}

async function deleteClipFile(item) {
  const ok = await confirmDialog(
    `この切り出しfileを消します（${item.filename}）。\n${item.path}\n`
    + "元録画と見どころの行は残るので、同じ範囲を出し直せます。"
    + (item.kind === "subtitle" ? "" : "\n添えた字幕fileも一緒に消えます。"),
    { title: "切り出しfileの削除", confirmLabel: "削除する", danger: true },
  );
  if (!ok) return;
  try {
    const params = `root=${encodeURIComponent(item.root)}&name=${encodeURIComponent(item.name)}`;
    const result = await apiSend("DELETE", `/api/clips/file?${params}`);
    const subs = (result.subtitle_files || []).length;
    showToast(`切り出し ${item.filename}（${fmtBytes(result.freed_bytes)}）を削除しました。`
      + (subs ? `字幕file ${fmtNum(subs)}件も消しました。` : ""));
    // 観ていたfileを消したまま再生枠へ残さない(実体の無いものを指し続けることになる)。
    if ($("clip-file-head").textContent === item.filename) closeClipFilePlayer();
    loadClipFiles();
  } catch (err) {
    showError(err, "切り出しfileの削除");
  }
}

// ===== 一括書き出し =====
// 実行はserverのqueue。録画ごとに1 jobへ束ねられるので、browserを閉じても続く。
// 押した直後の結末(queueへ載った・載らなかった)はtoastでも出す。cuts-statusは帯の右端に
// あって視線が行かず、完了はWSのtoastで届くのに投入だけ無音だと「押せていないのでは」と
// 二度押しされる。完了と同じ場所で名乗らせて、押した操作の始まりと終わりを揃える。

async function exportCuts() {
  // 対象は選択した行、選んでいなければ表示中(=グループで絞った後)のlist。表と違う中身を
  // 書き出すと、見えていない行が黙ってqueueへ入る。
  const cuts = targetMarks();
  if (!cuts.length) {
    $("cuts-status").textContent = "尺のある見どころが表示中にありません。";
    showToast("尺のある見どころが表示中にありません。", "error",
      { title: "切り出しの一括書き出し" });
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
        label: cut.memo || null,
        // 書き出した事実をこの行へ書き戻させる。範囲はここで渡した値がそのまま使われる。
        bookmark_id: cut.id,
      })),
      ...clipOptions(),
    });
    const text =
      `${fmtNum(result.total)}件を${fmtNum(result.jobs.length)}個のjobで書き出します（Job画面で進み具合を確認できます）。`;
    $("cuts-status").textContent = text;
    showToast(text, null, { title: "切り出しの一括書き出し", duration: JOB_TOAST_MS });
  } catch (err) {
    $("cuts-status").textContent = err.message;
    showError(err, "切り出しの一括書き出し");
  }
  button.disabled = false;
}

async function makeReel() {
  // 対象は選択した行、選んでいなければ表示中のlist。グループを選んでいればposition順に
  // 繋がる(選択した分だけを繋ぐ場合もその順序のまま)ので、並び=完成の構成になる。
  const cuts = targetMarks();
  if (!cuts.length) {
    $("cuts-status").textContent = "尺のある見どころが表示中にありません。";
    showToast("尺のある見どころが表示中にありません。", "error", { title: "切り出しの連結" });
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
        label: cut.memo || null,
      })),
      variant: $("cuts-variant").dataset.value || "source",
    });
    const text = `${fmtNum(result.parts)}件を1本に連結します（Job画面で進み具合を確認できます）。`;
    $("cuts-status").textContent = text;
    showToast(text, null, { title: "切り出しの連結", duration: JOB_TOAST_MS });
  } catch (err) {
    $("cuts-status").textContent = err.message;
    showError(err, "切り出しの連結");
  }
  button.disabled = false;
}

// 作品の型(clip_presets)。設定画面の「shortの型」と同じ表を引く — 作り方を2箇所で持つと、
// 同じ型を選んだつもりで違う仕上がりが出る。
// 型が1つも無ければ作品は作れない。可否はここだけが知っているので、押せるかどうかを決める
// renderMarksHead から読めるよう外に置く(あちらが毎回書き直すため、局所変数では消える)。
let workPresetsReady = false;
// 型の一覧を引けたか。引けていない状態を「型がありません」と名乗ると、buttonのtooltipが
// 間違った対処(設定画面で型を作れ)を指示することになる — selectの文言とも食い違う。
let workPresetsKnown = false;

async function loadWorkPresets() {
  const select = $("cuts-preset");
  try {
    const result = await apiSend("GET", "/api/clip-presets");
    const presets = result.presets || [];
    workPresetsReady = presets.length > 0;
    workPresetsKnown = true;
    fillSpanPresets(presets);
    select.replaceChildren(
      ...(workPresetsReady
        ? presets.map((preset) => {
          const option = document.createElement("option");
          option.value = String(preset.id);
          option.textContent = preset.name;
          return option;
        })
        // 空のまま押させると、queueへ載ってから落ちる。理由と直し方をその場に出す。
        : [new Option("型がありません（設定画面で作成）", "")]),
    );
  } catch (err) {
    workPresetsReady = false;
    workPresetsKnown = false;
    select.replaceChildren(new Option(`型を読めません（${err.message}）`, ""));
  }
  renderMarksHead();
}

// 尺の欄に出す候補。点へ尺を与えるときの「よくある長さ」で、値は作品の型の目標秒から
// 引く(ここで数字を直に持つと、型を変えても候補が古い狙いのまま残る)。
// 同じ秒数の型が複数あっても候補は1つでよい。
function fillSpanPresets(presets) {
  const list = $("span-presets");
  if (!list) return;
  const seen = new Set();
  const options = [];
  presets.forEach((preset) => {
    const seconds = Number(preset.target_seconds);
    if (!isFinite(seconds) || seconds <= 0) return;
    const text = fmtCutTime(seconds);
    if (seen.has(text)) return;
    seen.add(text);
    const option = document.createElement("option");
    option.value = text;
    option.label = `${preset.name}（${text}）`;
    options.push(option);
  });
  list.replaceChildren(...options);
}

// グループ内の並べ替え。行を掴んで別の行の上へ落とすと、その位置へ入る。
// 並び(position)は作品と連結が繋ぐ順そのものなのに、これまで画面に変える手段が1つも
// 無く、行を入れた順のまま固定されていた(serverのAPIは既にあった)。
// グループを選んでいる間だけ効く — 「全て」「未分類」では順そのものが定まらない。
function bindRowReorder(tr, mark, rows) {
  tr.addEventListener("dragover", (event) => {
    const drag = state.drag;
    // 棚(グループ)へのドロップと同じdragを使う。行の上では並べ替えとして受ける。
    if (!drag || drag.kind !== "marks" || drag.ids.includes(mark.id)) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
    tr.classList.add("vd-drop-over");
  });
  tr.addEventListener("dragleave", () => tr.classList.remove("vd-drop-over"));
  tr.addEventListener("drop", async (event) => {
    tr.classList.remove("vd-drop-over");
    const drag = state.drag;
    if (!drag || drag.kind !== "marks" || drag.ids.includes(mark.id)) return;
    event.preventDefault();
    const moving = new Set(drag.ids);
    // 掴んだ行を一度抜いてから、落とした行の手前へまとめて入れる。掴んだ複数行は
    // 表示順のまま連れて行く(選択の相対順を崩さない)。
    const order = rows.map((row) => row.id);
    const carried = order.filter((id) => moving.has(id));
    const rest = order.filter((id) => !moving.has(id));
    const at = rest.indexOf(mark.id);
    if (at < 0) return;
    const next = [...rest.slice(0, at), ...carried, ...rest.slice(at)];
    const group = selectedGroup();
    if (!group) return;
    try {
      await apiSend("POST", `/api/groups/${group.id}/order`, { bookmark_ids: next });
    } catch (err) {
      $("marks-status").textContent = err.message;
      showError(err, "書き出し順の並べ替え");
      return;
    }
    $("marks-status").textContent =
      `${fmtNum(carried.length)}件を並べ替えました（書き出し順が変わります）。`;
    await loadMarks();
  });
}

// 作品の下見。押す前に「何をどの順で繋ぐか」「何が焼かれるか」「作れない行はどれか」を
// 読めるようにする。生成は分単位かかるので、確認を成果物で行うと確認のcostが実行と同じになる。
async function previewWork(announce) {
  const group = selectedGroup();
  if (!group) {
    $("cuts-status").textContent = "グループを選んでください。";
    if (announce) showToast("グループを選んでください。", "error", { title: "作品の下見" });
    return;
  }
  const presetId = $("cuts-preset").value;
  try {
    const plan = await apiSend(
      "GET",
      `/api/groups/${group.id}/work-plan${presetId ? `?preset_id=${presetId}` : ""}`,
    );
    const bits = [
      `${fmtNum(plan.scene_count)}シーン / 合計 ${fmtDuration(plan.requested_seconds)}`,
      `焼く: ${plan.burns.length ? plan.burns.join("・") : "なし（素材のまま繋ぎます）"}`,
    ];
    if (plan.tighten) bits.push("間を詰めます");
    if (plan.upscale) bits.push("高画質化します（GPUを長時間使います）");
    // 「前回の中間が在る」は事実で、「焼き直さない」ではない。焼き込みは設定・event・
    // 文字起こしまで見る別のcache判定を持つので、そちらが焼き直すと決めればこの数は当てにならない。
    const ready = plan.scenes.filter((s) => s.part_ready).length;
    if (ready) bits.push(`前回の中間が在る: ${fmtNum(ready)}シーン（${fmtBytes(plan.cache_bytes)}）`);
    if (plan.blocking.length) {
      bits.push(`作れないシーン: ${plan.blocking.join("・")}番目（素材かSessionがありません）`);
    }
    $("cuts-status").textContent = bits.join(" / ");
    if (announce) showToast(bits, null, { title: `作品の下見（${group.name}）` });
    return plan;
  } catch (err) {
    $("cuts-status").textContent = err.message;
    if (announce) showError(err, "作品の下見");
    return null;
  }
}

async function makeWork() {
  // 対象はグループ全体。行の選択には従わない(選択で範囲を変えると、DBのpositionと画面が
  // 組み立てた並びが食い違う余地が生まれる)。
  const group = selectedGroup();
  if (!group) {
    $("cuts-status").textContent = "グループを選んでください。";
    showToast("グループを選んでください。", "error", { title: "作品の書き出し" });
    return;
  }
  const button = $("cuts-work");
  button.disabled = true;
  try {
    // 作れない行が在るかを押した瞬間に確かめる。下見の結果をUIの状態として持つと、表の
    // 再描画がそれを消してしまう(同じ形の退行を型の有無で一度出している)。
    const plan = await previewWork();
    if (plan && plan.blocking.length) {
      const blocked =
        `${plan.blocking.join("・")}番目のシーンに素材がありません。直してから押してください。`;
      $("cuts-status").textContent = blocked;
      showToast(blocked, "error", { title: "作品の書き出し" });
      button.disabled = false;
      return;
    }
    $("cuts-status").textContent = "queueへ投入中…";
    const presetId = $("cuts-preset").value;
    const result = await apiSend("POST", `/api/groups/${group.id}/work`, {
      preset_id: presetId ? Number(presetId) : null,
    });
    const text = `${fmtNum(result.scenes)}シーンを1本の作品にします（Job画面で進み具合を確認できます）。`;
    $("cuts-status").textContent = text;
    showToast(text, null, { title: "作品の書き出し", duration: JOB_TOAST_MS });
  } catch (err) {
    $("cuts-status").textContent = err.message;
    showError(err, "作品の書き出し");
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
  // segmented controlのsetterはchangeを出さない(user操作ではないため)。, . keyでの
  // 変更はここで残す。
  prefSet(PLAY_RATE_PREF_KEY, select.value);
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
  prefSet(VOLUME_PREF_KEY, String(percent));
  prefSet(MUTE_PREF_KEY, video.muted ? "1" : "0");
}

function restoreVolume() {
  const video = $("video");
  // 保存が無いときは全開で始める。Number(null)は0なので、未保存を「音量0」と読むと
  // 初めて開いた人が無音の録画を観ることになる。
  const stored = prefGet(VOLUME_PREF_KEY);
  const saved = stored === null ? NaN : Number(stored);
  video.volume = Number.isFinite(saved) && saved >= 0 && saved <= 100 ? saved / 100 : 1;
  video.muted = prefGet(MUTE_PREF_KEY) === "1";
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
    s: () => runStill(),
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

// copyは画面上に何も現れない操作なので、成否の合図はここが唯一の出所になる。
// player-statusはpanel下端の0.68remの1行で、押した場所(章立てblock・切り出しの結果行)から
// 離れていることがある。
async function copyText(text, message) {
  try {
    await navigator.clipboard.writeText(text);
    $("player-status").textContent = message;
    showToast(message);
  } catch {
    // clipboard APIはhttp origin等で拒否されることがある。手動copyできるよう値を出す。
    // 本文はそのままstatusへ(toastへ流すと長文が画面を覆う)。
    $("player-status").textContent = `copyできませんでした: ${text}`;
    showToast("copyできませんでした。値は再生画面の状態欄に出しています。", "error",
      { title: "clipboardへのcopy" });
  }
}

// ===== 配信者selectの名簿 =====
// 候補は一括処理の集計(/api/bulk/status)から作る。同じ走査をする一覧を検索側にもう1本
// 持っていた頃は、同じ画面に母集合の違う「録画」列が2つ並び、数が食い違っていた。

// 配信者の絞り込みに出すのは「選ぶと何かが出てくる」配信者だけ。実体(素材/mp4)が1本も
// 残っておらず、文字起こしもコメント索引も無い配信者は、選んでも空の一覧が出るだけの選択肢に
// なる(retentionで素材が消えた配信者が実測13名居た)。逆に実体が無くても文字起こし・索引が在れば
// 残す — その録画へ辿る道はここしかない(録画一覧が「実体なし」の行を残しているのと同じ理由)。
function hasSomethingToShow(streamer) {
  return Boolean(streamer.playable
    || (streamer.done || {}).transcribe
    || streamer.comment_indexed);
}

// 一括処理の配信者select。候補は一括処理の対象表そのもの(検索側の絞り込みとは母集合が
// 違う — 文字起こしも索引も無く、実体だけが在る配信者は焼き込みの対象にはなる)。
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
    state.bulk.filter(hasSomethingToShow).forEach((streamer) => {
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
    // 前回選んでいた配信者を当てる。選択肢はdataで決まるのでここが復元できる最初の
    // 機会になる(消えた配信者は選択肢に無いので当たらない)。効くのは選択が空の初回だけで、
    // 以降はkeepが今の値を保つ。
    if (!select.value) restorePref(select, STREAMER_PREF_KEY);
  });
}

// 配信者名のcell。実体(素材/mp4)が1本も残っていない配信者はここで名乗らせる — 表からは
// 消さない。「録画5本・文字起こし0本」の行が理由も無く消えるより、なぜ進まないのかが読める方がよい。
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
// 表の列の並び。作る種別を先に、消す種別を最後に置く。BULK_LABELSのkey順に頼らない
// (順序を持たないobjectに表の並びを預けると、種別を足したときに列が任意の位置へ入る)。
const BULK_KIND_ORDER = ["transcribe", "laugh", "overlay", "upscale", "reprocess",
  "audionorm", "pack", "delete_mp4"];
// 種別ごとの「何に触れて何を残すか」。列見出しのhoverと、投入前の確認に出す。恒常的な
// 説明を確認paneだけに置くと、押す前(=どの列を押すか選ぶとき)には読めない。
const BULK_KIND_NOTES = {
  transcribe: "字幕の焼き込みにも使います。GPUを1本ずつ直列に使うため、まとめて投入しても"
    + "同時には走りません。",
  laugh: "音声から笑い声を検出し、シーン検索の探し方「笑い声」で一覧できるようにします。語では"
    + "なく音が根拠なので、文字起こしに「笑」と書かれていなくても拾います（文字起こしは笑い声を"
    + "文字にしません）。コラボ・Battle中は数えません（相手の声が混ざり、どの笑いが配信者の"
    + "ものかを音から決められないため）。解析済みでも一覧へ入っていない録画・共演を外す前に"
    + "数えた録画は対象になり、その場合は数十msで終わります。",
  overlay: "コメント・ギフトを映像へ焼き込んだmp4を作ります。再encodeのため、元動画と同程度"
    + "以上の容量を出力先に使います。",
  upscale: "AIで高画質化したmp4を作ります。再encodeのため、元動画と同程度以上の容量を"
    + "出力先に使います。",
  reprocess: "保持している.tsから録画を作り直します。設定「再mp4化: 元録画の音量も正規化する」"
    + "がONなら、同時に音量も揃います。",
  audionorm: "映像をそのまま複製し、音声だけを作り直して元のmp4と差し替えます。元のmp4は"
    + "_backup/へ退避するので、一時的に2本分の容量を使います。",
  pack: "素材の.tsを解像度の切れ目ごとに1 fileへ束ね直します。再encodeしないbyte連結なので、"
    + "映像も再生も変わりません。file数だけが減ります。",
  delete_mp4: "queueには載らず即座に消えます。対象は.tsが残っている録画だけで、作り直せない"
    + "録画は自動で対象から外します。焼き込み・Up出力・名前を変えたfileは残ります。",
};
// 作らずに消す種別。queueへは載せず専用APIで即時に実行するので、文言もbuttonも分ける。
const BULK_DELETE_KIND = "delete_mp4";
// 出力を作らない種別。元mp4の容量も所要の実測比も意味を持たないので、見積りの出し方を分ける。
const BULK_PACK_KIND = "pack";
// 台帳では kind=stt を名乗る種別。job_updateのdomainはDBのkindなので、一括処理の種別名
// (transcribe)とは一致しない。
const BULK_TRANSCRIBE_KIND = "transcribe";
// job_updateのdomain → 一括処理の種別。完了のたびに対象数が変わるので、届いたjobがどの列の
// 数字を動かすのかをここで引く。
const BULK_DOMAIN_KINDS = { stt: "transcribe", laugh: "laugh", overlay: "overlay",
  upscale: "upscale", reprocess: "reprocess", audionorm: "audionorm", pack: "pack" };
// 失敗として扱うjobの終わり方。cancelledは人が止めた結果なので含めない(押した本人が
// 知っていることを改めて出しても、本当に落ちた1本が埋もれるだけになる)。
const FAILED_JOB_STATES = ["failed", "interrupted"];
// 音声から笑い声を検出してシーン検索へ載せる種別。出力fileを作らないので、
// 文字起こしと同じくdiskの見積りもmp4のchipも意味を持たない。
const BULK_LAUGH_KIND = "laugh";
// mp4を作らない種別。元mp4の合計を並べても確かめるべき数字にならないので、chipを分ける。
const BULK_NO_MP4_KINDS = [BULK_PACK_KIND, BULK_TRANSCRIBE_KIND, BULK_LAUGH_KIND];
// 出力fileを作らない種別。disk空きの警告で投入を止める意味が無い。
const BULK_NO_DISK_KINDS = [BULK_TRANSCRIBE_KIND, BULK_LAUGH_KIND];
// 「作り直す」余地が無い種別。ts結合は冪等(束ね済みは何もしない)で、削除は一方通行。
// 文字起こしは含めない — modelを替えたときや時刻mapの版が上がったときは文字起こしをやり直す。
const BULK_NO_REDO_KINDS = [BULK_PACK_KIND, BULK_DELETE_KIND];

async function loadBulk() {
  // 集計は録画数ぶんのfile確認を伴うので数秒かかることがある。待っている間に古い/空の表を
  // そのまま出すと「表示しようとしているのか、対象が無いのか」が読めない。先に集計中を出す。
  $("bulk-summary").textContent = "集計中…（録画数が多いと数秒かかります）";
  if (!state.bulk.length) setListState($("bulk-empty"), "loading");
  let data;
  try {
    // 種別は指定しない(serverの既定が全種別)。列ごとにrequestを分けると、表1枚を描くのに
    // 種別の数だけ全録画の走査が走る。
    data = await apiSend("GET", "/api/bulk/status");
  } catch (err) {
    state.bulkNote = err.message;
    setListState($("bulk-empty"), "failed", err);
    return;
  }
  state.bulk = data.streamers || [];
  state.bulkDisk = data.disk || null;
  state.sttAvailable = data.stt_available;
  // 検索側の配信者選択もこの名簿から作る。集計が届いた時点が、選択肢を埋められる最初の機会。
  fillStreamerSelects();
  renderBulk();
}

// 「出力済みも作り直す」を入れると、済んだ本数も対象へ戻る。作り直す余地の無い種別
// (ts結合は冪等、削除は一方通行)には効かせない — serverの投入側も済みを戻さないので、
// 足すと画面の本数だけが実際より多くなる。
function bulkTargetCount(streamer, kind, redo) {
  const targets = (streamer.targets || {})[kind] || 0;
  const done = (streamer.done || {})[kind] || 0;
  return redo && !BULK_NO_REDO_KINDS.includes(kind) ? targets + done : targets;
}

// ---- 録画を選んでの投入 ----
// 可否の判定はserverの_bulk_classifyだけが持つ。画面側で「たぶん対象」を描くと、選べる
// のに投入されない録画が出る。

function closeBulkRows() {
  state.bulkOpen = null;
  state.bulkOpenRows = null;
  state.bulkSelected = new Set();
}

function bulkOpenIs(uniqueId, kind) {
  const open = state.bulkOpen;
  return Boolean(open && open.uniqueId === uniqueId && open.kind === kind);
}

async function loadBulkRecordings(uniqueId, kind) {
  const params = new URLSearchParams({
    kind,
    unique_id: uniqueId,
    // 効かせる範囲はcell・見積りと同じにする(作り直す余地の無い種別には効かせない)。
    redo: $("bulk-redo").checked && !BULK_NO_REDO_KINDS.includes(kind) ? "1" : "0",
  });
  const data = await apiSend("GET", `/api/bulk/recordings?${params}`);
  state.bulkOpenRows = data.recordings || [];
  // 種別や再出力の指定を変えると投入できる録画が変わる。選択は残さず、今の条件で投入
  // できるものだけへ絞る(選んだつもりの録画が黙って落ちるより、選び直させる方が安い)。
  const eligible = new Set(state.bulkOpenRows.filter((r) => r.eligible).map((r) => r.id));
  state.bulkSelected = new Set([...state.bulkSelected].filter((id) => eligible.has(id)));
}

// cellを押したら、その配信者×その種別で「まるごと投入の見積り」と「録画を選んでの投入」を
// 同時に開く。1 clickで両方見せるのは、どちらを使うかは規模(=見積り)を見てから決めるため。
// 開く場所は押した行の直下なので、どのcellに対する内容かを探さずに済む。
async function toggleBulkCell(uniqueId, kind) {
  if (bulkOpenIs(uniqueId, kind)) {
    closeBulkRows();
    hideBulkConfirm();
    renderBulk();
    return;
  }
  closeBulkRows();
  state.bulkOpen = { uniqueId, kind };
  hideBulkConfirm();
  // 先に開いて「読み込み中」を出す。取得を待ってから開くと、押しても何も起きない間が空く。
  renderBulk();
  // 見積りと録画一覧は独立に取れる。順に待つと、開いてから操作できるまでが2倍かかる。
  const [, recordings] = await Promise.allSettled([
    askBulk(uniqueId, null, kind),
    loadBulkRecordings(uniqueId, kind),
  ]);
  if (recordings.status === "rejected") {
    state.bulkOpenRows = false;
    state.bulkNote = recordings.reason.message;
    showError(recordings.reason, "録画一覧の取得");
  }
  renderBulk();
}

function bulkDetailRow(streamer, kind) {
  const tr = document.createElement("tr");
  tr.className = "bulk-detail";
  const cell = document.createElement("td");
  cell.colSpan = bulkColumnCount();
  tr.appendChild(cell);
  const rows = state.bulkOpenRows;
  if (rows === null) {
    cell.textContent = "録画を読み込み中…";
    return tr;
  }
  // falseは取得失敗。null(読み込み中)と[](0件)の2値しか無かった頃は、引けなかった一覧を
  // 「この配信者の録画はありません。」と断定していた(理由は表の上端の薄字1行のみ)。
  if (rows === false) {
    cell.className = "list-failed";
    cell.textContent = "録画一覧を取得できませんでした（0件という意味ではありません）。";
    return tr;
  }
  if (!rows.length) {
    cell.textContent = "この配信者の録画はありません。";
    return tr;
  }

  // 何をする場所なのかを名乗らせる。tool列が「投入できる全て / 選択を解除」から始まって
  // いた頃は、この一覧が「まるごと投入の対象を眺める場所」なのか「選んで投入する場所」なのか
  // が読めず、上に開いているまるごと投入のbuttonがそのまま押されていた。
  const title = document.createElement("div");
  title.className = "bulk-confirm-head";
  title.textContent = `録画を選んで${kind === BULK_DELETE_KIND ? "削除" : "投入"}`;
  cell.appendChild(title);

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
    "<thead><tr><th>選択</th><th>録画</th><th>開始</th>"
    + '<th class="num">尺</th><th class="num">容量</th><th>状態</th></tr></thead>';
  const tbody = document.createElement("tbody");
  table.appendChild(tbody);
  wrap.appendChild(table);
  cell.appendChild(wrap);

  const eligible = rows.filter((r) => r.eligible);
  const paint = () => {
    count.textContent =
      `選択 ${fmtNum(state.bulkSelected.size)} / 投入できる ${fmtNum(eligible.length)}本`;
    run.textContent = kind === BULK_DELETE_KIND
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
    // 行のどこを押しても選べるようにする。押す的がcheckbox 1個ぶんしか無いと、数十本を
    // 選ぶのに狙いを付け続けることになり、まるごと投入の方が近道になってしまう。
    if (row.eligible) {
      line.addEventListener("click", (ev) => {
        if (ev.target === box) return;
        box.checked = !box.checked;
        box.dispatchEvent(new Event("change"));
      });
    }
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
    askBulk(streamer.unique_id, [...state.bulkSelected], kind));
  paint();
  return tr;
}

// ---- 投入前の確認 ----
// 押した行の直下へ開く。表の外(toolbarの下)へ出していた頃は、開いた瞬間に配信者一覧が
// まるごと下へ動き、どの行に対する確認なのかも読み取れなかった。

function hideBulkConfirm() {
  state.bulkPending = null;
}

async function askBulk(uniqueId, recordingIds, kind) {
  // 作り直す余地の無い種別には効かせない。表のcellと同じ判断にしておかないと、確認の
  // 見出しだけが「処理済みも作り直す」と名乗り、実際には1本も戻らない。
  const redo = $("bulk-redo").checked && !BULK_NO_REDO_KINDS.includes(kind);
  // 先に前の見積りを捨てる。残したまま失敗すると、開いたままの確認paneが前回の対象
  // (多くは「未処理すべて」)を名乗り続け、そこで「この内容で投入」を押すと選んだ数本では
  // なく全件が投入される。押した側は右上の薄字1行しか見ていないので気付けない。
  hideBulkConfirm();
  $("bulk-summary").textContent = "見積りを計算中…";
  const params = new URLSearchParams({ kind, redo: redo ? "1" : "0" });
  if (uniqueId) params.set("unique_id", uniqueId);
  (recordingIds || []).forEach((id) => params.append("recording_id", id));
  let estimate;
  try {
    estimate = await apiSend("GET", `/api/bulk/estimate?${params}`);
  } catch (err) {
    state.bulkNote = err.message;
    showError(err, `${BULK_LABELS[kind]}の見積り`);
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
  cell.colSpan = bulkColumnCount();
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

  // その種別が何をするか。列見出しのhoverと同じ文で、押す直前にもう一度出す(hoverは
  // pointerを外すと消えるので、確認の場に残らない)。
  const what = document.createElement("div");
  what.className = "result-sub-note";
  what.textContent = BULK_KIND_NOTES[estimate.kind] || "";
  cell.appendChild(what);

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
  if ((disk.low_volumes || []).length && !BULK_NO_DISK_KINDS.includes(estimate.kind)) {
    notes.push(`空き容量が下限を下回っているvolumeがあります（${disk.low_volumes.join(", ")}）。`
      + "この状態では投入できません。");
  }
  // 「何が起きるか」の恒常的な説明は列見出しのhoverと同じ文(BULK_KIND_NOTES)を使う。
  // 押す前と押した後で違う言葉になると、確認しているものが同じだと読めない。
  if (estimate.kind === "overlay" || estimate.kind === "upscale") {
    notes.push("処理中は出力とは別に中間fileの領域も必要です。");
  }
  if (estimate.kind === BULK_PACK_KIND) {
    notes.push("束ねる間は元segmentを残したまま検証するため、その録画の素材と同じだけの"
      + "空きが一時的に要ります（足りない録画はjobが空き容量不足として止まります）。");
  }
  if (estimate.kind === BULK_DELETE_KIND) {
    notes.push("削除後は同じ.tsから再mp4化で作り直せます。");
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
  run.type = "button";
  // 「この内容で」は、何が対象なのかをbuttonが名乗っていない。同じ場所に録画を選んでの
  // 投入が開いている以上、押した側は選んだぶんが走ると読む。範囲を語で名指しする。
  const scope = pending.recordingIds ? "選んだ" : "対象すべて";
  run.textContent = estimate.kind === BULK_DELETE_KIND
    ? `${scope}${fmtNum(estimate.recordings)}本のmp4を削除`
    : `${scope}${fmtNum(estimate.recordings)}本を投入`;
  // 同じcellの録画一覧が開いている間は、まるごと投入を主のbuttonにしない。選んで投入する
  // 側と2つ並ぶ場面で色が強い方だけが押され、選択が無視されていた。
  const picking = Boolean(!pending.recordingIds && state.bulkOpen
    && state.bulkOpen.uniqueId === pending.uniqueId && state.bulkOpen.kind === pending.kind);
  run.className = estimate.kind === BULK_DELETE_KIND
    ? "btn btn-danger btn-small"
    : (picking ? "btn btn-small" : "btn btn-primary btn-small");
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
  // まるごと投入の確認には、録画を選ぶ道を必ず並べる。この確認は列見出しのbuttonからも
  // 開き、そちらから来た人には表のcellを押す導線が視界に入らない(実際、録画一覧を引く
  // requestが一度も出ていなかった)。決める場所と選び直す場所を同じ行に置く。
  if (!pending.recordingIds && !picking) {
    const pick = document.createElement("button");
    pick.className = "btn btn-small";
    pick.type = "button";
    pick.textContent = estimate.kind === BULK_DELETE_KIND
      ? "録画を選んで削除" : "録画を選んで投入";
    // 全配信者ぶんの確認からは開けない。録画一覧は配信者1人ぶんを引くもので、ここで
    // 勝手に1人へ絞ると、確認に出ている本数と開く一覧の母集合が食い違う。
    pick.disabled = !pending.uniqueId;
    pick.title = pending.uniqueId
      ? `@${pending.uniqueId}の録画を1本ずつ選んで${estimate.kind === BULK_DELETE_KIND
        ? "削除" : "投入"}します（表の本数を押すのと同じ一覧が開きます）。`
      : "上の「配信者」で1人を選ぶと、録画を1本ずつ選べます。";
    pick.addEventListener("click", () => {
      if (!pending.uniqueId) return;
      toggleBulkCell(pending.uniqueId, pending.kind);
    });
    tools.insertBefore(pick, cancel);
  }
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

// 表の列数。確認・録画一覧を差し込む行がcolSpanで使う。配信者・録画・種別ごと・comment
// 索引・総時間。
function bulkColumnCount() {
  return BULK_KIND_ORDER.length + 4;
}

// cellに出す数字。押したら何本走るかを主にし、済みは添えるだけにする。母数(録画数)は同じ行の
// 「録画」列に在るので、種別の数だけ繰り返さない。
function bulkCountCell(streamer, kind, redo) {
  const count = bulkTargetCount(streamer, kind, redo);
  const done = (streamer.done || {})[kind] || 0;
  const wrap = document.createElement("span");
  wrap.className = "bulk-cell";
  const main = document.createElement("span");
  main.className = count ? "bulk-todo" : "bulk-todo none";
  // 0本を0と描くと、押せるcellと押せないcellが同じ形で並ぶ。対象が無いことは記号で示す。
  main.textContent = count ? fmtNum(count) : "—";
  wrap.appendChild(main);
  // 済み件数と「選ぶ」は同じ段に並べる。縦に積むと、種別8列ぶんの行がすべて3段になる。
  const sub = document.createElement("span");
  sub.className = "bulk-sub";
  if (done) {
    const tail = document.createElement("span");
    tail.className = "bulk-done";
    tail.textContent = `済${fmtNum(done)}`;
    sub.appendChild(tail);
  }
  // 録画を選んで投入する道が在ることを、cell自身に名乗らせる。枠と説明文だけで示していた
  // 頃は、押されるのは列見出し(=まるごと投入)のbuttonばかりで、実際の操作logでも録画一覧
  // (/api/bulk/recordings)が一度も引かれていなかった。対象0本のcellには出さない —
  // 押しても何も開かないcellに操作名を出すと、押せる列を数字の濃さで見分けられなくなる。
  if (count) {
    const pick = document.createElement("span");
    pick.className = "bulk-pick";
    pick.textContent = "選ぶ";
    sub.appendChild(pick);
  }
  if (sub.childElementCount) wrap.appendChild(sub);
  return wrap;
}

// 押せない理由。押してから409や503で知るのでは遅いので、buttonの状態と同じ場所で決める。
function bulkCellBlockReason(streamer, kind, count) {
  if (kind === BULK_TRANSCRIBE_KIND && state.sttAvailable === false) {
    return "文字起こし機能が無効です。設定を確認してください。";
  }
  if (!count) {
    return `${BULK_LABELS[kind]}の対象がありません`
      + ((streamer.done || {})[kind] ? "（すべて処理済みです）。" : "。");
  }
  return "";
}

function bulkHeadRow(rows, redo) {
  const tr = document.createElement("tr");
  const head = (label, cls) => {
    const th = document.createElement("th");
    th.textContent = label;
    if (cls) th.className = cls;
    tr.appendChild(th);
    return th;
  };
  head("配信者");
  head("録画", "num").title = "この配信者の録画の行数です（実体の無い録画も含みます）。";
  BULK_KIND_ORDER.forEach((kind) => {
    const th = document.createElement("th");
    // 消す種別の列は列ごと印を付ける(btn-dangerだけではhoverするまで見分けが付かない)。
    th.className = kind === BULK_DELETE_KIND ? "num bulk-col-del" : "num";
    // 見出しそのものを押せるようにする。「全配信者をまとめて」を1つのbuttonで持っていた
    // 頃は、そのbuttonだけが種別も本数も名乗らず、消す種別でも作る種別と同じ色をしていた。
    const button = document.createElement("button");
    // btn-smallではなくbtn-compact。.btn-smallは.btnより前に定義されているためpaddingで
    // 負け、種別の数だけ1.4remの余白が積み上がって表が横へ伸びていた。
    button.className = kind === BULK_DELETE_KIND
      ? "btn btn-danger btn-compact bulk-head-btn"
      : "btn btn-compact bulk-head-btn";
    button.type = "button";
    const total = rows.reduce((sum, s) => sum + bulkTargetCount(s, kind, redo), 0);
    const scope = state.bulkOnly ? `@${state.bulkOnly}` : "全配信者";
    button.textContent = BULK_LABELS[kind];
    button.disabled = total === 0
      || (kind === BULK_TRANSCRIBE_KIND && state.sttAvailable === false);
    button.title = button.disabled
      ? (kind === BULK_TRANSCRIBE_KIND && state.sttAvailable === false
        ? "文字起こし機能が無効です。設定を確認してください。"
        : `${scope}に${BULK_LABELS[kind]}の対象がありません。`)
      : `${scope}の${BULK_LABELS[kind]} ${fmtNum(total)}本をまとめて処理します`
        + "（押すと投入前の確認が開きます）。"
        // 見出しは「まるごと」しか持たない。1本ずつ選ぶ道が別に在ることを、押す前に
        // 名乗っておく(確認paneにも同じ操作を並べている)。
        + `1本ずつ選ぶときは、この列の本数を押します。${BULK_KIND_NOTES[kind] || ""}`;
    button.addEventListener("click", () => {
      closeBulkRows();
      askBulk(state.bulkOnly, null, kind);
    });
    const count = document.createElement("span");
    count.className = "bulk-head-count";
    count.textContent = total ? fmtNum(total) : "—";
    th.append(button, count);
    tr.appendChild(th);
  });
  head("comment索引", "num").title =
    "コメントをシーン検索で引ける録画の数です。索引は録画の確定時に作られるので、"
    + "ここから投入する操作はありません。";
  head("総時間", "num");
  return tr;
}

function renderBulk() {
  const redo = $("bulk-redo").checked;
  fillBulkStreamerSelect();
  // 配信者画面から来たときは、その配信者だけを出す。全体を出すと目的の行を探し直す
  // ことになり、渡された選択が無駄になる。
  const rows = state.bulkOnly
    ? state.bulk.filter((s) => s.unique_id === state.bulkOnly)
    : state.bulk;

  // 恒常的な説明はここに1つだけ置く。種別ごとの説明は列見出しのhoverと確認paneが持つ
  // (8種別ぶんを常時並べると、読むべき数字が文章に埋もれる)。
  $("bulk-note").textContent =
    "表の本数はそのまま押せます。cellを押すとその配信者ぶんの見積りと録画一覧が開き、"
    + "録画を選んで投入できます（列見出しを押すと表示中の全配信者ぶんをまとめて投入します）。"
    + "所要時間はこのserverで実際に完了した"
    + "同種jobの実測から出しています（実績が無い種別は不明と表示します）。";
  // 投入結果や失敗の文言(bulkNote)は、次に条件を変えるまで残す。renderのたびに既定の
  // 集計文へ戻していた頃は、投入した瞬間に「入れました」が消えて何も起きていないように
  // 見えていた。
  const totals = BULK_KIND_ORDER
    .map((kind) => [kind, rows.reduce((sum, s) => sum + bulkTargetCount(s, kind, redo), 0)])
    .filter(([, total]) => total > 0);
  $("bulk-summary").textContent = state.bulkNote
    || (totals.length
      ? `未処理: ${totals.map(([kind, total]) => `${BULK_LABELS[kind]} ${fmtNum(total)}本`).join(" / ")}`
      : "未処理の対象はありません。");

  $("bulk-head").replaceChildren(bulkHeadRow(rows, redo));

  const tbody = $("bulk-rows");
  tbody.innerHTML = "";
  $("bulk-empty").classList.toggle("hidden", rows.length > 0);
  const pending = state.bulkPending;
  // 全配信者ぶんの確認だけは掛ける行が無いので表の先頭へ置く。
  if (pending && !pending.uniqueId) appendBulkConfirm(tbody);

  rows.forEach((streamer) => {
    const tr = document.createElement("tr");
    const cells = [streamerNameCell(streamer), fmtNum(streamer.recordings)];
    BULK_KIND_ORDER.forEach((kind) => {
      const count = bulkTargetCount(streamer, kind, redo);
      const button = document.createElement("button");
      button.className = "btn btn-compact bulk-cell-btn";
      button.type = "button";
      const open = bulkOpenIs(streamer.unique_id, kind);
      button.classList.toggle("bulk-cell-open", open);
      button.setAttribute("aria-expanded", open ? "true" : "false");
      button.appendChild(bulkCountCell(streamer, kind, redo));
      const blocked = bulkCellBlockReason(streamer, kind, count);
      button.disabled = Boolean(blocked);
      button.title = blocked
        || `${BULK_LABELS[kind]} ${fmtNum(count)}本 / 処理済 `
          + `${fmtNum((streamer.done || {})[kind] || 0)}本。`
          + "押すと見積りと録画一覧が開き、録画を選んで投入できます。";
      button.addEventListener("click", () => toggleBulkCell(streamer.unique_id, kind));
      cells.push(button);
    });
    cells.push(`${fmtNum(streamer.comment_indexed || 0)} / ${fmtNum(streamer.recordings)}`);
    cells.push(fmtDuration(streamer.seconds));

    // 消す種別の列。見出しと同じ位置に印を付けないと、列の途中で印が切れる。
    const delCol = 2 + BULK_KIND_ORDER.indexOf(BULK_DELETE_KIND);
    cells.forEach((value, col) => {
      const td = document.createElement("td");
      if (col >= 1) td.className = col === delCol ? "num bulk-col-del" : "num";
      if (value instanceof Node) td.appendChild(value);
      else td.textContent = value;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);

    // 確認と録画一覧は、押したcellの行の直下へ続けて出す。
    if (pending && pending.uniqueId === streamer.unique_id) appendBulkConfirm(tbody);
    const open = state.bulkOpen;
    if (open && open.uniqueId === streamer.unique_id) {
      tbody.appendChild(bulkDetailRow(streamer, open.kind));
    }
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
      : `${BULK_LABELS[pending.kind]} ${fmtNum(result.total)}本を投入しました。`;
    // 確認paneが閉じる見た目は中止と同じ。取り消せない削除の結果まで#bulk-summaryの
    // 0.68remの1行だけに置くと、何本消えたのかが押した本人にも残らない。
    showToast(state.bulkNote, null,
      { title: deleting ? "元mp4の削除" : BULK_LABELS[pending.kind], duration: JOB_TOAST_MS });
    // 投入した録画は「既にqueueにある」へ変わる。開いている一覧もその状態へ揃える。
    if (state.bulkOpen) {
      try {
        await loadBulkRecordings(state.bulkOpen.uniqueId, state.bulkOpen.kind);
      } catch (err) {
        // bulkNoteには投入できた件数が入っている。そこへ書くと成功の報告が消えるので、
        // 開いている一覧を引けなかったことは別に出す(黙ると行が消えた理由が残らない)。
        state.bulkOpenRows = false;
        showError(err, "録画一覧の再取得");
      }
    }
    loadBulk();
  } catch (err) {
    state.bulkNote = err.message;
    showError(err, deleting ? "元mp4の削除" : BULK_LABELS[pending.kind]);
    renderBulk();
    button.disabled = false;
  }
}

// ===== 起動 =====

// 排他選択のうち往復の多いものはsegmented controlで出す。listenerを付ける前に生やす
// (initSegmentedが.valueとchange eventを要素へ足すため、以降は<select>と同じに扱える)。
const SEGMENTED = [
  "flt-mode", "flt-order", "flt-laugh-order", "flt-browse-order", "clip-variant", "cuts-variant",
  "clip-mode", "cuts-mode", "play-rate", "review-state", "gops-filter"];

// 表示設定の復元とuser操作時の保存。ここは値を入れるだけで、初期描画・初期fetchは
// 起動側の既存の順序に任せる(bindPrefのonChangeはuser操作の時しか呼ばれないので、
// 復元で二重の取得は起きない)。segmented controlの.valueを使うのでinitSegmentedの後、
// 値を読む起動時のrunSearch・loadBulkより前に呼ぶこと。
//
// 残さないもの: 検索語(自由入力)・IN/OUT・ラベル・メモ(1件を指した一時的な入力)、
// 行の選択と移動先(表の中身に紐づく一時的な対象指定)、確認状態の印(録画ごとの値)、
// 再生位置、「出力済みも作り直す」(既存出力の上書き指定)、一括処理の種別
// (集計の重い種別・消す種別が起動時に選ばれた状態になる)、拡大窓の追従と幅
// (録画を開くたび既定へ戻す設計)、IN/OUTのループ(境界確認という一時的なmode)。
// 文字起こし・コメントは見出しから畳める。どちらを読むかは作業の型なので、録画ごとでは
// なく画面の設定として残す。0件で自動的に畳むのとは別classなので、文字起こしが届いた録画を
// 開いても畳んだ選択は保たれる。
const FOLD_BLOCKS = [
  {
    block: "transcript-block",
    button: "transcript-fold",
    list: "segments",
    follow: "transcript-follow",
    row: () => $("segments").children[state.segmentIndex],
    pref: "tictok.videos.transcriptFold",
  },
  {
    block: "comment-block",
    button: "comment-fold",
    list: "comments",
    follow: "comment-follow",
    row: () => $("comments").children[state.commentIndex],
    pref: "tictok.videos.commentFold",
  },
  {
    block: "pk-block",
    button: "pk-fold",
    list: "pk-gift-list",
    follow: "pk-follow",
    // 積み上がる一覧なので、開き直した時に戻る先は「今の行」ではなく下端。
    onOpen: () => stickPkGiftsToBottom(),
    pref: "tictok.videos.pkFold",
  },
];

function applyFold(conf) {
  const folded = prefBool(conf.pref, false);
  $(conf.block).classList.toggle("vd-block-folded", folded);
  const button = $(conf.button);
  button.setAttribute("aria-expanded", folded ? "false" : "true");
  button.querySelector(".vd-fold-mark").textContent = folded ? "▸" : "▾";
  // 畳んでいる間は中身がlayoutから外れ、開き直すとscrollが頭へ戻る。追従ONなら今の行を
  // 中央へ置き直す(highlight系は行が変わらない限り何もしないので、ここから直接呼ぶ)。
  if (folded) return;
  if (conf.onOpen) conf.onOpen();
  if (!$(conf.follow).checked || !conf.row) return;
  const row = conf.row();
  if (row) centerRowIn($(conf.list), row);
}

function bindFoldBlocks() {
  FOLD_BLOCKS.forEach((conf) => {
    applyFold(conf);
    $(conf.button).addEventListener("click", () => {
      prefSet(conf.pref, prefBool(conf.pref, false) ? "0" : "1");
      applyFold(conf);
    });
  });
}

function bindDisplayPrefs() {
  // 検索の対象・絞り込み・方式・並替。値を読むのは起動時のrunSearch(語なしの録画一覧)。
  bindPref($("src-stt"), "tictok.videos.srcStt");
  bindPref($("src-comment"), "tictok.videos.srcComment");
  bindPref($("flt-review"), "tictok.videos.reviewFilter");
  bindPref($("flt-mode"), "tictok.videos.searchMode");
  bindPref($("flt-order"), "tictok.videos.searchOrder");
  // 笑い声の並替は語の検索とは選択肢が違うので別key。同じkeyを共有すると、片方の値
  // (関連度順・強い順)がもう片方の選択肢に無く、復元が「初期化されたように見える」。
  bindPref($("flt-laugh-order"), "tictok.videos.laughOrder");
  // 録画一覧の並替も別key。こちらは録画1本ごとの値(笑い声の合計)で並ぶので、シーンの
  // 一覧(強い順・長い順)ともう一方の選択肢が噛み合わない。
  bindPref($("flt-browse-order"), "tictok.videos.browseOrder");
  // 一括処理の配信者も検索側と同じ値を共有する。selectの選択肢はtabを開いた時に埋まるので
  // 値だけを先に入れる(hash遷移で配信者を渡された場合は、この後でそちらが上書きする)。
  state.bulkOnly = prefGet(STREAMER_PREF_KEY) || null;
  // 再生・編集の設定。倍率は録画を開くたびapplyRateが<video>へ入れ直す。
  bindPref($("play-rate"), PLAY_RATE_PREF_KEY);
  bindPref($("snap-seg"), "tictok.videos.snapSegments");
  bindPref($("transcript-follow"), "tictok.videos.transcriptFollow");
  bindPref($("comment-follow"), "tictok.videos.commentFollow");
  // 追従を入れ直した時は、そこまで積んだ最新の行が見えるよう下端へ戻す。
  bindPref($("pk-follow"), "tictok.videos.pkFollow", () => stickPkGiftsToBottom());
  // 文字起こし・コメント・PKの折り畳み。buttonなのでbindPrefのcontrolには載らない。
  bindFoldBlocks();
  // 開閉した表示section。畳んだ節は次も畳んだまま開く。
  bindPref($("cuts-help-export"), "tictok.videos.cutsHelpExport");
  // 出力済みclipの絞り込み。選択肢は開いた時に埋まるので、値だけ先に戻して描画へ渡す
  // (実在しない配信者が残っていればselectは「全て」へ落ちる)。
  bindPref($("clips-root"), "tictok.videos.clipsRoot", () => renderClipFiles());
  bindPref($("clips-streamer"), "tictok.videos.clipsStreamer", () => renderClipFiles());
  bindPref($("clips-kind"), "tictok.videos.clipsKind", () => renderClipFiles());
  bindPref($("clips-help-layout"), "tictok.videos.clipsHelpLayout");
  // グループ操作tabの絞り込み。左右のpaneが指すグループは選択肢を後から作るので、
  // bindPrefではなく起動時にstateへ直接戻す(GOPS_PREF_KEYS)。
  bindPref($("gops-filter"), "tictok.videos.gopsFilter");
  bindPref($("gops-help-shelf"), "tictok.videos.gopsHelpShelf");
}

function bind() {
  SEGMENTED.forEach(initSegmented);
  bindDisplayPrefs();
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
  ["src-stt", "src-comment", "flt-streamer", "flt-order", "flt-laugh-order",
    "flt-mode"].forEach((id) => $(id).addEventListener("change", () => runSearch(true)));
  // 録画一覧の並替は受け取り済みの一覧の上で行う(確認状態の絞り込みと同じ)。runSearchを
  // 通すと全録画の実体走査が並べ替えのたびに走る。
  $("flt-browse-order").addEventListener("change", () => {
    if (state.browsing) applyBrowseFilter();
  });
  $("flt-mode").addEventListener("change", () => loadSemantic());
  STREAMER_SELECTS.forEach((id) =>
    $(id).addEventListener("change", () => {
      shareStreamerSelection(id);
      // 3つのselectは同じ値を指すので、どれを操作しても1つのkeyへ残す。
      prefSet(STREAMER_PREF_KEY, $(id).value);
    }),
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
  $("do-still").addEventListener("click", runStill);
  // 出力済みclip。絞り込みの再描画はbindDisplayPrefs側(保存と同じ経路)が持つ。
  $("clips-reload").addEventListener("click", loadClipFiles);
  $("clip-file-close").addEventListener("click", closeClipFilePlayer);
  document.addEventListener("keydown", onKeydown);

  // key一覧は時間軸barの上へ重ねて開く。開きっぱなしだとbarを隠したままになるので、
  // 外を押した時点で畳む(閉じる場所を探させない)。
  const keyHelp = document.querySelector(".vd-keys");
  if (keyHelp) {
    document.addEventListener("click", (event) => {
      if (keyHelp.open && !keyHelp.contains(event.target)) keyHelp.open = false;
    });
  }

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

  // PK・ギフト: 見出しはそのPKの頭へ、ギフト行はその瞬間へ。PK外の案内buttonは自分で
  // 行き先を持つので、ここでは見出し(vd-pk-now-head)だけを拾う。
  $("pk-now").addEventListener("click", (event) => {
    if (!event.target.closest(".vd-pk-now-head")) return;
    const battle = battleAtTime(video.currentTime);
    if (battle) video.currentTime = battle.start;
  });
  $("pk-gift-list").addEventListener("click", (event) => {
    const row = event.target.closest(".vd-gift");
    if (row) video.currentTime = state.gifts[Number(row.dataset.index)].t;
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
    syncPkPanel();
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
    resizeTimer = setTimeout(() => {
      drawTimeline();
    }, RESIZE_DEBOUNCE_MS);
  });

  $("do-transcribe").addEventListener("click", transcribeCurrent);
  Object.entries(RECORDING_JOBS).forEach(([kind, spec]) =>
    $(spec.button).addEventListener("click", () => startRecordingJob(kind)),
  );
  // 素材版は再生にも効く。見どころtab側から写ってきた値はsetter経由で入るため
  // changeが出ない。あちらにも受け口を置く(syncClipControlsは何度呼んでも同じ)。
  $("clip-variant").addEventListener("change", () => reloadPlayback(true));
  $("cuts-variant").addEventListener("change", () => {
    syncClipControls(true);
    reloadPlayback(true);
  });

  // pointer captureで、bar外へ出てもdragが続く(長時間録画を粗く送るときに切れない)。
  // 波形は初回生成が長いが、無音snap・シーン選択の土台なので既定ON(明示的に切れば記憶する)。
  const showWave = $("show-wave");
  // 既定ONはprefBoolのfallbackで名乗る(markupは未checkのまま)。bindPrefの復元は保存が
  // 無いときは何もしないので、この既定はそのまま残る。
  showWave.checked = prefBool(WAVE_PREF_KEY, true);
  bindPref(showWave, WAVE_PREF_KEY, () => {
    if (state.current) loadWaveform(state.current.recording_id);
    else drawTimeline();
  });

  // giftのiconも既定ON(heatの金色の柱が何だったのかを読む手掛かりで、引くのは軽い)。
  // 波形と同じく、切れば記憶する。切り替えても引き直さない — giftはPK・ギフトpanelが
  // 常に使うので既に手元にあり、ここで決まるのは時間軸へ載せるかどうかだけ。
  const showGifts = $("show-gifts");
  showGifts.checked = prefBool(GIFT_PREF_KEY, true);
  bindPref(showGifts, GIFT_PREF_KEY, () => {
    giftLayout = null;
    drawTimeline();
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

  $("cuts-export").addEventListener("click", exportCuts);
  $("cuts-reel").addEventListener("click", makeReel);
  // 下見は結果そのものが成果なので、押したときだけtoastでも出す(makeWork内の下見は
  // 続けて投入のtoastが出るため、同じ内容を二重に積まない)。
  $("cuts-plan").addEventListener("click", () => previewWork(true));
  $("cuts-work").addEventListener("click", makeWork);
  loadWorkPresets();
  // 選択と一括削除。所属の付け替えは行のグループ欄と上段tabへのドラッグが持つ。
  $("cuts-dup-select").addEventListener("click", selectExtraMarks);
  $("marks-select-all").addEventListener("change", () => {
    if ($("marks-select-all").checked) {
      visibleMarks().forEach((mark) => state.marksSelected.add(mark.id));
    } else {
      state.marksSelected.clear();
    }
    state.lastPick.marks = null;
    renderMarks();
  });
  $("marks-bulk-delete").addEventListener("click", deleteSelectedMarks);
  $("cuts-clear").addEventListener("click", clearVisibleMarks);
  // 自動生成の行を出すかどうか。既定は出さない(人が付けた印と混ぜない)。
  $("marks-show-auto").addEventListener("change", () => {
    state.showAuto = $("marks-show-auto").checked;
    prefSet(SHOW_AUTO_PREF_KEY, state.showAuto ? "1" : "");
    // 隠れていた行が選択に残ったままだと、見えない行が書き出しの対象になる。
    state.lastPick.marks = null;
    renderMarksView();
  });
  // 見どころtabのplayer。範囲の終端で止めるのはtimeupdateで見る(seek済みの位置から
  // 飛び越えることがあるので、等号ではなく通過で判定する)。
  bindInlinePlayer("mark", markPlayer, (mark) => openMark(mark));
  // 観ている位置で端を決める2つ。時刻を打ち直すより速くて正しい。
  $("mark-play-setin").addEventListener("click", () => setMarkEdgeFromPlayer("in"));
  $("mark-play-setout").addEventListener("click", () => setMarkEdgeFromPlayer("out"));
  // グループのメモ。入力欄から離れた時点で確定する(打鍵ごとには投げない)。
  bindGroupMemo("marks-group-memo", "marks-status");
  bindGroupOps();
  bindClipControls();

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
      const text = "意味検索indexの構築を開始しました。進捗はJob画面で確認できます。";
      $("semantic-result").textContent = text;
      showToast(text, null, { title: "意味検索index", duration: JOB_TOAST_MS });
    } catch (err) {
      // #semantic-inlineは検索modeがsemanticのときしか出ない。押した後にmodeを戻すと、
      // ここへ書いた失敗は画面から消える(完了と失敗はWS側がtoastで出すのと同じ理由)。
      $("semantic-result").textContent = err.message;
      showError(err, "意味検索indexの構築");
    } finally {
      // finallyでないと、通信断や画面遷移でbuttonが押せないまま残る。
      // 再有効化の可否はserverのstatusに従う(別のbuildが走っている場合は塞いだまま)。
      button.disabled = false;
      loadSemantic();
    }
  });

  // 再出力の指定を変えたら、見せている見積りは別物になる。出したまま残すと「確認した内容」と
  // 「投入される内容」が食い違う。開いている録画一覧の可否も変わるので、開いたまま指定を
  // 変えたら取り直す。
  $("bulk-redo").addEventListener("change", async () => {
    hideBulkConfirm();
    state.bulkNote = "";
    renderBulk();
    if (!state.bulkOpen) return;
    const { uniqueId, kind } = state.bulkOpen;
    state.bulkOpenRows = null;
    renderBulk();
    try {
      await loadBulkRecordings(uniqueId, kind);
    } catch (err) {
      state.bulkOpenRows = false;
      state.bulkNote = err.message;
      showError(err, "録画一覧の取得");
    }
    renderBulk();
  });
  $("bulk-streamer").addEventListener("change", () => {
    hideBulkConfirm();
    closeBulkRows();
    renderBulk();
  });
}

// 切り出しの既定(音量正規化・方式)は設定画面が持つ。画面側にhard-codeしない。
async function loadClipDefaults() {
  try {
    const data = await apiSend("GET", "/api/settings");
    const byKey = new Map((data.settings || []).map((entry) => [entry.key, entry.value]));
    // 設定画面の値は「まだ選んでいない項目」の既定。この画面で選んだ値が残っていれば
    // そちらが今の指定なので上書きしない(選び直した方式が、後から届く応答で黙って戻る)。
    if (byKey.has("clip_normalize_audio") && prefGet(CLIP_PREF_KEYS.normalize_audio) === null) {
      $("clip-normalize").checked = Boolean(Number(byKey.get("clip_normalize_audio")));
    }
    if (byKey.has("clip_remove_bgm") && prefGet(CLIP_PREF_KEYS.remove_bgm) === null) {
      $("clip-nobgm").checked = Boolean(Number(byKey.get("clip_remove_bgm")));
    }
    if (byKey.has("clip_subtitles") && prefGet(CLIP_PREF_KEYS.subtitles) === null) {
      $("clip-subs").checked = Boolean(Number(byKey.get("clip_subtitles")));
    }
    const mode = byKey.get("clip_default_mode");
    if (mode && prefGet(CLIP_PREF_KEYS.mode) === null) {
      ["clip-mode", "cuts-mode"].forEach((id) => { $(id).value = String(mode); });
    }
    // 既定を当てた後は見どころtab側の同じ欄へも写す。写さないと、実際に使う値
    // (primary)とあちらに出ている値が食い違ったまま一括書き出しが走る。
    syncClipControls(false);
  } catch (err) {
    // 既定を当てられないと、切り出しの方式・正規化は画面の初期値のまま走る。設定画面で
    // 決めた値と違うもので書き出されるので、当てられなかったことを名乗る。
    $("player-status").textContent =
      `切り出しの既定を取得できませんでした（画面の初期値で動きます）: ${err.message}`;
    showError(err, "切り出しの既定の取得");
  }
}

function onMessage(message) {
  if (message.type === "semantic_index") {
    // 別tab/別clientが始めたbuildでも塞がるよう、開始と完了の両方で飛んでくる。
    renderSemantic(message.status);
    // 完了時だけresult、失敗時だけerrorが載る。応答を待たなくなったので、結果も失敗も
    // ここが唯一の出所(押した直後の「開始しました」を上書きしないと、死んでも気付けない)。
    // semantic-resultの親(#semantic-inline)はflt-modeがsemanticのときしか出ない。構築は
    // 最も長くかかる処理で、待つ間に検索modeを戻せば結果も失敗も見る手段が無くなる。
    if (message.error) {
      $("semantic-result").textContent = `意味検索indexの構築に失敗しました: ${message.error}`;
      showToast(message.error, "error", { title: "意味検索indexの構築" });
    } else if (message.result) {
      const text = `意味検索index: ${fmtNum(message.result.passages ?? 0)} passage / `
        + `${fmtNum(message.result.hits ?? 0)}件から構築しました。`;
      $("semantic-result").textContent = text;
      showToast(text);
    }
  } else if (message.type === "job_update" && message.job.domain === "clip_batch") {
    const job = message.job;
    if (job.state === "running") {
      $("cuts-status").textContent = `一括書き出し ${job.stage || ""} ${job.pct}%`.trim();
    } else if (job.state === "completed") {
      // 置き場まで言う。件数だけでは「どこに切り出されたか分からない」ままで、実際に
      // 成果物を探せなかった。出力先は配信者別で、rootは録画の所在によって変わる。
      const where = (job.result || {}).output_dir;
      const subs = (job.result || {}).subtitle_files || [];
      const subNote = subs.length
        ? ` 字幕file ${fmtNum(subs.length)}件も出しました。`
        : ((job.result || {}).subtitle_note ? ` ${job.result.subtitle_note}` : "");
      const text = `一括書き出しが終わりました（${fmtNum(job.result.count ?? 0)}件）。`
        + (where ? `出力先: ${where}` : "") + subNote;
      $("cuts-status").textContent = text;
      // cuts-statusは見どころtabの中で、他のviewへ移ると見えない。分単位で待つ処理なので
      // 待つ間に画面を離れるのが普通で、そこへだけ書くと終わったこと自体が届かない。
      showToast(text);
      // 書き出し済みの印を行へ反映する(serverが由来の行へ書き戻している)。
      loadMarks();
    } else if (job.state !== "pending") {
      $("cuts-status").textContent = `一括書き出し: ${job.message || job.state}`;
      showToast(job.message || job.state, "error", { title: "切り出しの一括書き出し" });
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
      const text = `${parts.join(" / ")}: ${r.output_path || r.filename || ""}`;
      $("cuts-status").textContent = text;
      showToast(text);
    } else if (job.state !== "pending") {
      $("cuts-status").textContent = `連結: ${job.message || job.state}`;
      showToast(job.message || job.state, "error", { title: "切り出しの連結" });
    }
  } else if (message.type === "job_update" && message.job.domain === "work") {
    const job = message.job;
    if (job.state === "running") {
      $("cuts-status").textContent = `作品 ${job.stage || ""} ${job.pct}%`.trim();
    } else if (job.state === "completed") {
      const r = job.result || {};
      // 指定尺と実尺を両方出す。間の詰めが効くと成果物は短くなるので、実尺だけを見せると
      // 「90秒のつもりが72秒」の理由が分からない。
      const parts = [`作品にしました（${fmtNum(r.scenes ?? 0)}シーン）`];
      if (r.requested_seconds != null) {
        parts.push(`指定尺 ${fmtDuration(r.requested_seconds)}`
          + ` − 詰め ${fmtDuration(r.tightened_seconds ?? 0)}`
          + ` ＝ 実尺 ${fmtDuration(r.output_duration_seconds ?? 0)}`);
      }
      // 検品に落ちても成果物は残る。合格していないことを名乗るだけで、消しはしない。
      if (r.gate_ok === false) {
        parts.push(`検品不合格: ${(r.gate_failures || []).join("、") || "理由不明"}`);
      }
      const text = `${parts.join(" / ")}: ${r.output_path || r.filename || ""}`;
      $("cuts-status").textContent = text;
      showToast(text, r.gate_ok === false ? "error" : undefined,
        { title: "作品の書き出し" });
    } else if (job.state !== "pending") {
      $("cuts-status").textContent = `作品: ${job.message || job.state}`;
      showToast(job.message || job.state, "error", { title: "作品の書き出し" });
    }
  } else if (message.type === "job_update" && message.job.domain === "still") {
    // スクショはどのtabからでも投げられる。押した場所の状態欄は投げた側が持っているが、
    // 完了は数秒後で、その頃には別のtabへ移っていることがある。結末はtabに依らず届く
    // toastを唯一の出所にし、状態欄はシーン検索側(押した直後の文面を上書きする場所)だけ
    // 面倒を見る。
    const job = message.job;
    if (job.state === "completed") {
      const r = job.result || {};
      // 要求どおりの位置で撮れないことがある(素材の映像がそこから始まっていない等)。
      // file名も画面も実際の位置で名乗るので、ずれた時はその事実を出す。
      const moved = r.requested_seconds !== null && r.requested_seconds !== undefined
        && r.at_seconds - r.requested_seconds > 0.3
        ? `（要求 ${fmtDuration(r.requested_seconds)} / 実際 ${fmtDuration(r.at_seconds)}）`
        : "";
      const text = `スクショを保存しました${moved}: ${r.output_path || r.filename || ""}`;
      setStillStatus(text);
      showToast(text);
      // 「出力済みclip」tabを開いたまま撮ったなら、撮った1枚がその場で並ぶ。
      if (!$("view-clips").classList.contains("hidden")) loadClipFiles();
    } else if (job.state !== "pending" && job.state !== "running") {
      setStillStatus(`スクショ: ${job.message || job.state}`);
      showToast(job.message || job.state, "error", { title: "スクショ" });
    }
  } else if (message.type === "job_update" && message.job.domain === "clip_overlay") {
    // 焼き込み切り抜きはこの画面から投げられるのに、受け口がどこにも無かった。完了しても
    // 画面は何も言わず、成果物(_clips の ....overlay.mp4)にも辿り着けなかった。
    const job = message.job;
    const status = $("player-status");
    if (job.state === "running") {
      status.textContent = `焼き込み切り抜き ${job.stage || ""} ${job.pct}%`.trim();
    } else if (job.state === "completed") {
      const r = job.result || {};
      const text = `焼き込み切り抜きができました: ${r.output_path || r.filename || ""}`;
      status.textContent = text;
      showToast(text);
      if (!$("view-clips").classList.contains("hidden")) loadClipFiles();
    } else if (job.state !== "pending") {
      status.textContent = `焼き込み切り抜き: ${job.message || job.state}`;
      showToast(job.message || job.state, "error", { title: "焼き込み切り抜き" });
    }
  } else if (message.type === "job_update" && BULK_DOMAIN_KINDS[message.job.domain]) {
    const job = message.job;
    const kind = BULK_DOMAIN_KINDS[job.domain];
    // 1本終わるたびに対象数が変わる。開いていないtabの引き直しは無駄なので出さない。
    // groupの行(recording_idを持たない集計行)は個別完了の後に来るだけなので無視する。
    if (job.state === "completed" && job.recording_id
        && !$("view-bulk").classList.contains("hidden")) {
      loadBulk();
    }
    // 一括投入は数十本を数時間かけて回す。完了しか見ていなかったため、途中の1本が落ちても
    // 画面はどこにも何も出さず、後でJob画面を開くまで失敗した事実が誰にも届かなかった。
    // 同じ文面は積まず回数だけ増えるので、まとめて落ちても画面は埋まらない。
    if (FAILED_JOB_STATES.includes(job.state) && job.recording_id) {
      showToast(job.message || job.state, "error", { title: `一括${BULK_LABELS[kind] || kind}` });
    }
    // 文字起こしが1本終わると検索対象が増える。開いている検索結果と、開いたままの録画の
    // 文字起こしを追従させる(以前はこれを別種のWS通知に頼っており、その通知はもう飛ばない)。
    if (kind === BULK_TRANSCRIBE_KIND && job.state === "completed" && job.recording_id) {
      if (state.query) runSearch(true);
      if (state.current && state.current.recording_id === job.recording_id) {
        loadTranscript(job.recording_id);
      }
    }
    // 開いている録画のjobなら、素材版の在り方が変わるのでplayer側にも反映する。
    if (state.current && job.recording_id === state.current.recording_id) {
      onRecordingJobUpdate(job);
    }
  } else if (message.type === "transcribe_progress") {
    // noteは再試行待ちのときだけ載る。%は動かないので、これが無いと固まって見える。
    const label = message.note || `文字起こし中 ${message.pct}%`;
    // 進捗そのものの置き場はJob画面。ここで出すのは再生中の録画のぶんだけで、この画面が
    // 台帳の縮小版を持たないのと同じ理由(2箇所に出すとどちらが今なのか読めない)。
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
// 記録先は録画を跨いで使い回す。読み直す前に入れておかないと、起動直後の1件だけが
// 前回のグループではなく未分類へ落ちる。
state.addGroup = loadAddGroupPref();
// 「表示するグループ」も同じく残す。指す先が消えていた場合は、loadMarksの中の
// refreshGroupDataが「全て」へ戻す。
state.groupSel = prefGet(GROUP_FILTER_PREF_KEY) || "";
// 自動生成の行を出すか。checkboxの初期値もここで揃える(既定は出さない)。
state.showAuto = Boolean(prefGet(SHOW_AUTO_PREF_KEY));
$("marks-show-auto").checked = state.showAuto;
// グループ操作tabの左右も同じく残す。指す先が消えていればrefreshGroupDataが未分類へ戻す。
// 右の既定を未分類にしているのは、左(全て)から拾って行き先へ入れるのが基本の流れのため。
GOPS_SIDES.forEach((side) => {
  const saved = prefGet(GOPS_PREF_KEYS[side]);
  if (saved !== null) state.gops[side] = saved;
});
// 他画面からの遷移先。tabを自分で探させない。#transcribe は「一括文字起こし」tabが
// 独立していた頃の名前で、外部linkが今も使うので別名として残す。
// #cuts は切り出しリストtabが独立していた頃の名前で、外部linkが今も使うので
// 統合先(見どころ)の別名として残す。
const HASH_VIEWS = { "#transcribe": "bulk", "#jobs": "bulk", "#bulk": "bulk",
  "#marks": "marks", "#cuts": "marks", "#groups": "groups", "#search": "search" };
const bootView = HASH_VIEWS[location.hash];
if (bootView) {
  // 配信者画面からの遷移は1人ぶんの容量整理の最中なので、同じ配信者を選んだ状態で入れる。
  // 解除しても同じ画面のselectで戻せる(以前は配信者画面へ戻り直すしかなかった)。
  // 表示の前に決める — showViewが走らせるloadBulkが、この値で絞った表を描く。
  if (location.hash === "#bulk") {
    state.bulkOnly = new URLSearchParams(location.search).get("streamer") || null;
  }
  showView(bootView);
} else {
  // 前回見ていたtabで始める。他画面からのhash遷移は行き先の明示なので、そちらが優先。
  const savedView = prefGet(VIEW_PREF_KEY);
  if (savedView && VIEWS.includes(savedView)) showView(savedView);
}
// 配信者selectの名簿でもあるので、一括処理tabを開いていなくても起動時に引く。
const statusLoaded = loadBulk();
loadSemantic();
loadClipDefaults();
// 開いた時点で録画一覧を出す。語なしの一覧はrunSearchが担うが、起動時は誰も呼ばないため
// 「検索語を入力してください」のまま止まり、当たる語を先に発明しないと1本も開けなかった
// (確認状態の印も、一覧が出ていなければ目に入らない)。
// 配信者の絞り込みを残している場合だけ、その復元(選択肢を埋めるloadBulkの中で起きる)を
// 待ってから引く。先に引くと、絞り込み前の全録画一覧を引いた後で絞った一覧をもう一度
// 引くことになり、この一覧は全録画の実体走査を伴う。
// 待つのは復元の機会を作るためだけなので、loadBulkが転んでも一覧は引く(finallyなので
// 失敗はそのまま外へ出る — 握って隠さない)。
if (prefGet(STREAMER_PREF_KEY)) statusLoaded.finally(() => runSearch(true));
else runSearch(true);
// player直下の「この録画の見どころ」と記録先chipは見どころ一覧・グループ一覧を使う。
// tabを開くまで読まないと、録画を開いた直後だけ空の一覧になる。
loadMarks();
connectWS(onMessage);
