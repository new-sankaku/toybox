# TaskSplit Agent（タスク分解）

## 概要

| 項目 | 内容 |
|-----|------|
| **役割** | 企画成果物を開発タスクに分解 |
| **Phase** | Phase1: 企画（最終Agent） |
| **入力** | 全企画成果物（コンセプト〜世界観） |
| **出力** | イテレーション計画（JSON） |
| **Human確認** | タスク分割の妥当性・優先度・依存関係を確認 |

---

## システムプロンプト

```
あなたはゲーム開発プロジェクト管理の専門家「TaskSplit Agent」です。
企画成果物を実装可能な開発タスクに分解し、効率的なイテレーション計画を立てることが役割です。

## あなたの専門性
- ゲーム開発プロジェクトマネージャーとして15年以上の経験
- アジャイル/スクラム開発の実践者
- 技術的な実装工数の見積もり能力
- アセットパイプラインと開発フローの深い理解

## 行動指針
1. 各イテレーションで動くものが完成するよう計画
2. 依存関係を明確にし、ブロッカーを最小化
3. コードとアセットの並行開発を最適化
4. リスクの高いタスクを早期に配置
5. MVPから段階的に機能追加する構造

## 禁止事項
- 曖昧なタスク定義を避ける（「○○を改善」等）
- 依存関係を無視した順序付けをしない
- 1タスクに複数の責務を混ぜない
- 見積もり不能な巨大タスクを作らない
```

---

## 処理フロー

### Step 1: 機能リスト抽出
全企画成果物から実装すべき機能を網羅的に抽出：
- コンセプト → コア機能
- 設計 → 技術コンポーネント
- シナリオ → イベント/ダイアログシステム
- キャラクター → キャラクター実装
- 世界観 → マップ/システム実装

### Step 2: タスク分解
各機能を実装単位のタスクに分解：
```
機能 → サブ機能 → 実装タスク（1-3日で完了可能なサイズ）
```

### Step 3: 依存関係分析
- 技術的依存（AがないとBが実装できない）
- アセット依存（画像がないとコードが完成しない）
- シナリオ依存（前のイベントが必要）

### Step 4: イテレーション割り当て
依存関係と優先度に基づきイテレーションに配置：
```
イテレーション1: 基盤 + 最小限のゲームプレイ
イテレーション2: コア機能の充実
イテレーション3: コンテンツ追加
イテレーション4: 仕上げ + ポリッシュ
```

### Step 5: 計画書生成
構造化されたJSON形式で出力

---

## 内部処理ループ

TaskSplit Agentは以下のループで各タスクを分解・定義します：

### ループ図

```
┌─────────────────────────────────────────────────────────────┐
│                    TASK DECOMPOSITION LOOP                   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ 1. 大分類作成    │
                    │  - コードタスク  │
                    │  - アセットタスク │
                    │  - 統合タスク    │
                    └────────┬────────┘
                              │
          ┌───────────────────┴───────────────────┐
          ▼                                       │
┌─────────────────┐                              │
│ 2. 大タスク選択  │◄────────────────────────────┤
│                 │                              │
└────────┬────────┘                              │
          │                                       │
          ▼                                       │
┌─────────────────┐                              │
│ 3. サブタスク分解│                              │
│  - 1日単位に分割 │                              │
│  - 受入条件定義 │                               │
└────────┬────────┘                              │
          │                                       │
          ├─────────────────────────┐             │
          ▼                         │             │
┌─────────────────┐                │             │
│ 4. サブタスク    │◄───────────────┤             │
│    詳細化        │                │             │
│  - 入力/出力    │                 │             │
│  - 依存関係     │                 │             │
│  - 担当Agent    │                 │             │
└────────┬────────┘                │             │
          │                         │             │
          ▼                         │             │
┌─────────────────┐                │             │
│ 5. 依存関係検証  │                │             │
│  - 循環依存なし │                 │             │
│  - 順序妥当性   │                 │             │
└────────┬────────┘                │             │
          │                         │             │
          ▼                         │             │
     ┌────────┐    NG              │             │
     │  判定   │───────►───────────┘             │
     └────┬───┘     (4へ戻る)                    │
          │OK                                     │
          ▼                                       │
┌─────────────────┐   次のサブタスク              │
│ 6. 次のサブ/     │───────────────►──────────────┤
│    大タスクへ    │                   (4へ戻る)   │
└────────┬────────┘                              │
          │全タスク完了                            │
          ▼                                       │
┌─────────────────┐
│ 7. イテレーション │
│    割り当て      │
│  - 優先度順配置  │
│  - 依存考慮     │
└────────┬────────┘
          │
          ▼
┌─────────────────┐
│ 8. クリティカル  │
│    パス分析      │
└────────┬────────┘
          │
          ▼
      [出力完了]
```

### 各ステップ詳細

| ステップ | 処理内容 | 成果物 |
|---------|---------|-------|
| 1. 大分類作成 | 高レベルタスクカテゴリ分け | `task_categories` |
| 2. 大タスク選択 | 次のカテゴリを取得 | `current_category` |
| 3. サブタスク分解 | 1日単位に分割 | `subtasks[]` |
| 4. 詳細化 | 入出力・依存・担当を定義 | `task_detail` |
| 5. 依存検証 | 循環依存と順序確認 | `validation_result` |
| 6. 次へ | 完了リストに追加 | `completed_tasks[]` |
| 7. イテレーション割当 | タスクを各イテレーションに配置 | `iteration_plan` |
| 8. クリティカルパス | 遅延リスク分析 | `TaskSplitOutput` |

### 品質チェック基準

各タスクは以下を満たすまでループ：

```typescript
interface TaskValidation {
  // サイズチェック
  is_one_day_or_less: boolean;     // 1日以内で完了可能か
  is_atomic: boolean;              // これ以上分割不要か

  // 明確性
  has_clear_input: boolean;        // 入力が明確か
  has_clear_output: boolean;       // 出力が明確か
  has_acceptance_criteria: boolean; // 受入条件があるか

  // 依存関係
  dependencies_exist: boolean;     // 依存先が存在するか
  no_circular_deps: boolean;       // 循環依存がないか

  // 担当
  assignee_capable: boolean;       // 担当Agentが対応可能か

  // 合格条件: 全てtrue
  passed: boolean;
}
```

### タスク分解の粒度

```
大タスク（機能単位）
  │
  ├─ 中タスク（コンポーネント単位）
  │     │
  │     ├─ 小タスク（1日単位） ← これが基本単位
  │     │     - 明確な入力/出力
  │     │     - 受入条件3-5個
  │     │     - 1人で完結
  │     │
  │     └─ 小タスク
  │
  └─ 中タスク
        └─ 小タスク
```

### 依存関係の種類

```typescript
type DependencyType =
  | "code_to_code"      // コード→コード（モジュール依存）
  | "asset_to_code"     // アセット→コード（読み込み必要）
  | "code_to_asset"     // コード→アセット（仕様が必要）
  | "parallel"          // 並列実行可能
  | "sequential";       // 直列実行必須
```

### イテレーション配置ルール

```
イテレーション1: 基盤構築
  └─ 依存元なしのタスクを優先配置

イテレーション2: コア機能
  └─ イテ1の成果物に依存するタスク

イテレーション3: 拡張機能
  └─ コア機能の上に構築するタスク

イテレーション4: 統合・ポリッシュ
  └─ 全体統合、テスト、調整
```

### リトライ上限

- 各タスク: 最大3回まで再定義
- 3回失敗時: Human確認を要求（`interrupt()`）
- クリティカルパス上のタスク: 必ずHuman確認

---

## 入力スキーマ

```typescript
interface TaskSplitInput {
  // Phase1の全成果物（必須）
  concept: ConceptOutput;
  design: DesignOutput;
  scenario: ScenarioOutput;
  characters: CharacterOutput;
  world: WorldOutput;

  // プロジェクト制約（任意）
  constraints?: {
    team_size: number;
    iteration_length_days: number;
    total_iterations: number;
    parallel_asset_production: boolean;
  };

  // 前回フィードバック（修正時のみ）
  previous_feedback?: string;
  previous_output?: TaskSplitOutput;
}
```

---

## 出力スキーマ

```typescript
interface TaskSplitOutput {
  // === プロジェクト概要 ===
  project_summary: {
    total_iterations: number;
    estimated_total_days: number;
    mvp_iteration: number;              // MVPが完成するイテレーション
    risk_assessment: string;
  };

  // === イテレーション計画 ===
  iterations: Array<{
    number: number;
    name: string;                        // イテレーション名
    goal: string;                        // このイテレーションの目標
    deliverables: string[];              // 成果物リスト
    estimated_days: number;

    // コードタスク
    code_tasks: Array<{
      id: string;
      name: string;
      description: string;
      component: string;                 // 対応するDesign上のコンポーネント
      priority: "critical" | "high" | "medium" | "low";
      estimated_hours: number;
      depends_on: string[];              // 依存タスクID
      required_assets: string[];         // 必要アセットID
      acceptance_criteria: string[];     // 完了条件
      technical_notes?: string;          // 実装メモ
    }>;

    // アセットタスク
    asset_tasks: Array<{
      id: string;
      name: string;
      type: "sprite" | "background" | "ui" | "audio" | "animation" | "data";
      description: string;
      specifications: {
        format: string;                  // ファイル形式
        dimensions?: string;             // サイズ
        frames?: number;                 // アニメーションフレーム数
        duration?: number;               // 音声の長さ
      };
      reference: string;                 // 参照情報（キャラクターID等）
      priority: "critical" | "high" | "medium" | "low";
      estimated_hours: number;
      depends_on: string[];
      acceptance_criteria: string[];
    }>;

    // イテレーション完了条件
    completion_criteria: string[];
  }>;

  // === 依存関係マップ ===
  dependency_map: {
    code_to_code: Array<{
      from: string;
      to: string;
      reason: string;
    }>;
    asset_to_code: Array<{
      asset_id: string;
      code_id: string;
      reason: string;
    }>;
    critical_path: string[];             // クリティカルパス上のタスクID
  };

  // === リスク項目 ===
  risks: Array<{
    risk: string;
    impact: "high" | "medium" | "low";
    probability: "high" | "medium" | "low";
    mitigation: string;
    contingency: string;                 // 発生時の対応策
    affected_tasks: string[];
  }>;

  // === マイルストーン ===
  milestones: Array<{
    name: string;
    iteration: number;
    criteria: string[];
    stakeholder_demo: boolean;           // デモ実施するか
  }>;

  // === 統計情報 ===
  statistics: {
    total_code_tasks: number;
    total_asset_tasks: number;
    total_estimated_hours: number;
    tasks_by_priority: {
      critical: number;
      high: number;
      medium: number;
      low: number;
    };
    assets_by_type: Record<string, number>;
  };

  // === Human確認ポイント ===
  approval_questions: string[];
}
```

---

## タスク分解ガイドライン

### タスクサイズの目安

| サイズ | 時間 | 例 |
|-------|------|-----|
| S | 2-4時間 | 単一コンポーネントの小機能追加 |
| M | 4-8時間 | 標準的な機能実装 |
| L | 8-16時間 | 複雑な機能、複数ファイル |
| XL（要分割） | 16時間以上 | 分割が必要 |

### 依存関係の種類

| 種類 | 説明 | 対処 |
|------|------|-----|
| 技術的依存 | 基盤がないと実装不可 | 基盤を先に |
| アセット依存 | 画像/音声が必要 | プレースホルダーで先行 |
| 知識依存 | 仕様確認が必要 | 早期にHuman確認 |
| テスト依存 | テスト対象が必要 | テストタスクを後に |

### イテレーション構成パターン

```
【イテレーション1: 基盤】
- ゲームコア（起動、ループ、シーン管理）
- 基本入力
- プレースホルダーアセット

【イテレーション2: コアゲームプレイ】
- メインメカニクス
- 基本UI
- 仮アセット→本アセット差し替え

【イテレーション3: コンテンツ】
- 追加コンテンツ
- サブシステム
- 全アセット完成

【イテレーション4: ポリッシュ】
- バグ修正
- バランス調整
- エフェクト、SE追加
```

---

## 品質基準

### 必須条件
- [ ] 全ての企画要素がタスクでカバーされている
- [ ] 依存関係が明確で循環がない
- [ ] 各タスクの完了条件が具体的
- [ ] MVP達成イテレーションが明確
- [ ] クリティカルパスが特定されている

### 推奨条件
- [ ] タスクサイズが均一で見積もりしやすい
- [ ] リスクの高いタスクが早期に配置
- [ ] コードとアセットの並行作業が可能

---

## エラーハンドリング

| エラー状況 | 対応 |
|-----------|------|
| 依存関係の循環 | 設計の見直しを提案 |
| 見積もり不能なタスク | より詳細な分割を実施 |
| 企画の漏れを発見 | Phase1 Agentへのフィードバックを提案 |
| リソース制約で実現不可 | スコープ縮小を提案 |

---

## 出力例

```json
{
  "project_summary": {
    "total_iterations": 4,
    "estimated_total_days": 60,
    "mvp_iteration": 2,
    "risk_assessment": "中程度。宇宙船設計システムの複雑さがリスク要因"
  },

  "iterations": [
    {
      "number": 1,
      "name": "基盤構築",
      "goal": "ゲームが起動し、基本的な操作ができる状態",
      "deliverables": [
        "タイトル画面",
        "ゲームシーンの基本構造",
        "プレイヤー移動",
        "基本UI"
      ],
      "estimated_days": 12,

      "code_tasks": [
        {
          "id": "code_001",
          "name": "プロジェクト初期設定",
          "description": "Phaser3 + TypeScript + Viteのプロジェクト構築",
          "component": "GameCore",
          "priority": "critical",
          "estimated_hours": 4,
          "depends_on": [],
          "required_assets": [],
          "acceptance_criteria": [
            "npm run devでゲームが起動する",
            "TypeScriptの型チェックが通る",
            "空のゲーム画面が表示される"
          ],
          "technical_notes": "Phaser3のViteテンプレートをベースに構築"
        },
        {
          "id": "code_002",
          "name": "シーン管理システム",
          "description": "BootScene, PreloadScene, MenuScene, GameSceneの基本構造",
          "component": "GameCore",
          "priority": "critical",
          "estimated_hours": 8,
          "depends_on": ["code_001"],
          "required_assets": [],
          "acceptance_criteria": [
            "各シーン間の遷移が動作する",
            "シーン間でデータを受け渡せる",
            "前のシーンが適切に破棄される"
          ]
        },
        {
          "id": "code_003",
          "name": "アセットローダー",
          "description": "画像、音声、JSONの読み込みシステム",
          "component": "AssetManager",
          "priority": "critical",
          "estimated_hours": 6,
          "depends_on": ["code_002"],
          "required_assets": [],
          "acceptance_criteria": [
            "PreloadSceneでアセットが読み込まれる",
            "読み込み進捗が表示される",
            "エラー時に適切にハンドリングされる"
          ]
        },
        {
          "id": "code_004",
          "name": "プレイヤー移動",
          "description": "キーボード/タッチ入力による2D移動",
          "component": "PlayerController",
          "priority": "high",
          "estimated_hours": 8,
          "depends_on": ["code_002"],
          "required_assets": ["asset_001"],
          "acceptance_criteria": [
            "WASDキーで8方向移動",
            "タッチ/クリックで移動",
            "画面端で止まる",
            "スムーズなアニメーション"
          ]
        },
        {
          "id": "code_005",
          "name": "基本HUD",
          "description": "HP、通貨、ミニマップの枠組み",
          "component": "UIManager",
          "priority": "high",
          "estimated_hours": 6,
          "depends_on": ["code_002"],
          "required_assets": ["asset_002"],
          "acceptance_criteria": [
            "HPバーが表示される",
            "通貨量が表示される",
            "ミニマップ枠が表示される"
          ]
        }
      ],

      "asset_tasks": [
        {
          "id": "asset_001",
          "name": "プレイヤースプライト（仮）",
          "type": "sprite",
          "description": "主人公キャラクターの基本スプライト",
          "specifications": {
            "format": "PNG",
            "dimensions": "32x32",
            "frames": 4
          },
          "reference": "characters.player_character",
          "priority": "critical",
          "estimated_hours": 4,
          "depends_on": [],
          "acceptance_criteria": [
            "4方向の歩行アニメーション",
            "背景透過",
            "視認性が良い色使い"
          ]
        },
        {
          "id": "asset_002",
          "name": "UIアセット基本セット",
          "type": "ui",
          "description": "HUD用のUIパーツ",
          "specifications": {
            "format": "PNG",
            "dimensions": "各種"
          },
          "reference": "design.ui",
          "priority": "high",
          "estimated_hours": 6,
          "depends_on": [],
          "acceptance_criteria": [
            "HPバー（空/満）",
            "通貨アイコン",
            "フレーム/パネル"
          ]
        },
        {
          "id": "asset_003",
          "name": "テスト用背景",
          "type": "background",
          "description": "開発用の仮背景",
          "specifications": {
            "format": "PNG",
            "dimensions": "800x600"
          },
          "reference": "world.locations",
          "priority": "medium",
          "estimated_hours": 2,
          "depends_on": [],
          "acceptance_criteria": [
            "グリッド表示で移動確認しやすい",
            "境界が分かりやすい"
          ]
        }
      ],

      "completion_criteria": [
        "ゲームが起動してタイトル画面が表示される",
        "ゲーム開始でプレイヤーが移動できる",
        "基本UIが表示される",
        "エラーなく5分間プレイできる"
      ]
    },
    {
      "number": 2,
      "name": "コアゲームプレイ",
      "goal": "探索・収集・クラフトの基本ループが動作",
      "deliverables": [
        "探索システム",
        "アイテム収集",
        "簡易クラフト",
        "最初のダンジョン"
      ],
      "estimated_days": 18,

      "code_tasks": [
        {
          "id": "code_006",
          "name": "マップシステム",
          "description": "タイルマップの読み込みと衝突判定",
          "component": "WorldGenerator",
          "priority": "critical",
          "estimated_hours": 12,
          "depends_on": ["code_003"],
          "required_assets": ["asset_004"],
          "acceptance_criteria": [
            "Tiledマップが正しく読み込まれる",
            "壁との衝突判定が動作",
            "複数レイヤーの表示"
          ]
        },
        {
          "id": "code_007",
          "name": "インベントリシステム",
          "description": "アイテムの取得、保持、使用",
          "component": "InventorySystem",
          "priority": "critical",
          "estimated_hours": 10,
          "depends_on": ["code_005"],
          "required_assets": ["asset_005"],
          "acceptance_criteria": [
            "アイテムを拾える",
            "インベントリUIで確認できる",
            "アイテムを使用できる"
          ]
        },
        {
          "id": "code_008",
          "name": "クラフトシステム基礎",
          "description": "レシピに基づくアイテム合成",
          "component": "CraftingSystem",
          "priority": "high",
          "estimated_hours": 8,
          "depends_on": ["code_007"],
          "required_assets": [],
          "acceptance_criteria": [
            "レシピ一覧が表示される",
            "素材があれば合成できる",
            "結果がインベントリに追加される"
          ]
        },
        {
          "id": "code_009",
          "name": "敵AI基礎",
          "description": "パトロール、追跡、攻撃の基本AI",
          "component": "EnemyManager",
          "priority": "high",
          "estimated_hours": 10,
          "depends_on": ["code_006"],
          "required_assets": ["asset_006"],
          "acceptance_criteria": [
            "敵がパトロールする",
            "プレイヤーを発見すると追跡",
            "接触で攻撃（ダメージ）"
          ]
        }
      ],

      "asset_tasks": [
        {
          "id": "asset_004",
          "name": "ステーション・ノヴァ タイルセット",
          "type": "background",
          "description": "最初のハブエリアのタイル",
          "specifications": {
            "format": "PNG",
            "dimensions": "512x512 atlas"
          },
          "reference": "world.locations.loc_station_nova",
          "priority": "critical",
          "estimated_hours": 16,
          "depends_on": [],
          "acceptance_criteria": [
            "床、壁、ドアが含まれる",
            "ネオンサイン装飾",
            "統一感のあるスタイル"
          ]
        },
        {
          "id": "asset_005",
          "name": "アイテムアイコン基本セット",
          "type": "ui",
          "description": "基本アイテムのアイコン",
          "specifications": {
            "format": "PNG",
            "dimensions": "32x32"
          },
          "reference": "world.economy.resources",
          "priority": "high",
          "estimated_hours": 8,
          "depends_on": [],
          "acceptance_criteria": [
            "スクラップ、燃料、古代の破片",
            "識別しやすいデザイン",
            "16個以上"
          ]
        },
        {
          "id": "asset_006",
          "name": "セキュリティドローン",
          "type": "sprite",
          "description": "最初の敵キャラクター",
          "specifications": {
            "format": "PNG",
            "dimensions": "32x32",
            "frames": 8
          },
          "reference": "characters.enemies.enemy_drone",
          "priority": "high",
          "estimated_hours": 6,
          "depends_on": [],
          "acceptance_criteria": [
            "待機、移動アニメーション",
            "攻撃モーション",
            "破壊エフェクト"
          ]
        }
      ],

      "completion_criteria": [
        "ステーション・ノヴァを探索できる",
        "アイテムを収集してインベントリに入る",
        "基本クラフトができる",
        "敵と戦闘してダメージを受ける",
        "MVPとして人に見せられる状態"
      ]
    }
  ],

  "dependency_map": {
    "code_to_code": [
      { "from": "code_001", "to": "code_002", "reason": "プロジェクト基盤" },
      { "from": "code_002", "to": "code_003", "reason": "シーン構造" },
      { "from": "code_002", "to": "code_004", "reason": "GameScene必要" },
      { "from": "code_003", "to": "code_006", "reason": "アセット読み込み" },
      { "from": "code_005", "to": "code_007", "reason": "UI基盤" },
      { "from": "code_007", "to": "code_008", "reason": "インベントリ必要" }
    ],
    "asset_to_code": [
      { "asset_id": "asset_001", "code_id": "code_004", "reason": "プレイヤー表示" },
      { "asset_id": "asset_002", "code_id": "code_005", "reason": "HUD表示" },
      { "asset_id": "asset_004", "code_id": "code_006", "reason": "マップ表示" },
      { "asset_id": "asset_005", "code_id": "code_007", "reason": "アイテム表示" },
      { "asset_id": "asset_006", "code_id": "code_009", "reason": "敵表示" }
    ],
    "critical_path": ["code_001", "code_002", "code_003", "code_006", "code_009"]
  },

  "risks": [
    {
      "risk": "宇宙船設計システムの複雑さ",
      "impact": "high",
      "probability": "medium",
      "mitigation": "イテレーション3に配置、事前にプロトタイプ",
      "contingency": "機能を簡略化（テンプレート選択のみ）",
      "affected_tasks": ["code_020", "code_021"]
    },
    {
      "risk": "アセット制作の遅延",
      "impact": "medium",
      "probability": "medium",
      "mitigation": "プレースホルダーで開発継続",
      "contingency": "外部素材の活用",
      "affected_tasks": ["asset_004", "asset_007"]
    }
  ],

  "milestones": [
    {
      "name": "技術基盤完成",
      "iteration": 1,
      "criteria": ["ゲーム起動", "基本操作"],
      "stakeholder_demo": false
    },
    {
      "name": "MVP完成",
      "iteration": 2,
      "criteria": ["コアループ動作", "最初のエリア完成"],
      "stakeholder_demo": true
    },
    {
      "name": "コンテンツ完成",
      "iteration": 3,
      "criteria": ["全エリア実装", "ストーリー完結"],
      "stakeholder_demo": true
    },
    {
      "name": "リリース準備完了",
      "iteration": 4,
      "criteria": ["バグ修正完了", "最終調整完了"],
      "stakeholder_demo": true
    }
  ],

  "statistics": {
    "total_code_tasks": 35,
    "total_asset_tasks": 28,
    "total_estimated_hours": 480,
    "tasks_by_priority": {
      "critical": 12,
      "high": 18,
      "medium": 25,
      "low": 8
    },
    "assets_by_type": {
      "sprite": 8,
      "background": 6,
      "ui": 5,
      "audio": 6,
      "animation": 3
    }
  },

  "approval_questions": [
    "イテレーション2のMVP範囲は適切ですか？",
    "クリティカルパスに懸念はありますか？",
    "アセットとコードの並行開発計画は現実的ですか？",
    "リスク対策は十分ですか？"
  ]
}
```

---

## 次のAgentへの引き継ぎ

このAgentの出力は **Phase2** に渡されます：

### Code Leader（Phase2）
- イテレーションごとのcode_tasks
- 依存関係情報
- 優先度情報

### Asset Leader（Phase2）
- イテレーションごとのasset_tasks
- 仕様詳細
- コードとの依存関係

### Orchestrator
- マイルストーン情報
- リスク情報
- 全体スケジュール
