# 秒の時間軸(media軸 / PTS軸)

## 3つの軸を混ぜない

録画1本の「◯秒地点」には別物の軸が3つある。混ぜると、**ズレが尺に比例して育つ**という
形で静かに壊れる。頭は合っているので気付きにくい。

| 軸 | 何の秒か | 出所 |
|---|---|---|
| 壁時計 (wall) | collectorがeventを受けた時刻(epoch) | `events.time`。録画の時間軸ではない |
| **media軸** | HLS playlistの `#EXTINF` 累積 | `timing.json` の `anchors` / `media_duration`。**.tsを再生するplayerのcurrentTimeはこれ** |
| **PTS軸** | mp4のpresentation timestamp | `timing.json` の `media_pts`(media→PTSの対応)。mp4を再生するplayerのcurrentTimeはこれ |

壁時計は録画の秒ではない。起動latency(実測15.2秒)・再接続の穴・muxのぶんだけずれ続けるので、
`time - started_at` を秒として使ってはいけない。変換は必ず `video_overlay._make_time_mapper`
(wall→media→PTS)を通す。

media軸とPTS軸も別物である。mp4はsegmentごとに一定のmux overheadを載せるため、PTSはmediaより
長く走る(実測で最大21.5秒)。さらにA/Vズレ修復前のconcat demuxerが作ったmp4には**幻の音声穴**が
あり、PTS軸がmedia軸より3〜5%(実測で最大636秒)長い。

## 軸を決めるのは「再生経路」であって、fileの有無ではない

- 素材(.ts)と再生list(`index.m3u8`)が揃っている録画 → **HLSで再生**する → **media軸**
- mp4しか無い録画 → mp4で再生する → **PTS軸**

判定は `layout.has_playable_media` 1箇所に置き、再生経路(`server._recording_media_dirs`)と
検索indexの軸(`indexer.playback_axis`)が同じ事実を見る。片方だけが変わると、秒だけが別の軸に
載った状態になる。

DBへ焼き付ける秒は、すべてこの軸に合わせる:

| 置き場 | 誰が書くか | 合わせ方 |
|---|---|---|
| `search_hits.video_time` (comment) | `indexer.index_comments` | 再生経路の軸で wall から引き直す |
| `search_hits.video_time` (stt) | `indexer.index_transcript` | 文字起こしのsegment時刻をそのまま使う |
| `transcripts.segments_json` | `transcription.transcribe` | **再生に使うのと同じ入力**から復号する |
| `bookmarks` / `cut_list` | ユーザーの操作 | playerの秒がそのまま入る |
| `recordings.time_axis` | 書いた側が名乗る | `media` / `pts`。二重変換の防止に使う |

文字起こしだけは注意が要る。faster-whisperの復号器はframeのPTSを捨てて samples を詰めるので、素の
segment時刻は**gapless軸**(音声が実在するぶんだけの軸)になる。`transcription` はこれを自分で
復号し直して container の時刻へ戻す(`timemap_version` / `timemap_drift_seconds`)。戻す先は
「復号したcontainerの軸」なので、**mp4から文字起こしすればPTS軸、.tsから文字起こしすればmedia軸**になる。
`transcribe_queue` が `prefer_hls=hls_source.plays_from_hls(path)` を渡すのはこのためである。

### 時刻map版(`timemap_version`)

| 版 | 中身 |
|---|---|
| NULL | mapが無かった頃の転写。gapless軸のままで、尺が伸びるほど後ろへズレる |
| 1 | gapless→media軸のanchor map |
| 2 | 1 に加え、源のtimestampが壊れたsegmentが残した**幻のjump**をplaylistの尺で畳む(`_rebase_phantom_jumps`) |

版2を入れた当初は版を据え置いたため、壊れた地図で作られた転写が現行版を名乗ったまま残った
(実測 録画00126: 素材2時間51分に対し転写の終端10時間43分。630.7秒地点の +28,288秒のjumpが
線形補間で残り全体へ引き伸ばされ、字幕clickが録画の外側へ飛ぶ)。

既存の版1は起動時の `timemap_migration` が選別する。物差しは焼き込みの関門と同じ
`video_overlay.material_media_seconds` と `subtitles.axis_matches_media` で、**転写の尺が素材に
収まっていれば畳む対象が無かった**のだから版2へ昇格させ、食い違うものだけ版1のまま据え置いて
「要再転写」を名乗らせる。実尺が測れない録画は昇格させる — 降格は「ズレている証拠がある」ときに
だけ行う。据え置かれた録画は再転写でしか直らない(既存segmentの張り直しは不可能)。

選別を走らせるかどうかは `timemap_migration.SELECTION_VERSION`(db_maintenanceへ刻む)で決める。
据え置いた行は版1のまま残るため、素直に毎起動で走らせると同じ母集合を測り直し続ける。
**選別の根拠(物差し)を変えたらこの値を上げること。**

### 「素材の実尺」は何を測るか

`material_media_seconds` が測るのは、**下流が実際にffmpegへ渡す素材**である
(`hls_source.ffmpeg_source` と同じ順: .ts が在れば採用集合、無ければmp4)。

`timing.json` の `media_duration` も `recordings.duration_seconds` も使わない。どちらも
finalize時のsnapshotで、その後にsession dirが太れば置き去りになる(実測: 捕捉processが
孤児化して書き続けた録画で、録画行 12.0秒 に対し採用集合 16,861.8秒)。逆に素材が消えてmp4
だけが残った録画では、もう存在しない .ts の尺を名乗り続け、mp4から作った正しい転写を
「軸が違う」と弾いていた(実測9件)。

## comment indexをいつ張るか

`search_hits`(comment)を作る経路は3つで、これ以外に自動で張るものは無い。検索hitもplayer下段の
comment panelも `search_hits` しか読まず、`events` を直接は見ないので、ここが抜けた録画は
「commentが1件も無い録画」として見える。

| 契機 | 呼ぶ側 | 対象 |
|---|---|---|
| 録画の確定 | `TikTokCollector._on_recording_finalized` | 確定した1本(`completed` のみ) |
| server起動 | `backfill_search_index`(`startup` の background task) | comment indexがまだ無い録画すべて |
| 手動 | `scripts/repair_search_time_axis.py --apply` | **既に張ってある**indexの軸の張り直し |

確定時に張るのは、起動時のbackfillだけでは**server稼働中に始まって終わった録画が次の再起動まで
空のまま**になるためである(実測 2026-07-29、録画00398/00399: eventは703件・780件揃っているのに
comment 0件)。転写側は STT 完了時に `index_transcript` を呼ぶので、この穴はcommentにしか出ない。

手動scriptは既存hitとのズレを測って判定するため、hitが0件の録画は `no_comments` として素通りする。
**張り直し用であって、張り忘れの回収には使えない**。

event窓は `[started_at, ended_at]` で切る。`ended_at` を持たない録画(crashで中断した行・確定の
途中で落ちた行)は窓の終わりが決まらないので、**同じsessionで次に始まった録画の開始時刻**で閉じる
(`storage.next_recording_start`)。開いたままにすると後続録画のcommentをこの録画のものとして
取り込む。次の録画が無ければ閉じる根拠が無いので開いたままにする — ここで勝手に切ると、session
最後の録画のcommentを落とす。閉じるのは窓だけで、mapperには渡さない(mapperの `ended_at` は
壁時計の窓を実尺へ載せる係数で、別の意味の値を入れると秒そのものが歪む)。

## 障害: 素材の在り方が変わった録画で、秒だけが古い軸に残った

2026-07-24のA/Vズレ修復で `concat_vod.m3u8` と `timing.json` を作り直し、再生をHLS直読みへ
移した。この時点でmedia軸は正しくなったが、**それ以前にDBへ焼き付けた秒は古いmp4のPTS軸の
まま**残った。実測(録画00268、実尺5074.8s):

- comment: 冒頭+0.1秒 → 末尾+133秒(以降は末尾へ潰れる)
- 文字起こし: `duration` が 5265.9s(実尺+191.1s)、末尾で191秒ずれ
- 全体では comment 79件 / 文字起こし 67件 の録画が別の軸に載っていた

`scripts/migrate_time_axis_to_media.py` は救済にならない。変換に使う `media_pts` は**修復後**の
timing.jsonが持つ値(pts≒media、実測で最大0.047秒差)なので実質何も動かさず、しかも
`time_axis='media'` を刻んで再実行を塞ぐ。

### 直し方

```bash
python scripts/repair_search_time_axis.py                       # dry-run
python scripts/repair_search_time_axis.py --apply               # comment indexを張り直す
python scripts/repair_search_time_axis.py --apply --enqueue-transcripts  # 文字起こしも再実行
```

commentは `events` の壁時計から今の軸で引き直せる(anchorsが根拠なので常に現在の軸になる)。
**文字起こしは引き直せない** — 古い軸から今の軸へ戻すmapは、timing.jsonを作り直した時点で失われて
いる。直す手段は文字起こしのやり直しだけで、判定は「文字起こしの `duration` と素材の実尺の差」で行う。bookmarkも
同じ理由で機械的には直せない(検出のみ)。

## 焼き込み(video_overlay)との関係

焼き込みは `prefer_hls=True` で .ts を直接読み、HLS入力のときは `media_pts` に恒等の2点mapを
渡す(`_render_context` の `is_hls` 分岐)。つまり**焼き込んだcommentの位置はmedia軸**で、HLS
再生と一致する。codec(AV1/HEVC/H.264)とCFR化は時間軸を動かさない — 実測で、.tsから焼いた
出力の尺は素材の実尺と+1.4秒(CFRの端数)まで一致する。

ただし**字幕は文字起こしのsegment時刻をそのまま焼く**ので、軸のずれた文字起こしのまま焼けばそのズレが
pixelに焼き付く。字幕ONで焼き直す前に、必ず文字起こしのやり直しを済ませること。

2026-07-22より前に焼いた既存出力は、当時のmp4(古いPTS軸)を入力にしているため尺が実尺より
3〜5%長い。焼き込みのcache signatureは素材の指紋・`timing.json`のmtime・文字起こしの指紋・version
(29)を畳み込むので、焼き直しを掛ければ現在の軸で作り直される。
