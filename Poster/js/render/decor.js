import { blendRgb, contrastRatio, hslToRgb, luma01, rgbToCss, rgbToHsl, shade } from '../core/color.js';

const MAX_GLYPH_PASSES = 8;
const MIN_STOP_CONTRAST = 3.0;
const MIN_PLATE_CONTRAST = 4.5;
const NOISY_STD = 0.17;
const MASK_PIXEL_LIMIT = 4194304;
const MASK_PAD_EM = 0.75;
const DARK_INK = [12, 10, 10];
const LIGHT_INK = [248, 246, 242];

const METAL_PROFILE = {
  gold: [[0, -0.42], [0.14, 0.2], [0.3, 0.62], [0.44, 0.06], [0.5, -0.34], [0.57, 0.06], [0.72, 0.58], [0.88, 0.06], [1, -0.44]],
  silver: [[0, -0.3], [0.2, 0.34], [0.46, 0.68], [0.52, -0.28], [0.7, 0.4], [1, -0.36]],
  chrome: [[0, 0.55], [0.4, 0.12], [0.47, -0.5], [0.53, 0.66], [0.64, 0.2], [1, -0.38]]
};

const METAL_TINT = {
  gold: { h: 0.115, s: 0.62, mix: 0.55 },
  silver: { h: 0, s: 0.04, mix: 0.7 },
  chrome: { h: 0.58, s: 0.1, mix: 0.5 }
};

const BOTEN_MARKS = ['●', '・', '◆', '○'];

const PRESETS = {
  cinema: {
    fill: [{ v: 'solid', w: 5 }, { v: 'linear', w: 3 }, { v: 'metallic', w: 3 }, { v: 'duotone', w: 1 }],
    metal: [{ v: 'silver', w: 4 }, { v: 'gold', w: 3 }, { v: 'chrome', w: 2 }],
    strokeCount: [{ v: 0, w: 6 }, { v: 1, w: 3 }, { v: 2, w: 1 }, { v: 3, w: 0.2 }],
    strokeWidth: [0.02, 0.055],
    glow: 0.32, glowAlpha: [0.2, 0.42], glowBlur: [0.22, 0.5],
    dropShadow: 0.5, hardShadow: 0.15, shadowOffset: [0.012, 0.045], shadowBlur: [0.06, 0.24], shadowAlpha: [0.3, 0.55],
    longShadow: 0.08, bevel: 0.12, innerLine: 0.2,
    plate: 0.12, plateTilt: 0.15, plateRound: 0.25, plateAlpha: [0.6, 0.88],
    rule: 0.28, ruleDouble: 0.3, boten: 0.02,
    skew: 0.06, skewRange: [0.05, 0.13],
    rotate: 0.06, rotateRange: [0.004, 0.016],
    scaleX: [0.84, 1.02], archP: 0.04, archRange: [0.02, 0.06],
    edgeSplit: 0.06
  },
  gravure: {
    fill: [{ v: 'solid', w: 3 }, { v: 'linear', w: 5 }, { v: 'metallic', w: 1 }, { v: 'duotone', w: 2 }],
    metal: [{ v: 'gold', w: 3 }, { v: 'silver', w: 2 }, { v: 'chrome', w: 1 }],
    strokeCount: [{ v: 0, w: 1 }, { v: 1, w: 3 }, { v: 2, w: 5 }, { v: 3, w: 1 }],
    strokeWidth: [0.06, 0.14],
    glow: 0.3, glowAlpha: [0.25, 0.5], glowBlur: [0.3, 0.7],
    dropShadow: 0.7, hardShadow: 0.1, shadowOffset: [0.02, 0.06], shadowBlur: [0.14, 0.4], shadowAlpha: [0.32, 0.6],
    longShadow: 0.05, bevel: 0.1, innerLine: 0.1,
    plate: 0.2, plateTilt: 0.3, plateRound: 0.6, plateAlpha: [0.65, 0.92],
    rule: 0.16, ruleDouble: 0.2, boten: 0.03,
    skew: 0.35, skewRange: [0.06, 0.16],
    rotate: 0.2, rotateRange: [0.006, 0.028],
    scaleX: [0.94, 1.1], archP: 0.12, archRange: [0.03, 0.09],
    edgeSplit: 0.04
  },
  novel: {
    fill: [{ v: 'solid', w: 5 }, { v: 'linear', w: 2 }, { v: 'metallic', w: 3 }, { v: 'duotone', w: 0.5 }],
    metal: [{ v: 'gold', w: 5 }, { v: 'silver', w: 3 }, { v: 'chrome', w: 1 }],
    strokeCount: [{ v: 0, w: 7 }, { v: 1, w: 2 }, { v: 2, w: 0.5 }, { v: 3, w: 0.1 }],
    strokeWidth: [0.014, 0.042],
    glow: 0.1, glowAlpha: [0.15, 0.3], glowBlur: [0.18, 0.4],
    dropShadow: 0.3, hardShadow: 0.05, shadowOffset: [0.008, 0.026], shadowBlur: [0.05, 0.18], shadowAlpha: [0.22, 0.42],
    longShadow: 0.02, bevel: 0.06, innerLine: 0.16,
    plate: 0.26, plateTilt: 0.06, plateRound: 0.12, plateAlpha: [0.72, 0.96],
    rule: 0.45, ruleDouble: 0.45, boten: 0.35,
    skew: 0.02, skewRange: [0.03, 0.07],
    rotate: 0.03, rotateRange: [0.003, 0.01],
    scaleX: [0.9, 1.0], archP: 0.01, archRange: [0.01, 0.03],
    edgeSplit: 0.01
  },
  asmr: {
    fill: [{ v: 'solid', w: 2 }, { v: 'linear', w: 5 }, { v: 'metallic', w: 0.5 }, { v: 'duotone', w: 3 }],
    metal: [{ v: 'silver', w: 3 }, { v: 'gold', w: 2 }, { v: 'chrome', w: 1 }],
    strokeCount: [{ v: 0, w: 0.5 }, { v: 1, w: 2 }, { v: 2, w: 6 }, { v: 3, w: 1.2 }],
    strokeWidth: [0.07, 0.15],
    glow: 0.75, glowAlpha: [0.32, 0.62], glowBlur: [0.4, 0.95],
    dropShadow: 0.45, hardShadow: 0.04, shadowOffset: [0.01, 0.035], shadowBlur: [0.2, 0.5], shadowAlpha: [0.24, 0.45],
    longShadow: 0.03, bevel: 0.05, innerLine: 0.08,
    plate: 0.12, plateTilt: 0.2, plateRound: 0.85, plateAlpha: [0.55, 0.85],
    rule: 0.08, ruleDouble: 0.2, boten: 0.05,
    skew: 0.1, skewRange: [0.04, 0.1],
    rotate: 0.25, rotateRange: [0.006, 0.03],
    scaleX: [0.96, 1.09], archP: 0.16, archRange: [0.03, 0.1],
    edgeSplit: 0.02
  },
  game: {
    fill: [{ v: 'solid', w: 2 }, { v: 'linear', w: 4 }, { v: 'metallic', w: 5 }, { v: 'duotone', w: 1 }],
    metal: [{ v: 'chrome', w: 4 }, { v: 'gold', w: 4 }, { v: 'silver', w: 3 }],
    strokeCount: [{ v: 0, w: 0.4 }, { v: 1, w: 1 }, { v: 2, w: 4 }, { v: 3, w: 5 }],
    strokeWidth: [0.05, 0.125],
    glow: 0.4, glowAlpha: [0.3, 0.6], glowBlur: [0.25, 0.7],
    dropShadow: 0.8, hardShadow: 0.6, shadowOffset: [0.03, 0.085], shadowBlur: [0.0, 0.2], shadowAlpha: [0.45, 0.8],
    longShadow: 0.3, bevel: 0.6, innerLine: 0.3,
    plate: 0.15, plateTilt: 0.5, plateRound: 0.15, plateAlpha: [0.7, 0.95],
    rule: 0.1, ruleDouble: 0.3, boten: 0.02,
    skew: 0.5, skewRange: [0.08, 0.2],
    rotate: 0.25, rotateRange: [0.006, 0.03],
    scaleX: [0.76, 0.98], archP: 0.08, archRange: [0.03, 0.08],
    edgeSplit: 0.12
  },
  adult: {
    fill: [{ v: 'solid', w: 5 }, { v: 'linear', w: 4 }, { v: 'metallic', w: 2 }, { v: 'duotone', w: 2 }],
    metal: [{ v: 'gold', w: 4 }, { v: 'chrome', w: 2 }, { v: 'silver', w: 2 }],
    strokeCount: [{ v: 0, w: 0.3 }, { v: 1, w: 1 }, { v: 2, w: 5 }, { v: 3, w: 4 }],
    strokeWidth: [0.07, 0.17],
    glow: 0.3, glowAlpha: [0.28, 0.55], glowBlur: [0.2, 0.55],
    dropShadow: 0.85, hardShadow: 0.7, shadowOffset: [0.03, 0.09], shadowBlur: [0.0, 0.16], shadowAlpha: [0.5, 0.85],
    longShadow: 0.25, bevel: 0.3, innerLine: 0.2,
    plate: 0.45, plateTilt: 0.6, plateRound: 0.1, plateAlpha: [0.8, 1.0],
    rule: 0.2, ruleDouble: 0.35, boten: 0.08,
    skew: 0.55, skewRange: [0.08, 0.22],
    rotate: 0.4, rotateRange: [0.008, 0.04],
    scaleX: [0.78, 1.12], archP: 0.1, archRange: [0.03, 0.1],
    edgeSplit: 0.15
  }
};

function presetOf(genre) {
  return PRESETS[genre] || PRESETS.cinema;
}

function levelOf(slot) {
  const d = slot && slot.decor ? slot.decor : 'accent';
  if (d === 'title') { return 1; }
  if (d === 'plain') { return 0.16; }
  return 0.6;
}

function clamp01(v) {
  return v < 0 ? 0 : (v > 1 ? 1 : v);
}

function chanceScaled(rng, p, gain) {
  return rng.chance(clamp01(p * gain));
}

function safeShade(base, amount, bg) {
  let a = amount;
  for (let i = 0; i < 7; i++) {
    const c = shade(base, a);
    if (contrastRatio(c, bg) >= MIN_STOP_CONTRAST) { return c; }
    a *= 0.6;
  }
  return base.slice();
}

function inkAgainst(bg) {
  return contrastRatio(DARK_INK, bg) >= contrastRatio(LIGHT_INK, bg) ? DARK_INK.slice() : LIGHT_INK.slice();
}

function inkOpposite(rgb) {
  return luma01(rgb) > 0.5 ? DARK_INK.slice() : LIGHT_INK.slice();
}

function metalBase(base, metal) {
  const tint = METAL_TINT[metal];
  const hsl = rgbToHsl(base);
  const l = Math.min(0.76, Math.max(0.3, hsl[2]));
  const h = metal === 'silver' ? hsl[0] : tint.h;
  return blendRgb(base, hslToRgb([h, tint.s, l]), tint.mix);
}

function buildFill(rng, preset, base, bg, level) {
  if (level < 0.25) {
    return { type: 'solid', angle: 0, stops: [{ t: 0, rgb: base.slice() }, { t: 1, rgb: base.slice() }] };
  }
  const type = rng.weighted(preset.fill);
  const vertical = rng.chance(0.74);
  const angle = vertical ? Math.PI / 2 + rng.range(-0.12, 0.12) : rng.range(-0.5, 0.5);

  if (type === 'metallic') {
    const metal = rng.weighted(preset.metal);
    const mb = metalBase(base, metal);
    if (contrastRatio(mb, bg) < MIN_STOP_CONTRAST) {
      return buildLinear(rng, base, bg, angle, 'linear');
    }
    const prof = METAL_PROFILE[metal];
    const stops = [];
    for (let i = 0; i < prof.length; i++) {
      stops.push({ t: prof[i][0], rgb: safeShade(mb, prof[i][1], bg) });
    }
    return { type: 'metallic', metal: metal, angle: Math.PI / 2 + rng.range(-0.08, 0.08), stops: stops };
  }

  if (type === 'duotone') {
    const split = rng.range(0.42, 0.58);
    const up = rng.range(0.2, 0.5) * (rng.chance(0.5) ? 1 : -1);
    const a = safeShade(base, up, bg);
    const b = safeShade(base, -up * rng.range(0.7, 1.3), bg);
    return {
      type: 'duotone', angle: angle,
      stops: [{ t: 0, rgb: a }, { t: split, rgb: a }, { t: Math.min(1, split + 0.004), rgb: b }, { t: 1, rgb: b }]
    };
  }

  if (type === 'linear') { return buildLinear(rng, base, bg, angle, 'linear'); }
  return { type: 'solid', angle: 0, stops: [{ t: 0, rgb: base.slice() }, { t: 1, rgb: base.slice() }] };
}

function buildLinear(rng, base, bg, angle, type) {
  const amp = rng.range(0.14, 0.44);
  const dir = rng.chance(0.62) ? 1 : -1;
  const stops = [{ t: 0, rgb: safeShade(base, amp * dir, bg) }];
  if (rng.chance(0.4)) {
    stops.push({ t: rng.range(0.4, 0.62), rgb: safeShade(base, amp * dir * 0.2, bg) });
  }
  stops.push({ t: 1, rgb: safeShade(base, -amp * dir * rng.range(0.6, 1.25), bg) });
  return { type: type, angle: angle, stops: stops };
}

function buildStrokes(rng, preset, base, bg, level, noisy) {
  let n = rng.weighted(preset.strokeCount);
  if (level < 0.25) { n = noisy ? 1 : 0; }
  else if (level < 0.7 && n > 2) { n = 2; }
  if (noisy && n === 0) { n = 1; }
  if (n === 0) { return []; }

  const edgeBg = inkAgainst(bg);
  const edgeInk = inkOpposite(base);
  const w0 = rng.range(preset.strokeWidth[0], preset.strokeWidth[1]) * (level < 0.7 ? 0.7 : 1) * (noisy ? 1.25 : 1);
  const strokes = [];

  if (n === 1) {
    const rgb = contrastRatio(edgeBg, base) >= 2.2 ? edgeBg : edgeInk;
    strokes.push({ width: w0, rgb: rgb, alpha: rng.range(0.85, 1) });
    return strokes;
  }

  strokes.push({ width: w0, rgb: edgeBg, alpha: 1 });
  const inner = contrastRatio(edgeInk, edgeBg) >= 2.2 ? edgeInk : shade(edgeBg, luma01(edgeBg) > 0.5 ? -0.6 : 0.6);
  strokes.push({ width: w0 * 0.56, rgb: inner, alpha: 1 });
  if (n >= 3) {
    const hsl = rgbToHsl(base);
    const accent = hslToRgb([(hsl[0] + rng.range(0.36, 0.64)) % 1, Math.max(0.5, hsl[1]), 0.5]);
    strokes.push({ width: w0 * 0.3, rgb: contrastRatio(accent, inner) >= 1.8 ? accent : shade(inner, 0.5), alpha: 1 });
  }
  return strokes;
}

function buildShadow(rng, preset, base, bg, gain, level) {
  if (level < 0.15) { return null; }
  if (!chanceScaled(rng, preset.dropShadow, gain)) { return null; }
  const hard = rng.chance(preset.hardShadow);
  let rgb = inkAgainst(bg);
  if (contrastRatio(rgb, base) < 1.6) { rgb = inkOpposite(rgb); }
  const off = rng.range(preset.shadowOffset[0], preset.shadowOffset[1]) * (hard ? 1.3 : 1);
  const ang = rng.range(Math.PI * 0.18, Math.PI * 0.42);
  return {
    hard: hard,
    rgb: rgb,
    alpha: rng.range(preset.shadowAlpha[0], preset.shadowAlpha[1]),
    dx: Math.cos(ang) * off,
    dy: Math.sin(ang) * off,
    blur: hard ? 0 : rng.range(preset.shadowBlur[0], preset.shadowBlur[1])
  };
}

function buildGlow(rng, preset, base, bg, gain, level, noisy) {
  const forced = noisy && level >= 0.5;
  if (!forced && !chanceScaled(rng, preset.glow, gain)) { return null; }
  const rgb = luma01(bg) > 0.5 ? shade(base, -0.55) : shade(base, 0.6);
  return {
    rgb: rgb,
    alpha: rng.range(preset.glowAlpha[0], preset.glowAlpha[1]),
    blur: rng.range(preset.glowBlur[0], preset.glowBlur[1]),
    passes: rng.chance(0.4) ? 2 : 1
  };
}

function buildPlate(rng, preset, base, bg) {
  let rgb = inkOpposite(base);
  const tinted = blendRgb(rgb, bg, 0.18);
  if (contrastRatio(tinted, base) >= MIN_PLATE_CONTRAST) { rgb = tinted; }
  const alpha = rng.range(preset.plateAlpha[0], preset.plateAlpha[1]);
  const tilt = rng.chance(preset.plateTilt);
  const round = rng.chance(preset.plateRound);
  return {
    kind: tilt ? 'tilt' : (round ? 'round' : 'rect'),
    rgb: rgb,
    alpha: alpha,
    padX: rng.range(0.14, 0.4),
    padY: rng.range(0.06, 0.22),
    radius: round ? rng.range(0.08, 0.34) : 0,
    skew: rng.chance(0.35) ? rng.range(0.08, 0.24) * (rng.chance(0.5) ? 1 : -1) : 0,
    rotate: tilt ? rng.range(0.012, 0.055) * (rng.chance(0.5) ? 1 : -1) : 0,
    border: rng.chance(0.3) ? { rgb: base.slice(), width: rng.range(0.012, 0.03), alpha: 0.9 } : null
  };
}

function buildRule(rng, preset, base, bg, gain) {
  if (!chanceScaled(rng, preset.rule, gain)) { return null; }
  const rgb = contrastRatio(base, bg) >= MIN_STOP_CONTRAST ? base.slice() : inkAgainst(bg);
  return {
    rgb: rgb,
    alpha: rng.range(0.7, 1),
    width: rng.range(0.022, 0.075),
    gap: rng.range(0.08, 0.24),
    double: rng.chance(preset.ruleDouble),
    spacing: rng.range(0.05, 0.11)
  };
}

function buildTransform(rng, preset, gain, level) {
  const t = { skewX: 0, rotate: 0, scaleX: 1, arch: 0, originX: 0.5, originY: 0.5 };
  if (level >= 0.5 && chanceScaled(rng, preset.skew, gain)) {
    t.skewX = rng.range(preset.skewRange[0], preset.skewRange[1]);
  }
  if (chanceScaled(rng, preset.rotate, gain)) {
    t.rotate = rng.range(preset.rotateRange[0], preset.rotateRange[1]) * (rng.chance(0.5) ? 1 : -1) * Math.PI;
  }
  const sx = rng.range(preset.scaleX[0], preset.scaleX[1]);
  if (Math.abs(sx - 1) > 0.03) { t.scaleX = sx; }
  if (level >= 0.5 && chanceScaled(rng, preset.archP, gain)) {
    t.arch = rng.range(preset.archRange[0], preset.archRange[1]) * (rng.chance(0.75) ? 1 : -1);
  }
  return t;
}

function passCost(spec) {
  let cost = 1;
  cost += spec.strokes.length;
  if (spec.glow) { cost += spec.glow.passes; }
  if (spec.bevel) { cost += 2; }
  if (spec.innerLine) { cost += 1; }
  if (spec.longShadow || spec.edgeSplit) { cost += 1; }
  return cost;
}

function capPasses(spec) {
  const drop = ['edgeSplit', 'longShadow', 'innerLine', 'bevel'];
  for (let i = 0; i < drop.length && passCost(spec) > MAX_GLYPH_PASSES; i++) {
    if (spec[drop[i]]) { spec[drop[i]] = null; }
  }
  if (passCost(spec) > MAX_GLYPH_PASSES && spec.glow && spec.glow.passes > 1) { spec.glow.passes = 1; }
  while (passCost(spec) > MAX_GLYPH_PASSES && spec.strokes.length > 1) { spec.strokes.pop(); }
  if (passCost(spec) > MAX_GLYPH_PASSES && spec.glow) { spec.glow = null; }
}

export function buildDecorSpec(rng, genre, slot, style, stats, intensity) {
  const preset = presetOf(genre);
  const level = levelOf(slot);
  const inten = typeof intensity === 'number' ? intensity : 0.5;
  const gain = level * (0.55 + inten * 0.9);
  const base = style.color.slice();
  const noisy = stats.std > NOISY_STD;

  let bg = stats.rgb.slice();
  if (style.scrim) { bg = blendRgb(bg, style.scrim.color, style.scrim.alpha); }

  const axes = [];
  const spec = {
    genre: genre, level: level,
    fill: null, strokes: [], glow: null, dropShadow: null, longShadow: null,
    bevel: null, innerLine: null, plate: null, underline: null, overline: null,
    boten: null, transform: null, edgeSplit: null, axes: axes
  };

  const wantPlate = level > 0.2 && (chanceScaled(rng, preset.plate, gain) || (noisy && rng.chance(0.5)));
  if (wantPlate) {
    spec.plate = buildPlate(rng, preset, base, bg);
    bg = blendRgb(bg, spec.plate.rgb, spec.plate.alpha);
    axes.push('plate:' + spec.plate.kind);
  }
  if (contrastRatio(base, bg) < MIN_STOP_CONTRAST && !spec.plate) {
    spec.plate = buildPlate(rng, preset, base, bg);
    bg = blendRgb(bg, spec.plate.rgb, spec.plate.alpha);
    axes.push('plate:' + spec.plate.kind);
  }

  spec.fill = buildFill(rng, preset, base, bg, level);
  axes.push('fill:' + (spec.fill.metal ? spec.fill.type + '-' + spec.fill.metal : spec.fill.type));

  spec.strokes = buildStrokes(rng, preset, base, bg, level, noisy && !spec.plate);
  if (spec.strokes.length > 0) { axes.push('stroke:' + spec.strokes.length); }

  spec.glow = buildGlow(rng, preset, base, bg, gain, level, noisy && !spec.plate && spec.strokes.length === 0);
  if (spec.glow) { axes.push('glow'); }

  spec.dropShadow = buildShadow(rng, preset, base, bg, gain, level);
  if (spec.dropShadow) { axes.push(spec.dropShadow.hard ? 'shadow:hard' : 'shadow:soft'); }

  if (level >= 0.5 && chanceScaled(rng, preset.longShadow, gain)) {
    const ang = rng.range(Math.PI * 0.15, Math.PI * 0.45);
    const len = rng.range(0.25, 0.75);
    const steps = Math.max(6, Math.min(18, Math.round(len / 0.035)));
    let rgb = inkAgainst(bg);
    if (contrastRatio(rgb, base) < 1.6) { rgb = inkOpposite(rgb); }
    spec.longShadow = {
      rgb: rgb, alpha: rng.range(0.35, 0.7), steps: steps,
      dx: Math.cos(ang) * len / steps, dy: Math.sin(ang) * len / steps
    };
    axes.push('longShadow');
  }

  if (level >= 0.5 && chanceScaled(rng, preset.bevel, gain)) {
    spec.bevel = {
      light: safeShade(base, rng.range(0.35, 0.7), bg),
      dark: safeShade(base, -rng.range(0.35, 0.7), bg),
      offset: rng.range(0.014, 0.05),
      alpha: rng.range(0.7, 1)
    };
    axes.push('bevel');
  }

  if (level >= 0.35 && chanceScaled(rng, preset.innerLine, gain)) {
    spec.innerLine = {
      rgb: luma01(base) > 0.5 ? shade(base, -0.5) : shade(base, 0.55),
      width: rng.range(0.008, 0.022),
      alpha: rng.range(0.55, 0.9)
    };
    axes.push('innerLine');
  }

  if (level >= 0.35) {
    const rule = buildRule(rng, preset, base, bg, gain);
    if (rule) {
      const where = rng.weighted([{ v: 'under', w: 6 }, { v: 'over', w: 2 }, { v: 'both', w: 1.2 }]);
      if (where !== 'over') { spec.underline = rule; }
      if (where !== 'under') { spec.overline = rule; }
      axes.push('rule:' + where);
    }
  }

  if (level >= 0.35 && chanceScaled(rng, preset.boten, gain)) {
    spec.boten = {
      rgb: contrastRatio(base, bg) >= MIN_STOP_CONTRAST ? base.slice() : inkAgainst(bg),
      mark: rng.pick(BOTEN_MARKS),
      size: rng.range(0.16, 0.26),
      gap: rng.range(0.06, 0.16),
      alpha: rng.range(0.8, 1)
    };
    axes.push('boten');
  }

  if (level >= 0.5 && chanceScaled(rng, preset.edgeSplit, gain)) {
    spec.edgeSplit = {
      dx: rng.range(0.006, 0.022) * (rng.chance(0.5) ? 1 : -1),
      dy: rng.range(0, 0.01) * (rng.chance(0.5) ? 1 : -1),
      alpha: rng.range(0.4, 0.8),
      a: [255, 46, 46],
      b: [40, 170, 255]
    };
    axes.push('edgeSplit');
  }

  spec.transform = buildTransform(rng, preset, gain, level);
  if (spec.transform.skewX) { axes.push('skew'); }
  if (spec.transform.rotate) { axes.push('rotate'); }
  if (spec.transform.scaleX !== 1) { axes.push(spec.transform.scaleX < 1 ? 'condense' : 'expand'); }
  if (spec.transform.arch) { axes.push('arch'); }

  if (noisy && !spec.plate && !spec.glow && spec.strokes.length === 0) {
    spec.strokes = buildStrokes(rng, preset, base, bg, Math.max(level, 0.7), true);
    axes.push('stroke:forced');
  }

  capPasses(spec);
  return spec;
}

function clearShadow(ctx) {
  ctx.shadowColor = 'rgba(0,0,0,0)';
  ctx.shadowBlur = 0;
  ctx.shadowOffsetX = 0;
  ctx.shadowOffsetY = 0;
}

function applyShadow(ctx, sh, size) {
  ctx.shadowColor = rgbToCss(sh.rgb, sh.alpha);
  ctx.shadowBlur = sh.blur * size;
  ctx.shadowOffsetX = sh.dx * size;
  ctx.shadowOffsetY = sh.dy * size;
}

function applyTransform(ctx, box, t) {
  if (!t) { return; }
  if (!t.skewX && !t.rotate && (!t.scaleX || t.scaleX === 1)) { return; }
  const ox = box.x + box.w * (typeof t.originX === 'number' ? t.originX : 0.5);
  const oy = box.y + box.h * (typeof t.originY === 'number' ? t.originY : 0.5);
  ctx.translate(ox, oy);
  if (t.rotate) { ctx.rotate(t.rotate); }
  if (t.skewX) { ctx.transform(1, 0, -t.skewX, 1, 0, 0); }
  if (t.scaleX && t.scaleX !== 1) { ctx.scale(t.scaleX, 1); }
  ctx.translate(-ox, -oy);
}

function makeFillStyle(ctx, box, fill) {
  if (!fill || fill.type === 'solid' || fill.stops.length < 2 || box.w <= 0 || box.h <= 0) {
    return rgbToCss(fill && fill.stops.length > 0 ? fill.stops[0].rgb : [255, 255, 255]);
  }
  const cx = box.x + box.w / 2;
  const cy = box.y + box.h / 2;
  const ca = Math.cos(fill.angle);
  const sa = Math.sin(fill.angle);
  const half = (Math.abs(box.w * ca) + Math.abs(box.h * sa)) / 2;
  if (half <= 0) { return rgbToCss(fill.stops[0].rgb); }
  const g = ctx.createLinearGradient(cx - ca * half, cy - sa * half, cx + ca * half, cy + sa * half);
  for (let i = 0; i < fill.stops.length; i++) {
    g.addColorStop(clamp01(fill.stops[i].t), rgbToCss(fill.stops[i].rgb));
  }
  return g;
}

function roundRectPath(ctx, x, y, w, h, r) {
  const rr = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.lineTo(x + w - rr, y);
  ctx.arcTo(x + w, y, x + w, y + rr, rr);
  ctx.lineTo(x + w, y + h - rr);
  ctx.arcTo(x + w, y + h, x + w - rr, y + h, rr);
  ctx.lineTo(x + rr, y + h);
  ctx.arcTo(x, y + h, x, y + h - rr, rr);
  ctx.lineTo(x, y + rr);
  ctx.arcTo(x, y, x + rr, y, rr);
  ctx.closePath();
}

function paintPlate(ctx, box, plate, size) {
  const px = plate.padX * size;
  const py = plate.padY * size;
  const x = box.x - px;
  const y = box.y - py;
  const w = box.w + px * 2;
  const h = box.h + py * 2;
  if (w <= 0 || h <= 0) { return; }
  ctx.save();
  if (plate.rotate || plate.skew) {
    const cx = x + w / 2;
    const cy = y + h / 2;
    ctx.translate(cx, cy);
    if (plate.rotate) { ctx.rotate(plate.rotate); }
    if (plate.skew) { ctx.transform(1, 0, -plate.skew, 1, 0, 0); }
    ctx.translate(-cx, -cy);
  }
  ctx.fillStyle = rgbToCss(plate.rgb, plate.alpha);
  if (plate.radius > 0) {
    roundRectPath(ctx, x, y, w, h, plate.radius * size);
    ctx.fill();
    if (plate.border) {
      ctx.lineWidth = plate.border.width * size;
      ctx.strokeStyle = rgbToCss(plate.border.rgb, plate.border.alpha);
      ctx.stroke();
    }
  } else {
    ctx.fillRect(x, y, w, h);
    if (plate.border) {
      ctx.lineWidth = plate.border.width * size;
      ctx.strokeStyle = rgbToCss(plate.border.rgb, plate.border.alpha);
      ctx.strokeRect(x, y, w, h);
    }
  }
  ctx.restore();
}

function paintRule(ctx, box, rule, size, top, vertical) {
  const gap = rule.gap * size;
  const lw = rule.width * size;
  ctx.save();
  ctx.fillStyle = rgbToCss(rule.rgb, rule.alpha);
  if (vertical) {
    const x0 = top ? box.x + box.w + gap : box.x - gap;
    const d = rule.spacing * size * (top ? 1 : -1);
    ctx.fillRect(x0 - lw / 2, box.y, lw, box.h);
    if (rule.double) { ctx.fillRect(x0 + d - lw * 0.3, box.y, lw * 0.6, box.h); }
  } else {
    const y0 = top ? box.y - gap : box.y + box.h + gap;
    const d = rule.spacing * size * (top ? -1 : 1);
    ctx.fillRect(box.x, y0 - lw / 2, box.w, lw);
    if (rule.double) { ctx.fillRect(box.x, y0 + d - lw * 0.3, box.w, lw * 0.6); }
  }
  ctx.restore();
}

function buildMask(ctx, emitter, box, pad) {
  if (typeof document === 'undefined') { return null; }
  let sx = 1;
  let sy = 1;
  if (typeof ctx.getTransform === 'function') {
    const m = ctx.getTransform();
    sx = Math.hypot(m.a, m.b);
    sy = Math.hypot(m.c, m.d);
  }
  if (!(sx > 0) || !(sy > 0)) { return null; }
  const bw = box.w + pad * 2;
  const bh = box.h + pad * 2;
  const w = Math.ceil(bw * sx);
  const h = Math.ceil(bh * sy);
  if (w < 2 || h < 2 || w * h > MASK_PIXEL_LIMIT) { return null; }
  const cv = document.createElement('canvas');
  cv.width = w;
  cv.height = h;
  const oc = cv.getContext('2d');
  if (!oc) { return null; }
  oc.scale(sx, sy);
  oc.translate(pad - box.x, pad - box.y);
  oc.fillStyle = '#000000';
  emitter(oc, 'fill');
  return { cv: cv, x: box.x - pad, y: box.y - pad, w: bw, h: bh };
}

function tintedMask(mask, rgb, alpha) {
  const cv = document.createElement('canvas');
  cv.width = mask.cv.width;
  cv.height = mask.cv.height;
  const oc = cv.getContext('2d');
  if (!oc) { return null; }
  oc.drawImage(mask.cv, 0, 0);
  oc.globalCompositeOperation = 'source-in';
  oc.fillStyle = rgbToCss(rgb, alpha);
  oc.fillRect(0, 0, cv.width, cv.height);
  return cv;
}

function paintLongShadow(ctx, mask, ls, size) {
  const layer = tintedMask(mask, ls.rgb, ls.alpha);
  if (!layer) { return; }
  for (let i = ls.steps; i >= 1; i--) {
    ctx.drawImage(layer, mask.x + ls.dx * size * i, mask.y + ls.dy * size * i, mask.w, mask.h);
  }
}

function paintEdgeSplit(ctx, mask, es, size) {
  const a = tintedMask(mask, es.a, es.alpha);
  const b = tintedMask(mask, es.b, es.alpha);
  if (!a || !b) { return; }
  ctx.drawImage(a, mask.x - es.dx * size, mask.y - es.dy * size, mask.w, mask.h);
  ctx.drawImage(b, mask.x + es.dx * size, mask.y + es.dy * size, mask.w, mask.h);
}

export function paintDecorated(ctx, emitter, box, spec, size) {
  if (!spec || !(size > 0)) { return; }
  ctx.save();
  applyTransform(ctx, box, spec.transform);
  clearShadow(ctx);

  if (spec.plate) { paintPlate(ctx, box, spec.plate, size); }

  let mask = null;
  if (spec.longShadow || spec.edgeSplit) {
    mask = buildMask(ctx, emitter, box, size * MASK_PAD_EM);
  }
  if (spec.longShadow && mask) { paintLongShadow(ctx, mask, spec.longShadow, size); }

  if (spec.glow) {
    ctx.fillStyle = rgbToCss(spec.glow.rgb, 1);
    ctx.shadowColor = rgbToCss(spec.glow.rgb, spec.glow.alpha);
    ctx.shadowBlur = spec.glow.blur * size;
    ctx.shadowOffsetX = 0;
    ctx.shadowOffsetY = 0;
    for (let i = 0; i < spec.glow.passes; i++) { emitter(ctx, 'fill'); }
    clearShadow(ctx);
  }

  let shadowPending = !!spec.dropShadow;
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  ctx.miterLimit = 2;

  for (let i = 0; i < spec.strokes.length; i++) {
    const s = spec.strokes[i];
    if (shadowPending) { applyShadow(ctx, spec.dropShadow, size); shadowPending = false; }
    else { clearShadow(ctx); }
    ctx.lineWidth = s.width * size;
    ctx.strokeStyle = rgbToCss(s.rgb, s.alpha);
    emitter(ctx, 'stroke');
  }
  clearShadow(ctx);

  if (spec.bevel) {
    const o = spec.bevel.offset * size;
    if (shadowPending) { applyShadow(ctx, spec.dropShadow, size); shadowPending = false; }
    ctx.fillStyle = rgbToCss(spec.bevel.dark, spec.bevel.alpha);
    ctx.translate(o, o);
    emitter(ctx, 'fill');
    ctx.translate(-o * 2, -o * 2);
    clearShadow(ctx);
    ctx.fillStyle = rgbToCss(spec.bevel.light, spec.bevel.alpha);
    emitter(ctx, 'fill');
    ctx.translate(o, o);
  }

  if (spec.edgeSplit && mask) { paintEdgeSplit(ctx, mask, spec.edgeSplit, size); }

  if (shadowPending) { applyShadow(ctx, spec.dropShadow, size); shadowPending = false; }
  ctx.fillStyle = makeFillStyle(ctx, box, spec.fill);
  emitter(ctx, 'fill');
  clearShadow(ctx);

  if (spec.innerLine) {
    ctx.lineWidth = spec.innerLine.width * size;
    ctx.strokeStyle = rgbToCss(spec.innerLine.rgb, spec.innerLine.alpha);
    emitter(ctx, 'stroke');
  }

  if (spec.underline) { paintRule(ctx, box, spec.underline, size, false, !!spec.vertical); }
  if (spec.overline) { paintRule(ctx, box, spec.overline, size, true, !!spec.vertical); }

  if (spec.boten) {
    ctx.fillStyle = rgbToCss(spec.boten.rgb, spec.boten.alpha);
    emitter(ctx, 'boten');
  }

  ctx.restore();
}
