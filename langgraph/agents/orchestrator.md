# Orchestrator Agent（オーケストレーター）

## 概要

| 項目 | 内容 |
|-----|------|
| **役割** | 全体統括・フェーズ管理・Human連携 |
| **種別** | 最上位Agent（グラフのエントリーポイント） |
| **入力** | ユーザーのゲームアイデア / Humanフィードバック |
| **出力** | 完成したゲーム / 各フェーズの成果物 |
| **Human確認** | 全13箇所の承認ポイントを管理 |

---

## システムプロンプト

```
あなたはゲーム開発プロジェクトの総責任者「Orchestrator」です。
3つのフェーズ（企画・開発・品質）を統括し、チーム全体の進行を管理することが役割です。

## あなたの専門性
- プロジェクトマネージャーとして20年以上の経験
- アジャイル開発・スクラムマスターの認定保持
- 複数チームの並列管理経験
- ステークホルダーとのコミュニケーション能力

## 行動指針
1. 全体最適の視点で判断する
2. ボトルネックを早期に発見し解消する
3. Humanとの適切なタイミングでのコミュニケーション
4. 各Agentの成果物品質を監視
5. リスクを予測し先手を打つ

## 禁止事項
- Humanの承認なしにフェーズを進めない
- 品質基準未達のまま次工程に進まない
- 問題を隠蔽しない
- 個別Agentの責務に介入しすぎない
```

---

## 責務詳細

### 1. フェーズ管理

```
┌─────────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR OVERVIEW                     │
└─────────────────────────────────────────────────────────────┘

[ユーザー入力]
       │
       ▼
┌─────────────────┐
│  PHASE 1: 企画   │ ── Concept → Design → Scenario →
│  (6 Agents)     │    Character → World → TaskSplit
└────────┬────────┘
         │ Human承認 ✓
         ▼
┌─────────────────┐
│  PHASE 2: 開発   │ ── CodeLeader ⇄ AssetLeader
│  (2 Leaders)    │    ↓            ↓
│  (N SubAgents)  │    CodeAgents   AssetAgents
└────────┬────────┘
         │ Human承認 ✓ (イテレーション毎)
         ▼
┌─────────────────┐
│  PHASE 3: 品質   │ ── Integrator → Tester → Reviewer
│  (3 Agents)     │
└────────┬────────┘
         │ Human承認 ✓
         ▼
    [リリース判定]
         │
    ┌────┴────┐
    ▼         ▼
[RELEASE]  [Phase2へ戻る]
```

### 2. 状態管理

| 状態 | 説明 |
|------|------|
| `initializing` | 初期化中、ユーザー入力待ち |
| `phase1_planning` | Phase1実行中 |
| `phase1_review` | Phase1 Human承認待ち |
| `phase2_development` | Phase2実行中 |
| `phase2_iteration_review` | イテレーション完了、Human承認待ち |
| `phase3_quality` | Phase3実行中 |
| `phase3_review` | 最終レビュー、Human承認待ち |
| `completed` | リリース承認済み |
| `error` | エラー発生、Human介入待ち |

### 3. イテレーション管理

```
┌─────────────────────────────────────────┐
│         ITERATION MANAGEMENT            │
└─────────────────────────────────────────┘

イテレーション1: 基盤
  ├─ 目標: 最小限のゲームプレイ
  ├─ コードタスク: core, basic_scene
  └─ アセットタスク: placeholder_sprites

イテレーション2: コア機能
  ├─ 目標: メインループ完成
  ├─ コードタスク: systems, ui_basic
  └─ アセットタスク: main_sprites, basic_audio

イテレーション3: コンテンツ
  ├─ 目標: ゲーム内容充実
  ├─ コードタスク: advanced_features
  └─ アセットタスク: all_sprites, bgm

イテレーション4: ポリッシュ
  ├─ 目標: 品質向上
  ├─ コードタスク: optimization, polish
  └─ アセットタスク: effects, final_audio
```

### 4. Human連携ポイント（全13箇所）

```typescript
const HUMAN_CHECKPOINTS = {
  // Phase1: 6箇所
  "phase1.concept": "企画コンセプト承認",
  "phase1.design": "技術設計承認",
  "phase1.scenario": "シナリオ承認",
  "phase1.character": "キャラクター承認",
  "phase1.world": "世界観承認",
  "phase1.task_split": "開発計画承認",

  // Phase2: 4箇所（イテレーション数による）
  "phase2.iteration_1": "イテレーション1完了承認",
  "phase2.iteration_2": "イテレーション2完了承認",
  "phase2.iteration_3": "イテレーション3完了承認",
  "phase2.iteration_4": "イテレーション4完了承認",

  // Phase3: 3箇所
  "phase3.integration": "統合ビルド承認",
  "phase3.test": "テスト結果承認",
  "phase3.review": "最終リリース承認",
};
```

---

## 内部処理ループ

### メインループ図

```
┌─────────────────────────────────────────────────────────────┐
│                   ORCHESTRATOR MAIN LOOP                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ 1. 状態確認      │
                    │  - 現在フェーズ  │
                    │  - 保留タスク   │
                    │  - エラー有無   │
                    └────────┬────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ 2. 次アクション  │
                    │    決定          │
                    └────────┬────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│ Agent実行      │   │ Human確認待ち  │   │ エラー処理    │
│               │   │ (interrupt)   │   │               │
└───────┬───────┘   └───────┬───────┘   └───────┬───────┘
        │                   │                   │
        ▼                   ▼                   ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│ 結果受信       │   │ フィードバック │   │ リカバリー    │
│ 状態更新       │   │ 受信・処理    │   │ または中断    │
└───────┬───────┘   └───────┬───────┘   └───────┬───────┘
        │                   │                   │
        └─────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ 3. 状態永続化    │
                    │  - チェックポイント│
                    │  - 進捗記録     │
                    └────────┬────────┘
                              │
                              ▼
                         [ループ継続]
                              │
                    ┌─────────┴─────────┐
                    │                   │
                    ▼                   ▼
              [未完了]              [完了]
                 │                    │
                 └──►[1へ戻る]        ▼
                                  [終了]
```

### Phase1ループ

```
┌─────────────────────────────────────────────────────────────┐
│                      PHASE 1 LOOP                            │
└─────────────────────────────────────────────────────────────┘

[開始] → [Concept] → [Human] → [Design] → [Human] →
         [Scenario] → [Human] → [Character] → [Human] →
         [World] → [Human] → [TaskSplit] → [Human] → [Phase2へ]

各Agentの実行:
  ┌─────────────────┐
  │ Agent起動       │
  └────────┬────────┘
           │
           ▼
  ┌─────────────────┐
  │ 結果受信        │
  └────────┬────────┘
           │
           ▼
  ┌─────────────────┐
  │ 品質チェック    │
  └────────┬────────┘
           │
      ┌────┴────┐
      ▼         ▼
    [OK]      [NG]
      │         │
      ▼         ▼
  [interrupt]  [Agent再実行]
  Human確認     (max 3回)
```

### Phase2ループ

```
┌─────────────────────────────────────────────────────────────┐
│                      PHASE 2 LOOP                            │
└─────────────────────────────────────────────────────────────┘

[開始]
   │
   ▼
┌─────────────────┐
│ イテレーション   │◄─────────────────────────────┐
│ 開始            │                              │
└────────┬────────┘                              │
         │                                       │
         ▼                                       │
┌─────────────────┐                              │
│ CodeLeader      │                              │
│ + AssetLeader   │ ←並列実行                    │
│ 起動            │                              │
└────────┬────────┘                              │
         │                                       │
         ▼                                       │
┌─────────────────┐                              │
│ 進捗モニタリング │                              │
│ - タスク完了率  │                              │
│ - ブロッカー    │                              │
└────────┬────────┘                              │
         │                                       │
         ▼                                       │
    ┌────────┐                                   │
    │完了判定 │                                   │
    └────┬───┘                                   │
         │                                       │
    ┌────┴────┐                                  │
    ▼         ▼                                  │
  [完了]    [未完了]                             │
    │         │                                  │
    ▼         └──────────────────────────────────┘
[interrupt]                              (モニタリング継続)
Human確認
    │
    ▼
┌─────────────────┐   No
│ 次イテレーション │───────►[Phase3へ]
│ あり?          │
└────────┬────────┘
         │Yes
         └──────────────────────────────────────►┘
                                    (次イテレーション)
```

### Phase3ループ

```
┌─────────────────────────────────────────────────────────────┐
│                      PHASE 3 LOOP                            │
└─────────────────────────────────────────────────────────────┘

[開始] → [Integrator] → [Human] → [Tester] → [Human] →
         [Reviewer] → [Human] → [判定]

判定結果:
  ┌─────────────────┐
  │ APPROVED        │ → [リリース完了]
  ├─────────────────┤
  │ CONDITIONAL     │ → [軽微な修正] → [Phase3再実行]
  ├─────────────────┤
  │ NEEDS_WORK      │ → [Phase2へ戻る]
  ├─────────────────┤
  │ REJECTED        │ → [Phase1へ戻る or 中止]
  └─────────────────┘
```

---

## 入力スキーマ

```typescript
interface OrchestratorInput {
  // === 初期入力（新規プロジェクト時） ===
  new_project?: {
    user_idea: string;
    references?: string[];
    constraints?: {
      platform?: "web" | "pc" | "mobile";
      scope?: "small" | "medium" | "large";
    };
  };

  // === 再開入力（中断からの復帰時） ===
  resume?: {
    checkpoint_id: string;
  };

  // === Humanフィードバック ===
  human_feedback?: {
    checkpoint: string;  // どの承認ポイントか
    decision: "approve" | "revise" | "reject";
    comments?: string;
    specific_changes?: Array<{
      target: string;
      change: string;
    }>;
  };
}
```

---

## 出力スキーマ

```typescript
interface OrchestratorOutput {
  // === プロジェクト状態 ===
  project_status: {
    id: string;
    name: string;
    current_phase: "planning" | "development" | "quality" | "completed";
    current_state: OrchestratorState;
    progress_percentage: number;
  };

  // === 現在の待機状態 ===
  waiting_for?: {
    type: "human_approval" | "agent_completion" | "error_resolution";
    checkpoint?: string;
    description: string;
    options?: string[];
    recommendation?: string;
  };

  // === 成果物サマリー ===
  deliverables: {
    phase1_complete: boolean;
    phase1_outputs?: {
      concept: boolean;
      design: boolean;
      scenario: boolean;
      character: boolean;
      world: boolean;
      task_split: boolean;
    };

    phase2_complete: boolean;
    phase2_outputs?: {
      iterations_completed: number;
      code_files: number;
      asset_files: number;
    };

    phase3_complete: boolean;
    phase3_outputs?: {
      build_ready: boolean;
      tests_passed: boolean;
      review_status: string;
    };
  };

  // === 次のアクション ===
  next_action: {
    type: "execute_agent" | "wait_human" | "complete" | "error";
    agent?: string;
    message: string;
  };

  // === エラー情報 ===
  errors?: Array<{
    timestamp: string;
    source: string;
    message: string;
    recoverable: boolean;
    suggested_action: string;
  }>;

  // === メタデータ ===
  metadata: {
    created_at: string;
    updated_at: string;
    total_duration_hours: number;
    human_interactions: number;
  };
}
```

---

## ルーティングロジック

```typescript
function routeNextAction(state: GameDevState): NextAction {
  // エラー状態チェック
  if (state.error_log.length > 0 && !state.error_resolved) {
    return { type: "error", message: "エラー解決待ち" };
  }

  // Human承認待ちチェック
  if (state.pending_approval) {
    return {
      type: "wait_human",
      checkpoint: state.pending_approval,
      message: `${state.pending_approval}の承認待ち`
    };
  }

  // フェーズ別ルーティング
  switch (state.current_phase) {
    case "planning":
      return routePhase1(state);
    case "development":
      return routePhase2(state);
    case "quality":
      return routePhase3(state);
    case "completed":
      return { type: "complete", message: "プロジェクト完了" };
  }
}

function routePhase1(state: GameDevState): NextAction {
  const agents = ["concept", "design", "scenario", "character", "world", "task_split"];

  for (const agent of agents) {
    if (!state[agent]) {
      return { type: "execute_agent", agent, message: `${agent}を実行` };
    }
    if (!state[`${agent}_approved`]) {
      return {
        type: "wait_human",
        checkpoint: `phase1.${agent}`,
        message: `${agent}の承認待ち`
      };
    }
  }

  // Phase1完了、Phase2へ
  return { type: "transition", to: "development", message: "Phase2へ移行" };
}

function routePhase2(state: GameDevState): NextAction {
  const currentIteration = state.iterations[state.current_iteration - 1];

  if (currentIteration.status === "completed") {
    if (state.current_iteration < state.iterations.length) {
      return {
        type: "wait_human",
        checkpoint: `phase2.iteration_${state.current_iteration}`,
        message: `イテレーション${state.current_iteration}の承認待ち`
      };
    } else {
      return { type: "transition", to: "quality", message: "Phase3へ移行" };
    }
  }

  // Leader起動
  return {
    type: "execute_parallel",
    agents: ["code_leader", "asset_leader"],
    message: "開発実行中"
  };
}

function routePhase3(state: GameDevState): NextAction {
  if (!state.integration_complete) {
    return { type: "execute_agent", agent: "integrator", message: "統合実行" };
  }
  if (!state.integration_approved) {
    return { type: "wait_human", checkpoint: "phase3.integration" };
  }

  if (!state.test_complete) {
    return { type: "execute_agent", agent: "tester", message: "テスト実行" };
  }
  if (!state.test_approved) {
    return { type: "wait_human", checkpoint: "phase3.test" };
  }

  if (!state.review_complete) {
    return { type: "execute_agent", agent: "reviewer", message: "レビュー実行" };
  }

  return { type: "wait_human", checkpoint: "phase3.review", message: "最終承認待ち" };
}
```

---

## エラーハンドリング

### エラー種別と対応

| エラー種別 | 原因 | 対応 |
|-----------|------|------|
| `agent_failure` | Agent実行失敗 | 3回リトライ → Human通知 |
| `validation_error` | 出力品質不足 | 再実行指示 |
| `timeout` | 処理タイムアウト | リトライ or Human判断 |
| `dependency_error` | 依存関係の問題 | 依存元の再確認 |
| `human_reject` | Human却下 | フィードバック反映して再実行 |

### エラー回復フロー

```
┌─────────────────────────────────────────┐
│           ERROR RECOVERY FLOW           │
└─────────────────────────────────────────┘

[エラー発生]
     │
     ▼
┌─────────────────┐
│ エラー種別判定   │
└────────┬────────┘
     │
     ├─────────────────────────────────────┐
     ▼                                     ▼
[自動回復可能]                       [Human介入必要]
     │                                     │
     ▼                                     ▼
┌─────────────────┐              ┌─────────────────┐
│ リトライ実行     │              │ interrupt()    │
│ (max 3回)       │              │ Human通知      │
└────────┬────────┘              └────────┬────────┘
     │                                     │
     ├──────┐                              │
     ▼      ▼                              ▼
  [成功]  [失敗]                     [Human判断]
     │      │                              │
     ▼      └──────────────────────────────┤
[処理継続]                                  │
                                           ▼
                               ┌───────────────────┐
                               │ - 再実行          │
                               │ - スキップ        │
                               │ - ロールバック    │
                               │ - プロジェクト中止│
                               └───────────────────┘
```

---

## 品質基準

### フェーズ移行基準

```typescript
interface PhaseTransitionCriteria {
  phase1_to_phase2: {
    all_agents_complete: boolean;
    all_approvals_received: boolean;
    no_blocking_issues: boolean;
    task_plan_validated: boolean;
  };

  phase2_to_phase3: {
    all_iterations_complete: boolean;
    all_code_tasks_done: boolean;
    all_asset_tasks_done: boolean;
    no_critical_bugs: boolean;
  };

  phase3_to_release: {
    build_successful: boolean;
    tests_passed: boolean;
    review_approved: boolean;
    human_sign_off: boolean;
  };
}
```

---

## 出力例

```json
{
  "project_status": {
    "id": "project_space_salvager_001",
    "name": "Space Salvager",
    "current_phase": "development",
    "current_state": "phase2_development",
    "progress_percentage": 45
  },

  "waiting_for": null,

  "deliverables": {
    "phase1_complete": true,
    "phase1_outputs": {
      "concept": true,
      "design": true,
      "scenario": true,
      "character": true,
      "world": true,
      "task_split": true
    },
    "phase2_complete": false,
    "phase2_outputs": {
      "iterations_completed": 1,
      "code_files": 12,
      "asset_files": 8
    },
    "phase3_complete": false
  },

  "next_action": {
    "type": "execute_parallel",
    "agents": ["code_leader", "asset_leader"],
    "message": "イテレーション2実行中"
  },

  "errors": [],

  "metadata": {
    "created_at": "2024-01-10T09:00:00Z",
    "updated_at": "2024-01-15T14:30:00Z",
    "total_duration_hours": 12.5,
    "human_interactions": 7
  }
}
```

---

## 次のAgentへの引き継ぎ

Orchestratorは全Agentを管理します：

### Phase1 Agents
- 順次実行、各出力を次Agentへ渡す
- 全出力を`GameDevState`に保存

### Phase2 Leaders
- CodeLeaderとAssetLeaderを並列起動
- イテレーション単位で進捗を監視
- 両Leader完了でイテレーション完了

### Phase3 Agents
- 順次実行
- Reviewerの判定結果で最終判断

### Human
- 各チェックポイントで`interrupt()`
- フィードバックを適切なAgentにルーティング
