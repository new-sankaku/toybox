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
    └── app.js
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

## 使い方

1. 画面上部の入力欄に TikTok ID（`@` は不要）を入力します。
2. 「収集開始」を押すと、進捗 step（Request受付 → LIVE状態確認 → WebSocket接続 → Data受信中）と spinner が表示されます。
3. 接続後は統計（視聴者数・累計Like・Gift数・Diamonds・Comment数 など）と、Gift / Comment / Event Log の各 feed が Realtime に更新されます。
4. 「停止」で収集を終了します。

対象の User が LIVE 配信中でない場合や ID が存在しない場合は、該当 step が失敗表示になり、Error 内容が画面に表示されます。

## API

| Method | Path | 説明 |
| --- | --- | --- |
| GET | `/` | 監視画面 HTML |
| GET | `/api/status` | 現在の収集状態の snapshot |
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
