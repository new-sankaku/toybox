(function (PF) {
'use strict';

const ANCHOR_BASE = {
  filmScrim: { x: 0.000, y: 0.720, w: 1.000, h: 0.280 },
  billingPlate: { x: 0.000, y: 0.900, w: 1.000, h: 0.100 },
  specBand: { x: 0.000, y: 0.815, w: 1.000, h: 0.185 },
  obi: { x: 0.000, y: 0.660, w: 1.000, h: 0.340 },
  obiBox: { x: 0.045, y: 0.904, w: 0.430, h: 0.060 },
  voiceTopStrip: { x: 0.000, y: 0.000, w: 1.000, h: 0.048 },
  voicePlate: { x: 0.035, y: 0.755, w: 0.430, h: 0.155 },
  voiceFootBand: { x: 0.000, y: 0.928, w: 1.000, h: 0.072 },
  cvPlateRight: { x: 0.688, y: 0.846, w: 0.276, h: 0.088 },
  cvPlateLeft: { x: 0.036, y: 0.846, w: 0.276, h: 0.088 },
  voiceLogoPlate: { x: 0.028, y: 0.028, w: 0.208, h: 0.084 },
  circleMark: { x: 0.040, y: 0.075, w: 0.150, h: 0.200 },
  platformBand: { x: 0.000, y: 0.000, w: 1.000, h: 0.076 },
  platformTab: { x: 0.014, y: 0.016, w: 0.198, h: 0.114 },
  publisherRow: { x: 0.440, y: 0.884, w: 0.520, h: 0.056 },
  ratingPlate: { x: 0.040, y: 0.884, w: 0.088, h: 0.071 },
  gameFoot: { x: 0.000, y: 0.812, w: 1.000, h: 0.188 },
  seriesBand: { x: 0.000, y: 0.000, w: 1.000, h: 0.070 },
  avSash: { x: 0.040, y: 0.616, w: 0.640, h: 0.076, deg: -16 },
  avSpecBand: { x: 0.000, y: 0.855, w: 1.000, h: 0.145 },
  gridPlate: { x: 0.020, y: 0.828, w: 0.960, h: 0.160 },
  plate: { x: 0.080, y: 0.230, w: 0.840, h: 0.330 },
  laurelBadge: { x: 0.055, y: 0.045, w: 0.340, h: 0.100 },
  barcode: { x: 0.740, y: 0.925, w: 0.200, h: 0.055 },
  cornerPlate: { x: 0.545, y: 0.098, w: 0.415, h: 0.058 },
  waveBand: { x: 0.480, y: 0.882, w: 0.500, h: 0.042 },
  sealBadge: { x: 0.633, y: 0.232, w: 0.290, h: 0.410 },
  discSpine: { x: 0.000, y: 0.000, w: 0.030, h: 1.000 }
};

let active = null;
let touched = null;

function setActiveAnchors(map) {
  active = map || null;
}

// surface が実際に使った anchor を集める。文字配置はこれを占有領域として避ける。
function beginAnchorTrace() {
  touched = [];
}

function endAnchorTrace() {
  const out = touched || [];
  touched = null;
  return out;
}

function A(name) {
  const rect = (active && active[name]) ? active[name] : ANCHOR_BASE[name];
  if (touched && rect && touched.indexOf(rect) < 0) { touched.push(rect); }
  return rect;
}

function hasAnchor(name) {
  return !!(active && active[name]);
}

Object.assign(PF, { ANCHOR_BASE, setActiveAnchors, beginAnchorTrace, endAnchorTrace, A, hasAnchor });
})(window.PF = window.PF || {});
