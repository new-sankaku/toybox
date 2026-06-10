# TicTok — TikTok LIVE Monitor

TikTokLive (Python) を利用して TikTok LIVE の Gift 到着・Comment・Like・Follow などの Event を Backend で収集し、Browser 上の HTML で Realtime に確認できる standalone tool です。

## 構成

```
TicTok/
├── server.py          FastAPI server（HTML配信 / REST API / WebSocket配信）
├── collector.py       TikTokLive client wrapper（Event収集・統計集計・状態管理）
├── config.py          環境変数によるServer設定（host / port / log level / 履歴件数）
├── requirements.txt   依存Package
├── run.bat            Windows用起動script
├── run.sh             Linux/macOS用起動script
└── static/
    ├── index.html     監視画面（NieR:Automata風 sand配色）
    ├── style.css
    ├── app.js
    └── vendor/
        └── chart.umd.min.js   Chart.js v4（graph描画、offline動作のため同梱）
```

## 起動方法

Windows:

```bat
TicTok\run.bat
```

Linux / macOS:

```bash
bash TicTok/run.sh
```

初回実行時に `TicTok/venv` が作成され、依存Packageが install されます。起動後、Browser で `http://127.0.0.1:8520` を開きます。

## 設定（環境変数）

| 変数 | 既定値 | 説明 |
| --- | --- | --- |
| `TICTOK_HOST` | `127.0.0.1` | bind する host |
| `TICTOK_PORT` | `8520` | bind する port |
| `TICTOK_LOG_LEVEL` | `INFO` | log level |
| `TICTOK_EVENT_HISTORY` | `200` | 新規接続時に再送する Event 履歴件数 |
| `TICTOK_BUCKET_SECONDS` | `10` | Timeline 集計の bucket 幅（秒） |
| `TICTOK_TIMELINE_LIMIT` | `2160` | 保持する bucket 数の上限（10秒幅で約6時間） |
| `TICTOK_SIMULATION` | `0` | `1` で simulation mode（擬似 event を生成。LIVE 配信なしで画面確認可能） |
| `TICTOK_RECONNECT_MAX_ATTEMPTS` | `10` | 自動再接続の最大試行回数 |
| `TICTOK_RECONNECT_BASE_DELAY` | `2.0` | 再接続の初回待機秒数（exponential backoff） |
| `TICTOK_RECONNECT_MAX_DELAY` | `60.0` | 再接続待機秒数の上限 |

## 使い方

1. 画面上部の入力欄に TikTok ID（`@` は不要）を入力します。
2. 「収集開始」を押すと、進捗 step（Request受付 → LIVE状態確認 → WebSocket接続 → Data受信中）と spinner が表示されます。
3. 接続後は統計（視聴者数・累計Like・Gift数・Diamonds・Comment数 など）と、Gift / Comment / Event Log の各 feed が Realtime に更新されます。
4. 「停止」で収集を終了します。

対象の User が LIVE 配信中でない場合や ID が存在しない場合は、該当 step が失敗表示になり、Error 内容が画面に表示されます。

## 自動再接続

一時的な障害（Sign API の 502、network 断、予期しない切断など）は error にせず、exponential backoff（2秒 → 4秒 → … 最大60秒）で自動再接続します。

- 再接続中は「RECONNECTING」の控えめな badge と spinner を表示し、収集済み Data・統計・Timeline は保持されます。
- 回復不能な失敗（LIVE 未配信・User 不存在・年齢制限）は再接続せず error 表示します。
- 再接続が `TICTOK_RECONNECT_MAX_ATTEMPTS` 回失敗した場合のみ error として停止します。
- 再接続の成功は Timeline 上に「再接続」marker として記録されます。

## Timeline graph

Chart.js による時系列 graph を表示します（横軸 = 時間、bucket 幅は `TICTOK_BUCKET_SECONDS`）。

- 系列: Gift数 / Diamonds（bar）、同接数 / Comment数 / Like数 / 入室数 / Follow / Share（line）。凡例 click で表示の ON/OFF（filtering）ができます。
- 左軸は件数、右軸は Diamonds と同接数です。
- LIVE 状況の marker（LIVE接続 / Battle / LIVE終了 / 切断）を縦の破線として graph 上に表示します。

## Result 分析

収集中も停止後も「Result 分析」panel で確認できます。

- 合計値: Gift合計 / Diamonds合計 / Gift送信者数 / Comment合計 / Like合計 / Battle回数
- User ごとの Gift: Gift数・Diamonds の ranking と主な Gift
- Gift 種類別: 個数・単価（diamonds）・合計 Diamonds

## Event Log の filtering

Event Log panel 上部の chip（gift / comment / like / follow / share / join / subscribe / battle / system）で表示する Event 種別を切替できます。

## API

| Method | Path | 説明 |
| --- | --- | --- |
| GET | `/` | 監視画面 HTML |
| GET | `/api/status` | 現在の収集状態の snapshot |
| GET | `/api/timeline` | 時系列 bucket（gifts / diamonds / comments / likes / joins / follows / shares / viewers）と marker |
| GET | `/api/summary` | Result 分析（合計値、User ごとの Gift ranking、Gift 種類別 ranking） |
| POST | `/api/start` | `{"unique_id": "..."}` で収集開始 |
| POST | `/api/stop` | 収集停止 |
| WS | `/ws` | state / stats / event の push 配信 |

## 収集 Event

| 種別 | 内容 |
| --- | --- |
| gift | Gift 到着（Streak は確定時に集計、Streak 中は進行表示のみ） |
| comment | Comment |
| like | Like（累計値は LikeEvent の total を反映） |
| follow / share / join / subscribe | 各 user action |
| RoomUserSeq | 視聴者数・累計視聴者数の更新 |
| system | 接続・切断・LIVE 終了の通知 |

## 注意事項

- Gift の Streak（連打）は二重計上を防ぐため、Streak 確定時（`repeat_end`）にのみ Gift 数と Diamonds を加算します。
- TikTok 側の仕様変更により接続できない場合は、`TikTokLive` package の更新を確認してください。
