"use strict";

let streamers = [];
let selectedUid = null;
let trendChart = null;
let cohortChart = null;
let whaleChart = null;
let currentHeatmap = [];
// 推移の単位切替は取得済みのsessionを描き直すだけ(profileの再取得は要らない)。
let currentSessions = [];
// 同接の水準(通算の時間加重平均・宝箱窓を除いた平均・宝箱の収集開始)。
let currentViewerLevel = null;
let aiConfigured = false;
// 「未設定」と「確かめられなかった」を分けて持つ。status取得が落ちただけの状態を
// 未設定と名乗ると、確認できていない事実を断定することになる。
let aiStatusKnown = false;
// Battle詳細modalが使うowner(自陣host)。renderProfileのidentityを保持する。
let currentIdentity = null;

const elSearch = document.getElementById("sm-search");
const elHmMetric = document.getElementById("sm-hm-metric");
const elTrendUnit = document.getElementById("sm-trend-unit");

// 画面はnav遷移ごとにfull reloadされる。毎回選び直すことになる表示設定(選択中の配信者・
// 色の指標・対戦相手の絞込と並び・再生音量)だけをlocalStorageへ残す。
const PREF_SELECTED = "tictok.streamers.selected";
const PREF_HM_METRIC = "tictok.streamers.heatmapMetric";
const PREF_TREND_UNIT = "tictok.streamers.trendUnit";
const PREF_BATTLE_TREND_X = "tictok.streamers.battleTrendX";
const PREF_BATTLE_TREND_Y = "tictok.streamers.battleTrendY";
const PREF_OPP_MIN = "tictok.streamers.opponentMin";
const PREF_OPP_SORT = "tictok.streamers.opponentSort";
const PREF_VIDEO_VOLUME = "tictok.streamers.videoVolume";
const PREF_VIDEO_MUTED = "tictok.streamers.videoMuted";

// ---- 左: 配信者リスト ----
async function loadStreamers() {
  let payload;
  try {
    payload = await apiSend("GET", "/api/streamers");
  } catch (err) {
    // 握りつぶすと一覧が空のままになり、placeholderの「配信者がいません。」が
    // 取得失敗を0件として提示してしまう。
    setListState(document.getElementById("sm-list-empty"), "failed", err);
    return;
  }
  streamers = payload.streamers || [];
  renderList();
  // 初期選択: URLの ?uid= があればそれ、次に前回選んでいた配信者、無ければ先頭。
  // 前回の配信者が監視から外れている場合は一覧に居ないので先頭へ落ちる。
  const wanted = new URLSearchParams(location.search).get("uid");
  const saved = prefGet(PREF_SELECTED);
  const target =
    (wanted && streamers.find((s) => s.unique_id === wanted))
    || (saved && streamers.find((s) => s.unique_id === saved));
  if (!selectedUid) selectStreamer((target || streamers[0] || {}).unique_id);
}

function renderList() {
  const q = elSearch.value.trim().toLowerCase();
  const list = document.getElementById("sm-list");
  const rows = streamers.filter((s) => {
    if (!q) return true;
    return `${s.unique_id} ${s.nickname}`.toLowerCase().includes(q);
  });
  list.innerHTML = "";
  setListState(document.getElementById("sm-list-empty"), rows.length > 0 ? "ok" : "empty");
  rows.forEach((s) => {
    const item = document.createElement("button");
    item.className = "sm-item" + (s.unique_id === selectedUid ? " sel" : "");
    item.appendChild(userCell(s, { stackId: true }));
    const meta = document.createElement("span");
    meta.className = "sm-item-meta";
    meta.innerHTML =
      `<span class="v">${fmtCompact(s.diamonds)}</span><span class="l">コイン</span>`
      + `<span class="v">${fmtNum(s.sessions)}</span><span class="l">配信</span>`
      + `<span class="v">${fmtPercent(s.liver_coin_share)}</span>`
      + `<span class="l">ライバー/コイン</span>`
      + `<span class="v">${fmtPercent(s.liver_gifter_share)}</span>`
      + `<span class="l">ライバー/人数</span>`;
    meta.title = liverTitle(s);
    item.appendChild(meta);
    item.addEventListener("click", () => selectStreamer(s.unique_id));
    list.appendChild(item);
  });
}

// ---- 右: 配信者プロファイル ----
// light=true は収集中の live 更新で profile だけ貼り替える時。コホート/ハイライトは
// bucket全走査で重く、毎tick再計算は不要なため、手動選択時(light=false)のみ取得する。
async function selectStreamer(uid, light = false) {
  if (!uid) return;
  // 収集中のlive更新でも同じuidで呼ばれる。実際に選び直した時だけ書く。
  if (uid !== selectedUid) {
    prefSet(PREF_SELECTED, uid);
    // 期間の一覧も順位も配信者ごと。持ち越すと別人の期間が選ばれたまま描かれる。
    rankingCache.clear();
    Object.values(rankingPick).forEach((pick) => { pick.period = ""; });
  }
  selectedUid = uid;
  renderList();
  let profile;
  try {
    profile = await apiSend("GET", `/api/streamers/${encodeURIComponent(uid)}/profile`);
  } catch (err) {
    // 一覧の選択は既にuidへ移っているため、握りつぶすと直前の配信者の数値が
    // 新しい選択のものとして残る。表示を畳んで取得失敗だと明示する。
    if (selectedUid !== uid) return;
    document.getElementById("sm-body").classList.add("hidden");
    const ph = document.getElementById("sm-placeholder");
    ph.classList.remove("hidden");
    ph.textContent = `@${uid} のプロファイルを取得できませんでした。${errorDetailText(err)}`;
    return;
  }
  if (selectedUid !== uid) return;
  renderProfile(profile);
  if (!light) {
    resetAiReview();
    loadCohort(uid);
    // 人×日はBattle窓の解決を含むので、liveの定期更新(light)では引き直さない。
    loadMatrix(uid);
  }
}

// ---- AI 講評（配信者集約→自然言語） ----
async function loadAiStatus() {
  try {
    const res = await fetch("/api/ai/status");
    if (!res.ok) throw new Error(`AIの状態を取得できませんでした（HTTP ${res.status}）。`);
    const st = await res.json();
    aiConfigured = Boolean(st.configured);
    aiStatusKnown = true;
    document.getElementById("sm-ai-note").textContent = st.configured
      ? `model: ${st.model}`
      : st.enabled
        ? "model未設定 (TICTOK_AI_MODEL)"
        : "AI無効 (TICTOK_AI_ENABLED=1)";
    // status取得はloadStreamers/初回selectより後に解決し得る。確定後にbutton状態を
    // 同期する（この時点では結果は未生成なので消去の副作用はない）。
    if (selectedUid) resetAiReview();
  } catch (err) {
    aiConfigured = false;
    aiStatusKnown = false;
    document.getElementById("sm-ai-note").textContent = "AIの状態を確認できませんでした。";
    document.getElementById("sm-ai-note").title = errorDetailText(err);
    if (selectedUid) resetAiReview();
  }
}

// 講評はserverのai_analysis表へ保存される。配信者を選んだときはGETで保存済みだけを読み
// (LLMは走らない)、生成はbutton(POST)でのみ行う。「再講評」は集約dataが同じでも作り直す。
function renderAiMeta(payload) {
  const meta = document.getElementById("sm-ai-meta");
  if (!payload || !payload.computed_at) {
    meta.textContent = "";
    return;
  }
  meta.textContent = `分析日時: ${fmtDateTime(payload.computed_at)}`
    + ` / model: ${payload.model || "-"} / prompt版: ${payload.prompt_version}`;
}

function resetAiReview() {
  const btn = document.getElementById("sm-ai-btn");
  btn.disabled = !aiConfigured;
  btn.textContent = "講評する";
  btn.classList.remove("hidden");
  document.getElementById("sm-ai-rerun").classList.add("hidden");
  document.getElementById("sm-ai-status").textContent = aiConfigured
    ? ""
    : aiStatusKnown
      ? "ローカルAIが未設定のため利用できません。"
      : "AIの状態を確認できないため、講評を実行できません。";
  document.getElementById("sm-ai-meta").textContent = "";
  const res = document.getElementById("sm-ai-result");
  res.classList.add("hidden");
  res.innerHTML = "";
  loadStoredAiReview();
}

async function loadStoredAiReview() {
  if (!selectedUid) return;
  const uid = selectedUid;
  let payload;
  try {
    const res = await fetch(`/api/streamers/${encodeURIComponent(uid)}/ai-review`);
    if (!res.ok) throw new Error(`保存済みの講評を読めませんでした（HTTP ${res.status}）。`);
    payload = await res.json();
  } catch (err) {
    // 「まだ講評していない」と「保存済みを読めなかった」が同じ見た目になると、読めなかった
    // だけなのに講評を作り直させることになる(LLMが走る)。
    if (selectedUid === uid) {
      document.getElementById("sm-ai-status").textContent = errorDetailText(err);
    }
    return;
  }
  if (selectedUid !== uid || !payload.review) return;
  renderAiReview(payload.review);
  renderAiMeta(payload);
  document.getElementById("sm-ai-btn").classList.add("hidden");
  const rerun = document.getElementById("sm-ai-rerun");
  rerun.classList.remove("hidden");
  rerun.disabled = !aiConfigured;
  if (payload.error) document.getElementById("sm-ai-status").textContent = payload.error;
}

async function runAiReview(refresh) {
  if (!selectedUid || !aiConfigured) return;
  const uid = selectedUid;
  const btn = document.getElementById("sm-ai-btn");
  const rerun = document.getElementById("sm-ai-rerun");
  const status = document.getElementById("sm-ai-status");
  btn.disabled = true;
  rerun.disabled = true;
  status.textContent = "ローカルAIで講評を生成しています（modelにより数十秒かかることがあります）…";
  try {
    const payload = await apiSend(
      "POST",
      `/api/streamers/${encodeURIComponent(uid)}/ai-review${refresh ? "?refresh=1" : ""}`,
    );
    if (selectedUid !== uid) return;
    renderAiReview(payload.review || {});
    renderAiMeta(payload);
    status.textContent = payload.cached
      ? "前回と同じ集約data・同じmodelのため、保存済みの講評を表示しました。"
      : "";
    btn.classList.add("hidden");
    rerun.classList.remove("hidden");
  } catch (err) {
    // 数十秒かかると自ら案内する操作なので、待つ間に別のsectionへスクロールしている。
    // 講評section内の1行だけだと、失敗したことに戻ってくるまで気付けない。
    status.textContent = err.message;
    showError(err, `@${uid} のAI講評`);
  } finally {
    btn.disabled = false;
    btn.textContent = "講評する";
    rerun.disabled = false;
  }
}

function renderAiReview(r) {
  const res = document.getElementById("sm-ai-result");
  res.innerHTML = "";
  if (r.summary) {
    const m = document.createElement("div");
    m.className = "ai-mood";
    m.textContent = r.summary;
    res.appendChild(m);
  }
  [["強み", r.strengths], ["課題", r.issues], ["改善提案", r.advice]].forEach(([label, items]) => {
    if (!Array.isArray(items) || !items.length) return;
    const h = document.createElement("div");
    h.className = "ai-sub";
    h.textContent = label;
    res.appendChild(h);
    const ul = document.createElement("ul");
    ul.className = "ai-hl";
    items.forEach((x) => {
      const li = document.createElement("li");
      li.textContent = x;
      ul.appendChild(li);
    });
    res.appendChild(ul);
  });
  res.classList.remove("hidden");
}

async function loadCohort(uid) {
  let data;
  try {
    const res = await fetch(`/api/streamers/${encodeURIComponent(uid)}/cohort`);
    if (selectedUid !== uid) return;
    if (!res.ok) throw new Error(`継続率を取得できませんでした（HTTP ${res.status}）。`);
    // 大口帯は日次コホートと同じ走査から返る(server側で1度に出す)ので、同じpayloadで描く。
    data = await res.json();
  } catch (err) {
    if (selectedUid !== uid) return;
    // 前の配信者のグラフを残すと、その数字が今開いている配信者のものとして読まれる
    // (見出しの「N日」「最大N人」まで前の人のものが残る)。畳んでから失敗を名乗る。
    renderCohort({});
    renderWhales({});
    showError(err, `@${uid} のファン継続率`);
    return;
  }
  renderCohort(data);
  renderWhales(data);
}

function renderProfile(p) {
  document.getElementById("sm-placeholder").classList.add("hidden");
  document.getElementById("sm-body").classList.remove("hidden");
  currentIdentity = p.identity;
  renderHead(p.identity, p.count);
  renderKpi(p);
  renderEngagement(p.totals);
  currentSessions = p.sessions || [];
  currentViewerLevel = p.viewer_level || null;
  renderTrend(currentSessions, currentViewerLevel);
  renderGrowth(currentSessions);
  currentHeatmap = p.heatmap || [];
  renderHeatmap();
  renderConcentration(p.concentration);
  currentGifters = p.gifters || [];
  currentBattleGifters = p.battles.gifters || [];
  renderLivers(p.livers || []);
  renderCoop(p.coop);
  renderBattle(p.battles);
  renderBattleTrend(p.battles.history || []);
  // Gifter / Battle Gifterの2表は、選んでいる粒度に従って描く(既定は全期間=上の一覧)。
  renderRankings();
  // 配信者を選び直したら相手の絞込は持ち越さない(別人の相手で絞られたままになる)。
  pickedOpponent = null;
  renderOpponents(p.battles.opponents);
  renderBattleHistory(p.battles.history || []);
}

// エンゲージメント正規化: totals から算出(viewers=各SessionのPeak同接の総和、duration=総配信秒)。
// 規模の異なる配信者を「視聴者あたり」「時間あたり」で公平に比較するための指標。
function renderEngagement(t) {
  const hours = t.duration / 3600;
  const perViewer = (v) => (t.viewers > 0 ? v / t.viewers : 0);
  const perHour = (v) => (hours > 0 ? v / hours : 0);
  chipBar("sm-eng", [
    ["コイン / Peak視聴", fmtNum(Math.round(perViewer(t.diamonds)))],
    ["コメント / Peak視聴", perViewer(t.comments).toFixed(2)],
    ["コイン / 時間", fmtNum(Math.round(perHour(t.diamonds)))],
    ["コメント / 時間", fmtNum(Math.round(perHour(t.comments)))],
  ]);
}

// ---- ファン継続率(日次コホート) ----
// その日のActiveは「継続(前回配信日にも居た)」「復帰(以前は居たが前回は不在)」「新規」で
// 過不足なく分かれる。retainedはserverが持っているので、復帰だけを差で出す。
function cohortReturned(d) {
  return d.active - d.new - d.retained;
}

function renderCohort(data) {
  const days = data.days || [];
  document.getElementById("sm-cohort-empty").classList.toggle("hidden", days.length > 0);
  document.getElementById("sm-cohort-note").textContent = days.length ? `${days.length}日` : "";
  cohortChart.update(days);
}

// ---- 録画の再生(Battle履歴から該当場面へ) ----
// 再生中の録画。errorの理由をserverへ問い合わせる間に別の録画へ移ることがあるため、
// 到達時の対象と突き合わせる。
let playingRecordingId = null;

// 素材(.ts)が残っている録画はHLSで直接観る。mp4しか残っていない録画はmp4を観る。どちらに
// なるかはserverが録画ごとの実物を見て決めるので、こちらは受け取った経路で読み込む。
let hlsPlayer = null;

function detachHls() {
  if (!hlsPlayer) return;
  hlsPlayer.destroy();
  hlsPlayer = null;
}

// 再生できなかった理由を、再生boxの同じ場所に出す。再生できた/できなかったを利用者が
// 1か所で読めるようにするため、失敗も動画と同じ枠へ出す。
function showVideoMessage(label, text) {
  const box = document.getElementById("sm-video-box");
  document.getElementById("sm-video-title").textContent = label;
  document.getElementById("sm-video-message").textContent = text;
  box.classList.remove("hidden");
  box.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

async function openVideo(recordingId, offset, label) {
  const box = document.getElementById("sm-video-box");
  const video = document.getElementById("sm-video");
  const message = document.getElementById("sm-video-message");
  document.getElementById("sm-video-title").textContent = label;
  message.textContent = "";
  playingRecordingId = recordingId;
  detachHls();
  box.classList.remove("hidden");
  box.scrollIntoView({ block: "nearest", behavior: "smooth" });
  let playback;
  try {
    playback = await apiSend("GET", `/api/recordings/${recordingId}/playback`);
  } catch (err) {
    message.textContent = err.message;
    return;
  }
  // 待っている間に別の録画へ移っていたら、こちらは古い。上書きしない。
  if (playingRecordingId !== recordingId) return;
  if (playback.mode === "hls" && window.Hls && window.Hls.isSupported()) {
    hlsPlayer = new window.Hls();
    hlsPlayer.loadSource(playback.url);
    hlsPlayer.attachMedia(video);
    hlsPlayer.on(window.Hls.Events.ERROR, (_e, data) => {
      // hls.jsが握った失敗は<video>のerror eventにならないので、ここで理由を出す。
      if (data.fatal && playingRecordingId === recordingId) {
        message.textContent = "この録画を再生できませんでした。";
      }
    });
  } else if (playback.mode === "hls" && !video.canPlayType("application/vnd.apple.mpegurl")) {
    message.textContent = "このBrowserはHLS再生に対応していません。";
    return;
  } else {
    video.src = playback.url;
  }
  // メタデータ確定後に急増点へseekして再生。HLSのcurrentTimeはplaylistのEXTINF累積で、
  // mp4のmedia軸と同じ秒数なので、offsetはどちらの経路でもそのまま使える。
  const seek = () => {
    try { video.currentTime = offset; } catch (e) { /* seek不可でも先頭から再生 */ }
    video.play().catch(() => {});
    video.removeEventListener("loadedmetadata", seek);
  };
  video.addEventListener("loadedmetadata", seek);
}

function closeVideo() {
  const box = document.getElementById("sm-video-box");
  const video = document.getElementById("sm-video");
  video.pause();
  // src除去より先にidを落とす。除去自体がerrorを飛ばすので、残したままだと
  // 閉じただけで「再生できませんでした」を出しにいく。
  playingRecordingId = null;
  detachHls();
  video.removeAttribute("src");
  video.load();
  box.classList.add("hidden");
}

function renderHead(identity, count) {
  const head = document.getElementById("sm-head");
  head.innerHTML = "";
  const cell = userCell(identity, { stackId: true });
  cell.classList.add("sm-head-user");
  const sub = document.createElement("span");
  sub.className = "sm-head-sub";
  sub.textContent = `${fmtNum(count)} Session`;
  head.append(cell, sub);
}

function renderKpi(p) {
  const t = p.totals;
  const a = p.average;
  const b = p.best;
  const lv = p.viewer_level || {};
  chipBar("sm-kpi", [
    ["配信回数", fmtNum(p.count)],
    ["総コイン", fmtNum(t.diamonds)],
    ["平均コイン/配信", fmtNum(Math.round(a.diamonds))],
    ["自己Bestコイン", fmtNum(b.diamonds), "ok"],
    ["総配信時間", fmtDuration(t.duration)],
    // average.viewers は各配信のPeakを配信数で割った物で、同接の平均ではない。
    // 実体どおりに名乗る。平均同接は観測時間で加重した viewer_level 側を出す。
    ["平均同接", lv.avg == null ? "—" : fmtNum(Math.round(lv.avg))],
    ["平均同接（宝箱窓を除く）", lv.avg_nobox == null ? "—" : fmtNum(Math.round(lv.avg_nobox))],
    ["Peak同接の平均", fmtNum(Math.round(a.viewers))],
    ["最高同接", fmtNum(b.viewers)],
    ["総Gift", fmtNum(t.gifts)],
    ["総コメント", fmtNum(t.comments)],
    ["総Like", fmtNum(t.likes)],
    ["総B.Score", fmtNum(t.battle_points)],
  ]);
}

// 成長トレンド: 直近7日/30日のコイン合計と、その前の同期間との比(前週比/前月比)。
// 「伸びているか」を一目で。基準は現在時刻(直近に配信が無ければ減少として正直に出る)。
function renderGrowth(sessions) {
  const now = Date.now() / 1000;
  const day = 86400;
  const sumIn = (from, to) =>
    sessions.filter((s) => s.started_at >= from && s.started_at < to)
      .reduce((acc, s) => acc + (s.diamonds || 0), 0);
  const w0 = sumIn(now - 7 * day, now);
  const w1 = sumIn(now - 14 * day, now - 7 * day);
  const m0 = sumIn(now - 30 * day, now);
  const m1 = sumIn(now - 60 * day, now - 30 * day);
  chipBar("sm-growth", [
    ["直近7日コイン", fmtNum(w0)],
    ["前週比", pctText(w0, w1), pctCls(w0, w1)],
    ["直近30日コイン", fmtNum(m0)],
    ["前月比", pctText(m0, m1), pctCls(m0, m1)],
  ]);
}

function pctText(cur, prev) {
  if (prev <= 0) return cur > 0 ? "新規" : "—";
  const p = ((cur - prev) / prev) * 100;
  return (p >= 0 ? "+" : "") + p.toFixed(0) + "%";
}
function pctCls(cur, prev) {
  if (prev <= 0) return "";
  return cur >= prev ? "ok" : "warn";
}

// Session別推移の表示窓。件数(直近N件)で切ると配信頻度によって「いつからの推移か」が
// 配信者ごとに変わり、同じ画面の成長トレンド(7日/30日)や時間帯ヒートマップと期間が
// 揃わない。期間で切って、どの配信者でも同じ物差しで読めるようにする。
//
// 窓は単位ごとに持つ。1本=1期間なので同じ180日でも月合計は6本にしかならず、推移として
// 読めない。単位が変われば見たい射程も変わる(週=1年・月=取れているだけ)。
// 移動平均の窓は棒の本数。配信ごとは5配信でコラボ比率の推移(COOP_TREND_WINDOW)と揃える
// ―― 同じ画面で「移動平均」が2つの意味を持つと、どちらの線も読めなくなる。
const TREND_MA_WINDOW = 5;
const TREND_UNITS = {
  session: { days: 180, rollup: "", maWindow: TREND_MA_WINDOW, maText: `${TREND_MA_WINDOW}配信`, partial: "" },
  week: { days: 365, rollup: "を週合計", maWindow: 4, maText: "4週", partial: "右端の週は集計途中" },
  month: { days: 0, rollup: "を月合計", maWindow: 3, maText: "3か月", partial: "右端の月は集計途中" },
};

function trendUnit() {
  return TREND_UNITS[elTrendUnit.value] ? elTrendUnit.value : "session";
}

function renderTrend(sessions, viewerLevel) {
  // createSessionTrendChart は s.id / s.started_at / s.ended_at / s.stats.diamonds と、
  // 率・水準のpane用に s.comments / s.observed_seconds / s.viewers(Peak) /
  // s.viewers_avg / s.viewers_avg_nobox / s.nobox_seconds を読む。
  // profile の session 形(diamonds が top-level)を、その想定 shape へ寄せる。
  const unit = trendUnit();
  const u = TREND_UNITS[unit];
  const from = u.days ? Date.now() / 1000 - u.days * 86400 : 0;
  const rows = sessions
    .filter((s) => s.started_at >= from)
    .sort((x, y) => x.started_at - y.started_at)
    .map((s) => ({
      id: s.session_id,
      started_at: s.started_at,
      ended_at: s.ended_at,
      stats: { diamonds: s.diamonds },
      comments: s.comments,
      observed_seconds: s.observed_seconds,
      viewers: s.viewers,
      viewers_avg: s.viewers_avg,
      viewers_avg_nobox: s.viewers_avg_nobox,
      nobox_seconds: s.nobox_seconds,
    }));
  // 窓の名乗りだけでなく実際に描けた範囲も出す。配信者によっては観測開始が窓より新しく、
  // 「過去180日」と言いながら手前からしか無いことがある(欠けを黙って隠さない)。
  // 期間まとめでは右端が途中の週/月になる。黙って出すと落ち込みとして読まれるので名乗る。
  const scope = u.days ? `過去${u.days}日` : "取得できた全期間";
  const partial = u.partial && rows.length
    && trendPeriodStart(rows[rows.length - 1].started_at, unit) === trendPeriodStart(Date.now() / 1000, unit)
    ? `・${u.partial}` : "";
  // 宝箱窓を除いた同接は、宝箱の収集が始まった日より前へは引けない。どこから引けるのかを
  // 名乗らないと、線の途切れが「その頃は宝箱を落としていなかった」と読める。
  const since = viewerLevel && viewerLevel.envelope_since;
  const envelope = since
    ? `・宝箱窓を除く線は${fmtDate(since)}以降（それ以前は宝箱の記録が無い）`
    : "・宝箱の記録がまだ無いため、宝箱窓を除く線は出ません";
  document.getElementById("sm-trend-note").textContent = rows.length
    ? `${scope}・${rows.length}配信（${fmtDate(rows[0].started_at)}〜）${u.rollup}`
      + `・点線=直近${u.maText}の移動平均${partial}${envelope}`
    : `${scope}・配信なし`;
  trendChart.update(rows, { unit, movingAvgWindow: u.maWindow });
}

// ---- 時間帯ヒートマップ(曜日×時刻・bucket時系列ベース) ----
// backendの heatmap は (dow, hour) ごとに、配信中に実際発生したコイン/Comment/配信秒数を
// 集計したもの。開始時刻への一括帰属ではなく、長時間配信は各時間帯へ正しく分散される。
const HM_DAYS = ["月", "火", "水", "木", "金", "土", "日"];
const HM_METRICS = {
  diamonds: { label: "コイン", fmt: (v) => fmtNum(v) },
  active_seconds: { label: "配信時間", fmt: (v) => fmtDuration(v) },
  comments: { label: "コメント", fmt: (v) => fmtNum(v) },
};

// 1時間=4 slot(15分刻み)。列数 = 24*4 = 96。
const HM_SLOTS_PER_HOUR = 4;
const HM_SLOT_MIN = 60 / HM_SLOTS_PER_HOUR;
const HM_COLS = 24 * HM_SLOTS_PER_HOUR;

function renderHeatmap() {
  const metric = elHmMetric.value;
  const wrap = document.getElementById("sm-heatmap");
  wrap.innerHTML = "";
  // cell[Mon=0..Sun=6][slot] にbackend集計を展開する(slot = hour*4 + quarter)。
  const cells = Array.from({ length: 7 }, () =>
    Array.from({ length: HM_COLS }, () => ({ diamonds: 0, comments: 0, active_seconds: 0 })),
  );
  let max = 0;
  currentHeatmap.forEach((e) => {
    const day = (e.dow + 6) % 7; // backend: 0=Sun..6=Sat → Mon=0..Sun=6
    const slot = e.hour * HM_SLOTS_PER_HOUR + (e.quarter || 0);
    const cell = cells[day][slot];
    cell.diamonds += e.diamonds || 0;
    cell.comments += e.comments || 0;
    cell.active_seconds += e.active_seconds || 0;
    if (cell[metric] > max) max = cell[metric];
  });

  // ヘッダ行(時刻ラベル: 各hour cellが4 slot分を span、3時間おきに数値表示)
  wrap.appendChild(hmCell("", "hm-corner"));
  for (let h = 0; h < 24; h++) {
    const head = hmCell(h % 3 === 0 ? String(h) : "", "hm-hhead");
    head.style.gridColumn = `span ${HM_SLOTS_PER_HOUR}`;
    wrap.appendChild(head);
  }
  // 曜日 × 15分slot
  for (let day = 0; day < 7; day++) {
    wrap.appendChild(hmCell(HM_DAYS[day], "hm-dhead"));
    for (let slot = 0; slot < HM_COLS; slot++) {
      const c = cells[day][slot];
      const cell = hmCell("", "hm-cell");
      if (slot % HM_SLOTS_PER_HOUR === 0) cell.classList.add("hm-hr"); // hour境界
      // active_seconds>0 = その時間帯に配信実績あり。選択指標が0でも薄く塗る。
      if (c.active_seconds > 0) {
        const ratio = max > 0 ? c[metric] / max : 0;
        cell.style.background = cssTokenAlpha("--ramp", 0.12 + 0.8 * ratio);
        const hh = Math.floor(slot / HM_SLOTS_PER_HOUR);
        const mm = (slot % HM_SLOTS_PER_HOUR) * HM_SLOT_MIN;
        cell.title =
          `${HM_DAYS[day]} ${hh}:${String(mm).padStart(2, "0")}〜 · 配信 ${fmtDuration(c.active_seconds)}`
          + ` · コイン ${fmtNum(c.diamonds)} · コメント ${fmtNum(c.comments)}`;
        if (ratio > 0.55) cell.classList.add("hot");
      }
      wrap.appendChild(cell);
    }
  }
  renderHeatmapLegend(metric, max);
}

function renderHeatmapLegend(metric, max) {
  const legend = document.getElementById("sm-hm-legend");
  const m = HM_METRICS[metric];
  if (!max) {
    legend.textContent = "この配信者の時間帯データはまだありません（Session終了後に集計されます）。";
    return;
  }
  legend.innerHTML = "";
  const lab = document.createElement("span");
  lab.className = "hm-leg-l";
  lab.textContent = `${m.label} 少`;
  const grad = document.createElement("span");
  grad.className = "hm-leg-grad";
  const labMax = document.createElement("span");
  labMax.className = "hm-leg-l";
  labMax.textContent = `多 (最大 ${m.fmt(max)})`;
  legend.append(lab, grad, labMax);
}

function hmCell(text, cls) {
  const el = document.createElement("span");
  el.className = cls;
  if (text) el.textContent = text;
  return el;
}

// ---- Gifter / 収益分析 ----
// ライバー比率は判定済みのコインを分母にした値。判定は待ち行列で順に進むので、
// 未判定を「ライバーではない」と数えると実際より低く出る。判定がまだ1件も無い間は
// 0%ではなく — を出す(「居ないと確認できた」と「まだ判っていない」を混同させない)。
// ライバー(自分でも配信している人)の割合は、コイン基準と人数基準で意味が違う。1人の大口
// ライバーが居ればコイン比率だけが跳ね、少額のライバーが大勢居れば人数比率だけが上がる。
// どちらの分母かが名前から読めるよう、独立した項目として出す。
//
// 値が無い場合(判定が1件も済んでいない / serverが旧processでfieldを返さない)は — にする。
// 0%は「ライバーが居ないと確認できた」という別の意味なので、そこへ丸めない。
function fmtPercent(value) {
  return typeof value === "number" ? `${value.toFixed(1)}%` : "—";
}

// 分母はどちらも全体。未判定の人はライバーに数えられないため、この比率は下限である。
// 「判定済み」を必ず併記して、どこまで確認できた上での値かを読めるようにする。
function liverTitle(c) {
  const coin =
    `コイン: ${fmtNum(c.liver_diamonds || 0)} / ${fmtNum(c.liver_gift_diamonds || 0)}`;
  const head =
    `人数: ${fmtNum(c.liver_gifters || 0)} / ${fmtNum(c.liver_total_gifters || 0)} 人`;
  return (
    `ギフトに占めるライバー（自分でも配信している人）の割合です。\n${coin}\n${head}\n`
    + `分母は全体です。リーグ未判定の人はライバーに数えないため、この値は下限です`
    + `（判定済み コイン ${fmtPercent(c.liver_coin_coverage)} / `
    + `人数 ${fmtPercent(c.liver_gifter_coverage)}）。`
  );
}

function renderConcentration(c) {
  chipBar("sm-conc", [
    ["Gifter数", fmtNum(c.total_gifters)],
    ["固定ファン(2回+)", fmtNum(c.repeat_gifters), "ok"],
    ["一見(1回)", fmtNum(c.once_gifters)],
    ["Top1 比率", `${c.top1.toFixed(1)}%`],
    ["Top5 比率", `${c.top5.toFixed(1)}%`],
    ["Top10 比率", `${c.top10.toFixed(1)}%`],
    // 分母を名前に持たせて独立させる。「ライバー比率」だけでは、コインに対してなのか
    // 人数に対してなのかが読めない。
    ["ライバー / コイン全体", fmtPercent(c.liver_coin_share), "",
      `${fmtNum(c.liver_diamonds || 0)} / ${fmtNum(c.liver_gift_diamonds || 0)} コイン。`
      + `${liverTitle(c)}`],
    ["ライバー / ギフト人数", fmtPercent(c.liver_gifter_share), "",
      `${fmtNum(c.liver_gifters || 0)} / ${fmtNum(c.liver_total_gifters || 0)} 人。`
      + `${liverTitle(c)}`],
    ["リーグ判定済み(コイン)", fmtPercent(c.liver_coin_coverage), "",
      "リーグを確認できたギフターのコインが、コイン全体に占める割合です。"
      + "上の2つはこの範囲で確定した分だけを数えた下限値です。"],
    ["リーグ判定済み(人数)", fmtPercent(c.liver_gifter_coverage), "",
      "リーグを確認できたギフターが、ギフト人数全体に占める割合です。"],
  ]);
}

function renderGifterRows(rows, hasPrev) {
  renderTableRows(
    "sm-gifters",
    "sm-gifters-empty",
    rows,
    (g, rank) => [
      String(g.rank || rank),
      // 名前からその人のFan台帳(全配信者横断の実績)へ直接飛べるようにする。
      userCell(g, {
        stackId: true,
        href: g.identity_key ? `/fans?fan=${encodeURIComponent(g.identity_key)}` : "",
        linkTitle: "この視聴者のFan台帳（全配信者横断の実績）を開きます。",
      }),
      fmtNum(g.diamonds),
      fmtNum(g.gifts),
      `${fmtNum(g.sessions)} 回`,
      rankDeltaCell(g, hasPrev),
    ],
    [0, 2, 3, 4, 5],
  );
}

// ---- 期間別ランキング ----
// 通算の一覧をそのまま暦の期間(月=1日〜末日 / 週=月曜〜日曜 / 日=0時〜24時)で切り替える。
// 効くのはGifterとBattle Gifterの2つの表だけで、KPI・推移・Battle成績は通算のまま置く。
// 期間で絞ると、既存の数字(平均・比率・勝率)が別の意味になるためである。
//
// 粒度はlocalStorageへ残すが、選んだ期間は残さない。絶対日付を復元すると、翌月に開いた
// ときに先月が選ばれたままになり「今月は0」に見える。
const PREF_GIFTER_GRAN = "tictok.streamers.gifterGranularity";
const PREF_BATTLE_GIFTER_GRAN = "tictok.streamers.battleGifterGranularity";
// 収集中の配信では中身が動く。同じ期間を押し直したときに毎回serverを叩かない程度に
// 覚えつつ、古い値を出し続けないための保持時間。
const RANKING_CACHE_MS = 60000;

// 通算(全期間)の一覧。粒度を「全期間」へ戻したときに再取得せず描き直すために持つ。
let currentGifters = [];
let currentBattleGifters = [];
let rankingCache = new Map();
const rankingInflight = new Map();
// 表ごとの選択。granularity="all" は通算(profileの一覧)を出す。
const rankingPick = {
  "sm-gifters": { granularity: "all", period: "" },
  "sm-battle-gifters": { granularity: "all", period: "" },
};
// 応答が前後しても、最後に押した選択だけが画面に残るようにする。
const rankingSeq = { "sm-gifters": 0, "sm-battle-gifters": 0 };

const RANKING_TABLES = {
  "sm-gifters": {
    pref: PREF_GIFTER_GRAN,
    field: "gifters",
    render: renderGifterRows,
    allTime: () => currentGifters,
    // コインはselectの各期間に出ているので、noteは重ねずに人数を出す。上の集中度chipは
    // 通算のGifter数なので、この期間に何人居たのかが並んで読めるようにする。
    note: (data) => `Gifter ${fmtNum(data.gifter_count)} 人`,
  },
  "sm-battle-gifters": {
    pref: PREF_BATTLE_GIFTER_GRAN,
    field: "battle_gifters",
    render: renderBattleGifterRows,
    allTime: () => currentBattleGifters,
    note: (data) => `${fmtNum(data.battles)} 戦 · Gifter ${fmtNum(data.battle_gifter_count)} 人`,
  },
};

function periodLabel(key, granularity) {
  return granularity === "week" ? `${key} の週` : key;
}

// 前期比。矢印そのものが向きを名乗るので色は足さない(この画面の「良い/危ない」の2色に
// 新しい意味を乗せない)。初登場と横ばいだけ、読み飛ばせるよう薄くする。
function rankDeltaCell(row, hasPrev) {
  // 比べる前の期間が無い(全期間・最初の期間)ときは、差そのものが存在しない。
  if (!hasPrev) return "—";
  const el = document.createElement("span");
  if (row.prev_rank == null) {
    el.className = "rk-new";
    el.textContent = "new";
    el.title = "1つ前の期間には居なかった人です。";
    return el;
  }
  if (!row.rank_delta) {
    el.className = "rk-flat";
    el.textContent = "±0";
    return el;
  }
  el.textContent = row.rank_delta > 0 ? `↑${row.rank_delta}` : `↓${-row.rank_delta}`;
  el.title = `1つ前の期間は ${row.prev_rank} 位。`;
  return el;
}

function fetchRanking(uid, granularity, period) {
  const key = `${uid}|${granularity}|${period}`;
  const hit = rankingCache.get(key);
  if (hit && Date.now() - hit.at < RANKING_CACHE_MS) return Promise.resolve(hit.data);
  // 2つの表が同じ期間を出しているときは同じ応答を待つ。1回の応答に両方の一覧が入って
  // いるので、別々に投げるとserver側で同じ集計を2度走らせることになる。
  const running = rankingInflight.get(key);
  if (running) return running;
  const params = new URLSearchParams({ granularity });
  if (period) params.set("period", period);
  const request = apiSend(
    "GET", `/api/streamers/${encodeURIComponent(uid)}/ranking?${params}`,
  ).then((data) => {
    rankingCache.set(key, { at: Date.now(), data });
    // 期間を省いて引いたときは、返ってきた期間そのものでも引けるようにする(‹ › の往復で
    // 同じ期間を毎回取り直さないため)。
    rankingCache.set(`${uid}|${granularity}|${data.period}`, { at: Date.now(), data });
    return data;
  }).finally(() => rankingInflight.delete(key));
  rankingInflight.set(key, request);
  return request;
}

function fillPeriodOptions(select, data) {
  // 一覧はserverが「配信の在った範囲を1つも飛ばさずに」返す。Giftが0だった期間も残るので、
  // 間が空いていること自体が読める(抜くと「その週は配信していない」に化ける)。
  select.innerHTML = "";
  data.periods.forEach((p) => {
    const opt = document.createElement("option");
    opt.value = p.key;
    opt.textContent = `${periodLabel(p.key, data.granularity)}　${fmtCompact(p.diamonds)}`;
    select.appendChild(opt);
  });
  select.value = data.period;
}

async function applyRanking(tableId) {
  const conf = RANKING_TABLES[tableId];
  const pick = rankingPick[tableId];
  const note = document.getElementById(`${tableId}-note`);
  const select = document.getElementById(`${tableId}-period`);
  const steps = Array.from(
    document.querySelectorAll(`.sm-period-step[data-target="${tableId}"]`));
  const byPeriod = pick.granularity !== "all";
  select.classList.toggle("hidden", !byPeriod);
  steps.forEach((b) => b.classList.toggle("hidden", !byPeriod));
  const seq = ++rankingSeq[tableId];
  if (!byPeriod) {
    note.textContent = "";
    rankingEmptyState(tableId, null);
    conf.render(conf.allTime(), false);
    return;
  }
  if (!selectedUid) return;
  const uid = selectedUid;
  note.textContent = "読み込み中…";
  let data;
  try {
    data = await fetchRanking(uid, pick.granularity, pick.period);
  } catch (err) {
    if (selectedUid !== uid || rankingSeq[tableId] !== seq) return;
    // 前の期間の行を残すと、その順位が今選んだ期間のものとして読まれる。畳んでから名乗る。
    conf.render([], false);
    rankingEmptyState(tableId, err);
    note.textContent = "";
    return;
  }
  if (selectedUid !== uid || rankingSeq[tableId] !== seq) return;
  rankingEmptyState(tableId, null);
  pick.period = data.period;
  fillPeriodOptions(select, data);
  const keys = data.periods.map((p) => p.key);
  const index = keys.indexOf(data.period);
  steps.forEach((b) => {
    const next = index + Number(b.dataset.step);
    b.disabled = index < 0 || next < 0 || next >= keys.length;
  });
  note.textContent = conf.note(data);
  if (data.dropped_periods) {
    // 黙って切ると「この配信者はこの期間しか配信していない」と読めてしまう。
    note.textContent += `（古い ${fmtNum(data.dropped_periods)} 期間は一覧から省略）`;
  }
  conf.render(data[conf.field] || [], Boolean(data.prev_period));
}

// 取得失敗を「0件」として描かない。表のplaceholder(「Giftの記録がありません。」)は
// 記録が無いという断定なので、取れなかっただけの状態にこれを出してはいけない。
// 3状態(読み込み中/0件/取得失敗)はcommon.jsのsetListStateが持つ。
function rankingEmptyState(tableId, err) {
  const empty = document.getElementById(`${tableId}-empty`);
  if (err) {
    setListState(empty, "failed", err);
    return;
  }
  listStateReset(empty);
  if (empty.dataset.emptyText !== undefined) empty.textContent = empty.dataset.emptyText;
}

function stepPeriod(tableId, step) {
  const select = document.getElementById(`${tableId}-period`);
  const keys = Array.from(select.options).map((o) => o.value);
  const next = keys.indexOf(rankingPick[tableId].period) + step;
  if (next < 0 || next >= keys.length) return;
  rankingPick[tableId].period = keys[next];
  applyRanking(tableId);
}

function renderRankings() {
  Object.keys(RANKING_TABLES).forEach(applyRanking);
}

// ---- 人×期間の一覧 ----
// 1つの期間の断面(下の2表)は、誰が伸びて誰が落ちたのかを読むのに期間の行き来と記憶を
// 要求する。期間を列・人を行にして同時に出し、縦(その列の中での上下)と横(その人の
// 続き方)を1枚で読めるようにする。
//
// 並び替えは見出しのclickだけで行う。並び順の専用buttonを置くと、表示範囲を絞る操作に
// 見える(「直近3日」と名乗りながら14列出ている、という読み違いが起きる)。
//
// 粒度は残すが、選んだ日付は残さない(期間別ランキングと同じ理由 — 絶対日付を復元すると
// 次に開いた時には別の意味になる)。2つの表は窓を共有しない。
const PREF_GIFTER_MATRIX_GRAN = "tictok.streamers.gifterMatrixGran";
const PREF_BATTLE_MATRIX_GRAN = "tictok.streamers.battleMatrixGran";
// 列の粒度の名乗り。「配信日」のまま月を出すと、見出しが実物と違うことを言う。
const MATRIX_UNIT = { day: "配信日", week: "配信週", month: "配信月" };
const MATRIX_COUNT_UNIT = { day: "日", week: "週", month: "月" };
// 列以外の並び替えkey。列keyと同じ空間に置くので、日付と衝突しない名前にする。
const MATRIX_SORT_KEYS = ["total", "count", "trend"];

const matrixState = {
  "sm-gmx": { granularity: "day", since: "", until: "", sort: "total", asc: false, data: null },
  "sm-bmx": { granularity: "day", since: "", until: "", sort: "total", asc: false, data: null },
};
const MATRIX_TABLES = {
  "sm-gmx": {
    pref: PREF_GIFTER_MATRIX_GRAN,
    field: "gifters",
    countField: "gifter_count",
    // 列の見出しを押したときに同じ期間へ合わせる期間別ランキング。
    ranking: "sm-gifters",
    label: "Gifter",
    metric: "コイン",
    colHead: (p) => fmtCompact(p.diamonds),
    colTitle: (p, gran) => `${periodLabel(p.key, gran)}　コイン ${fmtNum(p.diamonds)}`
      + `　Gift ${fmtNum(p.gifts)} 個　${fmtNum(p.battles)} 戦`,
  },
  "sm-bmx": {
    pref: PREF_BATTLE_MATRIX_GRAN,
    field: "battle_gifters",
    countField: "battle_gifter_count",
    ranking: "sm-battle-gifters",
    label: "Battle Gifter",
    metric: "Batt中コイン",
    colHead: (p) => (p.battles ? `${p.battles} 戦` : "—"),
    colTitle: (p, gran) => `${periodLabel(p.key, gran)}　${fmtNum(p.battles)} 戦`,
  },
};
// 2つの表が同じ窓を見ているときは同じ応答を待つ。1回の応答に両方の一覧が入っているので、
// 別々に投げるとserver側で同じ集計(Battle窓の解決)を2度走らせることになる。
const matrixInflight = new Map();

function matrixUrl(uid, st) {
  const params = new URLSearchParams({ granularity: st.granularity });
  if (st.since) params.set("since", st.since);
  if (st.until) params.set("until", st.until);
  return `/api/streamers/${encodeURIComponent(uid)}/matrix?${params}`;
}

function fetchMatrix(url) {
  const running = matrixInflight.get(url);
  if (running) return running;
  const request = apiSend("GET", url);
  matrixInflight.set(url, request);
  const clear = () => {
    if (matrixInflight.get(url) === request) matrixInflight.delete(url);
  };
  request.then(clear, clear);
  return request;
}

// 配信者を選び直したときの入口。粒度は表示設定のまま残し、期間の指定と並び順は戻す
// (前の配信者で選んだ日付は、次の配信者では別の意味になる)。
function loadMatrix(uid) {
  return Promise.all(Object.keys(MATRIX_TABLES).map((id) => {
    const st = matrixState[id];
    st.since = "";
    st.until = "";
    st.sort = "total";
    st.asc = false;
    document.getElementById(`${id}-since`).value = "";
    document.getElementById(`${id}-until`).value = "";
    return applyMatrix(id, uid);
  }));
}

async function applyMatrix(id, uid) {
  const st = matrixState[id];
  st.data = null;
  setListState(document.getElementById(`${id}-empty`), "loading");
  document.getElementById(id).innerHTML = "";
  document.getElementById(`${id}-legend`).innerHTML = "";
  document.getElementById(`${id}-note`).textContent = "";
  document.getElementById(`${id}-unit`).textContent = MATRIX_UNIT[st.granularity];
  const url = matrixUrl(uid, st);
  // 応答が届くまでに配信者や窓が変わっていたら捨てる。遅れて着いた古い窓の表を
  // 今の操作の結果として描かない。
  const stale = () => selectedUid !== uid || matrixUrl(uid, st) !== url;
  let data;
  try {
    data = await fetchMatrix(url);
  } catch (err) {
    if (stale()) return;
    // 取れなかっただけの状態を「記録がありません」と名乗らせない。
    setListState(document.getElementById(`${id}-empty`), "failed", err);
    return;
  }
  if (stale()) return;
  st.data = data;
  renderMatrix(id);
}

function matrixCellValue(row, key) {
  const cell = row.cells && row.cells[key];
  return cell ? cell.diamonds || 0 : 0;
}

// 前半と後半の差。列数が奇数のときは中央の列を後半へ入れる(新しい側を厚くする)。
function matrixTrend(row, keys) {
  const half = Math.floor(keys.length / 2);
  const early = keys.slice(0, half).reduce((a, k) => a + matrixCellValue(row, k), 0);
  const late = keys.slice(half).reduce((a, k) => a + matrixCellValue(row, k), 0);
  return late - early;
}

function matrixSortValue(row, sort, keys) {
  if (sort === "total") return row.diamonds;
  if (sort === "count") return row.periods;
  if (sort === "trend") return matrixTrend(row, keys);
  return matrixCellValue(row, sort);
}

// tie-breakは常に通算。同点どうしの並びが見出しを押すたびに入れ替わると、同じ表を
// 読み直すことになる。
function matrixSorted(rows, keys, st) {
  const dir = st.asc ? -1 : 1;
  return rows.slice().sort(
    (a, b) => dir * (matrixSortValue(b, st.sort, keys) - matrixSortValue(a, st.sort, keys))
      || b.diamonds - a.diamonds,
  );
}

// 列の見出しの文字。月は年から出す(07だけでは何年の7月か読めない)。
function matrixColLabel(key, granularity) {
  return granularity === "month" ? key.replace("-", "/") : key.slice(5).replace("-", "/");
}

// 出している窓の名乗り。範囲を指定しているときは、指定そのものを返して確かめられるように
// する(「直近 N」とだけ出すと、指定が効いているのかが読めない)。
function matrixRangeNote(st, data) {
  const unit = MATRIX_UNIT[st.granularity];
  const count = (data.periods || []).length;
  const head = st.since || st.until
    ? `${st.since || data.first_date} 〜 ${st.until || data.last_date} の ${fmtNum(count)} ${unit}`
    : `直近 ${fmtNum(count)} ${unit}`;
  return head + (data.older_periods
    ? `（これより古い ${fmtNum(data.older_periods)} ${MATRIX_COUNT_UNIT[st.granularity]}は出していません）`
    : "");
}

function renderMatrix(id) {
  const conf = MATRIX_TABLES[id];
  const st = matrixState[id];
  const table = document.getElementById(id);
  const note = document.getElementById(`${id}-note`);
  const legend = document.getElementById(`${id}-legend`);
  const empty = document.getElementById(`${id}-empty`);
  table.innerHTML = "";
  legend.innerHTML = "";
  const data = st.data;
  const periods = (data && data.periods) || [];
  const rows = (data && data[conf.field]) || [];
  if (data) {
    // カレンダーの端は在る記録に合わせる。無い日を選べると、0件の理由が読めなくなる。
    ["since", "until"].forEach((k) => {
      const el = document.getElementById(`${id}-${k}`);
      el.min = data.first_date || "";
      el.max = data.last_date || "";
    });
  }
  if (!periods.length || !rows.length) {
    note.textContent = "";
    if (data) {
      setListState(empty, "empty");
      // 範囲で0件になったのを「記録が無い」と名乗らせない。
      if (!periods.length && (st.since || st.until)) {
        empty.textContent = "選んだ期間には配信の記録がありません。";
      }
    }
    return;
  }
  setListState(empty, "ok");
  const keys = periods.map((p) => p.key);
  // 粒度や範囲が変わって列が入れ替わったら、列で並べていた指定は落とす。
  if (!MATRIX_SORT_KEYS.includes(st.sort) && !keys.includes(st.sort)) {
    st.sort = "total";
    st.asc = false;
  }

  const values = rows.flatMap((r) => keys.map((k) => matrixCellValue(r, k))).filter((v) => v > 0);
  const max = Math.max(...values, 1);
  const min = Math.min(...values, max);
  // 濃さは対数で割る。0起点の線形だと、跳ねた1日のせいで残りが全部同じ薄さへ寄る。
  const span = Math.log10(max) - Math.log10(min);
  const ratioOf = (v) => (span > 0 ? (Math.log10(v) - Math.log10(min)) / span : 1);

  const countUnit = MATRIX_COUNT_UNIT[st.granularity];
  const head = table.createTHead().insertRow();
  head.appendChild(matrixTh(conf.label, "sm-mx-who"));
  periods.forEach((p) => {
    const th = matrixTh("", "sm-mx-day");
    const date = document.createElement("b");
    date.textContent = matrixColLabel(p.key, st.granularity);
    const sub = document.createElement("i");
    sub.textContent = conf.colHead(p);
    th.append(date, sub);
    th.title = `${conf.colTitle(p, st.granularity)}`
      + `\nこの列の${conf.metric}順に並べ替え、下の${conf.label}表もこの期間にします。`;
    if (p.key === st.sort) {
      th.classList.add("on");
      sub.append(" ", matrixSortMark(st.asc));
    }
    th.addEventListener("click", () => sortMatrix(id, p.key));
    head.appendChild(th);
  });
  matrixSortTh(head, id, st, "total", "通算", "出している列の合計です。");
  matrixSortTh(head, id, st, "count", `${countUnit}数`, `投げた${countUnit}の数です。`);
  matrixSortTh(head, id, st, "trend", "伸び", "窓の後半と前半の差（後半 − 前半）です。");

  // 列で並べているときだけ、その列の順位を行頭に出して未投稿を下へ落とす。昇順のときは
  // 順位を付けない(1が最下位になり、順位の意味が反転する)。
  const byColumn = keys.includes(st.sort);
  const body = table.createTBody();
  matrixSorted(rows, keys, st).forEach((row, i) => {
    const tr = body.insertRow();
    const onCol = byColumn ? matrixCellValue(row, st.sort) : 0;
    if (byColumn && !onCol) tr.className = "sm-mx-off";
    const who = tr.insertCell();
    who.className = "sm-mx-who";
    if (byColumn && !st.asc && onCol) {
      const rank = document.createElement("span");
      rank.className = "sm-mx-rank";
      rank.textContent = String(i + 1);
      who.appendChild(rank);
    }
    who.appendChild(userCell(row, {
      hideId: true,
      href: row.identity_key ? `/fans?fan=${encodeURIComponent(row.identity_key)}` : "",
      linkTitle: "この視聴者のFan台帳（全配信者横断の実績）を開きます。",
    }));
    keys.forEach((key) => {
      const td = tr.insertCell();
      td.className = "sm-mx-cell";
      if (key === st.sort) td.classList.add("on");
      const cell = row.cells && row.cells[key];
      if (!cell) return;
      const ratio = ratioOf(cell.diamonds || 0);
      td.style.background = cssTokenAlpha("--ramp", 0.12 + 0.8 * ratio);
      if (ratio > 0.62) td.classList.add("hot");
      td.textContent = fmtCompact(cell.diamonds || 0);
      td.title = `${row.nickname}　${periodLabel(key, st.granularity)}`
        + `　${conf.metric} ${fmtNum(cell.diamonds || 0)}`
        + `　Gift ${fmtNum(cell.gifts || 0)} 個`
        + (cell.battles ? `　${fmtNum(cell.battles)} 戦` : "");
    });
    matrixNumCell(tr, fmtNum(row.diamonds));
    matrixNumCell(tr, `${fmtNum(row.periods)} ${countUnit}`);
    const trend = matrixTrend(row, keys);
    matrixNumCell(tr, trend ? `${trend > 0 ? "↑" : "↓"}${fmtCompact(Math.abs(trend))}` : "±0");
  });

  const shown = rows.length;
  const total = data[conf.countField] || shown;
  note.textContent = `${conf.label} ${fmtNum(total)} 人`
    + (total > shown ? `（上位 ${fmtNum(shown)} 人を表示）` : "")
    + ` · ${matrixRangeNote(st, data)}`;
  renderMatrixLegend(legend, conf.metric, min, max);
}

function matrixTh(text, cls) {
  const th = document.createElement("th");
  th.className = cls;
  if (text) th.textContent = text;
  return th;
}

// 並び替えの向き。矢印そのものが向きを名乗るので色は足さない。
function matrixSortMark(asc) {
  const el = document.createElement("span");
  el.className = "sm-mx-sortmark";
  el.textContent = asc ? "▲" : "▼";
  return el;
}

function matrixSortTh(head, id, st, key, text, title) {
  const th = matrixTh(text, "sm-mx-num");
  th.title = `${title}\n押すとこの順に並べ替えます（もう一度押すと昇順）。`;
  if (st.sort === key) {
    th.classList.add("on");
    th.append(" ", matrixSortMark(st.asc));
  }
  th.addEventListener("click", () => sortMatrix(id, key));
  head.appendChild(th);
}

function matrixNumCell(tr, text) {
  const td = tr.insertCell();
  td.className = "sm-mx-num";
  td.textContent = text;
}

function renderMatrixLegend(legend, metric, min, max) {
  const lo = document.createElement("span");
  lo.className = "hm-leg-l";
  lo.textContent = `${metric} 少 (${fmtCompact(min)})`;
  const grad = document.createElement("span");
  grad.className = "hm-leg-grad sm-mx-grad";
  const hi = document.createElement("span");
  hi.className = "hm-leg-l";
  hi.textContent = `多 (${fmtCompact(max)})`;
  legend.append(lo, grad, hi);
}

// 見出しのclick。同じ見出しをもう一度押すと昇順へ反す。列の見出しは並べ替えたうえで、
// 下の期間別ランキングも同じ期間へ送る — 一覧で見つけた期間を、もう一度selectから
// 選び直させないため。
function sortMatrix(id, key) {
  const st = matrixState[id];
  st.asc = st.sort === key ? !st.asc : false;
  st.sort = key;
  renderMatrix(id);
  const keys = ((st.data && st.data.periods) || []).map((p) => p.key);
  if (!keys.includes(key)) return;
  const conf = MATRIX_TABLES[id];
  const gran = document.getElementById(`${conf.ranking}-gran`);
  if (gran) gran.value = st.granularity;
  rankingPick[conf.ranking].granularity = st.granularity;
  rankingPick[conf.ranking].period = key;
  applyRanking(conf.ranking);
}

// ライバーからのギフト。比率だけでは「誰が投げたのか」が読めないので、リーグ帯の内訳と
// 本人の一覧を並べる。帯はA/B/Cのグループ単位で畳む(A1とA2を別の帯として並べると、
// 帯が10種類以上になって「どんなライバーか」が却って読めなくなる)。
function liverTiers(livers) {
  const groups = new Map();
  livers.forEach((l) => {
    const group = (l.league || "?").charAt(0);
    if (!groups.has(group)) groups.set(group, { count: 0, diamonds: 0, tiers: new Set() });
    const g = groups.get(group);
    g.count += 1;
    g.diamonds += l.diamonds || 0;
    g.tiers.add(l.league);
  });
  return Array.from(groups.entries()).sort((a, b) => b[1].diamonds - a[1].diamonds);
}

function renderLivers(livers) {
  chipBar(
    "sm-liver-tiers",
    liverTiers(livers).map(([group, g]) => [
      `${group} 帯`,
      `${fmtNum(g.count)} 人 / ${fmtNum(g.diamonds)} コイン`,
      "",
      `内訳: ${Array.from(g.tiers).sort().join(", ")}`,
    ]),
  );
  renderTableRows(
    "sm-livers",
    "sm-livers-empty",
    livers,
    (l, rank) => [
      String(rank),
      userCell(l, {
        stackId: true,
        href: l.identity_key ? `/fans?fan=${encodeURIComponent(l.identity_key)}` : "",
        linkTitle: "この視聴者のFan台帳（全配信者横断の実績）を開きます。",
      }),
      fmtNum(l.diamonds),
      fmtNum(l.gifts),
      `${fmtNum(l.sessions)} 回`,
    ],
    [0, 2, 3, 4],
  );
}

// ---- 共演構成(コラボ / Battle / ソロ) ----
// 「1時間あたり何回」は総配信時間が短いほど跳ねる指標なので、実数(回数)と集計対象の
// 配信時間を同じbarに並べて、頻度を単独で読ませない。
// 3つは並び順に意味の無い区分(nominal)なので系列色を先頭から順に当てる。積み棒の隣り合う
// 色として分離を確かめてある並び。
const COOP_SEGMENTS = [
  { key: "solo", label: "ソロ", color: cssToken("--series-1") },
  { key: "collab", label: "コラボ", color: cssToken("--series-2") },
  { key: "battle", label: "Battle", color: cssToken("--series-3") },
];

function fmtMinutes(seconds) {
  if (!seconds) return "—";
  const m = seconds / 60;
  return m >= 10 ? `${Math.round(m)} 分` : `${m.toFixed(1)} 分`;
}

function renderCoop(c) {
  const empty = document.getElementById("sm-coop-empty");
  const mix = document.getElementById("sm-coop-mix");
  const legend = document.getElementById("sm-coop-legend");
  mix.innerHTML = "";
  legend.innerHTML = "";
  // コラボ側が未計測(現行ruleの窓がまだ1件も無い)間は、0%ではなく「—」で名乗らない。
  // 0%と出すとその時間が全部ソロに見え、旧ruleとは逆向きの嘘になる。
  const ready = !!(c && c.collab_available);
  const skipped = (c && c.unobserved_sessions) || 0;
  document.getElementById("sm-coop-note").textContent = !ready
    ? "（コラボは現行ruleで再計測中。コラボ・ソロ・共演計は未計測）"
    : skipped
      ? `（コラボ収集開始前の ${fmtNum(skipped)} 配信は集計対象外）`
      : "";
  if (!c || !c.active_seconds) {
    chipBar("sm-coop", []);
    empty.textContent = skipped
      ? "コラボの収集を始める前の配信しかありません。"
      : "配信時間の記録がありません。";
    empty.classList.remove("hidden");
    // 配信者を選び直した時に前の人のグラフが残らないよう、空でも描き直す。
    renderCoopTrend([]);
    return;
  }
  empty.classList.add("hidden");
  // 未計測のときに出せるのはBattle側だけ。Battle窓はbattles表由来でコラボ窓に依存しない。
  const pct = (v) => (ready ? `${v.toFixed(1)}%` : "—");
  chipBar("sm-coop", [
    ["コラボ比率", pct(c.collab_share)],
    ["Battle比率", `${c.battle_share.toFixed(1)}%`],
    ["ソロ比率", pct(c.solo_share)],
    ["共演計", pct(c.coop_share), ready && c.coop_share >= 50 ? "ok" : ""],
    ["Battle 回/時", `${c.battles_per_hour.toFixed(2)}`],
    ["コラボ 回/時", ready ? `${c.collabs_per_hour.toFixed(2)}` : "—"],
    ["Battle回数", `${fmtNum(c.battle_count)} 回`],
    ["コラボ回数", ready ? `${fmtNum(c.collab_count)} 回` : "—"],
    ["平均Battle長", fmtMinutes(c.avg_battle_seconds)],
    ["平均コラボ長", ready ? fmtMinutes(c.avg_collab_seconds) : "—"],
    ["コラボした配信", ready ? `${fmtNum(c.sessions_with_collab)} / ${fmtNum(c.sessions)}` : "—"],
    ["集計対象", `${fmtDuration(c.active_seconds)}`],
  ]);

  if (!ready) {
    // 内訳barはコラボ/ソロの3分割なので、コラボが未計測の間は成立しない。
    renderCoopTrend([]);
    return;
  }

  COOP_SEGMENTS.forEach((seg) => {
    const share = c[`${seg.key}_share`] || 0;
    if (share > 0) {
      const el = document.createElement("span");
      el.className = "sm-mix-seg";
      el.style.flexGrow = String(share);
      el.style.background = seg.color;
      el.title = `${seg.label} ${share.toFixed(1)}% / ${fmtDuration(c[`${seg.key}_seconds`])}`;
      // 幅が狭い区間に文字を押し込むと読めなくなるので、数字はlegend側で必ず出す。
      const b = document.createElement("b");
      b.textContent = `${share.toFixed(0)}%`;
      el.appendChild(b);
      mix.appendChild(el);
    }
    const item = document.createElement("span");
    item.className = "sm-mix-item";
    const dot = document.createElement("i");
    dot.style.background = seg.color;
    const text = document.createElement("span");
    text.textContent = `${seg.label} ${share.toFixed(1)}%（${fmtDuration(c[`${seg.key}_seconds`])}）`;
    item.append(dot, text);
    legend.appendChild(item);
  });
  renderCoopTrend(c.series || []);
}

// コラボ比率の推移。棒はその配信の比率、点線は直近COOP_TREND_WINDOW配信の時間加重平均。
// 窓幅はSession別推移の移動平均と揃える(画面内で「移動平均」の意味を1つに保つ)。
const COOP_TREND_WINDOW = 5;
const COOP_COLLAB_COLOR = COOP_SEGMENTS.find((s) => s.key === "collab").color;
let coopTrendChart = null;

function renderCoopTrend(series) {
  const empty = document.getElementById("sm-coop-trend-empty");
  const note = document.getElementById("sm-coop-trend-note");
  // コラボが1秒も無ければ、0%が並ぶだけの帯を出しても読めるものが無い。
  const hasCollab = series.some((s) => s.collab_seconds > 0);
  document.getElementById("sm-coop-trend").parentElement.classList.toggle("hidden", !hasCollab);
  empty.classList.toggle("hidden", hasCollab);
  empty.textContent = "コラボの記録がありません。";
  note.textContent = hasCollab
    ? `直近${series.length}配信・点線=直近${COOP_TREND_WINDOW}配信の時間加重移動平均`
    : "";
  if (!hasCollab) {
    coopTrendChart.update([]);
    return;
  }
  coopTrendChart.update(series);
}

function createCoopTrendChart(canvas) {
  let rows = [];
  const chart = new Chart(canvas, {
    type: "bar",
    data: {
      labels: [],
      datasets: [
        { type: "bar", label: "コラボ比率", data: [], backgroundColor: COOP_COLLAB_COLOR, yAxisID: "y" },
        { type: "line", label: `コラボ比率 移動平均(${COOP_TREND_WINDOW}配信)`, data: [], borderColor: cssToken("--series-4"), backgroundColor: "transparent", borderWidth: 2, borderDash: [5, 3], pointRadius: 0, tension: 0.3, yAxisID: "y" },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: { ticks: { ...nierTicks(), maxRotation: 0, autoSkip: true, maxTicksLimit: 18 }, grid: { color: NIER_GRID_COLOR } },
        // 率なので上限は100%で固定。データの最大に合わせて伸縮すると、配信ごとに
        // 同じ高さが違う割合を指すことになり、推移として読めない。
        y: { position: "left", beginAtZero: true, max: 100, title: { display: true, text: "コラボ比率(%)", color: NIER_AXIS_COLOR, font: { family: "monospace", size: 10 } }, ticks: nierTicks(), grid: { color: NIER_GRID_COLOR } },
      },
      plugins: {
        legend: { labels: { color: cssToken("--chart-ink"), font: { family: "monospace", size: 11 }, boxWidth: 14, boxHeight: 8 } },
        tooltip: {
          ...nierTooltip(),
          callbacks: {
            title: (items) => {
              const r = rows[items[0].dataIndex];
              return r ? `#${sessionNo(r.session_id)}  ${fmtDateTime(r.started_at)}` : "";
            },
            label: (item) => {
              const r = rows[item.dataIndex];
              if (item.parsed.y === null) return "";
              const pct = `${item.parsed.y.toFixed(1)}%`;
              // 率だけでは「6時間のうち10分」と「10分のうち10分」が同じ高さに見える。
              // 棒には元の秒を必ず添える。
              return item.dataset.type === "bar" && r
                ? `${item.dataset.label}: ${pct}（${fmtDuration(r.collab_seconds)} / ${fmtDuration(r.active_seconds)}・${fmtNum(r.collab_count)} 回）`
                : `${item.dataset.label}: ${pct}`;
            },
          },
        },
      },
    },
  });
  function update(orderedRows) {
    rows = orderedRows || [];
    const ymdSeen = {};
    chart.data.labels = rows.map((r) => {
      const ymd = fmtYmd(r.started_at);
      ymdSeen[ymd] = (ymdSeen[ymd] || 0) + 1;
      return ymdSeen[ymd] > 1 ? `${ymd}:${ymdSeen[ymd]}` : ymd;
    });
    chart.data.datasets[0].data = rows.map((r) => r.collab_share || 0);
    chart.data.datasets[1].data = weightedShareAverage(
      rows.map((r) => r.collab_seconds || 0),
      rows.map((r) => r.active_seconds || 0),
      COOP_TREND_WINDOW,
    );
    chart.update();
  }
  return { update };
}

// ---- Battle 分析 ----
// チーム戦は自陣=チーム全体なので、Scoreも貢献者も「監視配信者ぶん」と「チーム計」で値が
// 変わる。片方だけ出すと個人戦と桁が揃わず読み違えるため、両方を 自分 / チーム計 で併記する。
function renderBattle(b) {
  chipBar("sm-battle", [
    ["対戦数", fmtNum(b.count)],
    ["勝率", b.count ? `${b.win_rate.toFixed(1)}%` : "—", b.win_rate >= 50 ? "ok" : ""],
    ["戦績", `${b.wins}勝 ${b.losses}敗 ${b.draws}分`],
    [
      "平均自陣Score 自分/陣営",
      `${fmtNum(Math.round(b.avg_own_host_score))} / ${fmtNum(Math.round(b.avg_own_score))}`,
    ],
    ["平均敵陣Score", fmtNum(Math.round(b.avg_opp_score))],
    [
      `貢献者${b.key_contrib_threshold}+/戦 自室/陣営`,
      `${b.avg_key_contributors.toFixed(1)} / ${b.avg_team_key_contributors.toFixed(1)} 人`,
    ],
    ["Battle中コイン比率", `${b.battle_diamond_share.toFixed(1)}%`],
  ]);
  document.getElementById("sm-battle-history-keycontrib").textContent =
    `貢献者${b.key_contrib_threshold}+ 自室/陣営`;
  // 不成立(全陣営が閾値以下)で外した戦数。出さないと対戦数が実際の枠数と食い違って見える。
  document.getElementById("sm-battle-note").textContent = b.no_contest
    ? `（全陣営のScoreが${b.no_contest_score}以下の ${fmtNum(b.no_contest)} 戦は除外）`
    : "";
}

// 対戦相手別: serverは全件(配信者あたり数百)返す。ここで絞込・並べ替えして出す。
// 上位N件で切ると、裾の相手が「対戦していない」ように見えるため件数の上限は設けない。
let opponentsAll = [];

function renderOpponents(opponents) {
  opponentsAll = opponents || [];
  renderOpponentRows();
}

// 勝率は勝敗のついたBattleだけが母数。引分/未確定しかない相手は率を持たないため、
// 率での並べ替えでは末尾へ置く(0%として混ぜると「全敗」と読めてしまう)。
function opponentRate(o) {
  const decided = o.wins + o.losses;
  return decided ? o.wins / decided : null;
}

const OPPONENT_SORTS = {
  battles: (o) => o.battles,
  wins: (o) => o.wins,
  losses: (o) => o.losses,
  rate: (o) => (opponentRate(o) == null ? -1 : opponentRate(o)),
};

function renderOpponentRows() {
  const q = document.getElementById("sm-opp-search").value.trim().toLowerCase();
  const min = Number(document.getElementById("sm-opp-min").value) || 1;
  const sortKey = document.getElementById("sm-opp-sort").value;
  const keyOf = OPPONENT_SORTS[sortKey] || OPPONENT_SORTS.battles;
  const rows = opponentsAll
    .filter((o) => o.battles >= min)
    .filter((o) => !q || `${o.nickname} @${o.unique_id}`.toLowerCase().includes(q))
    // 同値は対戦数の多い順を第2キーにする(率で並べた時に1戦だけの相手が上に来ないように)。
    .sort((a, b) => keyOf(b) - keyOf(a) || b.battles - a.battles);
  document.getElementById("sm-opp-note").textContent = opponentsAll.length
    ? `（${fmtNum(opponentsAll.length)} 名中 ${fmtNum(rows.length)} 名）`
    : "";
  if (opponentsAll.length && !rows.length) {
    setListMessage(
      document.getElementById("sm-opponents-empty"),
      "条件に合う対戦相手がいません。絞込を緩めてください。",
    );
  } else {
    setListMessage(document.getElementById("sm-opponents-empty"), "Battleの記録がありません。");
  }
  renderTableRows(
    "sm-opponents",
    "sm-opponents-empty",
    rows,
    (o, rank) => {
      const r = opponentRate(o);
      const rate = r == null ? "—" : `${(r * 100).toFixed(0)}%`;
      return [
        String(rank),
        userCell(o, { stackId: true }),
        fmtNum(o.battles),
        fmtNum(o.wins),
        fmtNum(o.losses),
        rate,
      ];
    },
    [0, 2, 3, 4, 5],
    // 行clickでBattle履歴をその相手だけに絞る。相手を見つけてから「その対戦がどれか」
    // を探すのに、履歴を日時で目視照合させない(1配信者で数百戦ある)。
    (tr, o) => {
      tr.classList.add("row-clickable");
      tr.classList.toggle("sm-opp-picked", !!pickedOpponent && pickedOpponent.key === o.key);
      tr.tabIndex = 0;
      tr.title = "clickでこの相手とのBattle履歴に絞込";
      tr.addEventListener("click", () => pickOpponent(o));
      tr.addEventListener("keydown", (e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        e.preventDefault();
        pickOpponent(o);
      });
    },
  );
}

// 対戦相手別で選んでいる相手(null=絞込なし)。Battle履歴の絞込と、相手一覧の選択表示の
// 両方がこれ1つを見る。
let pickedOpponent = null;

function pickOpponent(o) {
  // 同じ相手をもう一度clickしたら解除。絞込を外す手段が帯のbuttonだけだと、選び直しの
  // たびに一覧と帯を往復することになる。
  pickedOpponent = pickedOpponent && pickedOpponent.key === o.key ? null : o;
  renderOpponentRows();
  renderBattleHistoryRows();
  if (pickedOpponent) {
    document
      .getElementById("sm-battle-history")
      .closest(".table-wrap")
      .scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
}

function clearOpponentPick() {
  pickedOpponent = null;
  renderOpponentRows();
  renderBattleHistoryRows();
}

// Battle Gifter: Battle時間窓内に自陣へ投げたファンの集計（どんなギフターで出てきたか）。
function renderBattleGifterRows(rows, hasPrev) {
  renderTableRows(
    "sm-battle-gifters",
    "sm-battle-gifters-empty",
    rows,
    (g, rank) => [
      String(g.rank || rank),
      // 導線も身元もGifter一覧と同じにする。同じ人が2つの表に出るのに、片方からしか
      // Fan台帳へ飛べないと「別人かもしれない」という読みを残す。
      userCell(g, {
        stackId: true,
        href: g.identity_key ? `/fans?fan=${encodeURIComponent(g.identity_key)}` : "",
        linkTitle: "この視聴者のFan台帳（全配信者横断の実績）を開きます。",
      }),
      fmtNum(g.diamonds),
      fmtNum(g.gifts),
      `${fmtNum(g.battles)} 回`,
      rankDeltaCell(g, hasPrev),
    ],
    [0, 2, 3, 4, 5],
  );
}

const BATTLE_TYPE_LABEL = { team: "チーム戦", personal: "個人戦" };

// 「監視配信者ぶん / 陣営計」の併記。個人戦は自陣host=1人で両者一致するため1つだけ出し、
// 差が出るチーム戦だけ併記する。自host分が不明(古いrecordでhostを特定できない)なら —。
function pairValue(own, team) {
  if (own === null || own === undefined) return `— / ${fmtNum(team)}`;
  if (own === team) return fmtNum(own);
  return `${fmtNum(own)} / ${fmtNum(team)}`;
}
const BATTLE_RESULT = { win: ["WIN", "ok"], lose: ["LOSE", "warn"], draw: ["分", ""] };

// Battle開始の何秒前から再生するか。開始時刻ちょうどに飛ぶと、既にBattleが始まった絵から
// 見ることになり、直前の呼びかけ(誰が入ってきたか)が見えない。
const BATTLE_VIDEO_LEAD_SECONDS = 5;

// その対戦を含む録画があれば、対戦の場面から再生するbutton。録画が無い対戦(未録画・
// retentionで削除済み)は「—」— 押しても何も無いbuttonは出さない。
function battleVideoCell(h) {
  if (!h.recording_id) return "—";
  const btn = document.createElement("button");
  btn.className = "btn btn-small";
  btn.textContent = "▶ 再生";
  const label = `Battle ${fmtDateTime(h.started_at)}（録画 #${sessionNo(h.session_id)}）`;
  btn.title = `${label} の場面から再生します。`;
  btn.addEventListener("click", async (e) => {
    // 行clickはBattle結果modalを開く。buttonを押した時に両方走らせない。
    e.stopPropagation();
    btn.disabled = true;
    try {
      // 動画の何秒地点かはserverに解かせる。壁時計との差(起動latency・再接続の穴・mux)は
      // 録画fileの時刻anchorが無いと解けず、画面で引き算すると分単位でずれる。
      const at = encodeURIComponent(h.started_at);
      const found = await apiSend("GET", `/api/recordings/${h.recording_id}/locate?at=${at}`);
      openVideo(
        h.recording_id,
        Math.max(0, found.video_time - BATTLE_VIDEO_LEAD_SECONDS),
        label,
      );
    } catch (err) {
      // 理由を出せる場所は再生boxしかない。前の再生は止めてから出す(音が続いたまま
      // 別の対戦のerrorが出ると、どちらの話か読めない)。
      closeVideo();
      showVideoMessage(label, err.message);
    } finally {
      btn.disabled = false;
    }
  });
  return btn;
}

// Battle 履歴: 1戦ごとのScore/結果/相手/Batt中コイン（新しい順）。
// 「どんなスコアになったか」を過去のBattle全体で一覧できる。
let battleHistoryAll = [];

function renderBattleHistory(history) {
  battleHistoryAll = history || [];
  renderBattleHistoryRows();
}

function renderBattleHistoryRows() {
  // 絞込は代表相手ではなく参加した全員(opponent_keys)に当てる。チーム戦・個人マルチで
  // 格下だった相手を選んだ時に、その対戦が履歴から消えてしまうため。
  const rows = pickedOpponent
    ? battleHistoryAll.filter((h) => (h.opponent_keys || []).includes(pickedOpponent.key))
    : battleHistoryAll;
  const filterBar = document.getElementById("sm-battle-history-filter");
  filterBar.classList.toggle("hidden", !pickedOpponent);
  if (pickedOpponent) {
    const name = pickedOpponent.nickname || pickedOpponent.unique_id || "(unknown)";
    document.getElementById("sm-battle-history-filter-label").textContent =
      `${name} との対戦 ${fmtNum(rows.length)} 戦`;
  }
  document.getElementById("sm-battle-history-note").textContent = battleHistoryAll.length
    ? `（新しい順・${fmtNum(rows.length)} / ${fmtNum(battleHistoryAll.length)} 戦）`
    : "（新しい順）";
  setListMessage(
    document.getElementById("sm-battle-history-empty"),
    pickedOpponent
      ? "この相手との対戦は履歴にありません。"
      : "Battleの記録がありません。",
  );
  renderTableRows(
    "sm-battle-history",
    "sm-battle-history-empty",
    rows,
    (h) => {
      const [label, cls] = BATTLE_RESULT[h.result] || ["—", ""];
      const res = document.createElement("span");
      res.className = "sm-bres" + (cls ? " " + cls : "");
      res.textContent = label;
      let mode = BATTLE_TYPE_LABEL[h.type] || "個人戦";
      // 個人マルチ(3コラ/4コラ)は参加者数を併記。チーム戦は人数が陣営で分かれるため付けない。
      if (h.type !== "team" && h.opponent_count > 1) mode += ` ${h.opponent_count + 1}コラ`;
      const opp = h.opponent ? userCell(h.opponent, { stackId: true }) : "—";
      return [
        fmtDateTime(h.started_at),
        mode,
        opp,
        pairValue(h.own_host_score, h.own_score),
        fmtNum(h.opp_score),
        res,
        pairValue(h.diamonds, h.team_diamonds),
        `${pairValue(h.key_contributors, h.team_key_contributors)} 人`,
        battleVideoCell(h),
      ];
    },
    [3, 4, 6, 7],
    // 行clickでそのBattleの詳細(参加者/貢献者カード)をmodal表示。dblclickは
    // hoverしないと存在に気付けず、row-clickableなのに単clickが無反応で期待を裏切った。
    (tr, h) => {
      tr.classList.add("row-clickable");
      tr.tabIndex = 0;
      tr.title = "clickでBattle結果を表示";
      tr.addEventListener("click", () => showBattleDetail(h));
      tr.addEventListener("keydown", (e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        e.preventDefault();
        showBattleDetail(h);
      });
    },
  );
}

// Battle履歴の1行 → そのSessionのBattleを取得し、該当Battle(battle_id一致、無ければ
// start_time最近)のカードを詳細modalに描画する。カードは/battleページ・履歴詳細と共有の
// renderBattleCardsを使う。
async function showBattleDetail(h) {
  const title = document.getElementById("sm-battle-title");
  const cards = document.getElementById("sm-battle-cards");
  const empty = document.getElementById("sm-battle-empty");
  title.textContent = `Battle結果 — ${fmtDateTime(h.started_at)}`;
  empty.classList.add("hidden");
  renderBattleCards(cards, [], currentIdentity || {});
  const battleModal = document.getElementById("sm-battle-modal");
  battleModal.classList.remove("hidden");
  focusModalOpen(battleModal, document.getElementById("sm-battle-close"));

  const res = await fetch(`/api/sessions/${h.session_id}`);
  if (!res.ok) {
    empty.textContent = "Battle結果の取得に失敗しました。";
    empty.classList.remove("hidden");
    return;
  }
  const data = await res.json();
  const battles = data.battles || [];
  const owner = data.owner || currentIdentity || { unique_id: h.session_id };
  const battle =
    (h.battle_id && battles.find((b) => String(b.battle_id) === String(h.battle_id)))
    || battles.find((b) => b.start_time === h.started_at)
    || null;
  if (!battle) {
    renderBattleCards(cards, [], owner);
    empty.textContent = "このBattleの詳細が見つかりませんでした。";
    empty.classList.remove("hidden");
    return;
  }
  renderBattleCards(cards, [battle], owner);
}

function closeBattleDetail() {
  // renderBattleCardsで保持中のChart instanceを破棄してから閉じる。
  renderBattleCards(document.getElementById("sm-battle-cards"), [], currentIdentity || {});
  const battleModal = document.getElementById("sm-battle-modal");
  battleModal.classList.add("hidden");
  focusModalClose(battleModal);
}

// スコア推移: 過去Battleを古い→新しい順に、自陣/敵陣Scoreの折れ線 + Batt中コインの棒で表示。
// 「過去のBattleでスコアがどう伸びてきたか」の傾向を1枚で俯瞰する。
//
// 生誕祭のようなイベント回は通常の数十〜数百倍まで跳ねる。線形軸だとその1戦が縦を占有して
// 残りの全戦が軸の底へ潰れるため、縦軸は 対数 / 線形 / 常用域(上位を頭打ち) を選べるように
// する。跳ねた戦を一覧から外して逃げることはしない — 外すと「いつ跳ねたのか」が画面のどこ
// にも無くなるので、どの表示でも全戦を並べる。
// 横軸は戦順(1戦=1枠の等間隔)と日時(実時間)を選べる。等間隔は密に戦った日も潰さない代わりに
// 配信の空いた期間が消え、実時間はその逆になる。どちらか一方では時間の見え方が欠ける。
let battleTrendChart = null;
function renderBattleTrend(history) {
  const ordered = history.slice().reverse(); // backendは新しい順 → 時系列(古い→新しい)へ
  document.getElementById("sm-battle-trend-empty").classList.toggle("hidden", ordered.length > 0);
  document.getElementById("sm-battle-trend-note").textContent = ordered.length ? `${ordered.length} 戦` : "";
  battleTrendChart.update(ordered);
}

// 頭打ちにする分位。跳ねるのは全戦の数%なので、ここで切ると残りが縦いっぱいに広がる。
const BATTLE_TREND_CLIP_Q = 0.95;
const BATTLE_TREND_BAR = cssToken("--ramp-2");
// 頭打ちにした棒。上端で切った物と、たまたま上端まで届いた物を見分けるための色。
const BATTLE_TREND_CAP_BAR = cssToken("--ramp-5");
const DAY_MS = 86400000;

// 頭打ちの位置。母数が少なくて分位が定まらない時と、跳ねが無くて分位=最大の時はnull
// (頭打ちの印を出しておいて、実際には何も切っていない状態を作らない)。
function battleTrendCap(values) {
  const v = values.filter((n) => Number.isFinite(n) && n > 0).sort((a, b) => a - b);
  if (v.length < 10) return null;
  const cap = v[Math.ceil(BATTLE_TREND_CLIP_Q * v.length) - 1];
  return cap < v[v.length - 1] ? cap : null;
}

// 日時軸の目盛り。Chart.jsの線形軸は切りの良いms値へ目盛りを置くため、そのまま日付へ
// 直すと同じ日が並んだり半端な時刻を指す。日境界へ揃えた目盛りを自前で作る。
function dayTicks(min, max, maxCount) {
  const days = Math.max(1, Math.ceil((max - min) / DAY_MS));
  const step = [1, 2, 3, 7, 14, 30, 60, 90, 180, 365].find((s) => days / s <= maxCount)
    || Math.ceil(days / maxCount);
  const first = new Date(min);
  first.setHours(0, 0, 0, 0);
  const ticks = [];
  for (let t = first.getTime(); t <= max; t += step * DAY_MS) {
    if (t >= min) ticks.push({ value: t });
  }
  return ticks.length ? ticks : [{ value: min }];
}

// containerは .x-chartstack。Score(点)とコイン(枚)は単位が違うので二軸で重ねず、
// 上下のpanelへ分けて戦の並び(x)だけを共有する。頭打ち・対数の切替は panel ごとに効く。
function createBattleTrendChart(container) {
  const elX = document.getElementById("sm-battle-trend-x");
  const elY = document.getElementById("sm-battle-trend-y");
  let rows = [];
  // 頭打ちの位置。tooltipは描いた値ではなく元の値を出すため、こちらも保持する
  // (頭打ちで描いた点の実値まで隠すと、その戦がいくつだったかが画面のどこにも無くなる)。
  let caps = { y: null, y2: null };

  // datasetIndex から元dataのkeyを引く。paneごとにkeyの並びが違う。
  const SCORE_KEYS = ["own_score", "opp_score"];
  const COIN_KEYS = ["diamonds"];

  function tooltipFor(keys, capOf) {
    return {
      ...nierTooltip(),
      callbacks: {
        title: (items) => {
          const r = rows[items[0].dataIndex];
          if (!r) return "";
          const res = (BATTLE_RESULT[r.result] || ["—"])[0];
          const opp = r.opponent ? ` vs ${r.opponent.nickname || r.opponent.unique_id}` : "";
          return `${fmtDateTime(r.started_at)} · ${res}${opp}`;
        },
        // 頭打ちにした戦は、描いた値(上端)ではなく元の値を出す。
        label: (item) => {
          const r = rows[item.dataIndex];
          const raw = r ? r[keys[item.datasetIndex]] || 0 : item.parsed.y;
          const cap = capOf();
          const capped = cap && raw > cap ? "（頭打ち）" : "";
          return `${item.dataset.label}: ${fmtNum(raw)}${capped}`;
        },
      },
    };
  }

  function paneBase(tooltip, legend) {
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: { ticks: { ...nierTicks(), maxRotation: 0, autoSkip: true, maxTicksLimit: 18 }, grid: { color: NIER_GRID_COLOR } },
        y: { position: "left", beginAtZero: true, afterFit: stackedYFit, ticks: nierTicks(), grid: { color: NIER_GRID_COLOR } },
      },
      plugins: {
        legend: { display: legend, labels: { color: cssToken("--chart-ink"), font: { family: "monospace", size: 11 }, boxWidth: 14, boxHeight: 8 } },
        tooltip,
      },
    };
  }

  const scoreChart = new Chart(stackPane(container, { lead: true }), {
    type: "line",
    data: {
      labels: [],
      datasets: [
        { type: "line", label: "自陣Score", data: [], borderColor: BATTLE_OWN_LINE, backgroundColor: BATTLE_OWN_LINE, borderWidth: 2, pointRadius: 2, tension: 0.25 },
        { type: "line", label: "敵陣Score", data: [], borderColor: BATTLE_OPP_LINE, backgroundColor: BATTLE_OPP_LINE, borderWidth: 2, pointRadius: 2, tension: 0.25 },
      ],
    },
    options: paneBase(tooltipFor(SCORE_KEYS, () => caps.y), true),
  });
  const coinChart = new Chart(stackPane(container), {
    type: "bar",
    data: {
      labels: [],
      // 1系列なので凡例は出さない。軸のtitleが指標を名乗る。
      datasets: [{ type: "bar", label: "Batt中コイン", data: [], backgroundColor: BATTLE_TREND_BAR }],
    },
    options: paneBase(tooltipFor(COIN_KEYS, () => caps.y2), false),
  });

  // 2つのpanelは戦の並び(x)を共有するので、読み取りの縦線も共有する。
  linkCrosshair([scoreChart, coinChart]);
  enableValueMarks(scoreChart);
  enableValueMarks(coinChart);
  // 頭打ちにした戦は上端に置いて描いてある。札には描いた値ではなく元の値を出す
  // (tooltipと同じ理由 ―― 上端の数字を実値と読ませない)。
  const rawValue = (keys) => (di, i) => (rows[i] ? rows[i][keys[di]] || 0 : null);
  scoreChart.$readoutValue = rawValue(SCORE_KEYS);
  coinChart.$readoutValue = rawValue(COIN_KEYS);

  // 戦順の目盛り。同じ日に複数戦あると日付が並ぶので、2戦目以降へ通し番号を添える。
  function seqLabels() {
    const seen = {};
    return rows.map((r) => {
      const ymd = fmtYmd(r.started_at);
      seen[ymd] = (seen[ymd] || 0) + 1;
      return seen[ymd] > 1 ? `${ymd}:${seen[ymd]}` : ymd;
    });
  }

  // bottom=false のpanelは目盛を伏せる(x軸は最下段だけが名乗り、上のpanelと時間軸を共有する)。
  function xScale(xMode, bottom) {
    if (xMode !== "time") {
      return {
        type: "category",
        ticks: { ...nierTicks(), maxRotation: 0, autoSkip: true, maxTicksLimit: 18, display: bottom },
        grid: { color: NIER_GRID_COLOR },
      };
    }
    return {
      type: "linear",
      ticks: { ...nierTicks(), maxRotation: 0, autoSkip: false, display: bottom, callback: (v) => fmtYmd(v / 1000) },
      afterBuildTicks: (scale) => { scale.ticks = dayTicks(scale.min, scale.max, 12); },
      grid: { color: NIER_GRID_COLOR },
    };
  }

  function yScale(label, cap, yMode) {
    // 軸の読み方は軸自身に名乗らせる。切替を知らずに見た人が、圧縮された縦を実差だと
    // 読むことがないようにする。
    const suffix = yMode === "log" ? "（対数）" : cap ? `（${fmtNum(cap)}で頭打ち）` : "";
    const scale = {
      position: "left",
      afterFit: stackedYFit,
      title: { display: true, text: `${label}${suffix}`, color: NIER_AXIS_COLOR, font: { family: "monospace", size: 10 } },
      ticks: nierTicks(),
      grid: { color: NIER_GRID_COLOR },
    };
    if (yMode === "log") {
      scale.type = "logarithmic";
      // 対数の目盛りは10の冪の間にも刻みが入り、桁が広いと上端で数字が重なる。間引く。
      scale.ticks.maxTicksLimit = 8;
      return scale;
    }
    scale.type = "linear";
    scale.beginAtZero = true;
    // 頭打ちの点は上端ちょうどに来るため、軸をcapで止めると印が枠で切れて見えない。
    // 少しだけ上を空けて、頭打ちの列が枠の内側に収まるようにする。
    if (cap) scale.max = Math.round(cap * 1.05);
    return scale;
  }

  function applyMode() {
    const xMode = elX.value;
    const yMode = elY.value;
    caps = {
      y: yMode === "clip" ? battleTrendCap(rows.flatMap((r) => [r.own_score || 0, r.opp_score || 0])) : null,
      y2: yMode === "clip" ? battleTrendCap(rows.map((r) => r.diamonds || 0)) : null,
    };
    // 対数軸に0は置けない。0のまま渡すと点が軸の外へ落ちるので、線を切る意味のnullにする。
    const plot = (v, cap) => {
      if (yMode === "log") return v > 0 ? v : null;
      return cap && v > cap ? cap : v;
    };
    const point = (r, v) => (xMode === "time" ? { x: r.started_at * 1000, y: v } : v);
    const over = (v, cap) => !!cap && v > cap;

    const labels = xMode === "time" ? [] : seqLabels();
    scoreChart.data.labels = labels;
    coinChart.data.labels = labels;

    const bar = coinChart.data.datasets[0];
    bar.data = rows.map((r) => point(r, plot(r.diamonds || 0, caps.y2)));
    bar.backgroundColor = rows.map((r) =>
      (over(r.diamonds || 0, caps.y2) ? BATTLE_TREND_CAP_BAR : BATTLE_TREND_BAR));
    // 実時間軸では戦と戦の間隔がそのまま棒の幅になり、密に戦った日は棒が消える。幅は固定で置く。
    bar.barThickness = xMode === "time" ? 3 : undefined;

    SCORE_KEYS.forEach((key, i) => {
      const ds = scoreChart.data.datasets[i];
      const value = (r) => r[key] || 0;
      ds.data = rows.map((r) => point(r, plot(value(r), caps.y)));
      ds.pointStyle = rows.map((r) => (over(value(r), caps.y) ? "triangle" : "circle"));
      ds.pointRadius = rows.map((r) => (over(value(r), caps.y) ? 5 : 2));
      // 実時間軸では、日をまたぐ隙間に線を引くと配信していない期間に推移があったように
      // 見える。1日以上空いた区間は線を消して点だけ残す(戦順は時間を名乗らないので繋ぐ)。
      ds.segment = xMode === "time"
        ? { borderColor: (ctx) => (ctx.p1.parsed.x - ctx.p0.parsed.x > DAY_MS ? "transparent" : undefined) }
        : undefined;
    });

    scoreChart.options.scales.x = xScale(xMode, false);
    scoreChart.options.scales.y = yScale("Score", caps.y, yMode);
    coinChart.options.scales.x = xScale(xMode, true);
    coinChart.options.scales.y = yScale("コイン", caps.y2, yMode);
    scoreChart.update();
    coinChart.update();
  }

  function update(orderedRows) {
    rows = orderedRows || [];
    applyMode();
  }
  return { update, applyMode };
}

// 大口(実弾)の日次人数。帯は金額順に並ぶ順序尺度なので、色は系統色を薄→濃で当てる
// (別々の色にすると帯の上下関係が読めなくなる)。帯定義はserverから来るぶんだけ作る。
// 帯の本数はrampの5段より多い。足りないぶんを剰余で先頭へ折り返すと薄い色が下の帯にも
// 現れ、色から読める上下関係が壊れる。5段の間を補間して段数ぶんの薄→濃を作る。
function whaleTierColors(count) {
  if (count <= RAMP_STEPS.length) return rampOf(count);
  const stops = RAMP_STEPS.map(rgbaOf);
  return Array.from({ length: count }, (_, i) => {
    const pos = (i * (stops.length - 1)) / (count - 1);
    const lo = Math.min(Math.floor(pos), stops.length - 2);
    const t = pos - lo;
    const c = [0, 1, 2].map((k) => Math.round(stops[lo][k] + (stops[lo + 1][k] - stops[lo][k]) * t));
    return `rgb(${c.join(", ")})`;
  });
}
// 合計は帯ではないので、帯の系統色から外した無彩の色を当てる。系統色の続きにすると
// 「一番上の帯」に見える。
const WHALE_TOTAL_COLOR = cssToken("--chart-ink");
// 段の名前は色ではなく文字で名乗らせる。系統色の薄い側は地色に対して文字として読めず、
// 色だけを頼りにすると段の身元が消える。色は名前の脇の小さな見本が持つ。
const WHALE_LABEL_INK = cssToken("--chart-ink");
const WHALE_VALUE_FONT = "11px monospace";
// chartが敷く紙の面。半透明の塗りを混ぜて実際の明るさを出すのに使う。
const CHART_SURFACE_COLOR = cssToken("--chart-surface");
const WHALE_VALUE_LINE = 11;
// 棒の中へ数字を置く時の明るい文字色。濃い帯の上ではink色が沈む。
const WHALE_VALUE_ON_FILL = cssToken("--chart-surface");

// 色指定を [r,g,b,a] へ開く。帯の塗りは token の #rrggbb と、半透明の rgba() の
// どちらも来る。片方しか読めないと、読めない方は全部同じ文字色になる。
function rgbaOf(color) {
  const s = String(color);
  const hex = s.match(/^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);
  if (hex) return [1, 2, 3].map((i) => parseInt(hex[i], 16)).concat(1);
  const fn = s.match(/(\d+)[,\s]+(\d+)[,\s]+(\d+)(?:[,\s]+([\d.]+))?/);
  if (fn) return [Number(fn[1]), Number(fn[2]), Number(fn[3]), fn[4] === undefined ? 1 : Number(fn[4])];
  return null;
}

// 塗りの上に載せる文字色。帯の塗りは半透明のこともあるので、地色と混ぜた実際の明るさで選ぶ
// (alphaを無視すると濃い側/薄い側の境目を読み違える)。
function inkOnFill(fill) {
  const c = rgbaOf(fill);
  if (!c) return WHALE_LABEL_INK;
  // 地色はchartが敷く紙の面。CSS側の定義を唯一の根拠にする。
  const bg = rgbaOf(CHART_SURFACE_COLOR);
  const mix = [0, 1, 2].map((i) => c[3] * c[i] + (1 - c[3]) * bg[i]);
  const lum = (0.299 * mix[0] + 0.587 * mix[1] + 0.114 * mix[2]) / 255;
  return lum > 0.5 ? WHALE_LABEL_INK : WHALE_VALUE_ON_FILL;
}

// 段の縦目盛りを伏せている代わりに、棒に人数そのものを書く。0の日は棒が立たないので書かない
// (0が並ぶと、投げた人が居なかった日と配信が無かった日の区別も付かないまま数字だけが密集
// する)。日数が増えて数字が棒の間隔に入らなくなったら、その段は数字を出さない(重ねて出すと
// 隣の日の数字と混ざって読めなくなる)。その場合も実数はtooltipと段の最大値で読める。
//
// 置き場所は棒の上。上に1行ぶん残っていない一番高い棒だけは棒の中へ入れる。全部の棒が
// 収まるだけの余白を上へ空けると、その空きぶん棒が縮んで段の上半分が死ぬ。
function makeWhaleValuePlugin(fill) {
  const onFill = inkOnFill(fill);
  return {
    id: "tictokWhaleValues",
    afterDatasetsDraw(chart) {
      const els = chart.getDatasetMeta(0).data || [];
      const values = chart.data.datasets[0].data || [];
      if (!els.length) return;
      const { ctx, chartArea } = chart;
      ctx.save();
      ctx.font = WHALE_VALUE_FONT;
      ctx.textAlign = "center";
      const step = els.length > 1
        ? Math.abs(els[1].x - els[0].x)
        : chartArea.right - chartArea.left;
      const widest = values.reduce((m, v) => Math.max(m, v ? ctx.measureText(fmtNum(v)).width : 0), 0);
      if (widest && widest + 2 > step) {
        ctx.restore();
        return;
      }
      els.forEach((el, i) => {
        const v = values[i];
        if (!v) return;
        const above = el.y - 2;
        if (above - WHALE_VALUE_LINE >= chartArea.top) {
          ctx.fillStyle = WHALE_LABEL_INK;
          ctx.textBaseline = "bottom";
          ctx.fillText(fmtNum(v), el.x, above);
        } else {
          ctx.fillStyle = onFill;
          ctx.textBaseline = "top";
          ctx.fillText(fmtNum(v), el.x, el.y + 1);
        }
      });
      ctx.restore();
    },
  };
}

// 棒に重ねたときに出す顔ぶれ。人数だけでは「同じ常連が毎日居るのか、日替わりで別人が
// 来ているのか」が読めない。canvasの中にはアイコン画像を置けないので、chartの標準tooltipは
// 伏せてHTMLの札を自前で出す(身元の見せ方は表のuserCellと同じ組にする)。
const WHALE_TIP_ROWS = 12;

// 札は1枚を使い回す。段ごとに持つと、段を跨いでcursorを動かしたとき前の段の札が残る。
let whaleTipEl = null;
function whaleTip() {
  if (!whaleTipEl) {
    whaleTipEl = document.createElement("div");
    whaleTipEl.className = "sm-whale-tip hidden";
    document.body.appendChild(whaleTipEl);
  }
  return whaleTipEl;
}

// 札の中身。人数(count)は帯の集計そのもので、一覧は表示用に切れうる。切れた分は
// 「他N人」で名乗る(一覧の行数を人数として読ませない)。
function fillWhaleTip(tip, title, count, rows, people) {
  tip.textContent = "";
  const head = document.createElement("div");
  head.className = "sm-whale-tip-head";
  head.textContent = `${title} ${fmtNum(count)}人`;
  tip.appendChild(head);
  rows.slice(0, WHALE_TIP_ROWS).forEach((w) => {
    const person = people[w.key] || {};
    const row = document.createElement("div");
    row.className = "sm-whale-tip-row";
    row.appendChild(userCell(person, { hideBadges: true, avatarClass: "sm" }));
    const coins = document.createElement("b");
    coins.className = "sm-whale-tip-coins";
    coins.textContent = fmtNum(w.coins);
    row.appendChild(coins);
    tip.appendChild(row);
  });
  const rest = count - Math.min(rows.length, WHALE_TIP_ROWS);
  if (rest > 0) {
    const more = document.createElement("div");
    more.className = "sm-whale-tip-more";
    more.textContent = `他 ${fmtNum(rest)}人`;
    tip.appendChild(more);
  }
}

// 置き場所。canvasの中の座標(caret)をviewport座標へ直し、はみ出す側では反対へ寄せる。
// 札は段の高さより背が高くなるので、段の中に収める前提では置けない。
function placeWhaleTip(tip, canvas, caretX, caretY) {
  const rect = canvas.getBoundingClientRect();
  const box = tip.getBoundingClientRect();
  const gap = 12;
  let left = rect.left + caretX + gap;
  if (left + box.width > window.innerWidth - 8) left = rect.left + caretX - box.width - gap;
  let top = rect.top + caretY - box.height / 2;
  top = Math.min(Math.max(top, 8), window.innerHeight - box.height - 8);
  tip.style.left = `${Math.max(left, 8)}px`;
  tip.style.top = `${top}px`;
}

// 帯ごとに独立目盛りの小型panelを縦へ並べる(small multiples)。1枚へ積み上げると、
// 下の帯が動いた分だけ上の帯の底が上下するので、その帯自身の増減が読めない。加えて
// 1K〜5Kは日に数人・100K↑は0〜1人と桁が違い、共通目盛りでは上位帯が線にもならない。
// 目盛りを出すと段ごとに左端の位置がずれて日付が縦に対応しなくなるため、目盛りは伏せて
// 段ごとに「最大N人」を添える(段どうしの高さは比べられない、と読ませる)。
//
// 名前と最大値は棒の領域へ重ねず、左の欄へ出す。重ねると名前1行ぶんの余白を常に上へ
// 空けることになり、段の高さの3〜4割が塗りに使えないまま残る。
function createWhaleChart(container) {
  // 最下段だけx軸目盛りを出す。端の目盛りlabelのはみ出し分だけChart.jsが左右にpaddingを
  // 足すので、全段へ同じ左右padを固定して日付の横位置を揃える(TIMELINEと同じ作り)。
  const EDGE = 16;
  let specs = [];
  let panels = [];
  // 札(顔ぶれ)が引く元。棒に持たせず、描いた時のpayloadをそのまま覚えておく。
  let rows = [];
  let people = {};

  // 段の構成: 最上段が「1K↑ 合計」、以下が帯ごと。合計の呼び名は最小帯の下限そのもので、
  // 文字で書くと帯定義を変えたときここだけ古い額を名乗るのでserverの帯から作る。
  function panelSpecs(tiers) {
    if (!tiers.length) return [];
    const colors = whaleTierColors(tiers.length);
    return [{ key: "total", label: `${tiers[0].min_label}↑ 合計`, color: WHALE_TOTAL_COLOR, tier: null }].concat(
      tiers.map((t, i) => ({
        key: `tier${i}`,
        label: t.label,
        color: colors[i],
        // 顔ぶれを引くときの帯番号。合計段(null)は帯で絞らず、その日の大口を全部出す。
        tier: i,
      })),
    );
  }

  function makePanel(spec, isLast) {
    // 左の欄(名前+最大値)と右の塗り。gridの1行ぶんとして2cellを直に並べるので、名前欄の
    // 幅は全段で揃い、塗りの左端も自動で一致する。
    const head = document.createElement("div");
    // 最下段は日付の目盛り1行ぶん高い。名前も同じだけ下がると棒の帯からずれるので詰める。
    head.className = isLast ? "sm-whale-head is-last" : "sm-whale-head";
    const name = document.createElement("b");
    name.className = "sm-whale-name";
    const swatch = document.createElement("i");
    swatch.className = "a-spark-swatch";
    swatch.style.background = spec.color;
    const nameText = document.createElement("span");
    nameText.textContent = spec.label;
    name.appendChild(swatch);
    name.appendChild(nameText);
    const peak = document.createElement("span");
    peak.className = "sm-whale-peak";
    head.appendChild(name);
    head.appendChild(peak);
    const plot = document.createElement("div");
    plot.className = "sm-whale-plot";
    const canvas = document.createElement("canvas");
    plot.appendChild(canvas);
    container.appendChild(head);
    container.appendChild(plot);

    // 棒に重ねたときの札。段が持つのは帯だけなので、その日の顔ぶれをこの段の帯で絞る
    // (合計段は絞らない)。人数は帯の集計そのものを出し、一覧の行数から数え直さない。
    function showTip(ctx) {
      const tip = whaleTip();
      const point = (ctx.tooltip.dataPoints || [])[0];
      const day = point ? rows[point.dataIndex] : null;
      if (!ctx.tooltip.opacity || !day) {
        tip.classList.add("hidden");
        return;
      }
      const count = spec.tier === null
        ? day.whales || 0
        : (day.tiers || [])[spec.tier] || 0;
      // 同じ段の同じ日に居る間は組み直さない。mousemoveのたびに作り直すと、そのたびに
      // アイコンのimgが差し替わってちらつき、proxyへの再読込も無駄に走る。
      const at = `${spec.key}|${day.date}`;
      tip.classList.remove("hidden");
      if (tip.dataset.at === at) return;
      tip.dataset.at = at;
      const list = (day.whales_list || []).filter(
        (w) => spec.tier === null || w.tier === spec.tier,
      );
      fillWhaleTip(tip, `${day.date} ${spec.label}`, count, list, people);
      placeWhaleTip(tip, ctx.chart.canvas, ctx.tooltip.caretX, ctx.tooltip.caretY);
    }

    const chart = new Chart(canvas, {
      type: "bar",
      data: { labels: [], datasets: [{ label: spec.label, data: [], backgroundColor: spec.color, borderWidth: 0 }] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        layout: { padding: { top: 2, right: isLast ? 0 : EDGE, bottom: 0, left: isLast ? 0 : EDGE } },
        interaction: { mode: "index", intersect: false },
        scales: {
          x: {
            display: isLast,
            afterFit(scale) { scale.paddingLeft = EDGE; scale.paddingRight = EDGE; },
            ticks: { ...nierTicks(), maxRotation: 0, autoSkip: true, maxTicksLimit: 12 },
            grid: { color: NIER_GRID_COLOR },
          },
          // 一番高い棒は段の上端近くまで伸ばす(数字はその棒の中へ入る)。
          y: { display: false, beginAtZero: true, grace: "6%" },
        },
        plugins: {
          legend: { display: false },
          // canvasの中にはアイコンを描けないので、標準tooltipは伏せてHTMLの札を出す。
          tooltip: { ...nierTooltip(), enabled: false, external: showTip },
        },
      },
      plugins: [makeWhaleValuePlugin(spec.color)],
    });
    return { spec, chart, peak };
  }

  // 帯の本数・labelはserverの定義に従う。段を作り直すのは構成が変わった時だけで、同じ
  // 配信者を選び直しただけならdataの差し替えで済ませる。
  function syncPanels(next) {
    const same = specs.length === next.length && specs.every((s, i) => s.label === next[i].label);
    if (same) return;
    panels.forEach((p) => p.chart.destroy());
    container.textContent = "";
    specs = next;
    panels = next.map((s, i) => makePanel(s, i === next.length - 1));
    // 1段の高さはCSS側(--whale-row)が決める。最下段だけ日付の目盛り1行ぶん高くする。
    const last = "calc(var(--whale-row) + var(--whale-axis))";
    container.style.gridTemplateRows = next.length > 1
      ? `repeat(${next.length - 1}, var(--whale-row)) ${last}`
      : last;
  }

  function update(days, tiers, roster) {
    syncPanels(panelSpecs(tiers || []));
    rows = days;
    people = roster || {};
    // 段を組み直したときも札は前の配信者の顔ぶれを出したまま残りうる。描き直しで畳み、
    // 「今出している段と日」も忘れる(同じ日付の別配信者で古い顔ぶれを使い回さない)。
    if (whaleTipEl) {
      whaleTipEl.classList.add("hidden");
      delete whaleTipEl.dataset.at;
    }
    const labels = days.map((d) => d.date);
    panels.forEach((p, i) => {
      const values = i === 0
        ? days.map((d) => d.whales || 0)
        : days.map((d) => (d.tiers || [])[i - 1] || 0);
      const peak = values.reduce((m, v) => (v > m ? v : m), 0);
      p.chart.data.labels = labels;
      p.chart.data.datasets[0].data = values;
      p.peak.textContent = `最大 ${fmtNum(peak)}人`;
      p.chart.update();
    });
  }
  return { update };
}

// 帯ごとの人数は「その日1K以上を投げた人」の内訳。1人も居ない配信者では空表示にする。
function renderWhales(data) {
  const days = data.days || [];
  const tiers = data.tiers || [];
  const total = days.reduce((a, d) => a + (d.whales || 0), 0);
  document.getElementById("sm-whale-empty").classList.toggle("hidden", total > 0);
  // 1人も居ないなら段を並べても0の平線が並ぶだけ。案内文だけを残してgraphは畳む。
  document.getElementById("sm-whale-panels").classList.toggle("hidden", total === 0);
  const peak = days.reduce((a, d) => Math.max(a, d.whales || 0), 0);
  document.getElementById("sm-whale-note").textContent = total
    ? `${days.length}日 / 最大 ${fmtNum(peak)}人`
    : "";
  whaleChart.update(days, tiers, data.people);
}

// 内訳(新規/復帰/継続)は「つながりの強さ」の順序尺度なので、大口帯と同じく系統色を
// 薄→濃で当てる。別々の色にすると順序が読めず、色の対応を凡例で引き直すことになる。
// 濃い側ほど関係が長い(継続)。
const COHORT_TIER_COLORS = rampOf(3);
const COHORT_NEW_COLOR = COHORT_TIER_COLORS[0];
const COHORT_RETURNED_COLOR = COHORT_TIER_COLORS[1];
const COHORT_RETAINED_COLOR = COHORT_TIER_COLORS[2];
// 率の線は人数の棒と別物なので、棒の系統色から外れた色を当てる。
const COHORT_RATE_COLOR = cssToken("--series-4");
// Activeは3系列の合計であって内訳の1つではない。系統色から外した無彩の破線で、
// 内訳と同じ色の仲間に見えないようにする。
const COHORT_TOTAL_COLOR = NIER_AXIS_COLOR;

// 下から順に「継続→復帰→新規」。関係が長い側を先に置く(凡例の並びも同じ)。
const COHORT_SERIES = [
  { label: "継続", color: COHORT_RETAINED_COLOR, pick: (d) => d.retained },
  { label: "復帰", color: COHORT_RETURNED_COLOR, pick: cohortReturned },
  { label: "新規", color: COHORT_NEW_COLOR, pick: (d) => d.new },
];

function cohortLegend() {
  return { labels: { color: cssToken("--chart-ink"), font: { family: "monospace", size: 11 }, boxWidth: 14, boxHeight: 8 } };
}

// 人数(線)と継続率(線)は単位が違う。1枚に重ねると目盛りが左右2本になり、どの系列が
// どちらの軸のものかを読む手間が常にかかるので、日付軸を共有した2枚に分ける。
// 上=内訳(人)、下=率(%)。同じ日が上下で同じ横位置に来るよう、左目盛りの幅を揃える。
//
// 内訳は積み上げない。積み上げると土台(継続)が動いた分だけ上の系列の底も上下するので、
// 復帰や新規が増えたのか土台が動いただけなのかが読めない。3系列は同じ桁に収まるため、
// 同じ目盛りの上に線で重ねれば系列ごとの推移をそのまま追える。積み上げの高さで読めて
// いたActive(その日の実人数)は、合計の破線として別に引く。
function createCohortChart(countCanvas, rateCanvas) {
  let days = [];
  // Chart.jsは左目盛りの幅を「人数の桁数」「100%」といった目盛り文字から別々に決めるので、
  // 2枚を素のまま描くと同じ日が上下でずれる。fitが出した素の幅を控えてから、広い方へ
  // 合わせる。canvasの大きさが変わって再fitが走っても、そのたびに揃え直す。
  const naturalWidth = { count: 0, rate: 0 };
  const pinAxis = (self, other) => (scale) => {
    naturalWidth[self] = scale.width;
    scale.width = Math.max(scale.width, naturalWidth[other]);
  };
  const dayAxis = (showLabels) => ({
    ticks: { ...nierTicks(), display: showLabels, maxRotation: 0, autoSkip: true, maxTicksLimit: 12 },
    grid: { color: NIER_GRID_COLOR },
  });
  const count = new Chart(countCanvas, {
    type: "line",
    data: {
      labels: [],
      datasets: COHORT_SERIES.map((s) => ({
        label: s.label, data: [], borderColor: s.color, backgroundColor: s.color,
        borderWidth: 2, pointRadius: 2.5, pointHoverRadius: 5, tension: 0.25,
      })).concat([{
        label: "Active(合計)", data: [], borderColor: COHORT_TOTAL_COLOR, backgroundColor: COHORT_TOTAL_COLOR,
        borderWidth: 1, borderDash: [4, 4], pointRadius: 0, tension: 0.25,
      }]),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        // 日付は下のグラフが持つ。同じ軸を2回書くと縦の対応が読みにくくなる。
        x: dayAxis(false),
        y: {
          beginAtZero: true, afterFit: pinAxis("count", "rate"),
          title: { display: true, text: "人", color: NIER_AXIS_COLOR, font: { family: "monospace", size: 10 } },
          ticks: nierTicks(), grid: { color: NIER_GRID_COLOR },
        },
      },
      plugins: {
        legend: cohortLegend(),
        tooltip: {
          ...nierTooltip(),
          // Activeは3系列の合計そのもの。本文と footer に同じ数を2度出さない。
          filter: (item) => item.datasetIndex < COHORT_SERIES.length,
          callbacks: {
            label: (item) => `${item.dataset.label}: ${fmtNum(item.parsed.y)}人`,
            footer: (items) =>
              (items.length ? `Active: ${fmtNum(days[items[0].dataIndex].active)}人` : ""),
          },
        },
      },
    },
  });
  const rate = new Chart(rateCanvas, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          label: "継続率", data: [], borderColor: COHORT_RATE_COLOR, backgroundColor: COHORT_RATE_COLOR,
          borderWidth: 2, pointRadius: 2.5, pointHoverRadius: 5, tension: 0.25,
          // 率が無い日(初日)は線を繋がない。繋ぐと存在しない値を通ったように見える。
          spanGaps: false,
        },
        {
          label: "平均", data: [], borderColor: NIER_AXIS_COLOR, backgroundColor: NIER_AXIS_COLOR,
          borderWidth: 1, borderDash: [4, 4], pointRadius: 0, tension: 0,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: dayAxis(true),
        y: {
          beginAtZero: true, max: 100, afterFit: pinAxis("rate", "count"),
          ticks: { ...nierTicks(), callback: (v) => `${v}%` }, grid: { color: NIER_GRID_COLOR },
        },
      },
      plugins: {
        legend: cohortLegend(),
        tooltip: {
          ...nierTooltip(),
          // 平均は全日同じ値の目安線。日ごとのtooltipに混ぜると読む物が増えるだけ。
          filter: (item) => item.datasetIndex === 0,
          callbacks: {
            label: (item) => `継続率: ${item.parsed.y.toFixed(0)}%`,
            // 率だけでは何人の話か分からない。分母(前回配信日のActive)と分子を添える。
            footer: (items) => {
              if (!items.length) return "";
              const i = items[0].dataIndex;
              const prev = days[i - 1];
              if (!prev) return "";
              return `前回 ${prev.date} の ${fmtNum(prev.active)}人 のうち ${fmtNum(days[i].retained)}人`;
            },
          },
        },
      },
    },
  });
  function update(next) {
    days = next;
    const labels = days.map((d) => d.date);
    count.data.labels = labels;
    COHORT_SERIES.forEach((s, i) => {
      count.data.datasets[i].data = days.map(s.pick);
    });
    count.data.datasets[COHORT_SERIES.length].data = days.map((d) => d.active);
    const rates = days.map((d) => d.retention);
    const known = rates.filter((v) => v !== null);
    const avg = known.length ? known.reduce((a, v) => a + v, 0) / known.length : null;
    rate.data.labels = labels;
    rate.data.datasets[0].data = rates;
    rate.data.datasets[1].label = avg === null ? "平均" : `平均 ${avg.toFixed(0)}%`;
    rate.data.datasets[1].data = labels.map(() => avg);
    // 1度目で互いの素の幅が出揃うので、2度目で狭い方が広い方へ寄る。
    count.update();
    rate.update();
    count.update();
    rate.update();
  }
  return { update };
}

// ---- 未監視の配信者の発見 ----
// 候補は過去の全Battleの対戦相手から毎回導出する(保存しない)。順位は「時間減衰つき対戦数」で、
// 閾値・半減期・件数は設定画面の「配信者の発見」で変えられる。
// 昇格は監視画面と同じ POST /api/monitors を呼ぶ。ここ専用の追加経路は作らない。
let discoverMode = "candidates";

function discoverBusy(busy) {
  document.getElementById("sm-discover-tab-candidates").disabled = busy;
  document.getElementById("sm-discover-tab-dismissed").disabled = busy;
}

function openDiscover(mode) {
  discoverMode = mode;
  const discoverModal = document.getElementById("sm-discover-modal");
  discoverModal.classList.remove("hidden");
  focusModalOpen(discoverModal, document.getElementById("sm-discover-close"));
  loadDiscover();
}

function closeDiscover() {
  const discoverModal = document.getElementById("sm-discover-modal");
  discoverModal.classList.add("hidden");
  focusModalClose(discoverModal);
  document.getElementById("sm-discover-message").textContent = "";
}

function discoverHead(labels) {
  const head = document.getElementById("sm-discover-head");
  head.innerHTML = "";
  labels.forEach((label) => {
    const th = document.createElement("th");
    th.textContent = label;
    head.appendChild(th);
  });
}

function actionButton(label, title, onClick, danger) {
  const btn = document.createElement("button");
  btn.className = "btn btn-small" + (danger ? " btn-danger" : "");
  btn.textContent = label;
  btn.title = title;
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    try {
      await onClick();
    } catch (err) {
      // messageはmodal上端(表の直前)にあり、押したbuttonは数十行スクロールした先の行内。
      // 行は消えないまま理由だけ画面外に出るので、押した場所から離れないtoastでも名乗る。
      document.getElementById("sm-discover-message").textContent = err.message;
      showError(err, `「${label}」`);
      btn.disabled = false;
    }
  });
  return btn;
}

async function loadDiscover() {
  const isCandidates = discoverMode === "candidates";
  const title = document.getElementById("sm-discover-title");
  const note = document.getElementById("sm-discover-note");
  const empty = document.getElementById("sm-discover-empty");
  document.getElementById("sm-discover-message").textContent = "";
  document.getElementById("sm-discover-tab-candidates").classList.toggle("btn-primary", isCandidates);
  document.getElementById("sm-discover-tab-dismissed").classList.toggle("btn-primary", !isCandidates);
  title.textContent = isCandidates ? "未監視の配信者（発見候補）" : "却下した候補";
  empty.dataset.label = isCandidates ? "発見候補" : "却下した候補";
  setListState(empty, "loading");
  document.getElementById("sm-discover-rows").innerHTML = "";
  discoverBusy(true);
  let payload;
  try {
    payload = await apiSend("GET", isCandidates ? "/api/discovery" : "/api/discovery/dismissed");
  } catch (err) {
    // 取得失敗を0件として描くと「候補はいない」という誤った事実の提示になる。
    discoverHead([]);
    note.textContent = "";
    setListState(empty, "failed", err);
    discoverBusy(false);
    return;
  } finally {
    discoverBusy(false);
  }
  if (isCandidates) renderCandidates(payload);
  else renderDismissed(payload.dismissed || []);
}

function renderCandidates(payload) {
  const rows = payload.candidates || [];
  document.getElementById("sm-discover-note").textContent =
    `対戦${payload.min_contacts}回以上の未監視の配信者 ${payload.eligible} 名のうち上位 ${rows.length} 名`
    + `（対戦相手 ${payload.seen} 名を集計・半減期 ${payload.half_life_days} 日`
    + `・却下 ${payload.dismissed} 名を除外）`;
  discoverHead(["#", "配信者", "対戦数", "直近の対戦", "スコア", "当たった監視配信者", "操作"]);
  setListMessage(
    document.getElementById("sm-discover-empty"),
    "条件に合う候補がありません。設定の「候補に出す最小のBattle対戦数」を下げると増えます。",
  );
  renderTableRows(
    "sm-discover-rows",
    "sm-discover-empty",
    rows,
    (c, rank) => {
      const actions = document.createElement("span");
      actions.className = "modal-head-actions";
      actions.appendChild(
        // 監視追加は非破壊で、いつでも外せる。同じ画面の「却下」に確認が無いのに
        // こちらだけ挟むのは重さが逆で、確認dialogそのものが読み飛ばされる。
        actionButton("監視へ追加", `@${c.unique_id} の監視を開始します。（LIVE中なら接続し、設定に従って録画します。あとで監視対象から外せます）`, async () => {
          await apiSend("POST", "/api/monitors", { unique_id: c.unique_id, record_video: true });
          showToast(`@${c.unique_id} の監視を開始しました。`);
          loadDiscover();
          loadStreamers();
        }),
      );
      actions.appendChild(
        actionButton("却下", "この配信者を候補に出さないようにします（後から戻せます）。", async () => {
          await apiSend("POST", `/api/discovery/${encodeURIComponent(c.unique_id)}/dismiss`);
          showToast(`@${c.unique_id} を候補から外しました。`);
          loadDiscover();
        }, true),
      );
      return [
        String(rank),
        userCell(c, { stackId: true }),
        `${fmtNum(c.contacts)} 戦`,
        fmtDateTime(c.last_contact),
        c.score.toFixed(2),
        c.via.map((v) => `@${v}`).join(" / "),
        actions,
      ];
    },
    [0, 2, 4],
  );
}

function renderDismissed(rows) {
  document.getElementById("sm-discover-note").textContent =
    `候補に出さないようにした配信者 ${rows.length} 名`;
  discoverHead(["配信者", "却下した日時", "操作"]);
  setListMessage(
    document.getElementById("sm-discover-empty"),
    "却下した候補はありません。",
  );
  renderTableRows(
    "sm-discover-rows",
    "sm-discover-empty",
    rows,
    (d) => [
      `@${d.unique_id}`,
      fmtDateTime(d.dismissed_at),
      actionButton("候補へ戻す", "この配信者を再び候補に出します。", async () => {
        await apiSend("DELETE", `/api/discovery/${encodeURIComponent(d.unique_id)}/dismiss`);
        showToast(`@${d.unique_id} を候補に戻しました。`);
        loadDiscover();
      }),
    ],
    [],
  );
}

// ---- WS: 収集中の更新で選択中の配信者を貼り替える ----
// monitors/stateは収集中に高頻度で届く。一覧の取り直しはserver側で127〜207msかかるので、
// 1件ごとに引くと収集の裏で最も重い側へ張り付く。~1秒で合体させて最大1回/秒に抑える
// (履歴画面のscheduleReloadと同じ作法)。
let reloadTimer = null;
function scheduleReload() {
  if (reloadTimer) return;
  reloadTimer = setTimeout(() => {
    reloadTimer = null;
    loadStreamers();
  }, 1000);
}

function handleMessage(msg) {
  if (msg.type === "monitors" || msg.type === "state") {
    // 画面を開いた直後の1通目は、末尾のloadStreamers()と同じ内容を運んでくるだけなので
    // 取り直さない(印はcommon.jsのconnectWSが付ける)。
    if (!msg.initial) scheduleReload();
  }
  if ((msg.type === "stats" || msg.type === "battles") && msg.monitor === selectedUid) {
    selectStreamer(selectedUid, true);
  }
}

elSearch.addEventListener("input", renderList);
// 復元はここで済ませる。初期描画(renderProfile→renderHeatmap / renderOpponentRows)は
// profile取得の後なので、この時点で値を入れておけば復元後の値で描かれる。
bindPref(elHmMetric, PREF_HM_METRIC, renderHeatmap);
bindPref(elTrendUnit, PREF_TREND_UNIT, () => renderTrend(currentSessions, currentViewerLevel));
document.getElementById("sm-opp-search").addEventListener("input", renderOpponentRows);
// 軸の切替は取得済みのrowsを描き直すだけ。profileの再取得は要らない。
bindPref(document.getElementById("sm-battle-trend-x"), PREF_BATTLE_TREND_X, () => battleTrendChart.applyMode());
bindPref(document.getElementById("sm-battle-trend-y"), PREF_BATTLE_TREND_Y, () => battleTrendChart.applyMode());
bindPref(document.getElementById("sm-opp-min"), PREF_OPP_MIN, renderOpponentRows);
bindPref(document.getElementById("sm-opp-sort"), PREF_OPP_SORT, renderOpponentRows);
document.getElementById("sm-battle-history-clear").addEventListener("click", clearOpponentPick);
// 期間別ランキング。粒度は残し、選んだ期間は残さない(絶対日付は次に開いた時には別の意味)。
Object.entries(RANKING_TABLES).forEach(([tableId, conf]) => {
  const gran = initSegmented(`${tableId}-gran`);
  bindPref(gran, conf.pref, () => {
    rankingPick[tableId].granularity = gran.value;
    // 粒度を変えたら期間は選び直す。月の "2026-07" を週の一覧へ持ち越せない。
    rankingPick[tableId].period = "";
    applyRanking(tableId);
  });
  rankingPick[tableId].granularity = gran.value;
  document.getElementById(`${tableId}-period`).addEventListener("change", (e) => {
    rankingPick[tableId].period = e.target.value;
    applyRanking(tableId);
  });
});
document.querySelectorAll(".sm-period-step").forEach((btn) => {
  btn.addEventListener("click", () => stepPeriod(btn.dataset.target, Number(btn.dataset.step)));
});
// 人×期間の列。粒度は残すが、カレンダーで選んだ日付は残さない(絶対日付を復元すると、
// 次に開いた時には別の意味になる)。2つの表は窓を共有せず、それぞれ引き直す。
Object.entries(MATRIX_TABLES).forEach(([id, conf]) => {
  const gran = initSegmented(`${id}-gran`);
  bindPref(gran, conf.pref, () => {
    const st = matrixState[id];
    st.granularity = gran.value;
    // 粒度が変われば列そのものが変わる。列で並べていた指定は持ち越せない。
    st.sort = "total";
    st.asc = false;
    if (selectedUid) applyMatrix(id, selectedUid);
  });
  matrixState[id].granularity = gran.value;
  ["since", "until"].forEach((edge) => {
    document.getElementById(`${id}-${edge}`).addEventListener("change", (e) => {
      matrixState[id][edge] = e.target.value;
      if (selectedUid) applyMatrix(id, selectedUid);
    });
  });
  document.getElementById(`${id}-latest`).addEventListener("click", () => {
    const st = matrixState[id];
    if (!st.since && !st.until) return;
    st.since = "";
    st.until = "";
    document.getElementById(`${id}-since`).value = "";
    document.getElementById(`${id}-until`).value = "";
    if (selectedUid) applyMatrix(id, selectedUid);
  });
});
document.getElementById("sm-ai-btn").addEventListener("click", () => runAiReview(false));
document.getElementById("sm-ai-rerun").addEventListener("click", () => runAiReview(true));
document.getElementById("sm-video-stop").addEventListener("click", closeVideo);
document.getElementById("sm-discover-btn").addEventListener("click", () => openDiscover("candidates"));
document.getElementById("sm-discover-tab-candidates").addEventListener("click", () => openDiscover("candidates"));
document.getElementById("sm-discover-tab-dismissed").addEventListener("click", () => openDiscover("dismissed"));
document.getElementById("sm-discover-close").addEventListener("click", closeDiscover);
document.getElementById("sm-discover-modal").addEventListener("click", (e) => {
  if (e.target.id === "sm-discover-modal") closeDiscover();
});
bindVideoError(
  document.getElementById("sm-video"),
  () => playingRecordingId,
  (text) => { document.getElementById("sm-video-message").textContent = text; },
);
// 音量・muteは<video>のpropertyで<select>やcheckboxではないため、restorePrefではなく
// 直接当てる。srcが無いうちに入れても保持され、load()で戻らないので再生前に効く。
// (値を入れるだけで再生は始まらない)
const elVideo = document.getElementById("sm-video");
const savedVolume = prefGet(PREF_VIDEO_VOLUME);
if (savedVolume !== null) {
  const vol = Number(savedVolume);
  if (Number.isFinite(vol) && vol >= 0 && vol <= 1) elVideo.volume = vol;
}
elVideo.muted = prefBool(PREF_VIDEO_MUTED, elVideo.muted);
elVideo.addEventListener("volumechange", () => {
  prefSet(PREF_VIDEO_VOLUME, elVideo.volume);
  prefSet(PREF_VIDEO_MUTED, elVideo.muted ? "1" : "0");
});
document.getElementById("sm-battle-close").addEventListener("click", closeBattleDetail);
document.getElementById("sm-battle-modal").addEventListener("click", (e) => {
  if (e.target.id === "sm-battle-modal") closeBattleDetail();
});
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (!document.getElementById("sm-discover-modal").classList.contains("hidden")) closeDiscover();
  else if (!document.getElementById("sm-battle-modal").classList.contains("hidden")) closeBattleDetail();
});
trendChart = createSessionTrendChart(document.getElementById("sm-trend"), {
  panels: ["coins", "comments", "viewers", "peak", "hours"],
  movingAvg: true,
  movingAvgWindow: TREND_MA_WINDOW,
});
cohortChart = createCohortChart(
  document.getElementById("sm-cohort-chart"),
  document.getElementById("sm-cohort-rate-chart"),
);
whaleChart = createWhaleChart(document.getElementById("sm-whale-panels"));
battleTrendChart = createBattleTrendChart(document.getElementById("sm-battle-trend"));
coopTrendChart = createCoopTrendChart(document.getElementById("sm-coop-trend"));
loadAiStatus();
loadStreamers();
connectWS(handleMessage);
