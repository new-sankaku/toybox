# 章立ての境界検出をembeddingへ置き換える案(設計検討・未実装)

現行の章立て([CHAPTERS.md](CHAPTERS.md))は境界検出も表題付けもLLMに任せている。この文書は
**境界検出をembeddingへ移し、LLMを表題付けだけに縮める**案の設計上の論点を洗い出したもの。

実装・実行はしていない。着手可否の判断材料として書いている。

## 動機

実測した弱点は要約能力ではなく**境界検出**だった(recording 188)。

- 「お疲れ様でした」— 挨拶であって話題ではないものを章にした
- 「ブロックされた理由」— 話題は実在するが開始が約10秒遅く、引用が表題を支えていない

「話題が変わる位置」は隣接区間の意味的な近さが落ちる位置であり、embeddingはその量を直接
測れる。生成modelに探させるより素直で、かつ桁違いに安い。

## 既存資産の調査結果

**結論: 必要なembeddingは既に全て存在する。新規の埋め込み計算は不要。**

`semantic_index.db` / `semantic_vectors.bin` の実測(いずれも `mode=ro` で確認):

| 項目 | 実測値 |
| --- | --- |
| meta | `dim=768` / `dtype=float32` / `model=embeddinggemma:300m` / `schema_version=1` |
| stt passage | 28,680本 / 160 recording(= 現行timemapのtranscript全件) |
| comment passage | 19,756本 / 171 recording |
| vector file | 148,795,392 byte(48,436行 × 768 × 4、行数と厳密に一致) |

- **stt の `search_hits` 1行 = transcript segment 1件**(recording 15 の先頭 hit が
  `video_time=0.0 / end_time=9.69` で、segment[0] と一致することを確認)
- passageはそれを `TICTOK_SEMANTIC_PASSAGE_SECONDS`(既定25秒)と
  `TICTOK_SEMANTIC_PASSAGE_MAX_CHARS`(既定800字)で束ねたもの
- recording 15(41分/650 segment)→ **74 passage**。読み出すvectorは 74×768×4 = 227KB

つまり境界検出は「227KBを読んでcos類似度を並べる」だけで、**GPUもembedding APIも使わない**。
所要はmillisecond order。現行の map call(12000字 × chunk数)が丸ごと消える。

## Algorithm: TextTiling系のdepth score

素の「隣接passageのcos類似度が閾値を下回ったら境界」は採らない。cos類似度の絶対値はmodelと
題材で水準が変わるため、閾値を固定値で持つと**modelを替えた瞬間に無意味になる**(hard-code
禁止の趣旨に照らしても、意味を持たない数値を設定値に置くことになる)。

標準手法である depth score を使う:

1. 各passage境界 i について、左右それぞれ `k` 本のblockを平均vectorにまとめ、cos類似度 `s(i)` を出す
2. `s` の谷 i に対し `depth(i) = (左の直近peak - s(i)) + (右の直近peak - s(i))`
3. `depth(i) > mean(depth) + c * stddev(depth)` を満たす谷を境界に採る

**閾値が絶対値ではなく分布に対する相対値**になるので、modelや配信の題材が変わっても意味を保つ。
`c` は「どれくらい深い谷なら話題の変わり目とみなすか」で、これは設定値として意味がある。

vectorは保存時に既にL2正規化済み(`_normalize`)なので、cos類似度はdot積1本で済む。

## 設定化する値

| 環境変数 | 想定既定 | 意味 |
| --- | --- | --- |
| `TICTOK_AI_CHAPTER_BLOCK_PASSAGES` | 3 | depth score の左右block幅 `k`(passage本数) |
| `TICTOK_AI_CHAPTER_DEPTH_SIGMA` | 1.0 | 境界と認める深さ `c`(mean + c×stddev) |

**既存の `TICTOK_AI_CHAPTER_MAX` と `TICTOK_AI_CHAPTER_MIN_SECONDS` はそのまま流用する。**
最大件数と最小間隔は検出手段が変わっても同じ意味を持ち、`_thin()` も `_finalize()` も
そのまま使える。新設は上記2つだけで済む。

`TICTOK_AI_CHAPTER_CHUNK_CHARS` と `TICTOK_AI_CHAPTER_PER_CHUNK` は map段が消えるため不要になる
(削除するかは移行方針次第。現行実装を残して選べるようにするなら両方要る)。

## 境界の分解能と、その限界

**候補になり得る位置はpassageの先頭に量子化される。** passageは25秒/800字で切られているので、
分解能は概ね ±25秒。

- 章立ての最小間隔が既定60秒であることを踏まえると、**目次としては十分**
- ただし「10秒遅い」という現行の不満がそのまま消えるわけではない。性質が変わるだけである
  (LLMの気まぐれによる遅れ → 窓幅による系統的な量子化)。ここは誇張せずに評価すべき点

**任意の精密化(段階2)**: 検出した境界の前後1 passageぶんのsegmentだけを個別に埋め込み直し、
最も類似度が落ちるsegment境界へ寄せる。数十件の短文embeddingで済むので依然として安い。
必要と判断されたときだけ入れればよく、初版には要らない。

## 拒否条件(fallback禁止の観点で最重要)

現行の timemap gate に**加えて**、index側の gate が要る。どちらも「静かに壊れる」経路なので、
満たさないときは `AIError` で拒否し、LLM単独へ**退避しない**。

1. **transcriptの `timemap_version` が現行版**(現行と同じ判定。passageの `video_time` は
   search_hits 由来 = segment由来なので、時刻mapが古ければpassageも同じだけズレている)
2. **その recording が index 済みで、かつ最新**。`indexed` 表の `(hit_count, hit_max_id)` が
   現在の `search_hits` と一致すること(build自身が再構築要否に使っている判定と同じものを使う。
   ここで別の判定を書くと定義が2つに割れる)
3. **`meta.model` が現在の `TICTOK_SEMANTIC_MODEL` と一致**。異なるmodelのvectorを混ぜて
   類似度を測ると数値は出るが意味を持たない。`dim` 不一致は既存codeが検出して止めるが、
   **同じ次元の別model**は検出できないため model 名の一致確認が要る
4. `meta.dtype` が vector file の読み出しdtypeと一致(既存の `_index_dtype` を使う)

2番が満たされないとき「意味検索indexを更新してください」と案内する形になる。これは現行より
**前提条件が1つ増える**ということで、素直な劣化点である。

## 残るLLM call

区間ごとの表題付けのみ。入力は各区間の文字起こしtext(先頭数百字で足りる)で、出力は20字程度の名詞句。

- call数 = 章数(既定上限30)、1 callあたり数百字
- 現行の「12000字 × chunk数 + 統合1回」と比べ、**入力token量が桁で減る**
- 1 callにまとめて全区間の表題を一度に付けさせる案もあるが、区間数×表題で出力が伸びると
  `finish_reason=length` の罠([CHAPTERS.md](CHAPTERS.md) 参照)に再び触れる。**区間ごとに
  分ける方が安全**で、かつ失敗した区間だけ作り直せる
- `quote`(その位置の実発話)と、時刻をmodelに書かせない原則は**現行のまま維持する**。
  表題付けのcallは時刻を一切受け取らない形にできるので、むしろ現行より安全になる

## 見積り

| | 現行(LLM境界検出) | 本案 |
| --- | --- | --- |
| 41分の録画 | 約10分(実測、qwen3-vl:8b) | 境界検出 <1秒 + 短い表題call × 章数 |
| 3時間級 | 数十分 | 章数に比例するのみ(passage数に依存しない) |
| VRAM占有 | 9.66GB を数十分 | 表題callの間だけ |

GPU admission control の trade-off(章立て実行中に焼き込み・STTが数十分止まる)も、保持時間が
桁で縮むため判断が軽くなる。

## 未確認の論点

正直に書くと、以下は机上の検討にとどまり実データで確かめていない(録画進行中のためGPUもserverも
使えず、embedding計算を伴う検証を行っていない)。

- `c`(depth sigma)の妥当な既定値。**実データでの当たり付けが必須**で、複数録画で
  検出された境界を文字起こしと突き合わせないと決められない。現行実装のときと同様、
  出てきた境界を人間が読んで確かめる工程を省くべきではない
- 25秒passageが実際に話題の変わり目を捉えられているか。上の調査で recording 15 の
  passage境界の1つが 107.57秒 = 現行LLMが選んだ境界と一致していたが、これは1例にすぎない
- 挨拶・定型句(「お疲れ様」「ありがとう」)が繰り返される配信で、depth scoreがそれらを
  境界と誤検出しないか。TikTok Liveは視聴者の出入りで挨拶が頻出するため、**現行LLMが
  踏んだのと同じ穴に別の理由で落ちる可能性がある**
