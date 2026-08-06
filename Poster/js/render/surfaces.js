import { hexToRgb, rgbToCss, luma01, shade } from '../core/color.js';
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
const SEAL_LABELS = ['初回限定', '数量限定', 'PREMIUM', '特典映像', '完全生産限定', 'BONUS'];

function inkOn(hex) {
  return luma01(hexToRgb(hex)) > 0.55 ? '#12100e' : '#ffffff';
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

function drawLetterbox(ctx, W, H, rng) {
  ctx.save();
  const barH = H * rng.range(0.035, 0.075);
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

function drawObi(ctx, W, H, rng, theme) {
  ctx.save();
  const a = SURFACE_ANCHORS.obi;
  const top = H * (a.y + rng.range(-0.020, 0.008));
  const color = rng.pick(theme.obiColors);
  ctx.fillStyle = color;
  ctx.fillRect(0, top, W, H - top);
  ctx.fillStyle = 'rgba(0,0,0,0.16)';
  ctx.fillRect(0, top, W, H * 0.004);
  if (rng.chance(0.5)) {
    const line = luma01(hexToRgb(color)) > 0.55 ? 'rgba(30,24,18,0.42)' : 'rgba(255,255,255,0.35)';
    ctx.strokeStyle = line;
    ctx.lineWidth = Math.max(1, W * 0.002);
    ctx.strokeRect(W * 0.02, top + H * 0.010, W * 0.96, H - top - H * 0.020);
  }
  ctx.restore();
}

function drawRibbon(ctx, W, H, rng, theme) {
  ctx.save();
  const a = SURFACE_ANCHORS.ribbon;
  const top = H * (a.y + rng.range(0, 0.012));
  const h = H * rng.range(0.065, 0.082);
  const color = rng.pick(theme.ribbonColors);
  const x = W * a.x;
  const w = W * rng.range(0.72, 0.93);
  if (rng.chance(0.4)) {
    ctx.translate(W / 2, top + h / 2);
    ctx.rotate(rng.range(-0.030, 0.030));
    ctx.translate(-W / 2, -(top + h / 2));
  }
  ctx.fillStyle = color;
  ctx.fillRect(x, top, w, h);
  ctx.fillStyle = 'rgba(255,255,255,0.22)';
  ctx.fillRect(x, top, w, h * 0.28);
  ctx.fillStyle = 'rgba(0,0,0,0.18)';
  ctx.fillRect(x, top + h * 0.88, w, h * 0.12);
  ctx.restore();
}

function drawPlate(ctx, W, H, rng, theme) {
  ctx.save();
  const a = SURFACE_ANCHORS.plate;
  const x = W * a.x;
  const y = H * (a.y + rng.range(-0.020, 0.010));
  const w = W * a.w;
  const h = H * (a.h + rng.range(0, 0.050));
  const color = rng.pick(theme.plateColors);
  ctx.globalAlpha = rng.range(0.88, 1);
  ctx.fillStyle = color;
  ctx.fillRect(x, y, w, h);
  ctx.globalAlpha = 1;
  ctx.strokeStyle = luma01(hexToRgb(color)) > 0.55 ? 'rgba(0,0,0,0.35)' : 'rgba(255,255,255,0.32)';
  ctx.lineWidth = Math.max(1, W * 0.0025);
  ctx.strokeRect(x + W * 0.012, y + H * 0.008, w - W * 0.024, h - H * 0.016);
  ctx.restore();
}

function drawFrame(ctx, W, H, rng, theme) {
  ctx.save();
  const m = W * rng.range(0.030, 0.055);
  const accent = rng.pick(theme.accentColors);
  ctx.strokeStyle = rng.chance(0.4) ? rgbToCss(hexToRgb(accent), 0.7) : (rng.chance(0.5) ? 'rgba(255,255,255,0.55)' : 'rgba(20,16,12,0.55)');
  ctx.lineWidth = Math.max(1, W * 0.0022);
  ctx.strokeRect(m, m, W - m * 2, H - m * 2);
  if (rng.chance(0.45)) {
    const m2 = m + W * 0.010;
    ctx.lineWidth = Math.max(1, W * 0.0011);
    ctx.strokeRect(m2, m2, W - m2 * 2, H - m2 * 2);
  }
  ctx.restore();
}

function drawCornerPlate(ctx, W, H, rng, theme) {
  ctx.save();
  const w = W * rng.range(0.16, 0.24);
  const h = w * 0.34;
  const right = rng.chance(0.5);
  const x = right ? W - w - W * 0.05 : W * 0.05;
  const y = H * 0.045;
  const color = rng.pick(theme.ribbonColors);
  ctx.fillStyle = color;
  ctx.fillRect(x, y, w, h);
  ctx.fillStyle = 'rgba(255,255,255,0.18)';
  ctx.fillRect(x, y, w, h * 0.30);
  const base = rng.pick(CORNER_LABELS);
  const label = base === 'Vol.' ? 'Vol.' + rng.int(1, 9) : base;
  ctx.fillStyle = inkOn(color);
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  fitFont(ctx, label, w * 0.82, h * 0.44, '700', STACK_CONDENSED);
  ctx.fillText(label, x + w / 2, y + h * 0.54);
  ctx.restore();
}

function drawBarcode(ctx, W, H, rng, theme) {
  ctx.save();
  const a = SURFACE_ANCHORS.barcode;
  const w = W * a.w;
  const h = H * a.h;
  const x = W * a.x;
  const y = H * a.y;
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(x, y, w, h);
  ctx.fillStyle = '#111111';
  let cx = x + w * 0.05;
  const limit = x + w * 0.95;
  while (cx < limit) {
    const bw = Math.max(1, w * rng.range(0.004, 0.016));
    ctx.fillRect(cx, y + h * 0.12, Math.min(bw, limit - cx), h * 0.62);
    cx += bw + w * rng.range(0.006, 0.020);
  }
  const digits = '4' + rng.int(100000, 999999) + rng.int(1000, 9999);
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  fitFont(ctx, digits, w * 0.88, h * 0.20, '400', STACK_MONO);
  ctx.fillText(digits, x + w / 2, y + h * 0.78);
  ctx.restore();
}

function drawRatingBox(ctx, W, H, rng, theme) {
  ctx.save();
  const a = SURFACE_ANCHORS.ratingBox;
  const x = W * a.x;
  const y = H * a.y;
  const w = W * a.w;
  const h = H * a.h;
  const rank = rng.pick(RATING_RANKS);
  ctx.fillStyle = '#f4f2ee';
  ctx.fillRect(x, y, w, h);
  ctx.strokeStyle = '#14120f';
  ctx.lineWidth = Math.max(1.5, W * 0.004);
  ctx.strokeRect(x, y, w, h);
  const headH = h * 0.20;
  ctx.fillStyle = rank.color;
  ctx.fillRect(x, y, w, headH);
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillStyle = '#ffffff';
  fitFont(ctx, 'RATING', w * 0.80, headH * 0.62, '700', STACK_CONDENSED);
  ctx.fillText('RATING', x + w / 2, y + headH * 0.55);
  ctx.fillStyle = rank.color;
  fitFont(ctx, rank.key, w * 0.62, h * 0.48, '800', STACK_SANS);
  ctx.fillText(rank.key, x + w / 2, y + headH + (h - headH) * 0.40);
  const footH = h * 0.24;
  ctx.fillStyle = '#14120f';
  ctx.fillRect(x, y + h - footH, w, footH);
  ctx.fillStyle = '#ffffff';
  fitFont(ctx, rank.age, w * 0.86, footH * 0.52, '600', STACK_JP);
  ctx.fillText(rank.age, x + w / 2, y + h - footH * 0.48);
  ctx.restore();
}

function drawPlatformBar(ctx, W, H, rng, theme) {
  ctx.save();
  const a = SURFACE_ANCHORS.platformBar;
  const h = H * a.h;
  const color = rng.pick(theme.accentColors);
  const rgb = hexToRgb(color);
  const g = ctx.createLinearGradient(0, 0, 0, h);
  g.addColorStop(0, rgbToCss(shade(rgb, 0.18), 0.96));
  g.addColorStop(1, rgbToCss(shade(rgb, -0.35), 0.96));
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, h);
  ctx.fillStyle = 'rgba(255,255,255,0.16)';
  ctx.fillRect(0, 0, W, h * 0.16);
  ctx.fillStyle = 'rgba(0,0,0,0.28)';
  ctx.fillRect(0, h - Math.max(1, h * 0.08), W, Math.max(1, h * 0.08));
  const ink = inkOn(color);
  const mark = h * 0.44;
  ctx.fillStyle = ink;
  ctx.globalAlpha = 0.85;
  ctx.fillRect(W * 0.035, h * 0.5 - mark / 2, mark, mark);
  ctx.globalAlpha = 1;
  const name = rng.pick(PLATFORM_NAMES);
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  ctx.fillStyle = ink;
  fitFont(ctx, name, W * 0.34, h * 0.52, '700', STACK_CONDENSED);
  ctx.fillText(name, W * 0.035 + mark * 1.5, h * 0.52);
  ctx.restore();
}

function drawDiagonalBand(ctx, W, H, rng, theme) {
  ctx.save();
  const cy = H * rng.range(0.34, 0.72);
  const ang = rng.range(0.12, 0.34) * rng.sign();
  const bh = H * rng.range(0.055, 0.105);
  const color = rng.pick(theme.accentColors);
  ctx.translate(W / 2, cy);
  ctx.rotate(ang);
  ctx.globalAlpha = rng.range(0.80, 0.96);
  ctx.fillStyle = color;
  ctx.fillRect(-W, -bh / 2, W * 2, bh);
  ctx.globalAlpha = 1;
  ctx.fillStyle = 'rgba(255,255,255,0.20)';
  ctx.fillRect(-W, -bh / 2, W * 2, bh * 0.22);
  if (rng.chance(0.55)) {
    const stripe = rng.pick(theme.ribbonColors);
    ctx.fillStyle = stripe;
    const sh = bh * rng.range(0.14, 0.26);
    ctx.fillRect(-W, bh / 2 + bh * 0.18, W * 2, sh);
  }
  if (rng.chance(0.45)) {
    ctx.fillStyle = 'rgba(0,0,0,0.20)';
    const step = W * rng.range(0.05, 0.09);
    for (let x = -W; x < W; x += step * 2) {
      ctx.fillRect(x, -bh / 2, step, bh);
    }
  }
  ctx.restore();
}

function drawTapeStrip(ctx, W, H, rng, theme) {
  ctx.save();
  const w = W * rng.range(0.16, 0.30);
  const h = w * rng.range(0.16, 0.26);
  const left = rng.chance(0.5);
  const x = left ? W * rng.range(0.03, 0.10) : W * rng.range(0.62, 0.80);
  const y = H * rng.range(0.08, 0.72);
  const color = rng.pick(theme.accentColors);
  ctx.translate(x + w / 2, y + h / 2);
  ctx.rotate(rng.range(-0.26, 0.26));
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
  const top = H * rng.range(0.575, 0.655);
  const h = H * rng.range(0.070, 0.100);
  const color = rng.pick(theme.accentColors);
  const rgb = hexToRgb(color);
  const g = ctx.createLinearGradient(0, top, 0, top + h);
  g.addColorStop(0, rgbToCss(rgb, 0));
  g.addColorStop(0.5, rgbToCss(rgb, rng.range(0.18, 0.34)));
  g.addColorStop(1, rgbToCss(rgb, 0));
  ctx.fillStyle = g;
  ctx.fillRect(0, top, W, h);
  const mid = top + h / 2;
  const bars = rng.int(56, 108);
  const bw = W / bars;
  ctx.fillStyle = rgbToCss(shade(rgb, 0.35), rng.range(0.65, 0.9));
  for (let i = 0; i < bars; i++) {
    const t = i / bars;
    const env = Math.sin(Math.PI * t);
    const amp = (0.14 + 0.86 * Math.pow(rng.next(), 1.5)) * env * h * 0.46;
    ctx.fillRect(i * bw + bw * 0.22, mid - amp, bw * 0.56, amp * 2);
  }
  ctx.strokeStyle = rgbToCss(shade(rgb, 0.5), 0.5);
  ctx.lineWidth = Math.max(1, W * 0.0012);
  ctx.beginPath();
  ctx.moveTo(0, mid);
  ctx.lineTo(W, mid);
  ctx.stroke();
  ctx.restore();
}

function drawDiscSpine(ctx, W, H, rng, theme) {
  ctx.save();
  const w = W * rng.range(0.042, 0.062);
  const right = rng.chance(0.5);
  const x = right ? W - w : 0;
  const color = rng.pick(theme.obiColors);
  const rgb = hexToRgb(color);
  const g = ctx.createLinearGradient(x, 0, x + w, 0);
  g.addColorStop(0, rgbToCss(shade(rgb, -0.30), 0.94));
  g.addColorStop(0.65, rgbToCss(rgb, 0.94));
  g.addColorStop(1, rgbToCss(shade(rgb, -0.45), 0.94));
  ctx.fillStyle = g;
  ctx.fillRect(x, 0, w, H);
  const accent = hexToRgb(rng.pick(theme.accentColors));
  ctx.fillStyle = rgbToCss(accent, 0.9);
  const inner = right ? x : x + w - Math.max(1, w * 0.10);
  ctx.fillRect(inner, 0, Math.max(1, w * 0.10), H);
  ctx.fillStyle = rgbToCss(accent, 0.85);
  const tickH = H * rng.range(0.06, 0.11);
  ctx.fillRect(x, H * rng.range(0.06, 0.16), w, tickH);
  ctx.restore();
}

function drawGridPlate(ctx, W, H, rng, theme) {
  ctx.save();
  const a = SURFACE_ANCHORS.gridPlate;
  const x = W * a.x;
  const y = H * a.y;
  const w = W * a.w;
  const h = H * a.h;
  const color = rng.pick(theme.plateColors);
  ctx.globalAlpha = rng.range(0.82, 0.94);
  ctx.fillStyle = color;
  ctx.fillRect(x, y, w, h);
  ctx.globalAlpha = 1;
  const line = luma01(hexToRgb(color)) > 0.55 ? 'rgba(20,16,12,0.45)' : 'rgba(238,236,232,0.45)';
  ctx.strokeStyle = line;
  ctx.lineWidth = Math.max(1, W * 0.0022);
  ctx.strokeRect(x, y, w, h);
  ctx.lineWidth = Math.max(1, W * 0.0012);
  const cols = rng.int(2, 4);
  for (let i = 1; i < cols; i++) {
    const cx = x + (w / cols) * i;
    ctx.beginPath();
    ctx.moveTo(cx, y);
    ctx.lineTo(cx, y + h);
    ctx.stroke();
  }
  const rows = rng.int(1, 3);
  for (let i = 1; i < rows; i++) {
    const cy = y + (h / rows) * i;
    ctx.beginPath();
    ctx.moveTo(x, cy);
    ctx.lineTo(x + w, cy);
    ctx.stroke();
  }
  ctx.restore();
}

function drawSealBadge(ctx, W, H, rng, theme) {
  ctx.save();
  const r = W * rng.range(0.085, 0.125);
  const left = rng.chance(0.45);
  const cx = left ? W * rng.range(0.14, 0.24) : W * rng.range(0.76, 0.86);
  const cy = H * rng.range(0.12, 0.30);
  const color = rng.pick(theme.ribbonColors);
  ctx.translate(cx, cy);
  ctx.rotate(rng.range(-0.30, 0.30));
  ctx.fillStyle = 'rgba(0,0,0,0.22)';
  ctx.beginPath();
  ctx.arc(r * 0.05, r * 0.06, r, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(0, 0, r, 0, Math.PI * 2);
  ctx.fill();
  const ink = inkOn(color);
  ctx.strokeStyle = ink;
  ctx.globalAlpha = 0.75;
  ctx.lineWidth = Math.max(1, r * 0.05);
  ctx.beginPath();
  ctx.arc(0, 0, r * 0.84, 0, Math.PI * 2);
  ctx.stroke();
  ctx.globalAlpha = 1;
  const label = rng.pick(SEAL_LABELS);
  ctx.fillStyle = ink;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  fitFont(ctx, label, r * 1.42, r * 0.40, '700', STACK_JP);
  ctx.fillText(label, 0, 0);
  ctx.restore();
}

function drawNoticeStrip(ctx, W, H, rng, theme) {
  ctx.save();
  const a = SURFACE_ANCHORS.noticeStrip;
  const x = W * a.x;
  const y = H * a.y;
  const w = W * a.w;
  const h = H * a.h;
  ctx.fillStyle = 'rgba(10,9,8,0.55)';
  ctx.fillRect(x, y, w, h);
  const ink = hexToRgb(rng.pick(theme.inkColors));
  ctx.fillStyle = rgbToCss(ink, 0.62);
  const rows = rng.int(2, 3);
  const rowH = h / (rows + 1);
  for (let r = 0; r < rows; r++) {
    let cx = x + w * 0.02;
    const limit = x + w * rng.range(0.86, 0.98);
    const ry = y + rowH * (r + 0.4);
    while (cx < limit) {
      const seg = w * rng.range(0.012, 0.055);
      ctx.fillRect(cx, ry, Math.min(seg, limit - cx), Math.max(1, rowH * 0.30));
      cx += seg + w * rng.range(0.006, 0.018);
    }
  }
  ctx.restore();
}

export const SURFACE_FUNCS = {
  letterbox: drawLetterbox,
  bottomGradient: drawBottomGradient,
  topGradient: drawTopGradient,
  sideBand: drawSideBand,
  obi: drawObi,
  ribbon: drawRibbon,
  plate: drawPlate,
  frame: drawFrame,
  cornerPlate: drawCornerPlate,
  barcode: drawBarcode,
  ratingBox: drawRatingBox,
  platformBar: drawPlatformBar,
  diagonalBand: drawDiagonalBand,
  tapeStrip: drawTapeStrip,
  waveBand: drawWaveBand,
  discSpine: drawDiscSpine,
  gridPlate: drawGridPlate,
  sealBadge: drawSealBadge,
  noticeStrip: drawNoticeStrip
};
