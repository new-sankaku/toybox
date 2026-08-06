import { createRng } from '../core/rng.js';
import { buildSampleBuffer, computeLumaMap } from '../core/analysis.js';
import { detectFaces, detectFacesSkin, remapFaces } from '../core/face.js';
import { computeSaliency } from '../core/saliency.js';
import { computeCropRect, analyzeImageFit } from '../core/crop.js';
import { buildSubjectMask, maskToCanvas } from '../core/segment.js';
import { buildCostMap, findBestRect, regionStats } from '../core/placement.js';
import { resolveTextStyle } from '../core/legibility.js';
import { generateCopy } from '../text/copywriter.js';
import { processImage } from '../image/process.js';
import { pickFonts, PALETTES } from './fonts.js';
import { buildDecorSpec } from './decor.js';
import { drawSlot } from './text.js';
import { LAYOUTS } from './layouts.js';
import { buildTheme } from './theme.js';
import { SURFACE_FUNCS } from './surfaces.js';
import { OVERLAY_FUNCS } from './overlays.js';
import { rgbToCss } from '../core/color.js';

export const OUTPUT_HEIGHT = 1400;

function pickLayout(rng, genre) {
  const list = LAYOUTS[genre];
  if (!list || list.length === 0) { throw new Error('layout未定義: ' + genre); }
  return rng.pick(list);
}

function titleIsVertical(layout) {
  for (let i = 0; i < layout.slots.length; i++) {
    if (layout.slots[i].role === 'title') { return !!layout.slots[i].vertical; }
  }
  return false;
}

function drawScrim(ctx, rect, scrim, W, H) {
  const pad = W * 0.012;
  const gx = rect.x * W - pad;
  const gy = rect.y * H - pad;
  const gw = rect.w * W + pad * 2;
  const gh = rect.h * H + pad * 2;
  const grad = ctx.createLinearGradient(0, gy, 0, gy + gh);
  const cs = rgbToCss(scrim.color, scrim.alpha);
  const cs0 = rgbToCss(scrim.color, 0);
  grad.addColorStop(0, cs0);
  grad.addColorStop(0.25, cs);
  grad.addColorStop(0.75, cs);
  grad.addColorStop(1, cs0);
  ctx.save();
  ctx.fillStyle = grad;
  ctx.fillRect(gx, gy, gw, gh);
  ctx.restore();
}

function drawDebugOverlay(ctx, W, H, buf, costInfo, faces, placements) {
  ctx.save();
  ctx.globalAlpha = 0.42;
  const tmp = document.createElement('canvas');
  tmp.width = buf.w; tmp.height = buf.h;
  const tctx = tmp.getContext('2d');
  const img = tctx.createImageData(buf.w, buf.h);
  for (let i = 0; i < buf.w * buf.h; i++) {
    const v = Math.min(1, costInfo.cost[i]);
    const p = i * 4;
    img.data[p] = Math.round(255 * v);
    img.data[p + 1] = Math.round(60 * (1 - v));
    img.data[p + 2] = Math.round(255 * (1 - v));
    img.data[p + 3] = 170;
  }
  tctx.putImageData(img, 0, 0);
  ctx.drawImage(tmp, 0, 0, W, H);
  ctx.restore();

  ctx.save();
  ctx.lineWidth = Math.max(2, W * 0.004);
  ctx.strokeStyle = '#00ff88';
  for (let i = 0; i < faces.length; i++) {
    const f = faces[i];
    ctx.strokeRect(f.x * W, f.y * H, f.w * W, f.h * H);
  }
  ctx.strokeStyle = '#ffee00';
  for (let i = 0; i < placements.length; i++) {
    const r = placements[i].rect;
    ctx.strokeRect(r.x * W, r.y * H, r.w * W, r.h * H);
  }
  ctx.restore();
}

export async function generatePoster(opts) {
  const t0 = performance.now();
  const rng = createRng(opts.seed);
  const genre = opts.genre;
  const src = opts.bitmap;
  const srcW = src.width;
  const srcH = src.height;

  const fullBuf = buildSampleBuffer(src, srcW, srcH);
  const fullLuma = computeLumaMap(fullBuf);
  const fullSaliency = computeSaliency(fullBuf, fullLuma);
  const preFaces = opts.avoidFace ? await detectFaces(src, fullBuf) : [];

  const layout = pickLayout(rng, genre);
  const aspect = layout.aspect;
  const H = OUTPUT_HEIGHT;
  const W = Math.round(H * aspect);
  const fit = analyzeImageFit(srcW, srcH, aspect);
  const crop = computeCropRect(srcW, srcH, aspect, preFaces, fullSaliency, rng);

  const baseCv = document.createElement('canvas');
  baseCv.width = W;
  baseCv.height = H;
  const baseCtx = baseCv.getContext('2d');
  baseCtx.imageSmoothingEnabled = true;
  baseCtx.imageSmoothingQuality = 'high';
  baseCtx.drawImage(src, crop.x, crop.y, crop.w, crop.h, 0, 0, W, H);

  const buf = buildSampleBuffer(baseCv, W, H);
  const luma = computeLumaMap(buf);
  const saliency = computeSaliency(buf, luma);

  let faces = [];
  if (opts.avoidFace) {
    faces = remapFaces(preFaces, crop, srcW, srcH);
    if (faces.length === 0) { faces = detectFacesSkin(buf); }
  }
  const costInfo = buildCostMap(buf, luma, faces, opts.avoidFace, saliency);

  const out = opts.canvas;
  out.width = W;
  out.height = H;
  const ctx = out.getContext('2d');
  ctx.clearRect(0, 0, W, H);

  let subject = null;
  if (opts.cutoutMode !== 'off') {
    const tolerance = opts.cutoutMode === 'force' ? 62 : 40;
    const built = buildSubjectMask(buf, tolerance);
    if (built) {
      subject = {
        mask: built.mask,
        ratio: built.ratio,
        w: buf.w,
        h: buf.h,
        canvas: maskToCanvas(built.mask, buf.w, buf.h)
      };
    }
  }

  const imageResult = processImage({
    ctx: ctx,
    baseCanvas: baseCv,
    W: W,
    H: H,
    rng: rng,
    genre: genre,
    intensity: opts.intensity,
    faces: faces,
    subject: subject,
    cutoutMode: opts.cutoutMode,
    gradeMode: opts.gradeMode,
    glitchMode: opts.glitchMode
  });

  const theme = buildTheme(rng, genre);
  const surfaceCount = Math.max(1, Math.round(layout.surfaces.length * (0.6 + rng.next() * 0.5)));
  const chosenSurfaces = rng.sample(layout.surfaces, surfaceCount);
  for (let i = 0; i < layout.slots.length; i++) {
    const need = layout.slots[i].onSurface;
    if (need && chosenSurfaces.indexOf(need) < 0 && layout.surfaces.indexOf(need) >= 0) {
      chosenSurfaces.push(need);
    }
  }
  for (let i = 0; i < chosenSurfaces.length; i++) {
    const fn = SURFACE_FUNCS[chosenSurfaces[i]];
    if (fn) { fn(ctx, W, H, rng, theme); }
  }

  const copy = generateCopy(rng, genre, opts.density, { verticalTitle: titleIsVertical(layout) });
  const fonts = pickFonts(rng, genre);
  const palette = PALETTES[genre];

  const occupied = [];
  const placements = [];
  for (let i = 0; i < layout.slots.length; i++) {
    const slot = layout.slots[i];
    const text = copy[slot.role];
    if (!text) { continue; }
    let rect;
    if (slot.onSurface) {
      rect = slot.candidates[0];
    } else {
      rect = findBestRect(costInfo, buf.w, buf.h, slot.candidates, occupied, 0.045);
    }
    occupied.push(rect);
    placements.push({ slot: slot, rect: rect, text: text });
  }

  const postBuf = buildSampleBuffer(out, W, H);
  for (let i = 0; i < placements.length; i++) {
    const p = placements[i];
    const slot = p.slot;
    const stats = regionStats(postBuf, p.rect);
    const style = resolveTextStyle(stats, palette, !!slot.big, rng);
    if (style.scrim) { drawScrim(ctx, p.rect, style.scrim, W, H); }

    const decor = buildDecorSpec(rng, genre, slot, style, stats, opts.intensity);
    const fontCss = slot.latin ? fonts.latin.css : (slot.big ? fonts.title.css : fonts.sub.css);
    const weight = slot.big ? (rng.chance(0.5) ? '700' : '600') : (rng.chance(0.3) ? '600' : '400');
    const startSize = H * slot.size * (slot.big ? (0.92 + rng.next() * 0.22) : (0.94 + rng.next() * 0.16));

    ctx.save();
    drawSlot(ctx, {
      text: p.text,
      rect: p.rect,
      slot: slot,
      style: style,
      decor: decor,
      fontCss: fontCss,
      weight: weight,
      startSize: startSize,
      W: W,
      H: H
    });
    ctx.restore();
  }

  const overlayCount = Math.max(1, Math.round(layout.overlays.length * (0.5 + opts.intensity * 0.8)));
  const chosenOverlays = rng.sample(layout.overlays, overlayCount);
  const applied = [];
  for (let i = 0; i < chosenOverlays.length; i++) {
    const name = chosenOverlays[i];
    if (imageResult.filterSpec && imageResult.filterSpec.grayscale > 0.7 && (name === 'bloom' || name === 'neonGlow')) { continue; }
    const fn = OVERLAY_FUNCS[name];
    if (fn) { fn(ctx, W, H, rng, theme); applied.push(name); }
  }

  if (opts.debug) {
    drawDebugOverlay(ctx, W, H, buf, costInfo, faces, placements);
  }

  return {
    ms: Math.round(performance.now() - t0),
    seed: opts.seed,
    genre: genre,
    layoutId: layout.id,
    aspect: aspect,
    fit: fit,
    crop: crop,
    faces: faces,
    filterMode: imageResult.filterSpec ? imageResult.filterSpec.mode : 'none',
    gradeLook: imageResult.gradeSpec ? imageResult.gradeSpec.look : 'off',
    glitchOps: imageResult.glitchOps || [],
    cutoutUsed: imageResult.cutoutUsed,
    cutoutRatio: subject ? subject.ratio : 0,
    surfaces: chosenSurfaces,
    overlays: applied,
    fonts: fonts,
    copy: copy
  };
}
