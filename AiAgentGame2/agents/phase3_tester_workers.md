# Tester Workers（テスターワーカー）

## 概要

Tester Leaderの配下で動作するWorker群。各種テストを担当。

---

## UnitTest Worker（ユニットテストワーカー）

### 役割
ユニットテストを実行し、カバレッジを測定

### 出力スキーマ
```typescript
interface UnitTestWorkerOutput {
  unit_test_results: {
    total: number;
    passed: number;
    failed: number;
    coverage: {
      statements: number;
      branches: number;
      functions: number;
      lines: number;
    };
    failed_tests: Array<{
      name: string;
      error: string;
      file: string;
    }>;
    uncovered_files: string[];
  };
}
```

---

## IntegrationTest Worker（インテグレーションテストワーカー）

### 役割
統合テストを実行

### 出力スキーマ
```typescript
interface IntegrationTestWorkerOutput {
  integration_test_results: {
    total: number;
    passed: number;
    failed: number;
    results: Array<{
      name: string;
      status: "passed" | "failed";
      duration_ms: number;
      error?: string;
    }>;
  };
}
```

---

## E2ETest Worker（E2Eテストワーカー）

### 役割
E2Eシナリオテストを実行

### 出力スキーマ
```typescript
interface E2ETestWorkerOutput {
  e2e_test_results: {
    total: number;
    passed: number;
    failed: number;
    scenarios: Array<{
      name: string;
      steps: string[];
      status: "passed" | "failed";
      screenshot?: string;
      error?: string;
    }>;
  };
}
```

---

## PerformanceTest Worker（パフォーマンステストワーカー）

### 役割
パフォーマンステストと負荷テストを実行

### 出力スキーマ
```typescript
interface PerformanceTestWorkerOutput {
  performance_results: {
    fps: {
      average: number;
      min: number;
      max: number;
      status: "passed" | "warning" | "failed";
    };
    load_time: {
      initial_load_ms: number;
      status: "passed" | "warning" | "failed";
    };
    memory: {
      initial_mb: number;
      peak_mb: number;
      leak_detected: boolean;
      status: "passed" | "warning" | "failed";
    };
  };
  bottlenecks: Array<{
    location: string;
    issue: string;
    recommendation: string;
  }>;
}
```

---

## Worker間連携

```
UnitTest Worker ──► IntegrationTest Worker ──► E2ETest Worker ──► PerformanceTest Worker
       │                     │                      │                     │
       ▼                     ▼                      ▼                     ▼
   単体テスト            統合テスト              E2Eテスト          パフォーマンステスト
       │                     │                      │                     │
       └─────────────────────┴──────────────────────┴─────────────────────┘
                                          │
                                          ▼
                                    Tester Leader
                                   (統合・品質管理)
```
