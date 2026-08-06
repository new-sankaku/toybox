import { buildFilterSpec, drawWithFilter } from './filterSpec.js';
import { buildGradeSpec, applyGrade } from './grade.js';
import { buildGlitchPlan, applyGlitch } from './glitch.js';
import { maskToCanvas } from '../core/segment.js';
import { ANALYSIS_WIDTH } from '../core/analysis.js';

const COOL_LOOKS = { 'cold-night': 1, 'cyanotype': 1, 'neon-night': 1, 'teal-orange': 1 };
const SAT_LOOKS = { 'neon-night': 1, 'cross-process': 1, 'teal-orange': 1 };

function clamp01(v) {
  const n = typeof v === 'number' && isFinite(v) ? v : 0;
  return n < 0 ? 0 : (n > 1 ? 1 : n);
}

function reconcile(f, g) {
  const mono = f.grayscale >= 0.6;
  if (g.duotone) {
    g.saturation = 1;
    g.duotone.amount = Math.min(1, g.duotone.amount * (mono ? 1.15 : 1));
    f.saturate = 1;
    f.sepia = 0;
    f.hueRotate = 0;
    f.grayscale = Math.min(f.grayscale, 0.85);
  } else if (mono) {
    g.saturation = 1;
    g.shadowAmount = Math.min(0.8, g.shadowAmount * 1.3);
    g.highlightAmount = Math.min(0.8, g.highlightAmount * 1.3);
  }
  if (f.sepia > 0.2 && COOL_LOOKS[g.look]) { f.sepia *= 0.25; }
  if (f.mode === 'vivid' && SAT_LOOKS[g.look]) {
    f.saturate = 1 + (f.saturate - 1) * 0.45;
    g.saturation = 1 + (g.saturation - 1) * 0.75;
  }
  if (f.mode === 'bleach' && g.look === 'bleach-bypass') {
    f.contrast = 1 + (f.contrast - 1) * 0.4;
    f.brightness = 1 + (f.brightness - 1) * 0.4;
  }
  if (f.mode === 'desaturate' && (g.look === 'cyanotype' || g.look === 'silver-halide')) {
    f.saturate = 1 + (f.saturate - 1) * 0.5;
  }
  if (Math.abs(f.hueRotate || 0) > 0.05 && g.look === 'cyanotype') { f.hueRotate = 0; }
}

function backgroundGrade(spec, darker, rng) {
  const gainScale = darker ? rng.range(0.68, 0.82) : rng.range(1.08, 1.2);
  const out = {
    look: spec.look,
    strength: Math.min(1, spec.strength * 0.9),
    lift: spec.lift.slice(),
    gamma: spec.gamma.slice(),
    gain: [spec.gain[0] * gainScale, spec.gain[1] * gainScale, spec.gain[2] * gainScale],
    contrast: 1 + (spec.contrast - 1) * 0.7,
    saturation: (1 + (spec.saturation - 1) * 0.3) * 0.42,
    shadowTint: spec.shadowTint.slice(),
    shadowAmount: Math.min(0.85, spec.shadowAmount * 1.2),
    shadowExp: spec.shadowExp,
    highlightTint: spec.highlightTint.slice(),
    highlightAmount: Math.min(0.85, spec.highlightAmount * 1.1),
    highlightExp: spec.highlightExp,
    duotone: spec.duotone
      ? { dark: spec.duotone.dark.slice(), light: spec.duotone.light.slice(), amount: spec.duotone.amount }
      : null
  };
  return out;
}

function maskSize(subject) {
  const len = subject.mask.length;
  const w = subject.w > 0 ? subject.w : ANALYSIS_WIDTH;
  const h = subject.h > 0 ? subject.h : Math.round(len / w);
  if (w < 2 || h < 2 || w * h !== len) { return null; }
  return { w: w, h: h };
}

function drawSeparated(ctx, base, W, H, filterSpec, gradeSpec, subject, rng) {
  let maskCv = subject.canvas || null;
  if (!maskCv) {
    const size = maskSize(subject);
    if (!size) { return false; }
    maskCv = maskToCanvas(subject.mask, size.w, size.h);
  }
  if (!maskCv || !maskCv.width || !maskCv.height) { return false; }
  const darker = rng.chance(0.62);
  const bgFilter = {
    grayscale: Math.min(1, filterSpec.grayscale + rng.range(0.35, 0.55)),
    sepia: filterSpec.sepia * 0.6,
    saturate: filterSpec.saturate * rng.range(0.25, 0.45),
    contrast: filterSpec.contrast * rng.range(0.88, 0.96),
    brightness: filterSpec.brightness * (darker ? rng.range(0.62, 0.80) : rng.range(1.12, 1.26)),
    hueRotate: filterSpec.hueRotate,
    blur: 0,
    mode: filterSpec.mode
  };
  drawWithFilter(ctx, base, W, H, bgFilter, W * rng.range(0.003, 0.006));
  if (gradeSpec) { applyGrade(ctx, W, H, backgroundGrade(gradeSpec, darker, rng)); }

  const fgCv = document.createElement('canvas');
  fgCv.width = W;
  fgCv.height = H;
  const fgCtx = fgCv.getContext('2d');
  drawWithFilter(fgCtx, base, W, H, filterSpec, 0);
  if (gradeSpec) { applyGrade(fgCtx, W, H, gradeSpec); }
  fgCtx.globalCompositeOperation = 'destination-in';
  fgCtx.imageSmoothingEnabled = true;
  fgCtx.drawImage(maskCv, 0, 0, W, H);
  ctx.drawImage(fgCv, 0, 0);
  return true;
}

export function processImage(opts) {
  const ctx = opts.ctx;
  const base = opts.baseCanvas;
  const W = opts.W;
  const H = opts.H;
  const rng = opts.rng;
  const genre = opts.genre;
  const intensity = clamp01(opts.intensity);
  const faces = opts.faces || [];
  const gradeMode = opts.gradeMode || 'auto';
  const glitchMode = opts.glitchMode || 'auto';
  const cutoutMode = opts.cutoutMode || 'auto';

  const filterSpec = buildFilterSpec(rng, genre, intensity);

  let gradeSpec = null;
  if (gradeMode !== 'off') {
    const gi = gradeMode === 'strong' ? Math.min(1, 0.5 + intensity * 0.6) : intensity;
    gradeSpec = buildGradeSpec(rng, genre, gi);
    reconcile(filterSpec, gradeSpec);
  }

  const subject = opts.subject;
  const wantCutout = !!subject && cutoutMode !== 'off' && (cutoutMode === 'force' || rng.chance(0.55));

  ctx.save();
  ctx.globalAlpha = 1;
  ctx.globalCompositeOperation = 'source-over';
  ctx.filter = 'none';

  let cutoutUsed = false;
  if (wantCutout) {
    cutoutUsed = drawSeparated(ctx, base, W, H, filterSpec, gradeSpec, subject, rng);
  }
  if (!cutoutUsed) {
    drawWithFilter(ctx, base, W, H, filterSpec, 0);
    if (gradeSpec) { applyGrade(ctx, W, H, gradeSpec); }
  }
  ctx.restore();

  const plan = buildGlitchPlan(rng, genre, intensity, glitchMode);
  const applied = applyGlitch(ctx, W, H, plan, rng, faces);
  const glitchOps = [];
  for (let i = 0; i < applied.length; i++) { glitchOps.push(applied[i].type); }

  return {
    filterSpec: filterSpec,
    gradeSpec: gradeSpec,
    glitchOps: glitchOps,
    cutoutUsed: cutoutUsed
  };
}
