import { contrastRatio } from './color.js';
import {
  srgbToOklch,
  srgbToOklab,
  oklchToSrgb,
  deltaEOk,
  deltaEOkLch,
  hueDistance,
  mod360,
  clamp01,
  apcaContrast,
  simulateCvd
} from './oklch.js';

export const SCHEMES = [
  'monochromatic',
  'analogous',
  'complementary',
  'splitComplementary',
  'triadic',
  'tetradic',
  'accentedNeutral',
  'analogousComplement'
];

const HUE_ANCHOR_H = [0, 29, 60, 90, 110, 142, 170, 195, 230, 264, 290, 304, 328, 360];
const HUE_ANCHOR_P = [0, 34, 70, 96, 116, 140, 155, 170, 192, 215, 262, 286, 318, 360];

const LOW_COLORFUL_W = {
  monochromatic: 0.50,
  analogous: 0.75,
  complementary: 1.80,
  splitComplementary: 1.50,
  triadic: 1.60,
  tetradic: 1.15,
  accentedNeutral: 0.85,
  analogousComplement: 1.30
};
const HIGH_COLORFUL_W = {
  monochromatic: 1.80,
  analogous: 1.70,
  complementary: 0.50,
  splitComplementary: 0.50,
  triadic: 0.35,
  tetradic: 0.30,
  accentedNeutral: 1.90,
  analogousComplement: 0.60
};

export const VIBRATION = { hueMin: 150, lightMax: 0.15, chromaMin: 0.12 };
export const CHROMA_BUDGET = { high: 0.14, low: 0.08, maxHigh: 1, mergeDe: 0.025 };
export const SIMULTANEOUS = { bgChroma: 0.10, textChroma: 0.05, bandMin: 15, bandMax: 75 };
export const CVD_TYPES = ['protan', 'deutan'];
export const CVD_RELAX = 0.8;
export const CVD_MIN_DE = 0.08;

function piecewise(src, dst, v) {
  const x = mod360(v);
  for (let i = 1; i < src.length; i++) {
    if (x <= src[i]) {
      const span = src[i] - src[i - 1];
      const t = span <= 0 ? 0 : (x - src[i - 1]) / span;
      return dst[i - 1] + (dst[i] - dst[i - 1]) * t;
    }
  }
  return dst[dst.length - 1];
}

export function warpHue(h) {
  return piecewise(HUE_ANCHOR_H, HUE_ANCHOR_P, h);
}

export function unwarpHue(p) {
  return piecewise(HUE_ANCHOR_P, HUE_ANCHOR_H, p);
}

export function rotateHue(h, deg) {
  return mod360(unwarpHue(mod360(warpHue(h) + deg)));
}

function lch(L, C, h) {
  return [clamp01(L), C < 0 ? 0 : C, mod360(h)];
}

export function buildScheme(rng, keyLch, schemeName) {
  const L = clamp01(keyLch[0]);
  const C = Math.max(keyLch[1], 0.02);
  const h = mod360(keyLch[2]);
  const j = () => rng.range(-6, 6);
  switch (schemeName) {
    case 'monochromatic':
      return [
        lch(L, C, h),
        lch(L + rng.range(0.18, 0.30), C * rng.range(0.35, 0.60), rotateHue(h, j())),
        lch(L - rng.range(0.18, 0.30), C * rng.range(0.60, 0.95), rotateHue(h, j())),
        lch(L + rng.range(-0.08, 0.08), C * rng.range(0.15, 0.32), h)
      ];
    case 'analogous': {
      const d = rng.range(18, 42);
      return [
        lch(L, C, h),
        lch(L + rng.range(0.06, 0.20), C * rng.range(0.7, 1.05), rotateHue(h, d)),
        lch(L - rng.range(0.06, 0.20), C * rng.range(0.7, 1.05), rotateHue(h, -d)),
        lch(L + rng.range(-0.05, 0.05), C * rng.range(0.3, 0.55), rotateHue(h, d * 2))
      ];
    }
    case 'complementary': {
      const c2 = rotateHue(h, 180 + j());
      return [
        lch(L, C, h),
        lch(L + (L < 0.5 ? rng.range(0.18, 0.34) : -rng.range(0.18, 0.34)), C * rng.range(0.8, 1.15), c2),
        lch(L + rng.range(-0.12, 0.12), C * rng.range(0.25, 0.45), h),
        lch(L + rng.range(-0.1, 0.1), C * rng.range(0.2, 0.4), c2)
      ];
    }
    case 'splitComplementary': {
      const spread = rng.range(24, 40);
      return [
        lch(L, C, h),
        lch(L + rng.range(0.10, 0.28), C * rng.range(0.7, 1.05), rotateHue(h, 180 - spread)),
        lch(L - rng.range(0.10, 0.28), C * rng.range(0.7, 1.05), rotateHue(h, 180 + spread)),
        lch(L + rng.range(-0.06, 0.06), C * rng.range(0.2, 0.4), h)
      ];
    }
    case 'triadic':
      return [
        lch(L, C, h),
        lch(L + rng.range(0.08, 0.26), C * rng.range(0.65, 1.0), rotateHue(h, 120 + j())),
        lch(L - rng.range(0.08, 0.26), C * rng.range(0.65, 1.0), rotateHue(h, 240 + j())),
        lch(L + rng.range(-0.05, 0.05), C * rng.range(0.2, 0.4), h)
      ];
    case 'tetradic': {
      const rect = rng.chance(0.5);
      const a = rect ? 60 : 90;
      return [
        lch(L, C, h),
        lch(L + rng.range(0.10, 0.24), C * rng.range(0.6, 0.95), rotateHue(h, a + j())),
        lch(L - rng.range(0.10, 0.24), C * rng.range(0.6, 0.95), rotateHue(h, 180 + j())),
        lch(L + rng.range(-0.16, 0.16), C * rng.range(0.5, 0.85), rotateHue(h, 180 + a + j()))
      ];
    }
    case 'accentedNeutral': {
      const nh = rotateHue(h, rng.range(-10, 10));
      return [
        lch(L, 0.014, nh),
        lch(L + rng.range(0.22, 0.40), 0.020, nh),
        lch(L - rng.range(0.22, 0.40), 0.016, nh),
        lch(clamp01(L + rng.range(-0.18, 0.18)), C * rng.range(1.1, 1.6), rotateHue(h, rng.range(140, 220)))
      ];
    }
    case 'analogousComplement': {
      const d = rng.range(20, 38);
      return [
        lch(L, C, h),
        lch(L + rng.range(0.08, 0.22), C * rng.range(0.7, 1.0), rotateHue(h, rng.sign() * d)),
        lch(L - rng.range(0.08, 0.22), C * rng.range(0.8, 1.2), rotateHue(h, 180 + j())),
        lch(L + rng.range(-0.06, 0.06), C * rng.range(0.2, 0.4), h)
      ];
    }
    default:
      return null;
  }
}

export function chooseScheme(rng, palette, genreWeights) {
  const t = clamp01((palette.colorfulness - 0.20) / 0.40);
  const items = [];
  for (let i = 0; i < SCHEMES.length; i++) {
    const name = SCHEMES[i];
    const base = LOW_COLORFUL_W[name] + (HIGH_COLORFUL_W[name] - LOW_COLORFUL_W[name]) * t;
    const g = genreWeights && genreWeights[name] !== undefined ? genreWeights[name] : 1;
    let w = base * g;
    if (palette.isNeutral && (name === 'monochromatic' || name === 'analogous')) { w *= 0.25; }
    if (palette.chromaSpread > 0.07 && (name === 'triadic' || name === 'tetradic')) { w *= 0.6; }
    items.push({ v: name, w: Math.max(0.01, w) });
  }
  return rng.weighted(items);
}

export function hasVibration(a, b) {
  return hueDistance(a[2], b[2]) >= VIBRATION.hueMin
    && Math.abs(a[0] - b[0]) < VIBRATION.lightMax
    && a[1] > VIBRATION.chromaMin
    && b[1] > VIBRATION.chromaMin;
}

export function hasSimultaneousShift(textLch, bgLch) {
  if (bgLch[1] <= SIMULTANEOUS.bgChroma) { return false; }
  if (textLch[1] <= SIMULTANEOUS.textChroma) { return false; }
  const d = hueDistance(textLch[2], bgLch[2]);
  return d > SIMULTANEOUS.bandMin && d < SIMULTANEOUS.bandMax;
}

export function enforceChromaBudget(colors, budget) {
  const b = budget || CHROMA_BUDGET;
  const out = colors.map((c) => [c[0], c[1], c[2]]);
  const order = out.map((c, i) => i).sort((x, y) => out[y][1] - out[x][1]);
  const kept = [];
  for (let i = 0; i < order.length; i++) {
    const idx = order[i];
    const c = out[idx];
    if (c[1] <= b.high) { continue; }
    let merged = false;
    for (let m = 0; m < kept.length; m++) {
      if (deltaEOkLch(c, kept[m]) <= b.mergeDe) { merged = true; break; }
    }
    if (merged) { continue; }
    if (kept.length < b.maxHigh) { kept.push([c[0], c[1], c[2]]); continue; }
    c[1] = b.low;
  }
  return out;
}

export function violatesChromaBudget(colors, budget) {
  const b = budget || CHROMA_BUDGET;
  const high = [];
  const mid = [];
  for (let i = 0; i < colors.length; i++) {
    const c = colors[i];
    if (c[1] > b.high) {
      let merged = false;
      for (let m = 0; m < high.length; m++) {
        if (deltaEOkLch(c, high[m]) <= b.mergeDe) { merged = true; break; }
      }
      if (!merged) { high.push(c); }
    } else if (c[1] > b.low) {
      let merged = false;
      for (let m = 0; m < high.length; m++) {
        if (deltaEOkLch(c, high[m]) <= b.mergeDe) { merged = true; break; }
      }
      if (!merged) { mid.push(c); }
    }
  }
  return high.length > b.maxHigh || mid.length > 0;
}

export function separateLightness(fixed, movable, minDelta) {
  const d = movable[0] - fixed[0];
  if (Math.abs(d) >= minDelta) { return movable; }
  const up = fixed[0] + minDelta;
  const down = fixed[0] - minDelta;
  const canUp = up <= 1;
  const canDown = down >= 0;
  let target;
  if (canUp && canDown) { target = (d >= 0) ? up : down; }
  else if (canUp) { target = up; }
  else if (canDown) { target = down; }
  else { target = fixed[0] >= 0.5 ? 0 : 1; }
  return [clamp01(target), movable[1], movable[2]];
}

export function enforceLightnessSpread(colors, minDelta) {
  const idx = colors.map((c, i) => i).sort((a, b) => colors[a][0] - colors[b][0]);
  const out = colors.map((c) => [c[0], c[1], c[2]]);
  for (let i = 1; i < idx.length; i++) {
    const prev = out[idx[i - 1]];
    const cur = out[idx[i]];
    if (cur[0] - prev[0] < minDelta) { cur[0] = clamp01(prev[0] + minDelta); }
  }
  return out;
}

export function cvdContrastOk(fgRgb, bgRgb, minWcag) {
  for (let i = 0; i < CVD_TYPES.length; i++) {
    const f = simulateCvd(fgRgb, CVD_TYPES[i]);
    const b = simulateCvd(bgRgb, CVD_TYPES[i]);
    if (contrastRatio(f, b) < minWcag * CVD_RELAX) { return false; }
    if (deltaEOk(srgbToOklab(f), srgbToOklab(b)) < CVD_MIN_DE) { return false; }
  }
  return true;
}

export function pickReadable(candidates, bgRgb, minWcag, minApca) {
  if (!candidates || candidates.length === 0) { return null; }
  const bgLch = srgbToOklch(bgRgb);
  let best = null;
  let bestScore = -Infinity;
  for (let i = 0; i < candidates.length; i++) {
    const rgb = candidates[i];
    const wcag = contrastRatio(rgb, bgRgb);
    if (wcag < minWcag) { continue; }
    const lc = Math.abs(apcaContrast(rgb, bgRgb));
    if (lc < minApca) { continue; }
    const cl = srgbToOklch(rgb);
    if (hasVibration(cl, bgLch)) { continue; }
    if (hasSimultaneousShift(cl, bgLch)) { continue; }
    if (!cvdContrastOk(rgb, bgRgb, minWcag)) { continue; }
    const score = lc / 100 + Math.min(wcag, 12) / 24 + cl[1];
    if (score > bestScore) { bestScore = score; best = rgb; }
  }
  return best;
}

export function readableCandidates(candidates, bgRgb, minWcag, minApca) {
  const out = [];
  const bgLch = srgbToOklch(bgRgb);
  for (let i = 0; i < candidates.length; i++) {
    const rgb = candidates[i];
    if (contrastRatio(rgb, bgRgb) < minWcag) { continue; }
    if (Math.abs(apcaContrast(rgb, bgRgb)) < minApca) { continue; }
    const cl = srgbToOklch(rgb);
    if (hasVibration(cl, bgLch)) { continue; }
    if (hasSimultaneousShift(cl, bgLch)) { continue; }
    if (!cvdContrastOk(rgb, bgRgb, minWcag)) { continue; }
    out.push(rgb);
  }
  return out;
}

export function lightnessLadder(baseLch, steps, maxChroma) {
  const out = [];
  const n = Math.max(2, steps);
  for (let i = 0; i < n; i++) {
    const t = i / (n - 1);
    const L = 0.06 + t * 0.93;
    const bell = 1 - Math.abs(t - 0.5) * 2;
    const C = Math.min(maxChroma, maxChroma * bell * bell);
    out.push([L, C, baseLch[2]]);
  }
  return out;
}

export function toRgbList(lchList) {
  const out = [];
  for (let i = 0; i < lchList.length; i++) { out.push(oklchToSrgb(lchList[i])); }
  return out;
}
