# Agentの並列化処理

## 概要

依存関係のないタスクを複数のWORKERで同時に実行し、全体の処理時間を短縮する。
ただし、リソース制約とコンフリクト回避を考慮する。

## 並列化の条件

### 並列実行可能な条件

| 条件 | 説明 |
|------|------|
| 依存関係がない | タスクAの完了がタスクBの開始に必要でない |
| 同一ファイルを編集しない | ファイルロックで競合しない |
| 共有リソースを使わない | API rate limit等の制約がない |

### 並列実行不可の条件

| 条件 | 例 |
|------|-----|
| 順序依存 | 「基底クラス作成」→「派生クラス作成」 |
| ファイル競合 | 同じファイルを2つのWORKERが編集 |
| リソース競合 | 同じAPIを同時に大量呼び出し |

## 依存関係グラフ

タスクには以下の情報を持たせる:
- task_id: タスクID
- depends_on: 依存するタスクIDのリスト
- modifies_files: 変更するファイル

依存タスクがすべて完了しているタスクを「実行可能」として並列実行する。

## 並列度の設定（DB管理）

| 設定項目 | 説明 |
|---------|------|
| max_workers_total | システム全体の最大WORKER数 |
| max_workers_per_leader | 1 LEADERあたりの最大WORKER数 |
| max_workers_per_phase | 1 Phaseあたりの最大WORKER数 |
| cpu_limit_percent | CPU使用率上限 |
| memory_limit_percent | メモリ使用率上限 |
| api_calls_per_minute | API呼び出し制限 |

## ファイルロック機構

### ロックの種類

| 種類 | 説明 | 用途 |
|------|------|------|
| 排他ロック | 1つのWORKERのみ | 書き込み |
| 共有ロック | 複数のWORKERが可能 | 読み取り |

### ロック管理

1. タスク開始前にファイルロックを取得
2. ロック取得失敗 → キューで待機
3. タスク完了後にロックを解放

## API Rate Limit対策

- 共有のレートリミッターを使用
- 上限に達したら待機
- 呼び出し記録を保持

## 監視メトリクス

| メトリクス | 説明 |
|-----------|------|
| active_workers | 現在稼働中のWORKER数 |
| parallel_efficiency | 並列実行効率（実際/理論最大） |
| lock_contention | ロック競合回数 |
| queue_depth | 待機中タスク数 |
| avg_wait_time | 平均待機時間 |

## Phase別の並列化

### Phase1（企画）

- Character と World は並列可能
- TaskSplit は他すべての完了後

### Phase2（開発）

- Code LEADER と Asset LEADER は完全並列
- 各LEADER配下のWORKERも依存関係なければ並列

### Phase3（品質）

- 基本的に順次実行
- Testerの一部テストは並列可能
