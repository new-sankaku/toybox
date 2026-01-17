# Reviewer Workers（レビューアーワーカー）

## 概要

Reviewer Leaderの配下で動作するWorker群。各領域のレビューを担当。

---

## CodeReview Worker（コードレビューワーカー）

### 役割
コード品質をレビュー

### 出力スキーマ
```typescript
interface CodeReviewWorkerOutput {
  code_review: {
    score: number;  // 1-10
    architecture: {
      score: number;
      design_adherence: boolean;
      concerns: string[];
      strengths: string[];
    };
    quality_metrics: {
      readability: number;
      maintainability: number;
      testability: number;
      documentation: number;
    };
    issues: Array<{
      file: string;
      line: number;
      severity: "high" | "medium" | "low";
      message: string;
    }>;
    tech_debt: Array<{
      location: string;
      description: string;
      priority: "high" | "medium" | "low";
    }>;
  };
}
```

---

## AssetReview Worker（アセットレビューワーカー）

### 役割
アセット品質をレビュー

### 出力スキーマ
```typescript
interface AssetReviewWorkerOutput {
  asset_review: {
    score: number;  // 1-10
    style_consistency: {
      score: number;
      consistent_elements: string[];
      inconsistent_elements: string[];
    };
    technical_quality: {
      score: number;
      format_compliance: boolean;
      size_optimization: boolean;
    };
    completeness: {
      required_assets: number;
      delivered_assets: number;
      missing_assets: string[];
    };
  };
}
```

---

## GameplayReview Worker（ゲームプレイレビューワーカー）

### 役割
ゲームプレイとUXをレビュー

### 出力スキーマ
```typescript
interface GameplayReviewWorkerOutput {
  gameplay_review: {
    score: number;  // 1-10
    user_experience: {
      score: number;
      first_impression: string;
      frustration_points: string[];
      delight_moments: string[];
    };
    balance: {
      score: number;
      difficulty_curve: "too_easy" | "appropriate" | "too_hard";
      issues: string[];
    };
    completeness: {
      core_loop_implemented: boolean;
      features_vs_spec: {
        specified: number;
        implemented: number;
        missing: string[];
      };
    };
  };
}
```

---

## Compliance Worker（コンプライアンスワーカー）

### 役割
仕様との整合性をチェック

### 出力スキーマ
```typescript
interface ComplianceWorkerOutput {
  specification_compliance: {
    overall_compliance: number;  // パーセンテージ
    feature_checklist: Array<{
      feature: string;
      status: "complete" | "partial" | "missing";
      notes: string;
    }>;
    deviations: Array<{
      spec: string;
      implementation: string;
      severity: "high" | "medium" | "low";
    }>;
  };
  risk_assessment: {
    overall_risk: "low" | "medium" | "high" | "critical";
    technical_risks: string[];
    release_blockers: string[];
  };
}
```

---

## Worker間連携

```
CodeReview Worker ──► AssetReview Worker ──► GameplayReview Worker ──► Compliance Worker
        │                    │                       │                       │
        ▼                    ▼                       ▼                       ▼
   コード評価           アセット評価           ゲームプレイ評価         仕様整合性
        │                    │                       │                       │
        └────────────────────┴───────────────────────┴───────────────────────┘
                                           │
                                           ▼
                                    Reviewer Leader
                                   (統合・リリース判定)
```
