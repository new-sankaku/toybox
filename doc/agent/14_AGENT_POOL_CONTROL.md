# Sub Agent起動数の制御

## 概要

WebUIからWORKERの同時起動数を制御できるようにする。
マシンスペックやコスト制約に応じて、適切な並列度を設定する。

## 制御対象

| Agent種別 | 制御 | 理由 |
|----------|------|------|
| DIRECTOR | 不可 | Phase毎に1体固定 |
| LEADER | 不可 | 機能単位で固定 |
| WORKER | 可能 | 動的に増減 |

## 設定項目（DB管理）

### WORKER設定

| 項目 | 説明 |
|------|------|
| max_total | システム全体の最大WORKER数 |
| max_per_leader | 1 LEADERあたりの最大WORKER数 |
| max_per_phase | 1 Phaseあたりの最大WORKER数 |
| min_total | 最小起動数（常に維持） |

### スケーリング設定

| 項目 | 説明 |
|------|------|
| enabled | スケーリング有効化 |
| scale_up_threshold | スケールアップ閾値（キュー使用率%） |
| scale_down_threshold | スケールダウン閾値（キュー使用率%） |
| cooldown_seconds | スケーリング間隔 |

### リソース制約

| 項目 | 説明 |
|------|------|
| cpu_percent | CPU使用率上限 |
| memory_percent | メモリ使用率上限 |
| api_calls_per_minute | API呼び出し制限 |

## プリセット

| プリセット | max_total | max_per_leader | 推奨環境 |
|-----------|-----------|----------------|---------|
| minimal | 2 | 2 | 低スペックPC（メモリ8GB以下） |
| standard | 5 | 3 | 一般的なPC（メモリ16GB） |
| performance | 10 | 5 | 高スペックPC（メモリ32GB以上） |
| server | 20 | 8 | サーバー環境 |

## WebUI

### 設定画面

| UI要素 | 説明 |
|--------|------|
| プリセット選択 | minimal / standard / performance / server / custom |
| 最大WORKER数スライダー | 全体、LEADERあたり |
| リソース制限スライダー | CPU、メモリ上限 |
| 保存ボタン | 設定を保存 |

### ダッシュボード

| 表示項目 | 説明 |
|---------|------|
| アクティブWORKER | 現在稼働中のWORKER数/上限 |
| 待機タスク | キュー待ちタスク数 |
| CPU使用率 | 現在の使用率 |
| メモリ使用率 | 現在の使用率 |
| WORKER一覧 | 稼働中WORKERのリスト |

## APIエンドポイント

| メソッド | パス | 説明 |
|---------|------|------|
| GET | /agent-pool/config | 現在の設定を取得 |
| PUT | /agent-pool/config | 設定を更新 |
| GET | /agent-pool/stats | 統計情報を取得 |
| GET | /agent-pool/presets | プリセット一覧 |
| POST | /agent-pool/presets/{name}/apply | プリセットを適用 |

## 安全機能

### 緊急停止

全WORKERを即座に停止し、キューをクリアする。

### リソース超過時の自動制限

- 新規WORKERの起動を一時停止
- 通知を送信
- 回復を待って再開
