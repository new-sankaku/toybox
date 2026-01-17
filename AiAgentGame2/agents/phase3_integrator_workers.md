# Integrator Workers（インテグレーターワーカー）

## 概要

Integrator Leaderの配下で動作するWorker群。依存関係、ビルド、検証を担当。

---

## Dependency Worker（ディペンデンシーワーカー）

### 役割
依存関係の解決とパッケージ管理

### 出力スキーマ
```typescript
interface DependencyWorkerOutput {
  dependency_resolution: {
    npm_packages: {
      installed: number;
      resolved: string[];
      warnings: string[];
    };
    local_modules: {
      resolved: string[];
      unresolved: string[];
    };
    asset_references: {
      resolved: string[];
      unresolved: string[];
    };
  };
  issues: Issue[];
}
```

---

## Build Worker（ビルドワーカー）

### 役割
ビルドの実行とバンドル生成

### 出力スキーマ
```typescript
interface BuildWorkerOutput {
  build_summary: {
    status: "success" | "failed" | "partial";
    build_id: string;
    duration_seconds: number;
    output_dir: string;
  };
  integrated_files: {
    code: Array<{
      source_path: string;
      output_path: string;
      size_kb: number;
      minified: boolean;
    }>;
    assets: Array<{
      source_path: string;
      output_path: string;
      size_kb: number;
      optimized: boolean;
    }>;
  };
  build_checks: {
    typescript_compilation: {
      status: "passed" | "failed";
      errors: string[];
    };
    asset_validation: {
      status: "passed" | "failed";
      missing_assets: string[];
    };
    bundle_analysis: {
      total_size_kb: number;
      code_size_kb: number;
      asset_size_kb: number;
    };
  };
}
```

---

## IntegrationValidation Worker（インテグレーションバリデーションワーカー）

### 役割
起動テストと基本動作確認

### 出力スキーマ
```typescript
interface IntegrationValidationWorkerOutput {
  startup_checks: {
    compilation: "passed" | "failed";
    asset_loading: "passed" | "failed" | "partial";
    startup: "passed" | "failed";
    initial_render: "passed" | "failed";
    console_errors: string[];
  };
  issues: Array<{
    severity: "error" | "warning";
    category: "code" | "asset";
    message: string;
    suggestion: string;
  }>;
}
```

---

## Worker間連携

```
Dependency Worker ──► Build Worker ──► IntegrationValidation Worker
        │                  │                       │
        ▼                  ▼                       ▼
   依存解決           ビルド実行               起動検証
        │                  │                       │
        └──────────────────┴───────────────────────┘
                           │
                           ▼
                    Integrator Leader
                    (統合・品質管理)
```
