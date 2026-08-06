import { clamp255, contrastRatio } from './color.js';

const GAMUT_EPS = 1e-9;
const GAMUT_ITER = 26;
const APCA = {
  trc: 2.4,
  rc: 0.2126729,
  gc: 0.7151522,
  bc: 0.0721750,
  normBg: 0.56,
  normTxt: 0.57,
  revTxt: 0.62,
  revBg: 0.65,
  blkThrs: 0.022,
  blkClmp: 1.414,
  scaleBoW: 1.14,
  scaleWoB: 1.14,
  loBoWoffset: 0.027,
  loWoBoffset: 0.027,
  deltaYmin: 0.0005,
  loClip: 0.1
};
const CVD_LMS = [
  17.8824, 43.5161, 4.11935,
  3.45565, 27.1554, 3.86714,
  0.0299566, 0.184309, 1.46709
];
const CVD_LMS_INV = [
  0.0809444479, -0.130504409, 0.116721066,
  -0.0102485335, 0.0540193266, -0.113614708,
  -0.000365296938, -0.00412161469, 0.693511405
];
const CVD_MAT = {
  protan: [0, 2.02344, -2.52581],
  deutan: [0.494207, 0, 1.24827],
  tritan: [-0.395913, 0.801109, 0]
};

export function clamp01(v) {
  return v < 0 ? 0 : (v > 1 ? 1 : v);
}

export function mod360(h) {
  let x = h % 360;
  if (x < 0) { x += 360; }
  return x;
}

export function srgbChannelToLinear(v) {
  const c = v / 255;
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

export function linearChannelToSrgb(v) {
  const c = v <= 0.0031308 ? v * 12.92 : 1.055 * Math.pow(v, 1 / 2.4) - 0.055;
  return c * 255;
}

export function linearRgbToOklab(lin) {
  const r = lin[0], g = lin[1], b = lin[2];
  const l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b;
  const m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b;
  const s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b;
  const lc = Math.cbrt(l), mc = Math.cbrt(m), sc = Math.cbrt(s);
  return [
    0.2104542553 * lc + 0.7936177850 * mc - 0.0040720468 * sc,
    1.9779984951 * lc - 2.4285922050 * mc + 0.4505937099 * sc,
    0.0259040371 * lc + 0.7827717662 * mc - 0.8086757660 * sc
  ];
}

export function oklabToLinearRgb(lab) {
  const L = lab[0], a = lab[1], b = lab[2];
  const lc = L + 0.3963377774 * a + 0.2158037573 * b;
  const mc = L - 0.1055613458 * a - 0.0638541728 * b;
  const sc = L - 0.0894841775 * a - 1.2914855480 * b;
  const l = lc * lc * lc, m = mc * mc * mc, s = sc * sc * sc;
  return [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
  ];
}

export function srgbToOklab(rgb) {
  return linearRgbToOklab([
    srgbChannelToLinear(rgb[0]),
    srgbChannelToLinear(rgb[1]),
    srgbChannelToLinear(rgb[2])
  ]);
}

export function oklabToSrgb(lab) {
  const lin = oklabToLinearRgb(lab);
  return [
    clamp255(linearChannelToSrgb(lin[0] < 0 ? 0 : (lin[0] > 1 ? 1 : lin[0]))),
    clamp255(linearChannelToSrgb(lin[1] < 0 ? 0 : (lin[1] > 1 ? 1 : lin[1]))),
    clamp255(linearChannelToSrgb(lin[2] < 0 ? 0 : (lin[2] > 1 ? 1 : lin[2])))
  ];
}

export function oklabToOklch(lab) {
  const a = lab[1], b = lab[2];
  const c = Math.sqrt(a * a + b * b);
  const h = c < 1e-9 ? 0 : mod360(Math.atan2(b, a) * 180 / Math.PI);
  return [lab[0], c, h];
}

export function oklchToOklab(lch) {
  const rad = lch[2] * Math.PI / 180;
  return [lch[0], lch[1] * Math.cos(rad), lch[1] * Math.sin(rad)];
}

export function srgbToOklch(rgb) {
  return oklabToOklch(srgbToOklab(rgb));
}

function linearInGamut(lin) {
  return lin[0] >= -GAMUT_EPS && lin[0] <= 1 + GAMUT_EPS
    && lin[1] >= -GAMUT_EPS && lin[1] <= 1 + GAMUT_EPS
    && lin[2] >= -GAMUT_EPS && lin[2] <= 1 + GAMUT_EPS;
}

export function isInGamut(lch) {
  return linearInGamut(oklabToLinearRgb(oklchToOklab(lch)));
}

export function clampChroma(lch) {
  const L = clamp01(lch[0]);
  const h = mod360(lch[2]);
  const c0 = lch[1] < 0 ? 0 : lch[1];
  if (linearInGamut(oklabToLinearRgb(oklchToOklab([L, c0, h])))) { return [L, c0, h]; }
  let lo = 0;
  let hi = c0;
  for (let i = 0; i < GAMUT_ITER; i++) {
    const mid = (lo + hi) / 2;
    if (linearInGamut(oklabToLinearRgb(oklchToOklab([L, mid, h])))) { lo = mid; } else { hi = mid; }
  }
  return [L, lo, h];
}

export function oklchToSrgb(lch) {
  const safe = clampChroma(lch);
  const lin = oklabToLinearRgb(oklchToOklab(safe));
  return [
    clamp255(linearChannelToSrgb(lin[0] < 0 ? 0 : (lin[0] > 1 ? 1 : lin[0]))),
    clamp255(linearChannelToSrgb(lin[1] < 0 ? 0 : (lin[1] > 1 ? 1 : lin[1]))),
    clamp255(linearChannelToSrgb(lin[2] < 0 ? 0 : (lin[2] > 1 ? 1 : lin[2])))
  ];
}

export function deltaEOk(a, b) {
  const dl = a[0] - b[0];
  const da = a[1] - b[1];
  const db = a[2] - b[2];
  return Math.sqrt(dl * dl + da * da + db * db);
}

export function deltaEOkLch(a, b) {
  return deltaEOk(oklchToOklab(a), oklchToOklab(b));
}

export function hueDistance(a, b) {
  const d = Math.abs(mod360(a) - mod360(b));
  return d > 180 ? 360 - d : d;
}

export function mixOklch(a, b, t) {
  const ha = mod360(a[2]);
  const hb = mod360(b[2]);
  let dh = hb - ha;
  if (dh > 180) { dh -= 360; }
  if (dh < -180) { dh += 360; }
  const ca = a[1], cb = b[1];
  const h = (ca < 1e-6) ? hb : ((cb < 1e-6) ? ha : mod360(ha + dh * t));
  return [a[0] + (b[0] - a[0]) * t, ca + (cb - ca) * t, h];
}

export function pullHue(h, target, strength) {
  return mixOklch([0, 1, h], [0, 1, target], strength)[2];
}

function apcaY(rgb) {
  const y = APCA.rc * Math.pow(clamp255(rgb[0]) / 255, APCA.trc)
    + APCA.gc * Math.pow(clamp255(rgb[1]) / 255, APCA.trc)
    + APCA.bc * Math.pow(clamp255(rgb[2]) / 255, APCA.trc);
  return y < APCA.blkThrs ? y + Math.pow(APCA.blkThrs - y, APCA.blkClmp) : y;
}

export function apcaContrast(textRgb, bgRgb) {
  const yt = apcaY(textRgb);
  const yb = apcaY(bgRgb);
  if (Math.abs(yb - yt) < APCA.deltaYmin) { return 0; }
  let sapc;
  let out;
  if (yb > yt) {
    sapc = (Math.pow(yb, APCA.normBg) - Math.pow(yt, APCA.normTxt)) * APCA.scaleBoW;
    out = sapc < APCA.loClip ? 0 : sapc - APCA.loBoWoffset;
  } else {
    sapc = (Math.pow(yb, APCA.revBg) - Math.pow(yt, APCA.revTxt)) * APCA.scaleWoB;
    out = sapc > -APCA.loClip ? 0 : sapc + APCA.loWoBoffset;
  }
  return out * 100;
}

export function apcaThreshold(fontPx, weight) {
  const w = weight >= 700 ? 1 : 0;
  if (fontPx >= 96) { return w ? 30 : 35; }
  if (fontPx >= 48) { return w ? 38 : 45; }
  if (fontPx >= 32) { return w ? 45 : 55; }
  if (fontPx >= 24) { return w ? 55 : 65; }
  return w ? 65 : 75;
}

export function simulateCvd(rgb, type) {
  const m = CVD_MAT[type];
  if (!m) { return [rgb[0], rgb[1], rgb[2]]; }
  const r = srgbChannelToLinear(rgb[0]);
  const g = srgbChannelToLinear(rgb[1]);
  const b = srgbChannelToLinear(rgb[2]);
  const L = CVD_LMS[0] * r + CVD_LMS[1] * g + CVD_LMS[2] * b;
  const M = CVD_LMS[3] * r + CVD_LMS[4] * g + CVD_LMS[5] * b;
  const S = CVD_LMS[6] * r + CVD_LMS[7] * g + CVD_LMS[8] * b;
  let L2 = L, M2 = M, S2 = S;
  if (type === 'protan') { L2 = m[1] * M + m[2] * S; }
  else if (type === 'deutan') { M2 = m[0] * L + m[2] * S; }
  else { S2 = m[0] * L + m[1] * M; }
  const lr = CVD_LMS_INV[0] * L2 + CVD_LMS_INV[1] * M2 + CVD_LMS_INV[2] * S2;
  const lg = CVD_LMS_INV[3] * L2 + CVD_LMS_INV[4] * M2 + CVD_LMS_INV[5] * S2;
  const lb = CVD_LMS_INV[6] * L2 + CVD_LMS_INV[7] * M2 + CVD_LMS_INV[8] * S2;
  return [
    clamp255(linearChannelToSrgb(lr < 0 ? 0 : (lr > 1 ? 1 : lr))),
    clamp255(linearChannelToSrgb(lg < 0 ? 0 : (lg > 1 ? 1 : lg))),
    clamp255(linearChannelToSrgb(lb < 0 ? 0 : (lb > 1 ? 1 : lb)))
  ];
}

export function cvdContrastRatio(fgRgb, bgRgb, type) {
  return contrastRatio(simulateCvd(fgRgb, type), simulateCvd(bgRgb, type));
}
