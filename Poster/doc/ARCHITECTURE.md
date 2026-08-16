# POSTER FORGE 構成と module 間契約

Server不要のstatic site。build工程を持たず `file://` で動く。
機能単位に分割したfileを `index.html` が依存順の script tag で読み、
各fileは IIFE で包んで公開関数だけを `window.PF` に載せる。
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
- `async detectFaces(source, srcW, srcH) → Rect[]`（`src` fieldに検出手段名）
- `remapFaces(faces, crop, srcW, srcH) → Rect[]`

検出は TensorFlow.js 上の BlazeFace（short range）。model は `vendor/model/blazeface.artifacts.js` に
base64 で封入してあり、`tf.io.fromMemory` で読むため `fetch` が要らず `file://` のままでも動く。

BlazeFace は入力を 128x128 へ潰すので、画面に占める顔が小さいほどscoreが落ちる
（実測: 顔が幅の約5%の画像で0.23、顔が1/4を占めるcropで0.93）。
このため全体像と 1/2 tile の2段で走査し、tile座標を画像全体の正規化座標へ戻してからIoUで統合する。
box は目から口までに寄るので、額と顎を含むよう上下左右へ広げてから返す。

### 文字色の決定順序

写真の上で直接読める色を探すと、明るい画像では暗色しか通らず、原色・ネオンが候補から消える。
そのため「先に分離手段を決め、そのうえで色を選ぶ」順序を取る。

1. `slot.outline` / `slot.inkOnly` かつ大きな文字 … `outlinedStyle`。
   縁を「背景から最も遠い色」に固定し、塗りは**縁との**contrastで選ぶ。
   背景とのcontrastは同化回避の下限（`OUTLINE_BG_MIN`）だけ課す。
   小さい文字は線幅が足りず縁で分離できないので、この緩和を適用しない。
2. `titleCover` に当たった大きな文字 … 下地を濃く敷いてから色を選ぶ（`COVER_ALPHAS`）。
   下地色は accent の色相へ寄せた `coverColors`。端をfadeさせない実塗り。
3. それ以外 … 従来通り 直接 → scrim → 縁取り。

候補の重み付けは `chooseColor`。縁や下地で可読性を別途担保している場合は
contrast差を重みに使わない（使うと純白・純黒が構造的に最有力になる）。
`textMinChroma` を持つgenreでは、下限彩度に満たない候補を母集団から外す
（重みを下げるだけでは一定確率で無彩色が引かれ続ける）。
`textLBand` を持つgenre（pastel前提の asmr）は明度帯でも絞る。候補が尽きたら彩度だけに緩める。

彩度・明度の方針は **大きな文字にだけ** 課す。小さい文字にも掛けると、plate上の暗色文字まで
明度を持ち上げて地色と同化する（黄色いpillに黄色い文字）。

`decor` 側にも色を潰す経路が複数あるため、組み上がった `spec.fill.stops` に対して
`enforceVividFill` で彩度の下限を一度だけ課し、`repairFillAgainstPlate` で plate との
contrastを明度側で回復させる。純黒はgamut上その明度で彩度を持てないため、
彩度を出せる明度帯へ寄せてから彩度を与える。

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
- `buildGlitchPlan(rng, genre, intensity, mode, restraint) → op[]`（`mode` は `'auto'|'strong'|'off'`）
- opは `common`（lightLeak/noiseBand/rgbSplitBand/edgeGhost）`uncommon`（sliceShift/scanTear/monoBand）`rare`（posterizeBand/pixelBand/halftoneBand/blockScramble/waveWarp）のtierを持つ。tier単位で出現確率gateと枚数上限を掛けるため、写真として不自然な処理は稀にしか乗らない。`mode === 'strong'` のみgateを外す
- `restraint` は0〜1。monochrome寄りのfilterや重いgrade lookと重ね掛けになる場合に process.js から渡し、uncommon/rareのgateを下げる
- `applyGlitch(ctx, w, h, plan, rng, faces)`（`faces` は正規化Rect[]。重なる帯は使わない）

### js/image/process.js
- `processImage(opts) → {filterSpec, gradeSpec, glitchOps, cutoutUsed}`
  `opts = {ctx, baseCanvas, W, H, rng, genre, intensity, faces, subject, cutoutMode, gradeMode, glitchMode}`

`intensity`（画像加工の強さ）と `decorIntensity`（文字装飾の強さ）はUI上も内部でも別軸。
画像を素のまま出しつつ文字だけ強く飾る指定ができるよう、1本のslider兼用をやめている。
`intensity` は filter / grade / glitch / overlay、`decorIntensity` は colorPlan の accent 彩度と
decor の予算に効く。

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

### js/render/anchors.js
`ANCHOR_BASE[name] → Rect`（基準値。skeleton が解決しなかった anchor の既定値）
- `setActiveAnchors(map)` / `A(name) → Rect` / `hasAnchor(name) → boolean`

surface は座標定数を直接参照せず、必ず `A(name)` 経由で解決済み矩形を読む。
これにより同一 surface でも poster ごとに位置・寸法が変わる。

### 文字サイズの下限（text.js）

`minFontSize(startSize, H)` は「絶対px」「canvas高比 `MIN_FONT_H_RATIO`」「開始サイズ比
`MIN_SIZE_RATIO`」の最大値（ただし開始サイズは超えない）。
絶対pxだけで決めると出力が大きいほど相対的に小さくなり、表示倍率で潰れる。
収まらない場合は縮小し続けるのではなく、字詰め（`FIT_STEPS` の `sx`）→ 行削り → 省略記号で処理する。
読めない文字より省略の方がまし、という判断。

### 装飾 surface の原則

**位置に根拠を持たせる。** 文言を持たない装飾を被写体の上の乱数位置に置かない。
空の色板が浮くだけで成果物が壊れる（`tapeStrip` を削除した理由）。
文言を載せる floater は `floaters` の仕組みを使う。

罫線の類は帯の縁に沿わせる（`drawHairRules` は `RULE_FOOT_ANCHORS` / `RULE_HEAD_ANCHORS` で
実在する帯を探し、無ければ引かない）。乱数のyに引くと写真を横切るだけの線になる。

**画面に置く装飾は anchor 経由で引く。** `A(name)` を通した矩形は `beginAnchorTrace` に
記録され、文字配置が占有領域として避ける。直接座標で描くと文字が上に乗る
（`discSpine` に anchor を与えた理由）。

### js/render/skeleton.js
固定 layout 表を持たず、genre 仕様から骨格を毎回生成する。

- `GENRE_SPEC[genre]` … aspect 候補・hero 配置 mode・role の組版値・帯 (`foot`/`head`)・
  floater・装飾 surface・overlay の語彙
- `buildSkeleton(rng, genre) → Plan`
  `Plan = {genre, spec, aspect, heroMode, heroVertical, titleVertical, margin}`
- `composeLayout(rng, plan, copy) → Layout`
  `Layout = {id, aspect, slots: Slot[], surfaces, overlays, anchors, heroMode, bands}`
  `Slot = {role, size, tracking, maxLines, align, latin?, vertical?, big?, onSurface?,
           decor?, fixed, slide, rect, candidates: Rect[]}`

`align` は `'left'|'center'|'right'|'top'`。`decor` は `'title'|'accent'|'plain'`。
`fixed` は帯・floater 内の slot（矩形確定済み）、それ以外は `candidates` を
`findBestRect` が `slide` の範囲で画像を見て選ぶ。

生成順は 帯 → hero → floater → satellite → 装飾 surface。
後段ほど先行要素の矩形（`occupied`）を避けるため、この順序を崩すと文字が重なる。

### js/render/theme.js
- `buildTheme(rng, genre) → {obiColors, ribbonColors, plateColors, accentColors, inkColors}`

### js/render/surfaces.js / js/render/overlays.js
- `SURFACE_FUNCS[name] = (ctx, W, H, rng, theme) => void`
- `OVERLAY_FUNCS[name] = (ctx, W, H, rng, theme) => void`

## 描画順序（poster.js）

1. 顔検出・saliency（原画）
2. `buildSkeleton`（aspect と hero mode を決定）→ crop決定 → base canvas
3. crop後の再解析（luma / saliency / face / costmap）
4. 画像処理（filter → grade → glitch、被写体分離があれば前景背景で別処理）
5. 文言生成 → `composeLayout` → `setActiveAnchors`
6. surface（文字の下地）／font決定
7. slot配置探索（`fixed` は確定矩形、それ以外は `findBestRect`）
8. 合成後のpixelから文字色決定 → 装飾spec → 描画
9. overlay
10. debug表示

## 制約

- 固定幅CSSを使わない
- Comment は TODO 以外書かない
- fallback で誤魔化さず、条件を満たさないときは効果を使わない
- 顔領域は文字も破壊効果も避ける
