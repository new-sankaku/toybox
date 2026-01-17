# TaskSplit Workers（タスク分割ワーカー）

## 概要

TaskSplit Leaderの配下で動作するWorker群。要件分析、タスク分解、スケジュール作成を担当。

---

## Analysis Worker（アナリシスワーカー）

### 役割
企画成果物から要件を分析し、機能を抽出

### 出力スキーマ
```typescript
interface AnalysisWorkerOutput {
  requirements: Array<{
    id: string;
    type: "functional" | "non-functional";
    description: string;
    source: "concept" | "design" | "scenario";
    priority: "must" | "should" | "could";
  }>;
  features: Array<{
    id: string;
    name: string;
    description: string;
    requirements: string[];
    complexity: "high" | "medium" | "low";
  }>;
}
```

---

## Decomposition Worker（デコンポジションワーカー）

### 役割
機能をコードタスクとアセットタスクに分解

### 出力スキーマ
```typescript
interface DecompositionWorkerOutput {
  code_tasks: Array<{
    id: string;
    name: string;
    description: string;
    component: string;
    priority: "critical" | "high" | "medium" | "low";
    estimated_hours: number;
    depends_on: string[];
    required_assets: string[];
    acceptance_criteria: string[];
  }>;
  asset_tasks: Array<{
    id: string;
    name: string;
    type: "sprite" | "background" | "ui" | "audio";
    specifications: {
      format: string;
      dimensions?: string;
    };
    priority: "critical" | "high" | "medium" | "low";
    estimated_hours: number;
  }>;
  dependency_map: {
    code_to_code: Array<{ from: string; to: string; reason: string }>;
    asset_to_code: Array<{ asset_id: string; code_id: string; reason: string }>;
    critical_path: string[];
  };
}
```

---

## Schedule Worker（スケジュールワーカー）

### 役割
イテレーション計画とマイルストーンを作成

### 出力スキーマ
```typescript
interface ScheduleWorkerOutput {
  iterations: Array<{
    number: number;
    name: string;
    goal: string;
    deliverables: string[];
    estimated_days: number;
    code_task_ids: string[];
    asset_task_ids: string[];
    completion_criteria: string[];
  }>;
  milestones: Array<{
    name: string;
    iteration: number;
    criteria: string[];
    stakeholder_demo: boolean;
  }>;
  risks: Array<{
    risk: string;
    impact: "high" | "medium" | "low";
    probability: "high" | "medium" | "low";
    mitigation: string;
  }>;
}
```

---

## Worker間連携

```
Analysis Worker ──► Decomposition Worker ──► Schedule Worker
       │                    │                     │
       ▼                    ▼                     ▼
   要件分析            タスク分解           スケジュール作成
       │                    │                     │
       └────────────────────┴─────────────────────┘
                            │
                            ▼
                     TaskSplit Leader
                     (統合・品質管理)
```
