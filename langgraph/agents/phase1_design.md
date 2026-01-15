# Design Agent（設計）

## 概要

| 項目 | 内容 |
|-----|------|
| **役割** | コンセプトを技術的な設計に落とし込む |
| **Phase** | Phase1: 企画 |
| **入力** | ゲームコンセプト文書 |
| **出力** | 技術設計書（JSON） |
| **Human確認** | 技術選定・アーキテクチャが適切か確認 |

---

## 処理フロー

1. コンセプトから技術要件を抽出
2. 適切な技術スタックを選定
3. システムアーキテクチャを設計
4. コンポーネント分割を決定
5. 設計書を生成

---

## 出力形式

```json
{
  "tech_stack": {
    "language": "TypeScript",
    "framework": "Phaser.js",
    "libraries": ["matter.js", "howler.js"]
  },
  "architecture": "コンポーネントベース",
  "components": [
    {"name": "GameCore", "responsibility": "ゲームループ管理"},
    {"name": "PlayerSystem", "responsibility": "プレイヤー操作・状態管理"},
    {"name": "WorldGenerator", "responsibility": "惑星の手続き生成"},
    {"name": "CombatSystem", "responsibility": "戦闘ロジック"},
    {"name": "UIManager", "responsibility": "UI表示・操作"}
  ],
  "data_flow": "イベント駆動型"
}
```
