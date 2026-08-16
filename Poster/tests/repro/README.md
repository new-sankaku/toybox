# 文字装飾 再現bench

参考画像から文字部分を切り出し、`js/render/decor.js` + `js/render/text.js` の実装で
同じ見た目を作れるかを1点ずつ検証する台。

## 流れ

```
targets/<genre>.json   切り出し定義（元画像とpixel box）
        ↓ crop.py
crops/<id>.png         参考画像の切り出し（正解）
crops/<id>.bg.png      再現描画の下地（文字が写り込まない背景）
        ↓
specs/<id>.json        再現の指示（font・size・decor spec）
        ↓ render.mjs
out/<id>.png           再現描画
        ↓ sheet.py
compare/<id>.png       参考と再現を左右に並べた比較画像
compare/_sheet.png     全件を縦に連結したもの
```

## command

```bash
cd C:/01_work/00_Git/toybox/Poster
.venv/Scripts/python.exe tests/repro/crop.py --info        # 元画像の寸法一覧
.venv/Scripts/python.exe tests/repro/crop.py               # 全件切り出し
.venv/Scripts/python.exe tests/repro/crop.py --id adult-01 # 個別
node tests/repro/render.mjs                                # 全件描画
node tests/repro/render.mjs adult-01                       # 個別
.venv/Scripts/python.exe tests/repro/sheet.py --id adult-01
```

## targets/<genre>.json

```json
[{
  "id": "adult-01-title",
  "src": "doc/reference/adult/AdultVideo1.webp",
  "box": [1225, 725, 930, 205],
  "bgbox": [300, 1100, 930, 205],
  "text": "メイドのご奉仕",
  "note": "白の光沢gradient + 金の外周glow"
}]
```

- `box` … 元画像のpixel座標 `[x, y, w, h]`。文字の周囲に少し余白を残して切る。
- `bgbox` … 同じ元画像の**文字が乗っていない**領域。切り出しと同じ寸法感の場所を選ぶ。
  再現描画の下地に使う。省略すると `box` を強くぼかしたものになるが、
  白文字がぼけて下地が明るくなるため、可能な限り `bgbox` を指定する。

## specs/<id>.json

```json
{
  "W": 930, "H": 205,
  "items": [{
    "text": "メイドのご奉仕",
    "fontCss": "\"Yu Mincho\",\"Noto Serif JP\",serif",
    "weight": "400",
    "startSize": 152,
    "rect": { "x": -0.5, "y": -0.13, "w": 2.0, "h": 1.5 },
    "slot": { "align": "center", "maxLines": 1, "tracking": 0, "decor": "title" },
    "spec": { ... decor spec ... }
  }]
}
```

- `W`/`H` は crop と同じpixel寸法にする（sheet.py が寸法を揃えるため）。
- `rect` は canvas に対する比率。**[0,1] の外に出してよい**。
  大きな rect を渡すと自動縮小が効かず `startSize` がそのまま出る。
  文字の中心は rect の中心に来るので、`x = cx - w/2`, `y = cy - h/2` で位置を決める。
- `items` は複数書ける（title と 小さなtag を1枚に重ねる等）。描画順は配列順。
- `slot`: `align` は `left|center|right`、`vertical: true` で縦組み、
  `maxLines` は行数（縦組みでは列数）、`tracking` は字送りの比率（**負の値＝詰め組み**、下限 -0.3）、
  `sizeTier`/`phraseWrap`/`tiered`/`big` も指定可。

## decor spec の全field

`js/render/decor.js` の `paintDecorated` が解釈するもの。長さ・幅の類は
**すべて font size に対する比率**（0.1 なら size の10%）。色は `[r,g,b]` の0-255。

```jsonc
{
  // 塗り（必須）
  "fill": {
    "type": "solid|linear|duotone|metallic|mirror|stripe|pattern|image|none",
    "angle": 1.5708,                       // gradientの角度（rad）。縦gradientは PI/2
    "alpha": 0.4,                          // 塗り全体の不透明度（省略時1）。半透明のcredit等に使う
    "stops": [{ "t": 0, "rgb": [255,255,255], "a": 0.6 }, { "t": 1, "rgb": [230,200,140] }],
    "stripe":  { "rgb": [0,0,0], "width": 0.12, "slant": 0.8 },        // type=stripe
    "pattern": { "kind": "dots|grid|diagonal|crosshatch|checker",
                 "rgb": [0,0,0], "step": 0.12, "weight": 0.2 },        // type=pattern
    "image":   { "veil": [0,0,0], "veilAlpha": 0.35, "zoom": 1.2 }     // type=image（下地画像を文字で抜く）
  },

  // 塊全体の変形（scaleX は縁・影まで潰す。字面だけ潰したい時は下の glyphScaleX を使う）
  "transform": { "skewX": 0.12, "rotate": -0.03, "scaleX": 0.86 },
  // 字面だけを横に潰す／広げる。ctxを変形しないので縁の太さは等方のまま
  "glyphScaleX": 1.35,

  // 縁取り。配列の順に描くので **太い順**（外側→内側）に並べる
  // align:"outside" は字面を痩せさせずに外側だけへ縁を回す（煽りtitleの定型）
  // isotropic:true は字型を膨らませて縁を作る。glyphScaleX で字を潰しても縁は真円のまま
  "strokes": [{ "width": 0.09, "rgb": [24,18,40], "alpha": 1, "align": "outside" },
              { "width": 0.05, "rgb": [255,255,255], "alpha": 1, "isotropic": true }],

  // 外周の光。配列で複数段書ける（先頭から描くので 広いhalo → 細いrim の順）
  "glow": [{ "rgb": [180,120,30], "alpha": 0.85, "blur": 0.6,  "passes": 2 },
           { "rgb": [255,210,120], "alpha": 1,   "blur": 0.06, "passes": 2 }],

  // 落ち影。最初のstroke（strokeが無ければfill）に付く
  "dropShadow": { "rgb": [0,0,0], "alpha": 0.45, "dx": 0.02, "dy": 0.03, "blur": 0.06 },

  // 長い影（1方向に steps 回ずらして重ねる）
  "longShadow": { "rgb": [20,20,20], "alpha": 0.7, "steps": 12, "dx": 0.02, "dy": 0.02 },

  // 押し出し（near→far へ色を送りながら steps 回）
  "extrude": { "near": [180,40,40], "far": [80,10,10], "steps": 8, "dx": 0.015, "dy": 0.02 },

  // 座布団
  "plate": {
    "scope": "all|line|phrase|glyph|head|tail|random",
    "shape": "rect|roundRect|circle|ellipse|square|hexagon|diamond|ribbon|tag|speechBubble|brush|tornPaper|underlineBar|markerHighlight",
    "rgb": [10,10,10], "alpha": 1,
    // 板1枚ごとの矩形に gradient を張る。指定すると rgb より優先
    "fill": { "type": "metallic", "angle": 1.05,
              "stops": [{ "t": 0, "rgb": [120,88,30] }, { "t": 0.35, "rgb": [246,226,160] },
                        { "t": 0.55, "rgb": [176,134,52] }, { "t": 1, "rgb": [232,208,140] }] },
    // 板の立体縁（上辺が明るく下辺が暗い金属板）
    "bevel": { "light": [255,244,205], "dark": [92,64,18], "offset": 0.035 },
    // 並び順に沿って板ごとに明度を振る（fill 指定時のみ。0.18 なら ±18%）
    "ramp": 0.18,
    // 既定では外側 transform があると板の rotate/skew は捨てられる（歪みの二重掛けを避けるため）。
    // 板だけ別角度に倒したい時だけ true にする
    "ignoreOuterTransform": false,
    "padX": 0.24, "padY": 0.12, "radius": 0.2,
    "n": 2, "ratio": 0.3,                  // scope=head/tail の字数、random の割合
    "skew": 0, "rotate": 0, "perRotate": 0,
    "border": { "rgb": [255,255,255], "width": 0.02, "alpha": 1 },
    "shadow": { "rgb": [0,0,0], "alpha": 0.4, "dx": 0.03, "dy": 0.03, "blur": 0.05 },
    "double": { "rgb": [200,30,60], "dx": 0.05, "dy": 0.04, "alpha": 1 },
    "knockout": false,                     // true で板を文字型に抜く（白抜き文字）
    "seed": 1
  },

  // 効果
  // inset:true で字型に切り、光沢を画線の内側だけに留める（縁を痩せさせない）
  "bevel":       { "light": [255,255,255], "dark": [80,60,20], "offset": 0.03, "alpha": 0.9, "inset": true },
  "innerLine":   { "rgb": [120,90,30], "width": 0.014, "alpha": 0.8, "inset": true },
  "edgeSplit":   { "dx": 0.012, "dy": 0.004, "alpha": 0.6, "a": [255,46,46], "b": [40,170,255] },
  "misregister": { "layers": [{ "rgb": [255,0,80], "dx": 0.02, "dy": -0.01, "alpha": 0.7 }] },
  "splitCut":    { "at": 0.5, "shift": 0.08 },
  "reflection":  { "gap": 0.06, "alpha": 0.35, "fade": 0.5 },
  "roughEdge":   { "amount": 0.04, "density": 1.0, "seed": 7 },
  "torn":        { "count": 3, "amount": 0.2, "seed": 7 },

  // 仕上がった字の**外周**を半径 width ぶん一様に削る。
  // 単色塗りだけの字を細くする用途（太い丸ゴを細く見せる等）に使う。
  // 縁やglowと併用すると縮むのは外周silhouetteだけで、内部の色境界には効かない。
  // 罫（underline/overline）と傍点は削られない（収縮後に引かれる）。
  // 実用上限は 0.035 前後。それを超えると細部が千切れて字形が保てない。
  "erode": { "width": 0.008 },

  // 罫・傍点。angle/extend/taper/border を足すと手書きlogoの「払い」になる
  "underline": { "rgb": [200,30,40], "alpha": 1, "width": 0.05, "gap": 0.14, "double": false, "spacing": 0.08,
                 "perLine": true,    // 行ごとに1本ずつ引く（省略時は塊全体に1本）
                 "angle": -0.14,     // 傾き（rad）
                 "extend": 0.35,     // box幅に対する左右の伸長比（文字boxの外へ伸ばす）
                 "taper": 0.85,      // 端の細り率（0で従来の帯、1で端が尖る）
                 "shift": 0.1,       // 長さ方向へのずらし（size比）
                 "border": { "rgb": [120,200,235], "width": 0.012, "alpha": 1 } },
  "overline":  { ...同じ... },
  "boten":     { "rgb": [0,0,0], "mark": "●", "size": 0.2, "gap": 0.1, "alpha": 1 },

  // 字ごとの変形
  "distort": {
    "arc": 0.1, "wave": { "amp": 0.06, "freq": 1, "phase": 0 },
    "jitter": { "rot": 0.015, "off": 0.012, "scale": 0.03 },
    "trapezoid": 0.3, "bulge": 0.3, "fan": 0.1, "stagger": 0.08,
    "alternate": 0.2, "ramp": 0.3, "shear": 0.15, "dropCap": 0.6,
    "drift": 0.14,                          // 字は正立のまま行（列）だけ斜めに流す
    // 式では決まらない癖を字番号で直接指定する（手書きlogo調）。既存の軸と併用できる
    // kern はその字の後ろの送りを増減する手詰め（負で詰まる）。均等trackingでは作れない字面に
    "perGlyph": [{ "i": 0, "s": 1.28, "dy": -0.03, "kern": -0.06 }, { "i": 2, "s": 0.84, "rot": 0.05 }],

    "shatter": { "ratio": 0.15, "amp": 0.1 }, "seed": 1
  },

}
```

省略したfieldは `null` 扱いで描かれない。`fill` だけは必須。

### 描画順（重なりの前後関係）

```
plate → longShadow → extrude → glow → strokes(配列順) → bevel
      → misregister/edgeSplit → fill → innerLine → reflection
      → underline/overline → boten
```

`strokes` は fill より**先**に描かれるので、太い縁は自動的に文字の外側に回る。

## 進め方

1. `crop.py --info` で元画像の寸法を見る
2. `targets/<genre>.json` に box を書いて `crop.py` → `crops/<id>.png` を**目で見て**
   文字がきちんと収まるまで box を直す
3. `specs/<id>.json` を書いて `render.mjs` → `sheet.py` → `compare/<id>.png` を**目で見る**
4. 合うまで 3 を繰り返す
5. decor spec でどうしても表現できない要素は README ではなく報告に書く
   （engine側の不足として別途 decor.js を直す）
