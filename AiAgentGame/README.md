# AI Agent Game Creator

> 対話形式でゲームを自動生成する AI Agent システム

Claude Codeのように対話形式でゲームを作成できるAI Agentシステム。
ユーザーが「シューティングゲームを作って」と指示すると、複数のAgentが協調して企画・実装・アセット生成・テストを自動で行います。

## 🌟 特徴

- **🤖 複数Agent協調**: Planner, Coder, Tester, Debugger, Asset生成Agent等が協力
- **🔄 4段階開発**: MOCK → GENERATE → POLISH → FINAL で段階的に品質向上
- **🎨 自動アセット生成**: 画像・音声・UIを自動生成（MOCK phaseではプレースホルダー）
- **🔧 LLM非依存**: Claude/GPT/Deepseek等を切り替え可能
- **📝 Human-in-the-Loop**: ファイルベースのフィードバック機構でいつでも介入可能
- **🔍 可視化**: LangSmithによるトレース・デバッグ

## 📁 プロジェクト構造

```
AiAgentGame/
├── src/
│   ├── agents/          # Agent実装
│   │   ├── planner.py
│   │   ├── coder.py
│   │   ├── tester.py
│   │   ├── debugger.py
│   │   ├── reviewer.py
│   │   ├── asset_coordinator.py
│   │   ├── visual_agent.py
│   │   ├── audio_agent.py
│   │   └── ui_agent.py
│   ├── core/            # コア機能
│   │   ├── state.py
│   │   ├── llm.py
│   │   ├── graph.py
│   │   └── feedback.py
│   └── main.py          # エントリーポイント
├── output/              # 生成物出力
│   ├── code/
│   ├── images/
│   ├── audio/
│   └── ui/
├── config/              # 設定
│   ├── llm_config.yaml
│   └── agent_config.yaml
└── ARCHITECTURE.md      # 詳細設計書
```

## 🚀 クイックスタート

### 1. インストール

```bash
# リポジトリのクローン
cd AiAgentGame

# 依存関係のインストール
pip install -r requirements.txt
```

### 2. 環境設定

```bash
# .envファイルを作成
cp .env.example .env

# APIキーを設定（どれか1つ必須）
# .envファイルを編集してAPIキーを入力
```

最低限必要な設定:
```bash
# Claude使用時
ANTHROPIC_API_KEY=your_key_here

# または GPT使用時
OPENAI_API_KEY=your_key_here

# または Deepseek使用時
DEEPSEEK_API_KEY=your_key_here
```

### 3. ゲーム生成

```bash
# 基本的な使い方（MOCK phase）
python -m src.main "Create a simple platformer game"

# 異なるフェーズで実行
python -m src.main "Make a space shooter" --phase generate

# ヘルプを表示
python -m src.main --help
```

### 4. 生成されたゲームを実行

```bash
cd output/code
python main.py
```

## 🎯 開発フェーズ

### MOCK Phase（デフォルト）
最速で動作確認。数分で動くプロトタイプを生成。

```bash
python -m src.main "Create a platformer" --phase mock
```

- 画像: 色付き矩形
- 音声: システム音
- コード: 最小限の実装

### GENERATE Phase
実際のアセットを使用。基本的なゲーム体験。

```bash
python -m src.main "Create a platformer" --phase generate
```

- 画像: フリー素材 or AI生成
- 音声: フリー素材 or AI生成
- コード: 基本機能実装

### POLISH Phase
品質向上。見た目と動作を改善。

```bash
python -m src.main "Create a platformer" --phase polish
```

- 画像: Upscale、背景削除
- 音声: ループ加工、ノーマライズ
- コード: リファクタリング

### FINAL Phase
完成版。リリース品質。

```bash
python -m src.main "Create a platformer" --phase final
```

- 画像: 高解像度、アニメーション
- 音声: BGMバリエーション、SE追加
- コード: 最適化、ドキュメント

## 💬 フィードバック機能

生成中にフィードバックを与えることができます：

```bash
# 成果物を確認後、フィードバックファイルを作成
echo "もっと明るい色にして" > feedback/visual_player.txt

# 30秒以内にフィードバックを書くと、Agentが反映します
```

## 📖 使用例

### シンプルなプラットフォーマー
```bash
python -m src.main "Create a platformer where a green square jumps on platforms"
```

### シューティングゲーム
```bash
python -m src.main "Make a space shooter with enemies and power-ups"
```

### パズルゲーム
```bash
python -m src.main "Create a match-3 puzzle game"
```

## 🔧 設定

### LLMプロバイダーの変更

`config/llm_config.yaml` を編集:

```yaml
default:
  provider: anthropic  # または openai, deepseek
  model: claude-3-5-sonnet-20241022
  temperature: 0.7
```

### Agent別のLLM設定

```yaml
agent_overrides:
  coder:
    provider: deepseek
    model: deepseek-coder
  planner:
    provider: anthropic
    model: claude-3-opus-20240229
```

## 📚 詳細ドキュメント

- [ARCHITECTURE.md](ARCHITECTURE.md) - システムアーキテクチャ詳細
- [config/](config/) - 設定ファイル

## 🛠️ 開発状況

### ✅ 実装済み
- ✅ Phase 1: 基盤構築（State, LangGraph, Feedback）
- ✅ Phase 2: Core Agent（Planner, Coder, Tester, Debugger, Reviewer）
- ✅ Phase 3-4: Asset Agent（Visual, Audio, UI）
- ✅ MOCK phase 完全対応

### 🚧 今後の拡張
- ⏳ GENERATE phase（フリー素材検索、AI生成）
- ⏳ POLISH phase（Upscale、後処理）
- ⏳ FINAL phase（高品質生成）
- ⏳ Claude Code統合（複雑なタスクの委譲）
- ⏳ LangSmith統合（トレース・デバッグ）

## 🤝 貢献

プルリクエスト歓迎！以下の領域で特に協力者を募集中：

- フリー素材API統合
- AI画像/音声生成の実装
- ゲームエンジン対応の拡張（Godot, Unity等）
- テストケースの追加

## 📄 ライセンス

MIT License

## 🙏 謝辞

- LangChain / LangGraph チーム
- Anthropic Claude チーム
- フリー素材提供サイト各位

---

**🎮 さあ、AIにゲームを作らせよう！**

```bash
python -m src.main "Create an awesome game"
```
