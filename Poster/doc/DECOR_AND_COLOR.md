# 文字装飾と色彩設計の仕様（ARCHITECTURE.md の追補）

## 1. 問題認識

### 装飾軸が足りない
「塗り＋縁＋影」しか無いのは、装飾ではなく**書式**に過ぎない。
実際のパッケージ文字には、地（座布団）・歪曲・特殊効果という3系統が存在する。

### Presetが硬直している
genreごとに固定の組合せを持つと、同じgenreの出力が毎回同じ顔になる。
genreは**軸ごとの重みvector**であるべきで、確定した組合せであってはならない。

### 色彩設計が無い
画像の色・文字の色・効果の色・surfaceの色が、それぞれ独立にrandomで決まっていた。
結果として整合性が無い。**1枚のposterは1つの配色計画に従う**必要がある。

---

## 2. 色彩設計（Color Plan）

### 2.1 色空間

知覚均等な **OKLab / OKLCH** を基準にする。sRGBのHSLで色相を回すと明度が破綻するため使わない。

`js/core/oklch.js`
- `srgbToOklab(rgb) / oklabToSrgb(lab)`
- `oklabToOklch(lab) / oklchToOklab(lch)`
- `srgbToOklch(rgb) / oklchToSrgb(lch)`（gamut外は chroma を二分探索でclampして戻す）
- `deltaEOk(a, b)`
- `apcaContrast(textRgb, bgRgb)`（WCAGと併用する）

### 2.2 画像からの色抽出

`js/core/palette.js`
- `extractPalette(buf, opts) → {clusters, dominant, colorfulness, temperature, meanL, chromaSpread}`
  - 192px幅bufferをOKLabへ変換し、**k-means++（k=6, 反復8回程度）** で代表色を得る
  - 各clusterに `{lch, weight, rgb}`
  - `colorfulness`：Hasler–Süsstrunk指標（rg/yb軸の標準偏差と平均から算出）
  - `temperature`：OKLab b* の重み付き平均（正=暖色寄り）
  - `opts.excludeSkin` で肌色域clusterを key 選定から除外できるようにする（顔色に引きずられないため）
- `pickKeyColor(palette, opts) → lch`
  面積比 × chroma の積が最大のclusterを key とする。無彩色画像なら chroma 0 の key を返し、その旨をflagで示す

### 2.3 調和配色の生成

`js/core/harmony.js`
- `buildScheme(rng, keyLch, schemeName) → lch[]`
  scheme：`monochromatic / analogous / complementary / splitComplementary / triadic / tetradic / accentedNeutral / analogousComplement`
- `chooseScheme(rng, palette, genre) → schemeName`
  **画像のcolorfulnessで重みを変える**こと。
  - 低彩度画像 → complementary / triadic（accentが映える）
  - 高彩度画像 → monochromatic / analogous / accentedNeutral（これ以上色を足すと濁る）
- `hasVibration(a, b) → boolean`
  色相差150°以上・明度差 0.15未満・両方 chroma 0.12超 の組は目がちらつくため禁止
- `enforceChromaBudget(colors, budget)`
  高彩度（C > 0.14）は **1色まで**。他は C ≤ 0.08 に落とす（60-30-10の10側だけを強くする）
- `pickReadable(candidates, bgRgb, minWcag, minApca) → rgb | null`
  条件を満たす候補が無ければ **null を返す**（無理に返さない）

### 2.4 配色計画

`js/render/colorPlan.js`
- `buildColorPlan(rng, genre, palette, intensity) → ColorPlan`

```
ColorPlan = {
  scheme,              // 採用した調和scheme名
  key,                 // key色 lch
  roles: {
    ink, inkAlt,       // 文字の主色・副色
    accent,            // 強調色（chroma budgetの1色）
    surface, surfaceAlt,
    stroke, glow, plate, shadow
  },                   // 各 {rgb, lch}
  textPalette: rgb[],  // legibility が選択に使う候補列
  tints: {             // 画像gradeへ渡す
    shadow, highlight, duotoneA, duotoneB
  },
  ratio: {dominant, secondary, accent}   // 60/30/10 の実配分
}
```

**要点：画像のgrade・surfaceの色・文字色・glow色・plate色が、すべてこの1つのplanから出る。**
genreは role への割当ての傾向（例：novelは ink=墨・accent=臙脂、gameは accent=金属）を**重みとして**与えるだけで、確定はさせない。

### 2.5 既存moduleへの反映

| module | 変更 |
| --- | --- |
| `js/image/grade.js` | `buildGradeSpec(rng, genre, intensity, colorPlan)`。split-toneのtintとduotone色を `colorPlan.tints` から取る |
| `js/render/theme.js` | `buildTheme(rng, genre, colorPlan)`。帯・板・枠の色を plan の role から取る |
| `js/core/legibility.js` | palette引数に `colorPlan.textPalette` を渡す。scrim色も plan の shadow role を使う |
| `js/render/decor.js` | `buildDecorSpec(rng, genre, slot, style, stats, intensity, colorPlan)` |

---

## 3. 装飾軸の拡張

装飾は**3系統 × 各系統内の独立軸**とし、genreは重みだけを与える。

### 3.1 系統A：地（文字の背景）

- 適用範囲：`none / 全体 / 行ごと / 文節ごと / 文字ごと / 先頭N字 / 末尾N字 / random部分`
  → **「文字の一部にだけ背景色が付く」を必ず表現できること**
- 形状：`rect / roundRect / circle / ellipse / square / hexagon / diamond / ribbon（両端V字）/ speechBubble / brush（筆跡）/ tornPaper / tag（片側尖り）/ underlineBar / markerHighlight（文字の下半分だけ蛍光帯）`
- 装飾：縁取り付き / 影付き / 二重板（色違いでずらす）/ 傾き / 角度違いの平行四辺形
- `knockout`：板を文字型に**抜く**（白抜き文字）。`globalCompositeOperation = 'destination-out'` で実現

### 3.2 系統B：歪曲・変形

字ごと・行ごとの座標に関数を掛ける。**layoutで座標を確定してからpaintで変形する**構造を活かす。

- `arc`：円弧に沿わせる（字ごとにrotate + baseline移動）
- `wave`：sin波でbaselineを上下
- `jitter`：字ごとに微小な回転・上下・大小の揺れ（**でこぼこ**）
- `trapezoid`：台形（遠近）。上下で字幅を線形変化
- `bulge`：中央の字を大きく、両端を小さく
- `fan`：扇状の回転配置
- `stagger`：階段状の配置
- `alternateScale`：大小交互
- `rampScale`：漸増・漸減
- `perGlyphShear`：字ごとに異なるskew

### 3.3 系統C：特殊効果

- `extrude`：奥行き方向に多重描画（3D押し出し）
- `neonTube`：太い外glow + 細い明色の芯
- `chrome`：水平分割の反転gradient（鏡面）
- `stripeFill`：縞塗り（clipして縞を描く）
- `patternFill`：網点・格子・斜線でclip塗り
- `imageFill`：**文字の中に元画像を流し込む**（文字をmaskにして画像をclip）
- `splitCut`：文字を水平に割って上下をずらす
- `outlineOnly`：塗り無し・線のみ
- `reflection`：下に反転コピーをgradient fadeで
- `shatter`：一部の字だけ大きくずらす
- `misregister`：版ズレ（色を変えて2〜3回重ねる）
- `roughEdge`：縁をノイズで荒らす
- `torn`：一部を欠けさせる
- `dropCap`：先頭字だけ極端に大きく

### 3.4 Presetの脱・硬直化

**decor budget方式**にする。

1. genre と `slot.decor`（`title/accent/plain`）から **予算値**（例 title:100, accent:55, plain:20）を決める
2. 各装飾軸に**コスト**と**genre別重み**を持たせる
3. 予算を使い切るまで重み付きrandomで軸を選ぶ
4. 相互排他表（例：`outlineOnly` と `imageFill` は同時不可、`knockout` と `metallic` は同時不可、`arc` と `trapezoid` は同時不可）で矛盾を除去
5. 視認性の必須条件（背景std大 → plate/太縁/glowのいずれか）は**予算外で強制確保**

これにより、同じgenreでも毎回違う組合せになり、かつ崩壊しない。

---

## 4. 視認性の不変条件（装飾を増やしても守る）

- 文字色と**その直下の実際の地**（板を敷いたなら板の色）のcontrastを検算する
- gradient / metallic の全stopが下限contrastを満たすこと
- `hasVibration` に該当する前景・背景の組を作らない
- 高彩度色は plan の chroma budget を超えない
- glyph描画passの総数に上限を設ける（速度）
