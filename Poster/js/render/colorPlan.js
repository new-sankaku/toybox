import { contrastRatio } from '../core/color.js';
import {
  oklchToSrgb,
  srgbToOklch,
  clampChroma,
  clamp01,
  mod360,
  hueDistance,
  pullHue,
  apcaContrast
} from '../core/oklch.js';
import { pickKeyColor } from '../core/palette.js';
import {
  buildScheme,
  chooseScheme,
  hasVibration,
  enforceChromaBudget,
  violatesChromaBudget,
  separateLightness,
  lightnessLadder,
  pickReadable,
  rotateHue,
  pickGroundLightness,
  pickFreeLightness,
  inGroundBand,
  groundSideRange,
  CHROMA_BUDGET
} from '../core/harmony.js';

const MAX_ATTEMPTS = 3;
const FINAL_SCHEME = 'accentedNeutral';
const MIN_ROLE_L_DELTA = 0.12;
const MIN_INK_WCAG = 4.5;
const MIN_INK_APCA = 60;
const TEXT_LADDER_STEPS = 7;
const TEXT_LADDER_CHROMA = 0.045;
const TINT_MAX_CHROMA = 0.075;

const ROLE_NAMES = ['ink', 'inkAlt', 'accent', 'surface', 'surfaceAlt', 'stroke', 'glow', 'plate', 'shadow'];
const GROUND_ROLES = ['surface', 'surfaceAlt', 'plate'];
const FIGURE_GROUND_PAIRS = [
  ['surface', 'ink'],
  ['surface', 'inkAlt'],
  ['surface', 'accent'],
  ['surface', 'surfaceAlt'],
  ['surface', 'glow'],
  ['surface', 'shadow'],
  ['ink', 'accent'],
  ['ink', 'stroke'],
  ['ink', 'plate']
];
const REPAIR_PAIRS = [
  ['surface', 'ink'],
  ['surface', 'inkAlt'],
  ['surface', 'accent'],
  ['surface', 'glow'],
  ['surface', 'shadow'],
  ['ink', 'accent'],
  ['ink', 'stroke']
];
const VIBRATION_PAIRS = [
  ['ink', 'surface'],
  ['ink', 'plate'],
  ['ink', 'accent'],
  ['inkAlt', 'surface'],
  ['accent', 'surface'],
  ['accent', 'surfaceAlt'],
  ['glow', 'surface'],
  ['stroke', 'ink'],
  ['plate', 'surface']
];

const GENRE_BIAS = {
  cinema: {
    darkPolarity: 0.78,
    inkChroma: 0.50,
    surfaceChroma: 0.55,
    accentChroma: 1.00,
    lightnessShift: -0.03,
    accentPull: { hues: [88, 45], strength: [0.10, 0.30] },
    glowGain: 0.9,
    tintContrastPref: 0.65,
    scheme: {
      monochromatic: 1.30, analogous: 1.20, complementary: 1.00, splitComplementary: 0.90,
      triadic: 0.50, tetradic: 0.40, accentedNeutral: 1.40, analogousComplement: 1.00
    }
  },
  gravure: {
    darkPolarity: 0.28,
    inkChroma: 0.70,
    surfaceChroma: 0.90,
    accentChroma: 1.25,
    lightnessShift: 0.05,
    accentPull: { hues: [12, 350, 62], strength: [0.10, 0.28] },
    glowGain: 1.1,
    tintContrastPref: 0.45,
    scheme: {
      monochromatic: 0.60, analogous: 1.10, complementary: 1.20, splitComplementary: 1.20,
      triadic: 1.30, tetradic: 1.00, accentedNeutral: 0.70, analogousComplement: 1.10
    }
  },
  novel: {
    darkPolarity: 0.35,
    inkChroma: 0.25,
    surfaceChroma: 0.35,
    accentChroma: 0.90,
    lightnessShift: 0.02,
    accentPull: { hues: [25, 264], strength: [0.25, 0.50] },
    glowGain: 0.5,
    tintContrastPref: 0.35,
    scheme: {
      monochromatic: 1.20, analogous: 1.00, complementary: 0.90, splitComplementary: 0.80,
      triadic: 0.50, tetradic: 0.40, accentedNeutral: 1.60, analogousComplement: 0.90
    }
  },
  asmr: {
    darkPolarity: 0.18,
    inkChroma: 0.45,
    surfaceChroma: 0.60,
    accentChroma: 0.70,
    lightnessShift: 0.10,
    accentPull: { hues: [310, 200], strength: [0.15, 0.35] },
    glowGain: 0.8,
    tintContrastPref: 0.30,
    scheme: {
      monochromatic: 1.40, analogous: 1.50, complementary: 0.60, splitComplementary: 0.70,
      triadic: 0.60, tetradic: 0.50, accentedNeutral: 1.20, analogousComplement: 0.90
    }
  },
  game: {
    darkPolarity: 0.80,
    inkChroma: 0.40,
    surfaceChroma: 0.50,
    accentChroma: 1.15,
    lightnessShift: -0.04,
    accentPull: { hues: [95, 250], strength: [0.20, 0.45] },
    glowGain: 1.3,
    tintContrastPref: 0.70,
    scheme: {
      monochromatic: 0.70, analogous: 0.90, complementary: 1.40, splitComplementary: 1.30,
      triadic: 1.00, tetradic: 0.90, accentedNeutral: 1.10, analogousComplement: 1.20
    }
  },
  adult: {
    darkPolarity: 0.62,
    inkChroma: 0.80,
    surfaceChroma: 1.00,
    accentChroma: 1.40,
    lightnessShift: 0.00,
    accentPull: { hues: [350, 100, 200], strength: [0.15, 0.40] },
    glowGain: 1.4,
    tintContrastPref: 0.60,
    scheme: {
      monochromatic: 0.50, analogous: 0.80, complementary: 1.50, splitComplementary: 1.40,
      triadic: 1.40, tetradic: 1.20, accentedNeutral: 0.60, analogousComplement: 1.20
    }
  }
};

function biasFor(genre) {
  return GENRE_BIAS[genre] || GENRE_BIAS.cinema;
}

function mostChromatic(colors, from) {
  let best = colors[from] || colors[0];
  for (let i = from; i < colors.length; i++) {
    if (colors[i][1] > best[1]) { best = colors[i]; }
  }
  return best;
}

function pickPolarity(rng, bias, palette) {
  const p = bias.darkPolarity * 0.65 + (1 - palette.meanL) * 0.35;
  return rng.chance(clamp01(p));
}

function applyAccentPull(rng, hue, bias) {
  const pull = bias.accentPull;
  if (!pull || pull.hues.length === 0) { return hue; }
  const target = rng.pick(pull.hues);
  const strength = rng.range(pull.strength[0], pull.strength[1]);
  return pullHue(hue, target, strength);
}

function chooseTintStrategy(rng, bias) {
  return rng.chance(bias.tintContrastPref) ? 'contrasting' : 'harmonic';
}

function buildTints(rng, strategy, keyHue, palette, bias) {
  const warm = palette.temperature >= 0;
  let shadowHue;
  let highlightHue;
  if (strategy === 'contrasting') {
    if (warm) {
      shadowHue = rotateHue(keyHue, 180);
      highlightHue = keyHue;
    } else {
      shadowHue = keyHue;
      highlightHue = rotateHue(keyHue, 180);
    }
  } else {
    shadowHue = rotateHue(keyHue, -rng.range(10, 26));
    highlightHue = rotateHue(keyHue, rng.range(10, 26));
  }
  const sc = Math.min(TINT_MAX_CHROMA, rng.range(0.030, TINT_MAX_CHROMA) * bias.surfaceChroma);
  const hc = Math.min(TINT_MAX_CHROMA, rng.range(0.025, TINT_MAX_CHROMA) * bias.surfaceChroma);
  return {
    shadow: clampChroma([rng.range(0.18, 0.30), sc, shadowHue]),
    highlight: clampChroma([rng.range(0.78, 0.92), hc, highlightHue]),
    duotoneA: clampChroma([rng.range(0.09, 0.20), Math.min(TINT_MAX_CHROMA, sc * 1.1), shadowHue]),
    duotoneB: clampChroma([rng.range(0.80, 0.94), Math.min(TINT_MAX_CHROMA, hc * 1.1), highlightHue]),
    shadowHue: shadowHue,
    highlightHue: highlightHue
  };
}

function buildRoles(rng, bias, colors, intensity, dark) {
  const base = colors[0];
  const second = colors[1] || base;
  const third = colors[2] || base;
  const accentSrc = mostChromatic(colors, 1);
  const shift = bias.lightnessShift;
  const side = groundSideRange(dark, 'small');

  const surfaceL = dark
    ? Math.min(side[1] - 0.06, Math.max(side[0], rng.range(0.17, 0.27) + shift))
    : Math.max(side[0] + 0.06, Math.min(0.985, rng.range(0.88, 0.965) + shift));
  const surfaceC = Math.min(0.055, base[1] * 0.35) * bias.surfaceChroma;
  const surface = [clamp01(surfaceL), surfaceC, base[2]];

  const inkL = dark ? rng.range(0.93, 0.985) : Math.max(0.045, rng.range(0.10, 0.19) + shift * 0.4);
  const inkC = Math.min(0.05, base[1] * 0.30) * bias.inkChroma;
  const ink = [clamp01(inkL), inkC, base[2]];

  const altL = pickGroundLightness(rng, dark, [surface[0]], MIN_ROLE_L_DELTA, 'large');
  const surfaceAlt = [
    altL === null ? clamp01(surface[0] + (dark ? 1 : -1) * MIN_ROLE_L_DELTA) : altL,
    Math.min(0.06, surfaceC * 1.4),
    second[2]
  ];

  const inkAltL = ink[0] + (dark ? -1 : 1) * rng.range(0.14, 0.26);
  const inkAlt = [clamp01(inkAltL), Math.min(0.07, inkC * 1.8 + 0.01), second[2]];

  const accentL = pickFreeLightness(rng, [0.10, 0.92], [surface[0], ink[0]], MIN_ROLE_L_DELTA + 0.01);
  const accentC = (0.155 + 0.065 * clamp01(intensity)) * bias.accentChroma;
  const accentH = applyAccentPull(rng, accentSrc[2], bias);
  const accent = clampChroma([
    accentL === null ? clamp01((surface[0] + ink[0]) / 2) : accentL,
    accentC,
    accentH
  ]);

  const glowDir = accent[0] >= surface[0] ? 1 : -1;
  const glow = clampChroma([clamp01(accent[0] + glowDir * 0.015), accent[1], accent[2]]);

  const stroke = [
    clamp01(dark ? rng.range(0.05, 0.15) : rng.range(0.90, 0.985)),
    Math.min(0.03, surfaceC * 0.5),
    third[2]
  ];

  const plateInverted = rng.chance(0.35);
  const plateL = pickGroundLightness(rng, plateInverted ? !dark : dark, [ink[0]], MIN_ROLE_L_DELTA, 'large');
  const plate = [
    plateL === null ? surface[0] : plateL,
    Math.min(0.05, surfaceC * 1.1),
    third[2]
  ];

  const shadowMax = dark ? Math.min(0.13, surface[0] - MIN_ROLE_L_DELTA - 0.01) : 0.13;
  const shadow = [
    clamp01(rng.range(Math.min(0.03, shadowMax), Math.max(0.035, shadowMax))),
    Math.min(0.045, base[1] * 0.4),
    base[2]
  ];

  return {
    ink: ink,
    inkAlt: inkAlt,
    accent: accent,
    surface: surface,
    surfaceAlt: surfaceAlt,
    stroke: stroke,
    glow: glow,
    plate: plate,
    shadow: shadow,
    plateInverted: plateInverted
  };
}

function repairLightness(roles) {
  for (let i = 0; i < REPAIR_PAIRS.length; i++) {
    const fixed = roles[REPAIR_PAIRS[i][0]];
    const name = REPAIR_PAIRS[i][1];
    roles[name] = separateLightness(fixed, roles[name], MIN_ROLE_L_DELTA);
  }
  return roles;
}

function repairChroma(roles, tints) {
  const names = ROLE_NAMES.slice();
  const list = names.map((n) => roles[n]);
  const tintNames = ['shadow', 'highlight', 'duotoneA', 'duotoneB'];
  for (let i = 0; i < tintNames.length; i++) { list.push(tints[tintNames[i]]); }
  const fixed = enforceChromaBudget(list, CHROMA_BUDGET);
  for (let i = 0; i < names.length; i++) { roles[names[i]] = fixed[i]; }
  for (let i = 0; i < tintNames.length; i++) { tints[tintNames[i]] = fixed[names.length + i]; }
}

function repairInkContrast(roles, dark) {
  const surfaceRgb = oklchToSrgb(roles.surface);
  let inkRgb = oklchToSrgb(roles.ink);
  if (contrastRatio(inkRgb, surfaceRgb) >= MIN_INK_WCAG
    && Math.abs(apcaContrast(inkRgb, surfaceRgb)) >= MIN_INK_APCA) {
    return true;
  }
  roles.ink = [dark ? 0.99 : 0.04, Math.min(roles.ink[1], 0.02), roles.ink[2]];
  inkRgb = oklchToSrgb(roles.ink);
  return contrastRatio(inkRgb, surfaceRgb) >= MIN_INK_WCAG
    && Math.abs(apcaContrast(inkRgb, surfaceRgb)) >= MIN_INK_APCA;
}

function planViolations(roles, tints) {
  const out = [];
  const list = ROLE_NAMES.map((n) => roles[n])
    .concat([tints.shadow, tints.highlight, tints.duotoneA, tints.duotoneB]);
  if (violatesChromaBudget(list, CHROMA_BUDGET)) { out.push('chromaBudget'); }
  for (let i = 0; i < VIBRATION_PAIRS.length; i++) {
    const a = roles[VIBRATION_PAIRS[i][0]];
    const b = roles[VIBRATION_PAIRS[i][1]];
    if (hasVibration(a, b)) { out.push('vibration:' + VIBRATION_PAIRS[i].join('/')); }
  }
  for (let i = 0; i < FIGURE_GROUND_PAIRS.length; i++) {
    const a = roles[FIGURE_GROUND_PAIRS[i][0]];
    const b = roles[FIGURE_GROUND_PAIRS[i][1]];
    if (Math.abs(a[0] - b[0]) < MIN_ROLE_L_DELTA - 1e-6) {
      out.push('lightness:' + FIGURE_GROUND_PAIRS[i].join('/'));
    }
  }
  if (!inGroundBand(roles.surface[0], 'small')) { out.push('groundBand:surface'); }
  for (let i = 1; i < GROUND_ROLES.length; i++) {
    if (!inGroundBand(roles[GROUND_ROLES[i]][0], 'large')) { out.push('groundBand:' + GROUND_ROLES[i]); }
  }
  const surfaceRgb = oklchToSrgb(roles.surface);
  const inkRgb = oklchToSrgb(roles.ink);
  if (contrastRatio(inkRgb, surfaceRgb) < MIN_INK_WCAG) { out.push('inkContrastWcag'); }
  if (Math.abs(apcaContrast(inkRgb, surfaceRgb)) < MIN_INK_APCA) { out.push('inkContrastApca'); }
  return out;
}

function buildTextPalette(roles, dark) {
  const ladder = lightnessLadder(roles.ink, TEXT_LADDER_STEPS, TEXT_LADDER_CHROMA);
  const list = ladder.map((c) => oklchToSrgb(c));
  list.push(oklchToSrgb(roles.ink));
  list.push(oklchToSrgb(roles.inkAlt));
  list.push(oklchToSrgb(roles.accent));
  list.push(oklchToSrgb([dark ? 0.995 : 0.035, 0, roles.ink[2]]));
  list.push(oklchToSrgb([dark ? 0.035 : 0.995, 0, roles.ink[2]]));
  const seen = [];
  const out = [];
  for (let i = 0; i < list.length; i++) {
    const key = Math.round(list[i][0]) + ',' + Math.round(list[i][1]) + ',' + Math.round(list[i][2]);
    if (seen.indexOf(key) >= 0) { continue; }
    seen.push(key);
    out.push(list[i]);
  }
  return out;
}

function buildRatio(rng) {
  const dominant = 0.60 + rng.range(-0.06, 0.06);
  const accent = 0.10 + rng.range(-0.03, 0.04);
  const secondary = 1 - dominant - accent;
  return { dominant: dominant, secondary: secondary, accent: accent };
}

function toRoleColors(roles) {
  const out = {};
  for (let i = 0; i < ROLE_NAMES.length; i++) {
    const n = ROLE_NAMES[i];
    out[n] = { lch: roles[n], rgb: oklchToSrgb(roles[n]) };
  }
  return out;
}

function toTintColors(tints) {
  return {
    shadow: { lch: tints.shadow, rgb: oklchToSrgb(tints.shadow) },
    highlight: { lch: tints.highlight, rgb: oklchToSrgb(tints.highlight) },
    duotoneA: { lch: tints.duotoneA, rgb: oklchToSrgb(tints.duotoneA) },
    duotoneB: { lch: tints.duotoneB, rgb: oklchToSrgb(tints.duotoneB) }
  };
}

export function buildColorPlan(rng, genre, palette, intensity) {
  const bias = biasFor(genre);
  const key = pickKeyColor(palette, { excludeSkin: true });
  const keyHue = key.isNeutral ? mod360(rng.range(0, 360)) : key.lch[2];
  const keyLch = key.isNeutral
    ? [palette.meanL || 0.5, 0.02, keyHue]
    : key.lch;
  const dark = pickPolarity(rng, bias, palette);
  const strength = clamp01(intensity === undefined ? 0.6 : intensity);

  let scheme = null;
  let roles = null;
  let tints = null;
  let violations = null;
  let attempts = 0;

  for (attempts = 1; attempts <= MAX_ATTEMPTS + 1; attempts++) {
    scheme = attempts > MAX_ATTEMPTS ? FINAL_SCHEME : chooseScheme(rng, palette, bias.scheme);
    const colors = buildScheme(rng, keyLch, scheme);
    if (!colors) { continue; }
    const strategy = chooseTintStrategy(rng, bias);
    roles = buildRoles(rng, bias, colors, strength, dark);
    tints = buildTints(rng, strategy, keyHue, palette, bias);
    tints.strategy = strategy;
    repairLightness(roles);
    repairChroma(roles, tints);
    repairInkContrast(roles, dark);
    repairLightness(roles);
    violations = planViolations(roles, tints);
    if (violations.length === 0) { break; }
  }

  const textPalette = buildTextPalette(roles, dark);
  const roleColors = toRoleColors(roles);

  return {
    scheme: scheme,
    key: keyLch,
    keySource: key.source,
    keyIsNeutral: key.isNeutral,
    polarity: dark ? 'dark' : 'light',
    intensity: strength,
    genre: genre,
    glowGain: bias.glowGain,
    plateInverted: roles.plateInverted,
    roles: roleColors,
    textPalette: textPalette,
    tints: toTintColors(tints),
    tintStrategy: tints.strategy,
    temperature: palette.temperature,
    colorfulness: palette.colorfulness,
    ratio: buildRatio(rng),
    attempts: attempts > MAX_ATTEMPTS + 1 ? MAX_ATTEMPTS + 1 : attempts,
    violations: violations
  };
}

export function planTextColor(plan, bgRgb, isLarge) {
  const minWcag = isLarge ? 3.4 : 4.5;
  const minApca = isLarge ? 45 : 60;
  return pickReadable(plan.textPalette, bgRgb, minWcag, minApca);
}

export function planSurfaceFor(plan, bgRgb) {
  const surface = plan.roles.surface.rgb;
  const alt = plan.roles.surfaceAlt.rgb;
  const bg = srgbToOklch(bgRgb);
  const ds = Math.abs(bg[0] - plan.roles.surface.lch[0]);
  const da = Math.abs(bg[0] - plan.roles.surfaceAlt.lch[0]);
  return ds >= da ? surface : alt;
}

export function planAccentHueDistance(plan, hue) {
  return hueDistance(plan.roles.accent.lch[2], hue);
}
