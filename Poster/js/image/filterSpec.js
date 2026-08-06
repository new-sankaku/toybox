let canvasFilterSupported = null;

export function supportsCanvasFilter() {
  if (canvasFilterSupported !== null) { return canvasFilterSupported; }
  try {
    const cv = document.createElement('canvas');
    cv.width = 2;
    cv.height = 2;
    const ctx = cv.getContext('2d');
    ctx.filter = 'grayscale(50%)';
    canvasFilterSupported = (ctx.filter === 'grayscale(50%)');
  } catch (e) {
    canvasFilterSupported = false;
  }
  return canvasFilterSupported;
}

export function buildFilterSpec(rng, genre, intensity) {
  const k = Math.max(0, Math.min(1, intensity));
  const spec = {
    grayscale: 0,
    sepia: 0,
    saturate: 1,
    contrast: 1,
    brightness: 1,
    hueRotate: 0,
    blur: 0,
    mode: 'neutral'
  };
  const mode = rng.weighted([
    { v: 'neutral', w: 20 },
    { v: 'desaturate', w: 24 },
    { v: 'mono', w: 14 },
    { v: 'sepia', w: 12 },
    { v: 'vivid', w: 18 },
    { v: 'bleach', w: 10 },
    { v: 'shift', w: 8 }
  ]);
  if (mode === 'neutral') {
    spec.contrast = 1 + rng.range(0, 0.12) * k;
    spec.saturate = 1 + rng.range(-0.1, 0.15) * k;
  } else if (mode === 'desaturate') {
    spec.saturate = 1 - rng.range(0.30, 0.65) * k;
    spec.contrast = 1 + rng.range(0.05, 0.25) * k;
  } else if (mode === 'mono') {
    spec.grayscale = rng.range(0.80, 1.0);
    spec.contrast = 1 + rng.range(0.10, 0.35) * k;
  } else if (mode === 'sepia') {
    spec.sepia = rng.range(0.35, 0.80) * k;
    spec.saturate = 1 - rng.range(0.1, 0.3) * k;
    spec.brightness = 1 + rng.range(-0.05, 0.08);
  } else if (mode === 'vivid') {
    spec.saturate = 1 + rng.range(0.25, 0.75) * k;
    spec.contrast = 1 + rng.range(0.10, 0.30) * k;
    spec.brightness = 1 + rng.range(0.0, 0.10) * k;
  } else if (mode === 'bleach') {
    spec.brightness = 1 + rng.range(0.10, 0.26) * k;
    spec.contrast = 1 - rng.range(0.05, 0.18) * k;
    spec.saturate = 1 - rng.range(0.15, 0.45) * k;
  } else {
    spec.hueRotate = rng.range(-26, 26) * k;
    spec.saturate = 1 + rng.range(-0.15, 0.30) * k;
    spec.contrast = 1 + rng.range(0.04, 0.18) * k;
  }
  if (genre === 'gravure') {
    spec.brightness += 0.05 * k;
    spec.grayscale = Math.min(spec.grayscale, 0.35);
  }
  if (genre === 'novel') {
    spec.saturate = Math.min(spec.saturate, 1.05);
  }
  spec.mode = mode;
  return spec;
}

export function filterSpecToCss(spec, extraBlur) {
  const parts = [];
  if (spec.grayscale > 0.001) { parts.push('grayscale(' + (spec.grayscale * 100).toFixed(1) + '%)'); }
  if (spec.sepia > 0.001) { parts.push('sepia(' + (spec.sepia * 100).toFixed(1) + '%)'); }
  if (Math.abs(spec.saturate - 1) > 0.002) { parts.push('saturate(' + (spec.saturate * 100).toFixed(1) + '%)'); }
  if (Math.abs(spec.contrast - 1) > 0.002) { parts.push('contrast(' + (spec.contrast * 100).toFixed(1) + '%)'); }
  if (Math.abs(spec.brightness - 1) > 0.002) { parts.push('brightness(' + (spec.brightness * 100).toFixed(1) + '%)'); }
  if (Math.abs(spec.hueRotate || 0) > 0.05) { parts.push('hue-rotate(' + spec.hueRotate.toFixed(1) + 'deg)'); }
  const blur = (spec.blur || 0) + (extraBlur || 0);
  if (blur > 0.05) { parts.push('blur(' + blur.toFixed(2) + 'px)'); }
  return parts.length > 0 ? parts.join(' ') : 'none';
}

function boxBlurHorizontal(src, dst, w, h, radius) {
  const win = radius * 2 + 1;
  const inv = 1 / win;
  for (let y = 0; y < h; y++) {
    const row = y * w * 4;
    let sr = 0, sg = 0, sb = 0;
    for (let i = -radius; i <= radius; i++) {
      const x = i < 0 ? 0 : (i >= w ? w - 1 : i);
      const p = row + x * 4;
      sr += src[p]; sg += src[p + 1]; sb += src[p + 2];
    }
    for (let x = 0; x < w; x++) {
      const p = row + x * 4;
      dst[p] = sr * inv;
      dst[p + 1] = sg * inv;
      dst[p + 2] = sb * inv;
      dst[p + 3] = src[p + 3];
      const xo = x - radius;
      const xi = x + radius + 1;
      const po = row + (xo < 0 ? 0 : xo) * 4;
      const pi = row + (xi >= w ? w - 1 : xi) * 4;
      sr += src[pi] - src[po];
      sg += src[pi + 1] - src[po + 1];
      sb += src[pi + 2] - src[po + 2];
    }
  }
}

function boxBlurVertical(src, dst, w, h, radius) {
  const win = radius * 2 + 1;
  const inv = 1 / win;
  const stride = w * 4;
  for (let x = 0; x < w; x++) {
    const col = x * 4;
    let sr = 0, sg = 0, sb = 0;
    for (let i = -radius; i <= radius; i++) {
      const y = i < 0 ? 0 : (i >= h ? h - 1 : i);
      const p = y * stride + col;
      sr += src[p]; sg += src[p + 1]; sb += src[p + 2];
    }
    for (let y = 0; y < h; y++) {
      const p = y * stride + col;
      dst[p] = sr * inv;
      dst[p + 1] = sg * inv;
      dst[p + 2] = sb * inv;
      dst[p + 3] = src[p + 3];
      const yo = y - radius;
      const yi = y + radius + 1;
      const po = (yo < 0 ? 0 : yo) * stride + col;
      const pi = (yi >= h ? h - 1 : yi) * stride + col;
      sr += src[pi] - src[po];
      sg += src[pi + 1] - src[po + 1];
      sb += src[pi + 2] - src[po + 2];
    }
  }
}

export function applyFilterFallback(ctx, w, h, spec) {
  const img = ctx.getImageData(0, 0, w, h);
  const d = img.data;
  const gs = spec.grayscale || 0;
  const sp = spec.sepia || 0;
  const sa = spec.saturate === undefined ? 1 : spec.saturate;
  const co = spec.contrast === undefined ? 1 : spec.contrast;
  const br = spec.brightness === undefined ? 1 : spec.brightness;
  const hueDeg = spec.hueRotate || 0;
  const useHue = Math.abs(hueDeg) > 0.05;
  let h0 = 1, h1 = 0, h2 = 0, h3 = 0, h4 = 1, h5 = 0, h6 = 0, h7 = 0, h8 = 1;
  if (useHue) {
    const a = hueDeg * Math.PI / 180;
    const cs = Math.cos(a), sn = Math.sin(a);
    h0 = 0.213 + cs * 0.787 - sn * 0.213;
    h1 = 0.715 - cs * 0.715 - sn * 0.715;
    h2 = 0.072 - cs * 0.072 + sn * 0.928;
    h3 = 0.213 - cs * 0.213 + sn * 0.143;
    h4 = 0.715 + cs * 0.285 + sn * 0.140;
    h5 = 0.072 - cs * 0.072 - sn * 0.283;
    h6 = 0.213 - cs * 0.213 - sn * 0.787;
    h7 = 0.715 - cs * 0.715 + sn * 0.715;
    h8 = 0.072 + cs * 0.928 + sn * 0.072;
  }
  const len = d.length;
  for (let i = 0; i < len; i += 4) {
    let r = d[i], g = d[i + 1], b = d[i + 2];
    if (gs > 0) {
      const l = 0.2126 * r + 0.7152 * g + 0.0722 * b;
      r += (l - r) * gs; g += (l - g) * gs; b += (l - b) * gs;
    }
    if (sp > 0) {
      const sr = 0.393 * r + 0.769 * g + 0.189 * b;
      const sg2 = 0.349 * r + 0.686 * g + 0.168 * b;
      const sb = 0.272 * r + 0.534 * g + 0.131 * b;
      r += (sr - r) * sp; g += (sg2 - g) * sp; b += (sb - b) * sp;
    }
    if (sa !== 1) {
      const l = 0.2126 * r + 0.7152 * g + 0.0722 * b;
      r = l + (r - l) * sa; g = l + (g - l) * sa; b = l + (b - l) * sa;
    }
    if (co !== 1) {
      r = (r - 127.5) * co + 127.5;
      g = (g - 127.5) * co + 127.5;
      b = (b - 127.5) * co + 127.5;
    }
    if (br !== 1) { r *= br; g *= br; b *= br; }
    if (useHue) {
      const nr = h0 * r + h1 * g + h2 * b;
      const ng = h3 * r + h4 * g + h5 * b;
      const nb = h6 * r + h7 * g + h8 * b;
      r = nr; g = ng; b = nb;
    }
    d[i] = r;
    d[i + 1] = g;
    d[i + 2] = b;
  }
  const blur = spec.blur || 0;
  if (blur > 0.5) {
    const radius = Math.max(1, Math.round(blur));
    const tmp = new Uint8ClampedArray(len);
    boxBlurHorizontal(d, tmp, w, h, radius);
    boxBlurVertical(tmp, d, w, h, radius);
  }
  ctx.putImageData(img, 0, 0);
}

export function drawWithFilter(dstCtx, src, w, h, spec, extraBlur) {
  if (supportsCanvasFilter()) {
    dstCtx.save();
    dstCtx.filter = filterSpecToCss(spec, extraBlur);
    dstCtx.drawImage(src, 0, 0, w, h);
    dstCtx.restore();
    return;
  }
  dstCtx.save();
  dstCtx.filter = 'none';
  dstCtx.drawImage(src, 0, 0, w, h);
  dstCtx.restore();
  const merged = {
    grayscale: spec.grayscale,
    sepia: spec.sepia,
    saturate: spec.saturate,
    contrast: spec.contrast,
    brightness: spec.brightness,
    hueRotate: spec.hueRotate,
    blur: (spec.blur || 0) + (extraBlur || 0)
  };
  applyFilterFallback(dstCtx, w, h, merged);
}
