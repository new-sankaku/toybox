(function (PF) {
'use strict';
const { buildIntegral } = PF;

const FEATURE_PAIRS = [[0, 2], [1, 3], [2, 4]];

function boxBlurFromIntegral(integral, w, h, radius) {
  const out = new Float32Array(w * h);
  const iw = w + 1;
  const r = Math.max(1, Math.round(radius));
  for (let y = 0; y < h; y++) {
    const y0 = y - r < 0 ? 0 : y - r;
    const y1 = y + r + 1 > h ? h : y + r + 1;
    const top = y0 * iw;
    const bottom = y1 * iw;
    const rh = y1 - y0;
    const row = y * w;
    for (let x = 0; x < w; x++) {
      const x0 = x - r < 0 ? 0 : x - r;
      const x1 = x + r + 1 > w ? w : x + r + 1;
      const sum = integral[bottom + x1] - integral[top + x1] - integral[bottom + x0] + integral[top + x0];
      out[row + x] = sum / ((x1 - x0) * rh);
    }
  }
  return out;
}

function normalizeInPlace(map) {
  let max = 1e-6;
  for (let i = 0; i < map.length; i++) { if (map[i] > max) { max = map[i]; } }
  let sum = 0;
  const inv = 1 / max;
  for (let i = 0; i < map.length; i++) {
    const v = map[i] * inv;
    map[i] = v;
    sum += v;
  }
  const mean = sum / map.length;
  return (1 - mean) * (1 - mean);
}

function centerSurround(channel, w, h, scales) {
  const integral = buildIntegral(channel, w, h);
  const blurred = [];
  for (let i = 0; i < scales.length; i++) {
    blurred.push(boxBlurFromIntegral(integral, w, h, scales[i]));
  }
  const feature = new Float32Array(w * h);
  for (let p = 0; p < FEATURE_PAIRS.length; p++) {
    const center = blurred[FEATURE_PAIRS[p][0]];
    const surround = blurred[FEATURE_PAIRS[p][1]];
    const layer = new Float32Array(w * h);
    for (let i = 0; i < layer.length; i++) {
      const d = center[i] - surround[i];
      layer[i] = d < 0 ? -d : d;
    }
    const gain = normalizeInPlace(layer);
    for (let i = 0; i < feature.length; i++) { feature[i] += layer[i] * gain; }
  }
  normalizeInPlace(feature);
  return feature;
}

function buildChannels(buf, step) {
  const w = buf.w, h = buf.h, d = buf.data;
  const cw = Math.max(1, Math.floor(w / step));
  const ch = Math.max(1, Math.floor(h / step));
  const n = cw * ch;
  const intensity = new Float32Array(n);
  const rg = new Float32Array(n);
  const by = new Float32Array(n);
  for (let y = 0; y < ch; y++) {
    for (let x = 0; x < cw; x++) {
      let sr = 0, sg = 0, sb = 0, count = 0;
      const sy1 = Math.min(h, (y + 1) * step);
      const sx1 = Math.min(w, (x + 1) * step);
      for (let sy = y * step; sy < sy1; sy++) {
        for (let sx = x * step; sx < sx1; sx++) {
          const p = (sy * w + sx) * 4;
          sr += d[p]; sg += d[p + 1]; sb += d[p + 2];
          count++;
        }
      }
      const r = sr / count, g = sg / count, b = sb / count;
      const i = y * cw + x;
      intensity[i] = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
      const max = r > g ? (r > b ? r : b) : (g > b ? g : b);
      if (max >= 20) {
        const min = r < g ? r : g;
        rg[i] = (r - g) / max;
        by[i] = (b - min) / max;
      }
    }
  }
  return { w: cw, h: ch, intensity: intensity, rg: rg, by: by };
}

function upsample(src, sw, sh, w, h) {
  if (sw === w && sh === h) { return src; }
  const out = new Float32Array(w * h);
  const scaleX = sw / w;
  const scaleY = sh / h;
  for (let y = 0; y < h; y++) {
    let fy = (y + 0.5) * scaleY - 0.5;
    if (fy < 0) { fy = 0; }
    if (fy > sh - 1) { fy = sh - 1; }
    const y0 = Math.floor(fy);
    const y1 = y0 + 1 < sh ? y0 + 1 : y0;
    const wy = fy - y0;
    const row0 = y0 * sw;
    const row1 = y1 * sw;
    const outRow = y * w;
    for (let x = 0; x < w; x++) {
      let fx = (x + 0.5) * scaleX - 0.5;
      if (fx < 0) { fx = 0; }
      if (fx > sw - 1) { fx = sw - 1; }
      const x0 = Math.floor(fx);
      const x1 = x0 + 1 < sw ? x0 + 1 : x0;
      const wx = fx - x0;
      const a = src[row0 + x0] + (src[row0 + x1] - src[row0 + x0]) * wx;
      const b = src[row1 + x0] + (src[row1 + x1] - src[row1 + x0]) * wx;
      out[outRow + x] = a + (b - a) * wy;
    }
  }
  return out;
}

function robustScale(map) {
  const bins = 256;
  const hist = new Int32Array(bins);
  let max = 1e-6;
  for (let i = 0; i < map.length; i++) { if (map[i] > max) { max = map[i]; } }
  const scale = (bins - 1) / max;
  for (let i = 0; i < map.length; i++) {
    let b = (map[i] * scale) | 0;
    if (b < 0) { b = 0; }
    hist[b]++;
  }
  const cutCount = map.length * 0.99;
  let acc = 0;
  let top = bins - 1;
  for (let b = 0; b < bins; b++) {
    acc += hist[b];
    if (acc >= cutCount) { top = b; break; }
  }
  const hi = Math.max(1e-6, ((top + 1) / bins) * max);
  const inv = 1 / hi;
  for (let i = 0; i < map.length; i++) {
    const v = map[i] * inv;
    map[i] = v > 1 ? 1 : v;
  }
}

function applyCenterPrior(map, w, h) {
  const invSpanX = 1 / (w * 0.5);
  const invSpanY = 1 / (h * 0.5);
  const rowPrior = new Float32Array(h);
  for (let y = 0; y < h; y++) {
    const dy = (y + 0.5 - h * 0.5) * invSpanY;
    rowPrior[y] = dy * dy;
  }
  const colPrior = new Float32Array(w);
  for (let x = 0; x < w; x++) {
    const dx = (x + 0.5 - w * 0.5) * invSpanX;
    colPrior[x] = dx * dx;
  }
  for (let y = 0; y < h; y++) {
    const row = y * w;
    const ry = rowPrior[y];
    for (let x = 0; x < w; x++) {
      map[row + x] *= 0.74 + 0.26 * Math.exp(-(ry + colPrior[x]) / 0.55);
    }
  }
}

function computeSaliency(buf, luma) {
  const w = buf.w;
  const h = buf.h;
  const step = w >= 128 && h >= 128 ? 2 : 1;
  const channels = buildChannels(buf, step);
  const cw = channels.w;
  const ch = channels.h;

  const unit = Math.max(1, cw / 96);
  const scales = [unit, unit * 2, unit * 4, unit * 8, unit * 16];

  const fIntensity = centerSurround(channels.intensity, cw, ch, scales);
  const fRg = centerSurround(channels.rg, cw, ch, scales);
  const fBy = centerSurround(channels.by, cw, ch, scales);

  const merged = new Float32Array(cw * ch);
  for (let i = 0; i < merged.length; i++) {
    merged[i] = 0.50 * fIntensity[i] + 0.28 * fRg[i] + 0.22 * fBy[i];
  }

  const full = upsample(merged, cw, ch, w, h);
  const map = boxBlurFromIntegral(buildIntegral(full, w, h), w, h, Math.max(1, Math.round(w / 128)));

  if (luma && luma.length === w * h) {
    const detail = new Float32Array(w * h);
    const blurredLuma = boxBlurFromIntegral(buildIntegral(luma, w, h), w, h, Math.max(2, Math.round(w / 48)));
    for (let i = 0; i < detail.length; i++) {
      const d = luma[i] - blurredLuma[i];
      detail[i] = d < 0 ? -d : d;
    }
    normalizeInPlace(detail);
    for (let i = 0; i < map.length; i++) { map[i] += 0.22 * detail[i]; }
  }

  applyCenterPrior(map, w, h);
  robustScale(map);
  return { map: map, w: w, h: h };
}

Object.assign(PF, { computeSaliency });
})(window.PF = window.PF || {});
