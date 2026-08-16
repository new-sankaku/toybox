(function (PF) {
'use strict';
const { hslToRgb, rgbToCss } = PF;

const OP_WEIGHTS = [
  { type: 'sliceShift', base: 7, gain: 11, tier: 'uncommon' },
  { type: 'rgbSplitBand', base: 17, gain: 6, tier: 'common' },
  { type: 'blockScramble', base: 3, gain: 12, tier: 'rare' },
  { type: 'scanTear', base: 7, gain: 6, tier: 'uncommon' },
  { type: 'posterizeBand', base: 5, gain: 9, tier: 'rare' },
  { type: 'monoBand', base: 6, gain: 6, tier: 'uncommon' },
  { type: 'pixelBand', base: 2, gain: 11, tier: 'rare' },
  { type: 'lightLeak', base: 18, gain: 4, tier: 'common' },
  { type: 'halftoneBand', base: 3, gain: 10, tier: 'rare' },
  { type: 'edgeGhost', base: 5, gain: 8, tier: 'common' },
  { type: 'waveWarp', base: 4, gain: 10, tier: 'rare' },
  { type: 'noiseBand', base: 16, gain: 5, tier: 'common' }
];

const OP_LIMIT = {
  sliceShift: 2,
  rgbSplitBand: 2,
  blockScramble: 1,
  scanTear: 1,
  posterizeBand: 1,
  monoBand: 1,
  pixelBand: 1,
  lightLeak: 2,
  halftoneBand: 1,
  edgeGhost: 1,
  waveWarp: 1,
  noiseBand: 2
};

const TIER_BUDGET = { common: 3, uncommon: 1, rare: 1 };

const TIER_GATE = {
  common: function () { return 1; },
  uncommon: function (k) { return 0.05 + 0.20 * k; },
  rare: function (k) { return 0.015 + 0.09 * k; }
};

const GENRE_BIAS = {
  cinema: { sliceShift: 1.2, lightLeak: 1.3, noiseBand: 1.2, halftoneBand: 0.7 },
  gravure: { lightLeak: 1.5, noiseBand: 1.2, blockScramble: 0.6, pixelBand: 0.5 },
  novel: { halftoneBand: 1.5, noiseBand: 1.3, monoBand: 1.3, pixelBand: 0.6 },
  asmr: {
    sliceShift: 0, rgbSplitBand: 0, blockScramble: 0, scanTear: 0,
    posterizeBand: 0, monoBand: 0, pixelBand: 0, halftoneBand: 0,
    edgeGhost: 0, waveWarp: 0, noiseBand: 0.12, lightLeak: 1.20
  },
  game: {
    blockScramble: 0, pixelBand: 0, sliceShift: 0, scanTear: 0,
    halftoneBand: 0, monoBand: 0, posterizeBand: 0, waveWarp: 0,
    rgbSplitBand: 0, edgeGhost: 0, lightLeak: 1.25, noiseBand: 1.10
  },
  adult: { rgbSplitBand: 1.3, lightLeak: 1.3, edgeGhost: 1.2 }
};

function tintColor(rng) {
  const family = rng.weighted([
    { v: 'warm', w: 10 },
    { v: 'cool', w: 8 },
    { v: 'magenta', w: 6 },
    { v: 'green', w: 3 }
  ]);
  let hue;
  if (family === 'warm') { hue = rng.range(0.02, 0.12); }
  else if (family === 'cool') { hue = rng.range(0.50, 0.62); }
  else if (family === 'magenta') { hue = rng.range(0.84, 0.95); }
  else { hue = rng.range(0.28, 0.40); }
  return hslToRgb([hue, rng.range(0.55, 1.0), rng.range(0.52, 0.72)]);
}

function makeOp(type, rng, k) {
  const y = rng.range(0.02, 0.9);
  if (type === 'sliceShift') {
    return {
      type: type, band: true, y: y,
      h: rng.range(0.008, 0.02 + 0.075 * k),
      dx: rng.sign() * rng.range(0.005, 0.02 + 0.11 * k)
    };
  }
  if (type === 'rgbSplitBand') {
    return {
      type: type, band: true, y: y,
      h: rng.range(0.03, 0.10 + 0.20 * k),
      dx: rng.range(0.0009, 0.0016 + 0.0065 * k)
    };
  }
  if (type === 'blockScramble') {
    return {
      type: type, band: true, y: y,
      h: rng.range(0.06, 0.10 + 0.16 * k),
      x: rng.range(0, 0.55),
      w: rng.range(0.18, 0.45),
      cols: rng.int(3, 10),
      rows: rng.int(2, 6),
      swaps: rng.int(2, 3 + Math.round(6 * k))
    };
  }
  if (type === 'scanTear') {
    return {
      type: type, band: true, y: y,
      h: rng.range(0.05, 0.13 + 0.20 * k),
      step: rng.int(2, 9),
      kind: rng.chance(0.5) ? 'drop' : 'double',
      dx: rng.sign() * rng.range(0, 0.004 + 0.012 * k)
    };
  }
  if (type === 'posterizeBand') {
    return {
      type: type, band: true, y: y,
      h: rng.range(0.03, 0.09 + 0.14 * k),
      levels: rng.int(2, 3 + Math.round(6 * (1 - k)))
    };
  }
  if (type === 'monoBand') {
    return {
      type: type, band: true, y: y,
      h: rng.range(0.04, 0.10 + 0.16 * k),
      contrast: rng.range(1.1, 1.25 + 0.5 * k),
      amount: rng.range(0.7, 1.0)
    };
  }
  if (type === 'pixelBand') {
    return {
      type: type, band: true, y: y,
      h: rng.range(0.03, 0.06 + 0.10 * k),
      cell: rng.int(4, 6 + Math.round(18 * k))
    };
  }
  if (type === 'lightLeak') {
    return {
      type: type, band: false,
      pos: rng.range(0.02, 0.98),
      posY: rng.range(0.05, 0.95),
      angle: rng.range(-1.25, 1.25),
      width: rng.range(0.06, 0.26),
      alpha: rng.range(0.10, 0.20 + 0.34 * k),
      color: tintColor(rng)
    };
  }
  if (type === 'halftoneBand') {
    return {
      type: type, band: true, y: y,
      h: rng.range(0.05, 0.10 + 0.16 * k),
      cell: rng.int(3, 5 + Math.round(7 * k))
    };
  }
  if (type === 'edgeGhost') {
    return {
      type: type, band: true, y: y,
      h: rng.range(0.14, 0.30 + 0.40 * k),
      dx: rng.sign() * rng.range(0.002, 0.004 + 0.013 * k),
      dy: rng.sign() * rng.range(0, 0.002 + 0.006 * k),
      alpha: rng.range(0.22, 0.38 + 0.42 * k),
      color: tintColor(rng)
    };
  }
  if (type === 'waveWarp') {
    return {
      type: type, band: true, y: y,
      h: rng.range(0.08, 0.16 + 0.26 * k),
      amp: rng.range(0.0018, 0.005 + 0.022 * k),
      period: rng.range(0.02, 0.14),
      phase: rng.range(0, Math.PI * 2)
    };
  }
  return {
    type: 'noiseBand', band: true, y: y,
    h: rng.range(0.06, 0.14 + 0.30 * k),
    amount: rng.range(0.03, 0.06 + 0.20 * k),
    chroma: rng.chance(0.25)
  };
}

function tierBudget(rng, k, strong, calm) {
  const budget = {};
  for (const tier in TIER_BUDGET) {
    if (strong) {
      budget[tier] = TIER_BUDGET[tier] + 1;
      continue;
    }
    const gate = TIER_GATE[tier](k) * (tier === 'common' ? 1 : calm);
    budget[tier] = gate >= 1 || rng.chance(gate) ? TIER_BUDGET[tier] : 0;
  }
  return budget;
}

function buildGlitchPlan(rng, genre, intensity, mode, restraint) {
  if (mode === 'off') { return []; }
  const strong = mode === 'strong';
  const base = Math.max(0, Math.min(1, intensity));
  const k = strong ? Math.min(1, 0.45 + base * 0.75) : base;
  const calm = typeof restraint === 'number' ? Math.max(0, Math.min(1, restraint)) : 1;
  const count = strong
    ? rng.int(4, 8)
    : Math.max(0, Math.round(rng.range(-0.8, 1.0) + k * 2.8));
  if (count <= 0) { return []; }

  const bias = GENRE_BIAS[genre] || null;
  const budget = tierBudget(rng, k, strong, calm);
  const used = {};
  const plan = [];
  for (let n = 0; n < count; n++) {
    const items = [];
    for (let i = 0; i < OP_WEIGHTS.length; i++) {
      const t = OP_WEIGHTS[i].type;
      if ((used[t] || 0) >= OP_LIMIT[t]) { continue; }
      if (budget[OP_WEIGHTS[i].tier] <= 0) { continue; }
      const mul = bias && typeof bias[t] === 'number' ? bias[t] : 1;
      const w = (OP_WEIGHTS[i].base + OP_WEIGHTS[i].gain * k) * mul;
      if (w > 0) { items.push({ v: t, w: w, tier: OP_WEIGHTS[i].tier }); }
    }
    if (items.length === 0) { break; }
    const type = rng.weighted(items);
    for (let i = 0; i < items.length; i++) {
      if (items[i].v === type) { budget[items[i].tier] -= 1; break; }
    }
    used[type] = (used[type] || 0) + 1;
    plan.push(makeOp(type, rng, k));
  }
  return plan;
}

function faceBlocked(faces) {
  const out = [];
  for (let i = 0; i < faces.length; i++) {
    const f = faces[i];
    if (!f || !isFinite(f.y) || !isFinite(f.h)) { continue; }
    const a = Math.max(0, f.y - f.h * 0.32 - 0.015);
    const b = Math.min(1, f.y + f.h * 1.32 + 0.015);
    if (b > a) { out.push([a, b]); }
  }
  out.sort(function (p, q) { return p[0] - q[0]; });
  const merged = [];
  for (let i = 0; i < out.length; i++) {
    const last = merged.length > 0 ? merged[merged.length - 1] : null;
    if (last && out[i][0] <= last[1]) {
      if (out[i][1] > last[1]) { last[1] = out[i][1]; }
    } else {
      merged.push([out[i][0], out[i][1]]);
    }
  }
  return merged;
}

function freeIntervals(blocked) {
  const free = [];
  let cur = 0;
  for (let i = 0; i < blocked.length; i++) {
    if (blocked[i][0] - cur > 0.004) { free.push([cur, blocked[i][0]]); }
    if (blocked[i][1] > cur) { cur = blocked[i][1]; }
  }
  if (1 - cur > 0.004) { free.push([cur, 1]); }
  return free;
}

function placeBand(op, free, rng) {
  if (free.length === 0) { return null; }
  const y1 = op.y + op.h;
  for (let i = 0; i < free.length; i++) {
    if (op.y >= free[i][0] && y1 <= free[i][1]) { return op; }
  }
  const cands = [];
  let total = 0;
  for (let i = 0; i < free.length; i++) {
    const span = free[i][1] - free[i][0];
    if (span >= op.h) { cands.push(free[i]); total += span; }
  }
  if (cands.length === 0) { return null; }
  let r = rng.next() * total;
  let chosen = cands[cands.length - 1];
  for (let i = 0; i < cands.length; i++) {
    r -= (cands[i][1] - cands[i][0]);
    if (r <= 0) { chosen = cands[i]; break; }
  }
  const out = {};
  for (const key in op) { out[key] = op[key]; }
  out.y = rng.range(chosen[0], chosen[1] - op.h);
  return out;
}

function bandPx(op, W, H) {
  let y = Math.round(op.y * H);
  if (y < 0) { y = 0; }
  if (y > H - 1) { y = H - 1; }
  let bh = Math.round(op.h * H);
  if (bh < 1) { bh = 1; }
  if (y + bh > H) { bh = H - y; }
  return { y: y, h: bh };
}

function getCanvas(store, key, w, h) {
  let e = store[key];
  if (!e) {
    const cv = document.createElement('canvas');
    cv.width = Math.max(1, w);
    cv.height = Math.max(1, h);
    e = { cv: cv, ctx: cv.getContext('2d', { willReadFrequently: key === 'small' }) };
    store[key] = e;
    return e;
  }
  if (e.cv.width < w || e.cv.height < h) {
    e.cv.width = Math.max(e.cv.width, w);
    e.cv.height = Math.max(e.cv.height, h);
  }
  return e;
}

function opSliceShift(ctx, W, H, op, store) {
  const b = bandPx(op, W, H);
  const dx = Math.round(op.dx * W);
  if (b.h < 2 || dx === 0 || Math.abs(dx) >= W) { return false; }
  const s = getCanvas(store, 'band', W, b.h);
  s.ctx.clearRect(0, 0, W, b.h);
  s.ctx.drawImage(ctx.canvas, 0, b.y, W, b.h, 0, 0, W, b.h);
  ctx.drawImage(s.cv, 0, 0, W, b.h, dx, b.y, W, b.h);
  const a = Math.abs(dx);
  if (dx > 0) {
    ctx.drawImage(s.cv, W - a, 0, a, b.h, 0, b.y, a, b.h);
  } else {
    ctx.drawImage(s.cv, 0, 0, a, b.h, W - a, b.y, a, b.h);
  }
  return true;
}

function opRgbSplitBand(ctx, W, H, op) {
  const b = bandPx(op, W, H);
  const sx = Math.max(1, Math.round(op.dx * W));
  if (b.h < 2 || sx * 2 >= W) { return false; }
  const img = ctx.getImageData(0, b.y, W, b.h);
  const d = img.data;
  const src = new Uint8ClampedArray(d);
  for (let y = 0; y < b.h; y++) {
    const row = y * W * 4;
    for (let x = 0; x < W; x++) {
      const p = row + x * 4;
      let xr = x - sx;
      if (xr < 0) { xr = 0; }
      let xb = x + sx;
      if (xb > W - 1) { xb = W - 1; }
      d[p] = src[row + xr * 4];
      d[p + 2] = src[row + xb * 4 + 2];
    }
  }
  ctx.putImageData(img, 0, b.y);
  return true;
}

function opBlockScramble(ctx, W, H, op, rng, store) {
  const b = bandPx(op, W, H);
  const rx = Math.max(0, Math.round(op.x * W));
  const rw = Math.min(W - rx, Math.round(op.w * W));
  if (rw < 24 || b.h < 12) { return false; }
  const s = getCanvas(store, 'band', rw, b.h);
  s.ctx.clearRect(0, 0, rw, b.h);
  s.ctx.drawImage(ctx.canvas, rx, b.y, rw, b.h, 0, 0, rw, b.h);
  const cols = Math.max(2, op.cols);
  const rows = Math.max(1, op.rows);
  const cw = rw / cols;
  const ch = b.h / rows;
  let done = 0;
  for (let n = 0; n < op.swaps; n++) {
    const ax = rng.int(0, cols - 1);
    const ay = rng.int(0, rows - 1);
    const bx = rng.int(0, cols - 1);
    const by = rng.int(0, rows - 1);
    if (ax === bx && ay === by) { continue; }
    ctx.drawImage(s.cv, bx * cw, by * ch, cw, ch, rx + ax * cw, b.y + ay * ch, cw, ch);
    ctx.drawImage(s.cv, ax * cw, ay * ch, cw, ch, rx + bx * cw, b.y + by * ch, cw, ch);
    done++;
  }
  return done > 0;
}

function opScanTear(ctx, W, H, op) {
  const b = bandPx(op, W, H);
  if (b.h < 5) { return false; }
  const step = Math.max(2, op.step);
  const dx = Math.round((op.dx || 0) * W);
  let n = 0;
  for (let y = b.y + 1; y < b.y + b.h - 1; y += step) {
    if (op.kind === 'drop') {
      ctx.drawImage(ctx.canvas, 0, y - 1, W, 1, dx, y, W, 1);
    } else {
      ctx.drawImage(ctx.canvas, 0, y, W, 1, dx, y + 1, W, 1);
    }
    n++;
  }
  return n > 0;
}

function opPosterizeBand(ctx, W, H, op) {
  const b = bandPx(op, W, H);
  const levels = Math.max(2, Math.min(12, op.levels));
  if (b.h < 2) { return false; }
  const lut = new Uint8ClampedArray(256);
  const stepIn = 255 / (levels - 1);
  for (let i = 0; i < 256; i++) {
    lut[i] = Math.round(i / stepIn) * stepIn;
  }
  const img = ctx.getImageData(0, b.y, W, b.h);
  const d = img.data;
  for (let i = 0; i < d.length; i += 4) {
    d[i] = lut[d[i]];
    d[i + 1] = lut[d[i + 1]];
    d[i + 2] = lut[d[i + 2]];
  }
  ctx.putImageData(img, 0, b.y);
  return true;
}

function opMonoBand(ctx, W, H, op) {
  const b = bandPx(op, W, H);
  if (b.h < 2) { return false; }
  const co = op.contrast;
  const amt = op.amount;
  const img = ctx.getImageData(0, b.y, W, b.h);
  const d = img.data;
  for (let i = 0; i < d.length; i += 4) {
    const r = d[i], g = d[i + 1], bl = d[i + 2];
    let v = 0.299 * r + 0.587 * g + 0.114 * bl;
    v = (v - 127.5) * co + 127.5;
    d[i] = r + (v - r) * amt;
    d[i + 1] = g + (v - g) * amt;
    d[i + 2] = bl + (v - bl) * amt;
  }
  ctx.putImageData(img, 0, b.y);
  return true;
}

function opPixelBand(ctx, W, H, op, store) {
  const b = bandPx(op, W, H);
  const cell = Math.max(3, op.cell);
  const cw = Math.max(2, Math.round(W / cell));
  const ch = Math.max(1, Math.round(b.h / cell));
  if (b.h < 4 || cw >= W) { return false; }
  const s = getCanvas(store, 'small', cw, ch);
  s.ctx.clearRect(0, 0, cw, ch);
  s.ctx.drawImage(ctx.canvas, 0, b.y, W, b.h, 0, 0, cw, ch);
  const prev = ctx.imageSmoothingEnabled;
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(s.cv, 0, 0, cw, ch, 0, b.y, W, b.h);
  ctx.imageSmoothingEnabled = prev;
  return true;
}

function opLightLeak(ctx, W, H, op) {
  const diag = Math.sqrt(W * W + H * H);
  const wdt = Math.max(10, op.width * diag);
  ctx.save();
  ctx.globalCompositeOperation = 'lighter';
  ctx.translate(op.pos * W, op.posY * H);
  ctx.rotate(op.angle);
  const g = ctx.createLinearGradient(-wdt / 2, 0, wdt / 2, 0);
  g.addColorStop(0, rgbToCss(op.color, 0));
  g.addColorStop(0.45, rgbToCss(op.color, op.alpha));
  g.addColorStop(0.62, rgbToCss(op.color, op.alpha * 0.7));
  g.addColorStop(1, rgbToCss(op.color, 0));
  ctx.fillStyle = g;
  ctx.fillRect(-wdt / 2, -diag, wdt, diag * 2);
  ctx.restore();
  return true;
}

function opHalftoneBand(ctx, W, H, op, store) {
  const b = bandPx(op, W, H);
  const cell = Math.max(3, op.cell);
  const cw = Math.ceil(W / cell);
  const ch = Math.ceil(b.h / cell);
  if (b.h < 6 || cw < 4 || ch < 2 || cw * ch > 90000) { return false; }
  const s = getCanvas(store, 'small', cw, ch);
  s.ctx.clearRect(0, 0, cw, ch);
  s.ctx.drawImage(ctx.canvas, 0, b.y, W, b.h, 0, 0, cw, ch);
  const d = s.ctx.getImageData(0, 0, cw, ch).data;
  const n = cw * ch;
  let ar = 0, ag = 0, ab = 0;
  for (let i = 0; i < n; i++) {
    const p = i * 4;
    ar += d[p]; ag += d[p + 1]; ab += d[p + 2];
  }
  ar /= n; ag /= n; ab /= n;
  const paper = [ar * 0.3 + 255 * 0.7, ag * 0.3 + 255 * 0.7, ab * 0.3 + 255 * 0.7];
  const ink = [ar * 0.22, ag * 0.22, ab * 0.22];
  ctx.save();
  ctx.fillStyle = rgbToCss(paper, 1);
  ctx.fillRect(0, b.y, W, b.h);
  ctx.fillStyle = rgbToCss(ink, 1);
  ctx.beginPath();
  const rmax = cell * 0.66;
  const half = cell / 2;
  for (let y = 0; y < ch; y++) {
    const cy = b.y + y * cell + half;
    for (let x = 0; x < cw; x++) {
      const p = (y * cw + x) * 4;
      const l = (d[p] * 0.299 + d[p + 1] * 0.587 + d[p + 2] * 0.114) / 255;
      const r = (1 - l) * rmax;
      if (r < 0.4) { continue; }
      const cx = x * cell + half;
      ctx.moveTo(cx + r, cy);
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
    }
  }
  ctx.fill();
  ctx.restore();
  return true;
}

function opEdgeGhost(ctx, W, H, op, store) {
  const b = bandPx(op, W, H);
  const ww = Math.min(W, 320);
  const wh = Math.max(6, Math.round(b.h * (ww / W)));
  if (b.h < 12 || ww < 16) { return false; }
  const s = getCanvas(store, 'small', ww, wh);
  s.ctx.clearRect(0, 0, ww, wh);
  s.ctx.drawImage(ctx.canvas, 0, b.y, W, b.h, 0, 0, ww, wh);
  const img = s.ctx.getImageData(0, 0, ww, wh);
  const d = img.data;
  const total = ww * wh;
  const lum = new Float32Array(total);
  for (let i = 0; i < total; i++) {
    const p = i * 4;
    lum[i] = (d[p] * 0.299 + d[p + 1] * 0.587 + d[p + 2] * 0.114) / 255;
  }
  const mag = new Float32Array(total);
  let peak = 1e-6;
  for (let y = 1; y < wh - 1; y++) {
    for (let x = 1; x < ww - 1; x++) {
      const i = y * ww + x;
      const tl = lum[i - ww - 1], tc = lum[i - ww], tr = lum[i - ww + 1];
      const ml = lum[i - 1], mr = lum[i + 1];
      const bl = lum[i + ww - 1], bc = lum[i + ww], br = lum[i + ww + 1];
      const gx = (tr + 2 * mr + br) - (tl + 2 * ml + bl);
      const gy = (bl + 2 * bc + br) - (tl + 2 * tc + tr);
      const m = Math.sqrt(gx * gx + gy * gy);
      mag[i] = m;
      if (m > peak) { peak = m; }
    }
  }
  const cr = op.color[0], cg = op.color[1], cb = op.color[2];
  const alpha = op.alpha;
  for (let i = 0; i < total; i++) {
    const p = i * 4;
    const e = mag[i] / peak;
    d[p] = cr;
    d[p + 1] = cg;
    d[p + 2] = cb;
    d[p + 3] = e * e * 255 * alpha;
  }
  s.ctx.putImageData(img, 0, 0);
  ctx.save();
  ctx.globalCompositeOperation = 'lighter';
  ctx.drawImage(s.cv, 0, 0, ww, wh, Math.round(op.dx * W), b.y + Math.round(op.dy * H), W, b.h);
  ctx.restore();
  return true;
}

function opWaveWarp(ctx, W, H, op) {
  const b = bandPx(op, W, H);
  const amp = op.amp * W;
  const period = Math.max(2, op.period * H);
  if (b.h < 6 || amp < 0.8) { return false; }
  const img = ctx.getImageData(0, b.y, W, b.h);
  const d = img.data;
  const src = new Uint8ClampedArray(d);
  const stride = W * 4;
  for (let y = 0; y < b.h; y++) {
    const row = y * stride;
    const shift = Math.round(amp * Math.sin((y / period) * Math.PI * 2 + op.phase));
    if (shift === 0) { continue; }
    if (shift > 0) {
      const s = Math.min(W, shift);
      d.set(src.subarray(row, row + (W - s) * 4), row + s * 4);
      for (let x = 0; x < s; x++) {
        const p = row + x * 4;
        d[p] = src[row];
        d[p + 1] = src[row + 1];
        d[p + 2] = src[row + 2];
      }
    } else {
      const s = Math.min(W, -shift);
      d.set(src.subarray(row + s * 4, row + stride), row);
      const last = row + (W - 1) * 4;
      for (let x = W - s; x < W; x++) {
        const p = row + x * 4;
        d[p] = src[last];
        d[p + 1] = src[last + 1];
        d[p + 2] = src[last + 2];
      }
    }
  }
  ctx.putImageData(img, 0, b.y);
  return true;
}

function opNoiseBand(ctx, W, H, op, rng) {
  const b = bandPx(op, W, H);
  if (b.h < 2) { return false; }
  const amp = op.amount * 255;
  const img = ctx.getImageData(0, b.y, W, b.h);
  const d = img.data;
  const chroma = op.chroma;
  for (let i = 0; i < d.length; i += 4) {
    const v = (rng.next() - 0.5) * amp;
    if (chroma) {
      d[i] = d[i] + v;
      d[i + 1] = d[i + 1] + (rng.next() - 0.5) * amp;
      d[i + 2] = d[i + 2] + (rng.next() - 0.5) * amp;
    } else {
      d[i] = d[i] + v;
      d[i + 1] = d[i + 1] + v;
      d[i + 2] = d[i + 2] + v;
    }
  }
  ctx.putImageData(img, 0, b.y);
  return true;
}

function runOp(ctx, W, H, op, rng, store) {
  switch (op.type) {
    case 'sliceShift': return opSliceShift(ctx, W, H, op, store);
    case 'rgbSplitBand': return opRgbSplitBand(ctx, W, H, op);
    case 'blockScramble': return opBlockScramble(ctx, W, H, op, rng, store);
    case 'scanTear': return opScanTear(ctx, W, H, op);
    case 'posterizeBand': return opPosterizeBand(ctx, W, H, op);
    case 'monoBand': return opMonoBand(ctx, W, H, op);
    case 'pixelBand': return opPixelBand(ctx, W, H, op, store);
    case 'lightLeak': return opLightLeak(ctx, W, H, op);
    case 'halftoneBand': return opHalftoneBand(ctx, W, H, op, store);
    case 'edgeGhost': return opEdgeGhost(ctx, W, H, op, store);
    case 'waveWarp': return opWaveWarp(ctx, W, H, op);
    case 'noiseBand': return opNoiseBand(ctx, W, H, op, rng);
    default: return false;
  }
}

function applyGlitch(ctx, w, h, plan, rng, faces) {
  const applied = [];
  if (!plan || plan.length === 0 || w < 8 || h < 8) { return applied; }
  const free = freeIntervals(faceBlocked(faces || []));
  const store = {};
  for (let i = 0; i < plan.length; i++) {
    const op = plan[i];
    let placed = op;
    if (op.band) {
      placed = placeBand(op, free, rng);
      if (!placed) { continue; }
    }
    if (runOp(ctx, w, h, placed, rng, store)) { applied.push(placed); }
  }
  return applied;
}

Object.assign(PF, { buildGlitchPlan, applyGlitch });
})(window.PF = window.PF || {});
