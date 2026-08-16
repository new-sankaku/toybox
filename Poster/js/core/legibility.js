(function (PF) {
'use strict';
const { hexToRgb, contrastRatio, blendRgb } = PF;
const { srgbToOklch } = PF;

const MIN_CONTRAST_LARGE = 3.4;
const MIN_CONTRAST_SMALL = 4.5;
const NOISY_STD = 0.17;
const SPREAD_WEIGHT = 0.7;
const SCRIM_ALPHAS = [0.35, 0.5, 0.65, 0.8];
// 下地を積極的に敷く場合は、薄掛けだと写真が透けて彩度の高い色が通らないため濃い側から試す
const COVER_ALPHAS = [0.72, 0.84, 0.93, 1];
const DARK_INK = [16, 14, 12];
const LIGHT_INK = [255, 255, 255];
const CONTRAST_EXP = 1;
const CHROMA_BIAS_MIN = -0.95;
const CHROMA_REF = 0.16;
// 縁取り体裁での塗り選び。縁が分離を作るので背景とのcontrastは
// 「完全に同化しない」ことだけを見る。need基準にすると中間輝度の彩度色が全部落ちる。
const OUTLINE_BG_MIN = 1.25;

function backgroundRange(background, std) {
  const excursion = Math.min(0.5, std) * SPREAD_WEIGHT;
  return [
    background,
    blendRgb(background, LIGHT_INK, excursion),
    blendRgb(background, DARK_INK, excursion)
  ];
}

function passingColors(palette, backgrounds, need) {
  const out = [];
  for (let i = 0; i < palette.length; i++) {
    const rgb = hexToRgb(palette[i]);
    let ratio = Infinity;
    for (let b = 0; b < backgrounds.length; b++) {
      const r = contrastRatio(rgb, backgrounds[b]);
      if (r < ratio) { ratio = r; }
    }
    if (ratio >= need) { out.push({ rgb: rgb, ratio: ratio }); }
  }
  return out;
}

// RGBの (max-min)/max は暗色で跳ねる（#0c0a0a が 0.167）ため、知覚的な OKLCh chroma を
// 標準的なaccentの濃さで正規化して使う
function chromaUnit(rgb) {
  return srgbToOklch(rgb)[1] / CHROMA_REF;
}

function mostDistant(palette, targets) {
  let best = null;
  for (let i = 0; i < palette.length; i++) {
    const rgb = hexToRgb(palette[i]);
    let ratio = Infinity;
    for (let t = 0; t < targets.length; t++) {
      const r = contrastRatio(rgb, targets[t]);
      if (r < ratio) { ratio = r; }
    }
    if (best === null || ratio > best.ratio) { best = { rgb: rgb, ratio: ratio }; }
  }
  if (best === null) {
    throw new Error('mostDistant: paletteが空です');
  }
  return best;
}

// 重みを下げるだけでは無彩色が一定確率で引かれ続ける。
// 原色が前提のgenreでは、下限彩度に満たない候補を母集団から外す。
function preferVivid(candidates, minChroma, lBand) {
  if (!(minChroma > 0) && !lBand) { return candidates; }
  const out = [];
  for (let i = 0; i < candidates.length; i++) {
    const lch = srgbToOklch(candidates[i].rgb);
    if (minChroma > 0 && lch[1] < minChroma) { continue; }
    if (lBand && (lch[0] < lBand[0] || lch[0] > lBand[1])) { continue; }
    out.push(candidates[i]);
  }
  if (out.length > 0) { return out; }
  // 明度帯まで課すと候補が尽きることがある。彩度だけに緩めてから諦める
  if (lBand && minChroma > 0) { return preferVivid(candidates, minChroma, null); }
  return candidates;
}

function chooseColor(candidates, rng, chromaBias, ignoreContrast) {
  let bestRatio = 0;
  for (let i = 0; i < candidates.length; i++) {
    if (candidates[i].ratio > bestRatio) { bestRatio = candidates[i].ratio; }
  }
  const bias = Math.max(CHROMA_BIAS_MIN, chromaBias);
  const items = [];
  for (let i = 0; i < candidates.length; i++) {
    // passingColors が既に下限を満たす候補だけを返しているので、
    // ここで contrast を再度強く重ねると最大値の純白・純黒しか残らない。
    // 縁や下地で可読性を別途担保している場合は、contrast差を重みに使わない。
    const share = ignoreContrast ? 1 : candidates[i].ratio / bestRatio;
    const w = Math.pow(share, CONTRAST_EXP) * (1 + bias * chromaUnit(candidates[i].rgb));
    items.push({ v: candidates[i], w: w });
  }
  return rng.weighted(items);
}

// 縁取りで読ませる体裁では、塗りの可読性は縁が担保する。
// 塗りまで背景とのcontrastで選ぶと、明るい写真の上では純黒しか残らない。
// 縁を「背景から最も遠い色」に固定し、塗りは縁とのcontrastで選ぶことで彩度の高い色が使える。
function outlinedStyle(stats, palette, need, rng, chromaBias, minChroma, bgMin, lBand) {
  const style = { color: null, scrim: null, stroke: null, shadow: null };
  const guard = mostDistant(palette, [stats.rgb]);
  const fills = [];
  for (let i = 0; i < palette.length; i++) {
    const rgb = hexToRgb(palette[i]);
    const vsGuard = contrastRatio(rgb, guard.rgb);
    if (vsGuard < need) { continue; }
    if (contrastRatio(rgb, stats.rgb) < bgMin) { continue; }
    fills.push({ rgb: rgb, ratio: vsGuard });
  }
  const pool = preferVivid(fills, minChroma, lBand);
  style.color = pool.length > 0
    ? chooseColor(pool, rng, chromaBias, true).rgb
    : mostDistant(palette, [guard.rgb]).rgb;
  style.stroke = { color: guard.rgb, width: 0.055, alpha: 0.9 };
  style.shadow = { color: guard.rgb, alpha: 0.5, blur: 0.8 };
  return style;
}

function resolveTextStyle(stats, palette, isLarge, rng, opts) {
  const need = isLarge ? MIN_CONTRAST_LARGE : MIN_CONTRAST_SMALL;
  const style = { color: null, scrim: null, stroke: null, shadow: null };
  const noisy = stats.std > NOISY_STD;
  const inkOnly = !!(opts && opts.inkOnly);
  const outlined = inkOnly || !!(opts && opts.outline);
  const cover = !!(opts && opts.forceCover);
  const chromaBias = opts ? opts.chromaBias : undefined;
  if (typeof chromaBias !== 'number' || !isFinite(chromaBias)) {
    throw new Error('resolveTextStyle: opts.chromaBias が数値ではありません: ' + chromaBias);
  }
  // 下限彩度は縁や下地で分離を作れる大きな文字にだけ課す
  const minChroma = isLarge && opts ? opts.minChroma : 0;
  // 大きな文字は縁が分離を作るので背景とのcontrastを緩められるが、
  // 小さい文字は線幅が足りないため背景側の下限を残す
  const bgMin = isLarge ? OUTLINE_BG_MIN : need * 0.8;
  // pastel前提のgenreは明度帯も指定される。小さい文字は可読性優先で課さない
  const lBand = isLarge && opts ? (opts.lBand || null) : null;

  // 縁に可読性を委ねられるのは、線幅が字面に対して十分取れる大きな文字だけ。
  // 小さい文字まで同じ扱いにすると、背景と輝度の近い色が選ばれて潰れる。
  if (outlined && isLarge) { return outlinedStyle(stats, palette, need, rng, chromaBias, minChroma, bgMin, lBand); }

  const spread = backgroundRange(stats.rgb, stats.std);
  const direct = passingColors(palette, spread, need);
  if (direct.length > 0 && !noisy && !cover) {
    const chosen = chooseColor(direct, rng, chromaBias);
    style.color = chosen.rgb;
    if (chosen.ratio < need * 1.5) {
      style.shadow = { color: stats.luma > 0.5 ? DARK_INK : LIGHT_INK, alpha: 0.35, blur: 0.5 };
    }
    return style;
  }

  // 下地を敷かない体裁のgenreは、ここから先の scrim 経路を使わず縁取りで処理する
  if (inkOnly) { return outlinedStyle(stats, palette, need, rng, chromaBias, minChroma, bgMin, lBand); }

  // 明るい写真の上で直接読める色は暗色だけになり、原色・ネオンが候補から消える。
  // 先に下地を敷いてから色を決めると、明度の高い彩度色が選べるようになる。
  const covers = opts && opts.coverColors ? opts.coverColors : null;
  const scrimColor = stats.luma > 0.5
    ? (covers ? covers.dark : [12, 10, 8])
    : (covers ? covers.light : [244, 240, 232]);
  const alphas = cover ? COVER_ALPHAS : SCRIM_ALPHAS;
  const scrimNeed = noisy ? need * 1.15 : need;
  for (let a = 0; a < alphas.length; a++) {
    const alpha = alphas[a];
    const blended = spread.map((bg) => blendRgb(bg, scrimColor, alpha));
    const candidates = passingColors(palette, blended, scrimNeed);
    if (candidates.length > 0) {
      style.scrim = { color: scrimColor, alpha: alpha, solid: cover };
      style.color = chooseColor(preferVivid(candidates, cover ? minChroma : 0, cover ? lBand : null), rng, chromaBias, cover).rgb;
      if (noisy) {
        style.shadow = { color: scrimColor, alpha: 0.4, blur: 0.6 };
      }
      return style;
    }
  }

  return outlinedStyle(stats, palette, need, rng, chromaBias, minChroma, bgMin, lBand);
}

Object.assign(PF, { resolveTextStyle });
})(window.PF = window.PF || {});
