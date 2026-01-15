# Character Agent（キャラクター）

## 概要

| 項目 | 内容 |
|-----|------|
| **役割** | ゲームに登場するキャラクターを設計 |
| **Phase** | Phase1: 企画 |
| **入力** | シナリオ文書 |
| **出力** | キャラクター仕様（JSON） |
| **Human確認** | キャラクターの魅力・バランスを確認 |

---

## 出力形式

```json
{
  "characters": [
    {
      "id": "player",
      "name": "（プレイヤー命名）",
      "role": "主人公",
      "personality": "好奇心旺盛、正義感が強い",
      "appearance": {
        "age": 25,
        "gender": "選択可能",
        "features": "パイロットスーツ着用"
      },
      "abilities": ["操縦", "射撃", "修理"]
    },
    {
      "id": "rival",
      "name": "レイ",
      "role": "ライバル/後に仲間",
      "personality": "クール、合理的",
      "backstory": "元軍人、過去に家族を失う"
    }
  ]
}
```
