# 退避mp4(_backup)と、作り直しの出力先

再mp4化(reprocess)と音量正規化(audionorm)は元mp4を上書きしない。`<root>/_backup/` へ
moveしてから新しいmp4を置き、失敗・取り消し時はそこから戻す(job行へ退避先を**moveの前に**
書くので、その間にprocessが落ちても起動時の `_restore_reprocess_backup` が戻せる)。

## 出力先はmp4の現在地であって.tsの在り処ではない

作り直しは2つのrootに跨がる。読む材料(`seg*.ts`)は録画した1次(work)に残り、成果物である
mp4は完了時に2次(final)へ移送されている。**基準はmp4の現在地**で固定する。

| | 読む先 | 書く先 | 退避先 |
|---|---|---|---|
| 再mp4化 | `.ts` のあるroot | mp4のroot | mp4のroot の `_backup/` |
| 音量正規化 | mp4 | 同じ場所(その場置換) | mp4のroot の `_backup/` |

以前は再mp4化だけが `.ts` 側のrootへ書いていた。2次へ退避済みの録画を作り直すたびに、
新mp4もその退避も1次へ落ちる — つまり**録画中の書き込み先(SSD)を、作り直すたびに
静かに食い潰す**。DBのpathも1次へ書き換わるので、画面上は正常に見えて気付けない。

決め方は `_recording_home_root()`: 実在のmp4(`_current_recording_mp4`) → 行が指していた
root(fileは消えている) → `FINAL_DIR`(完成mp4の既定の置き場)。

`Recorder.finalize_recovered_hls(base, mp4_root=...)` が読む先と書く先の分離を受ける。
live captureが無い経路なので一旦1次へ書いてから移す理由も無く、数十GBを二度書きしない。
確定は移送しないので、segmentは読んだ場所(1次)にそのまま残る。

2次へ在るべき録画が既に1次へ落ちている場合は、`/capacity`(動画容量)の「最終保存先へ移動」で戻す
([RELOCATE_TO_FINAL.md](RELOCATE_TO_FINAL.md))。

## 退避は誰も消さない

retentionにも容量policyにも `_backup/` の削除経路は無い。走らせた分だけ積み上がる
(2026-07-25実測: 1次 122GB + 2次 185GB = 307GB)。容量内訳には「再mp4化の退避(_backup)」
として出るだけで、消すのは `scripts/prune_backup_mp4.py`(dry-runが既定、`--apply`で削除)。

## 掃除の判定に尺を使ってはいけない

退避を消してよいのは「作り直した現行mp4が本当に使える」場合だけである。退避がその録画の
唯一の原本であり得るため、fileの有無では足りない。判定は次を全て満たすもののみ:

1. 退避名から録画のstemが解ける
2. 現行mp4がどちらかのrootに実在し、0byteでない
3. DBの録画行が completed で、実在するmp4を指している
4. 現行mp4にffprobeがvideo streamを見つけられる
5. **現行mp4のvideo frame数**が退避の `1 - tolerance` 以上

5に尺(container duration)を使うと**全滅する**。旧経路(concat demuxer)のmp4は幻の音声穴で
timestampが伸びており、同じ内容を作り直すと尺だけが数%縮む(A/Vズレとプツプツの真因だった
幻の音声穴。結合をhls demuxer+自前VOD playlistへ替えて解消した、あの差分そのもの)。実測:

| | 退避(旧) | 現行(作り直し後) |
|---|---|---|
| container duration | 4151.0秒 | 4000.3秒 |
| video frame数 | 87652 | **87652** |
| audio frame数 | 194574 | 187511 |

内容は1 frameも失われていない。尺で見た初回のdry-runは18件中13件を「短くなった」と
誤判定した。frame数は結合し直し(再mp4化)でも映像stream copy(音量正規化)でも変わらず、
**内容が欠けたときにだけ減る**。

### 実dataでのdry-run(2026-07-25)

| root | 削除可 | 保留 |
|---|---|---|
| 1次 `recordings/` | 18件 121.3GB | 0件 |
| 2次 `K:\80_Tiktok` | 73件 156.8GB | 13件 27.4GB |

保留13件の内訳は、現行mp4が無い5件・**現行mp4にvideo streamが無い2件**・frame数が
明らかに足りない5件(例: 23458 < 266967)・行が実fileを指していない1件。作り直しが壊れた/
途中で切れた録画がこれだけ実在し、その原本は退避にしか無い。frame数で見なければ、
これらを尺の誤判定に紛れさせたまま消していた。
