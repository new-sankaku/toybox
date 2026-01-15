# Tester Agent（テスト）

## 概要

| 項目 | 内容 |
|-----|------|
| **役割** | 統合ビルドのテスト実行 |
| **Phase** | Phase3: 品質 |
| **入力** | 統合済みビルド |
| **出力** | テスト結果レポート（JSON） |
| **Human確認** | テスト結果・品質基準を確認 |

---

## テスト種別

1. **ユニットテスト**
   - 各コンポーネントの単体動作

2. **統合テスト**
   - コンポーネント間連携

3. **機能テスト**
   - ユーザーストーリーベース

4. **パフォーマンステスト**
   - FPS、読み込み時間

---

## 出力形式

```json
{
  "summary": {
    "total": 25,
    "passed": 23,
    "failed": 2,
    "skipped": 0
  },
  "results": [
    {
      "name": "PlayerController.move",
      "status": "passed",
      "duration_ms": 15
    },
    {
      "name": "GameCore.sceneTransition",
      "status": "failed",
      "error": "Timeout: シーン遷移が5秒以上",
      "suggestion": "非同期処理の見直しが必要"
    }
  ],
  "performance": {
    "average_fps": 58,
    "load_time_ms": 1200
  }
}
```
