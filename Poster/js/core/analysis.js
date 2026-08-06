export const ANALYSIS_WIDTH = 192;

export function buildSampleBuffer(source, srcW, srcH) {
  const w = ANALYSIS_WIDTH;
  const h = Math.max(1, Math.round(w * srcH / srcW));
  const cv = document.createElement('canvas');
  cv.width = w;
  cv.height = h;
  const ctx = cv.getContext('2d', { willReadFrequently: true });
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = 'medium';
  ctx.drawImage(source, 0, 0, w, h);
  return { w: w, h: h, data: ctx.getImageData(0, 0, w, h).data };
}

export function computeLumaMap(buf) {
  const n = buf.w * buf.h;
  const out = new Float32Array(n);
  const d = buf.data;
  for (let i = 0; i < n; i++) {
    const p = i * 4;
    out[i] = (0.299 * d[p] + 0.587 * d[p + 1] + 0.114 * d[p + 2]) / 255;
  }
  return out;
}

export function computeEdgeMap(luma, w, h) {
  const out = new Float32Array(w * h);
  let max = 1e-6;
  for (let y = 1; y < h - 1; y++) {
    for (let x = 1; x < w - 1; x++) {
      const i = y * w + x;
      const tl = luma[i - w - 1], tc = luma[i - w], tr = luma[i - w + 1];
      const ml = luma[i - 1], mr = luma[i + 1];
      const bl = luma[i + w - 1], bc = luma[i + w], br = luma[i + w + 1];
      const gx = (tr + 2 * mr + br) - (tl + 2 * ml + bl);
      const gy = (bl + 2 * bc + br) - (tl + 2 * tc + tr);
      const mag = Math.sqrt(gx * gx + gy * gy);
      out[i] = mag;
      if (mag > max) { max = mag; }
    }
  }
  for (let i = 0; i < out.length; i++) { out[i] /= max; }
  return out;
}

export function buildIntegral(src, w, h) {
  const iw = w + 1;
  const out = new Float64Array(iw * (h + 1));
  for (let y = 0; y < h; y++) {
    let rowSum = 0;
    for (let x = 0; x < w; x++) {
      rowSum += src[y * w + x];
      out[(y + 1) * iw + (x + 1)] = out[y * iw + (x + 1)] + rowSum;
    }
  }
  return out;
}

export function integralSum(integral, w, x, y, rw, rh) {
  const iw = w + 1;
  const x0 = Math.max(0, Math.min(w, x));
  const y0 = Math.max(0, y);
  const x1 = Math.max(0, Math.min(w, x + rw));
  const y1 = Math.max(0, y + rh);
  return integral[y1 * iw + x1] - integral[y0 * iw + x1] - integral[y1 * iw + x0] + integral[y0 * iw + x0];
}
