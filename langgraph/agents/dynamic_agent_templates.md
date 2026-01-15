# 動的Agent テンプレート

## 概要

Phase2では、Code LeaderとAsset Leaderがタスクに応じて動的にサブAgentを生成します。
このドキュメントでは、動的生成されるAgentのテンプレートと生成ルールを定義します。

---

## Code Agent テンプレート

### 基本構造

```typescript
interface CodeAgentTemplate {
  // === Agent識別 ===
  id: string;                    // 例: "code_agent_core_001"
  type: CodeAgentType;
  task_id: string;               // 担当タスクID

  // === システムプロンプト ===
  system_prompt: string;         // 専門性に応じて生成

  // === 入出力 ===
  input: CodeAgentInput;
  output: CodeAgentOutput;

  // === 制約 ===
  constraints: {
    max_file_size_lines: number;
    allowed_dependencies: string[];
    coding_standards: string;
  };
}

type CodeAgentType =
  | "core"          // コアシステム実装
  | "system"        // ゲームシステム実装
  | "scene"         // シーン実装
  | "ui"            // UI実装
  | "utility"       // ユーティリティ実装
  | "test";         // テストコード作成
```

### Agent種別とシステムプロンプト

#### 1. Core Agent

```
あなたはゲームのコアシステムを実装する「Core Agent」です。

## 担当領域
- GameConfig, Constants, Types定義
- メインエントリーポイント
- 基盤クラス・インターフェース

## 技術スタック
- TypeScript (strict mode)
- 指定されたゲームエンジン（Phaser/PixiJS等）

## 行動指針
1. 他の全コンポーネントの基盤となる安定したコードを書く
2. 型定義を厳密に行い、型安全性を確保
3. 変更頻度の低い、堅牢な設計

## 禁止事項
- 外部状態への依存
- 循環参照の作成
- マジックナンバーの使用
```

#### 2. System Agent

```
あなたはゲームシステムを実装する「System Agent」です。

## 担当領域
- InputSystem, PhysicsSystem, AudioSystem等
- ゲームロジックの中核部分
- 状態管理システム

## 技術スタック
- TypeScript
- イベント駆動アーキテクチャ
- コンポーネントベース設計

## 行動指針
1. 単一責任の原則を守る
2. 他システムとはイベント経由で疎結合
3. テスタブルな設計

## 禁止事項
- 他システムへの直接参照
- グローバル状態の使用
- 非同期処理の不適切な扱い
```

#### 3. Scene Agent

```
あなたはゲームシーンを実装する「Scene Agent」です。

## 担当領域
- TitleScene, GameScene, ResultScene等
- シーン遷移ロジック
- シーン固有のUI・演出

## 技術スタック
- TypeScript
- ゲームエンジンのシーンシステム
- アセットローディング

## 行動指針
1. シーンのライフサイクルを正しく管理
2. メモリリークを防ぐ（リソース解放）
3. 遷移時の状態保持

## 禁止事項
- 他シーンへの直接参照
- シーン外のグローバル状態変更
- 重いオブジェクトのシーン間持ち越し
```

#### 4. UI Agent

```
あなたはUI/HUDを実装する「UI Agent」です。

## 担当領域
- HUD, メニュー, ダイアログ
- ボタン、テキスト、プログレスバー等
- レスポンシブ対応

## 技術スタック
- TypeScript
- DOM または Canvas UI
- アニメーションライブラリ

## 行動指針
1. ユーザビリティを最優先
2. アクセシビリティ考慮
3. パフォーマンスに配慮したレンダリング

## 禁止事項
- ゲームロジックの混入
- ハードコードされたサイズ・位置
- 入力イベントの握りつぶし
```

#### 5. Test Agent

```
あなたはテストコードを作成する「Test Agent」です。

## 担当領域
- ユニットテスト
- 統合テスト
- E2Eテストシナリオ

## 技術スタック
- Jest / Vitest
- Testing Library
- Playwright (E2E)

## 行動指針
1. 境界値・エッジケースを網羅
2. 読みやすいテスト名
3. Arrange-Act-Assertパターン

## 禁止事項
- 実装の詳細に依存したテスト
- 非決定的なテスト（Flaky）
- 外部サービスへの実際の接続
```

---

## Asset Agent テンプレート

### 基本構造

```typescript
interface AssetAgentTemplate {
  // === Agent識別 ===
  id: string;                    // 例: "asset_agent_sprite_001"
  type: AssetAgentType;
  task_id: string;               // 担当タスクID

  // === 生成設定 ===
  generation_config: {
    model: string;               // 使用するAIモデル
    base_prompt: string;         // ベースプロンプト
    style_guide: StyleGuide;     // スタイルガイド
  };

  // === 出力仕様 ===
  output_spec: {
    format: string;              // png, jpg, mp3等
    dimensions?: { width: number; height: number };
    color_profile?: string;
    quality?: number;
  };
}

type AssetAgentType =
  | "character_sprite"    // キャラクタースプライト
  | "background"          // 背景画像
  | "ui_element"          // UIパーツ
  | "effect"              // エフェクト
  | "icon"                // アイコン
  | "audio_bgm"           // BGM
  | "audio_se";           // 効果音
```

### Agent種別とプロンプトテンプレート

#### 1. Character Sprite Agent

```
あなたはキャラクタースプライトを生成する「Character Sprite Agent」です。

## 生成対象
- プレイヤーキャラクター
- NPC
- 敵キャラクター

## スタイル準拠
[StyleGuide参照]

## プロンプト構造
"[キャラクター名], [ポーズ/アクション], [スタイル指定],
 [背景: 透過], [アスペクト比], [品質指定]"

## 必須後処理
- 背景透過
- サイズ調整
- スプライトシート分割（アニメーション時）
```

#### 2. Background Agent

```
あなたは背景画像を生成する「Background Agent」です。

## 生成対象
- ゲーム背景
- タイトル画面背景
- メニュー背景

## スタイル準拠
[StyleGuide参照]

## プロンプト構造
"[場所/シーン], [時間帯], [雰囲気], [スタイル指定],
 [解像度], [遠近感指定]"

## 必須後処理
- 指定解像度への調整
- パララックス用レイヤー分割（必要時）
- タイルシームレス化（必要時）
```

#### 3. UI Element Agent

```
あなたはUIパーツを生成する「UI Element Agent」です。

## 生成対象
- ボタン（通常/ホバー/押下）
- フレーム、パネル
- アイコン、バッジ

## スタイル準拠
[StyleGuide参照]

## プロンプト構造
"[UI種類], [状態], [スタイル指定], [背景: 透過],
 [サイズ], [9-slice対応: yes/no]"

## 必須後処理
- 背景透過
- 状態別バリエーション生成
- 9-sliceガイド追加
```

#### 4. Audio BGM Agent

```
あなたはBGMを生成する「Audio BGM Agent」です。

## 生成対象
- タイトルBGM
- ゲームプレイBGM
- リザルトBGM

## スタイル準拠
[AudioStyleGuide参照]

## 生成指示構造
"[ジャンル], [テンポBPM], [雰囲気], [楽器構成],
 [長さ秒], [ループ: yes/no]"

## 必須後処理
- ループポイント設定
- 音量正規化
- フォーマット変換（mp3/ogg）
```

---

## 動的生成ロジック

### Code Agent生成

```typescript
function spawnCodeAgent(task: CodeTask): CodeAgent {
  // タスク種別からAgent種別を決定
  const agentType = determineCodeAgentType(task);

  // システムプロンプトを生成
  const systemPrompt = generateCodeSystemPrompt(agentType, task);

  // 制約を設定
  const constraints = {
    max_file_size_lines: 500,
    allowed_dependencies: task.dependencies,
    coding_standards: state.design.coding_standards,
  };

  return {
    id: `code_agent_${agentType}_${task.id}`,
    type: agentType,
    task_id: task.id,
    system_prompt: systemPrompt,
    input: {
      task_description: task.description,
      acceptance_criteria: task.acceptance_criteria,
      dependencies: task.dependencies,
      related_code: getRelatedCode(task),
    },
    output: {
      files: [],
      test_files: [],
    },
    constraints,
  };
}

function determineCodeAgentType(task: CodeTask): CodeAgentType {
  const typeMapping: Record<string, CodeAgentType> = {
    "core": "core",
    "system": "system",
    "scene": "scene",
    "ui": "ui",
    "util": "utility",
    "test": "test",
  };

  for (const [keyword, type] of Object.entries(typeMapping)) {
    if (task.component.toLowerCase().includes(keyword)) {
      return type;
    }
  }

  return "system"; // デフォルト
}
```

### Asset Agent生成

```typescript
function spawnAssetAgent(task: AssetTask): AssetAgent {
  // タスク種別からAgent種別を決定
  const agentType = determineAssetAgentType(task);

  // 生成設定を構築
  const generationConfig = buildGenerationConfig(agentType, task);

  // 出力仕様を設定
  const outputSpec = getOutputSpec(agentType, task);

  return {
    id: `asset_agent_${agentType}_${task.id}`,
    type: agentType,
    task_id: task.id,
    generation_config: generationConfig,
    output_spec: outputSpec,
  };
}

function buildGenerationConfig(
  type: AssetAgentType,
  task: AssetTask
): GenerationConfig {
  const styleGuide = state.design.style_guide;

  const basePrompts: Record<AssetAgentType, string> = {
    character_sprite: `${styleGuide.art_style}, game character sprite, transparent background`,
    background: `${styleGuide.art_style}, game background, detailed environment`,
    ui_element: `${styleGuide.ui_style}, game UI element, clean design`,
    effect: `${styleGuide.art_style}, game visual effect, transparent background`,
    icon: `${styleGuide.ui_style}, game icon, simple and clear`,
    audio_bgm: `${styleGuide.music_style}, game background music`,
    audio_se: `game sound effect, clear and distinct`,
  };

  return {
    model: "stable-diffusion-xl", // or other
    base_prompt: basePrompts[type],
    style_guide: styleGuide,
  };
}
```

---

## Agent内部処理ループ

### Code Agent ループ

```
┌─────────────────────────────────────────────────────────────┐
│                    CODE AGENT LOOP                           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ 1. タスク理解    │
                    │  - 要件分析     │
                    │  - 依存確認     │
                    └────────┬────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ 2. 設計確認      │
                    │  - インターフェース│
                    │  - 型定義       │
                    └────────┬────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ 3. コード生成    │
                    │  - 実装        │
                    │  - テスト      │
                    └────────┬────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ 4. 自己レビュー  │
                    │  - 基準照合     │
                    │  - 品質チェック │
                    └────────┬────────┘
                              │
                              ▼
                         ┌────────┐
                         │  判定   │
                         └────┬───┘
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
                  [OK]               [NG]
                    │                   │
                    ▼                   ▼
              [Code Leader      [修正して3へ]
               に返却]           (max 3回)
```

### Asset Agent ループ

```
┌─────────────────────────────────────────────────────────────┐
│                   ASSET AGENT LOOP                           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ 1. 要件確認      │
                    │  - 仕様理解     │
                    │  - スタイル確認 │
                    └────────┬────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ 2. プロンプト    │
                    │    構築          │
                    │  - ベース＋詳細 │
                    │  - ネガティブ   │
                    └────────┬────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ 3. 生成実行      │
                    │  - AI生成      │
                    │  - 複数候補    │
                    └────────┬────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ 4. 後処理        │
                    │  - 背景除去     │
                    │  - リサイズ     │
                    │  - 最適化      │
                    └────────┬────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ 5. 品質チェック  │
                    │  - スタイル     │
                    │  - 技術仕様    │
                    └────────┬────────┘
                              │
                              ▼
                         ┌────────┐
                         │  判定   │
                         └────┬───┘
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
                  [OK]               [NG]
                    │                   │
                    ▼                   ▼
              [Asset Leader     [プロンプト調整
               に返却]           して3へ]
                                 (max 3回)
```

---

## 品質チェック基準

### Code Agent 出力検証

```typescript
interface CodeAgentOutputValidation {
  // 機能要件
  meets_requirements: boolean;      // 受入条件を満たすか
  all_functions_implemented: boolean;

  // コード品質
  no_syntax_errors: boolean;        // 構文エラーなし
  no_type_errors: boolean;          // 型エラーなし
  follows_conventions: boolean;     // コーディング規約準拠
  no_code_smells: boolean;          // コードスメルなし

  // テスト
  tests_included: boolean;          // テストコードあり
  tests_pass: boolean;              // テスト通過

  // 合格条件
  passed: boolean;
}
```

### Asset Agent 出力検証

```typescript
interface AssetAgentOutputValidation {
  // スタイル
  matches_style_guide: boolean;     // スタイルガイド準拠
  consistent_quality: boolean;      // 品質一貫性

  // 技術仕様
  correct_format: boolean;          // 形式正しい
  correct_dimensions: boolean;      // サイズ正しい
  optimized: boolean;               // 最適化済み
  transparent_if_needed: boolean;   // 透過必要なら透過

  // 使用可能性
  no_artifacts: boolean;            // 視覚的不具合なし
  game_ready: boolean;              // ゲームで使用可能

  // 合格条件
  passed: boolean;
}
```

---

## リトライ上限

- 各動的Agent: 最大3回まで再実行
- 3回失敗時: Leaderにエスカレーション
- Leaderで解決不能: Human確認を要求（`interrupt()`）
