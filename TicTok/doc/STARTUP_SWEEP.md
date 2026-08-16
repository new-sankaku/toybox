# 起動時sweep

server起動のたびに「まだ作られていない派生物」をqueueへ積む仕組み。実処理は行わず、
**投入だけ**を行う。

## 何を積むか

| 種別 | 積む先 | 上限の設定 | 既定 |
|---|---|---|---|
| ts結合 (`pack`) | media job queue | `pack_sweep_per_start` | 10本/起動 |
| 音声波形 (`waveform`) | media job queue | `waveform_sweep_per_start` | 10本/起動 |
| サムネ (`sprite`) | media job queue | `sprite_sweep_per_start` | 10本/起動 |
| 文字起こし (`transcribe`) | media job queue (kind=stt) | `transcribe_sweep_enabled` | ON・本数無制限 |

文字起こしだけ本数で区切らないのは、GPUを1本ずつ直列に使い、queueが再起動をまたいで残る
ため。全部積んでも同時に走るのは常に1本で、終わらなかったぶんは次の起動でそのまま続く。

上限が無いぶん、待機列は文字起こしのない録画で埋まる。人が録画詳細から1本を頼んだときは、その録画が
既にsweep行として並んでいるのが普通なので、新しい行を足さずその行の順番だけを人の優先度へ
上げる(`media_job_queue.promote`)。二重投入として拒むと「押しても何も始まらない」になり、
順番を上げないと数百本の自動投入の後ろで動かない。

## 何を積まないか

焼き込み・Up出力・再mp4化・音量正規化は入れない。不可逆な成果物を作るか元mp4を差し替える
処理で、人が投げた覚えの無いまま起動のたびに走ってよい理由が無い。sweepに置くのは
**素材を書き換えない / 消えても作り直せる / 無いと人がその場で待たされる** の3つを満たす
種別だけ。

## 候補の選び方

`_startup_sweep_candidates` が録画一覧を**1回だけ**走査して種別ごとに選ぶ。種別ごとに
走査すると、同じ録画のstat・dir一覧を種別の数だけ繰り返すことになる。どの種別もlimit件で
満ちたところで打ち切るので、費用は録画の総数ではなくlimitに比例する。

古い順に見る。新しい録画ほど再生・焼き込みで触られる可能性が高いので、触られにくいものから
片付ける。

共通の除外:

- 録画中 (`status == 'recording'`)
- 直近に書き込みのあった録画 — 判定は種別で違う(下記)
- 前回 `failed` / `skipped` / `cancelled` で終わった録画
  (`media_job_recording_ids_in_states`)

最後のものが要るのは、候補判定が**成果物の実在**だから。失敗した録画は成果物が無いまま
残るので、放っておくと次の起動でまた候補に戻る。音声の無い録画のように結果が変わらないものを
毎回積み直すと、台帳が同じ失敗で埋まる。台帳の行は `prune_media_jobs` で期限切れになるため、
この抑止は永久ではなく保持期間ぶんの猶予になる(環境側の問題なら、期限が来れば戻ってくる)。

### 「直近に書き込みのあった」の判定が種別で違う

| 種別 | 見るもの | 理由 |
|---|---|---|
| ts結合 | session dir内のfileの更新時刻 | 素材そのものを書き換える。捕捉中のffmpegはindex.m3u8を書き続けるので、その最中に束ねると差し替えた直後に上書きされ、消したsegmentを指すplaylistが残る(実際に1本やってしまった) |
| 音声波形・サムネ | 録画の `ended_at` | 素材を**読むだけ**。早すぎた場合に出来るのは指紋の合わないcacheであって壊れた素材ではなく、作り直しは再生画面が要求した時点で生成側が判断する |

猶予の長さはどちらも `pack_sweep_quiet_minutes`(既定15分)。

### 済み判定

`_bulk_classify` と同じ事実を見る(一括生成画面とsweepで「済み」の意味が食い違わないように、
判定は1箇所に置く)。

- ts結合: `hls_pack.is_packed`(束ねたfileの実在だけが根拠。DBに印は持たない)
- 音声波形 / サムネ: `.sidecars/` 内のcache fileの実在

sidecarは録画ごとのdirではなくrecord root直下の単一 `.sidecars/` に集まるので、rootの数だけ
scandirすれば全録画ぶんの実在がmembershipで分かる(`_sidecar_names`)。録画ごとのstatは
数千本規模で効く。

見るのは実在だけで、cacheの指紋(mtime+size)までは照合しない。sweepの仕事は「一度も作られて
いない録画を無くすこと」であって、cacheの鮮度を追いかけることではない。

## 人の投入を待たせない

sweepは人が待っていない自動投入で、起動のたびに数十本積まれる。そのままだとworkerを埋めて
しまうので2段で譲る。

| 何を | どう | 実装 |
|---|---|---|
| 順番 | sweepの行はpriorityを下げる(`SWEEP_JOB_PRIORITY = -10`)ので、待機列に人の投入があれば必ずそちらが先に始まる | `_enqueue_media_job(..., priority=)` |
| 同時実行の本数 | sweepの行は同時に1本まで(既定)。残りのworker枠は人の投入のために空けておく | `media_job_queue.sweep` 列 + `claim_next_pending_media_job(sweep_limit=)` |

本数の上限は `TICTOK_MEDIA_QUEUE_SWEEP_CONCURRENCY`(既定1、0で無制限)。数え方と掴み方を
同じlockの中に置いてあるのは、上限判定と掴みが別呼び出しだと2人のworkerが同時に「まだ空きが
ある」と判断できてしまうため。

sweepが積んだ行かどうかはjob画面へも `sweep: true` として届く。人が投げた覚えの無いjobが
並ぶ理由を画面が名乗れるようにするため。

## 起動時の順序

中断録画の復旧(`_recover_interrupted_recordings_bg`)の**完了を待ってから**積む。復旧は録画を
もう一度確定させる処理で、最後にsession dirごと最終保存先へ移す。復旧の対象はDB上
`interrupted` であって「録画中」ではないため候補の除外を素通りし、束ねと移送が同じsegmentを
奪い合う。詳細は [RELOCATE_TO_FINAL.md](RELOCATE_TO_FINAL.md#確定処理中の録画には誰も触らない)。

## なぜfinalizeでやらないか

finalizeに置くと、そこで落ちたときに誰も再開しない。起動時sweepなら、失敗しても次の起動で
また積まれて自然に収束する。
