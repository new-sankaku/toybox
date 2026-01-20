# Concept Workers（コンセプトワーカー）

Concept Leaderの配下で動作するWorker群。

## Research Worker
- **役割**: 市場調査と競合ゲーム分析
- **分析観点**: 市場規模/トレンド、競合の強み・弱み、参入機会

## Ideation Worker
- **役割**: ゲームコンセプトの要素を創出
- **創出観点**: ゲームメカニクス案、ビジュアルスタイル案、差別化ポイント

## Validation Worker
- **役割**: コンセプトの整合性と実現可能性を検証
- **検証観点**: 市場適合性、技術的実現可能性、リソース要件、オリジナリティ
- **判定**: approved / needs_revision / rejected

## Worker間連携
Research → Ideation → Validation → Concept Leader（統合・品質管理）

## スキーマ
参照: `_SCHEMAS.md`
