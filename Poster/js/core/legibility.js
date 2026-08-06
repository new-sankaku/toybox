import { hexToRgb, contrastRatio, blendRgb } from './color.js';

const MIN_CONTRAST_LARGE = 3.4;
const MIN_CONTRAST_SMALL = 4.5;
const NOISY_STD = 0.17;
const SCRIM_ALPHAS = [0.35, 0.5, 0.65, 0.8];
const DARK_INK = [16, 14, 12];
const LIGHT_INK = [255, 255, 255];

function passingColors(palette, background, need) {
  const out = [];
  for (let i = 0; i < palette.length; i++) {
    const rgb = hexToRgb(palette[i]);
    const ratio = contrastRatio(rgb, background);
    if (ratio >= need) { out.push({ rgb: rgb, ratio: ratio }); }
  }
  return out;
}

function chooseColor(candidates, rng) {
  let bestRatio = 0;
  for (let i = 0; i < candidates.length; i++) {
    if (candidates[i].ratio > bestRatio) { bestRatio = candidates[i].ratio; }
  }
  const items = [];
  for (let i = 0; i < candidates.length; i++) {
    const share = candidates[i].ratio / bestRatio;
    items.push({ v: candidates[i], w: share * share * share });
  }
  return rng.weighted(items);
}

export function resolveTextStyle(stats, palette, isLarge, rng) {
  const need = isLarge ? MIN_CONTRAST_LARGE : MIN_CONTRAST_SMALL;
  const style = { color: null, scrim: null, stroke: null, shadow: null };
  const noisy = stats.std > NOISY_STD;

  const direct = passingColors(palette, stats.rgb, need);
  if (direct.length > 0 && !noisy) {
    const chosen = chooseColor(direct, rng);
    style.color = chosen.rgb;
    if (chosen.ratio < need * 1.5) {
      style.shadow = { color: stats.luma > 0.5 ? DARK_INK : LIGHT_INK, alpha: 0.35, blur: 0.5 };
    }
    return style;
  }

  const scrimColor = stats.luma > 0.5 ? [12, 10, 8] : [244, 240, 232];
  const scrimNeed = noisy ? need * 1.15 : need;
  for (let a = 0; a < SCRIM_ALPHAS.length; a++) {
    const alpha = SCRIM_ALPHAS[a];
    const blended = blendRgb(stats.rgb, scrimColor, alpha);
    const candidates = passingColors(palette, blended, scrimNeed);
    if (candidates.length > 0) {
      style.scrim = { color: scrimColor, alpha: alpha };
      style.color = chooseColor(candidates, rng).rgb;
      if (noisy) {
        style.shadow = { color: scrimColor, alpha: 0.4, blur: 0.6 };
      }
      return style;
    }
  }

  const useLight = contrastRatio(LIGHT_INK, stats.rgb) >= contrastRatio(DARK_INK, stats.rgb);
  style.color = useLight ? LIGHT_INK : DARK_INK;
  style.stroke = { color: useLight ? DARK_INK : LIGHT_INK, width: 0.055, alpha: 0.85 };
  style.shadow = { color: useLight ? [0, 0, 0] : [255, 255, 255], alpha: 0.5, blur: 0.8 };
  return style;
}
