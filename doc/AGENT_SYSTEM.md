# LangGraph ゲーム開発システム - Agentシステム設計

## 用語定義

| 用語 | 定義 |
|------|------|
| Agent | LangGraph上の1ノード。単一タスクを実行するLLMベースの処理単位 |
| Leader | 配下のAgentを統括し、タスク分配・進捗管理を行う上位Agent |
| Checkpoint | Human承認を待つ中断ポイント。`interrupt()`で実装 |
| State | グラフ全体で共有されるデータ。各Agentが読み書き |

## システムフロー

```
Phase1: 企画
Concept → Design → Scenario → Character → World → TaskSplit
    ↓↑       ↓↑        ↓↑          ↓↑         ↓↑         ↓↑
        [～～～ 人間による承認とフィードバック ～～～]

Phase2: 開発
CodeLeader → AssetLeader → CodeAgents → AssetAgents → Integrator
     ↓↑           ↓↑            ↓↑            ↓↑            ↓↑
        [～～～ 人間による承認とフィードバック ～～～]

Phase3: 品質
Test → Review → [Release | Phase2へ戻る]
 ↓↑       ↓↑
  [人間による承認]
```

Human介入は全13箇所。各ポイントで「承認」「修正指示」「却下」を選択可。

## Agent一覧

### Phase1: 企画（6 Agent）

Concept, Design, Scenario, Character, World, TaskSplit

### Phase2: 開発（2 Leader + 動的Agent）

| Agent | 種別 |
|-------|------|
| CodeLeader | Leader |
| AssetLeader | Leader |
| CodeAgents | 動的生成 (GameLoop, State, UI等) |
| AssetAgents | 動的生成 (Image, Audio等) |

### Phase3: 品質（3 Agent）

Integrator, Tester, Reviewer

## Human連携フロー

Leader → Agent → (サブタスク割当・実行・結果返却) → Leader → Human → (承認/修正指示ループ) → 次のステップ

## 状態スキーマ (GameDevState)

| フィールド | 説明 |
|-----------|------|
| _schema_version | スキーマバージョン |
| current_phase | planning / development / quality |
| current_iteration | イテレーション番号 |
| concept, design, scenario, characters, world | 企画出力 |
| iterations | イテレーション管理 |
| code_outputs, asset_outputs | 開発出力 (task_id → content) |
| asset_code_dependencies | Asset-Code間依存関係 |
| test_results, review_comments | 品質出力 |
| pending_approval, human_feedback | Human連携 |
| error_log | エラーログ |

## Asset-Code間の依存関係

CodeLeader → AssetLeader (アセット要求) → AssetAgent (生成) → AssetLeader → CodeLeader (納品通知) → CodeAgent (実装)

依存状態: waiting → ready → integrated

## WebUI連携

**関連ドキュメント:** WEBUI_DESIGN.md, WEBUI_ARCHITECTURE.md

### WebSocket Events

| Event | Direction | 説明 |
|-------|-----------|------|
| agent:started/progress/completed/failed/log | S→C | Agent状態 |
| checkpoint:created/resolved | S→C | Human承認 |
