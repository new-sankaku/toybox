export const SURFACE_ANCHORS = {
  filmScrim: { x: 0.000, y: 0.720, w: 1.000, h: 0.280 },
  billingPlate: { x: 0.000, y: 0.900, w: 1.000, h: 0.100 },
  specBand: { x: 0.000, y: 0.815, w: 1.000, h: 0.185 },
  obi: { x: 0.000, y: 0.660, w: 1.000, h: 0.340 },
  obiBox: { x: 0.045, y: 0.904, w: 0.430, h: 0.060 },
  voiceTopStrip: { x: 0.000, y: 0.000, w: 1.000, h: 0.048 },
  voicePlate: { x: 0.035, y: 0.755, w: 0.430, h: 0.155 },
  voiceFootBand: { x: 0.000, y: 0.928, w: 1.000, h: 0.072 },
  circleMark: { x: 0.040, y: 0.075, w: 0.150, h: 0.200 },
  platformBand: { x: 0.000, y: 0.000, w: 1.000, h: 0.100 },
  publisherRow: { x: 0.235, y: 0.858, w: 0.725, h: 0.128 },
  ratingPlate: { x: 0.030, y: 0.852, w: 0.112, h: 0.112 },
  seriesBand: { x: 0.000, y: 0.000, w: 1.000, h: 0.070 },
  avSash: { x: 0.040, y: 0.616, w: 0.640, h: 0.076, deg: -16 },
  avSpecBand: { x: 0.000, y: 0.855, w: 1.000, h: 0.145 },
  gridPlate: { x: 0.020, y: 0.828, w: 0.960, h: 0.160 },
  plate: { x: 0.080, y: 0.230, w: 0.840, h: 0.330 },
  laurelBadge: { x: 0.055, y: 0.045, w: 0.340, h: 0.100 },
  laurelText: { x: 0.100, y: 0.058, w: 0.250, h: 0.074 },
  barcode: { x: 0.740, y: 0.925, w: 0.200, h: 0.055 },
  cornerPlate: { x: 0.620, y: 0.115, w: 0.320, h: 0.075 },
  waveBand: { x: 0.480, y: 0.882, w: 0.500, h: 0.042 },
  sealBadge: { x: 0.633, y: 0.232, w: 0.290, h: 0.410 }
};

export const LAYOUTS = {
  cinema: [
    {
      id: 'cinema-jp-b1', aspect: 0.707,
      slots: [
        { role: 'badge', size: 0.017, tracking: 0.05, maxLines: 3, align: 'center', onSurface: 'laurelBadge', decor: 'plain',
          candidates: [{ x: 0.100, y: 0.058, w: 0.250, h: 0.074 }] },
        { role: 'catch', size: 0.038, tracking: 0.06, maxLines: 2, align: 'center', decor: 'plain',
          candidates: [{ x: 0.100, y: 0.170, w: 0.740, h: 0.085 }, { x: 0.100, y: 0.400, w: 0.740, h: 0.085 }] },
        { role: 'name', size: 0.026, tracking: 0.14, maxLines: 2, align: 'center', decor: 'plain',
          candidates: [{ x: 0.120, y: 0.470, w: 0.720, h: 0.046 }, { x: 0.120, y: 0.280, w: 0.720, h: 0.046 }] },
        { role: 'title', size: 0.125, tracking: 0.04, maxLines: 2, align: 'center', big: true, decor: 'title',
          candidates: [{ x: 0.100, y: 0.560, w: 0.800, h: 0.140 }, { x: 0.100, y: 0.190, w: 0.800, h: 0.140 }] },
        { role: 'extra', size: 0.024, tracking: 0.28, maxLines: 1, align: 'center', latin: true, decor: 'plain',
          candidates: [{ x: 0.200, y: 0.720, w: 0.560, h: 0.030 }] },
        { role: 'release', size: 0.030, tracking: 0.10, maxLines: 1, align: 'center', onSurface: 'filmScrim', decor: 'plain',
          candidates: [{ x: 0.160, y: 0.856, w: 0.640, h: 0.036 }] },
        { role: 'credit', size: 0.016, tracking: 0.01, maxLines: 5, align: 'center', onSurface: 'billingPlate', decor: 'plain',
          candidates: [{ x: 0.080, y: 0.916, w: 0.840, h: 0.054 }] }
      ],
      surfaces: ['filmScrim', 'billingPlate', 'laurelBadge', 'topGradient'],
      overlays: ['grain', 'vignette', 'halation']
    },
    {
      id: 'cinema-jp-vertical', aspect: 0.707,
      slots: [
        { role: 'title', size: 0.090, tracking: 0.14, maxLines: 1, align: 'top', vertical: true, big: true, decor: 'title',
          candidates: [{ x: 0.740, y: 0.105, w: 0.170, h: 0.520 }, { x: 0.090, y: 0.105, w: 0.170, h: 0.520 }] },
        { role: 'catch', size: 0.032, tracking: 0.06, maxLines: 2, align: 'left', decor: 'plain',
          candidates: [{ x: 0.080, y: 0.175, w: 0.520, h: 0.105 }, { x: 0.080, y: 0.560, w: 0.580, h: 0.100 }] },
        { role: 'name', size: 0.024, tracking: 0.12, maxLines: 2, align: 'left', decor: 'plain',
          candidates: [{ x: 0.080, y: 0.300, w: 0.500, h: 0.055 }] },
        { role: 'badge', size: 0.017, tracking: 0.05, maxLines: 3, align: 'center', onSurface: 'laurelBadge', decor: 'plain',
          candidates: [{ x: 0.100, y: 0.058, w: 0.250, h: 0.074 }] },
        { role: 'release', size: 0.028, tracking: 0.10, maxLines: 1, align: 'center', onSurface: 'filmScrim', decor: 'plain',
          candidates: [{ x: 0.160, y: 0.856, w: 0.640, h: 0.036 }] },
        { role: 'credit', size: 0.016, tracking: 0.01, maxLines: 5, align: 'center', onSurface: 'billingPlate', decor: 'plain',
          candidates: [{ x: 0.080, y: 0.916, w: 0.840, h: 0.054 }] }
      ],
      surfaces: ['filmScrim', 'billingPlate', 'sideBand', 'laurelBadge'],
      overlays: ['grain', 'scanline', 'chromaEdge', 'halation']
    },
    {
      id: 'cinema-jp-top', aspect: 0.707,
      slots: [
        { role: 'tag', size: 0.021, tracking: 0.30, maxLines: 1, align: 'right', latin: true, decor: 'plain',
          candidates: [{ x: 0.420, y: 0.048, w: 0.500, h: 0.032 }] },
        { role: 'badge', size: 0.017, tracking: 0.05, maxLines: 3, align: 'center', onSurface: 'laurelBadge', decor: 'plain',
          candidates: [{ x: 0.100, y: 0.058, w: 0.250, h: 0.074 }] },
        { role: 'title', size: 0.118, tracking: 0.04, maxLines: 2, align: 'center', big: true, decor: 'title',
          candidates: [{ x: 0.080, y: 0.160, w: 0.840, h: 0.150 }, { x: 0.080, y: 0.560, w: 0.840, h: 0.150 }] },
        { role: 'catch', size: 0.034, tracking: 0.09, maxLines: 2, align: 'center', decor: 'plain',
          candidates: [{ x: 0.120, y: 0.330, w: 0.760, h: 0.080 }] },
        { role: 'name', size: 0.026, tracking: 0.16, maxLines: 2, align: 'center', decor: 'plain',
          candidates: [{ x: 0.140, y: 0.430, w: 0.720, h: 0.046 }] },
        { role: 'release', size: 0.028, tracking: 0.10, maxLines: 1, align: 'center', onSurface: 'filmScrim', decor: 'plain',
          candidates: [{ x: 0.160, y: 0.856, w: 0.640, h: 0.036 }] },
        { role: 'credit', size: 0.016, tracking: 0.01, maxLines: 5, align: 'center', onSurface: 'billingPlate', decor: 'plain',
          candidates: [{ x: 0.080, y: 0.916, w: 0.840, h: 0.054 }] }
      ],
      surfaces: ['filmScrim', 'billingPlate', 'topGradient', 'letterbox', 'laurelBadge'],
      overlays: ['grain', 'vignette', 'dust', 'halation']
    },
    {
      id: 'cinema-us-onesheet', aspect: 0.675,
      slots: [
        { role: 'name', size: 0.020, tracking: 0.22, maxLines: 1, align: 'center', latin: true, decor: 'plain',
          candidates: [{ x: 0.190, y: 0.042, w: 0.620, h: 0.026 }] },
        { role: 'tag', size: 0.020, tracking: 0.26, maxLines: 1, align: 'center', latin: true, decor: 'plain',
          candidates: [{ x: 0.230, y: 0.600, w: 0.540, h: 0.026 }] },
        { role: 'title', size: 0.098, tracking: 0.10, maxLines: 2, align: 'center', big: true, decor: 'title',
          candidates: [{ x: 0.190, y: 0.640, w: 0.620, h: 0.085 }] },
        { role: 'release', size: 0.020, tracking: 0.18, maxLines: 1, align: 'center', onSurface: 'filmScrim', decor: 'plain',
          candidates: [{ x: 0.250, y: 0.866, w: 0.500, h: 0.026 }] },
        { role: 'credit', size: 0.013, tracking: 0.01, maxLines: 5, align: 'center', onSurface: 'billingPlate', decor: 'plain',
          candidates: [{ x: 0.130, y: 0.918, w: 0.740, h: 0.042 }] }
      ],
      surfaces: ['filmScrim', 'billingPlate', 'bottomGradient'],
      overlays: ['grain', 'vignette', 'softFocus']
    }
  ],

  gravure: [
    {
      id: 'gravure-name-top', aspect: 0.708,
      slots: [
        { role: 'name', size: 0.098, tracking: 0.08, maxLines: 1, align: 'center', big: true, decor: 'title',
          candidates: [{ x: 0.130, y: 0.070, w: 0.740, h: 0.105 }] },
        { role: 'title', size: 0.048, tracking: 0.10, maxLines: 2, align: 'center', decor: 'plain',
          candidates: [{ x: 0.170, y: 0.195, w: 0.660, h: 0.070 }] },
        { role: 'catch', size: 0.026, tracking: 0.04, maxLines: 2, align: 'center', decor: 'plain',
          candidates: [{ x: 0.190, y: 0.285, w: 0.620, h: 0.048 }] },
        { role: 'tag', size: 0.018, tracking: 0.10, maxLines: 1, align: 'center', latin: true, decor: 'plain',
          candidates: [{ x: 0.190, y: 0.348, w: 0.620, h: 0.034 }] },
        { role: 'badge', size: 0.022, tracking: 0.03, maxLines: 2, align: 'center', onSurface: 'sealBadge', decor: 'accent',
          candidates: [{ x: 0.655, y: 0.398, w: 0.245, h: 0.078 }] },
        { role: 'extra', size: 0.019, tracking: 0.03, maxLines: 1, align: 'left', onSurface: 'specBand', decor: 'plain',
          candidates: [{ x: 0.050, y: 0.832, w: 0.900, h: 0.052 }] },
        { role: 'code', size: 0.017, tracking: 0.12, maxLines: 1, align: 'left', latin: true, onSurface: 'specBand', decor: 'plain',
          candidates: [{ x: 0.050, y: 0.900, w: 0.400, h: 0.046 }] },
        { role: 'release', size: 0.017, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'specBand', decor: 'plain',
          candidates: [{ x: 0.490, y: 0.900, w: 0.240, h: 0.046 }] }
      ],
      surfaces: ['specBand', 'sealBadge', 'hairRules', 'gridPlate', 'tapeStrip'],
      overlays: ['sparkle', 'bloom', 'grain', 'lightLeak']
    },
    {
      id: 'gravure-name-bottom', aspect: 0.708,
      slots: [
        { role: 'title', size: 0.046, tracking: 0.10, maxLines: 2, align: 'center', decor: 'plain',
          candidates: [{ x: 0.170, y: 0.630, w: 0.660, h: 0.068 }, { x: 0.170, y: 0.100, w: 0.660, h: 0.068 }] },
        { role: 'name', size: 0.092, tracking: 0.08, maxLines: 1, align: 'center', big: true, decor: 'title',
          candidates: [{ x: 0.130, y: 0.700, w: 0.740, h: 0.100 }] },
        { role: 'catch', size: 0.024, tracking: 0.04, maxLines: 2, align: 'center', decor: 'plain',
          candidates: [{ x: 0.190, y: 0.545, w: 0.620, h: 0.048 }, { x: 0.190, y: 0.190, w: 0.620, h: 0.048 }] },
        { role: 'credit', size: 0.018, tracking: 0.06, maxLines: 1, align: 'center', decor: 'plain',
          candidates: [{ x: 0.190, y: 0.348, w: 0.620, h: 0.034 }] },
        { role: 'badge', size: 0.022, tracking: 0.03, maxLines: 2, align: 'center', onSurface: 'sealBadge', decor: 'accent',
          candidates: [{ x: 0.655, y: 0.398, w: 0.245, h: 0.078 }] },
        { role: 'extra', size: 0.019, tracking: 0.03, maxLines: 1, align: 'left', onSurface: 'specBand', decor: 'plain',
          candidates: [{ x: 0.050, y: 0.832, w: 0.900, h: 0.052 }] },
        { role: 'code', size: 0.017, tracking: 0.12, maxLines: 1, align: 'left', latin: true, onSurface: 'specBand', decor: 'plain',
          candidates: [{ x: 0.050, y: 0.900, w: 0.400, h: 0.046 }] },
        { role: 'release', size: 0.017, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'specBand', decor: 'plain',
          candidates: [{ x: 0.490, y: 0.900, w: 0.240, h: 0.046 }] }
      ],
      surfaces: ['specBand', 'sealBadge', 'topGradient', 'hairRules'],
      overlays: ['sparkle', 'bloom', 'bokehDots', 'softFocus']
    },
    {
      id: 'gravure-split', aspect: 0.708,
      slots: [
        { role: 'tag', size: 0.018, tracking: 0.24, maxLines: 1, align: 'left', latin: true, decor: 'plain',
          candidates: [{ x: 0.060, y: 0.062, w: 0.500, h: 0.030 }] },
        { role: 'name', size: 0.084, tracking: 0.06, maxLines: 1, align: 'left', big: true, decor: 'title',
          candidates: [{ x: 0.060, y: 0.105, w: 0.660, h: 0.115 }] },
        { role: 'title', size: 0.042, tracking: 0.08, maxLines: 2, align: 'left', decor: 'plain',
          candidates: [{ x: 0.060, y: 0.235, w: 0.600, h: 0.080 }] },
        { role: 'catch', size: 0.024, tracking: 0.04, maxLines: 2, align: 'left', decor: 'plain',
          candidates: [{ x: 0.060, y: 0.325, w: 0.580, h: 0.058 }] },
        { role: 'badge', size: 0.022, tracking: 0.03, maxLines: 2, align: 'center', onSurface: 'sealBadge', decor: 'accent',
          candidates: [{ x: 0.655, y: 0.398, w: 0.245, h: 0.078 }] },
        { role: 'extra', size: 0.019, tracking: 0.03, maxLines: 1, align: 'left', onSurface: 'specBand', decor: 'plain',
          candidates: [{ x: 0.050, y: 0.832, w: 0.900, h: 0.052 }] },
        { role: 'code', size: 0.017, tracking: 0.12, maxLines: 1, align: 'left', latin: true, onSurface: 'specBand', decor: 'plain',
          candidates: [{ x: 0.050, y: 0.900, w: 0.400, h: 0.046 }] },
        { role: 'release', size: 0.017, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'specBand', decor: 'plain',
          candidates: [{ x: 0.490, y: 0.900, w: 0.240, h: 0.046 }] }
      ],
      surfaces: ['specBand', 'sealBadge', 'sideBand', 'discSpine'],
      overlays: ['sparkle', 'softFocus', 'grain', 'lightLeak']
    },
    {
      id: 'gravure-disc', aspect: 0.708,
      slots: [
        { role: 'name', size: 0.088, tracking: 0.08, maxLines: 1, align: 'center', big: true, decor: 'title',
          candidates: [{ x: 0.140, y: 0.690, w: 0.720, h: 0.098 }, { x: 0.140, y: 0.085, w: 0.720, h: 0.098 }] },
        { role: 'title', size: 0.044, tracking: 0.10, maxLines: 2, align: 'center', decor: 'plain',
          candidates: [{ x: 0.160, y: 0.590, w: 0.680, h: 0.068 }] },
        { role: 'catch', size: 0.024, tracking: 0.04, maxLines: 2, align: 'center', decor: 'plain',
          candidates: [{ x: 0.190, y: 0.215, w: 0.620, h: 0.048 }] },
        { role: 'tag', size: 0.018, tracking: 0.10, maxLines: 1, align: 'center', latin: true, decor: 'plain',
          candidates: [{ x: 0.190, y: 0.348, w: 0.620, h: 0.034 }] },
        { role: 'badge', size: 0.022, tracking: 0.03, maxLines: 2, align: 'center', onSurface: 'sealBadge', decor: 'accent',
          candidates: [{ x: 0.655, y: 0.398, w: 0.245, h: 0.078 }] },
        { role: 'extra', size: 0.019, tracking: 0.03, maxLines: 1, align: 'left', onSurface: 'specBand', decor: 'plain',
          candidates: [{ x: 0.050, y: 0.832, w: 0.900, h: 0.052 }] },
        { role: 'code', size: 0.017, tracking: 0.12, maxLines: 1, align: 'left', latin: true, onSurface: 'specBand', decor: 'plain',
          candidates: [{ x: 0.050, y: 0.900, w: 0.400, h: 0.046 }] },
        { role: 'release', size: 0.017, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'specBand', decor: 'plain',
          candidates: [{ x: 0.490, y: 0.900, w: 0.240, h: 0.046 }] }
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
          candidates: [{ x: 0.715, y: 0.045, w: 0.195, h: 0.480 }] },
        { role: 'name', size: 0.034, tracking: 0.16, maxLines: 1, align: 'top', vertical: true, decor: 'plain',
          candidates: [{ x: 0.585, y: 0.060, w: 0.110, h: 0.300 }] },
        { role: 'catch', size: 0.046, tracking: 0.04, maxLines: 2, align: 'center', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: 0.045, y: 0.680, w: 0.910, h: 0.128 }] },
        { role: 'extra', size: 0.024, tracking: 0.02, maxLines: 2, align: 'center', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: 0.045, y: 0.816, w: 0.910, h: 0.082 }] },
        { role: 'badge', size: 0.026, tracking: 0.04, maxLines: 1, align: 'center', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: 0.058, y: 0.911, w: 0.404, h: 0.046 }] },
        { role: 'tag', size: 0.020, tracking: 0.08, maxLines: 1, align: 'right', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: 0.500, y: 0.904, w: 0.455, h: 0.040 }] },
        { role: 'release', size: 0.017, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: 0.500, y: 0.950, w: 0.455, h: 0.034 }] },
        { role: 'credit', size: 0.017, tracking: 0.02, maxLines: 1, align: 'left', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: 0.045, y: 0.970, w: 0.430, h: 0.026 }] }
      ],
      surfaces: ['obi', 'frame'],
      overlays: ['paper', 'vignette', 'inkBleed']
    },
    {
      id: 'novel-tate-left', aspect: 0.695,
      slots: [
        { role: 'title', size: 0.082, tracking: 0.12, maxLines: 1, align: 'top', vertical: true, big: true, decor: 'title',
          candidates: [{ x: 0.085, y: 0.048, w: 0.190, h: 0.475 }] },
        { role: 'name', size: 0.032, tracking: 0.18, maxLines: 1, align: 'top', vertical: true, decor: 'plain',
          candidates: [{ x: 0.305, y: 0.062, w: 0.110, h: 0.295 }] },
        { role: 'catch', size: 0.046, tracking: 0.04, maxLines: 2, align: 'center', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: 0.045, y: 0.680, w: 0.910, h: 0.128 }] },
        { role: 'extra', size: 0.024, tracking: 0.02, maxLines: 2, align: 'center', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: 0.045, y: 0.816, w: 0.910, h: 0.082 }] },
        { role: 'badge', size: 0.026, tracking: 0.04, maxLines: 1, align: 'center', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: 0.058, y: 0.911, w: 0.404, h: 0.046 }] },
        { role: 'tag', size: 0.020, tracking: 0.08, maxLines: 1, align: 'right', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: 0.500, y: 0.904, w: 0.455, h: 0.040 }] },
        { role: 'release', size: 0.017, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: 0.500, y: 0.950, w: 0.455, h: 0.034 }] },
        { role: 'credit', size: 0.017, tracking: 0.02, maxLines: 1, align: 'left', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: 0.045, y: 0.970, w: 0.430, h: 0.026 }] }
      ],
      surfaces: ['obi', 'frame', 'topGradient'],
      overlays: ['paper', 'inkBleed', 'dust']
    },
    {
      id: 'novel-yoko', aspect: 0.691,
      slots: [
        { role: 'tag', size: 0.019, tracking: 0.24, maxLines: 1, align: 'center', decor: 'plain',
          candidates: [{ x: 0.140, y: 0.070, w: 0.720, h: 0.030 }] },
        { role: 'title', size: 0.090, tracking: 0.06, maxLines: 2, align: 'center', big: true, decor: 'title',
          candidates: [{ x: 0.090, y: 0.125, w: 0.820, h: 0.160 }, { x: 0.090, y: 0.400, w: 0.820, h: 0.160 }] },
        { role: 'name', size: 0.030, tracking: 0.20, maxLines: 1, align: 'center', decor: 'plain',
          candidates: [{ x: 0.160, y: 0.300, w: 0.680, h: 0.048 }] },
        { role: 'catch', size: 0.046, tracking: 0.04, maxLines: 2, align: 'center', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: 0.045, y: 0.680, w: 0.910, h: 0.128 }] },
        { role: 'extra', size: 0.024, tracking: 0.02, maxLines: 2, align: 'center', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: 0.045, y: 0.816, w: 0.910, h: 0.082 }] },
        { role: 'badge', size: 0.026, tracking: 0.04, maxLines: 1, align: 'center', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: 0.058, y: 0.911, w: 0.404, h: 0.046 }] },
        { role: 'release', size: 0.017, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: 0.500, y: 0.950, w: 0.455, h: 0.034 }] },
        { role: 'credit', size: 0.017, tracking: 0.02, maxLines: 1, align: 'left', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: 0.045, y: 0.970, w: 0.430, h: 0.026 }] }
      ],
      surfaces: ['obi', 'frame'],
      overlays: ['paper', 'grain', 'inkBleed']
    },
    {
      id: 'novel-tate-plate', aspect: 0.709,
      slots: [
        { role: 'title', size: 0.078, tracking: 0.10, maxLines: 1, align: 'top', vertical: true, big: true, onSurface: 'plate', decor: 'title',
          candidates: [{ x: 0.640, y: 0.255, w: 0.230, h: 0.290 }] },
        { role: 'name', size: 0.028, tracking: 0.16, maxLines: 1, align: 'top', vertical: true, onSurface: 'plate', decor: 'plain',
          candidates: [{ x: 0.470, y: 0.270, w: 0.140, h: 0.240 }] },
        { role: 'catch', size: 0.046, tracking: 0.04, maxLines: 2, align: 'center', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: 0.045, y: 0.680, w: 0.910, h: 0.128 }] },
        { role: 'extra', size: 0.024, tracking: 0.02, maxLines: 2, align: 'center', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: 0.045, y: 0.816, w: 0.910, h: 0.082 }] },
        { role: 'badge', size: 0.026, tracking: 0.04, maxLines: 1, align: 'center', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: 0.058, y: 0.911, w: 0.404, h: 0.046 }] },
        { role: 'tag', size: 0.020, tracking: 0.08, maxLines: 1, align: 'right', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: 0.500, y: 0.904, w: 0.455, h: 0.040 }] },
        { role: 'release', size: 0.017, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: 0.500, y: 0.950, w: 0.455, h: 0.034 }] },
        { role: 'credit', size: 0.017, tracking: 0.02, maxLines: 1, align: 'left', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: 0.045, y: 0.970, w: 0.430, h: 0.026 }] }
      ],
      surfaces: ['obi', 'plate', 'frame'],
      overlays: ['paper', 'vignette', 'inkBleed', 'dust']
    }
  ],

  asmr: [
    {
      id: 'asmr-voice-right', aspect: 1.333,
      slots: [
        { role: 'title', size: 0.105, tracking: 0.06, maxLines: 3, align: 'top', vertical: true, big: true, decor: 'title',
          candidates: [{ x: 0.700, y: 0.070, w: 0.240, h: 0.620 }] },
        { role: 'catch', size: 0.052, tracking: 0.06, maxLines: 2, align: 'top', vertical: true, decor: 'accent',
          candidates: [{ x: 0.555, y: 0.115, w: 0.125, h: 0.430 }] },
        { role: 'badge', size: 0.030, tracking: 0.04, maxLines: 1, align: 'center', decor: 'accent',
          candidates: [{ x: 0.480, y: 0.610, w: 0.190, h: 0.062 }] },
        { role: 'release', size: 0.014, tracking: 0.06, maxLines: 1, align: 'center', onSurface: 'voiceChrome', decor: 'plain',
          candidates: [{ x: 0.045, y: 0.010, w: 0.910, h: 0.030 }] },
        { role: 'name', size: 0.048, tracking: 0.04, maxLines: 1, align: 'left', onSurface: 'voiceChrome', decor: 'accent',
          candidates: [{ x: 0.058, y: 0.772, w: 0.384, h: 0.070 }] },
        { role: 'credit', size: 0.030, tracking: 0.04, maxLines: 1, align: 'left', onSurface: 'voiceChrome', decor: 'plain',
          candidates: [{ x: 0.058, y: 0.850, w: 0.384, h: 0.048 }] },
        { role: 'tag', size: 0.026, tracking: 0.04, maxLines: 1, align: 'left', onSurface: 'voiceChrome', decor: 'plain',
          candidates: [{ x: 0.045, y: 0.942, w: 0.480, h: 0.044 }] },
        { role: 'extra', size: 0.024, tracking: 0.03, maxLines: 1, align: 'right', onSurface: 'voiceChrome', decor: 'plain',
          candidates: [{ x: 0.560, y: 0.942, w: 0.400, h: 0.044 }] }
      ],
      surfaces: ['voiceChrome', 'jacketFrame', 'circleMark', 'waveBand'],
      overlays: ['softFocus', 'bloom', 'grain', 'bokehDots', 'lightLeak']
    },
    {
      id: 'asmr-voice-left', aspect: 1.333,
      slots: [
        { role: 'title', size: 0.105, tracking: 0.06, maxLines: 3, align: 'top', vertical: true, big: true, decor: 'title',
          candidates: [{ x: 0.060, y: 0.070, w: 0.240, h: 0.620 }] },
        { role: 'catch', size: 0.052, tracking: 0.06, maxLines: 2, align: 'top', vertical: true, decor: 'accent',
          candidates: [{ x: 0.330, y: 0.115, w: 0.125, h: 0.430 }] },
        { role: 'badge', size: 0.030, tracking: 0.04, maxLines: 1, align: 'center', decor: 'accent',
          candidates: [{ x: 0.660, y: 0.610, w: 0.190, h: 0.062 }] },
        { role: 'release', size: 0.014, tracking: 0.06, maxLines: 1, align: 'center', onSurface: 'voiceChrome', decor: 'plain',
          candidates: [{ x: 0.045, y: 0.010, w: 0.910, h: 0.030 }] },
        { role: 'name', size: 0.048, tracking: 0.04, maxLines: 1, align: 'left', onSurface: 'voiceChrome', decor: 'accent',
          candidates: [{ x: 0.058, y: 0.772, w: 0.384, h: 0.070 }] },
        { role: 'credit', size: 0.030, tracking: 0.04, maxLines: 1, align: 'left', onSurface: 'voiceChrome', decor: 'plain',
          candidates: [{ x: 0.058, y: 0.850, w: 0.384, h: 0.048 }] },
        { role: 'tag', size: 0.026, tracking: 0.04, maxLines: 1, align: 'left', onSurface: 'voiceChrome', decor: 'plain',
          candidates: [{ x: 0.045, y: 0.942, w: 0.480, h: 0.044 }] },
        { role: 'extra', size: 0.024, tracking: 0.03, maxLines: 1, align: 'right', onSurface: 'voiceChrome', decor: 'plain',
          candidates: [{ x: 0.560, y: 0.942, w: 0.400, h: 0.044 }] }
      ],
      surfaces: ['voiceChrome', 'jacketFrame', 'circleMark', 'sideBand'],
      overlays: ['softFocus', 'bokehDots', 'bloom', 'lightLeak']
    },
    {
      id: 'asmr-voice-wide', aspect: 1.333,
      slots: [
        { role: 'title', size: 0.098, tracking: 0.06, maxLines: 4, align: 'top', vertical: true, big: true, decor: 'title',
          candidates: [{ x: 0.640, y: 0.065, w: 0.300, h: 0.640 }] },
        { role: 'catch', size: 0.048, tracking: 0.06, maxLines: 2, align: 'top', vertical: true, decor: 'accent',
          candidates: [{ x: 0.480, y: 0.110, w: 0.140, h: 0.440 }] },
        { role: 'badge', size: 0.030, tracking: 0.04, maxLines: 1, align: 'center', decor: 'accent',
          candidates: [{ x: 0.060, y: 0.640, w: 0.220, h: 0.060 }] },
        { role: 'release', size: 0.014, tracking: 0.06, maxLines: 1, align: 'center', onSurface: 'voiceChrome', decor: 'plain',
          candidates: [{ x: 0.045, y: 0.010, w: 0.910, h: 0.030 }] },
        { role: 'name', size: 0.048, tracking: 0.04, maxLines: 1, align: 'left', onSurface: 'voiceChrome', decor: 'accent',
          candidates: [{ x: 0.058, y: 0.772, w: 0.384, h: 0.070 }] },
        { role: 'credit', size: 0.030, tracking: 0.04, maxLines: 1, align: 'left', onSurface: 'voiceChrome', decor: 'plain',
          candidates: [{ x: 0.058, y: 0.850, w: 0.384, h: 0.048 }] },
        { role: 'tag', size: 0.026, tracking: 0.04, maxLines: 1, align: 'left', onSurface: 'voiceChrome', decor: 'plain',
          candidates: [{ x: 0.045, y: 0.942, w: 0.480, h: 0.044 }] },
        { role: 'extra', size: 0.024, tracking: 0.03, maxLines: 1, align: 'right', onSurface: 'voiceChrome', decor: 'plain',
          candidates: [{ x: 0.560, y: 0.942, w: 0.400, h: 0.044 }] }
      ],
      surfaces: ['voiceChrome', 'jacketFrame', 'waveBand', 'circleMark'],
      overlays: ['softFocus', 'bloom', 'grain', 'bokehDots']
    },
    {
      id: 'asmr-voice-soft', aspect: 1.333,
      slots: [
        { role: 'title', size: 0.100, tracking: 0.06, maxLines: 3, align: 'top', vertical: true, big: true, decor: 'title',
          candidates: [{ x: 0.690, y: 0.090, w: 0.250, h: 0.580 }] },
        { role: 'catch', size: 0.048, tracking: 0.06, maxLines: 2, align: 'top', vertical: true, decor: 'accent',
          candidates: [{ x: 0.540, y: 0.130, w: 0.130, h: 0.400 }] },
        { role: 'badge', size: 0.030, tracking: 0.04, maxLines: 1, align: 'center', decor: 'accent',
          candidates: [{ x: 0.470, y: 0.620, w: 0.200, h: 0.060 }] },
        { role: 'release', size: 0.014, tracking: 0.06, maxLines: 1, align: 'center', onSurface: 'voiceChrome', decor: 'plain',
          candidates: [{ x: 0.045, y: 0.010, w: 0.910, h: 0.030 }] },
        { role: 'name', size: 0.048, tracking: 0.04, maxLines: 1, align: 'left', onSurface: 'voiceChrome', decor: 'accent',
          candidates: [{ x: 0.058, y: 0.772, w: 0.384, h: 0.070 }] },
        { role: 'credit', size: 0.030, tracking: 0.04, maxLines: 1, align: 'left', onSurface: 'voiceChrome', decor: 'plain',
          candidates: [{ x: 0.058, y: 0.850, w: 0.384, h: 0.048 }] },
        { role: 'tag', size: 0.026, tracking: 0.04, maxLines: 1, align: 'left', onSurface: 'voiceChrome', decor: 'plain',
          candidates: [{ x: 0.045, y: 0.942, w: 0.480, h: 0.044 }] },
        { role: 'extra', size: 0.024, tracking: 0.03, maxLines: 1, align: 'right', onSurface: 'voiceChrome', decor: 'plain',
          candidates: [{ x: 0.560, y: 0.942, w: 0.400, h: 0.044 }] }
      ],
      surfaces: ['voiceChrome', 'jacketFrame', 'circleMark', 'topGradient'],
      overlays: ['bokehDots', 'bloom', 'grain', 'neonGlow', 'softFocus']
    }
  ],

  game: [
    {
      id: 'game-switch', aspect: 0.618,
      slots: [
        { role: 'tag', size: 0.022, tracking: 0.16, maxLines: 1, align: 'right', latin: true, onSurface: 'gameChrome', decor: 'plain',
          candidates: [{ x: 0.420, y: 0.022, w: 0.545, h: 0.056 }] },
        { role: 'catch', size: 0.030, tracking: 0.08, maxLines: 2, align: 'center', decor: 'accent',
          candidates: [{ x: 0.150, y: 0.450, w: 0.700, h: 0.075 }, { x: 0.150, y: 0.150, w: 0.700, h: 0.075 }] },
        { role: 'title', size: 0.108, tracking: 0.02, maxLines: 2, align: 'center', big: true, decor: 'title',
          candidates: [{ x: 0.110, y: 0.560, w: 0.780, h: 0.150 }, { x: 0.110, y: 0.180, w: 0.780, h: 0.150 }] },
        { role: 'badge', size: 0.024, tracking: 0.16, maxLines: 1, align: 'center', latin: true, decor: 'accent',
          candidates: [{ x: 0.200, y: 0.735, w: 0.600, h: 0.040 }] },
        { role: 'credit', size: 0.015, tracking: 0.02, maxLines: 2, align: 'right', onSurface: 'gameChrome', decor: 'plain',
          candidates: [{ x: 0.250, y: 0.874, w: 0.705, h: 0.046 }] },
        { role: 'release', size: 0.016, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'gameChrome', decor: 'plain',
          candidates: [{ x: 0.250, y: 0.930, w: 0.705, h: 0.040 }] }
      ],
      surfaces: ['gameChrome', 'bottomGradient'],
      overlays: ['grain', 'bloom', 'chromaEdge', 'halation']
    },
    {
      id: 'game-ps5', aspect: 0.794,
      slots: [
        { role: 'tag', size: 0.022, tracking: 0.16, maxLines: 1, align: 'right', latin: true, onSurface: 'gameChrome', decor: 'plain',
          candidates: [{ x: 0.420, y: 0.022, w: 0.545, h: 0.056 }] },
        { role: 'badge', size: 0.024, tracking: 0.16, maxLines: 1, align: 'center', latin: true, decor: 'accent',
          candidates: [{ x: 0.190, y: 0.380, w: 0.620, h: 0.040 }] },
        { role: 'catch', size: 0.030, tracking: 0.08, maxLines: 2, align: 'center', decor: 'accent',
          candidates: [{ x: 0.150, y: 0.460, w: 0.700, h: 0.075 }] },
        { role: 'title', size: 0.112, tracking: 0.02, maxLines: 2, align: 'center', big: true, decor: 'title',
          candidates: [{ x: 0.120, y: 0.575, w: 0.760, h: 0.150 }, { x: 0.120, y: 0.160, w: 0.760, h: 0.150 }] },
        { role: 'name', size: 0.022, tracking: 0.12, maxLines: 1, align: 'center', decor: 'plain',
          candidates: [{ x: 0.200, y: 0.745, w: 0.600, h: 0.036 }] },
        { role: 'credit', size: 0.015, tracking: 0.02, maxLines: 2, align: 'right', onSurface: 'gameChrome', decor: 'plain',
          candidates: [{ x: 0.250, y: 0.874, w: 0.705, h: 0.046 }] },
        { role: 'release', size: 0.016, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'gameChrome', decor: 'plain',
          candidates: [{ x: 0.250, y: 0.930, w: 0.705, h: 0.040 }] }
      ],
      surfaces: ['gameChrome', 'bottomGradient', 'cornerPlate'],
      overlays: ['grain', 'halation', 'chromaEdge', 'neonGlow']
    },
    {
      id: 'game-classic', aspect: 0.716,
      slots: [
        { role: 'tag', size: 0.022, tracking: 0.16, maxLines: 1, align: 'right', latin: true, onSurface: 'gameChrome', decor: 'plain',
          candidates: [{ x: 0.420, y: 0.022, w: 0.545, h: 0.056 }] },
        { role: 'title', size: 0.100, tracking: 0.02, maxLines: 2, align: 'left', big: true, decor: 'title',
          candidates: [{ x: 0.050, y: 0.175, w: 0.680, h: 0.175 }, { x: 0.050, y: 0.540, w: 0.680, h: 0.175 }] },
        { role: 'catch', size: 0.028, tracking: 0.07, maxLines: 2, align: 'left', decor: 'accent',
          candidates: [{ x: 0.050, y: 0.370, w: 0.620, h: 0.085 }] },
        { role: 'name', size: 0.022, tracking: 0.12, maxLines: 1, align: 'left', decor: 'plain',
          candidates: [{ x: 0.050, y: 0.470, w: 0.580, h: 0.042 }] },
        { role: 'extra', size: 0.018, tracking: 0.04, maxLines: 2, align: 'left', decor: 'plain',
          candidates: [{ x: 0.050, y: 0.745, w: 0.550, h: 0.056 }] },
        { role: 'credit', size: 0.015, tracking: 0.02, maxLines: 2, align: 'right', onSurface: 'gameChrome', decor: 'plain',
          candidates: [{ x: 0.250, y: 0.874, w: 0.705, h: 0.046 }] },
        { role: 'release', size: 0.016, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'gameChrome', decor: 'plain',
          candidates: [{ x: 0.250, y: 0.930, w: 0.705, h: 0.040 }] }
      ],
      surfaces: ['gameChrome', 'sideBand', 'discSpine'],
      overlays: ['scanline', 'grain', 'chromaEdge', 'neonGlow']
    },
    {
      id: 'game-edition', aspect: 0.788,
      slots: [
        { role: 'tag', size: 0.022, tracking: 0.16, maxLines: 1, align: 'right', latin: true, onSurface: 'gameChrome', decor: 'plain',
          candidates: [{ x: 0.420, y: 0.022, w: 0.545, h: 0.056 }] },
        { role: 'title', size: 0.086, tracking: 0.02, maxLines: 2, align: 'center', big: true, onSurface: 'plate', decor: 'title',
          candidates: [{ x: 0.150, y: 0.312, w: 0.700, h: 0.125 }] },
        { role: 'badge', size: 0.026, tracking: 0.18, maxLines: 1, align: 'center', latin: true, onSurface: 'plate', decor: 'accent',
          candidates: [{ x: 0.170, y: 0.455, w: 0.660, h: 0.046 }] },
        { role: 'catch', size: 0.028, tracking: 0.07, maxLines: 2, align: 'center', decor: 'accent',
          candidates: [{ x: 0.150, y: 0.600, w: 0.700, h: 0.072 }] },
        { role: 'name', size: 0.022, tracking: 0.12, maxLines: 1, align: 'center', decor: 'plain',
          candidates: [{ x: 0.200, y: 0.700, w: 0.600, h: 0.036 }] },
        { role: 'extra', size: 0.018, tracking: 0.04, maxLines: 2, align: 'center', decor: 'plain',
          candidates: [{ x: 0.190, y: 0.760, w: 0.620, h: 0.044 }] },
        { role: 'credit', size: 0.015, tracking: 0.02, maxLines: 2, align: 'right', onSurface: 'gameChrome', decor: 'plain',
          candidates: [{ x: 0.250, y: 0.874, w: 0.705, h: 0.046 }] },
        { role: 'release', size: 0.016, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'gameChrome', decor: 'plain',
          candidates: [{ x: 0.250, y: 0.930, w: 0.705, h: 0.040 }] }
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
          candidates: [{ x: 0.050, y: 0.012, w: 0.900, h: 0.046 }] },
        { role: 'title', size: 0.086, tracking: 0.01, maxLines: 4, align: 'center', big: true, tiered: true, decor: 'title',
          candidates: [{ x: 0.110, y: 0.120, w: 0.780, h: 0.198 }] },
        { role: 'name', size: 0.052, tracking: 0.06, maxLines: 1, align: 'center', decor: 'accent',
          candidates: [{ x: 0.200, y: 0.380, w: 0.600, h: 0.055 }, { x: 0.200, y: 0.500, w: 0.600, h: 0.055 }] },
        { role: 'badge', size: 0.034, tracking: 0.03, maxLines: 1, align: 'center', rotateDeg: -16, onSurface: 'avLayers', decor: 'accent',
          candidates: [{ x: 0.040, y: 0.616, w: 0.640, h: 0.076 }] },
        { role: 'extra', size: 0.017, tracking: 0.03, maxLines: 1, align: 'left', onSurface: 'avLayers', decor: 'plain',
          candidates: [{ x: 0.050, y: 0.872, w: 0.590, h: 0.044 }] },
        { role: 'credit', size: 0.016, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'avLayers', decor: 'plain',
          candidates: [{ x: 0.660, y: 0.872, w: 0.290, h: 0.044 }] },
        { role: 'code', size: 0.017, tracking: 0.12, maxLines: 1, align: 'left', latin: true, onSurface: 'avLayers', decor: 'plain',
          candidates: [{ x: 0.050, y: 0.928, w: 0.400, h: 0.042 }] },
        { role: 'release', size: 0.017, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'avLayers', decor: 'plain',
          candidates: [{ x: 0.470, y: 0.928, w: 0.255, h: 0.042 }] }
      ],
      surfaces: ['avLayers', 'boldFrame', 'barcode'],
      overlays: ['grain', 'neonGlow', 'halation', 'bloom']
    },
    {
      id: 'adult-kikaku', aspect: 0.708,
      slots: [
        { role: 'tag', size: 0.026, tracking: 0.06, maxLines: 1, align: 'center', onSurface: 'avLayers', decor: 'accent',
          candidates: [{ x: 0.050, y: 0.012, w: 0.900, h: 0.046 }] },
        { role: 'title', size: 0.104, tracking: 0.01, maxLines: 4, align: 'center', big: true, tiered: true, decor: 'title',
          candidates: [{ x: 0.050, y: 0.095, w: 0.900, h: 0.440 }] },
        { role: 'name', size: 0.048, tracking: 0.06, maxLines: 1, align: 'left', decor: 'accent',
          candidates: [{ x: 0.050, y: 0.550, w: 0.700, h: 0.055 }] },
        { role: 'badge', size: 0.034, tracking: 0.03, maxLines: 1, align: 'center', rotateDeg: -16, onSurface: 'avLayers', decor: 'accent',
          candidates: [{ x: 0.040, y: 0.616, w: 0.640, h: 0.076 }] },
        { role: 'extra', size: 0.017, tracking: 0.03, maxLines: 1, align: 'left', onSurface: 'avLayers', decor: 'plain',
          candidates: [{ x: 0.050, y: 0.872, w: 0.590, h: 0.044 }] },
        { role: 'credit', size: 0.016, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'avLayers', decor: 'plain',
          candidates: [{ x: 0.660, y: 0.872, w: 0.290, h: 0.044 }] },
        { role: 'code', size: 0.017, tracking: 0.12, maxLines: 1, align: 'left', latin: true, onSurface: 'avLayers', decor: 'plain',
          candidates: [{ x: 0.050, y: 0.928, w: 0.400, h: 0.042 }] },
        { role: 'release', size: 0.017, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'avLayers', decor: 'plain',
          candidates: [{ x: 0.470, y: 0.928, w: 0.255, h: 0.042 }] }
      ],
      surfaces: ['avLayers', 'boldFrame', 'tapeStrip', 'barcode'],
      overlays: ['neonGlow', 'halation', 'grain', 'chromaEdge']
    },
    {
      id: 'adult-mixed', aspect: 0.708,
      slots: [
        { role: 'tag', size: 0.026, tracking: 0.06, maxLines: 1, align: 'center', onSurface: 'avLayers', decor: 'accent',
          candidates: [{ x: 0.050, y: 0.012, w: 0.900, h: 0.046 }] },
        { role: 'title', size: 0.098, tracking: 0.01, maxLines: 4, align: 'left', big: true, tiered: true, decor: 'title',
          candidates: [{ x: 0.050, y: 0.105, w: 0.640, h: 0.450 }] },
        { role: 'name', size: 0.046, tracking: 0.14, maxLines: 1, align: 'top', vertical: true, decor: 'accent',
          candidates: [{ x: 0.760, y: 0.110, w: 0.150, h: 0.330 }] },
        { role: 'badge', size: 0.034, tracking: 0.03, maxLines: 1, align: 'center', rotateDeg: -16, onSurface: 'avLayers', decor: 'accent',
          candidates: [{ x: 0.040, y: 0.616, w: 0.640, h: 0.076 }] },
        { role: 'extra', size: 0.017, tracking: 0.03, maxLines: 1, align: 'left', onSurface: 'avLayers', decor: 'plain',
          candidates: [{ x: 0.050, y: 0.872, w: 0.590, h: 0.044 }] },
        { role: 'credit', size: 0.016, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'avLayers', decor: 'plain',
          candidates: [{ x: 0.660, y: 0.872, w: 0.290, h: 0.044 }] },
        { role: 'code', size: 0.017, tracking: 0.12, maxLines: 1, align: 'left', latin: true, onSurface: 'avLayers', decor: 'plain',
          candidates: [{ x: 0.050, y: 0.928, w: 0.400, h: 0.042 }] },
        { role: 'release', size: 0.017, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'avLayers', decor: 'plain',
          candidates: [{ x: 0.470, y: 0.928, w: 0.255, h: 0.042 }] }
      ],
      surfaces: ['avLayers', 'discSpine', 'tapeStrip'],
      overlays: ['grain', 'bokehDots', 'neonGlow', 'lightLeak']
    },
    {
      id: 'adult-frame', aspect: 0.708,
      slots: [
        { role: 'tag', size: 0.026, tracking: 0.06, maxLines: 1, align: 'center', onSurface: 'avLayers', decor: 'accent',
          candidates: [{ x: 0.050, y: 0.012, w: 0.900, h: 0.046 }] },
        { role: 'title', size: 0.092, tracking: 0.01, maxLines: 4, align: 'center', big: true, tiered: true, decor: 'title',
          candidates: [{ x: 0.130, y: 0.135, w: 0.740, h: 0.208 }] },
        { role: 'name', size: 0.050, tracking: 0.08, maxLines: 1, align: 'center', decor: 'accent',
          candidates: [{ x: 0.210, y: 0.420, w: 0.580, h: 0.055 }] },
        { role: 'badge', size: 0.034, tracking: 0.03, maxLines: 1, align: 'center', rotateDeg: -16, onSurface: 'avLayers', decor: 'accent',
          candidates: [{ x: 0.040, y: 0.616, w: 0.640, h: 0.076 }] },
        { role: 'extra', size: 0.017, tracking: 0.03, maxLines: 1, align: 'left', onSurface: 'avLayers', decor: 'plain',
          candidates: [{ x: 0.050, y: 0.872, w: 0.590, h: 0.044 }] },
        { role: 'credit', size: 0.016, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'avLayers', decor: 'plain',
          candidates: [{ x: 0.660, y: 0.872, w: 0.290, h: 0.044 }] },
        { role: 'code', size: 0.017, tracking: 0.12, maxLines: 1, align: 'left', latin: true, onSurface: 'avLayers', decor: 'plain',
          candidates: [{ x: 0.050, y: 0.928, w: 0.400, h: 0.042 }] },
        { role: 'release', size: 0.017, tracking: 0.04, maxLines: 1, align: 'right', onSurface: 'avLayers', decor: 'plain',
          candidates: [{ x: 0.470, y: 0.928, w: 0.255, h: 0.042 }] }
      ],
      surfaces: ['avLayers', 'boldFrame', 'discSpine', 'barcode'],
      overlays: ['grain', 'vignette', 'inkBleed', 'halation']
    }
  ]
};
