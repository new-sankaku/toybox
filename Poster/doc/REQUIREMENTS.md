# POSTER FORGE 要件

## 概要
画像を加工して各種パッケージ風に見せるお遊びのdemo site。

## 前提
- Serverなし（client側のみで完結、network通信なし）
- 高速動作が必須
- PC / smart phone 双方で動作

## User操作（2 step）
1. Genreを選ぶ
2. 画像を投入する

## Genre（6種）
| key | 表示 | 体裁 |
| --- | --- | --- |
| cinema | 映画風 | キャッチ／billing block／公開日 |
| gravure | イメージビデオ風 | 帯・型番・特典表記 |
| novel | 小説風 | 縦組み・帯コピー・レーベル |
| asmr | ASMR音声作品風 | 正方形に近い比率・CV表記・track情報 |
| game | ゲームパッケージ風 | 機種帯・年齢区分枠・edition表記 |
| adult | アダルトビデオ風 | 品番・斜め帯・販促文言 |

すべて **文字と意匠の体裁のみ** の差異とする。
画像内容をgenreに応じてR18方向に変える処理は作らない。

## 多様性の設計方針
語彙を線形に増やすのではなく、**独立軸を増やして積にする**。

- 名詞は部品化して合成する（前部要素50 × 後部要素50 = 2,500語）
- 表記・体裁を独立軸にする（鉤括弧・読点位置・三点リーダ・感嘆符・英字併記）
- 数値slot（回数・部数・年月・型番）で連続値を注入
- 人名は姓60 × 名60 = 3,600通りの合成
- 毎回すべてをmergeしない。タイトルが『犬』の一語でもよい
- 語彙tableはgenreごとに変える

## 画像加工の要件
- 色彩を変える（color grade。lift/gamma/gain・split tone・duotone）
- 一部分だけにglitchを入れる（帯単位のslice shift、色収差、mosaic、網点 等）
- 顔領域は文字も破壊効果も避ける
- 投入画像が想定と異なる比率のときは自動で切り抜く（saliency + 顔 + 三分割法）

## 文字装飾の要件
実際のパッケージで使われる装飾を調査し、genreごとのpresetに落とす。
袋文字・二重縁・bevel・metallic gradient・long shadow・outer glow・ベタ板・傍点・擬似コンデンス等を
独立軸として組み合わせる。

## 視認性の制約
- 白がmainの画像に白文字など、明らかに視認性が下がる組合せを除外する
- WCAG contrast比で large 3.4 / small 4.5 を下限とする
- 背景のばらつきが大きい領域では scrim / plate / 太い縁取り / glow のいずれかを必ず入れる

## 成果物
static site（`index.html` + `css/` + `js/`）。起動scriptは Windows / Linux 両対応。
