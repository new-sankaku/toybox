import { hexToRgb, rgbToCss, shade } from '../core/color.js';

function scratch(w, h) {
  const c = document.createElement('canvas');
  c.width = Math.max(1, Math.round(w));
  c.height = Math.max(1, Math.round(h));
  return c;
}

function downscale(ctx, divisor) {
  const src = ctx.canvas;
  const sw = Math.max(8, Math.round(src.width / divisor));
  const sh = Math.max(8, Math.round(src.height / divisor));
  const c = scratch(sw, sh);
  const cctx = c.getContext('2d');
  cctx.drawImage(src, 0, 0, sw, sh);
  return c;
}

function drawGrain(ctx, W, H, rng) {
  const tile = scratch(128, 128);
  const tctx = tile.getContext('2d');
  const img = tctx.createImageData(128, 128);
  const data = img.data;
  for (let i = 0; i < data.length; i += 4) {
    const v = 110 + Math.floor(rng.next() * 90);
    data[i] = v; data[i + 1] = v; data[i + 2] = v; data[i + 3] = 255;
  }
  tctx.putImageData(img, 0, 0);
  ctx.save();
  ctx.globalCompositeOperation = 'overlay';
  ctx.globalAlpha = rng.range(0.10, 0.24);
  ctx.fillStyle = ctx.createPattern(tile, 'repeat');
  ctx.fillRect(0, 0, W, H);
  ctx.restore();
}

function drawVignette(ctx, W, H, rng) {
  ctx.save();
  const g = ctx.createRadialGradient(W / 2, H / 2, Math.min(W, H) * 0.28, W / 2, H / 2, Math.max(W, H) * 0.78);
  g.addColorStop(0, 'rgba(0,0,0,0)');
  g.addColorStop(1, 'rgba(0,0,0,' + rng.range(0.30, 0.62).toFixed(3) + ')');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);
  ctx.restore();
}

function drawScanline(ctx, W, H, rng) {
  ctx.save();
  ctx.globalAlpha = rng.range(0.05, 0.13);
  ctx.fillStyle = '#000000';
  const step = Math.max(2, Math.round(H / rng.int(320, 620)));
  for (let y = 0; y < H; y += step * 2) {
    ctx.fillRect(0, y, W, step);
  }
  ctx.restore();
}

function drawDust(ctx, W, H, rng) {
  ctx.save();
  ctx.globalAlpha = rng.range(0.10, 0.24);
  ctx.strokeStyle = '#ffffff';
  const count = rng.int(8, 26);
  for (let i = 0; i < count; i++) {
    const x = rng.range(0, W);
    const y = rng.range(0, H);
    ctx.lineWidth = rng.range(0.4, 1.6);
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x + rng.range(-3, 3), y + rng.range(4, H * 0.06));
    ctx.stroke();
  }
  ctx.restore();
}

function drawSparkle(ctx, W, H, rng) {
  ctx.save();
  ctx.globalCompositeOperation = 'lighter';
  const count = rng.int(6, 16);
  for (let i = 0; i < count; i++) {
    const x = rng.range(W * 0.05, W * 0.95);
    const y = rng.range(H * 0.05, H * 0.80);
    const r = rng.range(W * 0.008, W * 0.045);
    const g = ctx.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, 'rgba(255,255,255,0.85)');
    g.addColorStop(0.4, 'rgba(255,240,220,0.25)');
    g.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
}

function drawBloom(ctx, W, H, rng) {
  ctx.save();
  ctx.globalCompositeOperation = 'lighter';
  ctx.globalAlpha = rng.range(0.05, 0.14);
  const g = ctx.createLinearGradient(0, 0, W * 0.6, H);
  g.addColorStop(0, 'rgba(255,220,235,1)');
  g.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);
  ctx.restore();
}

function drawPaper(ctx, W, H, rng) {
  ctx.save();
  ctx.globalCompositeOperation = 'multiply';
  ctx.globalAlpha = rng.range(0.06, 0.16);
  const g = ctx.createLinearGradient(0, 0, W, H);
  g.addColorStop(0, '#efe6d2');
  g.addColorStop(0.5, '#d8ccb2');
  g.addColorStop(1, '#f2ead8');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);
  ctx.restore();
}

function drawHalation(ctx, W, H, rng, theme) {
  const small = downscale(ctx, 8);
  const bright = scratch(small.width, small.height);
  const bctx = bright.getContext('2d');
  bctx.drawImage(small, 0, 0);
  bctx.globalCompositeOperation = 'multiply';
  bctx.drawImage(small, 0, 0);
  bctx.drawImage(small, 0, 0);
  const tint = hexToRgb(rng.pick(theme.accentColors));
  bctx.globalCompositeOperation = 'multiply';
  bctx.globalAlpha = rng.range(0.30, 0.65);
  bctx.fillStyle = rgbToCss(shade(tint, 0.55), 1);
  bctx.fillRect(0, 0, bright.width, bright.height);
  ctx.save();
  ctx.globalCompositeOperation = 'lighter';
  ctx.globalAlpha = rng.range(0.18, 0.38);
  const spread = 1 + rng.range(0.020, 0.065);
  const ox = W * (spread - 1) / 2;
  const oy = H * (spread - 1) / 2;
  ctx.drawImage(bright, -ox, -oy, W * spread, H * spread);
  ctx.restore();
}

function drawNeonGlow(ctx, W, H, rng, theme) {
  const a = hexToRgb(rng.pick(theme.accentColors));
  const b = hexToRgb(rng.pick(theme.accentColors));
  ctx.save();
  ctx.globalCompositeOperation = 'screen';
  ctx.globalAlpha = rng.range(0.10, 0.24);
  const g = ctx.createLinearGradient(0, 0, W * rng.range(0.4, 1), H);
  g.addColorStop(0, rgbToCss(shade(a, 0.25), 1));
  g.addColorStop(0.55, rgbToCss(shade(b, 0.10), 0.55));
  g.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);
  ctx.globalCompositeOperation = 'lighter';
  ctx.globalAlpha = rng.range(0.06, 0.16);
  const rx = W * rng.range(0.2, 0.8);
  const ry = H * rng.range(0.15, 0.6);
  const rr = Math.max(W, H) * rng.range(0.35, 0.65);
  const rg = ctx.createRadialGradient(rx, ry, 0, rx, ry, rr);
  rg.addColorStop(0, rgbToCss(shade(a, 0.4), 0.9));
  rg.addColorStop(1, rgbToCss(a, 0));
  ctx.fillStyle = rg;
  ctx.fillRect(0, 0, W, H);
  ctx.restore();
}

function edgeMasked(ctx, tintCss, inner) {
  const small = downscale(ctx, 3);
  const sctx = small.getContext('2d');
  sctx.globalCompositeOperation = 'multiply';
  sctx.fillStyle = tintCss;
  sctx.fillRect(0, 0, small.width, small.height);
  sctx.globalCompositeOperation = 'destination-in';
  const cx = small.width / 2;
  const cy = small.height / 2;
  const outer = Math.max(small.width, small.height) * 0.72;
  const g = sctx.createRadialGradient(cx, cy, outer * inner, cx, cy, outer);
  g.addColorStop(0, 'rgba(0,0,0,0)');
  g.addColorStop(1, 'rgba(0,0,0,1)');
  sctx.fillStyle = g;
  sctx.fillRect(0, 0, small.width, small.height);
  return small;
}

function drawChromaEdge(ctx, W, H, rng) {
  const shift = W * rng.range(0.003, 0.010);
  const inner = rng.range(0.42, 0.62);
  const red = edgeMasked(ctx, '#ff0000', inner);
  const cyan = edgeMasked(ctx, '#00ffff', inner);
  ctx.save();
  ctx.globalCompositeOperation = 'lighter';
  ctx.globalAlpha = rng.range(0.22, 0.40);
  ctx.drawImage(red, -shift, -shift * 0.5, W, H);
  ctx.drawImage(cyan, shift, shift * 0.5, W, H);
  ctx.restore();
}

function drawSoftFocus(ctx, W, H, rng) {
  const blurred = downscale(ctx, rng.int(10, 18));
  ctx.save();
  ctx.globalAlpha = rng.range(0.16, 0.30);
  ctx.drawImage(blurred, 0, 0, W, H);
  ctx.globalCompositeOperation = 'lighter';
  ctx.globalAlpha = rng.range(0.05, 0.12);
  ctx.drawImage(blurred, 0, 0, W, H);
  ctx.restore();
}

function drawBokehDots(ctx, W, H, rng, theme) {
  ctx.save();
  ctx.globalCompositeOperation = 'lighter';
  const count = rng.int(10, 26);
  for (let i = 0; i < count; i++) {
    const c = shade(hexToRgb(rng.pick(theme.accentColors)), rng.range(0.15, 0.5));
    const x = rng.range(-W * 0.05, W * 1.05);
    const y = rng.range(-H * 0.05, H * 0.95);
    const r = W * rng.range(0.012, 0.070);
    const alpha = rng.range(0.10, 0.30);
    const g = ctx.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, rgbToCss(c, alpha * 0.85));
    g.addColorStop(0.70, rgbToCss(c, alpha * 0.60));
    g.addColorStop(0.90, rgbToCss(c, alpha * 1.20));
    g.addColorStop(1, rgbToCss(c, 0));
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
}

function drawInkBleed(ctx, W, H, rng, theme) {
  const ink = hexToRgb(rng.pick(theme.inkColors));
  ctx.save();
  ctx.globalCompositeOperation = 'multiply';
  const blobs = rng.int(8, 20);
  for (let i = 0; i < blobs; i++) {
    const edge = rng.int(0, 3);
    let x, y;
    if (edge === 0) { x = rng.range(0, W); y = rng.range(0, H * 0.10); }
    else if (edge === 1) { x = rng.range(0, W); y = rng.range(H * 0.90, H); }
    else if (edge === 2) { x = rng.range(0, W * 0.10); y = rng.range(0, H); }
    else { x = rng.range(W * 0.90, W); y = rng.range(0, H); }
    const r = W * rng.range(0.020, 0.090);
    const g = ctx.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, rgbToCss(ink, rng.range(0.10, 0.24)));
    g.addColorStop(0.6, rgbToCss(ink, rng.range(0.04, 0.10)));
    g.addColorStop(1, rgbToCss(ink, 0));
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
  }
  const specks = rng.int(40, 110);
  ctx.fillStyle = rgbToCss(ink, rng.range(0.06, 0.14));
  for (let i = 0; i < specks; i++) {
    const x = rng.range(0, W);
    const y = rng.range(0, H);
    const r = W * rng.range(0.0006, 0.0035);
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
}

function drawLightLeak(ctx, W, H, rng, theme) {
  const c = shade(hexToRgb(rng.pick(theme.accentColors)), rng.range(0.20, 0.50));
  ctx.save();
  ctx.globalCompositeOperation = 'lighter';
  ctx.globalAlpha = rng.range(0.10, 0.26);
  const fromRight = rng.chance(0.5);
  const x0 = fromRight ? W : 0;
  const x1 = fromRight ? W * rng.range(0.35, 0.70) : W * rng.range(0.30, 0.65);
  const y0 = H * rng.range(-0.10, 0.25);
  const y1 = H * rng.range(0.60, 1.10);
  const g = ctx.createLinearGradient(x0, y0, x1, y1);
  g.addColorStop(0, rgbToCss(c, 0.95));
  g.addColorStop(0.45, rgbToCss(c, 0.35));
  g.addColorStop(1, rgbToCss(c, 0));
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);
  ctx.restore();
}

export const OVERLAY_FUNCS = {
  grain: drawGrain,
  vignette: drawVignette,
  scanline: drawScanline,
  dust: drawDust,
  sparkle: drawSparkle,
  bloom: drawBloom,
  paper: drawPaper,
  halation: drawHalation,
  neonGlow: drawNeonGlow,
  chromaEdge: drawChromaEdge,
  softFocus: drawSoftFocus,
  bokehDots: drawBokehDots,
  inkBleed: drawInkBleed,
  lightLeak: drawLightLeak
};
