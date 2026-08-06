export const SURFACE_ANCHORS = {
  obi: { x: 0.00, y: 0.780, w: 1.00, h: 0.220 },
  ribbon: { x: 0.04, y: 0.865, w: 0.92, h: 0.075 },
  plate: { x: 0.10, y: 0.270, w: 0.80, h: 0.270 },
  platformBar: { x: 0.00, y: 0.000, w: 1.00, h: 0.052 },
  gridPlate: { x: 0.30, y: 0.800, w: 0.65, h: 0.145 },
  ratingBox: { x: 0.045, y: 0.800, w: 0.20, h: 0.145 },
  noticeStrip: { x: 0.05, y: 0.955, w: 0.55, h: 0.028 },
  barcode: { x: 0.75, y: 0.925, w: 0.20, h: 0.055 }
};

export const LAYOUTS = {
  cinema: [
    {
      id: 'cinema-classic', aspect: 0.680,
      slots: [
        { role: 'tag', size: 0.022, tracking: 0.30, maxLines: 1, align: 'center', latin: true, decor: 'plain',
          candidates: [{ x: .10, y: .075, w: .80, h: .035 }, { x: .10, y: .620, w: .80, h: .035 }] },
        { role: 'catch', size: 0.036, tracking: 0.08, maxLines: 2, align: 'center', decor: 'accent',
          candidates: [{ x: .08, y: .120, w: .84, h: .100 }, { x: .08, y: .660, w: .84, h: .090 }] },
        { role: 'title', size: 0.115, tracking: 0.05, maxLines: 2, align: 'center', big: true, decor: 'title',
          candidates: [{ x: .06, y: .705, w: .88, h: .150 }, { x: .06, y: .220, w: .88, h: .160 }] },
        { role: 'release', size: 0.030, tracking: 0.10, maxLines: 1, align: 'center', decor: 'plain',
          candidates: [{ x: .08, y: .875, w: .84, h: .040 }] },
        { role: 'credit', size: 0.019, tracking: 0.02, maxLines: 3, align: 'center', decor: 'plain',
          candidates: [{ x: .08, y: .925, w: .84, h: .060 }] }
      ],
      surfaces: ['letterbox', 'bottomGradient'],
      overlays: ['grain', 'vignette', 'halation']
    },
    {
      id: 'cinema-vertical', aspect: 0.700,
      slots: [
        { role: 'title', size: 0.085, tracking: 0.14, maxLines: 1, align: 'top', vertical: true, big: true, decor: 'title',
          candidates: [{ x: .74, y: .070, w: .16, h: .600 }, { x: .08, y: .070, w: .16, h: .600 }] },
        { role: 'catch', size: 0.030, tracking: 0.06, maxLines: 2, align: 'left', decor: 'accent',
          candidates: [{ x: .08, y: .100, w: .48, h: .100 }, { x: .08, y: .720, w: .55, h: .090 }] },
        { role: 'badge', size: 0.020, tracking: 0.06, maxLines: 2, align: 'left', decor: 'accent',
          candidates: [{ x: .08, y: .840, w: .50, h: .050 }] },
        { role: 'release', size: 0.026, tracking: 0.08, maxLines: 1, align: 'left', decor: 'plain',
          candidates: [{ x: .08, y: .900, w: .60, h: .040 }] }
      ],
      surfaces: ['sideBand', 'bottomGradient', 'discSpine'],
      overlays: ['grain', 'scanline', 'chromaEdge']
    },
    {
      id: 'cinema-top', aspect: 0.720,
      slots: [
        { role: 'tag', size: 0.020, tracking: 0.34, maxLines: 1, align: 'center', latin: true, decor: 'plain',
          candidates: [{ x: .10, y: .050, w: .80, h: .030 }] },
        { role: 'title', size: 0.105, tracking: 0.04, maxLines: 2, align: 'center', big: true, decor: 'title',
          candidates: [{ x: .06, y: .090, w: .88, h: .160 }, { x: .06, y: .680, w: .88, h: .160 }] },
        { role: 'catch', size: 0.032, tracking: 0.10, maxLines: 2, align: 'center', decor: 'accent',
          candidates: [{ x: .10, y: .270, w: .80, h: .080 }, { x: .10, y: .590, w: .80, h: .080 }] },
        { role: 'name', size: 0.026, tracking: 0.18, maxLines: 1, align: 'center', decor: 'plain',
          candidates: [{ x: .12, y: .370, w: .76, h: .045 }] },
        { role: 'credit', size: 0.018, tracking: 0.02, maxLines: 3, align: 'center', decor: 'plain',
          candidates: [{ x: .08, y: .885, w: .84, h: .060 }] }
      ],
      surfaces: ['topGradient', 'letterbox', 'noticeStrip'],
      overlays: ['grain', 'vignette', 'dust', 'halation']
    },
    {
      id: 'cinema-noir', aspect: 0.675,
      slots: [
        { role: 'title', size: 0.082, tracking: 0.08, maxLines: 2, align: 'center', big: true, onSurface: 'plate', decor: 'title',
          candidates: [{ x: .14, y: .320, w: .72, h: .120 }] },
        { role: 'name', size: 0.026, tracking: 0.22, maxLines: 1, align: 'center', onSurface: 'plate', decor: 'plain',
          candidates: [{ x: .16, y: .455, w: .68, h: .045 }] },
        { role: 'tag', size: 0.020, tracking: 0.32, maxLines: 1, align: 'center', latin: true, decor: 'plain',
          candidates: [{ x: .12, y: .120, w: .76, h: .032 }] },
        { role: 'catch', size: 0.030, tracking: 0.06, maxLines: 2, align: 'center', decor: 'accent',
          candidates: [{ x: .09, y: .620, w: .82, h: .090 }, { x: .09, y: .170, w: .82, h: .080 }] },
        { role: 'release', size: 0.024, tracking: 0.10, maxLines: 1, align: 'center', decor: 'plain',
          candidates: [{ x: .10, y: .800, w: .80, h: .038 }] },
        { role: 'credit', size: 0.017, tracking: 0.02, maxLines: 3, align: 'center', decor: 'plain',
          candidates: [{ x: .08, y: .880, w: .84, h: .060 }] }
      ],
      surfaces: ['plate', 'frame', 'letterbox', 'bottomGradient'],
      overlays: ['grain', 'vignette', 'softFocus']
    }
  ],

  gravure: [
    {
      id: 'gravure-band', aspect: 0.740,
      slots: [
        { role: 'tag', size: 0.024, tracking: 0.24, maxLines: 1, align: 'left', latin: true, decor: 'plain',
          candidates: [{ x: .07, y: .055, w: .60, h: .035 }] },
        { role: 'title', size: 0.100, tracking: 0.02, maxLines: 2, align: 'left', big: true, decor: 'title',
          candidates: [{ x: .06, y: .100, w: .70, h: .150 }, { x: .06, y: .660, w: .74, h: .150 }] },
        { role: 'name', size: 0.048, tracking: 0.14, maxLines: 1, align: 'left', decor: 'accent',
          candidates: [{ x: .06, y: .260, w: .60, h: .060 }, { x: .06, y: .820, w: .60, h: .060 }] },
        { role: 'catch', size: 0.024, tracking: 0.04, maxLines: 2, align: 'left', decor: 'plain',
          candidates: [{ x: .06, y: .330, w: .62, h: .060 }] },
        { role: 'badge', size: 0.026, tracking: 0.06, maxLines: 1, align: 'center', onSurface: 'ribbon', decor: 'accent',
          candidates: [{ x: .06, y: .880, w: .60, h: .048 }] }
      ],
      surfaces: ['ribbon', 'cornerPlate', 'topGradient', 'tapeStrip'],
      overlays: ['sparkle', 'grain', 'bloom']
    },
    {
      id: 'gravure-cover', aspect: 0.715,
      slots: [
        { role: 'name', size: 0.078, tracking: 0.10, maxLines: 1, align: 'center', big: true, decor: 'title',
          candidates: [{ x: .06, y: .060, w: .88, h: .100 }, { x: .06, y: .700, w: .88, h: .100 }] },
        { role: 'title', size: 0.052, tracking: 0.06, maxLines: 2, align: 'center', decor: 'accent',
          candidates: [{ x: .08, y: .175, w: .84, h: .090 }, { x: .08, y: .610, w: .84, h: .090 }] },
        { role: 'catch', size: 0.024, tracking: 0.04, maxLines: 2, align: 'center', decor: 'plain',
          candidates: [{ x: .10, y: .280, w: .80, h: .060 }] },
        { role: 'badge', size: 0.024, tracking: 0.04, maxLines: 1, align: 'center', onSurface: 'ribbon', decor: 'accent',
          candidates: [{ x: .10, y: .878, w: .60, h: .048 }] },
        { role: 'code', size: 0.016, tracking: 0.12, maxLines: 1, align: 'left', latin: true, decor: 'plain',
          candidates: [{ x: .06, y: .950, w: .38, h: .030 }] }
      ],
      surfaces: ['ribbon', 'barcode', 'bottomGradient'],
      overlays: ['sparkle', 'bloom', 'bokehDots']
    },
    {
      id: 'gravure-split', aspect: 0.720,
      slots: [
        { role: 'tag', size: 0.020, tracking: 0.28, maxLines: 1, align: 'left', latin: true, decor: 'plain',
          candidates: [{ x: .07, y: .060, w: .55, h: .032 }] },
        { role: 'title', size: 0.086, tracking: 0.03, maxLines: 2, align: 'left', big: true, decor: 'title',
          candidates: [{ x: .06, y: .110, w: .62, h: .150 }, { x: .06, y: .560, w: .66, h: .150 }] },
        { role: 'name', size: 0.042, tracking: 0.16, maxLines: 1, align: 'left', decor: 'accent',
          candidates: [{ x: .06, y: .275, w: .55, h: .055 }, { x: .06, y: .725, w: .58, h: .055 }] },
        { role: 'catch', size: 0.026, tracking: 0.05, maxLines: 2, align: 'left', decor: 'plain',
          candidates: [{ x: .06, y: .345, w: .56, h: .065 }] },
        { role: 'release', size: 0.020, tracking: 0.08, maxLines: 1, align: 'right', decor: 'plain',
          candidates: [{ x: .40, y: .940, w: .53, h: .032 }] }
      ],
      surfaces: ['sideBand', 'sealBadge', 'topGradient', 'cornerPlate'],
      overlays: ['sparkle', 'softFocus', 'grain', 'lightLeak']
    },
    {
      id: 'gravure-disc', aspect: 0.725,
      slots: [
        { role: 'title', size: 0.072, tracking: 0.04, maxLines: 2, align: 'center', big: true, decor: 'title',
          candidates: [{ x: .12, y: .130, w: .80, h: .130 }, { x: .12, y: .580, w: .80, h: .130 }] },
        { role: 'name', size: 0.046, tracking: 0.12, maxLines: 1, align: 'center', decor: 'accent',
          candidates: [{ x: .14, y: .275, w: .76, h: .055 }] },
        { role: 'badge', size: 0.022, tracking: 0.05, maxLines: 1, align: 'center', onSurface: 'ribbon', decor: 'accent',
          candidates: [{ x: .10, y: .878, w: .58, h: .048 }] },
        { role: 'extra', size: 0.017, tracking: 0.03, maxLines: 3, align: 'left', decor: 'plain',
          candidates: [{ x: .12, y: .720, w: .60, h: .080 }] },
        { role: 'code', size: 0.015, tracking: 0.14, maxLines: 1, align: 'left', latin: true, decor: 'plain',
          candidates: [{ x: .12, y: .952, w: .40, h: .028 }] }
      ],
      surfaces: ['discSpine', 'ribbon', 'barcode', 'bottomGradient'],
      overlays: ['bloom', 'grain', 'bokehDots', 'halation']
    }
  ],

  novel: [
    {
      id: 'novel-obi', aspect: 0.690,
      slots: [
        { role: 'title', size: 0.085, tracking: 0.10, maxLines: 1, align: 'top', vertical: true, big: true, decor: 'title',
          candidates: [{ x: .70, y: .060, w: .18, h: .550 }, { x: .10, y: .060, w: .18, h: .550 }] },
        { role: 'name', size: 0.034, tracking: 0.16, maxLines: 1, align: 'top', vertical: true, decor: 'plain',
          candidates: [{ x: .57, y: .100, w: .10, h: .280 }, { x: .26, y: .100, w: .10, h: .280 }] },
        { role: 'catch', size: 0.042, tracking: 0.04, maxLines: 2, align: 'center', onSurface: 'obi', decor: 'accent',
          candidates: [{ x: .07, y: .805, w: .86, h: .080 }] },
        { role: 'credit', size: 0.020, tracking: 0.02, maxLines: 3, align: 'center', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: .07, y: .888, w: .70, h: .050 }] },
        { role: 'tag', size: 0.020, tracking: 0.12, maxLines: 1, align: 'right', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: .55, y: .948, w: .38, h: .030 }] }
      ],
      surfaces: ['obi', 'frame'],
      overlays: ['paper', 'vignette', 'inkBleed']
    },
    {
      id: 'novel-horizontal', aspect: 0.700,
      slots: [
        { role: 'tag', size: 0.019, tracking: 0.26, maxLines: 1, align: 'center', decor: 'plain',
          candidates: [{ x: .12, y: .075, w: .76, h: .030 }] },
        { role: 'title', size: 0.092, tracking: 0.06, maxLines: 2, align: 'center', big: true, decor: 'title',
          candidates: [{ x: .08, y: .120, w: .84, h: .160 }, { x: .08, y: .560, w: .84, h: .160 }] },
        { role: 'name', size: 0.032, tracking: 0.20, maxLines: 1, align: 'center', decor: 'plain',
          candidates: [{ x: .12, y: .300, w: .76, h: .050 }, { x: .12, y: .735, w: .76, h: .050 }] },
        { role: 'catch', size: 0.038, tracking: 0.03, maxLines: 2, align: 'center', onSurface: 'obi', decor: 'accent',
          candidates: [{ x: .07, y: .830, w: .86, h: .080 }] },
        { role: 'code', size: 0.015, tracking: 0.14, maxLines: 1, align: 'right', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: .55, y: .950, w: .38, h: .028 }] }
      ],
      surfaces: ['obi', 'frame', 'topGradient'],
      overlays: ['paper', 'grain', 'inkBleed']
    },
    {
      id: 'novel-plate', aspect: 0.700,
      slots: [
        { role: 'title', size: 0.078, tracking: 0.08, maxLines: 2, align: 'center', big: true, onSurface: 'plate', decor: 'title',
          candidates: [{ x: .13, y: .310, w: .74, h: .125 }] },
        { role: 'name', size: 0.028, tracking: 0.22, maxLines: 1, align: 'center', onSurface: 'plate', decor: 'plain',
          candidates: [{ x: .16, y: .455, w: .68, h: .040 }] },
        { role: 'badge', size: 0.030, tracking: 0.04, maxLines: 1, align: 'center', onSurface: 'obi', decor: 'accent',
          candidates: [{ x: .07, y: .845, w: .86, h: .060 }] },
        { role: 'release', size: 0.018, tracking: 0.06, maxLines: 1, align: 'right', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: .45, y: .945, w: .48, h: .030 }] }
      ],
      surfaces: ['plate', 'obi', 'frame'],
      overlays: ['paper', 'vignette', 'dust', 'inkBleed']
    },
    {
      id: 'novel-bunko', aspect: 0.685,
      slots: [
        { role: 'title', size: 0.076, tracking: 0.12, maxLines: 1, align: 'top', vertical: true, big: true, decor: 'title',
          candidates: [{ x: .74, y: .100, w: .16, h: .480 }, { x: .09, y: .100, w: .16, h: .480 }] },
        { role: 'name', size: 0.030, tracking: 0.20, maxLines: 1, align: 'top', vertical: true, decor: 'plain',
          candidates: [{ x: .62, y: .140, w: .09, h: .250 }, { x: .28, y: .140, w: .09, h: .250 }] },
        { role: 'tag', size: 0.019, tracking: 0.22, maxLines: 1, align: 'center', latin: true, decor: 'plain',
          candidates: [{ x: .20, y: .060, w: .60, h: .030 }] },
        { role: 'catch', size: 0.036, tracking: 0.03, maxLines: 2, align: 'center', onSurface: 'obi', decor: 'accent',
          candidates: [{ x: .07, y: .800, w: .86, h: .075 }] },
        { role: 'extra', size: 0.018, tracking: 0.02, maxLines: 2, align: 'left', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: .07, y: .885, w: .56, h: .048 }] },
        { role: 'code', size: 0.015, tracking: 0.12, maxLines: 1, align: 'right', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: .56, y: .946, w: .37, h: .028 }] }
      ],
      surfaces: ['obi', 'frame', 'tapeStrip', 'noticeStrip'],
      overlays: ['paper', 'inkBleed', 'dust', 'vignette']
    }
  ],

  asmr: [
    {
      id: 'asmr-square', aspect: 0.980,
      slots: [
        { role: 'tag', size: 0.024, tracking: 0.28, maxLines: 1, align: 'center', latin: true, decor: 'plain',
          candidates: [{ x: .10, y: .060, w: .80, h: .035 }] },
        { role: 'title', size: 0.095, tracking: 0.04, maxLines: 2, align: 'center', big: true, decor: 'title',
          candidates: [{ x: .07, y: .140, w: .86, h: .150 }, { x: .07, y: .400, w: .86, h: .150 }] },
        { role: 'catch', size: 0.030, tracking: 0.06, maxLines: 2, align: 'center', decor: 'accent',
          candidates: [{ x: .10, y: .310, w: .80, h: .080 }, { x: .10, y: .180, w: .80, h: .070 }] },
        { role: 'name', size: 0.036, tracking: 0.12, maxLines: 1, align: 'center', decor: 'plain',
          candidates: [{ x: .10, y: .420, w: .80, h: .050 }, { x: .10, y: .780, w: .80, h: .050 }] },
        { role: 'badge', size: 0.022, tracking: 0.05, maxLines: 1, align: 'center', onSurface: 'ribbon', decor: 'accent',
          candidates: [{ x: .08, y: .878, w: .62, h: .048 }] },
        { role: 'release', size: 0.016, tracking: 0.10, maxLines: 1, align: 'right', decor: 'plain',
          candidates: [{ x: .50, y: .950, w: .43, h: .028 }] }
      ],
      surfaces: ['waveBand', 'ribbon', 'bottomGradient', 'tapeStrip'],
      overlays: ['softFocus', 'bloom', 'grain', 'bokehDots', 'lightLeak']
    },
    {
      id: 'asmr-jewel', aspect: 0.950,
      slots: [
        { role: 'title', size: 0.070, tracking: 0.05, maxLines: 2, align: 'center', big: true, onSurface: 'plate', decor: 'title',
          candidates: [{ x: .14, y: .315, w: .72, h: .120 }] },
        { role: 'name', size: 0.028, tracking: 0.20, maxLines: 1, align: 'center', onSurface: 'plate', decor: 'plain',
          candidates: [{ x: .16, y: .455, w: .68, h: .045 }] },
        { role: 'tag', size: 0.021, tracking: 0.26, maxLines: 1, align: 'center', latin: true, decor: 'plain',
          candidates: [{ x: .12, y: .075, w: .76, h: .032 }] },
        { role: 'catch', size: 0.026, tracking: 0.05, maxLines: 2, align: 'center', decor: 'accent',
          candidates: [{ x: .10, y: .620, w: .80, h: .080 }, { x: .10, y: .150, w: .80, h: .075 }] },
        { role: 'extra', size: 0.019, tracking: 0.02, maxLines: 3, align: 'left', onSurface: 'gridPlate', decor: 'plain',
          candidates: [{ x: .325, y: .818, w: .60, h: .110 }] },
        { role: 'code', size: 0.015, tracking: 0.12, maxLines: 1, align: 'left', latin: true, decor: 'plain',
          candidates: [{ x: .06, y: .955, w: .22, h: .028 }] }
      ],
      surfaces: ['plate', 'gridPlate', 'frame', 'discSpine'],
      overlays: ['paper', 'grain', 'softFocus', 'bokehDots']
    },
    {
      id: 'asmr-wave', aspect: 1.000,
      slots: [
        { role: 'tag', size: 0.022, tracking: 0.30, maxLines: 1, align: 'left', latin: true, decor: 'plain',
          candidates: [{ x: .08, y: .065, w: .60, h: .032 }] },
        { role: 'title', size: 0.088, tracking: 0.03, maxLines: 2, align: 'left', big: true, decor: 'title',
          candidates: [{ x: .07, y: .120, w: .70, h: .140 }, { x: .07, y: .400, w: .74, h: .140 }] },
        { role: 'catch', size: 0.028, tracking: 0.05, maxLines: 2, align: 'left', decor: 'accent',
          candidates: [{ x: .07, y: .280, w: .64, h: .080 }] },
        { role: 'name', size: 0.038, tracking: 0.14, maxLines: 1, align: 'left', decor: 'plain',
          candidates: [{ x: .07, y: .800, w: .60, h: .050 }, { x: .07, y: .375, w: .60, h: .050 }] },
        { role: 'extra', size: 0.018, tracking: 0.02, maxLines: 3, align: 'left', decor: 'plain',
          candidates: [{ x: .07, y: .862, w: .58, h: .070 }] },
        { role: 'release', size: 0.017, tracking: 0.08, maxLines: 1, align: 'right', decor: 'plain',
          candidates: [{ x: .55, y: .945, w: .38, h: .030 }] }
      ],
      surfaces: ['waveBand', 'topGradient', 'sideBand', 'tapeStrip'],
      overlays: ['bokehDots', 'bloom', 'grain', 'neonGlow', 'softFocus']
    },
    {
      id: 'asmr-track', aspect: 0.960,
      slots: [
        { role: 'title', size: 0.078, tracking: 0.05, maxLines: 2, align: 'center', big: true, decor: 'title',
          candidates: [{ x: .10, y: .110, w: .82, h: .140 }, { x: .10, y: .520, w: .82, h: .140 }] },
        { role: 'name', size: 0.034, tracking: 0.14, maxLines: 1, align: 'center', decor: 'accent',
          candidates: [{ x: .12, y: .265, w: .78, h: .050 }] },
        { role: 'catch', size: 0.026, tracking: 0.05, maxLines: 2, align: 'center', decor: 'plain',
          candidates: [{ x: .12, y: .335, w: .76, h: .075 }] },
        { role: 'extra', size: 0.019, tracking: 0.02, maxLines: 4, align: 'left', decor: 'plain',
          candidates: [{ x: .10, y: .760, w: .55, h: .095 }] },
        { role: 'badge', size: 0.021, tracking: 0.05, maxLines: 1, align: 'left', decor: 'accent',
          candidates: [{ x: .10, y: .700, w: .45, h: .045 }] },
        { role: 'code', size: 0.015, tracking: 0.12, maxLines: 1, align: 'left', latin: true, decor: 'plain',
          candidates: [{ x: .10, y: .958, w: .35, h: .026 }] }
      ],
      surfaces: ['discSpine', 'bottomGradient', 'barcode', 'noticeStrip'],
      overlays: ['grain', 'softFocus', 'halation', 'bokehDots']
    }
  ],

  game: [
    {
      id: 'game-standard', aspect: 0.710,
      slots: [
        { role: 'tag', size: 0.020, tracking: 0.18, maxLines: 1, align: 'right', latin: true, onSurface: 'platformBar', decor: 'plain',
          candidates: [{ x: .45, y: .009, w: .49, h: .034 }] },
        { role: 'catch', size: 0.030, tracking: 0.08, maxLines: 2, align: 'center', decor: 'accent',
          candidates: [{ x: .08, y: .440, w: .84, h: .085 }, { x: .08, y: .110, w: .84, h: .085 }] },
        { role: 'title', size: 0.105, tracking: 0.03, maxLines: 2, align: 'center', big: true, decor: 'title',
          candidates: [{ x: .06, y: .545, w: .88, h: .160 }, { x: .06, y: .140, w: .88, h: .160 }] },
        { role: 'name', size: 0.026, tracking: 0.16, maxLines: 1, align: 'center', decor: 'plain',
          candidates: [{ x: .10, y: .730, w: .80, h: .042 }] },
        { role: 'credit', size: 0.017, tracking: 0.02, maxLines: 3, align: 'left', onSurface: 'gridPlate', decor: 'plain',
          candidates: [{ x: .325, y: .818, w: .60, h: .110 }] }
      ],
      surfaces: ['platformBar', 'ratingBox', 'gridPlate', 'bottomGradient'],
      overlays: ['grain', 'bloom', 'chromaEdge', 'halation']
    },
    {
      id: 'game-hero', aspect: 0.715,
      slots: [
        { role: 'tag', size: 0.020, tracking: 0.18, maxLines: 1, align: 'right', latin: true, onSurface: 'platformBar', decor: 'plain',
          candidates: [{ x: .45, y: .009, w: .49, h: .034 }] },
        { role: 'title', size: 0.110, tracking: 0.03, maxLines: 2, align: 'center', big: true, decor: 'title',
          candidates: [{ x: .06, y: .095, w: .88, h: .170 }, { x: .06, y: .560, w: .88, h: .170 }] },
        { role: 'catch', size: 0.030, tracking: 0.08, maxLines: 2, align: 'center', decor: 'accent',
          candidates: [{ x: .08, y: .290, w: .84, h: .085 }] },
        { role: 'name', size: 0.026, tracking: 0.14, maxLines: 1, align: 'left', decor: 'plain',
          candidates: [{ x: .08, y: .680, w: .60, h: .045 }] },
        { role: 'release', size: 0.024, tracking: 0.10, maxLines: 1, align: 'left', decor: 'accent',
          candidates: [{ x: .08, y: .740, w: .60, h: .040 }] },
        { role: 'code', size: 0.015, tracking: 0.14, maxLines: 1, align: 'left', latin: true, decor: 'plain',
          candidates: [{ x: .30, y: .820, w: .40, h: .030 }] }
      ],
      surfaces: ['platformBar', 'discSpine', 'bottomGradient', 'barcode', 'ratingBox'],
      overlays: ['grain', 'halation', 'chromaEdge', 'scanline']
    },
    {
      id: 'game-edition', aspect: 0.705,
      slots: [
        { role: 'tag', size: 0.020, tracking: 0.18, maxLines: 1, align: 'right', latin: true, onSurface: 'platformBar', decor: 'plain',
          candidates: [{ x: .45, y: .009, w: .49, h: .034 }] },
        { role: 'title', size: 0.078, tracking: 0.04, maxLines: 2, align: 'center', big: true, onSurface: 'plate', decor: 'title',
          candidates: [{ x: .14, y: .310, w: .72, h: .125 }] },
        { role: 'catch', size: 0.026, tracking: 0.06, maxLines: 1, align: 'center', onSurface: 'plate', decor: 'accent',
          candidates: [{ x: .16, y: .458, w: .68, h: .045 }] },
        { role: 'badge', size: 0.028, tracking: 0.05, maxLines: 1, align: 'left', decor: 'accent',
          candidates: [{ x: .07, y: .620, w: .52, h: .050 }] },
        { role: 'name', size: 0.024, tracking: 0.14, maxLines: 1, align: 'left', decor: 'plain',
          candidates: [{ x: .07, y: .690, w: .55, h: .042 }] },
        { role: 'extra', size: 0.017, tracking: 0.02, maxLines: 3, align: 'left', onSurface: 'gridPlate', decor: 'plain',
          candidates: [{ x: .325, y: .818, w: .60, h: .110 }] }
      ],
      surfaces: ['platformBar', 'cornerPlate', 'plate', 'gridPlate', 'sealBadge'],
      overlays: ['grain', 'neonGlow', 'halation', 'bloom']
    },
    {
      id: 'game-arena', aspect: 0.712,
      slots: [
        { role: 'tag', size: 0.020, tracking: 0.18, maxLines: 1, align: 'right', latin: true, onSurface: 'platformBar', decor: 'plain',
          candidates: [{ x: .45, y: .009, w: .49, h: .034 }] },
        { role: 'title', size: 0.098, tracking: 0.03, maxLines: 2, align: 'left', big: true, decor: 'title',
          candidates: [{ x: .05, y: .160, w: .64, h: .165 }, { x: .05, y: .520, w: .68, h: .165 }] },
        { role: 'catch', size: 0.028, tracking: 0.07, maxLines: 2, align: 'left', decor: 'accent',
          candidates: [{ x: .05, y: .350, w: .60, h: .080 }] },
        { role: 'name', size: 0.024, tracking: 0.14, maxLines: 1, align: 'left', decor: 'plain',
          candidates: [{ x: .05, y: .450, w: .56, h: .042 }] },
        { role: 'release', size: 0.024, tracking: 0.10, maxLines: 1, align: 'left', decor: 'accent',
          candidates: [{ x: .05, y: .730, w: .55, h: .040 }] },
        { role: 'credit', size: 0.016, tracking: 0.02, maxLines: 2, align: 'right', decor: 'plain',
          candidates: [{ x: .30, y: .880, w: .65, h: .050 }] }
      ],
      surfaces: ['platformBar', 'sideBand', 'ratingBox', 'noticeStrip'],
      overlays: ['scanline', 'grain', 'chromaEdge', 'neonGlow']
    }
  ],

  adult: [
    {
      id: 'adult-obi', aspect: 0.700,
      slots: [
        { role: 'title', size: 0.098, tracking: 0.03, maxLines: 2, align: 'center', big: true, decor: 'title',
          candidates: [{ x: .06, y: .100, w: .88, h: .155 }, { x: .06, y: .520, w: .88, h: .155 }] },
        { role: 'name', size: 0.044, tracking: 0.12, maxLines: 1, align: 'center', decor: 'accent',
          candidates: [{ x: .08, y: .285, w: .84, h: .055 }, { x: .08, y: .690, w: .84, h: .055 }] },
        { role: 'badge', size: 0.026, tracking: 0.05, maxLines: 1, align: 'left', decor: 'accent',
          candidates: [{ x: .06, y: .390, w: .50, h: .050 }, { x: .06, y: .620, w: .50, h: .050 }] },
        { role: 'catch', size: 0.038, tracking: 0.03, maxLines: 2, align: 'center', onSurface: 'obi', decor: 'accent',
          candidates: [{ x: .07, y: .800, w: .86, h: .075 }] },
        { role: 'extra', size: 0.018, tracking: 0.02, maxLines: 2, align: 'left', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: .07, y: .885, w: .55, h: .048 }] },
        { role: 'code', size: 0.016, tracking: 0.14, maxLines: 1, align: 'left', latin: true, onSurface: 'obi', decor: 'plain',
          candidates: [{ x: .06, y: .945, w: .40, h: .030 }] }
      ],
      surfaces: ['obi', 'diagonalBand', 'cornerPlate', 'barcode'],
      overlays: ['grain', 'neonGlow', 'halation', 'bloom']
    },
    {
      id: 'adult-vertical', aspect: 0.700,
      slots: [
        { role: 'title', size: 0.082, tracking: 0.10, maxLines: 1, align: 'top', vertical: true, big: true, decor: 'title',
          candidates: [{ x: .72, y: .060, w: .18, h: .580 }, { x: .08, y: .060, w: .18, h: .580 }] },
        { role: 'name', size: 0.036, tracking: 0.16, maxLines: 1, align: 'top', vertical: true, decor: 'accent',
          candidates: [{ x: .59, y: .100, w: .11, h: .300 }, { x: .24, y: .100, w: .11, h: .300 }] },
        { role: 'badge', size: 0.026, tracking: 0.05, maxLines: 2, align: 'left', decor: 'accent',
          candidates: [{ x: .06, y: .700, w: .50, h: .060 }] },
        { role: 'catch', size: 0.024, tracking: 0.04, maxLines: 1, align: 'center', onSurface: 'ribbon', decor: 'accent',
          candidates: [{ x: .08, y: .878, w: .62, h: .048 }] },
        { role: 'release', size: 0.020, tracking: 0.08, maxLines: 1, align: 'left', decor: 'plain',
          candidates: [{ x: .06, y: .790, w: .50, h: .035 }] },
        { role: 'code', size: 0.015, tracking: 0.14, maxLines: 1, align: 'right', latin: true, decor: 'plain',
          candidates: [{ x: .55, y: .950, w: .38, h: .028 }] }
      ],
      surfaces: ['ribbon', 'sideBand', 'tapeStrip', 'discSpine'],
      overlays: ['grain', 'bokehDots', 'softFocus', 'neonGlow', 'lightLeak']
    },
    {
      id: 'adult-strip', aspect: 0.705,
      slots: [
        { role: 'tag', size: 0.020, tracking: 0.26, maxLines: 1, align: 'left', latin: true, decor: 'plain',
          candidates: [{ x: .06, y: .060, w: .55, h: .032 }] },
        { role: 'title', size: 0.102, tracking: 0.02, maxLines: 2, align: 'left', big: true, decor: 'title',
          candidates: [{ x: .05, y: .115, w: .82, h: .160 }, { x: .05, y: .520, w: .86, h: .160 }] },
        { role: 'catch', size: 0.030, tracking: 0.05, maxLines: 2, align: 'left', decor: 'accent',
          candidates: [{ x: .06, y: .300, w: .74, h: .085 }] },
        { role: 'name', size: 0.042, tracking: 0.12, maxLines: 1, align: 'left', decor: 'accent',
          candidates: [{ x: .06, y: .620, w: .60, h: .055 }, { x: .06, y: .410, w: .60, h: .055 }] },
        { role: 'badge', size: 0.024, tracking: 0.05, maxLines: 1, align: 'left', decor: 'accent',
          candidates: [{ x: .06, y: .700, w: .45, h: .045 }] },
        { role: 'extra', size: 0.017, tracking: 0.02, maxLines: 3, align: 'left', onSurface: 'gridPlate', decor: 'plain',
          candidates: [{ x: .325, y: .818, w: .60, h: .110 }] },
        { role: 'code', size: 0.015, tracking: 0.14, maxLines: 1, align: 'left', latin: true, decor: 'plain',
          candidates: [{ x: .06, y: .955, w: .22, h: .028 }] }
      ],
      surfaces: ['diagonalBand', 'gridPlate', 'sealBadge', 'topGradient'],
      overlays: ['neonGlow', 'halation', 'grain', 'chromaEdge']
    },
    {
      id: 'adult-frame', aspect: 0.695,
      slots: [
        { role: 'title', size: 0.080, tracking: 0.06, maxLines: 2, align: 'center', big: true, onSurface: 'plate', decor: 'title',
          candidates: [{ x: .14, y: .305, w: .72, h: .130 }] },
        { role: 'name', size: 0.028, tracking: 0.18, maxLines: 1, align: 'center', onSurface: 'plate', decor: 'plain',
          candidates: [{ x: .16, y: .458, w: .68, h: .045 }] },
        { role: 'badge', size: 0.026, tracking: 0.05, maxLines: 1, align: 'center', decor: 'accent',
          candidates: [{ x: .12, y: .630, w: .76, h: .050 }] },
        { role: 'catch', size: 0.036, tracking: 0.03, maxLines: 2, align: 'center', onSurface: 'obi', decor: 'accent',
          candidates: [{ x: .07, y: .800, w: .86, h: .072 }] },
        { role: 'extra', size: 0.017, tracking: 0.02, maxLines: 2, align: 'left', onSurface: 'obi', decor: 'plain',
          candidates: [{ x: .07, y: .882, w: .55, h: .045 }] },
        { role: 'code', size: 0.015, tracking: 0.14, maxLines: 1, align: 'right', latin: true, onSurface: 'obi', decor: 'plain',
          candidates: [{ x: .55, y: .943, w: .38, h: .030 }] }
      ],
      surfaces: ['plate', 'frame', 'obi', 'tapeStrip'],
      overlays: ['grain', 'vignette', 'inkBleed', 'softFocus']
    }
  ]
};
