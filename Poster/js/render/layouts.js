export const SURFACE_ANCHORS = {
  filmScrim: { x: 0.00, y: 0.720, w: 1.00, h: 0.280 },
  specBand: { x: 0.00, y: 0.845, w: 1.00, h: 0.155 },
  obi: { x: 0.00, y: 0.660, w: 1.00, h: 0.340 },
  obiBox: { x: 0.055, y: 0.866, w: 0.400, h: 0.070 },
  voiceTopBand: { x: 0.00, y: 0.000, w: 1.00, h: 0.130 },
  voiceBottomBand: { x: 0.00, y: 0.845, w: 1.00, h: 0.155 },
  platformBand: { x: 0.00, y: 0.000, w: 1.00, h: 0.100 },
  publisherRow: { x: 0.235, y: 0.858, w: 0.725, h: 0.128 },
  ratingPlate: { x: 0.030, y: 0.852, w: 0.112, h: 0.112 },
  seriesBand: { x: 0.00, y: 0.000, w: 1.00, h: 0.070 },
  sashPlate: { x: 0.045, y: 0.698, w: 0.620, h: 0.080 },
  avSpecBand: { x: 0.00, y: 0.855, w: 1.00, h: 0.145 },
  gridPlate: { x: 0.02, y: 0.862, w: 0.96, h: 0.128 },
  ribbon: { x: 0.05, y: 0.868, w: 0.90, h: 0.072 },
  plate: { x: 0.10, y: 0.270, w: 0.80, h: 0.270 },
  roundPlate: { x: 0.10, y: 0.290, w: 0.80, h: 0.250 },
  laurelBadge: { x: 0.055, y: 0.045, w: 0.340, h: 0.095 },
  barcode: { x: 0.74, y: 0.925, w: 0.20, h: 0.055 },
  cornerPlate: { x: 0.62, y: 0.115, w: 0.32, h: 0.075 }
};

export const LAYOUTS = {
  cinema: [
    {
      id: 'cinema-jp-b1', aspect: 0.707,
      slots: [
        { role: 'badge', size: 0.019, tracking: 0.06, maxLines: 2, align: 'center', onSurface: 'laurelBadge', decor: 'plain',
          candidates: [{ x: .075, y: .058, w: .300, h: .068 }] },
        { role: 'catch', size: 0.038, tracking: 0.06, maxLines: 2, align: 'center', decor: 'accent',
          candidates: [{ x: .08, y: .150, w: .84, h: .110 }, { x: .08, y: .400, w: .84, h: .105 }] },
        { role: 'name', size: 0.026, tracking: 0.14, maxLines: 2, align: 'center', decor: 'plain',
          candidates: [{ x: .08, y: .490, w: .84, h: .060 }, { x: .08, y: .285, w: .84, h: .055 }] },
        { role: 'title', size: 0.125, tracking: 0.04, maxLines: 2, align: 'center', big: true, decor: 'title',
          candidates: [{ x: .06, y: .575, w: .88, h: .170 }, { x: .06, y: .180, w: .88, h: .170 }] },
        { role: 'extra', size: 0.024, tracking: 0.28, maxLines: 1, align: 'center', latin: true, decor: 'plain',
          candidates: [{ x: .12, y: .762, w: .76, h: .040 }] },
        { role: 'release', size: 0.030, tracking: 0.10, maxLines: 1, align: 'center', onSurface: 'filmScrim', decor: 'plain',
          candidates: [{ x: .08, y: .862, w: .84, h: .044 }] },
        { role: 'credit', size: 0.016, tracking: 0.01, maxLines: 5, align: 'center', onSurface: 'filmScrim', decor: 'plain',
          candidates: [{ x: .07, y: .916, w: .86, h: .068 }] }
      ],
      surfaces: ['filmScrim', 'laurelBadge', 'topGradient'],
      overlays: ['grain', 'vignette', 'halation']
    },
    {
      id: 'cinema-jp-vertical', aspect: 0.707,
      slots: [
        { role: 'title', size: 0.090, tracking: 0.14, maxLines: 1, align: 'top', vertical: true, big: true, decor: 'title',
          candidates: [{ x: .74, y: .105, w: .17, h: .520 }, { x: .09, y: .105, w: .17, h: .520 }] },
        { role: 'catch', size: 0.032, tracking: 0.06, maxLines: 2, align: 'left', decor: 'accent',
          candidates: [{ x: .08, y: .120, w: .52, h: .105 }, { x: .08, y: .560, w: .58, h: .100 }] },
        { role: 'name', size: 0.024, tracking: 0.12, maxLines: 2, align: 'left', decor: 'plain',
          candidates: [{ x: .08, y: .250, w: .50, h: .055 }] },
        { role: 'badge', size: 0.019, tracking: 0.06, maxLines: 2, align: 'center', onSurface: 'laurelBadge', decor: 'plain',
          candidates: [{ x: .075, y: .058, w: .300, h: .068 }] },
        { role: 'release', size: 0.028, tracking: 0.10, maxLines: 1, align: 'center', onSurface: 'filmScrim', decor: 'plain',
          candidates: [{ x: .08, y: .858, w: .84, h: .042 }] },
        { role: 'credit', size: 0.016, tracking: 0.01, maxLines: 5, align: 'center', onSurface: 'filmScrim', decor: 'plain',
          candidates: [{ x: .07, y: .914, w: .86, h: .070 }] }
      ],
      surfaces: ['filmScrim', 'sideBand', 'laurelBadge'],
      overlays: ['grain', 'scanline', 'chromaEdge', 'halation']
    },
    {
      id: 'cinema-jp-top', aspect: 0.707,
      slots: [
        { role: 'tag', size: 0.021, tracking: 0.30, maxLines: 1, align: 'right', latin: true, decor: 'plain',
          candidates: [{ x: .42, y: .048, w: .50, h: .032 }] },
        { role: 'title', size: 0.118, tracking: 0.04, maxLines: 2, align: 'center', big: true, decor: 'title',
          candidates: [{ x: .06, y: .095, w: .88, h: .170 }, { x: .06, y: .560, w: .88, h: .170 }] },
        { role: 'catch', size: 0.034, tracking: 0.09, maxLines: 2, align: 'center', decor: 'accent',
          candidates: [{ x: .09, y: .285, w: .82, h: .095 }] },
        { role: 'name', size: 0.026, tracking: 0.16, maxLines: 2, align: 'center', decor: 'plain',
          candidates: [{ x: .10, y: .400, w: .80, h: .055 }] },
        { role: 'badge', size: 0.019, tracking: 0.06, maxLines: 2, align: 'center', onSurface: 'laurelBadge', decor: 'plain',
          candidates: [{ x: .075, y: .058, w: .300, h: .068 }] },
        { role: 'release', size: 0.028, tracking: 0.10, maxLines: 1, align: 'center', onSurface: 'filmScrim', decor: 'plain',
          candidates: [{ x: .08, y: .858, w: .84, h: .042 }] },
        { role: 'credit', size: 0.016, tracking: 0.01, maxLines: 5, align: 'center', onSurface: 'filmScrim', decor: 'plain',
          candidates: [{ x: .07, y: .914, w: .86, h: .070 }] }
      ],
      surfaces: ['filmScrim', 'topGradient', 'letterbox', 'laurelBadge'],
      overlays: ['grain', 'vignette', 'dust', 'halation']
    },
    {
      id: 'cinema-us-onesheet', aspect: 0.675,
      slots: [
        { role: 'name', size: 0.020, tracking: 0.22, maxLines: 1, align: 'center', latin: true, decor: 'plain',
          candidates: [{ x: .10, y: .042, w: .80, h: .032 }] },
        { role: 'title', size: 0.098, tracking: 0.10, maxLines: 2, align: 'center', big: true, decor: 'title',
          candidates: [{ x: .10, y: .645, w: .80, h: .110 }] },
        { role: 'tag', size: 0.020, tracking: 0.26, maxLines: 1, align: 'center', latin: true, decor: 'plain',
          candidates: [{ x: .14, y: .600, w: .72, h: .030 }] },
        { role: 'release', size: 0.020, tracking: 0.18, maxLines: 1, align: 'center', onSurface: 'filmScrim', decor: 'plain',
          candidates: [{ x: .18, y: .872, w: .64, h: .030 }] },
        { role: 'credit', size: 0.013, tracking: 0.01, maxLines: 5, align: 'center', onSurface: 'filmScrim', decor: 'plain',
          candidates: [{ x: .09, y: .918, w: .82, h: .056 }] }
      ],
      surfaces: ['filmScrim', 'bottomGradient'],
      overlays: ['grain', 'vignette', 'softFocus']
    }
  ],

  gravure: [
    {
      id: 'gravure-name-top', aspect: 0.708,
      slots: [
        { role: 'name', size: 0.098, tracking: 0.08, maxLines: 1, align: 'center', big: true, decor: 'title',
          candidates: [{ x: .06, y: .065, w: .88, h: .130 }] },
        { role: 'title', size: 0.048, tracking: 0.10, maxLines: 2, align: 'center', decor: 'accent',
          candidates: [{ x: .10, y: .205, w: .80, h: .090 }] },
        { role: 'catch', size: 0.026, tracking: 0.04, maxLines: 2, align: 'center', decor: 'plain',
          candidates: [{ x: .12, y: .305, w: .76, h: .060 }] },
        { role: 'badge', size: 0.022, tracking: 0.03, maxLines: 2, align: 'center', onSurface: 'sealBadge', decor: 'accent',
          candidates: [{ x: .655, y: .398, w: .245, h: .078 }] },
        { role: 'extra', size: 0.018, tracking: 0.03, maxLines: 1, align: 'left', onSurface: 'specBand', decor: 'plain',
          candidates: [{ x: .05, y: .862, w: .90, h: .046 }] },
        { role: 'code', size: 0.015, tracking: 0.12, maxLines: 1, align: 'left', latin: true, onSurface: 'specBand', decor: 'plain',
          candidates: [{ x: .05, y: .918, w: .40, h: .036 }] },
        { role: 'release', size: 0.015, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'specBand', decor: 'plain',
          candidates: [{ x: .49, y: .918, w: .24, h: .036 }] },
        { role: 'tag', size: 0.014, tracking: 0.06, maxLines: 1, align: 'left', onSurface: 'specBand', decor: 'plain',
          candidates: [{ x: .05, y: .960, w: .66, h: .030 }] }
      ],
      surfaces: ['specBand', 'sealBadge', 'hairRules', 'gridPlate'],
      overlays: ['sparkle', 'bloom', 'grain', 'lightLeak']
    },
    {
      id: 'gravure-name-bottom', aspect: 0.708,
      slots: [
        { role: 'title', size: 0.046, tracking: 0.10, maxLines: 2, align: 'center', decor: 'accent',
          candidates: [{ x: .10, y: .620, w: .80, h: .085 }, { x: .10, y: .090, w: .80, h: .085 }] },
        { role: 'name', size: 0.092, tracking: 0.08, maxLines: 1, align: 'center', big: true, decor: 'title',
          candidates: [{ x: .06, y: .715, w: .88, h: .120 }] },
        { role: 'catch', size: 0.024, tracking: 0.04, maxLines: 2, align: 'center', decor: 'plain',
          candidates: [{ x: .12, y: .535, w: .76, h: .060 }, { x: .12, y: .185, w: .76, h: .060 }] },
        { role: 'badge', size: 0.022, tracking: 0.03, maxLines: 2, align: 'center', onSurface: 'sealBadge', decor: 'accent',
          candidates: [{ x: .655, y: .398, w: .245, h: .078 }] },
        { role: 'extra', size: 0.018, tracking: 0.03, maxLines: 1, align: 'left', onSurface: 'specBand', decor: 'plain',
          candidates: [{ x: .05, y: .862, w: .90, h: .046 }] },
        { role: 'code', size: 0.015, tracking: 0.12, maxLines: 1, align: 'left', latin: true, onSurface: 'specBand', decor: 'plain',
          candidates: [{ x: .05, y: .918, w: .40, h: .036 }] },
        { role: 'release', size: 0.015, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'specBand', decor: 'plain',
          candidates: [{ x: .49, y: .918, w: .24, h: .036 }] },
        { role: 'credit', size: 0.014, tracking: 0.04, maxLines: 1, align: 'left', onSurface: 'specBand', decor: 'plain',
          candidates: [{ x: .05, y: .960, w: .66, h: .030 }] }
      ],
      surfaces: ['specBand', 'sealBadge', 'topGradient', 'hairRules'],
      overlays: ['sparkle', 'bloom', 'bokehDots', 'softFocus']
    },
    {
      id: 'gravure-split', aspect: 0.708,
      slots: [
        { role: 'name', size: 0.084, tracking: 0.06, maxLines: 1, align: 'left', big: true, decor: 'title',
          candidates: [{ x: .06, y: .105, w: .66, h: .115 }] },
        { role: 'title', size: 0.042, tracking: 0.08, maxLines: 2, align: 'left', decor: 'accent',
          candidates: [{ x: .06, y: .235, w: .60, h: .080 }] },
        { role: 'catch', size: 0.024, tracking: 0.04, maxLines: 2, align: 'left', decor: 'plain',
          candidates: [{ x: .06, y: .325, w: .58, h: .058 }] },
        { role: 'tag', size: 0.018, tracking: 0.24, maxLines: 1, align: 'left', latin: true, decor: 'plain',
          candidates: [{ x: .06, y: .062, w: .50, h: .030 }] },
        { role: 'badge', size: 0.022, tracking: 0.03, maxLines: 2, align: 'center', onSurface: 'sealBadge', decor: 'accent',
          candidates: [{ x: .655, y: .398, w: .245, h: .078 }] },
        { role: 'extra', size: 0.018, tracking: 0.03, maxLines: 1, align: 'left', onSurface: 'specBand', decor: 'plain',
          candidates: [{ x: .05, y: .862, w: .90, h: .046 }] },
        { role: 'code', size: 0.015, tracking: 0.12, maxLines: 1, align: 'left', latin: true, onSurface: 'specBand', decor: 'plain',
          candidates: [{ x: .05, y: .918, w: .40, h: .036 }] },
        { role: 'release', size: 0.015, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'specBand', decor: 'plain',
          candidates: [{ x: .49, y: .918, w: .24, h: .036 }] }
      ],
      surfaces: ['specBand', 'sealBadge', 'sideBand', 'discSpine'],
      overlays: ['sparkle', 'softFocus', 'grain', 'lightLeak']
    },
    {
      id: 'gravure-disc', aspect: 0.708,
      slots: [
        { role: 'name', size: 0.088, tracking: 0.08, maxLines: 1, align: 'center', big: true, decor: 'title',
          candidates: [{ x: .08, y: .690, w: .86, h: .115 }, { x: .08, y: .080, w: .86, h: .115 }] },
        { role: 'title', size: 0.044, tracking: 0.10, maxLines: 2, align: 'center', decor: 'accent',
          candidates: [{ x: .10, y: .595, w: .82, h: .082 }] },
        { role: 'catch', size: 0.024, tracking: 0.04, maxLines: 2, align: 'center', decor: 'plain',
          candidates: [{ x: .12, y: .215, w: .76, h: .058 }] },
        { role: 'badge', size: 0.022, tracking: 0.03, maxLines: 2, align: 'center', onSurface: 'sealBadge', decor: 'accent',
          candidates: [{ x: .655, y: .398, w: .245, h: .078 }] },
        { role: 'extra', size: 0.018, tracking: 0.03, maxLines: 1, align: 'left', onSurface: 'specBand', decor: 'plain',
          candidates: [{ x: .05, y: .862, w: .90, h: .046 }] },
        { role: 'code', size: 0.015, tracking: 0.12, maxLines: 1, align: 'left', latin: true, onSurface: 'specBand', decor: 'plain',
          candidates: [{ x: .05, y: .918, w: .40, h: .036 }] },
        { role: 'release', size: 0.015, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'specBand', decor: 'plain',
          candidates: [{ x: .49, y: .918, w: .24, h: .036 }] },
        { role: 'tag', size: 0.014, tracking: 0.06, maxLines: 1, align: 'left', onSurface: 'specBand', decor: 'plain',
          candidates: [{ x: .05, y: .960, w: .66, h: .030 }] }
      ],
      surfaces: ['specBand', 'sealBadge', 'discSpine', 'hairRules', 'barcode'],
      overlays: ['bloom', 'grain', 'bokehDots', 'halation']
    }
  ],

  novel: [
    {
      id: 'novel-tate-right', aspect: 0.709,
      slots: [
        { role: 'title', size: 0.088, tracking: 0.10, maxLines: 1, align: 'top', vertical: true, big: true, decor: 'title',
          candidates: [{ x: .700, y: .080, w: .180, h: .430 }] },
        { role: 'name', size: 0.034, tracking: 0.16, maxLines: 1, align: 'top', vertical: true, decor: 'plain',
          candidates: [{ x: .560, y: .120, w: .105, h: .270 }] },
        { role: 'catch', size: 0.046, tracking: 0.04, maxLines: 2, align: 'center', onSurface: 'obi', decor: 'accent',
          candidates: [{ x: .060, y: .690, w: .880, h: .100 }] },
        { role: 'extra', size: 0.024, tracking: 0.02, maxLines: 2, align: 'center', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: .060, y: .798, w: .880, h: .060 }] },
        { role: 'badge', size: 0.026, tracking: 0.04, maxLines: 1, align: 'center', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: .068, y: .878, w: .374, h: .046 }] },
        { role: 'tag', size: 0.020, tracking: 0.08, maxLines: 1, align: 'right', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: .500, y: .880, w: .440, h: .042 }] },
        { role: 'release', size: 0.017, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: .500, y: .940, w: .440, h: .036 }] },
        { role: 'credit', size: 0.017, tracking: 0.02, maxLines: 1, align: 'left', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: .060, y: .940, w: .400, h: .036 }] }
      ],
      surfaces: ['obi', 'frame'],
      overlays: ['paper', 'vignette', 'inkBleed']
    },
    {
      id: 'novel-tate-left', aspect: 0.695,
      slots: [
        { role: 'title', size: 0.082, tracking: 0.12, maxLines: 1, align: 'top', vertical: true, big: true, decor: 'title',
          candidates: [{ x: .095, y: .085, w: .175, h: .430 }] },
        { role: 'name', size: 0.032, tracking: 0.18, maxLines: 1, align: 'top', vertical: true, decor: 'plain',
          candidates: [{ x: .310, y: .120, w: .100, h: .260 }] },
        { role: 'catch', size: 0.044, tracking: 0.04, maxLines: 2, align: 'center', onSurface: 'obi', decor: 'accent',
          candidates: [{ x: .060, y: .690, w: .880, h: .100 }] },
        { role: 'extra', size: 0.024, tracking: 0.02, maxLines: 2, align: 'center', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: .060, y: .798, w: .880, h: .060 }] },
        { role: 'badge', size: 0.026, tracking: 0.04, maxLines: 1, align: 'center', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: .068, y: .878, w: .374, h: .046 }] },
        { role: 'tag', size: 0.020, tracking: 0.08, maxLines: 1, align: 'right', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: .500, y: .880, w: .440, h: .042 }] },
        { role: 'release', size: 0.017, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: .500, y: .940, w: .440, h: .036 }] }
      ],
      surfaces: ['obi', 'frame', 'topGradient'],
      overlays: ['paper', 'inkBleed', 'dust']
    },
    {
      id: 'novel-yoko', aspect: 0.691,
      slots: [
        { role: 'tag', size: 0.019, tracking: 0.24, maxLines: 1, align: 'center', decor: 'plain',
          candidates: [{ x: .12, y: .072, w: .76, h: .030 }] },
        { role: 'title', size: 0.090, tracking: 0.06, maxLines: 2, align: 'center', big: true, decor: 'title',
          candidates: [{ x: .09, y: .130, w: .82, h: .160 }, { x: .09, y: .400, w: .82, h: .160 }] },
        { role: 'name', size: 0.030, tracking: 0.20, maxLines: 1, align: 'center', decor: 'plain',
          candidates: [{ x: .14, y: .310, w: .72, h: .048 }] },
        { role: 'catch', size: 0.044, tracking: 0.04, maxLines: 2, align: 'center', onSurface: 'obi', decor: 'accent',
          candidates: [{ x: .060, y: .690, w: .880, h: .100 }] },
        { role: 'extra', size: 0.024, tracking: 0.02, maxLines: 2, align: 'center', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: .060, y: .798, w: .880, h: .060 }] },
        { role: 'badge', size: 0.026, tracking: 0.04, maxLines: 1, align: 'center', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: .068, y: .878, w: .374, h: .046 }] },
        { role: 'release', size: 0.017, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: .500, y: .940, w: .440, h: .036 }] },
        { role: 'credit', size: 0.017, tracking: 0.02, maxLines: 1, align: 'right', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: .500, y: .880, w: .440, h: .042 }] }
      ],
      surfaces: ['obi', 'frame'],
      overlays: ['paper', 'grain', 'inkBleed']
    },
    {
      id: 'novel-tate-plate', aspect: 0.709,
      slots: [
        { role: 'title', size: 0.078, tracking: 0.10, maxLines: 1, align: 'top', vertical: true, big: true, onSurface: 'plate', decor: 'title',
          candidates: [{ x: .620, y: .300, w: .150, h: .215 }] },
        { role: 'name', size: 0.028, tracking: 0.16, maxLines: 1, align: 'top', vertical: true, onSurface: 'plate', decor: 'plain',
          candidates: [{ x: .470, y: .310, w: .090, h: .170 }] },
        { role: 'catch', size: 0.044, tracking: 0.04, maxLines: 2, align: 'center', onSurface: 'obi', decor: 'accent',
          candidates: [{ x: .060, y: .690, w: .880, h: .100 }] },
        { role: 'extra', size: 0.024, tracking: 0.02, maxLines: 2, align: 'center', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: .060, y: .798, w: .880, h: .060 }] },
        { role: 'badge', size: 0.026, tracking: 0.04, maxLines: 1, align: 'center', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: .068, y: .878, w: .374, h: .046 }] },
        { role: 'tag', size: 0.020, tracking: 0.08, maxLines: 1, align: 'right', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: .500, y: .880, w: .440, h: .042 }] },
        { role: 'release', size: 0.017, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: .500, y: .940, w: .440, h: .036 }] },
        { role: 'credit', size: 0.017, tracking: 0.02, maxLines: 1, align: 'left', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: .060, y: .940, w: .400, h: .036 }] }
      ],
      surfaces: ['obi', 'plate', 'frame'],
      overlays: ['paper', 'vignette', 'inkBleed', 'dust']
    }
  ],

  asmr: [
    {
      id: 'asmr-wide-center', aspect: 1.333,
      slots: [
        { role: 'tag', size: 0.048, tracking: 0.03, maxLines: 2, align: 'center', onSurface: 'voiceBands', decor: 'accent',
          candidates: [{ x: .050, y: .022, w: .900, h: .086 }] },
        { role: 'title', size: 0.115, tracking: 0.03, maxLines: 2, align: 'center', big: true, decor: 'title',
          candidates: [{ x: .07, y: .310, w: .86, h: .200 }, { x: .07, y: .180, w: .86, h: .200 }] },
        { role: 'catch', size: 0.042, tracking: 0.05, maxLines: 2, align: 'center', decor: 'accent',
          candidates: [{ x: .10, y: .540, w: .80, h: .110 }] },
        { role: 'badge', size: 0.034, tracking: 0.04, maxLines: 1, align: 'center', decor: 'accent',
          candidates: [{ x: .12, y: .680, w: .76, h: .075 }] },
        { role: 'extra', size: 0.036, tracking: 0.03, maxLines: 1, align: 'left', onSurface: 'voiceBands', decor: 'plain',
          candidates: [{ x: .050, y: .862, w: .580, h: .052 }] },
        { role: 'credit', size: 0.036, tracking: 0.04, maxLines: 1, align: 'left', onSurface: 'voiceBands', decor: 'plain',
          candidates: [{ x: .050, y: .924, w: .580, h: .052 }] },
        { role: 'release', size: 0.030, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'voiceBands', decor: 'plain',
          candidates: [{ x: .660, y: .862, w: .290, h: .052 }] },
        { role: 'name', size: 0.032, tracking: 0.06, maxLines: 1, align: 'right', onSurface: 'voiceBands', decor: 'plain',
          candidates: [{ x: .660, y: .924, w: .290, h: .052 }] }
      ],
      surfaces: ['voiceBands', 'waveBand', 'gridPlate', 'tapeStrip'],
      overlays: ['softFocus', 'bloom', 'grain', 'bokehDots', 'lightLeak']
    },
    {
      id: 'asmr-wide-right', aspect: 1.333,
      slots: [
        { role: 'tag', size: 0.048, tracking: 0.03, maxLines: 2, align: 'left', onSurface: 'voiceBands', decor: 'accent',
          candidates: [{ x: .050, y: .022, w: .900, h: .086 }] },
        { role: 'title', size: 0.108, tracking: 0.03, maxLines: 3, align: 'right', big: true, decor: 'title',
          candidates: [{ x: .48, y: .200, w: .47, h: .290 }] },
        { role: 'catch', size: 0.040, tracking: 0.05, maxLines: 2, align: 'right', decor: 'accent',
          candidates: [{ x: .50, y: .520, w: .45, h: .110 }] },
        { role: 'badge', size: 0.032, tracking: 0.04, maxLines: 1, align: 'right', decor: 'accent',
          candidates: [{ x: .55, y: .660, w: .40, h: .070 }] },
        { role: 'extra', size: 0.036, tracking: 0.03, maxLines: 1, align: 'left', onSurface: 'voiceBands', decor: 'plain',
          candidates: [{ x: .050, y: .862, w: .580, h: .052 }] },
        { role: 'credit', size: 0.036, tracking: 0.04, maxLines: 1, align: 'left', onSurface: 'voiceBands', decor: 'plain',
          candidates: [{ x: .050, y: .924, w: .580, h: .052 }] },
        { role: 'release', size: 0.030, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'voiceBands', decor: 'plain',
          candidates: [{ x: .660, y: .862, w: .290, h: .052 }] },
        { role: 'name', size: 0.032, tracking: 0.06, maxLines: 1, align: 'right', onSurface: 'voiceBands', decor: 'plain',
          candidates: [{ x: .660, y: .924, w: .290, h: .052 }] }
      ],
      surfaces: ['voiceBands', 'waveBand', 'sideBand', 'gridPlate'],
      overlays: ['softFocus', 'bokehDots', 'bloom', 'lightLeak']
    },
    {
      id: 'asmr-wide-plate', aspect: 1.333,
      slots: [
        { role: 'tag', size: 0.048, tracking: 0.03, maxLines: 2, align: 'center', onSurface: 'voiceBands', decor: 'accent',
          candidates: [{ x: .050, y: .022, w: .900, h: .086 }] },
        { role: 'title', size: 0.105, tracking: 0.03, maxLines: 2, align: 'center', big: true, onSurface: 'roundPlate', decor: 'title',
          candidates: [{ x: .140, y: .330, w: .720, h: .150 }] },
        { role: 'catch', size: 0.038, tracking: 0.05, maxLines: 1, align: 'center', onSurface: 'roundPlate', decor: 'accent',
          candidates: [{ x: .160, y: .492, w: .680, h: .038 }] },
        { role: 'badge', size: 0.032, tracking: 0.04, maxLines: 1, align: 'center', decor: 'accent',
          candidates: [{ x: .18, y: .660, w: .64, h: .070 }] },
        { role: 'extra', size: 0.036, tracking: 0.03, maxLines: 1, align: 'left', onSurface: 'voiceBands', decor: 'plain',
          candidates: [{ x: .050, y: .862, w: .580, h: .052 }] },
        { role: 'credit', size: 0.036, tracking: 0.04, maxLines: 1, align: 'left', onSurface: 'voiceBands', decor: 'plain',
          candidates: [{ x: .050, y: .924, w: .580, h: .052 }] },
        { role: 'release', size: 0.030, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'voiceBands', decor: 'plain',
          candidates: [{ x: .660, y: .862, w: .290, h: .052 }] },
        { role: 'name', size: 0.032, tracking: 0.06, maxLines: 1, align: 'right', onSurface: 'voiceBands', decor: 'plain',
          candidates: [{ x: .660, y: .924, w: .290, h: .052 }] }
      ],
      surfaces: ['voiceBands', 'roundPlate', 'waveBand', 'discSpine'],
      overlays: ['softFocus', 'bloom', 'grain', 'bokehDots']
    },
    {
      id: 'asmr-wide-left', aspect: 1.333,
      slots: [
        { role: 'tag', size: 0.048, tracking: 0.03, maxLines: 2, align: 'left', onSurface: 'voiceBands', decor: 'accent',
          candidates: [{ x: .050, y: .022, w: .900, h: .086 }] },
        { role: 'title', size: 0.108, tracking: 0.03, maxLines: 3, align: 'left', big: true, decor: 'title',
          candidates: [{ x: .05, y: .200, w: .47, h: .290 }] },
        { role: 'catch', size: 0.040, tracking: 0.05, maxLines: 2, align: 'left', decor: 'accent',
          candidates: [{ x: .05, y: .520, w: .45, h: .110 }] },
        { role: 'badge', size: 0.032, tracking: 0.04, maxLines: 1, align: 'left', decor: 'accent',
          candidates: [{ x: .05, y: .660, w: .40, h: .070 }] },
        { role: 'extra', size: 0.036, tracking: 0.03, maxLines: 1, align: 'left', onSurface: 'voiceBands', decor: 'plain',
          candidates: [{ x: .050, y: .862, w: .580, h: .052 }] },
        { role: 'credit', size: 0.036, tracking: 0.04, maxLines: 1, align: 'left', onSurface: 'voiceBands', decor: 'plain',
          candidates: [{ x: .050, y: .924, w: .580, h: .052 }] },
        { role: 'release', size: 0.030, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'voiceBands', decor: 'plain',
          candidates: [{ x: .660, y: .862, w: .290, h: .052 }] },
        { role: 'name', size: 0.032, tracking: 0.06, maxLines: 1, align: 'right', onSurface: 'voiceBands', decor: 'plain',
          candidates: [{ x: .660, y: .924, w: .290, h: .052 }] }
      ],
      surfaces: ['voiceBands', 'waveBand', 'tapeStrip', 'gridPlate'],
      overlays: ['bokehDots', 'bloom', 'grain', 'neonGlow', 'softFocus']
    }
  ],

  game: [
    {
      id: 'game-switch', aspect: 0.618,
      slots: [
        { role: 'tag', size: 0.022, tracking: 0.16, maxLines: 1, align: 'right', latin: true, onSurface: 'gameChrome', decor: 'plain',
          candidates: [{ x: .420, y: .022, w: .545, h: .056 }] },
        { role: 'catch', size: 0.030, tracking: 0.08, maxLines: 2, align: 'center', decor: 'accent',
          candidates: [{ x: .08, y: .450, w: .84, h: .090 }, { x: .08, y: .150, w: .84, h: .090 }] },
        { role: 'title', size: 0.108, tracking: 0.02, maxLines: 2, align: 'center', big: true, decor: 'title',
          candidates: [{ x: .06, y: .570, w: .88, h: .175 }, { x: .06, y: .180, w: .88, h: .175 }] },
        { role: 'badge', size: 0.024, tracking: 0.16, maxLines: 1, align: 'center', latin: true, decor: 'accent',
          candidates: [{ x: .10, y: .762, w: .80, h: .048 }] },
        { role: 'credit', size: 0.015, tracking: 0.02, maxLines: 2, align: 'right', onSurface: 'gameChrome', decor: 'plain',
          candidates: [{ x: .250, y: .874, w: .705, h: .046 }] },
        { role: 'release', size: 0.016, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'gameChrome', decor: 'plain',
          candidates: [{ x: .250, y: .930, w: .705, h: .040 }] }
      ],
      surfaces: ['gameChrome', 'bottomGradient'],
      overlays: ['grain', 'bloom', 'chromaEdge', 'halation']
    },
    {
      id: 'game-ps5', aspect: 0.794,
      slots: [
        { role: 'tag', size: 0.022, tracking: 0.16, maxLines: 1, align: 'right', latin: true, onSurface: 'gameChrome', decor: 'plain',
          candidates: [{ x: .420, y: .022, w: .545, h: .056 }] },
        { role: 'title', size: 0.112, tracking: 0.02, maxLines: 2, align: 'center', big: true, decor: 'title',
          candidates: [{ x: .06, y: .580, w: .88, h: .180 }, { x: .06, y: .160, w: .88, h: .180 }] },
        { role: 'catch', size: 0.030, tracking: 0.08, maxLines: 2, align: 'center', decor: 'accent',
          candidates: [{ x: .08, y: .460, w: .84, h: .090 }] },
        { role: 'name', size: 0.022, tracking: 0.12, maxLines: 1, align: 'center', decor: 'plain',
          candidates: [{ x: .12, y: .775, w: .76, h: .042 }] },
        { role: 'badge', size: 0.024, tracking: 0.16, maxLines: 1, align: 'center', latin: true, decor: 'accent',
          candidates: [{ x: .10, y: .380, w: .80, h: .048 }] },
        { role: 'credit', size: 0.015, tracking: 0.02, maxLines: 2, align: 'right', onSurface: 'gameChrome', decor: 'plain',
          candidates: [{ x: .250, y: .874, w: .705, h: .046 }] },
        { role: 'release', size: 0.016, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'gameChrome', decor: 'plain',
          candidates: [{ x: .250, y: .930, w: .705, h: .040 }] }
      ],
      surfaces: ['gameChrome', 'bottomGradient', 'cornerPlate'],
      overlays: ['grain', 'halation', 'chromaEdge', 'neonGlow']
    },
    {
      id: 'game-classic', aspect: 0.716,
      slots: [
        { role: 'tag', size: 0.022, tracking: 0.16, maxLines: 1, align: 'right', latin: true, onSurface: 'gameChrome', decor: 'plain',
          candidates: [{ x: .420, y: .022, w: .545, h: .056 }] },
        { role: 'title', size: 0.100, tracking: 0.02, maxLines: 2, align: 'left', big: true, decor: 'title',
          candidates: [{ x: .05, y: .175, w: .68, h: .175 }, { x: .05, y: .540, w: .72, h: .175 }] },
        { role: 'catch', size: 0.028, tracking: 0.07, maxLines: 2, align: 'left', decor: 'accent',
          candidates: [{ x: .05, y: .370, w: .62, h: .085 }] },
        { role: 'name', size: 0.022, tracking: 0.12, maxLines: 1, align: 'left', decor: 'plain',
          candidates: [{ x: .05, y: .470, w: .58, h: .042 }] },
        { role: 'extra', size: 0.018, tracking: 0.04, maxLines: 2, align: 'left', decor: 'plain',
          candidates: [{ x: .05, y: .745, w: .55, h: .056 }] },
        { role: 'credit', size: 0.015, tracking: 0.02, maxLines: 2, align: 'right', onSurface: 'gameChrome', decor: 'plain',
          candidates: [{ x: .250, y: .874, w: .705, h: .046 }] },
        { role: 'release', size: 0.016, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'gameChrome', decor: 'plain',
          candidates: [{ x: .250, y: .930, w: .705, h: .040 }] }
      ],
      surfaces: ['gameChrome', 'sideBand', 'discSpine'],
      overlays: ['scanline', 'grain', 'chromaEdge', 'neonGlow']
    },
    {
      id: 'game-edition', aspect: 0.788,
      slots: [
        { role: 'tag', size: 0.022, tracking: 0.16, maxLines: 1, align: 'right', latin: true, onSurface: 'gameChrome', decor: 'plain',
          candidates: [{ x: .420, y: .022, w: .545, h: .056 }] },
        { role: 'title', size: 0.086, tracking: 0.02, maxLines: 2, align: 'center', big: true, onSurface: 'plate', decor: 'title',
          candidates: [{ x: .150, y: .312, w: .700, h: .125 }] },
        { role: 'badge', size: 0.026, tracking: 0.18, maxLines: 1, align: 'center', latin: true, onSurface: 'plate', decor: 'accent',
          candidates: [{ x: .170, y: .455, w: .660, h: .046 }] },
        { role: 'catch', size: 0.028, tracking: 0.07, maxLines: 2, align: 'center', decor: 'accent',
          candidates: [{ x: .08, y: .600, w: .84, h: .085 }] },
        { role: 'name', size: 0.022, tracking: 0.12, maxLines: 1, align: 'center', decor: 'plain',
          candidates: [{ x: .12, y: .715, w: .76, h: .042 }] },
        { role: 'extra', size: 0.018, tracking: 0.04, maxLines: 2, align: 'center', decor: 'plain',
          candidates: [{ x: .12, y: .775, w: .76, h: .052 }] },
        { role: 'credit', size: 0.015, tracking: 0.02, maxLines: 2, align: 'right', onSurface: 'gameChrome', decor: 'plain',
          candidates: [{ x: .250, y: .874, w: .705, h: .046 }] },
        { role: 'release', size: 0.016, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'gameChrome', decor: 'plain',
          candidates: [{ x: .250, y: .930, w: .705, h: .040 }] }
      ],
      surfaces: ['gameChrome', 'plate', 'cornerPlate', 'bottomGradient'],
      overlays: ['grain', 'neonGlow', 'halation', 'bloom']
    }
  ],

  adult: [
    {
      id: 'adult-tanpin', aspect: 0.708,
      slots: [
        { role: 'tag', size: 0.026, tracking: 0.06, maxLines: 1, align: 'center', onSurface: 'avLayers', decor: 'accent',
          candidates: [{ x: .050, y: .012, w: .900, h: .046 }] },
        { role: 'title', size: 0.086, tracking: 0.01, maxLines: 4, align: 'center', big: true, tiered: true, decor: 'title',
          candidates: [{ x: .06, y: .120, w: .88, h: .300 }] },
        { role: 'name', size: 0.052, tracking: 0.06, maxLines: 1, align: 'center', decor: 'accent',
          candidates: [{ x: .10, y: .460, w: .80, h: .075 }, { x: .10, y: .590, w: .80, h: .075 }] },
        { role: 'badge', size: 0.032, tracking: 0.03, maxLines: 1, align: 'center', onSurface: 'avLayers', decor: 'accent',
          candidates: [{ x: .060, y: .712, w: .590, h: .052 }] },
        { role: 'extra', size: 0.017, tracking: 0.03, maxLines: 1, align: 'left', onSurface: 'avLayers', decor: 'plain',
          candidates: [{ x: .050, y: .872, w: .590, h: .044 }] },
        { role: 'credit', size: 0.016, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'avLayers', decor: 'plain',
          candidates: [{ x: .660, y: .872, w: .290, h: .044 }] },
        { role: 'code', size: 0.017, tracking: 0.12, maxLines: 1, align: 'left', latin: true, onSurface: 'avLayers', decor: 'plain',
          candidates: [{ x: .050, y: .928, w: .400, h: .042 }] },
        { role: 'release', size: 0.017, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'avLayers', decor: 'plain',
          candidates: [{ x: .470, y: .928, w: .255, h: .042 }] }
      ],
      surfaces: ['avLayers', 'boldFrame', 'barcode'],
      overlays: ['grain', 'neonGlow', 'halation', 'bloom']
    },
    {
      id: 'adult-kikaku', aspect: 0.708,
      slots: [
        { role: 'tag', size: 0.026, tracking: 0.06, maxLines: 1, align: 'center', onSurface: 'avLayers', decor: 'accent',
          candidates: [{ x: .050, y: .012, w: .900, h: .046 }] },
        { role: 'title', size: 0.104, tracking: 0.01, maxLines: 4, align: 'center', big: true, tiered: true, decor: 'title',
          candidates: [{ x: .04, y: .095, w: .92, h: .470 }] },
        { role: 'name', size: 0.048, tracking: 0.06, maxLines: 1, align: 'left', decor: 'accent',
          candidates: [{ x: .05, y: .590, w: .70, h: .070 }] },
        { role: 'badge', size: 0.032, tracking: 0.03, maxLines: 1, align: 'center', onSurface: 'avLayers', decor: 'accent',
          candidates: [{ x: .060, y: .712, w: .590, h: .052 }] },
        { role: 'extra', size: 0.017, tracking: 0.03, maxLines: 1, align: 'left', onSurface: 'avLayers', decor: 'plain',
          candidates: [{ x: .050, y: .872, w: .590, h: .044 }] },
        { role: 'credit', size: 0.016, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'avLayers', decor: 'plain',
          candidates: [{ x: .660, y: .872, w: .290, h: .044 }] },
        { role: 'code', size: 0.017, tracking: 0.12, maxLines: 1, align: 'left', latin: true, onSurface: 'avLayers', decor: 'plain',
          candidates: [{ x: .050, y: .928, w: .400, h: .042 }] },
        { role: 'release', size: 0.017, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'avLayers', decor: 'plain',
          candidates: [{ x: .470, y: .928, w: .255, h: .042 }] }
      ],
      surfaces: ['avLayers', 'boldFrame', 'tapeStrip', 'barcode'],
      overlays: ['neonGlow', 'halation', 'grain', 'chromaEdge']
    },
    {
      id: 'adult-mixed', aspect: 0.708,
      slots: [
        { role: 'tag', size: 0.026, tracking: 0.06, maxLines: 1, align: 'center', onSurface: 'avLayers', decor: 'accent',
          candidates: [{ x: .050, y: .012, w: .900, h: .046 }] },
        { role: 'title', size: 0.098, tracking: 0.01, maxLines: 4, align: 'left', big: true, tiered: true, decor: 'title',
          candidates: [{ x: .05, y: .105, w: .62, h: .420 }] },
        { role: 'name', size: 0.046, tracking: 0.14, maxLines: 1, align: 'top', vertical: true, decor: 'accent',
          candidates: [{ x: .760, y: .110, w: .150, h: .330 }] },
        { role: 'badge', size: 0.032, tracking: 0.03, maxLines: 1, align: 'center', onSurface: 'avLayers', decor: 'accent',
          candidates: [{ x: .060, y: .712, w: .590, h: .052 }] },
        { role: 'extra', size: 0.017, tracking: 0.03, maxLines: 1, align: 'left', onSurface: 'avLayers', decor: 'plain',
          candidates: [{ x: .050, y: .872, w: .590, h: .044 }] },
        { role: 'credit', size: 0.016, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'avLayers', decor: 'plain',
          candidates: [{ x: .660, y: .872, w: .290, h: .044 }] },
        { role: 'code', size: 0.017, tracking: 0.12, maxLines: 1, align: 'left', latin: true, onSurface: 'avLayers', decor: 'plain',
          candidates: [{ x: .050, y: .928, w: .400, h: .042 }] },
        { role: 'release', size: 0.017, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'avLayers', decor: 'plain',
          candidates: [{ x: .470, y: .928, w: .255, h: .042 }] }
      ],
      surfaces: ['avLayers', 'discSpine', 'tapeStrip'],
      overlays: ['grain', 'bokehDots', 'neonGlow', 'lightLeak']
    },
    {
      id: 'adult-frame', aspect: 0.708,
      slots: [
        { role: 'tag', size: 0.026, tracking: 0.06, maxLines: 1, align: 'center', onSurface: 'avLayers', decor: 'accent',
          candidates: [{ x: .050, y: .012, w: .900, h: .046 }] },
        { role: 'title', size: 0.092, tracking: 0.01, maxLines: 4, align: 'center', big: true, tiered: true, decor: 'title',
          candidates: [{ x: .08, y: .135, w: .84, h: .340 }] },
        { role: 'name', size: 0.050, tracking: 0.08, maxLines: 1, align: 'center', decor: 'accent',
          candidates: [{ x: .12, y: .520, w: .76, h: .075 }] },
        { role: 'badge', size: 0.032, tracking: 0.03, maxLines: 1, align: 'center', onSurface: 'avLayers', decor: 'accent',
          candidates: [{ x: .060, y: .712, w: .590, h: .052 }] },
        { role: 'extra', size: 0.017, tracking: 0.03, maxLines: 1, align: 'left', onSurface: 'avLayers', decor: 'plain',
          candidates: [{ x: .050, y: .872, w: .590, h: .044 }] },
        { role: 'credit', size: 0.016, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'avLayers', decor: 'plain',
          candidates: [{ x: .660, y: .872, w: .290, h: .044 }] },
        { role: 'code', size: 0.017, tracking: 0.12, maxLines: 1, align: 'left', latin: true, onSurface: 'avLayers', decor: 'plain',
          candidates: [{ x: .050, y: .928, w: .400, h: .042 }] },
        { role: 'release', size: 0.017, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'avLayers', decor: 'plain',
          candidates: [{ x: .470, y: .928, w: .255, h: .042 }] }
      ],
      surfaces: ['avLayers', 'boldFrame', 'discSpine', 'barcode'],
      overlays: ['grain', 'vignette', 'inkBleed', 'halation']
    }
  ]
};
