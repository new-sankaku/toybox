(function (PF) {
'use strict';
const { hexToRgb, rgbToCss, luma01, shade, rgbToHsl, hslToRgb } = PF;
const { A, hasAnchor } = PF;

const STACK_MONO = '"SFMono-Regular",Consolas,"Roboto Mono","Courier New",monospace';
const STACK_CONDENSED = '"Arial Narrow","Helvetica Neue",Arial,"Noto Sans JP",sans-serif';
const STACK_SANS = '"Helvetica Neue",Arial,"Segoe UI",sans-serif';
const STACK_JP = '"Hiragino Kaku Gothic ProN","Yu Gothic","Noto Sans JP",Meiryo,sans-serif';

const PLATFORM_NAMES = [
  'NEXA STATION 7', 'ORBIT BOX X', 'PORTA LINK 2', 'VECTOR PC',
  'CUBE ONE', 'HALO DECK', 'ZENITH VR', 'PRISM ARCADE'
];

const RATING_RANKS = [
  { key: 'A', age: '全年齢対象' },
  { key: 'B', age: '12才以上対象' },
  { key: 'C', age: '15才以上対象' },
  { key: 'D', age: '17才以上対象' },
  { key: 'Z', age: '18才以上対象' }
];

const CORNER_LABELS = ['NEW', 'LIMITED', 'HD REMASTER', '特典付', '完全版', 'Vol.'];

function inkOn(hex) {
  return luma01(hexToRgb(hex)) > 0.55 ? '#12100e' : '#ffffff';
}

function liftInk(hex) {
  const rgb = hexToRgb(hex);
  const l = luma01(rgb);
  if (l >= 0.62) { return rgbToCss(rgb, 0.95); }
  return rgbToCss(shade(rgb, (0.72 - l) * 1.15), 0.95);
}

function fitFont(ctx, text, maxWidth, startPx, weight, stack) {
  let px = startPx;
  ctx.font = weight + ' ' + px + 'px ' + stack;
  let w = ctx.measureText(text).width;
  while (w > maxWidth && px > 4) {
    px = px * Math.max(0.72, maxWidth / w);
    ctx.font = weight + ' ' + px + 'px ' + stack;
    w = ctx.measureText(text).width;
  }
  return px;
}

function box(anchor, W, H) {
  return { x: anchor.x * W, y: anchor.y * H, w: anchor.w * W, h: anchor.h * H };
}

function hairline(ctx, x, y, w, color, thick) {
  ctx.fillStyle = color;
  ctx.fillRect(x, y, w, thick);
}

function drawLetterbox(ctx, W, H, rng) {
  ctx.save();
  const barH = H * rng.range(0.035, 0.070);
  ctx.fillStyle = 'rgba(8,7,6,0.95)';
  ctx.fillRect(0, 0, W, barH);
  ctx.fillRect(0, H - barH, W, barH);
  ctx.restore();
}

function drawBottomGradient(ctx, W, H, rng) {
  ctx.save();
  const g = ctx.createLinearGradient(0, H * rng.range(0.45, 0.62), 0, H);
  g.addColorStop(0, 'rgba(6,5,4,0)');
  g.addColorStop(1, 'rgba(6,5,4,' + rng.range(0.62, 0.88).toFixed(3) + ')');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);
  ctx.restore();
}

function drawTopGradient(ctx, W, H, rng) {
  ctx.save();
  const g = ctx.createLinearGradient(0, 0, 0, H * rng.range(0.28, 0.45));
  g.addColorStop(0, 'rgba(6,5,4,' + rng.range(0.45, 0.75).toFixed(3) + ')');
  g.addColorStop(1, 'rgba(6,5,4,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);
  ctx.restore();
}

function drawSideBand(ctx, W, H, rng) {
  ctx.save();
  const right = rng.chance(0.6);
  const bw = W * rng.range(0.16, 0.24);
  const x = right ? W - bw : 0;
  const g = ctx.createLinearGradient(right ? W : 0, 0, right ? W - bw : bw, 0);
  g.addColorStop(0, 'rgba(6,5,4,0.78)');
  g.addColorStop(1, 'rgba(6,5,4,0)');
  ctx.fillStyle = g;
  ctx.fillRect(x, 0, bw, H);
  ctx.restore();
}

function drawFilmScrim(ctx, W, H, rng) {
  ctx.save();
  const a = box(A('filmScrim'), W, H);
  const g = ctx.createLinearGradient(0, a.y, 0, H);
  g.addColorStop(0, 'rgba(4,4,5,0)');
  g.addColorStop(0.45, 'rgba(4,4,5,' + rng.range(0.62, 0.78).toFixed(3) + ')');
  g.addColorStop(1, 'rgba(4,4,5,' + rng.range(0.88, 0.97).toFixed(3) + ')');
  ctx.fillStyle = g;
  ctx.fillRect(0, a.y, W, H - a.y);
  ctx.restore();
}

function drawBillingPlate(ctx, W, H, rng) {
  ctx.save();
  const a = box(A('billingPlate'), W, H);
  const g = ctx.createLinearGradient(0, a.y - H * 0.03, 0, a.y + H * 0.02);
  g.addColorStop(0, 'rgba(3,3,4,0)');
  g.addColorStop(1, 'rgba(3,3,4,0.96)');
  ctx.fillStyle = g;
  ctx.fillRect(0, a.y - H * 0.03, W, H * 0.05);
  ctx.fillStyle = 'rgba(3,3,4,' + rng.range(0.94, 0.99).toFixed(3) + ')';
  ctx.fillRect(0, a.y + H * 0.02, W, H - a.y - H * 0.02);
  ctx.restore();
}

function drawObi(ctx, W, H, rng, theme) {
  ctx.save();
  const a = box(A('obi'), W, H);
  const color = rng.pick(theme.obiColors);
  ctx.fillStyle = color;
  ctx.fillRect(a.x, a.y, a.w, a.h);
  const dark = luma01(hexToRgb(color)) < 0.55;
  hairline(ctx, 0, a.y, W, 'rgba(0,0,0,0.22)', Math.max(1, H * 0.0022));
  const inner = a.h * 0.022 + H * 0.002;
  hairline(ctx, 0, a.y + inner, W, dark ? 'rgba(255,255,255,0.30)' : 'rgba(30,24,18,0.30)', Math.max(1, H * 0.0012));
  if (hasAnchor('obiBox')) {
    const bx = box(A('obiBox'), W, H);
    ctx.fillStyle = dark ? '#f3efe6' : '#141210';
    ctx.fillRect(bx.x, bx.y, bx.w, bx.h);
  }
  ctx.restore();
}

function drawSpecBand(ctx, W, H, rng, theme) {
  ctx.save();
  const a = box(A('specBand'), W, H);
  const color = rng.pick(theme.plateColors);
  ctx.fillStyle = color;
  ctx.fillRect(a.x, a.y, a.w, a.h);
  const dark = luma01(hexToRgb(color)) < 0.55;
  const rule = dark ? 'rgba(255,255,255,0.42)' : 'rgba(24,20,16,0.42)';
  hairline(ctx, 0, a.y, W, rule, Math.max(1, H * 0.0026));
  hairline(ctx, 0, a.y + a.h * 0.042, W, rule, Math.max(1, H * 0.0010));
  ctx.fillStyle = rng.pick(theme.accentColors);
  ctx.fillRect(rng.chance(0.5) ? 0 : W * rng.range(0.30, 0.58), a.y - H * 0.014, W * rng.range(0.18, 0.44), H * 0.010);
  ctx.fillStyle = dark ? 'rgba(255,255,255,0.22)' : 'rgba(24,20,16,0.22)';
  ctx.fillRect(W * 0.05, a.y + a.h * rng.range(0.24, 0.40), W * 0.90, Math.max(1, H * 0.0010));
  ctx.restore();
}

// 帯の縁に沿わせる。乱数のyに引くと写真の上を横切るだけの線になり、意味を持たない。
const RULE_FOOT_ANCHORS = ['specBand', 'obi', 'avSpecBand', 'gameFoot', 'filmScrim', 'voiceFootBand'];
const RULE_HEAD_ANCHORS = ['seriesBand', 'platformBand', 'voiceTopStrip'];

function firstAnchorRect(names, W, H) {
  for (let i = 0; i < names.length; i++) {
    if (hasAnchor(names[i])) { return box(A(names[i]), W, H); }
  }
  return null;
}

function drawHairRules(ctx, W, H, rng, theme) {
  const foot = firstAnchorRect(RULE_FOOT_ANCHORS, W, H);
  const head = firstAnchorRect(RULE_HEAD_ANCHORS, W, H);
  if (!foot && !head) { return; }
  ctx.save();
  const c = hexToRgb(rng.pick(theme.accentColors));
  const t = Math.max(1, H * 0.0018);
  const gap = t * 2.4;
  ctx.fillStyle = rgbToCss(c, 0.85);
  if (head) {
    const y = head.y + head.h + H * rng.range(0.008, 0.020);
    ctx.fillRect(0, y, W, t);
    ctx.fillRect(0, y + gap, W, t * 0.6);
  }
  if (foot) {
    const y = foot.y - H * rng.range(0.008, 0.020);
    ctx.fillRect(0, y - t, W, t);
    ctx.fillRect(0, y - t - gap, W, t * 0.6);
  }
  ctx.restore();
}

function roundRectPath(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.arcTo(x + w, y, x + w, y + r, r);
  ctx.lineTo(x + w, y + h - r);
  ctx.arcTo(x + w, y + h, x + w - r, y + h, r);
  ctx.lineTo(x + r, y + h);
  ctx.arcTo(x, y + h, x, y + h - r, r);
  ctx.lineTo(x, y + r);
  ctx.arcTo(x, y, x + r, y, r);
  ctx.closePath();
}

function drawVoiceChrome(ctx, W, H, rng, theme) {
  ctx.save();
  const stripH = H * rng.range(0.026, 0.062);
  const foot = box(A('voiceFootBand'), W, H);
  const strip = { x: 0, y: 0, w: W, h: stripH };
  const stripRgb = hexToRgb(rng.pick(theme.obiColors));
  if (rng.chance(0.55)) {
    ctx.fillStyle = rgbToCss(stripRgb, rng.range(0.62, 0.80));
    ctx.fillRect(0, strip.y, W, strip.h);
  } else {
    strip.h = 0;
  }
  const footRgb = hexToRgb(rng.pick(theme.plateColors));
  ctx.fillStyle = rgbToCss(footRgb, rng.range(0.86, 0.96));
  ctx.fillRect(0, foot.y, W, foot.h);
  const accent = hexToRgb(rng.pick(theme.accentColors));
  hairline(ctx, 0, foot.y, W, rgbToCss(accent, 0.85), Math.max(1, H * 0.0030));
  if (strip.h > 0) {
    hairline(ctx, 0, strip.y + strip.h, W, rgbToCss(accent, 0.55), Math.max(1, H * 0.0018));
  }
  ctx.restore();
}

function mostSaturated(list) {
  let best = list[0];
  let bestS = -1;
  for (let i = 0; i < list.length; i++) {
    const s = rgbToHsl(hexToRgb(list[i]))[1];
    if (s > bestS) { bestS = s; best = list[i]; }
  }
  return best;
}

function drawVoicePill(ctx, W, H, rng, theme, anchor) {
  const a = box(anchor, W, H);
  const r = a.h / 2;
  ctx.save();
  ctx.fillStyle = 'rgba(0,0,0,0.22)';
  roundRectPath(ctx, a.x + a.h * 0.06, a.y + a.h * 0.10, a.w, a.h, r);
  ctx.fill();
  const base = hexToRgb(mostSaturated(theme.ribbonColors));
  const hsl = rgbToHsl(base);
  const fill = hslToRgb([hsl[0], Math.max(hsl[1], 0.55), Math.min(0.72, Math.max(0.55, hsl[2]))]);
  ctx.fillStyle = rgbToCss(fill, rng.range(0.90, 1));
  roundRectPath(ctx, a.x, a.y, a.w, a.h, r);
  ctx.fill();
  const gloss = ctx.createLinearGradient(0, a.y, 0, a.y + a.h);
  gloss.addColorStop(0, 'rgba(255,255,255,0.30)');
  gloss.addColorStop(0.5, 'rgba(255,255,255,0)');
  ctx.fillStyle = gloss;
  roundRectPath(ctx, a.x, a.y, a.w, a.h, r);
  ctx.fill();
  ctx.strokeStyle = luma01(fill) > 0.55 ? 'rgba(32,26,38,0.55)' : 'rgba(255,255,255,0.92)';
  ctx.lineWidth = Math.max(2, H * 0.0040);
  roundRectPath(ctx, a.x, a.y, a.w, a.h, r);
  ctx.stroke();
  ctx.restore();
}

function drawCvPlateRight(ctx, W, H, rng, theme) {
  drawVoicePill(ctx, W, H, rng, theme, A('cvPlateRight'));
}

function drawCvPlateLeft(ctx, W, H, rng, theme) {
  drawVoicePill(ctx, W, H, rng, theme, A('cvPlateLeft'));
}

function drawVoiceLogoPlate(ctx, W, H, rng, theme) {
  const a = box(A('voiceLogoPlate'), W, H);
  const r = a.h * 0.20;
  ctx.save();
  ctx.fillStyle = 'rgba(0,0,0,0.16)';
  roundRectPath(ctx, a.x + a.h * 0.05, a.y + a.h * 0.07, a.w, a.h, r);
  ctx.fill();
  const plate = hexToRgb(rng.pick(theme.plateColors));
  ctx.fillStyle = rgbToCss(plate, rng.range(0.88, 0.97));
  roundRectPath(ctx, a.x, a.y, a.w, a.h, r);
  ctx.fill();
  ctx.fillStyle = rgbToCss(hexToRgb(rng.pick(theme.accentColors)), 0.90);
  ctx.fillRect(a.x + a.w * 0.12, a.y + a.h * 0.78, a.w * 0.76, Math.max(1, H * 0.0024));
  ctx.restore();
}

function drawJacketFrame(ctx, W, H, rng, theme) {
  ctx.save();
  const m = Math.max(2, W * rng.range(0.008, 0.014));
  const rgb = hexToRgb(rng.pick(theme.obiColors));
  ctx.strokeStyle = rgbToCss(rgb, 0.85);
  ctx.lineWidth = m;
  ctx.strokeRect(m / 2, m / 2, W - m, H - m);
  ctx.strokeStyle = rgbToCss(hexToRgb(rng.pick(theme.accentColors)), 0.55);
  ctx.lineWidth = Math.max(1, m * 0.28);
  ctx.strokeRect(m * 1.7, m * 1.7, W - m * 3.4, H - m * 3.4);
  ctx.restore();
}

function drawCircleMark(ctx, W, H, rng, theme) {
  ctx.save();
  const a = box(A('circleMark'), W, H);
  const cx = a.x + a.w / 2;
  const cy = a.y + a.w / 2;
  const r = a.w * 0.42;
  const ink = liftInk(rng.pick(theme.accentColors));
  ctx.strokeStyle = ink;
  ctx.fillStyle = ink;
  ctx.lineWidth = Math.max(1, r * 0.10);
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.stroke();
  const points = rng.int(4, 6);
  ctx.beginPath();
  for (let i = 0; i < points * 2; i++) {
    const ang = -Math.PI / 2 + (Math.PI * i) / points;
    const rr = i % 2 === 0 ? r * 0.62 : r * 0.26;
    const px = cx + Math.cos(ang) * rr;
    const py = cy + Math.sin(ang) * rr;
    if (i === 0) { ctx.moveTo(px, py); } else { ctx.lineTo(px, py); }
  }
  ctx.closePath();
  ctx.fill();
  ctx.lineWidth = Math.max(1, r * 0.06);
  ctx.beginPath();
  ctx.moveTo(cx - r * 0.75, cy + r * 1.42);
  ctx.lineTo(cx + r * 0.75, cy + r * 1.42);
  ctx.stroke();
  ctx.restore();
}

function brandColor(hex, rng) {
  const hsl = rgbToHsl(hexToRgb(hex));
  const s = Math.min(0.96, Math.max(0.66, hsl[1] * 1.5 + 0.34));
  return hslToRgb([hsl[0], s, rng.range(0.33, 0.45)]);
}

function signColor(hex, rng) {
  const hsl = rgbToHsl(hexToRgb(hex));
  const light = rng.chance(0.4);
  const s = light
    ? Math.min(0.55, Math.max(0.14, hsl[1] * 0.8 + 0.10))
    : Math.min(0.94, Math.max(0.58, hsl[1] * 1.4 + 0.30));
  return hslToRgb([hsl[0], s, light ? rng.range(0.80, 0.92) : rng.range(0.28, 0.42)]);
}

function splitPlatformName(name) {
  const words = name.split(' ');
  if (words.length < 2) { return [name]; }
  return [words[0], words.slice(1).join(' ')];
}

function trackedWidth(ctx, text, track) {
  return ctx.measureText(text).width + track * Math.max(0, text.length - 1);
}

function fillTracked(ctx, text, cx, y, track) {
  const total = trackedWidth(ctx, text, track);
  let x = cx - total / 2;
  for (let i = 0; i < text.length; i++) {
    const ch = text.charAt(i);
    ctx.fillText(ch, x, y);
    x += ctx.measureText(ch).width + track;
  }
}

function drawConsoleMark(ctx, cx, cy, w, h, color) {
  const r = Math.min(w, h) * 0.26;
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = Math.max(1, h * 0.16);
  roundRectPath(ctx, cx - w / 2, cy - h / 2, w, h, r);
  ctx.stroke();
  ctx.fillStyle = color;
  ctx.fillRect(cx - h * 0.06, cy - h / 2 + h * 0.16, h * 0.12, h * 0.68);
  ctx.restore();
}

function drawGameSpine(ctx, W, H, rgb) {
  ctx.save();
  const w = W * 0.019;
  ctx.fillStyle = rgbToCss(rgb, 1);
  ctx.fillRect(0, 0, w, H);
  ctx.fillStyle = 'rgba(0,0,0,0.32)';
  ctx.fillRect(w - Math.max(1, W * 0.0016), 0, Math.max(1, W * 0.0016), H);
  ctx.restore();
}

function drawPlatformTab(ctx, W, H, rng, theme, rgb) {
  ctx.save();
  const a = box(A('platformTab'), W, H);
  roundRectPath(ctx, a.x, a.y, a.w, a.h, Math.min(a.w, a.h) * 0.15);
  ctx.fillStyle = rgbToCss(rgb, 1);
  ctx.fill();
  const lines = splitPlatformName(rng.pick(PLATFORM_NAMES));
  const markH = a.h * 0.30;
  drawConsoleMark(ctx, a.x + a.w / 2, a.y + a.h * 0.30, markH * 1.55, markH, '#ffffff');
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  ctx.fillStyle = '#ffffff';
  const textTop = a.y + a.h * 0.56;
  const step = a.h * 0.24;
  for (let i = 0; i < lines.length; i++) {
    const track = a.w * 0.016;
    let px = fitFont(ctx, lines[i], a.w * 0.80, a.h * 0.20, '800', STACK_CONDENSED);
    while (trackedWidth(ctx, lines[i], track) > a.w * 0.80 && px > 4) {
      px *= 0.94;
      ctx.font = '800 ' + px + 'px ' + STACK_CONDENSED;
    }
    fillTracked(ctx, lines[i], a.x + a.w / 2, textTop + step * i, track);
  }
  ctx.restore();
}

function drawPlatformBand(ctx, W, H, rng, theme, rgb) {
  ctx.save();
  const a = box(A('platformBand'), W, H);
  const g = ctx.createLinearGradient(0, 0, W, 0);
  g.addColorStop(0, rgbToCss(shade(rgb, -0.45), 1));
  g.addColorStop(0.55, rgbToCss(rgb, 1));
  g.addColorStop(1, rgbToCss(shade(rgb, 0.42), 1));
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, a.h);
  ctx.fillStyle = 'rgba(0,0,0,0.30)';
  ctx.fillRect(0, a.h - Math.max(1, H * 0.0022), W, Math.max(1, H * 0.0022));
  const markH = a.h * 0.52;
  drawConsoleMark(ctx, W * 0.048 + markH * 0.78, a.h * 0.50, markH * 1.55, markH, '#ffffff');
  const name = rng.pick(PLATFORM_NAMES);
  const left = W * 0.048 + markH * 1.9;
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  ctx.fillStyle = '#ffffff';
  fitFont(ctx, name, W * 0.38, a.h * 0.44, '800', STACK_CONDENSED);
  ctx.fillText(name, left, a.h * 0.52);
  ctx.restore();
}

function drawRatingBox(ctx, W, H, rng) {
  ctx.save();
  const a = A('ratingPlate');
  const w = W * a.w;
  const h = H * a.h;
  const x = W * a.x;
  const y = H * a.y;
  const rank = rng.pick(RATING_RANKS);
  const edge = Math.max(1.2, w * 0.045);
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(x, y, w, h);
  ctx.strokeStyle = '#111111';
  ctx.lineWidth = edge;
  ctx.strokeRect(x + edge / 2, y + edge / 2, w - edge, h - edge);
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  const headH = h * 0.28;
  ctx.fillStyle = '#111111';
  fitFont(ctx, 'CERO', w * 0.68, headH * 0.62, '700', STACK_CONDENSED);
  ctx.fillText('CERO', x + w / 2, y + headH * 0.60);
  ctx.fillRect(x + edge, y + headH, w - edge * 2, Math.max(1, edge * 0.5));
  const footH = h * 0.20;
  fitFont(ctx, rank.key, w * 0.56, h * 0.52, '700', STACK_SANS);
  ctx.fillText(rank.key, x + w / 2, y + headH + (h - headH - footH) * 0.50);
  ctx.fillRect(x + edge, y + h - footH - edge, w - edge * 2, footH);
  ctx.fillStyle = '#ffffff';
  fitFont(ctx, rank.age, (w - edge * 2) * 0.90, footH * 0.60, '600', STACK_JP);
  ctx.fillText(rank.age, x + w / 2, y + h - footH * 0.50 - edge);
  ctx.restore();
}

function drawGameChrome(ctx, W, H, rng, theme) {
  const rgb = brandColor(rng.pick(theme.ribbonColors), rng);
  if (W / H < 0.66) {
    drawGameSpine(ctx, W, H, rgb);
    drawPlatformTab(ctx, W, H, rng, theme, rgb);
  } else {
    drawPlatformBand(ctx, W, H, rng, theme, rgb);
  }
  ctx.save();
  const foot = H * A('gameFoot').y;
  const g = ctx.createLinearGradient(0, foot, 0, H);
  g.addColorStop(0, 'rgba(8,8,10,0)');
  g.addColorStop(0.55, 'rgba(8,8,10,' + rng.range(0.34, 0.46).toFixed(3) + ')');
  g.addColorStop(1, 'rgba(8,8,10,' + rng.range(0.66, 0.80).toFixed(3) + ')');
  ctx.fillStyle = g;
  ctx.fillRect(0, foot, W, H - foot);
  ctx.restore();
  drawRatingBox(ctx, W, H, rng);
}

function drawKeyartMarks(ctx, W, H, rng, theme) {
  ctx.save();
  const accents = theme.accentColors;
  const cells = rng.int(6, 9);
  const barW = W * rng.range(0.150, 0.260);
  const cellW = barW / cells;
  const barX = rng.chance(0.5) ? W * rng.range(0.055, 0.180) : W - barW - W * rng.range(0.055, 0.180);
  const barY = H * rng.range(0.930, 0.968);
  const barH = H * 0.011;
  for (let i = 0; i < cells; i++) {
    ctx.fillStyle = rgbToCss(hexToRgb(accents[i % accents.length]), rng.range(0.72, 0.95));
    ctx.fillRect(barX + i * cellW, barY, cellW * 0.84, barH);
  }
  ctx.strokeStyle = liftInk(rng.pick(accents));
  ctx.lineWidth = Math.max(1, H * 0.0013);
  const spots = [
    { x: W * rng.range(0.040, 0.130), y: H * rng.range(0.120, 0.320) },
    { x: W * rng.range(0.690, 0.940), y: H * rng.range(0.560, 0.790) }
  ];
  const r = H * 0.020;
  for (let i = 0; i < spots.length; i++) {
    ctx.beginPath();
    ctx.moveTo(spots[i].x - r, spots[i].y);
    ctx.lineTo(spots[i].x + r, spots[i].y);
    ctx.moveTo(spots[i].x, spots[i].y - r);
    ctx.lineTo(spots[i].x, spots[i].y + r);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(spots[i].x, spots[i].y, r * 0.42, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.restore();
}

function drawDiagonalBand(ctx, W, H, rng, theme) {
  ctx.save();
  const a = A('avSash');
  const cx = (a.x + a.w / 2) * W + W * rng.range(-0.06, 0.10);
  const cy = (a.y + a.h / 2) * H + H * rng.range(-0.30, 0.14);
  const bw = a.w * W * rng.range(1.05, 1.45);
  const bh = a.h * H * rng.range(0.82, 1.30);
  const color = rng.pick(theme.ribbonColors);
  const deg = (a.deg == null ? -16 : a.deg) * rng.range(0.35, 1.55) * rng.sign();
  ctx.translate(cx, cy);
  ctx.rotate(deg * Math.PI / 180);
  ctx.fillStyle = 'rgba(0,0,0,0.30)';
  ctx.fillRect(-bw / 2 + bh * 0.10, -bh / 2 + bh * 0.12, bw, bh);
  ctx.fillStyle = color;
  ctx.fillRect(-bw / 2, -bh / 2, bw, bh);
  ctx.fillStyle = 'rgba(255,255,255,0.20)';
  ctx.fillRect(-bw / 2, -bh / 2, bw, bh * 0.20);
  ctx.fillStyle = 'rgba(0,0,0,0.28)';
  ctx.fillRect(-bw / 2, bh / 2 - bh * 0.14, bw, bh * 0.14);
  if (rng.chance(0.6)) {
    ctx.fillStyle = rgbToCss(hexToRgb(rng.pick(theme.accentColors)), 0.9);
    ctx.fillRect(-bw / 2, bh / 2, bw, bh * rng.range(0.10, 0.18));
  }
  ctx.restore();
}

function drawAvLayers(ctx, W, H, rng, theme) {
  ctx.save();
  const series = box(A('seriesBand'), W, H);
  const seriesColor = rng.pick(theme.obiColors);
  ctx.fillStyle = seriesColor;
  ctx.fillRect(0, 0, W, series.h);
  hairline(ctx, 0, series.h, W, rgbToCss(hexToRgb(rng.pick(theme.accentColors)), 0.9), Math.max(1, H * 0.0022));
  ctx.restore();

  drawDiagonalBand(ctx, W, H, rng, theme);

  ctx.save();
  const spec = box(A('avSpecBand'), W, H);
  const specColor = hexToRgb(rng.pick(theme.plateColors));
  const g = ctx.createLinearGradient(0, spec.y, 0, H);
  g.addColorStop(0, rgbToCss(specColor, 0.90));
  g.addColorStop(1, rgbToCss(shade(specColor, -0.20), 0.97));
  ctx.fillStyle = g;
  ctx.fillRect(0, spec.y, W, H - spec.y);
  hairline(ctx, 0, spec.y, W, rgbToCss(hexToRgb(rng.pick(theme.accentColors)), 0.92), Math.max(2, H * 0.0030));
  ctx.restore();
}

function drawAvBottomBar(ctx, W, H, rng, theme) {
  ctx.save();
  const spec = box(A('avSpecBand'), W, H);
  const specColor = hexToRgb(rng.pick(theme.plateColors));
  const g = ctx.createLinearGradient(0, spec.y, 0, H);
  g.addColorStop(0, rgbToCss(specColor, 0.90));
  g.addColorStop(1, rgbToCss(shade(specColor, -0.20), 0.97));
  ctx.fillStyle = g;
  ctx.fillRect(0, spec.y, W, H - spec.y);
  hairline(ctx, 0, spec.y, W, rgbToCss(hexToRgb(rng.pick(theme.accentColors)), 0.92), Math.max(2, H * 0.0030));
  ctx.restore();
}

function drawPlate(ctx, W, H, rng, theme) {
  ctx.save();
  const a = box(A('plate'), W, H);
  const color = rng.pick(theme.plateColors);
  ctx.globalAlpha = rng.range(0.88, 1);
  ctx.fillStyle = color;
  ctx.fillRect(a.x, a.y, a.w, a.h);
  ctx.globalAlpha = 1;
  ctx.strokeStyle = luma01(hexToRgb(color)) > 0.55 ? 'rgba(0,0,0,0.35)' : 'rgba(255,255,255,0.32)';
  ctx.lineWidth = Math.max(1, W * 0.0025);
  ctx.strokeRect(a.x + W * 0.012, a.y + H * 0.008, a.w - W * 0.024, a.h - H * 0.016);
  ctx.restore();
}

function drawFrame(ctx, W, H, rng, theme) {
  ctx.save();
  const m = W * rng.range(0.030, 0.050);
  const accent = rng.pick(theme.accentColors);
  ctx.strokeStyle = rng.chance(0.4) ? rgbToCss(hexToRgb(accent), 0.7) : (rng.chance(0.5) ? 'rgba(255,255,255,0.55)' : 'rgba(20,16,12,0.55)');
  const obi = A('obi');
  const top = obi.y > 0.5 ? m : H * (obi.y + obi.h) + m * 0.6;
  const bottom = obi.y > 0.5 ? H * obi.y - m * 0.4 : H - m;
  ctx.lineWidth = Math.max(1, W * 0.0022);
  ctx.strokeRect(m, top, W - m * 2, bottom - top);
  if (rng.chance(0.5)) {
    const m2 = W * 0.010;
    ctx.lineWidth = Math.max(1, W * 0.0011);
    ctx.strokeRect(m + m2, top + m2, W - (m + m2) * 2, bottom - top - m2 * 2);
  }
  ctx.restore();
}

function drawBoldFrame(ctx, W, H, rng, theme) {
  ctx.save();
  const t = W * rng.range(0.010, 0.020);
  const color = rng.pick(theme.accentColors);
  ctx.fillStyle = color;
  ctx.fillRect(0, 0, W, t);
  ctx.fillRect(0, H - t, W, t);
  ctx.fillRect(0, 0, t, H);
  ctx.fillRect(W - t, 0, t, H);
  ctx.strokeStyle = 'rgba(0,0,0,0.45)';
  ctx.lineWidth = Math.max(1, W * 0.0016);
  ctx.strokeRect(t, t, W - t * 2, H - t * 2);
  ctx.restore();
}

function drawCornerPlate(ctx, W, H, rng, theme) {
  ctx.save();
  const a = box(A('cornerPlate'), W, H);
  const color = signColor(rng.pick(theme.ribbonColors), rng);
  const seed = rng.pick(CORNER_LABELS);
  const label = seed === 'Vol.' ? 'Vol.' + rng.int(1, 9) : seed;
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  fitFont(ctx, label, a.w * 0.72, a.h * 0.46, '700', STACK_JP);
  const track = a.h * 0.07;
  const bw = Math.min(a.w, trackedWidth(ctx, label, track) + a.h * 1.2);
  const bx = a.x + a.w - bw;
  ctx.fillStyle = rgbToCss(color, 1);
  ctx.fillRect(bx, a.y, bw, a.h);
  ctx.strokeStyle = 'rgba(12,12,14,0.35)';
  ctx.lineWidth = Math.max(1, H * 0.0014);
  ctx.strokeRect(bx, a.y, bw, a.h);
  ctx.fillStyle = luma01(color) > 0.55 ? '#12100e' : '#ffffff';
  fillTracked(ctx, label, bx + bw / 2, a.y + a.h * 0.54, track);
  ctx.restore();
}

function drawSealBadge(ctx, W, H, rng, theme) {
  ctx.save();
  const a = box(A('sealBadge'), W, H);
  const r = a.w / 2;
  const cx = a.x + a.w / 2;
  const cy = a.y + a.h / 2;
  const color = rng.pick(theme.ribbonColors);
  ctx.fillStyle = 'rgba(0,0,0,0.22)';
  ctx.beginPath();
  ctx.arc(cx + r * 0.05, cy + r * 0.06, r, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = inkOn(color);
  ctx.globalAlpha = 0.72;
  ctx.lineWidth = Math.max(1, r * 0.05);
  ctx.beginPath();
  ctx.arc(cx, cy, r * 0.86, 0, Math.PI * 2);
  ctx.stroke();
  ctx.restore();
}

function drawLaurelBadge(ctx, W, H, rng, theme) {
  ctx.save();
  const a = box(A('laurelBadge'), W, H);
  const cx = a.x + a.w / 2;
  const base = a.y + a.h * 0.98;
  const ink = liftInk(rng.pick(theme.accentColors));
  const span = a.w * 0.46;
  const rise = a.h * 0.94;
  const leafL = Math.max(2, a.h * 0.115);
  const leafW = Math.max(1, a.h * 0.045);
  ctx.strokeStyle = ink;
  ctx.fillStyle = ink;
  ctx.lineWidth = Math.max(1, a.h * 0.030);
  ctx.lineCap = 'round';
  for (let side = -1; side <= 1; side += 2) {
    const tipX = cx + side * span;
    const ctrlX = cx + side * span * 1.28;
    ctx.beginPath();
    ctx.moveTo(cx + side * a.w * 0.10, base);
    ctx.quadraticCurveTo(ctrlX, base - rise * 0.55, tipX, base - rise);
    ctx.stroke();
    for (let i = 0; i < 6; i++) {
      const t = 0.14 + i * 0.145;
      const mt = 1 - t;
      const px = mt * mt * (cx + side * a.w * 0.10) + 2 * mt * t * ctrlX + t * t * tipX;
      const py = mt * mt * base + 2 * mt * t * (base - rise * 0.55) + t * t * (base - rise);
      const dx = 2 * mt * (ctrlX - (cx + side * a.w * 0.10)) + 2 * t * (tipX - ctrlX);
      const dy = 2 * mt * ((base - rise * 0.55) - base) + 2 * t * ((base - rise) - (base - rise * 0.55));
      const ang = Math.atan2(dy, dx) - side * 0.85;
      ctx.beginPath();
      ctx.ellipse(px + Math.cos(ang) * leafL * 0.55, py + Math.sin(ang) * leafL * 0.55, leafL, leafW, ang, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  ctx.restore();
}

function drawBarcode(ctx, W, H, rng) {
  ctx.save();
  const a = box(A('barcode'), W, H);
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(a.x, a.y, a.w, a.h);
  ctx.fillStyle = '#111111';
  let cx = a.x + a.w * 0.05;
  const limit = a.x + a.w * 0.95;
  while (cx < limit) {
    const bw = Math.max(1, a.w * rng.range(0.004, 0.016));
    ctx.fillRect(cx, a.y + a.h * 0.12, Math.min(bw, limit - cx), a.h * 0.62);
    cx += bw + a.w * rng.range(0.006, 0.020);
  }
  const digits = '4' + rng.int(100000, 999999) + rng.int(1000, 9999);
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  fitFont(ctx, digits, a.w * 0.88, a.h * 0.20, '400', STACK_MONO);
  ctx.fillText(digits, a.x + a.w / 2, a.y + a.h * 0.78);
  ctx.restore();
}


function drawWaveBand(ctx, W, H, rng, theme) {
  ctx.save();
  const a = box(A('waveBand'), W, H);
  const top = a.y;
  const h = a.h;
  const color = rng.pick(theme.accentColors);
  const rgb = hexToRgb(color);
  const mid = top + h / 2;
  const bars = rng.int(38, 68);
  const bw = a.w / bars;
  ctx.fillStyle = rgbToCss(shade(rgb, 0.30), rng.range(0.55, 0.80));
  for (let i = 0; i < bars; i++) {
    const env = Math.sin(Math.PI * (i / bars));
    const amp = (0.14 + 0.86 * Math.pow(rng.next(), 1.5)) * env * h * 0.44;
    ctx.fillRect(a.x + i * bw + bw * 0.22, mid - amp, bw * 0.56, amp * 2);
  }
  ctx.strokeStyle = rgbToCss(shade(rgb, 0.45), 0.40);
  ctx.lineWidth = Math.max(1, H * 0.0012);
  ctx.beginPath();
  ctx.moveTo(a.x, mid);
  ctx.lineTo(a.x + a.w, mid);
  ctx.stroke();
  ctx.restore();
}

function drawDiscSpine(ctx, W, H, rng, theme) {
  ctx.save();
  // anchor 経由で引くことで、文字配置側が占有領域として避けられる
  const a = box(A('discSpine'), W, H);
  const w = a.w;
  const color = rng.pick(theme.obiColors);
  const rgb = hexToRgb(color);
  const g = ctx.createLinearGradient(0, 0, w, 0);
  g.addColorStop(0, rgbToCss(shade(rgb, -0.30), 0.94));
  g.addColorStop(0.65, rgbToCss(rgb, 0.94));
  g.addColorStop(1, rgbToCss(shade(rgb, -0.45), 0.94));
  ctx.fillStyle = g;
  ctx.fillRect(a.x, a.y, w, a.h);
  const accent = hexToRgb(rng.pick(theme.accentColors));
  ctx.fillStyle = rgbToCss(accent, 0.9);
  ctx.fillRect(a.x + w - Math.max(1, w * 0.16), a.y, Math.max(1, w * 0.16), a.h);
  ctx.fillRect(a.x, a.y + a.h * rng.range(0.10, 0.20), w, a.h * rng.range(0.05, 0.09));
  ctx.restore();
}

function drawGridPlate(ctx, W, H, rng, theme) {
  ctx.save();
  const a = box(A('gridPlate'), W, H);
  const color = hexToRgb(rng.pick(theme.plateColors));
  ctx.fillStyle = rgbToCss(color, rng.range(0.14, 0.26));
  ctx.fillRect(a.x, a.y, a.w, a.h);
  const line = luma01(color) > 0.55 ? 'rgba(20,16,12,0.42)' : 'rgba(238,236,232,0.42)';
  ctx.strokeStyle = line;
  ctx.lineWidth = Math.max(1, W * 0.0018);
  ctx.strokeRect(a.x, a.y, a.w, a.h);
  ctx.lineWidth = Math.max(1, W * 0.0010);
  const cols = rng.int(2, 4);
  for (let i = 1; i < cols; i++) {
    const cx = a.x + (a.w / cols) * i;
    ctx.beginPath();
    ctx.moveTo(cx, a.y);
    ctx.lineTo(cx, a.y + a.h);
    ctx.stroke();
  }
  const rows = rng.int(1, 3);
  for (let i = 1; i < rows; i++) {
    const cy = a.y + (a.h / rows) * i;
    ctx.beginPath();
    ctx.moveTo(a.x, cy);
    ctx.lineTo(a.x + a.w, cy);
    ctx.stroke();
  }
  ctx.restore();
}

const SURFACE_FUNCS = {
  letterbox: drawLetterbox,
  bottomGradient: drawBottomGradient,
  topGradient: drawTopGradient,
  sideBand: drawSideBand,
  filmScrim: drawFilmScrim,
  billingPlate: drawBillingPlate,
  obi: drawObi,
  specBand: drawSpecBand,
  hairRules: drawHairRules,
  voiceChrome: drawVoiceChrome,
  cvPlateRight: drawCvPlateRight,
  cvPlateLeft: drawCvPlateLeft,
  voiceLogoPlate: drawVoiceLogoPlate,
  jacketFrame: drawJacketFrame,
  circleMark: drawCircleMark,
  gameChrome: drawGameChrome,
  avLayers: drawAvLayers,
  avBottomBar: drawAvBottomBar,
  platformBand: drawPlatformBand,
  platformTab: drawPlatformTab,
  keyartMarks: drawKeyartMarks,
  ratingBox: drawRatingBox,
  diagonalBand: drawDiagonalBand,
  plate: drawPlate,
  frame: drawFrame,
  boldFrame: drawBoldFrame,
  cornerPlate: drawCornerPlate,
  sealBadge: drawSealBadge,
  laurelBadge: drawLaurelBadge,
  barcode: drawBarcode,
  waveBand: drawWaveBand,
  discSpine: drawDiscSpine,
  gridPlate: drawGridPlate
};

Object.assign(PF, { SURFACE_FUNCS });
})(window.PF = window.PF || {});
