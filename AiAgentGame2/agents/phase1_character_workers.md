# Character Workers（キャラクターワーカー）

## 概要

Character Leaderの配下で動作するWorker群。主要キャラクター、NPC、関係性設計を担当。

---

## MainCharacter Worker（メインキャラクターワーカー）

### 役割
プレイヤーキャラクターと主要キャラクターを設計

### 出力スキーマ
```typescript
interface MainCharacterWorkerOutput {
  player_character: {
    id: string;
    role: string;
    backstory_premise: string;
    personality_traits: string[];
    visual_design: {
      silhouette_description: string;
      color_palette: Record<string, string>;
      distinctive_features: string[];
    };
  };
  main_characters: Array<{
    id: string;
    name: string;
    archetype: string;
    role_in_story: string;
    personality: {
      traits: string[];
      strengths: string[];
      flaws: string[];
    };
    visual_design: VisualDesign;
  }>;
}
```

---

## NPC Worker（NPCワーカー）

### 役割
NPC、敵キャラクター、ボスを設計

### 出力スキーマ
```typescript
interface NPCWorkerOutput {
  npcs: Array<{
    id: string;
    name: string;
    role: string;
    location: string;
    function: string;
  }>;
  enemies: {
    regular: Array<{
      id: string;
      name: string;
      type: string;
      behavior: string;
    }>;
    bosses: Array<{
      id: string;
      name: string;
      chapter: number;
      mechanics: string[];
    }>;
  };
}
```

---

## Relationship Worker（リレーションシップワーカー）

### 役割
キャラクター間の関係性と相関図を設計

### 出力スキーマ
```typescript
interface RelationshipWorkerOutput {
  relationship_map: {
    connections: Array<{
      from: string;
      to: string;
      type: string;
      description: string;
    }>;
    factions: Array<{
      name: string;
      members: string[];
      stance: string;
    }>;
    key_dynamics: string[];
  };
}
```

---

## Worker間連携

```
MainCharacter Worker ──► NPC Worker ──► Relationship Worker
         │                   │                  │
         ▼                   ▼                  ▼
    主要キャラ          NPC・敵設計         関係性設計
         │                   │                  │
         └───────────────────┴──────────────────┘
                             │
                             ▼
                      Character Leader
                      (統合・品質管理)
```
