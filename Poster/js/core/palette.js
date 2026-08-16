(function (PF) {
'use strict';
const { mulberry32 } = PF;
const { oklabToOklch, oklchToSrgb, oklchToOklab, deltaEOk } = PF;

const DEFAULT_K = 6;
const DEFAULT_ITER = 8;
const DEFAULT_STEP = 3;
const COLORFULNESS_SCALE = 100;
const SKIN = { hMin: 18, hMax: 82, cMin: 0.022, cMax: 0.20, lMin: 0.38, lMax: 0.96 };
const NEUTRAL_CHROMA = 0.040;
const NEUTRAL_COLORFULNESS = 0.13;

function isSkinLch(lch) {
  return lch[2] >= SKIN.hMin && lch[2] <= SKIN.hMax
    && lch[1] >= SKIN.cMin && lch[1] <= SKIN.cMax
    && lch[0] >= SKIN.lMin && lch[0] <= SKIN.lMax;
}

function buildLinearLut() {
  const lut = new Float64Array(256);
  for (let i = 0; i < 256; i++) {
    const v = i / 255;
    lut[i] = v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  }
  return lut;
}

function collectSamples(buf, step) {
  const d = buf.data;
  const w = buf.w;
  const h = buf.h;
  const cols = Math.ceil(w / step);
  const rows = Math.ceil(h / step);
  const lab = new Float64Array(cols * rows * 3);
  const lut = buildLinearLut();
  const cbrt = Math.cbrt;
  let n = 0;
  let hash = 2166136261;
  let sumRg = 0, sumYb = 0, sumRg2 = 0, sumYb2 = 0;
  for (let y = 0; y < h; y += step) {
    const rowBase = y * w;
    for (let x = 0; x < w; x += step) {
      const p = (rowBase + x) * 4;
      if (d[p + 3] < 8) { continue; }
      const r = d[p], g = d[p + 1], b = d[p + 2];
      const lr = lut[r], lg = lut[g], lb = lut[b];
      const cl = cbrt(0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb);
      const cm = cbrt(0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb);
      const cs = cbrt(0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb);
      const o = n * 3;
      lab[o] = 0.2104542553 * cl + 0.7936177850 * cm - 0.0040720468 * cs;
      lab[o + 1] = 1.9779984951 * cl - 2.4285922050 * cm + 0.4505937099 * cs;
      lab[o + 2] = 0.0259040371 * cl + 0.7827717662 * cm - 0.8086757660 * cs;
      n++;
      const rg = r - g;
      const yb = 0.5 * (r + g) - b;
      sumRg += rg;
      sumYb += yb;
      sumRg2 += rg * rg;
      sumYb2 += yb * yb;
      hash = Math.imul(hash ^ (r + (g << 8) + (b << 16)), 16777619);
    }
  }
  return { lab: lab, n: n, hash: hash >>> 0, sumRg: sumRg, sumYb: sumYb, sumRg2: sumRg2, sumYb2: sumYb2 };
}

function haslerSusstrunk(s) {
  if (s.n === 0) { return 0; }
  const mRg = s.sumRg / s.n;
  const mYb = s.sumYb / s.n;
  const vRg = Math.max(0, s.sumRg2 / s.n - mRg * mRg);
  const vYb = Math.max(0, s.sumYb2 / s.n - mYb * mYb);
  const sigma = Math.sqrt(vRg + vYb);
  const mu = Math.sqrt(mRg * mRg + mYb * mYb);
  return sigma + 0.3 * mu;
}

function seedCenters(lab, n, k, rnd) {
  const centers = new Float64Array(k * 3);
  const dist = new Float64Array(n);
  let first = Math.min(n - 1, Math.floor(rnd() * n));
  centers[0] = lab[first * 3];
  centers[1] = lab[first * 3 + 1];
  centers[2] = lab[first * 3 + 2];
  for (let i = 0; i < n; i++) { dist[i] = Infinity; }
  for (let c = 1; c < k; c++) {
    const cx = centers[(c - 1) * 3], cy = centers[(c - 1) * 3 + 1], cz = centers[(c - 1) * 3 + 2];
    let total = 0;
    for (let i = 0; i < n; i++) {
      const o = i * 3;
      const dl = lab[o] - cx, da = lab[o + 1] - cy, db = lab[o + 2] - cz;
      const d2 = dl * dl + da * da + db * db;
      if (d2 < dist[i]) { dist[i] = d2; }
      total += dist[i];
    }
    let target = rnd() * total;
    let pick = n - 1;
    for (let i = 0; i < n; i++) {
      target -= dist[i];
      if (target <= 0) { pick = i; break; }
    }
    centers[c * 3] = lab[pick * 3];
    centers[c * 3 + 1] = lab[pick * 3 + 1];
    centers[c * 3 + 2] = lab[pick * 3 + 2];
  }
  return centers;
}

function kmeans(lab, n, k, iterations, rnd) {
  const centers = seedCenters(lab, n, k, rnd);
  const sums = new Float64Array(k * 3);
  const counts = new Int32Array(k);
  for (let it = 0; it < iterations; it++) {
    sums.fill(0);
    counts.fill(0);
    for (let i = 0; i < n; i++) {
      const o = i * 3;
      const pl = lab[o], pa = lab[o + 1], pb = lab[o + 2];
      let best = 0;
      let bestD = Infinity;
      for (let c = 0; c < k; c++) {
        const q = c * 3;
        const dl = pl - centers[q], da = pa - centers[q + 1], db = pb - centers[q + 2];
        const d2 = dl * dl + da * da + db * db;
        if (d2 < bestD) { bestD = d2; best = c; }
      }
      const t = best * 3;
      sums[t] += pl;
      sums[t + 1] += pa;
      sums[t + 2] += pb;
      counts[best]++;
    }
    for (let c = 0; c < k; c++) {
      if (counts[c] === 0) { continue; }
      const q = c * 3;
      centers[q] = sums[q] / counts[c];
      centers[q + 1] = sums[q + 1] / counts[c];
      centers[q + 2] = sums[q + 2] / counts[c];
    }
  }
  return { centers: centers, counts: counts };
}

function extractPalette(buf, opts) {
  const o = opts || {};
  const k = o.k || DEFAULT_K;
  const iterations = o.iterations || DEFAULT_ITER;
  const step = o.step || DEFAULT_STEP;
  const s = collectSamples(buf, step);
  if (s.n === 0) {
    return {
      clusters: [],
      dominant: null,
      colorfulness: 0,
      colorfulnessRaw: 0,
      temperature: 0,
      meanL: 0,
      chromaSpread: 0,
      isNeutral: true,
      sampleCount: 0
    };
  }
  const rnd = mulberry32(o.seed === undefined ? s.hash : (o.seed >>> 0));
  const km = kmeans(s.lab, s.n, Math.min(k, s.n), iterations, rnd);
  const kk = Math.min(k, s.n);
  const clusters = [];
  for (let c = 0; c < kk; c++) {
    if (km.counts[c] === 0) { continue; }
    const q = c * 3;
    const lab = [km.centers[q], km.centers[q + 1], km.centers[q + 2]];
    const lch = oklabToOklch(lab);
    clusters.push({
      lab: lab,
      lch: lch,
      rgb: oklchToSrgb(lch),
      weight: km.counts[c] / s.n,
      isSkin: isSkinLch(lch)
    });
  }
  clusters.sort((a, b) => b.weight - a.weight);

  let meanL = 0;
  let temperature = 0;
  let meanC = 0;
  for (let i = 0; i < clusters.length; i++) {
    meanL += clusters[i].lch[0] * clusters[i].weight;
    temperature += clusters[i].lab[2] * clusters[i].weight;
    meanC += clusters[i].lch[1] * clusters[i].weight;
  }
  let varC = 0;
  for (let i = 0; i < clusters.length; i++) {
    const d = clusters[i].lch[1] - meanC;
    varC += d * d * clusters[i].weight;
  }
  const raw = haslerSusstrunk(s);
  const colorfulness = Math.min(1, raw / COLORFULNESS_SCALE);
  let maxC = 0;
  for (let i = 0; i < clusters.length; i++) {
    if (clusters[i].lch[1] > maxC) { maxC = clusters[i].lch[1]; }
  }
  return {
    clusters: clusters,
    dominant: clusters.length > 0 ? clusters[0] : null,
    colorfulness: colorfulness,
    colorfulnessRaw: raw,
    temperature: temperature,
    meanL: meanL,
    meanChroma: meanC,
    maxChroma: maxC,
    chromaSpread: Math.sqrt(varC),
    isNeutral: colorfulness < NEUTRAL_COLORFULNESS && maxC < NEUTRAL_CHROMA,
    sampleCount: s.n
  };
}

function pickKeyColor(palette, opts) {
  const o = opts || {};
  const clusters = palette.clusters;
  if (!clusters || clusters.length === 0) {
    return { lch: [palette.meanL || 0.5, 0, 0], rgb: oklchToSrgb([palette.meanL || 0.5, 0, 0]), source: 'neutral', weight: 0, isNeutral: true };
  }
  let pool = clusters;
  let source = 'cluster';
  if (o.excludeSkin) {
    const nonSkin = clusters.filter((c) => !c.isSkin);
    if (nonSkin.length > 0) {
      pool = nonSkin;
      source = 'cluster-nonskin';
    } else {
      source = 'skin';
    }
  }
  let best = null;
  let bestScore = -1;
  for (let i = 0; i < pool.length; i++) {
    const score = pool[i].weight * pool[i].lch[1];
    if (score > bestScore) { bestScore = score; best = pool[i]; }
  }
  if (!best || best.lch[1] < NEUTRAL_CHROMA * 0.5 || palette.isNeutral) {
    const lch = [palette.meanL, 0, 0];
    return { lch: lch, rgb: oklchToSrgb(lch), source: 'neutral', weight: best ? best.weight : 0, isNeutral: true };
  }
  return { lch: best.lch.slice(), rgb: best.rgb.slice(), source: source, weight: best.weight, isNeutral: false };
}

function nearestCluster(palette, lch) {
  const lab = oklchToOklab(lch);
  let best = null;
  let bestD = Infinity;
  for (let i = 0; i < palette.clusters.length; i++) {
    const d = deltaEOk(palette.clusters[i].lab, lab);
    if (d < bestD) { bestD = d; best = palette.clusters[i]; }
  }
  return best;
}

Object.assign(PF, { isSkinLch, extractPalette, pickKeyColor, nearestCluster });
})(window.PF = window.PF || {});
