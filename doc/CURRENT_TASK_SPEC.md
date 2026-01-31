# currentTask 詳細化仕様

## 概要

`currentTask`はエージェントが現在実行中の作業を示すフィールド。フロントエンドで状態を視覚的に表示するため、バックエンドから詳細情報を送信する。

## 基本形式

```
[ステップ番号/総ステップ数] アクション: 詳細
```

例: `[2/5] LLM呼び出し: concept.md を生成中`

## アクションカテゴリ

| カテゴリ | 表示例 |
|---------|--------|
| 初期化 | `初期化: コンテキスト準備中` |
| LLM呼び出し | `LLM呼び出し: キャラクター設計を生成中` |
| LLM応答待ち | `LLM応答待ち: 応答受信中 (1,234トークン)` |
| ファイル読み込み | `ファイル読み込み: requirements.txt` |
| ファイル保存 | `ファイル保存: character_specs.md` |
| 検証 | `検証: 出力形式をチェック中` |
| 待機 | `待機: 依存エージェント完了待ち` |
| エラー処理 | `エラー処理: リトライ中 (2/3)` |

## agent:progress イベントデータ

| フィールド | 説明 |
|-----------|------|
| agentId | エージェントID |
| progress | 0-100の進捗率 |
| currentTask | 現在のタスク（上記形式） |
| currentStep | 現在のステップ番号 |
| totalSteps | 総ステップ数 |
| action | アクションカテゴリ |
| detail | 詳細情報 |
| metadata | llmTokens, fileName, retryCount等 |

## ワークフロー構造

Phase 0: concept → Phase 1: scenario_leader/worker, task_split_leader/worker → Phase 2（並列）: world, character, design, code_leader/worker, asset_leader/worker → Phase 3: integrator → tester → reviewer

## 各エージェントのステップ例

| Phase | エージェント | ステップ例 |
|-------|-------------|-----------|
| 0 | concept | 初期化→LLM呼び出し→検証→ファイル保存 |
| 1 | scenario | 初期化→LLM呼び出し→検証→ファイル保存 |
| 2 | code_worker | 初期化→LLM呼び出し→ファイル保存（繰り返し）→完了 |
| 3 | integrator | 初期化→LLM呼び出し→検証→ファイル保存 |

## 実装優先度

1. **必須**: `[ステップ/総数] アクション: 詳細` の基本形式
2. **推奨**: `currentStep`と`totalSteps`の分離
3. **オプション**: `metadata`による追加情報

## 互換性

- 旧形式（空または「処理中」）の場合、フロントエンドは「処理中」と表示
- 新形式判定: `currentTask.startsWith('[')` で可能
