# TicTok — TikTok LIVE Monitor

TikTokLive (Python) を利用して TikTok LIVE の Gift 到着・Comment・Like・Follow などの Event を Backend で収集し、Browser 上の HTML で Realtime に確認できる standalone tool です。複数配信者の同時監視、SQLite への自動保存、Session 履歴と総合 dashboard に対応しています。

## 構成

```
TicTok/
├── server.py          FastAPI server（HTML配信 / REST API / WebSocket配信）
├── manager.py         複数Collectorの管理（配信者ごとに1 instance）
├── collector.py       TikTokLive client wrapper（Event収集・統計集計・自動再接続）
├── storage.py         SQLite保存層（WAL mode、Session/Event/Timeline/Memo）
├── config.py          環境変数によるServer設定
├── requirements.txt   依存Package
├── run.bat            Windows用起動script
├── run.sh             Linux/macOS用起動script
└── static/
    ├── index.html     監視page（tab切替で配信者ごとの詳細dashboard）
    ├── overview.html  全体監視page（監視中の全配信者をcard一覧）
    ├── history.html   履歴page（総合dashboard / Session履歴 / Memo / Session詳細）
    ├── common.js      共通utility（chart factory・WebSocket・整形）
    ├── app.js / overview.js / history.js
    ├── style.css      NieR:Automata風 sand配色
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
| `TICTOK_DB_PATH` | `TicTok/tictok.db` | SQLite database の path |
| `TICTOK_EVENT_HISTORY` | `200` | 新規接続時に再送する Event 履歴件数 |
| `TICTOK_BUCKET_SECONDS` | `10` | Timeline 集計の bucket 幅（秒） |
| `TICTOK_TIMELINE_LIMIT` | `2160` | memory 上に保持する bucket 数の上限 |
| `TICTOK_SESSION_LIST_LIMIT` | `100` | 履歴一覧の表示件数 |
| `TICTOK_SIMULATION` | `0` | `1` で simulation mode（擬似 event を生成。LIVE 配信なしで画面確認可能） |
| `TICTOK_RECONNECT_MAX_ATTEMPTS` | `10` | 自動再接続の最大試行回数 |
| `TICTOK_RECONNECT_BASE_DELAY` | `2.0` | 再接続の初回待機秒数（exponential backoff） |
| `TICTOK_RECONNECT_MAX_DELAY` | `60.0` | 再接続待機秒数の上限 |

## Page 構成

### 監視 page（`/`）

- TikTok ID を入力して「監視開始」で監視対象を追加します。**複数の配信者を同時に監視**でき、tab で切替えます。
- 配信者ごとに、状態 badge・進捗 step・spinner、統計（視聴者数・Gift数・Diamonds・**分間 rate 指標**（Gift/分・Diamonds/分・Comment/分・Like/分）など）、Timeline graph、Result 分析、Gift / Comment / Event Log の feed を表示します。
- 「停止」「再開」「監視解除」を tab ごとに操作できます。監視解除しても収集済み Session は履歴に残ります。

### 全体監視 page（`/overview`）

監視中の全配信者を 1 画面の card 一覧で表示します。card には状態・視聴者数・Gift数・Diamonds・分間 rate・接続時間・直近の Gift / Comment が realtime 表示され、click で該当配信者の詳細 tab に移動します。

### 履歴 page（`/history`）

- **総合 Dashboard（全 Session）**: 総 Gift 数・総 Diamonds・総 Comment・総収集時間、直近 Session ごとの推移 graph、配信者別の累計、全 Session を通じた上位 Gift 送信 User。
- **Session 履歴**: 過去の収集を一覧表示。各 Session に対して「表示」「CSV」「JSON」「削除」を操作できます（削除は確認 dialog あり、収集中の Session は削除不可）。
- **Memo 機能**: Session ごとに自由記述の Memo を保存できます。
- **Session 詳細**: 選択した Session の Timeline graph・Result 分析（User ごとの Gift / Gift 種類別）を表示します。

## 自動保存（SQLite）

- Event は受信のたびに SQLite へ書き込まれ、Timeline と統計は Session 終了時に確定保存されます。Server を再起動しても収集 Data は失われません。
- 異常終了（強制終了など）で残った「収集中」Session は、次回起動時に events から統計を再構築して回復します。
- DB は WAL mode + busy_timeout で運用します。

## Timeline graph

Chart.js による時系列 graph を表示します（横軸 = 時間、bucket 幅は `TICTOK_BUCKET_SECONDS`）。

- 系列: Gift数 / Diamonds（bar）、同接数 / Comment数 / Like数 / 入室数 / Follow / Share（line）。凡例 click で表示の ON/OFF（filtering）ができます。
- LIVE 状況の marker（LIVE接続 / 再接続 / Battle / LIVE終了 / 切断）を縦の破線として graph 上に表示します。

## 自動再接続

一時的な障害（Sign API の 502、network 断、予期しない切断など）は error にせず、exponential backoff で自動再接続します。再接続中は控えめな RECONNECTING badge を表示し、収集済み Data は保持されます。回復不能な失敗（LIVE 未配信・User 不存在・年齢制限）は再接続せず error 表示します。

## API

| Method | Path | 説明 |
| --- | --- | --- |
| GET | `/` `/overview` `/history` | 各 page の HTML |
| GET | `/api/monitors` | 監視中の全 collector の snapshot |
| POST | `/api/monitors` | `{"unique_id": "..."}` で監視開始（既存 ID は再開） |
| POST | `/api/monitors/{unique_id}/stop` | 収集停止 |
| DELETE | `/api/monitors/{unique_id}` | 監視対象から削除（Session は履歴に残る） |
| GET | `/api/monitors/{unique_id}/timeline` | 収集中の時系列 bucket と marker |
| GET | `/api/monitors/{unique_id}/summary` | 収集中の Result 分析 |
| GET | `/api/sessions` | Session 履歴一覧 |
| GET | `/api/sessions/{id}` | Session 詳細（統計・Timeline・分析・Memo） |
| PATCH | `/api/sessions/{id}` | `{"note": "..."}` で Memo 保存 |
| DELETE | `/api/sessions/{id}` | Session 削除（収集中は 409） |
| GET | `/api/sessions/{id}/export.csv` | Event の CSV export（BOM 付き UTF-8） |
| GET | `/api/sessions/{id}/export.json` | Session 全体の JSON export |
| GET | `/api/dashboard` | 総合 dashboard（全 Session 集計） |
| WS | `/ws` | monitors / state / stats / event の push 配信（`monitor` field で配信者を識別） |

## 収集 Event

| 種別 | 内容 |
| --- | --- |
| gift | Gift 到着（Streak は確定時に集計、Streak 中は進行表示のみ） |
| comment | Comment |
| like | Like（累計値は LikeEvent の total を反映） |
| follow / share / join / subscribe | 各 user action |
| battle | LinkMicBattle（Battle 検出、Timeline に marker 表示） |
| RoomUserSeq | 視聴者数・累計視聴者数の更新 |
| system | 接続・再接続・切断・LIVE 終了の通知 |

## 注意事項

- Gift の Streak（連打）は二重計上を防ぐため、Streak 確定時（`repeat_end`）にのみ Gift 数と Diamonds を加算します。
- 分間 rate 指標は直近 60 秒の bucket 集計から算出します。
- TikTok 側の仕様変更により接続できない場合は、`TikTokLive` package の更新を確認してください。
