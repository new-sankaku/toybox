# Asset Leader（アセットリーダー）

## 概要

| 項目 | 内容 |
|-----|------|
| **役割** | アセット制作タスクの統括・品質管理 |
| **Phase** | Phase2: 開発 |
| **種別** | Leader Agent |
| **入力** | イテレーション計画のasset_tasks + キャラクター/世界観仕様 |
| **出力** | 制作済みアセット群 + 進捗レポート |
| **Human確認** | アセット品質・スタイル統一・方向性を確認 |

---

## システムプロンプト

```
あなたはゲーム開発チームのアセットリーダー「Asset Leader」です。
Phase1で作成された仕様に基づき、配下のAsset Agentを指揮して高品質なアセットを制作することが役割です。

## あなたの専門性
- アートディレクターとして15年以上の経験
- 2D/3Dアセット制作パイプラインの設計・運用
- スタイルガイドの策定と品質管理
- AI画像生成（DALL-E, Stable Diffusion等）の活用

## 行動指針
1. キャラクター/世界観仕様に忠実なアセット制作
2. 視覚的一貫性（スタイル、色調）の維持
3. 技術仕様（サイズ、形式）の厳守
4. Code Leaderとの密な連携（優先度調整）
5. 品質と制作速度のバランス

## 禁止事項
- 仕様から逸脱したデザインを独断で採用しない
- スタイルの不統一を放置しない
- 技術仕様を無視したアセットを納品しない
- ライセンス問題のある素材を使用しない
```

---

## 責務詳細

### 1. タスク管理

```
タスク受領 → 仕様確認 → Agent割り当て → 制作監督 → 品質検証 → 納品
```

- **優先度判定**: Code Leaderからのブロッキング要求を最優先
- **バッチ処理**: 類似アセットの一括制作
- **イテレーション管理**: プレースホルダー → 仮版 → 最終版

### 2. 配下Agent管理

動的に生成される専門Asset Agentを統括：

| Agent種別 | 担当領域 | 使用ツール |
|----------|---------|-----------|
| SpriteAgent | キャラクター、オブジェクトスプライト | DALL-E, 画像編集 |
| BackgroundAgent | 背景、タイルセット | DALL-E, タイル化処理 |
| UIAgent | UIパーツ、アイコン | ベクター生成、画像編集 |
| AnimationAgent | アニメーション、スプライトシート | フレーム生成、シート化 |
| AudioAgent | BGM、SE | 音声生成AI、編集 |
| DataAgent | JSONデータ、設定ファイル | 構造化データ生成 |

### 3. 品質管理

- **スタイル一貫性**: 全アセットのトーン・タッチ統一
- **技術仕様適合**: サイズ、形式、最適化
- **ゲーム内確認**: 実際のゲーム画面での見栄え

### 4. Code Leader連携

- **要求受信**: ブロッキングアセットの優先制作
- **プレースホルダー提供**: 開発継続のための仮アセット
- **納品通知**: 完成アセットの即時通知

---

## 内部処理ループ

Asset Leaderは以下のループでアセット制作を管理します：

### ループ図

```
┌─────────────────────────────────────────────────────────────┐
│                  ASSET LEADER PRODUCTION LOOP                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ 1. アセットリスト │
                    │    収集          │
                    │  - 計画タスク    │
                    │  - 緊急要求     │
                    └────────┬────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ 2. 優先度決定    │
                    │  - ブロッキング優先│
                    │  - 依存関係考慮  │
                    └────────┬────────┘
                              │
          ┌───────────────────┴───────────────────┐
          ▼                                       │
┌─────────────────┐                              │
│ 3. アセット選択  │◄────────────────────────────┤
│                 │                              │
└────────┬────────┘                              │
          │                                       │
          ▼                                       │
┌─────────────────┐                              │
│ 4. プレースホルダー│                             │
│    生成          │                              │
│  - 仮アセット作成 │                              │
│  - Code Leaderに通知│                           │
└────────┬────────┘                              │
          │                                       │
          ▼                                       │
┌─────────────────┐                              │
│ 5. 本制作        │                              │
│  - AI生成       │                               │
│  - プロンプト調整│                               │
│  - 後処理       │                               │
└────────┬────────┘                              │
          │                                       │
          ▼                                       │
┌─────────────────┐                              │
│ 6. 品質チェック  │                              │
│  - スタイル統一  │                              │
│  - 技術仕様     │                               │
│  - ゲーム内確認 │                               │
└────────┬────────┘                              │
          │                                       │
          ▼                                       │
     ┌────────┐    NG (max 3回)                  │
     │  判定   │─────────────┐                   │
     └────┬───┘              │                   │
          │OK                ▼                   │
          │         ┌─────────────┐              │
          │         │ 再生成      │              │
          │         │ (プロンプト調整)│            │
          │         └──────┬──────┘              │
          │                 │                     │
          │                 └──────►──────────────┘
          ▼                        (5へ戻る)
┌─────────────────┐
│ 7. 最終アセット  │
│    登録・通知    │
│  - バージョン更新│
│  - Code Leader通知│
└────────┬────────┘
          │
          ▼
┌─────────────────┐
│ 8. 次のアセットへ│─────────────────────────────►─┘
│  (残りがあれば)   │                    (3へ戻る)
└────────┬────────┘
          │全アセット完了
          ▼
┌─────────────────┐
│ 9. 一貫性最終確認│
│  - スタイル統一 │
│  - マニフェスト更新│
└────────┬────────┘
          │
          ▼
      [出力完了]
```

### アセットバージョン管理サイクル

```
[placeholder] ──► [draft] ──► [final]
     │              │           │
     ▼              ▼           ▼
 即時提供      レビュー用     本番使用
 (開発継続)    (確認依頼)    (完成品)
```

### 各ステップ詳細

| ステップ | 処理内容 | 成果物 |
|---------|---------|-------|
| 1. リスト収集 | 必要アセットを洗い出し | `asset_requests[]` |
| 2. 優先度決定 | ブロッキング/依存関係で並び替え | `prioritized_list` |
| 3. アセット選択 | 次のアセットを取得 | `current_asset` |
| 4. プレースホルダー | 仮アセット即時提供 | `placeholder_asset` |
| 5. 本制作 | AI生成+後処理 | `generated_asset` |
| 6. 品質チェック | スタイル/技術仕様確認 | `quality_result` |
| 7. 登録・通知 | 完成版をCode Leaderに通知 | `final_asset` |
| 8. 次へ | 残りがあれば継続 | `pending_assets[]` |
| 9. 最終確認 | 全体の一貫性確認 | `AssetLeaderOutput` |

### 品質チェック基準

各アセットは以下を満たすまでループ：

```typescript
interface AssetQualityValidation {
  // スタイル
  matches_style_guide: boolean;       // スタイルガイド準拠
  consistent_with_others: boolean;    // 他アセットと統一感
  appropriate_mood: boolean;          // 雰囲気が適切

  // 技術仕様
  correct_format: boolean;            // ファイル形式正しい
  correct_dimensions: boolean;        // サイズ/解像度正しい
  optimized_size: boolean;            // ファイルサイズ最適化
  transparent_bg_if_needed: boolean;  // 必要なら透過背景

  // ゲーム適合
  works_in_game: boolean;             // ゲーム内で正常表示
  animation_smooth: boolean;          // アニメーション滑らか(該当時)
  no_visual_artifacts: boolean;       // 視覚的不具合なし

  // 合格条件: 全てtrue
  passed: boolean;
}
```

### AI生成プロンプト調整サイクル

```
┌─────────────────────────────────────────┐
│         PROMPT REFINEMENT LOOP          │
└─────────────────────────────────────────┘

[基本プロンプト]
      │
      ▼
[生成実行] ───► [結果確認]
      ▲              │
      │              ▼
      │         品質OK？
      │           │    │
      │          No   Yes
      │           │    │
      │           ▼    ▼
      └─── [プロンプト調整]  [完了]
           - スタイル強調
           - ネガティブ追加
           - シード変更
```

### Code Leader連携プロトコル

```
Asset Leader                    Code Leader
     │                              │
     │ ◄── アセット要求 ─────────    │
     │     asset_id, priority       │
     │                              │
     │ ── プレースホルダー ──────►   │
     │    (version: "placeholder")  │
     │                              │
     │    [制作開始]                │
     │                              │
     │ ── Draft提出（任意）──────►  │
     │    (version: "draft")        │
     │                              │
     │ ◄── フィードバック ─────────  │
     │                              │
     │ ── 最終アセット ──────────►  │
     │    (version: "final")        │
     │                              │
```

### 優先度決定ロジック

```typescript
function calculatePriority(asset: AssetRequest): number {
  let priority = 0;

  // ブロッキング状態を最優先
  if (asset.is_blocking_code) {
    priority += 1000;
  }

  // 依存されている数が多いほど優先
  priority += asset.dependents.length * 100;

  // クリティカルパス上なら優先
  if (asset.on_critical_path) {
    priority += 500;
  }

  // 緊急要求は割り込み
  if (asset.urgency === "immediate") {
    priority += 2000;
  }

  return priority;
}
```

### リトライ上限

- 各アセット: 最大3回まで再生成
- 3回失敗時: Human確認を要求（`interrupt()`）
- キーアセット（キャラメイン等）: 必ずHuman確認

---

## 入力スキーマ

```typescript
interface AssetLeaderInput {
  // TaskSplit Agentからのイテレーション計画
  iteration: {
    number: number;
    asset_tasks: AssetTask[];
  };

  // 参照仕様
  character_spec: CharacterOutput;
  world_spec: WorldOutput;
  design_spec: DesignOutput;

  // Code Leaderからの要求
  code_leader_requests?: Array<{
    asset_id: string;
    urgency: "blocking" | "needed_soon" | "nice_to_have";
    placeholder_spec?: object;
  }>;

  // 前イテレーションからの引き継ぎ
  previous_assets?: {
    completed_assets: string[];
    style_guide_updates?: string[];
  };

  // Humanからのフィードバック
  feedback?: string;
}

interface AssetTask {
  id: string;
  name: string;
  type: "sprite" | "background" | "ui" | "audio" | "animation" | "data";
  description: string;
  specifications: {
    format: string;
    dimensions?: string;
    frames?: number;
    duration?: number;
  };
  reference: string;
  priority: "critical" | "high" | "medium" | "low";
  estimated_hours: number;
  depends_on: string[];
  acceptance_criteria: string[];
}
```

---

## 出力スキーマ

```typescript
interface AssetLeaderOutput {
  // === 実行サマリー ===
  summary: {
    iteration: number;
    total_tasks: number;
    completed_tasks: number;
    in_progress_tasks: number;
    blocked_tasks: number;
  };

  // === タスク実行結果 ===
  task_results: Array<{
    task_id: string;
    status: "completed" | "in_progress" | "blocked" | "revision_needed";
    assigned_agent: string;
    version: "placeholder" | "draft" | "final";

    // 完了時
    output?: {
      file_path: string;
      file_size_kb: number;
      dimensions?: string;
      format: string;
    };

    // 問題時
    issue?: {
      type: "quality" | "specification" | "technical" | "dependency";
      description: string;
      suggested_resolution: string;
    };

    // 品質チェック
    quality_check: {
      style_consistency: boolean;
      spec_compliance: boolean;
      visual_quality: "excellent" | "good" | "acceptable" | "needs_work";
      review_notes: string[];
    };
  }>;

  // === 生成アセット ===
  asset_outputs: Array<{
    asset_id: string;
    file_path: string;
    type: string;
    version: "placeholder" | "draft" | "final";
    metadata: {
      dimensions?: string;
      frames?: number;
      duration_seconds?: number;
      file_size_kb: number;
    };
    generation_prompt?: string;        // AI生成時のプロンプト記録
  }>;

  // === Code Leaderへの通知 ===
  code_leader_notifications: Array<{
    type: "asset_ready" | "asset_delayed" | "placeholder_available";
    asset_id: string;
    file_path?: string;
    estimated_completion?: string;
    can_proceed_with_placeholder: boolean;
  }>;

  // === スタイルガイド更新 ===
  style_guide_updates?: {
    color_palette_additions: string[];
    pattern_library_additions: string[];
    notes: string[];
  };

  // === Human確認必要事項 ===
  human_review_required: Array<{
    type: "style_approval" | "quality_concern" | "direction_change";
    asset_ids: string[];
    description: string;
    preview_paths: string[];
    options?: string[];
    recommendation: string;
  }>;
}
```

---

## 処理フロー

### アセット制作パイプライン

```
1. 仕様確認
   └─ キャラクター/世界観仕様の参照
   └─ 技術仕様の確認

2. プロンプト設計（AI生成の場合）
   └─ スタイルキーワード
   └─ 具体的な要素
   └─ ネガティブプロンプト

3. 生成/制作
   └─ AI生成 or 手動制作
   └─ 必要に応じて複数候補生成

4. 後処理
   └─ サイズ調整
   └─ 背景除去
   └─ 形式変換
   └─ 最適化

5. 品質確認
   └─ スタイル一貫性
   └─ 仕様適合
   └─ ゲーム内プレビュー

6. 納品
   └─ ファイル配置
   └─ Code Leaderへ通知
```

---

## AI画像生成プロンプトガイド

### 基本構造

```
[スタイル], [主題], [詳細], [背景], [技術指定]

例:
"pixel art style, space station interior, neon lights, bustling marketplace,
traders and robots, cyberpunk atmosphere, 32-bit color palette,
top-down perspective, game asset, transparent background"
```

### スタイルキーワード例

| カテゴリ | キーワード |
|---------|-----------|
| ピクセルアート | pixel art, 16-bit, 32-bit, retro game style |
| アニメ調 | anime style, cel shaded, japanese game art |
| 手描き風 | hand-drawn, illustrated, watercolor |
| SF | sci-fi, futuristic, cyberpunk, space opera |

### ネガティブプロンプト（避けるべき要素）

```
blurry, low quality, distorted, watermark, signature,
text, multiple characters (単体キャラの場合),
realistic photo (スタイル統一のため)
```

---

## 品質基準

### アセット品質チェックリスト

- [ ] 仕様のサイズ・形式に適合
- [ ] スタイルガイドに準拠
- [ ] 背景透過が正確（該当する場合）
- [ ] 色数/パレットが適切
- [ ] ゲーム内でのサイズ感が適切
- [ ] アニメーションが滑らか（該当する場合）
- [ ] ファイルサイズが最適化

### バージョン定義

| バージョン | 用途 | 品質 |
|-----------|------|------|
| placeholder | 開発用仮アセット | 単色/シンプル形状 |
| draft | レビュー用 | 概ね完成、調整可能性あり |
| final | 本番用 | 完全版、最適化済み |

---

## エラーハンドリング

| 状況 | 対応 |
|-----|------|
| AI生成の品質不足 | リトライ、プロンプト調整、手動修正 |
| スタイル不一致 | 参照画像追加、一貫性調整 |
| 仕様との乖離 | 仕様確認、必要なら仕様側を調整提案 |
| 技術的問題（形式等） | 変換処理、形式調整 |
| ライセンス問題 | 使用中止、代替制作 |

---

## 出力例

```json
{
  "summary": {
    "iteration": 1,
    "total_tasks": 6,
    "completed_tasks": 4,
    "in_progress_tasks": 1,
    "blocked_tasks": 1
  },

  "task_results": [
    {
      "task_id": "asset_001",
      "status": "completed",
      "assigned_agent": "SpriteAgent",
      "version": "final",
      "output": {
        "file_path": "assets/sprites/player.png",
        "file_size_kb": 12,
        "dimensions": "32x32",
        "format": "PNG"
      },
      "quality_check": {
        "style_consistency": true,
        "spec_compliance": true,
        "visual_quality": "excellent",
        "review_notes": ["シルエットが明確", "色使いが統一"]
      }
    },
    {
      "task_id": "asset_004",
      "status": "in_progress",
      "assigned_agent": "BackgroundAgent",
      "version": "draft",
      "issue": {
        "type": "quality",
        "description": "タイルの継ぎ目が目立つ",
        "suggested_resolution": "シームレス処理を追加"
      },
      "quality_check": {
        "style_consistency": true,
        "spec_compliance": true,
        "visual_quality": "needs_work",
        "review_notes": ["継ぎ目の調整が必要"]
      }
    }
  ],

  "asset_outputs": [
    {
      "asset_id": "asset_001",
      "file_path": "assets/sprites/player.png",
      "type": "sprite",
      "version": "final",
      "metadata": {
        "dimensions": "32x32",
        "frames": 4,
        "file_size_kb": 12
      },
      "generation_prompt": "pixel art style, space salvager character, orange and gray color scheme, utility suit, goggles, tool belt, 32x32 sprite, 4 directional walk cycle, transparent background, game asset"
    }
  ],

  "code_leader_notifications": [
    {
      "type": "asset_ready",
      "asset_id": "asset_001",
      "file_path": "assets/sprites/player.png",
      "can_proceed_with_placeholder": false
    },
    {
      "type": "asset_delayed",
      "asset_id": "asset_004",
      "estimated_completion": "2時間後",
      "can_proceed_with_placeholder": true
    }
  ],

  "style_guide_updates": {
    "color_palette_additions": ["#FF6B35 (アクセントオレンジ)"],
    "pattern_library_additions": ["ネオンサイン基本パターン"],
    "notes": ["SF要素は青/紫の発光を基調とする"]
  },

  "human_review_required": [
    {
      "type": "style_approval",
      "asset_ids": ["asset_004"],
      "description": "ステーション・ノヴァのタイルセット方向性確認",
      "preview_paths": ["previews/station_nova_tiles_v1.png"],
      "options": ["現在のサイバーパンク寄り", "よりクリーンなSF調"],
      "recommendation": "現在のサイバーパンク寄りがコンセプトに合致"
    }
  ]
}
```

---

## Code Leaderとの連携プロトコル

### 要求受信

```json
{
  "request_type": "asset_needed",
  "asset_id": "asset_001",
  "urgency": "blocking",
  "task_context": "code_004のPlayerController実装",
  "placeholder_spec": {
    "type": "sprite",
    "dimensions": "32x32",
    "color": "#FF0000"
  }
}
```

### 応答（プレースホルダー）

```json
{
  "response_type": "placeholder_available",
  "asset_id": "asset_001",
  "file_path": "assets/sprites/player_placeholder.png",
  "final_eta": "4時間後",
  "can_proceed": true
}
```

### 応答（完成）

```json
{
  "response_type": "asset_delivered",
  "asset_id": "asset_001",
  "file_path": "assets/sprites/player.png",
  "version": "final",
  "replaces_placeholder": true
}
```

---

## 次のAgentへの引き継ぎ

このAgentの出力は以下に渡されます：

### Integrator Agent（Phase3）
- 全asset_outputs
- ファイルパス一覧
- バージョン情報

### Code Leader（並行）
- 完成通知
- プレースホルダー情報
- 遅延情報

### Reviewer Agent（Phase3）
- アセット品質レポート
- スタイル一貫性情報
