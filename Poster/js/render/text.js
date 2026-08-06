import { paintDecorated } from './decor.js';

const KINSOKU_HEAD = '、。，．・：；？！」』）］｝〉》〕ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮーゝゞ々…‥';
const KINSOKU_TAIL = '「『（［｛〈《〔';
const VERT_ROTATE = 'ー－―‐〜～（）｛｝〔〕【】〈〉《》「」『』［］()[]{}<>＜＞=＝…‥‖｜|~';
const VERT_SMALL = 'ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶ';
const VERT_CORNER = '、。，．';
const NO_BOTEN = ' 　、。，．・「」『』（）ー…‥!！?？';

const MIN_FONT_PX = 8;
const MIN_SIZE_RATIO = 0.28;
const SHRINK_STEP = 0.93;
const LINE_HEIGHT = 1.32;
const LINE_HEIGHT_TIGHT = 1.16;
const VERT_TRACK_SCALE = 0.4;
const COL_ADVANCE = 1.34;
const EM_ASCENT = 0.82;
const EM_DESCENT = 0.2;
const ARCH_ROT_SCALE = 1.6;
const BOTEN_LIFT = 0.06;
const VERT_SMALL_SHIFT = 0.06;
const VERT_CORNER_SHIFT_X = 0.28;
const VERT_CORNER_SHIFT_Y = 0.3;
const SCALE_MIN = 0.25;
const SCALE_MAX = 3;
const SY_MIN = 0.3;
const SY_MAX = 2.4;
const VERT_LATERAL_LIMIT = 0.3;
const LATIN_TIER_MIN = 0.6;
const LATIN_TIER_SCALE = 0.5;
const TIER_LATIN_SYMBOLS = '()（）／/-–—.,:\'"’&+';
const TIERED_RATIOS = [0.75, 1, 0.55, 0.4];
const LINE_GAP_MIN = 0.06;
const ELLIPSIS = '…';
const FIT_STEPS = [
  { track: 1, sx: 1, extra: 0 },
  { track: 0.6, sx: 1, extra: 0 },
  { track: 0.25, sx: 1, extra: 0 },
  { track: 0.25, sx: 0.9, extra: 0 },
  { track: 0.25, sx: 0.82, extra: 0 },
  { track: 0.25, sx: 0.82, extra: 1 }
];

function hash01(n) {
  let x = Math.sin(n * 12.9898) * 43758.5453;
  x -= Math.floor(x);
  return x < 0 ? x + 1 : x;
}

function fontSpecOf(weight, size, fontCss) {
  return weight + ' ' + size + 'px ' + fontCss;
}

function charClass(ch) {
  const c = ch.charCodeAt(0);
  if (c === 32 || c === 0x3000) { return 'sp'; }
  if (c >= 0x30 && c <= 0x39) { return 'num'; }
  if ((c >= 0x41 && c <= 0x5a) || (c >= 0x61 && c <= 0x7a)) { return 'lat'; }
  if (c >= 0x3040 && c <= 0x309f) { return 'hira'; }
  if (c >= 0x30a0 && c <= 0x30ff) { return 'kata'; }
  if ((c >= 0x4e00 && c <= 0x9fff) || (c >= 0x3400 && c <= 0x4dbf)) { return 'kanji'; }
  return 'sym';
}

function phraseBreak(prev, cur) {
  if (prev === null) { return false; }
  if (cur === 'sp' || prev === 'sp') { return true; }
  if (cur === 'sym' || prev === 'sym') { return true; }
  if (prev === cur) { return false; }
  if (prev === 'kanji' && cur === 'hira') { return false; }
  if (prev === 'kata' && cur === 'hira') { return false; }
  if (prev === 'num' && cur === 'lat') { return false; }
  return true;
}

function tokenizeForWrap(text) {
  const tokens = [];
  let buffer = '';
  for (let i = 0; i < text.length; i++) {
    const ch = text.charAt(i);
    const code = ch.charCodeAt(0);
    if (code >= 0x21 && code <= 0x7e) {
      buffer += ch;
    } else {
      if (buffer.length > 0) { tokens.push(buffer); buffer = ''; }
      tokens.push(ch);
    }
  }
  if (buffer.length > 0) { tokens.push(buffer); }
  return tokens;
}

let widthCacheKey = '';
let widthCache = null;

function charWidth(ctx, ch) {
  if (widthCacheKey !== ctx.font) {
    widthCacheKey = ctx.font;
    widthCache = new Map();
  }
  let w = widthCache.get(ch);
  if (w === undefined) {
    w = ctx.measureText(ch).width;
    widthCache.set(ch, w);
  }
  return w;
}

function measureTracked(ctx, text, tracking) {
  let w = 0;
  for (let i = 0; i < text.length; i++) { w += charWidth(ctx, text.charAt(i)); }
  if (text.length > 1) { w += tracking * (text.length - 1); }
  return w;
}

function applyKinsoku(lines) {
  for (let i = 1; i < lines.length; i++) {
    while (lines[i].length > 0 && KINSOKU_HEAD.indexOf(lines[i].charAt(0)) >= 0) {
      lines[i - 1] += lines[i].charAt(0);
      lines[i] = lines[i].substring(1);
    }
    while (lines[i - 1].length > 1 && KINSOKU_TAIL.indexOf(lines[i - 1].charAt(lines[i - 1].length - 1)) >= 0) {
      lines[i] = lines[i - 1].charAt(lines[i - 1].length - 1) + lines[i];
      lines[i - 1] = lines[i - 1].substring(0, lines[i - 1].length - 1);
    }
  }
  const out = [];
  for (let i = 0; i < lines.length; i++) { if (lines[i].length > 0) { out.push(lines[i]); } }
  return out;
}

function wrapText(ctx, text, maxWidth, tracking) {
  const paragraphs = String(text).split('\n');
  const lines = [];
  for (let p = 0; p < paragraphs.length; p++) {
    const tokens = tokenizeForWrap(paragraphs[p]);
    let line = '';
    let lineW = 0;
    for (let i = 0; i < tokens.length; i++) {
      const token = tokens[i];
      const tokenW = measureTracked(ctx, token, tracking);
      const add = line.length === 0 ? tokenW : tokenW + tracking;
      if (line.length > 0 && lineW + add > maxWidth) {
        lines.push(line);
        line = token;
        lineW = tokenW;
      } else {
        line += token;
        lineW += add;
      }
    }
    if (line.length > 0) { lines.push(line); }
  }
  return applyKinsoku(lines);
}

function wrapVertical(text, perColumn) {
  const paragraphs = String(text).split('\n');
  const cols = [];
  for (let p = 0; p < paragraphs.length; p++) {
    const src = paragraphs[p];
    for (let i = 0; i < src.length; i += perColumn) {
      cols.push(src.substring(i, i + perColumn));
    }
  }
  return applyKinsoku(cols);
}

function blockMetrics(ctx, sample, size) {
  const m = ctx.measureText(sample);
  const a = m.actualBoundingBoxAscent;
  const d = m.actualBoundingBoxDescent;
  if (typeof a === 'number' && typeof d === 'number' && (a + d) > 0) {
    return { ascent: a, descent: d > 0 ? d : 0 };
  }
  return { ascent: size * EM_ASCENT, descent: size * EM_DESCENT };
}

function glyphMods(d, i, n, size) {
  const mods = { s: 1, sy: 1, dx: 0, dy: 0, rot: 0, shear: 0 };
  if (!d) { return mods; }
  const u = n > 1 ? (i + 0.5) / n : 0.5;
  const c = 2 * u - 1;
  if (d.arc) {
    mods.dy += -d.arc * size * 4 * (u - u * u);
    mods.rot += d.arc * ARCH_ROT_SCALE * c;
  }
  if (d.wave) { mods.dy += d.wave.amp * size * Math.sin(d.wave.phase + u * Math.PI * 2 * d.wave.freq); }
  if (d.fan) { mods.rot += d.fan * c * 2; mods.dy += c * c * size * d.fan; }
  if (d.stagger) { mods.dy += (i % 3) * d.stagger * size; }
  if (d.trapezoid) { mods.sy *= 1 + d.trapezoid * c; }
  if (d.bulge) { mods.s *= 1 + d.bulge * (1 - c * c); }
  if (d.alternate) { mods.s *= 1 + d.alternate * (i % 2 === 0 ? 1 : -1); }
  if (d.ramp) { mods.s *= 1 + d.ramp * c * 0.5; }
  if (d.shear) { mods.shear += d.shear * (i % 2 === 0 ? 1 : -1); }
  if (d.dropCap && i === 0) { mods.s *= 1 + d.dropCap; }
  if (d.jitter) {
    mods.rot += (hash01(d.seed + i * 3.3) - 0.5) * 2 * d.jitter.rot;
    mods.dx += (hash01(d.seed + i * 7.7) - 0.5) * 2 * d.jitter.off * size;
    mods.dy += (hash01(d.seed + i * 11.1) - 0.5) * 2 * d.jitter.off * size;
    mods.s *= 1 + (hash01(d.seed + i * 5.5) - 0.5) * 2 * d.jitter.scale;
  }
  if (d.shatter && hash01(d.seed + i * 13.7) < d.shatter.ratio) {
    mods.dx += (hash01(d.seed + i * 19.3) - 0.5) * 2 * d.shatter.amp * size;
    mods.dy += (hash01(d.seed + i * 23.1) - 0.5) * 2 * d.shatter.amp * size;
    mods.rot += (hash01(d.seed + i * 29.7) - 0.5) * 0.5;
  }
  mods.s = Math.max(SCALE_MIN, Math.min(SCALE_MAX, mods.s));
  mods.sy = Math.max(SY_MIN, Math.min(SY_MAX, mods.sy));
  return mods;
}

function distortBleedRatio(d) {
  if (!d) { return 0; }
  let b = 0;
  if (d.jitter) { b += d.jitter.off; }
  if (d.shatter) { b += d.shatter.amp; }
  return b;
}

function scaledLineWidth(ctx, line, tracking, distort, size, tier) {
  let w = 0;
  for (let i = 0; i < line.length; i++) {
    w += charWidth(ctx, line.charAt(i)) * glyphMods(distort, i, line.length, size).s * tier;
  }
  if (line.length > 1) { w += tracking * (line.length - 1) * tier; }
  return w;
}

function latinShare(line) {
  let n = 0;
  let total = 0;
  for (let i = 0; i < line.length; i++) {
    const ch = line.charAt(i);
    const cls = charClass(ch);
    if (cls === 'sp') { continue; }
    total++;
    if (cls === 'lat' || cls === 'num') { n++; }
    else if (cls === 'sym' && TIER_LATIN_SYMBOLS.indexOf(ch) >= 0) { n++; }
  }
  return total === 0 ? 0 : n / total;
}

function lineTiers(lines, isTitle, tiered) {
  const t = [];
  if (tiered) {
    for (let i = 0; i < lines.length; i++) {
      t.push(TIERED_RATIOS[Math.min(i, TIERED_RATIOS.length - 1)]);
    }
    return t;
  }
  for (let i = 0; i < lines.length; i++) {
    t.push(isTitle && i > 0 && latinShare(lines[i]) >= LATIN_TIER_MIN ? LATIN_TIER_SCALE : 1);
  }
  return t;
}

function lineAdvance(size, lhFactor, tierPrev, tierCur, metrics) {
  const nominal = size * lhFactor * (tierPrev + tierCur) / 2;
  const minimal = metrics.descent * tierPrev + metrics.ascent * tierCur
    + size * LINE_GAP_MIN * Math.max(tierPrev, tierCur);
  return nominal > minimal ? nominal : minimal;
}

function blockHeight(lines, tiers, size, lhFactor, metrics) {
  if (lines.length === 0) { return 0; }
  let h = metrics.ascent * tiers[0] + metrics.descent * tiers[lines.length - 1];
  for (let i = 1; i < lines.length; i++) {
    h += lineAdvance(size, lhFactor, tiers[i - 1], tiers[i], metrics);
  }
  return h;
}

function transformedSize(w, h, t) {
  let bw = w * (t && t.scaleX ? Math.abs(t.scaleX) : 1);
  let bh = h;
  if (t && t.skewX) { bw += Math.abs(t.skewX) * bh; }
  if (t && t.rotate) {
    const c = Math.abs(Math.cos(t.rotate));
    const sn = Math.abs(Math.sin(t.rotate));
    const nw = bw * c + bh * sn;
    const nh = bw * sn + bh * c;
    bw = nw;
    bh = nh;
  }
  return { w: bw, h: bh };
}

function transformedBounds(box, t) {
  if (!t || (!t.skewX && !t.rotate && (!t.scaleX || t.scaleX === 1))) {
    return { x: box.x, y: box.y, w: box.w, h: box.h };
  }
  const ox = box.x + box.w * (typeof t.originX === 'number' ? t.originX : 0.5);
  const oy = box.y + box.h * (typeof t.originY === 'number' ? t.originY : 0.5);
  const pts = [[box.x, box.y], [box.x + box.w, box.y], [box.x, box.y + box.h], [box.x + box.w, box.y + box.h]];
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  const cos = t.rotate ? Math.cos(t.rotate) : 1;
  const sin = t.rotate ? Math.sin(t.rotate) : 0;
  for (let i = 0; i < pts.length; i++) {
    let px = pts[i][0] - ox;
    let py = pts[i][1] - oy;
    if (t.scaleX && t.scaleX !== 1) { px *= t.scaleX; }
    if (t.skewX) { px -= t.skewX * py; }
    const rx = px * cos - py * sin;
    const ry = px * sin + py * cos;
    const fx = rx + ox;
    const fy = ry + oy;
    if (fx < x0) { x0 = fx; }
    if (fy < y0) { y0 = fy; }
    if (fx > x1) { x1 = fx; }
    if (fy > y1) { y1 = fy; }
  }
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
}

function shiftLayout(glyphs, box, dx, dy) {
  if (!dx && !dy) { return; }
  for (let i = 0; i < glyphs.length; i++) {
    glyphs[i].cx += dx;
    glyphs[i].cy += dy;
    glyphs[i].bx += dx;
    glyphs[i].by += dy;
    if (glyphs[i].col !== undefined) { glyphs[i].col += dx; }
  }
  box.x += dx;
  box.y += dy;
}

function ellipsizeLine(ctx, line, tracking, maxWidth) {
  let out = line;
  if (out.charAt(out.length - 1) !== ELLIPSIS) { out += ELLIPSIS; }
  while (out.length > 1 && measureTracked(ctx, out, tracking) > maxWidth) {
    out = out.substring(0, out.length - 2) + ELLIPSIS;
  }
  return out;
}

function pushRegion(map, key, rect) {
  if (!map[key]) { map[key] = { x: rect.x, y: rect.y, w: rect.w, h: rect.h }; return; }
  const r = map[key];
  const x1 = Math.max(r.x + r.w, rect.x + rect.w);
  const y1 = Math.max(r.y + r.h, rect.y + rect.h);
  r.x = Math.min(r.x, rect.x);
  r.y = Math.min(r.y, rect.y);
  r.w = x1 - r.x;
  r.h = y1 - r.y;
}

function collectRegions(glyphs) {
  const lineMap = {};
  const phraseMap = {};
  const glyphRects = [];
  for (let i = 0; i < glyphs.length; i++) {
    const g = glyphs[i];
    if (g.blank) { continue; }
    const rect = { x: g.bx, y: g.by, w: g.bw, h: g.bh };
    glyphRects.push(rect);
    pushRegion(lineMap, String(g.line), rect);
    pushRegion(phraseMap, String(g.phrase), rect);
  }
  const lines = [];
  const phrases = [];
  const lk = Object.keys(lineMap);
  for (let i = 0; i < lk.length; i++) { lines.push(lineMap[lk[i]]); }
  const pk = Object.keys(phraseMap);
  for (let i = 0; i < pk.length; i++) { phrases.push(phraseMap[pk[i]]); }
  return { glyph: glyphRects, line: lines, phrase: phrases };
}

function boundsOf(glyphs) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (let i = 0; i < glyphs.length; i++) {
    const g = glyphs[i];
    if (g.blank) { continue; }
    if (g.bx < x0) { x0 = g.bx; }
    if (g.by < y0) { y0 = g.by; }
    if (g.bx + g.bw > x1) { x1 = g.bx + g.bw; }
    if (g.by + g.bh > y1) { y1 = g.by + g.bh; }
  }
  if (!(x1 > x0) || !(y1 > y0)) { return null; }
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
}

function tryHorizontal(ctx, args, spec, cfg, env) {
  const rectW = args.rect.w * args.W;
  const availH = args.rect.h * args.H;
  const tracking = env.baseTracking * cfg.track;
  const sxTotal = env.baseScaleX * cfg.sx;
  const maxLinesAllowed = env.maxLines + cfg.extra;
  const tf = { skewX: env.skewX, rotate: env.rotate, scaleX: sxTotal };
  const minSize = Math.max(MIN_FONT_PX, args.startSize * MIN_SIZE_RATIO);
  let size = args.startSize;
  let lines = [];
  let tiers = [];
  let metrics = null;
  let blockH = 0;
  let widest = 0;
  let fits = false;

  for (let pass = 0; pass < 26; pass++) {
    ctx.font = fontSpecOf(args.weight, size, args.fontCss);
    lines = wrapText(ctx, args.text, rectW / sxTotal, tracking * size);
    if (lines.length === 0) { return null; }
    tiers = lineTiers(lines, env.isTitle, env.tiered);
    metrics = blockMetrics(ctx, lines.join(''), size);
    widest = 0;
    for (let i = 0; i < lines.length; i++) {
      const w = scaledLineWidth(ctx, lines[i], tracking * size, env.distort, size, tiers[i]);
      if (w > widest) { widest = w; }
    }
    blockH = blockHeight(lines, tiers, size, env.lhFactor, metrics);
    const raw = widest + env.bleedRatio * size * 2;
    const tb = transformedSize(raw, blockH, tf);
    let over = 1;
    if (lines.length > maxLinesAllowed) { over = 1 / SHRINK_STEP; }
    if (rectW > 0 && tb.w > rectW) { over = Math.max(over, tb.w / rectW); }
    if (availH > 0 && tb.h > availH) { over = Math.max(over, tb.h / availH); }
    if (over <= 1.002 && lines.length <= maxLinesAllowed) { fits = true; break; }
    if (size <= minSize) { break; }
    size = Math.max(minSize, size / over);
  }

  return {
    fits: fits, size: size, lines: lines, tiers: tiers, metrics: metrics,
    blockH: blockH, widest: widest, tracking: tracking, sxTotal: sxTotal,
    maxLinesAllowed: maxLinesAllowed, availH: availH, rectW: rectW
  };
}

function layoutHorizontalSlot(ctx, args, spec, scaleX) {
  const slot = args.slot;
  const distort = spec ? spec.distort : null;
  const tiered = !!slot.tiered;
  const isTitle = slot.decor === 'title' || tiered;
  const tf = spec && spec.transform ? spec.transform : null;
  const env = {
    baseTracking: slot.tracking > 0 ? slot.tracking : 0,
    baseScaleX: scaleX,
    maxLines: slot.maxLines > 0 ? slot.maxLines : 1,
    isTitle: isTitle,
    tiered: tiered,
    distort: distort,
    lhFactor: isTitle ? LINE_HEIGHT_TIGHT : LINE_HEIGHT,
    skewX: tf && tf.skewX ? tf.skewX : 0,
    rotate: tf && tf.rotate ? tf.rotate : 0,
    bleedRatio: distortBleedRatio(distort)
      + (spec && spec.strokes && spec.strokes.length > 0 ? spec.strokes[0].width : 0)
  };

  ctx.textAlign = 'center';
  ctx.textBaseline = 'alphabetic';

  let attempt = null;
  for (let i = 0; i < FIT_STEPS.length; i++) {
    attempt = tryHorizontal(ctx, args, spec, FIT_STEPS[i], env);
    if (!attempt) { return null; }
    if (attempt.fits) { break; }
  }

  let truncated = false;
  let lines = attempt.lines;
  let tiers = attempt.tiers;
  let metrics = attempt.metrics;
  let blockH = attempt.blockH;
  const size = attempt.size;
  const tracking = attempt.tracking;
  const sxTotal = attempt.sxTotal;
  const availH = attempt.availH;
  const rectW = attempt.rectW;

  ctx.font = fontSpecOf(args.weight, size, args.fontCss);
  if (!attempt.fits) {
    if (lines.length > attempt.maxLinesAllowed) {
      lines = lines.slice(0, attempt.maxLinesAllowed);
      truncated = true;
    }
    tiers = lineTiers(lines, env.isTitle, env.tiered);
    metrics = blockMetrics(ctx, lines.join(''), size);
    blockH = blockHeight(lines, tiers, size, env.lhFactor, metrics);
    while (lines.length > 1 && blockH > availH) {
      lines = lines.slice(0, lines.length - 1);
      tiers = lineTiers(lines, env.isTitle, env.tiered);
      metrics = blockMetrics(ctx, lines.join(''), size);
      blockH = blockHeight(lines, tiers, size, env.lhFactor, metrics);
      truncated = true;
    }
    if (truncated) {
      const last = lines.length - 1;
      lines[last] = ellipsizeLine(ctx, lines[last], tracking * size, rectW / sxTotal / tiers[last]);
    }
  }
  if (lines.length === 0) { return null; }

  if (spec && spec.transform) { spec.transform.scaleX = sxTotal; }

  const rectTop = args.rect.y * args.H;
  let top = slot.align === 'top' ? rectTop : rectTop + (availH - blockH) / 2;
  if (top < rectTop) { top = rectTop; }

  const rectLeft = args.rect.x * args.W;
  let align = slot.align;
  let anchorX;
  let originX;
  if (align === 'center') { anchorX = rectLeft + rectW / 2; originX = 0.5; }
  else if (align === 'right') { anchorX = rectLeft + rectW; originX = 1; }
  else { anchorX = rectLeft; align = 'left'; originX = 0; }

  const glyphs = [];
  let phrase = 0;
  let baseY = top + metrics.ascent * tiers[0];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const tier = tiers[i];
    if (i > 0) { baseY += lineAdvance(size, env.lhFactor, tiers[i - 1], tier, metrics); }
    const lineW = scaledLineWidth(ctx, line, tracking * size, distort, size, tier);
    let x = anchorX;
    if (align === 'center') { x -= lineW / 2; }
    else if (align === 'right') { x -= lineW; }
    let prevClass = null;
    phrase++;
    for (let j = 0; j < line.length; j++) {
      const ch = line.charAt(j);
      const cls = charClass(ch);
      if (phraseBreak(prevClass, cls)) { phrase++; }
      prevClass = cls;
      const mods = glyphMods(distort, j, line.length, size);
      const gsx = mods.s * tier;
      const gsy = mods.s * mods.sy * tier;
      const adv = charWidth(ctx, ch) * gsx;
      const cx = x + adv / 2 + mods.dx * tier;
      const cy = baseY + mods.dy * tier;
      const asc = metrics.ascent * gsy;
      const desc = metrics.descent * gsy;
      const bw = Math.max(adv, size * 0.12);
      glyphs.push({
        ch: ch, cx: cx, cy: cy, adv: adv, line: i, phrase: phrase,
        rot: mods.rot, shear: mods.shear, sx: gsx, sy: gsy,
        blank: cls === 'sp',
        bx: cx - bw / 2, by: cy - asc, bw: bw, bh: asc + desc
      });
      x += adv + tracking * size * tier;
    }
  }

  const box = boundsOf(glyphs);
  if (!box) { return null; }
  const rect = { x: rectLeft, y: rectTop, w: rectW, h: availH };
  const outer = transformedBounds(box, spec ? spec.transform : null);
  let dx = 0;
  let dy = 0;
  if (outer.w <= rect.w) {
    if (outer.x < rect.x) { dx = rect.x - outer.x; }
    else if (outer.x + outer.w > rect.x + rect.w) { dx = rect.x + rect.w - (outer.x + outer.w); }
  }
  if (outer.h <= rect.h) {
    if (outer.y < rect.y) { dy = rect.y - outer.y; }
    else if (outer.y + outer.h > rect.y + rect.h) { dy = rect.y + rect.h - (outer.y + outer.h); }
  }
  shiftLayout(glyphs, box, dx, dy);

  return {
    size: size, glyphs: glyphs, lines: lines, vertical: false,
    ascent: metrics.ascent, descent: metrics.descent,
    textAlign: 'center', textBaseline: 'alphabetic', originX: originX,
    fontSpec: fontSpecOf(args.weight, size, args.fontCss),
    regions: collectRegions(glyphs), box: box, blockH: blockH, availH: availH,
    truncated: truncated, rect: rect
  };
}

function layoutVerticalSlot(ctx, args, spec, scaleX) {
  const slot = args.slot;
  const distort = spec ? spec.distort : null;
  const baseMaxCols = slot.maxLines > 0 ? slot.maxLines : 1;
  const baseTrack = (slot.tracking > 0 ? slot.tracking : 0) * VERT_TRACK_SCALE;
  const availH = args.rect.h * args.H;
  const rectW = args.rect.w * args.W;
  const minSize = Math.max(MIN_FONT_PX, args.startSize * MIN_SIZE_RATIO);
  const text = String(args.text);
  let truncated = false;
  let size = args.startSize;
  let cols = [];
  let trackRatio = baseTrack;
  let sxTotal = scaleX;
  let maxCols = baseMaxCols;
  let fitted = false;

  for (let step = 0; step < FIT_STEPS.length && !fitted; step++) {
    trackRatio = baseTrack * FIT_STEPS[step].track;
    sxTotal = scaleX * FIT_STEPS[step].sx;
    maxCols = baseMaxCols + FIT_STEPS[step].extra;
    const availW = rectW / sxTotal;
    size = args.startSize;
    for (let pass = 0; pass < 26; pass++) {
      const cell = size * (1 + trackRatio);
      const perCol = Math.max(1, Math.floor((availH + size * trackRatio) / cell));
      cols = wrapVertical(text, perCol);
      let longestTry = 0;
      for (let i = 0; i < cols.length; i++) { if (cols[i].length > longestTry) { longestTry = cols[i].length; } }
      const ok = cols.length <= maxCols
        && cols.length * size * COL_ADVANCE <= availW
        && longestTry * cell - size * trackRatio <= availH;
      if (ok) { fitted = true; break; }
      if (size <= minSize) { break; }
      size = Math.max(minSize, size * SHRINK_STEP);
    }
  }
  if (cols.length === 0) { return null; }
  if (spec && spec.transform) { spec.transform.scaleX = sxTotal; }
  if (cols.length > maxCols) { cols = cols.slice(0, maxCols); truncated = true; }

  ctx.font = fontSpecOf(args.weight, size, args.fontCss);
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';

  const track = size * trackRatio;
  const cell = size + track;
  const colW = size * COL_ADVANCE;
  const availW = rectW / sxTotal;
  const perColLimit = Math.max(1, Math.floor((availH + track) / cell));
  for (let i = 0; i < cols.length; i++) {
    if (cols[i].length > perColLimit) {
      cols[i] = cols[i].substring(0, perColLimit - 1) + ELLIPSIS;
      truncated = true;
    }
  }
  while (cols.length > 1 && cols.length * colW > availW) {
    cols = cols.slice(0, cols.length - 1);
    truncated = true;
  }
  if (truncated) {
    const lastCol = cols[cols.length - 1];
    if (lastCol.charAt(lastCol.length - 1) !== ELLIPSIS) {
      cols[cols.length - 1] = lastCol.substring(0, Math.max(1, lastCol.length - 1)) + ELLIPSIS;
    }
  }
  const blockW = cols.length * colW;
  const rectLeft = args.rect.x * args.W;
  let blockRight;
  let originX;
  if (slot.align === 'left') { blockRight = rectLeft + blockW; originX = 0; }
  else if (slot.align === 'right') { blockRight = rectLeft + rectW; originX = 1; }
  else { blockRight = rectLeft + rectW / 2 + blockW / 2; originX = 0.5; }

  let longest = 0;
  for (let i = 0; i < cols.length; i++) { if (cols[i].length > longest) { longest = cols[i].length; } }
  const colH = longest * cell - track;
  const rectTop = args.rect.y * args.H;
  let top = slot.align === 'top' ? rectTop : rectTop + (availH - colH) / 2;
  if (top < rectTop) { top = rectTop; }

  const glyphs = [];
  let phrase = 0;
  for (let c = 0; c < cols.length; c++) {
    const colCenter = blockRight - colW * (c + 0.5);
    let prevClass = null;
    phrase++;
    for (let k = 0; k < cols[c].length; k++) {
      const ch = cols[c].charAt(k);
      const cls = charClass(ch);
      if (phraseBreak(prevClass, cls)) { phrase++; }
      prevClass = cls;
      const mods = glyphMods(distort, k, cols[c].length, size);
      const lateral = size * VERT_LATERAL_LIMIT;
      let dx = Math.max(-lateral, Math.min(lateral, mods.dy));
      let dy = mods.dx;
      let rot = mods.rot;
      if (VERT_ROTATE.indexOf(ch) >= 0) { rot += Math.PI / 2; }
      else if (VERT_CORNER.indexOf(ch) >= 0) { dx += size * VERT_CORNER_SHIFT_X; dy -= size * VERT_CORNER_SHIFT_Y; }
      else if (VERT_SMALL.indexOf(ch) >= 0) { dx += size * VERT_SMALL_SHIFT; dy -= size * VERT_SMALL_SHIFT; }
      const cx = colCenter + dx;
      const cy = top + k * cell + size / 2 + dy;
      const half = size * 0.5 * mods.s;
      glyphs.push({
        ch: ch, cx: cx, cy: cy, adv: size * mods.s, line: c, phrase: phrase, col: colCenter,
        rot: rot, shear: mods.shear, sx: mods.s, sy: mods.s * mods.sy,
        blank: cls === 'sp',
        bx: cx - half, by: cy - half * mods.sy, bw: half * 2, bh: half * 2 * mods.sy
      });
    }
  }
  if (glyphs.length === 0) { return null; }
  const box = boundsOf(glyphs);
  if (!box) { return null; }

  return {
    size: size, glyphs: glyphs, lines: cols, vertical: true,
    ascent: size / 2, descent: size / 2,
    textAlign: 'center', textBaseline: 'middle', originX: originX,
    fontSpec: fontSpecOf(args.weight, size, args.fontCss),
    regions: collectRegions(glyphs), box: box, blockH: colH, availH: availH,
    truncated: truncated, rect: { x: rectLeft, y: rectTop, w: rectW, h: availH }
  };
}

function drawGlyph(c, g, stroke) {
  if (!g.rot && !g.shear && g.sx === 1 && g.sy === 1) {
    if (stroke) { c.strokeText(g.ch, g.cx, g.cy); } else { c.fillText(g.ch, g.cx, g.cy); }
    return;
  }
  c.save();
  c.translate(g.cx, g.cy);
  if (g.rot) { c.rotate(g.rot); }
  if (g.shear) { c.transform(1, 0, -g.shear, 1, 0, 0); }
  if (g.sx !== 1 || g.sy !== 1) { c.scale(g.sx, g.sy); }
  if (stroke) { c.strokeText(g.ch, 0, 0); } else { c.fillText(g.ch, 0, 0); }
  c.restore();
}

function makeEmitter(layout, spec, fontCss) {
  const emit = function (c, mode) {
    if (mode === 'boten') {
      if (!spec || !spec.boten) { return; }
      const ms = layout.size * spec.boten.size;
      c.font = '400 ' + ms + 'px ' + fontCss;
      c.textAlign = 'center';
      c.textBaseline = 'middle';
      const gap = layout.size * spec.boten.gap;
      for (let i = 0; i < layout.glyphs.length; i++) {
        const g = layout.glyphs[i];
        if (g.blank || NO_BOTEN.indexOf(g.ch) >= 0) { continue; }
        if (layout.vertical) {
          c.fillText(spec.boten.mark, g.col + layout.size * 0.5 + gap + ms / 2, g.cy);
        } else {
          c.fillText(spec.boten.mark, g.cx, g.by - gap - ms / 2 - layout.size * BOTEN_LIFT);
        }
      }
      return;
    }
    c.font = layout.fontSpec;
    c.textAlign = layout.textAlign;
    c.textBaseline = layout.textBaseline;
    const stroke = mode === 'stroke';
    for (let i = 0; i < layout.glyphs.length; i++) {
      const g = layout.glyphs[i];
      if (g.blank) { continue; }
      drawGlyph(c, g, stroke);
    }
  };
  emit.regions = layout.regions;
  emit.glyphs = layout.glyphs;
  emit.vertical = layout.vertical;
  emit.size = layout.size;
  return emit;
}

function specFromStyle(style) {
  const spec = {
    fill: { type: 'solid', angle: 0, stops: [{ t: 0, rgb: style.color }, { t: 1, rgb: style.color }] },
    strokes: [], glow: null, dropShadow: null, longShadow: null, extrude: null, bevel: null,
    innerLine: null, plate: null, underline: null, overline: null, boten: null,
    edgeSplit: null, misregister: null, splitCut: null, reflection: null, roughEdge: null,
    torn: null, distort: null, transform: null, vertical: false, axes: ['plain']
  };
  if (style.stroke) {
    spec.strokes.push({ width: style.stroke.width, rgb: style.stroke.color, alpha: style.stroke.alpha });
  }
  if (style.shadow) {
    spec.dropShadow = {
      hard: false, rgb: style.shadow.color, alpha: style.shadow.alpha,
      dx: 0, dy: 0.02, blur: style.shadow.blur * 0.25
    };
  }
  return spec;
}

export function drawSlot(ctx, args) {
  if (!args || !args.text || !args.slot || !(args.startSize > 0)) { return null; }
  if (!args.decor && !args.style) { return null; }
  const spec = args.decor ? args.decor : specFromStyle(args.style);
  if (spec.fill && spec.fill.type === 'image' && !spec.fill.source && args.sourceCanvas) {
    spec.fill.source = args.sourceCanvas;
  }
  const scaleX = spec.transform && spec.transform.scaleX > 0 ? spec.transform.scaleX : 1;

  ctx.save();
  const layout = args.slot.vertical
    ? layoutVerticalSlot(ctx, args, spec, scaleX)
    : layoutHorizontalSlot(ctx, args, spec, scaleX);
  ctx.restore();
  if (!layout) { return null; }

  spec.vertical = layout.vertical;
  if (spec.transform) {
    spec.transform.originX = layout.originX;
    spec.transform.originY = 0.5;
  }

  const emitter = makeEmitter(layout, spec, args.fontCss);
  ctx.save();
  paintDecorated(ctx, emitter, layout.box, spec, layout.size);
  ctx.restore();

  return {
    size: layout.size, box: layout.box, lines: layout.lines,
    vertical: layout.vertical, regions: layout.regions,
    blockH: layout.blockH, availH: layout.availH,
    truncated: !!layout.truncated, rect: layout.rect,
    outer: transformedBounds(layout.box, spec.transform)
  };
}
