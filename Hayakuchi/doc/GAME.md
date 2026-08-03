# Game Runtime

配信者PC上で完結する構成。外部Serviceへは接続しない。
Platform APIも使用しないため、Twitch/YouTube/TikTokのいずれでも同じ動作になる。

## 構成

```
[Mic] ──> Python Service (Local)
            ├ 音声取得        audio_source.py
            ├ 発話端点検出    vad.py
            ├ 逐次認識        engines/hf_ctc.py（別Threadで実行）
            ├ 逐次判定        realtime.py
            └ FastAPI + WebSocket   server/app.py
                 ├──> /overlay.html  OBS Browser Source（透過）
                 └──> /              配信者用操作画面
```

音声は配信Streamからではなく**Mic入力から直接**取得する。Platformの配信遅延が
判定経路に乗らないため、配信者の声とOverlayの表示はListener側でも同期する。

## 起動

```bash
cd backend
.venv/bin/python scripts/run_game.py
```

OBSに `http://127.0.0.1:8790/overlay.html` をBrowser Sourceとして追加する。
背景は透過しているためChroma keyもWindow captureも不要。
操作画面は `http://127.0.0.1:8790/` をBrowserで開く。

Micが無い環境では、WAVを実時間で流して同じ経路を検証できる。

```bash
.venv/bin/python scripts/run_game.py --source-file data/probe/sample.wav --loop
```

## 実装上の要点

### 推論をFrame取り込みと直列にしない

推論は数百msかかる。これをFrame取り込みと同じ流れで待つと、取り込み速度が
推論速度に律速され、音声が実時間から遅れ続ける。別Taskへ逃がし、
実行中は次の推論を発行しない（`_schedule_progress`）。

### 経過時間は音声長から算出する

壁時計ではなく取り込んだSample数から算出する。壁時計を使うと、負荷で
取り込みが遅れた際にまだ発話中の句を打ち切ってしまう。

### 先端付近の誤り表示を保留する

発話途中のMoraは音声が届き切っていないため一時的に誤りへ倒れる。
先端から `error_margin_mora` 個は誤り表示を保留し、Overlayの点滅を防ぐ。
確定判定は発話終了後に別途行うため、最終結果には影響しない。

### 結果表示後は同じ句のまま待機へ戻す

`result_hold_ms` 経過後にREADYへ戻る。戻さないと2回目の挑戦ができない。
句の変更は操作画面から行う。

## 誤判定への対処

判定を誤ってFAILにすると配信が止まる。Platform APIを使わない方針のため
Chat投票は使えず、Local完結で以下を用意している。

- 崩れたMoraの可視化（Overlay上で赤表示）
- 何拍目で崩れたかの表示
- 操作画面からの手動判定変更（Overlayへ即時反映、変更済みである旨も表示）

## 設定

`config/game.yaml` に集約する。Model ID、Thread数、閾値、VADのParameterを含む。

| 項目 | 既定値 | 根拠 |
|---|---|---|
| `engine.params.num_threads` | 2 | 実測で2 Threadで頭打ち。残りをOBSと本命Gameへ譲る |
| `inference_interval_ms` | 300 | Mora点灯の更新間隔 |
| `error_margin_mora` | 2 | 先端付近の誤り表示保留 |
| `result_hold_ms` | 6000 | 結果表示から待機へ戻るまで |
| `pass_accuracy` | 0.9 | 暫定。実収録のBenchmark後に確定させる |
