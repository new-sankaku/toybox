# Reviewer Workers（レビューアーワーカー）

Reviewer Leaderの配下で動作するWorker群。

## CodeReview Worker
- **役割**: コード品質をレビュー
- **出力**: score, architecture（design_adherence, concerns, strengths）, quality_metrics（readability/maintainability/testability）, issues, tech_debt

## AssetReview Worker
- **役割**: アセット品質をレビュー
- **出力**: score, style_consistency, technical_quality（format_compliance, size_optimization）, completeness（required/delivered/missing）

## GameplayReview Worker
- **役割**: ゲームプレイとUXをレビュー
- **出力**: score, user_experience（first_impression, frustration_points, delight_moments）, balance（difficulty_curve）, completeness（core_loop, features_vs_spec）

## Compliance Worker
- **役割**: 仕様との整合性をチェック
- **出力**: overall_compliance, feature_checklist, deviations, risk_assessment（overall_risk, technical_risks, release_blockers）

## Worker間連携
CodeReview → AssetReview → GameplayReview → Compliance → Reviewer Leader（統合・リリース判定）

## スキーマ
参照: `_SCHEMAS.md`
