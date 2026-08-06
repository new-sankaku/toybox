# POSTER FORGE 要件

## 概要
画像を加工して映画風・image video package風・novel風に見せるお遊びのdemo site。

## 前提
- Serverなし（client側のみで完結）
- 高速動作が必須
- PC / smart phone 双方で動作

## User操作（2 step）
1. Genreを選ぶ（movie風 / image video風 / novel風）
2. 画像を投入する

## Template方針
- Font、色彩調整、脱色、背景削除などをrandomで組み合わせる
- 文字装飾もrandomで組み合わせる
- 台詞は大量に用意し、randomな組み合わせで生成する
- Templateと文字は固定にしない

## Algorithm要件
- 顔部分は避けて配置する
- 白がmainの画像に白色fontなど、明らかに視認性が下がる組み合わせは除外する
- 多少の整合性の違いは許容する

## 成果物
- `poster_forge_1.html`（single file）
