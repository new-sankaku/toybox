import { buildIntegral, integralSum } from './analysis.js';

const MATCH_TOLERANCE = 0.15;
const PANORAMA_ASPECT = 2.2;
const TOWER_ASPECT = 0.45;
const MIN_CROP_WIDTH_RATIO = 0.35;
const MAX_TRIM_PER_SIDE = 0.25;
const SEARCH_STEPS = 26;
const HEADROOM_MIN = 0.35;
const HEADROOM_MAX = 0.70;
const THIRDS = [1 / 3, 2 / 3];

export function analyzeImageFit(srcW, srcH, targetAspect) {
  const srcAspect = srcW / srcH;
  const ratio = srcAspect / targetAspect;
  let kind;
  if (ratio >= 1 - MATCH_TOLERANCE && ratio <= 1 + MATCH_TOLERANCE) {
    kind = 'match';
  } else if (srcAspect >= PANORAMA_ASPECT) {
    kind = 'panorama';
  } else if (srcAspect <= TOWER_ASPECT) {
    kind = 'tower';
  } else if (ratio > 1) {
    kind = 'wide';
  } else {
    kind = 'tall';
  }
  return { srcAspect: srcAspect, ratio: ratio, kind: kind };
}

function rowProfile(map, w, h) {
  const rows = new Float32Array(h);
  for (let y = 0; y < h; y++) {
    let sum = 0, sum2 = 0;
    for (let x = 0; x < w; x++) {
      const v = map[y * w + x];
      sum += v;
      sum2 += v * v;
    }
    const mean = sum / w;
    rows[y] = mean + Math.sqrt(Math.max(0, sum2 / w - mean * mean));
  }
  return rows;
}

function colProfile(map, w, h) {
  const cols = new Float32Array(w);
  for (let x = 0; x < w; x++) {
    let sum = 0, sum2 = 0;
    for (let y = 0; y < h; y++) {
      const v = map[y * w + x];
      sum += v;
      sum2 += v * v;
    }
    const mean = sum / h;
    cols[x] = mean + Math.sqrt(Math.max(0, sum2 / h - mean * mean));
  }
  return cols;
}

function trimLow(profile, limit) {
  let total = 0;
  let peak = 0;
  for (let i = 0; i < profile.length; i++) {
    total += profile[i];
    if (profile[i] > peak) { peak = profile[i]; }
  }
  if (peak < 0.02) { return { start: 0, end: profile.length }; }
  const mean = total / profile.length;
  const enter = Math.min(peak * 0.05, mean * 0.10);
  const leave = peak * 0.22;
  const maxTrim = Math.floor(profile.length * limit);
  const blurMargin = Math.ceil(profile.length * 0.045);
  let start = 0;
  if (profile[0] < enter) {
    while (start < maxTrim && profile[start] < leave) { start++; }
    if (start > 0) { start = Math.min(maxTrim, start + blurMargin); }
  }
  let end = profile.length;
  if (profile[end - 1] < enter) {
    while (profile.length - end < maxTrim && end > start + 1 && profile[end - 1] < leave) { end--; }
    if (end < profile.length) { end = Math.max(start + 1, end - Math.min(blurMargin, maxTrim - (profile.length - end))); }
  }
  return { start: start, end: end };
}

function trimFlatBands(saliency) {
  const map = saliency.map, w = saliency.w, h = saliency.h;
  const vertical = trimLow(rowProfile(map, w, h), MAX_TRIM_PER_SIDE);
  const horizontal = trimLow(colProfile(map, w, h), MAX_TRIM_PER_SIDE);
  return {
    x: horizontal.start / w,
    y: vertical.start / h,
    w: (horizontal.end - horizontal.start) / w,
    h: (vertical.end - vertical.start) / h
  };
}

function expandToFaces(region, faces) {
  if (!faces || faces.length === 0) { return region; }
  let x0 = region.x, y0 = region.y, x1 = region.x + region.w, y1 = region.y + region.h;
  for (let i = 0; i < faces.length; i++) {
    const f = faces[i];
    const marginY = f.h * (HEADROOM_MAX + 0.15);
    if (f.x < x0) { x0 = f.x; }
    if (f.y - marginY < y0) { y0 = Math.max(0, f.y - marginY); }
    if (f.x + f.w > x1) { x1 = f.x + f.w; }
    if (f.y + f.h > y1) { y1 = f.y + f.h; }
  }
  return { x: Math.max(0, x0), y: Math.max(0, y0), w: Math.min(1, x1) - Math.max(0, x0), h: Math.min(1, y1) - Math.max(0, y0) };
}

function saliencyCentroid(saliency) {
  const map = saliency.map, w = saliency.w, h = saliency.h;
  let sx = 0, sy = 0, sw = 0;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const v = map[y * w + x];
      sx += (x + 0.5) * v;
      sy += (y + 0.5) * v;
      sw += v;
    }
  }
  if (sw <= 0) { return { x: 0.5, y: 0.5, weight: 0 }; }
  return { x: sx / sw / w, y: sy / sw / h, weight: sw };
}

function faceFocus(faces) {
  let sx = 0, sy = 0, sw = 0;
  for (let i = 0; i < faces.length; i++) {
    const f = faces[i];
    const weight = f.w * f.h;
    sx += (f.x + f.w * 0.5) * weight;
    sy += (f.y + f.h * 0.5) * weight;
    sw += weight;
  }
  if (sw <= 0) { return null; }
  return { x: sx / sw, y: sy / sw };
}

function intersectRatio(face, rect) {
  const x0 = Math.max(face.x, rect.x);
  const y0 = Math.max(face.y, rect.y);
  const x1 = Math.min(face.x + face.w, rect.x + rect.w);
  const y1 = Math.min(face.y + face.h, rect.y + rect.h);
  if (x1 <= x0 || y1 <= y0) { return 0; }
  return ((x1 - x0) * (y1 - y0)) / (face.w * face.h);
}

function thirdsBonus(value) {
  let best = 0;
  for (let i = 0; i < THIRDS.length; i++) {
    const d = Math.abs(value - THIRDS[i]);
    if (d < 0.07) {
      const b = 1 - d / 0.07;
      if (b > best) { best = b; }
    }
  }
  return best;
}

function buildZoomLevels(kind, rng) {
  const jitter = rng ? rng.range(-0.04, 0.06) : 0;
  if (kind === 'panorama' || kind === 'tower') {
    return [1, 1.18 + jitter, 1.38 + jitter, 1.62 + jitter];
  }
  if (kind === 'match') {
    return [1, 1.08 + jitter];
  }
  return [1, 1.12 + jitter, 1.28 + jitter];
}

function evaluateWindow(context, rect) {
  const faces = context.faces;
  const required = context.required;
  let clippedFace = 0;
  for (let i = 0; i < faces.length; i++) {
    const r = intersectRatio(faces[i], rect);
    if (r > 0.02 && r < 0.985) { clippedFace += (1 - r) * faces[i].w * faces[i].h; }
  }
  if (clippedFace > 0 && context.strictFaces) { return null; }

  let missing = 0;
  for (let i = 0; i < required.length; i++) {
    if (intersectRatio(required[i], rect) < 0.985) { missing++; }
  }
  if (missing > 0 && context.strictFaces) { return null; }

  let headroom = 0;
  let headroomScore = 0;
  if (required.length > 0) {
    let topFace = required[0];
    for (let i = 1; i < required.length; i++) {
      if (required[i].y < topFace.y) { topFace = required[i]; }
    }
    const margin = (topFace.y - rect.y) / topFace.h;
    headroom = margin;
    if (context.strictFaces && (margin < 0.12 || margin > 1.6)) { return null; }
    const center = (HEADROOM_MIN + HEADROOM_MAX) * 0.5;
    const spread = (HEADROOM_MAX - HEADROOM_MIN) * 0.85;
    headroomScore = Math.exp(-((margin - center) * (margin - center)) / (2 * spread * spread));
  }

  let density = 0;
  let coverage = 0;
  if (context.integral) {
    const mw = context.mapW, mh = context.mapH;
    const x0 = Math.max(0, Math.min(mw - 1, Math.round(rect.x * mw)));
    const y0 = Math.max(0, Math.min(mh - 1, Math.round(rect.y * mh)));
    const x1 = Math.max(x0 + 1, Math.min(mw, Math.round((rect.x + rect.w) * mw)));
    const y1 = Math.max(y0 + 1, Math.min(mh, Math.round((rect.y + rect.h) * mh)));
    const sum = integralSum(context.integral, mw, x0, y0, x1 - x0, y1 - y0);
    density = sum / ((x1 - x0) * (y1 - y0));
    coverage = context.totalSaliency > 0 ? sum / context.totalSaliency : 0;
  }
  const densityScore = context.meanSaliency > 0 ? Math.min(1.6, density / context.meanSaliency) / 1.6 : 0;

  const focus = context.focus;
  const relX = (focus.x - rect.x) / rect.w;
  const relY = (focus.y - rect.y) / rect.h;
  let composition = 0;
  let snapped = false;
  if (relX >= 0 && relX <= 1 && relY >= 0 && relY <= 1) {
    const bx = thirdsBonus(relX);
    const by = thirdsBonus(relY);
    composition = 0.5 * bx + 0.5 * by;
    snapped = bx > 0.5 || by > 0.5;
  }

  const drift = context.driftX * (relX - 0.5) + context.driftY * (relY - 0.5);

  let score = 0.42 * densityScore
    + 0.30 * coverage
    + 0.16 * headroomScore
    + 0.12 * composition
    + 0.05 * drift
    - 0.10 * (context.zoom - 1)
    - 2.5 * clippedFace
    - 0.35 * missing;

  score += context.noise;

  return { score: score, snapped: snapped, headroom: headroom, clippedFace: clippedFace, missing: missing };
}

function searchWindows(context, region, cropW, cropH, rng) {
  const spanX = region.w - cropW;
  const spanY = region.h - cropH;
  const stepsX = spanX > 1e-6 ? SEARCH_STEPS : 1;
  const stepsY = spanY > 1e-6 ? SEARCH_STEPS : 1;
  let best = null;
  for (let iy = 0; iy < stepsY; iy++) {
    const ty = stepsY === 1 ? 0 : iy / (stepsY - 1);
    const y = region.y + Math.max(0, spanY) * ty;
    for (let ix = 0; ix < stepsX; ix++) {
      const tx = stepsX === 1 ? 0 : ix / (stepsX - 1);
      const x = region.x + Math.max(0, spanX) * tx;
      const rect = { x: x, y: y, w: cropW, h: cropH };
      context.noise = rng ? rng.range(-0.018, 0.018) : 0;
      const result = evaluateWindow(context, rect);
      if (!result) { continue; }
      if (!best || result.score > best.score) {
        best = { score: result.score, rect: rect, snapped: result.snapped, clippedFace: result.clippedFace };
      }
    }
  }
  return best;
}

function orderFacesByArea(faces) {
  return faces.slice().sort(function (a, b) { return (b.w * b.h) - (a.w * a.h); });
}

export function computeCropRect(srcW, srcH, targetAspect, faces, saliency, rng) {
  const fit = analyzeImageFit(srcW, srcH, targetAspect);
  const faceList = faces ? faces.slice() : [];
  const hasSaliency = !!(saliency && saliency.map && saliency.w > 0 && saliency.h > 0);

  const modeParts = [];
  let region = { x: 0, y: 0, w: 1, h: 1 };
  if (hasSaliency) {
    const trimmed = trimFlatBands(saliency);
    if (trimmed.w > 0.4 && trimmed.h > 0.4 && (trimmed.w < 0.995 || trimmed.h < 0.995)) {
      region = expandToFaces(trimmed, faceList);
      modeParts.push('trim');
    }
  }
  if (region.w <= 0 || region.h <= 0) { region = { x: 0, y: 0, w: 1, h: 1 }; }

  const regionAspect = (region.w * srcW) / (region.h * srcH);
  let baseW, baseH;
  if (regionAspect > targetAspect) {
    baseH = region.h;
    baseW = (region.h * srcH * targetAspect) / srcW;
  } else {
    baseW = region.w;
    baseH = (region.w * srcW / targetAspect) / srcH;
  }

  let context;
  if (hasSaliency) {
    const integral = buildIntegral(saliency.map, saliency.w, saliency.h);
    let total = 0;
    for (let i = 0; i < saliency.map.length; i++) { total += saliency.map[i]; }
    context = {
      integral: integral,
      mapW: saliency.w,
      mapH: saliency.h,
      totalSaliency: total,
      meanSaliency: total / saliency.map.length
    };
    modeParts.push('saliency');
  } else {
    context = { integral: null, mapW: 0, mapH: 0, totalSaliency: 0, meanSaliency: 0 };
    modeParts.push('geometry');
  }

  const centroid = hasSaliency ? saliencyCentroid(saliency) : { x: 0.5, y: 0.5 };
  const facePoint = faceList.length > 0 ? faceFocus(faceList) : null;
  context.focus = facePoint ? { x: facePoint.x, y: Math.max(0.1, facePoint.y - 0.04) } : centroid;
  context.faces = faceList;
  context.driftX = rng ? rng.range(-1, 1) : 0;
  context.driftY = rng ? rng.range(-1, 1) : 0;
  context.noise = 0;

  const zoomLevels = buildZoomLevels(fit.kind, rng);
  const minCropW = Math.min(baseW, MIN_CROP_WIDTH_RATIO);
  const ordered = orderFacesByArea(faceList);

  let winner = null;
  let winnerZoom = 1;
  let winnerRequired = ordered.length;
  let oversizeFaces = false;

  for (let attempt = 0; attempt <= ordered.length; attempt++) {
    context.strictFaces = true;
    for (let z = 0; z < zoomLevels.length; z++) {
      const zoom = Math.max(1, zoomLevels[z]);
      let cropW = baseW / zoom;
      let cropH = baseH / zoom;
      if (cropW < minCropW) {
        const scale = minCropW / cropW;
        cropW *= scale;
        cropH *= scale;
      }
      if (cropW > region.w + 1e-6 || cropH > region.h + 1e-6) { continue; }
      const containable = [];
      for (let i = 0; i < ordered.length; i++) {
        if (ordered[i].w <= cropW * 0.98 && ordered[i].h <= cropH * 0.98) { containable.push(ordered[i]); }
      }
      context.faces = containable;
      context.required = containable.slice(0, Math.max(0, containable.length - attempt));
      context.zoom = baseW / cropW;
      const found = searchWindows(context, region, cropW, cropH, rng);
      if (found && (!winner || found.score > winner.score)) {
        winner = found;
        winnerZoom = Math.max(1, baseW / cropW);
        winnerRequired = context.required.length;
        oversizeFaces = containable.length < ordered.length;
      }
    }
    if (winner) { break; }
  }

  if (!winner) {
    context.faces = [];
    context.required = [];
    context.strictFaces = false;
    context.zoom = 1;
    winner = searchWindows(context, region, baseW, baseH, rng);
    winnerZoom = 1;
    winnerRequired = 0;
    modeParts.push('relaxed');
  }

  const rect = winner.rect;
  if (faceList.length > 0) {
    modeParts.push(winnerRequired === faceList.length ? 'face' : 'face' + winnerRequired + '/' + faceList.length);
    if (oversizeFaces) { modeParts.push('face-oversize'); }
  }
  if (winner.snapped) { modeParts.push('thirds'); }
  if (winnerZoom > 1.01) { modeParts.push('zoom' + winnerZoom.toFixed(2)); }
  if (winner.clippedFace > 0) { modeParts.push('face-clipped'); }
  modeParts.push(fit.kind);

  const x = Math.max(0, Math.min(srcW - 1, Math.round(rect.x * srcW)));
  const y = Math.max(0, Math.min(srcH - 1, Math.round(rect.y * srcH)));
  const w = Math.max(1, Math.min(srcW - x, Math.round(rect.w * srcW)));
  const h = Math.max(1, Math.min(srcH - y, Math.round(rect.h * srcH)));

  return {
    x: x,
    y: y,
    w: w,
    h: h,
    mode: modeParts.join('+'),
    zoom: winnerZoom
  };
}
