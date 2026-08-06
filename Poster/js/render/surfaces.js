import { hexToRgb, rgbToCss, luma01, shade, rgbToHsl, hslToRgb } from '../core/color.js';
import { SURFACE_ANCHORS } from './layouts.js';

const STACK_MONO = '"SFMono-Regular",Consolas,"Roboto Mono","Courier New",monospace';
const STACK_CONDENSED = '"Arial Narrow","Helvetica Neue",Arial,"Noto Sans JP",sans-serif';
const STACK_SANS = '"Helvetica Neue",Arial,"Segoe UI",sans-serif';
const STACK_JP = '"Hiragino Kaku Gothic ProN","Yu Gothic","Noto Sans JP",Meiryo,sans-serif';

const PLATFORM_NAMES = [
  'NEXA STATION 7', 'ORBIT BOX X', 'PORTA LINK 2', 'VECTOR PC',
  'CUBE ONE', 'HALO DECK', 'ZENITH VR', 'PRISM ARCADE'
];

const RATING_RANKS = [
  { key: 'A', age: '全年齢対象', color: '#1b1b1b' },
  { key: 'B', age: '12才以上対象', color: '#2f7d32' },
  { key: 'C', age: '15才以上対象', color: '#1f5fa8' },
  { key: 'D', age: '17才以上対象', color: '#d97a12' },
  { key: 'Z', age: '18才以上対象', color: '#b32020' }
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

function deepInk(hex) {
  const hsl = rgbToHsl(hexToRgb(hex));
  const s = Math.min(hsl[1], 0.32);
  const l = Math.min(hsl[2], 0.20);
  return hslToRgb([hsl[0], s, l]);
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
  const a = box(SURFACE_ANCHORS.filmScrim, W, H);
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
  const a = box(SURFACE_ANCHORS.billingPlate, W, H);
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
  const a = box(SURFACE_ANCHORS.obi, W, H);
  const color = rng.pick(theme.obiColors);
  ctx.fillStyle = color;
  ctx.fillRect(a.x, a.y, a.w, a.h);
  const dark = luma01(hexToRgb(color)) < 0.55;
  hairline(ctx, 0, a.y, W, 'rgba(0,0,0,0.22)', Math.max(1, H * 0.0022));
  hairline(ctx, 0, a.y + H * 0.006, W, dark ? 'rgba(255,255,255,0.30)' : 'rgba(30,24,18,0.30)', Math.max(1, H * 0.0012));
  const bx = box(SURFACE_ANCHORS.obiBox, W, H);
  ctx.fillStyle = dark ? '#f3efe6' : '#141210';
  ctx.fillRect(bx.x, bx.y, bx.w, bx.h);
  ctx.restore();
}

function drawSpecBand(ctx, W, H, rng, theme) {
  ctx.save();
  const a = box(SURFACE_ANCHORS.specBand, W, H);
  const color = rng.pick(theme.plateColors);
  ctx.fillStyle = color;
  ctx.fillRect(a.x, a.y, a.w, a.h);
  const dark = luma01(hexToRgb(color)) < 0.55;
  const rule = dark ? 'rgba(255,255,255,0.42)' : 'rgba(24,20,16,0.42)';
  hairline(ctx, 0, a.y, W, rule, Math.max(1, H * 0.0026));
  hairline(ctx, 0, a.y + H * 0.007, W, rule, Math.max(1, H * 0.0010));
  ctx.fillStyle = rng.pick(theme.accentColors);
  ctx.fillRect(0, a.y - H * 0.014, W * rng.range(0.20, 0.42), H * 0.010);
  ctx.fillStyle = dark ? 'rgba(255,255,255,0.22)' : 'rgba(24,20,16,0.22)';
  ctx.fillRect(W * 0.05, a.y + H * 0.052, W * 0.90, Math.max(1, H * 0.0010));
  ctx.restore();
}

function drawHairRules(ctx, W, H, rng, theme) {
  ctx.save();
  const c = hexToRgb(rng.pick(theme.accentColors));
  const t = Math.max(1, H * 0.0018);
  ctx.fillStyle = rgbToCss(c, 0.85);
  ctx.fillRect(0, H * 0.052, W, t);
  ctx.fillRect(0, H * 0.052 + t * 2.4, W, t * 0.6);
  ctx.fillRect(0, H * 0.800, W, t);
  ctx.fillRect(0, H * 0.800 - t * 2.4, W, t * 0.6);
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
  const strip = box(SURFACE_ANCHORS.voiceTopStrip, W, H);
  const foot = box(SURFACE_ANCHORS.voiceFootBand, W, H);
  const plate = box(SURFACE_ANCHORS.voicePlate, W, H);
  const stripRgb = hexToRgb(rng.pick(theme.obiColors));
  ctx.fillStyle = rgbToCss(stripRgb, rng.range(0.62, 0.80));
  ctx.fillRect(0, strip.y, W, strip.h);
  const footRgb = hexToRgb(rng.pick(theme.plateColors));
  ctx.fillStyle = rgbToCss(footRgb, rng.range(0.86, 0.96));
  ctx.fillRect(0, foot.y, W, foot.h);
  const accent = hexToRgb(rng.pick(theme.accentColors));
  hairline(ctx, 0, foot.y, W, rgbToCss(accent, 0.85), Math.max(1, H * 0.0030));
  hairline(ctx, 0, strip.y + strip.h, W, rgbToCss(accent, 0.55), Math.max(1, H * 0.0018));
  ctx.restore();

  ctx.save();
  const r = plate.h * 0.28;
  ctx.fillStyle = 'rgba(0,0,0,0.20)';
  roundRectPath(ctx, plate.x + plate.h * 0.04, plate.y + plate.h * 0.05, plate.w, plate.h, r);
  ctx.fill();
  const plateRgb = hexToRgb(rng.pick(theme.plateColors));
  ctx.fillStyle = rgbToCss(plateRgb, rng.range(0.88, 0.97));
  roundRectPath(ctx, plate.x, plate.y, plate.w, plate.h, r);
  ctx.fill();
  ctx.strokeStyle = rgbToCss(accent, 0.70);
  ctx.lineWidth = Math.max(1, H * 0.0022);
  roundRectPath(ctx, plate.x, plate.y, plate.w, plate.h, r);
  ctx.stroke();
  ctx.fillStyle = rgbToCss(accent, 0.85);
  ctx.fillRect(plate.x + plate.w * 0.035, plate.y + plate.h * 0.50, plate.w * 0.93, Math.max(1, H * 0.0016));
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
  const a = box(SURFACE_ANCHORS.circleMark, W, H);
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

function drawPlatformBar(ctx, W, H, rng, theme) {
  ctx.save();
  const a = box(SURFACE_ANCHORS.platformBand, W, H);
  const rgb = deepInk(rng.pick(theme.obiColors));
  const color = rgbToCss(rgb, 1);
  const g = ctx.createLinearGradient(0, 0, 0, a.h);
  g.addColorStop(0, rgbToCss(shade(rgb, 0.16), 0.97));
  g.addColorStop(1, rgbToCss(shade(rgb, -0.30), 0.97));
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, a.h);
  ctx.fillStyle = 'rgba(255,255,255,0.16)';
  ctx.fillRect(0, 0, W, a.h * 0.14);
  ctx.fillStyle = 'rgba(0,0,0,0.55)';
  ctx.fillRect(0, a.h - Math.max(2, W * 0.004), W, Math.max(2, W * 0.004));
  const ink = luma01(rgb) > 0.55 ? '#12100e' : '#ffffff';
  const mark = a.h * 0.40;
  ctx.fillStyle = ink;
  ctx.globalAlpha = 0.88;
  ctx.fillRect(W * 0.035, a.h * 0.5 - mark / 2, mark, mark);
  ctx.globalAlpha = 1;
  const name = rng.pick(PLATFORM_NAMES);
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  ctx.fillStyle = ink;
  fitFont(ctx, name, W * 0.30, a.h * 0.40, '700', STACK_CONDENSED);
  ctx.fillText(name, W * 0.035 + mark * 1.5, a.h * 0.50);
  ctx.restore();
}

function drawRatingBox(ctx, W, H, rng) {
  ctx.save();
  const a = SURFACE_ANCHORS.ratingPlate;
  const side = H * a.h;
  const x = W * a.x;
  const y = H * a.y;
  const rank = rng.pick(RATING_RANKS);
  ctx.fillStyle = '#f6f4f0';
  ctx.fillRect(x, y, side, side);
  ctx.strokeStyle = '#14120f';
  ctx.lineWidth = Math.max(1.5, side * 0.035);
  ctx.strokeRect(x, y, side, side);
  const headH = side * 0.20;
  ctx.fillStyle = rank.color;
  ctx.fillRect(x, y, side, headH);
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillStyle = '#ffffff';
  fitFont(ctx, 'RATING', side * 0.80, headH * 0.62, '700', STACK_CONDENSED);
  ctx.fillText('RATING', x + side / 2, y + headH * 0.55);
  ctx.fillStyle = rank.color;
  fitFont(ctx, rank.key, side * 0.58, side * 0.46, '800', STACK_SANS);
  ctx.fillText(rank.key, x + side / 2, y + headH + (side - headH) * 0.38);
  const footH = side * 0.24;
  ctx.fillStyle = '#14120f';
  ctx.fillRect(x, y + side - footH, side, footH);
  ctx.fillStyle = '#ffffff';
  fitFont(ctx, rank.age, side * 0.88, footH * 0.50, '600', STACK_JP);
  ctx.fillText(rank.age, x + side / 2, y + side - footH * 0.48);
  ctx.restore();
}

function drawGameChrome(ctx, W, H, rng, theme) {
  drawPlatformBar(ctx, W, H, rng, theme);
  ctx.save();
  const pub = box(SURFACE_ANCHORS.publisherRow, W, H);
  const g = ctx.createLinearGradient(0, pub.y - H * 0.06, 0, H);
  g.addColorStop(0, 'rgba(6,7,10,0)');
  g.addColorStop(1, 'rgba(6,7,10,' + rng.range(0.80, 0.94).toFixed(3) + ')');
  ctx.fillStyle = g;
  ctx.fillRect(0, pub.y - H * 0.06, W, H - pub.y + H * 0.06);
  const accent = hexToRgb(rng.pick(theme.accentColors));
  hairline(ctx, W * 0.20, pub.y - H * 0.008, W * 0.78, rgbToCss(accent, 0.75), Math.max(1, H * 0.0016));
  ctx.restore();
  drawRatingBox(ctx, W, H, rng);
}

function drawDiagonalBand(ctx, W, H, rng, theme) {
  ctx.save();
  const a = SURFACE_ANCHORS.avSash;
  const cx = (a.x + a.w / 2) * W;
  const cy = (a.y + a.h / 2) * H;
  const bw = a.w * W * 1.22;
  const bh = a.h * H;
  const color = rng.pick(theme.ribbonColors);
  ctx.translate(cx, cy);
  ctx.rotate(a.deg * Math.PI / 180);
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
  const series = box(SURFACE_ANCHORS.seriesBand, W, H);
  const seriesColor = rng.pick(theme.obiColors);
  ctx.fillStyle = seriesColor;
  ctx.fillRect(0, 0, W, series.h);
  hairline(ctx, 0, series.h, W, rgbToCss(hexToRgb(rng.pick(theme.accentColors)), 0.9), Math.max(1, H * 0.0022));
  ctx.restore();

  drawDiagonalBand(ctx, W, H, rng, theme);

  ctx.save();
  const spec = box(SURFACE_ANCHORS.avSpecBand, W, H);
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
  const a = box(SURFACE_ANCHORS.plate, W, H);
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
  ctx.lineWidth = Math.max(1, W * 0.0022);
  ctx.strokeRect(m, m, W - m * 2, H * 0.655 - m);
  if (rng.chance(0.5)) {
    const m2 = m + W * 0.010;
    ctx.lineWidth = Math.max(1, W * 0.0011);
    ctx.strokeRect(m2, m2, W - m2 * 2, H * 0.655 - m2);
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
  const a = box(SURFACE_ANCHORS.cornerPlate, W, H);
  const color = rng.pick(theme.ribbonColors);
  ctx.fillStyle = color;
  ctx.fillRect(a.x, a.y, a.w, a.h);
  ctx.fillStyle = 'rgba(255,255,255,0.18)';
  ctx.fillRect(a.x, a.y, a.w, a.h * 0.30);
  const base = rng.pick(CORNER_LABELS);
  const label = base === 'Vol.' ? 'Vol.' + rng.int(1, 9) : base;
  ctx.fillStyle = inkOn(color);
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  fitFont(ctx, label, a.w * 0.84, a.h * 0.44, '700', STACK_CONDENSED);
  ctx.fillText(label, a.x + a.w / 2, a.y + a.h * 0.56);
  ctx.restore();
}

function drawSealBadge(ctx, W, H, rng, theme) {
  ctx.save();
  const a = box(SURFACE_ANCHORS.sealBadge, W, H);
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
  const a = box(SURFACE_ANCHORS.laurelBadge, W, H);
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
  const a = box(SURFACE_ANCHORS.barcode, W, H);
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

function drawTapeStrip(ctx, W, H, rng, theme) {
  ctx.save();
  const w = W * rng.range(0.16, 0.28);
  const h = w * rng.range(0.16, 0.24);
  const left = rng.chance(0.5);
  const x = left ? W * rng.range(0.06, 0.12) : W * rng.range(0.60, 0.74);
  const y = H * rng.range(0.14, 0.58);
  const color = rng.pick(theme.accentColors);
  ctx.translate(x + w / 2, y + h / 2);
  ctx.rotate(rng.range(-0.24, 0.24));
  ctx.fillStyle = 'rgba(0,0,0,0.22)';
  ctx.fillRect(-w / 2 + w * 0.012, -h / 2 + h * 0.05, w, h);
  ctx.globalAlpha = rng.range(0.80, 0.95);
  ctx.fillStyle = color;
  ctx.fillRect(-w / 2, -h / 2, w, h);
  ctx.globalAlpha = 1;
  ctx.fillStyle = 'rgba(255,255,255,0.28)';
  ctx.fillRect(-w / 2, -h / 2, w, h * 0.22);
  const notch = h * 0.16;
  ctx.fillStyle = 'rgba(0,0,0,0.16)';
  for (let t = -w / 2 + notch; t < w / 2 - notch; t += notch * 2.2) {
    ctx.beginPath();
    ctx.arc(t, -h / 2, notch * 0.42, 0, Math.PI * 2);
    ctx.fill();
    ctx.beginPath();
    ctx.arc(t, h / 2, notch * 0.42, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
}

function drawWaveBand(ctx, W, H, rng, theme) {
  ctx.save();
  const a = box(SURFACE_ANCHORS.waveBand, W, H);
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
  const w = W * rng.range(0.024, 0.036);
  const color = rng.pick(theme.obiColors);
  const rgb = hexToRgb(color);
  const g = ctx.createLinearGradient(0, 0, w, 0);
  g.addColorStop(0, rgbToCss(shade(rgb, -0.30), 0.94));
  g.addColorStop(0.65, rgbToCss(rgb, 0.94));
  g.addColorStop(1, rgbToCss(shade(rgb, -0.45), 0.94));
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, H);
  const accent = hexToRgb(rng.pick(theme.accentColors));
  ctx.fillStyle = rgbToCss(accent, 0.9);
  ctx.fillRect(w - Math.max(1, w * 0.16), 0, Math.max(1, w * 0.16), H);
  ctx.fillRect(0, H * rng.range(0.10, 0.20), w, H * rng.range(0.05, 0.09));
  ctx.restore();
}

function drawGridPlate(ctx, W, H, rng, theme) {
  ctx.save();
  const a = box(SURFACE_ANCHORS.gridPlate, W, H);
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

export const SURFACE_FUNCS = {
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
  jacketFrame: drawJacketFrame,
  circleMark: drawCircleMark,
  gameChrome: drawGameChrome,
  avLayers: drawAvLayers,
  platformBar: drawPlatformBar,
  ratingBox: drawRatingBox,
  diagonalBand: drawDiagonalBand,
  plate: drawPlate,
  frame: drawFrame,
  boldFrame: drawBoldFrame,
  cornerPlate: drawCornerPlate,
  sealBadge: drawSealBadge,
  laurelBadge: drawLaurelBadge,
  barcode: drawBarcode,
  tapeStrip: drawTapeStrip,
  waveBand: drawWaveBand,
  discSpine: drawDiscSpine,
  gridPlate: drawGridPlate
};
