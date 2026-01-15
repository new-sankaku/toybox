# エラー回復パターン

## 概要

このドキュメントでは、システム全体のエラーハンドリング戦略と
具体的な回復パターンを定義します。

---

## エラー分類

### エラー重要度

```typescript
type ErrorSeverity =
  | "critical"      // システム停止、即時Human介入
  | "major"         // 処理続行不可、エスカレーション
  | "minor"         // 処理続行可、ログ記録
  | "warning";      // 注意、監視継続
```

### エラーカテゴリ

```typescript
type ErrorCategory =
  | "llm_error"           // LLM呼び出し失敗
  | "validation_error"    // 出力検証失敗
  | "dependency_error"    // 依存関係エラー
  | "timeout_error"       // タイムアウト
  | "resource_error"      // リソース不足
  | "state_error"         // 状態不整合
  | "communication_error" // 通信エラー
  | "human_reject";       // Human却下
```

### エラーコード体系

```
E_[CATEGORY]_[SPECIFIC]

例:
- E_LLM_RATE_LIMIT      : LLMレート制限
- E_LLM_CONTEXT_LENGTH  : コンテキスト長超過
- E_VAL_SCHEMA_MISMATCH : スキーマ不一致
- E_DEP_CIRCULAR        : 循環依存
- E_TIMEOUT_AGENT       : Agent実行タイムアウト
- E_STATE_INCONSISTENT  : 状態不整合
```

---

## 回復パターン

### パターン1: 自動リトライ（Automatic Retry）

```
┌─────────────────────────────────────────────────────────────┐
│                    AUTOMATIC RETRY PATTERN                   │
└─────────────────────────────────────────────────────────────┘

適用: 一時的な障害（ネットワーク、レート制限等）

[処理実行]
     │
     ▼
  [失敗?] ─── No ──► [成功]
     │
    Yes
     │
     ▼
┌─────────────────┐
│ リトライ判定     │
│ - 回数 < 最大?  │
│ - リトライ可能? │
└────────┬────────┘
     │
     ├─── No ──► [エスカレーション]
     │
    Yes
     │
     ▼
[指数バックオフ待機]
  1s → 2s → 4s
     │
     └──────► [再実行] ──► [失敗?] ...
```

```typescript
const RETRY_CONFIG = {
  max_attempts: 3,
  initial_delay_ms: 1000,
  max_delay_ms: 30000,
  backoff_factor: 2,
  jitter_factor: 0.1,

  retryable_errors: [
    "E_LLM_RATE_LIMIT",
    "E_LLM_TEMPORARY",
    "E_COMMUNICATION_TIMEOUT",
    "E_RESOURCE_BUSY",
  ],
};

async function withRetry<T>(
  operation: () => Promise<T>,
  config = RETRY_CONFIG
): Promise<T> {
  let lastError: Error;
  let delay = config.initial_delay_ms;

  for (let attempt = 1; attempt <= config.max_attempts; attempt++) {
    try {
      return await operation();
    } catch (error) {
      lastError = error;

      if (!isRetryable(error, config.retryable_errors)) {
        throw error;
      }

      if (attempt < config.max_attempts) {
        const jitter = delay * config.jitter_factor * Math.random();
        await sleep(delay + jitter);
        delay = Math.min(delay * config.backoff_factor, config.max_delay_ms);
      }
    }
  }

  throw new RetryExhaustedError(lastError, config.max_attempts);
}
```

---

### パターン2: フォールバック（Fallback）

```
┌─────────────────────────────────────────────────────────────┐
│                      FALLBACK PATTERN                        │
└─────────────────────────────────────────────────────────────┘

適用: 代替手段が存在する場合

[主処理実行]
     │
     ▼
  [失敗?] ─── No ──► [成功]
     │
    Yes
     │
     ▼
[フォールバック選択]
     │
     ├─► [代替処理A] ─── 成功 ──► [完了]
     │        │
     │      失敗
     │        ▼
     ├─► [代替処理B] ─── 成功 ──► [完了]
     │        │
     │      失敗
     │        ▼
     └─► [デフォルト値 or エスカレーション]
```

```typescript
interface FallbackChain<T> {
  primary: () => Promise<T>;
  fallbacks: Array<{
    condition?: (error: Error) => boolean;
    handler: () => Promise<T>;
    name: string;
  }>;
  default?: T;
}

// 例: アセット生成のフォールバック
const assetGenerationFallback: FallbackChain<Asset> = {
  primary: () => generateWithPrimaryModel("stable-diffusion-xl"),
  fallbacks: [
    {
      condition: (e) => e.code === "E_LLM_RATE_LIMIT",
      handler: () => generateWithPrimaryModel("stable-diffusion-xl", { wait: true }),
      name: "rate_limit_wait",
    },
    {
      condition: (e) => e.code === "E_LLM_UNAVAILABLE",
      handler: () => generateWithBackupModel("dalle-3"),
      name: "backup_model",
    },
    {
      handler: () => usePlaceholderAsset(),
      name: "placeholder",
    },
  ],
  default: EMPTY_PLACEHOLDER,
};
```

---

### パターン3: サーキットブレーカー（Circuit Breaker）

```
┌─────────────────────────────────────────────────────────────┐
│                   CIRCUIT BREAKER PATTERN                    │
└─────────────────────────────────────────────────────────────┘

適用: 連続失敗を検出し、システム保護

状態遷移:
       ┌──────────────┐
       │    CLOSED    │ ← 正常状態
       │  (通常処理)   │
       └──────┬───────┘
              │ 失敗が閾値超過
              ▼
       ┌──────────────┐
       │     OPEN     │ ← 遮断状態
       │ (即座にFail)  │
       └──────┬───────┘
              │ タイムアウト後
              ▼
       ┌──────────────┐
       │  HALF-OPEN   │ ← 回復確認
       │ (1件だけ試行) │
       └──────┬───────┘
              │
       ┌──────┴──────┐
       ▼             ▼
    [成功]        [失敗]
       │             │
       ▼             ▼
   [CLOSED]      [OPEN]
```

```typescript
class CircuitBreaker {
  private state: "closed" | "open" | "half-open" = "closed";
  private failures = 0;
  private lastFailure?: Date;

  constructor(private config: {
    failureThreshold: number;    // 失敗閾値
    recoveryTimeout: number;     // 回復待機時間(ms)
    monitorWindow: number;       // 監視ウィンドウ(ms)
  }) {}

  async execute<T>(operation: () => Promise<T>): Promise<T> {
    if (this.state === "open") {
      if (this.shouldAttemptReset()) {
        this.state = "half-open";
      } else {
        throw new CircuitOpenError();
      }
    }

    try {
      const result = await operation();
      this.onSuccess();
      return result;
    } catch (error) {
      this.onFailure();
      throw error;
    }
  }

  private onSuccess() {
    this.failures = 0;
    this.state = "closed";
  }

  private onFailure() {
    this.failures++;
    this.lastFailure = new Date();

    if (this.state === "half-open" || this.failures >= this.config.failureThreshold) {
      this.state = "open";
    }
  }

  private shouldAttemptReset(): boolean {
    if (!this.lastFailure) return true;
    return Date.now() - this.lastFailure.getTime() > this.config.recoveryTimeout;
  }
}

// 使用例
const llmCircuitBreaker = new CircuitBreaker({
  failureThreshold: 5,
  recoveryTimeout: 60000,    // 1分
  monitorWindow: 300000,     // 5分
});
```

---

### パターン4: 補償トランザクション（Compensating Transaction）

```
┌─────────────────────────────────────────────────────────────┐
│               COMPENSATING TRANSACTION PATTERN               │
└─────────────────────────────────────────────────────────────┘

適用: 複数ステップの処理で途中失敗した場合のロールバック

[Step 1] ──► [Step 2] ──► [Step 3] ──► [完了]
    │            │            │
    ▼            ▼            ▼
 [補償1]      [補償2]      [補償3]

失敗時:
[Step 1] ──► [Step 2] ──► [Step 3] ✗ 失敗
                              │
                              ▼
                         [補償3実行]
                              │
                              ▼
                         [補償2実行]
                              │
                              ▼
                         [補償1実行]
                              │
                              ▼
                         [初期状態に復帰]
```

```typescript
interface CompensatableStep<T> {
  name: string;
  execute: () => Promise<T>;
  compensate: (result: T) => Promise<void>;
}

async function executeWithCompensation<T>(
  steps: CompensatableStep<any>[]
): Promise<T[]> {
  const completed: Array<{ step: CompensatableStep<any>; result: any }> = [];

  try {
    for (const step of steps) {
      const result = await step.execute();
      completed.push({ step, result });
    }
    return completed.map((c) => c.result);
  } catch (error) {
    // 逆順で補償処理実行
    for (const { step, result } of completed.reverse()) {
      try {
        await step.compensate(result);
      } catch (compensateError) {
        console.error(`Compensation failed for ${step.name}:`, compensateError);
        // 補償失敗はログに記録して続行
      }
    }
    throw error;
  }
}

// 例: Phase1の処理
const phase1Steps: CompensatableStep<any>[] = [
  {
    name: "concept",
    execute: () => runConceptAgent(),
    compensate: (result) => clearConceptFromState(result.id),
  },
  {
    name: "design",
    execute: () => runDesignAgent(),
    compensate: (result) => clearDesignFromState(result.id),
  },
  // ...
];
```

---

### パターン5: チェックポイント復帰（Checkpoint Recovery）

```
┌─────────────────────────────────────────────────────────────┐
│                 CHECKPOINT RECOVERY PATTERN                  │
└─────────────────────────────────────────────────────────────┘

適用: 長時間処理の途中状態からの復帰

[開始]
   │
   ▼
[処理1] ──► [Checkpoint A 保存]
   │
   ▼
[処理2] ──► [Checkpoint B 保存]
   │
   ▼
[処理3] ✗ 失敗
   │
   ▼
[Checkpoint B から復帰]
   │
   ▼
[処理3 再実行]
   │
   ▼
[完了]
```

```typescript
interface Checkpoint {
  id: string;
  timestamp: string;
  phase: string;
  state: GameDevState;
  metadata: {
    agent: string;
    iteration?: number;
  };
}

class CheckpointManager {
  async save(state: GameDevState, metadata: object): Promise<string> {
    const checkpoint: Checkpoint = {
      id: generateId(),
      timestamp: new Date().toISOString(),
      phase: state.current_phase,
      state: deepClone(state),
      metadata,
    };

    await this.storage.save(checkpoint);
    return checkpoint.id;
  }

  async restore(checkpointId: string): Promise<GameDevState> {
    const checkpoint = await this.storage.load(checkpointId);
    if (!checkpoint) {
      throw new CheckpointNotFoundError(checkpointId);
    }
    return checkpoint.state;
  }

  async listCheckpoints(projectId: string): Promise<Checkpoint[]> {
    return this.storage.list(projectId);
  }
}

// LangGraphでの使用
const checkpointConfig = {
  checkpointer: new MemorySaver(),  // または PostgresSaver
  interrupt_before: ["human_approval"],
  interrupt_after: [],
};
```

---

### パターン6: 段階的デグレード（Graceful Degradation）

```
┌─────────────────────────────────────────────────────────────┐
│                 GRACEFUL DEGRADATION PATTERN                 │
└─────────────────────────────────────────────────────────────┘

適用: 部分的な機能低下を許容して処理続行

[フル機能モード]
       │
       │ リソース不足 / エラー
       ▼
[縮退モード1]
  - 一部機能制限
  - 品質低下許容
       │
       │ さらなる問題
       ▼
[縮退モード2]
  - 最小限機能
  - placeholder使用
       │
       │ 回復不能
       ▼
[最終フォールバック]
  - Human介入要求
```

```typescript
interface DegradationLevel {
  level: number;
  name: string;
  restrictions: string[];
  enabled_features: string[];
}

const DEGRADATION_LEVELS: DegradationLevel[] = [
  {
    level: 0,
    name: "full",
    restrictions: [],
    enabled_features: ["all"],
  },
  {
    level: 1,
    name: "reduced_quality",
    restrictions: ["high_quality_generation"],
    enabled_features: ["basic_generation", "placeholder_fallback"],
  },
  {
    level: 2,
    name: "minimal",
    restrictions: ["ai_generation"],
    enabled_features: ["placeholder_only", "manual_input"],
  },
  {
    level: 3,
    name: "emergency",
    restrictions: ["automated_processing"],
    enabled_features: ["human_only"],
  },
];

class DegradationManager {
  private currentLevel = 0;

  escalate(reason: string): void {
    if (this.currentLevel < DEGRADATION_LEVELS.length - 1) {
      this.currentLevel++;
      this.notifyLevelChange(reason);
    }
  }

  recover(): void {
    if (this.currentLevel > 0) {
      this.currentLevel--;
    }
  }

  isFeatureEnabled(feature: string): boolean {
    const level = DEGRADATION_LEVELS[this.currentLevel];
    return level.enabled_features.includes(feature) ||
           level.enabled_features.includes("all");
  }
}
```

---

## エラー別対応マトリクス

| エラーコード | パターン | リトライ | フォールバック | Human通知 |
|-------------|---------|---------|--------------|----------|
| E_LLM_RATE_LIMIT | Retry + CB | ✓ | - | ✗ |
| E_LLM_CONTEXT_LENGTH | Fallback | ✗ | 分割処理 | ✗ |
| E_LLM_UNAVAILABLE | CB + Fallback | ✓ | 代替モデル | ✗ |
| E_VAL_SCHEMA_MISMATCH | Retry | ✓ | 再生成 | 3回失敗時 |
| E_VAL_QUALITY_LOW | Retry | ✓ | - | 3回失敗時 |
| E_DEP_MISSING | Compensate | ✗ | - | ✓ |
| E_DEP_CIRCULAR | - | ✗ | - | ✓ |
| E_TIMEOUT_AGENT | Retry + CB | ✓ | - | 3回失敗時 |
| E_STATE_INCONSISTENT | Checkpoint | ✗ | 復帰 | ✓ |
| E_HUMAN_REJECT | - | ✗ | 修正再実行 | - |

---

## Human介入フロー

```
┌─────────────────────────────────────────────────────────────┐
│                   HUMAN INTERVENTION FLOW                    │
└─────────────────────────────────────────────────────────────┘

[エラー発生]
     │
     ▼
[自動回復試行]
     │
     ├── 成功 ──► [処理続行]
     │
     ▼ 失敗
[エスカレーション判定]
     │
     ├── エスカレーション不要 ──► [ログ記録のみ]
     │
     ▼ エスカレーション必要
[interrupt() 呼び出し]
     │
     ▼
[Human通知]
  - エラー内容
  - 影響範囲
  - 選択肢
  - 推奨アクション
     │
     ▼
[Human判断待ち]
     │
     ├─► [再実行] ──► [同じ処理を再試行]
     │
     ├─► [スキップ] ──► [該当処理をスキップして続行]
     │
     ├─► [手動入力] ──► [Humanが直接結果を入力]
     │
     ├─► [ロールバック] ──► [チェックポイントに戻る]
     │
     └─► [中止] ──► [プロジェクト中止]
```

```typescript
interface HumanInterventionRequest {
  error: {
    code: string;
    message: string;
    context: Record<string, any>;
  };

  impact: {
    affected_agents: string[];
    blocked_tasks: string[];
    estimated_delay: string;
  };

  options: Array<{
    action: string;
    description: string;
    risk_level: "low" | "medium" | "high";
    recommended: boolean;
  }>;

  auto_action_after?: {
    action: string;
    timeout_hours: number;
  };
}

// 例
const interventionRequest: HumanInterventionRequest = {
  error: {
    code: "E_VAL_QUALITY_LOW",
    message: "Character Agentの出力が品質基準を満たしませんでした",
    context: {
      agent: "character",
      attempt: 3,
      quality_score: 45,
      required_score: 70,
    },
  },
  impact: {
    affected_agents: ["world", "task_split"],
    blocked_tasks: ["world_001", "task_split_001"],
    estimated_delay: "2-4 hours",
  },
  options: [
    {
      action: "retry_with_feedback",
      description: "フィードバックを追加して再生成",
      risk_level: "low",
      recommended: true,
    },
    {
      action: "manual_edit",
      description: "出力を手動で修正",
      risk_level: "medium",
      recommended: false,
    },
    {
      action: "accept_as_is",
      description: "現状の品質で続行",
      risk_level: "high",
      recommended: false,
    },
  ],
  auto_action_after: {
    action: "retry_with_feedback",
    timeout_hours: 24,
  },
};
```

---

## ログとモニタリング

### エラーログ形式

```typescript
interface ErrorLog {
  timestamp: string;
  error_id: string;
  error_code: string;
  severity: ErrorSeverity;
  category: ErrorCategory;

  source: {
    agent: string;
    task_id?: string;
    iteration?: number;
  };

  details: {
    message: string;
    stack_trace?: string;
    context: Record<string, any>;
  };

  recovery: {
    pattern_applied: string;
    attempts: number;
    resolved: boolean;
    resolution?: string;
  };
}
```

### アラート設定

```typescript
const ALERT_RULES = {
  // Critical: 即時通知
  critical: {
    channels: ["slack", "email", "sms"],
    delay: 0,
  },

  // Major: 5分以内に通知
  major: {
    channels: ["slack", "email"],
    delay: 300000,  // 5分
    aggregate: true,  // 集約
  },

  // Minor: 1時間ごとにサマリー
  minor: {
    channels: ["slack"],
    delay: 3600000,  // 1時間
    aggregate: true,
  },

  // Warning: 日次レポートに含める
  warning: {
    channels: ["daily_report"],
    aggregate: true,
  },
};
```
