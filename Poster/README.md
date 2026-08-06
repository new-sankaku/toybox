# POSTER FORGE

画像を投入して、映画風・イメージビデオ風・小説風・ASMR音声作品風・ゲームパッケージ風・アダルトビデオ風の
擬似パッケージを生成する client side demo。Serverもnetwork通信も使わず、画像は端末内でのみ処理される。

## 起動

ES module を使うため `file://` では動かない。同梱のscriptでlocal serverを立てる。

```bash
./serve.sh          # Linux / macOS
serve.bat           # Windows
```

`http://localhost:8080/` を開く。

## 操作

1. genre を選ぶ
2. 画像を投入する（drag & drop / tap / paste）

以降は SHUFFLE で seed を振り直すたびに別物が出る。SAME SEED は同じ seed で条件だけ変えて再描画する。

## 生成の考え方

多様性は語彙の量ではなく **独立軸の積** で作る。

- 文言：語基合成（前部要素 × 後部要素）× 構文skeleton × 表記体裁 × 数値slot × 人名合成（姓 × 名）
- 画像：crop戦略 × filter mode × color grade look × 破壊効果の組合せ × 被写体分離
- 意匠：layout × surface × overlay × font × 文字装飾spec

同じ seed からは常に同じ結果が出る（PRNGは mulberry32）。

## 構成

```
index.html
css/style.css
js/main.js                UI結線
js/core/     rng color analysis face saliency crop segment placement legibility
js/text/     lexicon morphology orthography patterns copywriter
js/image/    filterSpec grade glitch process
js/render/   fonts decor text layouts theme surfaces overlays poster
tests/smoke.mjs           Chromiumでの生成smoke test
doc/         ARCHITECTURE.md REQUIREMENTS.md
```

module間の契約は `doc/ARCHITECTURE.md` を参照。

## test

```bash
npm i playwright-core      # 初回のみ
node tests/smoke.mjs
```

Chromiumのpathは `CHROMIUM_PATH` で上書きできる。

local serverを立ててChromiumを起動し、6 genre × 複数seed × 複数aspectの画像で生成を回す。
例外・console errorが出たら失敗する。`tests/shots/` にgenreごとのscreenshotを出力する。
