"use strict";

// 素材画面: 収集の途中でdiskへ溜めたTikTok由来の画像(Userアイコン・Giftアイコン・Emote)を
// 一覧し、検索してZIPで取り出す。ここに出るのは既に手元に在るcacheだけで、この画面から
// TikTokへ取りに行くことはしない — 一覧に無い=その時に取り込めなかった、が事実。
//
// 種別(kind)はserverのsummaryが唯一の出所。画面へ種別の一覧を書くと、poolへ種別が増えた
// 時に画面だけが黙って古いままになる(Job画面の種別labelで実際に起きたのと同じ形)。

// 並び順のkey→日本語。keyそのものはserverが決め、画面は名前だけを持つ。ここに無いkeyが
// 来たらkeyのまま出す — 訳語を勝手に作ると、serverが受ける値と画面の語がずれる。
const ASSET_SORT_LABELS = {
  name: "名前",
  size: "容量",
  mtime: "更新日時",
  last_seen: "最近見た順",
  // 集計値で並べる版。ここに書くのは選択肢の語だけで、「どの種別がどの数字を持つか」は
  // 持たない(それを決めるのはserverのsorts)。並び順のkeyはタイルのstatsのkeyと同じ物なので、
  // 「今どの数字で並んでいるか」はその項目を強調して示す ―― 画面が種別と数字の対応表を
  // 持つと、serverが項目を足した時に画面だけが黙って古いままになる。
  // sendsはevent数ではなくgift_countの合計(=個数)。「回数」と名乗ると、10連ギフトが
  // 1回に見えるのに数字は10と出て食い違う。coinsは1個あたりの単価で、そのgift 1回の
  // 総額ではない。
  sends: "送られた個数",
  coins: "コイン単価",
  uses: "使われた回数",
  freq: "出現回数",
};

// 集計(rescan)がないと成立しない並び順。ASSET_SORT_LABELSのうち、値がsnapshotの集計から
// 来るものだけを挙げる(name/size/mtime/last_seenはfileとDBから直に出るので集計は要らない)。
const ASSET_STAT_SORTS = new Set(["sends", "coins", "uses", "freq"]);

// 種別が受ける絞込の名前。summaryのkindが filters で名乗る。画面は「どの種別が配信者で
// 絞れるか」を持たない ―― 種別名で出し分けると、同じ絞込を受ける種別が増えた時に
// その種別だけ絞れないまま黙る(並び順をsortsから作っているのと同じ理由)。
const ASSET_FILTER_STREAMER = "streamer";

// 語なしで端から眺めても目的の素材へ辿り着けない大きさの境目。Userアイコンは19万件あり、
// 並べても人が端から端まで見る物ではない。避けたいのは取得の費用ではなく(一覧はlimitで
// 切ってあり実測100件233ms)、語を持たない一覧が役に立たないことの方。
// 判定は件数で決める — 「avatarだけ特別」と種別名で書くと、同じ規模の種別が増えた時に
// その種別だけ無限scrollになる。
// 根拠にするのは一覧応答のtotalで、summaryのcountではない。countは未集計だとnullで、
// 「集計していないから一覧requestも出さない」にすると、その一覧requestでしか埋まらない
// 種別のsnapshotが永久に埋まらず、264件のemote棚すら開けなくなる。
const ASSET_BROWSE_LIMIT = 5000;

// 検索は打つたびにserverを叩かない。videos(シーン検索)と同じ間合いにする。
const ASSET_SEARCH_DEBOUNCE_MS = 250;

// ZIPは2段構え。1段目のPOSTが券を返し、2段目のGETでZIPが流れる。券のURLは短いので、
// 選んだidをURLへ並べていた頃の長さの問題(1件41文字のsha1)は無くなった。
// 一度に選べる件数の上限はserverのsettingsが持つ。画面は上限を持たず、断られた理由を出す。
const ASSET_TICKET_PATH = "/api/assets/archive";

const ASSET_KIND_PREF = "tictok.assets.kind";
// 配信者の絞込は残す。同じ人の素材を追う間は種別を移っても同じ人を指し続ける物で、
// 「繰り返し同じ値を選ぶcontrol」の側(並び順・表示件数と同じ)。1回限りの入力である
// 検索語とは性質が違う。配信者動画の絞込(tictok.videos.streamer)も同じ扱いにしてある。
const ASSET_STREAMER_PREF = "tictok.assets.streamer";
const ASSET_SORT_PREF = "tictok.assets.sort";
const ASSET_ORDER_PREF = "tictok.assets.order";
const ASSET_LIMIT_PREF = "tictok.assets.limit";

let assetSummary = null;
let assetKinds = [];
let currentKind = "";
let assetItems = [];
let assetTotal = 0;
// 選んだid。種別を移ると捨てる(別の棚の物が混ざったZIPになる)。検索語を変えても残すのは、
// 22万件から語を変えながら拾い集めるのがこの画面の使い方だから。見えない選択が溜まらない
// よう、件数は常にtoolbarのbuttonが名乗る。
const assetSelected = new Set();
// 一覧が空に見えるときの理由。取得前(loading)・0件(empty)・取得失敗(failed)を取り違えると、
// 落ちているだけのserverを「素材が無い」と読み違える。
let assetListState = "loading";
// 語なしで開いた大きな種別。先頭ぶんだけを出して、続きは絞り込みへ促している状態。
let assetHeadOnly = false;
let assetListError = null;
// 応答の追い越し。検索語を打っている間は前のrequestが後から届くことがあり、そのまま
// 描くと打ち終えた語と違う結果が残る。
let assetReqSeq = 0;
let assetSearchTimer = null;

function assetKindInfo(kind) {
  return assetKinds.find((info) => info.kind === kind) || null;
}

// その種別が受ける絞込かどうか。名乗るのはserver(kindのfilters)。
function assetAcceptsFilter(info, name) {
  return Boolean(info) && Array.isArray(info.filters) && info.filters.includes(name);
}

// 選べる配信者。summaryのtop levelが唯一の出所で、一覧の中身からは作らない
// (今出ている100件に居る人だけが候補になると、絞込が絞込にならない)。
function assetStreamerList() {
  const list = assetSummary && assetSummary.streamers;
  return Array.isArray(list) ? list.filter((s) => s && s.unique_id) : [];
}

// まだ一度も集計していない種別(countがnull)。0件とは違う ―― 数えていないだけで、
// 素材はdiskに在るかもしれない。
function assetUncounted(info) {
  return Boolean(info) && (info.count === null || info.count === undefined);
}

// 集計はDBのsnapshotで、古くなり得る。いつの値かを絶対時刻で出したうえで経過も添える
// (時刻だけだと今の値と読まれる)。fans.jsの日単位は、押した直後の再集計まで
// 「24時間以内」としか言えないのでここでは使えない。
function assetElapsedText(epochSeconds) {
  const sec = Date.now() / 1000 - Number(epochSeconds || 0);
  if (sec < 60) return "たった今";
  if (sec < 3600) return `${Math.floor(sec / 60)}分前`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}時間前`;
  return `${Math.floor(sec / 86400)}日前`;
}

// 集計に掛かった時間。秒に丸めると、12msで終わる種別が全部「0秒」になる。
function assetScanCostText(ms) {
  const n = Number(ms || 0);
  if (!n) return "";
  if (n >= 10000) return `${Math.round(n / 1000)}秒`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}秒`;
  return `${Math.round(n)}ms`;
}

// 一覧に出せない素材の数。avatarのpoolには、実体は在るのに名前を辿れない素材が居る
// (鍵はsha1だけで、改名等でusers表と結び付かなくなったもの)。countはdiskの実数、
// listableはそのうち名前を辿れる点数で、countと同じ母集団を数える。差はこの
// 「名乗る名前が無い」ぶんちょうどになる — listableを人数(users表の行数)で数えると
// cacheの無い人がlistable側に入り、差が実際の名無し素材とずれる。
// 判定はlistable < countだけで行う — 種別名で出し分けると、同じ性質の種別が増えた時に
// その種別だけ黙る(検索前提の判定を件数で決めているのと同じ理由)。
function assetHiddenCount(info) {
  if (!info) return 0;
  const listable = info.listable;
  if (listable === null || listable === undefined) return 0;
  if (assetUncounted(info)) return 0;
  const gap = Number(info.count) - Number(listable);
  return gap > 0 ? gap : 0;
}

// 種別の件数・容量。集計していなければ「未集計」と名乗る(0件と書かない)。
function assetCountText(info) {
  if (!info) return "";
  if (assetUncounted(info)) return "未集計";
  return `${fmtNum(info.count)}件 / ${fmtBytes(info.bytes)}`;
}

function assetQuery() {
  return document.getElementById("as-q").value.trim();
}

function assetLimit() {
  return Number(document.getElementById("as-limit").value) || 100;
}

// 今の配信者の絞込。受けない種別ではcontrolごと伏せてあり、そこでは何も返さない。
// 伏せる=渡さない、で400を先回りする(並び順を出していない種別へsortを渡さないのと同じ形)。
function assetStreamerFilter() {
  const field = document.getElementById("as-streamer-field");
  if (field.classList.contains("hidden")) return "";
  return document.getElementById("as-streamer").value || "";
}

// 今の並び順。serverが選択肢を出していない種別では並び順を渡さない — 推測した値を送って
// 400を踏むより、選べないと名乗る方が実態に合う。
function assetSort() {
  const field = document.getElementById("as-sort-field");
  if (field.classList.contains("hidden")) return null;
  return {
    sort: document.getElementById("as-sort").value,
    order: document.getElementById("as-order").value,
  };
}

// ---- 種別pane ----------------------------------------------------------------

function renderKinds() {
  const pane = document.getElementById("as-kinds");
  pane.replaceChildren();
  if (!assetKinds.length) {
    const note = document.createElement("div");
    note.className = "as-kind-note";
    note.textContent = assetSummary ? "素材の種別がありません。" : "種別を取得できませんでした。";
    pane.appendChild(note);
    return;
  }
  assetKinds.forEach((info) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "as-kind" + (info.kind === currentKind ? " active" : "");
    button.dataset.kind = info.kind;
    button.setAttribute("aria-pressed", info.kind === currentKind ? "true" : "false");
    button.title = info.scanned_at
      ? `集計時点: ${fmtDateTime(info.scanned_at)}（${assetElapsedText(info.scanned_at)}）`
      : "この種別はまだ集計していません。「この種別を再集計」で数えられます。";
    const name = document.createElement("span");
    name.className = "as-kind-name";
    name.textContent = info.label || info.kind;
    const meta = document.createElement("span");
    meta.className = "as-kind-meta";
    meta.textContent = assetCountText(info);
    button.append(name, meta);
    button.addEventListener("click", () => selectKind(info.kind));
    pane.appendChild(button);
  });
  const root = document.createElement("div");
  root.className = "as-kind-note";
  root.textContent = assetSummary && assetSummary.pool_root ? assetSummary.pool_root : "";
  root.title = "素材poolの場所";
  pane.appendChild(root);
}

function selectKind(kind) {
  if (kind === currentKind) return;
  currentKind = kind;
  prefSet(ASSET_KIND_PREF, kind);
  assetSelected.clear();
  syncSortControls();
  syncStreamerControls();
  renderKinds();
  loadItems(true);
}

// 配信者の絞込。出すのは「その種別が受ける(filters)」かつ「選べる配信者が居る」時だけで、
// どちらかが欠けたらcontrolごと伏せる ―― 選べない選択肢だけのcontrolは、絞れるのに
// 絞れないように見える。
function syncStreamerControls() {
  const info = assetKindInfo(currentKind);
  const list = assetStreamerList();
  const show = assetAcceptsFilter(info, ASSET_FILTER_STREAMER) && list.length > 0;
  const field = document.getElementById("as-streamer-field");
  field.classList.toggle("hidden", !show);
  if (!show) return;
  const select = document.getElementById("as-streamer");
  // 選んだ配信者は種別を移っても引き継ぐ。配信者は種別に属さない身元で、同じ人のGift
  // アイコンから同じ人のEmoteへ移るのがこの絞込の使い方だから。選択(assetSelected)を
  // 種別で捨てるのは、idが別の棚の物になって混ざったZIPになるからで、ここには当てはまらない。
  // 選択肢はserverの応答から作るので、bindPrefの復元(script評価時)はここへ届かない。
  // 一度組んだ後はcontrolの値が唯一の出所で、保存値を読むのは最初に組む時だけ
  // (「すべて」へ戻した後に保存値が生き返るのを防ぐ)。
  const want = select.options.length ? select.value : (prefGet(ASSET_STREAMER_PREF) || "");
  select.replaceChildren();
  const all = document.createElement("option");
  all.value = "";
  all.textContent = "すべて";
  select.appendChild(all);
  list.forEach((streamer) => {
    const option = document.createElement("option");
    option.value = streamer.unique_id;
    option.textContent = streamer.label || streamer.unique_id;
    select.appendChild(option);
  });
  // 候補から消えた配信者(監視を外した等)を指したままにすると、一致0件の一覧から
  // 戻れなくなる。「すべて」へ落とす。
  select.value = list.some((s) => s.unique_id === want) ? want : "";
}

// 並び順の選択肢はsummaryのsortsが唯一の出所。持っていない種別ではcontrolごと伏せる。
function syncSortControls() {
  const info = assetKindInfo(currentKind);
  const sorts = Array.isArray(info && info.sorts) ? info.sorts.filter(Boolean) : [];
  const field = document.getElementById("as-sort-field");
  const orderField = document.getElementById("as-order-field");
  field.classList.toggle("hidden", sorts.length === 0);
  orderField.classList.toggle("hidden", sorts.length === 0);
  if (!sorts.length) return;
  const select = document.getElementById("as-sort");
  // 選択肢はserverの応答から作るので、bindPrefの復元(script評価時)はここへ届かない。
  // userが選んだ並び順は保存値が唯一の出所で、種別を移っても同じkeyが在れば引き継ぐ。
  // 前の種別の**既定**まで引き継ぐと、serverが先頭に置いた既定(avatarの最近見た順)が
  // 一度も選ばれないまま埋もれる。
  const want = prefGet(ASSET_SORT_PREF) || "";
  select.replaceChildren();
  sorts.forEach((key) => {
    const option = document.createElement("option");
    option.value = key;
    option.textContent = ASSET_SORT_LABELS[key] || key;
    select.appendChild(option);
  });
  // 保存値・前の種別の並び順がこの種別に無ければ、serverが並べた先頭を既定にする。
  select.value = sorts.includes(want) ? want : sorts[0];
}

// ---- 一覧 --------------------------------------------------------------------

function itemsUrl(offset) {
  const params = new URLSearchParams({ kind: currentKind });
  const q = assetQuery();
  if (q) params.set("q", q);
  const streamer = assetStreamerFilter();
  if (streamer) params.set("streamer", streamer);
  const order = assetSort();
  if (order) {
    params.set("sort", order.sort);
    params.set("order", order.order);
  }
  params.set("limit", String(assetLimit()));
  params.set("offset", String(offset));
  return `/api/assets?${params.toString()}`;
}

function fileUrl(item, download) {
  const params = new URLSearchParams({ kind: currentKind, id: String(item.id) });
  if (download) params.set("download", "1");
  return `/api/assets/file?${params.toString()}`;
}

function ticketUrl(ticket) {
  return `${ASSET_TICKET_PATH}/${encodeURIComponent(ticket)}`;
}

async function loadItems(reset) {
  const info = assetKindInfo(currentKind);
  if (!info) return;
  if (reset) {
    assetItems = [];
    assetTotal = 0;
  }
  const uncounted = assetUncounted(info);
  const seq = ++assetReqSeq;
  if (!assetItems.length) {
    assetListState = "loading";
    render();
  }
  try {
    const body = await apiSend("GET", itemsUrl(assetItems.length));
    if (seq !== assetReqSeq) return;
    assetTotal = Number(body.total || 0);
    // 語なしで端まで辿れる大きさを超えていたら、先頭ぶんは出したうえで絞り込みへ促す。
    // 出すのは、既定の並びがserverの決めた意味を持つため(avatarなら最近見た順)で、
    // 「さらに読み込む」だけを伏せて無限scrollにはしない。
    assetHeadOnly = !assetQuery() && assetTotal > ASSET_BROWSE_LIMIT;
    assetItems = assetItems.concat(body.items || []);
    assetListState = "ok";
    assetListError = null;
    // 未集計だった種別は、この一覧requestがdirを全走査したついでにsnapshotが埋まる。
    // 棚が「未集計」のまま一覧だけ出ていると数字が食い違って見えるので、読み直す
    // (DBのsnapshotを読むだけなので数ms)。埋まった後は通らない。
    if (uncounted && reset) refreshSummary();
  } catch (err) {
    if (seq !== assetReqSeq) return;
    assetItems = [];
    assetTotal = 0;
    assetHeadOnly = false;
    assetListState = "failed";
    assetListError = err;
    // 400は「この組み合わせは受け付けない」というserverの断り(絞込を受けない種別へ
    // 渡した等)。画面はその組み合わせを作らないよう先回りしているので、ここへ来たのは
    // 画面とserverの食い違い。placeholderの「取得できませんでした」だけでは直し方が
    // 読めないので、断った理由をserverの文言のまま出す。落ちている/繋がらない類は
    // 人が直せる物ではないのでplaceholderに任せる(検索の打鍵ごとにtoastを積まない)。
    if (err && err.status === 400) showError(err, "素材一覧");
  }
  render();
}

// タイルへ出す集計値。何の項目が来るか・その語はserverが決める(gift=送られた個数/コイン単価、
// emote=使われた回数…)ので、種別で分岐せず来た配列をそのまま並べる。
// 記録の無い項目はserverが落として寄越す ―― 落ちた項目を0で補うと「送られた記録が無い」が
// 「0個送られた」に化ける。値の無い項目はここでも描かない。
function assetTileStats(item) {
  const stats = Array.isArray(item && item.stats) ? item.stats : [];
  return stats.filter((stat) => stat && stat.value !== null && stat.value !== undefined);
}

// 集計値1件。unitが無ければ単位なし。sortedは「今この数字で並んでいる」印で、判定は
// 並び順のkeyとstatsのkeyが同じ物であることだけに拠る(画面は種別と数字の対応表を持たない)。
function assetStatRow(stat, sortKey) {
  const sorted = Boolean(stat.key) && stat.key === sortKey;
  const row = document.createElement("div");
  row.className = "as-stat" + (sorted ? " is-sorted" : "");
  const label = document.createElement("span");
  label.className = "k";
  label.textContent = stat.label || stat.key || "";
  const value = document.createElement("span");
  value.className = "v";
  value.textContent = `${fmtNum(stat.value)}${stat.unit || ""}`;
  row.append(label, value);
  // labelは幅で省略されるので、全文はtooltipに残す。
  row.title = `${label.textContent}: ${value.textContent}`
    + (sorted ? "（今この数字で並んでいます）" : "");
  return row;
}

// 1タイル。名前を持たない素材(名前の源が無いgift/emote)があるので、代わりの名前は作らず
// idで名乗る。cacheが無い行(cached:false)は0件として畳まず「未取得」として出し、選択と
// Downloadだけを閉じる — 人は居るがアイコンを取り込めなかった、という事実がそこにある。
function assetTile(item, sortKey) {
  const tile = document.createElement("div");
  tile.className = "as-tile";
  tile.dataset.id = String(item.id);
  const cached = item.cached !== false;
  if (!cached) tile.classList.add("as-missing");

  const pick = document.createElement("input");
  pick.type = "checkbox";
  pick.className = "as-pick";
  pick.checked = assetSelected.has(item.id);
  pick.setAttribute("aria-label", `${item.name || item.id} を選ぶ`);
  if (!cached) {
    pick.disabled = true;
    pick.title = "この素材はcacheが無いため(未取得)、選択もDownloadもできません。";
  }
  pick.addEventListener("change", () => togglePick(tile, item, pick.checked));

  const thumb = document.createElement("div");
  thumb.className = "as-thumb";
  if (cached) {
    const img = document.createElement("img");
    img.src = fileUrl(item, false);
    img.alt = "";
    img.loading = "lazy";
    // 走査した後にfileが消えることはある。壊れた枠を出したまま黙らない。
    // 「未取得」(cacheが無い)とは別の印にする — こちらはserverが在ると言った素材が
    // 引けなかった状態で、選択もDownloadも閉じない(次に押せば通ることがある)。
    img.addEventListener("error", () => {
      img.remove();
      tile.classList.add("as-broken");
      thumb.textContent = "表示できません";
    });
    thumb.appendChild(img);
  } else {
    thumb.textContent = "未取得";
  }

  const name = document.createElement("div");
  name.className = "as-name";
  name.textContent = item.name || String(item.id);
  name.title = item.name ? `${item.name}（${item.id}）` : String(item.id);

  const meta = document.createElement("div");
  meta.className = "as-meta";
  const sub = document.createElement("span");
  sub.className = "as-sub";
  sub.textContent = item.sub || "";
  const size = document.createElement("span");
  size.className = "as-size";
  size.textContent = cached ? fmtBytes(item.bytes) : "未取得";
  meta.append(sub, size);
  if (item.mtime) meta.title = fmtDateTime(item.mtime);

  tile.append(pick, thumb, name, meta);

  // 集計値は名前・容量の下へ縦に積む。名前とmetaを横に割ると、labelも数字も削られて
  // どちらも読めなくなる(1タイルの下限は9rem)。
  const stats = assetTileStats(item);
  if (stats.length) {
    const box = document.createElement("div");
    box.className = "as-stats";
    stats.forEach((stat) => box.appendChild(assetStatRow(stat, sortKey)));
    tile.appendChild(box);
  }

  if (cached) {
    const dl = document.createElement("a");
    dl.className = "as-dl btn btn-small";
    dl.href = fileUrl(item, true);
    dl.textContent = "保存";
    dl.title = "この素材だけをDownloadします。";
    tile.appendChild(dl);
    // タイルのどこを押しても選択が動く。Downloadのlinkだけはlinkの仕事に任せる。
    tile.addEventListener("click", (event) => {
      if (event.target === pick || event.target.closest("a")) return;
      pick.checked = !pick.checked;
      togglePick(tile, item, pick.checked);
    });
  }
  return tile;
}

function togglePick(tile, item, on) {
  if (on) assetSelected.add(item.id);
  else assetSelected.delete(item.id);
  tile.classList.toggle("is-picked", on);
  renderSelection();
}

function renderGrid() {
  const grid = document.getElementById("as-grid");
  // 「さらに読み込む」は既に読んだぶんも組み直す。位置を戻さないと、続きを読むたびに
  // 一覧の先頭へ跳ね、読んでいた場所を人が探し直すことになる。
  const top = grid.scrollTop;
  // 今どの数字で並んでいるか。並び順の識別子とstatsのkeyは同じ物なので、タイル側は
  // 対応表を持たずにその項目だけを強調できる。
  const sort = assetSort();
  const sortKey = sort ? sort.sort : "";
  const fragment = document.createDocumentFragment();
  assetItems.forEach((item) => {
    const tile = assetTile(item, sortKey);
    if (assetSelected.has(item.id)) tile.classList.add("is-picked");
    fragment.appendChild(tile);
  });
  grid.replaceChildren(fragment);
  grid.scrollTop = top;
}

function renderPlaceholder() {
  const empty = document.getElementById("as-empty");
  if (assetListState === "failed") {
    setListState(empty, "failed", assetListError);
    return;
  }
  if (assetListState === "loading" && !assetItems.length) {
    setListState(empty, "loading");
    return;
  }
  if (!assetItems.length && assetNeedsRescan()) {
    // 0件の理由が「この配信者は使っていない」ではなく「まだ集計していない」場合。
    // 同じ「素材はありません。」で出すと、集計すれば出てくる物を無いことにする。
    const label = (assetKindInfo(currentKind) || {}).label || "この種別";
    setListMessage(empty,
      `${label}はまだ集計していません（0件という意味ではありません）。`
      + "「この種別を再集計」を押すと、配信者ごとの絞込と集計順が使えるようになります。");
    return;
  }
  setListState(empty, assetItems.length ? "ok" : "empty");
}

// 集計が要る操作(配信者の絞込・集計順)をしているのに、その種別がまだ集計されていないか。
// serverのaggregatedが唯一の出所で、画面は種別ごとの事情を持たない。集計の要否は
// 「並び順の識別子がstatsのkeyでもあるか」で決まる ―― 同じ語で対応しているので、
// serverが新しい集計を足しても画面はそのまま追従する。
function assetNeedsRescan() {
  const info = assetKindInfo(currentKind);
  if (!info || info.aggregated !== false) return false;
  if (assetStreamerFilter()) return true;
  const order = assetSort();
  return Boolean(order && ASSET_STAT_SORTS.has(order.sort));
}

// 選択の件数はbuttonが名乗る。検索語を変えても選択は残るので、どこにも出さないと
// 「いつの間にか入っていた素材」がZIPに混ざる。
function renderSelection() {
  const zip = document.getElementById("as-zip-selected");
  const clear = document.getElementById("as-clear");
  const count = assetSelected.size;
  zip.textContent = count ? `選択をZIP（${fmtNum(count)}件）` : "選択をZIP";
  zip.disabled = count === 0;
  clear.disabled = count === 0;
}

function render() {
  const info = assetKindInfo(currentKind);
  document.getElementById("as-title").textContent = (info && info.label) || "素材";
  renderGrid();
  renderPlaceholder();
  renderSelection();

  // 件数・容量は集計時点の値で、行の「未取得」は今の事実。混ぜて読まれないよう、
  // 件数の側にだけ必ず時点を添える(時点の無い数字は今の数だと読まれる)。
  const summary = document.getElementById("as-summary");
  if (info) {
    const parts = [`${info.label || info.kind}: ${assetCountText(info)}`];
    if (info.scanned_at) {
      parts.push(`集計時点 ${fmtDateTimeShort(info.scanned_at)}（${assetElapsedText(info.scanned_at)}）`);
    }
    // 一覧に出る数と、集計の数が食い違って見える種別がある。黙ると、ZIPの件数が一覧より
    // 多い理由も、2つの数字が違う理由も画面から読めない。
    const hidden = assetHiddenCount(info);
    if (hidden) {
      parts.push(`一覧に出せる ${fmtNum(info.listable)}件`
        + `（差の ${fmtNum(hidden)}件は名前を辿れず一覧に出ませんが、全件ZIPには入ります）`);
    }
    if (assetListState === "ok") {
      parts.push(`一致 ${fmtNum(assetTotal)}件のうち ${fmtNum(assetItems.length)}件を表示`);
    }
    summary.textContent = parts.join(" / ");
  } else {
    summary.textContent = "";
  }

  // 語なしで開いた大きな種別の案内。一覧の上に出す — 下へ置くと、先頭ぶんをscrollし
  // 切った人にしか届かない。件数の根拠は一覧応答のtotalで、集計(count)ではない
  // (countは未集計だとnullで、その種別だけ数を言えなくなる)。
  const headOnly = assetHeadOnly && assetListState === "ok";
  document.getElementById("as-note").textContent = headOnly
    ? `${fmtNum(assetTotal)}件あります。先頭 ${fmtNum(assetItems.length)}件だけを出しています。`
      + "目的の素材は名前かIDで絞り込んでください。"
    : "";

  // 続きの読み込み。語なしの大きな種別では出さない ―― 19万件を100件ずつ押し進める
  // 使い方は無いので、押せるようにしておくと「押し続ければ辿り着ける」と誤らせる。
  // 絞り込めば(語が入れば)この頭打ちは外れる。
  const more = document.getElementById("as-more");
  const rest = assetTotal - assetItems.length;
  const canMore = assetListState === "ok" && rest > 0 && !assetHeadOnly;
  more.classList.toggle("hidden", !canMore);
  document.getElementById("as-more-note").textContent = canMore ? `残り ${fmtNum(rest)}件` : "";

  document.getElementById("as-select-all").disabled = !assetItems.length;
  document.getElementById("as-rescan").disabled = !info;
  // 未集計の種別でも押せる。何件入るかを数えるのは発券するserverの仕事で、
  // 画面の古い集計値で押せる/押せないを決めると、数えていない棚を触れなくしてしまう。
  document.getElementById("as-zip-all").disabled = !info;
}

// ---- Download ----------------------------------------------------------------

// 受け取りは隠しiframeへ流す。fetchしてblobにすると、全件538MBをbrowserのmemoryへ
// 抱えることになる。location.hrefだと、券が切れていた場合の404 JSONへ画面ごと飛ぶ。
// file名はserverのContent-Dispositionが決める(画面が名前を付けると命名が2箇所に割れる)。
function startDownload(url) {
  const frame = document.getElementById("as-dl-frame");
  // 同じURLを入れ直しても読み直さないbrowserがある(2回目の受け取りが黙って何も起きない)。
  frame.removeAttribute("src");
  frame.src = url;
}

// ---- 起動 --------------------------------------------------------------------

// 集計結果はDBのsnapshotで、この応答はdiskを走査しない。走査(再集計)は下の明示操作だけが
// 起こす — 22万件の全走査は開くたびに払える費用ではない(容量内訳の再scanと同じ考え)。
function applySummary(body) {
  assetSummary = body;
  assetKinds = body.kinds || [];
}

// 一覧requestの副作用で埋まったsnapshotを読み直す。失敗しても一覧は既に出ているので、
// 棚の数字が古いままになるだけ — ここで取得失敗を名乗ると、出ている一覧と食い違う。
async function refreshSummary() {
  try {
    applySummary(await apiSend("GET", "/api/assets/summary"));
  } catch (err) {
    console.warn("素材の集計を読み直せませんでした", err);
    return;
  }
  // 選べる配信者・受ける絞込もこの応答が出所なので、読み直したら組み直す。
  syncStreamerControls();
  renderKinds();
  render();
}

async function loadSummary() {
  try {
    applySummary(await apiSend("GET", "/api/assets/summary"));
  } catch (err) {
    assetSummary = null;
    assetKinds = [];
    assetListState = "failed";
    assetListError = err;
    renderKinds();
    render();
    showError(err, "素材の種別一覧");
    return;
  }
  // 保存してある種別が消えていることはある(poolを整理した後など)。serverが並べた先頭へ落とす。
  const stored = prefGet(ASSET_KIND_PREF) || "";
  const next = assetKindInfo(stored) ? stored : (assetKinds[0] ? assetKinds[0].kind : "");
  currentKind = "";
  renderKinds();
  if (next) selectKind(next);
  else render();
}

document.getElementById("as-q").addEventListener("input", () => {
  clearTimeout(assetSearchTimer);
  assetSearchTimer = setTimeout(() => loadItems(true), ASSET_SEARCH_DEBOUNCE_MS);
});

// 配信者の絞込・並び順・向き・表示件数はserverの絞り込みが変わるので取り直す。
// 配信者を変えても選択(assetSelected)は捨てない ―― 検索語と同じで、絞り込みを変えながら
// 拾い集めるのがこの画面の使い方。件数は常にtoolbarのbuttonが名乗る。
bindPref(document.getElementById("as-streamer"), ASSET_STREAMER_PREF, () => loadItems(true));
bindPref(document.getElementById("as-sort"), ASSET_SORT_PREF, () => loadItems(true));
bindPref(document.getElementById("as-order"), ASSET_ORDER_PREF, () => loadItems(true));
bindPref(document.getElementById("as-limit"), ASSET_LIMIT_PREF, () => loadItems(true));

document.getElementById("as-more").addEventListener("click", () => loadItems(false));

document.getElementById("as-select-all").addEventListener("click", () => {
  // 選べるのは手元にcacheが在る素材だけ。未取得の行を混ぜるとZIPが黙って欠ける。
  assetItems.forEach((item) => {
    if (item.cached !== false) assetSelected.add(item.id);
  });
  render();
});

document.getElementById("as-clear").addEventListener("click", () => {
  assetSelected.clear();
  render();
});

// ZIPは発券(POST)→確認→受け取り(GET)の3手。確認に出す件数と容量は券が名乗った実数で、
// 画面が数えた値ではない — 検索語を変えると手元の行は入れ替わるので、画面には数えられない。
// idsを渡さなければその種別の全件。
async function runArchive(ids, title, note) {
  const busy = document.getElementById("as-busy");
  document.getElementById("as-zip-selected").disabled = true;
  document.getElementById("as-zip-all").disabled = true;
  setFormMessage(busy, "ZIPに入れる素材を数えています…");
  let ticket = null;
  try {
    const body = { kind: currentKind };
    if (ids && ids.length) body.ids = ids;
    ticket = await apiSend("POST", ASSET_TICKET_PATH, body);
  } catch (err) {
    // 件数の上限を超えた等の断りもここへ来る。理由はserverの文言をそのまま出す
    // (上限は画面が持っていないので、画面から言えることが無い)。
    showError(err, title);
  }
  setFormMessage(busy, "");
  // 押せる/押せないは選択と種別が決める。ここで戻さないと、失敗した後に押せなくなる。
  render();
  if (!ticket) return;
  if (!ticket.count) {
    showToast("ZIPに入れられる素材がありませんでした。", "error", { title });
    return;
  }
  const lines = [`${fmtNum(ticket.count)}件 / ${fmtBytes(ticket.bytes)} をZIPにします。`];
  if (note) lines.push(note);
  lines.push("作成には時間がかかり、終わるまでbrowserの保存は始まりません。");
  const ok = await confirmDialog(lines.join(""), { title, confirmLabel: "ZIPを作る" });
  if (!ok) return;
  // 券には期限がある。切れた券を引くと404が返るが、受け取りは隠しiframeの中で起きるので
  // 画面には何も出ない。押した時点で切れているなら、ここで名乗って止める。
  if (ticket.expires_at && Number(ticket.expires_at) * 1000 <= Date.now()) {
    showToast("ZIPの有効期限が切れました。もう一度押して作り直してください。", "error", { title });
    return;
  }
  startDownload(ticketUrl(ticket.ticket));
  showToast([
    `${fmtNum(ticket.count)}件 / ${fmtBytes(ticket.bytes)} のZIPをserverが作っています。`,
    "作り終わるとbrowserの保存が始まります。それまでこの画面で待つ必要はありません。",
  ], null, { title });
}

document.getElementById("as-zip-selected").addEventListener("click", () => {
  if (!assetSelected.size) return;
  runArchive([...assetSelected], "選択のZIP");
});

document.getElementById("as-zip-all").addEventListener("click", () => {
  const info = assetKindInfo(currentKind);
  if (!info) return;
  // 発券は種別とidsしか受けない。絞り込んだ状態だと「今見えている物のZIP」と読めるので、
  // その読み違いをここで断つ。効いている絞込だけを名指しする — 使っていない絞込まで
  // 並べると、何が反映されないのかがぼやける。
  const narrowed = [];
  if (assetQuery()) narrowed.push("検索");
  if (assetStreamerFilter()) narrowed.push("配信者");
  runArchive(null, `${info.label || info.kind} を全件ZIP`,
    narrowed.length ? `${narrowed.join("・")}での絞込は反映されません。種別の全件が対象です。` : "");
});

// 再集計はこのbuttonだけが起こす。走るのは選んでいる種別のぶんだけで、他の種別の
// 集計値には触らない(押した種別以外まで数え直すと、待ち時間の理由が読めなくなる)。
document.getElementById("as-rescan").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const busy = document.getElementById("as-busy");
  const kind = currentKind;
  const info = assetKindInfo(kind);
  if (!info) return;
  button.disabled = true;
  setFormMessage(busy, `${info.label || kind}を集計しています…（件数の多い種別は十数秒かかります）`);
  try {
    applySummary(await apiSend("POST", "/api/assets/rescan", { kind }));
    setFormMessage(busy, "");
    renderKinds();
    // 結末は必ず名乗る。件数が変わらなかったときに何も出ないと、押せていないのか
    // 変化が無かったのかが読めない。
    const now = assetKindInfo(kind);
    const cost = now ? assetScanCostText(now.duration_ms) : "";
    showToast(now
      ? `${now.label || kind}: ${assetCountText(now)}${cost ? `（${cost}）` : ""}`
      : "集計しました。", null, { title: "素材の再集計" });
    // 未集計だった種別は、ここで初めて一覧を出せるようになる。
    loadItems(true);
  } catch (err) {
    setFormMessage(busy, err.message, true);
    showError(err, "素材の再集計");
    render();
  } finally {
    button.disabled = false;
  }
});

setListState(document.getElementById("as-empty"), "loading");
renderSelection();
loadSummary();
// この画面はWSのeventを使わないが、topbarの接続表示とJob badgeはconnectWSが面倒を見る。
// 繋がないと「Server接続中…」のまま固まり、落ちているように見える。
connectWS(() => {});
