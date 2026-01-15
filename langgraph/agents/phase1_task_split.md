# TaskSplit Agent（タスク分解）

## 概要

| 項目 | 内容 |
|-----|------|
| **役割** | 企画成果物を開発タスクに分解 |
| **Phase** | Phase1: 企画 |
| **入力** | 全企画成果物（コンセプト〜世界観） |
| **出力** | イテレーション計画（JSON） |
| **Human確認** | タスク分割の妥当性・優先度を確認 |

---

## 処理フロー

1. 企画成果物から必要機能を抽出
2. 機能を実装単位に分解
3. 依存関係を分析
4. イテレーションに割り当て
5. 計画書を生成

---

## 出力形式

```json
{
  "iterations": [
    {
      "number": 1,
      "goal": "基本移動と探索の実装",
      "code_tasks": [
        {
          "id": "code_001",
          "name": "GameCore実装",
          "description": "ゲームループ、シーン管理",
          "depends_on": [],
          "required_assets": []
        },
        {
          "id": "code_002",
          "name": "PlayerController実装",
          "description": "プレイヤー移動、入力処理",
          "depends_on": ["code_001"],
          "required_assets": ["asset_001"]
        }
      ],
      "asset_tasks": [
        {
          "id": "asset_001",
          "name": "プレイヤースプライト",
          "type": "image",
          "description": "主人公キャラクター画像"
        }
      ]
    }
  ]
}
```
