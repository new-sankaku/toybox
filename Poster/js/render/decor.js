import { blendRgb, contrastRatio, hslToRgb, luma01, rgbToCss, rgbToHsl, shade } from '../core/color.js';

const MAX_GLYPH_PASSES = 8;
const HEAVY_GLYPHS = 40;
const MIN_HEAVY_PASSES = 3;
const MIN_STOP_CONTRAST = 3.0;
const MIN_PLATE_CONTRAST = 4.5;
const MIN_EDGE_CONTRAST = 2.2;
const NOISY_STD = 0.17;
const MASK_PIXEL_LIMIT = 4194304;
const RAMP_BUCKETS = 4;
const MASK_PAD_EM = 0.35;
const MAX_BLUR_PX = 56;
const RAMP_HALF_PIXELS = 250000;
const RAMP_THIRD_PIXELS = 900000;
const DARK_INK = [12, 10, 10];
const LIGHT_INK = [248, 246, 242];
const GENRE_ORDER = ['cinema', 'gravure', 'novel', 'asmr', 'game', 'adult'];
const BUDGET = { title: 60, accent: 34, plain: 14 };
const GENRE_BUDGET = [1, 0.92, 0.28, 0.88, 1.05, 1.1];
const DISTORT_RATE = [0.03, 0.06, 0, 0.06, 0.09, 0.11];
const GLITCH_RATE = [0.04, 0.015, 0, 0.015, 0.08, 0.09];
const PARTIAL_PLATE_RATE = 0.12;
const BEVEL_RATE = [0, 0, 0, 0, 0.05, 0.12];
const METAL_RATE = [0.04, 0, 0, 0, 0.15, 0.3];

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
const PLATE_SHAPES = [
  { v: 'rect', w: 5 }, { v: 'roundRect', w: 4 }, { v: 'ribbon', w: 1.2 },
  { v: 'underlineBar', w: 0.8 }, { v: 'tag', w: 0.8 }, { v: 'brush', w: 0.5 },
  { v: 'tornPaper', w: 0.5 }, { v: 'ellipse', w: 0.3 }, { v: 'hexagon', w: 0.2 },
  { v: 'diamond', w: 0.2 }, { v: 'speechBubble', w: 0.3 }
];
const GLYPH_SHAPES = [
  { v: 'roundRect', w: 3 }, { v: 'circle', w: 2 }, { v: 'square', w: 2 },
  { v: 'ellipse', w: 1.5 }, { v: 'diamond', w: 0.6 }, { v: 'hexagon', w: 0.5 }
];
const PATTERN_KINDS = ['dots', 'grid', 'diagonal', 'crosshatch', 'checker'];

const AXES = [
  { id: 'fill.solid', group: 'fill', cost: 6, w: [4, 4, 8, 3, 2, 3] },
  { id: 'fill.linear', group: 'fill', cost: 8, w: [2, 3, 0, 4, 3, 3] },
  { id: 'fill.duotone', group: 'fill', cost: 10, w: [0.4, 0.8, 0, 1.2, 0.6, 1.2], minLevel: 0.5 },
  { id: 'fill.metallic', group: 'fill', cost: 16, w: [0.8, 0, 0, 0, 4, 2.5], minLevel: 1 },
  { id: 'fill.mirror', group: 'fill', cost: 16, w: [0.2, 0, 0, 0, 1.2, 0.8], minLevel: 1 },
  { id: 'fill.stripe', group: 'fill', cost: 14, w: [0.2, 0.3, 0, 0.4, 0.6, 1], minLevel: 1 },
  { id: 'fill.pattern', group: 'fill', cost: 14, w: [0.3, 0.3, 0, 0.5, 0.5, 0.8], minLevel: 1 },
  { id: 'fill.image', group: 'fill', cost: 18, w: [0.8, 0.3, 0, 0.2, 0.8, 0.6], minLevel: 1, need: 'source' },
  { id: 'fill.outlineOnly', group: 'fill', cost: 10, w: [0.3, 0.2, 0, 0.3, 0.5, 0.6], minLevel: 1 },

  { id: 'stroke.single', group: 'stroke', cost: 9, w: [3, 4, 0, 4, 1, 1] },
  { id: 'stroke.double', group: 'stroke', cost: 12, w: [1.5, 0.8, 0, 1.2, 5, 5] },
  { id: 'stroke.triple', group: 'stroke', cost: 18, w: [0.1, 0, 0, 0.1, 4, 4], minLevel: 1 },

  { id: 'glow.soft', group: 'glow', cost: 11, w: [0, 0, 0, 4, 0.4, 0] },
  { id: 'glow.neon', group: 'glow', cost: 16, w: [0, 0, 0, 1.2, 0.3, 0.2], minLevel: 1 },

  { id: 'shadow.soft', group: 'shadow', cost: 9, w: [1.5, 3.5, 0, 0.8, 1, 0.8] },
  { id: 'shadow.hard', group: 'shadow', cost: 8, w: [0.3, 0.4, 0, 0.2, 2.5, 4] },
  { id: 'shadow.long', group: 'shadow', cost: 14, w: [1.6, 0.2, 0, 0.1, 0.8, 1], minLevel: 1 },
  { id: 'shadow.extrude', group: 'shadow', cost: 16, w: [0.1, 0.1, 0, 0.1, 1.6, 1.2], minLevel: 1 },

  { id: 'plate.all', group: 'plate', cost: 10, w: [0.5, 1.5, 0.8, 1.2, 1, 2.2] },
  { id: 'plate.line', group: 'plate', cost: 12, w: [0.5, 1.2, 0.6, 1, 0.9, 1.8] },
  { id: 'plate.marker', group: 'plate', cost: 10, w: [0.3, 1.2, 0.6, 1, 0.4, 1.4], minLevel: 0.35 },
  { id: 'plate.knockout', group: 'plate', cost: 18, w: [0.8, 0.8, 1.2, 0.5, 1, 1.5], minLevel: 0.5 },
  { id: 'plate.phrase', group: 'plate', cost: 14, w: [0.4, 0.6, 0.3, 0.6, 0.6, 1], minLevel: 1, partial: true },
  { id: 'plate.head', group: 'plate', cost: 12, w: [0.4, 0.6, 0.5, 0.5, 0.5, 0.8], minLevel: 1, partial: true },
  { id: 'plate.tail', group: 'plate', cost: 12, w: [0.3, 0.4, 0.3, 0.4, 0.4, 0.6], minLevel: 1, partial: true },
  { id: 'plate.glyph', group: 'plate', cost: 18, w: [0.2, 0.5, 0.1, 0.6, 0.4, 0.6], minLevel: 1, partial: true },
  { id: 'plate.random', group: 'plate', cost: 16, w: [0.1, 0.3, 0.1, 0.3, 0.3, 0.5], minLevel: 1, partial: true },

  { id: 'distort.arc', group: 'distort', cost: 10, w: [0, 0, 0, 0, 2, 2], minLevel: 1 },
  { id: 'distort.wave', group: 'distort', cost: 10, w: [0.3, 1.5, 0, 1.5, 0.6, 1.2], minLevel: 1 },
  { id: 'distort.jitter', group: 'distort', cost: 10, w: [0.4, 0.8, 0, 0.8, 1.2, 2], minLevel: 1 },
  { id: 'distort.trapezoid', group: 'distort', cost: 12, w: [0.8, 0.4, 0, 0.3, 1.6, 1.2], minLevel: 1 },
  { id: 'distort.bulge', group: 'distort', cost: 10, w: [0.2, 0.8, 0, 0.8, 0.8, 1.2], minLevel: 1 },
  { id: 'distort.fan', group: 'distort', cost: 12, w: [0.1, 0.6, 0, 0.6, 0.4, 0.8], minLevel: 1 },
  { id: 'distort.stagger', group: 'distort', cost: 10, w: [0.2, 0.5, 0, 0.5, 0.6, 1.2], minLevel: 1 },
  { id: 'distort.alternate', group: 'distort', cost: 10, w: [0.2, 0.6, 0, 0.8, 0.5, 1.2], minLevel: 1 },
  { id: 'distort.ramp', group: 'distort', cost: 10, w: [0.4, 0.5, 0, 0.4, 0.6, 0.8], minLevel: 1 },
  { id: 'distort.shear', group: 'distort', cost: 10, w: [0.2, 0.4, 0, 0.3, 0.8, 1], minLevel: 1 },
  { id: 'distort.dropCap', group: 'distort', cost: 10, w: [0.3, 0.3, 0, 0.3, 0.2, 0.6], minLevel: 1 },
  { id: 'distort.shatter', group: 'distort', cost: 12, w: [0.1, 0.2, 0, 0.1, 1, 0.8], minLevel: 1 },

  { id: 'fx.bevel', group: 'fx', cost: 10, w: [0, 0, 0, 0, 3.5, 2.5], minLevel: 1 },
  { id: 'fx.innerLine', group: 'fx', cost: 9, w: [0.6, 0.3, 0, 0.2, 1.5, 1], minLevel: 0.5 },
  { id: 'fx.edgeSplit', group: 'fx', cost: 8, w: [2, 1, 0, 1, 4, 4], minLevel: 1, glitch: true },
  { id: 'fx.misregister', group: 'fx', cost: 12, w: [2, 1, 0, 1, 3, 3], minLevel: 1, glitch: true },
  { id: 'fx.splitCut', group: 'fx', cost: 12, w: [1, 0.5, 0, 0.5, 2, 2], minLevel: 1, glitch: true },
  { id: 'fx.reflection', group: 'fx', cost: 12, w: [0.2, 0.4, 0, 0.4, 1, 0.6], minLevel: 1 },
  { id: 'fx.roughEdge', group: 'fx', cost: 10, w: [0.6, 0.1, 0, 0.1, 0.6, 0.5], minLevel: 1 },
  { id: 'fx.torn', group: 'fx', cost: 10, w: [0.4, 0.1, 0.1, 0.1, 0.4, 0.4], minLevel: 1 },

  { id: 'orn.underline', group: 'orn', cost: 9, w: [1.2, 1.2, 2.2, 0.6, 0.8, 1.6] },
  { id: 'orn.overline', group: 'orn', cost: 9, w: [0.6, 0.6, 1.6, 0.4, 0.6, 0.8] },
  { id: 'orn.boten', group: 'orn', cost: 10, w: [0, 0, 3.5, 0, 0, 0], minLevel: 0.35 },

  { id: 'tf.skew', group: 'tf', cost: 9, w: [0.3, 1.2, 0, 0.4, 1.6, 2.5], minLevel: 1 },
  { id: 'tf.rotate', group: 'tf', cost: 8, w: [0.2, 0.8, 0, 0.6, 0.6, 1.6], minLevel: 1 },
  { id: 'tf.condense', group: 'tf', cost: 8, w: [3, 0.2, 0.3, 0.2, 1.2, 3] },
  { id: 'tf.expand', group: 'tf', cost: 8, w: [0.1, 0.6, 0, 0.8, 0.2, 0.4], minLevel: 0.5 }
];

const GROUP_CAP = { fill: 1, stroke: 1, glow: 1, shadow: 1, plate: 1, distort: 1, fx: 2, orn: 2, tf: 2 };

const RAW_CONFLICTS = {
  'fill.outlineOnly': ['plate.knockout', 'fx.reflection', 'fx.roughEdge', 'fx.splitCut', 'fx.bevel', 'fx.innerLine'],
  'fill.image': ['fx.misregister', 'fx.edgeSplit', 'plate.knockout'],
  'fill.stripe': ['plate.knockout', 'fx.misregister'],
  'fill.pattern': ['plate.knockout', 'fx.misregister'],
  'fill.metallic': ['plate.knockout', 'fill.mirror'],
  'fill.mirror': ['plate.knockout', 'fx.splitCut'],
  'fill.duotone': ['plate.knockout', 'fx.splitCut'],
  'fill.linear': ['plate.knockout'],
  'plate.knockout': ['glow.neon', 'fx.bevel', 'fx.edgeSplit', 'fx.misregister', 'fx.reflection', 'fx.splitCut', 'fx.roughEdge', 'fx.torn', 'fx.innerLine', 'shadow.extrude', 'shadow.long'],
  'plate.glyph': ['plate.marker', 'fx.reflection'],
  'glow.neon': ['fx.bevel', 'shadow.extrude', 'fx.misregister'],
  'shadow.extrude': ['shadow.long', 'fx.reflection', 'fx.splitCut'],
  'shadow.long': ['fx.reflection'],
  'fx.splitCut': ['distort.arc', 'distort.wave', 'distort.fan', 'distort.bulge', 'distort.trapezoid', 'fx.reflection'],
  'fx.reflection': ['distort.arc', 'distort.wave', 'distort.fan', 'distort.stagger'],
  'fx.misregister': ['fx.edgeSplit'],
  'fx.roughEdge': ['fx.torn', 'fx.bevel'],
  'distort.arc': ['distort.trapezoid', 'distort.wave', 'distort.fan', 'distort.stagger', 'distort.shatter'],
  'distort.wave': ['distort.fan', 'distort.stagger', 'distort.trapezoid'],
  'distort.bulge': ['distort.ramp', 'distort.alternate', 'distort.dropCap'],
  'distort.ramp': ['distort.alternate', 'distort.dropCap'],
  'distort.fan': ['distort.stagger', 'distort.trapezoid'],
  'distort.jitter': ['distort.shatter'],
  'tf.condense': ['tf.expand']
};

const CONFLICTS = (function () {
  const map = {};
  const keys = Object.keys(RAW_CONFLICTS);
  for (let i = 0; i < keys.length; i++) {
    const a = keys[i];
    const list = RAW_CONFLICTS[a];
    if (!map[a]) { map[a] = {}; }
    for (let j = 0; j < list.length; j++) {
      const b = list[j];
      map[a][b] = true;
      if (!map[b]) { map[b] = {}; }
      map[b][a] = true;
    }
  }
  return map;
})();

function genreIndex(genre) {
  const i = GENRE_ORDER.indexOf(genre);
  return i < 0 ? 0 : i;
}

function levelOf(slot) {
  const d = slot && slot.decor ? slot.decor : 'accent';
  if (d === 'title') { return 1; }
  if (d === 'plain') { return 0.16; }
  return 0.6;
}

function budgetOf(slot) {
  const d = slot && slot.decor ? slot.decor : 'accent';
  return BUDGET[d] !== undefined ? BUDGET[d] : BUDGET.accent;
}

function clamp01(v) {
  return v < 0 ? 0 : (v > 1 ? 1 : v);
}

function minContrast(rgb, bgs) {
  let m = Infinity;
  for (let i = 0; i < bgs.length; i++) {
    const c = contrastRatio(rgb, bgs[i]);
    if (c < m) { m = c; }
  }
  return m;
}

function safeShade(base, amount, bgs) {
  let a = amount;
  for (let i = 0; i < 7; i++) {
    const c = shade(base, a);
    if (minContrast(c, bgs) >= MIN_STOP_CONTRAST) { return c; }
    a *= 0.6;
  }
  return base.slice();
}

function inkAgainst(bgs) {
  return minContrast(DARK_INK, bgs) >= minContrast(LIGHT_INK, bgs) ? DARK_INK.slice() : LIGHT_INK.slice();
}

function inkOpposite(rgb) {
  return luma01(rgb) > 0.5 ? DARK_INK.slice() : LIGHT_INK.slice();
}

function planRgb(colorPlan, role) {
  if (!colorPlan || !colorPlan.roles) { return null; }
  const r = colorPlan.roles[role];
  if (!r || !r.rgb || r.rgb.length < 3) { return null; }
  return [r.rgb[0], r.rgb[1], r.rgb[2]];
}

function planOr(colorPlan, role, bgs, minRatio, derived) {
  const c = planRgb(colorPlan, role);
  if (c && minContrast(c, bgs) >= minRatio) { return c; }
  return derived;
}

function metalBase(base, metal) {
  const tint = METAL_TINT[metal];
  const hsl = rgbToHsl(base);
  const l = Math.min(0.76, Math.max(0.3, hsl[2]));
  const h = metal === 'silver' ? hsl[0] : tint.h;
  return blendRgb(base, hslToRgb([h, tint.s, l]), tint.mix);
}

function accentOf(rng, base, bgs, colorPlan) {
  const fromPlan = planRgb(colorPlan, 'accent');
  if (fromPlan && minContrast(fromPlan, bgs) >= MIN_STOP_CONTRAST) { return fromPlan; }
  const hsl = rgbToHsl(base);
  const cand = hslToRgb([(hsl[0] + rng.range(0.3, 0.7)) % 1, Math.max(0.45, hsl[1]), hsl[2]]);
  return minContrast(cand, bgs) >= MIN_STOP_CONTRAST ? cand : safeShade(base, rng.chance(0.5) ? 0.5 : -0.5, bgs);
}

function eligible(axis, state, ignoreBudget) {
  if (state.taken[axis.id]) { return false; }
  if (axis.group === 'distort' && !state.allow.distort) { return false; }
  if (axis.glitch && !state.allow.glitch) { return false; }
  if (axis.partial && !state.allow.partialPlate) { return false; }
  if (!ignoreBudget && axis.cost > state.budget) { return false; }
  if (axis.minLevel && state.level < axis.minLevel) { return false; }
  if (axis.need === 'source' && !state.source) { return false; }
  if ((state.groupCount[axis.group] || 0) >= GROUP_CAP[axis.group]) { return false; }
  const conf = CONFLICTS[axis.id];
  if (conf) {
    for (let k = 0; k < state.chosen.length; k++) { if (conf[state.chosen[k]]) { return false; } }
  }
  return axis.w[state.gi] > 0;
}

function pickAxis(rng, pool, state, ignoreBudget) {
  const items = [];
  for (let i = 0; i < pool.length; i++) {
    if (eligible(pool[i], state, ignoreBudget)) { items.push({ v: pool[i], w: pool[i].w[state.gi] }); }
  }
  if (items.length === 0) { return null; }
  return rng.weighted(items);
}

function takeAxis(state, axis) {
  state.taken[axis.id] = true;
  state.chosen.push(axis.id);
  state.groupCount[axis.group] = (state.groupCount[axis.group] || 0) + 1;
  state.budget -= axis.cost;
}

function buildLinearStops(rng, base, bgs, colorPlan) {
  const amp = rng.range(0.14, 0.44);
  const dir = rng.chance(0.62) ? 1 : -1;
  const alt = planRgb(colorPlan, 'inkAlt');
  const far = alt && minContrast(alt, bgs) >= MIN_STOP_CONTRAST
    ? alt
    : safeShade(base, -amp * dir * rng.range(0.6, 1.25), bgs);
  const stops = [{ t: 0, rgb: safeShade(base, amp * dir, bgs) }];
  if (rng.chance(0.4)) { stops.push({ t: rng.range(0.4, 0.62), rgb: safeShade(base, amp * dir * 0.2, bgs) }); }
  stops.push({ t: 1, rgb: far });
  return stops;
}

function shadowInk(base, bgs, colorPlan) {
  const fromPlan = planRgb(colorPlan, 'shadow');
  if (fromPlan && contrastRatio(fromPlan, base) >= 1.6 && minContrast(fromPlan, bgs) >= 1.4) { return fromPlan; }
  const against = inkAgainst(bgs);
  if (contrastRatio(against, base) >= 1.6) { return against; }
  return blendRgb(base, bgs[0], 0.6);
}

function layerInk(base, bgs, t) {
  let c = blendRgb(base, bgs[0], t);
  if (contrastRatio(c, base) < 1.5 || minContrast(c, bgs) < 1.5) {
    c = blendRgb(base, bgs[0], 0.55);
  }
  return c;
}

function buildShadow(rng, base, bgs, colorPlan, hard) {
  const off = rng.range(0.012, hard ? 0.09 : 0.055);
  const ang = rng.range(Math.PI * 0.18, Math.PI * 0.42);
  return {
    hard: hard, rgb: shadowInk(base, bgs, colorPlan),
    alpha: rng.range(hard ? 0.45 : 0.24, hard ? 0.85 : 0.6),
    dx: Math.cos(ang) * off, dy: Math.sin(ang) * off,
    blur: hard ? 0 : rng.range(0.06, 0.4)
  };
}

function buildRule(rng, base, bgs, colorPlan) {
  const derived = minContrast(base, bgs) >= MIN_STOP_CONTRAST ? base.slice() : inkAgainst(bgs);
  return {
    rgb: planOr(colorPlan, 'accent', bgs, MIN_STOP_CONTRAST, derived),
    alpha: rng.range(0.7, 1), width: rng.range(0.022, 0.075),
    gap: rng.range(0.08, 0.24), double: rng.chance(0.3), spacing: rng.range(0.05, 0.11)
  };
}

function plateColorFor(base, bg0, colorPlan) {
  const opp = inkOpposite(base);
  const cands = [];
  const planColor = planRgb(colorPlan, 'plate');
  if (planColor) { cands.push(planColor); }
  cands.push(blendRgb(opp, bg0, 0.18));
  cands.push(opp);
  cands.push([0, 0, 0]);
  cands.push([255, 255, 255]);
  let best = cands[0];
  let bestC = contrastRatio(cands[0], base);
  for (let i = 0; i < cands.length; i++) {
    const r = contrastRatio(cands[i], base);
    if (r >= MIN_PLATE_CONTRAST) { return cands[i]; }
    if (r > bestC) { best = cands[i]; bestC = r; }
  }
  return best;
}

function buildPlate(rng, id, base, bgs, colorPlan, forceCover) {
  const kind = id.substring(6);
  const rgb = plateColorFor(base, bgs[0], colorPlan);
  const perGlyph = kind === 'glyph' || kind === 'random';
  let shape;
  if (forceCover) { shape = rng.weighted([{ v: 'rect', w: 4 }, { v: 'roundRect', w: 2.5 }, { v: 'ribbon', w: 1 }, { v: 'tag', w: 1 }, { v: 'tornPaper', w: 1 }, { v: 'brush', w: 1 }, { v: 'hexagon', w: 0.6 }]); }
  else if (kind === 'marker') { shape = 'markerHighlight'; }
  else if (perGlyph) { shape = rng.weighted(GLYPH_SHAPES); }
  else if (kind === 'knockout') { shape = rng.weighted([{ v: 'rect', w: 4 }, { v: 'roundRect', w: 2 }, { v: 'ribbon', w: 1 }, { v: 'tag', w: 1 }]); }
  else if (kind === 'head' || kind === 'tail') { shape = rng.weighted([{ v: 'rect', w: 3 }, { v: 'roundRect', w: 2 }, { v: 'square', w: 2 }, { v: 'circle', w: 1.5 }, { v: 'tag', w: 1.5 }, { v: 'diamond', w: 1 }]); }
  else { shape = rng.weighted(PLATE_SHAPES); }

  let scope = kind;
  if (kind === 'marker') { scope = 'line'; }
  if (kind === 'knockout') { scope = rng.weighted([{ v: 'all', w: 4 }, { v: 'line', w: 2 }]); }
  if (forceCover && scope !== 'all' && scope !== 'line' && scope !== 'phrase') {
    scope = rng.weighted([{ v: 'all', w: 3 }, { v: 'line', w: 2 }, { v: 'phrase', w: 1 }]);
  }
  const covers = (scope === 'all' || scope === 'line' || scope === 'phrase')
    && shape !== 'markerHighlight' && shape !== 'underlineBar';

  return {
    scope: scope, kind: kind, covers: covers, knockout: kind === 'knockout', shape: shape,
    rgb: rgb, alpha: rng.range(0.7, 1),
    n: rng.int(1, 3), ratio: rng.range(0.2, 0.5),
    padX: perGlyph ? rng.range(0.04, 0.2) : rng.range(0.14, 0.44),
    padY: perGlyph ? rng.range(0.02, 0.14) : rng.range(0.05, 0.24),
    radius: rng.range(0.08, 0.34),
    skew: rng.chance(0.3) ? rng.range(0.1, 0.3) * (rng.chance(0.5) ? 1 : -1) : 0,
    rotate: rng.chance(0.3) ? rng.range(0.012, 0.06) * (rng.chance(0.5) ? 1 : -1) : 0,
    perRotate: perGlyph && rng.chance(0.5) ? rng.range(0.02, 0.14) : 0,
    border: rng.chance(0.32) ? { rgb: base.slice(), width: rng.range(0.012, 0.035), alpha: 0.9 } : null,
    shadow: rng.chance(0.3) ? { dx: rng.range(0.02, 0.08), dy: rng.range(0.02, 0.08), blur: rng.range(0, 0.2), rgb: DARK_INK.slice(), alpha: rng.range(0.25, 0.55) } : null,
    double: rng.chance(0.25) ? { rgb: planOr(colorPlan, 'accent', rgb, 1.6, shade(rgb, luma01(rgb) > 0.5 ? -0.35 : 0.4)), dx: rng.range(0.03, 0.12) * (rng.chance(0.5) ? 1 : -1), dy: rng.range(0.02, 0.1), alpha: rng.range(0.6, 1) } : null,
    seed: rng.int(1, 99999)
  };
}

function settlePlate(plate, bgBefore, base) {
  const target = Math.min(MIN_PLATE_CONTRAST, contrastRatio(plate.rgb, base));
  for (let i = 0; i < 10; i++) {
    const eff = blendRgb(bgBefore, plate.rgb, plate.alpha);
    if (contrastRatio(base, eff) >= target) { return eff; }
    if (plate.alpha >= 1) { break; }
    plate.alpha = Math.min(1, plate.alpha + 0.1);
  }
  plate.alpha = 1;
  return plate.rgb.slice();
}

function buildStrokes(rng, count, base, bgs, colorPlan, thick) {
  if (count <= 0) { return []; }
  const edgeBg = planOr(colorPlan, 'stroke', bgs, MIN_EDGE_CONTRAST, inkAgainst(bgs));
  const edgeInk = inkOpposite(base);
  const w0 = rng.range(0.03, 0.12) * (thick ? 1.3 : 1);
  const strokes = [];
  if (count === 1) {
    const rgb = contrastRatio(edgeBg, base) >= MIN_EDGE_CONTRAST ? edgeBg : edgeInk;
    strokes.push({ width: w0, rgb: rgb, alpha: rng.range(0.85, 1) });
    return strokes;
  }
  strokes.push({ width: w0, rgb: edgeBg, alpha: 1 });
  const inner = contrastRatio(edgeInk, edgeBg) >= MIN_EDGE_CONTRAST ? edgeInk : shade(edgeBg, luma01(edgeBg) > 0.5 ? -0.6 : 0.6);
  strokes.push({ width: w0 * 0.56, rgb: inner, alpha: 1 });
  if (count >= 3) {
    const hsl = rgbToHsl(base);
    const accent = hslToRgb([(hsl[0] + rng.range(0.36, 0.64)) % 1, Math.max(0.5, hsl[1]), 0.5]);
    strokes.push({ width: w0 * 0.3, rgb: contrastRatio(accent, inner) >= 1.8 ? accent : shade(inner, 0.5), alpha: 1 });
  }
  return strokes;
}

function applyAxis(id, s) {
  const rng = s.rng;
  const spec = s.spec;
  const base = s.base;
  const bgs = s.bgs;
  const plan = s.colorPlan;
  const vertical = rng.chance(0.74);
  const angle = vertical ? Math.PI / 2 + rng.range(-0.12, 0.12) : rng.range(-0.5, 0.5);

  switch (id) {
    case 'fill.solid':
      spec.fill = { type: 'solid', angle: 0, stops: [{ t: 0, rgb: base.slice() }, { t: 1, rgb: base.slice() }] };
      break;
    case 'fill.linear':
      spec.fill = { type: 'linear', angle: angle, stops: buildLinearStops(rng, base, bgs, plan) };
      break;
    case 'fill.duotone': {
      const split = rng.range(0.42, 0.58);
      const up = rng.range(0.2, 0.5) * (rng.chance(0.5) ? 1 : -1);
      const a = planOr(plan, 'ink', bgs, MIN_STOP_CONTRAST, safeShade(base, up, bgs));
      const b = planOr(plan, 'inkAlt', bgs, MIN_STOP_CONTRAST, safeShade(base, -up * rng.range(0.7, 1.3), bgs));
      spec.fill = {
        type: 'duotone', angle: angle,
        stops: [{ t: 0, rgb: a }, { t: split, rgb: a }, { t: Math.min(1, split + 0.004), rgb: b }, { t: 1, rgb: b }]
      };
      break;
    }
    case 'fill.metallic': {
      const metal = rng.weighted([{ v: 'gold', w: 3 }, { v: 'silver', w: 3 }, { v: 'chrome', w: 2 }]);
      const mb = metalBase(base, metal);
      if (minContrast(mb, bgs) < MIN_STOP_CONTRAST) {
        spec.fill = { type: 'linear', angle: angle, stops: buildLinearStops(rng, base, bgs, plan) };
        break;
      }
      const prof = METAL_PROFILE[metal];
      const stops = [];
      for (let i = 0; i < prof.length; i++) { stops.push({ t: prof[i][0], rgb: safeShade(mb, prof[i][1], bgs) }); }
      spec.fill = { type: 'metallic', metal: metal, angle: Math.PI / 2 + rng.range(-0.08, 0.08), stops: stops };
      break;
    }
    case 'fill.mirror': {
      const split = rng.range(0.44, 0.56);
      const hi = safeShade(base, 0.6, bgs);
      const lo = safeShade(base, -0.45, bgs);
      spec.fill = {
        type: 'mirror', angle: Math.PI / 2,
        stops: [
          { t: 0, rgb: lo }, { t: Math.max(0.01, split - 0.02), rgb: hi },
          { t: Math.min(0.99, split + 0.02), rgb: lo }, { t: 1, rgb: hi }
        ]
      };
      break;
    }
    case 'fill.stripe': {
      const alt = planOr(plan, 'accent', bgs, MIN_STOP_CONTRAST, safeShade(base, rng.chance(0.5) ? 0.55 : -0.5, bgs));
      spec.fill = {
        type: 'stripe', angle: 0,
        stops: [{ t: 0, rgb: base.slice() }, { t: 1, rgb: base.slice() }],
        stripe: {
          rgb: alt, width: rng.range(0.06, 0.18),
          slant: rng.chance(0.55) ? rng.range(0.4, 1.2) * (rng.chance(0.5) ? 1 : -1) : 0
        }
      };
      break;
    }
    case 'fill.pattern': {
      const alt = planOr(plan, 'accent', bgs, MIN_STOP_CONTRAST, safeShade(base, rng.chance(0.5) ? 0.5 : -0.45, bgs));
      spec.fill = {
        type: 'pattern', angle: 0,
        stops: [{ t: 0, rgb: base.slice() }, { t: 1, rgb: base.slice() }],
        pattern: { kind: rng.pick(PATTERN_KINDS), rgb: alt, step: rng.range(0.07, 0.2), weight: rng.range(0.1, 0.3) }
      };
      break;
    }
    case 'fill.image':
      spec.fill = {
        type: 'image', angle: 0,
        stops: [{ t: 0, rgb: base.slice() }, { t: 1, rgb: base.slice() }],
        image: { veil: base.slice(), veilAlpha: rng.range(0.28, 0.5), zoom: rng.range(1, 1.8) },
        source: s.source
      };
      break;
    case 'fill.outlineOnly':
      spec.fill = { type: 'none', angle: 0, stops: [{ t: 0, rgb: base.slice() }, { t: 1, rgb: base.slice() }] };
      spec.needStroke = true;
      break;

    case 'stroke.single': spec.strokeCount = 1; break;
    case 'stroke.double': spec.strokeCount = 2; break;
    case 'stroke.triple': spec.strokeCount = 3; break;

    case 'glow.soft':
      spec.glow = {
        rgb: planOr(plan, 'glow', bgs, 1, luma01(bgs[0]) > 0.5 ? shade(base, -0.55) : shade(base, 0.6)),
        alpha: rng.range(0.25, 0.55), blur: rng.range(0.22, 0.7), passes: rng.chance(0.4) ? 2 : 1
      };
      break;
    case 'glow.neon': {
      const tube = accentOf(rng, base, bgs, plan);
      spec.glow = { rgb: tube, alpha: rng.range(0.55, 0.9), blur: rng.range(0.6, 1.3), passes: 2 };
      spec.neon = { tube: tube, core: safeShade(base, 0.8, bgs), width: rng.range(0.07, 0.14) };
      break;
    }

    case 'shadow.soft': spec.dropShadow = buildShadow(rng, base, bgs, plan, false); break;
    case 'shadow.hard': spec.dropShadow = buildShadow(rng, base, bgs, plan, true); break;
    case 'shadow.long': {
      const ang = rng.range(Math.PI * 0.15, Math.PI * 0.45);
      const len = rng.range(0.18, 0.5);
      const steps = Math.max(6, Math.min(18, Math.round(len / 0.035)));
      spec.longShadow = {
        rgb: layerInk(base, bgs, rng.range(0.5, 0.72)), alpha: rng.range(0.5, 0.85), steps: steps,
        dx: Math.cos(ang) * len / steps, dy: Math.sin(ang) * len / steps
      };
      break;
    }
    case 'shadow.extrude': {
      const ang = rng.range(Math.PI * 0.1, Math.PI * 0.5);
      const depth = rng.range(0.08, 0.26);
      const steps = Math.max(4, Math.min(14, Math.round(depth / 0.018)));
      const face = layerInk(base, bgs, rng.range(0.4, 0.6));
      spec.extrude = {
        near: face, far: blendRgb(face, bgs[0], 0.45), steps: steps,
        dx: Math.cos(ang) * depth / steps, dy: Math.sin(ang) * depth / steps
      };
      break;
    }

    case 'plate.all':
    case 'plate.line':
    case 'plate.phrase':
    case 'plate.glyph':
    case 'plate.head':
    case 'plate.tail':
    case 'plate.random':
    case 'plate.marker':
    case 'plate.knockout':
      spec.plate = buildPlate(rng, id, base, bgs, plan, s.forceCover);
      break;

    case 'distort.arc':
      spec.distort.arc = rng.range(0.04, 0.16) * (rng.chance(0.75) ? 1 : -1);
      break;
    case 'distort.wave':
      spec.distort.wave = { amp: rng.range(0.03, 0.09), freq: rng.range(0.5, 1.4), phase: rng.range(0, Math.PI * 2) };
      break;
    case 'distort.jitter':
      spec.distort.jitter = { rot: rng.range(0.006, 0.022), off: rng.range(0.006, 0.02), scale: rng.range(0.02, 0.05) };
      break;
    case 'distort.trapezoid':
      spec.distort.trapezoid = rng.range(0.12, 0.42) * (rng.chance(0.5) ? 1 : -1);
      break;
    case 'distort.bulge':
      spec.distort.bulge = rng.range(0.12, 0.45);
      break;
    case 'distort.fan':
      spec.distort.fan = rng.range(0.05, 0.2);
      break;
    case 'distort.stagger':
      spec.distort.stagger = rng.range(0.04, 0.12) * (rng.chance(0.5) ? 1 : -1);
      break;
    case 'distort.alternate':
      spec.distort.alternate = rng.range(0.08, 0.28);
      break;
    case 'distort.ramp':
      spec.distort.ramp = rng.range(0.15, 0.5) * (rng.chance(0.5) ? 1 : -1);
      break;
    case 'distort.shear':
      spec.distort.shear = rng.range(0.06, 0.24);
      break;
    case 'distort.dropCap':
      spec.distort.dropCap = rng.range(0.35, 0.9);
      break;
    case 'distort.shatter':
      spec.distort.shatter = { ratio: rng.range(0.08, 0.2), amp: rng.range(0.05, 0.16) };
      break;

    case 'fx.bevel':
      spec.bevel = {
        light: safeShade(base, rng.range(0.35, 0.7), bgs),
        dark: safeShade(base, -rng.range(0.35, 0.7), bgs),
        offset: rng.range(0.014, 0.05), alpha: rng.range(0.7, 1)
      };
      break;
    case 'fx.innerLine':
      spec.innerLine = {
        rgb: luma01(base) > 0.5 ? shade(base, -0.5) : shade(base, 0.55),
        width: rng.range(0.008, 0.022), alpha: rng.range(0.55, 0.9)
      };
      break;
    case 'fx.edgeSplit':
      spec.edgeSplit = {
        dx: rng.range(0.006, 0.024) * (rng.chance(0.5) ? 1 : -1),
        dy: rng.range(0, 0.01) * (rng.chance(0.5) ? 1 : -1),
        alpha: rng.range(0.4, 0.8), a: [255, 46, 46], b: [40, 170, 255]
      };
      break;
    case 'fx.misregister': {
      const a = accentOf(rng, base, bgs, plan);
      spec.misregister = {
        layers: [
          { rgb: a, dx: rng.range(0.008, 0.03) * (rng.chance(0.5) ? 1 : -1), dy: rng.range(-0.02, 0.02), alpha: rng.range(0.45, 0.85) },
          { rgb: safeShade(base, -0.5, bgs), dx: rng.range(-0.03, -0.008), dy: rng.range(-0.02, 0.02), alpha: rng.range(0.35, 0.7) }
        ]
      };
      if (rng.chance(0.35)) {
        spec.misregister.layers.push({ rgb: safeShade(base, 0.5, bgs), dx: rng.range(-0.02, 0.02), dy: rng.range(0.008, 0.03), alpha: rng.range(0.3, 0.6) });
      }
      break;
    }
    case 'fx.splitCut':
      spec.splitCut = { at: rng.range(0.4, 0.62), shift: rng.range(0.03, 0.13) * (rng.chance(0.5) ? 1 : -1) };
      break;
    case 'fx.reflection':
      spec.reflection = { gap: rng.range(0.02, 0.12), alpha: rng.range(0.22, 0.5), fade: rng.range(0.3, 0.7) };
      break;
    case 'fx.roughEdge':
      spec.roughEdge = { amount: rng.range(0.02, 0.06), density: rng.range(0.6, 1.4), seed: rng.int(1, 9999) };
      break;
    case 'fx.torn':
      spec.torn = { count: rng.int(2, 5), amount: rng.range(0.1, 0.32), seed: rng.int(1, 9999) };
      break;

    case 'orn.underline': spec.underline = buildRule(rng, base, bgs, plan); break;
    case 'orn.overline': spec.overline = buildRule(rng, base, bgs, plan); break;
    case 'orn.boten':
      spec.boten = {
        rgb: minContrast(base, bgs) >= MIN_STOP_CONTRAST ? base.slice() : inkAgainst(bgs),
        mark: rng.pick(BOTEN_MARKS), size: rng.range(0.16, 0.26),
        gap: rng.range(0.06, 0.16), alpha: rng.range(0.8, 1)
      };
      break;

    case 'tf.skew': spec.transform.skewX = rng.range(0.05, 0.22); break;
    case 'tf.rotate': spec.transform.rotate = rng.range(0.004, 0.04) * (rng.chance(0.5) ? 1 : -1) * Math.PI; break;
    case 'tf.condense': spec.transform.scaleX = rng.range(0.72, 0.94); break;
    case 'tf.expand': spec.transform.scaleX = rng.range(1.05, 1.16); break;
    default: break;
  }
}

function usesMask(spec) {
  return !!(spec.longShadow || spec.extrude || spec.edgeSplit || spec.misregister
    || spec.reflection || spec.roughEdge || spec.torn
    || (spec.plate && spec.plate.knockout)
    || spec.fill.type === 'stripe' || spec.fill.type === 'pattern' || spec.fill.type === 'image');
}

function layerFillActive(spec) {
  const t = spec.fill.type;
  return t === 'stripe' || t === 'pattern' || t === 'image' || !!spec.roughEdge || !!spec.torn;
}

function fillPasses(spec) {
  if (spec.plate && spec.plate.knockout) { return 0; }
  if (spec.fill.type === 'none') { return 0; }
  if (layerFillActive(spec)) { return 0; }
  if (spec.splitCut) { return 2; }
  return 1;
}

function passCost(spec) {
  let cost = fillPasses(spec);
  cost += spec.strokes.length;
  if (spec.glow) { cost += spec.glow.passes; }
  if (spec.bevel) { cost += 2; }
  if (spec.innerLine) { cost += 1; }
  if (usesMask(spec)) { cost += 1; }
  return cost;
}

function capPasses(spec) {
  const drop = ['edgeSplit', 'misregister', 'reflection', 'innerLine', 'bevel', 'splitCut', 'torn'];
  for (let i = 0; i < drop.length && passCost(spec) > MAX_GLYPH_PASSES; i++) {
    if (spec[drop[i]]) { spec[drop[i]] = null; }
  }
  if (passCost(spec) > MAX_GLYPH_PASSES && spec.glow && spec.glow.passes > 1) { spec.glow.passes = 1; }
  while (passCost(spec) > MAX_GLYPH_PASSES && spec.strokes.length > 1) { spec.strokes.pop(); }
  if (passCost(spec) > MAX_GLYPH_PASSES && spec.glow) { spec.glow = null; }
}

export function buildDecorSpec(rng, genre, slot, style, stats, intensity, colorPlan, opts) {
  const level = levelOf(slot);
  const inten = typeof intensity === 'number' ? intensity : 0.5;
  const base = style.color.slice();
  const noisy = stats.std > NOISY_STD;
  const tiered = !!(slot && slot.tiered);
  const plan = colorPlan || null;
  const gi = genreIndex(genre);
  const source = opts && opts.sourceCanvas ? opts.sourceCanvas : null;

  let bareBg = stats.rgb.slice();
  if (style.scrim) { bareBg = blendRgb(bareBg, style.scrim.color, style.scrim.alpha); }

  const spec = {
    genre: genre, level: level,
    fill: null, strokes: [], strokeCount: 0, glow: null, neon: null, dropShadow: null,
    longShadow: null, extrude: null, bevel: null, innerLine: null, plate: null,
    underline: null, overline: null, boten: null, edgeSplit: null, misregister: null,
    splitCut: null, reflection: null, roughEdge: null, torn: null, needStroke: false,
    distort: {
      arc: 0, wave: null, jitter: null, trapezoid: 0, bulge: 0, fan: 0, stagger: 0,
      alternate: 0, ramp: 0, shear: 0, dropCap: 0, shatter: null, seed: rng.int(1, 99999)
    },
    transform: { skewX: 0, rotate: 0, scaleX: 1, originX: 0.5, originY: 0.5 },
    vertical: false, effectiveBg: bareBg, plateBg: null, axes: []
  };

  const state = {
    rng: rng, spec: spec, base: base, bgs: [bareBg], colorPlan: plan, source: source,
    gi: gi, level: level, taken: {}, chosen: [], groupCount: {},
    allow: {
      distort: level >= 1 && rng.chance(DISTORT_RATE[gi]),
      glitch: level >= 1 && rng.chance(GLITCH_RATE[gi]),
      partialPlate: level >= 1 && rng.chance(PARTIAL_PLATE_RATE)
    },
    budget: budgetOf(slot) * (0.65 + inten * 0.7) * GENRE_BUDGET[gi]
  };

  const fillPool = [];
  const platePool = [];
  const distortPool = [];
  const glitchPool = [];
  const metalPool = [];
  const bevelPool = [];
  for (let i = 0; i < AXES.length; i++) {
    const a = AXES[i];
    if (a.group === 'fill') {
      fillPool.push(a);
      if (a.id === 'fill.metallic' || a.id === 'fill.mirror') { metalPool.push(a); }
    } else if (a.group === 'distort') { distortPool.push(a); }
    else if (a.glitch) { glitchPool.push(a); }
    else if (a.id === 'fx.bevel') { bevelPool.push(a); }
    else if (a.group === 'plate' && a.id !== 'plate.knockout' && a.id !== 'plate.glyph'
      && a.id !== 'plate.random' && a.id !== 'plate.marker') { platePool.push(a); }
  }

  const selected = [];
  if (noisy || tiered || minContrast(base, state.bgs) < MIN_STOP_CONTRAST) {
    const forced = pickAxis(rng, platePool, state, true);
    if (forced) {
      takeAxis(state, forced);
      state.budget += forced.cost;
      selected.push({ axis: forced, forceCover: true });
    }
  }

  if (state.allow.distort) {
    const d = pickAxis(rng, distortPool, state, true);
    if (d) { takeAxis(state, d); selected.push({ axis: d, forceCover: false }); }
  }
  if (state.allow.glitch) {
    const gx = pickAxis(rng, glitchPool, state, true);
    if (gx) { takeAxis(state, gx); selected.push({ axis: gx, forceCover: false }); }
  }

  if (level >= 1 && rng.chance(BEVEL_RATE[gi])) {
    const bv = pickAxis(rng, bevelPool, state, true);
    if (bv) { takeAxis(state, bv); selected.push({ axis: bv, forceCover: false }); }
  }

  let fillAxis = null;
  if (level >= 1 && rng.chance(METAL_RATE[gi])) { fillAxis = pickAxis(rng, metalPool, state, true); }
  if (!fillAxis) { fillAxis = pickAxis(rng, fillPool, state, false); }
  if (!fillAxis) { fillAxis = pickAxis(rng, fillPool, state, true); }
  if (fillAxis) {
    takeAxis(state, fillAxis);
    selected.push({ axis: fillAxis, forceCover: false });
  }

  for (let guard = 0; guard < 24 && state.budget > 2; guard++) {
    const axis = pickAxis(rng, AXES, state, false);
    if (!axis) { break; }
    takeAxis(state, axis);
    selected.push({ axis: axis, forceCover: false });
  }

  const rank = { plate: 0, fill: 1 };
  const ordered = selected.slice().sort(function (a, b) {
    const ra = rank[a.axis.group] === undefined ? 2 : rank[a.axis.group];
    const rb = rank[b.axis.group] === undefined ? 2 : rank[b.axis.group];
    return ra - rb;
  });

  for (let i = 0; i < ordered.length; i++) {
    const entry = ordered[i];
    state.forceCover = entry.forceCover;
    applyAxis(entry.axis.id, state);
    state.forceCover = false;
    if (entry.axis.group === 'plate' && spec.plate) {
      const plated = settlePlate(spec.plate, bareBg, base);
      spec.plateBg = plated;
      state.bgs = spec.plate.covers ? [plated] : [bareBg, plated];
    }
    let label = entry.axis.id;
    if (entry.axis.group === 'plate' && spec.plate) { label += ':' + spec.plate.scope + '/' + spec.plate.shape; }
    if (entry.axis.group === 'fill' && spec.fill && spec.fill.metal) { label += ':' + spec.fill.metal; }
    spec.axes.push(label);
  }

  const bgs = state.bgs;

  const covered = !!(spec.plate && (spec.plate.covers || spec.plate.knockout));
  if (spec.needStroke && spec.strokeCount === 0) { spec.strokeCount = 1; }
  if (spec.neon && spec.strokeCount === 0) { spec.strokeCount = 1; }
  if (noisy && spec.strokeCount === 0 && !covered && !spec.glow) { spec.strokeCount = 1; }
  if (tiered && !covered && spec.strokeCount < 2) { spec.strokeCount = 2; }
  if (spec.plate && spec.strokeCount === 0
    && contrastRatio(spec.plate.rgb, base) < MIN_STOP_CONTRAST) { spec.strokeCount = 1; }
  spec.strokes = buildStrokes(rng, spec.strokeCount, base, bgs, plan, noisy && !covered);

  if (spec.neon && spec.strokes.length > 0) {
    spec.strokes[0].rgb = spec.neon.tube;
    spec.strokes[0].width = spec.neon.width;
    spec.strokes[0].alpha = 1;
    if (spec.fill.type === 'solid' || spec.fill.type === 'linear') {
      spec.fill = { type: 'solid', angle: 0, stops: [{ t: 0, rgb: spec.neon.core }, { t: 1, rgb: spec.neon.core }] };
    }
  }

  if (spec.fill.type === 'image' && !spec.fill.source) {
    spec.fill = { type: 'linear', angle: Math.PI / 2, stops: buildLinearStops(rng, base, bgs, plan) };
  }
  if ((spec.fill.type === 'image' || spec.fill.type === 'none') && spec.strokes.length === 0) {
    spec.strokes = buildStrokes(rng, 1, base, bgs, plan, true);
  }
  if (noisy && !covered && !spec.glow && spec.strokes.length === 0) {
    spec.strokes = buildStrokes(rng, 2, base, bgs, plan, true);
    spec.axes.push('stroke.forced');
  }

  spec.effectiveBg = bgs[0];
  spec.effectiveBgs = bgs;
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
  ctx.shadowBlur = Math.min(sh.blur * size, MAX_BLUR_PX);
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

function hash01(n) {
  let x = Math.sin(n * 12.9898) * 43758.5453;
  x -= Math.floor(x);
  return x < 0 ? x + 1 : x;
}

function shapePath(ctx, shape, x, y, w, h, r, seed) {
  const cx = x + w / 2;
  const cy = y + h / 2;
  ctx.beginPath();
  if (shape === 'circle') {
    ctx.arc(cx, cy, Math.max(w, h) / 2, 0, Math.PI * 2);
    return;
  }
  if (shape === 'ellipse') {
    if (typeof ctx.ellipse === 'function') { ctx.ellipse(cx, cy, w / 2, h / 2, 0, 0, Math.PI * 2); }
    else { ctx.arc(cx, cy, Math.max(w, h) / 2, 0, Math.PI * 2); }
    return;
  }
  if (shape === 'square') {
    const s = Math.max(w, h) / 2;
    ctx.rect(cx - s, cy - s, s * 2, s * 2);
    return;
  }
  if (shape === 'diamond') {
    ctx.moveTo(cx, y - h * 0.18);
    ctx.lineTo(x + w * 1.08, cy);
    ctx.lineTo(cx, y + h * 1.18);
    ctx.lineTo(x - w * 0.08, cy);
    ctx.closePath();
    return;
  }
  if (shape === 'hexagon') {
    const k = Math.min(w * 0.3, h * 0.32);
    ctx.moveTo(x + k, y);
    ctx.lineTo(x + w - k, y);
    ctx.lineTo(x + w, cy);
    ctx.lineTo(x + w - k, y + h);
    ctx.lineTo(x + k, y + h);
    ctx.lineTo(x, cy);
    ctx.closePath();
    return;
  }
  if (shape === 'ribbon') {
    const k = Math.min(w * 0.24, h * 0.34);
    ctx.moveTo(x, y);
    ctx.lineTo(x + w, y);
    ctx.lineTo(x + w - k, cy);
    ctx.lineTo(x + w, y + h);
    ctx.lineTo(x, y + h);
    ctx.lineTo(x + k, cy);
    ctx.closePath();
    return;
  }
  if (shape === 'tag') {
    const k = Math.min(w * 0.3, h * 0.42);
    ctx.moveTo(x, y);
    ctx.lineTo(x + w - k, y);
    ctx.lineTo(x + w, cy);
    ctx.lineTo(x + w - k, y + h);
    ctx.lineTo(x, y + h);
    ctx.closePath();
    return;
  }
  if (shape === 'speechBubble') {
    const rr = Math.min(r, w / 2, h / 2);
    const tx = x + w * 0.24;
    ctx.moveTo(x + rr, y);
    ctx.lineTo(x + w - rr, y);
    ctx.arcTo(x + w, y, x + w, y + rr, rr);
    ctx.lineTo(x + w, y + h - rr);
    ctx.arcTo(x + w, y + h, x + w - rr, y + h, rr);
    ctx.lineTo(tx + h * 0.3, y + h);
    ctx.lineTo(tx, y + h + h * 0.34);
    ctx.lineTo(tx, y + h);
    ctx.lineTo(x + rr, y + h);
    ctx.arcTo(x, y + h, x, y + h - rr, rr);
    ctx.lineTo(x, y + rr);
    ctx.arcTo(x, y, x + rr, y, rr);
    ctx.closePath();
    return;
  }
  if (shape === 'brush') {
    const n = 7;
    ctx.moveTo(x, y + h * 0.06);
    for (let i = 1; i <= n; i++) {
      const t = i / n;
      ctx.quadraticCurveTo(x + w * (t - 0.5 / n), y + h * (hash01(seed + i) * 0.18 - 0.04), x + w * t, y + h * (hash01(seed + i + 40) * 0.12));
    }
    ctx.lineTo(x + w, y + h * 0.94);
    for (let i = n; i >= 0; i--) {
      const t = i / n;
      ctx.quadraticCurveTo(x + w * (t + 0.5 / n), y + h * (0.86 + hash01(seed + i + 80) * 0.18), x + w * t, y + h * (0.9 + hash01(seed + i + 120) * 0.1));
    }
    ctx.closePath();
    return;
  }
  if (shape === 'tornPaper') {
    const n = 9;
    ctx.moveTo(x, y);
    for (let i = 1; i <= n; i++) { ctx.lineTo(x + w * (i / n), y + h * hash01(seed + i) * 0.12); }
    ctx.lineTo(x + w, y + h);
    for (let i = n; i >= 0; i--) { ctx.lineTo(x + w * (i / n), y + h * (0.88 + hash01(seed + i + 50) * 0.12)); }
    ctx.closePath();
    return;
  }
  if (shape === 'underlineBar') {
    ctx.rect(x, y + h * 0.7, w, h * 0.3);
    return;
  }
  if (shape === 'markerHighlight') {
    ctx.rect(x, y + h * 0.36, w, h * 0.68);
    return;
  }
  if (shape === 'roundRect') {
    const rr = Math.min(r, w / 2, h / 2);
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
    return;
  }
  ctx.rect(x, y, w, h);
}

function unionRect(list) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (let i = 0; i < list.length; i++) {
    if (list[i].x < x0) { x0 = list[i].x; }
    if (list[i].y < y0) { y0 = list[i].y; }
    if (list[i].x + list[i].w > x1) { x1 = list[i].x + list[i].w; }
    if (list[i].y + list[i].h > y1) { y1 = list[i].y + list[i].h; }
  }
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
}

function plateRegions(regions, plate, box) {
  if (!regions) { return [box]; }
  const scope = plate.scope;
  if (scope === 'line' && regions.line && regions.line.length) { return regions.line; }
  if (scope === 'phrase' && regions.phrase && regions.phrase.length) { return regions.phrase; }
  if (scope === 'glyph' && regions.glyph && regions.glyph.length) { return regions.glyph; }
  const g = regions.glyph || [];
  if ((scope === 'head' || scope === 'tail') && g.length > 0) {
    const n = Math.max(1, Math.min(plate.n, g.length));
    return [unionRect(scope === 'head' ? g.slice(0, n) : g.slice(g.length - n))];
  }
  if (scope === 'random' && g.length > 0) {
    const out = [];
    for (let i = 0; i < g.length; i++) {
      if (hash01(plate.seed + i * 7.13) < plate.ratio) { out.push(g[i]); }
    }
    return out.length > 0 ? out : [g[0]];
  }
  return [box];
}

function paintPlateShape(ctx, rect, plate, size, index, tf) {
  const px = plate.padX * size;
  const py = plate.padY * size;
  const x = rect.x - px;
  const y = rect.y - py;
  const w = rect.w + px * 2;
  const h = rect.h + py * 2;
  if (!(w > 0) || !(h > 0)) { return; }
  const flat = plate.shape === 'markerHighlight' || plate.shape === 'underlineBar';
  const outerSkewed = !!(tf && (tf.skewX || tf.rotate));
  const suppress = flat || outerSkewed;
  ctx.save();
  const rot = suppress ? 0 : plate.rotate + (plate.perRotate ? (hash01(plate.seed + index * 3.7) - 0.5) * 2 * plate.perRotate : 0);
  const skew = suppress ? 0 : plate.skew;
  if (rot || skew) {
    const cx = x + w / 2;
    const cy = y + h / 2;
    ctx.translate(cx, cy);
    if (rot) { ctx.rotate(rot); }
    if (skew) { ctx.transform(1, 0, -skew, 1, 0, 0); }
    ctx.translate(-cx, -cy);
  }
  if (plate.double) {
    ctx.fillStyle = rgbToCss(plate.double.rgb, plate.double.alpha);
    shapePath(ctx, plate.shape, x + plate.double.dx * size, y + plate.double.dy * size, w, h, plate.radius * size, plate.seed + index);
    ctx.fill();
  }
  if (plate.shadow) {
    ctx.shadowColor = rgbToCss(plate.shadow.rgb, plate.shadow.alpha);
    ctx.shadowBlur = plate.shadow.blur * size;
    ctx.shadowOffsetX = plate.shadow.dx * size;
    ctx.shadowOffsetY = plate.shadow.dy * size;
  }
  ctx.fillStyle = rgbToCss(plate.rgb, plate.alpha);
  shapePath(ctx, plate.shape, x, y, w, h, plate.radius * size, plate.seed + index);
  ctx.fill();
  clearShadow(ctx);
  if (plate.border) {
    ctx.lineWidth = plate.border.width * size;
    ctx.strokeStyle = rgbToCss(plate.border.rgb, plate.border.alpha);
    ctx.stroke();
  }
  ctx.restore();
}

function paintPlates(ctx, regions, box, plate, size, tf) {
  const rects = plateRegions(regions, plate, box);
  for (let i = 0; i < rects.length; i++) { paintPlateShape(ctx, rects[i], plate, size, i, tf); }
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

function newCanvas(w, h) {
  if (typeof document === 'undefined') { return null; }
  const cv = document.createElement('canvas');
  cv.width = w;
  cv.height = h;
  return cv;
}

const SCRATCH = [];

function scratchCtx(slot, w, h) {
  const e = SCRATCH[slot];
  if (!e || e.cv.width < w || e.cv.height < h || e.cv.width * e.cv.height > w * h * 4) {
    const cv = newCanvas(w, h);
    if (!cv) { return null; }
    const ctx = cv.getContext('2d');
    if (!ctx) { return null; }
    SCRATCH[slot] = { cv: cv, ctx: ctx };
    return SCRATCH[slot];
  }
  e.ctx.setTransform(1, 0, 0, 1, 0, 0);
  e.ctx.globalCompositeOperation = 'source-over';
  e.ctx.globalAlpha = 1;
  e.ctx.clearRect(0, 0, w, h);
  return e;
}

function blit(ctx, cv, mask, dx, dy) {
  ctx.drawImage(cv, 0, 0, mask.pw, mask.ph, mask.x + dx, mask.y + dy, mask.w, mask.h);
}

function buildMask(ctx, emitter, box, pad) {
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
  const e = scratchCtx(0, w, h);
  if (!e) { return null; }
  const oc = e.ctx;
  const x = box.x - pad;
  const y = box.y - pad;
  oc.save();
  oc.scale(sx, sy);
  oc.translate(-x, -y);
  oc.fillStyle = '#000000';
  emitter(oc, 'fill');
  oc.restore();
  return { cv: e.cv, x: x, y: y, w: bw, h: bh, pw: w, ph: h, sx: sx, sy: sy };
}

function tintedMask(mask, rgb, alpha, slot) {
  const e = scratchCtx(slot, mask.pw, mask.ph);
  if (!e) { return null; }
  const oc = e.ctx;
  oc.drawImage(mask.cv, 0, 0, mask.pw, mask.ph, 0, 0, mask.pw, mask.ph);
  oc.globalCompositeOperation = 'source-in';
  oc.fillStyle = rgbToCss(rgb, alpha);
  oc.fillRect(0, 0, mask.pw, mask.ph);
  oc.globalCompositeOperation = 'source-over';
  return e.cv;
}

function maskedLayer(mask, painter, slot) {
  const e = scratchCtx(slot, mask.pw, mask.ph);
  if (!e) { return null; }
  const oc = e.ctx;
  oc.save();
  oc.scale(mask.sx, mask.sy);
  oc.translate(-mask.x, -mask.y);
  painter(oc);
  oc.restore();
  oc.globalCompositeOperation = 'destination-in';
  oc.drawImage(mask.cv, 0, 0, mask.pw, mask.ph, 0, 0, mask.pw, mask.ph);
  oc.globalCompositeOperation = 'source-over';
  return e;
}

function eraseNoise(oc, pw, ph, spec, size, scale) {
  oc.save();
  oc.globalCompositeOperation = 'destination-out';
  oc.fillStyle = '#000000';
  const step = Math.max(3, size * 0.09 * scale);
  const amp = spec.amount * size * scale;
  const cols = Math.ceil(pw / step);
  const rows = Math.ceil(ph / step);
  const threshold = Math.min(0.9, 0.4 * spec.density);
  oc.beginPath();
  for (let i = 0; i < cols; i++) {
    for (let j = 0; j < rows; j++) {
      if (hash01(spec.seed + i * 31.7 + j * 7.13) > threshold) { continue; }
      const r = amp * (0.4 + hash01(spec.seed + i * 3.1 + j * 11.7));
      oc.moveTo(i * step + step / 2 + r, j * step + step / 2);
      oc.arc(i * step + step / 2, j * step + step / 2, r, 0, Math.PI * 2);
    }
  }
  oc.fill();
  oc.restore();
}

function eraseTorn(oc, pw, ph, spec, size, scale) {
  oc.save();
  oc.globalCompositeOperation = 'destination-out';
  oc.fillStyle = '#000000';
  for (let i = 0; i < spec.count; i++) {
    const x = hash01(spec.seed + i * 5.7) * pw;
    const y = hash01(spec.seed + i * 13.1) * ph;
    const w = spec.amount * size * scale * (0.5 + hash01(spec.seed + i * 2.3));
    const h = spec.amount * size * scale * (0.5 + hash01(spec.seed + i * 9.9));
    oc.save();
    oc.translate(x, y);
    oc.rotate(hash01(spec.seed + i * 17.3) * Math.PI);
    oc.fillRect(-w / 2, -h / 2, w, h);
    oc.restore();
  }
  oc.restore();
}

function paintOffsetLayers(ctx, mask, layers, size) {
  for (let i = 0; i < layers.length; i++) {
    const l = layers[i];
    const cv = tintedMask(mask, l.rgb, l.alpha, 1);
    if (!cv) { return; }
    blit(ctx, cv, mask, l.dx * size, l.dy * size);
  }
}

function paintRamp(ctx, mask, near, far, steps, dx, dy, size, alpha) {
  const px = mask.pw * mask.ph;
  let n = steps;
  if (px > RAMP_THIRD_PIXELS) { n = Math.max(3, Math.round(steps / 3)); }
  else if (px > RAMP_HALF_PIXELS) { n = Math.max(3, Math.round(steps / 2)); }
  const mx = dx * steps / n;
  const my = dy * steps / n;
  const flat = near[0] === far[0] && near[1] === far[1] && near[2] === far[2];
  const buckets = flat ? 1 : Math.min(RAMP_BUCKETS, n);
  const layers = [];
  for (let b = 0; b < buckets; b++) {
    const t = buckets > 1 ? b / (buckets - 1) : 0;
    const cv = tintedMask(mask, blendRgb(near, far, t), alpha, 2 + b);
    if (!cv) { return; }
    layers.push(cv);
  }
  for (let i = n; i >= 1; i--) {
    const t = n > 1 ? (i - 1) / (n - 1) : 0;
    const idx = buckets > 1 ? Math.min(buckets - 1, Math.round(t * (buckets - 1))) : 0;
    blit(ctx, layers[idx], mask, mx * size * i, my * size * i);
  }
}

function paintStripes(oc, mask, fill, size) {
  oc.fillStyle = rgbToCss(fill.stops[0].rgb);
  oc.fillRect(mask.x, mask.y, mask.w, mask.h);
  oc.fillStyle = rgbToCss(fill.stripe.rgb);
  const step = Math.max(1, fill.stripe.width * size);
  const slant = fill.stripe.slant;
  const over = Math.abs(slant) * mask.h;
  for (let y = mask.y - mask.h; y < mask.y + mask.h * 2; y += step * 2) {
    oc.beginPath();
    oc.moveTo(mask.x - over, y);
    oc.lineTo(mask.x + mask.w + over, y + slant * mask.h);
    oc.lineTo(mask.x + mask.w + over, y + slant * mask.h + step);
    oc.lineTo(mask.x - over, y + step);
    oc.closePath();
    oc.fill();
  }
}

function paintPattern(oc, mask, fill, size) {
  oc.fillStyle = rgbToCss(fill.stops[0].rgb);
  oc.fillRect(mask.x, mask.y, mask.w, mask.h);
  const p = fill.pattern;
  const step = Math.max(2, p.step * size);
  oc.fillStyle = rgbToCss(p.rgb);
  oc.strokeStyle = rgbToCss(p.rgb);
  oc.lineWidth = Math.max(0.5, step * p.weight);
  if (p.kind === 'dots') {
    for (let x = mask.x; x < mask.x + mask.w; x += step) {
      for (let y = mask.y; y < mask.y + mask.h; y += step) {
        oc.beginPath();
        oc.arc(x, y, step * p.weight, 0, Math.PI * 2);
        oc.fill();
      }
    }
    return;
  }
  if (p.kind === 'checker') {
    let i = 0;
    for (let x = mask.x; x < mask.x + mask.w; x += step, i++) {
      let j = 0;
      for (let y = mask.y; y < mask.y + mask.h; y += step, j++) {
        if ((i + j) % 2 === 0) { oc.fillRect(x, y, step, step); }
      }
    }
    return;
  }
  oc.beginPath();
  if (p.kind === 'grid' || p.kind === 'crosshatch') {
    for (let x = mask.x; x < mask.x + mask.w; x += step) { oc.moveTo(x, mask.y); oc.lineTo(x, mask.y + mask.h); }
    for (let y = mask.y; y < mask.y + mask.h; y += step) { oc.moveTo(mask.x, y); oc.lineTo(mask.x + mask.w, y); }
  }
  if (p.kind === 'diagonal' || p.kind === 'crosshatch') {
    for (let x = mask.x - mask.h; x < mask.x + mask.w; x += step) {
      oc.moveTo(x, mask.y);
      oc.lineTo(x + mask.h, mask.y + mask.h);
    }
  }
  oc.stroke();
}

function paintImageFill(oc, mask, fill) {
  const src = fill.source;
  const sw = src.width;
  const sh = src.height;
  if (!(sw > 0) || !(sh > 0)) { return; }
  const scale = Math.max(mask.w / sw, mask.h / sh) * fill.image.zoom;
  const dw = sw * scale;
  const dh = sh * scale;
  oc.drawImage(src, mask.x + (mask.w - dw) / 2, mask.y + (mask.h - dh) / 2, dw, dh);
  oc.fillStyle = rgbToCss(fill.image.veil, fill.image.veilAlpha);
  oc.fillRect(mask.x, mask.y, mask.w, mask.h);
}

function paintKnockout(ctx, mask, regions, box, plate, size) {
  const e = scratchCtx(7, mask.pw, mask.ph);
  if (!e) { return false; }
  const oc = e.ctx;
  oc.save();
  oc.scale(mask.sx, mask.sy);
  oc.translate(-mask.x, -mask.y);
  paintPlates(oc, regions, box, plate, size, null);
  oc.restore();
  oc.globalCompositeOperation = 'destination-out';
  oc.drawImage(mask.cv, 0, 0, mask.pw, mask.ph, 0, 0, mask.pw, mask.ph);
  oc.globalCompositeOperation = 'source-over';
  blit(ctx, e.cv, mask, 0, 0);
  return true;
}

function paintReflection(ctx, mask, box, spec, size) {
  const e = scratchCtx(8, mask.pw, mask.ph);
  if (!e) { return; }
  const oc = e.ctx;
  oc.drawImage(mask.cv, 0, 0, mask.pw, mask.ph, 0, 0, mask.pw, mask.ph);
  oc.globalCompositeOperation = 'source-in';
  const g = oc.createLinearGradient(0, 0, 0, mask.ph);
  const rgb = spec.fill.stops[spec.fill.stops.length - 1].rgb;
  g.addColorStop(0, rgbToCss(rgb, 0));
  g.addColorStop(clamp01(1 - spec.reflection.fade), rgbToCss(rgb, 0));
  g.addColorStop(1, rgbToCss(rgb, spec.reflection.alpha));
  oc.fillStyle = g;
  oc.fillRect(0, 0, mask.pw, mask.ph);
  oc.globalCompositeOperation = 'source-over';
  const mirrorY = box.y + box.h + spec.reflection.gap * size;
  ctx.save();
  ctx.translate(0, mirrorY * 2);
  ctx.scale(1, -1);
  blit(ctx, e.cv, mask, 0, 0);
  ctx.restore();
}

function paintSplitCut(ctx, emitter, box, spec, size) {
  const cut = box.y + box.h * spec.splitCut.at;
  const shift = spec.splitCut.shift * size;
  const pad = size * 3;
  ctx.save();
  ctx.beginPath();
  ctx.rect(box.x - pad, box.y - pad, box.w + pad * 2, cut - box.y + pad);
  ctx.clip();
  ctx.translate(-shift, 0);
  emitter(ctx, 'fill');
  ctx.restore();
  ctx.save();
  ctx.beginPath();
  ctx.rect(box.x - pad, cut, box.w + pad * 2, box.h + pad * 2);
  ctx.clip();
  ctx.translate(shift, 0);
  emitter(ctx, 'fill');
  ctx.restore();
}

function trimForGlyphCount(spec, glyphCount) {
  if (!(glyphCount > HEAVY_GLYPHS)) { return; }
  const allowed = Math.max(MIN_HEAVY_PASSES, Math.round(MAX_GLYPH_PASSES * HEAVY_GLYPHS / glyphCount));
  const drop = ['edgeSplit', 'misregister', 'reflection', 'innerLine', 'bevel', 'splitCut', 'torn', 'roughEdge'];
  for (let i = 0; i < drop.length && passCost(spec) > allowed; i++) {
    if (spec[drop[i]]) { spec[drop[i]] = null; }
  }
  if (passCost(spec) > allowed && spec.glow && spec.glow.passes > 1) { spec.glow.passes = 1; }
  while (passCost(spec) > allowed && spec.strokes.length > 1) { spec.strokes.pop(); }
  if (passCost(spec) > allowed && spec.glow) { spec.glow = null; }
}

export function paintDecorated(ctx, emitter, box, spec, size) {
  if (!spec || !(size > 0)) { return; }
  const regions = emitter && emitter.regions ? emitter.regions : null;
  trimForGlyphCount(spec, emitter && emitter.glyphs ? emitter.glyphs.length : 0);
  ctx.save();
  applyTransform(ctx, box, spec.transform);
  clearShadow(ctx);

  const mask = usesMask(spec) ? buildMask(ctx, emitter, box, size * MASK_PAD_EM) : null;
  const maskScale = mask ? mask.sx : 1;

  if (spec.plate && spec.plate.knockout) {
    if (!mask || !paintKnockout(ctx, mask, regions, box, spec.plate, size)) {
      paintPlates(ctx, regions, box, spec.plate, size, spec.transform);
      ctx.fillStyle = makeFillStyle(ctx, box, spec.fill);
      emitter(ctx, 'fill');
    }
    if (spec.underline) { paintRule(ctx, box, spec.underline, size, false, !!spec.vertical); }
    if (spec.overline) { paintRule(ctx, box, spec.overline, size, true, !!spec.vertical); }
    ctx.restore();
    return;
  }

  if (spec.plate) { paintPlates(ctx, regions, box, spec.plate, size, spec.transform); }

  if (spec.longShadow && mask) {
    paintRamp(ctx, mask, spec.longShadow.rgb, spec.longShadow.rgb, spec.longShadow.steps,
      spec.longShadow.dx, spec.longShadow.dy, size, spec.longShadow.alpha);
  }
  if (spec.extrude && mask) {
    paintRamp(ctx, mask, spec.extrude.near, spec.extrude.far, spec.extrude.steps,
      spec.extrude.dx, spec.extrude.dy, size, 1);
  }

  if (spec.glow) {
    ctx.fillStyle = rgbToCss(spec.glow.rgb, 1);
    ctx.shadowColor = rgbToCss(spec.glow.rgb, spec.glow.alpha);
    ctx.shadowBlur = Math.min(spec.glow.blur * size, MAX_BLUR_PX);
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

  if (spec.misregister && mask) { paintOffsetLayers(ctx, mask, spec.misregister.layers, size); }
  if (spec.edgeSplit && mask) {
    paintOffsetLayers(ctx, mask, [
      { rgb: spec.edgeSplit.a, dx: -spec.edgeSplit.dx, dy: -spec.edgeSplit.dy, alpha: spec.edgeSplit.alpha },
      { rgb: spec.edgeSplit.b, dx: spec.edgeSplit.dx, dy: spec.edgeSplit.dy, alpha: spec.edgeSplit.alpha }
    ], size);
  }

  if (shadowPending) { applyShadow(ctx, spec.dropShadow, size); shadowPending = false; }

  const type = spec.fill.type;
  if (type === 'none') {
    clearShadow(ctx);
  } else if (layerFillActive(spec) && mask) {
    const layer = maskedLayer(mask, function (oc) {
      if (type === 'stripe') { paintStripes(oc, mask, spec.fill, size); }
      else if (type === 'pattern') { paintPattern(oc, mask, spec.fill, size); }
      else if (type === 'image' && spec.fill.source) { paintImageFill(oc, mask, spec.fill); }
      else {
        oc.fillStyle = makeFillStyle(oc, box, spec.fill);
        oc.fillRect(mask.x, mask.y, mask.w, mask.h);
      }
    }, 6);
    if (layer) {
      if (spec.roughEdge) { eraseNoise(layer.ctx, mask.pw, mask.ph, spec.roughEdge, size, maskScale); }
      if (spec.torn) { eraseTorn(layer.ctx, mask.pw, mask.ph, spec.torn, size, maskScale); }
      blit(ctx, layer.cv, mask, 0, 0);
    }
    clearShadow(ctx);
  } else if (spec.splitCut) {
    ctx.fillStyle = makeFillStyle(ctx, box, spec.fill);
    paintSplitCut(ctx, emitter, box, spec, size);
    clearShadow(ctx);
  } else {
    ctx.fillStyle = makeFillStyle(ctx, box, spec.fill);
    emitter(ctx, 'fill');
    clearShadow(ctx);
  }

  if (spec.innerLine) {
    ctx.lineWidth = spec.innerLine.width * size;
    ctx.strokeStyle = rgbToCss(spec.innerLine.rgb, spec.innerLine.alpha);
    emitter(ctx, 'stroke');
  }

  if (spec.reflection && mask) { paintReflection(ctx, mask, box, spec, size); }

  if (spec.underline) { paintRule(ctx, box, spec.underline, size, false, !!spec.vertical); }
  if (spec.overline) { paintRule(ctx, box, spec.overline, size, true, !!spec.vertical); }

  if (spec.boten) {
    ctx.fillStyle = rgbToCss(spec.boten.rgb, spec.boten.alpha);
    emitter(ctx, 'boten');
  }

  ctx.restore();
}
