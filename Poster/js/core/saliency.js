import { buildIntegral, integralSum } from './analysis.js';

function boxBlurFromIntegral(integral, w, h, radius) {
  const out = new Float32Array(w * h);
  const r = Math.max(1, Math.round(radius));
  for (let y = 0; y < h; y++) {
    const y0 = y - r < 0 ? 0 : y - r;
    const y1 = y + r + 1 > h ? h : y + r + 1;
    const rh = y1 - y0;
    for (let x = 0; x < w; x++) {
      const x0 = x - r < 0 ? 0 : x - r;
      const x1 = x + r + 1 > w ? w : x + r + 1;
      const rw = x1 - x0;
      out[y * w + x] = integralSum(integral, w, x0, y0, rw, rh) / (rw * rh);
    }
  }
  return out;
}

function normalizeInPlace(map) {
  let max = 1e-6;
  for (let i = 0; i < map.length; i++) { if (map[i] > max) { max = map[i]; } }
  let sum = 0;
  for (let i = 0; i < map.length; i++) { map[i] /= max; sum += map[i]; }
  const mean = sum / map.length;
  const gain = (1 - mean) * (1 - mean);
  return gain;
}

function centerSurround(channel, w, h, scales) {
  const integral = buildIntegral(channel, w, h);
  const blurred = [];
  for (let i = 0; i < scales.length; i++) {
    blurred.push(boxBlurFromIntegral(integral, w, h, scales[i]));
  }
  const feature = new Float32Array(w * h);
  const pairs = [[0, 2], [0, 3], [1, 3], [1, 4]];
  for (let p = 0; p < pairs.length; p++) {
    const c = blurred[pairs[p][0]];
    const s = blurred[pairs[p][1]];
    if (!c || !s) { continue; }
    const layer = new Float32Array(w * h);
    for (let i = 0; i < layer.length; i++) {
      const d = c[i] - s[i];
      layer[i] = d < 0 ? -d : d;
    }
    const gain = normalizeInPlace(layer);
    for (let i = 0; i < feature.length; i++) { feature[i] += layer[i] * gain; }
  }
  normalizeInPlace(feature);
  return feature;
}

function buildOpponentChannels(buf) {
  const n = buf.w * buf.h;
  const d = buf.data;
  const rg = new Float32Array(n);
  const by = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const p = i * 4;
    const r = d[p], g = d[p + 1], b = d[p + 2];
    const max = r > g ? (r > b ? r : b) : (g > b ? g : b);
    if (max < 20) { continue; }
    const min = r < g ? r : g;
    rg[i] = (r - g) / max;
    by[i] = (b - min) / max;
  }
  return { rg: rg, by: by };
}

function robustScale(map, w, h) {
  const bins = 256;
  const hist = new Int32Array(bins);
  let max = 1e-6;
  for (let i = 0; i < map.length; i++) { if (map[i] > max) { max = map[i]; } }
  for (let i = 0; i < map.length; i++) {
    let b = Math.floor((map[i] / max) * (bins - 1));
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
  for (let i = 0; i < map.length; i++) {
    let v = map[i] / hi;
    map[i] = v > 1 ? 1 : v;
  }
  return map;
}

export function computeSaliency(buf, luma) {
  const w = buf.w;
  const h = buf.h;
  const n = w * h;
  const base = luma && luma.length === n ? luma : null;
  const intensity = new Float32Array(n);
  if (base) {
    intensity.set(base);
  } else {
    const d = buf.data;
    for (let i = 0; i < n; i++) {
      const p = i * 4;
      intensity[i] = (0.299 * d[p] + 0.587 * d[p + 1] + 0.114 * d[p + 2]) / 255;
    }
  }

  const unit = Math.max(1, w / 96);
  const scales = [unit, unit * 2, unit * 4, unit * 8, unit * 16];
  const opponent = buildOpponentChannels(buf);

  const fIntensity = centerSurround(intensity, w, h, scales);
  const fRg = centerSurround(opponent.rg, w, h, scales);
  const fBy = centerSurround(opponent.by, w, h, scales);

  const merged = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    merged[i] = 0.50 * fIntensity[i] + 0.28 * fRg[i] + 0.22 * fBy[i];
  }

  const smoothed = boxBlurFromIntegral(buildIntegral(merged, w, h), w, h, Math.max(1, Math.round(unit)));

  const invSpanX = 1 / (w * 0.5);
  const invSpanY = 1 / (h * 0.5);
  for (let y = 0; y < h; y++) {
    const dy = (y + 0.5 - h * 0.5) * invSpanY;
    for (let x = 0; x < w; x++) {
      const dx = (x + 0.5 - w * 0.5) * invSpanX;
      const prior = 0.74 + 0.26 * Math.exp(-(dx * dx + dy * dy) / 0.55);
      smoothed[y * w + x] *= prior;
    }
  }

  robustScale(smoothed, w, h);
  return { map: smoothed, w: w, h: h };
}
