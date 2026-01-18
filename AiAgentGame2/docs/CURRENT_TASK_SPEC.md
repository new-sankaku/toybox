# currentTask 詳細化仕様

## 概要

`currentTask` はエージェントが現在実行中の作業を示す文字列フィールドです。フロントエンドでエージェントの状態を視覚的に分かりやすく表示するために、バックエンドから詳細な情報を送る必要があります。

## 現状の問題

現在の `currentTask` は以下のような一般的な文字列のみ：
- `"処理中"`
- `"開始待機"`
- `null` または空文字列

これでは「何をしているか」が分からない。

## 提案する情報構造

### 1. 基本形式

```
[ステップ番号/総ステップ数] アクション: 詳細
```

例：
- `[1/5] 初期化: プロジェクト設定を読み込み中`
- `[2/5] LLM呼び出し: concept.md を生成中`
- `[3/5] ファイル保存: concept.md を保存中`

### 2. アクションカテゴリ

| カテゴリ | 表示例 | 説明 |
|---------|--------|------|
| 初期化 | `初期化: コンテキスト準備中` | エージェント起動時の初期化処理 |
| LLM呼び出し | `LLM呼び出し: キャラクター設計を生成中` | Claude/GPT API への呼び出し |
| LLM応答待ち | `LLM応答待ち: 応答受信中 (1,234トークン)` | API 応答を待機中 |
| ファイル読み込み | `ファイル読み込み: requirements.txt` | ファイルの読み取り |
| ファイル保存 | `ファイル保存: character_specs.md` | ファイルの書き込み |
| 検証 | `検証: 出力形式をチェック中` | 生成結果の検証 |
| 待機 | `待機: 依存エージェント完了待ち` | 他エージェントの完了待ち |
| エラー処理 | `エラー処理: リトライ中 (2/3)` | エラーからの回復処理 |

### 3. WebSocket イベントで送信する情報

`agent:progress` イベントで送信するデータ構造：

```typescript
interface AgentProgressEvent {
  agentId: string
  progress: number          // 0-100 の進捗率
  message: string           // ログメッセージ
  currentTask: string       // 現在のタスク（上記形式）
  currentStep?: number      // 現在のステップ番号
  totalSteps?: number       // 総ステップ数
  action?: string           // アクションカテゴリ
  detail?: string           // 詳細情報
  metadata?: {
    llmTokens?: number      // LLM使用トークン数（呼び出し中の場合）
    fileName?: string       // 操作中のファイル名
    retryCount?: number     // リトライ回数
  }
}
```

### 4. バックエンド実装ガイド

各エージェントは以下のタイミングで `currentTask` を更新：

1. **エージェント開始時**
   ```python
   self.update_task("[1/N] 初期化: エージェント起動中")
   ```

2. **LLM呼び出し前**
   ```python
   self.update_task(f"[{step}/{total}] LLM呼び出し: {target}を生成中")
   ```

3. **LLM応答受信中**
   ```python
   self.update_task(f"[{step}/{total}] LLM応答待ち: 応答受信中 ({tokens}トークン)")
   ```

4. **ファイル操作時**
   ```python
   self.update_task(f"[{step}/{total}] ファイル保存: {filename}")
   ```

5. **完了直前**
   ```python
   self.update_task(f"[{total}/{total}] 完了: 結果を出力中")
   ```

### 5. フロントエンド表示例

AgentCard での表示：

```
Designer [実行中]
├─ [2/5] LLM呼び出し: キャラクター設計を生成中
├─ 進捗: ████████░░ 80%
└─ 42秒  1,234tk
```

### 6. ワークフロー構造

```
Phase 0 (ユーザー入力)
  └─ concept

Phase 1 (企画)
  ├─ scenario_leader → scenario_worker
  └─ task_split_leader → task_split_worker

Phase 2 (開発) - task_split_worker 完了後に並列実行
  ├─ world
  ├─ character
  ├─ design
  ├─ code_leader → code_worker
  └─ asset_leader → asset_worker

Phase 3 (品質) - Phase 2 全完了後
  └─ integrator → tester → reviewer
```

### 7. 各エージェントのステップ例

#### Phase 0: コンセプト (concept)
```
[1/4] 初期化: プロジェクト情報を読み込み中
[2/4] LLM呼び出し: ゲームコンセプトを生成中
[3/4] 検証: 出力形式をチェック中
[4/4] ファイル保存: concept.md を保存中
```

#### Phase 1: シナリオ (scenario_leader → scenario_worker)
```
[1/4] 初期化: コンセプト情報を読み込み中
[2/4] LLM呼び出し: シナリオ構成を生成中
[3/4] 検証: シナリオ整合性をチェック中
[4/4] ファイル保存: scenario.md を保存中
```

#### Phase 2: コードワーカー (code_worker)
```
[1/6] 初期化: コード生成指示を受け取り中
[2/6] LLM呼び出し: コード生成中 (main.ts)
[3/6] ファイル保存: main.ts を保存中
[4/6] LLM呼び出し: コード生成中 (utils.ts)
[5/6] ファイル保存: utils.ts を保存中
[6/6] 完了: 生成ファイル一覧を出力中
```

#### Phase 3: 統合 (integrator)
```
[1/4] 初期化: 成果物を収集中
[2/4] LLM呼び出し: 統合処理を実行中
[3/4] 検証: 統合結果をチェック中
[4/4] ファイル保存: build_result.md を保存中
```

### 8. 実装優先度

1. **必須**: `currentTask` の基本形式（`[ステップ/総数] アクション: 詳細`）
2. **推奨**: `currentStep` と `totalSteps` の分離
3. **オプション**: `metadata` による追加情報

### 9. 既存コードとの互換性

- `currentTask` が空または旧形式の場合、フロントエンドは「処理中」と表示
- 新形式の判定: `currentTask.startsWith('[')` で判定可能
- 段階的に各エージェントを更新可能
