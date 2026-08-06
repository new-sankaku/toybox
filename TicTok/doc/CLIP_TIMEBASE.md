# 切り出し・窓焼き込みの時刻軸（実測記録）

2026-07-26 に実録画と合成素材で測った結果。ここに書いてある数値は推論ではなく実測で、
再導出には数時間かかる。**根拠なく書き換えないこと。** 覆すなら測定手順と数値を添える。

測定に使った素材と script は session の scratchpad に残してあるが、恒久保存はしていない。
再現手順は各節に command を書いた。

---

## 1. HLS入力に任意時刻を渡すと forward へ飛んで内容が欠落する

`-ss` の着地は、**実録画の密sweep（0.75秒刻み25点）で3点(12%)が forward**、最大 **1.789秒**
の欠落。残り22点は backward（前置き）。

疎な数点だけを見ると全部 backward に見えるので誤判定しやすい（実際に一度それで誤った）。
**必ず密にsweepして確かめること。**

判定は `land - (ss + container start_time)` の符号。正なら forward = 欠落。
forward は直前 keyframe を飛ばす形で起きる（例: `-ss 100.75` → 目標 102.18、keyframe 102.01 が
実在するのに 103.969 へ着地）。

### 支配要因は segment 境界との関係

合成実験（8 playlist × 4 target = 32組）で切り分けた結果:

| 候補 | 結論 |
|---|---|
| playlist tag（VERSION 6 / INDEPENDENT-SEGMENTS / BYTERANGE / DISCONTINUITY） | **無関係**（32組すべてで着地一致） |
| container start_time | **無関係** |
| `-copyts` の有無 | **無関係** |
| GOP/segment 比 | 欠落量と0byte発生率には効くが、**forward自体は消えない**（比1・keyframe整列でも出る） |
| **segment境界と要求時刻の関係** | **これが支配要因**。着地は概ね「ssより後ろの最初のsegment境界」= ceiling |

**0byte出力は比18倍（37秒GOP / 2秒segment）で実在**。比3では未発生で、その間の閾値は未測定。
error終了ではなく `Output file is empty` で 0 byte file が残るのが特に危険。

要求時刻を segment 境界へ snap し、かつ segment が keyframe 整列していれば前置き0・欠落0に
なる（合成で実測）。ただし**非整列だと境界snapしてもkeyframeを2つ飛ばして最大7.7秒失う**ため、
snap 単独では不十分で**着地検証との併用が必須**。

### 実録画の keyframe 間隔

8本調査で **最大6.08秒**（segment 約2秒）。`clipper.py` docstring の「2.1〜37.6秒」は
現存録画では再現しない（該当録画が retention で消えた可能性）。

### 既存 clipper への影響（修正済み・2026-07-26）

`make_clip` の copy 経路は任意時刻をそのまま `-ss` に渡していたため、実測で**要求30秒の
切り出しが「先頭1.99秒は音声だけ（映像なし）」で出て、要求した頭0.7秒ぶんの映像を
失っていた**。しかも `keyframe_lead_seconds` は `max(0.0, actual-duration)` で、`actual` は
長い方の stream（= 手前から入った audio）の尺なので **0 と報告される**。尺の警告も
tolerance 1.0秒未満の欠落を素通りしていた。

copy 経路は §6.2 と同じ2段（TS中間1つ経由）に変え、前置きは**実測した着地**から出す。

### 再現

```bash
# 37秒GOPの素材（keyframeを0/5/42の3点に固定）
ffmpeg -y -f lavfi -i testsrc2=size=320x240:rate=30:duration=60 \
  -f lavfi -i sine=frequency=440:duration=60 \
  -c:v libx264 -force_key_frames 0,5,42 -sc_threshold 0 -g 9999 \
  -pix_fmt yuv420p -c:a aac -shortest long_gop.mp4

# 着地の測定（-muxdelay 0 -muxpreload 0 が無いと mpegts の1.4秒 initial offset を誤読する）
ffmpeg -y -v error -ss $T -i <src or playlist> -to 45 -copyts \
  -muxdelay 0 -muxpreload 0 -c copy -f mpegts out.ts
ffprobe -v error -select_streams v:0 -show_packets -read_intervals '%+#1' \
  -show_entries packet=pts_time,flags -of csv=p=0 out.ts
```

---

## 2. `-copyts` 下で出力側 `-t` は使えない

出力側 `-t` は出力 timestamp 基準で測るため、**窓開始が `-t` 値以上だと1 frameも出ず空になる**
（`-ss 30 ... -t 10` で 0 frame / 262 byte）。既存 code の comment は「短く切れる」と書いているが
現象を過小に記述している。

`-copyts` は **global option** で、output 位置に書いても回避できない。
使えるのは**入力側 `-t`** か `-to <絶対終端>`。入力側 `-t` の方が音声尺が厳密だった。

`-to` は `-output_ts_offset` 適用**前**の軸で評価されるので、両者は干渉しない。

---

## 2b. `-ss` は media 軸、`-to` は container 軸（同じ command の中で軸が違う）

実録画（HLS入力、container start_time 1.43秒）で media 100→110 を要求した実測:

| 渡した値 | 内容の media 軸終端 | 判定 |
|---|---|---|
| `-to 110`（media値） | **108.737** | 要求の末尾 **1.43秒が落ちる** |
| `-to 111.43`（container値 = media + offset） | 110.177 | 正しい |

`-ss` は ffmpeg が container start_time を足して解釈するので **media 軸のまま渡す**。
`-to` は `-copyts` 下で **container 軸**なので、**media 軸の値に container start_time を
足し戻す**必要がある。`concat.cut_part` はこれを行う。mp4 入力では offset が0なので無害。

**この非対称は `-muxdelay 0 -muxpreload 0` を付けずに測ると見えない。** mpegts muxer の
約1.4秒 initial offset が偶然ちょうど打ち消して「`-to` も media 軸だ」と読めてしまう
（実際に一度それで誤読した）。§7 の落とし穴と同根。

修正前の `reel.py` は media 軸の値をそのまま `-to` に渡していたため、**HLS 由来の各 part の
末尾が約1.43秒早く切れていた**。

## 3. `-copyts` は外せない

外すと filter の `t` が0起点になり、**絶対時刻で key している overlay（gift の
`enable=between(t,...)`）が壊れる**。`-output_ts_offset` は filter より後段の mux 段で効くので、
「filter は絶対軸・出力は0起点」を同時に満たせる。

---

## 4. 0起点化は `-output_ts_offset` のみ

| 案 | v start_time | video elst | 判定 |
|---|---|---|---|
| **`-output_ts_offset -<絶対開始>`** | 0.000000 | 1 entry（原本と同型） | **採用** |
| `-avoid_negative_ts make_zero` | 0.066016 | **empty edit 66ms** + v/a不揃い + skip_samples消失 | 不可 |
| `-muxdelay 0` | 30.000000 | 変化なし | mp4 に無効（mpegts/ps 用） |
| 併用 | make_zero と同一 | 劣化のみ | 不可 |

渡す値は「**container start_time + 相対seek**」。相対値の符号反転では足りない
（HLS入力の container start_time は実測 1.43秒で0ではない）。ffprobe で取る手数が要る。

実 HLS 入力では offset を付けても **約5msのempty editが残る**（accurate seek の frame 量子化）。
「完全に clean」にはならない。

### 既存 preview clip の欠陥

`preview_clip` は絶対 timestamp のまま出力するため、窓開始120秒の例で **121.4秒の empty edit**
が両 track に入る（video timescale 19264 で 2339324、audio 48000 で 5827584）。
ffmpeg 自身は復号できるが、edit list を尊重する player での見え方は未確認。

---

## 5. 音声

窓経路が音声を捨てているのは `-an` が入っているだけで、**`-map 0:a?` を足せば戻る**
（実 HLS 録画で確認）。専用の第2 input は不要。

ただし comment layer 経路では input 0 が `-an` 付きの CFR base なので `-map 0:a?` は静かに
空振りする。その場合だけ原本を音声用の追加 input として開く必要がある。

### AAC priming を A/V desync と誤読しないこと

音声を自身の0起点 decode 軸で測ると 21.33ms（1024 sample）ずれて見えるが、presentation 軸で
video frame を抜いて突き合わせると同期している。**派生 metric ではなく成果物で確認すること。**

---

## 6. 連結の A/V ずれ（解決済み・2026-07-26）

### 6.1 真因は連結ではなく切り出し段の非対称

`-ss` に**要求時刻をそのまま渡す**と、実録画（HLS入力、keyframe 約1.96秒間隔、container
start_time 1.402）で次のようになる。値は `-muxdelay 0 -muxpreload 0` 付きの container 軸:

| | 実測 | 意味 |
|---|---|---|
| 要求 | 301.402 | media 300 |
| **video の先頭** | **302.082** | 要求の**直後**の keyframe。直前の 300.121 は実在するのに落ちる |
| **audio の先頭** | **300.053** | 要求より手前の segment 境界 |

つまり **video は要求した範囲の頭を最大1 GOP失い、audio は逆に手前から余分に入る**。
part の先頭に約2秒の音声だけの区間ができる。`-noaccurate_seek` でも入力側 `-t` でも同じ。
`-copypriorss` はこの ffmpeg build では入力に適用できない。

concat demuxer は次の file へ与える offset を **file 全体の尺（= 長い方 = audio）**で決めるので、
この差が接合ごとに **video の穴**として現れる。

### 6.2 直し方

1. `-ss` には要求時刻ではなく **要求以前の最後の keyframe を狙う値**を渡す
   （`keyframes.seek_target`。着地は毎回実測して検証し、要求より後ろなら失敗させる）
2. 残る audio の前置きは **concat demuxer の `inpoint`/`outpoint`** で落とす

`inpoint` の置き場所は実測で決まった。**2条件を同時に満たす必要がある**:

| inpoint の置き方 | A/Vずれ | 映像 |
|---|---|---|
| video 先頭と同値 | — | **次の keyframe へ飛ぶ**（GOPが1つだけの part では**映像stream が消える**） |
| 境界の途中（1ms / frame/8 / frame/2、`+genpts` 有無も） | **75ms 音が先行** | あり |
| **audio packet の境界ちょうど**（video 先頭の直前） | **8〜68ms** | あり |

境界を1〜2 packet手前へずらしても差は出なかった（13〜17ms）。`+genpts` の有無も無関係
（両方 75ms）。**「境界ちょうどか否か」だけが効く。**

映像が消える閾値は素材で動く（合成素材: frame 33ms・余裕15msで映像0 packet、余裕40msで182
packet）。そこで**余裕は最小（1 packet以内）から始め、出力に映像が無ければ1 packetずつ
下げてやり直す**（`WIDEN_ATTEMPTS` まで）。ffmpeg は映像stream が消えても error にしないので、
確かめない限り「音だけのmp4」が成功として渡る。推測した固定の余裕で済ませると、素材によって
黙って映像を失う。

### 6.3 成果物での確認結果

派生 metric では足りないので、出来た mp4 から次の2つを測って差を見た:

- `f_v(t)` = reel 時刻 t に映っている frame の原本時刻。**`showinfo` の checksum で突き合わせる**
  （reel は stream copy なので復号 frame は原本と bit 一致する）
- `f_a(t)` = reel 時刻 t に鳴っている音の原本時刻。波形の正規化相互相関

実録画5範囲（各12秒）:

| 指標 | 修正前 | 修正後 |
|---|---|---|
| A/Vずれの最大 | 1,320ms | **68ms**（多くの点は 20〜50ms） |
| video の穴（合計） | 10.5秒 | 2.3秒（注1） |
| audio の穴（合計） | 0.671秒 | **0秒** |
| 要求した頭の欠落 | 最大1 GOP | **無し**（着地を毎回検証） |

注1: 残る2.3秒は原本自身が keyframe ごとに持つ1 frameぶん（40ms）の間隔が37箇所で、
接合とは無関係。

**残差の測り方の限界。** 修正後の値は同じ成果物を測り直しても 8ms〜68ms の幅で動く
（探索窓の位相を ±0.5秒動かした再現性は ±5ms だが、別 run では f_v が 1 frame = 40ms
ずれることがある）。したがって「17ms」と断定はできず、**実際の残差は 68ms 以下**、
典型 20〜50ms と読むのが正しい。修正前の 1,320ms とは桁が違うので比較の結論は動かない。
なお 1,320ms が出るのは part の頭（映像が前の part で止まっている区間）で、part の内側では
修正前も ±18ms に収まっていた — **修正前の症状は「連続的なずれ」ではなく「接合ごとの穴」**
である。

### 6.4 測り方の落とし穴（自分で踏んだ）

- **単 frame の一致で時刻を決めてはいけない。** 静止気味の場面では 64x64 gray の差が 0.0 になる
  候補が何十個も並び、ずれていても「完全一致」する。最初の測定はこれで A/Vずれを
  -400〜-1000ms と誤って出した
- **動きの時系列の相関でも足りない。** VFR 素材を固定 fps へ再 sample すると位相で duplication
  の並びが変わり decorrelate する（corr 0.4〜0.9 しか出ない）。checksum 突き合わせが唯一確実
- **audio の nominal packet 長を 1024/48000 と決め打ちしない。** この素材は HE-AAC で
  **2048 sample = 42.67ms**。21.33ms 前提だと全 frame が「穴」に見える（実測値の中央値を使う）
- 修正前の出力は照合そのものが成立しない点が多い（探索窓を外れる）。**照合が弱い点を
  採用しない**フィルタを入れないと、ノイズを ±3.8秒のずれとして報告してしまう

### loudnorm は無罪

かつて `reel.py` は「範囲ごとの loudnorm で先頭0.5秒がずれる」を正規化を入れない根拠に
していたが、切り分けの結果 **loudnorm は完全に timing 中立**だった（loudnorm のみを掛けた
出力は無しの版と全点 0.2ms 以内で一致）。ずれを直していたのは同梱の `aresample=async=1` の方。
根拠とされた「0.5秒のずれ」は合成素材で**再現しなかった**。

- `aresample=async=1` は同期を直すが、実体は**各接合点への約150msの無音の実挿入**で、
  連続音声では dropout として聞こえる
- 切り出し段が揃った今、`aresample` は不要
- 副次: `linear=true` は target LRA < measured LRA のとき**無警告で dynamic へ落ちる**

---

## 7. 測定時に踏んだ落とし穴

- **mpegts muxer は既定で約1.4秒の initial offset を乗せる。** TS の timestamp を読むときは
  `-muxdelay 0 -muxpreload 0` を付けないと着地位置を誤読する
- **`-read_intervals` は `start%+尺` ではなく `start%end`（絶対終端）で渡す。** 実HLS録画では
  seek 直後の先頭 packet の `pts` が `N/A` だと `+尺` 形式は尺を決められず、**その1 packetだけを
  返して読むのを止める**（45秒窓で packet 0本・keyframe 0本）。同じ窓を絶対終端で渡せば
  1,131 packet・keyframe 23本が返る。`pts=N/A` は MPEG-TS の segment 境界で正常に混ざるものなので、
  `+尺` 形式は**実素材では走査が丸ごと空振りする**（`keyframes.video_keyframes` で修正済み。
  この形式のままでは smart cut は実録画で必ず失敗していた）
- HLS playlist に対する `-read_intervals 0%+N` は `Could not seek to position 0: Operation not
  permitted` で終了コード1になる
- **`pts_time=N/A` の packet が正常に混ざる**（MPEG-TS の segment 境界直後、実測で全 packet の
  約2.4% = segment 1本につき1 packet）。`float()` に渡して例外にすると、正常な録画を
  「壊れている」と誤診する
- 疎な数点のsweepで一般化しない（§1）

---

## 8. 精密（全編再encode）は原本へ直接 `-ss` を渡せない（修正済み・2026-08-05）

2.4時間の実録画（`00471_pomiiiip_20260804_222135`、HLS 4,389 segment、途中で解像度が
640→720 に変わる）から**60秒**を切り、開始位置を変えて測った。

### 症状: 所要時間が「切る尺」ではなく「開始位置」に比例していた

| 開始位置 | 修正前（出力側 `-ss`） | 修正後 |
|---|---|---|
| 60秒 | 2.95s | 2.85s |
| 3,600秒 | 26.55s | 2.80s |
| 7,200秒 | 49.71s | 2.67s |

encode 自体は約2.5秒。出力側 `-ss` は**seekせず要求位置まで復号しては捨てる**ので、2時間
地点では所要の95%が捨てるための復号だった。GPU（`av1_nvenc`）は最初から使えており、
encoder の問題ではない。

### 4案を実測して比べた（video/audio を stream 別に測る。container の尺は嘘をつく）

| 案 | 結果 |
|---|---|
| A 出力側 `-ss` + 出力側 `-t`（修正前） | 常に正しいが**遅い**（上表） |
| B 入力側 `-ss` + 出力側 `-t` | 速いが、**HLSが位置により前方のsegmentへ飛ぶ**。開始5000秒で出力の映像が **1.960秒** 遅れて始まり（先頭は音声だけ）、末尾も同じだけ短い（映像58.08s / 音声60.03s）。3,640 / 5,000 / 6,000 秒で再現 |
| C 入力側 `-ss` + 入力側 `-t` | 尺が膨らむ。要求60秒に対し**出力82.24秒**（開始3,600秒）。§2 の「入力側 `-t` の方が厳密」は `-copyts` 下の話で、ここには当てはまらない |
| D 入力側 `-ss` + 出力側 `-to` | B と同じ（58.08s） |
| E 粗くseek + `trim`/`atrim` filter | 速く正確だが、**解像度が変わる録画で filter chain が途中で止まる**。要求60秒が37.76秒で終わった（BUG_CHECKLIST の `reinit_filter` と同根） |
| **F copy経路で粗く切る → 短い中間だけ再encode（採用）** | 6位置すべてで **1.75〜2.31秒**・映像 59.93〜60.00秒 |

### 採用した F の理由

`concat.cut_part` は狙点を要求以前の keyframe へ寄せ、着地を毎回実測して検証する（§1・§6）。
その中間は数秒の前置きしか持たないので、そこからの再encodeは**開始位置に依らず**要求した
尺ぶんの復号で済む。前方飛びも解像度変動も、既に検証済みの copy 経路の中で扱われる。

### 着地の照合

要求 3,600秒 で修正前後の成果物を原本の frame 群へ sweep で突き合わせ、**どちらも media
3600.000 に山**（PSNR 分布まで一致）。問題位置（3,640 / 5,000秒）では A と F が一致し、
B だけがずれた。

**sweep の基準 frame を入力側 `-ss` で作ってはいけない** — 基準そのものが前方へ飛び、
どの案も「ずれている」ように見える（実際に一度それで誤読した）。基準は
「粗く入力側seek + 出力側 `-ss` で復号して捨てる」で作る。

### 未修正の隣接問題（smart cut）

- `_head_args` は入力側 `-t` を使うので C と同じ膨張を踏む。head 4.0秒の要求に対し実測
  6.22秒（開始3,620秒）・5.94秒（開始5,000秒）。head が接合点を越えて伸びるぶん、
  tail と内容が重複する
- smart cut は head の着地を検証していない（検証しているのは tail だけ）。B と同じ前方飛びを
  head も踏むので、要求どおりの IN 点という smart cut の売りが位置によって成立しない
- 開始5,000秒の smart cut は tail の着地検証が `+2.000秒` で正しく失敗し、その範囲は切れない
- 解像度が切り替わる窓では head と tail の形式が揃わず `check_compatible` で失敗する

---

## 9. smart cut の4つの欠陥（修正済み・2026-08-05）

§8 と同じ録画で測った。修正前は**位置によって失敗するか、成果物が壊れていた**。

| # | 症状（実測） | 直し方 |
|---|---|---|
| 1 | headの入力側 `-t` で尺が膨らむ。要求4.0秒に対し **6.22秒**(開始3,620秒)・5.94秒(5,000秒)。接合点を越えた分はtailと内容が重複する | headも**copy経路で粗く切った中間から焼く**。中間の中の要求位置は実測して出す（窓は先頭keyframeを守るため後ろへ広げ直されるので、`lead_seconds` をそのまま使うとずれる） |
| 2 | headの着地を検証していない。入力側 `-ss` はHLSで前方へ飛ぶので、要求どおりのIN点という前提が位置によって崩れる | 同上。`cut_part` が着地を検証する経路に乗る |
| 3 | tailの着地が狙いと違うと `RuntimeError`。開始5,000秒は **+2.000秒** で失敗し、その範囲は切り出せなかった | 着いた先も実在のkeyframeなので、**そこを接合点に採り直す**（headをそこまで焼く）。範囲の外へ着いた回だけ範囲全体を焼く縮退にし、`degenerate` で報告する |
| 4 | 範囲内で解像度が変わると `check_compatible` で失敗（640→720、実測3,626.895秒） | 接合点を**最後の切替以降**へ寄せ、切替を跨ぐheadは `-s` でtailの解像度に揃えて焼く。切替時刻はkeyframe単位で走査する（**切替のkeyframeは `pts` がN/A**なので `best_effort_timestamp` を見る） |

### 途中で見つかった、より深い2件

- **接合点に映像の穴が空いていた**（smart cut全般）。head/tailを窓無しで繋いでいたため、tailの
  先頭に付くaudioだけの区間の分だけ映像が止まる。実測で**2.40秒と2.08秒の穴**、出力も要求より
  2.5秒長かった。tailに `inpoint`/`outpoint` を付けて解決。**headには始点を書かない** —
  書くとそこでseekが起きて先頭のkeyframeが落ちる（実測: 出力の映像がheadを飛ばして接合点から
  始まった）
- **copy経路の関門が甘かった**（copy/reel共通）。窓の始点が先頭keyframeの1µs手前に来た回で
  **152 packetが2 packet**まで落ちたのに「成功」で返っていた。`_missing_streams` が拾うのは
  映像streamが丸ごと消えた場合だけで、次のkeyframeがあると映像は残る。各partの期待位置に
  **keyframeが在るか**を見る関門を足した（時刻だけでは見抜けない。落ちた後も非keyframeの
  packetはその時刻に並ぶ）。併せて `_inpoint_for` が `audio.first` で頭打ちだったのをやめた
  （前置きが1 video frameより短い素材では広げ直しが1段しか効かなかった）

### 狙点は1つでは足りない

`cut_part` は着地が要求より後ろなら**1 GOP手前を狙い直す**（梯子）。合成HLS（keyframeが
0.023/5.023/42.0秒）での実測では `-ss` 0〜0.05が**2つ目**のkeyframeへ着地し、0.5〜4.9が
1つ目へ着地した。「素材の最初のkeyframeなら半分を狙う」という旧規則は、まさに飛ぶ側だった。

### 修正後（実録画・60秒の切り出し）

| 開始位置 | 修正前 | 修正後 |
|---|---|---|
| 2,000秒 | 成功（接合点に穴） | 3.07s / head 1.06s |
| 3,600秒（解像度切替を跨ぐ） | **失敗** | 4.18s / head 29.38s（切替以降で接合） |
| 5,000秒（着地が+2.000秒） | **失敗** | 3.24s / head 2.96s |
| 7,200秒 | 成功（接合点に穴） | 3.03s / head 0.61s |

接合点の穴は4本とも消えた。残る映像の穴は**原本側**に在るもの（media 3,623.09秒の0.27秒など、
ffprobeで確認済み）。IN点は原本のframeへのsweepで1 frame以内に一致（PSNR 47dB、隣は31dB）。

## 10. 長GOPの録画では窓の始点が「全か無か」（修正済み・2026-08-05）

11本の一括切り出しで**2本だけ**が失敗した。どちらも6月の旧録画（keyframe間隔が10〜17.5秒）で、
`_copy_clip` の連結段が `連結後の出力に映像が入りませんでした` / `映像が10.314秒から始まりました`
で落ちた。窓の始点を1 audio packetずつ下げる梯子（3段＝約64ms）が、この素材では届いていなかった。

### 実測（rec16 / 2954.43-2957.43。partは video 2943.920 から、audio 2943.701 から）

| `inpoint` | 出力 video | 出力 audio |
|---|---|---|
| 2943.914663（梯子 back=0） | **0 packet** | 636 |
| 2943.850 / 2943.800（back=1〜3の先） | **0 packet** | 640 |
| 2943.790 以下（〜audio.first、さらに手前も同じ） | 196 packet | **644（1つも落ちない）** |
| 書かない | 196 packet | 644 |

**始点で前置きだけを落とすことはできない。** 映像が入る始点はどれも audio を1 packetも落とさず、
落とせる位置に置くと先頭keyframeを飛び越す。partにGOPが1つしか無ければ映像streamが丸ごと消え、
次のkeyframeがあればそこまで飛ぶ（rec56 は 0.073秒のはずが 10.314秒から始まった）。
別の2範囲（rec56 の 2398.32 / 12521.42）でも同じ形で、閾値は video 先頭の 0.13〜0.17秒手前。

### 直し方

梯子の**下げ切った先を「始点を書かない」**に置いた（`_widened` が file 先頭に達したら `None` へ倒し、
上限まで届かなかった場合も最後に一度だけ始点を外して試す）。残るのは audio の前置きぶんの
A/Vずれ（実測 0.131〜0.219秒）だけで、要求した映像は全て残る。始点を外した回は
`concat.window_start_dropped` に残った秒数を出す（接合点では映像が止まるため黙って通さない）。
下げ切ってなお映像が入らなければ原因は窓ではないので、従来どおり失敗させる。

### 結果（失敗していた3範囲 × copy/precise）

6本とも成功。precise の出力尺は要求どおり（3.00→3.04 / 3.10→3.10 / 3.96→3.98秒）で、先頭frameは
原本の要求時刻のframeと一致（SSIM 0.975。差は av1_nvenc の再encode分）。copy は stream copy 本来の
前置きぶん長い（keyframe間隔17.5秒の素材で lead 10.51秒）。
