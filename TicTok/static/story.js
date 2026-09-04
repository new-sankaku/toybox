// ストーリー: TikTok本体が出すハイライト(LIVE replayの切り抜き)を、こちらの録画へ音声指紋で
// 突き合わせ、gift名とgifter(誰が投げたか)を割り出して1本の動画へ繋ぐまでの画面。
// 経路の根拠と実測は doc/HIGHLIGHT_MATCH.md にある。
//
// この画面が扱う単位は「ハイライト 1本 = segment(gift演出)の列」である。ハイライトはmontageで、
// 平均6秒のgift演出が10個ほど、複数の録画から繋がれている。gift演出のすべてがgift地点ではない
// (実測で10個中3個はgift無し)ので、gift無しのgift演出も「giftではなかった」という結果として
// 扱う ―― 取得に失敗したものと同じ見え方にしてはいけない。
//
// **面は3つだけである。** 以前は「照合結果」という1本の中だけを読む面が別に在り、検証の
// 行をclickすると毎回そちらへ飛ばされていた。1件確かめるたびに面が入れ替わるので、
// 数百件を続けて見ることができない ―― 確かめる場所(動画)は一覧と同じ面の左へ置く。

const $ = (id) => document.getElementById(id);

// 「queueへ載った」を告げるtoastの表示時間。受け取った合図なので短くてよい
// (完了のtoastはWSのjob_updateが既定の長さで別に出す)。
const JOB_TOAST_MS = 3000;
// 窓幅が変わると時間軸は描き直しになる。resizeはdragの間ずっと届くので、手が止まってから
// 1回だけ描き直す。
const RESIZE_DEBOUNCE_MS = 120;
// 時間軸(seek bar)の寸法・handleの掴み幅・再生位置・目盛り・gift iconの並べ方は
// static/timeline.js が持つ。**配信者動画の seek bar と同じ物を同じ見た目・同じ操作で
// 出すため**で、この画面が足すのは「地に敷く物が波形ではなくgift演出であること」と
// 「下端のlaneに置くのが見どころではなく演出区間であること」だけである。
// 区間だけを再生するときの、終端の見張りの余裕(秒)。timeupdateは4回/秒ほどしか来ないので、
// ぴったりで止めようとすると毎回少し行き過ぎる。
const PLAY_STOP_SLACK = 0.05;

// 区間の最短。**Server(``highlight_export.MIN_CUT_SECONDS``)と同じ床**で、これより短い窓は
// 切っても中身が無い。ここで止めるのは往復を1回省くためで、判断そのものはServerも持つ。
const MIN_CUT_SECONDS = 0.25;
// gift演出の端との比較に使う遊び。0.001秒に丸めた値を送るので、厳密に比べると自分が出した
// 値で弾かれる。
const CUT_EPSILON = 0.001;
// キーで区間を動かす刻み。0.25秒は「演出の立ち上がりを1つ跨ぐ」程度の幅で、実測のgift演出
// (5〜6秒)を20手ほどで端から端まで動かせる。Shiftはその4倍。
const NUDGE_SECONDS = 0.25;
const NUDGE_BIG_SECONDS = 1.0;
// 刻みを溜めてから送るまでの間。**打鍵ごとに投げない** —— 0.25秒ずつ20回叩けば20往復に
// なり、途中の値が全部DBを通って、結末の名乗りも20枚積み上がる。手が止まるのを待つ長さで、
// これより長くすると「保存されたのか」が分からない間が生まれる。
const CUT_SEND_DELAY_MS = 400;
// hover中のサムネイルを頼む秒の刻み。frameはServerが1枚ずつ切ってcacheへ残すので、
// 連続した秒をそのまま頼むと同じ場面のためにffmpegが何十回も起きる。0.5秒に丸めれば
// 60秒のハイライトでも120枚で頭打ちになり、2度目からはcacheが返す。
const THUMB_STEP_SECONDS = 0.5;
// サムネイルの横幅(px)。配信者動画のspriteのtileと同じ幅にする(縦は絵の実比率で決まる)。
const THUMB_WIDTH_PX = 120;
// 軸の**下**へ敷くコマの帯の高さ(px)。地へ敷いていた頃は、その上に載るgiftのiconと名前が
// 絵に紛れて読めなかった(利用者の指摘) —— 絵と名前は別々の場所へ置く。この帯のぶんだけ
// canvasを厚くするので、本体(gift演出・icon・名前)の高さは敷いても減らない。
// 縦動画のtileは80x142なので、この高さで1枚が25px前後の幅を占める。
const STRIP_LANE_PX = 46;
// hoverが止まってからサムネイルを頼むまでの間(ms)。barの上を素通りしただけで
// 通り道の秒を全部頼まないようにする。
const THUMB_DELAY_MS = 90;

// これ未満の遅れは「切り替わり演出なし」として扱う。30fpsの1 frameが0.033秒なので、
// これより小さい差は画面にも出力にも現れない。
const SWITCH_MIN_SECONDS = 0.05;

// 通し再生で繋ぎ目の前後をどれだけ流すか(秒)。前の場面が頭に残っていないかを見るのが
// 目的なので、短くてよい ―― 長くすると「繋ぎ目だけ」が通し再生とほぼ同じ長さになる。
const JOIN_LEAD_SECONDS = 1.5;
const JOIN_TAIL_SECONDS = 1.5;

// 次の窓へ移るときの待ち(ms)。0にすると、seekの完了前にtimeupdateが前の窓の値で
// 走って二重に送ってしまう。
const SEQUENCE_STEP_MS = 60;

// seekの着地を「送った先へ着いた」と認める幅(秒)。要求した秒ちょうどには着かない(frameの
// 頭へ丸められる)。**人がシークバーを掴んだのか、こちらが送ったのかの見分けにも使う**ので、
// 大きくすると人の小さな操作を自分の送りと取り違える。
const RUN_SEEK_SLACK = 0.25;

const round3 = (value) => Math.round(Number(value) * 1000) / 1000;

const VIEWS = ["list", "cover", "export"];

// 状態の日本語。ここに無い状態はserverが返した文字列をそのまま出す ―― server側が状態を
// 足したときに、その行だけどの絞り込みにも出てこない、という消え方をさせない。
const HL_STATUS_LABELS = {
  new: "未照合",
  pending: "順番待ち",
  queued: "順番待ち",
  running: "照合中",
  matching: "照合中",
  matched: "照合済",
  done: "照合済",
  failed: "失敗",
  error: "失敗",
  missing: "fileが無い",
};

// 実体が置き場から消えた行の状態(store.highlights.HIGHLIGHT_STATUS_MISSING)。**この1つ
// だけは画面も名前で知っている必要がある** ―― 再生できない理由の名乗りと、溜まった行の
// 片付けが、この状態を指して初めて成り立つ。他の状態は文字列のまま素通しでよい。
const HL_STATUS_MISSING = "missing";

// 照合の合否(highlight_segments.confidence)。"high" は票・比・相関の3条件を**全部**
// 満たしたときだけで、"low" は1つでも届かなかったgift演出、"none" は票が立たなかった区間で
// ある(doc/HIGHLIGHT_MATCH.md)。**画面に出すのは点(score)の方**で、この文字列は
// 「線に届いたか」の判定にだけ使う ―― 表に語と数を両方並べると、どちらを読んで判断
// すればよいのかが読めない。
const CONFIDENCE_NONE = "none";

// 出力に載せてよいと言い切れるgift演出の線。**これ以外は名乗る。** 実際に、鹿の全画面演出
// (Guardian's Pledge / 4999🪙 / よい🐢💤 ｻｲｺｳｯ!)が「Goal Highlight」として別人
// (あきと🐢💤)のfileへ入り、出来上がったmp4を観るまで誰も気付けなかった。
const CONFIDENCE_OK = "high";

// 点の目盛りの名乗り(Serverが名乗らないときだけの控え)。**線の値は画面が決めない** ――
// 合否の線は Server の highlight_match.SCORE_PASS で、payloadの ``score_pass`` が運ぶ。
const SCORE_WEAKEST_LABELS = { votes: "票", ratio: "比", corr: "相関" };

const PREF = {
  view: "story.view",
  streamer: "story.streamer",
  status: "story.status",
  // 畳んであるfolderの source_dir(改行区切り)。folderは利用者が作る物なので、選択肢を
  // 画面が先に持てない —— 開閉の記憶も「今は閉じている物の名前」で持つ。
  folds: "story.folders",
  opts: "story.opts",
  exOpts: "story.export-opts",
  days: "story.match-days",
  scope: "story.match-scope",
  giftLead: "story.match-gift-lead",
  giftTail: "story.match-gift-tail",
  minDiamonds: "story.match-min-diamonds",
  window: "story.match-window",
  hop: "story.match-hop",
  showStrip: "story.show-strip",
  exOrder: "story.export-order",
  cvFilter: "story.cover-filter",
  cvOrder: "story.cover-order",
  cvMin: "story.cover-min",
  cvAutoplay: "story.cover-autoplay",
  cvStats: "story.cover-stats",
  exPadLead: "story.export-pad-lead",
  exPadTail: "story.export-pad-tail",
  // 再生速度は検証tabと出力tabで**同じ1つの設定**である。同じ画面の同じ「観る」操作
  // なので、tabを移るたびに選び直させない。
  playRate: "story.play-rate",
  // 直前に観たハイライトの縦横比。**観る場所の幅は開いた瞬間から要る** —— 列の幅はその
  // 動画の実幅に合わせてあるので(fitStageWidth)、比率が判るまで既定の割合で場所を空けて
  // おくと、1本目を載せた瞬間に列の幅ごと表が動く(利用者の指摘「再生したらガタガタ揺れる」)。
  // 前に観た1本の実測を**次に開いた時の**初期値として使い、面を開いている間は動かさない。
  stageRatio: "story.stage-ratio",
};

const state = {
  // 一覧は絞り込む前の全件を持つ。左paneの棚(配信者)の件数は全件から数えないと、
  // 1人を選んだ瞬間に他の配信者が棚から消えて選び直せなくなる。
  highlights: [],
  // Serverが名乗る既定値(GET /api/highlights の defaults)。**照合側と出力側に分かれて
  // 返る**(どちらにも min_diamonds が在り、意味が違うため)。画面はこれを**初期表示にだけ**
  // 使い、bodyへは入れない ―― 書き写すと、設定を変えても画面から起動した分だけ古い値で
  // 走る。空欄のまま送れば、実際に効くのは常にServer側の値である。
  defaults: null,
  // 配信者ごとの投入先(GET /api/highlights の upload_dirs)。dropの受け皿が「どこへ入るか」
  // を落とす前に名乗るために持つ。**画面ではpathを組み立てない** ―― 置き場の決まりが
  // 変わった日に、画面だけが実在しない場所を名乗ることになる。
  uploadDirs: {},
  // 置き場と、その下のsubfolder(GET /api/highlights の folders)。**1本も入っていない
  // folderもここへ来る**(Serverは置き場に在る物をそのまま名乗る)が、棚として出すのは
  // 中身か子孫の在る物だけである —— 素材の入っていない仕分け先まで並べると、実際に観る
  // 行がそのぶん下へ押し出される。入れ子(親子)は place と name から組む(folderTree)ので、
  // 画面はpathを切らない。綴りは行の source_dir と同じ物をServerが名乗るので、画面は
  // pathを組み立てずに行と突き合わせられる。
  folders: [],
  // 受け取れる拡張子(GET /api/highlights の extensions)。folderごとdropされた中身を
  // 絞るために持つ ―― 画面が綴りを持つと、Serverが受ける拡張子と2箇所に分かれる。
  uploadExtensions: [],
  // 作れる週のfolderの候補(GET /api/highlights の week_folders)。名前も週の境目も
  // Serverが決める ―― 画面で日付を組み立てると、対象の週(検証・出力tab)と1日ずれた
  // 名前のfolderが静かに増える。
  weekFolders: [],
  // 畳んであるfolderの source_dir。**畳むのは見た目だけ**で、絞り込み(配信者・状態)とは
  // 別物である ―― 畳んだ行も選択にも件数にも入ったままにする。
  folded: new Set(),
  streamer: "",
  picked: new Set(),
  // 一覧tabの左paneで今観ているハイライトのid。同じ行をもう一度clickしたときにsrcを
  // 差し替えないために持つ ―― 差し替えると読み込みからやり直しになる。
  listPlayId: null,
  // 一覧tabで**押した**行のid。出せない行(fileが無い・URLが無い)でも印は付けるので、
  // 「今観ている本」(listPlayId)とは別に持つ。
  listMarkId: null,
  // 左の動画エリアが開いているハイライト。{highlight, segments}。
  current: null,
  currentId: null,
  // 軸の下へ敷くコマ(filmstrip)。specはServerが名乗るsprite sheetの仕様で、imageはその
  // 1枚。**画面はtileの番号からしか秒を知らない**ので、2つは必ず対で入れ替える。
  strip: null,
  stripImage: null,
  currentSegId: null,
  // 手直しの相手のgift(`gifts[].id`)。**gift演出ではなくgiftが単位**である ―― gift演出1つが
  // 複数のgiftを持つので、gift演出だけを指しても直す相手が決まらない。
  currentGiftId: null,
  // 軸をdragしている間の仮の値 {bar, mode, start, end, segId, ...}。確定(PATCH)まではこちらを
  // 描く。
  barDrag: null,
  // 直前の区間の変更(1手だけ)。**Serverには機械が出した窓へ戻る道が無い** ―― 端を動かした
  // 時点で上書きされるので、取り消しは画面が持つしかない。履歴は積まない(どこまで戻ったかを
  // 画面が名乗れなくなる)。
  cutUndo: null,
  // まだ送っていない刻み。連打の間はここが本当の値で、画面もここを描く。
  cutPending: null,
  cutTimer: null,
  // 区間だけを再生している間の終端(秒)。null なら見張らない。
  playUntil: null,
  // 出力tabで選んだハイライトと、そこから組んだ並び。
  exPicked: new Set(),
  // Serverから引いた「出来上がるfileの一覧」。1件=1本のmp4で、画面はこれを描くだけ ――
  // 誰のfileを作るかも中身の並びもServerが決める。
  exFiles: [],
  // fileにならなかった人。黙って消さないために必ず持つ。
  exSkipped: [],
  // 週合計は下限を越えているのに、ハイライトに1件も出ていない人。**これも結果である** ――
  // 出さないと「1,000🪙投げた人のfileが無い」ことに誰も気付けない。
  exUncovered: [],
  // 置き場に実在する書き出し済みfile(GET /api/highlights/exports)。下見とは別物で、
  // 計画を組まなくても観られるようにするために持つ。
  exOutputs: [],
  exOutputSeq: 0,
  // 通し再生。``{name, chapters, ranges, mode, index}``。**繋いだ物を順番どおり流す**ため
  // の状態で、null なら何も追いかけていない(video要素の見張りもそのとき素通りする)。
  run: null,
  // 章の帯に今出ている窓の列。帯を組み直さずに「いま何本目か」だけを塗り替えるために持つ。
  chapters: [],
  chapterName: "",
  // 対象の週。中身は配信者画面の「週のGifter」と同じ応答(weeks / prev_week / next_week /
  // start_label / end_label / post_min)で、画面は週の境界も閾値も組み立てない。
  exWeek: "",
  exWeekData: null,
  exWeekSeq: 0,
  // 週を引いた時点の配信者。切り替わったことを見分けるためだけに持つ。
  exWeekStreamer: "",
  // 素材を付け替えた時の週。素材は週から決まるので、これは診断のための控えである。
  exAutoWeek: null,
  // 下見を引いている最中か。開いただけで自動的に引くようにしたので、二重に走らせない。
  exPlanning: false,
  // 自動で下見を引いた条件。同じ条件で引き直さないための印(0件も結果である)。
  exPlanKey: null,
  // いま左で観ている1本のfile名と、その中の1件(gift eventのid)。表の行に印を付けるため
  // だけに持つ ―― 観ている物が表のどの行なのかが読めないと、次に確かめる行を選べない。
  exPlayFile: "",
  exPlayItem: null,
  // 検証(週×ハイライト)。giftの行はServerが突き合わせた結果で、画面は絞って並べるだけ。
  // 週の選択肢も境界もこの応答が持っている(weeks / prev_week / next_week / start_label /
  // end_label / post_min)ので、週を別の口から引かない ―― 2つの口から引くと、選んで
  // いる週と表の中身が別々に動く余地ができる。
  cvWeek: "",
  cvStreamer: "",
  cvData: null,
  cvSeq: 0,
  // 今表に並んでいる行(絞り込み・並べ替えの後)と、選んでいる位置。↑↓で送るために持つ。
  // 位置(cvAt)は並べ替えや絞り込みで別のgiftを指すので、**選んでいる物そのもの**は
  // giftのevent_id(cvKey)で覚える —— 位置だけで覚えると、並びを変えた瞬間に選択が
  // 無関係な行へ飛ぶ。
  cvRows: [],
  cvAt: -1,
  cvKey: null,
};

let resizeTimer = null;

// ===== 書式 =====

// 値の無い項目を0として扱わない。Number(null)もNumber("")も0になるので、素のNumber()では
// 「まだ決まっていない端」と「先頭(0秒)」が同じ0になり、画面がそれを区別できなくなる。
function num(value) {
  if (value === null || value === undefined || value === "") return null;
  const v = Number(value);
  return Number.isFinite(v) ? v : null;
}

// ハイライトの中の位置。1本は1分前後でgift演出は平均6秒なので、秒だけでは端を詰める作業に
// 足りない。分:秒.1 で出す。
function fmtPos(seconds) {
  const v = num(seconds);
  if (v === null) return "—";
  const clamped = Math.max(0, v);
  const m = Math.floor(clamped / 60);
  const s = clamped - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, "0")}`;
}

function fmtLen(seconds) {
  const v = num(seconds);
  if (v === null) return "—";
  return `${v.toFixed(1)}秒`;
}

function statusLabel(status) {
  if (!status) return "—";
  return HL_STATUS_LABELS[status] || status;
}

// giftの名乗り。iconだけでは何が飛んだかしか読めず、名前だけでは一覧の中で見分けにくい。
// giftを割り出せなかったgift演出は「—」で、これは失敗ではなく「gift地点ではなかった」結果。
//
// gift_image は**serverが解決済みのproxy URL**(出せないgiftでは空文字)。画面側で
// /api/gift-icon を組み立て直さない ―― 二重に包んだURLになるうえ、「出せない」という
// serverの判断を画面が覆して壊れた画像箱を置くことになる。
function giftNode(seg) {
  const wrap = document.createElement("span");
  wrap.className = "st-gift";
  if (!seg.gift_id && !seg.gift_name) {
    wrap.textContent = "—";
    return wrap;
  }
  // proxy経由(同一origin)のURLだけを<img>に入れる。TikTokのCDN URLをそのまま入れても
  // hotlinkで拒まれるだけで、拒まれるまでの間に画面が外へrequestを出すことになる。
  // 解決できていないgiftはiconを出さず名前だけにする(壊れた画像箱も置かない)。
  const icon = String(seg.gift_image || "");
  if (icon.startsWith("/")) {
    const img = document.createElement("img");
    img.src = icon;
    img.alt = "";
    img.loading = "lazy";
    // 取り込めなかったiconは画像だけ消し、名前は残す(壊れた画像箱を置かない)。
    img.addEventListener("error", () => img.remove());
    wrap.appendChild(img);
  }
  const name = document.createElement("span");
  name.className = "st-gift-name";
  name.textContent = seg.gift_name || `gift ${seg.gift_id}`;
  // 名前は表の幅しだいで省略される。全文はここで読ませる ―― 省略された字だけでは
  // 別のgiftと見分けられない("Guardian's…" と "Guardian…" は別物になり得る)。
  wrap.title = name.textContent;
  wrap.appendChild(name);
  return wrap;
}

function gifterNode(seg) {
  if (!seg.user_unique_id && !seg.user_nickname) {
    const dash = document.createElement("span");
    dash.textContent = "—";
    return dash;
  }
  // 表の中では表示名だけを出す。@idまで並べると1人ぶんが2段になり、表が横へ溢れて
  // 右端の列が画面の外へ出る。
  //
  // 名前は絵文字混じりで長さの上限が無い(実物に「🟡むらたろう🍑🏌️‍♂️🍔」のような名前が
  // 居る)。伸びるに任せるとこの列だけで表が横scrollになるので、字の大きさに追従する
  // 上限で省略し、全文はcellのtooltipで読ませる ―― 固定幅ではないので窓幅と字の大きさに
  // 追い付く。
  const cell = userCell(
    { unique_id: seg.user_unique_id, nickname: seg.user_nickname }, { hideId: true });
  cell.classList.add("st-gifter");
  cell.title = [seg.user_nickname, seg.user_unique_id && `@${seg.user_unique_id}`]
    .filter(Boolean).join(" ");
  return cell;
}

// gift演出に付いた印。折り返させると1行が3段まで伸びて、表の見える行数がその分減る。
// **印は短い語だけで、説明は付けない**(利用者の指定)。
function markNode(marks) {
  const span = document.createElement("span");
  span.className = "st-nowrap";
  span.textContent = marks.join("・") || "—";
  return span;
}

// ===== 場面の絵は置かない =====

// **代表frameの列は外した。** かつては出力の下見が束の行に2枚(ハイライト側と録画側)を
// 並べていた ―― 文字だけでは、鹿の全画面演出(Guardian's Pledge)が「Goal Highlight」の
// 名前で別人のfileへ入っていたことに気付けなかったためである。
//
// いま同じ役目を果たしているのは**行ごとの▶(素材から1件だけ再生)と「通し」**で、絵1枚
// より動いている物の方が確実に強い。加えて絵は行を高くするので、束を開いたときに一度に
// 読める件数がその分減る ―― 別人が混ざっていないかは gifter の列(束の持ち主と違えば
// 印が付く)を上から追うのが速い。

// ===== スコア =====

// 言い切れるgift演出か。値そのものが無い行は「判らない」であって「大丈夫」ではないので、
// ここでは通さない ―― 通すと、合否を記録していない古い結果が全部「確認不要」に見える。
function isSure(value) {
  return String(value || "") === CONFIDENCE_OK;
}

// 点の名乗り。**語ではなく数を出す**(利用者の指定) ―― 「高 / 低」の2択では、低い行が
// 10件並んだときにどれから観ればよいのかを語が答えられなかった。0〜100で、線ちょうどが
// 50。目盛りはServerの highlight_match.score_of が持つ。
//
// tooltipは**元になった3つの値だけ**で、読み方は書かない。色(.st-risk-text)が担うのは
// 「線に届いていない」の1点である。
function scoreNode(hit) {
  const span = document.createElement("span");
  span.className = "st-nowrap st-score";
  const value = num(hit && hit.score);
  if (value === null) {
    span.textContent = "—";
    return span;
  }
  span.textContent = fmtNum(value);
  if (!isSure(hit.confidence)) span.classList.add("st-risk-text");
  const votes = num(hit.votes);
  const ratio = num(hit.ratio);
  const corr = num(hit.corr);
  const parts = [
    votes === null ? "" : `${SCORE_WEAKEST_LABELS.votes} ${fmtNum(votes)}`,
    ratio === null ? "" : `${SCORE_WEAKEST_LABELS.ratio} ${ratio.toFixed(1)}`,
    corr === null ? "" : `${SCORE_WEAKEST_LABELS.corr} ${corr.toFixed(2)}`,
  ].filter(Boolean);
  if (parts.length) span.title = parts.join(" / ");
  return span;
}

// ===== 警告 =====

// その当たりの**警告**。印(marks)と分けてあるのは、印が「知っておくこと」なのに対し、
// こちらは「照合そのものが壊れている疑い」だからである ―― 混ぜると、普通に付く印に
// 紛れて見落とす。
//
// いまの条件は1つ。**投げた人が1人しか居ないのにgift演出が長い**行で、繋ぎを跨いで
// 2場面が1つになった疑いが濃い。実測(2026-09-04 / 86件)で長さは中央値5.91秒・95%点
// 8.22秒、10秒超えは3件だけ、そのうちgifterが1人の1件がまさにそれだった。gifterが
// 複数居る長い行は演出が続けて起きただけなので警告しない。**線(秒)はServerが名乗る。**
function hitWarnings(hit) {
  const line = num(state.cvData && state.cvData.long_segment_seconds);
  const start = num(hit && hit.segment_start);
  const end = num(hit && hit.segment_end);
  const gifters = num(hit && hit.segment_gifters);
  if (line === null || start === null || end === null) return [];
  if (end - start < line) return [];
  if (gifters !== null && gifters > 1) return [];
  return [`長い ${fmtLen(end - start)}`];
}

function warnNode(warnings) {
  const span = document.createElement("span");
  span.className = "st-nowrap";
  if (!warnings.length) {
    span.textContent = "—";
    return span;
  }
  span.textContent = warnings.join("・");
  span.classList.add("st-warn-text");
  return span;
}

function segLength(seg) {
  const s = num(seg.start);
  const e = num(seg.end);
  if (s === null || e === null) return null;
  return e - s;
}

// gift演出が1件でもgiftを持つか。**gift演出は複数のgiftを持ち得る**ので、単数の gift_event_id で
// 判断してはいけない ―― 1件だけを見る形に戻すと、実測で6000🪙が範囲外の10🪙に負けた
// 「窓の中の1件しか持たない」時代の誤りが同じ形で戻る。
function hasGift(seg) {
  return ((seg && seg.gifts) || []).length > 0;
}

// そのgift演出の🪙。**giftの合計を数える** —— gift演出の行にも同じ名前の欄は在るが、値が入って
// いない(実測で全gift演出がnull)。数を持っているのはgiftの方なので、そちらから足す。
function segmentDiamonds(seg) {
  return ((seg && seg.gifts) || []).reduce(
    (sum, gift) => sum + (Number(gift.diamonds) || 0), 0);
}

// ===== 畳んだpanel =====

// buttonで開け閉めするpanel。`<details>` を使わないのは、利用者が「buttonにして」と
// 言ったからで、開いた状態はbrowserごとに覚える(bindPrefと同じkeyの流儀)。
function bindPanel(buttonId, panelId, prefKey) {
  const button = $(buttonId);
  const panel = $(panelId);
  if (!button || !panel) return;
  const apply = (open) => {
    panel.classList.toggle("hidden", !open);
    button.setAttribute("aria-expanded", open ? "true" : "false");
    button.classList.toggle("btn-on", open);
  };
  apply(prefGet(prefKey) === "1");
  button.addEventListener("click", () => {
    const open = button.getAttribute("aria-expanded") !== "true";
    apply(open);
    prefSet(prefKey, open ? "1" : "0");
  });
}

// ===== view切替 =====

function showView(name) {
  prefSet(PREF.view, name);
  VIEWS.forEach((view) => {
    $(`view-${view}`).classList.toggle("hidden", view !== name);
    $(`tab-${view}`).classList.toggle("active", view === name);
  });
  // 画面に無いplayerは止める。鳴り続けると、どこから音が出ているのか分からなくなる。
  // 通し再生も一緒に止める ―― 止めないと、見張りが見えない画面で次の窓を始め続ける。
  if (name !== "export") stopRun();
  ["cv-video", "ex-video"].forEach((id) => {
    const video = $(id);
    if (video && !video.paused) video.pause();
  });
  // 時間軸は隠れている間の描画要求を全て捨てる(実寸が0になるため即returnする)。
  // 戻った時点で1回描き直す。
  if (name === "cover") {
    renderCoverPicks();
    drawTimeline();
  }
  if (name === "export") renderExportPicks();
}

// 空欄のときに実際に効く値を、薄字(placeholder)で名乗る。「なし」と読める表示にしない
// ―― 下限が効いているのに「なし」と見えると、利用者は下限なしで繋がれると読む。
//
// **Serverは既定を2つに分けて返す**(`defaults.match` と `defaults.export`)。両方に
// `min_diamonds` が在り、意味が違うためである(照合側は探す範囲、出力側は成果物の中身)。
// 以前ここが平らなdictを期待していたため、**どの欄も既定値を引けず「Server既定」の
// 文字が欄の幅で切れて「Serv」と出ていた** ―― 設定が壊れているように見えていたのは
// これで、値そのものはServer側で正しく効いていた。
const DEFAULT_FIELDS = [
  ["opt-gift-lead", "match", "gift_lead", ""],
  ["opt-gift-tail", "match", "gift_tail", ""],
  ["opt-min-diamonds", "match", "min_diamonds", "🪙"],
  ["opt-window", "match", "window", ""],
  ["opt-hop", "match", "hop", ""],
  ["ex-min", "export", "min_diamonds", "🪙"],
  ["ex-pad-lead", "export", "pad_lead", ""],
  ["ex-pad-tail", "export", "pad_tail", ""],
  // 検証の面の下限は**照合側と同じ出所**がServer側で効く(route が
  // highlight_match.defaults を読む)。空欄のときに実際に効く値をここでも名乗らないと、
  // この面だけ「何で絞った表なのか」が読めない。
  ["cv-min", "match", "min_diamonds", "🪙"],
];

// Serverが名乗った既定値を1つ引く。名乗っていなければ null(数字を作らない)。
function defaultOf(group, key) {
  const all = state.defaults;
  if (!all) return null;
  const box = all[group];
  return box ? num(box[key]) : null;
}

function renderDefaults() {
  DEFAULT_FIELDS.forEach(([id, group, key]) => {
    const el = $(id);
    if (!el) return;
    const value = defaultOf(group, key);
    // 欄は数値のために狭い。名乗る値が無いときは短い語で済ませる ―― 長い文字列を
    // placeholderに入れても、欄の幅で切れて意味の無いgift演出が出るだけである。
    //
    // **単位の絵文字は欄の中に入れない**(利用者の指摘)。placeholderは欄の中に薄字で出る
    // ので、初期表示では「入力欄の中に絵文字が入っている」ようにしか見えなかった。単位は
    // 欄の左のlabelが名乗っている。実際に効く既定値はこの薄字が唯一の名乗りで、
    // tooltipへ同じことを書き足さない(利用者の指定)。
    el.placeholder = value === null ? "既定" : fmtNum(value);
  });
  // **遡る日数だけは既定が1つに決まらない。** Serverは狭い順の段(既定 14→30日)を持って
  // いて、狭い窓で1本も当たらなければ広げてもう一度走る。段をそのまま薄字に出す ――
  // 単数の数字にすると「その窓しか見ない」と読めてしまう。
  const stages = (state.defaults && state.defaults.match
                  && state.defaults.match.day_stages) || [];
  const days = $("opt-days");
  days.placeholder = stages.length ? `${stages.map((d) => fmtNum(d)).join("→")}日` : "既定";
  // 候補の範囲(scope)も同じ扱い。「既定」としか書いていないと、どちらが効くのか読めない。
  const mode = state.defaults && state.defaults.match && state.defaults.match.scope;
  const button = $("opt-scope").querySelector('.seg-item[data-value=""]');
  if (button) {
    button.textContent = mode ? `既定（${SCOPE_MODE_LABELS[mode] || mode}）` : "既定";
  }
}

const SCOPE_MODE_LABELS = { gift: "gift地点", all: "録画全体" };

// ===== ハイライト一覧 =====

function visibleHighlights() {
  const status = $("hl-status").value;
  return state.highlights.filter((h) => {
    if (state.streamer && h.unique_id !== state.streamer) return false;
    if (status && h.status !== status) return false;
    return true;
  });
}

// 配信者の棚。件数は全件から数える(絞り込みの後で数えると、選んだ配信者だけが1件、
// 他が0件の棚になる)。
function renderStreamerShelf() {
  const container = $("hl-streamers");
  container.innerHTML = "";
  const counts = new Map();
  state.highlights.forEach((h) => {
    const key = h.unique_id || "";
    counts.set(key, (counts.get(key) || 0) + 1);
  });
  const names = [...counts.keys()].filter(Boolean).sort();
  // 選んでいた配信者が置き場から消えていたら「全て」へ戻す。指せない棚を選んだままに
  // すると、一覧が0件のまま理由が読めない。
  if (state.streamer && !counts.has(state.streamer)) state.streamer = "";

  const addPick = (value, label, meta) => {
    const item = document.createElement("div");
    item.className = "vd-group-item";
    const btn = document.createElement("button");
    btn.className = "vd-group-pick";
    btn.type = "button";
    btn.setAttribute("aria-pressed", state.streamer === value ? "true" : "false");
    const name = document.createElement("span");
    name.className = "vd-group-name";
    name.textContent = label;
    const sub = document.createElement("span");
    sub.className = "vd-group-meta";
    sub.textContent = meta;
    btn.append(name, sub);
    btn.addEventListener("click", () => {
      state.streamer = value;
      prefSet(PREF.streamer, value);
      renderStreamerShelf();
      // 作る先は配信者で決まる。棚を押した時に押せる・押せないが変わらないと、
      // 「配信者を選べ」と言われたまま何も変わらないbuttonが残る。
      renderWeekFolders();
      renderHighlights();
    });
    item.appendChild(btn);
    container.appendChild(item);
  };

  addPick("", "全て", `${fmtNum(state.highlights.length)}件`);
  if (names.length) {
    const sep = document.createElement("div");
    sep.className = "vd-group-sep";
    container.appendChild(sep);
  }
  names.forEach((name) => addPick(name, name, `${fmtNum(counts.get(name))}件`));
}

// 状態の選択肢はserverが返した値から組む。画面が状態名を先に決めると、server側が状態を
// 足したときにその行だけどの絞り込みにも出なくなる。
function renderStatusOptions() {
  const select = $("hl-status");
  // 保存値はここで拾う。bindPrefが張られる時点では選択肢がまだ1つも無く(状態はserverが
  // 返した値から組む)、restorePrefは「存在しない選択肢」として復元を諦めている。
  const want = select.value || prefGet(PREF.status) || "";
  const seen = [...new Set(state.highlights.map((h) => h.status).filter(Boolean))].sort();
  select.innerHTML = "";
  const all = document.createElement("option");
  all.value = "";
  all.textContent = "全て";
  select.appendChild(all);
  seen.forEach((status) => {
    const option = document.createElement("option");
    option.value = status;
    option.textContent = statusLabel(status);
    select.appendChild(option);
  });
  // 選んでいた状態が今の一覧に無ければ「全て」へ戻す。指せない値を選んだままにすると、
  // 一覧が0件のまま理由が読めない。
  select.value = seen.includes(want) ? want : "";
  if (select.value !== want) prefSet(PREF.status, select.value);
  return select.value !== "";
}

function renderPickedCount() {
  const count = state.picked.size;
  $("hl-selected").textContent = count ? fmtNum(count) : "";
  $("hl-match").disabled = count === 0;
  $("hl-delete").disabled = count === 0;
}

// 実体の無い行(状態=fileが無い)。**絞り込みを通さず全件から数える** ―― 溜まっている
// ことに気付いてもらうための数なので、今の絞り込みで見えているかどうかとは関係が無い。
function missingHighlights() {
  return state.highlights.filter((h) => h.status === HL_STATUS_MISSING);
}

// 片付けbuttonの名乗り。0件のときは出さない ―― 常設にすると、出ているのが普通の帯に
// なって目に入らなくなる(検証の面の要注意件数と同じ扱い)。
function renderPurgeButton() {
  const rows = missingHighlights();
  const button = $("hl-purge");
  button.classList.toggle("hidden", rows.length === 0);
  button.textContent = `✕ ${fmtNum(rows.length)}`;
}

// 一覧tabの左paneで観る。**この面は動かない。**
//
// 実体の無い行はServerが ``url`` を返さない(``_with_url``)。押しても404になる再生を
// 起こさず、**なぜ出せないのか**をここで名乗る —— 「file が無い行がここに在る」ことが
// 読めて初めて、片付けるという次の操作に繋がる。
function playInList(h) {
  const video = $("hl-video");
  if (!h) {
    state.listPlayId = null;
    state.listMarkId = null;
    video.pause();
    video.removeAttribute("src");
    video.load();
    // 何も載っていないときは何も名乗らない(利用者の指定)。使い方の案内を常設にすると、
    // **理由を出す場所**(実体の無い行・URLを返さない行)が案内文に埋もれる ―― ここへ
    // 文字が出ているのは「出せない理由が在るとき」だけ、という読み方に揃える。
    setFormMessage($("hl-play-status"), "", false);
    markListSelection();
    return;
  }
  // **押した行には必ず印を付ける**(検証・出力の面と同じ)。出せない行でも印は付ける ――
  // 「押したのに何も起きない」と「押した行がこれで、出せない理由はこれ」は別物である。
  state.listMarkId = h.id;
  if (!h.url) {
    state.listPlayId = null;
    video.pause();
    video.removeAttribute("src");
    video.load();
    setFormMessage($("hl-play-status"),
      h.status === HL_STATUS_MISSING ? "fileが無い" : "再生URLが無い", true);
    markListSelection();
    return;
  }
  setFormMessage($("hl-play-status"), "", false);
  markListSelection();
  // 同じ本を開き直さない。srcを差し替えると読み込みからやり直しになる。
  if (state.listPlayId === h.id) return;
  state.listPlayId = h.id;
  video.src = h.url;
}

// 観ている行の印。**表を組み直さずにclassだけ付け替える**(検証・出力の面と同じ) ――
// 一覧は数百行になるので、1本選ぶたびに作り直すと選択も畳んだ棚も失われる。
function markListSelection() {
  const tbody = $("hl-rows");
  if (!tbody) return;
  const at = state.listMarkId === null || state.listMarkId === undefined
    ? "" : String(state.listMarkId);
  [...tbody.rows].forEach((tr) => {
    tr.classList.toggle("st-current", Boolean(at) && tr.dataset.hlid === at);
  });
}

// その照合が**どの窓で走ったか**と、**1本も当たらなかったか**。Serverが結果へ残した
// ``scope`` をそのまま読むだけで、画面は判断を持たない。
//
// **これが無いと空振りの理由が読めない。** 候補の窓は「今」から遡って張られるので、窓より
// 古い配信のハイライトは当たらない ―― それを「照合済 / gift演出0件」としてしか出さないと、
// 「TikTokが選ばなかった」のか「候補の窓の外だった」のかを人が切り分けられない。実測でも
// 例外は出ず、gift演出1件・gift 0件・確からしさ"none"が黙って返るだけだった。
//
// 古い結果は ``matched_recordings`` を持たない(この項目より前に照合したもの)。**持って
// いないものを「当たり無し」と描かない** ―― 判らないことと、当たらなかったことは別である。
function matchNote(h) {
  const scope = h && h.scope;
  if (!scope) return null;
  const parts = [];
  const from = num(scope.window_start);
  const to = num(scope.window_end);
  if (from !== null && to !== null) {
    parts.push(`${fmtDateTimeShort(from)} 〜 ${fmtDateTimeShort(to)}`);
  }
  if (num(scope.pool) !== null) parts.push(`${fmtNum(scope.pool)}本`);
  const tried = Array.isArray(scope.days_tried) ? scope.days_tried : [];
  if (tried.length) parts.push(`${tried.map((d) => fmtNum(d)).join("→")}日`);
  const hits = Array.isArray(scope.matched_recordings) ? scope.matched_recordings : null;
  const empty = hits !== null && hits.length === 0;
  // tooltipは**走った窓の値だけ**にする(読み方の説明は置かない)。空振りは列の
  // 「当たり無し」が名乗る。
  const title = parts.join(" / ");
  return { empty, title, hits };
}

// ===== 置き場のfolderで畳む =====
//
// 置き場の下は利用者が作ったfolderで仕分けられている(週ごとの ``20260829-20260905`` など)。
// file名の平らな列で出すと、今どの週の素材を見ているのかが行からは読めない ―― 棚はfolderで、
// 行はその中身である。**folderの名乗りはServerが持つ**(行の source_dir と応答の folders)ので、
// 画面はpathを組み立てない。
//
// **棚は実際の入れ子のまま出す。** folderの深さに上限は無く(Serverは置き場の下を辿って
// 名乗る)、棚も行も同じ左端から始めると、どの棚の中身なのかが行の見た目からは読めない
// ―― 親子は place と name の区切りから決め、中身は親より1段深く寄せる。
//
// **空の棚も出す。** かつては中身も子孫も無い棚を落としていた(観る行が下へ押し出される
// ため)が、folderは**投入先**でもある —— 週のfolderを作る操作と、folderの行へ動画を落とす
// 操作を持った今、作った直後の空のfolderが一覧に出ないと、そこへ入れる手段が画面から消える。
// 空であることは見出しの「0本」が名乗る。
//
// **畳むのは見た目だけである。** 絞り込み(配信者・状態)は「何が対象か」を決めるが、畳んだ
// folderの行は対象のままにする —— 畳んだ拍子に選択が落ちると、選び直すために畳み直すことに
// なる(表示中を全選択も同じ理由で、畳んだ行を数に入れる)。下の棚も同じで、親を畳めば
// 隠れるだけ、対象からは落ちない。

function folderKey(h) {
  return h.source_dir || "";
}

// 棚の素。**Serverが名乗ったfolderと、行が名乗ったfolderの両方**から組む ――
// 前者だけだと、置き場から消えたfolderに居る行(実体の無い行は残す約束)が並ぶ場所を失う。
// 後者だけだと、中身が子孫にしか無い途中のfolderが名乗れず、入れ子が途切れる。
function folderGroups(rows) {
  const groups = new Map();
  const take = (key, seed) => {
    if (!groups.has(key)) {
      groups.set(key, { key, place: key, name: "", path: "", rows: [],
                        // 投入先としてServerへ渡すのはこの2つ(root_key と source_dir)
                        // だけである。**画面はpathを組み立てない** ―― 実pathは名乗りの
                        // ためだけに持ち、口へはServerが名乗った綴りをそのまま返す。
                        root_key: "", unique_id: "", ...seed });
    }
    return groups.get(key);
  };
  (state.folders || []).forEach((folder) => {
    // 棚も今の絞り込みに合わせる。配信者を選んでいるのに他人の置き場が並ぶと、0件の棚が
    // 縦を食うだけになる。
    if (state.streamer && folder.unique_id !== state.streamer) return;
    take(folder.source_dir || "", {
      place: folder.place || folder.source_dir || "",
      name: folder.name || "",
      path: folder.path || "",
      root_key: folder.root_key || "",
      unique_id: folder.unique_id || "",
    });
  });
  rows.forEach((h) => {
    const group = take(folderKey(h), {
      root_key: h.root_key || "", unique_id: h.unique_id || "" });
    group.rows.push(h);
  });
  return [...groups.values()];
}

// 並びは置き場が先、その下は新しい名前が先。週のfolderは日付で始まるので、一覧の並び
// (新しい順)と同じ向きになる。
function folderOrder(a, b) {
  return (a.group.place.localeCompare(b.group.place)
    || (a.group.name === "" ? -1
      : (b.group.name === "" ? 1 : b.group.name.localeCompare(a.group.name))));
}

// 棚を入れ子に組み直す。親は「同じ置き場の、1段浅い name」―― pathの文字を切って親を
// 当てるのではなく、Serverが名乗った place と name だけで決める(画面はpathを組み立てない)。
//
// node は { group, rows(直下の行), all(子孫まで含む行), children }。**空の node も残す**
// (投入先として押せる必要がある)。
function folderTree(groups) {
  const byName = new Map();
  const nodes = groups.map((group) => {
    const node = { group, rows: group.rows, all: [], children: [] };
    byName.set(`${group.place}\n${group.name || ""}`, node);
    return node;
  });
  const roots = [];
  nodes.forEach((node) => {
    const parts = node.group.name ? node.group.name.split("/") : [];
    let parent = null;
    // 一番近い先祖へ吊る。間の段が棚に無いことがある(実体の消えたfolderに居る行だけが
    // その名を名乗る場合)ので、見つかるまで1段ずつ上がる。
    for (let cut = parts.length - 1; cut >= 0 && !parent; cut -= 1) {
      const found = byName.get(`${node.group.place}\n${parts.slice(0, cut).join("/")}`);
      if (found && found !== node) parent = found;
    }
    if (parent) parent.children.push(node);
    else roots.push(node);
  });
  // 中身は下から数える。子孫の行は親の数にも入れる —— 畳んだ親が「0本」と名乗ると、
  // 中に何が在るのかを開くまで言えない。**数えるだけで、空でも落とさない。**
  const count = (node) => {
    node.children.forEach(count);
    node.children.sort(folderOrder);
    node.all = node.children.reduce((acc, child) => acc.concat(child.all), [...node.rows]);
  };
  roots.forEach(count);
  return roots.sort(folderOrder);
}

// 棚の中身の名乗り。数の言い方は帯の要約(#hl-summary)と揃える ―― 同じ物を2通りの言い方で
// 並べると、どちらを読めばよいのか判らなくなる。**子孫のぶんまで数える**(畳んだ親の
// 見出しが、中に在る物を名乗らないことにならないように)。
function folderSummary(node) {
  const rows = node.all;
  if (!rows.length) return "0";
  const gifts = rows.reduce((sum, h) => sum + (Number(h.gift_total_count) || 0), 0);
  const coins = rows.reduce((sum, h) => sum + (Number(h.gift_diamonds) || 0), 0);
  return `${fmtNum(rows.length)} · ${fmtNum(gifts)} · 🪙${fmtCompact(coins)}`;
}

function saveFolds() {
  prefSet(PREF.folds, JSON.stringify([...state.folded]));
}

// 前回畳んでいたfolderを引き継ぐ。棚は利用者が作る物なので、画面は選択肢を持てない
// —— 覚えるのは「今は閉じている物の名前」だけで、知らない名前は素通しになる。
function restoreFolds() {
  let keys = null;
  try {
    keys = JSON.parse(prefGet(PREF.folds) || "[]");
  } catch (err) {
    // 読めない保存値は棚の開閉の記憶に過ぎない。全部開いた状態から始める。
    keys = null;
  }
  if (Array.isArray(keys)) keys.forEach((key) => state.folded.add(key));
}

function folderRow(node, colspan, depth) {
  const group = node.group;
  const open = !state.folded.has(group.key);
  // 見出しは自分の段の名前だけにする。入れ子で出すので、親の名前まで繰り返すと、どこで
  // 段が変わったのかが読めなくなる。
  const label = group.name ? group.name.split("/").pop() : group.place;
  const tr = document.createElement("tr");
  tr.className = "st-folder";
  tr.dataset.fold = group.key;
  // dropの投入先。**この行へ落とせばこのfolderへ入る。** Serverが名乗った綴りをそのまま
  // 持ち回るだけで、画面はpathを組み立てない(実pathは名乗りにしか使わない)。
  tr.dataset.streamer = group.unique_id || "";
  tr.dataset.rootKey = group.root_key || "";
  tr.dataset.path = group.path || "";
  tr.dataset.folderLabel = label;
  // 段の深さは字下げにだけ渡す(cssが calc で寄せる)。段ごとにcellを足すと、表の列の
  // 意味が段によって変わってしまう。
  tr.style.setProperty("--st-depth", String(depth));
  // 選択の列は棚でも同じ意味にする。folder 1つを丸ごと照合・削除へ渡す操作が、行を
  // 1本ずつ押す以外に無かった(週のfolderには十数本入る)。
  //
  // **相手はその folder の直下の行だけである(子孫は含めない)。** 以前は子孫まで数えて
  // いたので、subfolderを1つ選んだだけで**上の棚まで印が付いた** —— 実測の置き場は
  // 直下に1本も持たず素材が全部 週のfolderの中に在るので、週を選ぶと置き場の棚が
  // そのまま「全選択」の見た目になっていた(利用者の指摘)。選んでいない物の印が付く
  // 以上、押した結果を画面から読めない。
  //
  // 表示と操作の相手を同じ物に揃えるのがここの要点で、片側だけ子孫にすると、押した
  // 直後に自分の印が外れるcheckboxができる(直下に行の無い棚)。丸ごと選びたい時は
  // 棚ごとに押す ―― 段は「置き場 → 週 → 仕分け先」の3段までで、見出し行の全選択
  // (#hl-select-all)が今見えている全部を1手で選ぶ道を別に持っている。
  const pickCell = document.createElement("td");
  if (node.rows.length) {
    const box = document.createElement("input");
    box.type = "checkbox";
    const picked = node.rows.filter((h) => state.picked.has(h.id)).length;
    box.checked = picked === node.rows.length;
    box.indeterminate = picked > 0 && picked < node.rows.length;
    box.setAttribute("aria-label", `${label} のfolderの行を全選択`);
    box.addEventListener("change", () => {
      node.rows.forEach((h) => {
        if (box.checked) state.picked.add(h.id);
        else state.picked.delete(h.id);
      });
      renderHighlights();
    });
    pickCell.appendChild(box);
  }
  const cell = document.createElement("td");
  cell.colSpan = colspan;
  // 見出しの中身はcellの中の箱へ入れる。**cell自身をflexにしない** —— tdにflexを当てると
  // 表のcellでなくなり、colspanが効かずに1列ぶんの幅へ縮む(見出しが2段に折れる)。
  const head = document.createElement("span");
  head.className = "st-folder-head";
  const toggle = document.createElement("button");
  toggle.className = "btn btn-small st-folder-toggle";
  toggle.type = "button";
  // 開閉の印は他の画面(job一覧の明細)と同じ▼/▶にする。
  toggle.textContent = `${open ? "▼" : "▶"} ${label}`;
  toggle.setAttribute("aria-expanded", open ? "true" : "false");
  // **実pathはServerが名乗った値をそのまま出す。** 画面で組み立てると、置き場の決まりが
  // 変わった日に画面だけが実在しない場所を名乗る。見出しは段の名前だけなので、
  // pathは省略された値の復元としてtooltipに残す。
  toggle.title = group.path || "";
  toggle.addEventListener("click", () => {
    if (open) state.folded.add(group.key);
    else state.folded.delete(group.key);
    saveFolds();
    renderHighlights();
  });
  head.appendChild(toggle);
  // どの置き場のfolderなのか。置き場は2通り×2rootあり、名前(日付)だけでは同じ名前の
  // folderを見分けられない ―― ただし入れ子の中では置き場は上の段が名乗っているので、
  // 繰り返さない。名前を持ったまま根に居る棚(親が絞り込みで消えた)だけが名乗る。
  if (group.name && depth === 0) {
    const place = document.createElement("span");
    place.className = "st-folder-place";
    place.textContent = group.place;
    head.appendChild(place);
  }
  const meta = document.createElement("span");
  meta.className = "vd-summary";
  meta.textContent = folderSummary(node);
  head.appendChild(meta);
  cell.appendChild(head);
  tr.append(pickCell, cell);
  return tr;
}

// 描き終わった行をfolderごとに畳み直す。**共通の描画(renderTableRows)は行だけを作る**ので、
// 棚の見出しはその後で差し込む —— 列の意味は1つの表に1組だけである。
function renderFolderRows(roots) {
  const tbody = $("hl-rows");
  const head = $("hl-table").tHead;
  const colspan = head ? head.rows[0].cells.length - 1 : 1;
  const byKey = new Map();
  Array.from(tbody.rows).forEach((tr) => {
    const key = tr.dataset.folder || "";
    if (!byKey.has(key)) byKey.set(key, []);
    byKey.get(key).push(tr);
  });
  const fragment = document.createDocumentFragment();
  const walk = (node, depth, hiddenAbove) => {
    const shelf = folderRow(node, colspan, depth);
    // 親を畳んだら下の棚ごと隠す。棚の見出しだけが残ると、畳んだはずの中身の在り処が
    // そのまま並び続ける。
    shelf.classList.toggle("hidden", hiddenAbove);
    fragment.appendChild(shelf);
    const hideBelow = hiddenAbove || state.folded.has(node.group.key);
    (byKey.get(node.group.key) || []).forEach((tr) => {
      // 畳んでいる間も行はDOMに残す(隠すだけ)。選択も件数もそのままである。
      tr.classList.toggle("hidden", hideBelow);
      tr.style.setProperty("--st-depth", String(depth + 1));
      fragment.appendChild(tr);
    });
    byKey.delete(node.group.key);
    node.children.forEach((child) => walk(child, depth + 1, hideBelow));
  };
  roots.forEach((node) => walk(node, 0, false));
  // 棚の付かなかった行。行の在るfolderは必ず棚になる(落とすのは空の棚だけ)ので普段は
  // 空だが、**黙って捨てない** —— 一覧から消えた行は、消したのか出ていないのか読めない。
  byKey.forEach((list) => list.forEach((tr) => {
    tr.classList.remove("hidden");
    fragment.appendChild(tr);
  }));
  tbody.replaceChildren(fragment);
}

function renderHighlights() {
  const rows = visibleHighlights();
  // 表示していない行の選択は落とす。見えない行が黙って照合・削除の対象に入らないように。
  const visibleIds = new Set(rows.map((h) => h.id));
  [...state.picked].forEach((id) => { if (!visibleIds.has(id)) state.picked.delete(id); });

  // 棚は行を描く前に組む。入れ子(親子)と、中身の無い棚を落とすところまでここで決めて
  // おかないと、行を差し込む先が決まらない。
  const shelves = folderTree(folderGroups(rows));

  // 直前の「読み込み中…」「取得できませんでした」を素の文言へ戻す。0件の描画は
  // renderTableRowsがhiddenの付け外しで行う。
  setListState($("hl-empty"), "empty");
  renderTableRows(
    "hl-rows", "hl-empty", rows,
    (h) => {
      const pick = document.createElement("input");
      pick.type = "checkbox";
      pick.checked = state.picked.has(h.id);
      pick.setAttribute("aria-label", `${h.filename} を選ぶ`);
      pick.addEventListener("change", () => {
        if (pick.checked) state.picked.add(h.id);
        else state.picked.delete(h.id);
        renderPickedCount();
        syncSelectAll();
      });

      const file = document.createElement("span");
      file.className = "st-file";
      file.textContent = h.filename || "—";
      file.title = h.path || h.filename || "";

      const status = document.createElement("span");
      status.textContent = statusLabel(h.status);
      if (h.error) status.title = h.error;
      // 照合の窓と結末。**「照合済」だけでは空振りが読めない。**
      const note = matchNote(h);
      if (note) {
        status.title = [h.error, note.title].filter(Boolean).join("\n");
        if (note.empty) {
          const mark = document.createElement("span");
          mark.className = "st-risk-text st-nowrap";
          mark.textContent = " 当たり無し";
          status.appendChild(mark);
        }
      }

      // 行の操作は「照合」だけにする(利用者の指定)。隣に在った「検証」は**行の主語と
      // 移る先の主語が違った** —— 押した1本ではなく、その配信者の週ぜんたいの面へ飛ぶ
      // buttonが行ごとに並んでいたので、押した本と出てくる物が結び付かない。検証の面へは
      // 上のtabから移る。
      const ops = document.createElement("span");
      ops.className = "vd-row-pair";
      const match = document.createElement("button");
      match.className = "btn btn-small";
      match.type = "button";
      match.textContent = "照合";
      match.addEventListener("click", () => runMatch([h.id]));
      ops.append(match);

      return [
        pick,
        h.unique_id || "—",
        file,
        h.duration_seconds ? fmtDuration(h.duration_seconds) : "—",
        status,
        num(h.segment_count) === null ? "—" : fmtNum(h.segment_count),
        // **2つの数は別物である。** gift演出1つが複数のgiftを持つので、「giftを持つgift演出の数」
        // と「giftの件数」は一致しない(実測でHearts 199🪙の6連投が1つのgift演出に乗る)。
        num(h.gift_segment_count) === null ? "—" : fmtNum(h.gift_segment_count),
        num(h.gift_total_count) === null ? "—" : fmtNum(h.gift_total_count),
        Number(h.top_diamonds) ? fmtNum(h.top_diamonds) : "—",
        Number(h.gift_diamonds) ? fmtNum(h.gift_diamonds) : "—",
        h.matched_at ? fmtDateTimeShort(h.matched_at) : "—",
        ops,
      ];
    },
    [3, 5, 6, 7, 8, 9],
    (tr, h) => {
      // どのfolderの中身か。棚の見出しはこの印を頼りに差し込む(renderFolderRows)。
      tr.dataset.folder = folderKey(h);
      // 観ている行の印を、表を組み直さずに付け替えるための鍵(markListSelection)。
      tr.dataset.hlid = String(h.id);
      // 一覧はfile名の順で、先頭行に順位の意味は無い(共通の描画が付ける1位の印を外す)。
      tr.classList.remove("rank-top");
      tr.classList.add("row-clickable");
      // 実体の無い行も警告色で名乗る。状態の列(「fileが無い」)だけでは、行が数十本
      // 並んだときに気付けない ―― 片付けるべき行が在ることが、一覧を眺めた時点で
      // 目に入る必要がある。
      const gone = h.status === HL_STATUS_MISSING;
      if (h.error || gone) tr.classList.add("row-warn");
      // 名乗るのはServerのerror文だけ。押した結果(左で再生)は押せば判る。
      if (h.error) tr.title = h.error;
      // **clickでは面を移らない。** 以前は検証tabへ飛ばしていたので、1本確かめるたびに
      // 一覧の位置も選択も失われ、選んで消すという一続きの操作がそこで切れていた。
      // 検証の面へは行のbuttonで移る。
      tr.addEventListener("click", (ev) => {
        if (ev.target.closest("button, input, select, a")) return;
        // 選択の列は「選ぶ」ための列である。checkboxそのものは小さく、その周りのcellを
        // 押した時に再生が始まると、選ぼうとした操作が別の意味に化ける。
        if (ev.target.closest("td") === tr.cells[0]) {
          const box = tr.cells[0].querySelector("input[type=checkbox]");
          if (box) {
            box.checked = !box.checked;
            box.dispatchEvent(new Event("change"));
          }
          return;
        }
        playInList(h);
      });
    },
  );

  renderFolderRows(shelves);
  // 組み直した後に印を戻す。走査や照合で一覧が引き直されても、観ている行は観ている行の
  // ままである ―― 印が消えると、どの行を映しているのかが動画側からしか判らなくなる。
  markListSelection();

  const total = rows.reduce((sum, h) => sum + (Number(h.gift_diamonds) || 0), 0);
  const gifts = rows.reduce((sum, h) => sum + (Number(h.gift_total_count) || 0), 0);
  $("hl-summary").textContent =
    `${fmtNum(rows.length)} · ${fmtNum(gifts)} · 🪙${fmtCompact(total)}`;
  renderPickedCount();
  renderPurgeButton();
  syncSelectAll();
  renderExportPicks();
  // 観ていた本が台帳から消えた(削除・片付け)。playerに前の本が残ったままだと、消したのに
  // 消えていないように見える。
  const watching = state.listPlayId !== null ? state.listPlayId : state.listMarkId;
  if (watching !== null && !state.highlights.some((h) => h.id === watching)) {
    playInList(null);
  }
  // 検証tabを開いたまま一覧が届いた時。配信者の選択肢は一覧から組むので、届いた時点で
  // 組み直さないと空のままになる ―― 前回見ていたtabが検証だと、開いた瞬間はまだ
  // 一覧が無い(showViewは読み込みより先に走る)。開いていない間は引かない。
  if (!$("view-cover").classList.contains("hidden")) renderCoverPicks();
}

function syncSelectAll() {
  const rows = visibleHighlights();
  const box = $("hl-select-all");
  const picked = rows.filter((h) => state.picked.has(h.id)).length;
  box.checked = rows.length > 0 && picked === rows.length;
  box.indeterminate = picked > 0 && picked < rows.length;
}

async function loadHighlights() {
  setListState($("hl-empty"), "loading");
  let data;
  try {
    // 絞り込みは画面側で行う。棚(配信者)と状態の選択肢は全件から組むもので、
    // 絞った結果から組むと選び直せなくなる。
    data = await apiSend("GET", "/api/highlights");
  } catch (err) {
    setListState($("hl-empty"), "failed", err);
    showError(err, "ハイライトの一覧");
    return;
  }
  state.highlights = data.items || [];
  // Serverが既定を名乗るなら受け取る。名乗らない版のServerでは null のままで、画面は
  // 数字を作らずに「既定」と出す。
  state.defaults = data.defaults || null;
  // 投入先はServerが名乗る。名乗らない版のServerでは空のままで、受け皿は配信者だけを
  // 名乗る(pathを画面側で組み立てて埋めない)。
  state.uploadDirs = data.upload_dirs || {};
  // 置き場のfolder。**空のfolderもここに来る**(棚に出すかどうかは画面が決める)。
  // 名乗らない版のServerでは空のままで、棚は行が名乗ったfolderだけから組む
  // (画面が置き場のpathを組み立てることはしない)。
  state.folders = data.folders || [];
  // 受け取れる拡張子。folderごとdropされた中身をここで絞る ―― 画面が綴りを持つと、
  // Serverが受ける拡張子と2箇所に分かれる。名乗らない版のServerでは空のままで、
  // 絞らずに全部を送る(断る理由はServerが1件ずつ返す)。
  state.uploadExtensions = (data.extensions || []).map((ext) => String(ext).toLowerCase());
  // 作れる週のfolderの候補。**名前も週の境目もServerが決める**(土曜の朝7時始まり)。
  state.weekFolders = data.week_folders || [];
  renderDefaults();
  renderStreamerShelf();
  renderStatusOptions();
  renderWeekFolders();
  renderHighlights();
}

// 「週のfolder」の選択肢。Serverが名乗った候補をそのまま並べる ―― 画面で日付を組み立てる
// と、対象の週(検証・出力tab)と1日ずれた名前のfolderが静かに増える。
//
// 作れるのは配信者を選んでいる間だけである。置き場は配信者folderの下なので、「全て」の
// ままでは作る先が決まらない —— 押せるままにして押してから断るのでは、何を直せばよいのかが
// 判らない。
function renderWeekFolders() {
  const select = $("hl-folder-week");
  const want = select.value;
  const names = state.weekFolders || [];
  select.innerHTML = "";
  names.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.name || "";
    option.textContent = item.name || "";
    // 週の端はServerの名乗りをそのまま出す。folder名(日付だけ)からは、境目が朝7時で
    // あることも、どちらの日が含まれるのかも読めない。
    if (item.label) option.title = item.label;
    select.appendChild(option);
  });
  if (want && names.some((item) => item.name === want)) select.value = want;
  select.disabled = names.length === 0;
  const button = $("hl-folder-add");
  // 押せない状態はbuttonそのものが名乗る(利用者の指定)。押せない理由の文言は置かない。
  button.disabled = !names.length || !state.streamer;
}

// 週のfolderを作る。**作る先はServerが決める**(配信者の投入先の下) —— 画面がpathを
// 組み立てると、置き場の決まりが変わった日に画面だけが実在しない場所を名乗る。
async function createWeekFolder() {
  const name = $("hl-folder-week").value;
  const streamer = state.streamer;
  if (!name || !streamer) return;
  const button = $("hl-folder-add");
  button.disabled = true;
  try {
    const res = await apiSend("POST", "/api/highlights/folders", { streamer, name });
    // 既に在る場合もServerが名乗る(作ったのか元から在ったのかを画面で決めない)。
    showToast(`${res.created ? "作成" : "既存"}: ${res.path || name}`);
    await loadHighlights();
  } catch (err) {
    showError(err, "folderの作成");
  } finally {
    renderWeekFolders();
  }
}

async function scanHighlights() {
  const btn = $("hl-scan");
  btn.disabled = true;
  setFormMessage($("hl-status-note"), "走査中…", false);
  try {
    const body = state.streamer ? { streamer: state.streamer } : {};
    const res = await apiSend("POST", "/api/highlights/scan", body);
    // 見た置き場の数まで言う。0件のときに「どこも見ていない」のか「見たが空だった」のかを
    // 画面が言い分けられないと、置き場の設定漏れが「ハイライトが無い」と読める。
    const dirs = (res.dirs || []).length;
    const text = `${fmtNum(dirs)}箇所 +${fmtNum(res.added)}`
      + ` ~${fmtNum(res.updated)} ?${fmtNum(res.missing)}`;
    setFormMessage($("hl-status-note"), text, false);
    showToast(text);
    await loadHighlights();
  } catch (err) {
    setFormMessage($("hl-status-note"), "", false);
    showError(err, "置き場の走査");
  } finally {
    btn.disabled = false;
  }
}

// ===== 投入(dropとbutton) =====

// ハイライトのmp4を画面へdropして置き場へ入れる。ここまでは利用者がfolderを開いて、
// 配信者ごとの正しい置き場へ手でfileを置き、それから「置き場を走査」を押していた。
//
// **投入先は配信者folderの下**なので、配信者が決まらないままでは受けない。置き場を
// 間違えたハイライトは失敗として現れず、その人の週のgiftと突き合わせて「当たらない」
// だけになる —— 静かに増えるので、後から気付く手立てが無い。
//
// pathは**Serverが名乗った値**(`upload_dirs`)をそのまま出す。画面で組み立てると、置き場の
// 決まりが変わった日に画面だけが実在しない場所を名乗る(投入自体は成功するので、名乗りが
// 嘘であることに誰も気付かない)。

// dragの間だけ受け皿を縁取る。dragoverはdragの間ずっと届き、**dragleaveは受け皿の中の
// 子要素へ移るたびにも届く**ので、離れたことを1回のeventで判断しない。最後のdragoverから
// この時間が空いたら畳む。
const DROP_HINT_CLEAR_MS = 180;

// folderごとdropされたときに辿る段の上限。entryの木は理屈の上では無限に深くでき
// (junctionやsymlinkの環)、辿り切るまで画面が返らない。仕分けは「週 / その中の分類」
// までなので、これで足りないほど深い置き場は人が畳んでから落とす。
const DROP_DIR_DEPTH_MAX = 8;

let dropHintTimer = null;

// fileのdragか。文字やURLのdragで受け皿を光らせない(落としても何も起きない)。
function isFileDrag(ev) {
  const types = ev.dataTransfer && ev.dataTransfer.types;
  return Boolean(types) && Array.from(types).includes("Files");
}

// dragが今どのfolderの行の上に居るか。**folderの行へ落とせばそのfolderへ入る。**
// 週ごとの仕分けは投入した後に人が手でfileを動かしていたが、一覧には既にその棚が
// 出ているので、そこへ落とせるなら移す手間がまるごと消える。
//
// 覆い(#hl-drop)は pointer-events を持たないので、dragの当たり判定は下の行に届く。
function dropFolderRow(ev) {
  if (!ev.target || !ev.target.closest) return null;
  const tr = ev.target.closest("tr.st-folder");
  // 配信者の名乗れないfolder(Serverが unique_id を返していない)へは入れない ――
  // 置き場は配信者folderの下で、誰の置き場かが決まらないまま投入すると、別人の置き場に
  // 入ったハイライトが「当たらないだけ」の形で静かに増える。
  return tr && tr.dataset.streamer ? tr : null;
}

// 投入先の名乗り。folderの行の上ならそのfolder、そうでなければ棚で選んでいる配信者の
// 置き場。配信者が決まっていなければ null(受け皿は受けないと名乗る)。
//
// **Serverへ渡すのは root_key と source_dir だけ**である。実pathは名乗りにしか使わない
// ―― 画面がpathを組み立てると、置き場の決まりが変わった日に画面だけが実在しない場所を
// 名乗る(投入は成功するので、名乗りが嘘であることに誰も気付かない)。
function uploadTarget(row) {
  if (row) {
    return {
      streamer: row.dataset.streamer || "",
      directory: row.dataset.path || "",
      rootKey: row.dataset.rootKey || "",
      sourceDir: row.dataset.fold || "",
      folder: row.dataset.folderLabel || "",
    };
  }
  const streamer = state.streamer;
  if (!streamer) return null;
  return { streamer, directory: (state.uploadDirs || {})[streamer] || "",
           rootKey: "", sourceDir: "", folder: "" };
}

// dropされた物からmp4を集める。**folderごと落とされたら中を再帰で辿る。**
//
// ``DataTransferItemList`` は event handler を抜けた時点で空になるので、entryの取り出し
// だけは await より前に済ませる(fileの読み出しはその後でよい)。
function dropEntries(dataTransfer) {
  const items = (dataTransfer && dataTransfer.items) || [];
  const entries = [];
  Array.from(items).forEach((item) => {
    if (!item || item.kind !== "file") return;
    const entry = typeof item.webkitGetAsEntry === "function"
      ? item.webkitGetAsEntry() : null;
    if (entry) entries.push(entry);
  });
  return entries;
}

// entry 1つぶん。folderなら中を辿る。
//
// ``readEntries`` は**1回で全部を返さない**決まりで、空の配列が返るまで呼び続けるのが
// 正しい読み方である ―― 1回で止めると、100件を超えるfolderの後ろが黙って落ちる。
async function collectEntry(entry, out, depth) {
  if (!entry) return;
  if (entry.isFile) {
    const file = await new Promise((resolve) => entry.file(resolve, () => resolve(null)));
    if (file) out.push(file);
    return;
  }
  if (!entry.isDirectory || depth >= DROP_DIR_DEPTH_MAX) return;
  const reader = entry.createReader();
  for (;;) {
    const batch = await new Promise(
      (resolve) => reader.readEntries(resolve, () => resolve([])));
    if (!batch || !batch.length) break;
    for (const child of batch) {
        await collectEntry(child, out, depth + 1);
    }
  }
}

// 受け取れる拡張子か。**判定の綴りは画面が持たない** ―― Serverが名乗った一覧
// (`GET /api/highlights` の extensions)で絞る。folderごと落とすと動画以外も入って
// くるので、ここで絞らないと1件ずつ断りのtoastが何十個も並ぶ。
//
// Serverが名乗らない版では絞らない。**画面側の綴りで黙って捨てるより、Serverに断らせて
// 理由を出す方が読める**(何が入らなかったのかが1件ずつ判る)。
function isHighlightFile(file) {
  const exts = state.uploadExtensions || [];
  if (!exts.length) return true;
  const name = String((file && file.name) || "").toLowerCase();
  return exts.some((ext) => name.endsWith(ext));
}

// dropされた物ぜんたい。{files, skipped}。
async function filesFromDrop(dataTransfer) {
  const entries = dropEntries(dataTransfer);
  // entryの口を持たないbrowserでは、平らなfileの列しか受け取れない(folderの中は辿れない)。
  const raw = [];
  if (entries.length) {
    for (const entry of entries) {
        await collectEntry(entry, raw, 0);
    }
  } else {
    Array.from((dataTransfer && dataTransfer.files) || []).forEach((f) => raw.push(f));
  }
  const files = raw.filter(isHighlightFile);
  return { files, skipped: raw.length - files.length };
}

// ハイライト一覧tabが今見えているか。**受けるのはこの面だけ**である。
function listViewOpen() {
  return !$("view-list").classList.contains("hidden");
}

function hideDropHint() {
  clearTimeout(dropHintTimer);
  dropHintTimer = null;
  const drop = $("hl-drop");
  drop.classList.add("hidden");
  drop.classList.remove("st-drop-row");
  $("view-list").classList.remove("st-drop-on");
  Array.from(document.querySelectorAll("tr.st-folder-drop"))
    .forEach((tr) => tr.classList.remove("st-folder-drop"));
}

// 受け皿を縁取り、**どこへ入るのか**を名乗る。落とす前にこれが読めることが要件で、
// 配信者が決まっていないときは受けないことをここで言う(落としてから断るのでは遅い)。
//
// folderの行を狙っている間は、覆いの地を外して行そのものを縁取る ―― 面を覆ったままでは、
// 狙う相手(どの週のfolderか)が覆いの向こうに隠れて選べない。
function showDropHint(row) {
  const target = uploadTarget(row);
  const where = $("hl-drop-where");
  const drop = $("hl-drop");
  drop.classList.remove("hidden");
  drop.classList.toggle("st-drop-blocked", !target);
  drop.classList.toggle("st-drop-row", Boolean(row));
  $("view-list").classList.add("st-drop-on");
  Array.from(document.querySelectorAll("tr.st-folder-drop"))
    .forEach((tr) => { if (tr !== row) tr.classList.remove("st-folder-drop"); });
  if (row) row.classList.add("st-folder-drop");
  where.textContent = !target
    ? "配信者を選んでください"
    : (target.directory ? `${target.streamer} / ${target.directory}` : target.streamer);
  clearTimeout(dropHintTimer);
  dropHintTimer = setTimeout(hideDropHint, DROP_HINT_CLEAR_MS);
}

// 投入そのもの。**multipartなのでapiSendは通らない**(あちらはJSONを送る口である)。
// 失敗の名乗り方だけは揃える ―― Serverの文言(detail)をそのまま画面へ出す。
//
// 投入先のfolderは root_key と source_dir で名乗る(Serverが一覧で名乗った綴りそのまま)。
// 空なら配信者の置き場そのもの ―― pathを送らないのは、画面から任意のdirを名乗れる口を
// 作らないためである。
async function postUploads(target, files) {
  const form = new FormData();
  form.append("streamer", target.streamer);
  if (target.rootKey) form.append("root_key", target.rootKey);
  if (target.sourceDir) form.append("source_dir", target.sourceDir);
  files.forEach((file) => form.append("files", file, file.name));
  let res;
  try {
    res = await fetch("/api/highlights/upload", { method: "POST", body: form });
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
  return res.json();
}

async function uploadHighlights(files, options = {}) {
  const list = Array.from(files || []).filter(Boolean);
  const skipped = Number(options.skipped) || 0;
  const target = options.target === undefined ? uploadTarget() : options.target;
  if (!list.length) {
    // folderごと落として1本も動画が無かった時。**黙って終わらない** ―― 落とした本人には、
    // 受け皿が反応しなかったのか、中に動画が無かったのかが見分けられない。
    if (skipped) {
      showToast(`${fmtNum(skipped)}件は動画ではないので除きました`,
                "error", { title: "ハイライトの投入" });
    }
    return;
  }
  if (!target) {
    // 「全て」のままでは投入先が決まらない。黙って捨てず、何をすればよいかを名乗る。
    showToast("配信者を選んでください", "error", { title: "ハイライトの投入" });
    return;
  }
  const add = $("hl-add");
  add.disabled = true;
  setFormMessage($("hl-status-note"),
    `投入中… ${fmtNum(list.length)} → ${target.folder || target.streamer}`, false);
  let res;
  try {
    res = await postUploads(target, list);
  } catch (err) {
    setFormMessage($("hl-status-note"), "", false);
    showError(err, "ハイライトの投入");
    return;
  } finally {
    add.disabled = false;
  }
  // **断ったfileは1件ずつ理由を出す。** まとめて「n件失敗」にすると、どれがなぜ入らなかった
  // のかが判らず、利用者はもう一度全部を落とすしかなくなる。
  (res.items || []).filter((item) => !item.saved).forEach((item) => {
    showToast(`${item.filename}: ${item.reason || "保存できませんでした。"}`,
      "error", { title: "投入できなかったfile" });
  });
  const saved = Number(res.saved) || 0;
  const rejected = Number(res.rejected) || 0;
  const text = `+${fmtNum(saved)}`
    + (rejected ? ` ✕${fmtNum(rejected)}` : "")
    // folderごと落としたときに除いた動画以外のfile。件数を出さないと、置いたはずの物が
    // 一覧に出ない理由が読めない。
    + (skipped ? ` −${fmtNum(skipped)}` : "")
    + (res.directory ? ` ${res.directory}` : "");
  setFormMessage($("hl-status-note"), text, rejected > 0);
  if (saved) {
    showToast(text);
    // 台帳はServerが走査して作る。1本も入らなかったときは置き場が変わっていないので
    // 引き直さない(同じ一覧をもう一度引くだけになる)。
    await loadHighlights();
  }
}

// 画面のどこへ落としてもbrowserが動画を開いてしまわないよう、既定動作は面の外でも止める。
// **ただし受けるのはハイライト一覧tabだけ**である ―― 検証tab・出力tabへ落ちた物を黙って
// 投入すると、見ている面と関係の無い所でfileが増える。
function bindDrop() {
  const onList = (ev) =>
    listViewOpen() && ev.target && ev.target.closest
    && Boolean(ev.target.closest("#view-list"));

  document.addEventListener("dragover", (ev) => {
    if (!isFileDrag(ev)) return;
    ev.preventDefault();
    if (!onList(ev)) {
      if (ev.dataTransfer) ev.dataTransfer.dropEffect = "none";
      hideDropHint();
      return;
    }
    const row = dropFolderRow(ev);
    if (ev.dataTransfer) ev.dataTransfer.dropEffect = uploadTarget(row) ? "copy" : "none";
    showDropHint(row);
  });

  document.addEventListener("drop", (ev) => {
    if (!isFileDrag(ev)) return;
    ev.preventDefault();
    // **投入先とentryは、この場で決めて掴んでおく。** dataTransfer は handler を抜けると
    // 空になり、覆いを畳んだ後では狙っていた行も判らなくなる。
    const target = uploadTarget(dropFolderRow(ev));
    const picked = filesFromDrop(ev.dataTransfer);
    hideDropHint();
    if (!onList(ev)) return;
    picked.then(({ files, skipped }) => uploadHighlights(files, { target, skipped }));
  });

  // dragを画面の外で終えた場合。縁取りが残ると、受け皿がまだ開いているように見える。
  document.addEventListener("dragleave", (ev) => {
    if (ev.relatedTarget) return;
    hideDropHint();
  });
  document.addEventListener("dragend", hideDropHint);
}

// 照合の設定。空欄の項目は body に入れない ―― 画面が既定の数値を持つと、Server側の
// 設定を変えても画面から起動した分だけ古い値で走る。
function matchOptions() {
  const body = {};
  const put = (id, key) => {
    const raw = $(id).value.trim();
    if (raw === "") return;
    const value = Number(raw);
    if (Number.isFinite(value)) body[key] = value;
  };
  put("opt-days", "days");
  put("opt-gift-lead", "gift_lead");
  put("opt-gift-tail", "gift_tail");
  put("opt-min-diamonds", "min_diamonds");
  put("opt-window", "window");
  put("opt-hop", "hop");
  const scope = $("opt-scope").value;
  if (scope) body.scope = scope;
  return body;
}

async function runMatch(ids) {
  if (!ids.length) return;
  const body = matchOptions();
  let started = 0;
  const failures = [];
  for (const id of ids) {
    try {
      await apiSend("POST", `/api/highlights/${id}/match`, body);
      started += 1;
    } catch (err) {
      failures.push(err);
    }
  }
  if (started) {
    showToast(`${fmtNum(started)}本を順番待ちへ`, undefined,
              { title: "照合", duration: JOB_TOAST_MS });
  }
  // 失敗は1件ずつ理由を出す。まとめて「n件失敗」にすると、どれがなぜ落ちたのか判らない。
  failures.forEach((err) => showError(err, "照合の起動"));
  await loadHighlights();
}

// 台帳から外す。**失敗は1件ずつ理由を出す。** 「n本外しました」だけにすると、外れなかった
// 行が黙って一覧へ残り、押しても消えないbuttonに見える。
async function deleteHighlightRows(ids, { title, message, confirmLabel }) {
  if (!ids.length) return 0;
  const ok = await confirmDialog(message, { title, confirmLabel });
  if (!ok) return 0;
  let done = 0;
  const failures = [];
  for (const id of ids) {
    try {
      await apiSend("DELETE", `/api/highlights/${id}`);
      done += 1;
      state.picked.delete(id);
    } catch (err) {
      failures.push(err);
    }
  }
  if (done) showToast(`✕ ${fmtNum(done)}`, "info", { title });
  failures.forEach((err) => showError(err, title));
  await loadHighlights();
  return done;
}

async function deletePicked() {
  const ids = [...state.picked];
  if (!ids.length) return;
  await deleteHighlightRows(ids, {
    title: "台帳から削除",
    message: `${fmtNum(ids.length)}本を台帳から外します（動画fileは残ります）。`,
    confirmLabel: "外す",
  });
}

// 実体の無い行をまとめて外す。**絞り込みを通さず全件が対象**である ―― 溜まっているのを
// 片付けるための操作なので、今どの配信者・どの状態で絞っているかとは関係が無い。
// 動画fileには触らない(そもそも置き場にもう無い行である)。
async function purgeMissing() {
  const rows = missingHighlights();
  if (!rows.length) return;
  const names = rows.slice(0, 5).map((h) => `・${h.unique_id || "?"} / ${h.filename}`);
  if (rows.length > names.length) names.push(`・ほか ${fmtNum(rows.length - names.length)}本`);
  await deleteHighlightRows(rows.map((h) => h.id), {
    title: "実体の無い行の片付け",
    message: `${fmtNum(rows.length)}本を台帳から外します。\n${names.join("\n")}`,
    confirmLabel: "外す",
  });
}

// ===== 左の動画エリア(検証の面) =====

// そのハイライトを左のplayerへ載せる。既に開いていれば何もしない ―― 同じ本の別のgiftへ
// 移るたびにsrcを差し替えると、そのたびに読み込みからやり直しになって続けて見られない。
async function openStage(highlightId) {
  const id = num(highlightId);
  if (id === null) return false;
  if (state.currentId === id && state.current) return true;
  let data;
  try {
    data = await apiSend("GET", `/api/highlights/${id}`);
  } catch (err) {
    state.current = null;
    state.currentId = null;
    showError(err, "ハイライトの読み込み");
    loadVideo(null);
    drawTimeline();
    return false;
  }
  state.current = data;
  state.currentId = id;
  state.currentSegId = null;
  state.currentGiftId = null;
  // 時間軸へ載せるgiftの絵を先に頼む。描く時になって初めて頼むと、開いた直後の数秒だけ
  // 名前しか出ていない軸になる。
  preloadIcons(timelineGifts().map((gift) => gift.gift_image));
  loadStrip(id);
  loadVideo(data.highlight);
  return true;
}

// ===== 軸の下へ敷くコマ(filmstrip) =====
//
// hoverの1枚(``/frame``)とは役目が違う。あちらは「指した秒に何が映っているか」を1枚で
// 答える物で、こちらは**軸と同じ横軸を絵で埋めて「どこで場面が変わるか」を目で追わせる**
// 物である。gift演出の境目は音で決まっていて映像はそこから遅れて切り替わるので、切り替わりが
// どこで終わるのかは再生しない限り読めなかった。
//
// **置き場所は軸の地ではなく軸の下の1本の帯である。** 地へ敷いていた頃は、同じ場所に
// gift iconとgift名が載っていて、絵の上の字も絵に重なるiconも読めなかった(利用者の指摘)。
// 面を分ければ、絵は絵として詰めて敷けて、iconと名前は元の地色の上に戻る。横軸は共通
// なので、「この絵の秒に何が飛んだか」は真上を見れば読める。
//
// 1枚ずつのfileで敷くと軸1本に数十のHTTP往復が要るため、Serverが焼いた1枚のsprite sheetを
// 背景として使い回す(配信者動画のseek barと同じ作り)。**開いた時点で頼む** —— 描く時に
// なって初めて頼むと、行を送るたびに最初の描画だけコマの無い軸になる。
async function loadStrip(highlightId) {
  state.strip = null;
  state.stripImage = null;
  let spec;
  try {
    spec = await apiSend("GET", `/api/highlights/${highlightId}/thumbnails`);
  } catch (err) {
    // 敷けなくても軸は読める(gift演出・gift・演出区間はそのまま出る)ので、面は止めない。
    // 名乗るのはconsoleだけにする —— 人が押した操作の結末ではない。
    console.warn("filmstrip load failed", err);
    return;
  }
  // 焼いている間に別のハイライトへ移っていたら捨てる。開いている本と違う絵を敷くと、
  // 秒はこちらの本のまま絵だけが別の本になる(絵は出るので誰も気付かない)。
  if (state.currentId !== highlightId) return;
  const image = new Image();
  image.addEventListener("load", () => {
    if (state.strip !== spec) return;
    drawTimeline();
  });
  image.src = spec.url;
  state.strip = spec;
  state.stripImage = image;
}

// 敷ける状態か。仕様と絵が対で揃っていて、かつ利用者が出す設定にしているとき。
function stripSpec() {
  const spec = state.strip;
  const image = state.stripImage;
  if (!spec || !image || !stripEnabled()) return null;
  return image.complete && image.naturalWidth > 0 ? spec : null;
}

// 利用者が出す設定にしているか。**帯の場所は絵が届く前から空けておく** —— 絵の到着で軸の
// 高さが変わると、行を送るたびに下の欄が跳ねる。
function stripEnabled() {
  return $("cv-show-strip").checked;
}

// コマの帯の高さ(px)。切っているときは0で、軸は帯のぶんだけ薄くなる。
function stripLanePx() {
  return stripEnabled() ? STRIP_LANE_PX : 0;
}

// 帯のぶんだけcanvasを**厚くする**。本体から削って場所を作ると、iconの段が作れなくなって
// 「同じ数秒に飛んだgiftが🪙の重い1件しか出ない」に戻る。高さの出所はCSS側のclampのまま
// にして、足す量だけをここから渡す —— pxを画面とCSSの2か所に書くと、片方だけ直した日に
// 絵が帯からはみ出す。
//
// 渡す先は**軸の枠(.st-axis)**である。canvasへ直に書いていた頃は、間の受け皿
// (.vd-heat-wrap)がこの値を読めなかった —— 面が縦に足りないときに軸を薄くする下限は
// 受け皿とcanvasの両方が同じ値で持っていなければ、片方だけが先に止まってはみ出す。
function syncStripLane() {
  const px = `${stripLanePx()}px`;
  const canvas = $("cv-timeline");
  const el = canvas && (canvas.closest(".st-axis") || canvas);
  if (!el || el.style.getPropertyValue("--strip-lane") === px) return;
  el.style.setProperty("--strip-lane", px);
}

// 軸の下のコマの帯。敷けないとき(絵がまだ来ていない・その動画が読めない)は、帯の場所を
// 地色で残す —— 詰めるのは絵だけで、場所そのものは設定が決めている。
function drawStripLane(ctx, { left, right, top, bottom, secondsAt, width }) {
  if (!(bottom > top)) return;
  ctx.fillStyle = cssTokenAlpha("--line", 0.14);
  ctx.fillRect(0, top, width, bottom - top);
  // 本体との境。帯が本体の続きに見えると、絵の上にgift演出の面が載っているように読める。
  ctx.fillStyle = cssTokenAlpha("--line", 0.45);
  ctx.fillRect(0, top, width, 1);
  drawFilmstrip(ctx, { left, right, top: top + 1, bottom, secondsAt });
}

// 帯へコマを敷く。敷けたらtrue。
//
// **敷く枚数はsheetの刻みではなく軸の幅で決める。** 0.25秒刻みのまま並べると、60秒を
// 1200pxへ写した軸では1枚が5pxの短冊になって、何が映っているのか読めない。1枚が縦横比
// なりの幅を占めるように置き、その場所の秒に一番近いtileを選ぶ。
//
// tileは**その秒以前**の物を選ぶ(切り上げない)。切り替わりの手前の枠に「切り替わった後の
// 絵」が入ると、境目が実際より手前に在るように見える —— この軸で詰めているのは、まさに
// その境目である。
function drawFilmstrip(ctx, { left, right, top, bottom, secondsAt }) {
  const spec = stripSpec();
  if (!spec) return false;
  const laneHeight = bottom - top;
  const laneWidth = right - left;
  if (!(laneHeight > 0) || !(laneWidth > 0)) return false;
  const slot = Math.max(6, Math.round(laneHeight * spec.tile_width / spec.tile_height));
  ctx.save();
  ctx.beginPath();
  ctx.rect(left, top, laneWidth, laneHeight);
  ctx.clip();
  for (let x = left; x < right; x += slot) {
    const at = secondsAt(x + slot / 2);
    if (!Number.isFinite(at)) continue;
    const index = Math.max(0, Math.min(spec.count - 1,
                                       Math.floor(at / spec.interval_seconds)));
    ctx.drawImage(state.stripImage,
                  (index % spec.columns) * spec.tile_width,
                  Math.floor(index / spec.columns) * spec.tile_height,
                  spec.tile_width, spec.tile_height,
                  x, top, slot, laneHeight);
  }
  ctx.restore();
  return true;
}

// ハイライトの動画はserverが再生URLを名乗る。画面がpathからURLを組み立てると、置き場の
// 決まりが変わった瞬間に、実在しないURLを黙って指すようになる。
function loadVideo(highlight) {
  const video = $("cv-video");
  video.pause();
  state.playUntil = null;
  const url = highlight && highlight.url;
  if (!url) {
    video.removeAttribute("src");
    video.load();
    setFormMessage($("cv-play-status"), highlight ? "再生URLが無い" : "", Boolean(highlight));
    return;
  }
  setFormMessage($("cv-play-status"), "", false);
  video.src = url;
}

// その位置へ飛ぶ。読み込みが終わる前に呼ばれることがあるので、metadataが来た時にもう一度
// 当てる ―― 一度だけ当てて諦めると、開いた直後の1件だけ頭から再生される。
function seekTo(at, { play = false, until = null } = {}) {
  const video = $("cv-video");
  const value = num(at);
  if (value === null) return;
  state.playUntil = until === null ? null : Number(until);
  const apply = () => {
    if (video.readyState <= 0) return false;
    video.currentTime = value;
    if (play) {
      const started = video.play();
      // 自動再生を止めるbrowserが在る。黙って何も起きないのが一番読めないので名乗る。
      if (started && started.catch) {
        started.catch(() => setFormMessage($("cv-play-status"), "clickで再生", false));
      }
    }
    return true;
  };
  if (!apply()) {
    video.addEventListener("loadedmetadata", apply, { once: true });
  }
}

// ===== 倍速再生 =====
// 検証tabと出力tabは**同じ1つの速さ**を使う。同じ画面の同じ「観る」操作で、tabを移る
// たびに選び直させる理由が無い。選んだ速さはlocalStorageへ残り、次に開いた時も同じ
// 速さで始まる(key は tictok.story.play-rate)。
//
// **<video>はsrcを差し替えるたびに速さを1xへ戻す。** この画面は行を送るたびに、また
// 通し再生で窓を跨ぐたびにsrcを差し替えるので、速さを入れて終わりにはできない ――
// 読み込みの度に当たる defaultPlaybackRate にも入れ、loadedmetadataでも当て直す。
const RATE_IDS = ["cv-rate", "ex-rate"];
// 一覧tabの「観る」(hl-video)はここに含めない。速さの操作を置いていない面で勝手に
// 速くなると、押した覚えのない設定で観ることになる。
const RATE_VIDEOS = ["cv-video", "ex-video"];

function playRate() {
  return Number($("cv-rate").value) || 1;
}

function applyRate() {
  const rate = playRate();
  RATE_VIDEOS.forEach((id) => {
    const video = $(id);
    if (!video) return;
    video.defaultPlaybackRate = rate;
    video.playbackRate = rate;
  });
}

// 片方を動かしたら、もう片方の摘みも同じ段へ寄せる。setterはchangeを出さない
// (user操作ではないため)ので、ここで往復し続けることはない。
function syncRate(from) {
  const value = $(from).value;
  RATE_IDS.forEach((id) => { if (id !== from) $(id).value = value; });
  applyRate();
}

// ===== 時間軸 =====

// ハイライトの尺。動画が読めていればそれが正で、まだならsegmentの終端で代用する
// (読み込み前でもgift演出の並びだけは描けるようにする)。
function timelineDuration() {
  const video = $("cv-video");
  if (Number.isFinite(video.duration) && video.duration > 0) return video.duration;
  const h = state.current && state.current.highlight;
  if (h && Number(h.duration_seconds) > 0) return Number(h.duration_seconds);
  const segments = (state.current && state.current.segments) || [];
  return segments.reduce((max, s) => Math.max(max, Number(s.end) || 0), 0);
}

// 演出区間。serverは ``segment.effect`` に ``[[開始, 終了], …]`` を秒で返す。秒の軸は
// ハイライトの中の秒である(highlight_match._spans がgift演出の開始 run["start"] を足して
// 作っている)。読めない形は何も描かない ―― それらしい区間を作ると、実際には映っていない
// 場所を演出だと読ませることになる。
function effectSpans(seg) {
  const raw = seg && seg.effect;
  if (!raw) return [];
  let value = raw;
  if (typeof raw === "string") {
    try {
      value = JSON.parse(raw);
    } catch (err) {
      return [];
    }
  }
  const list = Array.isArray(value)
    ? value
    : (value && Array.isArray(value.spans) ? value.spans : []);
  const out = [];
  list.forEach((item) => {
    const pair = Array.isArray(item)
      ? item
      : (item && typeof item === "object" ? [item.start, item.end] : null);
    if (!pair) return;
    const s = Number(pair[0]);
    const e = Number(pair[1]);
    if (!Number.isFinite(s) || !Number.isFinite(e) || e <= s) return;
    out.push([s, e]);
  });
  return out;
}

// 🪙の量。gift演出の面そのものを濃く塗ると、最高額のgift演出の上に載せたgift名が地に沈んで
// 読めなくなる(実測: 10,000🪙のgift演出で名前が判読できなかった)。量はgift演出の下端から立ち上がる
// 柱の高さで出し、面は明るいまま残して名前を読ませる。
// 高さの写像に平方根を挟むのは、🪙が10〜20,000と3桁またぐため ―― 単純な比だと最高額
// 以外の柱が全部床に張り付く。
function diamondRatio(diamonds, max) {
  const value = Number(diamonds) || 0;
  if (!(value > 0) || !(max > 0)) return 0;
  return Math.sqrt(Math.min(1, value / max));
}

// gift演出の窓。**dragで動くのはgift演出ではなく区間(切り出す範囲)の方**なので、ここは常に
// serverの値をそのまま返す。
function segmentWindow(seg) {
  return { start: Number(seg.start), end: Number(seg.end) };
}

// dragの間の仮の区間。確定(PATCH)するまでserverの値は書き換えないので、画面はこちらを描く。
function draggingCut() {
  const drag = state.barDrag;
  return drag && drag.mode !== "seek" ? { start: drag.start, end: drag.end } : null;
}

// 時間軸に載せるgift。**位置(``at``)を出せないgiftは載せない** —— gift演出の頭で代用すると、
// 判っていない位置が判っているように並ぶ。iconのURLをServerが出せなかったgiftも外す
// (場所だけ取って絵の出ない枠を置くと、そこに描けたはずの隣のgiftまで落ちる)。
function timelineGifts() {
  const out = [];
  ((state.current && state.current.segments) || []).forEach((seg) => {
    (seg.gifts || []).forEach((gift) => {
      if (num(gift.at) === null) return;
      if (!String(gift.gift_image || "").startsWith("/")) return;
      out.push(gift);
    });
  });
  return out;
}

// giftの名乗り。**gift名そのもの**を出す(配信者動画のbarが送り主の名前を出すのと同じ位置)。
// 切り詰めない —— 「Guardian's…」と「Guardian…」は別のgiftになり得るので、途中で切れた字は
// 見分けの役に立たない。名前のぶんの幅は間引き側が場所として数えるので、入らないものは
// 段が下りるか、🪙の重い方が残る。
function giftLabel(gift) {
  return String(gift.gift_name || (gift.gift_id ? `gift ${gift.gift_id}` : "")).trim();
}

// iconと名前を並べる段。**配信者動画の拡大窓と同じ組み方**で、iconの下に1行、入らない
// ものは段を下ろして拾う。
function drawTimelineGifts(ctx, { width, toX, top, bottom }) {
  const gifts = timelineGifts();
  if (!gifts.length) return;
  const laneH = bottom - top;
  const size = Math.max(10, Math.min(GIFT_ICON_PX, laneH * 0.45));
  const rowH = size + GIFT_NAME_LANE_PX + GIFT_ROW_GAP_PX;
  const rows = Math.max(1, Math.min(GIFT_MAX_ROWS,
                                    Math.floor((laneH * GIFT_LANE_RATIO) / rowH)));
  const picked = pickIcons(ctx, gifts, {
    toX: (gift) => toX(Number(gift.at)),
    width,
    size,
    rows,
    labelOf: giftLabel,
    rankOf: (gift) => Number(gift.diamonds) || 0,
  });
  drawIcons(ctx, picked, {
    top: top + 1,
    size,
    rowH,
    tickBottom: bottom,
    names: true,
    width,
    imageOf: (entry) => iconImage(entry.data.gift_image),
    decorate: (c, entry, y, iconSize, ink, barWidth) => {
      if (entry.label) drawIconLabel(c, entry.label, entry.x, y + iconSize, ink, barWidth);
    },
  });
}

// 時間軸。**配信者動画の seek bar と同じ作りである** —— 上端が範囲のhandle lane、下端が
// 時刻ruler、その間が本体で、本体の下端に印のlaneが載る。違うのは中身だけで、地に敷くのは
// 波形とheatではなく**gift演出(montageの継ぎ目)**、印のlaneに置くのは見どころではなく
// **演出区間**である。
function drawTimeline() {
  const canvas = $("cv-timeline");
  // 高さを測る前に帯のぶんを足す。測ってから足すと、1回ぶん古い高さで描いた絵が残る。
  syncStripLane();
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  // tab非表示のときは実寸が0になる。この状態で描いても捨てるだけなので何もしない。
  if (!width || !height) return;
  // canvas.width/heightへの代入はbacking storeを作り直して全消去する。timeupdate毎に
  // 再確保しないよう、寸法が変わったときだけ代入する。
  if (canvas.width !== width) canvas.width = width;
  if (canvas.height !== height) canvas.height = height;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, width, height);

  const duration = timelineDuration();
  if (!(duration > 0)) {
    $("cv-tl-note").textContent = "";
    return;
  }
  const toX = (t) => (Math.max(0, Math.min(duration, t)) / duration) * width;
  // 上端=区間のhandle lane、下端=時刻ruler。演出区間は本体の下端のlaneへ置く
  // (配信者動画が見どころを置いているのと同じ場所)。コマの帯はその更に下、rulerの直上に
  // 置く —— 本体(gift演出・icon・名前)とは別の面である。
  //
  // **演出区間の出し入れは持たない。** 常に載せる —— 選択肢を持っていた頃も既定は
  // 「載せる」で、消す理由のある人が居なかった(利用者の指定でcheckboxを外した)。
  const bodyTop = RANGE_LANE_PX;
  const bodyBottom = height - RULER_LANE_PX;
  const stripTop = bodyBottom - stripLanePx();
  const effectTop = stripTop - MARKER_LANE_PX;
  const segments = (state.current && state.current.segments) || [];
  const maxDiamonds = segments.reduce((m, s) => Math.max(m, segmentDiamonds(s)), 0);

  // gift演出。面は明るいまま残し、🪙の量は下端から立ち上がる柱の高さで出す(配信者動画の
  // heatの柱と同じ役目)。giftを割り出せなかったgift演出は柱を持たず地に近い薄さで置く ――
  // 取得の失敗ではなく、そこがgift地点ではなかったという結果なので、警告色は当てない。
  ctx.save();
  segments.forEach((seg) => {
    const win = segmentWindow(seg);
    if (!Number.isFinite(win.start) || !Number.isFinite(win.end)) return;
    const x0 = toX(win.start);
    const x1 = toX(win.end);
    const w = Math.max(1, x1 - x0);
    const gift = hasGift(seg);
    // 面は地の色のまま。**絵はこの上に載らない**(帯は下に在る)ので、透かす必要は無く、
    // 柱もiconも名前も元の濃さで読める。
    ctx.fillStyle = gift ? cssToken("--sand-panel") : cssTokenAlpha("--line", 0.12);
    ctx.fillRect(x0, bodyTop, w, effectTop - bodyTop);
    if (gift) {
      const ratio = diamondRatio(segmentDiamonds(seg), maxDiamonds);
      const bar = Math.round((effectTop - bodyTop) * ratio);
      if (bar > 0) {
        ctx.fillStyle = cssTokenAlpha("--ramp", 0.55);
        ctx.fillRect(x0, effectTop - bar, w, bar);
      }
    }
    // 切れ目。montageの継ぎ目そのものなので、必ず1本引く。
    ctx.fillStyle = cssTokenAlpha("--line", 0.9);
    ctx.fillRect(x0, bodyTop, 1, effectTop - bodyTop);
    ctx.fillRect(x1 - 1, bodyTop, 1, effectTop - bodyTop);
    // NG(出力から外した)gift演出は打ち消しの斜線で「繋がれない」ことを出す(色は足さない)。
    if (seg.excluded) {
      ctx.strokeStyle = cssTokenAlpha("--ink", 0.55);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x0, effectTop);
      ctx.lineTo(x1, bodyTop);
      ctx.stroke();
    }
  });
  ctx.restore();

  // giftのiconと名前。**gift演出の面へ名前を書き込むのはやめた** —— gift演出の幅は6秒ぶんしか
  // 無く、入らない名前は出ないままだった。配信者動画と同じく、飛んだ位置へiconを置いて
  // そこから時刻へ線を落とす。
  drawTimelineGifts(ctx, { width, toX, top: bodyTop, bottom: effectTop });

  // 演出区間。ギフト演出は視聴者のclientが描くもので録画には映らない ―― ハイライトに
  // だけ在る差分なので、gift演出とは別のlaneに置く。
  let effectCount = 0;
  let outside = 0;
  ctx.save();
  ctx.fillStyle = cssTokenAlpha("--line", 0.14);
  ctx.fillRect(0, effectTop, width, MARKER_LANE_PX);
  segments.forEach((seg) => {
    effectSpans(seg).forEach(([s, e]) => {
      effectCount += 1;
      if (e < 0 || s > duration) {
        outside += 1;
        return;
      }
      ctx.fillStyle = cssTokenAlpha("--ink", 0.45);
      ctx.fillRect(toX(s), effectTop + 1, Math.max(1, toX(e) - toX(s)), MARKER_LANE_PX - 2);
    });
  });
  ctx.restore();
  if (!effectCount) $("cv-tl-note").textContent = "演出 0";
  else if (outside === effectCount) {
    $("cv-tl-note").textContent = `演出 ${fmtNum(effectCount)}（尺の外）`;
  } else $("cv-tl-note").textContent = `演出 ${fmtNum(effectCount)}`;

  // コマの帯。rulerの直上、本体の外に置く。
  if (stripLanePx() > 0) {
    drawStripLane(ctx, {
      left: 0, right: width, top: stripTop, bottom: bodyBottom, width,
      secondsAt: (x) => (x / width) * duration,
    });
    // gift演出の継ぎ目を帯へも落とす。**どの絵がどのgift演出の物か**が読めないと、切り替わりの
    // 秒を目で詰める用に敷いた絵が、ただの帯になる。
    ctx.fillStyle = cssTokenAlpha("--sand-panel", 0.85);
    segments.forEach((seg) => {
      const win = segmentWindow(seg);
      if (!Number.isFinite(win.start)) return;
      ctx.fillRect(toX(win.start), stripTop, 1, bodyBottom - stripTop);
    });
  }

  // 選んでいるgift演出の枠。**表で選んだ行が指しているのはこのgift演出である**ことを、配信者動画の
  // 「拡大窓がどこを見ているか」の枠と同じ描き方で出す。枠の中にだけ、映像の切り替わりと
  // 同じgift演出の他の人のgiftを出す。
  const current = currentSegment();
  if (current) {
    const win = segmentWindow(current);
    const s0 = toX(win.start);
    const s1 = toX(win.end);
    drawSegmentDetail(ctx, {
      seg: current, toX, top: bodyTop, bottom: effectTop, left: s0, right: s1,
    });
    ctx.strokeStyle = "rgba(29, 27, 22, 0.55)";
    ctx.lineWidth = 1;
    ctx.strokeRect(s0 + 0.5, bodyTop + 0.5, Math.max(2, s1 - s0) - 1, effectTop - bodyTop - 1);
  }

  // 切り出す範囲。**掴めるのはgift演出の窓ではなくこの区間の端**なので、配信者動画のIN/OUTと
  // 同じ帯・同じ緑赤・同じhandleで出す(2つの画面で掴み方が違うと手が覚え直しになる)。
  const cut = draggingCut() || editingCut();
  drawRangeLane(ctx, width, bodyBottom, toX,
                cut ? cut.start : null, cut ? cut.end : null);

  drawRuler(ctx, { width, bodyBottom, from: 0, to: duration, toX });

  // 再生位置。
  const video = $("cv-video");
  if (Number.isFinite(video.currentTime) && video.currentTime > 0) {
    drawPlayhead(ctx, toX(video.currentTime), bodyBottom);
  }
}

// 選んでいるgift演出の中だけに出す2つの物。**以前はgift演出±2秒だけを映す拡大軸が持っていた** ――
// 軸を1本にしたので(利用者の指定)、同じことをこのgift演出の枠の中で出す。60秒を横いっぱい
// (実測1200px前後)へ写した軸では1pxが0.05秒しか無く、6秒のgift演出は120px前後を占めるので、
// どちらもこの幅で読める。
//
//   ・映像が切り替わり終わる秒(頭)と、次のgiftへ切り替わり始める秒(尻)。**既定の窓の端は
//     ここに在る。** gift演出の端(音の境目)との間に挟まっているのが前後のgiftの場面と演出で、
//     その帯を見せないと、窓がgift演出の境目とずれている理由が読めない。
//   ・同じgift演出に載る**他の人のgiftの区間**。1つのgift演出に別人のgiftが複数入る(実測でgift 49件
//     のうち19件)ので、見えないまま詰めると他人のfileまで動かしたことに気付けない。
function drawSegmentDetail(ctx, { seg, toX, top, bottom, left, right }) {
  const height = bottom - top;
  const cut = editingCut();
  const low = Number(seg.start);
  const high = Number(seg.end);

  (seg.gifts || []).forEach((gift) => {
    if (cut && cut.gift && gift.id === cut.gift.id) return;
    const other = cutOf(gift);
    if (!other) return;
    ctx.fillStyle = cssTokenAlpha("--ink", 0.10);
    ctx.fillRect(toX(other.start), top,
                 Math.max(1, toX(other.end) - toX(other.start)), height);
  });

  const switchAt = num(seg.video_start);
  if (switchAt !== null && switchAt > low + SWITCH_MIN_SECONDS && switchAt < high) {
    const xs = toX(switchAt);
    ctx.fillStyle = cssTokenAlpha("--ink", 0.18);
    ctx.fillRect(left, top, xs - left, height);
    ctx.fillStyle = cssToken("--ink-muted");
    for (let y = top; y < bottom; y += 6) ctx.fillRect(xs - 1, y, 2, 3);
  }

  const switchTo = num(seg.video_end);
  if (switchTo !== null && switchTo < high - SWITCH_MIN_SECONDS && switchTo > low) {
    const xe = toX(switchTo);
    ctx.fillStyle = cssTokenAlpha("--ink", 0.18);
    ctx.fillRect(xe, top, right - xe, height);
    ctx.fillStyle = cssToken("--ink-muted");
    for (let y = top; y < bottom; y += 6) ctx.fillRect(xe - 1, y, 2, 3);
  }
}

// ===== 軸の操作 =====
//
// **配信者動画の seek bar と同じ手つきにする。** 上端のlaneで範囲を掴み(端はどの高さでも
// 掴める)、それ以外はclick/dragでその位置へ移る。hoverでその秒の絵が出る。
//
// **軸は1本だけである。** 以前はこの下にgift演出±2秒だけを映す拡大軸がもう1本在ったが、
// ハイライトは実測でほとんどが1分前後で、横いっぱいへ移した今の軸は1pxが0.05秒しか
// 無い —— 同じ物を2本並べる理由が無くなった(利用者の指定)。拡大軸だけが持っていた
// 「映像の切り替わり」と「同じgift演出に載る他の人のgift」は、選んでいるgift演出の中へ移した。

// 軸が映している範囲と、区間が出られる壁。開いていなければnull。
function barRange() {
  const duration = timelineDuration();
  if (!(duration > 0)) return null;
  const seg = currentSegment();
  return {
    from: 0,
    to: duration,
    // 区間はgift演出の外へは出せない(montageなので、外はまったく無関係な場面である)。
    low: seg ? Number(seg.start) : 0,
    high: seg ? Number(seg.end) : duration,
  };
}

// 秒⇔x。xはcanvasのcontent boxを基準にする(描画側もclientWidthを全幅として描く)。
function barGeometry(barId) {
  const range = barRange();
  const canvas = $(barId);
  if (!range || !canvas) return null;
  const rect = canvas.getBoundingClientRect();
  const width = canvas.clientWidth || rect.width;
  if (!(width > 0) || !(range.to > range.from)) return null;
  const span = range.to - range.from;
  return {
    ...range,
    canvas,
    rect,
    width,
    // barの左端からのpx。
    xOf: (seconds) => ((seconds - range.from) / span) * width,
    // pointerの位置が指す秒(軸の映す範囲で止める)。
    secondsAt: (clientX) => {
      const ratio = Math.min(1, Math.max(0,
        (clientX - rect.left - canvas.clientLeft) / width));
      return range.from + ratio * span;
    },
  };
}

// 区間の端が置ける秒。**壁の外へは出さない。**
function clampToSegment(geo, seconds) {
  return Math.max(geo.low, Math.min(geo.high, seconds));
}

// 何を掴んだか。端(in/out)は帯の全高で掴める —— 線は全高に描いてあるので、laneの中でしか
// 掴めないと「線の上を掴んだのにseekした」になる。上端laneの帯の中は範囲ごとの平行移動、
// それ以外はseek。**範囲の新規作成は無い** —— giftごとに区間は必ず在るので、作る操作より
// 「今在る範囲を動かす」方しか要らない。
function hitTestBar(barId, event) {
  const geo = barGeometry(barId);
  const cut = editingCut();
  if (!geo || !cut) return "seek";
  const x = event.clientX - geo.rect.left;
  const inLane = event.clientY - geo.rect.top <= RANGE_LANE_PX;
  const base = event.pointerType === "mouse" ? HANDLE_HIT_PX : HANDLE_HIT_TOUCH_PX;
  const handle = nearestHandle(x, geo.xOf, inLane ? base : base * HANDLE_HIT_BODY_RATIO,
                               cut.start, cut.end);
  if (handle) return handle;
  if (inLane && x > geo.xOf(cut.start) && x < geo.xOf(cut.end)) return "band";
  return "seek";
}

const CV_CURSORS = { seek: "pointer", in: "ew-resize", out: "ew-resize", band: "grab" };

// pointermoveは1 frameに何度も届く一方、出せる絵は1 frameに1枚しかない。届いた最後の
// 位置だけをframeの頭で処理する(掴めるbarは同時に1つなので溜め先も1つでよい)。
let barMoveEvent = null;
let barMoveBar = null;
let barMoveFrame = null;

function applyBarMove(barId, event) {
  const drag = state.barDrag;
  if (drag && drag.bar === barId) {
    dragBar(event);
  } else if (!drag) {
    $(barId).style.cursor = CV_CURSORS[hitTestBar(barId, event)];
  }
  showBarThumb(barId, event.clientX);
}

function scheduleBarMove(barId, event) {
  barMoveEvent = event;
  barMoveBar = barId;
  if (barMoveFrame !== null) return;
  barMoveFrame = requestAnimationFrame(() => {
    barMoveFrame = null;
    const latest = barMoveEvent;
    const bar = barMoveBar;
    barMoveEvent = null;
    barMoveBar = null;
    if (latest) applyBarMove(bar, latest);
  });
}

// 溜めてある位置を今すぐ反映する。dragの終わりは最後の位置まで入れてから確定させないと、
// 離す直前の詰めが1 frameぶん捨てられる。
function flushBarMove() {
  if (barMoveFrame !== null) {
    cancelAnimationFrame(barMoveFrame);
    barMoveFrame = null;
  }
  const event = barMoveEvent;
  const barId = barMoveBar;
  barMoveEvent = null;
  barMoveBar = null;
  if (event) applyBarMove(barId, event);
}

function cancelBarMove() {
  if (barMoveFrame !== null) {
    cancelAnimationFrame(barMoveFrame);
    barMoveFrame = null;
  }
  barMoveEvent = null;
  barMoveBar = null;
}

// drag中は掴んでいる端へ再生位置を追従させる。切り所を目で確かめながら詰められる。
function dragBar(event) {
  const drag = state.barDrag;
  const geo = barGeometry(drag.bar);
  if (!geo) return;
  const seconds = geo.secondsAt(event.clientX);
  if (drag.mode === "seek") {
    state.playUntil = null;
    seekTo(seconds);
    drawTimeline();
    return;
  }
  const at = clampToSegment(geo, seconds);
  if (drag.mode === "in") {
    drag.start = Math.min(at, drag.end);
  } else if (drag.mode === "out") {
    drag.end = Math.max(at, drag.start);
  } else if (drag.mode === "band") {
    // 尺を保ったまま平行移動する。両端がgift演出の外へ出ないよう壁で止める。
    const start = Math.max(geo.low, Math.min(geo.high - drag.length, at - drag.offset));
    drag.start = start;
    drag.end = start + drag.length;
  }
  state.playUntil = null;
  seekTo(drag.mode === "out" ? drag.end : drag.start);
  drawTimeline();
}

function bindBar(barId) {
  const canvas = $(barId);
  canvas.addEventListener("pointerdown", (event) => {
    const geo = barGeometry(barId);
    if (!geo) return;
    const mode = hitTestBar(barId, event);
    const cut = editingCut();
    canvas.setPointerCapture(event.pointerId);
    if (mode === "seek" || !cut) {
      state.barDrag = { bar: barId, mode: "seek" };
      // 手でどこかへ飛んだら、区間の終わりでの自動停止は解く ―― 見たい所へ移ったのに
      // 数秒で止まると、playerが壊れているように見える。
      state.playUntil = null;
      seekTo(geo.secondsAt(event.clientX));
      drawTimeline();
      return;
    }
    state.barDrag = {
      bar: barId,
      mode,
      segId: cut.seg.id,
      giftId: cut.gift ? cut.gift.id : null,
      start: cut.start,
      end: cut.end,
      length: cut.end - cut.start,
      offset: clampToSegment(geo, geo.secondsAt(event.clientX)) - cut.start,
    };
    event.preventDefault();
  });
  canvas.addEventListener("pointermove", (event) => scheduleBarMove(barId, event));
  canvas.addEventListener("pointerleave", () => {
    cancelBarMove();
    hideBarThumb();
  });
  const finish = async (event) => {
    flushBarMove();
    const drag = state.barDrag;
    state.barDrag = null;
    hideBarThumb();
    if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    if (!drag || drag.mode === "seek") return;
    const cut = editingCut();
    // 掴んでいる間に相手が入れ替わっていたら送らない(別のgiftの区間を上書きしてしまう)。
    if (!cut || cut.seg.id !== drag.segId
        || (cut.gift ? cut.gift.id : null) !== drag.giftId) {
      drawTimeline();
      return;
    }
    await saveCut(drag.start, drag.end, "区間");
  };
  canvas.addEventListener("pointerup", finish);
  canvas.addEventListener("pointercancel", (event) => {
    cancelBarMove();
    state.barDrag = null;
    hideBarThumb();
    if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    drawTimeline();
  });
}

// ===== seek barのサムネイル =====
//
// 配信者動画は録画1本ぶんのspriteを先に作って持つが、ハイライトにその口は無い。代わりに
// **1枚ずつ切ってcacheへ残す口**(``/api/highlights/{id}/frame``)を、秒を丸めて叩く ――
// 60秒のハイライトなら0.5秒刻みで120枚が上限で、2度目からはcacheが返す。
let thumbTimer = null;
let thumbWanted = null;

// hoverが指す秒。丸めるのは、通り道の秒をそのまま頼むとffmpegが何十回も起きるためである。
function thumbSecondsOf(seconds) {
  return Math.round(seconds / THUMB_STEP_SECONDS) * THUMB_STEP_SECONDS;
}

function thumbUrlAt(seconds) {
  const id = state.currentId;
  if (id === null || id === undefined) return null;
  return `/api/highlights/${id}/frame?at=${seconds.toFixed(3)}&w=${THUMB_WIDTH_PX}`;
}

function showBarThumb(barId, clientX) {
  const thumb = $("cv-thumb");
  const geo = barGeometry(barId);
  if (!thumb || !geo) {
    hideBarThumb();
    return;
  }
  const seconds = geo.secondsAt(clientX);
  const host = geo.canvas.parentElement;
  if (thumb.parentElement !== host) host.appendChild(thumb);
  const wrap = host.getBoundingClientRect();
  $("cv-thumb-time").textContent = fmtPos(seconds);
  thumb.classList.remove("hidden");
  // barの端で枠が外へ出ないよう、wrapperの中に収める。
  const left = Math.min(wrap.width - THUMB_WIDTH_PX,
                        Math.max(0, clientX - wrap.left - THUMB_WIDTH_PX / 2));
  thumb.style.left = `${left}px`;
  thumb.style.bottom = `${geo.rect.height + 4}px`;
  // 絵は手が止まってから頼む。素通りしただけの秒まで切らせない。
  const at = thumbSecondsOf(seconds);
  if (at === thumbWanted) return;
  thumbWanted = at;
  if (thumbTimer) clearTimeout(thumbTimer);
  thumbTimer = setTimeout(() => {
    thumbTimer = null;
    const url = thumbUrlAt(at);
    if (!url || thumbWanted !== at) return;
    // 取れなかった秒(尺の外・fileが無い)は404で終わる。絵を差し替えないだけにして、
    // 壊れた画像箱は置かない。
    $("cv-thumb-img").src = url;
  }, THUMB_DELAY_MS);
}

function hideBarThumb() {
  const thumb = $("cv-thumb");
  if (thumb) thumb.classList.add("hidden");
  thumbWanted = null;
  if (thumbTimer) clearTimeout(thumbTimer);
  thumbTimer = null;
}

function bindTimeline() {
  const video = $("cv-video");
  bindBar("cv-timeline");

  video.addEventListener("timeupdate", () => {
    // 区間だけの再生。終端を過ぎたら止める ―― 続けて次のgift演出(=無関係な場面)が流れると、
    // 今どのgiftを見ているのか分からなくなる。
    if (state.playUntil !== null && video.currentTime >= state.playUntil - PLAY_STOP_SLACK) {
      state.playUntil = null;
      video.pause();
    }
    drawTimeline();
    const duration = timelineDuration();
    $("cv-time").textContent =
      `${fmtDuration(video.currentTime)} / ${duration ? fmtDuration(duration) : "--:--:--"}`;
  });
  video.addEventListener("loadedmetadata", () => {
    drawTimeline();
    $("cv-time").textContent = `${fmtDuration(0)} / ${fmtDuration(video.duration)}`;
  });
  // ハイライトは録画ではないので、録画の実在をserverへ問い合わせる共通のbindVideoErrorは
  // 使えない。srcを外したとき(別の本へ移る時)もerrorは飛ぶので、空srcは異常としない。
  video.addEventListener("error", () => {
    if (!video.getAttribute("src")) return;
    setFormMessage($("cv-play-status"), "再生できません", true);
  });
}

// ===== 区間の手直し =====

function currentSegment() {
  if (!state.current || state.currentSegId === null) return null;
  return state.current.segments.find((s) => s.id === state.currentSegId) || null;
}

// 手直しの相手になっているgift。**「そのgift演出のgift」ではなく「そのgift」**である ――
// gift演出1つが複数のgiftを持つので、gift演出だけを指すと直す相手が決まらない。
function currentGift() {
  const seg = currentSegment();
  if (!seg || state.currentGiftId === null) return null;
  return (seg.gifts || []).find((g) => g.id === state.currentGiftId) || null;
}

// 触っている相手を手放す。**区間の受け皿は時間軸だけ**なので、畳む枠はもう無い ――
// 残っているのは「誰のどのgiftを触っているか」という状態だけである。
function clearEditTarget() {
  state.currentSegId = null;
  state.currentGiftId = null;
  setCutUndo(null);
  // 相手が居なくなったので、溜めた刻みは行き先を失う。呼ぶ側(selectCoverAt)が先に
  // 送り終えているので、ここに残っているのは送れなかった分だけである。
  state.cutPending = null;
  if (state.cutTimer) clearTimeout(state.cutTimer);
  state.cutTimer = null;
}

// 手直しの相手になっている区間。**giftを選んでいればそのgiftの窓**で、giftを1件も持たない
// gift演出(実測で10個中3個)でだけgift演出の窓になる。この2つを1つの関数に畳んでおかないと、読む所
// ごとにどちらを見るかの判断が散らばり、いつか片方だけがgift演出の窓のまま残る。
function editingCut() {
  const seg = currentSegment();
  if (!seg) return null;
  const gift = currentGift();
  const cut = cutOf(gift);
  const base = cut
    ? { ...cut, gift, seg, own: Boolean(gift.cut_own) }
    : { start: Number(seg.start), end: Number(seg.end), gift: null, seg, own: false };
  // まだ送っていない刻みが在れば、そちらを本当の値として扱う。**画面は打った瞬間に
  // その値になる** —— 送るのを待ってから描くと、連打したときに数字が遅れて追いかけてきて、
  // 今どこに居るのかが読めない。
  const pending = state.cutPending;
  if (pending && pending.segId === seg.id
      && pending.giftId === (gift ? gift.id : null)) {
    return { ...base, start: pending.start, end: pending.end, own: true };
  }
  return base;
}

// 変更はその場でPATCHへ送り、結末を必ず出す。送った先で何が起きたかを画面が黙ると、
// 直したつもりの値が残っていない、という壊れ方を誰も気付けない。
async function patchSegment(patch, label) {
  const seg = currentSegment();
  if (!seg || !state.current) return false;
  const hid = state.current.highlight.id;
  const before = { start: Number(seg.start), end: Number(seg.end) };
  let updated;
  try {
    updated = await apiSend("PATCH", `/api/highlights/${hid}/segments/${seg.id}`, patch);
  } catch (err) {
    showError(err, label);
    // 送れなかったのだから、画面もserverの値のままに戻す。時間軸はstateから描くので、
    // 描き直すだけで元の範囲へ戻る(送る前の値を画面が握り続けない)。
    drawTimeline();
    return false;
  }
  applySegment(seg.id, updated, patch);
  showToast(`${label}を保存しました。`);
  const again = currentSegment();
  if (again) syncCoverageSegment(again, before);
  drawTimeline();
  return true;
}

// 応答が返したgift演出で置き換える。**gift列は丸ごと差し替える** ―― 送った内容を当てて
// 済ませると、giftを1件足した時に画面のgiftsが古いまま残る(3つの口はどれも
// giftを添えたgift演出まるごとを返す)。
function applySegment(segId, updated, patch) {
  const next = updated && updated.segment;
  const list = state.current.segments;
  const at = list.findIndex((s) => s.id === segId);
  if (at < 0) return;
  if (next) list[at] = next;
  // Serverがgift演出を返さない版では、送った内容だけを当てる。giftの数が変わる操作では
  // 当てられないので、その場合は読み直す(推測でgiftの列を作らない)。
  else if (patch) list[at] = Object.assign({}, list[at], patch);
}

// 検証の表の行にも同じ結果を映す。**引き直さない** ―― 週ぜんたいを引き直すと、
// 1件NGを付けるたびに表が組み直されて、見ていた場所も選択も飛ぶ。
//
// ``at``(そのgiftがハイライトの中で何秒目か)はgift演出の頭からの相対で決まるので、頭を
// 動かした分だけ一緒に動く(store.highlights.gift_position と同じ写像)。ここで動かさないと、
// 区間を詰めた後の飛び先が古い位置のままになる。
function syncCoverageSegment(seg, before) {
  const items = (state.cvData && state.cvData.items) || [];
  const delta = Number(seg.start) - (before ? before.start : Number(seg.start));
  // gift行は**行のid(gift_row_id)**で結ぶ。俯瞰の当たりが名乗るのはこのidで、gift演出が持つ
  // giftの ``id`` と同じ物を指す(選ぶときの引き当ても同じ鍵を使っている)。
  const byRow = new Map((seg.gifts || []).map((gift) => [gift.id, gift]));
  items.forEach((gift) => {
    (gift.hits || []).forEach((hit) => {
      if (hit.segment_id !== seg.id) return;
      hit.segment_start = Number(seg.start);
      hit.segment_end = Number(seg.end);
      if (delta && num(hit.at) !== null) hit.at = Number(hit.at) + delta;
      hit.approved = Boolean(seg.approved);
      hit.edited = Boolean(seg.edited);
      hit.segment_excluded = Boolean(seg.excluded);
      hit.confidence = seg.confidence;
      const row = byRow.get(hit.gift_row_id);
      if (row) {
        // **区間とNGはgiftごと**である。gift演出の値で上書きすると、同じgift演出の3人が同じ
        // 区間・同じNGとして並び、gift単位で詰めた意味が表から消える。
        hit.cut_start = num(row.cut_start);
        hit.cut_end = num(row.cut_end);
        hit.cut_own = Boolean(row.cut_own);
        hit.gift_excluded = Boolean(row.excluded);
        // 使う1本の指定もgiftごとである。同じgiftの他の当たりから落とすのは
        // ``markChosenHit`` の仕事で、ここは開いているgift演出の行だけを映す。
        hit.chosen = Boolean(row.chosen);
      }
      hit.excluded = Boolean(seg.excluded) || Boolean(hit.gift_excluded);
    });
  });
  renderCoverage({ keepScroll: true });
}

// gift 1件への手直し。**gift演出ごとの操作とは別の口**である ―― gift演出ごと外すと同じgift演出の
// 他のgiftまで巻き添えになるので、口も画面も分けてある。
async function patchGift(giftRowId, patch, label, opts = {}) {
  const seg = currentSegment();
  if (!seg || !state.current) return false;
  const hid = state.current.highlight.id;
  let updated;
  try {
    updated = await apiSend(
      "PATCH", `/api/highlights/${hid}/segments/${seg.id}/gifts/${giftRowId}`, patch);
  } catch (err) {
    showError(err, label);
    drawTimeline();
    return false;
  }
  applySegment(seg.id, updated, null);
  // 畳んだ行は同じ操作をgiftの数だけ送る。**結末は1回だけ名乗る** ―― 4件の連投で
  // 「保存しました」が4回積み上がると、何件に効いたのかがかえって読めない。
  if (!opts.quiet) showToast(`${label}を保存しました。`);
  const again = currentSegment();
  if (again) {
    // 表にも映す。**gift 1件の変更でも表は動く** ―― 区間もNGもgiftごとの値なので、
    // gift演出の操作だけを表へ反映していた頃は、詰めた区間が表に出ないままだった。
    syncCoverageSegment(again, null);
  }
  drawTimeline();
  return true;
}

// 区間を1つ書く。**gift 1件の窓を動かす**(giftを持たないgift演出でだけgift演出の窓を動かす)。
//
// 送る前にgift演出の中へ収まっていることを確かめる。Serverも同じ検算をして400を返すが、
// キーの連打で1回ずつ往復させるより、画面で止めた方が速く、理由もその場で読める。
// **黙って丸めない** ―― 丸めると打った値と切られる場所が食い違い、しかも数字は出る。
async function saveCut(start, end, label) {
  const cut = editingCut();
  if (!cut) return false;
  const seg = cut.seg;
  if (!cutFits(seg, start, end)) return false;
  const low = Number(seg.start);
  const high = Number(seg.end);
  // 端ちょうどの丸め誤差ぶんだけ内側へ寄せる。**外へ出た値を直すのではない**(それは
  // 上で断っている) —— 画面がgift演出の端そのものを送ったときに、浮動小数の桁で弾かれない
  // ようにするためである。
  const fixed = { start: round3(Math.min(Math.max(start, low), high)),
                  end: round3(Math.min(Math.max(end, low), high)) };
  rememberCut(cut);
  state.cutPending = null;
  if (state.cutTimer) clearTimeout(state.cutTimer);
  state.cutTimer = null;
  if (!cut.gift) return patchSegment({ start: fixed.start, end: fixed.end }, label);
  return patchGift(cut.gift.id,
    { cut_start: fixed.start, cut_end: fixed.end }, label);
}

// 区間を1つだけ刻んで動かす(頭か尻か)。もう片方は今の値のまま。
//
// **打鍵ごとにPATCHは投げない。** 0.25秒ずつ20回叩けば20往復になり、途中の値が全部DBを
// 通り、結末の名乗り(toast)も20枚積み上がる。打った瞬間に画面だけ動かし、手が止まって
// から1回だけ送る。
function nudgeCut(which, delta) {
  const cut = editingCut();
  if (!cut) return;
  const start = round3(which === "start" ? cut.start + delta : cut.start);
  const end = round3(which === "end" ? cut.end + delta : cut.end);
  if (!cutFits(cut.seg, start, end)) return;
  // 取り消しの控えは**連打の1手目でだけ**採る。1打ごとに上書きすると、Zが1回ぶんしか
  // 戻らず、連打の前の状態へは二度と戻れない。
  if (!state.cutPending) rememberCut(cut);
  if (state.cutTimer) clearTimeout(state.cutTimer);
  state.cutPending = { segId: cut.seg.id, giftId: cut.gift ? cut.gift.id : null,
                       start, end };
  // 打った瞬間に映るのは時間軸の帯である(区間の受け皿はそこだけになった)。
  drawTimeline();
  // **動かした端の絵をその場で出す。** 数字と帯だけが動いて映像が前のままだと、
  // 0.25秒詰めた結果が「切れて良い場面か」を目で確かめられない ―― 詰める操作は
  // 端の絵を見るための操作なので、頭を動かしたら頭、尻を動かしたら尻へ飛ぶ。
  // **再生は始めない。** 端を1つ見るための移動で、ここから流したい訳ではない。
  // 区間再生の見張りが載っている最中だけは終端を新しい値へ差し替える ―― 消すと
  // 続けて次のgift演出(=無関係な場面)まで流れ、古い値のままだと動かす前の秒で止まる。
  seekTo(which === "start" ? start : end,
         { until: state.playUntil === null ? null : end });
  state.cutTimer = setTimeout(flushCut, CUT_SEND_DELAY_MS);
}

// 溜めた刻みを1回だけ送る。
async function flushCut() {
  const pending = state.cutPending;
  if (!pending) return false;
  if (state.cutTimer) clearTimeout(state.cutTimer);
  state.cutTimer = null;
  state.cutPending = null;
  const seg = currentSegment();
  if (!seg || seg.id !== pending.segId) return false;
  if (!pending.giftId) {
    return patchSegment({ start: pending.start, end: pending.end }, "区間");
  }
  return patchGift(pending.giftId,
    { cut_start: pending.start, cut_end: pending.end }, "区間");
}

// 区間がgift演出の中に収まっているか。収まらなければ理由を出して偽を返す。
function cutFits(seg, start, end) {
  const low = Number(seg.start);
  const high = Number(seg.end);
  if (!(end - start >= MIN_CUT_SECONDS)) {
    showToast(`区間は ${MIN_CUT_SECONDS}秒 より短くできません。`, "error", { title: "区間" });
    return false;
  }
  if (start < low - CUT_EPSILON || end > high + CUT_EPSILON) {
    showToast(`区間は ${fmtPos(low)}〜${fmtPos(high)} の中へ`, "error", { title: "区間" });
    return false;
  }
  return true;
}

// 直前の値を1手ぶん覚える。Serverには機械が出した窓へ戻る道が無い(端を動かした時点で
// 上書きされる)ので、取り消しは画面が持つしかない。
function rememberCut(cut) {
  setCutUndo({ segId: cut.seg.id, giftId: cut.gift ? cut.gift.id : null,
               start: cut.start, end: cut.end, own: cut.own });
}

// 取り消せる1手はここでだけ書き換える。1箇所に畳んでおかないと、どこかの経路で
// 「戻す先が残っているつもりで何も戻らない」状態が作れる。
function setCutUndo(value) {
  state.cutUndo = value;
}

// **自動の範囲の端を文章で名乗るのはやめた**(利用者の指定)。映像が切り替わり終わる秒は
// 時間軸の点線が出しており、同じことを文で言い直していた。

// 直前の区間の変更を1手だけ戻す。**戻せるのは1手** ―― 履歴を積むと「どこまで戻ったか」を
// 画面が名乗れなくなり、押した人が今どの状態に居るのか分からなくなる。
async function undoCut() {
  const undo = state.cutUndo;
  if (!undo) {
    showToast("戻せる区間の変更がありません。", "error", { title: "区間" });
    return;
  }
  // まだ送っていない刻みは**送らずに捨てる**。戻す操作なので、送ってから戻すと往復が
  // 1回増えるだけで、途中の値がDBを通る。
  state.cutPending = null;
  if (state.cutTimer) clearTimeout(state.cutTimer);
  state.cutTimer = null;
  if (state.currentSegId !== undo.segId || state.currentGiftId !== undo.giftId) {
    showToast("別の行を選んでいます",
      "error", { title: "区間" });
    return;
  }
  setCutUndo(null);
  if (!undo.giftId) {
    await patchSegment({ start: undo.start, end: undo.end }, "区間を戻す");
    return;
  }
  if (!undo.own) {
    await patchGift(undo.giftId, { cut_clear: true }, "区間を戻す");
    return;
  }
  await patchGift(undo.giftId,
    { cut_start: round3(undo.start), cut_end: round3(undo.end) }, "区間を戻す");
}

// NG(出力から外す)。**外れるのはこのgift 1件だけ**である ―― 1つのgift演出に別人のgiftが
// 複数入るので(実測でgift 49件のうち19件が、別のgifterと同じgift演出に載っている)、gift演出ごと
// 外すと押した覚えのない人の見せ場まで消える。gift演出ごとは :func:`toggleNgSegment`。
// 台帳からは消さない ―― 消すと、次の照合で同じ誤りが戻ったときに「一度人が否定した」と
// いう記録まで消える。
async function toggleNg() {
  const seg = currentSegment();
  if (!seg) return;
  const gift = currentGift();
  if (!gift) {
    // giftを持たないgift演出。外す相手がgiftではないので、演出ごとの操作へ落とす。
    await toggleNgSegment();
    return;
  }
  const excluded = !gift.excluded;
  const label = gift.excluded ? "NGの取り消し" : "このgiftをNG";
  // 畳んだ連投は**中のgiftを全部**まとめて外す。1つの演出なので、中の1件だけを残すと、
  // 次の照合で主が入れ替わったときにその1件が出力へ戻る。畳んだ行は同じgift演出の上に
  // 載っているので、相手はどれもこのsegmentのgift行である。
  const ids = ngRowIds(gift);
  for (let i = 0; i < ids.length; i += 1) {
    // 順に送る。並行に投げるとPATCHの応答が互いのgift列を上書きし合う。
    // eslint-disable-next-line no-await-in-loop
    const ok = await patchGift(ids[i], { excluded }, label,
                               { quiet: i < ids.length - 1 });
    if (!ok) return;
  }
}

// NGの相手になるgift行のid。畳んでいない行は選んでいる1件、畳んだ行は中の全件。
function ngRowIds(gift) {
  const row = state.cvRows[state.cvAt];
  if (!row || comboSize(row) < 2) return [gift.id];
  const ids = comboItems(row)
    .map((item) => num((coverHits(item)[0] || {}).gift_row_id))
    .filter((id) => id !== null);
  return ids.length ? ids : [gift.id];
}

// gift演出ごと外す。**同じgift演出の他の人のgiftも一緒に外れる**ので、2件以上載っているときは
// 誰が巻き添えになるのかを名前で挙げてから訊く。
async function toggleNgSegment() {
  const seg = currentSegment();
  if (!seg) return;
  const gifts = seg.gifts || [];
  if (!seg.excluded && gifts.length > 1) {
    const names = [...new Set(gifts.map((g) => g.user_nickname || g.user_unique_id || "—"))];
    if (!window.confirm(`このgift演出には ${fmtNum(gifts.length)}件のgiftが載っています`
      + `（${names.join(" / ")}）。全部まとめて出力から外しますか？`)) return;
  }
  await patchSegment({ excluded: !seg.excluded },
    seg.excluded ? "gift演出ごとのNGの取り消し" : "gift演出ごとNG");
}

// ===== 検証: 週のgift × ハイライト =====

// 配信者の選択肢は台帳に居る配信者から組む。走査していない配信者はハイライトを持たないので
// 突き合わせる相手が無い。
function renderCoverStreamers() {
  const select = $("cv-streamer");
  const want = select.value;
  const names = [...new Set(state.highlights.map((h) => h.unique_id).filter(Boolean))].sort();
  select.innerHTML = "";
  names.forEach((name) => {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    select.appendChild(option);
  });
  select.value = names.includes(want) ? want : (names[0] || "");
  select.disabled = names.length <= 1;
  return select.value;
}

function renderCoverPicks() {
  const streamer = renderCoverStreamers();
  if (streamer && streamer !== state.cvStreamer) {
    state.cvStreamer = streamer;
    state.cvWeek = "";
    loadCoverage();
  }
}

// 突き合わせはServerが返す。画面は引くだけで、gift一覧とハイライトを自分で突き合わせない。
// **週の選択肢もこの応答が持っている**(weeks / prev_week / next_week / start_label /
// end_label / post_min)ので、週を別の口から引き直さない ―― 2つの口から引くと、棚が
// 名乗る週と表の中身が別々に動く余地ができる。
async function loadCoverage() {
  const streamer = $("cv-streamer").value;
  if (!streamer) {
    state.cvData = null;
    setListMessage($("cv-empty"), "");
    clearCoverPanels();
    return;
  }
  const seq = (state.cvSeq += 1);
  setListState($("cv-empty"), "loading");
  const params = new URLSearchParams({ streamer });
  if (state.cvWeek) params.set("week", state.cvWeek);
  const min = num($("cv-min").value);
  if (min !== null) params.set("min_diamonds", String(min));
  let data;
  try {
    data = await apiSend("GET", `/api/highlights/coverage?${params.toString()}`);
  } catch (err) {
    if (seq !== state.cvSeq) return;
    // 取得できなかったものを0件として描かない ―― この面は「無いgift」を読む面なので、
    // 失敗を空の表として出すと「全部ハイライトに無い」と読める。
    state.cvData = null;
    state.cvRows = [];
    state.cvAt = -1;
    state.cvKey = null;
    $("cv-rows").innerHTML = "";
    clearCoverPanels();
    setListState($("cv-empty"), "failed", err);
    showError(err, "週のgiftとハイライトの対応");
    return;
  }
  if (seq !== state.cvSeq) return;
  state.cvData = data;
  state.cvWeek = data.week || "";
  // 別の週・別の配信者の行が来た。前に選んでいたgiftは居ないので選択を捨てる ――
  // 残すと、同じevent_idが偶然在ったときに無関係な行が選ばれたように見える。
  state.cvAt = -1;
  state.cvKey = null;
  renderCoverWeeks();
  renderCoverStats();
  renderCoverage();
}

// 週の名乗り・俯瞰・要注意を空にする。前の週や前の配信者の数字を残さない ―― 別の週の
// ものとして読まれる。**週の選択そのものも落とす** ―― 引けなかったとき棚だけが前の
// 配信者の週を名乗り続けると、その週を見ているように読める。
function clearCoverPanels() {
  const week = $("cv-week");
  week.innerHTML = "";
  week.disabled = true;
  $("cv-week-prev").disabled = true;
  $("cv-week-next").disabled = true;
  $("cv-stats").innerHTML = "";
  $("cv-note").textContent = "";
  setFormMessage($("cv-week-range"), "", false);
}

function renderCoverWeeks() {
  const data = state.cvData;
  const select = $("cv-week");
  select.innerHTML = "";
  if (!data || !(data.weeks || []).length) {
    $("cv-week-prev").disabled = true;
    $("cv-week-next").disabled = true;
    select.disabled = true;
    setFormMessage($("cv-week-range"), data ? "記録なし" : "", false);
    return;
  }
  select.disabled = false;
  data.weeks.forEach((w) => {
    const option = document.createElement("option");
    option.value = w.key;
    option.textContent = `${w.label || w.key}　${fmtCompact(w.diamonds)}`;
    select.appendChild(option);
  });
  select.value = data.week;
  $("cv-week-prev").disabled = !data.prev_week;
  $("cv-week-next").disabled = !data.next_week;
  // 名乗りはserverが組んだ文字列をそのまま出す。日付から組み直すと時刻が落ち、
  // 土曜の朝(0〜7時)がどちらの週とも読める名乗りになる。
  setFormMessage($("cv-week-range"),
    data.start_label ? `${data.start_label} 〜 ${data.end_label}` : "", false);
}

function stepCoverWeek(step) {
  const data = state.cvData;
  if (!data) return;
  const next = step < 0 ? data.prev_week : data.next_week;
  if (!next) return;
  state.cvWeek = next;
  loadCoverage();
}

// この週の俯瞰。割合はServerが返した合計から出す(行を数え直さない ―― 絞り込みを掛けた
// 行数で割ると、絞るたびに割合が動いて意味を失う)。
//
// **既定では畳んである。** 13行の数字を左の縦paneへ常時置いていたために、表と動画から
// 幅を奪ったうえ、何を読む面なのか分からなくなっていた(利用者の指摘)。開いたときは
// 帯として横へ流す ―― 縦に積むと、開くたびに表が画面の外へ押し出される。
function renderCoverStats() {
  const box = $("cv-stats");
  box.innerHTML = "";
  const data = state.cvData;
  const t = (data && data.totals) || null;
  if (!t) return;
  const pct = (part, whole) => {
    const a = num(part);
    const b = num(whole);
    if (a === null || b === null || b <= 0) return "";
    return `（${((a / b) * 100).toFixed(1)}%）`;
  };
  const count = (value, unit) => (num(value) === null ? "—" : `${fmtNum(value)}${unit}`);
  const post = num(data.post_min);
  // **「うち◯◯」を独立した行にしない。** 帯として横へ流すと、親の行と離れた場所へ
  // 置かれて何の内訳なのか読めなくなる(縦に積んでいた頃は上下の並びが文脈だった)。
  // 1項目 = 「全体（うち…）」の1組にして、どこへ流れても単独で読めるようにする。
  const rows = [
    ["週のgift", count(t.gifts, "件"),
      `→ ${count(t.matched, "件")}${pct(t.matched, t.gifts)}`],
    // どこまで見たか。**母数は並べた行**で、Serverが数えた値をそのまま出す
    // (絞り込んだ後の行数で割ると、絞るたびに割合が動いて意味を失う)。
    ["確認済み", count(t.checked, "件"),
      num(t.checked) === null || num(t.gifts) === null
        ? "" : `未確認 ${count(t.gifts - t.checked, "件")}`],
    ["週の🪙", num(t.diamonds) === null ? "—" : fmtNum(t.diamonds),
      `→ ${num(t.matched_diamonds) === null ? "—" : fmtNum(t.matched_diamonds)}`
      + `${pct(t.matched_diamonds, t.diamonds)}`],
    // 演出を持つ階層のgiftが、どれだけハイライトへ入ったか。**この差が「演出があるのに
    // 出てこないgift」の件数**で、人の一番の関心事である。coinを代理指標にしたServerの
    // 推定なので、「全画面演出がある」の意味ではない(99🪙階層の演出は小さな章や帽子)。
    ["演出を持つ階層", count(t.effect_expected, "件"),
      `→ ${count(t.effect_expected_matched, "件")}`
      + `${pct(t.effect_expected_matched, t.effect_expected)}`],
    ["gifter", count(t.gifters, "人"), `→ file ${count(t.target_gifters, "人")}`],
    ["この週のハイライト", count(t.highlights, "本"), ""],
    // 演出の音が配信の音を覆うと票が立たない区間が出る(実測で60.8秒のうち5.7秒)ので、
    // gift未同定が0にならないのが普通である。異常として名乗らない。
    ["gift演出", count(t.segments, "件"), `未同定 ${count(t.unidentified, "件")}`],
    // 誰のfileが作られる週なのか。出力tabと同じ規則(Serverのpost_min)で、画面は数字を
    // 持たない。**この表はこの下限で絞ってある** ―― 届かない人のgiftはServerが並べない
    // ので、外れた件数をここで名乗る(黙って消すと、人はまず数を疑う)。
    ["週合計の下限", post === null ? "—" : `🪙${fmtNum(post)}`,
      num(t.offtarget) === null ? "" : `外したgift ${count(t.offtarget, "件")}`],
  ];
  rows.forEach(([label, value, note]) => {
    const line = document.createElement("div");
    line.className = "st-stat";
    const l = document.createElement("span");
    l.className = "st-stat-l";
    l.textContent = label;
    const v = document.createElement("span");
    v.className = "st-stat-v";
    v.textContent = value;
    line.append(l, v);
    if (note) {
      const n = document.createElement("span");
      n.className = "st-stat-n";
      n.textContent = `（${note}）`;
      line.appendChild(n);
    }
    box.appendChild(line);
  });
}

// そのgiftが当たった先。**先頭の1件**を行の代表にする(複数のときは印で名乗る)。
function coverHits(gift) {
  return (gift && gift.hits) || [];
}

// 言い切れていない当たりを持つか。位置がずれている可能性がある行で、**別人のgiftが
// 別人のfileへ入る事故はここから始まる。**
function coverRisky(gift) {
  const hits = coverHits(gift);
  return hits.length > 0 && !hits.every((h) => isSure(h.confidence));
}

// NG(出力から外した)当たりを持つか。
function coverNg(gift) {
  return coverHits(gift).some((h) => h.excluded);
}

// 「この行は見た」の印。**gift 1件ごと**で、gift演出の ``approved`` には相乗りさせない ――
// gift演出を持たない行(どのハイライトにも出ていないgift)にこそ印が要る。そこがこの面の
// 一番の用途で、印を残せる行と残せない行に分かれると「どこまで見たか」が残らない。
//
// **送れた時だけ画面を動かす。** 付いたように見えて保存されていない印は、次に開いた時に
// 黙って消える(録画の確認状態と同じ約束)。**週ぜんたいは引き直さない**(NGと同じ理由 ――
// 1件ごとに表が組み直されると、見ていた場所も選択も飛ぶ)。
//
// 送るidをlistにしてあるのは、1行が複数のeventを畳む形になっても口を増やさないため
// である(1件ずつ往復させると、途中で失敗した行が「半分だけ確認済み」になる)。
//
// **送れたかどうかを返す。** Enter(印を付けて次へ)は送れた時だけ行を送るので、呼ぶ側が
// 結末を知れないと、印の付いていない行を「見た」として画面から流してしまう。
async function setCoverChecked(gift, next) {
  if (!gift) return false;
  const want = Boolean(next);
  // 畳んだ連投は中の全件へまとめて送る。1件ずつ往復させると、途中で失敗した行が
  // 「半分だけ確認済み」になり、checkboxで表せない状態ができる。
  const ids = comboItems(gift).map((item) => item.event_id);
  try {
    await apiSend("POST", "/api/highlights/coverage/checks",
                  { gift_event_ids: ids, checked: want });
  } catch (err) {
    showError(err, want ? "確認済みの記録" : "確認済みの取り消し");
    // 送れなかったのだから、画面もserverの値のままに戻す(checkboxは組み直しで戻る)。
    renderCoverage({ keepScroll: true });
    return;
  }
  // 印はgift event 1件ごとなので、畳んだ行では中の全件を動かす(次の描き直しで
  // 畳んだ行の checkbox はそこから組み直される)。
  let moved = 0;
  comboItems(gift).forEach((item) => {
    if (Boolean(item.checked) !== want) moved += want ? 1 : -1;
    item.checked = want;
  });
  gift.checked = want;
  // 集計の確認済みもその場で動かす。Serverが返した合計を持ったままだと、開いている間
  // だけ数字が古くなる(母数は並べた行ではなくgift eventなので、増減は動いた件数ぶん)。
  const totals = state.cvData && state.cvData.totals;
  if (totals && num(totals.checked) !== null) totals.checked += moved;
  renderCoverStats();
  const at = state.cvAt;
  renderCoverage({ keepScroll: true });
  // 絞り込みが「未確認」のときは、印を付けた行がその場で表から外れる。**同じ位置の行を
  // 選び直す** ―― 選択が外れたままだと、次の↑↓が先頭へ飛んで見ていた場所が判らなくなる。
  if (at >= 0 && state.cvAt < 0 && state.cvRows.length) {
    await selectCoverAt(Math.min(at, state.cvRows.length - 1), { play: false });
  }
  return true;
}

// 確認済みにして次のgiftを観る(Enter)。**上から順に潰す面の主keyである** ―― 印(A)と
// 送り(↓)を毎行ぶん交互に叩くと、数百件では打鍵が倍になり、どちらかを叩き忘れた行が
// 「見たのに印が無い」「印は在るのに見ていない」として残る。
//
// **印は必ず付ける側へ倒す**(Aのような切り替えにしない)。送りながら押すkeyが、既に印の
// 在る行で印を落とすと、通り過ぎた後ろで「どこまで見たか」が静かに壊れる。
//
// **再生は自動再生の設定に依らない。** Enterは「見た、次を観る」と言い切っている操作で、
// 送るだけの↑↓とはそこが違う(自動再生を切るのは「行を送っても勝手に流すな」という
// 指定であって、観るための操作まで止める指定ではない)。
async function checkAndAdvance(gift) {
  if (!gift) return;
  const key = gift.event_id;
  const at = state.cvAt;
  // **印が送れた時だけ送る。** 送れていない行を置いて次へ移ると、印の無い行が「見た」
  // として画面から流れ、次に開いた時に黙って戻ってくる。
  if (!(await setCoverChecked(gift, true))) return;
  // 絞り込みが「未確認」のときは、印を付けた行がその場で表から抜ける ―― 抜けた後の
  // **同じ位置が既に次のgift**なので、そこから更に1つ送ると1件飛ばす。
  const now = state.cvRows.findIndex((row) => row.event_id === key);
  const next = now < 0 ? Math.min(at, state.cvRows.length - 1) : now + 1;
  await selectCoverAt(next, { play: true });
}

// 絞り込みも並べ替えも、返ってきた行の性質で行うだけ。突き合わせの再計算はしない。
function coverRows() {
  const items = (state.cvData && state.cvData.items) || [];
  const mode = $("cv-filter").value;
  const rows = items.filter((g) => {
    const seen = coverHits(g).length;
    if (mode === "missing") return seen === 0;
    if (mode === "multi") return seen > 1;
    if (mode === "risk") return coverRisky(g);
    if (mode === "ng") return coverNg(g);
    // **未確認。** 数百件を上から潰していく面なので、次に見る行だけを出せないと、
    // 開き直すたびに済んだ行を読み飛ばすところから始まる。
    if (mode === "unchecked") return !g.checked;
    return true;
  });
  const by = coverOrder($("cv-order").value);
  // **並べる → 畳む → もう一度並べる。** 畳むには同じ塊が隣り合っている必要があるので
  // 先に並べ、畳んだ行の🪙は合計になるので並べ直す ―― 一度きりだと、300🪙×3を畳んだ
  // 900🪙の行が699🪙の行の下に残り、「高額順」の名乗りが嘘になる。
  return foldCombos([...rows].sort(by)).sort(by);
}

// 並べ方。**畳む前と後で同じ物を使う**ので、比べ方は1箇所に置く。
function coverOrder(order) {
  if (order === "time") return (a, b) => (num(a.time) || 0) - (num(b.time) || 0);
  // Gifterごと。**同じ人のgiftをひと塊にする**並びで、塊そのものは週合計の多い順に置く
  // ―― 1人ぶんを続けて確かめるときは、誰から見るかが週合計で決まる。塊の中は高額順。
  if (order === "gifter") {
    return (a, b) => (num(b.week_diamonds) || 0) - (num(a.week_diamonds) || 0)
      || String(a.identity_key || "").localeCompare(String(b.identity_key || ""))
      || (num(b.diamonds) || 0) - (num(a.diamonds) || 0)
      || (num(a.time) || 0) - (num(b.time) || 0);
  }
  // Serverが既に高額順で返すが、絞り込みの後も同じ順であることを画面側で保証する。
  return (a, b) => (num(b.diamonds) || 0) - (num(a.diamonds) || 0)
    || (num(a.time) || 0) - (num(b.time) || 0);
}

// 動画をどこへ飛ばすか。``at`` は**そのgiftがハイライトの中で何秒目か**で、gift演出の頭
// (``segment_start``)とは別の値である ―― giftはgift演出の頭に在るとは限らない(実測で1.2秒
// 後ろ)。録画に当たっていないgift演出ではServerが ``at`` を返さないので、そのときだけgift演出の
// 頭へ落とす。**その判断は読む側がする**ものとしてServerがnullを返している。
function hitSeekAt(hit) {
  const at = num(hit.at);
  return at === null ? num(hit.segment_start) : at;
}

// 区間まで見た飛び先。**人が詰めた範囲が在れば、その頭から観せる。**
//
// giftの位置は範囲を詰めても動かない(動くのはgift演出の頭を動かした時だけ)ので、giftの位置
// だけで飛ぶと**詰めた後の再生が範囲に追従しない** —— 頭を後ろへ詰めれば範囲の外から流れ、
// 範囲ごとgiftより手前へ動かすと、飛び先がもう終端を過ぎているので押した瞬間に止まる
// (何も再生されない)。詰める操作の目的は「出力に入る範囲そのものを観る」ことなので、
// 自分の窓を持った行は範囲の頭を飛び先にする。
//
// 触っていない行(Serverの窓=gift演出の窓)は今までどおりgiftの位置である。gift演出の窓はgiftの
// 6秒手前から始まるので、頭から流すと演出が立ち上がるまで何も映らない時間が続く。
function cutSeekAt(hit, cut) {
  const at = hitSeekAt(hit);
  if (!cut) return at;
  if (cut.own) return cut.start;
  // 触っていない行でも、位置が窓の外に在れば窓の頭へ落とす(飛び先が終端の後ろだと、
  // 区間再生が一度も進まないまま止まる)。
  return at === null || at < cut.start || at >= cut.end ? cut.start : at;
}

// **そのgiftを切り出す範囲。gift演出の窓ではない。**
//
// 1つのgift演出には別人のgiftが複数入る（実測で6.0秒のgift演出に あきと6000🪙 / おニャンコ999🪙 /
// るきしろ99🪙 の3人）。出力はgifterごとに1本なので、gift演出の窓をそのまま「この行の区間」
// として扱うと、1人の行で詰めた値が他の2人のfileまで一緒に動く。
//
// Serverは触っていないgiftにも必ず値を入れて返す（そのときはgift演出の窓と同じ値になる）ので、
// 画面側で「無ければgift演出の窓」を組み立てない ―― 組み立てを各所に書くと、いつか片方だけが
// gift演出の窓のままになり、詰めたはずの区間が元の長さで出力へ入る。
function cutOf(item) {
  const start = num(item && item.cut_start);
  const end = num(item && item.cut_end);
  if (start === null || end === null) return null;
  return { start, end };
}

// その当たりの区間。
function hitSpanText(hit) {
  const cut = cutOf(hit);
  if (!cut) return "—";
  return `${fmtPos(cut.start)}〜${fmtPos(cut.end)}`;
}

// その当たりが**自分の見せ場**を持つか。1つのgift演出に順番待ちで並んだ演出のうち、その
// giftのものが映っている区間である。**空は「そのgift演出を割っていない」**で、gift演出の窓と
// 同じという意味ではない(割れるのは演出の数と載ったgiftの数が一致したときだけである)。
function hasShow(hit) {
  return !!hit && num(hit.show_start) !== null && num(hit.show_end) !== null;
}

// その当たりが「同席しただけ」か。**主(``is_primary``)でない当たりは出力に載らない** ――
// gift演出1つに映っている演出は1つで、それはその主の1本にだけ入る。人が付け替えた行
// (``manual``)は主でなくても載るので、ここも通す(判定はServerの highlight_export と同じ)。
//
// **投げた人が1人しか居ない所では「同席」ではない。** 同席は「別人のgiftが主」の意味なので、
// 自分の連投の2件目以降に付けるのは誤りである(利用者の指摘。Ramune 200🪙 を0.92秒の間に
// 4回投げた行が、2件目から「出力なし」を名乗っていた)。そちらは :func:`foldCombos` が1行へ
// 畳むが、畳めなかった時のためにここでも通さない。
function coverPassenger(hit) {
  if (!hit || hit.manual) return false;
  // **自分の見せ場を持つ行は同席ではない。** TikTokは全画面演出を順番待ちで1つずつ流すので、
  // 継ぎ目の無い1続きの場面には別人の演出が何本も並ぶ。照合がそれを割れた行は、他人の演出を
  // 1frameも含まない自分の窓を持っている ―― 主かどうかで落とす理由がそこには無い
  // (判定はServerの highlight_export.segment_owners と同じ)。
  if (hasShow(hit)) return false;
  if (hit.is_primary !== false) return false;
  const gifters = num(hit.segment_gifters);
  return gifters === null || gifters > 1;
}

// ===== 連投を1行へ畳む =====

// 1行が抱えるgift eventの数。畳んでいない行は1件である。
function comboSize(row) {
  return ((row && row.combo) || []).length || 1;
}

// その行が抱えるgift event。畳んでいない行は自分1件。
function comboItems(row) {
  return (row && row.combo) || [row];
}

// 畳む鍵。**同じ人・同じgift・同じgift演出**の3つが揃ったときだけ畳む。
//
// 揃った連投は**1つの演出**であって、出力にも1本しか入らない(主だけが通る)。同じ区間の
// 行が4つ並ぶのは表の水増しで、しかも2件目以降が「出力なし」を名乗るので、別人のgiftが載って
// いるように読めた(利用者の指摘)。実物は Ramune 200🪙 ×4 が **0.92秒**の間に届いた1回の
// combo burst だった。
//
// **gift演出が違えば畳まない。** 演出が2つ在るなら、確かめる相手も2つである。当たりの無い
// 行(どのハイライトにも出ていないgift)も畳まない ―― 畳む根拠(同じ演出)がそこには無い。
function foldKey(row) {
  const key = comboKey(row);
  const hit = coverHits(row)[0];
  if (!key || !hit || num(hit.segment_id) === null) return "";
  // 見せ場まで鍵に入れる。**同じgift演出でも見せ場が別なら別の行である** ―― 割れたgift演出
  // では連投の1件ずつが別の窓を持つので、gift演出だけで畳むと別々の区間が1つに化ける。
  return `${key} #${hit.segment_id}:${hasShow(hit) ? hit.show_start : ""}`;
}

// 畳んだ1行を作る。**代表は主(``is_primary``)の当たりを持つ行**である ―― 区間もNGも
// 出力に載るのはその1件で、代表を並び順で決めると、触った値が出力に効かない行に付く。
function foldedRow(rows) {
  const rep = rows.find((row) => (coverHits(row)[0] || {}).is_primary) || rows[0];
  const coins = rows.reduce((sum, row) => sum + (num(row.diamonds) || 0), 0);
  const count = rows.reduce((sum, row) => sum + (num(row.gift_count) || 1), 0);
  return {
    ...rep,
    // 時刻は**塊の先頭**。連投は数百msの間に届くので、代表の時刻では塊の頭が読めない。
    // 時刻を持たない行しか無ければ代表のまま(推測で時刻を作らない)。
    time: rows.reduce((first, row) => {
      const at = num(row.time);
      return at === null || (first !== null && first <= at) ? first : at;
    }, null) ?? rep.time,
    // 🪙は合計。単価と件数は coinNode が ``unit_diamonds`` × ``gift_count`` で添える。
    diamonds: coins,
    gift_count: count,
    // 「見た」の印は**全件が付いていて初めて付く**。一部を「済」に見せると、畳んだ中の
    // 未確認が消える。
    checked: rows.every((row) => Boolean(row.checked)),
    combo: rows,
  };
}

// 隣り合う連投を畳む。**絞り込みと並べ替えの後**に掛ける ―― 先に畳むと、畳んだ行の中に
// 絞り込みから外れる件が混ざる。
function foldCombos(rows) {
  const out = [];
  let run = [];
  const flush = () => {
    if (run.length > 1) out.push(foldedRow(run));
    else if (run.length) out.push(run[0]);
    run = [];
  };
  rows.forEach((row) => {
    const key = foldKey(row);
    if (run.length && key && key === foldKey(run[0])) {
      run.push(row);
      return;
    }
    flush();
    run = [row];
  });
  flush();
  return out;
}

function renderCoverage(opts = {}) {
  const wrap = $("cv-table").closest(".table-wrap");
  const scroll = opts.keepScroll && wrap ? wrap.scrollTop : null;
  const rows = coverRows();
  state.cvRows = rows;
  // 選んでいる物を追い直す。並べ替え・絞り込み・NGの後でも同じgiftが選ばれたままになる。
  state.cvAt = state.cvKey === null
    ? -1 : rows.findIndex((g) => g.event_id === state.cvKey);
  setListState($("cv-empty"), "empty");
  renderTableRows(
    "cv-rows", "cv-empty", rows,
    (gift) => {
      const hits = coverHits(gift);
      const first = hits[0] || null;

      // 区間。**ハイライトの中の秒はこの1列だけにする。** かつては「位置」(giftが映って
      // いる秒)を隣に並べていたが、位置も区間も同じ形の数字で、しかもどちらもハイライトの
      // 中の秒である ―― 隣り合っていると、どちらがfileに入る方なのかが読めなかった。
      // fileに入るのは区間の方なので列はそちらだけにし、giftの映っている秒はtooltipへ回す。
      // 当たりの無い行の「出ていない」もここに出る(この列が「ハイライトのどこか」を
      // 一手に引き受ける)。
      const span = document.createElement("span");
      span.className = "st-nowrap";
      if (!first) {
        // 「ハイライトに無い」は失敗ではなく結果。取得できなかったのと同じ見え方に
        // しないよう、記号ではなく言葉で名乗る。
        span.textContent = "出ていない";
        span.classList.add("st-cover-none");
      } else {
        span.textContent = hitSpanText(first);
        // この行だけの区間なのか、gift演出の窓のままなのかを名乗る。**どちらも同じ形の数字**
        // なので、印が無いと詰めたつもりの値が実はgift演出の窓だった、という読み違いが起きる。
        if (first.cut_own) span.classList.add("st-cut-own");
        // tooltipは**列に出ていない秒だけ**を出す(giftが映っている位置と、複数に出て
        // いるときの残りの当たり)。読み方も操作の説明も置かない。
        span.title = [
          fmtPos(hitSeekAt(first)),
          ...(hits.length > 1
            ? hits.map((h) => `${h.filename || `#${h.highlight_id}`} ${fmtPos(hitSeekAt(h))}`)
            : []),
        ].join("\n");
      }

      const marks = [];
      if (hits.length > 1) marks.push("複数");
      // **人が1本を選んだ行**。機械の順位ではなく人の指定でこの当たりが代表になっている、
      // ということが行から読めないと、同じ行を次に見た人が「なぜこの1本なのか」を辿れない。
      if (first && first.chosen) marks.push("選択");
      // 「対象外」の印は置かない。**週合計が下限に届かない人のgiftはServerが並べない**ので
      // (利用者の指定)、この面に来る行はすべて対象gifterのものである。届かない値のための
      // 描き分けを残すと、規則が2箇所に在るように読める。
      // **出力なし** ―― そのgift演出に載ってはいるが、映っている演出は別の人のgiftという行。
      // **割れなかったgift演出でだけ付く。** 見せ場へ割れた行は自分の窓を持つので、同じ演出に
      // 載っていても出力に載る(:func:`hasShow`)。
      // gift演出1つに映る演出は1つなので、そのgift演出はその主の1本にだけ入る。実測で6.0秒の
      // gift演出1つに 99🪙・6000🪙・999🪙 の3件が載っており、3人ぶんのfileへ入れていた頃は
      // 99🪙を投げた人の1本に他人の演出が続いていた。**この行は出力に載らない。**
      // **相席** ―― 自分が主で、同じgift演出に別の人のgiftも載っている行。相手の分は載らない。
      // 「出力なし」と1文字違いの語(旧「同席」)は、意味が正反対で読み分けられなかった。
      if (first && coverPassenger(first)) marks.push("出力なし");
      else if (first && num(first.segment_gifters) !== null && first.segment_gifters > 1) {
        marks.push("相席");
      }
      // **窓の外** ―― giftの瞬間そのものはハイライトに入っていない行(Serverの ``inside``)。
      // 演出は数秒続くので映っている可能性はある。だから**警告ではなく印**にする。
      if (first && first.inside === false) marks.push("窓の外");
      if (first && first.edited) marks.push("手直し");

      // NG。**この面で落とせることが要件**である ―― 確からしさの低い当たりを見つけても、
      // 外す場所が別の面に在ると、見つけた人がそこまで辿らない。
      const ng = document.createElement("button");
      ng.className = "btn btn-small st-ngbtn";
      ng.type = "button";
      if (!first) {
        ng.disabled = true;
        ng.textContent = "—";
      } else {
        const off = Boolean(first.excluded);
        ng.textContent = off ? "NG解除" : "NG";
        ng.classList.toggle("btn-danger", off);
        ng.setAttribute("aria-pressed", off ? "true" : "false");
        // 押した行を選んでから外す。**押した行が選ばれていないと、左の動画も区間の欄も
        // 別のgiftを出したままNGだけが飛ぶ** —— 何を外したのかが画面から読めなくなる。
        ng.addEventListener("click", async () => {
          await selectCoverAt(state.cvRows.indexOf(gift), { play: false });
          await toggleNg();
        });
      }

      // 確認済み。**当たりの有無にかかわらず押せる** ―― この面で一番確かめたいのは
      // 「出ていない」行で、その行はgift演出もgift行も持たない。gift演出の印(approved)に
      // 相乗りさせると、そこだけ押せない列ができる。
      const check = document.createElement("input");
      check.type = "checkbox";
      check.className = "st-checkbox";
      check.checked = Boolean(gift.checked);
      // 畳んだ行で一部だけ付いているとき。**「一部」を「済」に見せない** ―― 見せると
      // 畳んだ中の未確認が消える。
      check.indeterminate = !gift.checked
        && comboItems(gift).some((item) => Boolean(item.checked));
      check.setAttribute("aria-label", "確認済み");
      // 押しても左の動画は動かない(行のclickはinputを拾わない)。印を付けるのは「見た
      // あと」の操作なので、押した拍子に映像が別の行へ移ると確かめ直しになる。
      check.addEventListener("change", () => setCoverChecked(gift, check.checked));

      // 時刻は折り返させない。窓が狭いと「08/」「30」「14:」と1字ずつ縦に割れ、その1行
      // だけで表の高さが4倍になる(表そのものは.table-wrapが横へscrollさせる)。
      // **「配信時刻」である** ―― そのgiftが実際に投げられた時刻で、ハイライトの中の
      // 秒(位置・区間)とは別の軸である。
      const when = document.createElement("span");
      when.className = "st-nowrap";
      when.textContent = num(gift.time) === null ? "—" : fmtDateTimeShort(gift.time);

      return [
        when,
        // まとめ投げは単価×個数を添える。**下限を判定しているのは単価**なので、合計だけ
        // だと「270🪙が並ばないのはなぜか」を人が読み解けない。
        coinNode(gift, { className: "st-nowrap", mark: "" }),
        giftNode(gift),
        gifterNode(gift),
        span,
        first ? scoreNode(first) : "—",
        warnNode(first ? hitWarnings(first) : []),
        markNode(marks),
        check,
        ng,
      ];
    },
    // 数値列。HTML側のth.numと同じ並びでなければ、見出しと値が縦に揃わない
    // (🪙=1・区間=4・スコア=5)。
    [1, 4, 5],
    (tr, gift, index) => {
      // 先頭行に順位の意味は無い(共通の描画が付ける1位の印を外す)。
      tr.classList.remove("rank-top");
      const hits = coverHits(gift);
      // 当たった行と当たらなかった行を、行の側から名乗らせる。row-clickableは「押せる」の
      // 印であって照合の結果ではないので、見た目をそちらへ相乗りさせない。
      tr.classList.add(hits.length ? "st-hit" : "st-nogift");
      // 同席しただけの行。落として隠すと「なぜ出力に無いのか」が読めなくなるので、
      // 行は残して薄くする。**当たりが1本でも自分の見せ場なら同席では
      // ない** —— 代表(hits[0])だけを見ると、3本に入って2本が自分の見せ場のgiftでも、
      // 残る1本の同席で行ごと沈む。
      if (hits.length && hits.every((h) => coverPassenger(h))) tr.classList.add("st-offtarget");
      if (coverNg(gift)) tr.classList.add("st-excluded");
      // 見終わった行。**当たりの有無より先に付ける** ―― この面で一番読みたい「出ていない」
      // 行にこそ、どこまで見たかの印が要る(その行は当たりを持たないので、下の return より
      // 後ろに置くと印が付かない)。畳んだ行は中の全件が済んだ時だけで、一部だけの塊を
      // 「済」に見せない(checkboxの indeterminate と同じ約束)。
      if (gift.checked) tr.classList.add("st-checked");
      // 出ていない行は区間の列が「出ていない」と名乗る。行のtooltipで言い直さない。
      if (!hits.length) return;
      // 言い切れていない当たりは目立たせる。**この印を見て左の動画を確かめるのが、別人の
      // giftが別人のfileへ入る事故に画面から気付ける唯一の道である。**
      if (coverRisky(gift)) tr.classList.add("st-risk");
      tr.classList.add("row-clickable");
      tr.addEventListener("click", (ev) => {
        if (ev.target.closest("button, input, select, a")) return;
        selectCoverAt(index, { play: $("cv-autoplay").checked });
      });
    },
  );

  // 連投は畳まず、塊が読める形にする(表の行でも同じ規則)。
  markComboRows("cv-rows", rows);
  markCoverSelection();
  if (scroll !== null && wrap) wrap.scrollTop = scroll;

  const min = state.cvData && num(state.cvData.min_diamonds);
  // **何で絞った表なのかを名乗る。** gift 1件の下限だけを出していた頃は、週合計が下限に
  // 届かない人のgiftが並ばないことが画面から読めず、照合の取りこぼしとして追いかける先に
  // なっていた。人の下限(週合計)もServerの値(post_min)をそのまま出す。
  const post = state.cvData && num(state.cvData.post_min);
  $("cv-note").textContent = state.cvData
    ? [state.cvData.post_label,
       min === null ? "" : `🪙${fmtNum(min)}`,
       post === null ? "" : `週合計🪙${fmtNum(post)}⬆️のgifter`]
      .filter(Boolean).join("／") : "";
}

// 選んでいる行の印。**表を組み直さずにclassだけ付け替える** ―― ↑↓で送るたびに数百行を
// 作り直すと、押しっぱなしで送れなくなる。
function markCoverSelection() {
  const nodes = $("cv-rows").rows;
  for (let i = 0; i < nodes.length; i += 1) {
    nodes[i].classList.toggle("st-current", i === state.cvAt);
  }
  const row = nodes[state.cvAt];
  if (row && row.scrollIntoView) row.scrollIntoView({ block: "nearest" });
}

// 表の位置で選ぶ。↑↓もclickもここへ来る。
async function selectCoverAt(index, opts = {}) {
  const rows = state.cvRows;
  if (!rows.length) return;
  // **溜めた刻みは捨てずに送ってから移る。** 詰めた直後に↑↓で送ると、送る前の値が
  // 消えて「直したのに残っていない」という壊れ方をする。
  await flushCut();
  const at = Math.max(0, Math.min(rows.length - 1, index));
  state.cvAt = at;
  state.cvKey = rows[at].event_id;
  markCoverSelection();
  await selectCoverGift(rows[at], opts);
}

// そのgiftを左の動画エリアで開く。**面は動かさない。**
async function selectCoverGift(gift, opts = {}) {
  // 観る当たり。既定は代表(先頭)で、``hit`` を渡すのは人が候補を選び直したときだけである。
  const hit = opts.hit || coverHits(gift)[0];
  renderHitPicker(gift, hit);
  if (!hit) {
    clearEditTarget();
    // 出ていないgiftは映せない。前のgiftの映像を出したままにすると、それがこの行の中身だと
    // 読まれるので、何が起きているかを言葉で名乗る。
    setFormMessage($("cv-play-status"), "出ていない", false);
    drawTimeline();
    return;
  }
  setFormMessage($("cv-play-status"), "", false);
  const ok = await openStage(hit.highlight_id);
  if (!ok) return;
  const seg = (state.current.segments || []).find((s) => s.id === hit.segment_id);
  if (!seg) {
    clearEditTarget();
    drawTimeline();
    return;
  }
  state.currentSegId = seg.id;
  const gifts = seg.gifts || [];
  // 行のgiftそのものを選ぶ。gift演出が複数のgiftを持つので、代表を勝手に選ぶと表の行と
  // 手直しの相手が食い違う。
  const mine = gifts.find((g) => g.id === hit.gift_row_id)
    || gifts.find((g) => g.gift_event_id === gift.event_id)
    || seg.primary || gifts[0] || null;
  state.currentGiftId = mine ? mine.id : null;
  // 別の行へ移ったら、取り消せる1手は捨てる。持ち越すと、別の行を選んだままZを押した人が
  // 「戻せません」と言われるか、悪くすると無関係な行を戻すことになる。
  setCutUndo(null);
  // 飛び先はそのgiftの位置。**そのgiftの区間**だけを再生して、終わったら止める
  // (gift演出の尻ではない ―― 同じgift演出に別人のgiftが載っていれば、そこまで流れてしまう)。
  //
  // **候補を選び直したときだけはgift演出の頭から流す。** アニメは順番に出るので、giftの秒に
  // 着地するとその瞬間に映っているのは先に投げられた人のアニメである(実測: Whale diving
  // 2,150🪙 の秒は6.45秒で、本人のアニメが始まるのは11.8秒)。候補を選ぶのは「自分のアニメが
  // どれに映っているか」を探す操作なので、そこで頭を飛ばしては用を成さない。
  //
  // **ただし、人が窓を決め終えた行はその窓の頭である。** 探すために頭から流すのだから、
  // どこに映っているかを見つけて詰め終えた行にその理由はもう無い ―― その後もgift演出の頭から
  // 流すと、詰めた範囲の外で始まって「出力へ入る範囲そのもの」を一度も見られない(利用者の指摘)。
  // 飛び先の規則は cutSeekAt と同じものを使う。
  const cut = editingCut();
  const fromHead = Boolean(opts.fromHead) && !(cut && cut.own);
  seekTo(fromHead ? Number(hit.segment_start) : cutSeekAt(hit, cut), {
    play: Boolean(opts.play),
    until: opts.play && cut ? cut.end : null,
  });
  drawTimeline();
}

// この行のgiftが当たっているハイライトの一覧。**同じgiftは複数のハイライトに入る**ので、
// どれを観るかを人が選べないと、機械が代表に決めた1本にそのgiftのアニメが無いときに
// 手が無くなる。当たりが1本なら触れない(操作できる見た目のまま何も起きないのを避ける)。
function renderHitPicker(gift, current) {
  const select = $("cv-hit");
  if (!select) return;
  const hits = coverHits(gift);
  select.innerHTML = "";
  hits.forEach((hit) => {
    const option = document.createElement("option");
    option.value = String(hit.gift_row_id);
    option.textContent = hitPickLabel(hit);
    select.appendChild(option);
  });
  if (current) select.value = String(current.gift_row_id);
  select.disabled = hits.length < 2;
  // 0本と1本は別のことを言う。「1本だけ」と言われた人は在るはずの物を探しに行くが、
  // 出ていない行にはそもそも候補が無い。
  if (!hits.length) select.title = "このgiftはどのハイライトにも出ていません。";
  else if (hits.length < 2) select.title = "このgiftが当たっているハイライトは1本だけです。";
  else {
    select.title = "このgiftが当たっているハイライトです。選ぶと左の動画がその1本の"
      + "gift演出の頭から流れ、**書き出しもその1本を使います**（H / L でも送れます）。";
  }
}

// 候補1つの名乗り。**file名が主語**である(利用者の指定) —— どの素材を観ているのかは
// file名でしか言えない。頭は共通の羅列なので尻だけを出し、尺と印を添える。
function hitPickLabel(hit) {
  const name = String(hit.filename || `#${hit.highlight_id}`);
  const tail = name.length > 12 ? `…${name.slice(-12)}` : name;
  const span = num(hit.segment_end) !== null && num(hit.segment_start) !== null
    ? `${(Number(hit.segment_end) - Number(hit.segment_start)).toFixed(1)}秒` : "";
  const marks = [];
  if (hit.chosen) marks.push("選択中");
  else if (hit.is_primary) marks.push("主");
  if (hit.excluded) marks.push("NG");
  return [tail, span, marks.length ? `(${marks.join("・")})` : ""]
    .filter(Boolean).join(" ");
}

// 候補を選び直す。**観ることと出力の指定が同じ操作である**(利用者の指定) —— 観て確かめた
// 結果をもう一度どこかで指定させると、確かめた人と指定する人が同じでも手が2つに割れる。
async function chooseHit(rowId) {
  const gift = state.cvRows[state.cvAt];
  if (!gift) return;
  const hit = coverHits(gift).find((h) => String(h.gift_row_id) === String(rowId));
  if (!hit) return;
  // **溜めた刻みは捨てずに送ってから移る**(行を送るときと同じ)。詰めた直後にH/Lで
  // 候補を送ると、開いているgift演出が入れ替わって送り先を失い、送る前の値が黙って消える。
  await flushCut();
  await selectCoverGift(gift, { play: $("cv-autoplay").checked, hit, fromHead: true });
  const saved = await patchGift(hit.gift_row_id, { chosen: true }, "使う1本の指定");
  // 失敗したら選び直しは無かったことにする ―― selectは押した見た目のまま残るので、
  // 何も書けていないのに指定できたように読める。
  if (!saved) {
    renderHitPicker(gift, coverHits(gift)[0]);
    return;
  }
  markChosenHit(gift, hit);
  renderCoverage({ keepScroll: true });
  markCoverSelection();
  renderHitPicker(gift, hit);
}

// 選んだ1本を画面の側にも映す。**引き直さない**(表の他の操作と同じ規則) —— ただし印は
// 同じgiftの当たり**全体**に効くので、他の当たりから必ず落とす。Serverも同じことを
// ``gift_event_id`` 単位でやっている。
function markChosenHit(gift, chosen) {
  const hits = coverHits(gift);
  hits.forEach((hit) => { hit.chosen = hit.gift_row_id === chosen.gift_row_id; });
  // Serverと同じ順へ並べ替える(選んだ1本 → 見せ場/主 → 元の並び)。sortは安定なので、
  // 同じ側に居る当たりどうしの並びは崩れない。
  hits.sort((a, b) => hitPickRank(a) - hitPickRank(b));
}

function hitPickRank(hit) {
  return (hit.chosen ? 0 : 2) + ((hit.manual || hit.is_primary) ? 0 : 1);
}

// 候補を1つ隣へ送る(H / L)。**selectを開く操作と同じ物**である ―― 観ることと出力の指定が
// 同じ操作なので、keyだけ「観るだけ」にすると、目で選んだ1本と書き出す1本が食い違う。
//
// 端では回り込む。当たりは2〜3本なので、端で止める作りだと「戻す」を覚える必要が出る割に
// 戻る先が1つしか無い。当たりが1本の行では何もしない(選び直す相手が無い)。
async function stepHit(delta) {
  if (coverHits(state.cvRows[state.cvAt]).length < 2) return;
  // **溜めた刻みは捨てずに送ってから移る**(↑↓と同じ約束)。候補を送ると開く本もgift演出も
  // 変わるので、送る前の刻みは行き先を失う ―― 「詰めたのに残っていない」という壊れ方をする。
  await flushCut();
  const gift = state.cvRows[state.cvAt];
  const hits = coverHits(gift);
  if (hits.length < 2) return;
  const select = $("cv-hit");
  const at = hits.findIndex((hit) => String(hit.gift_row_id) === String(select.value));
  const next = hits[((at < 0 ? 0 : at) + delta + hits.length) % hits.length];
  if (next) chooseHit(next.gift_row_id);
}

// 表を触っている間のキー操作。**大量の行を続けて確かめるための道具**である ―― 1件ずつ
// clickして目で追うと、数百件は現実的に見られない。入力欄の中では効かせない(打鍵が
// そのまま操作になると、メモを書いている途中でgift演出がNGになる)。
function bindCoverKeys() {
  document.addEventListener("keydown", (ev) => {
    if ($("view-cover").classList.contains("hidden")) return;
    // 修飾keyは原則として受けない。**唯一の例外が Ctrl+←→ で、区間を伸ばす向きである**
    // ―― 縮める(素の←→)と伸ばすを別々のkeyに散らすと、詰める操作の途中で手が移る。
    const arrow = ev.key === "ArrowLeft" || ev.key === "ArrowRight";
    if (ev.altKey || ev.metaKey) return;
    if (ev.ctrlKey && !arrow) return;
    const target = ev.target;
    if (target && target.closest("input, select, textarea, [contenteditable=true]")) return;
    // 矢印は絞り込み・並びの群(role=radiogroup)が段送りに使うkeyでもある。focusがそこに
    // 在る間は群のものにする ―― 1打で段と区間が同時に動くと、何が動いたのか読めない。
    if ((arrow || ev.key === "ArrowUp" || ev.key === "ArrowDown")
        && target && target.closest(".seg")) return;
    const play = $("cv-autoplay").checked;
    if (ev.key === "ArrowDown" || ev.key === "j") {
      ev.preventDefault();
      selectCoverAt(state.cvAt + 1, { play });
      return;
    }
    if (ev.key === "ArrowUp" || ev.key === "k") {
      ev.preventDefault();
      selectCoverAt(state.cvAt <= 0 ? 0 : state.cvAt - 1, { play });
      return;
    }
    // **確認済みにして次を観る。** この面の主keyで、印(A)と送り(↓)を1打に畳んだ物である。
    // buttonにfocusが在るときのEnterはそのbuttonを押す操作なので奪わない(Spaceと同じ)。
    if (ev.key === "Enter") {
      if (target && target.closest("button")) return;
      const gift = state.cvRows[state.cvAt];
      if (!gift) return;
      ev.preventDefault();
      checkAndAdvance(gift);
      return;
    }
    // **縦が行、横が候補。** ↑↓(j/k)が表の行を送り、H/Lが「そのgiftが当たっている別の
    // ハイライト」を送る ―― 同じgiftは複数の本に入るので、代表の1本に本人のアニメが
    // 映っていない行では、隣の本を見に行けることが確かめる唯一の手になる。
    // ←→はここでは区間の端を動かすkeyなので、横の意味はH/Lが持つ。
    if (ev.key === "h" || ev.key === "H" || ev.key === "l" || ev.key === "L") {
      if (coverHits(state.cvRows[state.cvAt]).length < 2) return;
      ev.preventDefault();
      stepHit(ev.key === "h" || ev.key === "H" ? -1 : 1);
      return;
    }
    if (ev.key === " ") {
      // buttonにfocusが在るときのSpaceは、そのbuttonを押す操作である。奪うと、
      // NGを押した直後にSpaceを叩いた人が「押せないbutton」を見ることになる。
      if (target && target.closest("button")) return;
      const video = $("cv-video");
      if (!video.getAttribute("src")) return;
      ev.preventDefault();
      if (video.paused) video.play().catch(() => {});
      else video.pause();
      return;
    }
    // 確認済みの印。**行を送りながら**押せることが要件である(表の「確認」列と同じ口)。
    // NGと違って**当たりの無い行にも効く** ―― 出ていないgiftを1件ずつ確かめる面なので、
    // そこに印を残せないと「どこまで見たか」が残らない。
    if (ev.key === "a" || ev.key === "A") {
      const gift = state.cvRows[state.cvAt];
      if (!gift) return;
      ev.preventDefault();
      setCoverChecked(gift, !gift.checked);
      return;
    }

    // NGは**行を送りながら**落とせることが要件である。表の右端のbuttonと同じ口へ送る。
    // **Nは当たりを持つ行にしか効かない**(外す相手が当たりだから)。当たりの無い行にも
    // 効くのは上のAだけで、そこが2つの印の違いである。
    if (ev.key === "n" || ev.key === "N") {
      if (!currentSegment()) return;
      ev.preventDefault();
      toggleNg();
      return;
    }
    // ここから下は区間の微調整。**キーだけで詰め切れることが要件**である ―― 端を掴んで
    // dragする道しか無かった頃は、全体の軸で6秒のgift演出が70pxしか無く、0.25秒が3pxだった。
    if (!editingCut()) return;
    // [ ] は頭、 , . は尻。Shiftで刻みが4倍(0.25→1.0秒)になる。
    const step = ev.shiftKey ? NUDGE_BIG_SECONDS : NUDGE_SECONDS;
    const NUDGE = { "[": ["start", -1], "]": ["start", 1], ",": ["end", -1], ".": ["end", 1] };
    // **矢印は「帯が動く向き」、Ctrlは「伸ばす」。** どちらの端が動くかを覚えなくても、
    // 押した向きへ区間が縮む(素の←は尻を左へ、→は頭を右へ)か、同じ向きへ伸びる
    // (Ctrl+←は頭を左へ、Ctrl+→は尻を右へ)かだけで読める。[ ] , . は端を名指しで
    // 動かす手で、こちらは「どちらの端か」を言わずに詰め切るための手である。
    const ARROW = {
      ArrowLeft: ev.ctrlKey ? ["start", -1] : ["end", -1],
      ArrowRight: ev.ctrlKey ? ["end", 1] : ["start", 1],
    };
    // Shift+, / Shift+. は「<」「>」として届くので、両方の綴りを受ける。
    const nudge = ARROW[ev.key] || NUDGE[ev.key] || NUDGE[{ "<": ",", ">": "." }[ev.key]];
    if (nudge) {
      ev.preventDefault();
      nudgeCut(nudge[0], nudge[1] * step);
      return;
    }
    if (ev.key === "z" || ev.key === "Z") {
      ev.preventDefault();
      undoCut();
    }
  });
}

// ===== 出力 =====

// 出力の対象になり得る本。gift演出を1つも持たない本は繋ぐ物が無いので出さない。
function exportable() {
  return state.highlights.filter((h) => num(h.segment_count) > 0);
}

// 出力tabの配信者。選択肢は出力し得る本を持つ配信者だけで、必ず1人が選ばれている
// ―― 「全て」を作ると、そこで選んだ複数本がServerに400で弾かれる選択になる。
function renderExportStreamers() {
  const select = $("ex-streamer");
  const want = select.value;
  const names = [...new Set(exportable().map((h) => h.unique_id).filter(Boolean))].sort();
  select.innerHTML = "";
  names.forEach((name) => {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    select.appendChild(option);
  });
  select.value = names.includes(want) ? want : (names[0] || "");
  select.disabled = names.length <= 1;
  return select.value;
}

// 対象の週。**配信者画面の「週のGifter」と同じ口**から引く ―― 画面と出力で「誰が対象か」
// が食い違うのが最悪の結末なので、週の境界(土曜7時始まり)も閾値(post_min)も画面側では
// 組み立てず、Serverが返した物をそのまま出す。
async function loadWeeks(streamer) {
  const seq = (state.exWeekSeq += 1);
  const select = $("ex-week");
  if (!streamer) {
    state.exWeek = "";
    state.exWeekData = null;
    select.innerHTML = "";
    setFormMessage($("ex-week-range"), "", false);
    return;
  }
  const params = new URLSearchParams();
  if (state.exWeek) params.set("week", state.exWeek);
  const query = params.toString();
  let data;
  try {
    data = await apiSend("GET",
      `/api/streamers/${encodeURIComponent(streamer)}/mentions${query ? `?${query}` : ""}`);
  } catch (err) {
    if (seq !== state.exWeekSeq) return;
    // 週が引けないなら、前の週の名乗りを残さない ―― 別の週のものとして読まれる。
    state.exWeekData = null;
    select.innerHTML = "";
    setFormMessage($("ex-week-range"), "週を取得できません", true);
    showError(err, "対象の週");
    return;
  }
  if (seq !== state.exWeekSeq) return;
  state.exWeekData = data;
  state.exWeek = data.week || "";
  renderWeeks();
  // 週が決まった時点で素材を選び直す。**週を選ぶことが素材を選ぶこと**である ――
  // 期間を指定してあるのに、その期間の素材を毎回手で選ばせる理由が無い。
  renderExportPicks();
  loadExportOutputs();
}

function renderWeeks() {
  const data = state.exWeekData;
  const select = $("ex-week");
  select.innerHTML = "";
  if (!data || !(data.weeks || []).length) {
    $("ex-week-prev").disabled = true;
    $("ex-week-next").disabled = true;
    select.disabled = true;
    setFormMessage($("ex-week-range"), data ? "記録なし" : "", false);
    return;
  }
  select.disabled = false;
  // 選択肢は窓の開始だけで名乗る。どの週も同じ形(土7時→次の土7時)なので、終端まで
  // 並べても区別の助けにならない。範囲そのものは下の名乗りがServerの文字列で出す。
  data.weeks.forEach((w) => {
    const option = document.createElement("option");
    option.value = w.key;
    option.textContent = `${w.label || w.key}　${fmtCompact(w.diamonds)}`;
    select.appendChild(option);
  });
  select.value = data.week;
  $("ex-week-prev").disabled = !data.prev_week;
  $("ex-week-next").disabled = !data.next_week;
  // 名乗りはserverが組んだ文字列をそのまま出す。日付から組み直すと時刻が落ち、
  // 土曜の朝(0〜7時)がどちらの週とも読める名乗りになる。
  setFormMessage($("ex-week-range"),
    data.start_label ? `${data.start_label} 〜 ${data.end_label}` : "", false);
}

function stepWeek(step) {
  const data = state.exWeekData;
  if (!data) return;
  const next = step < 0 ? data.prev_week : data.next_week;
  if (!next) return;
  state.exWeek = next;
  clearExportPlan();
  loadWeeks($("ex-streamer").value);
}

function matchedHighlights() {
  const streamer = $("ex-streamer").value;
  return exportable().filter((h) => h.unique_id === streamer);
}

// その本が指定の週の素材か。**画面は日付から週を組み立てない** ―― 週keyはServerが当たった
// giftのeventの時刻から決めた物(`weeks` は跨いだ週を全部持つ)で、こちらで組み直すと
// 境目(土曜7時)の解釈が2箇所に生まれる。照合前の本はどの週にも属さない。
function inExportWeek(highlight, week) {
  if (!week) return false;
  const weeks = Array.isArray(highlight.weeks) && highlight.weeks.length
    ? highlight.weeks : (highlight.week ? [highlight.week] : []);
  return weeks.includes(week);
}

function weekHighlights() {
  return matchedHighlights().filter((h) => inExportWeek(h, state.exWeek));
}

// 対象の週の素材。**週を選ぶことが素材を選ぶことである** ―― 素材はその週のgiftに当たった
// ハイライトそのもので、file名(v1c43ag5000c…)から中身を当てられない一覧を人へ選ばせても
// 判断できない(利用者の指定で棚ごと外した)。
function pickWeekHighlights() {
  state.exPicked.clear();
  weekHighlights().forEach((h) => state.exPicked.add(h.id));
  state.exAutoWeek = state.exWeek;
}

function renderExportPicks() {
  const streamer = renderExportStreamers();
  // 週の顔ぶれは配信者ごとに別物。開いた配信者が変わったら引き直す。
  if (streamer && streamer !== state.exWeekStreamer) {
    state.exWeekStreamer = streamer;
    state.exWeek = "";
    loadWeeks(streamer);
  }
  const known = new Set(matchedHighlights().map((h) => h.id));
  [...state.exPicked].forEach((id) => { if (!known.has(id)) state.exPicked.delete(id); });
  // 一覧が届くたびに揃え直す。照合の終わった本がその週の物なら、押し直さずに素材へ入る。
  if (state.exWeek) {
    const before = [...state.exPicked].sort().join(",");
    pickWeekHighlights();
    // 素材が実際に変わった時だけ束を捨てる。捨てるついでに通し再生も止まるので、
    // 変わっていない時にも呼ぶと、観ている最中に一覧が届いただけで再生が切れる。
    if ([...state.exPicked].sort().join(",") !== before) clearExportPlan();
  }
  updateExportButtons();
  autoPlanExport();
}

// **出力tabを開いたら出来上がりを出す。** 素材は週で決まるので、人がここで決めることは
// 何も残っていない ―― それでも毎回「出来上がりを確認」を押さないと表が空だった
// (利用者の指定)。既に組んである束は組み直さない(観ている最中に一覧が届いただけで
// 表が入れ替わると、選んでいた行を見失う)。
function autoPlanExport() {
  if ($("view-export").classList.contains("hidden")) return;
  if (!state.exPicked.size || state.exFiles.length) return;
  // 同じ条件で一度引いたら、もう自動では引き直さない。**0件は409で返る** ―― 束が空の
  // ままなので、この印が無いと一覧が届くたびに同じ問い合わせを繰り返す。
  const key = [$("ex-streamer").value, state.exWeek, [...state.exPicked].sort().join(",")]
    .join("|");
  if (key === state.exPlanKey) return;
  state.exPlanKey = key;
  planExport();
}

// 組んだ束を捨てる。対象や条件が変わった時に呼ぶ ―― 画面に出ている束と、実際に
// 書き出される物が違う、という状態を作らない。
function clearExportPlan() {
  state.exFiles = [];
  // 条件が変わったので、自動の下見はもう一度引いてよい。
  state.exPlanKey = null;
  state.exSkipped = [];
  state.exUncovered = [];
  setListMessage($("ex-empty"), "");
  const tbody = $("ex-rows");
  if (tbody) tbody.innerHTML = "";
  // 章の帯も同じ理由で落とす。組み直す前の束の窓が並んだままだと、clickで消えた計画の
  // 窓を再生しに行くことになる。
  stopRun();
  renderChapters("", []);
  updateExportButtons();
}

function updateExportButtons() {
  const count = state.exPicked.size;
  $("ex-plan").disabled = count === 0;
  // 下見は確認の道具で、書き出しの前提条件ではない。下見を通さないと押せない作りにすると、
  // 下見のAPIが応えない日に書き出しそのものができなくなる。
  $("ex-run").disabled = count === 0;
  // 何本できるのかを押す前に名乗る。下見を通していなければ本数は判らないので、
  // 数を作らずbutton名だけにする。
  const files = state.exFiles.length;
  $("ex-run").textContent = files ? `書き出す ${fmtNum(files)}` : "書き出す";
  $("ex-summary").textContent = count ? fmtNum(count) : "";
}

// 束の作り方(誰のgift演出が何本のfileになるか)と「何件が載るか」は**Serverが決める**。
// 除外の規則(人が外した / 再照合で消えた / gift地点でない / 下限未満 / 同じgiftの重複)も
// 束ねる鍵(identity_key)も highlight_export の1箇所にあり、画面で先読みすると規則が2つに
// なって、片方だけ直った日に予告と成果物が食い違う。この画面はplanを引いて描くだけで、
// 判断は持たない。
async function planExport() {
  if (!state.exPicked.size || state.exPlanning) return;
  state.exPlanning = true;
  const btn = $("ex-plan");
  btn.disabled = true;
  setListState($("ex-empty"), "loading");
  let plan;
  try {
    plan = await apiSend("POST", "/api/highlights/export/plan", exportBody());
  } catch (err) {
    // 0件は409で、detailに内訳の文言が入って返る。空の一覧として描かない ―― 下見が
    // 引けなかったのか、条件に合う物が無かったのかは、書き出しの前に区別が要る。
    state.exFiles = [];
    state.exSkipped = [];
    state.exUncovered = [];
    setListState($("ex-empty"), "failed", err);
    showError(err, "書き出しの下見");
    btn.disabled = false;
    state.exPlanning = false;
    updateExportButtons();
    return;
  }
  btn.disabled = false;
  state.exPlanning = false;
  if (!Array.isArray(plan.files)) {
    // 読めない形の応答を、画面が組み直して埋めることはしない。誰のfileを作るかも
    // 中身の選び方もServer側の規則なので、代用すると予告と成果物が食い違う。
    state.exFiles = [];
    state.exSkipped = [];
    state.exUncovered = [];
    setListMessage($("ex-empty"), "Serverが files を返していません");
    $("ex-rows").innerHTML = "";
    showToast("Serverの応答にfilesがありません。", "error", { title: "書き出しの下見" });
    updateExportButtons();
    return;
  }
  state.exFiles = plan.files;
  state.exSkipped = plan.skipped || [];
  state.exUncovered = plan.uncovered || [];
  renderPlanRows();
  updateExportButtons();
}

// giftの出所。planのitemは素材の実pathを持たない(Serverが返さない ―― 画面が指すのは
// ハイライトの行であってfile systemではない)ので、**idで台帳を引く**。台帳に無いidは
// 名前を作らず `#id` のまま出す ―― 別のfileの名前を出すよりは、判らないと言う方がよい。
function srcName(highlightId) {
  const id = num(highlightId);
  if (id === null) return "";
  const row = state.highlights.find((h) => h.id === id);
  return row ? (row.filename || `#${id}`) : `#${id}`;
}

// 素材のハイライトの再生URL。**Serverが名乗ったものだけを使う** ―― pathから組み立てると、
// 置き場の決まりが変わった瞬間に実在しないURLを黙って指す。
function srcUrl(highlightId) {
  const id = num(highlightId);
  if (id === null) return "";
  const row = state.highlights.find((h) => h.id === id);
  return (row && row.url) || "";
}

// 1本の中身。行をclickしたときだけ開く ―― 全部のgiftを常時並べると、数十人ぶんで
// 数百行になり「誰のfileが何本できるか」が読めなくなる。
//
// **ここに絵を出すのが要件の核**である。出来上がったmp4の中身が別人のgiftだった事故は、
// この一覧がgift名とgifter名の文字列しか出していなかったために、書き出して観るまで
// 誰も気付けなかった。絵は大きめに出す(束を開いた行なので縦の余裕がある)。さらに
// **1件ずつ実物を再生できる** ―― 絵は1 frameでしかなく、演出が本当に映っているかは
// 動いている物を観ないと判らない。
function buildFileItems(file) {
  const wrap = document.createElement("div");
  wrap.className = "st-subitems";
  // 実際に付くfile名。**表の列からは外した**(順位・週・週合計🪙・gifterを並べ直した
  // 文字列で、どれも表に列として出ている)。ただし置き場を開いて現物を探すときには要る
  // ので、行を開いた中で全文を1行だけ出す ―― 名前はServerが決める(表示名の文字置換や
  // 衝突回避が入るので、画面で組み立てると実際に出来るfileと違う名前を予告する)。
  const named = document.createElement("div");
  named.className = "st-subname vd-summary";
  named.textContent = file.filename || "file名なし";
  wrap.appendChild(named);
  const items = file.items || [];
  items.forEach((item, i) => {
    const row = document.createElement("div");
    row.className = "st-subitem";
    if (item.gift_event_id !== undefined && item.gift_event_id !== null) {
      row.dataset.exitem = String(item.gift_event_id);
    }
    // **束の持ち主と違うgifterが混ざっていないか。** 以前はここを省いていた ―― 「同じ人の
    // gift演出が並ぶ」前提だったからである。その前提が破れたのが今回の事故で、あきと🐢💤 の
    // fileに よい🐢💤 ｻｲｺｳｯ! のgiftが入っていた。**違えばこの行で目に入る。**
    const mine = String(item.identity_key || "") === String(file.identity_key || "");
    if (item.identity_key && file.identity_key && !mine) row.classList.add("st-foreign");
    if (item.confidence !== undefined && item.confidence !== null
        && !isSure(item.confidence)) {
      row.classList.add("st-risk");
    }
    const no = document.createElement("span");
    no.className = "st-sub-no";
    no.textContent = String(i + 1);
    // その1件だけを素材から再生する。**書き出す前に動く物で確かめられる**唯一の場所。
    const play = document.createElement("button");
    play.className = "btn btn-small st-playbtn";
    play.type = "button";
    play.textContent = "▶";
    play.setAttribute("aria-label", "再生");
    const url = srcUrl(item.highlight_id);
    if (!url) {
      play.disabled = true;
    } else {
      play.addEventListener("click", (ev) => {
        ev.stopPropagation();
        playExportItem(file, item, url);
      });
    }
    const coin = coinNode(item);
    const len = document.createElement("span");
    len.className = "st-sub-len";
    const start = num(item.start);
    const end = num(item.end);
    len.textContent = fmtLen(start === null || end === null ? null : end - start);
    // そのgift演出が信用できるか。Serverが名乗らないfieldは何も出さない ―― 「印が無い」を
    // 「大丈夫」として描くと、確かめていないgift演出が確かめた物と同じ見え方になる。
    const marks = [];
    if (item.confidence !== undefined && item.confidence !== null
        && !isSure(item.confidence)) marks.push("要確認");
    if (item.edited) marks.push("手直し");
    const mark = document.createElement("span");
    mark.className = "st-sub-mark";
    if (marks.length) {
      mark.textContent = marks.join("・");
      mark.classList.add("st-risk-text");
    }
    // どのハイライトのどこから来たgift演出か。切り出す範囲(start〜end)を出す ―― giftの位置
    // (item.at)は絵の側が名乗るので、ここは「fileに入る尺そのもの」を出す。
    const from = document.createElement("span");
    from.className = "st-sub-from vd-summary";
    from.textContent = `${srcName(item.highlight_id)} ${fmtPos(item.start)}`;
    // 省略された値の復元。file名の全文と、列に出ていない終端の秒だけを持つ。
    from.title = `${srcName(item.highlight_id)} ${fmtPos(item.start)}〜${fmtPos(item.end)}`;
    // gifterは**束の持ち主と違うときだけ**出す。全行に出していた頃は、束の見出しに出て
    // いる名前が中の行にも十数回並ぶだけで、行の幅を食って読みにくくなっていた
    // (利用者の指摘)。**別人が混ざっていることは、この省略で弱まらない** ―― 束の中で
    // 名前が出ている行はその1行だけになるので、かえって目に入る。名乗りの無いgift
    // (identity_keyをServerが出せなかったもの)は「同じ人だ」と言い切れないので出す。
    const named = !(mine && item.identity_key && file.identity_key);
    const who = named ? gifterNode(item) : null;
    if (who) {
      who.classList.add("st-sub-who");
      // 別人が混ざっている行は色で名乗る(.st-risk-text)。名前が出ていること自体が印で、
      // 文章では言い直さない。
      if (item.identity_key && file.identity_key) who.classList.add("st-risk-text");
    }
    row.append(no, play, giftNode(item), ...(who ? [who] : []), coin, len, mark, from);
    // gift演出の行も**clickで再生**する。▶は小さく、狙って押す物が並ぶほど確かめる手が止まる
    // ―― 束の行と同じ操作で同じ結末になっているのが要件である。
    if (url) {
      row.classList.add("st-subclick");
      row.addEventListener("click", (ev) => {
        if (ev.target.closest("button, input, select, a")) return;
        playExportItem(file, item, url);
      });
    }
    wrap.appendChild(row);
  });
  // 連投の罫は**出力に載る行だけ**へ付ける。下の「載らなかったgift」まで同じ塊に見えると、
  // 入る物と入らない物の境目が消える(印の位置は行の並びで決まるので、先に付けておく)。
  markCombos(wrap, items);
  wrap.append(...buildMissingItems(file));
  return wrap;
}

// その週に投げたのに1本へ載らなかったgift。**出力の中身ではない**ので、薄い行として
// 出力の行の下へ続ける。
//
// **無い物を見せるのがこの行の要件である。** 照合結果だけを並べていた頃は、TikTokが
// 選ばなかったgiftも、人が外したgiftも、別のハイライトに在るだけのgiftも、すべて
// 「画面に無い」で一括りになっていた ―― 何が足りないのかを人が確かめる術が無かった。
// 理由はServerの文言をそのまま出す(画面で言い換えると、判断の説明が2箇所に増える)。
function buildMissingItems(file) {
  const missing = file.missing || [];
  if (!missing.length) return [];
  const total = missing.reduce((sum, g) => sum + (num(g.diamonds) || 0), 0);
  const head = document.createElement("div");
  head.className = "st-subitem st-misshead";
  head.textContent = `未収録 ${fmtNum(missing.length)}（🪙${fmtNum(total)}）`;
  const nodes = [head];
  missing.forEach((gift) => {
    const row = document.createElement("div");
    row.className = "st-subitem st-missitem";
    const no = document.createElement("span");
    no.className = "st-sub-no";
    no.textContent = "—";
    const when = document.createElement("span");
    when.className = "st-sub-when vd-summary";
    when.textContent = gift.label || fmtClock(gift.time);
    // ここに並ぶのは**その束の持ち主が投げたgift**なので、名前は出さない —— 束の見出しと
    // 同じ名前が薄い行に十数回並ぶだけである。持ち主と違う名乗りのときだけ出す。
    const mine = String(gift.identity_key || "") === String(file.identity_key || "");
    const who = mine ? null : gifterNode(gift);
    if (who) who.classList.add("st-sub-who");
    const why = document.createElement("span");
    why.className = "st-sub-from vd-summary";
    why.textContent = gift.reason || "";
    // 別のハイライトに在るなら、どれかまで言う ―― 左の棚でそれを選べば1本へ入る。
    const sources = gift.highlight_ids || [];
    why.title = [gift.reason || "", ...sources.map(srcName)].filter(Boolean).join("\n");
    row.append(no, when, giftNode(gift), ...(who ? [who] : []), coinNode(gift), why);
    nodes.push(row);
  });
  return nodes;
}

// gift 1件の🪙。**まとめ投げは単価と個数まで出す。** 合計しか出さないと「270🪙なのに
// 演出が出ていない」が謎のまま残る ―― 下限を判定しているのは単価の方である。
//
// **絵文字は数の手前に置く**(利用者の指定)。数の後ろに付けていた頃は、額の桁が行ごとに
// 違うので絵文字の位置が行ごとに動き、列としてどこが🪙の欄なのかが読めなかった。絵文字と
// 数を別のspanに分けてあるのは、欄の中で**絵文字を左端・数を右端**へ寄せるためである ――
// 1つの文字列にすると、右へ寄せれば絵文字が、左へ寄せれば数が、行ごとに揃わなくなる。
function coinNode(gift, { className = "st-sub-d", mark = "🪙" } = {}) {
  const coin = document.createElement("span");
  coin.className = className;
  // 単位を付けるかは呼ぶ側が決める。表の列は見出しが🪙を持っているので、値へ重ねない。
  const value = num(gift.diamonds);
  if (value !== null && mark) {
    const icon = document.createElement("span");
    icon.className = "st-coin-mark";
    icon.textContent = mark;
    coin.appendChild(icon);
  }
  const digits = document.createElement("span");
  digits.className = "st-coin-num";
  digits.textContent = value === null ? "—" : fmtNum(value);
  coin.appendChild(digits);
  const count = num(gift.gift_count);
  const unit = num(gift.unit_diamonds);
  if (count !== null && count > 1 && unit !== null) {
    const each = document.createElement("span");
    each.className = "st-sub-each vd-summary";
    each.textContent = `${fmtNum(unit)}×${fmtNum(count)}`;
    coin.appendChild(each);
  }
  return coin;
}

// 連投(combo)の見せ方。**1行へ潰さない。** 同じ人が同じgiftを6回投げれば6件の別event
// (message_idが全部違う)で、重複ではない ―― 畳むと「6件で1,194🪙」が「199🪙」に見える。
// ただし6行が同じ姿で並ぶと、人は表のbugだと思う。**同じ人の同じgiftが続く塊を罫でつなぎ、
// 先頭に件数を添える。**
//
// 塊の見分けは「並びの上で隣り合う・同じ人・同じgift」だけで決める。時間の閾値を置くと、
// それが画面の持つ判断になる(並び順は利用者が変えられるので、閾値は意味を持たない)。
function comboKey(row) {
  const who = row.identity_key || row.user_unique_id || row.user_nickname || "";
  const gift = row.gift_id || row.gift_name || "";
  if (!who || !gift) return "";
  return `${who} ${gift}`;
}

// 連続する同じ塊へ印を付ける。``onRun(from, rows数, event数)``。
//
// **件数はeventで数える。** 同じgift演出へ落ちた連投は1行へ畳まれる(:func:`foldCombos`)
// ので、行を数えると4件の連投が「1」になる。行が1つでも中に2件以上居れば塊である。
function eachComboRun(rows, onRun) {
  let start = 0;
  for (let i = 1; i <= rows.length; i += 1) {
    const key = i < rows.length ? comboKey(rows[i]) : "";
    if (i < rows.length && key && key === comboKey(rows[start])) continue;
    const size = rows.slice(start, i).reduce((sum, row) => sum + comboSize(row), 0);
    if (size > 1 && comboKey(rows[start])) onRun(start, i - start, size);
    start = i;
  }
}

// 表の行版。件数は時刻のcell(先頭)へ添える ―― 塊の頭がどこかは左端で読む物である。
// 罫でつなぐのは**2行以上に散っている塊**だけで、1行に畳まれた塊は件数だけを添える。
function markComboRows(tbodyId, rows) {
  const nodes = [...document.getElementById(tbodyId).rows];
  eachComboRun(rows, (from, count, size) => {
    if (count > 1) {
      for (let i = from; i < from + count; i += 1) {
        nodes[i].classList.add("st-combo");
        if (i === from) nodes[i].classList.add("st-combo-head");
        if (i === from + count - 1) nodes[i].classList.add("st-combo-tail");
      }
    }
    const badge = document.createElement("span");
    badge.className = "st-combo-n";
    badge.textContent = `×${fmtNum(size)}`;
    nodes[from].cells[0].appendChild(badge);
  });
}

function markCombos(wrap, items) {
  // gift演出の行だけを ``items`` と突き合わせる。枠には行以外の物(file名の見出し)も入るので、
  // children をそのまま数えると印が1つずつ隣の行へずれる。
  const nodes = [...wrap.querySelectorAll(":scope > .st-subitem")];
  eachComboRun(items, (from, count) => {
    for (let i = from; i < from + count; i += 1) {
      nodes[i].classList.add("st-combo");
      if (i === from) nodes[i].classList.add("st-combo-head");
      if (i === from + count - 1) nodes[i].classList.add("st-combo-tail");
    }
    const badge = document.createElement("span");
    badge.className = "st-combo-n";
    badge.textContent = `×${fmtNum(count)}`;
    // 行そのものへ足す。格子に載せた行なので、印は左の余白へ浮かせて置く(CSS)
    // ―― 列の1つとして入れると、印の付いた行だけ番号が左へずれる。
    nodes[from].appendChild(badge);
  });
}

// 出来上がらなかった人。**gifterの表の行として並べる。** 以前は表の下へ段を作り、
// 「下限を越えたgiftが5件（🪙1,495）ありますが、どれもハイライトに出ていません」と
// 1人ずつ文章で書いていたが、読む物は行であって説明ではない(利用者の指定) ――
// 同じ列(gifter / gift / 週合計🪙 / この1本🪙 / 尺)に載せれば、fileになる人と並べて
// 読める。**fileにならないことは行の警告色と gifter の脇の印で名乗る。**
//
// 2種類ある。どちらも「この週の対象なのにfileが1本も出来ない人」で、違うのは理由だけ:
//   uncovered … 選んだ素材のどこにも出てこない(照合の取りこぼしを疑う場面)
//   skipped   … 出てはいるが書き出せない(表示名がfile名に使えない等、Serverの文言)
function noFileRow(who, cols) {
  const tr = document.createElement("tr");
  tr.className = "st-nofile row-warn";
  const NUM_COLS = new Set([0, 2, 3, 4, 5]);
  const name = document.createElement("span");
  name.className = "st-groupname";
  const gifter = gifterNode({ user_nickname: who.nickname, user_unique_id: who.unique_id });
  // 印は短い語だけ。**なぜ出来ないのか**はServerの文言で、行のtooltipが持つ
  // (表の1行を3段に伸ばさない)。画面が言い換える説明は置かない。
  const tag = document.createElement("span");
  tag.className = "st-nofile-tag";
  tag.textContent = "⚠ fileにならない";
  name.append(gifter, tag);
  const cells = ["—", name, ...cols];
  cells.forEach((cell, col) => {
    const td = document.createElement("td");
    if (NUM_COLS.has(col)) td.className = "num";
    if (cell instanceof Node) td.appendChild(cell);
    else td.textContent = cell;
    tr.appendChild(td);
  });
  // 「観る」の列。観る物が無いので空のcellを1つ置く(列数を揃えないと罫がずれる)。
  tr.appendChild(document.createElement("td"));
  if (who.reason) tr.title = who.reason;
  return tr;
}

// 何件が行き場を失っているか。0件なら「下限を越えるgiftが無い」であって「取りこぼし」
// ではない —— 別の話なので、同じ印にしない。
function missingCountNode(row) {
  const wrap = document.createElement("span");
  wrap.textContent = "0";
  const miss = num(row.missing_count) || 0;
  if (!miss) return wrap;
  const tag = document.createElement("span");
  tag.className = "st-miss-n";
  tag.textContent = `未収録${fmtNum(miss)}`;
  // tooltipは**落ちたgiftそのもの**だけ。件数は印に出ている。
  tag.title = (row.missing || [])
    .map((g) => `${g.label || ""} ${g.gift_name || ""} 🪙${fmtNum(g.diamonds)}`
      + ` — ${g.reason || ""}`)
    .join("\n");
  wrap.appendChild(tag);
  return wrap;
}

function appendNoFileRows(fragment) {
  (state.exUncovered || []).forEach((row) => {
    fragment.appendChild(noFileRow(
      { ...row, reason: "選んだ素材のどこにも出ていません" },
      [missingCountNode(row), num(row.coin) === null ? "—" : fmtNum(row.coin), "—", "—"]));
  });
  (state.exSkipped || []).forEach((row) => {
    fragment.appendChild(noFileRow(
      // 理由はServerの文言をそのまま出す。画面で言い換えると、実際に起きたことと
      // 画面の説明が別々に動く。
      { ...row, reason: row.reason || "" },
      [num(row.segments) === null ? "—" : fmtNum(row.segments), "—", "—", "—"]));
  });
}

// 1本に入るgiftの件数と、**入らなかった件数**。数はどちらもServerが数えた値だけを出す
// (件数の数え方を画面が持つと、畳み方が変わった日に予告と成果物が食い違う)。
// 入らなかった件数を並べて出すのは、「12件入る」だけでは**その週に何を投げたのか**が
// 判らないためである ―― 3件落ちているのか0件なのかで、束を開いて確かめる理由が変わる。
function giftCountNode(file) {
  const wrap = document.createElement("span");
  wrap.textContent = num(file.count) === null ? "—" : fmtNum(file.count);
  const miss = num(file.missing_count);
  if (miss !== null && miss > 0) {
    const tag = document.createElement("span");
    tag.className = "st-miss-n";
    tag.textContent = `未収録${fmtNum(miss)}`;
    wrap.appendChild(tag);
  }
  return wrap;
}

// 出来上がるfileの表。**絵の出し入れで組み直せるように、下見の名乗り(件数の内訳)とは
// 分けてある** ―― 表を描き直すたびにServerの数を作り直すと、planを引いた時点の数と
// 画面の数が別々に動く。
function renderPlanRows() {
  const files = state.exFiles;
  const tbody = $("ex-rows");
  tbody.innerHTML = "";
  setListState($("ex-empty"), "empty");
  // 0件の名乗りは**表が空のときだけ**。fileは1本も出来なくても「fileにならない人」の
  // 行が並ぶことがあり、そこへ「押してください」と重ねると読めなくなる。
  const shown = files.length + (state.exUncovered || []).length
    + (state.exSkipped || []).length;
  $("ex-empty").classList.toggle("hidden", shown > 0);
  // 2段の表なので行は自分で組む。数値列の指定はHTML側のth.numが正で、cellにも同じ列へ
  // numを付ける(付け忘れるとヘッダと値が縦に揃わない)。
  const NUM_COLS = new Set([0, 2, 3, 4, 5]);
  const fragment = document.createDocumentFragment();
  files.forEach((file, index) => {
    const tr = document.createElement("tr");
    tr.className = "row-clickable st-group";
    // 観ている1本を印で示すための鍵。file名はServerが決めた一意な値で、書き出し済みの
    // 一覧(ex-files)から再生した時も同じ値で突き合わせられる。
    if (file.filename) tr.dataset.exfile = file.filename;
    const gifter = gifterNode({ user_nickname: file.nickname, user_unique_id: file.user_unique_id });
    // 順位は#の列に出ているので、名前のtooltipへは足さない(省略された名前の復元だけ)。
    // **行を選ぶ=再生し、その人のgift演出を開く。** 観ている1本の中身を確かめるのがこの面の
    // 用なので、選んだ行の内訳は開いた状態で待っている(利用者の指定)。閉じるのは専用の
    // caretで、選び直しても勝手には畳まない ―― 開け閉ては頻繁に使うので、行の頭
    // (gifterの手前)へ置く。
    const caret = document.createElement("button");
    caret.className = "btn btn-small st-caret";
    caret.type = "button";
    caret.textContent = "▸";
    caret.setAttribute("aria-expanded", "false");
    caret.setAttribute("aria-label", `${file.nickname || "この人"} のgift演出を開く`);
    const name = document.createElement("span");
    name.className = "st-groupname";
    name.append(caret, gifter);
    // 既に書き出してあれば観られる。**書き出した後に中身を確かめる手段が無かった**ので、
    // 別人のgiftが混ざったfileは配ってから気付くしかなかった。
    const output = state.exOutputs.find((o) => o.filename === file.filename) || null;
    const play = document.createElement("button");
    play.className = "btn btn-small st-playbtn";
    play.type = "button";
    play.textContent = "▶";
    play.setAttribute("aria-label", "再生");
    if (!output) {
      play.disabled = true;
    } else {
      play.addEventListener("click", (ev) => {
        ev.stopPropagation();
        openItems();
        playExportFile(output);
      });
    }
    // **書き出す前に、繋いだ順で通して観る。** 素材が複数のハイライトへ跨っていても
    // 続けて流れる。1件ずつの▶(束の中)では繋ぎ目が見えず、繋ぎ目こそが不具合の出る所
    // なので、ここを分けてある。
    const through = document.createElement("button");
    through.className = "btn btn-small st-playbtn";
    through.type = "button";
    through.textContent = "通し";
    const chapters = planChapters(file);
    if (!chapters.length) {
      through.disabled = true;
    } else {
      through.addEventListener("click", (ev) => {
        ev.stopPropagation();
        openItems();
        setExportPlaying(file.filename);
        renderChapters(`${file.filename || file.nickname || ""}（下見）`, chapters);
        startRun(`${file.filename || file.nickname || ""}（下見）`, chapters, "all");
      });
    }
    const plays = document.createElement("span");
    plays.className = "st-playcell";
    plays.append(play, through);
    const cells = [
      // Serverが決めた順位。**file名の先頭に入る数字と同じ**で、置き場を開いたときの
      // 並び順もこれになる(coinの数字だけでは文字列順が額の順にならない)。
      num(file.position) === null ? String(index + 1) : fmtNum(file.position),
      name,
      // **件数はServerが数えた値(`count`)だけを出す。** `items.length` で代用しない ――
      // 連投は畳まずに全件並べるが、時刻順の出力は同じgifterの重なる窓を1つへ畳むので、
      // 「gift 6件 / 6秒」のように件数と尺が比例しない。数え方を画面が持つと、畳み方が
      // 変わった日に予告と成果物が食い違う。名乗られなければ「—」で、数を作らない。
      giftCountNode(file),
      num(file.coin) === null ? "—" : fmtNum(file.coin),
      num(file.diamonds) === null ? "—" : fmtNum(file.diamonds),
      num(file.seconds) === null ? "—" : fmtLen(file.seconds),
      // **file名の列は無い。** 中身は順位・週・週合計🪙・gifterを並べ直した文字列で、
      // どれもこの並びに列として出ている ―― それが表の幅の46%(実測466px)を1列で使い、
      // gifterの列を139pxまで痩せさせて、名前の方を切っていた。実際に付く名前は行を
      // 開いた中で全文を出す(下の buildFileItems の見出し)。
      plays,
    ];
    cells.forEach((cell, col) => {
      const td = document.createElement("td");
      if (NUM_COLS.has(col)) td.className = "num";
      if (cell instanceof Node) td.appendChild(cell);
      else td.textContent = cell;
      tr.appendChild(td);
    });
    const sub = document.createElement("tr");
    sub.className = "st-subrow hidden";
    const subCell = document.createElement("td");
    subCell.colSpan = cells.length;
    subCell.appendChild(buildFileItems(file));
    sub.appendChild(subCell);
    const toggleItems = () => {
      const closed = sub.classList.toggle("hidden");
      tr.classList.toggle("st-group-open", !closed);
      caret.textContent = closed ? "▸" : "▾";
      caret.setAttribute("aria-expanded", String(!closed));
    };
    // 選んだ時に開く側だけを分けて持つ。**閉じているときしか触らない** ―― 開いている行を
    // 選び直すたびに畳むと、caretで開けた物が選択のたびに閉じる。
    const openItems = () => {
      if (sub.classList.contains("hidden")) toggleItems();
    };
    caret.addEventListener("click", (ev) => {
      ev.stopPropagation();
      toggleItems();
    });
    // 行のclick=再生と、その人のgift演出を開く。押した結果は押せば判るので名乗らない。
    // Serverが付けた印だけは、中身を解釈せずそのまま添える。
    if (file.mark) tr.title = String(file.mark);
    tr.addEventListener("click", (ev) => {
      if (ev.target.closest("button, input, select, a")) return;
      openItems();
      playPlanRow(file, output, chapters);
    });
    fragment.append(tr, sub);
  });
  // fileにならない人も同じ表に並べる(行の下に文章の段を作らない)。
  appendNoFileRows(fragment);
  tbody.appendChild(fragment);
  markExportSelection();
}

// いま観ている1本と、その中の1件に印を付ける。**表は組み直さない** ―― 再生のたびに
// 数十行を作り直すと、開いていた束が閉じ、押した行が指の下から消える。
function markExportSelection() {
  const tbody = $("ex-rows");
  if (!tbody) return;
  [...tbody.querySelectorAll("tr.st-group")].forEach((tr) => {
    const here = Boolean(state.exPlayFile) && tr.dataset.exfile === state.exPlayFile;
    tr.classList.toggle("st-current", here);
    // 束の中の行。開いていなければ何も見えないが、開いた時にそのまま印が残る。
    const sub = tr.nextElementSibling;
    if (!sub || !sub.classList.contains("st-subrow")) return;
    [...sub.querySelectorAll(".st-subitem")].forEach((row) => {
      row.classList.toggle("st-subitem-now",
        here && state.exPlayItem !== null
        && String(row.dataset.exitem || "") === String(state.exPlayItem));
    });
  });
}

// 観ている物を覚える。**1箇所でしか書き換えない** ―― 再生の入口は4つ(表の行・▶・
// 束の中の1件・書き出し済みの一覧)あり、どこかが書き忘れると印だけが前の行に残る。
function setExportPlaying(filename, itemId = null) {
  state.exPlayFile = filename || "";
  state.exPlayItem = itemId === undefined ? null : itemId;
  markExportSelection();
}

// 書き出す前に判っていなければならないこと。**Serverが名乗ったfieldだけを数える** ――
// 印の無いgift演出を「大丈夫」として数えると、確かめていない物が確かめた物と同じに見える。
// 出す先は書き出しの確認dialogだけである。常設の警告boxへも同じ文言を出していたが、
// 表の上に居座るだけで押す手が変わらず、読み飛ばされる帯になっていた(利用者の指定で
// 外した) ―― 名乗りは**押した瞬間に、進む/やめるを選べる場所**にだけ置く。
function exportRisks() {
  const items = [];
  state.exFiles.forEach((file) => (file.items || []).forEach((item) => items.push(item)));
  // confidence を1件でも持っていれば、Serverはその印を名乗っている。
  // **「確認済」は数えない。** 印を付ける口を画面から外した以上、全件が未確認になり、
  // 常に出ている帯は目に入らなくなる(利用者の指定)。
  const knowsConfidence = items.some(
    (i) => i.confidence !== undefined && i.confidence !== null);
  return {
    items: items.length,
    knowsConfidence,
    risky: knowsConfidence ? items.filter((i) => !isSure(i.confidence)).length : null,
  };
}

// 下見と書き出しは**同じbody**で投げる。組み立てが2箇所に分かれると、下見で見た束と
// 出来上がるfileが別の条件で作られる。
function exportBody() {
  const body = {
    highlight_ids: [...state.exPicked],
    // 並びは1本の中のgift演出の順。fileを分ける軸はgifterで固定なので、group_by_gifterは
    // 送らない(同じことを2通りに指定できる状態を作らない)。
    order: $("ex-order").value,
  };
  // 誰のfileを作るかを決める週。keyはServerが名乗った物をそのまま返す ―― 画面側で
  // 土曜7時の境界を組み立てると、判定がServerと画面の2箇所に分かれる。
  if (state.exWeek) body.week = state.exWeek;
  // 空欄の項目は送らない。Server側の既定(設定の演出gift下限など)を画面が写し取ると、
  // 設定を変えても画面から起動した分だけ古い値で走る。0は「下限なし」という明示の
  // 指定なので、未指定と同じ扱いにしない。
  const optional = (id, key) => {
    const value = num($(id).value);
    if (value !== null) body[key] = value;
  };
  optional("ex-min", "min_diamonds");
  optional("ex-pad-lead", "pad_lead");
  optional("ex-pad-tail", "pad_tail");
  // ``name`` と ``group_by_gifter`` は送らない ―― Serverが受け付けず422になる。file名は
  // Serverが決め、fileを分ける軸はgifterで固定である(指定できる形にすると、同じことを
  // 2通りに指定できる状態ができる)。
  return body;
}

async function runExport() {
  if (!state.exPicked.size) return;
  // 押す前に名乗る。**押させないのではなく、押す前に判ることが要件**である ―― 別人の
  // giftが別人のfileへ入った事故は、出来上がったmp4を観るまで誰も気付けなかった。
  // 下見を通していない(束が空の)ときは数えられないので、その旨だけを出す。
  const risks = exportRisks();
  const lines = [];
  if (risks.risky) lines.push(`要確認 ${fmtNum(risks.risky)}件`);
  // 印そのものが来ていないときは、そう言う。黙って0件にすると「確かなgift演出ばかりの束」に
  // 見え、確かめる手段が無いことに気付けない。
  if (state.exFiles.length && !risks.knowsConfidence) lines.push("確からしさ 不明");
  if (!state.exFiles.length) lines.push("下見なし");
  if (lines.length) {
    const ok = await confirmDialog(
      `${lines.join(" / ")}。このまま書き出しますか。`,
      { title: "gifterごとの書き出し", confirmLabel: "書き出す" });
    if (!ok) return;
  }
  const btn = $("ex-run");
  btn.disabled = true;
  try {
    await apiSend("POST", "/api/highlights/export", exportBody());
    const files = state.exFiles.length;
    showToast(files ? `${fmtNum(files)}本を順番待ちへ` : "順番待ちへ",
              undefined, { title: "書き出し", duration: JOB_TOAST_MS });
  } catch (err) {
    showError(err, "gifterごとの書き出し");
  } finally {
    updateExportButtons();
  }
}

// ===== 出力: 出来上がりを観る =====

// 置き場に実在する書き出し済みfile。**下見とは別物**で、計画を組まなくても観られる ――
// 先週書き出した物を確かめたいだけの時に、計画を組み直させる理由が無い。
async function loadExportOutputs() {
  const streamer = $("ex-streamer").value;
  const seq = (state.exOutputSeq += 1);
  if (!streamer) {
    state.exOutputs = [];
    renderExportOutputs();
    return;
  }
  const params = new URLSearchParams({ streamer });
  if (state.exWeek) params.set("week", state.exWeek);
  let data;
  try {
    data = await apiSend("GET", `/api/highlights/exports?${params.toString()}`);
  } catch (err) {
    if (seq !== state.exOutputSeq) return;
    // 引けなかったものを「0件」として描かない ―― 置き場に在るのに引けないのと、
    // まだ書き出していないのは別の話である。
    state.exOutputs = [];
    setListState($("ex-files-empty"), "failed", err);
    $("ex-files").innerHTML = "";
    $("ex-files-note").textContent = "";
    showError(err, "書き出し済みのfile");
    return;
  }
  if (seq !== state.exOutputSeq) return;
  state.exOutputs = data.items || [];
  renderExportOutputs();
  // 下見の表にも「観る」が出せるようになる。組んである束があれば描き直す。
  if (state.exFiles.length) renderPlanRows();
}

function renderExportOutputs() {
  const box = $("ex-files");
  const rows = state.exOutputs;
  box.innerHTML = "";
  setListState($("ex-files-empty"), "empty");
  $("ex-files-empty").classList.toggle("hidden", rows.length > 0);
  $("ex-files-note").textContent = rows.length ? fmtNum(rows.length) : "";
  rows.forEach((row) => {
    const btn = document.createElement("button");
    btn.className = "st-pick st-filepick";
    btn.type = "button";
    const body = document.createElement("span");
    body.className = "st-pick-body";
    const name = document.createElement("span");
    name.className = "st-pick-name";
    // 順位とgifterだけを1行で。file名の全文はtooltipで読ませる(縦paneの幅では
    // 省略された文字列が並ぶだけで、どのfileか判らない)。
    name.textContent = [num(row.position) === null ? "" : `${fmtNum(row.position)}.`,
                        row.nickname || row.filename].filter(Boolean).join(" ");
    const meta = document.createElement("span");
    meta.className = "st-pick-meta";
    meta.textContent = [num(row.coin) === null ? "" : `🪙${fmtCompact(row.coin)}`,
                        num(row.bytes) === null ? "" : fmtBytes(row.bytes)]
      .filter(Boolean).join(" / ");
    body.append(name, meta);
    btn.appendChild(body);
    // 省略された値の復元(全文のfile名とpath)。未検証は色(.st-risk)と短い印で名乗る。
    btn.title = `${row.filename}\n${row.path || ""}`
      + (row.verified === false ? "\n⚠ 未検証" : "");
    if (row.verified === false) btn.classList.add("st-risk");
    btn.addEventListener("click", () => playExportFile(row));
    box.appendChild(btn);
  });
}

// 出力の表の行をclickしたとき。**行が指しているのは「出来上がる1本」**なので、実物が
// 在るならそれを、まだ無いなら繋ぐ順の下見を出す ―― 書き出し前の行を押して何も起きない
// と、押した人はbuttonが無いのか壊れているのかを判じられない。
//
// どちらも出せないときは黙らない。**なぜ出せないのか**を名乗るのが、この行の最後の仕事
// である(素材の再生URLが無いのと、繋ぐ窓そのものが無いのは別の話である)。
function playPlanRow(file, output, chapters) {
  if (output) {
    playExportFile(output);
    return;
  }
  if (chapters.length) {
    const name = `${file.filename || file.nickname || ""}（下見）`;
    setExportPlaying(file.filename);
    renderChapters(name, chapters);
    startRun(name, chapters, "all");
    return;
  }
  setFormMessage($("ex-play-status"),
    (file.cuts || []).length ? "素材の再生URLが無い" : "繋ぐ窓が無い", true);
}

// 書き出し済みの1本を右で再生する。
function playExportFile(output) {
  const video = $("ex-video");
  if (!output || !output.url) {
    setFormMessage($("ex-play-status"), "再生URLが無い", true);
    return;
  }
  stopRun();
  setExportPlaying(output.filename);
  setFormMessage($("ex-play-status"), "", false);
  video.src = output.url;
  video.currentTime = 0;
  video.play().catch(() => {});
  // 章は素性のJSONから引く。**再生の後で**引くのは、素性が無いfileでも再生そのものは
  // 成り立つからである(章が出ないだけ)。
  loadOutputChapters(output);
}

// 束を開いた行の1件だけを、素材のハイライトから再生する。**出来上がりの一部を、
// 書き出す前に動く物で確かめる**ための操作。
function playExportItem(file, item, url) {
  const video = $("ex-video");
  // 1件だけを観る操作なので、通し再生は止める。止めないと、この1件の終わりで見張りが
  // 次の窓を始めてしまう。
  // stopRunが前の1件の見張りも外す。**見張りは自分の終端まで来て初めて自分を外す**ので、
  // 終わる前に別の1件へ移ると古い終端の見張りが残り、後でその秒を通り過ぎた再生を
  // 無関係な場所で止める。
  stopRun();
  setExportPlaying(file.filename, item.gift_event_id);
  setFormMessage($("ex-play-status"), "", false);
  const start = num(item.start) || 0;
  const end = num(item.end);
  const begin = () => {
    video.currentTime = start;
    video.play().catch(() => {});
  };
  if (video.getAttribute("src") !== url) {
    video.src = url;
    video.addEventListener("loadedmetadata", begin, { once: true });
  } else begin();
  // 区間の終わりで止める。次のgift演出(=無関係な場面)が続けて流れると、いま何を観ているのか
  // 分からなくなる。見張りはこの1回ぶんだけ張って、終わったら外す。
  if (end === null) return;
  const stop = () => {
    if (video.currentTime < end - PLAY_STOP_SLACK) return;
    video.pause();
    clearExportItemWatch(video);
  };
  exportItemWatch = stop;
  video.addEventListener("timeupdate", stop);
}

// 1件だけの再生に張った見張り。**同時に1つしか居ない** ―― 張り替える所と外す所を
// 1つの変数に畳んでおかないと、どこかの経路で外し忘れた見張りが残る。
let exportItemWatch = null;

function clearExportItemWatch(video) {
  if (!exportItemWatch) return;
  video.removeEventListener("timeupdate", exportItemWatch);
  exportItemWatch = null;
}

// ===== 出力: 通し再生と章 =====
//
// **1本のmp4は3〜8個の窓を繋いだ物である。** 繋ぎ目はmp4の中に印が無く(containerの
// chapterは書いていない)、素材が複数のハイライトへ跨ることもある。ここまで画面に在ったのは
// 「書き出し済みの1本を頭から流す」と「下見の1件だけを素材から流す」の2つで、**これから
// 作る1本を順番どおり通しで確かめる道が無かった。**
//
// 「繋ぎ目だけ」を別に持つのは、不具合が必ず繋ぎ目に出るからである。47秒を通して観るより、
// 接合点の前後だけを拾って流す方が速く確かめられる。

// 通し再生の1コマ。下見は素材のハイライトを跨ぐので窓ごとにurlが変わり、書き出し済みの
// 1本はurlが同じで位置だけが変わる。**どちらも同じ形へ均す** ―― 再生の側に2通りの
// 進み方を持たせると、片方だけが直る。
function planChapters(file) {
  const cuts = (file && file.cuts) || [];
  const chapters = cuts.map((cut, index) => ({
    no: index + 1,
    url: srcUrl(cut.highlight_id),
    start: num(cut.start),
    end: num(cut.end),
    coin: num(cut.diamonds),
    label: cutLabel(cut),
    source: srcName(cut.highlight_id),
  }));
  // **1つでも流せない窓が在れば、通しでは出さない。** 流せる分だけを繋ぐと、抜けたまま
  // 通しで観たものが「出来上がり」として読まれる ―― 抜けたことは画面のどこにも出ない。
  if (chapters.some((ch) => !ch.url || ch.start === null || !(ch.end > ch.start))) {
    return [];
  }
  return chapters;
}

function outputChapters(url, cuts) {
  return (cuts || []).map((cut, index) => ({
    no: index + 1,
    url,
    start: num(cut.at),
    end: (num(cut.at) || 0) + (num(cut.seconds) || 0),
    coin: num(cut.diamonds),
    label: cutLabel(cut),
    source: cut.src || "",
  })).filter((ch) => ch.start !== null && ch.end > ch.start);
}

// 窓1つの名乗り。**giftが複数入る窓が在る**(連投は1つの窓へ畳まれる)ので、先頭のgiftを
// 名乗って残りは件数で足す。名前を持たない窓は「—」にして、それらしい名前を作らない。
function cutLabel(cut) {
  const gifts = cut.gifts || [];
  const first = gifts[0] || null;
  if (!first || !first.gift_name) return "—";
  return first.gift_name + (gifts.length > 1 ? ` ×${fmtNum(gifts.length)}` : "");
}

// 流す範囲の列を作る。``joins`` は接合点の前後だけ ―― 同じ素材で連続していれば1つへ
// 繋いで、無駄なseekを挟まない。
function runRanges(chapters, mode) {
  if (mode !== "joins") {
    return chapters.map((ch) => ({ ...ch, note: `${ch.no}本目` }));
  }
  const out = [];
  for (let i = 0; i + 1 < chapters.length; i += 1) {
    const before = chapters[i];
    const after = chapters[i + 1];
    const lead = { url: before.url, start: Math.max(before.start, before.end - JOIN_LEAD_SECONDS),
                   end: before.end, label: before.label, no: before.no,
                   note: `${before.no}→${after.no}本目の繋ぎ目` };
    const tail = { url: after.url, start: after.start,
                   end: Math.min(after.end, after.start + JOIN_TAIL_SECONDS),
                   label: after.label, no: after.no,
                   note: `${before.no}→${after.no}本目の繋ぎ目` };
    if (lead.url === tail.url && Math.abs(lead.end - tail.start) < CUT_EPSILON) {
      out.push({ ...lead, end: tail.end, label: `${before.label} → ${after.label}` });
    } else {
      out.push(lead, tail);
    }
  }
  return out;
}

function stopRun(message = "") {
  const video = $("ex-video");
  if (state.run) video.pause();
  state.run = null;
  stopRunWatch();
  // 1件だけの再生に張った見張りもここで外す。**再生を始める道は4つ在る**(通し・繋ぎ目・
  // 書き出し済みの1本・1件だけ)ので、外す所を1つに畳んでおかないと、どれかの経路で
  // 古い終端の見張りが生き残る。
  clearExportItemWatch(video);
  $("ex-play-stop").disabled = true;
  $("ex-run-note").textContent = message;
  renderChapterMarks();
}

// 窓の終わりの見張り。**timeupdateだけでは足りない。** 実測でtimeupdateは1秒に4回ほどしか
// 来ないので、窓の終わりに気付くのが最大0.25秒遅れる。montageの繋ぎ目は音の境目の**手前
// から**映像の演出が始まる(:mod:`tictok.media.highlight_switch`)ため、行き過ぎた0.25秒には
// 既に次のgiftの場面が映っている —— 通しで観ている人には「この窓に次のgiftが入っている」
// としか見えず、それこそが確かめる目的を壊す。画面の更新に合わせて見れば1frameで収まる。
//
// timeupdateも残す。画面が隠れている間はrequestAnimationFrameが止まるので、戻ってきた
// ときに送る役が要る。
let runWatch = 0;

function startRunWatch() {
  if (runWatch || typeof requestAnimationFrame !== "function") return;
  const tick = () => {
    runWatch = state.run ? requestAnimationFrame(tick) : 0;
    onRunTick();
  };
  runWatch = requestAnimationFrame(tick);
}

function stopRunWatch() {
  if (runWatch) cancelAnimationFrame(runWatch);
  runWatch = 0;
}

// いま流している窓の名乗り。runStepと、人がシークバーで移った先の両方が同じ文を出す。
function runNote(run) {
  const range = run.ranges[run.index];
  if (!range) return "";
  return `${run.index + 1}/${run.ranges.length}　${range.note}　${range.label}`;
}

// 通し再生を始める。``chapters`` は :func:`planChapters` / :func:`outputChapters` の形。
function startRun(name, chapters, mode, from = 0) {
  if (!chapters.length) {
    setFormMessage($("ex-play-status"), "繋ぐ窓が無い", true);
    return;
  }
  const ranges = runRanges(chapters, mode);
  if (!ranges.length) {
    // 窓が1つしか無いfileには繋ぎ目が無い。**無いことを言う** ―― 黙って何も起きないと、
    // 押した人はbuttonが壊れているのか繋ぎ目が無いのか判らない。
    setFormMessage($("ex-play-status"), "繋ぎ目なし（窓は1つ）", true);
    return;
  }
  setFormMessage($("ex-play-status"), "", false);
  state.run = { name, chapters, ranges, mode,
                index: Math.max(0, Math.min(from, ranges.length - 1)),
                // 次の窓へ送っている最中(srcの差し替え・seekの着地待ち)。この間のtickは
                // 前の窓の位置で走るので読まない。
                pending: false,
                // こちらが送った先。人がシークバーを掴んだのかを見分ける唯一の手掛かりで、
                // seekedのeventはどちらも同じ形で来る。
                seekTo: null };
  $("ex-play-stop").disabled = false;
  runStep();
}

function runStep() {
  const run = state.run;
  if (!run) return;
  if (run.index >= run.ranges.length) {
    stopRun(run.mode === "joins" ? "繋ぎ目 終わり" : "終わり");
    return;
  }
  const range = run.ranges[run.index];
  const at = run.index;
  const video = $("ex-video");
  // **読み込みを待つ間に相手が変わっていたら、飛ばない。** 前の窓のために張った
  // loadedmetadataは、次の窓が始まった後にも1回だけ届く —— そのまま飛ばすと、
  // 押した「繋ぎ目だけ」が直前の通し再生の位置へ戻される。
  const begin = () => {
    if (state.run !== run || run.index !== at) return;
    run.seekTo = range.start;
    video.currentTime = range.start;
    run.pending = false;
    video.play().catch(() => {});
  };
  run.seekTo = range.start;
  if (video.getAttribute("src") !== range.url) {
    video.src = range.url;
    video.addEventListener("loadedmetadata", begin, { once: true });
  } else begin();
  $("ex-run-note").textContent = runNote(run);
  renderChapterMarks();
  startRunWatch();
}

// 窓の終わりで次へ送る。**いま流している窓の位置で走ったtickだけを読む。**
//
// 送っている最中(srcの差し替え中・seekの着地待ち)にもtickは走り、その値は**前の窓の位置**
// である。それを次の窓の判定に使うと、前の窓の終わりが次の窓の終わりより後ろだったときに
// **窓が丸ごと飛ぶ**。montageは素材ごとに別のfileなので、これは普通に起きる —— 実測で
// 2本目(Strong Finish / 36.3〜43.8秒)の次が3本目(Rocket Game / 6.8〜12.9秒)になり、
// 43.8 > 12.9 で3本目が一度も映らないまま「終わりまで観ました」になっていた。
//
// 見分ける条件は3つで、どれも「その窓を流している」ことの必要条件である: 読み込んでいる
// fileがその窓のものであること・seekが着地していること・位置が窓の頭より後ろであること。
function onRunTick() {
  const run = state.run;
  if (!run || run.pending) return;
  const range = run.ranges[run.index];
  const video = $("ex-video");
  if (!range) return;
  if (video.getAttribute("src") !== range.url || video.seeking) return;
  const now = video.currentTime;
  if (now < range.start - RUN_SEEK_SLACK) return;
  // ここまで来たら、送った先へは着いている。seekedを1度も貰えない送り(既にその位置に
  // 居たとき)で覚えたままにすると、次に人が近くを掴んだのを自分の送りと取り違える。
  run.seekTo = null;
  if (now < range.end - PLAY_STOP_SLACK) return;
  run.pending = true;
  video.pause();
  run.index += 1;
  setTimeout(runStep, SEQUENCE_STEP_MS);
}

// 人がシークバーを動かしたとき。**通し再生と綱引きをしない。**
//
// 掴んだ位置を含む窓へ印を移し、そこから続ける。窓の頭へ送り返すと、シークバーを動かす
// たびに元へ戻され、しかも戻された位置が次の窓の終わりを越えていれば窓が次々に送られる
// —— 秒数が飛び回って通しでは確かめられない、という形になる(利用者の指摘)。
//
// どの窓にも入らない位置へ移ったなら、通し再生は止める。掴んだ場所は人が観たい場所なので、
// そこを映したまま自由に観せる方が正しい。
function onRunSeeked() {
  const run = state.run;
  if (!run) return;
  const video = $("ex-video");
  const now = video.currentTime;
  if (run.seekTo !== null && Math.abs(now - run.seekTo) <= RUN_SEEK_SLACK) {
    run.seekTo = null;
    return;
  }
  const url = video.getAttribute("src");
  const index = run.ranges.findIndex(
    (r) => r.url === url && now >= r.start - RUN_SEEK_SLACK && now < r.end);
  if (index < 0) {
    stopRun("窓の外へ移ったので止めました");
    return;
  }
  run.index = index;
  run.pending = false;
  run.seekTo = null;
  $("ex-run-note").textContent = runNote(run);
  renderChapterMarks();
}

// 章の帯。clickでその窓の頭から通しで流し直す。
function renderChapters(name, chapters) {
  const box = $("ex-chapters");
  box.innerHTML = "";
  box.classList.toggle("hidden", chapters.length === 0);
  // 領域は畳まないので、空のときは何を待っているのかをその場に出す。
  $("ex-chapters-empty").classList.toggle("hidden", chapters.length > 0);
  state.chapters = chapters;
  state.chapterName = name;
  $("ex-play-all").disabled = chapters.length === 0;
  $("ex-play-joins").disabled = chapters.length < 2;
  chapters.forEach((ch) => {
    const btn = document.createElement("button");
    btn.className = "st-chapter";
    btn.type = "button";
    const no = document.createElement("span");
    no.className = "st-chapter-no";
    no.textContent = String(ch.no);
    const body = document.createElement("span");
    body.className = "st-chapter-body";
    const label = document.createElement("span");
    label.className = "st-chapter-label";
    label.textContent = ch.label;
    const meta = document.createElement("span");
    meta.className = "st-chapter-meta";
    meta.textContent = [ch.coin === null ? "" : `🪙${fmtCompact(ch.coin)}`,
                        fmtLen(ch.end - ch.start)].filter(Boolean).join(" / ");
    body.append(label, meta);
    btn.append(no, body);
    // 省略された値の復元。札に入り切らないgift名と、出所・範囲の秒だけを持つ。
    btn.title = `${ch.label}\n${ch.source || ""} ${fmtPos(ch.start)}〜${fmtPos(ch.end)}`;
    btn.addEventListener("click", () => startRun(name, chapters, "all", ch.no - 1));
    box.appendChild(btn);
  });
  renderChapterMarks();
}

// いま流れている章。**帯そのものは組み直さない** ―― 窓が変わるたびに数十個のbuttonを
// 作り直すと、clickの取りこぼしが起きる。
function renderChapterMarks() {
  const run = state.run;
  const now = run && run.ranges[run.index];
  [...$("ex-chapters").children].forEach((node, index) => {
    const here = Boolean(now) && now.no === index + 1;
    node.classList.toggle("st-chapter-now", here);
    // 帯は横へscrollする。流れている窓が枠の外へ出たままだと、印を付けても読めない。
    if (here && node.scrollIntoView) {
      node.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
  });
}

// 書き出し済み1本の章を素性のJSONから引く。**素性が無いfileでも再生はできる**ので、
// 章が出せないだけであることを言う(再生を止めない)。
async function loadOutputChapters(output) {
  const streamer = $("ex-streamer").value;
  if (!streamer || !output || !output.filename) {
    renderChapters("", []);
    return;
  }
  const params = new URLSearchParams({ streamer, filename: output.filename });
  let data;
  try {
    data = await apiSend("GET", `/api/highlights/exports/provenance?${params.toString()}`);
  } catch (err) {
    renderChapters("", []);
    showError(err, "書き出したfileの繋ぎ目");
    return;
  }
  if (!data.provenance) {
    renderChapters("", []);
    $("ex-run-note").textContent = "繋ぎ目 不明（素性なし）";
    return;
  }
  const chapters = outputChapters(output.url, data.cuts);
  renderChapters(output.filename, chapters);
  // 素性は在るのに窓が1つも読めない形。**0件として黙って描かない** ―― 章の帯が消えるだけ
  // だと、この1本には繋ぎ目が無いのか、読めなかったのかが人には区別できない。窓ごとの尺を
  // 持たない古い素性(切り終える前の窓一覧を書いていた頃のもの)がこれに当たる。
  if (!chapters.length && (data.cuts || []).length) {
    $("ex-run-note").textContent = `窓 ${fmtNum(data.cuts.length)}・尺なし`;
  }
}

// ===== job =====

// 突き合わせも結合もserverの永続queueで走る。応答はjob_idだけで、進み具合はWSで届く。
// domainはserver側が名乗る名前なので、こちらは「ハイライトのjobか」「結合か」の2つだけを
// 見分ける。知らないdomainには触らない。
function isHighlightJob(job) {
  return Boolean(job && typeof job.domain === "string" && job.domain.startsWith("highlight"));
}

function jobText(job, label) {
  if (job.state === "pending") return `${label} 待ち`;
  if (job.state === "running") return `${label} ${job.stage || ""} ${job.pct}%`.trim();
  if (job.state === "completed") return `${label} 完了${matchOutcome(job)}`;
  return `${label}: ${job.message || job.state}`;
}

// 照合が終わった時の結末。**1本も当たらなかったことを、終わった時点で言う。**
// 候補の窓は「今」から遡って張られるので、窓より古い配信のハイライトは当たらない ――
// 「終わりました」だけを出すと、利用者は一覧を開いてgift演出0件を見るまで気付けず、しかも
// それを見ても「TikTokが選ばなかった」のと区別が付かない。
// **Serverが名乗ったfieldだけを読む。** 古い版のServerは matched_recordings を返さないので、
// そのときは何も足さない(判らないことを「当たり無し」と言わない)。
function matchOutcome(job) {
  const result = job.result || {};
  const hits = result.matched_recordings;
  if (!Array.isArray(hits) || hits.length) return "";
  const tried = Array.isArray(result.days_tried) ? result.days_tried : [];
  return tried.length
    ? `・当たり無し（${tried.map((d) => fmtNum(d)).join("→")}日）` : "・当たり無し";
}

// 結合の結末。件数の内訳はServerが数えた物(job.result.counts)をそのまま出す ――
// 画面が数え直すと、規則が変わった日に予告と成果物が食い違う。
// 帯には短い名乗りだけを置き、内訳と出力先はtooltipとtoastへ回す ―― 全文を帯へ書くと
// 折り返して1行ぶんの帯が増え、その分だけ下の表が読めなくなる。
function exportDone(job) {
  const result = job.result || {};
  const c = result.counts || {};
  const parts = [];
  if (num(c.selected) !== null) parts.push(`${fmtNum(c.selected)}gift演出`);
  if (num(result.diamonds) !== null) parts.push(`🪙${fmtNum(result.diamonds)}`);
  if (num(result.seconds) !== null) parts.push(fmtDuration(result.seconds));
  const dropped = [
    ["対象", c.total], ["除外", c.excluded], ["gift無し", c.no_gift],
    ["下限未満", c.below_min_diamonds], ["重複", c.duplicated],
  ].filter(([, v]) => num(v) !== null).map(([label, v]) => `${label} ${fmtNum(v)}`);
  // 置き場は1つ(gifterごとのfileは同じfolderへ並ぶ)。個々のfile名は下見の表で読める。
  const where = result.output_dir || result.output_path || result.filename || "";
  // 何本できたか。Serverが files を名乗るならその数、無ければ counts.selected までで、
  // 画面が本数を作ることはしない。
  const files = Array.isArray(result.files) ? result.files.length : num(result.file_count);
  const head = files === null || files === undefined ? "完了" : `完了 ${fmtNum(files)}本`;
  const short = `${head}${parts.length ? `（${parts.join(" / ")}）` : ""}`;
  const full = [short, dropped.join(" / "), where].filter(Boolean).join("\n");
  return { short, full };
}

function onJobUpdate(job) {
  if (!isHighlightJob(job)) return;
  const isExport = job.domain.includes("export");
  const label = isExport ? "書き出し" : "照合";
  const done = isExport && job.state === "completed" ? exportDone(job) : null;
  const text = done ? done.full : jobText(job, label);
  if (isExport) {
    $("ex-job").textContent = done ? done.short : text;
    $("ex-job").title = done ? done.full : "";
  } else {
    $("hl-job").textContent = text;
  }
  if (job.state === "completed") {
    showToast(text);
    if (isExport) {
      // 出来上がったfileはその場で観られるようにする ―― 書き出した直後こそ、中身が
      // 正しいかを確かめる時である。
      loadExportOutputs();
    } else {
      // 照合が終わればgift演出も件数も変わる。開いている面は引き直す。
      loadHighlights();
      if (state.cvData) loadCoverage();
    }
  } else if (job.state !== "pending" && job.state !== "running") {
    showToast(job.message || job.state, "error", { title: label });
    if (!isExport) loadHighlights();
  }
}

function onMessage(message) {
  if (message.type === "job_update" && message.job) onJobUpdate(message.job);
}

// ===== 起動 =====

initSegmented("opt-scope");
initSegmented("ex-order");
initSegmented("cv-filter");
initSegmented("cv-order");
// 段が9つあり、意味が「速い/遅い」しか無い群はpillではなくbarで出す(録画画面と同じ形)。
initSegBar("cv-rate");
initSegBar("ex-rate");

VIEWS.forEach((view) => {
  $(`tab-${view}`).addEventListener("click", () => showView(view));
});

bindPanel("hl-opts-toggle", "hl-opts-body", PREF.opts);
bindPanel("ex-opts-toggle", "ex-opts-body", PREF.exOpts);
bindPanel("cv-stats-toggle", "cv-stats", PREF.cvStats);

// dropと同じことをbuttonからもできるようにする。**dropだけにしない** ―― dropはtouchや
// キー操作の利用者には使えない操作である。
$("hl-add").addEventListener("click", () => $("hl-file").click());
$("hl-file").addEventListener("change", async () => {
  const input = $("hl-file");
  const files = Array.from(input.files || []);
  // 同じfileを選び直したときにもchangeが起きるよう、先に空へ戻す。
  input.value = "";
  await uploadHighlights(files);
});
bindDrop();

$("hl-folder-add").addEventListener("click", createWeekFolder);

$("hl-scan").addEventListener("click", scanHighlights);
$("hl-match").addEventListener("click", () => runMatch([...state.picked]));
$("hl-delete").addEventListener("click", deletePicked);
$("hl-purge").addEventListener("click", purgeMissing);
$("hl-select-all").addEventListener("change", () => {
  const rows = visibleHighlights();
  if ($("hl-select-all").checked) rows.forEach((h) => state.picked.add(h.id));
  else rows.forEach((h) => state.picked.delete(h.id));
  renderHighlights();
});


$("ex-streamer").addEventListener("change", () => {
  // 別の配信者へ移ったら素材は持ち越さない。持ち越すと、画面には出ていない他人の本が
  // 結合へ渡り、Serverに400で弾かれる。週も選び直しになるので、そこから組み直す。
  state.exPicked.clear();
  state.exAutoWeek = null;
  clearExportPlan();
  renderExportPicks();
});
$("ex-files-reload").addEventListener("click", loadExportOutputs);
$("ex-play-all").addEventListener("click",
  () => startRun(state.chapterName, state.chapters, "all"));
$("ex-play-joins").addEventListener("click",
  () => startRun(state.chapterName, state.chapters, "joins"));
$("ex-play-stop").addEventListener("click", () => stopRun(""));
// 窓の終わりの見張り。**通し再生の間だけ働く**(state.run が null なら素通りする)ので、
// 1件だけの再生や手でのseekには影響しない。画面が見えている間の主役は
// :func:`startRunWatch` の方で、これは隠れていた間に進んだぶんを拾う控えである。
$("ex-video").addEventListener("timeupdate", onRunTick);
// 人のseekへ譲る。seekingではなくseekedで見るのは、着地した位置でしか「どの窓へ移ったか」
// を決められないためである。
$("ex-video").addEventListener("seeked", onRunSeeked);
// 最後の窓はfileの終端で終わることがある。timeupdateは終端でぴたりと止まるとは限らない
// ので、endedでも送る。
$("ex-video").addEventListener("ended", () => {
  const run = state.run;
  if (!run || run.pending) return;
  run.pending = true;
  run.index += 1;
  setTimeout(runStep, SEQUENCE_STEP_MS);
});

$("cv-streamer").addEventListener("change", () => {
  // 別の配信者へ移ったら週は選び直す。週keyは配信者ごとに別の窓を指す。
  state.cvWeek = "";
  state.cvStreamer = $("cv-streamer").value;
  loadCoverage();
});
$("cv-week-prev").addEventListener("click", () => stepCoverWeek(-1));
$("cv-week-next").addEventListener("click", () => stepCoverWeek(1));
$("cv-week").addEventListener("change", () => {
  state.cvWeek = $("cv-week").value;
  loadCoverage();
});
$("cv-reload").addEventListener("click", loadCoverage);
// 候補の切り替え。**表示設定ではないのでbindPrefへは載せない** —— 残すのは画面の好みでは
// なく、そのgiftをどの1本で出すかというDBの指定である。
$("cv-hit").addEventListener("change", () => chooseHit($("cv-hit").value));

$("ex-week-prev").addEventListener("click", () => stepWeek(-1));
$("ex-week-next").addEventListener("click", () => stepWeek(1));
$("ex-week").addEventListener("change", () => {
  state.exWeek = $("ex-week").value;
  // 週が変われば対象の顔ぶれも変わる。組んである束は別物になるので捨てる。
  clearExportPlan();
  loadWeeks($("ex-streamer").value);
});
$("ex-plan").addEventListener("click", planExport);
$("ex-run").addEventListener("click", runExport);

// 表示設定の保存はbindPrefへ一本化する(key は tictok.story.<control>)。
bindPref($("hl-status"), PREF.status, renderHighlights);
bindPref($("opt-days"), PREF.days);
bindPref($("opt-scope"), PREF.scope);
bindPref($("opt-gift-lead"), PREF.giftLead);
bindPref($("opt-gift-tail"), PREF.giftTail);
bindPref($("opt-min-diamonds"), PREF.minDiamonds);
bindPref($("opt-window"), PREF.window);
bindPref($("opt-hop"), PREF.hop);
bindPref($("cv-show-strip"), PREF.showStrip, drawTimeline);
bindPref($("cv-autoplay"), PREF.cvAutoplay);
// 再生速度は2つの摘みが**同じkeyを共有する**。どちらで変えても同じ設定が残り、
// もう片方の摘みもそこへ寄る。
bindPref($("cv-rate"), PREF.playRate, () => syncRate("cv-rate"));
bindPref($("ex-rate"), PREF.playRate, () => syncRate("ex-rate"));
// 並び・下限・余白を触ったら、組んである束は別物になる。組み直すまで出しっぱなしに
// しない(画面の束と出来上がるfileが食い違う)。
bindPref($("ex-order"), PREF.exOrder, clearExportPlan);
bindPref($("cv-filter"), PREF.cvFilter, () => renderCoverage());
bindPref($("cv-order"), PREF.cvOrder, () => renderCoverage());
bindPref($("cv-min"), PREF.cvMin, loadCoverage);
bindPref($("ex-pad-lead"), PREF.exPadLead);
bindPref($("ex-pad-tail"), PREF.exPadTail);
// 下限と余白を変えると束の中身が変わる。打ち直した時点で古い束を捨てる。
["ex-min", "ex-pad-lead", "ex-pad-tail"].forEach((id) => {
  $(id).addEventListener("change", clearExportPlan);
});

// 保存してあった速さを両方の摘みへ揃えてから、playerへ入れる。srcを差し替えるたびに
// 1xへ戻るので、読み込みの度にも当て直す。
syncRate("cv-rate");
RATE_VIDEOS.forEach((id) => $(id).addEventListener("loadedmetadata", applyRate));

// iconの絵は後から届く。読めた時点で軸を引き直す入口を共通側へ預ける。
bindTimelineRedraw(drawTimeline);
bindTimeline();
bindCoverKeys();

window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    drawTimeline();
  }, RESIZE_DEBOUNCE_MS);
});

// 前回選んでいた配信者から始める。置き場から消えていればrenderStreamerShelfが「全て」へ戻す。
state.streamer = prefGet(PREF.streamer) || "";

// 前回畳んでいたfolderは畳んだまま始める。棚は利用者が作るものなので、選択肢を画面が
// 持てない —— 覚えるのは「閉じている物の名前」だけで、知らない名前は素通しになる。
restoreFolds();

// 前回見ていたtabで始める。nav遷移はフルリロードなので、残さないと作業の途中で
// 他画面を見に行くたび一覧へ戻される。**照合結果tabは無くなった**ので、保存値が
// そこを指していたら一覧へ落ちる(VIEWSに無い値は復元しない)。
const savedView = prefGet(PREF.view);
if (savedView && VIEWS.includes(savedView)) showView(savedView);

// 左paneの名乗りを最初から出す。一覧が届く前でも「ここに何が出るのか」は読める。
playInList(null);

loadHighlights();
connectWS(onMessage);

// ---- 動画の枠の幅 ----
//
// 動画は**置かれた領域そのもの**を占める(CSS: .st-stage > .vd-mvideo)。そのうえで残るのは
// 領域と映像の**比率の差**である —— 縦動画を列の高さいっぱいに載せると実幅は列より狭く、
// その差がそのまま右の余白になっていた(実測: 列530pxに対し映像383px、利用者の指摘)。
//
// 余白を消すには列の幅を「その動画の実幅」にすればよいが、実幅を決めるのは
// **列の高さ×その動画の比率**で、CSSだけでは出せない(gridの列は行の高さより先に決まる)。
// ここで測って --st-vid-w へ渡す。
//
// **測った差を今の幅へ足す形で寄せる。** 列と映像の間には枠の padding が挟まっており、
// 「高さ×比率」をそのまま列の幅にすると、その padding のぶんだけ映像が細って上下に
// 透明の帯が残る(実測: 列533pxに対し映像517px、要る幅は534px)。差だけを足せば、間に何が
// 挟まっていても1回で寄る。
//
// **幅を決める比率は、面を開いた時点で固定する。** 読み込んだ動画のmetadataが届くたびに
// 引き直していた頃は、列の幅が動くたび右の表も時間軸も一緒にずれ、**再生を始めた瞬間に
// 面全体が一度がくんと揺れていた**(利用者の指摘。実測: 列491px→502px)。
// 比率は前に観た1本のもの(PREF.stageRatio)で、覚えが無い最初の1回だけ既定値を使う。
// 再生で判った比率は**次にこの面を開く時のため**にだけ覚え、今出ている幅には触らない ――
// 比率の違う素材が来た日は、箱を動かす代わりに object-fit:contain の余りを黒として見せる。
// 上限を持たせるのは、窓が極端に縦長のときに動画の実幅が列を食い潰して表が読めなく
// なるのを止めるためで、そこまで来たら余るのは映像の上下の側である。
const STAGE_FITS = [
  { video: "hl-video", col: ".st-liststage", area: ".st-listwrap", limit: ".st-listwrap", share: 0.45 },
  { video: "cv-video", col: ".st-cover > .st-stage", area: ".st-cover", limit: ".st-cover", share: 0.45 },
  // 出力の面も同じ幅にする。**人が棒(splitter)を掴むまでは**、という条件付きである ――
  // CSS側で列は var(--st-exsplit-a, var(--st-vid-w, 25fr)) と書いてあり、掴んだ時点で
  // 人の指定(--st-exsplit-a)が勝つ。割合で始めていた頃は、同じ動画が一覧・検証では
  // 485px、出力では383pxで出ていた(利用者の指摘)。
  { video: "ex-video", col: ".st-exsplit > .st-stage", area: ".st-exsplit", limit: ".st-exsplit", share: 0.45 },
];

// 覚えが無い最初の1回で使う比率。素材はほぼ全てが縦(9:16)なので、**その形で場を用意して
// おく方が、割合(28fr)の箱から1本目で寄り直すより揺れない**。CSS側の同じ既定
// (--st-stage-ar の fallback)と対にして直すこと。
const STAGE_RATIO_DEFAULT = 9 / 16;

// 面の幅を決める比率。前に観た1本のものを使い、覚えが無ければ既定で始める。
function stageRatio() {
  const saved = Number(prefGet(PREF.stageRatio));
  return Number.isFinite(saved) && saved > 0 ? saved : STAGE_RATIO_DEFAULT;
}

// 観た1本の比率を覚える。**今出ている幅には触らない** —— 触ると再生した瞬間に列が動く。
// 反映されるのは次にこの面を開いた時からで、その1回で「空の間の箱の形」と「実際に載る
// 映像の形」が揃う。
function rememberStageRatio(ratio) {
  if (!(ratio > 0)) return;
  const text = String(Math.round(ratio * 1e4) / 1e4);
  if (prefGet(PREF.stageRatio) !== text) prefSet(PREF.stageRatio, text);
}

// 面を開いた時点の比率。**この値は面を閉じるまで変えない**(上の但し書き)。
const STAGE_RATIO = stageRatio();

function fitStageWidth({ el, col, area, limit, share }) {
  // 測るのは常に player である。**空の間もそこに在り、寸法も同じ**なので(CSS: player は
  // 最初から出しておく)、1本目を載せた瞬間に列が跳ねることはない。
  const rect = el.getBoundingClientRect();
  const height = rect.height;
  const ratio = STAGE_RATIO;
  // tabを出していない間は実寸が0になる。開いた時にResizeObserverがもう一度呼ぶ。
  if (!(ratio > 0) || !(height > 0)) return;
  const shown = rect.width;
  const track = col.getBoundingClientRect().width;
  if (!(shown > 0) || !(track > 0)) return;
  const cap = limit.getBoundingClientRect().width * share;
  const next = Math.max(0, Math.min(track + (height * ratio - shown), cap));
  const px = `${Math.round(next)}px`;
  if (area.style.getPropertyValue("--st-vid-w") === px) return;
  area.style.setProperty("--st-vid-w", px);
}

// 面の中の箱(1列に落ちる窓のplayer・出力の面のplayer)も同じ比率で形を決める。**開いた
// 時点で1回だけ**書く —— 再生の途中で書き替えると、そこだけ形が変わって面がちらつく。
document.documentElement.style.setProperty(
  "--st-stage-ar", `${Math.round(STAGE_RATIO * 1e4) / 1e4} / 1`);

// 観た1本の比率は**どの面からでも覚える**(次に開く時の初期値になる)。出力の面は列の幅を
// 動画に合わせないが、比率は同じ素材から採れるので、出力tabしか使わない日でも次の1回で揃う。
["hl-video", "cv-video", "ex-video"].forEach((id) => {
  $(id).addEventListener("loadedmetadata", (ev) => {
    const el = ev.currentTarget;
    if (el.videoWidth > 0 && el.videoHeight > 0) rememberStageRatio(el.videoWidth / el.videoHeight);
  });
});

STAGE_FITS.forEach((spec) => {
  const el = $(spec.video);
  const col = document.querySelector(spec.col);
  const area = document.querySelector(spec.area);
  const limit = document.querySelector(spec.limit);
  if (!el || !col || !area || !limit) return;
  const fit = () => fitStageWidth({ el, col, area, limit, share: spec.share });
  // 高さが変わるたび(窓の伸縮・tabの出し入れ)に引き直す。幅の変化でも呼ばれるが、寄り
  // 切ったら書く値が変わらないので堂々巡りにはならない。
  // **再生では引き直さない**(metadataを待たない) —— playerは空の間も同じ寸法でそこに在り、
  // 幅を決める比率も面を開いた時点で固定してある。
  new ResizeObserver(fit).observe(el);
  fit();
});

// ---- paneの割り方 ----
// 出力の面は 動画 : ギフト : 出来上がるfileの表 の3領域。どれを広げたいかは作業の段階で
// 変わるので、割り方は人が決めて覚えさせる。既定はCSSの 25 : 14 : 61 と同じ位置。
const exsplit = document.querySelector(".st-exsplit");
if (exsplit) {
  bindSplitter3(exsplit, [$("ex-split-a"), $("ex-split-b")],
    "--st-exsplit", "story.split.export3", [0.25, 0.39]);
}

