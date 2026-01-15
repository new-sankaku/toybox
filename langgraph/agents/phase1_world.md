# World Agent（世界観）

## 概要

| 項目 | 内容 |
|-----|------|
| **役割** | ゲームの世界設定・ルール・場所を定義 |
| **Phase** | Phase1: 企画 |
| **入力** | シナリオ + キャラクター |
| **出力** | 世界設定書（JSON） |
| **Human確認** | 世界観の一貫性・魅力・ゲームプレイとの統合を確認 |

---

## システムプロンプト

```
あなたはゲーム世界設計の専門家「World Agent」です。
プレイヤーが没入できる一貫性のある世界を構築し、ゲームプレイを支える環境を設計することが役割です。

## あなたの専門性
- ワールドビルダーとして15年以上の経験
- ファンタジー、SF、現代など多様なジャンルの世界構築
- レベルデザインとナラティブ環境の設計
- 世界のルールとゲームメカニクスの統合

## 行動指針
1. シナリオとキャラクターを支える世界を設計
2. ゲームプレイに意味のある場所と構造を作る
3. 一貫性のあるルールで没入感を高める
4. 探索の動機付けとなる謎・秘密を配置
5. 技術的制約を考慮したスケール設計

## 禁止事項
- シナリオと矛盾する設定を作らない
- ゲームプレイに関係ない過剰な設定を避ける
- 実装困難な広大すぎる世界を設計しない
- 既存作品の丸パクリを避ける
```

---

## 処理フロー

### Step 1: 世界の基盤構築
- 物理法則・魔法/技術のルール
- 時代設定と文明レベル
- 基本的な世界観のトーン

### Step 2: 勢力・組織設計
- 主要な勢力とその目的
- 勢力間の関係性
- プレイヤーとの関わり方

### Step 3: 地理・場所設計
- マップ構造（オープンワールド/リニア等）
- 主要ロケーション
- 各場所のゲームプレイ機能

### Step 4: 経済・リソース設計
- 通貨システム
- 収集可能なリソース
- 取引システム

### Step 5: 文化・歴史設計
- 背景となる歴史イベント
- 文化的要素（風習、言語等）
- 発見可能なロア（背景設定）

### Step 6: 世界設定書生成
構造化されたJSON形式で出力

---

## 入力スキーマ

```typescript
interface WorldInput {
  // Scenario Agentからの出力（必須）
  scenario: ScenarioOutput;

  // Character Agentからの出力（必須）
  characters: CharacterOutput;

  // Design Agentからの出力（必須）
  design: DesignOutput;

  // 世界観の追加要望（任意）
  world_preferences?: {
    map_style: "open_world" | "hub_based" | "linear" | "metroidvania";
    exploration_importance: "low" | "medium" | "high";
    lore_depth: "minimal" | "moderate" | "deep";
  };

  // 前回フィードバック（修正時のみ）
  previous_feedback?: string;
  previous_output?: WorldOutput;
}
```

---

## 出力スキーマ

```typescript
interface WorldOutput {
  // === 世界の基本ルール ===
  world_rules: {
    physics: {
      description: string;            // 物理法則の説明
      deviations: string[];           // 現実との違い
    };
    technology_or_magic: {
      system_name: string;            // 技術/魔法体系の名前
      description: string;
      rules: string[];                // 基本ルール
      limitations: string[];          // 制限・代償
      player_access: string;          // プレイヤーがアクセスできる範囲
    };
    time_system?: {
      day_night_cycle: boolean;
      time_affects_gameplay: string[];
    };
  };

  // === 勢力・組織 ===
  factions: Array<{
    id: string;
    name: string;
    type: "government" | "corporation" | "cult" | "guild" | "criminal" | "other";
    description: string;
    goals: string[];
    methods: string[];
    territory: string[];              // 支配地域
    resources: string[];              // 保有リソース
    leader?: string;                  // リーダー（キャラクターID参照）
    relationship_to_player: {
      initial: "friendly" | "neutral" | "hostile";
      can_change: boolean;
      reputation_system?: string;
    };
    key_npcs: string[];               // 所属キャラクター
    visual_identity: {
      colors: string[];
      symbols: string;
      architecture_style: string;
    };
  }>;

  // === 勢力間関係 ===
  faction_relationships: Array<{
    faction_a: string;
    faction_b: string;
    relationship: "allied" | "neutral" | "rivals" | "war";
    description: string;
    player_impact: string;            // プレイヤーへの影響
  }>;

  // === 地理・マップ構造 ===
  geography: {
    map_type: string;                 // オープンワールド/ハブ等
    scale: string;                    // 世界の規模感
    regions: Array<{
      id: string;
      name: string;
      description: string;
      climate: string;
      terrain: string;
      controlling_faction?: string;
      danger_level: "safe" | "moderate" | "dangerous" | "extreme";
      unlock_condition?: string;      // アンロック条件
    }>;
    connectivity: {
      travel_methods: string[];       // 移動手段
      fast_travel: boolean;
      restrictions: string[];
    };
  };

  // === 主要ロケーション ===
  locations: Array<{
    id: string;
    name: string;
    region_id: string;
    type: "hub" | "dungeon" | "town" | "wilderness" | "landmark" | "secret";
    description: string;
    atmosphere: string;               // 雰囲気

    // ゲームプレイ機能
    gameplay_functions: string[];     // ショップ、セーブ等
    activities: string[];             // できること
    enemies?: string[];               // 出現する敵
    resources?: string[];             // 入手可能リソース

    // シナリオ連携
    story_relevance: string;          // シナリオでの役割
    key_events: string[];             // 発生するイベントID

    // ビジュアル
    visual_concept: {
      description: string;
      key_features: string[];
      lighting: string;
      color_palette: string[];
    };

    // サブロケーション
    sub_locations?: Array<{
      name: string;
      purpose: string;
    }>;
  }>;

  // === 経済システム ===
  economy: {
    currency: {
      name: string;
      description: string;
      acquisition_methods: string[];
    };
    resources: Array<{
      id: string;
      name: string;
      type: "material" | "consumable" | "currency" | "key_item";
      description: string;
      rarity: "common" | "uncommon" | "rare" | "legendary";
      found_in: string[];             // 入手場所
      uses: string[];                 // 用途
    }>;
    trading: {
      merchant_locations: string[];
      price_fluctuation: boolean;
      special_vendors: string[];
    };
  };

  // === 歴史・ロア ===
  lore: {
    timeline: Array<{
      era: string;
      events: Array<{
        name: string;
        description: string;
        impact_on_present: string;
      }>;
    }>;
    mysteries: Array<{
      id: string;
      name: string;
      teaser: string;                 // プレイヤーに見せるヒント
      truth: string;                  // 真相（内部用）
      discovery_method: string;       // 発見方法
      story_tie_in: string;           // シナリオとの関連
    }>;
    collectible_lore: Array<{
      type: string;                   // 本、碑文、録音等
      total_count: number;
      reward_for_completion?: string;
    }>;
  };

  // === 環境要素 ===
  environment: {
    hazards: Array<{
      name: string;
      locations: string[];
      effect: string;
      counterplay: string;
    }>;
    interactive_elements: Array<{
      name: string;
      description: string;
      gameplay_effect: string;
    }>;
    ambient_creatures?: Array<{
      name: string;
      locations: string[];
      behavior: string;
    }>;
  };

  // === アセット要件サマリー ===
  asset_requirements: {
    unique_environments: number;
    tileset_count: number;
    background_count: number;
    estimated_complexity: "low" | "medium" | "high";
  };

  // === Human確認ポイント ===
  approval_questions: string[];
}
```

---

## マップ構造タイプガイド

| タイプ | 特徴 | 適したゲーム |
|-------|------|-------------|
| オープンワールド | 自由探索、広大 | 探索重視RPG、サンドボックス |
| ハブベース | 拠点 + ミッションエリア | アクション、ミッション制 |
| リニア | 一本道、ステージ制 | アクション、パズル |
| メトロイドヴァニア | 相互接続、能力解放で進行 | 探索アクション |
| ノードマップ | ポイント移動 | ストラテジー、ビジュアルノベル |

---

## 品質基準

### 必須条件
- [ ] シナリオの全ロケーションがカバーされている
- [ ] 各場所にゲームプレイ機能がある
- [ ] 勢力設定がキャラクターと整合
- [ ] 世界のルールが一貫している
- [ ] プレイヤーの探索動機がある

### 推奨条件
- [ ] 発見可能な秘密やロアがある
- [ ] 勢力間の緊張関係がゲームプレイに影響
- [ ] 環境ストーリーテリング要素がある

---

## エラーハンドリング

| エラー状況 | 対応 |
|-----------|------|
| シナリオのロケーションと不整合 | シナリオに合わせて調整 |
| キャラクターの所属と勢力設定が矛盾 | 整合性を取る提案 |
| 世界が広すぎる | スケールダウンを提案 |
| ゲームプレイに使わない設定が多い | 簡略化を提案 |

---

## 出力例

```json
{
  "world_rules": {
    "physics": {
      "description": "基本的に現実準拠だが、宇宙空間での慣性制御技術が普及",
      "deviations": [
        "人工重力装置により宇宙船・ステーション内は1G環境",
        "ワープ航法により光速を超える移動が可能",
        "エネルギーシールドによる物理防御"
      ]
    },
    "technology_or_magic": {
      "system_name": "古代テック",
      "description": "大崩壊以前の失われた超技術。現代技術を遥かに凌駕する",
      "rules": [
        "古代テックは複製不可能（ブラックボックス）",
        "起動には特定の「鍵」が必要な場合がある",
        "エネルギー源が不明で、枯渇すると使用不能"
      ],
      "limitations": [
        "理解できないため修理が困難",
        "相性問題で現代機器との統合が難しい"
      ],
      "player_access": "ゲーム進行により古代テックを発見・装備可能"
    },
    "time_system": {
      "day_night_cycle": false,
      "time_affects_gameplay": ["特定イベントはシナリオ進行で発生"]
    }
  },

  "factions": [
    {
      "id": "earth_federation",
      "name": "地球連邦（残党）",
      "type": "government",
      "description": "大崩壊以前の人類統一政府の後継を自称。中央集権的な秩序の回復を目指す",
      "goals": ["銀河の再統一", "地球との通信回復", "古代テックの独占"],
      "methods": ["外交", "経済圧力", "必要なら軍事力"],
      "territory": ["内周セクター", "主要航路"],
      "resources": ["最大の艦隊", "旧時代の技術データ"],
      "leader": null,
      "relationship_to_player": {
        "initial": "neutral",
        "can_change": true,
        "reputation_system": "クエスト完了と選択で変動"
      },
      "key_npcs": [],
      "visual_identity": {
        "colors": ["青", "白", "金"],
        "symbols": "地球と星を囲む輪",
        "architecture_style": "機能的、対称的、威圧的"
      }
    },
    {
      "id": "atlas_corp",
      "name": "アトラス・コーポレーション",
      "type": "corporation",
      "description": "大崩壊後に急成長した巨大企業。利益のためなら手段を選ばない",
      "goals": ["経済的覇権", "古代テックの商業化", "連邦を操る影の支配者"],
      "methods": ["買収", "スパイ活動", "傭兵部隊"],
      "territory": ["経済特区", "採掘惑星"],
      "resources": ["莫大な資金", "私設軍隊", "情報網"],
      "leader": "boss_vega",
      "relationship_to_player": {
        "initial": "neutral",
        "can_change": true,
        "reputation_system": "敵対は避けられないが、タイミングは選べる"
      },
      "key_npcs": ["marcus", "boss_vega"],
      "visual_identity": {
        "colors": ["黒", "赤", "銀"],
        "symbols": "Aを模した三角形",
        "architecture_style": "モダン、効率重視、威圧的"
      }
    },
    {
      "id": "frontier_alliance",
      "name": "辺境同盟",
      "type": "guild",
      "description": "辺境セクターの独立コロニーの緩やかな連合。自治と自由を重視",
      "goals": ["独立の維持", "相互扶助", "外部勢力への抵抗"],
      "methods": ["連携", "情報共有", "ゲリラ戦術"],
      "territory": ["辺境セクター", "小規模ステーション"],
      "resources": ["地元の支持", "隠れ家ネットワーク"],
      "leader": null,
      "relationship_to_player": {
        "initial": "friendly",
        "can_change": true,
        "reputation_system": "辺境での行動で変動"
      },
      "key_npcs": ["vendor_rik"],
      "visual_identity": {
        "colors": ["緑", "茶", "オレンジ"],
        "symbols": "手を取り合う図案",
        "architecture_style": "有機的、リサイクル素材、実用的"
      }
    }
  ],

  "faction_relationships": [
    {
      "faction_a": "earth_federation",
      "faction_b": "atlas_corp",
      "relationship": "rivals",
      "description": "表向きは協力関係だが、水面下で覇権を争う",
      "player_impact": "両者の対立を利用可能"
    },
    {
      "faction_a": "earth_federation",
      "faction_b": "frontier_alliance",
      "relationship": "neutral",
      "description": "連邦は再統合を望むが、強制はできない状態",
      "player_impact": "橋渡し役になれる可能性"
    },
    {
      "faction_a": "atlas_corp",
      "faction_b": "frontier_alliance",
      "relationship": "hostile",
      "description": "アトラスの搾取に辺境は反発",
      "player_impact": "どちらかの味方をすると他方と敵対"
    }
  ],

  "geography": {
    "map_type": "ハブベース（ステーション）+ 探索エリア（惑星・遺跡）",
    "scale": "銀河辺境セクター。複数の星系を航行",
    "regions": [
      {
        "id": "region_nebula_edge",
        "name": "ネビュラ・エッジ",
        "description": "ゲームの主な舞台となる辺境セクター",
        "climate": "宇宙空間（各惑星で異なる）",
        "terrain": "星雲、小惑星帯、惑星群",
        "controlling_faction": "frontier_alliance",
        "danger_level": "moderate",
        "unlock_condition": null
      },
      {
        "id": "region_core",
        "name": "中央セクター",
        "description": "連邦の支配圏。プレイヤーは後半でアクセス",
        "climate": "管理された環境",
        "terrain": "高度に開発された宇宙空間",
        "controlling_faction": "earth_federation",
        "danger_level": "safe",
        "unlock_condition": "Act2クリア"
      },
      {
        "id": "region_sol",
        "name": "太陽系（地球）",
        "description": "最終目的地。何が起きているかは謎",
        "climate": "不明",
        "terrain": "不明",
        "controlling_faction": null,
        "danger_level": "extreme",
        "unlock_condition": "最終章"
      }
    ],
    "connectivity": {
      "travel_methods": ["ワープ航法", "通常航行（近距離）"],
      "fast_travel": true,
      "restrictions": ["ワープには燃料消費", "未発見エリアへは移動不可"]
    }
  },

  "locations": [
    {
      "id": "loc_station_nova",
      "name": "ステーション・ノヴァ",
      "region_id": "region_nebula_edge",
      "type": "hub",
      "description": "辺境最大の交易ステーション。様々な種族と勢力が集まる中立地帯",
      "atmosphere": "活気があり雑多、どこか退廃的",
      "gameplay_functions": ["ショップ", "クエスト受注", "船体改造", "セーブ"],
      "activities": ["NPC会話", "サブクエスト", "情報収集", "ギャンブル"],
      "enemies": null,
      "resources": ["各種アイテム購入可"],
      "story_relevance": "ゲーム序盤のハブ。ミラとの出会い、情報収集の拠点",
      "key_events": ["ev02_01"],
      "visual_concept": {
        "description": "円筒形の巨大ステーション。中心部は吹き抜けのマーケット",
        "key_features": ["ネオン看板", "雑多な屋台", "巨大な窓から見える星雲"],
        "lighting": "人工照明、ネオン、薄暗い路地",
        "color_palette": ["オレンジ", "紫", "青緑"]
      },
      "sub_locations": [
        { "name": "マーケット広場", "purpose": "ショップ、NPC集合" },
        { "name": "酒場「流星」", "purpose": "情報収集、ミラとの出会い" },
        { "name": "ドック", "purpose": "船体改造、出発" },
        { "name": "裏路地", "purpose": "闇市、サブクエスト" }
      ]
    },
    {
      "id": "loc_ruin_alpha",
      "name": "遺跡アルファ",
      "region_id": "region_nebula_edge",
      "type": "dungeon",
      "description": "最初に発見する古代文明の遺跡。座標データの一部が眠る",
      "atmosphere": "神秘的、静寂、時折危険",
      "gameplay_functions": ["探索", "パズル", "戦闘"],
      "activities": ["スキャン", "アイテム収集", "敵との戦闘"],
      "enemies": ["enemy_drone"],
      "resources": ["古代の破片", "データコア"],
      "story_relevance": "最初の主要ダンジョン。古代テック初体験",
      "key_events": ["ev01_01"],
      "visual_concept": {
        "description": "小惑星内部に築かれた施設。幾何学的な構造",
        "key_features": ["発光する壁面", "浮遊するオブジェクト", "謎の文字"],
        "lighting": "青白い発光、影のコントラスト",
        "color_palette": ["青", "銀", "黒"]
      },
      "sub_locations": [
        { "name": "エントランス", "purpose": "導入、基本探索" },
        { "name": "制御室", "purpose": "パズル、データ取得" },
        { "name": "深層部", "purpose": "ボスエリア" }
      ]
    }
  ],

  "economy": {
    "currency": {
      "name": "クレジット",
      "description": "銀河共通の電子通貨。大崩壊後も価値を維持",
      "acquisition_methods": ["敵撃破", "アイテム売却", "クエスト報酬", "サルベージ"]
    },
    "resources": [
      {
        "id": "res_scrap",
        "name": "スクラップ",
        "type": "material",
        "description": "汎用の金属廃材。修理や簡単なクラフトに使用",
        "rarity": "common",
        "found_in": ["廃墟", "敵ドロップ", "サルベージ"],
        "uses": ["船体修理", "基本クラフト"]
      },
      {
        "id": "res_ancient_fragment",
        "name": "古代の破片",
        "type": "material",
        "description": "古代テックの残骸。高度なアップグレードに必要",
        "rarity": "rare",
        "found_in": ["遺跡", "ボスドロップ"],
        "uses": ["高度なクラフト", "古代装備の修復"]
      },
      {
        "id": "res_fuel",
        "name": "ワープ燃料",
        "type": "consumable",
        "description": "ワープ航法に必要な特殊燃料",
        "rarity": "uncommon",
        "found_in": ["ステーション購入", "採掘", "敵艦サルベージ"],
        "uses": ["ワープ移動"]
      }
    ],
    "trading": {
      "merchant_locations": ["ステーション・ノヴァ", "各惑星の拠点"],
      "price_fluctuation": false,
      "special_vendors": ["闇市商人（レアアイテム）", "古物商（ロア関連）"]
    }
  },

  "lore": {
    "timeline": [
      {
        "era": "拡大期（22-24世紀）",
        "events": [
          {
            "name": "銀河進出",
            "description": "ワープ技術の発明により人類が銀河へ拡散",
            "impact_on_present": "現在の勢力分布の基礎"
          },
          {
            "name": "古代文明の発見",
            "description": "人類以前の超文明の痕跡を発見",
            "impact_on_present": "古代テックの起源"
          }
        ]
      },
      {
        "era": "大崩壊（25世紀）",
        "events": [
          {
            "name": "大崩壊",
            "description": "原因不明の大災害。地球との通信途絶、多くの技術が失われる",
            "impact_on_present": "現代の混乱の元凶。ゲームの謎の核心"
          }
        ]
      },
      {
        "era": "復興期（26-32世紀）",
        "events": [
          {
            "name": "各勢力の台頭",
            "description": "連邦残党、企業、辺境コロニーがそれぞれ発展",
            "impact_on_present": "現在の勢力図"
          }
        ]
      }
    ],
    "mysteries": [
      {
        "id": "mystery_collapse",
        "name": "大崩壊の真実",
        "teaser": "300年前、何が起きたのか？地球はなぜ沈黙したのか？",
        "truth": "古代テックの暴走実験。地球は隔離されている",
        "discovery_method": "メインストーリー進行",
        "story_tie_in": "最終章で明らかに"
      },
      {
        "id": "mystery_ancient",
        "name": "古代文明の正体",
        "teaser": "人類以前に銀河を支配した者たちは何者か？",
        "truth": "人類の遠い未来の子孫がタイムトラベルで残した",
        "discovery_method": "ロア収集100%",
        "story_tie_in": "エンディング後の示唆"
      }
    ],
    "collectible_lore": [
      {
        "type": "データログ",
        "total_count": 30,
        "reward_for_completion": "隠しエンディングヒント"
      },
      {
        "type": "古代碑文",
        "total_count": 10,
        "reward_for_completion": "最強装備の設計図"
      }
    ]
  },

  "environment": {
    "hazards": [
      {
        "name": "放射線帯",
        "locations": ["特定の宇宙空間"],
        "effect": "シールド持続ダメージ",
        "counterplay": "放射線対策モジュール装備"
      },
      {
        "name": "古代のセキュリティ",
        "locations": ["遺跡内部"],
        "effect": "トラップ発動",
        "counterplay": "スキャンで事前発見"
      }
    ],
    "interactive_elements": [
      {
        "name": "端末",
        "description": "情報取得、ドア開放、システムハック",
        "gameplay_effect": "探索進行、ロア獲得"
      },
      {
        "name": "サルベージポイント",
        "description": "漂流物からリソース回収",
        "gameplay_effect": "素材入手"
      }
    ],
    "ambient_creatures": [
      {
        "name": "宇宙クラゲ",
        "locations": ["星雲内"],
        "behavior": "非敵対、美しい発光"
      }
    ]
  },

  "asset_requirements": {
    "unique_environments": 8,
    "tileset_count": 5,
    "background_count": 12,
    "estimated_complexity": "medium"
  },

  "approval_questions": [
    "勢力バランスはゲームプレイに適切に影響しますか？",
    "マップ規模は開発スコープに見合っていますか？",
    "大崩壊の謎はゲーム中に十分に示唆されていますか？",
    "ロケーション数は多すぎ/少なすぎませんか？"
  ]
}
```

---

## 次のAgentへの引き継ぎ

このAgentの出力は以下のAgentに渡されます：

### TaskSplit Agent
- ロケーションごとの実装タスク
- 環境アセット制作タスク
- マップデータ作成タスク

### Asset Leader（Phase2）
- 背景画像制作
- タイルセット制作
- 環境オブジェクト制作

### Code Leader（Phase2）
- マップシステム実装
- 勢力システム実装
- 経済システム実装
