import { paintDecorated } from './decor.js';

const KINSOKU_HEAD = '、。，．・：；？！」』）］｝〉》〕ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮーゝゞ々…‥';
const KINSOKU_TAIL = '「『（［｛〈《〔';
const VERT_ROTATE = 'ー－―‐〜～（）｛｝〔〕【】〈〉《》「」『』［］()[]{}<>＜＞=＝…‥‖｜|~';
const VERT_SMALL = 'ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶ';
const VERT_CORNER = '、。，．';
const NO_BOTEN = ' 　、。，．・「」『』（）ー…‥!！?？';

const MIN_FONT_PX = 8;
const MIN_SIZE_RATIO = 0.42;
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

function measureTracked(ctx, text, tracking) {
  let w = 0;
  for (let i = 0; i < text.length; i++) { w += ctx.measureText(text.charAt(i)).width; }
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
    for (let i = 0; i < tokens.length; i++) {
      const test = line + tokens[i];
      if (line.length > 0 && measureTracked(ctx, test, tracking) > maxWidth) {
        lines.push(line);
        line = tokens[i];
      } else {
        line = test;
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

function scaledLineWidth(ctx, line, tracking, distort, size) {
  let w = 0;
  for (let i = 0; i < line.length; i++) {
    w += ctx.measureText(line.charAt(i)).width * glyphMods(distort, i, line.length, size).s;
  }
  if (line.length > 1) { w += tracking * (line.length - 1); }
  return w;
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

function layoutHorizontalSlot(ctx, args, spec, scaleX) {
  const slot = args.slot;
  const distort = spec ? spec.distort : null;
  const maxLines = slot.maxLines > 0 ? slot.maxLines : 1;
  const tracking = slot.tracking > 0 ? slot.tracking : 0;
  const maxWidth = (args.rect.w * args.W) / scaleX;
  const minSize = Math.max(MIN_FONT_PX, args.startSize * MIN_SIZE_RATIO);
  let size = args.startSize;
  let lines = null;

  ctx.textAlign = 'center';
  ctx.textBaseline = 'alphabetic';
  for (;;) {
    ctx.font = fontSpecOf(args.weight, size, args.fontCss);
    lines = wrapText(ctx, args.text, maxWidth, tracking * size);
    if (lines.length <= maxLines || size <= minSize) { break; }
    size = Math.max(minSize, size * SHRINK_STEP);
  }
  lines = lines.slice(0, maxLines);
  if (lines.length === 0) { return null; }

  const bleedRatio = distortBleedRatio(distort);
  for (let pass = 0; pass < 4; pass++) {
    ctx.font = fontSpecOf(args.weight, size, args.fontCss);
    let widest = 0;
    for (let i = 0; i < lines.length; i++) {
      const w = scaledLineWidth(ctx, lines[i], tracking * size, distort, size);
      if (w > widest) { widest = w; }
    }
    const need = widest + bleedRatio * size * 2;
    if (need <= maxWidth || size <= minSize || !(need > 0)) { break; }
    size = Math.max(minSize, size * (maxWidth / need));
  }
  ctx.font = fontSpecOf(args.weight, size, args.fontCss);

  const lh = size * (slot.decor === 'title' ? LINE_HEIGHT_TIGHT : LINE_HEIGHT);
  const metrics = blockMetrics(ctx, lines.join(''), size);
  const totalH = lh * (lines.length - 1) + metrics.ascent + metrics.descent;
  const availH = args.rect.h * args.H;
  const rectTop = args.rect.y * args.H;
  let top = slot.align === 'top' ? rectTop : rectTop + (availH - totalH) / 2;
  if (top < rectTop) { top = rectTop; }

  const rectLeft = args.rect.x * args.W;
  const rectW = args.rect.w * args.W;
  let align = slot.align;
  let anchorX;
  let originX;
  if (align === 'center') { anchorX = rectLeft + rectW / 2; originX = 0.5; }
  else if (align === 'right') { anchorX = rectLeft + rectW; originX = 1; }
  else { anchorX = rectLeft; align = 'left'; originX = 0; }

  const glyphs = [];
  let phrase = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const lineW = scaledLineWidth(ctx, line, tracking * size, distort, size);
    let x = anchorX;
    if (align === 'center') { x -= lineW / 2; }
    else if (align === 'right') { x -= lineW; }
    const baseY = top + metrics.ascent + i * lh;
    let prevClass = null;
    phrase++;
    for (let j = 0; j < line.length; j++) {
      const ch = line.charAt(j);
      const cls = charClass(ch);
      if (phraseBreak(prevClass, cls)) { phrase++; }
      prevClass = cls;
      const mods = glyphMods(distort, j, line.length, size);
      const adv = ctx.measureText(ch).width * mods.s;
      const cx = x + adv / 2 + mods.dx;
      const cy = baseY + mods.dy;
      const asc = metrics.ascent * mods.s * mods.sy;
      const desc = metrics.descent * mods.s * mods.sy;
      glyphs.push({
        ch: ch, cx: cx, cy: cy, adv: adv, line: i, phrase: phrase,
        rot: mods.rot, shear: mods.shear, sx: mods.s, sy: mods.s * mods.sy,
        blank: cls === 'sp',
        bx: cx - Math.max(adv, size * 0.12) / 2, by: cy - asc,
        bw: Math.max(adv, size * 0.12), bh: asc + desc
      });
      x += adv + tracking * size;
    }
  }

  const box = boundsOf(glyphs);
  if (!box) { return null; }
  return {
    size: size, glyphs: glyphs, lines: lines, vertical: false,
    ascent: metrics.ascent, descent: metrics.descent,
    textAlign: 'center', textBaseline: 'alphabetic', originX: originX,
    fontSpec: fontSpecOf(args.weight, size, args.fontCss),
    regions: collectRegions(glyphs), box: box
  };
}

function layoutVerticalSlot(ctx, args, spec, scaleX) {
  const slot = args.slot;
  const distort = spec ? spec.distort : null;
  const maxCols = slot.maxLines > 0 ? slot.maxLines : 1;
  const trackRatio = (slot.tracking > 0 ? slot.tracking : 0) * VERT_TRACK_SCALE;
  const availH = args.rect.h * args.H;
  const availW = (args.rect.w * args.W) / scaleX;
  const minSize = Math.max(MIN_FONT_PX, args.startSize * MIN_SIZE_RATIO);
  const text = String(args.text);
  let size = args.startSize;
  let cols = null;

  for (;;) {
    const cell = size * (1 + trackRatio);
    const perCol = Math.max(1, Math.floor((availH + size * trackRatio) / cell));
    cols = wrapVertical(text, perCol);
    let longestTry = 0;
    for (let i = 0; i < cols.length; i++) { if (cols[i].length > longestTry) { longestTry = cols[i].length; } }
    const fits = cols.length <= maxCols
      && cols.length * size * COL_ADVANCE <= availW
      && longestTry * cell - size * trackRatio <= availH;
    if (fits || size <= minSize) { break; }
    size = Math.max(minSize, size * SHRINK_STEP);
  }
  cols = cols.slice(0, maxCols);
  if (cols.length === 0) { return null; }

  ctx.font = fontSpecOf(args.weight, size, args.fontCss);
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';

  const track = size * trackRatio;
  const cell = size + track;
  const colW = size * COL_ADVANCE;
  const blockW = cols.length * colW;
  const rectLeft = args.rect.x * args.W;
  const rectW = args.rect.w * args.W;
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
    regions: collectRegions(glyphs), box: box
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
    vertical: layout.vertical, regions: layout.regions
  };
}
