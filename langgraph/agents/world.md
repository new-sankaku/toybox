# World Agent（世界観）

## 概要

| 項目 | 内容 |
|-----|------|
| **役割** | ゲームの世界設定・ルールを定義 |
| **Phase** | Phase1: 企画 |
| **入力** | シナリオ + キャラクター |
| **出力** | 世界設定書（JSON） |
| **Human確認** | 世界観の一貫性・魅力を確認 |

---

## 出力形式

```json
{
  "world_rules": {
    "physics": "リアル寄り（宇宙空間は無重力）",
    "technology_level": "超光速航行可能",
    "magic_system": null
  },
  "factions": [
    {
      "name": "地球連邦",
      "description": "人類の統一政府",
      "territory": "太陽系内惑星"
    },
    {
      "name": "辺境同盟",
      "description": "独立を求める植民地連合",
      "territory": "外縁部"
    }
  ],
  "economy": {
    "currency": "クレジット",
    "resources": ["燃料", "鉱石", "食料"]
  },
  "locations": [
    {
      "name": "ステーション・アルファ",
      "type": "宇宙ステーション",
      "description": "辺境最大の交易拠点"
    }
  ]
}
```
