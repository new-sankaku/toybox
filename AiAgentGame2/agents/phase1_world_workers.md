# World Workers（ワールドワーカー）

## 概要

World Leaderの配下で動作するWorker群。地理、設定、システム設計を担当。

---

## Geography Worker（ジオグラフィーワーカー）

### 役割
地理・マップ・ロケーションを設計

### 出力スキーマ
```typescript
interface GeographyWorkerOutput {
  geography: {
    map_type: "hub-based" | "open-world" | "linear";
    scale: string;
    regions: Array<{
      id: string;
      name: string;
      description: string;
      climate: string;
      danger_level: "safe" | "moderate" | "dangerous";
    }>;
  };
  locations: Array<{
    id: string;
    name: string;
    region_id: string;
    type: "hub" | "dungeon" | "town" | "wilderness";
    description: string;
    gameplay_functions: string[];
    visual_concept: {
      key_features: string[];
      color_palette: string[];
    };
  }>;
}
```

---

## Lore Worker（ロアワーカー）

### 役割
歴史・設定・世界観を設計

### 出力スキーマ
```typescript
interface LoreWorkerOutput {
  world_rules: {
    physics: {
      description: string;
      deviations: string[];
    };
    technology_or_magic: {
      system_name: string;
      rules: string[];
      limitations: string[];
    };
  };
  lore: {
    timeline: Array<{
      era: string;
      events: string[];
    }>;
    mysteries: string[];
    legends: string[];
  };
}
```

---

## System Worker（システムワーカー）

### 役割
経済システムと勢力を設計

### 出力スキーマ
```typescript
interface SystemWorkerOutput {
  economy: {
    currency: {
      name: string;
      acquisition_methods: string[];
    };
    resources: Array<{
      name: string;
      rarity: "common" | "rare" | "legendary";
      uses: string[];
    }>;
    trade_system: {
      shops: string[];
      trading_rules: string[];
    };
  };
  factions: Array<{
    id: string;
    name: string;
    type: "government" | "corporation" | "guild";
    goals: string[];
    territory: string[];
    relationship_to_player: {
      initial: "friendly" | "neutral" | "hostile";
      can_change: boolean;
    };
  }>;
}
```

---

## Worker間連携

```
Geography Worker ──► Lore Worker ──► System Worker
       │                 │               │
       ▼                 ▼               ▼
   地理設計          世界観設計      システム設計
       │                 │               │
       └─────────────────┴───────────────┘
                         │
                         ▼
                    World Leader
                   (統合・品質管理)
```
