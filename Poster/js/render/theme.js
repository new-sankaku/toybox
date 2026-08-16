(function (PF) {
'use strict';
const { hexToRgb, rgbToHsl, hslToRgb, clamp255 } = PF;

const GENRE_COLORS = {
  cinema: {
    obi: ['#0d0c0a', '#15120e', '#12333a', '#241d14'],
    ribbon: ['#a8291f', '#0d0c0a', '#d8c27a', '#1c4d55', '#c46a2a'],
    plate: ['#0d0c0a', '#f2ece0', '#12333a', '#221c15'],
    accent: ['#d8c27a', '#c9a227', '#2f7d8a', '#c46a2a', '#e8e2d4'],
    ink: ['#f2ece0', '#ffffff', '#0d0c0a', '#d8c27a', '#b8b4ad']
  },
  gravure: {
    obi: ['#ffffff', '#fdf6ee', '#eaf7fb', '#ffeef4', '#f6f1e2'],
    ribbon: ['#ff6f8f', '#ffab2e', '#4fc7d8', '#ff8a4d', '#ffd25e'],
    plate: ['#ffffff', '#fff4f8', '#f2fbfe', '#fbf6ea'],
    accent: ['#ff8fae', '#ffd25e', '#6fd3e4', '#ffb08a', '#a9e4f2'],
    ink: ['#2a2622', '#ffffff', '#c2385c', '#1d5560']
  },
  novel: {
    obi: ['#9b1b1b', '#1d3557', '#f5efe2', '#111111', '#c8a24a', '#2f4f3a'],
    ribbon: ['#9b1b1b', '#111111', '#1d3557'],
    plate: ['#f5efe2', '#111111', '#1d3557', '#ffffff', '#e6ddc8'],
    accent: ['#9b1b1b', '#c8a24a', '#1d3557', '#6b5b3e'],
    ink: ['#111111', '#f5efe2', '#9b1b1b', '#1d3557']
  },
  asmr: {
    obi: ['#c9b8e8', '#f6c8d8', '#bcdcf2', '#efe7f7', '#d9ecdf'],
    ribbon: ['#b39ddb', '#f4a7c0', '#8ecae6', '#ffffff'],
    plate: ['#fbf7ff', '#ffffff', '#f2eaf8', '#eaf4fb'],
    accent: ['#b39ddb', '#f6a5c0', '#8ecae6', '#d7c4ef', '#a8d8c8'],
    ink: ['#3a3350', '#ffffff', '#5b4b7a', '#2f4858']
  },
  game: {
    obi: ['#0f2b52', '#122f66', '#16181c', '#8c1520'],
    ribbon: ['#1f4fa8', '#c0392b', '#c8a227', '#0f1418', '#2c6fd1'],
    plate: ['#0f1c30', '#e8edf4', '#16181c', '#1d3a68'],
    accent: ['#3d8bfd', '#c8cdd6', '#c8a227', '#e03b2f', '#7ad1ff'],
    ink: ['#e8edf4', '#ffffff', '#0f1418', '#c8a227']
  },
  adult: {
    obi: ['#ff2d8a', '#ffe600', '#0a0a0a', '#ff5ac8', '#12b0ff'],
    ribbon: ['#ff2d8a', '#ffe600', '#0a0a0a', '#ff6a00'],
    plate: ['#0a0a0a', '#ffffff', '#1a0a14', '#ffe600'],
    accent: ['#ff2d8a', '#ffe600', '#ff6a00', '#12b0ff', '#ff5ac8'],
    ink: ['#ffffff', '#0a0a0a', '#ffe600', '#ff2d8a']
  }
};

function toHex(rgb) {
  const r = Math.round(clamp255(rgb[0]));
  const g = Math.round(clamp255(rgb[1]));
  const b = Math.round(clamp255(rgb[2]));
  return '#' + ((1 << 24) | (r << 16) | (g << 8) | b).toString(16).slice(1);
}

function jitter(hex, rng, hueAmt, litAmt) {
  const hsl = rgbToHsl(hexToRgb(hex));
  let h = hsl[0] + rng.range(-hueAmt, hueAmt);
  if (h < 0) { h += 1; }
  if (h >= 1) { h -= 1; }
  const s = Math.min(1, Math.max(0, hsl[1] * rng.range(0.88, 1.14)));
  const l = Math.min(1, Math.max(0, hsl[2] + rng.range(-litAmt, litAmt)));
  return toHex(hslToRgb([h, s, l]));
}

function polarize(hex, rng) {
  const hsl = rgbToHsl(hexToRgb(hex));
  const toDark = hsl[2] <= 0.52;
  if (toDark) {
    const l = Math.min(0.32, 0.06 + hsl[2] * 0.42 + rng.range(0, 0.05));
    const sat = Math.min(hsl[1], 0.72);
    return toHex(hslToRgb([hsl[0], sat, l]));
  }
  const l = Math.max(0.88, Math.min(0.985, 0.86 + hsl[2] * 0.10 + rng.range(0, 0.04)));
  const sat = Math.min(hsl[1], 0.30);
  return toHex(hslToRgb([hsl[0], sat, l]));
}

function polarized(list, rng) {
  const out = [];
  for (let i = 0; i < list.length; i++) { out.push(polarize(list[i], rng)); }
  return out;
}

function variant(list, rng, hueAmt, litAmt) {
  const shuffled = rng.shuffle(list);
  const out = [];
  for (let i = 0; i < shuffled.length; i++) {
    out.push(jitter(shuffled[i], rng, hueAmt, litAmt));
  }
  return out;
}

function planHex(role) {
  const rgb = role && role.rgb ? role.rgb : null;
  if (!rgb) { return null; }
  return toHex(rgb);
}

function planColors(colorPlan, names, rng, hueAmt, litAmt) {
  const out = [];
  for (let i = 0; i < names.length; i++) {
    const hex = planHex(colorPlan.roles[names[i]]);
    if (hex) { out.push(jitter(hex, rng, hueAmt, litAmt)); }
  }
  return out;
}

function buildTheme(rng, genre, colorPlan) {
  const src = GENRE_COLORS[genre];
  const theme = {
    obiColors: polarized(variant(src.obi, rng, 0.018, 0.030), rng),
    ribbonColors: variant(src.ribbon, rng, 0.022, 0.034),
    plateColors: polarized(variant(src.plate, rng, 0.012, 0.022), rng),
    accentColors: variant(src.accent, rng, 0.026, 0.038),
    inkColors: variant(src.ink, rng, 0.008, 0.016)
  };
  if (!colorPlan || !colorPlan.roles) { return theme; }
  const obi = planColors(colorPlan, ['surface', 'surfaceAlt', 'accent'], rng, 0.014, 0.024);
  const ribbon = planColors(colorPlan, ['accent', 'surface', 'inkAlt'], rng, 0.018, 0.028);
  const plate = planColors(colorPlan, ['plate', 'surfaceAlt', 'surface'], rng, 0.010, 0.018);
  const accent = planColors(colorPlan, ['accent', 'glow', 'inkAlt'], rng, 0.020, 0.030);
  const ink = planColors(colorPlan, ['ink', 'inkAlt', 'stroke'], rng, 0.006, 0.012);
  if (obi.length) { theme.obiColors = polarized(obi, rng); }
  if (ribbon.length) { theme.ribbonColors = ribbon; }
  if (plate.length) { theme.plateColors = polarized(plate, rng); }
  if (accent.length) { theme.accentColors = accent; }
  if (ink.length) { theme.inkColors = ink; }
  return theme;
}

Object.assign(PF, { buildTheme });
})(window.PF = window.PF || {});
