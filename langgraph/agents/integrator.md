# Integrator Agent（統合）

## 概要

| 項目 | 内容 |
|-----|------|
| **役割** | コードとアセットを統合し動作確認 |
| **Phase** | Phase3: 品質 |
| **入力** | 全コード + 全アセット |
| **出力** | 統合済みビルド |
| **Human確認** | 統合結果の動作確認 |

---

## 処理フロー

1. コード出力の収集
2. アセット出力の収集
3. 依存関係の解決
4. ビルド実行
5. 基本動作確認
6. 統合レポート生成

---

## 出力形式

```json
{
  "build_status": "success",
  "integrated_files": [
    "src/core/GameCore.ts",
    "src/player/PlayerController.ts",
    "assets/images/player.png"
  ],
  "dependency_resolution": {
    "resolved": ["code_002 <- asset_001"],
    "unresolved": []
  },
  "basic_checks": {
    "compilation": "passed",
    "asset_loading": "passed",
    "startup": "passed"
  }
}
```
