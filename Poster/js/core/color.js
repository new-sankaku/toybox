(function (PF) {
'use strict';

function clamp255(v) {
  return v < 0 ? 0 : (v > 255 ? 255 : v);
}

function srgbToLinear(c) {
  const v = c / 255;
  return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
}

function relativeLuminance(r, g, b) {
  return 0.2126 * srgbToLinear(r) + 0.7152 * srgbToLinear(g) + 0.0722 * srgbToLinear(b);
}

function contrastRatio(rgbA, rgbB) {
  const la = relativeLuminance(rgbA[0], rgbA[1], rgbA[2]);
  const lb = relativeLuminance(rgbB[0], rgbB[1], rgbB[2]);
  const hi = Math.max(la, lb);
  const lo = Math.min(la, lb);
  return (hi + 0.05) / (lo + 0.05);
}

function hexToRgb(hex) {
  const h = hex.replace('#', '');
  return [
    parseInt(h.substring(0, 2), 16),
    parseInt(h.substring(2, 4), 16),
    parseInt(h.substring(4, 6), 16)
  ];
}

function rgbToCss(rgb, alpha) {
  const r = Math.round(clamp255(rgb[0]));
  const g = Math.round(clamp255(rgb[1]));
  const b = Math.round(clamp255(rgb[2]));
  if (alpha === undefined || alpha >= 1) { return 'rgb(' + r + ',' + g + ',' + b + ')'; }
  return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
}

function blendRgb(bg, fg, alpha) {
  return [
    bg[0] * (1 - alpha) + fg[0] * alpha,
    bg[1] * (1 - alpha) + fg[1] * alpha,
    bg[2] * (1 - alpha) + fg[2] * alpha
  ];
}

function shade(rgb, amount) {
  if (amount >= 0) {
    return [
      rgb[0] + (255 - rgb[0]) * amount,
      rgb[1] + (255 - rgb[1]) * amount,
      rgb[2] + (255 - rgb[2]) * amount
    ];
  }
  const k = 1 + amount;
  return [rgb[0] * k, rgb[1] * k, rgb[2] * k];
}

function luma01(rgb) {
  return (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255;
}

function rgbToHsl(rgb) {
  const r = rgb[0] / 255, g = rgb[1] / 255, b = rgb[2] / 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  const l = (max + min) / 2;
  if (max === min) { return [0, 0, l]; }
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let h;
  if (max === r) { h = ((g - b) / d + (g < b ? 6 : 0)) / 6; }
  else if (max === g) { h = ((b - r) / d + 2) / 6; }
  else { h = ((r - g) / d + 4) / 6; }
  return [h, s, l];
}

function hueToRgb(p, q, t) {
  let x = t;
  if (x < 0) { x += 1; }
  if (x > 1) { x -= 1; }
  if (x < 1 / 6) { return p + (q - p) * 6 * x; }
  if (x < 1 / 2) { return q; }
  if (x < 2 / 3) { return p + (q - p) * (2 / 3 - x) * 6; }
  return p;
}

function hslToRgb(hsl) {
  const h = hsl[0], s = hsl[1], l = hsl[2];
  if (s === 0) { return [l * 255, l * 255, l * 255]; }
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
  const p = 2 * l - q;
  return [
    hueToRgb(p, q, h + 1 / 3) * 255,
    hueToRgb(p, q, h) * 255,
    hueToRgb(p, q, h - 1 / 3) * 255
  ];
}

Object.assign(PF, {
  clamp255, srgbToLinear, relativeLuminance, contrastRatio, hexToRgb, rgbToCss, blendRgb, shade, luma01,
  rgbToHsl, hslToRgb
});
})(window.PF = window.PF || {});
