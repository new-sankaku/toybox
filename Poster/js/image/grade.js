const LOOK_WEIGHTS = [
  { v: 'teal-orange', w: 14 },
  { v: 'bleach-bypass', w: 9 },
  { v: 'cross-process', w: 8 },
  { v: 'cold-night', w: 10 },
  { v: 'golden-hour', w: 11 },
  { v: 'faded-film', w: 12 },
  { v: 'high-key-pastel', w: 8 },
  { v: 'cyanotype', w: 6 },
  { v: 'duotone', w: 7 },
  { v: 'neon-night', w: 7 },
  { v: 'warm-portrait', w: 12 },
  { v: 'silver-halide', w: 9 }
];

const GENRE_BIAS = {
  cinema: { 'teal-orange': 1.5, 'bleach-bypass': 1.35, 'cold-night': 1.25, 'silver-halide': 1.15 },
  gravure: { 'golden-hour': 1.45, 'high-key-pastel': 1.4, 'warm-portrait': 1.5, 'cyanotype': 0.7 },
  novel: { 'faded-film': 1.45, 'silver-halide': 1.4, 'cyanotype': 1.25, 'neon-night': 0.7 },
  asmr: { 'high-key-pastel': 1.45, 'cold-night': 1.25, 'duotone': 1.2, 'bleach-bypass': 0.8 },
  game: { 'neon-night': 1.55, 'cross-process': 1.3, 'teal-orange': 1.25, 'faded-film': 0.75 },
  adult: { 'neon-night': 1.3, 'warm-portrait': 1.3, 'cross-process': 1.2, 'high-key-pastel': 0.8 }
};

const DUOTONE_PAIRS = [
  [[16, 12, 40], [255, 198, 88]],
  [[10, 20, 42], [238, 238, 232]],
  [[30, 8, 32], [255, 122, 152]],
  [[8, 28, 32], [176, 255, 220]],
  [[28, 10, 10], [255, 182, 120]],
  [[12, 14, 16], [118, 200, 255]],
  [[38, 22, 6], [250, 236, 200]],
  [[6, 16, 26], [255, 96, 72]]
];

function baseSpec() {
  return {
    look: 'neutral',
    strength: 1,
    lift: [0, 0, 0],
    gamma: [1, 1, 1],
    gain: [1, 1, 1],
    contrast: 1,
    saturation: 1,
    shadowTint: [0, 0, 0],
    shadowAmount: 0,
    shadowExp: 2,
    highlightTint: [255, 255, 255],
    highlightAmount: 0,
    highlightExp: 2,
    duotone: null
  };
}

const LOOKS = {
  'teal-orange': function (rng) {
    return {
      lift: [0, rng.range(0, 0.012), rng.range(0.014, 0.038)],
      gamma: [rng.range(1.0, 1.06), 1, rng.range(0.93, 0.99)],
      gain: [rng.range(1.0, 1.05), 1, rng.range(0.95, 1.0)],
      contrast: rng.range(1.14, 1.36),
      saturation: rng.range(1.04, 1.24),
      shadowTint: [rng.range(16, 42), rng.range(70, 108), rng.range(96, 134)],
      shadowAmount: rng.range(0.22, 0.40),
      shadowExp: rng.range(1.6, 2.6),
      highlightTint: [rng.range(238, 255), rng.range(156, 192), rng.range(92, 132)],
      highlightAmount: rng.range(0.18, 0.34),
      highlightExp: rng.range(1.6, 2.6)
    };
  },
  'bleach-bypass': function (rng) {
    return {
      lift: [rng.range(0.01, 0.04), rng.range(0.01, 0.04), rng.range(0.02, 0.05)],
      gamma: [rng.range(0.9, 0.98), rng.range(0.9, 0.98), rng.range(0.9, 0.98)],
      gain: [rng.range(1.02, 1.1), rng.range(1.02, 1.1), rng.range(1.02, 1.1)],
      contrast: rng.range(1.38, 1.72),
      saturation: rng.range(0.30, 0.55),
      shadowTint: [rng.range(28, 52), rng.range(34, 58), rng.range(44, 70)],
      shadowAmount: rng.range(0.14, 0.26),
      shadowExp: rng.range(2.0, 3.2),
      highlightTint: [rng.range(244, 255), rng.range(244, 255), rng.range(238, 252)],
      highlightAmount: rng.range(0.16, 0.30),
      highlightExp: rng.range(1.8, 2.8)
    };
  },
  'cross-process': function (rng) {
    return {
      lift: [rng.range(-0.02, 0.01), rng.range(0, 0.02), rng.range(0.04, 0.10)],
      gamma: [rng.range(1.08, 1.24), rng.range(0.96, 1.04), rng.range(0.78, 0.9)],
      gain: [rng.range(1.02, 1.12), rng.range(0.98, 1.04), rng.range(0.88, 0.98)],
      contrast: rng.range(1.22, 1.5),
      saturation: rng.range(1.15, 1.45),
      shadowTint: [rng.range(20, 50), rng.range(58, 92), rng.range(70, 110)],
      shadowAmount: rng.range(0.16, 0.32),
      shadowExp: rng.range(1.4, 2.4),
      highlightTint: [rng.range(230, 255), rng.range(220, 250), rng.range(120, 175)],
      highlightAmount: rng.range(0.18, 0.36),
      highlightExp: rng.range(1.4, 2.4)
    };
  },
  'cold-night': function (rng) {
    return {
      lift: [0, rng.range(0.005, 0.02), rng.range(0.02, 0.055)],
      gamma: [rng.range(0.86, 0.94), rng.range(0.9, 0.97), rng.range(1.0, 1.1)],
      gain: [rng.range(0.86, 0.95), rng.range(0.92, 0.99), rng.range(1.0, 1.08)],
      contrast: rng.range(1.16, 1.42),
      saturation: rng.range(0.62, 0.86),
      shadowTint: [rng.range(10, 30), rng.range(28, 56), rng.range(66, 104)],
      shadowAmount: rng.range(0.28, 0.46),
      shadowExp: rng.range(1.3, 2.2),
      highlightTint: [rng.range(180, 220), rng.range(208, 236), rng.range(238, 255)],
      highlightAmount: rng.range(0.16, 0.30),
      highlightExp: rng.range(2.0, 3.0)
    };
  },
  'golden-hour': function (rng) {
    return {
      lift: [rng.range(0.01, 0.035), rng.range(0, 0.018), 0],
      gamma: [rng.range(1.02, 1.12), rng.range(0.99, 1.05), rng.range(0.88, 0.96)],
      gain: [rng.range(1.03, 1.12), rng.range(0.99, 1.05), rng.range(0.86, 0.95)],
      contrast: rng.range(1.06, 1.24),
      saturation: rng.range(1.06, 1.28),
      shadowTint: [rng.range(52, 84), rng.range(38, 62), rng.range(46, 76)],
      shadowAmount: rng.range(0.16, 0.28),
      shadowExp: rng.range(1.8, 2.8),
      highlightTint: [rng.range(250, 255), rng.range(192, 220), rng.range(112, 156)],
      highlightAmount: rng.range(0.26, 0.44),
      highlightExp: rng.range(1.3, 2.1)
    };
  },
  'faded-film': function (rng) {
    return {
      lift: [rng.range(0.07, 0.14), rng.range(0.07, 0.14), rng.range(0.06, 0.13)],
      gamma: [rng.range(1.0, 1.1), rng.range(1.0, 1.1), rng.range(0.98, 1.08)],
      gain: [rng.range(0.86, 0.95), rng.range(0.87, 0.96), rng.range(0.86, 0.95)],
      contrast: rng.range(0.78, 0.94),
      saturation: rng.range(0.66, 0.88),
      shadowTint: [rng.range(52, 80), rng.range(58, 88), rng.range(48, 76)],
      shadowAmount: rng.range(0.24, 0.40),
      shadowExp: rng.range(1.2, 2.0),
      highlightTint: [rng.range(240, 255), rng.range(232, 248), rng.range(206, 232)],
      highlightAmount: rng.range(0.14, 0.26),
      highlightExp: rng.range(1.6, 2.6)
    };
  },
  'high-key-pastel': function (rng) {
    return {
      lift: [rng.range(0.08, 0.16), rng.range(0.08, 0.16), rng.range(0.09, 0.17)],
      gamma: [rng.range(1.16, 1.4), rng.range(1.16, 1.4), rng.range(1.16, 1.4)],
      gain: [rng.range(0.98, 1.04), rng.range(0.98, 1.04), rng.range(0.98, 1.04)],
      contrast: rng.range(0.72, 0.9),
      saturation: rng.range(0.74, 0.96),
      shadowTint: [rng.range(120, 160), rng.range(112, 150), rng.range(140, 180)],
      shadowAmount: rng.range(0.20, 0.36),
      shadowExp: rng.range(1.1, 1.8),
      highlightTint: [rng.range(252, 255), rng.range(236, 250), rng.range(238, 252)],
      highlightAmount: rng.range(0.18, 0.32),
      highlightExp: rng.range(1.4, 2.2)
    };
  },
  'cyanotype': function (rng) {
    return {
      lift: [0, rng.range(0.01, 0.03), rng.range(0.03, 0.07)],
      gamma: [rng.range(0.94, 1.04), rng.range(0.96, 1.06), rng.range(1.0, 1.1)],
      gain: [rng.range(0.9, 1.0), rng.range(0.95, 1.02), rng.range(1.0, 1.06)],
      contrast: rng.range(1.12, 1.36),
      saturation: rng.range(0.02, 0.12),
      shadowTint: [rng.range(6, 22), rng.range(24, 46), rng.range(62, 96)],
      shadowAmount: rng.range(0.52, 0.76),
      shadowExp: rng.range(1.0, 1.7),
      highlightTint: [rng.range(178, 208), rng.range(214, 238), rng.range(238, 255)],
      highlightAmount: rng.range(0.44, 0.68),
      highlightExp: rng.range(1.0, 1.7)
    };
  },
  'duotone': function (rng) {
    const pair = rng.pick(DUOTONE_PAIRS);
    const dark = pair[0].slice();
    const light = pair[1].slice();
    if (rng.chance(0.35)) {
      for (let i = 0; i < 3; i++) {
        dark[i] = Math.max(0, Math.min(255, dark[i] + rng.range(-14, 14)));
        light[i] = Math.max(0, Math.min(255, light[i] + rng.range(-16, 16)));
      }
    }
    return {
      lift: [0, 0, 0],
      gamma: [rng.range(0.92, 1.12), rng.range(0.92, 1.12), rng.range(0.92, 1.12)],
      gain: [1, 1, 1],
      contrast: rng.range(1.06, 1.34),
      saturation: 1,
      shadowAmount: 0,
      highlightAmount: 0,
      duotone: { dark: dark, light: light, amount: rng.range(0.82, 1.0) }
    };
  },
  'neon-night': function (rng) {
    return {
      lift: [rng.range(0, 0.03), 0, rng.range(0.02, 0.06)],
      gamma: [rng.range(0.86, 0.96), rng.range(0.86, 0.96), rng.range(0.94, 1.06)],
      gain: [rng.range(0.96, 1.06), rng.range(0.9, 1.0), rng.range(1.0, 1.1)],
      contrast: rng.range(1.32, 1.62),
      saturation: rng.range(1.3, 1.7),
      shadowTint: [rng.range(30, 62), rng.range(6, 26), rng.range(60, 104)],
      shadowAmount: rng.range(0.30, 0.50),
      shadowExp: rng.range(1.2, 2.0),
      highlightTint: [rng.range(60, 110), rng.range(206, 240), rng.range(238, 255)],
      highlightAmount: rng.range(0.22, 0.40),
      highlightExp: rng.range(1.6, 2.6)
    };
  },
  'warm-portrait': function (rng) {
    return {
      lift: [rng.range(0.005, 0.025), rng.range(0, 0.015), rng.range(0, 0.012)],
      gamma: [rng.range(1.0, 1.08), rng.range(1.0, 1.06), rng.range(0.96, 1.02)],
      gain: [rng.range(1.0, 1.06), rng.range(0.99, 1.03), rng.range(0.94, 1.0)],
      contrast: rng.range(1.04, 1.2),
      saturation: rng.range(0.96, 1.14),
      shadowTint: [rng.range(56, 86), rng.range(42, 66), rng.range(38, 62)],
      shadowAmount: rng.range(0.14, 0.26),
      shadowExp: rng.range(1.8, 2.8),
      highlightTint: [rng.range(250, 255), rng.range(220, 240), rng.range(196, 222)],
      highlightAmount: rng.range(0.16, 0.30),
      highlightExp: rng.range(1.6, 2.6)
    };
  },
  'silver-halide': function (rng) {
    const warm = rng.chance(0.5);
    return {
      lift: [rng.range(0, 0.03), rng.range(0, 0.03), rng.range(0, 0.03)],
      gamma: [rng.range(0.94, 1.04), rng.range(0.94, 1.04), rng.range(0.94, 1.04)],
      gain: [rng.range(0.98, 1.04), rng.range(0.98, 1.04), rng.range(0.98, 1.04)],
      contrast: rng.range(1.24, 1.52),
      saturation: rng.range(0.04, 0.16),
      shadowTint: warm
        ? [rng.range(46, 68), rng.range(38, 56), rng.range(30, 48)]
        : [rng.range(28, 46), rng.range(34, 52), rng.range(48, 72)],
      shadowAmount: rng.range(0.18, 0.34),
      shadowExp: rng.range(1.4, 2.4),
      highlightTint: warm
        ? [rng.range(250, 255), rng.range(240, 252), rng.range(216, 238)]
        : [rng.range(232, 246), rng.range(240, 252), rng.range(250, 255)],
      highlightAmount: rng.range(0.16, 0.30),
      highlightExp: rng.range(1.6, 2.6)
    };
  }
};

export function buildGradeSpec(rng, genre, intensity) {
  const k = Math.max(0, Math.min(1, intensity));
  const bias = GENRE_BIAS[genre] || null;
  const items = [];
  for (let i = 0; i < LOOK_WEIGHTS.length; i++) {
    const name = LOOK_WEIGHTS[i].v;
    const mul = bias && bias[name] ? bias[name] : 1;
    items.push({ v: name, w: LOOK_WEIGHTS[i].w * mul });
  }
  const look = rng.weighted(items);
  const spec = baseSpec();
  const part = LOOKS[look](rng);
  for (const key in part) { spec[key] = part[key]; }
  spec.look = look;
  spec.strength = 0.34 + 0.66 * k;
  return spec;
}

function scurve(v, s) {
  if (s === 1) { return v; }
  const x = v < 0 ? 0 : (v > 1 ? 1 : v);
  return x < 0.5 ? 0.5 * Math.pow(2 * x, s) : 1 - 0.5 * Math.pow(2 * (1 - x), s);
}

function buildToneLut(lift, gamma, gain, contrast, strength) {
  const lut = new Uint8ClampedArray(256);
  const invG = 1 / gamma;
  for (let i = 0; i < 256; i++) {
    const x = i / 255;
    let v = Math.pow(x, invG);
    v = lift + (gain - lift) * v;
    v = scurve(v, contrast);
    lut[i] = (x + (v - x) * strength) * 255;
  }
  return lut;
}

export function applyGrade(ctx, w, h, spec) {
  if (!spec || w <= 0 || h <= 0) { return; }
  const strength = Math.max(0, Math.min(1, spec.strength === undefined ? 1 : spec.strength));
  if (strength <= 0.002) { return; }

  const contrast = 1 + (spec.contrast - 1) * strength;
  const lutR = buildToneLut(spec.lift[0], spec.gamma[0], spec.gain[0], contrast, strength);
  const lutG = buildToneLut(spec.lift[1], spec.gamma[1], spec.gain[1], contrast, strength);
  const lutB = buildToneLut(spec.lift[2], spec.gamma[2], spec.gain[2], contrast, strength);

  const duo = spec.duotone;
  const duoAmt = duo ? Math.max(0, Math.min(1, duo.amount * strength)) : 0;
  const duoR = new Float32Array(256);
  const duoG = new Float32Array(256);
  const duoB = new Float32Array(256);
  if (duoAmt > 0) {
    for (let i = 0; i < 256; i++) {
      const t = i / 255;
      duoR[i] = duo.dark[0] + (duo.light[0] - duo.dark[0]) * t;
      duoG[i] = duo.dark[1] + (duo.light[1] - duo.dark[1]) * t;
      duoB[i] = duo.dark[2] + (duo.light[2] - duo.dark[2]) * t;
    }
  }

  const sAmt = (spec.shadowAmount || 0) * strength;
  const hAmt = (spec.highlightAmount || 0) * strength;
  const wsTab = new Float32Array(256);
  const whTab = new Float32Array(256);
  if (sAmt > 0 || hAmt > 0) {
    for (let i = 0; i < 256; i++) {
      const t = i / 255;
      wsTab[i] = sAmt > 0 ? sAmt * Math.pow(1 - t, spec.shadowExp) : 0;
      whTab[i] = hAmt > 0 ? hAmt * Math.pow(t, spec.highlightExp) : 0;
    }
  }
  const useTint = sAmt > 0 || hAmt > 0;
  const sr = spec.shadowTint[0], sg = spec.shadowTint[1], sb = spec.shadowTint[2];
  const hr = spec.highlightTint[0], hg = spec.highlightTint[1], hb = spec.highlightTint[2];

  const sat = 1 + (spec.saturation - 1) * strength;
  const useSat = Math.abs(sat - 1) > 0.004;

  const img = ctx.getImageData(0, 0, w, h);
  const d = img.data;
  const len = d.length;
  for (let i = 0; i < len; i += 4) {
    let r = lutR[d[i]];
    let g = lutG[d[i + 1]];
    let b = lutB[d[i + 2]];
    const li = (r * 77 + g * 150 + b * 29) >> 8;
    if (duoAmt > 0) {
      r += (duoR[li] - r) * duoAmt;
      g += (duoG[li] - g) * duoAmt;
      b += (duoB[li] - b) * duoAmt;
    }
    if (useTint) {
      const ws = wsTab[li];
      if (ws > 0) {
        r += (sr - r) * ws;
        g += (sg - g) * ws;
        b += (sb - b) * ws;
      }
      const wh = whTab[li];
      if (wh > 0) {
        r += (hr - r) * wh;
        g += (hg - g) * wh;
        b += (hb - b) * wh;
      }
    }
    if (useSat) {
      const lum = r * 0.299 + g * 0.587 + b * 0.114;
      r = lum + (r - lum) * sat;
      g = lum + (g - lum) * sat;
      b = lum + (b - lum) * sat;
    }
    d[i] = r;
    d[i + 1] = g;
    d[i + 2] = b;
  }
  ctx.putImageData(img, 0, 0);
}
