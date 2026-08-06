import { computeEdgeMap, buildIntegral, integralSum } from './analysis.js';

const FACE_PENALTY = 3.2;
const OVERLAP_PENALTY = 2.5;
const ORDER_PENALTY = 0.04;
const VARIANCE_RADIUS = 2;

function resolveSaliencyMap(saliency, w, h) {
  if (!saliency) { return null; }
  const map = saliency.map ? saliency.map : saliency;
  if (!map || typeof map.length !== 'number' || map.length !== w * h) { return null; }
  return map;
}

function buildVarianceMap(luma, w, h) {
  const lumaIntegral = buildIntegral(luma, w, h);
  const squared = new Float32Array(w * h);
  for (let i = 0; i < squared.length; i++) { squared[i] = luma[i] * luma[i]; }
  const squaredIntegral = buildIntegral(squared, w, h);
  const out = new Float32Array(w * h);
  let max = 1e-6;
  for (let y = 0; y < h; y++) {
    const y0 = y - VARIANCE_RADIUS < 0 ? 0 : y - VARIANCE_RADIUS;
    const y1 = y + VARIANCE_RADIUS + 1 > h ? h : y + VARIANCE_RADIUS + 1;
    for (let x = 0; x < w; x++) {
      const x0 = x - VARIANCE_RADIUS < 0 ? 0 : x - VARIANCE_RADIUS;
      const x1 = x + VARIANCE_RADIUS + 1 > w ? w : x + VARIANCE_RADIUS + 1;
      const n = (x1 - x0) * (y1 - y0);
      const s = integralSum(lumaIntegral, w, x0, y0, x1 - x0, y1 - y0);
      const s2 = integralSum(squaredIntegral, w, x0, y0, x1 - x0, y1 - y0);
      const mean = s / n;
      const v = Math.max(0, s2 / n - mean * mean);
      out[y * w + x] = v;
      if (v > max) { max = v; }
    }
  }
  for (let i = 0; i < out.length; i++) { out[i] /= max; }
  return out;
}

function applyFacePenalty(cost, w, h, faces) {
  for (let f = 0; f < faces.length; f++) {
    const face = faces[f];
    const cx = (face.x + face.w / 2) * w;
    const cy = (face.y + face.h / 2) * h;
    const rx = Math.max(1, face.w * w * 0.78);
    const ry = Math.max(1, face.h * h * 0.86);
    const x0 = Math.max(0, Math.floor(cx - rx));
    const x1 = Math.min(w, Math.ceil(cx + rx));
    const y0 = Math.max(0, Math.floor(cy - ry));
    const y1 = Math.min(h, Math.ceil(cy + ry));
    for (let y = y0; y < y1; y++) {
      for (let x = x0; x < x1; x++) {
        const dx = (x - cx) / rx;
        const dy = (y - cy) / ry;
        const d2 = dx * dx + dy * dy;
        if (d2 <= 1) { cost[y * w + x] += FACE_PENALTY * (1 - d2 * 0.5); }
      }
    }
  }
}

export function buildCostMap(buf, luma, faces, avoidFace, saliency) {
  const w = buf.w, h = buf.h;
  const edge = computeEdgeMap(luma, w, h);
  const variance = buildVarianceMap(luma, w, h);
  const salient = resolveSaliencyMap(saliency, w, h);

  const edgeWeight = salient ? 0.40 : 0.55;
  const varianceWeight = salient ? 0.28 : 0.45;
  const saliencyWeight = 0.32;

  const cost = new Float32Array(w * h);
  for (let i = 0; i < cost.length; i++) {
    cost[i] = edgeWeight * edge[i] + varianceWeight * variance[i];
    if (salient) { cost[i] += saliencyWeight * salient[i]; }
  }

  if (avoidFace && faces && faces.length > 0) { applyFacePenalty(cost, w, h, faces); }

  return { cost: cost, integral: buildIntegral(cost, w, h), edge: edge };
}

export function rectCost(costInfo, w, h, rect) {
  const x = Math.max(0, Math.min(w - 1, Math.round(rect.x * w)));
  const y = Math.max(0, Math.min(h - 1, Math.round(rect.y * h)));
  const rw = Math.max(1, Math.min(w - x, Math.round(rect.w * w)));
  const rh = Math.max(1, Math.min(h - y, Math.round(rect.h * h)));
  return integralSum(costInfo.integral, w, x, y, rw, rh) / (rw * rh);
}

export function overlapRatio(a, b) {
  const x0 = Math.max(a.x, b.x);
  const y0 = Math.max(a.y, b.y);
  const x1 = Math.min(a.x + a.w, b.x + b.w);
  const y1 = Math.min(a.y + a.h, b.y + b.h);
  if (x1 <= x0 || y1 <= y0) { return 0; }
  return ((x1 - x0) * (y1 - y0)) / (a.w * a.h);
}

export function findBestRect(costInfo, w, h, candidates, occupied, slide) {
  let best = null;
  let bestScore = Infinity;
  const verticalSteps = 9;
  const horizontalSteps = 5;
  const horizontalSlide = slide * 0.45;
  const placed = occupied || [];
  for (let c = 0; c < candidates.length; c++) {
    const base = candidates[c];
    for (let s = 0; s < verticalSteps; s++) {
      const dy = (s / (verticalSteps - 1) - 0.5) * 2 * slide;
      for (let t = 0; t < horizontalSteps; t++) {
        const dx = horizontalSteps === 1 ? 0 : (t / (horizontalSteps - 1) - 0.5) * 2 * horizontalSlide;
        const rect = { x: base.x + dx, y: base.y + dy, w: base.w, h: base.h };
        if (rect.y < 0.01 || rect.y + rect.h > 0.99) { continue; }
        if (rect.x < 0.01 || rect.x + rect.w > 0.99) { continue; }
        let score = rectCost(costInfo, w, h, rect);
        score += c * ORDER_PENALTY;
        score += Math.abs(dx) * 0.30;
        score += Math.abs(dy) * 0.12;
        for (let o = 0; o < placed.length; o++) {
          score += overlapRatio(rect, placed[o]) * OVERLAP_PENALTY;
        }
        if (score < bestScore) { bestScore = score; best = rect; }
      }
    }
  }
  return best || candidates[0];
}

export function regionStats(buf, rect) {
  const w = buf.w, h = buf.h, d = buf.data;
  const x0 = Math.max(0, Math.round(rect.x * w));
  const y0 = Math.max(0, Math.round(rect.y * h));
  const x1 = Math.min(w, Math.round((rect.x + rect.w) * w));
  const y1 = Math.min(h, Math.round((rect.y + rect.h) * h));
  let r = 0, g = 0, b = 0, l = 0, l2 = 0, n = 0;
  for (let y = y0; y < y1; y++) {
    for (let x = x0; x < x1; x++) {
      const p = (y * w + x) * 4;
      r += d[p]; g += d[p + 1]; b += d[p + 2];
      const lum = (0.299 * d[p] + 0.587 * d[p + 1] + 0.114 * d[p + 2]) / 255;
      l += lum; l2 += lum * lum;
      n++;
    }
  }
  if (n === 0) { return { rgb: [128, 128, 128], luma: 0.5, std: 0.2 }; }
  const meanL = l / n;
  return {
    rgb: [r / n, g / n, b / n],
    luma: meanL,
    std: Math.sqrt(Math.max(0, l2 / n - meanL * meanL))
  };
}
