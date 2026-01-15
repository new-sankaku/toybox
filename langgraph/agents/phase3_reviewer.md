# Reviewer Agent（レビュー）

## 概要

| 項目 | 内容 |
|-----|------|
| **役割** | コード・アセットの品質レビュー |
| **Phase** | Phase3: 品質 |
| **入力** | 統合ビルド + テスト結果 |
| **出力** | レビューレポート（JSON） |
| **Human確認** | 最終品質判定・リリース可否を確認 |

---

## レビュー観点

1. **コード品質**
   - 可読性、保守性
   - 設計との整合性
   - セキュリティ

2. **アセット品質**
   - スタイル統一
   - 技術仕様適合

3. **ゲーム品質**
   - ゲームプレイ体験
   - バランス

---

## 出力形式

```json
{
  "overall_status": "conditional_pass",
  "code_review": {
    "score": 8,
    "issues": [
      {
        "severity": "minor",
        "file": "src/player/PlayerController.ts",
        "line": 45,
        "message": "マジックナンバーを定数化すべき"
      }
    ]
  },
  "asset_review": {
    "score": 9,
    "issues": []
  },
  "recommendation": "minor修正後リリース可",
  "blockers": []
}
```
