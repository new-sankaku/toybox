# Character Agent（キャラクター）

## 概要

| 項目 | 内容 |
|-----|------|
| **役割** | ゲームに登場するキャラクターを設計 |
| **Phase** | Phase1: 企画 |
| **入力** | シナリオ文書 + 設計 |
| **出力** | キャラクター仕様書（JSON） |
| **Human確認** | キャラクターの魅力・バランス・実装可能性を確認 |

---

## システムプロンプト

```
あなたはゲームキャラクターデザインの専門家「Character Agent」です。
魅力的で記憶に残るキャラクターを設計し、ゲームプレイとシナリオを強化することが役割です。

## あなたの専門性
- キャラクターデザイナーとして15年以上の経験
- 心理学とアーキタイプ理論の深い知識
- ゲームバランスとキャラクター性能の調整経験
- アニメーション・ビジュアル制作との連携経験

## 行動指針
1. 各キャラクターに明確な役割と個性を与える
2. プレイヤーが感情移入できる深みを持たせる
3. シナリオでの役割とゲームプレイ機能を両立
4. 視覚的に区別しやすいデザイン指針を提供
5. アセット制作に必要十分な仕様を定義

## 禁止事項
- 役割が重複するキャラクターを作らない
- 設定だけで活躍しないキャラクターを避ける
- 実装困難なアニメーション要件を含めない
- ステレオタイプに頼りすぎない
```

---

## 処理フロー

### Step 1: 必要キャラクター分析
シナリオから以下を抽出：
- ストーリー上必要なキャラクター
- ゲームプレイ上必要なキャラクタータイプ
- 世界観を表現するためのキャラクター

### Step 2: キャラクターアーキタイプ選定
基本アーキタイプ：
```
ヒーロー / メンター / 仲間 / 番人 / 使者
シェイプシフター / 影（シャドウ） / トリックスター
```

### Step 3: キャラクター詳細設計
- 基本情報（名前、年齢、外見）
- 性格と動機
- バックストーリー
- 能力とゲームプレイ機能
- 他キャラクターとの関係

### Step 4: ビジュアル指針設計
- シルエットの差別化
- カラーパレット
- 特徴的なデザイン要素
- アニメーション要件

### Step 5: ゲームプレイ統合
- 戦闘能力（該当する場合）
- スキル/アビリティ
- 成長システム

### Step 6: キャラクター仕様書生成
構造化されたJSON形式で出力

---

## 入力スキーマ

```typescript
interface CharacterInput {
  // Scenario Agentからの出力（必須）
  scenario: ScenarioOutput;

  // Design Agentからの出力（必須）
  design: DesignOutput;

  // キャラクター要望（任意）
  character_preferences?: {
    player_character_customizable: boolean;
    party_system: boolean;
    enemy_variety: "low" | "medium" | "high";
    npc_depth: "minimal" | "moderate" | "detailed";
  };

  // 前回フィードバック（修正時のみ）
  previous_feedback?: string;
  previous_output?: CharacterOutput;
}
```

---

## 出力スキーマ

```typescript
interface CharacterOutput {
  // === プレイヤーキャラクター ===
  player_character: {
    id: string;
    name: string | null;                  // null = プレイヤー命名
    customizable: boolean;
    customization_options?: {
      appearance: string[];               // カスタマイズ可能な要素
      gender: boolean;
      name: boolean;
    };
    role: string;
    backstory_premise: string;            // 設定可能な範囲の背景
    personality_traits: string[];
    starting_abilities: string[];
    growth_potential: string[];
    visual_design: CharacterVisual;
  };

  // === メインキャラクター（ストーリー重要キャラ） ===
  main_characters: Array<{
    id: string;
    name: string;
    archetype: string;                    // ヒーロー/メンター等
    role_in_story: string;
    role_in_gameplay: string;

    // 基本情報
    profile: {
      age: number | string;               // 数値 or "不明"等
      gender: string;
      occupation: string;
      affiliation: string;                // 所属
    };

    // 性格・内面
    personality: {
      traits: string[];                   // 性格特性
      strengths: string[];                // 長所
      flaws: string[];                    // 欠点・弱点
      fears: string[];                    // 恐れ
      desires: string[];                  // 望み
      speech_pattern: string;             // 話し方の特徴
    };

    // バックストーリー
    backstory: {
      summary: string;
      key_events: string[];
      secrets?: string[];                 // 隠された設定
      character_arc: string;              // 成長の方向性
    };

    // 関係性
    relationships: Array<{
      character_id: string;
      relationship_type: string;          // 友人/ライバル/恋人等
      description: string;
      dynamic: string;                    // 関係の変化
    }>;

    // ゲームプレイ（該当する場合）
    gameplay?: {
      playable: boolean;
      combat_role?: string;               // タンク/アタッカー等
      abilities?: Array<{
        name: string;
        description: string;
        type: string;
      }>;
      stats_tendency?: string;            // ステータス傾向
    };

    // ビジュアル
    visual_design: CharacterVisual;
  }>;

  // === サブキャラクター ===
  supporting_characters: Array<{
    id: string;
    name: string;
    role: string;                         // 商人/情報屋等
    personality_summary: string;
    appearance_summary: string;
    function_in_game: string;             // ゲーム内での機能
    notable_dialog?: string[];            // 印象的なセリフ
  }>;

  // === 敵キャラクター ===
  enemies: {
    bosses: Array<{
      id: string;
      name: string;
      role_in_story: string;
      motivation: string;
      threat_level: string;
      visual_concept: string;
      combat_style: string;
      weakness_hint: string;              // 攻略のヒント
    }>;
    enemy_types: Array<{
      id: string;
      name: string;
      category: string;                   // 雑魚/中ボス等
      description: string;
      behavior_pattern: string;
      visual_concept: string;
      variants?: string[];                // バリエーション
    }>;
  };

  // === キャラクター関係図 ===
  relationship_map: {
    diagram: string;                      // ASCII関係図
    key_dynamics: Array<{
      characters: string[];
      relationship: string;
      story_significance: string;
    }>;
  };

  // === ビジュアルガイドライン ===
  visual_guidelines: {
    art_style: string;
    color_philosophy: string;             // 色使いの方針
    silhouette_variety: string;           // シルエット差別化方針
    animation_requirements: {
      common_animations: string[];        // 全キャラ共通
      character_specific: Array<{
        character_id: string;
        unique_animations: string[];
      }>;
    };
  };

  // === アセット要件サマリー ===
  asset_requirements: {
    sprite_count: number;
    portrait_count: number;
    animation_sets: number;
    estimated_complexity: "low" | "medium" | "high";
  };

  // === Human確認ポイント ===
  approval_questions: string[];
}

// ビジュアル情報の共通型
interface CharacterVisual {
  silhouette_description: string;         // シルエットの特徴
  color_palette: {
    primary: string;
    secondary: string;
    accent: string;
  };
  distinctive_features: string[];         // 特徴的な要素
  clothing_style: string;
  accessories: string[];
  reference_keywords: string[];           // 参考検索キーワード
}
```

---

## キャラクターアーキタイプガイド

| アーキタイプ | 役割 | ゲームでの活用例 |
|------------|------|-----------------|
| ヒーロー | 主人公、変化する者 | プレイヤーキャラ |
| メンター | 導き手、知恵の提供者 | チュートリアルNPC、情報提供者 |
| 番人 | 試練を与える者 | 中ボス、ゲートキーパー |
| 使者 | 冒険の呼びかけ | クエスト依頼者 |
| シェイプシフター | 信頼できない者 | 裏切りキャラ、謎の人物 |
| 影 | 対立者、闇の側面 | メインヴィラン |
| 仲間 | 支援者、相棒 | パーティメンバー |
| トリックスター | 混乱をもたらす者 | コメディリリーフ、情報屋 |

---

## 品質基準

### 必須条件
- [ ] 各キャラクターの役割が明確で重複がない
- [ ] シナリオの重要イベントに対応するキャラクターが存在
- [ ] ビジュアル指針がアセット制作に十分
- [ ] 関係性が物語を駆動する設計
- [ ] ゲームプレイ機能が定義されている（該当キャラ）

### 推奨条件
- [ ] キャラクターに意外性がある
- [ ] 成長/変化の余地がある
- [ ] プレイヤーの感情移入ポイントがある

---

## エラーハンドリング

| エラー状況 | 対応 |
|-----------|------|
| シナリオに必要なキャラが未定義 | 追加キャラを提案 |
| キャラ数が多すぎる | 統合または削減を提案 |
| アセット要件が現実的でない | スコープを調整 |
| 関係性が複雑すぎる | 簡略化を提案 |

---

## 出力例

```json
{
  "player_character": {
    "id": "player",
    "name": null,
    "customizable": true,
    "customization_options": {
      "appearance": ["髪型", "髪色", "肌色", "体型"],
      "gender": true,
      "name": true
    },
    "role": "サルベージャー（宇宙の廃品回収業者）",
    "backstory_premise": "辺境の小さな星で育ち、生計のためサルベージを始めた。過去に何かを失った経験がある（プレイヤーの解釈に委ねる）",
    "personality_traits": ["実利主義", "好奇心旺盛", "口数少なめ（選択肢で性格付け）"],
    "starting_abilities": ["基本操縦", "スキャン", "簡易修理"],
    "growth_potential": ["戦闘スキル", "交渉術", "高度技術"],
    "visual_design": {
      "silhouette_description": "実用的な作業服、背中にツールキット、ゴーグル",
      "color_palette": {
        "primary": "ダークグレー",
        "secondary": "オレンジ（アクセント）",
        "accent": "青い発光（ゴーグル、ツール）"
      },
      "distinctive_features": ["多機能ゴーグル", "使い込まれた手袋", "腰のツールベルト"],
      "clothing_style": "実用的な宇宙作業服",
      "accessories": ["改造ゴーグル", "マルチツール", "通信機"],
      "reference_keywords": ["スペースエンジニア", "サイバーパンク作業員", "SF整備士"]
    }
  },

  "main_characters": [
    {
      "id": "mira",
      "name": "ミラ・ヴェイン",
      "archetype": "メンター + 仲間",
      "role_in_story": "プレイヤーを導く考古学者。古代文明の知識を持つ",
      "role_in_gameplay": "情報提供、アイテム解説、一部クエストで同行",
      "profile": {
        "age": 34,
        "gender": "女性",
        "occupation": "宇宙考古学者",
        "affiliation": "独立研究者（元大学所属）"
      },
      "personality": {
        "traits": ["知的好奇心", "熱中すると周りが見えない", "皮肉屋だが根は優しい"],
        "strengths": ["博識", "冷静な分析力", "語学力"],
        "flaws": ["社交下手", "過去のトラウマ", "時に無謀"],
        "fears": ["研究が無意味だったと証明されること"],
        "desires": ["古代文明の真実を解明したい"],
        "speech_pattern": "専門用語を多用するが、説明好き。「これは興味深い…」が口癖"
      },
      "backstory": {
        "summary": "かつて大学で有望視されていたが、異端の学説を唱えて追放。独自に研究を続け、今回の発見で復権を狙う",
        "key_events": ["大学追放", "辺境での単独研究", "最初の遺跡発見"],
        "secrets": ["追放の真の理由は彼女の発見を奪おうとした上司との対立"],
        "character_arc": "学問のための探求から、人のための行動へ"
      },
      "relationships": [
        {
          "character_id": "player",
          "relationship_type": "パートナー",
          "description": "最初は利害関係、やがて信頼へ",
          "dynamic": "師弟関係から対等な仲間へ"
        },
        {
          "character_id": "marcus",
          "relationship_type": "旧知",
          "description": "大学時代の同期。複雑な感情",
          "dynamic": "再会により過去と向き合う"
        }
      ],
      "gameplay": {
        "playable": false,
        "combat_role": null,
        "abilities": null,
        "stats_tendency": null
      },
      "visual_design": {
        "silhouette_description": "長身でスレンダー、長いコートと大きな鞄",
        "color_palette": {
          "primary": "深い紫",
          "secondary": "白",
          "accent": "金（アクセサリー）"
        },
        "distinctive_features": ["厚い眼鏡", "常に持ち歩く古い本", "首元のペンダント"],
        "clothing_style": "学者風だが動きやすいコート",
        "accessories": ["アンティーク眼鏡", "データパッド", "母の形見のペンダント"],
        "reference_keywords": ["女性考古学者", "インディジョーンズ風", "知的SF女性"]
      }
    },
    {
      "id": "marcus",
      "name": "マーカス・レイン",
      "archetype": "シェイプシフター",
      "role_in_story": "味方に見えて実は裏切者。プレイヤーの選択で運命が変わる",
      "role_in_gameplay": "序盤の戦闘サポート、中盤で敵対または仲間に",
      "profile": {
        "age": 36,
        "gender": "男性",
        "occupation": "傭兵（表向き）、企業スパイ（実態）",
        "affiliation": "アトラス・コーポレーション（秘密裏に）"
      },
      "personality": {
        "traits": ["カリスマ的", "戦術家", "内面に葛藤を抱える"],
        "strengths": ["戦闘能力", "リーダーシップ", "適応力"],
        "flaws": ["忠誠心の欠如", "過去への罪悪感", "本心を隠す"],
        "fears": ["自分の行動で誰かが傷つくこと（矛盾を抱える）"],
        "desires": ["家族の借金を返済し、自由になりたい"],
        "speech_pattern": "軽口と真剣な言葉を使い分ける。本心を悟らせない"
      },
      "backstory": {
        "summary": "元連邦軍のエリート兵士。家族の借金のためアトラス社に取り込まれ、スパイとして送り込まれた",
        "key_events": ["軍での功績", "家族の危機", "アトラスとの契約"],
        "secrets": ["妹が人質同然の状態", "かつてミラに好意を持っていた"],
        "character_arc": "利己的な生存から、自己犠牲または完全な裏切りへ"
      },
      "relationships": [
        {
          "character_id": "player",
          "relationship_type": "仮初めの仲間",
          "description": "任務のために近づくが、次第に本当の絆が",
          "dynamic": "裏切り後、敵か味方かはプレイヤー次第"
        },
        {
          "character_id": "mira",
          "relationship_type": "元同期",
          "description": "複雑な過去を持つ",
          "dynamic": "裏切り時に最も衝撃を受ける"
        }
      ],
      "gameplay": {
        "playable": false,
        "combat_role": "アタッカー（序盤サポート時）",
        "abilities": [
          {
            "name": "戦術支援",
            "description": "敵の弱点をマークする",
            "type": "サポート"
          }
        ],
        "stats_tendency": "攻撃特化"
      },
      "visual_design": {
        "silhouette_description": "がっしりした体格、ミリタリーコート、短髪",
        "color_palette": {
          "primary": "ダークブルー",
          "secondary": "黒",
          "accent": "赤（警告色、裏切りの暗示）"
        },
        "distinctive_features": ["左頬の傷跡", "軍用タグ", "常に携帯する拳銃"],
        "clothing_style": "ミリタリー風の実用的な服装",
        "accessories": ["ドッグタグ", "カスタム拳銃", "通信イヤピース"],
        "reference_keywords": ["SF傭兵", "元軍人", "ダークヒーロー"]
      }
    }
  ],

  "supporting_characters": [
    {
      "id": "vendor_rik",
      "name": "リク",
      "role": "ステーション・ノヴァの商人",
      "personality_summary": "陽気でおしゃべり、情報通。金には細かい",
      "appearance_summary": "小柄で丸っこい体型、派手な商人服",
      "function_in_game": "アイテム売買、噂話（サブクエスト発生）",
      "notable_dialog": ["「お客さん、いいもの入ってるよ〜」", "「情報？高くつくぜ？」"]
    }
  ],

  "enemies": {
    "bosses": [
      {
        "id": "boss_vega",
        "name": "ヴェガ提督",
        "role_in_story": "アトラス社の実行部隊長。地球の技術で銀河支配を狙う",
        "motivation": "秩序ある銀河統一（強権的な方法で）",
        "threat_level": "最終ボス",
        "visual_concept": "威圧的な軍服、機械化された右腕、冷酷な表情",
        "combat_style": "重武装、範囲攻撃、部下召喚",
        "weakness_hint": "機械腕の冷却システム"
      }
    ],
    "enemy_types": [
      {
        "id": "enemy_merc",
        "name": "アトラス傭兵",
        "category": "雑魚",
        "description": "アトラス社に雇われた傭兵たち",
        "behavior_pattern": "集団で攻撃、カバーを活用",
        "visual_concept": "統一された黒いアーマー、フルフェイスヘルメット",
        "variants": ["軽装兵", "重装兵", "狙撃兵"]
      },
      {
        "id": "enemy_drone",
        "name": "セキュリティドローン",
        "category": "雑魚",
        "description": "遺跡や施設を守る自動防衛システム",
        "behavior_pattern": "パトロール、侵入者を発見すると攻撃",
        "visual_concept": "球形、青い発光、回転する武装",
        "variants": ["偵察型", "攻撃型", "シールド型"]
      }
    ]
  },

  "relationship_map": {
    "diagram": "```\n[プレイヤー] ──仲間──> [ミラ]\n     │                    │\n     │ 仮の同盟            │ 旧知\n     v                    v\n [マーカス] <──スパイ── [アトラス社]\n     │                    │\n     │ 裏切り or 改心      │ 指揮\n     v                    v\n [選択で分岐]        [ヴェガ提督]\n```",
    "key_dynamics": [
      {
        "characters": ["player", "mira"],
        "relationship": "探求のパートナー",
        "story_significance": "メインストーリーの推進力"
      },
      {
        "characters": ["player", "marcus"],
        "relationship": "信頼と裏切り",
        "story_significance": "中盤の転換点、プレイヤーの選択"
      },
      {
        "characters": ["mira", "marcus"],
        "relationship": "過去の因縁",
        "story_significance": "裏切りの衝撃を増幅"
      }
    ]
  },

  "visual_guidelines": {
    "art_style": "セミリアリスティック、SF調",
    "color_philosophy": "陣営ごとに色を分ける。主人公側=暖色、敵=寒色、中立=緑",
    "silhouette_variety": "各キャラクターは3秒で識別可能なシルエット差を持たせる",
    "animation_requirements": {
      "common_animations": ["待機", "歩行", "走行", "ダメージ", "死亡"],
      "character_specific": [
        {
          "character_id": "player",
          "unique_animations": ["スキャン", "クラフト", "操縦"]
        },
        {
          "character_id": "mira",
          "unique_animations": ["本を読む", "解説ジェスチャー", "驚き"]
        }
      ]
    }
  },

  "asset_requirements": {
    "sprite_count": 12,
    "portrait_count": 8,
    "animation_sets": 6,
    "estimated_complexity": "medium"
  },

  "approval_questions": [
    "マーカスの裏切り設定は物語に効果的ですか？",
    "プレイヤーキャラのカスタマイズ範囲は適切ですか？",
    "敵キャラのバリエーションは十分ですか？",
    "アセット要件は現実的な範囲ですか？"
  ]
}
```

---

## 次のAgentへの引き継ぎ

このAgentの出力は以下のAgentに渡されます：

### World Agent
- キャラクターの所属勢力情報
- キャラクターがいる場所

### TaskSplit Agent
- キャラクターアセットの制作タスク
- アニメーション制作タスク
- ダイアログ実装タスク

### Asset Leader（Phase2）
- キャラクタースプライト制作
- ポートレート制作
- アニメーション制作
