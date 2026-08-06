# Agent階層構造

## 概要

Agentを4層の階層構造で管理する。各層は明確な責務を持ち、上位層が下位層を管理する。

## 階層構造

| 層 | Agent | 数 |
|----|-------|-----|
| 1 | DIRECTOR | Phase毎に1体 |
| 2 | LEADER | 機能単位で1体 |
| 3 | WORKER | Task毎に動的生成 |

## 各層の定義

### DIRECTOR（Director）

| 項目 | 内容 |
|------|------|
| 数 | Phase毎に1体 |
| 役割 | Phase全体の統括 |
| 責務 | Phase内のLEADER管理、Phase完了判定 |
| 管理対象 | 配下のLEADER群 |
| 使用LLM | 思考型ハイパフォーマンス（Opus等） |

**Phase毎のDIRECTOR:**
- Phase1 DIRECTOR: Planning Phase統括
- Phase2 DIRECTOR: Development Phase統括
- Phase3 DIRECTOR: Quality Phase統括
- （将来的にPhaseが増える可能性あり）

**具体的な責務:**
- 配下LEADERへのTask分配
- LEADER間の調整（依存関係の解決）
- Phase完了条件の判定
- 上位層への進捗報告

### LEADER（Leader）

| 項目 | 内容 |
|------|------|
| 数 | 機能単位で1体 |
| 役割 | Team Leader |
| 責務 | WORKERへのTask分解・割当、成果物の統合、Human承認の提出 |
| 管理対象 | 配下のWORKER群 |
| 使用LLM | 思考型ハイパフォーマンス（Opus等） |

**Phase1のLEADER:**
- Concept LEADER: 企画立案
- Design LEADER: Game設計
- Scenario LEADER: Scenario作成
- Character LEADER: Character設計
- World LEADER: 世界観構築
- TaskSplit LEADER: Task分解

**Phase2のLEADER:**
- Code LEADER: Code実装統括
- Asset LEADER: Asset制作統括

**Phase3のLEADER:**
- Integrator LEADER: 統合作業
- Tester LEADER: Test実行
- Reviewer LEADER: Review実施

**具体的な責務:**
- 受け取ったTaskを単一Taskに分解
- WORKERの生成・割当
- WORKER成果物の確認・再指示（最大3回）
- 成果物の統合
- **Human承認の提出**（WebUIへの承認依頼）
- DIRECTORへの完了報告

### WORKER（Worker）

| 項目 | 内容 |
|------|------|
| 数 | Task毎に動的生成 |
| 役割 | 単一Taskの実行者 |
| 責務 | 1Task = 1成果物の生成 |
| 管理対象 | なし（末端） |
| 使用LLM | Haiku（Default）、難度・失敗時に昇格 |

**具体的な責務:**
- 割り当てられた単一Taskの実行
- 成果物の生成
- LEADERへの完了報告
- Error発生時のLEADERへのEscalation

## Human承認Flow

Human承認は**各LEADERが提出**する。

**Flow:**
1. LEADER が成果物を完成
2. WebUI承認画面に提出
3. HumanがReview
4. 承認 → 次のStepへ / 修正指示 → LEADERがWORKERに再指示 / 追加指示 → LEADERが追加Taskを作成

### 承認画面の表示内容

| 表示項目 | 説明 |
|---------|------|
| LEADERの指示内容 | LEADERがWORKERに出した指示 |
| WORKERへの指示 | 個別WORKERへの具体的な指示 |
| 生成物 | WORKERが作成した成果物 |
| 指示履歴 | 修正指示があった場合の履歴 |

### 未承認時の操作

| 操作 | 説明 |
|------|------|
| 指示内容の書き換え | LEADERの指示を編集して再実行 |
| 追加指示 | 既存の指示に追加で指示を付与 |
| 却下 | 作業を中止 |

## 通信Flow

### 下向き（指示）

DIRECTOR → LEADER → WORKER の順で指示が下りる。

### 上向き（報告）

WORKER → LEADER（確認）→ Human承認 → DIRECTOR の順で報告が上がる。

### 再確認処理

LEADER-WORKER間の再確認は無限Loopを避けるため**最大3回**に制限。

1. LEADER → WORKER: 指示
2. WORKER → LEADER: 成果物提出
3. LEADER: 確認 → OK なら完了、NG なら再指示（最大3回まで）
4. 3回NGでもダメならDIRECTORへEscalation

## 既存Fileの統合方針

| 対象 | 作業内容 |
|------|---------|
| AGENT_SYSTEM.md | 階層構造図を更新、DIRECTORの追加 |
| agents/_COMMON.md | AgentRole定義、共通Promptの更新 |
| agents/phase*_*_leader.md | LEADER定義として統一、Human承認提出の責務を追加 |
| agents/phase*_*_workers.md | WORKER定義として統一 |
| agents/directors/ | 新規作成：各Phase DIRECTORの定義 |
