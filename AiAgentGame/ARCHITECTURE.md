# AI Agent Game Creator - システムアーキテクチャ仕様書

## 1. 概要

### 1.1 プロジェクト概要

Claude Codeのように対話形式でゲームを作成できるAI Agentシステム。
ユーザーが「シューティングゲームを作って」と指示すると、複数のAgentが協調して
企画・実装・アセット生成・テストを自動で行う。

### 1.2 設計思想

- **LLM非依存**: LangChainによる抽象化で、Claude/GPT/Deepseek等を切り替え可能
- **Claude Code併用**: 複雑なコーディングタスクはClaude Codeにファイル経由で委譲
- **コスト最適化**: 自前API・無料API・フリー素材を優先し、有料APIはフォールバック
- **リアルタイムフィードバック**: ファイルベースの簡易な仕組みでいつでも介入可能
- **並列処理**: 独立したタスクは並列実行で効率化
- **監視可能**: LangSmithによるトレース・デバッグ
- **ライセンス遵守**: フリー素材使用時は出典・ライセンス情報を必ず保存

---

## 2. システム全体構成

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          AI Agent Game Creator                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         LangGraph Layer                              │   │
│  │                    (Agent Orchestration)                             │   │
│  │                                                                      │   │
│  │   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐           │   │
│  │   │ Planner │──▶│  Coder  │──▶│ Tester  │──▶│Debugger │           │   │
│  │   │  Agent  │   │  Agent  │   │  Agent  │   │  Agent  │           │   │
│  │   └─────────┘   └─────────┘   └─────────┘   └─────────┘           │   │
│  │        │                                                            │   │
│  │        ▼                                                            │   │
│  │   ┌──────────────────────────────────────────────────────────┐    │   │
│  │   │              Asset Coordinator Agent                      │    │   │
│  │   ├──────────────────────────────────────────────────────────┤    │   │
│  │   │                         │                                 │    │   │
│  │   │    ┌─────────┐   ┌─────────┐   ┌─────────┐              │    │   │
│  │   │    │ Visual  │   │  Audio  │   │   UI    │              │    │   │
│  │   │    │  Agent  │   │  Agent  │   │  Agent  │   並列実行   │    │   │
│  │   │    └─────────┘   └─────────┘   └─────────┘              │    │   │
│  │   │                                                           │    │   │
│  │   └──────────────────────────────────────────────────────────┘    │   │
│  │                                                                      │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                      │                                       │
│                                      │ LLM呼び出し                           │
│                                      ▼                                       │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                         LangChain Layer                               │   │
│  │                      (LLM Abstraction)                                │   │
│  │                                                                       │   │
│  │   • LLM切り替え (Claude / GPT / Deepseek / 自前API)                  │   │
│  │   • Tool定義・実行                                                    │   │
│  │   • Prompt Template管理                                               │   │
│  │   • Memory / Context管理                                              │   │
│  │                                                                       │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                      │                                       │
│                                      │ ログ・トレース                        │
│                                      ▼                                       │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                         LangSmith Layer                               │   │
│  │                      (Monitoring & Debug)                             │   │
│  │                                                                       │   │
│  │   • 実行トレース可視化                                                │   │
│  │   • トークン使用量・コスト監視                                        │   │
│  │   • エラー追跡・デバッグ                                              │   │
│  │   • A/Bテスト・評価                                                   │   │
│  │                                                                       │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    File-based Feedback System                         │   │
│  │                   (Human-in-the-Loop)                                 │   │
│  │                                                                       │   │
│  │   📁 output/     ← Agent成果物出力                                   │   │
│  │   📁 feedback/   ← ユーザーフィードバック入力                        │   │
│  │   📁 status/     ← 進捗状況                                          │   │
│  │                                                                       │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    Claude Code Integration                            │   │
│  │                   (File-based Task Delegation)                        │   │
│  │                                                                       │   │
│  │   📁 claude_tasks/    ← タスク依頼ファイル出力                       │   │
│  │   📁 claude_results/  ← Claude Code実行結果                          │   │
│  │                                                                       │   │
│  │   使用例:                                                             │   │
│  │   • 複雑なリファクタリング                                           │   │
│  │   • バグ修正・デバッグ                                               │   │
│  │   • テストコード生成                                                 │   │
│  │   • コードレビュー                                                   │   │
│  │                                                                       │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Agent定義

### 3.1 Agent一覧

| Agent名 | 役割 | 入力 | 出力 |
|---------|------|------|------|
| **Planner Agent** | ゲーム企画・仕様策定・タスク分解 | ユーザー要求 | ゲーム仕様書、タスクリスト |
| **Coder Agent** | ゲームコード実装 | 仕様書、タスク | ソースコード |
| **Reviewer Agent** | コードレビュー・改善提案 | ソースコード | レビューコメント |
| **Tester Agent** | ゲーム実行・動作確認 | ソースコード、アセット | テスト結果 |
| **Debugger Agent** | バグ解析・修正 | エラー情報、コード | 修正コード |
| **Asset Coordinator** | アセット生成の振り分け | 仕様書 | サブAgentへの指示 |
| **Visual Agent** | 画像・3D・アニメーション生成 | 画像仕様 | 画像ファイル |
| **Audio Agent** | BGM・SE・ボイス生成 | 音声仕様 | 音声ファイル |
| **UI Agent** | アイコン・ロゴ・UI部品生成 | UI仕様 | UI素材 |

### 3.2 Agent詳細

#### 3.2.1 Planner Agent

```yaml
役割: ゲーム企画・設計
入力:
  - user_request: string  # ユーザーの要求
  - constraints: dict     # 制約条件（オプション）
出力:
  - game_spec: GameSpec   # ゲーム仕様
  - tasks: list[Task]     # 実行タスクリスト
使用Tool:
  - WebSearch: 参考情報検索
  - FileRead: 既存コード参照

振る舞い:
  1. 要求解析:
    - ユーザー要求からゲームジャンル・規模を判定
    - 曖昧な要求は具体化のため質問を生成
    - 実現可能性を評価（技術的制約、リソース制約）

  2. 仕様策定:
    - ゲームメカニクスを定義
    - 必要なアセット一覧を作成（画像/音声/UI）
    - ターゲットプラットフォームを決定（pygame/pyxel/html5）

  3. タスク分解:
    - 実装タスクを依存関係順にリスト化
    - 各タスクに優先度と見積もり難易度を付与
    - 並列実行可能なタスクを識別

  4. 出力:
    - game_spec.json を ./output/ に保存
    - フィードバック待機（30秒タイムアウト）
    - 承認後、次フェーズへ

エラー処理:
  - 要求が不明確 → 質問を生成してユーザーに確認
  - 実現不可能な要求 → 代替案を提示
```

#### 3.2.2 Coder Agent

```yaml
役割: ゲームコード実装
入力:
  - game_spec: GameSpec
  - task: Task
  - existing_code: dict[str, str]  # 既存コード
出力:
  - code_files: dict[str, str]     # ファイル名 → コード
使用Tool:
  - FileWrite: コード出力
  - FileRead: 既存コード参照
  - FileEdit: コード修正
  - BashExec: コマンド実行（pip install等）
  - ClaudeCodeDelegate: 複雑タスク委譲

振る舞い:
  1. タスク評価:
    - タスクの複雑度を評価（LOC予測、依存関係数）
    - 複雑度が閾値超え → Claude Codeに委譲
    - 閾値以下 → 自身で実装

  2. コード実装:
    - テンプレートから基本構造を生成
    - game_specに従ってロジックを実装
    - 既存コードとの整合性を確認

  3. 品質チェック:
    - 構文エラーチェック（AST解析）
    - 基本的なlintチェック
    - 依存パッケージの自動インストール

  4. 出力:
    - ./output/code/ にファイル保存
    - 変更ファイル一覧をログ出力

Claude Code委譲条件:
  - 100行以上の新規実装
  - 3ファイル以上にまたがる変更
  - 複雑なアルゴリズム実装
  - 大規模リファクタリング

エラー処理:
  - 構文エラー → 自動修正を試行（3回まで）
  - 修正失敗 → Claude Codeに委譲
  - 依存エラー → pip installで解決試行
```

#### 3.2.3 Asset Coordinator Agent

```yaml
役割: アセット生成の振り分けと統括
入力:
  - game_spec: GameSpec
  - asset_requirements: list[AssetRequirement]
出力:
  - visual_tasks: list[VisualTask]
  - audio_tasks: list[AudioTask]
  - ui_tasks: list[UITask]

振る舞い:
  1. アセット分析:
    - game_specから必要アセットを抽出
    - アセットをカテゴリ分類（visual/audio/ui）
    - 各アセットの優先度・依存関係を決定

  2. ソース選択判断:
    - 各アセットに対して取得方法を決定:
      a. フリー素材検索（最優先）
      b. 自前生成（ComfyUI/AudioCraft等）
      c. 有料API（フォールバック）
    - スタイル一貫性を考慮（同一ソース優先）

  3. タスク振り分け:
    - Visual Agent: キャラ、背景、エフェクト、スプライト
    - Audio Agent: BGM、SE、ボイス
    - UI Agent: アイコン、ボタン、フォント
    - 独立タスクは並列実行

  4. 進捗管理:
    - 各Sub-Agentの完了を監視
    - 失敗時はリトライ or 代替ソースで再試行
    - 全完了後、統合チェック

出力フォルダ構造:
  ./output/images/
    ├── characters/      # キャラクター画像
    ├── backgrounds/     # 背景画像
    ├── effects/         # エフェクト
    ├── sprites/         # スプライトシート
    └── raw/             # 生成元画像（処理前）
  ./output/audio/
    ├── bgm/             # BGM
    ├── se/              # 効果音
    └── voice/           # ボイス
  ./output/ui/
    ├── icons/           # アイコン
    ├── buttons/         # ボタン素材
    └── fonts/           # フォントファイル

エラー処理:
  - Sub-Agent失敗 → 代替ソースで再試行（最大3回）
  - 全ソース失敗 → プレースホルダー生成 + 警告
```

#### 3.2.4 Visual Agent

```yaml
役割: ビジュアルアセット生成
担当:
  - キャラクター画像（立ち絵、表情差分）
  - 背景画像
  - 3Dモデル
  - アニメーション・スプライト
  - エフェクト
使用API:
  優先度1（フリー素材）:
    - OpenGameArt.org             # ゲーム用フリー素材
    - itch.io (free assets)       # インディーゲーム素材
    - Kenney.nl                   # CC0ゲームアセット
    - 写真AC / イラストAC         # 日本語フリー素材
  優先度2（自前生成）:
    - ComfyUI (self-hosted)       # メイン：ローカルSD環境
    - Stable Diffusion WebUI      # 代替ローカル環境
  優先度3（有料）:
    - DALL-E 3                    # フォールバック
    - Midjourney API              # 高品質が必要な場合
  3D:
    - Blender (ローカル)
    - Sketchfab (CC素材)          # 3Dフリー素材
出典管理:
  - 使用素材ごとに attribution.json へ記録
  - ライセンス種別（CC0, CC-BY, etc.）を保存
  - 出典URL・作者名を必須記録

振る舞い:
  1. ソース選択:
    - まずフリー素材サイトを検索
    - 適合素材なし → ComfyUI/SDで生成
    - ローカル環境なし → 有料APIにフォールバック

  2. 画像生成（自前生成の場合）:
    - ComfyUIワークフローを実行
    - プロンプトはgame_specのvisual_styleに基づく
    - 生成元画像は ./output/images/raw/ に保存

  3. 後処理パイプライン:
    a. Upscale処理（必須）:
      - Real-ESRGAN または ESRGAN で高解像度化
      - 最低2倍、必要に応じて4倍まで
      - ゲーム用途に応じた解像度に調整

    b. キャラクター画像の場合（必須）:
      - 背景削除（rembg / Segment Anything）
      - 透過PNG形式で保存
      - エッジのアンチエイリアス処理

    c. スプライト画像の場合:
      - スプライトシート形式に結合
      - アニメーションフレーム情報をJSON出力

  4. フォルダ振り分け:
    - characters/ : キャラ立ち絵、表情差分
    - backgrounds/: 背景画像
    - effects/    : エフェクト、パーティクル
    - sprites/    : スプライトシート
    - raw/        : 処理前の生成元画像

  5. 品質チェック:
    - 解像度が要件を満たすか確認
    - キャラ画像の透過が正しいか確認
    - フィードバック待機（30秒）

後処理ツール:
  - Upscale: Real-ESRGAN, ESRGAN, ComfyUI Upscaler
  - 背景削除: rembg, Segment Anything (SAM)
  - 画像編集: Pillow, OpenCV

エラー処理:
  - 生成失敗 → プロンプト調整して再試行（3回）
  - Upscale失敗 → 代替アルゴリズムで再試行
  - 背景削除失敗 → 手動確認フラグを立てる
```

#### 3.2.5 Audio Agent

```yaml
役割: オーディオアセット生成
担当:
  - BGM（ループ対応）
  - 効果音（SE）
  - ジングル
  - ボイス（オプション）
使用API:
  優先度1（フリー素材）:
    - Freesound.org (CC素材)       # SE・環境音
    - OpenGameArt.org (audio)      # ゲーム用BGM/SE
    - DOVA-SYNDROME                # 日本語フリーBGM
    - 効果音ラボ                   # 日本語フリーSE
    - 魔王魂                       # 日本語フリーBGM/SE
  優先度2（自前生成）:
    - AudioCraft (Meta, ローカル)  # BGM/SE生成
    - Bark (ローカル)              # 音声合成
    - VOICEVOX (ローカル)          # 日本語音声
  優先度3（有料）:
    - Suno AI                      # 高品質BGM
    - ElevenLabs                   # 高品質音声
出典管理:
  - 使用素材ごとに attribution.json へ記録
  - ライセンス種別・利用規約URLを保存
  - クレジット表記要否を記録

振る舞い:
  1. ソース選択:
    - まずフリー素材サイトを検索（キーワード、BPM、ムード）
    - 適合素材なし → AudioCraft/Bark で生成
    - ローカル環境なし → 有料APIにフォールバック

  2. 音声生成（自前生成の場合）:
    - BGM: AudioCraftでプロンプトから生成
    - SE: AudioCraftまたは合成
    - ボイス: VOICEVOX（日本語）/ Bark（多言語）
    - 生成元は ./output/audio/raw/ に保存

  3. 後処理パイプライン:
    a. BGMの場合（必須）:
      - ループポイント検出・設定
      - シームレスループ加工（クロスフェード）
      - 音量ノーマライズ（-14 LUFS目安）
      - フェードイン/アウト追加（オプション）

    b. SEの場合（必須）:
      - 無音トリミング（前後の無音除去）
      - 音量ノーマライズ
      - 必要に応じてピッチ/速度調整

    c. ボイスの場合:
      - ノイズ除去
      - 音量ノーマライズ
      - 無音トリミング

  4. フォーマット変換:
    - BGM: OGG形式（ループ対応）、MP3（フォールバック）
    - SE: WAV形式（低レイテンシ）、OGG（容量重視）
    - メタデータ（BPM、ループポイント等）をJSON出力

  5. フォルダ振り分け:
    - bgm/   : BGM、ジングル
    - se/    : 効果音
    - voice/ : ボイス、セリフ
    - raw/   : 処理前の生成元音声

  6. 品質チェック:
    - ループ再生テスト（BGM）
    - 音量バランス確認
    - フィードバック待機（30秒）

後処理ツール:
  - 音声編集: pydub, librosa, FFmpeg
  - ノーマライズ: pyloudnorm
  - ノイズ除去: noisereduce, RNNoise

エラー処理:
  - 生成失敗 → プロンプト調整して再試行（3回）
  - ループ加工失敗 → 手動確認フラグを立てる
  - フォーマット変換失敗 → 代替形式で出力
```

#### 3.2.6 UI Agent

```yaml
役割: UIアセット生成
担当:
  - ゲームアイコン
  - タイトルロゴ
  - ボタン・メニュー素材
  - HUD要素
  - フォント選定
使用API:
  優先度1（フリー素材）:
    - Google Fonts (無料)          # Webフォント
    - Font Awesome (無料)          # アイコンフォント
    - Heroicons / Lucide           # UIアイコン (MIT)
    - game-icons.net               # ゲーム用アイコン (CC-BY)
    - Kenney UI Pack               # UI素材 (CC0)
  優先度2（自前生成）:
    - ComfyUI (self-hosted)        # Visual Agentと共有
  優先度3（有料）:
    - DALL-E 3                     # フォールバック
    - Figma API                    # 複雑なUI設計時
出典管理:
  - 使用素材ごとに attribution.json へ記録
  - フォントライセンス（OFL, Apache等）を保存
  - アイコンライセンス・帰属表示を記録

振る舞い:
  1. ソース選択:
    - フォント → Google Fonts優先
    - アイコン → game-icons.net, Heroicons優先
    - ボタン/HUD → Kenney UI Pack優先
    - 適合素材なし → ComfyUIで生成

  2. UI素材生成（自前生成の場合）:
    - game_specのvisual_styleに合わせたプロンプト
    - 統一感のあるデザインを維持
    - 生成元は ./output/ui/raw/ に保存

  3. 後処理パイプライン:
    a. アイコン/ボタンの場合:
      - 適切なサイズにリサイズ（16x16, 32x32, 64x64等）
      - 透過PNG形式で保存
      - 複数サイズバリエーションを生成

    b. ロゴの場合:
      - 高解像度版とサムネイル版を生成
      - 背景透過版を作成
      - SVG形式への変換（可能な場合）

    c. フォントの場合:
      - ゲームエンジン対応形式に変換（TTF/OTF）
      - サブセット化（使用文字のみ抽出）

  4. フォルダ振り分け:
    - icons/   : ゲームアイコン、システムアイコン
    - buttons/ : ボタン、メニュー素材
    - hud/     : HUD要素、ゲージ、枠
    - logos/   : タイトルロゴ
    - fonts/   : フォントファイル
    - raw/     : 処理前の生成元素材

  5. スタイル統一チェック:
    - カラーパレットの一貫性確認
    - デザイントーンの統一確認
    - フィードバック待機（30秒）

エラー処理:
  - 生成失敗 → プロンプト調整して再試行（3回）
  - フォント変換失敗 → 代替フォントを提案
```

#### 3.2.7 Reviewer Agent

```yaml
役割: コードレビュー・改善提案
入力:
  - code_files: dict[str, str]  # レビュー対象コード
  - game_spec: GameSpec         # 仕様との照合用
出力:
  - review_comments: list[ReviewComment]
  - approval_status: bool
使用Tool:
  - FileRead: コード読み取り
  - ClaudeCodeDelegate: 詳細レビュー委譲

振る舞い:
  1. 静的解析:
    - lint/formatチェック（ruff, black）
    - 型チェック（mypy）
    - セキュリティチェック（bandit）

  2. ロジックレビュー:
    - game_specとの整合性確認
    - エッジケースの検出
    - パフォーマンス問題の指摘

  3. Claude Code委譲条件:
    - 複雑なロジックの妥当性検証
    - アーキテクチャ全体の評価
    - リファクタリング提案

  4. 出力:
    - 各指摘にseverity（error/warning/info）付与
    - 修正提案コードを含める
    - 承認/差し戻し判定

判定基準:
  - error: 0件 → 承認可能
  - error: 1件以上 → 差し戻し
  - warning: 5件以上 → 差し戻し検討
```

#### 3.2.8 Tester Agent

```yaml
役割: ゲーム実行・動作確認
入力:
  - code_files: dict[str, str]
  - assets: dict[str, str]       # アセットファイルパス
  - game_spec: GameSpec
出力:
  - test_results: TestResults
  - screenshots: list[str]       # 実行画面キャプチャ
使用Tool:
  - BashExec: ゲーム実行
  - FileRead: ログ確認
  - ClaudeCodeDelegate: テストコード生成

振る舞い:
  1. 環境準備:
    - 依存パッケージのインストール確認
    - アセットファイルの配置確認
    - 仮想ディスプレイ準備（headless環境）

  2. 自動テスト実行:
    - 起動テスト（クラッシュしないか）
    - 基本操作テスト（入力応答）
    - 画面キャプチャ取得

  3. テスト項目:
    a. 起動テスト:
      - 正常起動するか
      - 初期画面が表示されるか
      - エラーログがないか

    b. 機能テスト:
      - game_specの各mechanicsが動作するか
      - アセットが正しく読み込まれるか
      - 音声が再生されるか

    c. 安定性テスト:
      - 長時間実行でメモリリークないか
      - 連続操作でクラッシュしないか

  4. Claude Code委譲条件:
    - ユニットテストコードの生成
    - 複雑なテストシナリオの作成

  5. 出力:
    - テスト結果サマリー
    - 失敗テストの詳細ログ
    - スクリーンショット

判定基準:
  - 起動テスト失敗 → Debugger Agentへ
  - 機能テスト一部失敗 → 警告付きで続行可
  - 全テスト成功 → 完了
```

#### 3.2.9 Debugger Agent

```yaml
役割: バグ解析・修正
入力:
  - error_info: ErrorInfo        # エラー情報
  - code_files: dict[str, str]
  - test_results: TestResults
出力:
  - fixed_code: dict[str, str]
  - fix_summary: str
使用Tool:
  - FileRead: コード読み取り
  - FileEdit: コード修正
  - BashExec: 修正確認実行
  - ClaudeCodeDelegate: 複雑なバグ修正

振る舞い:
  1. エラー解析:
    - スタックトレース解析
    - エラー種別の特定
    - 原因箇所の特定

  2. 修正戦略決定:
    - 単純なエラー → 自動修正
    - 複雑なエラー → Claude Codeに委譲
    - ロジックエラー → Claude Codeに委譲

  3. 自動修正対象:
    - ImportError → パッケージインストール
    - SyntaxError → 構文修正
    - TypeError（単純） → 型変換追加
    - FileNotFoundError → パス修正

  4. Claude Code委譲条件:
    - ロジックバグ
    - 複数ファイルにまたがるバグ
    - 原因特定が困難なバグ
    - 3回修正しても解決しない

  5. 修正確認:
    - 修正後に再テスト実行
    - 同じエラーが出ないか確認
    - 新たなエラーが出ていないか確認

  6. 出力:
    - 修正内容のサマリー
    - 変更ファイル一覧
    - 修正理由の説明

リトライ制限:
  - 同一エラー: 最大3回
  - 全体リトライ: 最大10回
  - 超過 → 人間介入を要求
```

---

## 4. データ構造

### 4.1 State（状態）定義

```python
from typing import TypedDict, Optional
from enum import Enum

class Phase(Enum):
    PLANNING = "planning"
    CODING = "coding"
    ASSET_GENERATION = "asset_generation"
    TESTING = "testing"
    DEBUGGING = "debugging"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class ArtifactStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    NEEDS_REVISION = "needs_revision"
    APPROVED = "approved"

class Artifact(TypedDict):
    id: str
    type: str              # "image", "audio", "code", "ui"
    agent: str             # 生成したAgent名
    file_path: str         # 出力ファイルパス
    status: ArtifactStatus
    feedback_history: list[dict]

class Task(TypedDict):
    id: str
    type: str              # "code", "visual", "audio", "ui"
    description: str
    assigned_agent: str
    status: str
    dependencies: list[str]  # 依存するタスクID

class GameSpec(TypedDict):
    title: str
    genre: str
    description: str
    mechanics: list[str]
    visual_style: str
    audio_style: str
    target_platform: str   # "pygame", "html5", "pyxel"

class GameState(TypedDict):
    # ユーザー入力
    user_request: str

    # 企画
    game_spec: Optional[GameSpec]
    tasks: list[Task]

    # 成果物
    artifacts: dict[str, Artifact]
    code_files: dict[str, str]

    # レビュー・テスト
    review_comments: list[dict]
    test_results: Optional[dict]
    errors: list[dict]

    # 制御
    current_phase: Phase
    iteration: int

    # フィードバック
    pending_feedback: list[dict]
```

### 4.2 フィードバック構造

```python
class Feedback(TypedDict):
    artifact_id: str       # 対象の成果物ID
    action: str            # "approve", "redo", "fix", "comment"
    comment: str           # ユーザーコメント
    timestamp: float
    processed: bool
```

### 4.3 出典情報（Attribution）構造

```python
class Attribution(TypedDict):
    asset_id: str           # 対象アセットID
    asset_type: str         # "image", "audio", "font", "icon"
    source_type: str        # "free_asset", "generated", "purchased"

    # フリー素材の場合
    source_url: str         # 素材の出典URL
    source_name: str        # サイト名 (e.g., "OpenGameArt.org")
    author: str             # 作者名
    license: str            # ライセンス種別 (e.g., "CC0", "CC-BY-4.0", "OFL")
    license_url: str        # ライセンス全文URL
    requires_credit: bool   # クレジット表記が必要か
    credit_text: str        # 必要な場合のクレジット表記文

    # メタ情報
    downloaded_at: str      # ダウンロード日時
    notes: str              # 備考（利用規約の特記事項等）
```

### 4.4 Claude Code連携構造

```python
class ClaudeCodeTask(TypedDict):
    task_id: str            # タスクID
    task_type: str          # "refactor", "debug", "test", "review"
    description: str        # タスク説明
    target_files: list[str] # 対象ファイルパス
    context: str            # 追加コンテキスト
    priority: str           # "high", "medium", "low"
    created_at: str
    status: str             # "pending", "in_progress", "completed", "failed"

class ClaudeCodeResult(TypedDict):
    task_id: str            # 対応するタスクID
    success: bool
    modified_files: list[str]
    summary: str            # 実行結果の要約
    errors: list[str]       # エラーがあれば
    completed_at: str
```

---

## 5. ワークフロー

### 5.1 メインフロー

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Main Workflow                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   START                                                                      │
│     │                                                                        │
│     ▼                                                                        │
│   ┌─────────────────┐                                                       │
│   │  Planner Agent  │                                                       │
│   │   企画立案      │                                                       │
│   └────────┬────────┘                                                       │
│            │                                                                 │
│            ▼                                                                 │
│   ┌─────────────────┐    feedback    ┌─────────────────┐                   │
│   │  Output: spec   │───────────────▶│  User Review    │                   │
│   │  仕様書出力     │◀───────────────│  (file-based)   │                   │
│   └────────┬────────┘    approve/    └─────────────────┘                   │
│            │              revise                                             │
│            ▼                                                                 │
│   ┌─────────────────────────────────────────────────────────┐              │
│   │                    Parallel Execution                    │              │
│   │  ┌─────────────┐              ┌─────────────────────┐  │              │
│   │  │ Coder Agent │              │ Asset Coordinator   │  │              │
│   │  │  コード実装  │              │  アセット振り分け   │  │              │
│   │  └──────┬──────┘              └──────────┬──────────┘  │              │
│   │         │                                 │             │              │
│   │         │                    ┌────────────┼────────────┐│              │
│   │         │                    ▼            ▼            ▼│              │
│   │         │              ┌─────────┐ ┌─────────┐ ┌─────────┐            │
│   │         │              │ Visual  │ │  Audio  │ │   UI    │            │
│   │         │              │  Agent  │ │  Agent  │ │  Agent  │            │
│   │         │              └────┬────┘ └────┬────┘ └────┬────┘            │
│   │         │                   │           │           │     │            │
│   │         │                   └───────────┴───────────┘     │            │
│   │         │                              │                  │            │
│   │         ▼                              ▼                  │            │
│   │   ┌──────────┐                  ┌──────────┐             │            │
│   │   │  Output  │                  │  Output  │             │            │
│   │   │   Code   │                  │  Assets  │             │            │
│   │   └──────────┘                  └──────────┘             │            │
│   │         │                              │                  │            │
│   │         └──────────────┬───────────────┘                  │            │
│   └────────────────────────┼──────────────────────────────────┘            │
│                            ▼                                                │
│   ┌─────────────────────────────────────────────────────────┐              │
│   │                     Feedback Check                       │              │
│   │           (各成果物に対するフィードバック確認)            │              │
│   │                                                          │              │
│   │   ./feedback/*.txt をチェック                            │              │
│   │   ┌─────────────────────────────────────────┐           │              │
│   │   │ あり → 該当Agentで再生成/修正           │           │              │
│   │   │ なし → タイムアウト後に次へ             │           │              │
│   │   └─────────────────────────────────────────┘           │              │
│   └────────────────────────┬────────────────────────────────┘              │
│                            │                                                │
│                            ▼                                                │
│   ┌─────────────────┐                                                      │
│   │  Tester Agent   │                                                      │
│   │   動作テスト    │                                                      │
│   └────────┬────────┘                                                      │
│            │                                                                │
│            ▼                                                                │
│      ┌──────────┐     Yes    ┌─────────────────┐                          │
│      │ エラー？  │───────────▶│  Debugger Agent │──┐                       │
│      └────┬─────┘            │    バグ修正     │  │                       │
│           │ No               └─────────────────┘  │                       │
│           │                           │           │                       │
│           │                           └───────────┘                       │
│           ▼                                                                │
│   ┌─────────────────┐                                                      │
│   │    完成！🎮     │                                                      │
│   └─────────────────┘                                                      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 フィードバック処理フロー

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Feedback Processing Flow                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   Agent が成果物を生成                                                       │
│     │                                                                        │
│     ▼                                                                        │
│   ┌──────────────────────────────────────┐                                  │
│   │  ./output/{artifact_id}.{ext} に保存  │                                  │
│   │  ./status/current.json を更新         │                                  │
│   └──────────────────┬───────────────────┘                                  │
│                      │                                                       │
│                      ▼                                                       │
│   ┌──────────────────────────────────────┐                                  │
│   │  コンソールに通知:                    │                                  │
│   │  "✅ character_001 生成完了"          │                                  │
│   │  "⏳ フィードバック待機中 (30秒)..."  │                                  │
│   └──────────────────┬───────────────────┘                                  │
│                      │                                                       │
│                      ▼                                                       │
│   ┌──────────────────────────────────────┐                                  │
│   │        Feedback Check Loop            │                                  │
│   │                                       │                                  │
│   │   for 30 seconds:                     │                                  │
│   │     check ./feedback/{artifact_id}.txt│                                  │
│   │     if exists:                        │                                  │
│   │       process feedback                │                                  │
│   │       break                           │                                  │
│   │     sleep 1 second                    │                                  │
│   │                                       │                                  │
│   └──────────────────┬───────────────────┘                                  │
│                      │                                                       │
│          ┌───────────┴───────────┐                                          │
│          ▼                       ▼                                          │
│   ┌──────────────┐       ┌──────────────┐                                   │
│   │ Feedback     │       │ No Feedback  │                                   │
│   │ Received     │       │ (Timeout)    │                                   │
│   └──────┬───────┘       └──────┬───────┘                                   │
│          │                      │                                           │
│          ▼                      ▼                                           │
│   ┌──────────────┐       ┌──────────────┐                                   │
│   │ action に応じて│       │ 成果物確定   │                                   │
│   │ 再生成/修正   │       │ 次へ進む     │                                   │
│   └──────────────┘       └──────────────┘                                   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.3 Claude Code連携フロー

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      Claude Code Integration Flow                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   Agent (Coder/Debugger/Tester)                                             │
│     │                                                                        │
│     │ 複雑なタスクを検出                                                     │
│     ▼                                                                        │
│   ┌──────────────────────────────────────┐                                  │
│   │  ./claude_tasks/{task_id}.json 作成   │                                  │
│   │                                       │                                  │
│   │  {                                    │                                  │
│   │    "task_type": "refactor",          │                                  │
│   │    "description": "...",              │                                  │
│   │    "target_files": ["src/game.py"],  │                                  │
│   │    "context": "..."                   │                                  │
│   │  }                                    │                                  │
│   └──────────────────┬───────────────────┘                                  │
│                      │                                                       │
│                      ▼                                                       │
│   ┌──────────────────────────────────────┐                                  │
│   │  Claude Code (別プロセス/手動実行)    │                                  │
│   │                                       │                                  │
│   │  $ claude-code --task claude_tasks/   │                                  │
│   │    {task_id}.json                     │                                  │
│   │                                       │                                  │
│   │  ※ サブスク範囲内で実行可能           │                                  │
│   └──────────────────┬───────────────────┘                                  │
│                      │                                                       │
│                      ▼                                                       │
│   ┌──────────────────────────────────────┐                                  │
│   │  ./claude_results/{task_id}_result    │                                  │
│   │  .json に結果出力                     │                                  │
│   │                                       │                                  │
│   │  {                                    │                                  │
│   │    "success": true,                   │                                  │
│   │    "modified_files": [...],           │                                  │
│   │    "summary": "..."                   │                                  │
│   │  }                                    │                                  │
│   └──────────────────┬───────────────────┘                                  │
│                      │                                                       │
│                      ▼                                                       │
│   Agent が結果を取り込み、次のステップへ                                     │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

使用シナリオ:
  • Coder Agent → 複雑なリファクタリング → Claude Code
  • Debugger Agent → 難解なバグ → Claude Code
  • Tester Agent → テストコード生成 → Claude Code
  • Reviewer Agent → コードレビュー → Claude Code
```

---

## 6. ディレクトリ構造

```
📁 AiAgentGame/
├── 📁 src/                          # ソースコード
│   ├── 📁 agents/                   # Agent実装
│   │   ├── 📄 planner.py
│   │   ├── 📄 coder.py
│   │   ├── 📄 reviewer.py
│   │   ├── 📄 tester.py
│   │   ├── 📄 debugger.py
│   │   ├── 📄 asset_coordinator.py
│   │   ├── 📄 visual_agent.py
│   │   ├── 📄 audio_agent.py
│   │   └── 📄 ui_agent.py
│   │
│   ├── 📁 tools/                    # Tool実装
│   │   ├── 📄 file_tools.py         # FileRead, FileWrite, FileEdit
│   │   ├── 📄 bash_tools.py         # BashExec
│   │   ├── 📄 image_tools.py        # ImageGenerate
│   │   ├── 📄 audio_tools.py        # AudioGenerate
│   │   ├── 📄 web_tools.py          # WebSearch
│   │   ├── 📄 claude_code_tools.py  # Claude Code連携
│   │   ├── 📄 attribution_tools.py  # 出典情報管理
│   │   └── 📄 free_asset_tools.py   # フリー素材検索・取得
│   │
│   ├── 📁 core/                     # コア機能
│   │   ├── 📄 graph.py              # LangGraph定義
│   │   ├── 📄 state.py              # State定義
│   │   ├── 📄 feedback.py           # Feedback処理
│   │   └── 📄 llm.py                # LLM設定
│   │
│   └── 📄 main.py                   # エントリーポイント
│
├── 📁 output/                       # Agent成果物出力
│   ├── 📁 code/                     # 生成されたゲームコード
│   ├── 📁 images/                   # 画像アセット
│   ├── 📁 audio/                    # 音声アセット
│   ├── 📁 ui/                       # UI素材
│   └── 📄 attribution.json          # 全素材の出典・ライセンス情報
│
├── 📁 feedback/                     # ユーザーフィードバック
│   └── 📄 (artifact_id).txt         # 各成果物へのフィードバック
│
├── 📁 status/                       # 進捗状況
│   ├── 📄 current.json              # 現在の状態
│   └── 📄 history.json              # 実行履歴
│
├── 📁 claude_tasks/                 # Claude Code連携（タスク依頼）
│   └── 📄 (task_id).json            # タスク定義ファイル
│
├── 📁 claude_results/               # Claude Code連携（実行結果）
│   └── 📄 (task_id)_result.json     # 実行結果ファイル
│
├── 📁 templates/                    # ゲームテンプレート
│   ├── 📁 pygame/
│   ├── 📁 pyxel/
│   └── 📁 html5/
│
├── 📁 config/                       # 設定
│   ├── 📄 llm_config.yaml           # LLM設定
│   ├── 📄 api_keys.yaml             # APIキー（.gitignore）
│   └── 📄 agent_config.yaml         # Agent設定
│
├── 📄 requirements.txt
├── 📄 pyproject.toml
├── 📄 ARCHITECTURE.md               # この文書
└── 📄 README.md
```

---

## 7. Human-in-the-Loop（ファイルベース）

### 7.1 フィードバックの書き方

```bash
# 成果物を確認後、フィードバックを書く

# 画像の再生成
echo "もっと明るい色合いにして、背景は夕焼けで" > ./feedback/character_001.txt

# コードの修正
echo "ジャンプの高さを2倍にして" > ./feedback/player_controller.txt

# BGMの再生成
echo "もっとアップテンポで、8bit風に" > ./feedback/bgm_main.txt

# 全体への指示
echo "全体的にレトロゲーム風のテイストで統一して" > ./feedback/_global.txt
```

### 7.2 フィードバックファイル形式

#### シンプル形式（テキスト）

```
./feedback/character_001.txt:
もっと明るい髪色で、表情は笑顔にして
```

#### 詳細形式（JSON）

```json
// ./feedback/character_001.json
{
  "action": "redo",
  "priority": "high",
  "comment": "もっと明るい髪色で、表情は笑顔にして",
  "reference": "https://example.com/reference_image.png"
}
```

### 7.3 ステータスファイル形式

```json
// ./status/current.json
{
  "session_id": "game_001",
  "phase": "asset_generation",
  "started_at": "2025-01-14T10:00:00Z",
  "artifacts": {
    "character_001": {
      "status": "completed",
      "file": "./output/images/character_001.png",
      "awaiting_feedback": true,
      "timeout_at": "2025-01-14T10:05:30Z"
    },
    "bgm_main": {
      "status": "in_progress",
      "progress": 60
    }
  },
  "next_actions": [
    "character_002の生成",
    "title_screenの実装"
  ]
}
```

---

## 8. LLM設定

### 8.1 対応LLMプロバイダー

```yaml
# config/llm_config.yaml

# デフォルト設定
default:
  provider: anthropic
  model: claude-3-5-sonnet-20241022
  temperature: 0.7
  max_tokens: 4096

# プロバイダー別設定
providers:
  anthropic:
    models:
      - claude-3-5-sonnet-20241022
      - claude-3-opus-20240229
      - claude-3-haiku-20240307

  openai:
    models:
      - gpt-4-turbo
      - gpt-4o
      - gpt-3.5-turbo

  deepseek:
    base_url: https://api.deepseek.com/v1
    models:
      - deepseek-chat
      - deepseek-coder

  custom:
    base_url: ${CUSTOM_LLM_URL}
    models:
      - custom-model

# Agent別LLM設定（オプション）
agent_overrides:
  coder:
    provider: deepseek
    model: deepseek-coder
  planner:
    provider: anthropic
    model: claude-3-opus-20240229
```

### 8.2 LLM切り替えコード

```python
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

def get_llm(config: dict):
    provider = config.get("provider", "anthropic")

    if provider == "anthropic":
        return ChatAnthropic(
            model=config["model"],
            temperature=config.get("temperature", 0.7)
        )
    elif provider == "openai":
        return ChatOpenAI(
            model=config["model"],
            temperature=config.get("temperature", 0.7)
        )
    elif provider == "deepseek":
        return ChatOpenAI(
            base_url=config["base_url"],
            model=config["model"],
            api_key=os.getenv("DEEPSEEK_API_KEY")
        )
    elif provider == "custom":
        return ChatOpenAI(
            base_url=config["base_url"],
            model=config["model"],
            api_key=os.getenv("CUSTOM_API_KEY")
        )
```

---

## 9. 技術スタック

| カテゴリ | 技術 | バージョン | 用途 |
|---------|------|-----------|------|
| **言語** | Python | 3.10+ | メイン言語 |
| **Orchestration** | LangGraph | 1.0+ | Agent制御 |
| **LLM Interface** | LangChain | 1.0+ | LLM抽象化 |
| **Monitoring** | LangSmith | - | トレース・デバッグ |
| **Game Engine** | Pygame | 2.5+ | 2Dゲーム |
| **Game Engine** | Pyxel | 2.0+ | レトロゲーム |
| **Game Engine** | HTML5 Canvas | - | Webゲーム |
| **Image Gen** | ComfyUI | - | 画像生成（メイン・自前） |
| **Image Gen** | Stable Diffusion WebUI | - | 画像生成（代替・自前） |
| **Image Gen** | DALL-E 3 | - | 画像生成（フォールバック） |
| **Audio Gen** | AudioCraft | - | BGM/SE生成（自前） |
| **Audio Gen** | VOICEVOX | - | 日本語音声（自前） |
| **Audio Gen** | Freesound API | - | SE素材（無料） |
| **Audio Gen** | Suno AI | - | BGM生成（有料フォールバック） |
| **Audio Gen** | ElevenLabs | - | 音声生成（有料フォールバック） |
| **File Watch** | watchdog | 3.0+ | ファイル監視 |

---

## 10. 実装フェーズ

### Phase 1: 基盤構築
- [ ] プロジェクト初期化
- [ ] LangGraph基本フロー実装
- [ ] LangSmith接続設定
- [ ] ファイルベースFeedback実装

### Phase 2: Core Agent実装
- [ ] Planner Agent
- [ ] Coder Agent
- [ ] Tester Agent
- [ ] Debugger Agent

### Phase 3: Tool実装
- [ ] FileRead / FileWrite / FileEdit
- [ ] BashExec
- [ ] WebSearch

### Phase 4: Asset Agent実装
- [ ] Asset Coordinator
- [ ] Visual Agent
- [ ] Audio Agent
- [ ] UI Agent

### Phase 5: 統合・最適化
- [ ] 全Agent連携テスト
- [ ] エラーハンドリング強化
- [ ] パフォーマンス最適化

### Phase 6: 拡張機能
- [ ] ゲームテンプレート追加
- [ ] 複数ゲームエンジン対応
- [ ] Web UI（オプション）

---

## 11. 制約・前提条件

### 11.1 システム要件

- Python 3.10以上
- 8GB以上のRAM推奨
- インターネット接続（LLM API呼び出し）

### 11.2 必要なAPIキー

**必須（いずれか1つ）**:
- Anthropic API Key（Claude使用時）
- OpenAI API Key（GPT使用時）
- Deepseek API Key（Deepseek使用時）

**自前環境（推奨・APIキー不要）**:
- ComfyUI / Stable Diffusion WebUI（ローカル画像生成）
- AudioCraft / Bark（ローカル音声生成）
- VOICEVOX（ローカル日本語音声）

**オプション（有料フォールバック）**:
- OpenAI API Key（DALL-E 3使用時）
- Suno API Key（高品質BGM生成時）
- ElevenLabs API Key（高品質音声生成時）

### 11.3 制限事項

- ローカル実行を前提（ネットワーク越しのフィードバックは非対応）
- 同時実行セッションは1つ
- 大規模プロジェクトには追加のインフラが必要な場合あり

---

## 12. 今後の拡張候補

1. **Web UI**: ブラウザベースのインターフェース
2. **リモートフィードバック**: Redis/WebSocketによるネットワーク対応
3. **チーム開発**: 複数ユーザーによる同時フィードバック
4. **バージョン管理**: 成果物の履歴管理・ロールバック
5. **プリセット**: ゲームジャンル別テンプレート
6. **マーケットプレイス**: アセット共有・再利用

---

*最終更新: 2025-01-14*
*バージョン: 1.0.0*
