# 容量予測と定期健全性report

drive空き・録画量・DB行数を定期的に記録して時系列化し、増加速度から満杯までを見積もる。
画面は動画容量(`/capacity`)、APIは `GET /api/capacity` と
`POST /api/capacity/sample`。

## なぜ新しい表が要ったか

既存の `storage_scan` は `id INTEGER PRIMARY KEY CHECK (id = 1)` の**1行固定cache**で、
`save_storage_scan` が毎回全置換する。最新の内訳を持つのが役割で、**増減の履歴が原理的に
残らない**ため予測が出せない。

そこで**追記専用の `capacity_samples` を別表として足した**。`storage_scan` には一切触れて
いない(既存の `get_storage_scan` はそのまま動く)。1日1回なら年365行にしかならない。

## sampleはfilesystemを走査しない

`/api/storage/scan` は数TB規模で分単位かかる。日次でこれを回すのは論外なので、
snapshotは**走査を伴わないものだけ**で構成する。

| 項目 | 取得元 | 実測 |
|---|---|---|
| drive空き/容量 | `shutil.disk_usage` | O(1) |
| DB本体 / WAL / SHM | `Storage.db_file_bytes()` | 0ms |
| backups/ 合計 | DB backup先の直下のみ(数十file) | 0ms |
| 録画の本数・bytes | `recordings` 表 | 12ms |
| 各表の行数 | `COUNT(*)` | 0〜21ms |
| 完了率の母数 | `recordings` × `transcripts` / job queue | 1ms |

**合計 約48ms**。録画bytesはfilesystemを見なくても `recordings.bytes` に入っている。

`db_file_bytes()` は env(`TICTOK_DB_PATH`)を読み直さず**実際に開いているpath**を見る。
envは後から変わり得るので、読み直すと「いま計測しているDB」と別のfileを測ることになる
(testで実際に踏んだ)。

## 予測: 線形回帰 + 必ず区間 + 外挿の上限

`tictok/core/capacity.py`(純関数のみ。I/Oも設定読みも持たないので作法をtestで固定できる)。

容量の増減は「録画した分だけ減る」というほぼ線形の現象で、観測が数十点しかない段階で
非線形modelを当てても当てはまりが良くなるのは過去だけである。最小二乗の直線1本で足りる。

**ただし点推定を単独で出さない。** `forecast_days_to_full` が返す `status`:

| status | 意味 | 数値 |
|---|---|---|
| `insufficient_data` | 点が足りない/時間幅がない | 出さない |
| `not_shrinking` | 傾きが0以上(減っていない) | 出さない |
| `inconclusive` | 傾きの95%区間が0をまたぐ | 出さない |
| `beyond_horizon` | 予測が観測期間の N 倍より先 | 出さない(「少なくとも○日先」だけ) |
| `ok` | 上記以外 | `days_low` 〜 `days_high` |

区間は**傾きの95%信頼区間**を日数へ写したもの。傾きが急なほど早く尽きるので、傾きの
下限・上限と日数の上限・下限が入れ替わる。t分位点は df=1..30 を表で持つ(点が少ないとき
正規近似1.96では区間が実態より狭くなり、細い幅で言い切ってしまう)。

**外挿の上限が本質。** 観測7日で「あと1000日」と出るのは算術としては正しいが、
7日ぶんの観測がその先を保証していない。`max_extrapolation`(既定3.0)倍を超えたら
数値を伏せ、「少なくとも観測期間×3先までは持つ」という観測から言える形だけを返す。

閾値判定は**区間の下限**(最も早く尽きる側)で行う。点推定で判定すると、下限が既に閾値を
割っていても黙ることになる。

## 録画の増加実績は遡って出せる

drive空きの履歴は今から貯めるしかないが、**録画の日次増加は最初から `recordings` に
入っている**(`started_at` + `bytes`)。実測で**34日ぶん・285本・183.2GB**が即座に出た。

この2つは**由来が違うので画面でも系列を分けている**。sample由来の実測系列と、DBから
再構成した系列を同じ折れ線に混ぜると、観測していない期間を観測したことにしてしまう。

## 通知は既存経路に乗せる

閾値割れは `storage.record_ops_event(kind="capacity.forecast_low", severity=warning)` を
書くだけ。ops_eventsは `storage.set_ops_observer(notifier.on_ops_event)` 経由で既存の
通知rule(`notify_rule_ops`)がそのまま拾うので、**新しい通知経路もruleも作っていない**。

## 実dataでの結果(2026-07-20時点)

- 録画の増加: 直近14日平均 **8.69 GB/日**
- `C:` 空き **65.8GB** / 1905.6GB → このペースなら**約7.6日で満杯**
- `K:` 空き 5366.9GB / 7452.0GB
- DB 506MB(WAL 19MB)、backups 0.49GB
- 文字起こし完了率 **58.2%**(163/280)、焼き込み完了率 **1.8%**(5/280)

観測sampleが3件未満の間は、上の「7.6日」も画面には出ない(`insufficient_data`)。
出るのはsampleが貯まってからである。

## 設定(team-lead管理の `SETTING_DEFS` へ追加が必要)

| key | 既定 | 用途 |
|---|---|---|
| `capacity_sample_interval_hours` | 24 | snapshotを採る間隔 |
| `capacity_forecast_min_samples` | 3 | 予測に必要な最小sample数 |
| `capacity_forecast_max_extrapolation` | 3.0 | 観測期間の何倍先まで数値を出すか |
| `capacity_alert_days` | 14 | 満杯までの区間下限がこれを割ったらops_eventを出す |

`CAPACITY_HISTORY_LIMIT`(400)と `CAPACITY_SAMPLER_TICK_SECONDS`(900)は policy ではなく
描画量と確認粒度なので、設定にせず `server.py` の定数にしてある。
