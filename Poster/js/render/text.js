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
const LINE_HEIGHT_TIGHT = 1.14;
const VERT_TRACK_SCALE = 0.4;
const COL_ADVANCE = 1.34;
const EM_ASCENT = 0.82;
const EM_DESCENT = 0.2;
const ARCH_ROT_SCALE = 1.6;
const BOTEN_LIFT = 0.06;
const VERT_SMALL_SHIFT = 0.06;
const VERT_CORNER_SHIFT_X = 0.28;
const VERT_CORNER_SHIFT_Y = 0.3;

function fontSpecOf(weight, size, fontCss) {
  return weight + ' ' + size + 'px ' + fontCss;
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

function layoutHorizontalSlot(ctx, args, spec, scaleX) {
  const slot = args.slot;
  const maxLines = slot.maxLines > 0 ? slot.maxLines : 1;
  const tracking = slot.tracking > 0 ? slot.tracking : 0;
  const maxWidth = (args.rect.w * args.W) / scaleX;
  const minSize = Math.max(MIN_FONT_PX, args.startSize * MIN_SIZE_RATIO);
  let size = args.startSize;
  let lines = null;

  ctx.textAlign = 'left';
  ctx.textBaseline = 'alphabetic';
  for (;;) {
    ctx.font = fontSpecOf(args.weight, size, args.fontCss);
    lines = wrapText(ctx, args.text, maxWidth, tracking * size);
    if (lines.length <= maxLines || size <= minSize) { break; }
    size = Math.max(minSize, size * SHRINK_STEP);
  }
  lines = lines.slice(0, maxLines);
  if (lines.length === 0) { return null; }

  ctx.font = fontSpecOf(args.weight, size, args.fontCss);
  let widest = 0;
  for (let i = 0; i < lines.length; i++) {
    const w = measureTracked(ctx, lines[i], tracking * size);
    if (w > widest) { widest = w; }
  }
  if (widest > maxWidth && widest > 0) {
    size = Math.max(minSize, size * (maxWidth / widest));
    ctx.font = fontSpecOf(args.weight, size, args.fontCss);
  }

  const arch = spec && spec.transform ? spec.transform.arch : 0;
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
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const lineW = measureTracked(ctx, line, tracking * size);
    let x = anchorX;
    if (align === 'center') { x -= lineW / 2; }
    else if (align === 'right') { x -= lineW; }
    const baseY = top + metrics.ascent + i * lh;
    const startX = x;
    for (let j = 0; j < line.length; j++) {
      const ch = line.charAt(j);
      const w = ctx.measureText(ch).width;
      let dy = 0;
      let rot = 0;
      if (arch && lineW > 0) {
        const u = (x + w / 2 - startX) / lineW;
        dy = -arch * size * 4 * (u - u * u);
        rot = arch * ARCH_ROT_SCALE * (2 * u - 1);
      }
      glyphs.push({ ch: ch, x: x, y: baseY + dy, w: w, rot: rot });
      if (baseY + dy - metrics.ascent < minY) { minY = baseY + dy - metrics.ascent; }
      if (baseY + dy + metrics.descent > maxY) { maxY = baseY + dy + metrics.descent; }
      x += w + tracking * size;
    }
    if (startX < minX) { minX = startX; }
    if (startX + lineW > maxX) { maxX = startX + lineW; }
  }

  if (!(maxX > minX)) { return null; }
  return {
    size: size,
    glyphs: glyphs,
    lines: lines,
    vertical: false,
    ascent: metrics.ascent,
    descent: metrics.descent,
    textAlign: 'left',
    textBaseline: 'alphabetic',
    originX: originX,
    fontSpec: fontSpecOf(args.weight, size, args.fontCss),
    box: { x: minX, y: minY, w: maxX - minX, h: maxY - minY }
  };
}

function layoutVerticalSlot(ctx, args, spec, scaleX) {
  const slot = args.slot;
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
  for (let c = 0; c < cols.length; c++) {
    const cx = blockRight - colW * (c + 0.5);
    for (let k = 0; k < cols[c].length; k++) {
      const ch = cols[c].charAt(k);
      const cy = top + k * cell + size / 2;
      let dx = 0;
      let dy = 0;
      let rot = 0;
      if (VERT_ROTATE.indexOf(ch) >= 0) { rot = Math.PI / 2; }
      else if (VERT_CORNER.indexOf(ch) >= 0) { dx = size * VERT_CORNER_SHIFT_X; dy = -size * VERT_CORNER_SHIFT_Y; }
      else if (VERT_SMALL.indexOf(ch) >= 0) { dx = size * VERT_SMALL_SHIFT; dy = -size * VERT_SMALL_SHIFT; }
      glyphs.push({ ch: ch, x: cx + dx, y: cy + dy, w: size, rot: rot, col: cx });
    }
  }
  if (glyphs.length === 0) { return null; }

  return {
    size: size,
    glyphs: glyphs,
    lines: cols,
    vertical: true,
    ascent: size / 2,
    descent: size / 2,
    textAlign: 'center',
    textBaseline: 'middle',
    originX: originX,
    fontSpec: fontSpecOf(args.weight, size, args.fontCss),
    box: { x: blockRight - blockW, y: top, w: blockW, h: colH }
  };
}

function makeEmitter(layout, spec, fontCss) {
  return function (c, mode) {
    if (mode === 'boten') {
      if (!spec || !spec.boten) { return; }
      const ms = layout.size * spec.boten.size;
      c.font = '400 ' + ms + 'px ' + fontCss;
      c.textAlign = 'center';
      c.textBaseline = 'middle';
      const gap = layout.size * spec.boten.gap;
      for (let i = 0; i < layout.glyphs.length; i++) {
        const g = layout.glyphs[i];
        if (NO_BOTEN.indexOf(g.ch) >= 0) { continue; }
        if (layout.vertical) {
          c.fillText(spec.boten.mark, g.col + layout.size * 0.5 + gap + ms / 2, g.y);
        } else {
          c.fillText(spec.boten.mark, g.x + g.w / 2, g.y - layout.ascent - gap - ms / 2 - layout.size * BOTEN_LIFT);
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
      if (g.rot) {
        c.save();
        if (layout.vertical) {
          c.translate(g.x, g.y);
          c.rotate(g.rot);
          if (stroke) { c.strokeText(g.ch, 0, 0); } else { c.fillText(g.ch, 0, 0); }
        } else {
          c.translate(g.x + g.w / 2, g.y);
          c.rotate(g.rot);
          if (stroke) { c.strokeText(g.ch, -g.w / 2, 0); } else { c.fillText(g.ch, -g.w / 2, 0); }
        }
        c.restore();
      } else if (stroke) {
        c.strokeText(g.ch, g.x, g.y);
      } else {
        c.fillText(g.ch, g.x, g.y);
      }
    }
  };
}

function specFromStyle(style) {
  const spec = {
    fill: { type: 'solid', angle: 0, stops: [{ t: 0, rgb: style.color }, { t: 1, rgb: style.color }] },
    strokes: [], glow: null, dropShadow: null, longShadow: null, bevel: null,
    innerLine: null, plate: null, underline: null, overline: null, boten: null,
    transform: null, edgeSplit: null, axes: ['plain']
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
  if (!args || !args.text || !(args.startSize > 0)) { return null; }
  const spec = args.decor ? args.decor : specFromStyle(args.style);
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

  return { size: layout.size, box: layout.box, lines: layout.lines, vertical: layout.vertical };
}
