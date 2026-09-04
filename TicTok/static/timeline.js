// 時間軸(seek bar)の共通語彙。**同じ物を同じ見た目・同じ操作で出すための1つの実装**である。
//
// 使う面は2つある。
//   ・配信者動画: 録画1本の全尺barと拡大窓(videos.js)
//   ・ストーリー: ハイライト1本の時間軸とgift演出ズーム(story.js)
// どちらも「再生位置を掴む・範囲の端を詰める・その瞬間に何が飛んだかを見る」という同じ
// 作業をする面なので、handleの掴み方も再生位置の描き方も目盛りの刻み方も同じでなければ
// ならない。片方だけを直した日に、もう片方が別の操作感のまま残るのを防ぐために口を1つに
// する —— 画面ごとの事情(何を地に敷くか・iconに何を添えるか)は引数で受ける。
//
// この file はclassic scriptで、common.js の後・各画面のscriptの前に読む。

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
// bar下端のこの帯を印(見どころ・演出区間)専用にあてる。波形やheat、gift演出の面と重ねると、
// どちらが記録した位置なのか読めなくなる。
const MARKER_LANE_PX = 8;
// bar下端の時刻ruler。無いと拡大中に「今どの辺りか」が上のbarへ目を往復しないと
// 分からなくなる。
const RULER_LANE_PX = 14;
// timelineへ載せるgift iconの一辺(px)。録画の全尺barは縦を波形とheatで使い切っているので、
// そちらは更に小さくする。横に重なるiconは高額なものだけ残す(pickIcons)。
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
// 拾い直す(実際の段数は帯の高さが許すぶんだけ)。段を積み過ぎると地に敷いた物が残らない。
const GIFT_MAX_ROWS = 3;
const GIFT_ROW_GAP_PX = 2;
// gift側が使ってよい帯の高さの割合。ここを越えて段を足さない — barの本体は波形やgift演出を
// 読む場所で、giftはその上に載る注記に留める。段は詰まったときだけ使われる(空いていれば
// 全て最上段に載る)ので、この上限は「混んだ場面でどこまで下へ伸ばすか」を決める。
const GIFT_LANE_RATIO = 0.85;

// 目盛りの刻み。人が読める単位だけを並べる(3秒・7秒のような刻みは「今どこか」を数えさせる)。
const RULER_STEPS = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600];

// 測ったbarの矩形とx座標から秒を出す。矩形を引数に取るのは、1回の描画で同じbarを何度も
// 測り直さないため(測り直しはstyleを書いた後だとlayoutの再計算を伴う)。
// 基準はcontent box(clientLeft/clientWidth)にする。描画側は canvas.clientWidth を全尺として
// 描くので、border込みのrectで換算すると描いてある絵と当たる場所が最大1pxずれる。
// 全尺barは3時間×1600pxで1px≒6.7秒あり、端では「山を押したのに数秒ずれた所へ飛ぶ」になる。
function secondsFromRect(el, rect, clientX, duration) {
  if (!isFinite(duration) || duration <= 0) return null;
  const width = el.clientWidth || rect.width;
  const ratio = Math.min(1, Math.max(0, (clientX - rect.left - el.clientLeft) / width));
  return ratio * duration;
}

// pointerに一番近いhandleを返す(許容幅の外ならnull)。開始側を先に判定して即returnすると、
// 短い範囲では終了側が開始側の許容幅に飲まれて永久に掴めない。距離で決める。
function nearestHandle(x, toX, tolerance, inSec, outSec) {
  let mode = null;
  let best = Infinity;
  if (inSec !== null && inSec !== undefined) {
    best = Math.abs(x - toX(inSec));
    mode = "in";
  }
  if (outSec !== null && outSec !== undefined && Math.abs(x - toX(outSec)) <= best) {
    best = Math.abs(x - toX(outSec));
    mode = "out";
  }
  return best <= tolerance ? mode : null;
}

// 再生位置。panelと同系色の細線だと波形にもgift演出の面にも沈んで見失うので、暗い実線を
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

// 挟んだ範囲を帯で示す。切り出す前にどこを抜くのか目で確かめられる。地に敷いた物より後に
// 描かないと帯のtintにhandleが沈んで掴み所が見えなくなる。
// toXは秒→x座標の写像で、全尺barと拡大窓が別の写像を渡してくる。
function drawRangeLane(ctx, width, height, toX, inSec, outSec) {
  ctx.fillStyle = cssTokenAlpha("--line", 0.18);
  ctx.fillRect(0, 0, width, RANGE_LANE_PX);

  const inX = inSec === null || inSec === undefined ? null : toX(inSec);
  const outX = outSec === null || outSec === undefined ? null : toX(outSec);
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

function rulerStep(span) {
  const target = span / 8;
  return RULER_STEPS.find((step) => step >= target) || 7200;
}

// 目盛りは分秒だけで足りる場面が多い。1時間を超える尺だけ時を付ける。
function fmtTick(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const ms = `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return h > 0 ? `${h}:${ms}` : ms;
}

// 下端の時刻ruler。barの本体(bodyBottom)の下へ、刻みと数字を置く。
function drawRuler(ctx, { width, bodyBottom, from, to, toX }) {
  ctx.fillStyle = cssTokenAlpha("--line", 0.35);
  ctx.fillRect(0, bodyBottom, width, 1);
  const step = rulerStep(to - from);
  ctx.fillStyle = "rgba(90, 85, 70, 0.9)";
  ctx.font = '9px "JetBrains Mono", monospace';
  ctx.textAlign = "left";
  ctx.textBaseline = "top";
  for (let t = Math.ceil(from / step) * step; t <= to; t += step) {
    const x = toX(t);
    ctx.fillRect(x, bodyBottom - 3, 1, 3);
    ctx.fillText(fmtTick(t), Math.min(x + 2, width - 34), bodyBottom + 2);
  }
}

// ===== iconの絵 =====
// iconはgift_id別の不変な画像なので、録画やハイライトを跨いで使い回す(同じgiftは配信を
// 跨いで飛ぶ)。鍵はURL —— gift_idで持つと、画面ごとに違うproxy URLを渡された時に
// 「先に読んだ方の絵」が残る。
const iconImages = new Map();

// 読み込みが終わったiconを載せるための描き直し。画面ごとに「barを全部引き直す」入口が
// 違うので、ここでは名前を知らずに呼べるよう登録を受ける。
let timelineRedraw = null;
let iconRedrawQueued = false;

function bindTimelineRedraw(fn) {
  timelineRedraw = fn;
}

// 1件ずつ描き直すと、開いた直後に数十回の再描画が並ぶので1 frameへまとめる。
function scheduleIconRedraw() {
  if (iconRedrawQueued || !timelineRedraw) return;
  iconRedrawQueued = true;
  requestAnimationFrame(() => {
    iconRedrawQueued = false;
    if (timelineRedraw) timelineRedraw();
  });
}

// 先に絵を頼んでおく。取れなかったiconは描かないだけにする(errorでもcompleteは立つので、
// 描く側はnaturalWidthで実体の有無を見る)。
function preloadIcons(urls) {
  urls.forEach((url) => {
    if (!url || iconImages.has(url)) return;
    const img = new Image();
    img.addEventListener("load", scheduleIconRedraw);
    img.src = url;
    iconImages.set(url, img);
  });
}

// 描ける絵。まだ読めていない/取れなかったURLはnull(壊れた絵の箱を置かない)。
function iconImage(url) {
  if (!url) return null;
  if (!iconImages.has(url)) preloadIcons([url]);
  const img = iconImages.get(url);
  return img && img.complete && img.naturalWidth > 0 ? img : null;
}

function giftNameFont() {
  return `${GIFT_NAME_FONT_PX}px "JetBrains Mono", monospace`;
}

// 1件が時間軸上で占める幅。名前を出すときは名前の幅も含める — iconの幅だけで場所を
// 取ると、iconは離れているのに名前どうしが重なる。
function iconEntryWidth(ctx, label, size) {
  if (!label) return size;
  return Math.max(size, ctx.measureText(label).width + 2);
}

// 窓に入るitemを、重ならない位置へ間引いて返す。残すのは重い(rankOfの大きい)ものから
// —— 盛り上がりの主因が先に見える。同じ列に置けないものはrowsで許した段まで下ろし、
// どの段にも入らないものだけを捨てる。返り値は描画順に並べ替えた [{data, x, row, label, w}]。
function pickIcons(ctx, items, { toX, width, size, rows, labelOf, rankOf }) {
  // 幅の実測に使うfontは、実際に名前を描くときと同じものにする(違うfontで測ると、
  // 測った幅より広い名前が並んで重なる)。
  ctx.font = giftNameFont();
  const ranked = items
    .map((data) => {
      const label = labelOf ? labelOf(data) : "";
      return { data, x: toX(data), label, w: iconEntryWidth(ctx, label, size) };
    })
    .filter((entry) => entry.x >= -entry.w && entry.x <= width + entry.w)
    .sort((a, b) => rankOf(b.data) - rankOf(a.data));
  const lanes = [];
  for (let i = 0; i < Math.max(1, rows); i += 1) lanes.push([]);
  const kept = [];
  ranked.forEach((entry) => {
    const row = lanes.findIndex((lane) => lane.every(
      (other) => Math.abs(other.x - entry.x)
        >= (other.w + entry.w) / 2 + GIFT_ICON_GAP_PX));
    if (row < 0) return;
    entry.row = row;
    lanes[row].push(entry);
    kept.push(entry);
  });
  return kept.sort((a, b) => a.x - b.x);
}

// 描くときのtokenは1回の描画につき1度だけ読む。barは再生中ずっと毎frame描き直すので、
// 1件ずつ:rootを読むと件数ぶんのstyle参照が毎frame走る。
function iconInk() {
  return {
    disc: cssTokenAlpha("--line", 0.9),
    discInk: cssToken("--sand-panel"),
    edge: cssTokenAlpha("--sand-panel", 0.95),
    chip: cssTokenAlpha("--sand-panel", 0.85),
    name: cssToken("--ink-strong"),
  };
}

// iconを段へ並べ、そこから真下へ細い線を落とす。iconは横に広く、絵の中心がそのまま
// 時刻には読めないため、線が無いと「いつ飛んだか」が数秒ぶれる。
// 線を先に全部引いてからiconを載せるのは、上の段から落ちる線が下の段のiconを横切る
// ため — 絵の側が勝つ順に描く。
// layout: {top, size, rowH, tickBottom, names, width, imageOf, decorate}
function drawIcons(ctx, picked, layout) {
  const { top, size, rowH, tickBottom, names, width, imageOf, decorate } = layout;
  const entryH = size + (names ? GIFT_NAME_LANE_PX : 0);
  ctx.fillStyle = "rgba(122, 106, 60, 0.35)";
  picked.forEach((entry) => {
    if (!imageOf(entry)) return;
    const bottom = top + (entry.row || 0) * rowH + entryH;
    if (tickBottom > bottom) {
      ctx.fillRect(Math.round(entry.x), bottom, 1, tickBottom - bottom);
    }
  });
  const ink = iconInk();
  picked.forEach((entry) => {
    const img = imageOf(entry);
    if (!img) return;
    const y = top + (entry.row || 0) * rowH;
    ctx.drawImage(img, entry.x - size / 2, y, size, size);
    if (decorate) decorate(ctx, entry, y, size, ink, width);
  });
}

// iconに添える1行。名前は波形やgift演出の面の上に載る。字だけだと線に紛れて読めないので、
// 地色を敷いてから置く。
//
// ``width`` を渡すと、字がbarの端から出ないよう内側へ寄せる。**iconの真下から少しずれるが、
// 切れた字は読めない** —— barの端に飛んだgiftは名前の頭が画面の外へ出ていた(実測: 0秒の
// 位置のgiftで「Travel with You」の頭2文字が消えていた)。iconと時刻は線が名乗るので、
// 名前だけが寄っても指す先は読める。
function drawIconLabel(ctx, label, cx, top, ink, width) {
  ctx.save();
  ctx.font = giftNameFont();
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  const w = ctx.measureText(label).width;
  const x = width ? Math.min(Math.max(cx, w / 2 + 1), width - w / 2 - 1) : cx;
  ctx.fillStyle = ink.chip;
  ctx.fillRect(x - w / 2 - 1, top, w + 2, GIFT_NAME_LANE_PX);
  ctx.fillStyle = ink.name;
  ctx.fillText(label, x, top + 1);
  ctx.restore();
}
