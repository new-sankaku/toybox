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

const state = {
  query: "",
  offset: 0,
  total: 0,
  hits: [],
  hitIndex: -1,
  current: null,
  cutIn: null,
  cutOut: null,
  heat: null,
  wave: null,
  sprite: null,
  variants: [],
  streamers: [],
  segments: [],
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

const VIEWS = ["search", "marks", "candidates", "cuts", "jobs"];

function showView(name) {
  VIEWS.forEach((view) => {
    $(`view-${view}`).classList.toggle("hidden", view !== name);
    $(`tab-${view}`).classList.toggle("active", view === name);
  });
  if (name === "jobs") loadStatus();
  if (name === "cuts") loadCuts();
  if (name === "marks") loadMarks();
  if (name === "candidates") loadCandidates();
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
  if (!query || !sources.length) {
    state.hits = [];
    state.total = 0;
    renderHits();
    $("search-summary").textContent = "";
    setListMessage($("hit-empty"), sources.length
      ? "検索語を入力してください。"
      : "検索対象（音声／コメント）を選んでください。");
    return;
  }
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
  setListMessage($("hit-empty"), "該当するシーンがありません。複数語のANDは1つの発話・コメントの中で判定されます。");
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

function renderHits() {
  renderTableRows(
    "hit-rows",
    "hit-empty",
    state.hits,
    (hit) => {
      const kind = document.createElement("span");
      kind.className = hit.source === "stt" ? "vd-src vd-src-stt" : "vd-src vd-src-comment";
      kind.textContent = hit.source === "stt" ? "音声" : "コメント";
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

async function openHit(hit, index) {
  const video = $("video");
  const sameRecording = state.current && state.current.recording_id === hit.recording_id;
  state.current = hit;
  if (index !== undefined) {
    state.hitIndex = index;
    highlightHitRow();
  }
  $("player-head").textContent =
    `${hit.unique_id} / ${fmtDateTime(hit.started_at)} / ${fmtDuration(hit.video_time)}`;
  $("player-status").textContent = "";

  if (!sameRecording) {
    // 別録画に移ったらIN/OUTは持ち越さない(別fileの秒数として無意味になるため)。
    setCut(null, null);
    state.heat = null;
    // 別録画の候補は秒数として無意味なので持ち越さない。
    state.candidates = [];
    state.candidateRecordingId = null;
    // 転写の有無はloadTranscriptが確定させる。それまでは押せない状態にしておく。
    $("do-transcribe").disabled = true;
    drawHeat();
    video.src = `/api/recordings/${hit.recording_id}/play`;
    video.addEventListener(
      "loadedmetadata",
      () => {
        video.currentTime = hit.video_time;
        drawHeat();
      },
      { once: true },
    );
    loadHeat(hit.recording_id);
    loadPaths(hit.recording_id);
    loadTranscript(hit.recording_id);
    loadComments(hit.recording_id);
    loadBookmarks(hit.recording_id);
    loadThumbnails(hit.recording_id);
    loadWaveform(hit.recording_id);
  } else {
    video.currentTime = hit.video_time;
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

async function loadPaths(recordingId) {
  const select = $("path-variant");
  select.innerHTML = "";
  state.variants = [];
  // 選択肢が無い間は空箱を出さない。録画を開く前や派生fileが1つも無いときは、
  // copy対象を選ぶ余地が無いので選択肢欄そのものを出す意味が無い。
  select.classList.add("hidden");
  try {
    const data = await apiSend("GET", `/api/recordings/${recordingId}/path`);
    state.variants = data.variants || [];
  } catch (err) {
    $("player-status").textContent = err.message;
    return;
  }
  const labels = { source: "録画本体", overlay: "焼き込み済", upscaled: "高画質化済" };
  state.variants.forEach((variant) => {
    const option = document.createElement("option");
    option.value = variant.path;
    option.textContent = labels[variant.kind] || variant.kind;
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
  $("transcript-note").textContent = "文字起こしの順番待ちに入れています…";
  try {
    const result = await apiSend("POST", "/api/transcribe/queue", {
      recording_ids: [recordingId],
    });
    renderQueue(result.queue);
    $("transcript-note").textContent = result.added
      ? "順番待ちに入れました。終わり次第ここに反映されます。"
      : "既に順番待ちか処理済みです。";
  } catch (err) {
    $("transcript-note").textContent = err.message;
    button.disabled = false;
  }
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

function highlightActiveSegment() {
  const rows = $("segments").children;
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
  for (let i = 0; i < rows.length; i += 1) {
    rows[i].classList.toggle("vd-seg-active", i === active);
  }
  if (active >= 0) rows[active].scrollIntoView({ block: "nearest" });
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
    : "コメントがないか、検索indexが未構築です。";
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
    // このコメント自体が見どころの根拠になるので、本文をそのままmemoの初期値にして残す。
    const mark = document.createElement("button");
    mark.className = "vd-cmt-mark";
    mark.type = "button";
    mark.textContent = "★";
    mark.title = "この位置を見どころに記録";
    row.append(time, who, body, mark);
    fragment.appendChild(row);
  });
  container.appendChild(fragment);
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
  const rows = $("comments").children;
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
  if ($("comment-follow").checked) row.scrollIntoView({ block: "nearest" });
}

// ===== 見どころ(bookmark) =====
// cut listが「書き出す素材」なのに対し、こちらは「後でまた見たい場所」。点でも範囲でも
// 残せて、seek bar上のmarkerとして常に見えることで、同じ録画を開き直した時に辿り着ける。

async function loadBookmarks(recordingId) {
  state.bookmarks = [];
  drawHeat();
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
  loadBookmarks(state.current.recording_id);
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
function clipOptions() {
  return {
    variant: $("clip-variant").value,
    normalize_audio: $("clip-normalize").checked,
    precise: $("clip-precise").checked,
  };
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
    $("player-status").textContent = `出力: ${result.path}`;
    await copyText(result.path, "切り出しpathをcopyしました。");
  } catch (err) {
    $("player-status").textContent = err.message;
  }
  button.disabled = false;
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
  renderCuts();
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
      remove.addEventListener("click", async () => {
        await apiSend("DELETE", `/api/cutlist/${cut.id}`);
        loadCuts();
      });
      return [
        cut.unique_id,
        cut.filename || "-",
        fmtDuration(cut.start),
        fmtDuration(cut.end),
        fmtDuration(cut.end - cut.start),
        cut.label || "",
        remove,
      ];
    },
    [2, 3, 4],
  );
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

function renderCandidates() {
  const empty = $("cand-empty");
  empty.textContent = state.current
    ? "候補がありません。設定でしきい値を下げると増えます。"
    : "シーン検索で録画を開いてください。";
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
        candidate.metric === "diamonds" ? "ダイヤ" : "コメント",
        candidate.zscore.toFixed(1),
        fmtNum(candidate.diamonds),
        fmtNum(candidate.comments),
        actions,
      ];
    },
    [0, 1, 2, 4, 5, 6],
  );
}

async function openCandidate(candidate) {
  if (!state.current) return;
  showView("search");
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
      `${fmtNum(result.total)}件を${fmtNum(result.jobs.length)}個のjobで書き出します（job画面で進み具合を確認できます）。`;
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
  [$("flt-streamer"), $("job-streamer")].forEach((select) => {
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

const QUEUE_LABELS = {
  running: "実行中",
  pending: "待機",
  done: "完了",
  failed: "失敗",
  cancelled: "取消",
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
      item.state === "running" ? `${item.pct}%` : (item.state === "done" ? "100%" : "-"),
      item.error || "",
    ],
    [3],
  );
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

// ===== 起動 =====

function bind() {
  VIEWS.forEach((view) => $(`tab-${view}`).addEventListener("click", () => showView(view)));

  $("q").addEventListener("input", scheduleSearch);
  ["src-stt", "src-comment", "flt-streamer", "flt-order", "flt-mode"].forEach((id) =>
    $(id).addEventListener("change", () => runSearch(true)),
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

  $("comments").addEventListener("click", (event) => {
    const row = event.target.closest(".vd-cmt");
    if (!row) return;
    const comment = state.comments[Number(row.dataset.index)];
    if (event.target.closest(".vd-cmt-mark")) {
      const memo = comment.nickname ? `${comment.nickname}: ${comment.body}` : comment.body;
      saveBookmark(comment.t, null, memo, comment.id ?? null);
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

  const onTick = () => {
    loopRange();
    drawHeat();
    updateTimeLabel();
    highlightActiveSegment();
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

  $("cuts-csv").addEventListener("click", () => {
    window.location.href = "/api/cutlist/export?format=csv";
  });
  $("cuts-edl").addEventListener("click", () => {
    window.location.href = "/api/cutlist/export?format=edl";
  });
  $("cuts-export").addEventListener("click", exportCuts);
  $("cand-reload").addEventListener("click", loadCandidates);
  $("cand-add-all").addEventListener("click", async () => {
    const button = $("cand-add-all");
    button.disabled = true;
    for (const candidate of state.candidates) await addCandidate(candidate);
    $("cand-summary").textContent = `${fmtNum(state.candidates.length)}件を切り出しリストへ追加しました。`;
    button.disabled = false;
  });
  $("cuts-clear").addEventListener("click", async () => {
    await apiSend("DELETE", "/api/cutlist");
    loadCuts();
  });

  $("semantic-build").addEventListener("click", async () => {
    const button = $("semantic-build");
    button.disabled = true;
    $("job-summary").textContent = "意味検索indexを更新中…";
    try {
      const result = await apiSend("POST", "/api/search/semantic/build");
      $("job-summary").textContent =
        `意味検索index: ${fmtNum(result.passages ?? 0)} passage / ${fmtNum(result.hits ?? 0)}件から構築しました。`;
    } catch (err) {
      $("job-summary").textContent = err.message;
    }
    button.disabled = false;
  });

  $("job-enqueue").addEventListener("click", () => enqueue($("job-streamer").value));
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

// 音量正規化の既定は設定画面が持つ。画面側にhard-codeしない。
async function loadClipDefaults() {
  try {
    const data = await apiSend("GET", "/api/settings");
    const item = (data.settings || []).find((entry) => entry.key === "clip_normalize_audio");
    if (item) $("clip-normalize").checked = Boolean(Number(item.value));
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
  } else if (message.type === "job_update" && message.job.domain === "clip_batch") {
    const job = message.job;
    if (job.state === "running") {
      $("cuts-status").textContent = `一括書き出し ${job.stage || ""} ${job.pct}%`.trim();
    } else if (job.state === "completed") {
      $("cuts-status").textContent = `一括書き出しが終わりました（${fmtNum(job.result.count ?? 0)}件）。`;
    } else if (job.state !== "pending") {
      $("cuts-status").textContent = `一括書き出し: ${job.message || job.state}`;
    }
  } else if (message.type === "transcribe_progress") {
    const summary = $("job-summary");
    if (message.pct < 100) summary.textContent = `文字起こし中 ${message.pct}%`;
    // 再生中の録画の進捗は、jobs tabを開かなくても分かるようplayer側にも出す。
    if (state.current && state.current.recording_id === message.recording_id
        && message.pct < 100) {
      $("transcript-note").textContent = `文字起こし中 ${message.pct}%`;
    }
  }
}

bind();
loadStatus();
loadClipDefaults();
connectWS(onMessage);
