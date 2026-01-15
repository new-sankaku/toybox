# 実践例: Space Salvager開発ウォークスルー

## 概要

このドキュメントでは、「Space Salvager」というサンプルゲームを例に、
各Agentがどのように動作するかを具体的に示します。

---

## ゲーム概要

**Space Salvager（宇宙サルベージャー）**
- ジャンル: 2Dアクション・探索
- プラットフォーム: Web
- 概要: 宇宙の廃棄船を探索し、パーツを回収・売却するゲーム

---

## Phase 1: 企画フェーズ

### Step 1: Concept Agent

#### 入力

```json
{
  "user_idea": "宇宙を舞台にしたサルベージゲームを作りたい。廃棄された宇宙船を探索して、パーツを回収し、ステーションで売却する。プレイヤーは小型船を操作し、危険な廃棄船内を探索する。",
  "references": ["FTL", "Starbound", "Dead Space"],
  "constraints": {
    "platform": "web",
    "scope": "small"
  }
}
```

#### 内部処理ループ

```
[要素リスト作成]
  - コアループ定義
  - ジャンル・ターゲット
  - 差別化ポイント
  - MVP範囲
     │
     ▼
[コアループ定義] ← 最初の要素
  │
  ▼
[初期案生成]
  案1: 探索→回収→売却→アップグレード
  案2: 探索→戦闘→回収→修理
  案3: 探索→パズル→回収→製作
     │
     ▼
[詳細化: 案1を選択]
  - 探索: 廃棄船マップをリアルタイム移動
  - 回収: アイテムをインベントリに追加
  - 売却: ステーションで通貨に変換
  - アップグレード: 船の性能向上
     │
     ▼
[整合性チェック] ✓ OK
     │
     ▼
[次の要素: ジャンル・ターゲット] ...
```

#### 出力

```json
{
  "title": "Space Salvager",
  "genre": {
    "primary": "action_adventure",
    "secondary": ["exploration", "resource_management"]
  },
  "target_audience": {
    "age_range": "15-35",
    "player_type": "explorer",
    "session_length_minutes": 20
  },
  "core_loop": {
    "phases": [
      {
        "name": "探索",
        "action": "廃棄船内を移動・調査",
        "duration_percent": 50
      },
      {
        "name": "回収",
        "action": "パーツをインベントリに追加",
        "duration_percent": 20
      },
      {
        "name": "帰還",
        "action": "ステーションに戻る",
        "duration_percent": 10
      },
      {
        "name": "売却・強化",
        "action": "パーツ売却、船アップグレード",
        "duration_percent": 20
      }
    ],
    "motivation": "より良いパーツ、より危険な廃棄船への挑戦"
  },
  "unique_selling_points": [
    "リアルタイム宇宙船内探索",
    "廃棄船ごとのユニークなレイアウト",
    "緊張感のある酸素・燃料管理"
  ],
  "mvp_features": [
    "プレイヤー移動・操作",
    "廃棄船探索（3種類）",
    "アイテム回収・インベントリ",
    "ステーション・売却",
    "基本的な船アップグレード"
  ]
}
```

#### Human確認

```
[Concept完了]
- ゲームコンセプト「Space Salvager」を作成しました
- コアループ: 探索→回収→帰還→売却・強化
- MVP: 基本探索、3種類の廃棄船、アイテム売却、アップグレード

→ 承認 / 修正 / 却下
```

---

### Step 2: Design Agent

#### 入力

```json
{
  "concept": { /* ConceptAgent出力 */ },
  "tech_preferences": ["phaser", "typescript"]
}
```

#### 内部処理ループ

```
[コンポーネントリスト作成]
  - Core: GameConfig, Constants
  - Systems: InputSystem, PhysicsSystem, InventorySystem
  - Scenes: TitleScene, GameScene, StationScene
  - UI: HUD, InventoryUI, DialogUI
     │
     ▼
[GameConfig設計] ← Core層から開始
  │
  ▼
[責務定義]
  - ゲーム全体の設定値管理
  - 画面サイズ、物理設定等
     │
     ▼
[依存関係設計]
  - 依存なし（最下層）
     │
     ▼
[型定義作成]
  interface GameConfig {
    width: number;
    height: number;
    physics: PhysicsConfig;
    ...
  }
     │
     ▼
[品質チェック] ✓ OK
     │
     ▼
[次: InputSystem] ...
```

#### 出力（抜粋）

```json
{
  "tech_stack": {
    "engine": "phaser",
    "language": "typescript",
    "build_tool": "vite",
    "state_management": "custom_event_bus"
  },

  "architecture": {
    "pattern": "component_based",
    "layers": ["core", "systems", "entities", "scenes", "ui"]
  },

  "components": [
    {
      "name": "GameCore",
      "layer": "core",
      "responsibility": "ゲームの初期化・メインループ管理",
      "dependencies": [],
      "interface": {
        "methods": ["initialize()", "start()", "pause()", "resume()"],
        "events": ["game:ready", "game:pause", "game:resume"]
      }
    },
    {
      "name": "InputSystem",
      "layer": "systems",
      "responsibility": "入力処理・イベント発火",
      "dependencies": ["EventBus"],
      "interface": {
        "methods": ["update()", "isKeyDown(key)"],
        "events": ["input:move", "input:action", "input:cancel"]
      }
    },
    {
      "name": "InventorySystem",
      "layer": "systems",
      "responsibility": "インベントリ管理・アイテム操作",
      "dependencies": ["EventBus", "SaveSystem"],
      "interface": {
        "methods": ["addItem()", "removeItem()", "getItems()"],
        "events": ["inventory:add", "inventory:remove", "inventory:full"]
      }
    }
  ],

  "file_structure": {
    "src/": {
      "core/": ["GameCore.ts", "EventBus.ts", "Constants.ts"],
      "systems/": ["InputSystem.ts", "PhysicsSystem.ts", "InventorySystem.ts"],
      "entities/": ["Player.ts", "Item.ts", "Hazard.ts"],
      "scenes/": ["TitleScene.ts", "GameScene.ts", "StationScene.ts"],
      "ui/": ["HUD.ts", "InventoryUI.ts", "DialogUI.ts"]
    },
    "assets/": {
      "sprites/": [],
      "audio/": [],
      "data/": []
    }
  }
}
```

---

### Step 3: Character Agent

#### 入力

```json
{
  "scenario": { /* ScenarioAgent出力 */ },
  "design": { /* DesignAgent出力 */ }
}
```

#### 内部処理ループ

```
[キャラクターリスト作成]
  必要キャラクター:
  - プレイヤー（主人公）
  - ステーション店主
  - 情報屋NPC
  - 敵対ドローン（敵）
     │
     ▼
[プレイヤーキャラクター] ← 最初
  │
  ▼
[詳細設計]
  名前: カスタマイズ可能
  職業: サルベージャー
  背景: 借金返済のためサルベージを始めた
     │
     ▼
[ビジュアル指針]
  - 宇宙服姿
  - ヘルメットで顔は見えない
  - オレンジ系のカラー
     │
     ▼
[ゲームプレイ統合]
  - 移動速度: 基本値100
  - インベントリ: 10スロット
  - 特殊能力: なし（装備で拡張）
     │
     ▼
[品質チェック] ✓ OK
     │
     ▼
[次: ステーション店主] ...
```

#### 出力（抜粋）

```json
{
  "player_character": {
    "id": "player_001",
    "name": null,
    "customizable": true,
    "role": "サルベージャー（主人公）",
    "backstory_premise": "多額の借金を抱え、危険なサルベージ業に手を出した",
    "visual_design": {
      "silhouette": "humanoid_spacesuit",
      "primary_color": "#FF6B35",
      "secondary_color": "#1A1A2E",
      "distinctive_features": ["丸いヘルメット", "バックパック", "ツールベルト"]
    },
    "gameplay": {
      "base_speed": 100,
      "inventory_slots": 10,
      "oxygen_capacity": 100,
      "abilities": []
    }
  },

  "main_characters": [
    {
      "id": "npc_001",
      "name": "マーカス",
      "archetype": "mentor",
      "role_in_story": "主人公にサルベージの基本を教える",
      "role_in_gameplay": "チュートリアル、ヒント提供",
      "profile": {
        "age": 55,
        "occupation": "元サルベージャー、現ステーション店主"
      },
      "personality": {
        "traits": ["世話焼き", "皮肉屋", "経験豊富"],
        "speaking_style": "短い文、たまに昔話"
      },
      "visual_design": {
        "silhouette": "stocky_human",
        "primary_color": "#4A5568",
        "distinctive_features": ["白髪", "機械の義手", "エプロン"]
      }
    }
  ],

  "enemies": [
    {
      "id": "enemy_001",
      "name": "セキュリティドローン",
      "type": "minor_enemy",
      "behavior": "patrol",
      "combat": {
        "health": 30,
        "damage": 10,
        "attack_pattern": "接近して電撃"
      },
      "visual_design": {
        "silhouette": "floating_sphere",
        "primary_color": "#E53E3E",
        "animation_states": ["idle", "patrol", "alert", "attack"]
      }
    }
  ]
}
```

---

## Phase 2: 開発フェーズ

### イテレーション1: 基盤構築

#### Code Leader → Code Agents

```
Code Leader: タスク分配

[Task: code_001] → Core Agent
  - GameCore.ts実装
  - EventBus.ts実装

[Task: code_002] → System Agent
  - InputSystem.ts実装
  依存: EventBus（code_001完了後）

[Task: code_003] → Scene Agent
  - TitleScene.ts実装
  依存: GameCore, InputSystem
```

#### Code Agent (Core) 内部ループ

```
[タスク理解]
  GameCore: ゲーム初期化、Phaserセットアップ
     │
     ▼
[設計確認]
  Design仕様:
  - initialize(), start(), pause(), resume()
  - game:ready, game:pause, game:resumeイベント
     │
     ▼
[コード生成]
```

```typescript
// src/core/GameCore.ts
import Phaser from 'phaser';
import { EventBus } from './EventBus';
import { GAME_CONFIG } from './Constants';

export class GameCore {
  private game: Phaser.Game | null = null;
  private eventBus: EventBus;

  constructor() {
    this.eventBus = EventBus.getInstance();
  }

  initialize(): void {
    this.game = new Phaser.Game({
      type: Phaser.AUTO,
      width: GAME_CONFIG.width,
      height: GAME_CONFIG.height,
      physics: {
        default: 'arcade',
        arcade: { gravity: { y: 0 }, debug: false }
      },
      scene: []
    });

    this.game.events.once('ready', () => {
      this.eventBus.emit('game:ready');
    });
  }

  start(): void {
    if (!this.game) throw new Error('Game not initialized');
    this.game.scene.start('TitleScene');
  }

  pause(): void {
    this.game?.scene.pause();
    this.eventBus.emit('game:pause');
  }

  resume(): void {
    this.game?.scene.resume();
    this.eventBus.emit('game:resume');
  }
}
```

```
[自己レビュー]
  ✓ 全メソッド実装
  ✓ イベント発火
  ✓ エラーハンドリング
  ✓ 型安全
     │
     ▼
[Code Leaderに返却]
```

#### Asset Leader → Asset Agents

```
Asset Leader: タスク分配

[Task: asset_001] → Character Sprite Agent
  - player.png (プレイヤースプライト)
  優先度: HIGH（コード側がブロック）

[Task: asset_002] → Background Agent
  - title_bg.png (タイトル背景)
  優先度: NORMAL
```

#### Asset Agent (Character Sprite) 内部ループ

```
[要件確認]
  プレイヤースプライト
  - 宇宙服姿
  - オレンジ系カラー
  - 64x64px
  - 透過背景
  - アニメーション: idle, walk, action
     │
     ▼
[プロンプト構築]
  Base: "pixel art game character sprite, transparent background"
  Detail: "astronaut in orange spacesuit, round helmet, backpack,
           64x64 pixels, side view, walking animation frames"
  Negative: "realistic, 3d, blurry, low quality"
     │
     ▼
[生成実行]
  → 4候補生成
     │
     ▼
[後処理]
  - 背景除去
  - 64x64リサイズ
  - スプライトシート分割
     │
     ▼
[品質チェック]
  ✓ スタイル一致
  ✓ サイズ正確
  ✓ 透過OK
  ✗ アニメーションフレーム不足
     │
     ▼
[再生成: アニメーション部分]
  ...
     │
     ▼
[品質チェック] ✓ OK
     │
     ▼
[Asset Leaderに返却]
```

---

## Phase 3: 品質フェーズ

### Integrator Agent

#### 内部ループ

```
[成果物収集]
  Code: 12ファイル
  Assets: 8ファイル
     │
     ▼
[依存関係解析]
  npm packages: phaser@3.70.0, typescript@5.3.3
  local modules: 解決済み
  asset references: 全て存在
     │
     ▼
[ビルドステップ: npm ci]
  → 成功
     │
     ▼
[ビルドステップ: tsc]
  → 成功（警告2件）
     │
     ▼
[ビルドステップ: vite build]
  → 成功
     │
     ▼
[起動テスト]
  ✓ 起動OK
  ✓ タイトル画面表示
  ✓ アセット読み込み完了
  ✗ コンソール警告1件（非致命的）
     │
     ▼
[出力]
  build_status: success
  bundle_size: 1.2MB
  issues: 1 warning
```

### Tester Agent

#### 内部ループ

```
[テスト計画]
  Unit: 45 tests
  Integration: 12 tests
  E2E: 5 scenarios
  Performance: FPS, memory
     │
     ▼
[Unit Tests]
  GameCore: 8/8 passed
  EventBus: 6/6 passed
  InputSystem: 5/5 passed
  InventorySystem: 7/8 passed (1 failed)
  ...
     │
     ▼
[失敗テスト調査]
  InventorySystem.test.ts:45
  "should not exceed max capacity"
  Expected: 10, Actual: 11
     │
     ▼
[バグレポート生成]
  BUG-001: インベントリ上限超過バグ
  Severity: minor
  Reproduction: 同時に複数アイテム取得時
     │
     ▼
[E2E Tests]
  タイトル→ゲーム遷移: passed
  アイテム取得フロー: passed
  ステーション売却: passed
  セーブ/ロード: flaky (2/3 passed)
     │
     ▼
[Performance Tests]
  Average FPS: 58.5 (target: 60)
  Memory peak: 128MB
  Load time: 2.8s
     │
     ▼
[品質ゲート評価]
  ✓ Unit coverage: 85%
  ✓ Integration: 100%
  ✗ E2E: 93% (< 95%)
  ✗ FPS: 58.5 (< 60)
  ✓ Critical bugs: 0
     │
     ▼
[出力]
  quality_gate_passed: false
  blocking_issues: 2
```

### Reviewer Agent

#### 内部ループ

```
[レビュー対象収集]
  Phase1: concept, design, scenario, character, world, task_split
  Phase2: 12 code files, 8 assets
  Phase3: build, tests
     │
     ▼
[コード品質レビュー]
  Score: 8/10
  Issues:
  - minor: マジックナンバー使用 (InventorySystem:45)
  - suggestion: オブジェクトプール検討 (GameLoop:120)
     │
     ▼
[アセット品質レビュー]
  Score: 9/10
  Issues:
  - minor: 背景画像の彩度統一
     │
     ▼
[ゲームプレイレビュー]
  Score: 7/10
  UX: 操作直感的、インベントリUIやや煩雑
  Balance: 序盤のリソース獲得遅め
     │
     ▼
[仕様整合性]
  Compliance: 93%
  Missing: 実績システム（計画通り未実装）
     │
     ▼
[総合スコア算出]
  = 8*0.25 + 9*0.15 + 7*0.15 + 93*0.3/10 + 8*0.15
  = 2.0 + 1.35 + 1.05 + 2.79 + 1.2
  = 78.4 → 78
     │
     ▼
[リリース判定]
  Score: 78 (60-79 range)
  Blockers: 0 critical
  → CONDITIONAL
     │
     ▼
[Human確認]
  条件:
  1. インベントリバグ修正（必須）
  2. FPS最適化（推奨）
```

---

## Human確認ポイントまとめ

```
Phase1:
  [1] Concept承認 ✓
  [2] Design承認 ✓
  [3] Scenario承認 ✓
  [4] Character承認 ✓
  [5] World承認 ✓
  [6] TaskSplit承認 ✓

Phase2:
  [7] イテレーション1承認 ✓
  [8] イテレーション2承認 ✓
  [9] イテレーション3承認 ✓
  [10] イテレーション4承認 ✓

Phase3:
  [11] 統合ビルド承認 ✓
  [12] テスト結果承認 △（条件付き）
  [13] 最終リリース承認 → Human判断待ち

現在のステータス: CONDITIONAL
  - 必須修正: インベントリバグ
  - 推奨修正: FPS最適化

Human選択肢:
  A) 修正後リリース（推奨）
  B) 現状でリリース（リスク受容）
  C) 追加改善後リリース
```

---

## 完成物

### ファイル構成

```
space-salvager/
├── dist/                    # ビルド出力
│   ├── assets/
│   │   ├── main.js
│   │   ├── vendor.js
│   │   └── sprites/...
│   └── index.html
├── src/
│   ├── core/
│   │   ├── GameCore.ts
│   │   ├── EventBus.ts
│   │   └── Constants.ts
│   ├── systems/
│   │   ├── InputSystem.ts
│   │   ├── PhysicsSystem.ts
│   │   └── InventorySystem.ts
│   ├── entities/
│   │   ├── Player.ts
│   │   └── Item.ts
│   ├── scenes/
│   │   ├── TitleScene.ts
│   │   ├── GameScene.ts
│   │   └── StationScene.ts
│   └── ui/
│       ├── HUD.ts
│       └── InventoryUI.ts
├── assets/
│   ├── sprites/
│   │   ├── player.png
│   │   └── items.png
│   ├── audio/
│   │   └── bgm_title.mp3
│   └── data/
│       └── items.json
├── test/
│   └── *.test.ts
├── docs/
│   ├── concept.json
│   ├── design.json
│   └── ...
├── package.json
├── tsconfig.json
└── vite.config.ts
```

### 統計

| 項目 | 値 |
|------|-----|
| 開発期間 | 12.5時間（Agent稼働時間） |
| Human確認回数 | 13回 |
| コードファイル数 | 12 |
| アセットファイル数 | 8 |
| テスト数 | 62 |
| テストカバレッジ | 85% |
| バンドルサイズ | 1.2MB |
| 総合品質スコア | 78/100 |
