# POSTER FORGE

画像を投入して、映画風・イメージビデオ風・小説風・ASMR音声作品風・ゲームパッケージ風・アダルトビデオ風の
擬似パッケージを生成する client side demo。Serverもnetwork通信も使わず、画像は端末内でのみ処理される。

## 起動

`index.html` を browser で開くだけ。`file://` で動くのでlocal serverもbuildも要らない。
静的hostingに置く場合も、そのまま配置すれば動く。

顔検出の model は `vendor/` に同梱してあり、実行時に外部へ取りに行かない。
描画に WebGL を使うため、WebGL が使えない環境では顔検出が失敗する（「顔領域を避ける」を切れば生成は通る）。

## 操作

1. genre を選ぶ
2. 画像を投入する（drag & drop / tap / paste）

以降は SHUFFLE で seed を振り直すたびに別物が出る。SAME SEED は同じ seed で条件だけ変えて再描画する。

## 生成の考え方

多様性は語彙の量ではなく **独立軸の積** で作る。

- 文言：語基合成（前部要素 × 後部要素）× 構文skeleton × 表記体裁 × 数値slot × 人名合成（姓 × 名）
- 画像：crop戦略 × filter mode × color grade look × 破壊効果の組合せ × 被写体分離
- 意匠：骨格generator × surface × overlay × font × 文字装飾spec

同じ seed からは常に同じ結果が出る（PRNGは mulberry32）。

## 構成

```
index.html                script読み込み順（依存順）を定義
css/style.css
js/main.js                UI結線
vendor/tfjs/              TensorFlow.js + BlazeFace（顔検出）
vendor/model/             BlazeFace weightsをbase64封入したscript
js/core/     rng color analysis face saliency crop segment placement legibility
js/text/     lexicon morphology orthography patterns copywriter
js/image/    filterSpec grade glitch process
js/render/   fonts decor text anchors skeleton theme surfaces overlays poster
tests/smoke.mjs           Chromiumでの生成smoke test
doc/         ARCHITECTURE.md REQUIREMENTS.md
```

module間の契約は `doc/ARCHITECTURE.md` を参照。

各fileは `(function (PF) { ... })(window.PF = window.PF || {})` で包み、公開する関数だけを
末尾の `Object.assign(PF, {...})` で `window.PF` に載せる。他moduleの関数は先頭の
`const { ... } = PF;` で受け取る。module内部の名前は IIFE の外に漏れない。

module を追加したら `index.html` の script tag を**依存先より後ろ**に足す。
tag の順序がそのまま評価順であり、依存関係の唯一の定義になる。

## test

```bash
npm i playwright-core      # 初回のみ
node tests/smoke.mjs
```

`tests/sample.jpg` を先に置いてください。`smoke.mjs` と `decor-catalog.mjs` が
`input[type=file]` へ投入する入力です。画像は版権の恐れがあるため git に入れていません。
人物が写った写真であれば何でも構いません（顔検出と saliency を通すため）。

Chromiumのpathは `CHROMIUM_PATH` で上書きできる。指定が無ければ playwright の browser、
installed Chrome / Chromium の順に探す。

`index.html` を `file://` で開き、6 genre × 複数seed × 複数aspectの画像で生成を回す。
実fileを `input[type=file]` に投入して `getImageData` と PNG書き出しまで通すので、
`file://` での canvas tainting も検出できる。
例外・console errorが出たら失敗する。`tests/shots/` にgenreごとのscreenshotを出力する。
