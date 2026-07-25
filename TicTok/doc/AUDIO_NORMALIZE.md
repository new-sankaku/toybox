# 音量正規化

配信ごと・場面ごとの音量差を、EBU R128 の目標値へ揃える。実装は
`tictok/record/audio_norm.py` 1箇所で、切り出し・焼き込み出力・Up出力・**録画本体の音量正規化**・
**再mp4化**が同じ引数生成を通る。目標は I(統合ラウドネス)と TP(true peak)の2値だけで、
preset tableのような機構は置かない。

| 設定 | 既定 | 効く先 |
| --- | --- | --- |
| `audio_normalize_lufs` | -14.0 | 全経路共通の目標ラウドネス |
| `audio_normalize_true_peak` | -1.5 | 全経路共通の上限ピーク |
| `audio_normalize_bitrate_kbps` | 192 | 再encode(AAC)の品質 |
| `clip_normalize_audio` | 0 | 切り出しの既定(画面で毎回変更可) |
| `video_output_normalize_audio` | 0 | 焼き込み出力・Up出力 |
| `reprocess_normalize_audio` | 1 | 再mp4化のついでに録画本体も揃える |

## 方式: one-pass loudnorm 単体

実録画(3時間07分の配信のうち 01:12:00〜01:30:00 の18分。前半は静かな一人喋り、後半に
battleが2本入り相手の声が同じmixに乗る区間)で4方式を実測した結果:

| 方式 | 統合音量 | 短期音量の広がり(p90-p10) | LRA | True Peak | 処理時間 |
| --- | --- | --- | --- | --- | --- |
| 無加工 | -11.6 LUFS | 26.0 LU | 22.6 | **+1.3 dBFS(clip)** | — |
| **loudnorm単体** | -12.8 | **7.7** | 8.2 | -1.3 | 70.8s |
| speechnorm + loudnorm | -13.0 | 8.6 | 9.1 | -1.4 | 90.5s |
| dynaudnorm + loudnorm | -12.8 | 8.0 | 8.5 | -1.3 | 55.6s |
| loudnorm 2-pass(linear) | -13.7 | 25.4 | 20.4 | -1.3 | 89.8s |

判断:

- **one-pass loudnormが最良**。ffmpegのloudnormは1 passでは3秒先読みの動的normalizerとして
  働き、冒頭の -33.5 LUFS を -15.4 まで(18dB)持ち上げつつbattle区間は下げる。「loudnormは
  全体を一定gainするだけで場面差は縮まらない」という直感は、one-pass実装には当てはまらない。
- **speechnorm・dynaudnormの併用は採らない**。実測で単体より広がりが大きく、処理時間だけ増える。
- **2-passは採らない**。`linear=true` は一定gainなので統合値は目標へ正確に当たる代わりに、
  1本の中の落差がそのまま残る(広がり25.4 LU = ほぼ無加工)。file間の平均を厳密に揃えたい
  ときの手法であって、1本の中の聞き取りやすさを揃える用途には使えない。
- 元音声はTrue Peakが 0 dBFS を超えていることがある(実測 +1.3)。正規化はこのclipも同時に直す。

速度は実測15〜19倍速。3時間の録画1本で約12分。

## 話者ごとに揃えることはできるか

できない。録画の音声はTikTok側で既にmixされた1本のtrackで、配信者・コラボ相手・BGM・gift SEが
同じstereoに入っている。話者ごとに個別のgainを当てるには話者分離(diarization)が要り、BGMや
歓声が被る配信音源では境界を誤りやすい。上表のとおり、one-pass loudnormが**時間軸で**音量を
均すため、「相手の声だけ小さい」の実用的な解決にはそれで足りる。

## 経路ごとの違い

| 経路 | 入力 | 映像 | 出力先 |
| --- | --- | --- | --- |
| 切り出し(clip) | 完成mp4 | stream copy | clips/ の新規file |
| 焼き込み・Up出力 | 完成mp4 | 再encode | `.overlay.mp4` / `.up.mp4` |
| 音量正規化(`audionorm`) | 完成mp4 | **stream copy** | 元mp4を差し替え(元は `_backup/`) |
| 再mp4化(`reprocess`) | 保持HLS(.ts) | stream copy | 元mp4を差し替え(元は `_backup/`) |

- 音量正規化は映像をstream copyするので、画質も、焼き込みが突き合わせるtimestampも動かない
  (コメントのズレを持ち込まない)。
- 再mp4化は結合passがもともと音声をAACへ再encodeしているため、正規化を足しても**追加passは
  発生しない**。ただしHLS結合の音声filterは `aresample=async=1:first_pts=0` を前段に置くこと。
  live .tsの開始PTSは任意の値で、先頭を0へ寄せないと音声だけ別の原点で始まる。
- 完成mp4を入力に取る経路は `aresample=async=1`(first_ptsなし)。録画はHLS由来のVFRで、
  aresampleを挟まずに音声だけ再encodeすると映像との同期が崩れる。
- loudnormは入力に関わらず192kHzを出すため、**sourceの実rateを測って `-ar` で戻す**。
  指定しないと後段のaac encoderが96kHzを選び、音質は変わらないまま音声dataだけが約2倍になる。

## 差し替えの安全性

元mp4を差し替える2経路(音量正規化・再mp4化)は、同じ手順を踏む。

1. 出力を temp (`<name>.mp4.audionorm.tmp` / finalize経路のtemp) へ書く
2. 退避先(`<record root>/_backup/`)を **moveの前に** job行の `result` へ書く
3. 元mp4を退避 → tempを元のpathへ
4. 失敗・取り消しなら退避を戻す

2を省くと、moveの直後にprocessが落ちたとき退避先を知る手段が無くなり、録画がfileの無い状態で
残る。起動時の `_restore_reprocess_backup()` がこの `result` を読んで戻す。

## 状態の記録

`recordings.audio_normalized_at` / `audio_normalized_lufs` に適用時刻と目標値を書く。一括画面の
「処理済」判定はこの列だけを見る(全録画ぶんffprobeを回すのは非現実的で、そもそもloudnormは
mp4に痕跡を残さないのでfileからは判別できない)。再mp4化は中身を作り直すので、正規化せずに
作り直したときは必ずNULLへ戻す — 残すと素の音量の録画が対象から外れる。
