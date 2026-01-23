# currentTask 仕様

## 形式

```
[ステップ番号/総ステップ数] アクション: 詳細
```

例: `[2/5] LLM呼び出し: concept.md を生成中`

## アクションカテゴリ

| カテゴリ | 説明 |
|---------|------|
| 初期化 | エージェント起動時の初期化 |
| LLM呼び出し | Claude API への呼び出し |
| LLM応答待ち | API応答待機中 |
| ファイル読み込み | ファイル読み取り |
| ファイル保存 | ファイル書き込み |
| 検証 | 生成結果の検証 |
| 待機 | 他エージェント完了待ち |
| エラー処理 | リトライ中 |

## WebSocket イベント

```typescript
interface AgentProgressEvent {
  agentId: string
  progress: number          // 0-100
  currentTask: string       // [ステップ/総数] アクション: 詳細
  currentStep?: number
  totalSteps?: number
  metadata?: {
    llmTokens?: number
    fileName?: string
    retryCount?: number
  }
}
```

## ワークフロー

```
Phase 0: concept
Phase 1: scenario_leader → task_split_leader
Phase 2: world, character, design, code_leader, asset_leader (並列)
Phase 3: integrator → tester → reviewer
```

## 各エージェントのステップ例

```
[1/4] 初期化: プロジェクト情報を読み込み中
[2/4] LLM呼び出し: コンテンツを生成中
[3/4] 検証: 出力形式をチェック中
[4/4] ファイル保存: result.md を保存中
```

## 互換性

- `currentTask` が空/旧形式 → フロントエンドは「処理中」と表示
- 新形式判定: `currentTask.startsWith('[')` で判定
