const MAX_FACES = 5;
const MIN_FACE_SCORE = 0.34;
const NMS_IOU = 0.32;

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

function isSkinPixel(r, g, b) {
  const yv = 0.299 * r + 0.587 * g + 0.114 * b;
  if (yv < 48 || yv > 250) { return false; }
  const cb = 128 - 0.168736 * r - 0.331264 * g + 0.5 * b;
  const cr = 128 + 0.5 * r - 0.418688 * g - 0.081312 * b;
  if (cb < 74 || cb > 130 || cr < 132 || cr > 180) { return false; }
  if (cr + 0.6 * cb < 190 || cr + 0.6 * cb > 245) { return false; }
  if (r <= g || g < b - 14) { return false; }
  const max = r > g ? (r > b ? r : b) : (g > b ? g : b);
  const min = r < g ? (r < b ? r : b) : (g < b ? g : b);
  if (max - min < 12) { return false; }
  return true;
}

function iou(a, b) {
  const x0 = Math.max(a.x, b.x);
  const y0 = Math.max(a.y, b.y);
  const x1 = Math.min(a.x + a.w, b.x + b.w);
  const y1 = Math.min(a.y + a.h, b.y + b.h);
  if (x1 <= x0 || y1 <= y0) { return 0; }
  const inter = (x1 - x0) * (y1 - y0);
  return inter / (a.w * a.h + b.w * b.h - inter);
}

function suppress(boxes, threshold) {
  const sorted = boxes.slice().sort(function (p, q) { return q.score - p.score; });
  const kept = [];
  for (let i = 0; i < sorted.length; i++) {
    let blocked = false;
    for (let k = 0; k < kept.length; k++) {
      if (iou(sorted[i], kept[k]) > threshold) { blocked = true; break; }
    }
    if (!blocked) { kept.push(sorted[i]); }
    if (kept.length >= MAX_FACES) { break; }
  }
  return kept;
}

function clamp01(v) {
  return v < 0 ? 0 : (v > 1 ? 1 : v);
}

function labelComponents(mask, w, h) {
  const total = w * h;
  const visited = new Uint8Array(total);
  const stack = new Int32Array(total);
  const components = [];
  for (let start = 0; start < total; start++) {
    if (mask[start] !== 1 || visited[start] === 1) { continue; }
    let sp = 0;
    stack[sp++] = start;
    visited[start] = 1;
    let minX = w, minY = h, maxX = -1, maxY = -1, area = 0;
    while (sp > 0) {
      const idx = stack[--sp];
      const x = idx % w;
      const y = (idx - x) / w;
      area++;
      if (x < minX) { minX = x; }
      if (x > maxX) { maxX = x; }
      if (y < minY) { minY = y; }
      if (y > maxY) { maxY = y; }
      for (let dy = -1; dy <= 1; dy++) {
        const ny = y + dy;
        if (ny < 0 || ny >= h) { continue; }
        for (let dx = -1; dx <= 1; dx++) {
          const nx = x + dx;
          if (nx < 0 || nx >= w) { continue; }
          const nIdx = ny * w + nx;
          if (mask[nIdx] === 1 && visited[nIdx] === 0) { visited[nIdx] = 1; stack[sp++] = nIdx; }
        }
      }
    }
    components.push({ minX: minX, minY: minY, maxX: maxX, maxY: maxY, area: area });
  }
  return components;
}

export function detectFacesSkin(buf) {
  const w = buf.w, h = buf.h, d = buf.data;
  const total = w * h;
  const raw = new Uint8Array(total);
  let skinCount = 0;
  for (let i = 0; i < total; i++) {
    const p = i * 4;
    if (isSkinPixel(d[p], d[p + 1], d[p + 2])) { raw[i] = 1; skinCount++; }
  }
  if (skinCount < total * 0.004) { return []; }

  const opened = morph(morph(raw, w, h, 1, false), w, h, 1, true);
  const closed = morph(morph(opened, w, h, 2, true), w, h, 2, false);

  const components = labelComponents(closed, w, h);
  const candidates = [];
  for (let c = 0; c < components.length; c++) {
    const comp = components[c];
    const bw = comp.maxX - comp.minX + 1;
    const bh = comp.maxY - comp.minY + 1;
    if (bw < 4 || bh < 4) { continue; }
    const areaRatio = comp.area / total;
    if (areaRatio < 0.0035 || areaRatio > 0.35) { continue; }
    const aspect = bw / bh;
    if (aspect < 0.40 || aspect > 2.2) { continue; }
    const fill = comp.area / (bw * bh);
    if (fill < 0.42) { continue; }

    const fillScore = clamp01((fill - 0.42) / 0.36);
    const aspectLog = Math.log(aspect / 0.78);
    const aspectScore = Math.exp(-(aspectLog * aspectLog) / 0.18);
    const centerY = (comp.minY + comp.maxY) * 0.5 / h;
    const positionScore = clamp01(1.18 - centerY);
    const sizeLog = Math.log(areaRatio / 0.035);
    const sizeScore = Math.exp(-(sizeLog * sizeLog) / 1.8);
    const score = 0.36 * fillScore + 0.30 * aspectScore + 0.16 * positionScore + 0.18 * sizeScore;
    if (score < MIN_FACE_SCORE) { continue; }

    candidates.push({
      x: comp.minX / w,
      y: comp.minY / h,
      w: bw / w,
      h: bh / h,
      score: score,
      src: 'skin'
    });
  }
  return suppress(candidates, NMS_IOU);
}

async function detectFacesNative(source, srcW, srcH) {
  if (typeof window === 'undefined' || typeof window.FaceDetector !== 'function') { return null; }
  if (!srcW || !srcH) { return null; }
  try {
    const detector = new window.FaceDetector({ fastMode: true, maxDetectedFaces: MAX_FACES + 1 });
    const found = await detector.detect(source);
    if (!found || found.length === 0) { return null; }
    const out = [];
    for (let i = 0; i < found.length; i++) {
      const box = found[i].boundingBox;
      if (!box || box.width <= 0 || box.height <= 0) { continue; }
      const rect = {
        x: clamp01(box.x / srcW),
        y: clamp01(box.y / srcH),
        w: Math.min(1, box.width / srcW),
        h: Math.min(1, box.height / srcH),
        score: 1,
        src: 'native'
      };
      if (rect.x + rect.w > 1) { rect.w = 1 - rect.x; }
      if (rect.y + rect.h > 1) { rect.h = 1 - rect.y; }
      if (rect.w > 0.005 && rect.h > 0.005) { out.push(rect); }
    }
    if (out.length === 0) { return null; }
    out.sort(function (a, b) { return (b.w * b.h) - (a.w * a.h); });
    return out.slice(0, MAX_FACES);
  } catch (e) {
    return null;
  }
}

export async function detectFaces(source, buf) {
  const srcW = source ? (source.naturalWidth || source.width || 0) : 0;
  const srcH = source ? (source.naturalHeight || source.height || 0) : 0;
  const native = await detectFacesNative(source, srcW, srcH);
  if (native && native.length > 0) { return native; }
  if (!buf) { return []; }
  return detectFacesSkin(buf);
}

export function remapFaces(faces, crop, srcW, srcH) {
  const out = [];
  if (!faces || !crop || crop.w <= 0 || crop.h <= 0) { return out; }
  for (let i = 0; i < faces.length; i++) {
    const f = faces[i];
    const px0 = f.x * srcW;
    const py0 = f.y * srcH;
    const px1 = px0 + f.w * srcW;
    const py1 = py0 + f.h * srcH;
    const cx0 = Math.max(px0, crop.x);
    const cy0 = Math.max(py0, crop.y);
    const cx1 = Math.min(px1, crop.x + crop.w);
    const cy1 = Math.min(py1, crop.y + crop.h);
    if (cx1 <= cx0 || cy1 <= cy0) { continue; }
    const x = (cx0 - crop.x) / crop.w;
    const y = (cy0 - crop.y) / crop.h;
    const w = (cx1 - cx0) / crop.w;
    const h = (cy1 - cy0) / crop.h;
    if (w < 0.01 || h < 0.01) { continue; }
    out.push({
      x: x,
      y: y,
      w: w,
      h: h,
      score: f.score === undefined ? 1 : f.score,
      src: f.src,
      clipped: (cx1 - cx0) < (px1 - px0) - 1e-6 || (cy1 - cy0) < (py1 - py0) - 1e-6
    });
  }
  return out;
}
