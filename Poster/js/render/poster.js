(function (PF) {
'use strict';
const { createRng } = PF;
const { buildSampleBuffer, computeLumaMap } = PF;
const { detectFaces, remapFaces } = PF;
const { computeSaliency } = PF;
const { computeCropRect, analyzeImageFit } = PF;
const { buildSubjectMask, maskToCanvas } = PF;
const { buildCostMap, findBestRect, regionStats } = PF;
const { resolveTextStyle } = PF;
const { extractPalette } = PF;
const { buildColorPlan } = PF;
const { generateCopy } = PF;
const { processImage } = PF;
const { pickFonts, PALETTES } = PF;
const { buildDecorSpec } = PF;
const { drawSlot } = PF;
const { buildSkeleton, composeLayout } = PF;
const { setActiveAnchors, beginAnchorTrace, endAnchorTrace } = PF;
const { buildTheme } = PF;
const { SURFACE_FUNCS } = PF;
const { OVERLAY_FUNCS } = PF;
const { rgbToCss, clamp255 } = PF;

const OUTPUT_HEIGHT = 1400;

function rgbToHex(rgb) {
  const r = Math.round(clamp255(rgb[0]));
  const g = Math.round(clamp255(rgb[1]));
  const b = Math.round(clamp255(rgb[2]));
  return '#' + ((1 << 24) | (r << 16) | (g << 8) | b).toString(16).slice(1);
}

function drawScrim(ctx, rect, scrim, W, H) {
  const pad = W * 0.012;
  const gx = rect.x * W - pad;
  const gy = rect.y * H - pad;
  const gw = rect.w * W + pad * 2;
  const gh = rect.h * H + pad * 2;
  const cs = rgbToCss(scrim.color, scrim.alpha);
  ctx.save();
  if (scrim.solid) {
    // 端をfadeさせると文字の上下が下地の薄い所に載り、濃く敷いた意味が消える
    ctx.fillStyle = cs;
  } else {
    const grad = ctx.createLinearGradient(0, gy, 0, gy + gh);
    const cs0 = rgbToCss(scrim.color, 0);
    grad.addColorStop(0, cs0);
    grad.addColorStop(0.25, cs);
    grad.addColorStop(0.75, cs);
    grad.addColorStop(1, cs0);
    ctx.fillStyle = grad;
  }
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

async function generatePoster(opts) {
  const t0 = performance.now();
  if (typeof opts.decorIntensity !== 'number' || !isFinite(opts.decorIntensity)) {
    throw new Error('generatePoster: opts.decorIntensity が数値ではありません: ' + opts.decorIntensity);
  }
  const decorIntensity = Math.max(0, Math.min(1, opts.decorIntensity));
  const rng = createRng(opts.seed);
  const genre = opts.genre;
  const src = opts.bitmap;
  const srcW = src.width;
  const srcH = src.height;

  const fullBuf = buildSampleBuffer(src, srcW, srcH);
  const fullLuma = computeLumaMap(fullBuf);
  const fullSaliency = computeSaliency(fullBuf, fullLuma);
  const preFaces = opts.avoidFace ? await detectFaces(src, srcW, srcH) : [];

  const plan = buildSkeleton(rng, genre);
  const aspect = plan.aspect;
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

  const faces = opts.avoidFace ? remapFaces(preFaces, crop, srcW, srcH) : [];
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

  const palette = extractPalette(buf, { excludeSkin: true });
  const colorPlan = buildColorPlan(rng, genre, palette, decorIntensity);

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
    glitchMode: opts.glitchMode,
    colorPlan: colorPlan
  });

  const copy = generateCopy(rng, genre, opts.density, { verticalTitle: plan.titleVertical });
  const layout = composeLayout(rng, plan, copy);
  setActiveAnchors(layout.anchors);

  const theme = buildTheme(rng, genre, colorPlan);
  const chosenSurfaces = [];
  for (let i = 0; i < layout.surfaces.length; i++) {
    if (chosenSurfaces.indexOf(layout.surfaces[i]) < 0) { chosenSurfaces.push(layout.surfaces[i]); }
  }
  beginAnchorTrace();
  for (let i = 0; i < chosenSurfaces.length; i++) {
    const fn = SURFACE_FUNCS[chosenSurfaces[i]];
    if (fn) { fn(ctx, W, H, rng, theme); }
  }
  const surfaceRects = endAnchorTrace();

  const fonts = pickFonts(rng, genre);
  const textPalette = colorPlan.textPalette && colorPlan.textPalette.length
    ? colorPlan.textPalette.map((rgb) => rgbToHex(rgb))
    : PALETTES[genre];

  // surface は文字より先に描かれるが占有情報が無く、自由配置の文字が上に乗ってしまう。
  // overlap は soft penalty なので、置き場が無ければ従来通り重なる。
  const occupied = surfaceRects.slice();
  const placements = [];
  for (let i = 0; i < layout.slots.length; i++) {
    const slot = layout.slots[i];
    const text = copy[slot.role];
    if (!text) { continue; }
    let rect;
    if (slot.fixed) {
      rect = slot.rect;
    } else {
      rect = findBestRect(costInfo, buf.w, buf.h, slot.candidates, occupied, slot.slide);
    }
    occupied.push(rect);
    placements.push({ slot: slot, rect: rect, text: text });
  }

  const postBuf = buildSampleBuffer(out, W, H);
  for (let i = 0; i < placements.length; i++) {
    const p = placements[i];
    const slot = p.slot;
    const stats = regionStats(postBuf, p.rect);
    const style = resolveTextStyle(stats, textPalette, !!slot.big, rng, {
      inkOnly: !!slot.inkOnly,
      outline: !!slot.outline,
      chromaBias: colorPlan.textChromaBias,
      minChroma: colorPlan.textMinChroma,
      lBand: colorPlan.textLBand,
      forceCover: !!slot.big && !slot.outline && rng.chance(colorPlan.titleCover),
      coverColors: colorPlan.coverColors
    });
    if (style.scrim && !slot.outline) { drawScrim(ctx, p.rect, style.scrim, W, H); }

    const decor = buildDecorSpec(rng, genre, slot, style, stats, decorIntensity, colorPlan);
    const fontCss = slot.latin ? fonts.latin.css : (slot.big ? fonts.title.css : fonts.sub.css);
    const weight = slot.big ? (rng.chance(0.5) ? '700' : '600') : (rng.chance(0.3) ? '600' : '400');
    const startSize = H * slot.size * (slot.big ? (0.92 + rng.next() * 0.22) : (0.94 + rng.next() * 0.16));

    ctx.save();
    const drawn = drawSlot(ctx, {
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
    p.size = drawn ? drawn.size : 0;
    p.truncated = !!(drawn && drawn.truncated);
  }

  const overlayCount = Math.max(1, Math.round(layout.overlays.length * (0.34 + opts.intensity * 0.66)));
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
  setActiveAnchors(null);

  const placedRects = [];
  for (let i = 0; i < placements.length; i++) {
    placedRects.push({ role: placements[i].slot.role, rect: placements[i].rect, size: placements[i].size, truncated: placements[i].truncated });
  }

  return {
    ms: Math.round(performance.now() - t0),
    seed: opts.seed,
    genre: genre,
    layoutId: layout.id,
    heroMode: layout.heroMode,
    bands: layout.bands,
    placements: placedRects,
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
    colorScheme: colorPlan.scheme,
    colorPolarity: colorPlan.polarity,
    tintStrategy: colorPlan.tintStrategy,
    colorfulness: palette.colorfulness,
    fonts: fonts,
    copy: copy
  };
}

Object.assign(PF, { OUTPUT_HEIGHT, generatePoster });
})(window.PF = window.PF || {});
