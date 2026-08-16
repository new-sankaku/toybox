(function (PF) {
'use strict';

const MIN_BACKGROUND_RATIO = 0.10;
const MAX_BACKGROUND_RATIO = 0.90;

const LINEAR_LUT = (function () {
  const lut = new Float32Array(256);
  for (let i = 0; i < 256; i++) {
    const v = i / 255;
    lut[i] = v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  }
  return lut;
})();

function labFinv(t) {
  return t > 0.008856451679 ? Math.cbrt(t) : (t * 7.787037037 + 0.137931034);
}

function buildLabChannels(buf) {
  const n = buf.w * buf.h;
  const d = buf.data;
  const L = new Float32Array(n);
  const A = new Float32Array(n);
  const B = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const p = i * 4;
    const r = LINEAR_LUT[d[p]];
    const g = LINEAR_LUT[d[p + 1]];
    const b = LINEAR_LUT[d[p + 2]];
    const x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047;
    const y = (0.2126 * r + 0.7152 * g + 0.0722 * b);
    const z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883;
    const fx = labFinv(x);
    const fy = labFinv(y);
    const fz = labFinv(z);
    L[i] = 116 * fy - 16;
    A[i] = 500 * (fx - fy);
    B[i] = 200 * (fy - fz);
  }
  return { L: L, A: A, B: B };
}

function buildCountIntegral(mask, w, h) {
  const iw = w + 1;
  const out = new Int32Array(iw * (h + 1));
  for (let y = 0; y < h; y++) {
    let rowSum = 0;
    for (let x = 0; x < w; x++) {
      rowSum += mask[y * w + x];
      out[(y + 1) * iw + (x + 1)] = out[y * iw + (x + 1)] + rowSum;
    }
  }
  return out;
}

function morph(mask, w, h, radius, dilate) {
  const integral = buildCountIntegral(mask, w, h);
  const iw = w + 1;
  const out = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) {
    const y0 = y - radius < 0 ? 0 : y - radius;
    const y1 = y + radius + 1 > h ? h : y + radius + 1;
    for (let x = 0; x < w; x++) {
      const x0 = x - radius < 0 ? 0 : x - radius;
      const x1 = x + radius + 1 > w ? w : x + radius + 1;
      const count = integral[y1 * iw + x1] - integral[y0 * iw + x1] - integral[y1 * iw + x0] + integral[y0 * iw + x0];
      const area = (x1 - x0) * (y1 - y0);
      out[y * w + x] = dilate ? (count > 0 ? 1 : 0) : (count === area ? 1 : 0);
    }
  }
  return out;
}

function blurMask(mask, w, h, radius) {
  const tmp = new Float32Array(w * h);
  const out = new Float32Array(w * h);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      let sum = 0, count = 0;
      for (let k = -radius; k <= radius; k++) {
        const xx = x + k;
        if (xx < 0 || xx >= w) { continue; }
        sum += mask[y * w + xx];
        count++;
      }
      tmp[y * w + x] = sum / count;
    }
  }
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      let sum = 0, count = 0;
      for (let k = -radius; k <= radius; k++) {
        const yy = y + k;
        if (yy < 0 || yy >= h) { continue; }
        sum += tmp[yy * w + x];
        count++;
      }
      out[y * w + x] = sum / count;
    }
  }
  return out;
}

function collectSeeds(w, h) {
  const corners = [0, w - 1, (h - 1) * w, (h - 1) * w + w - 1];
  const edges = [];
  for (let x = 1; x < w - 1; x++) { edges.push(x); edges.push((h - 1) * w + x); }
  for (let y = 1; y < h - 1; y++) { edges.push(y * w); edges.push(y * w + w - 1); }
  return corners.concat(edges);
}

function buildSubjectMask(buf, tolerance) {
  const w = buf.w, h = buf.h;
  const total = w * h;
  if (total < 64) { return null; }

  const lab = buildLabChannels(buf);
  const L = lab.L, A = lab.A, B = lab.B;

  const seeds = collectSeeds(w, h);
  let refL = 0, refA = 0, refB = 0;
  for (let i = 0; i < seeds.length; i++) {
    refL += L[seeds[i]];
    refA += A[seeds[i]];
    refB += B[seeds[i]];
  }
  refL /= seeds.length;
  refA /= seeds.length;
  refB /= seeds.length;

  const localTol = Math.max(4, tolerance * 0.28);
  const globalTol = localTol * 2.8;

  const bg = new Uint8Array(total);
  const queue = new Int32Array(total);
  let head = 0, tail = 0;
  for (let i = 0; i < seeds.length; i++) {
    const idx = seeds[i];
    if (bg[idx] === 0) { bg[idx] = 1; queue[tail++] = idx; }
  }

  function deltaLocal(a, b) {
    const dl = L[a] - L[b];
    const da = A[a] - A[b];
    const db = B[a] - B[b];
    return Math.sqrt(dl * dl + da * da + db * db);
  }
  function deltaGlobal(a) {
    const dl = L[a] - refL;
    const da = A[a] - refA;
    const db = B[a] - refB;
    return Math.sqrt(dl * dl + da * da + db * db);
  }

  while (head < tail) {
    const idx = queue[head++];
    const x = idx % w;
    const y = (idx - x) / w;
    for (let k = 0; k < 4; k++) {
      let nIdx;
      if (k === 0) { if (x === 0) { continue; } nIdx = idx - 1; }
      else if (k === 1) { if (x === w - 1) { continue; } nIdx = idx + 1; }
      else if (k === 2) { if (y === 0) { continue; } nIdx = idx - w; }
      else { if (y === h - 1) { continue; } nIdx = idx + w; }
      if (bg[nIdx] === 1) { continue; }
      if (deltaLocal(idx, nIdx) > localTol) { continue; }
      if (deltaGlobal(nIdx) > globalTol) { continue; }
      bg[nIdx] = 1;
      queue[tail++] = nIdx;
    }
  }

  const subject = new Uint8Array(total);
  for (let i = 0; i < total; i++) { subject[i] = bg[i] === 1 ? 0 : 1; }

  const closed = morph(morph(subject, w, h, 2, true), w, h, 2, false);
  const cleaned = morph(morph(closed, w, h, 1, false), w, h, 1, true);

  let subjectCount = 0;
  for (let i = 0; i < total; i++) { if (cleaned[i] === 1) { subjectCount++; } }
  const ratio = 1 - subjectCount / total;
  if (ratio < MIN_BACKGROUND_RATIO || ratio > MAX_BACKGROUND_RATIO) { return null; }

  const raw = new Float32Array(total);
  for (let i = 0; i < total; i++) { raw[i] = cleaned[i]; }
  return { mask: blurMask(raw, w, h, 2), ratio: ratio };
}

function maskToCanvas(mask, w, h) {
  const cv = document.createElement('canvas');
  cv.width = w;
  cv.height = h;
  const ctx = cv.getContext('2d');
  const img = ctx.createImageData(w, h);
  const data = img.data;
  for (let i = 0; i < w * h; i++) {
    const p = i * 4;
    data[p] = 255;
    data[p + 1] = 255;
    data[p + 2] = 255;
    const v = mask[i];
    data[p + 3] = Math.round((v < 0 ? 0 : (v > 1 ? 1 : v)) * 255);
  }
  ctx.putImageData(img, 0, 0);
  return cv;
}

Object.assign(PF, { buildSubjectMask, maskToCanvas });
})(window.PF = window.PF || {});
