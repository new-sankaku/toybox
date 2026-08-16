(function (PF) {
'use strict';
const { ANCHOR_BASE } = PF;

const ALL_ROLES = ['title', 'catch', 'name', 'tag', 'badge', 'extra', 'credit', 'release', 'code'];

const GENRE_SPEC = {
  cinema: {
    hero: 'title',
    aspects: [{ v: 0.707, w: 3 }, { v: 0.675, w: 3 }, { v: 0.643, w: 1.2 }, { v: 0.727, w: 1.2 }, { v: 0.750, w: 1 }],
    heroModes: [
      { v: 'hBottom', w: 3 }, { v: 'hTop', w: 2.2 }, { v: 'hCenter', w: 1.6 },
      { v: 'vRight', w: 1.8 }, { v: 'vLeft', w: 1.1 }, { v: 'hLeft', w: 0.9 }
    ],
    margin: [0.045, 0.085],
    roles: {
      title: { sizeH: 0.118, sizeV: 0.092, trackH: 0.045, trackV: 0.13, maxLines: 2, big: true, decor: 'title' },
      catch: { size: 0.036, track: 0.07, maxLines: 2, decor: 'plain', satW: [0.56, 0.82], vertChance: 0.18 },
      name: { size: 0.026, track: 0.15, maxLines: 2, decor: 'plain', satW: [0.52, 0.80] },
      tag: { size: 0.021, track: 0.28, maxLines: 1, latin: true, decor: 'plain', satW: [0.38, 0.66] },
      extra: { size: 0.023, track: 0.26, maxLines: 1, latin: true, decor: 'plain', satW: [0.40, 0.68] },
      badge: { size: 0.017, track: 0.05, maxLines: 3, decor: 'plain' },
      release: { size: 0.029, track: 0.10, maxLines: 1, decor: 'plain', wFlex: 2.4 },
      credit: { size: 0.015, track: 0.01, maxLines: 5, decor: 'plain', wFlex: 5 }
    },
    foot: {
      surface: 'filmScrim', anchor: 'filmScrim', hRange: [0.19, 0.34],
      sub: { surface: 'billingPlate', anchor: 'billingPlate', hFrac: [0.28, 0.48] },
      items: [{ role: 'release', own: true, hFlex: 1.5, bias: 0.3 }, { role: 'credit', sub: true }],
      pad: { x: 0.06, t: 0.30, b: 0.06, gap: 0.10 }
    },
    head: {
      chance: 0.34, surface: 'topGradient', hRange: [0.055, 0.115],
      items: [{ role: 'tag' }], pad: { x: 0.06, t: 0.20, b: 0.20, gap: 0.10 }
    },
    floaters: {
      badge: {
        surface: 'laurelBadge', anchor: 'laurelBadge', chance: 0.62,
        w: [0.26, 0.40], ratio: [0.26, 0.34], inset: { x: 0.14, y: 0.13, w: 0.72, h: 0.74 },
        zones: [{ v: 'topLeft', w: 3 }, { v: 'topRight', w: 2.2 }, { v: 'topCenter', w: 1 }, { v: 'midLeft', w: 0.6 }]
      }
    },
    extras: [{ v: 'letterbox', w: 1.2 }, { v: 'sideBand', w: 1.2 }, { v: 'topGradient', w: 1.6 },
      { v: 'bottomGradient', w: 1.1 }, { v: 'circleMark', w: 0.5 }],
    extraCount: [0, 2],
    overlays: [{ v: 'grain', w: 4 }, { v: 'vignette', w: 3 }, { v: 'halation', w: 2.4 },
      { v: 'dust', w: 1.6 }, { v: 'softFocus', w: 1.4 }, { v: 'scanline', w: 0.8 }, { v: 'chromaEdge', w: 0.8 }],
    overlayCount: [1, 4]
  },

  gravure: {
    hero: 'name',
    titleVertChance: 0.16,
    aspects: [{ v: 0.708, w: 3 }, { v: 0.690, w: 1.6 }, { v: 0.750, w: 1.6 }, { v: 0.667, w: 1.4 }, { v: 0.780, w: 0.8 }],
    heroModes: [
      { v: 'hTop', w: 2.6 }, { v: 'hBottom', w: 2.6 }, { v: 'hLeft', w: 1.6 },
      { v: 'hRight', w: 1.1 }, { v: 'hCenter', w: 1.1 }, { v: 'vRight', w: 0.9 }, { v: 'vLeft', w: 0.7 }
    ],
    margin: [0.045, 0.090],
    roles: {
      name: { sizeH: 0.092, sizeV: 0.078, trackH: 0.08, trackV: 0.10, maxLines: 1, big: true, decor: 'title' },
      title: { size: 0.046, track: 0.10, maxLines: 2, decor: 'plain', satW: [0.52, 0.80], vertChance: 0.16 },
      catch: { size: 0.025, track: 0.04, maxLines: 2, decor: 'plain', satW: [0.48, 0.74] },
      tag: { size: 0.018, track: 0.12, maxLines: 1, latin: true, decor: 'plain', satW: [0.36, 0.62] },
      credit: { size: 0.018, track: 0.06, maxLines: 1, decor: 'plain', satW: [0.38, 0.66] },
      badge: { size: 0.022, track: 0.03, maxLines: 2, decor: 'accent' },
      extra: { size: 0.019, track: 0.03, maxLines: 1, decor: 'plain', wFlex: 4 },
      code: { size: 0.017, track: 0.12, maxLines: 1, latin: true, decor: 'plain', wFlex: 2 },
      release: { size: 0.017, track: 0.04, maxLines: 1, decor: 'plain', wFlex: 1.6 }
    },
    foot: {
      surface: 'specBand', anchor: 'specBand', hRange: [0.135, 0.235],
      items: [{ role: 'extra', own: true, bias: 0.2 }, { role: 'code', bias: 0.8 }, { role: 'release', bias: 0.8 }],
      pad: { x: 0.05, t: 0.14, b: 0.10, gap: 0.14 }
    },
    head: { chance: 0.18, surface: 'topGradient', hRange: [0.05, 0.09], items: [], pad: { x: 0.05, t: 0.2, b: 0.2, gap: 0.1 } },
    floaters: {
      badge: {
        surface: 'sealBadge', anchor: 'sealBadge', chance: 0.68,
        w: [0.20, 0.33], ratio: [1.30, 1.52], inset: { x: 0.10, y: 0.36, w: 0.80, h: 0.24 },
        zones: [{ v: 'midRight', w: 2.4 }, { v: 'midLeft', w: 1.6 }, { v: 'topRight', w: 1.4 },
          { v: 'topLeft', w: 1 }, { v: 'bottomRight', w: 1 }, { v: 'bottomLeft', w: 0.8 }]
      }
    },
    extras: [{ v: 'hairRules', w: 1.8 }, { v: 'gridPlate', w: 0.5 },
      { v: 'discSpine', w: 1.1 }, { v: 'sideBand', w: 0.9 }, { v: 'barcode', w: 1.1 },
      { v: 'topGradient', w: 1 }, { v: 'waveBand', w: 0.5 }],
    extraCount: [0, 3],
    overlays: [{ v: 'sparkle', w: 3 }, { v: 'bloom', w: 3 }, { v: 'grain', w: 2 },
      { v: 'lightLeak', w: 1.8 }, { v: 'bokehDots', w: 1.8 }, { v: 'softFocus', w: 1.6 }, { v: 'halation', w: 1.4 }],
    overlayCount: [1, 4]
  },

  novel: {
    hero: 'title',
    aspects: [{ v: 0.709, w: 3 }, { v: 0.695, w: 2 }, { v: 0.691, w: 2 }, { v: 0.660, w: 1.2 }, { v: 0.730, w: 1.2 }],
    heroModes: [
      { v: 'vRight', w: 3.4 }, { v: 'vLeft', w: 2.4 }, { v: 'vInner', w: 1.2 },
      { v: 'hTop', w: 1.6 }, { v: 'hCenter', w: 1.1 }
    ],
    margin: [0.050, 0.095],
    roles: {
      title: { sizeH: 0.090, sizeV: 0.086, trackH: 0.06, trackV: 0.11, maxLines: 2, big: true, decor: 'title' },
      name: { size: 0.031, track: 0.17, maxLines: 1, decor: 'plain', satW: [0.34, 0.60], vertChance: 0.80 },
      tag: { size: 0.019, track: 0.22, maxLines: 1, decor: 'plain', satW: [0.34, 0.62], wFlex: 2 },
      catch: { size: 0.046, track: 0.04, maxLines: 2, decor: 'plain', own: true, hFlex: 2.1, wFlex: 5 },
      extra: { size: 0.024, track: 0.02, maxLines: 2, decor: 'plain', hFlex: 1.3, wFlex: 5 },
      badge: { size: 0.026, track: 0.04, maxLines: 1, decor: 'plain', wFlex: 2.2 },
      release: { size: 0.017, track: 0.04, maxLines: 1, decor: 'plain', wFlex: 1.6 },
      credit: { size: 0.017, track: 0.02, maxLines: 1, decor: 'plain', wFlex: 1.6 }
    },
    foot: {
      surface: 'obi', anchor: 'obi', hRange: [0.245, 0.395], edgeSwap: 0.10,
      plateFor: 'badge', plateAnchor: 'obiBox',
      items: [{ role: 'catch', own: true, hFlex: 2.1, bias: 0.1 }, { role: 'extra', own: true, hFlex: 1.3, bias: 0.35 },
        { role: 'badge', bias: 0.8 }, { role: 'tag', bias: 0.8 }, { role: 'release', bias: 0.9 }, { role: 'credit', bias: 0.9 }],
      pad: { x: 0.045, t: 0.08, b: 0.06, gap: 0.09 }
    },
    head: { chance: 0.12, surface: 'topGradient', hRange: [0.05, 0.09], items: [], pad: { x: 0.05, t: 0.2, b: 0.2, gap: 0.1 } },
    floaters: {},
    extras: [{ v: 'frame', w: 2.6 }, { v: 'plate', w: 1.4 }, { v: 'topGradient', w: 1.2 },
      { v: 'sideBand', w: 0.9 }, { v: 'hairRules', w: 0.7 }, { v: 'circleMark', w: 0.5 }],
    extraCount: [0, 2],
    overlays: [{ v: 'paper', w: 4 }, { v: 'inkBleed', w: 3 }, { v: 'vignette', w: 2 },
      { v: 'dust', w: 1.6 }, { v: 'grain', w: 1.6 }, { v: 'softFocus', w: 0.8 }],
    overlayCount: [1, 4]
  },

  asmr: {
    hero: 'title',
    aspects: [{ v: 1.333, w: 3 }, { v: 1.500, w: 1.8 }, { v: 1.250, w: 1.6 }, { v: 1.778, w: 1.2 }, { v: 1.000, w: 0.8 }],
    heroModes: [
      { v: 'vRight', w: 3 }, { v: 'vLeft', w: 2.6 }, { v: 'vInner', w: 1.2 },
      { v: 'hTop', w: 1.8 }, { v: 'hRight', w: 1.4 }, { v: 'hLeft', w: 1.2 }, { v: 'hCenter', w: 1 }
    ],
    margin: [0.028, 0.060],
    outline: true,
    roles: {
      title: { sizeH: 0.125, sizeV: 0.176, trackH: 0.03, trackV: 0.04, maxLines: 3, big: true, decor: 'title', sizeTier: true, phraseWrap: true },
      catch: { size: 0.058, track: 0.05, maxLines: 2, decor: 'accent', satW: [0.42, 0.70], vertChance: 0.72, phraseWrap: true },
      extra: { size: 0.019, track: 0.31, maxLines: 1, latin: true, decor: 'plain', satW: [0.34, 0.62], vertChance: 0.42, phraseWrap: true },
      tag: { size: 0.027, track: 0.05, maxLines: 1, decor: 'accent', satW: [0.24, 0.42] },
      badge: { size: 0.029, track: 0.05, maxLines: 1, decor: 'accent', satW: [0.26, 0.44] },
      name: { size: 0.030, track: 0.06, maxLines: 1, decor: 'plain', satW: [0.26, 0.44] },
      credit: { size: 0.038, track: 0.04, maxLines: 1, decor: 'plain' }
    },
    foot: { chance: 0.22, surface: 'voiceChrome', anchor: 'voiceFootBand', hRange: [0.06, 0.11], items: [], pad: { x: 0.04, t: 0.2, b: 0.2, gap: 0.1 } },
    head: { chance: 0.0 },
    floaters: {
      credit: {
        surface: null, anchor: 'cvPlate', chance: 1,
        w: [0.21, 0.33], ratio: [0.26, 0.36], inset: { x: 0.06, y: 0.16, w: 0.88, h: 0.68 },
        pill: true,
        zones: [{ v: 'bottomRight', w: 3 }, { v: 'bottomLeft', w: 3 }, { v: 'topRight', w: 1 }, { v: 'topLeft', w: 1 }]
      },
      name: {
        surface: 'voiceLogoPlate', anchor: 'voiceLogoPlate', chance: 0.30,
        w: [0.15, 0.24], ratio: [0.36, 0.48], inset: { x: 0.06, y: 0.14, w: 0.88, h: 0.58 },
        zones: [{ v: 'topLeft', w: 3 }, { v: 'topRight', w: 2 }, { v: 'bottomLeft', w: 1 }]
      }
    },
    extras: [{ v: 'waveBand', w: 1.2 }, { v: 'circleMark', w: 0.8 }, { v: 'jacketFrame', w: 0.9 },
      { v: 'topGradient', w: 0.8 }, { v: 'sideBand', w: 0.7 }],
    extraCount: [0, 2],
    overlays: [{ v: 'bloom', w: 3 }, { v: 'bokehDots', w: 2.6 }, { v: 'sparkle', w: 2.6 },
      { v: 'halation', w: 2 }, { v: 'softFocus', w: 1.4 }, { v: 'lightLeak', w: 1.2 }, { v: 'grain', w: 0.8 }],
    overlayCount: [1, 4]
  },

  game: {
    hero: 'title',
    aspects: [{ v: 0.618, w: 2.6 }, { v: 0.794, w: 2.2 }, { v: 0.716, w: 2 }, { v: 0.788, w: 1.4 }, { v: 0.667, w: 1.4 }],
    heroModes: [
      { v: 'hBottom', w: 3 }, { v: 'hTop', w: 2.2 }, { v: 'hLeft', w: 1.8 },
      { v: 'hCenter', w: 1.4 }, { v: 'hRight', w: 1 }, { v: 'vRight', w: 0.9 }, { v: 'vLeft', w: 0.7 }
    ],
    margin: [0.050, 0.090],
    outline: true, inkOnly: true,
    roles: {
      title: { sizeH: 0.116, sizeV: 0.096, trackH: 0.012, trackV: 0.06, maxLines: 2, big: true, decor: 'title' },
      catch: { size: 0.025, track: 0.06, maxLines: 2, decor: 'plain', satW: [0.52, 0.82], vertChance: 0.24 },
      badge: { size: 0.019, track: 0.26, maxLines: 1, latin: true, decor: 'plain', satW: [0.44, 0.74] },
      tag: { size: 0.020, track: 0.16, maxLines: 1, decor: 'plain', satW: [0.34, 0.62] },
      name: { size: 0.022, track: 0.10, maxLines: 1, decor: 'plain', satW: [0.32, 0.58] },
      extra: { size: 0.020, track: 0.14, maxLines: 1, decor: 'plain', satW: [0.34, 0.62] },
      credit: { size: 0.022, track: 0.13, maxLines: 1, decor: 'plain', wFlex: 3 },
      release: { size: 0.0118, track: 0.01, maxLines: 1, decor: 'plain', wFlex: 5 }
    },
    foot: {
      surface: 'gameChrome', anchor: 'gameFoot', hRange: [0.145, 0.235], chrome: 'game',
      items: [{ role: 'credit', bias: 0.3 }, { role: 'release', own: true, bias: 0.9, hFlex: 0.7 }],
      pad: { x: 0.045, t: 0.18, b: 0.10, gap: 0.12 }, reserve: 'ratingPlate'
    },
    head: { chance: 0.0 },
    floaters: {},
    extras: [{ v: 'cornerPlate', w: 2.2 }, { v: 'keyartMarks', w: 1.6 }, { v: 'bottomGradient', w: 1.2 },
      { v: 'sideBand', w: 0.9 }, { v: 'topGradient', w: 0.8 }, { v: 'boldFrame', w: 0.5 }],
    extraCount: [0, 2],
    overlays: [{ v: 'bloom', w: 3 }, { v: 'grain', w: 3 }, { v: 'vignette', w: 1.6 },
      { v: 'chromaEdge', w: 1.2 }, { v: 'scanline', w: 1 }, { v: 'halation', w: 1.4 }],
    overlayCount: [1, 4]
  },

  adult: {
    hero: 'title',
    aspects: [{ v: 0.708, w: 3 }, { v: 0.690, w: 1.6 }, { v: 0.750, w: 1.6 }, { v: 0.667, w: 1.3 }, { v: 0.800, w: 0.9 }],
    heroModes: [
      { v: 'vRight', w: 3 }, { v: 'vLeft', w: 2 }, { v: 'hTop', w: 2.6 },
      { v: 'hCenter', w: 1.4 }, { v: 'hBottom', w: 1.2 }, { v: 'vInner', w: 0.8 }
    ],
    margin: [0.028, 0.060],
    roles: {
      title: { sizeH: 0.130, sizeV: 0.126, trackH: 0.005, trackV: 0.00, maxLines: 4, big: true, decor: 'title', tiered: true },
      catch: { size: 0.037, track: 0.02, maxLines: 1, decor: 'accent', satW: [0.44, 0.72], vertChance: 0.70 },
      name: { size: 0.048, track: 0.08, maxLines: 1, decor: 'accent', satW: [0.38, 0.64], vertChance: 0.55 },
      tag: { size: 0.026, track: 0.06, maxLines: 1, decor: 'accent', satW: [0.44, 0.86], wFlex: 5 },
      badge: { size: 0.034, track: 0.02, maxLines: 1, decor: 'accent', satW: [0.26, 0.46] },
      extra: { size: 0.019, track: 0.03, maxLines: 1, decor: 'plain', wFlex: 4 },
      credit: { size: 0.018, track: 0.04, maxLines: 1, decor: 'plain', wFlex: 2 },
      code: { size: 0.030, track: 0.10, maxLines: 1, latin: true, decor: 'accent', wFlex: 3 },
      release: { size: 0.019, track: 0.04, maxLines: 1, decor: 'plain', wFlex: 1.8 }
    },
    foot: {
      surface: 'avBottomBar', anchor: 'avSpecBand', hRange: [0.105, 0.195],
      items: [{ role: 'extra', bias: 0.2 }, { role: 'credit', bias: 0.25 }, { role: 'code', bias: 0.8 }, { role: 'release', bias: 0.85 }],
      pad: { x: 0.045, t: 0.12, b: 0.10, gap: 0.13 }
    },
    head: {
      chance: 0.42, surface: 'seriesBand', anchor: 'seriesBand', hRange: [0.048, 0.088],
      items: [{ role: 'tag' }], pad: { x: 0.045, t: 0.16, b: 0.16, gap: 0.1 }
    },
    floaters: {
      badge: {
        surface: null, anchor: 'avBadge', chance: 0.55,
        w: [0.26, 0.40], ratio: [0.16, 0.24], inset: { x: 0.04, y: 0.06, w: 0.92, h: 0.88 },
        zones: [{ v: 'midLeft', w: 2 }, { v: 'midRight', w: 2 }, { v: 'topLeft', w: 1.6 },
          { v: 'topRight', w: 1.6 }, { v: 'bottomLeft', w: 1 }, { v: 'bottomRight', w: 1 }]
      }
    },
    extras: [{ v: 'boldFrame', w: 2 }, { v: 'discSpine', w: 1.6 },
      { v: 'barcode', w: 1.8 }, { v: 'diagonalBand', w: 1.2 }, { v: 'sideBand', w: 0.8 }, { v: 'hairRules', w: 0.7 }],
    extraCount: [1, 3],
    overlays: [{ v: 'grain', w: 3 }, { v: 'neonGlow', w: 2.4 }, { v: 'halation', w: 2.2 },
      { v: 'bloom', w: 1.8 }, { v: 'chromaEdge', w: 1.4 }, { v: 'lightLeak', w: 1.2 },
      { v: 'vignette', w: 1.2 }, { v: 'inkBleed', w: 0.8 }, { v: 'bokehDots', w: 0.8 }],
    overlayCount: [1, 4]
  }
};

// anchor を持つ装飾 surface の配置規則。ここに無い surface は自前で rng 配置する。
const EXTRA_PLACE = {
  barcode: { anchor: 'barcode', place: 'foot', w: [0.15, 0.25], ratio: [0.20, 0.34], side: 'either' },
  gridPlate: { anchor: 'gridPlate', place: 'footFill', inset: [0.020, 0.060] },
  cornerPlate: {
    anchor: 'cornerPlate', place: 'free', w: [0.30, 0.47], ratio: [0.11, 0.18],
    zones: [{ v: 'topRight', w: 3 }, { v: 'topLeft', w: 1.6 }, { v: 'bottomRight', w: 1.2 }, { v: 'bottomLeft', w: 0.8 }]
  },
  circleMark: {
    anchor: 'circleMark', place: 'free', w: [0.10, 0.18], ratio: [1.15, 1.50],
    zones: [{ v: 'topLeft', w: 2 }, { v: 'topRight', w: 2 }, { v: 'bottomLeft', w: 1 }, { v: 'bottomRight', w: 1 }]
  },
  waveBand: {
    anchor: 'waveBand', place: 'free', w: [0.34, 0.58], ratio: [0.06, 0.11],
    zones: [{ v: 'bottomRight', w: 2 }, { v: 'bottomLeft', w: 2 }, { v: 'topRight', w: 1 }, { v: 'topLeft', w: 1 }]
  },
  plate: { anchor: 'plate', place: 'hero', pad: [0.030, 0.075] }
};

function clamp(v, lo, hi) { return v < lo ? lo : (v > hi ? hi : v); }

function rectClamp(r) {
  const w = clamp(r.w, 0.02, 0.98);
  const h = clamp(r.h, 0.012, 0.98);
  return { x: clamp(r.x, 0.008, 0.992 - w), y: clamp(r.y, 0.008, 0.992 - h), w: w, h: h };
}

function pickCount(rng, range, len) {
  const lo = clamp(range[0], 0, len);
  const hi = clamp(range[1], lo, len);
  return rng.int(lo, hi);
}

function sampleWeighted(rng, pool, n) {
  const rest = pool.slice();
  const out = [];
  for (let i = 0; i < n && rest.length > 0; i++) {
    const v = rng.weighted(rest);
    out.push(v);
    for (let j = 0; j < rest.length; j++) {
      if (rest[j].v === v) { rest.splice(j, 1); break; }
    }
  }
  return out;
}

// ---------------------------------------------------------------- bands

function makeBand(rng, bandSpec, edge) {
  const h = rng.range(bandSpec.hRange[0], bandSpec.hRange[1]);
  return { x: 0, y: edge === 'top' ? 0 : 1 - h, w: 1, h: h, edge: edge };
}

function rowsFromItems(rng, items) {
  const rows = [];
  const loose = [];
  for (let i = 0; i < items.length; i++) {
    if (items[i].own) { rows.push({ items: [items[i]] }); } else { loose.push(items[i]); }
  }
  const shuffled = rng.shuffle(loose);
  let i = 0;
  while (i < shuffled.length) {
    const remain = shuffled.length - i;
    let take = remain <= 1 ? 1 : rng.weighted([{ v: 1, w: 1.1 }, { v: 2, w: 3.2 }, { v: 3, w: 1.3 }]);
    if (take > remain) { take = remain; }
    rows.push({ items: rng.shuffle(shuffled.slice(i, i + take)) });
    i += take;
  }
  for (let r = 0; r < rows.length; r++) {
    const row = rows[r];
    let bias = 0;
    let hFlex = 0;
    for (let k = 0; k < row.items.length; k++) {
      const it = row.items[k];
      bias += it.bias == null ? 0.5 : it.bias;
      hFlex = Math.max(hFlex, it.hFlex == null ? 1 : it.hFlex);
    }
    row.bias = bias / row.items.length + rng.range(-0.12, 0.12);
    row.hFlex = hFlex;
  }
  rows.sort(function (a, b) { return a.bias - b.bias; });
  return rows;
}

function packBand(rng, band, items, pad, reserved) {
  const out = [];
  if (items.length === 0) { return out; }
  const padT = band.h * pad.t;
  const padB = band.h * pad.b;
  const innerY = band.y + padT;
  const innerH = Math.max(0.008, band.h - padT - padB);
  const rows = rowsFromItems(rng, items);

  let totalFlex = 0;
  for (let r = 0; r < rows.length; r++) { totalFlex += rows[r].hFlex; }
  const gap = rows.length > 1 ? innerH * pad.gap / (rows.length - 1) : 0;
  const usable = innerH - gap * (rows.length - 1);

  const padX = clamp(pad.x * rng.range(0.70, 1.45), 0.014, 0.16);
  let cy = innerY;
  for (let r = 0; r < rows.length; r++) {
    const row = rows[r];
    const rh = usable * (row.hFlex / totalFlex);
    let left = padX;
    let right = 1 - padX;
    // 予約矩形（rating plate 等）は帯の高さのほぼ全体を占めるため、
    // 最下段だけでなく縦に重なる行すべてで左右を詰める
    if (reserved && cy < reserved.y + reserved.h && cy + rh > reserved.y) {
      if (reserved.side === 'left') { left = Math.max(left, reserved.x + reserved.w + 0.018); }
      else { right = Math.min(right, reserved.x - 0.018); }
    }
    let availW = Math.max(0.10, right - left);
    // 単独行は毎回フル幅にせず、幅と寄せを振る（帯の中の左右位置が固定化するのを防ぐ）
    let soloAlign = null;
    if (row.items.length === 1) {
      soloAlign = row.items[0].soloAlign
        || rng.weighted([{ v: 'center', w: 2.4 }, { v: 'left', w: 1.8 }, { v: 'right', w: 1.2 }]);
      if (rng.chance(0.45)) {
        const shrunk = availW * rng.range(0.50, 0.88);
        if (soloAlign === 'right') { left = right - shrunk; }
        else if (soloAlign === 'center') { left = left + (availW - shrunk) / 2; }
        availW = shrunk;
      }
    }
    let wFlexSum = 0;
    for (let k = 0; k < row.items.length; k++) {
      wFlexSum += row.items[k].wFlex == null ? 1 : row.items[k].wFlex;
    }
    let cx = left;
    for (let k = 0; k < row.items.length; k++) {
      const it = row.items[k];
      const iw = availW * ((it.wFlex == null ? 1 : it.wFlex) / wFlexSum);
      let align;
      if (row.items.length === 1) {
        align = soloAlign;
      } else {
        align = k === 0 ? 'left' : (k === row.items.length - 1 ? 'right' : 'center');
      }
      out.push({ role: it.role, rect: rectClamp({ x: cx, y: cy, w: iw * 0.98, h: rh }), align: align });
      cx += iw;
    }
    cy += rh + gap;
  }
  return out;
}

// ---------------------------------------------------------------- hero

function heroTrack(rng, mode, free, m, aspect, style) {
  const ft = free.y;
  const fh = free.h;
  const lines = style && style.maxLines > 0 ? style.maxLines : 1;
  if (mode.charAt(0) === 'v') {
    const wide = aspect > 1;
    const w = wide ? rng.range(0.30, 0.48) : rng.range(0.150, 0.280);
    const h = fh * rng.range(0.56, 0.92);
    const y = ft + (fh - h) * rng.range(0, 0.40);
    let x;
    if (mode === 'vRight') { x = 1 - m - w - rng.range(0, 0.040); }
    else if (mode === 'vLeft') { x = m + rng.range(0, 0.040); }
    else { x = rng.range(m + 0.08, Math.max(m + 0.09, 1 - m - w - 0.08)); }
    return { rect: rectClamp({ x: x, y: y, w: w, h: h }), vertical: true, align: 'top' };
  }
  const w = rng.range(0.68, 0.94);
  // 行数ぶんの高さを確保しないと text が rect を溢れて隣接要素に被る
  const need = (style ? style.size : 0.10) * (0.95 + (lines - 1) * 0.52) * rng.range(0.94, 1.18);
  const h = Math.min(fh * 0.94, Math.max(fh * rng.range(0.14, 0.26), need));
  let y;
  if (mode === 'hTop') { y = ft + fh * rng.range(0.02, 0.17); }
  else if (mode === 'hBottom') { y = ft + fh - h - fh * rng.range(0.03, 0.20); }
  else { y = ft + (fh - h) * rng.range(0.32, 0.66); }
  let x, align;
  if (mode === 'hLeft') { x = m; align = 'left'; }
  else if (mode === 'hRight') { x = 1 - m - w; align = 'right'; }
  else { x = (1 - w) / 2 + rng.range(-0.020, 0.020); align = 'center'; }
  return { rect: rectClamp({ x: x, y: y, w: w, h: h }), vertical: false, align: align };
}

function freeZones(free, hero, m) {
  const zones = [];
  const ft = free.y;
  const fb = free.y + free.h;
  const hx0 = hero.x, hx1 = hero.x + hero.w;
  const hy0 = hero.y, hy1 = hero.y + hero.h;
  const gapTop = hy0 - ft;
  const gapBottom = fb - hy1;
  if (gapTop > 0.055) { zones.push({ x: m, y: ft, w: 1 - m * 2, h: gapTop - 0.008, tag: 'above' }); }
  if (gapBottom > 0.055) { zones.push({ x: m, y: hy1 + 0.008, w: 1 - m * 2, h: gapBottom - 0.008, tag: 'below' }); }
  const sideY = Math.max(ft, hy0);
  const sideH = Math.min(fb, hy1) - sideY;
  if (hx0 - m > 0.11 && sideH > 0.05) { zones.push({ x: m, y: sideY, w: hx0 - m - 0.010, h: sideH, tag: 'left' }); }
  if (1 - m - hx1 > 0.11 && sideH > 0.05) { zones.push({ x: hx1 + 0.010, y: sideY, w: 1 - m - hx1 - 0.010, h: sideH, tag: 'right' }); }
  const out = [];
  for (let i = 0; i < zones.length; i++) {
    if (zones[i].w > 0.06 && zones[i].h > 0.035) { out.push(zones[i]); }
  }
  return out;
}

// zone 内は cursor で縦に積む。同じ zone に複数入っても重ならない。
function rectInZone(rng, zone, w, h, forceAlign) {
  const ww = Math.min(w, zone.w);
  const hh = Math.min(h, zone.h);
  const slack = zone.w - ww;
  const align = forceAlign || rng.weighted([{ v: 'left', w: 2 }, { v: 'center', w: 2.2 }, { v: 'right', w: 1.5 }]);
  let x;
  if (align === 'left') { x = zone.x + slack * rng.range(0, 0.16); }
  else if (align === 'right') { x = zone.x + slack * rng.range(0.84, 1); }
  else { x = zone.x + slack * rng.range(0.36, 0.64); }
  if (zone.cursor == null) { zone.cursor = zone.y + zone.h * rng.range(0.02, 0.22); }
  const y = Math.min(zone.y + zone.h - hh, zone.cursor);
  return {
    rect: rectClamp({ x: x, y: y, w: ww, h: hh }),
    align: align,
    zone: zone,
    advance: hh + zone.h * rng.range(0.05, 0.16)
  };
}

function satelliteBlock(rng, style, vertical) {
  if (vertical) {
    const w = clamp(style.size * rng.range(1.7, 2.5), 0.045, 0.24);
    const h = rng.range(0.24, 0.56);
    return { w: w, h: h };
  }
  const wr = style.satW || [0.40, 0.70];
  const w = rng.range(wr[0], wr[1]);
  const lines = style.maxLines > 0 ? style.maxLines : 1;
  const h = clamp(style.size * lines * 1.5 + 0.010, 0.024, 0.30);
  return { w: w, h: h };
}

// ---------------------------------------------------------------- floaters

function floaterSpot(rng, zoneName, free, w, h, m) {
  const ft = free.y;
  const fb = free.y + free.h;
  const span = Math.max(0.001, fb - ft - h);
  let x, y;
  if (zoneName === 'topLeft') { x = m + rng.range(0, 0.055); y = ft + rng.range(0.008, 0.060); }
  else if (zoneName === 'topRight') { x = 1 - m - w - rng.range(0, 0.055); y = ft + rng.range(0.008, 0.060); }
  else if (zoneName === 'topCenter') { x = (1 - w) / 2 + rng.range(-0.05, 0.05); y = ft + rng.range(0.010, 0.055); }
  else if (zoneName === 'midLeft') { x = m + rng.range(0, 0.065); y = ft + span * rng.range(0.28, 0.66); }
  else if (zoneName === 'midRight') { x = 1 - m - w - rng.range(0, 0.065); y = ft + span * rng.range(0.28, 0.66); }
  else if (zoneName === 'bottomLeft') { x = m + rng.range(0, 0.055); y = fb - h - rng.range(0.010, 0.075); }
  else { x = 1 - m - w - rng.range(0, 0.055); y = fb - h - rng.range(0.010, 0.075); }
  return rectClamp({ x: x, y: y, w: w, h: h });
}

function placeExtra(rng, rule, cx) {
  if (rule.place === 'hero') {
    const h = cx.hero;
    if (!h || h.w < 0.05) { return null; }
    const px = rng.range(rule.pad[0], rule.pad[1]);
    const py = px * cx.aspect;
    return rectClamp({ x: h.x - px, y: h.y - py, w: h.w + px * 2, h: h.h + py * 2 });
  }
  if (rule.place === 'footFill') {
    const b = cx.foot;
    if (!b) { return null; }
    const ix = rng.range(rule.inset[0], rule.inset[1]);
    const iy = ix * cx.aspect;
    return rectClamp({ x: ix, y: b.y + iy, w: 1 - ix * 2, h: Math.max(0.030, b.h - iy * 2) });
  }
  const w = rng.range(rule.w[0], rule.w[1]);
  const h = w * rng.range(rule.ratio[0], rule.ratio[1]);
  if (rule.place === 'foot') {
    const b = cx.foot;
    if (b && b.h > h + 0.014) {
      const right = rng.chance(0.70);
      const x = right ? 1 - cx.m - w - rng.range(0, 0.035) : cx.m + rng.range(0, 0.035);
      const y = b.y + b.h - h - rng.range(0.005, Math.max(0.006, b.h - h - 0.006));
      return rectClamp({ x: x, y: y, w: w, h: h });
    }
    return floaterSpot(rng, rng.chance(0.70) ? 'bottomRight' : 'bottomLeft', cx.free, w, h, cx.m);
  }
  const pool = (rule.zones || []).slice();
  for (let t = 0; t < 6 && pool.length > 0; t++) {
    const z = rng.weighted(pool);
    for (let j = 0; j < pool.length; j++) {
      if (pool[j].v === z) { pool.splice(j, 1); break; }
    }
    const cand = floaterSpot(rng, z, cx.free, w, h, cx.m);
    if (!overlapsAny(cand, cx.occupied, 0.012)) { return cand; }
  }
  // 装飾は本文より優先度が低い。空きが無ければ描かない。
  return null;
}

function insetRect(r, ins) {
  return rectClamp({ x: r.x + r.w * ins.x, y: r.y + r.h * ins.y, w: r.w * ins.w, h: r.h * ins.h });
}

function overlapsAny(r, list, tol) {
  for (let i = 0; i < list.length; i++) {
    const b = list[i];
    const ox = Math.min(r.x + r.w, b.x + b.w) - Math.max(r.x, b.x);
    const oy = Math.min(r.y + r.h, b.y + b.h) - Math.max(r.y, b.y);
    if (ox > tol && oy > tol) { return true; }
  }
  return false;
}

// ---------------------------------------------------------------- plan

function buildSkeleton(rng, genre) {
  const spec = GENRE_SPEC[genre];
  if (!spec) { throw new Error('genre spec未定義: ' + genre); }
  const aspect = rng.weighted(spec.aspects);
  const heroMode = rng.weighted(spec.heroModes);
  const heroVertical = heroMode.charAt(0) === 'v';
  const titleVertical = spec.hero === 'title'
    ? heroVertical
    : rng.chance(spec.titleVertChance || 0);
  return {
    genre: genre,
    spec: spec,
    aspect: aspect,
    heroMode: heroMode,
    heroVertical: heroVertical,
    titleVertical: titleVertical,
    margin: rng.range(spec.margin[0], spec.margin[1])
  };
}

// ---------------------------------------------------------------- compose

function styleOf(spec, role, vertical) {
  const r = spec.roles[role] || {};
  const size = vertical
    ? (r.sizeV != null ? r.sizeV : r.size)
    : (r.sizeH != null ? r.sizeH : r.size);
  const track = vertical
    ? (r.trackV != null ? r.trackV : r.track)
    : (r.trackH != null ? r.trackH : r.track);
  return {
    size: size != null ? size : 0.024,
    track: track != null ? track : 0.04,
    maxLines: r.maxLines != null ? r.maxLines : 1,
    decor: r.decor || 'plain',
    big: !!r.big,
    latin: !!r.latin,
    tiered: !!r.tiered,
    sizeTier: !!r.sizeTier,
    phraseWrap: !!r.phraseWrap,
    satW: r.satW,
    wFlex: r.wFlex,
    hFlex: r.hFlex,
    own: r.own
  };
}

function makeSlot(rng, spec, role, style, rect, opts) {
  const jit = rng.range(0.92, 1.10);
  return {
    role: role,
    size: style.size * jit,
    tracking: style.track * rng.range(0.85, 1.18),
    maxLines: style.maxLines,
    align: opts.align,
    vertical: !!opts.vertical,
    big: style.big,
    latin: style.latin,
    tiered: style.tiered,
    sizeTier: style.sizeTier,
    phraseWrap: opts.vertical ? style.phraseWrap : false,
    outline: opts.outline,
    inkOnly: opts.inkOnly,
    decor: style.decor,
    onSurface: opts.onSurface || null,
    fixed: !!opts.fixed,
    slide: opts.slide != null ? opts.slide : 0.045,
    candidates: opts.candidates || [rect],
    rect: rect
  };
}

function composeLayout(rng, plan, copy) {
  const spec = plan.spec;
  const genre = plan.genre;
  const m = plan.margin;
  const anchors = {};
  const surfaces = [];
  const slots = [];
  const used = {};

  function has(role) { return !!(copy && copy[role]); }
  function take(role) { used[role] = true; }

  // ---- bands ----
  let foot = null;
  let head = null;
  const footSpec = spec.foot;
  if (footSpec && footSpec.surface) {
    const footRoles = [];
    for (let i = 0; i < (footSpec.items || []).length; i++) {
      if (has(footSpec.items[i].role)) { footRoles.push(footSpec.items[i]); }
    }
    const wanted = footSpec.chance == null ? true : rng.chance(footSpec.chance);
    if (wanted && (footRoles.length > 0 || footSpec.chance != null)) {
      const edge = footSpec.edgeSwap && rng.chance(footSpec.edgeSwap) ? 'top' : 'bottom';
      foot = makeBand(rng, footSpec, edge);
      foot.spec = footSpec;
      foot.items = footRoles;
      anchors[footSpec.anchor] = { x: foot.x, y: foot.y, w: foot.w, h: foot.h };
      surfaces.push(footSpec.surface);
    }
  }
  const headSpec = spec.head;
  if (headSpec && headSpec.surface && rng.chance(headSpec.chance)) {
    if (!foot || foot.edge !== 'top') {
      const headRoles = [];
      for (let i = 0; i < (headSpec.items || []).length; i++) {
        if (has(headSpec.items[i].role)) { headRoles.push(headSpec.items[i]); }
      }
      head = makeBand(rng, headSpec, 'top');
      head.spec = headSpec;
      head.items = headRoles;
      if (headSpec.anchor) { anchors[headSpec.anchor] = { x: head.x, y: head.y, w: head.w, h: head.h }; }
      surfaces.push(headSpec.surface);
    }
  }

  // foot 内の sub 帯（billing plate 等）
  if (foot && foot.spec.sub) {
    const frac = rng.range(foot.spec.sub.hFrac[0], foot.spec.sub.hFrac[1]);
    const sh = foot.h * frac;
    const sub = foot.edge === 'top'
      ? { x: 0, y: foot.y, w: 1, h: sh }
      : { x: 0, y: foot.y + foot.h - sh, w: 1, h: sh };
    foot.sub = sub;
    anchors[foot.spec.sub.anchor] = sub;
    surfaces.push(foot.spec.sub.surface);
  }

  // foot が予約する矩形（game の rating plate）。w は W 基準・h は H 基準なので aspect で換算する。
  let reserved = null;
  if (foot && foot.spec.reserve === 'ratingPlate') {
    const rw = rng.range(0.072, 0.104);
    const side = rng.chance(0.72) ? 'left' : 'right';
    const rh = rw * plan.aspect * 1.14;
    const ry = foot.y + foot.h - rh - rng.range(0.010, 0.032);
    const rx = side === 'left' ? m + rng.range(0, 0.030) : 1 - m - rw - rng.range(0, 0.030);
    reserved = { x: rx, y: ry, w: rw, h: rh, side: side };
    anchors.ratingPlate = { x: rx, y: ry, w: rw, h: rh };
  }

  // ---- band slots ----
  const bandList = [];
  if (foot) { bandList.push(foot); }
  if (head) { bandList.push(head); }
  for (let b = 0; b < bandList.length; b++) {
    const band = bandList[b];
    const mainItems = [];
    const subItems = [];
    for (let i = 0; i < band.items.length; i++) {
      const it = band.items[i];
      const st = styleOf(spec, it.role, false);
      const entry = {
        role: it.role, bias: it.bias, own: it.own || st.own,
        hFlex: it.hFlex != null ? it.hFlex : st.hFlex,
        wFlex: it.wFlex != null ? it.wFlex : st.wFlex
      };
      if (it.sub && band.sub) { subItems.push(entry); } else { mainItems.push(entry); }
    }
    const mainRect = band.sub
      ? (band.edge === 'top'
        ? { x: 0, y: band.sub.y + band.sub.h, w: 1, h: band.h - band.sub.h }
        : { x: 0, y: band.y, w: 1, h: band.h - band.sub.h })
      : { x: band.x, y: band.y, w: band.w, h: band.h };
    const packedMain = packBand(rng, mainRect, mainItems, band.spec.pad, reserved);
    const packedSub = band.sub
      ? packBand(rng, band.sub, subItems, { x: band.spec.pad.x, t: 0.12, b: 0.12, gap: 0.08 }, null)
      : [];
    const packed = packedMain.concat(packedSub);
    for (let i = 0; i < packed.length; i++) {
      const p = packed[i];
      const st = styleOf(spec, p.role, false);
      take(p.role);
      if (band.spec.plateFor === p.role && band.spec.plateAnchor) {
        anchors[band.spec.plateAnchor] = rectClamp({
          x: p.rect.x - 0.013, y: p.rect.y - p.rect.h * 0.18,
          w: p.rect.w + 0.026, h: p.rect.h * 1.36
        });
      }
      slots.push(makeSlot(rng, spec, p.role, st, p.rect, {
        align: p.align, vertical: false, fixed: true,
        onSurface: band.spec.surface,
        outline: !!spec.outline, inkOnly: !!spec.inkOnly
      }));
    }
  }

  const bandRects = [];
  for (let i = 0; i < slots.length; i++) { bandRects.push(slots[i].rect); }

  // gameChrome は自前で上端の platform 表示を描く。ここで場所を予約しないと本文が乗る。
  let chromeTop = 0;
  if (foot && foot.spec.chrome === 'game') {
    if (plan.aspect >= 0.66) {
      chromeTop = rng.range(0.055, 0.098);
      anchors.platformBand = { x: 0, y: 0, w: 1, h: chromeTop };
    } else {
      const tw = rng.range(0.165, 0.240);
      const th = tw * rng.range(0.50, 0.70);
      const tab = { x: rng.range(0.010, 0.030), y: rng.range(0.010, 0.030), w: tw, h: th };
      anchors.platformTab = tab;
      bandRects.push(tab);
    }
  }

  // ---- free region ----
  let freeTop = head ? head.y + head.h : (foot && foot.edge === 'top' ? foot.y + foot.h : 0);
  if (chromeTop > freeTop) { freeTop = chromeTop; }
  const freeBottom = foot && foot.edge === 'bottom' ? foot.y : 1;
  const free = { x: 0, y: freeTop + m * 0.35, w: 1, h: Math.max(0.18, freeBottom - freeTop - m * 0.7) };

  // ---- hero ----
  const heroRole = spec.hero;
  const occupied = bandRects.slice();
  let heroRect = null;
  if (has(heroRole)) {
    const vertical = plan.heroVertical;
    const st = styleOf(spec, heroRole, vertical);
    const track = heroTrack(rng, plan.heroMode, free, m, plan.aspect, st);
    heroRect = track.rect;
    occupied.push(heroRect);
    take(heroRole);
    slots.push(makeSlot(rng, spec, heroRole, st, heroRect, {
      align: track.align, vertical: vertical,
      outline: !!spec.outline, inkOnly: !!spec.inkOnly,
      slide: 0.028,
      candidates: [heroRect]
    }));
  } else {
    heroRect = { x: 0.5, y: free.y + free.h * 0.5, w: 0.001, h: 0.001 };
  }

  // ---- floaters ----
  const floaters = spec.floaters || {};
  const floaterNames = Object.keys(floaters);
  for (let i = 0; i < floaterNames.length; i++) {
    const role = floaterNames[i];
    const f = floaters[role];
    if (used[role] || !has(role)) { continue; }
    if (!rng.chance(f.chance)) { continue; }
    const fw = rng.range(f.w[0], f.w[1]);
    const fh = fw * rng.range(f.ratio[0], f.ratio[1]);
    let box = null;
    const zonePool = f.zones.slice();
    for (let t = 0; t < 5 && zonePool.length > 0; t++) {
      const zone = rng.weighted(zonePool);
      for (let j = 0; j < zonePool.length; j++) {
        if (zonePool[j].v === zone) { zonePool.splice(j, 1); break; }
      }
      const cand = floaterSpot(rng, zone, free, fw, fh, m);
      if (!overlapsAny(cand, occupied, 0.012)) { box = cand; break; }
      if (!box) { box = cand; }
    }
    if (!box) { continue; }
    let anchorName = f.anchor;
    let surfaceName = f.surface;
    if (f.pill) {
      const right = box.x + box.w * 0.5 > 0.5;
      anchorName = right ? 'cvPlateRight' : 'cvPlateLeft';
      surfaceName = right ? 'cvPlateRight' : 'cvPlateLeft';
    }
    anchors[anchorName] = box;
    if (surfaceName) { surfaces.push(surfaceName); }
    occupied.push(box);
    take(role);
    const st = styleOf(spec, role, false);
    slots.push(makeSlot(rng, spec, role, st, insetRect(box, f.inset), {
      align: 'center', vertical: false, fixed: true,
      onSurface: surfaceName,
      outline: !!spec.outline && !surfaceName, inkOnly: !!spec.inkOnly
    }));
  }

  // ---- satellites ----
  const zones = freeZones(free, heroRect, m);
  const satRoles = [];
  for (let i = 0; i < ALL_ROLES.length; i++) {
    const role = ALL_ROLES[i];
    if (used[role] || !has(role) || !spec.roles[role]) { continue; }
    satRoles.push(role);
  }
  const satOrder = rng.shuffle(satRoles);
  for (let i = 0; i < satOrder.length; i++) {
    const role = satOrder[i];
    if (zones.length === 0) { break; }
    const roleSpec = spec.roles[role] || {};
    let vertical;
    if (role === 'title' && spec.hero !== 'title') { vertical = plan.titleVertical; }
    else { vertical = rng.chance(roleSpec.vertChance || 0); }
    const st = styleOf(spec, role, vertical);
    const block = satelliteBlock(rng, st, vertical);
    // 既に確定した furniture（帯・floater・hero・先行 satellite）と当たらない候補を集める
    const candidates = [];
    let chosen = null;
    let fallback = null;
    const order = rng.shuffle(zones);
    for (let pass = 0; pass < 2 && candidates.length < 3; pass++) {
      for (let z = 0; z < order.length && candidates.length < 3; z++) {
        const placed = rectInZone(rng, order[z], block.w, block.h);
        if (!fallback) { fallback = placed; }
        if (!overlapsAny(placed.rect, occupied, 0.010)) {
          candidates.push(placed.rect);
          if (!chosen) { chosen = placed; }
        }
      }
    }
    if (candidates.length === 0) {
      if (!fallback) { continue; }
      chosen = fallback;
      candidates.push(fallback.rect);
    }
    chosen.zone.cursor = chosen.rect.y + chosen.advance;
    occupied.push(candidates[0]);
    take(role);
    const align = vertical ? 'top' : rng.weighted([{ v: 'center', w: 2 }, { v: 'left', w: 2 }, { v: 'right', w: 1.4 }]);
    slots.push(makeSlot(rng, spec, role, st, candidates[0], {
      align: align, vertical: vertical,
      outline: !!spec.outline, inkOnly: !!spec.inkOnly,
      slide: rng.range(0.070, 0.130),
      candidates: candidates
    }));
  }

  // ---- 装飾 surface ----
  const extras = sampleWeighted(rng, spec.extras || [], pickCount(rng, spec.extraCount || [0, 2], (spec.extras || []).length));
  const extraCtx = { free: free, foot: foot, hero: heroRect, m: m, aspect: plan.aspect, occupied: occupied };
  for (let i = 0; i < extras.length; i++) {
    const name = extras[i];
    if (surfaces.indexOf(name) >= 0) { continue; }
    const rule = EXTRA_PLACE[name];
    if (rule) {
      const box = placeExtra(rng, rule, extraCtx);
      if (!box) { continue; }
      anchors[rule.anchor] = box;
      occupied.push(box);
    }
    surfaces.push(name);
  }

  // ---- overlay ----
  const overlays = sampleWeighted(rng, spec.overlays || [], pickCount(rng, spec.overlayCount || [1, 3], (spec.overlays || []).length));

  // 固定 furniture → hero → satellite の順に確定させる。
  // 後段の findBestRect は occupied を見るので、この順序でないと satellite が furniture に被る。
  slots.sort(function (a, b) {
    const ai = a.fixed ? 0 : (a.big ? 1 : 2);
    const bi = b.fixed ? 0 : (b.big ? 1 : 2);
    return ai - bi;
  });

  const id = genre + '-' + plan.heroMode + '-' + (foot ? foot.edge[0] : 'n') + (head ? 'h' : '') + '-' + slots.length;

  return {
    id: id,
    aspect: plan.aspect,
    slots: slots,
    surfaces: surfaces,
    overlays: overlays,
    anchors: anchors,
    heroMode: plan.heroMode,
    bands: { foot: foot ? { edge: foot.edge, y: foot.y, h: foot.h } : null, head: head ? { y: head.y, h: head.h } : null }
  };
}

Object.assign(PF, { GENRE_SPEC, buildSkeleton, composeLayout });
})(window.PF = window.PF || {});
