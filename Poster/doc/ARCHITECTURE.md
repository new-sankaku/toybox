# POSTER FORGE 構成と module 間契約

Server不要のstatic site。ES module で機能単位に分割する。
`index.html` → `js/main.js`（UI結線）→ `js/render/poster.js`（生成本体）→ 各module。

## 設計の芯

生成の多様性は「語彙を線形に増やす」のではなく **独立軸の積** で作る。

| 層 | 軸 |
| --- | --- |
| 文言 | 語基合成（前部要素 × 後部要素） × 構文skeleton × 表記体裁 × 数値slot × 人名合成（姓 × 名） |
| 画像 | crop方式 × filter mode × color grade look × 破壊効果の組合せ × 被写体分離の有無 |
| 意匠 | layout × surface組合せ × overlay組合せ × font組合せ × 文字装飾spec |

## Genre

`'cinema' | 'gravure' | 'novel' | 'asmr' | 'game' | 'adult'`

すべて **文字表現のみ** の差異。画像側をgenreで露骨に変える処理は持たせない。

## 座標と型の約束

- 正規化矩形 `Rect = {x, y, w, h}`（対象画像に対する 0..1）
- 色は `[r, g, b]`（0..255 の数値配列）または `'#rrggbb'`
- sample buffer `Buf = {w, h, data: Uint8ClampedArray}`（RGBA）

## Module一覧と公開API

### js/core/rng.js（実装済）
`createRng(seed)` → `{seed, next, range(a,b), int(a,b), chance(p), pick(arr), weighted([{v,w}]), shuffle(arr), sample(arr,n), sign()}`
`randomSeed()`

### js/core/color.js（実装済）
`clamp255, srgbToLinear, relativeLuminance, contrastRatio(a,b), hexToRgb, rgbToCss(rgb,alpha), blendRgb(bg,fg,alpha), shade(rgb,amount), luma01(rgb), rgbToHsl, hslToRgb`

### js/core/analysis.js（実装済）
`ANALYSIS_WIDTH, buildSampleBuffer(source,srcW,srcH)→Buf, computeLumaMap(buf)→Float32Array, computeEdgeMap(luma,w,h)→Float32Array, buildIntegral(src,w,h), integralSum(integral,w,x,y,rw,rh)`

### js/core/face.js
- `detectFacesSkin(buf) → Rect[]`（`src` fieldに検出手段名）
- `async detectFaces(source, buf) → Rect[]`
- `remapFaces(faces, crop, srcW, srcH) → Rect[]`

### js/core/saliency.js
- `computeSaliency(buf, luma) → {map: Float32Array, w, h}`（0..1 正規化）

### js/core/crop.js
- `analyzeImageFit(srcW, srcH, targetAspect) → {srcAspect, ratio, kind}`
  `kind` は `'match' | 'wide' | 'tall' | 'panorama' | 'tower'`
- `computeCropRect(srcW, srcH, targetAspect, faces, saliency, rng) → {x, y, w, h, mode, zoom}`
  （source pixel単位。`mode` はlog用の文字列）

### js/core/segment.js
- `buildSubjectMask(buf, tolerance) → {mask: Float32Array, ratio} | null`
- `maskToCanvas(mask, w, h) → HTMLCanvasElement`

### js/core/placement.js
- `buildCostMap(buf, luma, faces, avoidFace, saliency) → {cost, integral, edge}`
- `rectCost(costInfo, w, h, rect) → number`
- `findBestRect(costInfo, w, h, candidates, occupied, slide) → Rect`
- `overlapRatio(a, b) → number`
- `regionStats(buf, rect) → {rgb, luma, std}`

### js/core/legibility.js
- `resolveTextStyle(stats, palette, isLarge, rng) → Style`
  `Style = {color:[r,g,b], scrim:{color,alpha}|null, stroke:{color,width,alpha}|null, shadow:{color,alpha,blur}|null}`

### js/text/lexicon.js
純data。`COMMON` と `LEXICON[genre]`。
形態素は `{ja, en}`（enは英字併記軸で使う大文字表記）。

### js/text/morphology.js
- `composeNoun(rng, genre, opts) → {ja, en, mode, parts}`
- `personName(rng, genre) → {ja, en}`
- `numeric(rng, kind) → string`

### js/text/orthography.js
- `styleTitle(rng, core, opts) → {text, latin, axes}`
  `opts = {vertical, genre, allowLatin, allowExclaim}`

### js/text/patterns.js
genre別のskeleton配列。`{slot}` 記法。

### js/text/copywriter.js
- `generateCopy(rng, genre, density, opts) → Copy`
  `opts = {verticalTitle: boolean}`
  `Copy` の key は **role名** に一致させる：
  `title, catch, name, tag, credit, release, badge, code, extra`
  値が空文字/undefinedのroleはlayout側でskipされる。
  `Copy.__axes` に選択した軸名をlog用に格納する。

### js/image/filterSpec.js
- `supportsCanvasFilter() → boolean`
- `buildFilterSpec(rng, genre, intensity) → spec`
- `filterSpecToCss(spec, extraBlur) → string`
- `applyFilterFallback(ctx, w, h, spec)`
- `drawWithFilter(dstCtx, src, w, h, spec, extraBlur)`

### js/image/grade.js
- `buildGradeSpec(rng, genre, intensity) → spec`（`spec.look` にlook名）
- `applyGrade(ctx, w, h, spec)`（ImageData 1passで完結させる）

### js/image/glitch.js
- `buildGlitchPlan(rng, genre, intensity, mode) → op[]`（`mode` は `'auto'|'strong'|'off'`）
- `applyGlitch(ctx, w, h, plan, rng, faces)`（`faces` は正規化Rect[]。重なる帯は使わない）

### js/image/process.js
- `processImage(opts) → {filterSpec, gradeSpec, glitchOps, cutoutUsed}`
  `opts = {ctx, baseCanvas, W, H, rng, genre, intensity, faces, subject, cutoutMode, gradeMode, glitchMode}`

### js/render/fonts.js
- `FONT_JP`, `FONT_LATIN`（`{name, css, kind}`）
- `pickFonts(rng, genre) → {title, sub, latin}`
- `PALETTES[genre] → string[]`

### js/render/decor.js
- `buildDecorSpec(rng, genre, slot, style, stats, intensity) → DecorSpec`
- `paintDecorated(ctx, emitter, box, spec, size)`
  `emitter(ctx, mode)` は `mode` が `'fill'|'stroke'` で全glyphを描くcallback。

### js/render/text.js
- `drawSlot(ctx, args)` / `args = {text, rect, slot, style, decor, fontCss, weight, startSize, W, H}`

### js/render/layouts.js
`LAYOUTS[genre] → Layout[]`
```
Layout = {id, aspect, slots: Slot[], surfaces: string[], overlays: string[]}
Slot = {role, size, tracking, maxLines, align, latin?, vertical?, big?, onSurface?, decor?, candidates: Rect[]}
```
`align` は `'left'|'center'|'right'|'top'`。`decor` は `'title'|'accent'|'plain'`。

### js/render/theme.js
- `buildTheme(rng, genre) → {obiColors, ribbonColors, plateColors, accentColors, inkColors}`

### js/render/surfaces.js / js/render/overlays.js
- `SURFACE_FUNCS[name] = (ctx, W, H, rng, theme) => void`
- `OVERLAY_FUNCS[name] = (ctx, W, H, rng, theme) => void`

## 描画順序（poster.js）

1. 顔検出・saliency（原画）
2. layout選択 → crop決定 → base canvas
3. crop後の再解析（luma / saliency / face / costmap）
4. 画像処理（filter → grade → glitch、被写体分離があれば前景背景で別処理）
5. surface（文字の下地）
6. 文言生成・font決定
7. slot配置探索
8. 合成後のpixelから文字色決定 → 装飾spec → 描画
9. overlay
10. debug表示

## 制約

- 固定幅CSSを使わない
- Comment は TODO 以外書かない
- fallback で誤魔化さず、条件を満たさないときは効果を使わない
- 顔領域は文字も破壊効果も避ける
