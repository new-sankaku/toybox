(function (PF) {
'use strict';

const MAX_FACES = 8;
const MIN_PROBABILITY = 0.70;
const IOU_THRESHOLD = 0.3;
const MERGE_IOU = 0.30;
const DETECT_LONG_EDGE = 384;
const BOX_EXPAND_TOP = 0.30;
const BOX_EXPAND_SIDE = 0.08;
const BOX_EXPAND_BOTTOM = 0.12;
const MIN_BOX_RATIO = 0.005;

// BlazeFaceは入力を128x128へ潰すため、画面に占める顔が小さいほどスコアが落ちる
// （実測: 全体像で0.23、顔が1/4を占めるcropで0.93）。粗→細のtile探索で小さい顔を拾う。
const PYRAMID = [1, 2];
const TILE_OVERLAP = 0.25;

let modelPromise = null;

function clamp01(v) {
  return v < 0 ? 0 : (v > 1 ? 1 : v);
}

function decodeBase64(text) {
  const bin = window.atob(text);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) { out[i] = bin.charCodeAt(i); }
  return out;
}

function modelArtifacts() {
  const src = window.PF_BLAZEFACE_ARTIFACTS;
  if (!src) {
    throw new Error('顔検出modelが読み込まれていません: vendor/model/blazeface.artifacts.js を確認してください');
  }
  const bytes = decodeBase64(src.weightDataBase64);
  return {
    format: src.format,
    generatedBy: src.generatedBy,
    convertedBy: src.convertedBy,
    userDefinedMetadata: src.userDefinedMetadata,
    modelTopology: src.modelTopology,
    weightSpecs: src.weightSpecs,
    weightData: bytes.buffer
  };
}

function loadModel() {
  if (modelPromise) { return modelPromise; }
  if (!window.tf || !window.tf.io || typeof window.tf.io.fromMemory !== 'function') {
    throw new Error('TensorFlow.js が読み込まれていません: vendor/tfjs/tf-core.min.js を確認してください');
  }
  if (!window.blazeface || typeof window.blazeface.load !== 'function') {
    throw new Error('BlazeFace が読み込まれていません: vendor/tfjs/blazeface.min.umd.js を確認してください');
  }
  modelPromise = window.blazeface.load({
    maxFaces: MAX_FACES,
    iouThreshold: IOU_THRESHOLD,
    scoreThreshold: MIN_PROBABILITY,
    modelUrl: window.tf.io.fromMemory(modelArtifacts())
  });
  return modelPromise;
}

function tileRects(W, H, n) {
  if (n <= 1) { return [{ x: 0, y: 0, w: W, h: H }]; }
  const cell = (W > H ? W : H) / n;
  const tw = Math.min(W, cell);
  const th = Math.min(H, cell);
  const step = 1 - TILE_OVERLAP;
  const nx = Math.max(1, Math.ceil((W - tw) / (tw * step)) + 1);
  const ny = Math.max(1, Math.ceil((H - th) / (th * step)) + 1);
  const out = [];
  for (let iy = 0; iy < ny; iy++) {
    for (let ix = 0; ix < nx; ix++) {
      out.push({
        x: nx === 1 ? 0 : (W - tw) * (ix / (nx - 1)),
        y: ny === 1 ? 0 : (H - th) * (iy / (ny - 1)),
        w: tw,
        h: th
      });
    }
  }
  return out;
}

// 原寸を渡しても内部で128x128へ潰されるので、tileごとに一定サイズへ縮めて転送量を抑える
function tileCanvas(source, rect) {
  const long = rect.w > rect.h ? rect.w : rect.h;
  const k = long > DETECT_LONG_EDGE ? DETECT_LONG_EDGE / long : 1;
  const cv = document.createElement('canvas');
  cv.width = Math.max(1, Math.round(rect.w * k));
  cv.height = Math.max(1, Math.round(rect.h * k));
  const ctx = cv.getContext('2d');
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = 'medium';
  ctx.drawImage(source, rect.x, rect.y, rect.w, rect.h, 0, 0, cv.width, cv.height);
  return cv;
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

function suppress(boxes) {
  const sorted = boxes.slice().sort(function (p, q) { return q.score - p.score; });
  const kept = [];
  for (let i = 0; i < sorted.length && kept.length < MAX_FACES; i++) {
    let blocked = false;
    for (let k = 0; k < kept.length; k++) {
      if (iou(sorted[i], kept[k]) > MERGE_IOU) { blocked = true; break; }
    }
    if (!blocked) { kept.push(sorted[i]); }
  }
  return kept;
}

// BlazeFaceのboxは目から口までに寄るので、額と顎を含む「顔領域」へ広げたうえで
// tile座標から画像全体の正規化座標へ戻す
function toImageBox(f, cv, rect, W, H) {
  const kx = rect.w / cv.width;
  const ky = rect.h / cv.height;
  const x0 = rect.x + f.topLeft[0] * kx;
  const y0 = rect.y + f.topLeft[1] * ky;
  const x1 = rect.x + f.bottomRight[0] * kx;
  const y1 = rect.y + f.bottomRight[1] * ky;
  const bw = x1 - x0;
  const bh = y1 - y0;
  const nx = clamp01((x0 - bw * BOX_EXPAND_SIDE) / W);
  const ny = clamp01((y0 - bh * BOX_EXPAND_TOP) / H);
  return {
    x: nx,
    y: ny,
    w: clamp01((x1 + bw * BOX_EXPAND_SIDE) / W) - nx,
    h: clamp01((y1 + bh * BOX_EXPAND_BOTTOM) / H) - ny
  };
}

async function detectFaces(source, srcW, srcH) {
  const W = srcW || (source ? (source.naturalWidth || source.width || 0) : 0);
  const H = srcH || (source ? (source.naturalHeight || source.height || 0) : 0);
  if (!W || !H) { return []; }

  const model = await loadModel();
  const found = [];
  for (let level = 0; level < PYRAMID.length; level++) {
    const rects = tileRects(W, H, PYRAMID[level]);
    for (let t = 0; t < rects.length; t++) {
      const cv = tileCanvas(source, rects[t]);
      const hits = await model.estimateFaces(cv, false, false, true);
      for (let i = 0; i < hits.length; i++) {
        const f = hits[i];
        if (!f.topLeft || !f.bottomRight) { continue; }
        const score = Array.isArray(f.probability) ? f.probability[0] : f.probability;
        if (!(score >= MIN_PROBABILITY)) { continue; }
        const box = toImageBox(f, cv, rects[t], W, H);
        if (box.w < MIN_BOX_RATIO || box.h < MIN_BOX_RATIO) { continue; }
        box.score = score;
        box.src = 'blazeface';
        found.push(box);
      }
    }
  }
  return suppress(found);
}

function remapFaces(faces, crop, srcW, srcH) {
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

Object.assign(PF, { detectFaces, remapFaces });
})(window.PF = window.PF || {});
