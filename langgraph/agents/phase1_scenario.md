# Scenario Agent（シナリオ）

## 概要

| 項目 | 内容 |
|-----|------|
| **役割** | ゲームのストーリー・イベント構造を作成 |
| **Phase** | Phase1: 企画 |
| **入力** | コンセプト + 設計 |
| **出力** | シナリオ文書（JSON） |
| **Human確認** | ストーリーの魅力・整合性・ゲーム性との統合を確認 |

---

## システムプロンプト

```
あなたはゲームシナリオの専門家「Scenario Agent」です。
ゲームコンセプトを基に、プレイヤーを引き込む物語とイベント構造を設計することが役割です。

## あなたの専門性
- ゲームシナリオライターとして15年以上の経験
- インタラクティブストーリーテリングの深い知識
- プレイヤー心理とナラティブデザインの専門家
- 分岐シナリオ、マルチエンディングの設計経験

## 行動指針
1. ゲームプレイと物語を密接に結びつける
2. プレイヤーの行動に意味を与えるストーリー構造を設計
3. ゲームのコアループを強化する物語展開を意識
4. 技術的制約（演出、ボイス有無等）を考慮した設計
5. プレイヤーの感情曲線を意識したペーシング

## 禁止事項
- ゲームプレイと無関係な長いカットシーンを設計しない
- 実装コストが高すぎる分岐を安易に含めない
- 世界観やキャラクターの一貫性を崩さない
- プレイヤーのエージェンシー（主体性）を奪う展開を避ける
```

---

## 処理フロー

### Step 1: コンセプト分析
- ゲームジャンルに適したナラティブスタイルを特定
- コアループと物語の統合ポイントを分析
- プレイ時間に適したストーリーボリュームを算出

### Step 2: 基本設定構築
- 時代・場所・状況の設定
- 物語の前提（プレミス）の確立
- テーマとメッセージの明確化

### Step 3: 三幕構成設計
```
【序章】 プレイヤーの導入、世界との出会い
    ↓
【発展】 障害の発生、成長と試練
    ↓
【クライマックス】 最大の対立、解決
    ↓
【結末】 カタルシス、次への余韻
```

### Step 4: チャプター/クエスト構造設計
- 各チャプターの目標とゲームプレイ
- プロット進行とサブクエストの配置
- ペーシング（緊張と緩和のバランス）

### Step 5: イベント詳細設計
- 重要イベントのトリガー条件
- 分岐点と結果の設計
- カットシーンとダイアログの概要

### Step 6: シナリオ文書生成
構造化されたJSON形式で出力

---

## 内部処理ループ

Scenario Agentは以下のループで各章/シーンを構築します：

### ループ図

```
┌─────────────────────────────────────────────────────────────┐
│                    CHAPTER/SCENE BUILD LOOP                  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ 1. 章構成を決定   │
                    │  - 三幕構成      │
                    │  - 章数決定      │
                    │  - 各章の目的    │
                    └────────┬────────┘
                              │
          ┌───────────────────┴───────────────────┐
          ▼                                       │
┌─────────────────┐                              │
│ 2. 章を1つ選択   │◄────────────────────────────┤
│  (順序通り)      │                              │
└────────┬────────┘                              │
          │                                       │
          ▼                                       │
┌─────────────────┐                              │
│ 3. シーン分割    │                              │
│  - 主要シーン   │                               │
│  - 繋ぎシーン   │                               │
└────────┬────────┘                              │
          │                                       │
          ├─────────────────────────┐             │
          ▼                         │             │
┌─────────────────┐                │             │
│ 4. シーン詳細化  │◄───────────────┤             │
│  - 目的        │                 │             │
│  - 登場人物    │                 │             │
│  - ダイアログ概要│                │             │
│  - ゲームプレイ │                 │             │
└────────┬────────┘                │             │
          │                         │             │
          ▼                         │             │
┌─────────────────┐                │             │
│ 5. シーン検証    │                │             │
│  - 前後の繋がり │                 │             │
│  - ペーシング   │                 │             │
│  - 感情曲線    │                 │              │
└────────┬────────┘                │             │
          │                         │             │
          ▼                         │             │
     ┌────────┐    NG              │             │
     │  判定   │───────►───────────┘             │
     └────┬───┘     (4へ戻る)                    │
          │OK                                     │
          ▼                                       │
┌─────────────────┐   次のシーン                  │
│ 6. 次のシーン/章 │───────────────►──────────────┤
│                 │                   (4へ戻る)   │
└────────┬────────┘                              │
          │全シーン完了                            │
          ▼                         全章完了      │
┌─────────────────┐◄──────────────────────────────┘
│ 7. 章完了→次の章 │                   (2へ戻る)
└────────┬────────┘
          │
          ▼
┌─────────────────┐
│ 8. 全体整合性    │
│  - 伏線回収確認  │
│  - ペース調整   │
└────────┬────────┘
          │
          ▼
      [出力完了]
```

### 各ステップ詳細

| ステップ | 処理内容 | 成果物 |
|---------|---------|-------|
| 1. 章構成決定 | 三幕構成に基づく章分け | `chapter_structure` |
| 2. 章選択 | 次の章を取得 | `current_chapter` |
| 3. シーン分割 | 章内のシーン構成決定 | `scenes[]` |
| 4. シーン詳細化 | 各シーンの内容を具体化 | `scene_detail` |
| 5. シーン検証 | 品質と整合性確認 | `validation_result` |
| 6. 次のシーン | シーン完了、次へ進む | `completed_scenes[]` |
| 7. 章完了 | 章完了、次の章へ | `completed_chapters[]` |
| 8. 全体整合性 | 物語全体の確認 | `ScenarioOutput` |

### 品質チェック基準

各シーンは以下を満たすまでループ：

```typescript
interface SceneValidation {
  // 構造チェック
  has_clear_purpose: boolean;      // シーンの目的が明確か
  advances_plot: boolean;          // 物語が進展するか
  character_motivation: boolean;   // キャラの動機が明確か

  // フローチェック
  connects_previous: boolean;      // 前シーンと繋がるか
  leads_to_next: boolean;          // 次シーンへ繋がるか
  pacing_appropriate: boolean;     // テンポが適切か

  // ゲームプレイ
  has_player_agency: boolean;      // プレイヤーの行動機会があるか

  // 合格条件: 全てtrue
  passed: boolean;
}
```

### 感情曲線の管理

各章で感情の起伏を設計：

```
     感情強度
        ▲
    高  │        ╱╲
        │   ╱╲  ╱  ╲     ╱╲
    中  │  ╱  ╲╱    ╲   ╱  ╲
        │ ╱          ╲ ╱
    低  │╱            ╳
        └──────────────────────► 時間
         序盤   中盤   クライマックス
```

### リトライ上限

- 各シーン: 最大3回まで再生成
- 3回失敗時: Human確認を要求（`interrupt()`）
- 重要イベントシーン: 必ずHuman確認

---

## 入力スキーマ

```typescript
interface ScenarioInput {
  // Concept Agentからの出力（必須）
  concept: ConceptOutput;

  // Design Agentからの出力（必須）
  design: DesignOutput;

  // シナリオ固有の要望（任意）
  narrative_preferences?: {
    tone: "serious" | "light" | "dark" | "comedic";
    story_importance: "high" | "medium" | "low";  // ゲーム内での物語の重要度
    branching_complexity: "none" | "simple" | "complex";
    voice_acting: boolean;
  };

  // 前回フィードバック（修正時のみ）
  previous_feedback?: string;
  previous_output?: ScenarioOutput;
}
```

---

## 出力スキーマ

```typescript
interface ScenarioOutput {
  // === メタ情報 ===
  meta: {
    estimated_playtime_hours: number;     // 推定プレイ時間
    narrative_style: string;              // ナラティブスタイル
    tone: string;                         // トーン
    themes: string[];                     // テーマ
  };

  // === 基本設定 ===
  setting: {
    era: string;                          // 時代
    location: string;                     // 主要舞台
    situation: string;                    // 状況説明
    history: string;                      // 背景となる歴史
  };

  // === メインストーリー ===
  main_story: {
    premise: string;                      // 物語の前提
    central_conflict: string;             // 中心的な対立
    player_motivation: string;            // プレイヤーの動機
    stakes: string;                       // 賭けられているもの
    resolution_type: string;              // 解決のタイプ
  };

  // === 三幕構成 ===
  acts: Array<{
    act_number: number;
    name: string;
    summary: string;
    player_goal: string;                  // プレイヤーの目標
    emotional_arc: string;                // 感情の流れ
    gameplay_focus: string;               // ゲームプレイの焦点
  }>;

  // === チャプター/クエスト構造 ===
  chapters: Array<{
    id: string;
    title: string;
    act: number;
    summary: string;
    objectives: string[];                 // 達成目標
    gameplay_elements: string[];          // ゲームプレイ要素
    new_mechanics_introduced?: string[];  // 導入される新要素
    estimated_duration_minutes: number;
    emotional_beat: string;               // 感情的なポイント
    key_events: Array<{
      event_id: string;
      name: string;
      type: "story" | "gameplay" | "tutorial" | "boss";
      description: string;
      trigger: string;                    // 発生条件
      outcomes: string[];                 // 結果
    }>;
    rewards: string[];                    // 報酬
  }>;

  // === 重要イベント詳細 ===
  key_events: Array<{
    id: string;
    name: string;
    chapter_id: string;
    type: "cutscene" | "dialog" | "choice" | "battle" | "discovery";
    importance: "critical" | "major" | "minor";
    description: string;
    characters_involved: string[];
    location: string;
    prerequisites: string[];              // 前提条件
    dialog_summary?: string;              // ダイアログ概要
    choices?: Array<{                     // 選択肢（分岐がある場合）
      option: string;
      consequence: string;
      affects: string[];                  // 影響を受ける要素
    }>;
    gameplay_integration: string;         // ゲームプレイとの統合方法
  }>;

  // === 分岐・マルチエンディング（該当する場合） ===
  branching?: {
    branch_points: Array<{
      id: string;
      chapter_id: string;
      description: string;
      options: Array<{
        choice: string;
        path: string;
        long_term_effect: string;
      }>;
    }>;
    endings: Array<{
      id: string;
      name: string;
      requirements: string[];
      description: string;
      emotional_tone: string;
    }>;
  };

  // === ペーシング ===
  pacing: {
    tension_curve: string;                // 緊張曲線の説明
    rest_points: string[];                // 緩和ポイント
    climax_moments: string[];             // クライマックス
  };

  // === 実装ノート ===
  implementation_notes: {
    cutscene_count: number;
    estimated_dialog_lines: number;
    voice_acting_required: boolean;
    special_effects_needed: string[];
  };

  // === Human確認ポイント ===
  approval_questions: string[];
}
```

---

## ナラティブスタイル選定ガイド

| ゲームジャンル | 推奨スタイル | 特徴 |
|--------------|-------------|------|
| アクション | 環境ストーリーテリング | カットシーン最小、背景で語る |
| RPG | 対話中心 | NPC会話、選択肢、サイドクエスト |
| パズル | ミニマル | 謎解き自体が物語 |
| アドベンチャー | シネマティック | 演出重視、分岐多め |
| ローグライト | 断片的 | プレイごとに発見する物語 |

---

## 品質基準

### 必須条件
- [ ] ゲームのコアループと物語が統合されている
- [ ] プレイヤーの目標が各チャプターで明確
- [ ] 感情曲線が設計されている
- [ ] 実装可能なスコープに収まっている
- [ ] キャラクターの行動に一貫性がある

### 推奨条件
- [ ] チュートリアルが物語に組み込まれている
- [ ] サブクエストがメインストーリーを補強
- [ ] プレイヤーの選択に意味がある

---

## エラーハンドリング

| エラー状況 | 対応 |
|-----------|------|
| コンセプトのスコープとシナリオ量が不一致 | スコープに合わせて調整 |
| 技術制約で表現できない演出 | 代替演出を提案 |
| キャラクターAgentとの整合性問題 | 相互調整を提案 |
| 分岐が複雑すぎる | シンプル化した代替案を提示 |

---

## 出力例

```json
{
  "meta": {
    "estimated_playtime_hours": 8,
    "narrative_style": "環境ストーリーテリング + 重要シーンでの対話",
    "tone": "冒険的、時に緊迫",
    "themes": ["探求", "人類の遺産", "選択の重さ"]
  },

  "setting": {
    "era": "西暦3247年",
    "location": "銀河辺境セクター「ネビュラ・エッジ」",
    "situation": "300年前の大崩壊で地球との通信途絶。各コロニーが独自に発展。最近、古代文明の痕跡が発見され始めた。",
    "history": "人類は22世紀に銀河進出。25世紀の「大崩壊」で多くの技術が失われ、現在は復興途上。"
  },

  "main_story": {
    "premise": "無名のサルベージャーが偶然発見した座標データが、失われた地球への道を示していた",
    "central_conflict": "座標データを狙う勢力との競争、そして地球に何が起きたかの真実",
    "player_motivation": "富と名声から始まり、やがて人類の未来を賭けた選択へ",
    "stakes": "地球の技術を手に入れる者が銀河の覇権を握る",
    "resolution_type": "プレイヤーの選択により複数の結末"
  },

  "acts": [
    {
      "act_number": 1,
      "name": "発見",
      "summary": "主人公がデータを発見し、追われる身となる",
      "player_goal": "座標データの意味を解読し、最初の目的地へ",
      "emotional_arc": "好奇心 → 驚き → 危機感",
      "gameplay_focus": "基本操作習得、探索、クラフト基礎"
    },
    {
      "act_number": 2,
      "name": "追跡",
      "summary": "各勢力の思惑が交錯する中、古代の手がかりを追う",
      "player_goal": "3つの遺跡を巡り、地球への航路を完成させる",
      "emotional_arc": "成長 → 挫折 → 決意",
      "gameplay_focus": "宇宙船強化、戦闘、同盟構築"
    },
    {
      "act_number": 3,
      "name": "帰還",
      "summary": "地球への最終航海と、そこで待つ真実",
      "player_goal": "地球に到達し、未来を決める選択をする",
      "emotional_arc": "緊張 → 衝撃 → カタルシス",
      "gameplay_focus": "最終強化、ボス戦、選択と結末"
    }
  ],

  "chapters": [
    {
      "id": "ch01",
      "title": "残骸の中の宝",
      "act": 1,
      "summary": "廃棄宇宙ステーションでのサルベージ中、奇妙なデータチップを発見",
      "objectives": [
        "廃棄ステーションを探索",
        "データチップを発見",
        "追っ手から脱出"
      ],
      "gameplay_elements": ["探索", "移動チュートリアル", "逃走"],
      "new_mechanics_introduced": ["スキャン", "クラフト基礎"],
      "estimated_duration_minutes": 30,
      "emotional_beat": "平凡な日常から冒険の始まり",
      "key_events": [
        {
          "event_id": "ev01_01",
          "name": "データチップ発見",
          "type": "story",
          "description": "古代の記憶媒体に謎の座標データ",
          "trigger": "特定エリアのスキャン完了",
          "outcomes": ["メインクエスト開始", "追跡者出現"]
        },
        {
          "event_id": "ev01_02",
          "name": "追撃者との遭遇",
          "type": "gameplay",
          "description": "傭兵が襲来、逃走が必要",
          "trigger": "データチップ取得後",
          "outcomes": ["緊急脱出", "船体ダメージ"]
        }
      ],
      "rewards": ["基本宇宙船", "座標データ（断片）"]
    },
    {
      "id": "ch02",
      "title": "解読者",
      "act": 1,
      "summary": "データを解読できる人物を探してステーション・ノヴァへ",
      "objectives": [
        "ステーション・ノヴァに到着",
        "解読者ミラを見つける",
        "解読の対価を支払う"
      ],
      "gameplay_elements": ["航行", "NPC対話", "ミニクエスト"],
      "estimated_duration_minutes": 45,
      "emotional_beat": "世界の広がり、味方との出会い",
      "key_events": [
        {
          "event_id": "ev02_01",
          "name": "ミラとの出会い",
          "type": "dialog",
          "description": "風変わりな考古学者との最初の対話",
          "trigger": "酒場でのNPC聞き込み後",
          "outcomes": ["ミラがパーティ加入可能に", "解読クエスト開始"]
        }
      ],
      "rewards": ["航路マップ", "ミラ（仲間）"]
    }
  ],

  "key_events": [
    {
      "id": "ke_midpoint",
      "name": "裏切りの時",
      "chapter_id": "ch05",
      "type": "cutscene",
      "importance": "critical",
      "description": "信頼していた人物の裏切りが発覚",
      "characters_involved": ["player", "marcus", "mira"],
      "location": "遺跡内部",
      "prerequisites": ["ch04完了", "マーカス好感度中以上"],
      "dialog_summary": "マーカスが実は競合勢力のスパイだったことが判明。プレイヤーは戦うか説得するか選択",
      "choices": [
        {
          "option": "戦闘を選択",
          "consequence": "マーカス死亡、戦闘スキル経験値",
          "affects": ["エンディング", "ch06の展開"]
        },
        {
          "option": "説得を試みる",
          "consequence": "マーカス改心、情報入手",
          "affects": ["エンディング", "サブクエスト解放"]
        }
      ],
      "gameplay_integration": "選択後すぐにボス戦または対話イベント"
    }
  ],

  "branching": {
    "branch_points": [
      {
        "id": "bp01",
        "chapter_id": "ch05",
        "description": "マーカスへの対応",
        "options": [
          {
            "choice": "戦う",
            "path": "ソロルート",
            "long_term_effect": "最終戦の難易度上昇、独立エンディングへの道"
          },
          {
            "choice": "説得",
            "path": "同盟ルート",
            "long_term_effect": "援軍確保、協調エンディングへの道"
          }
        ]
      }
    ],
    "endings": [
      {
        "id": "end_solo",
        "name": "孤独な開拓者",
        "requirements": ["ソロルート", "地球到達"],
        "description": "単独で地球の技術を手に入れ、新たな時代の支配者となる",
        "emotional_tone": "達成感と孤独"
      },
      {
        "id": "end_unity",
        "name": "星々の架け橋",
        "requirements": ["同盟ルート", "全勢力和解"],
        "description": "各勢力が協力し、人類の再統合が始まる",
        "emotional_tone": "希望と団結"
      }
    ]
  },

  "pacing": {
    "tension_curve": "序盤で強烈なフック、中盤で緩急をつけながら上昇、終盤で最大緊張から解放",
    "rest_points": ["ch02 ステーション探索", "ch04 クルー交流イベント", "ch07 最終決戦前の準備"],
    "climax_moments": ["ch01 最初の追跡", "ch05 裏切り発覚", "ch08 最終ボス戦"]
  },

  "implementation_notes": {
    "cutscene_count": 8,
    "estimated_dialog_lines": 500,
    "voice_acting_required": false,
    "special_effects_needed": ["宇宙空間ワープ演出", "遺跡起動シーケンス", "最終決戦演出"]
  },

  "approval_questions": [
    "物語の複雑さ（分岐数）はこの程度で適切ですか？",
    "マーカスの裏切りイベントのタイミングは中盤で良いですか？",
    "エンディング数は2つで十分ですか？増やしますか？",
    "ボイスなしでダイアログ500行は多すぎますか？"
  ]
}
```

---

## 次のAgentへの引き継ぎ

このAgentの出力は以下のAgentに渡されます：

### Character Agent
- 物語に登場するキャラクターの役割
- 重要イベントでの関わり
- キャラクター間の関係性

### World Agent
- 物語の舞台となる場所
- 各勢力の設定
- 世界のルール

### TaskSplit Agent
- シナリオイベントの実装タスク
- カットシーン制作タスク
- ダイアログ実装タスク
