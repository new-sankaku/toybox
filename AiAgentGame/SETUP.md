# セットアップガイド

## 🚀 完全に動作させるための手順

### 1. 依存関係のインストール

```bash
cd AiAgentGame

# 仮想環境を作成（推奨）
python -m venv venv
source venv/bin/activate  # Linux/Mac
# または
venv\Scripts\activate  # Windows

# 依存関係をインストール
pip install -r requirements.txt
```

### 2. APIキーの設定

```bash
# .envファイルを作成
cp .env.example .env

# .envファイルを編集してAPIキーを追加
# 以下のいずれか1つが必須：
nano .env
```

**.env の例:**
```bash
# Claude使用の場合（推奨）
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxx

# またはGPT使用の場合
OPENAI_API_KEY=sk-xxxxxxxxxxxxx

# またはDeepseek使用の場合
DEEPSEEK_API_KEY=xxxxxxxxxxxxx
```

### 3. 動作確認

```bash
# ヘルプを表示
python -m src.main --help

# 簡単なゲームを生成（MOCK phase）
python -m src.main "Create a simple game with a green square"

# 結果を確認
ls -la output/code/
```

### 4. 生成されたゲームを実行

```bash
cd output/code
python main.py
```

## 🧪 テスト実行（APIキーあり）

最小限のテストコマンド：

```bash
# 最もシンプルなゲーム生成
python -m src.main "Make a game with one square" --phase mock

# 期待される出力:
# - output/code/main.py
# - output/images/mock/player.png
# - output/audio/mock/jump_se.wav
# - output/ui/mock/play_button.png
```

## 🔍 トラブルシューティング

### エラー: `ModuleNotFoundError`
```bash
pip install -r requirements.txt
```

### エラー: `ANTHROPIC_API_KEY environment variable not set`
```bash
# .envファイルを確認
cat .env

# または環境変数を直接設定
export ANTHROPIC_API_KEY=your_key_here
```

### エラー: `No module named 'pygame'`
生成されたゲームを実行する際:
```bash
pip install pygame
```

### Pygameウィンドウが表示されない（Linux）
```bash
# X11 forwarding または仮想ディスプレイが必要
sudo apt-get install xvfb
xvfb-run python main.py
```

## 📝 動作確認済み環境

- Python 3.10+
- Ubuntu 20.04 / macOS / Windows 10+
- LangChain 0.3.0+
- LangGraph 0.2.0+

## ⚡ クイックスタート（全てのステップ）

```bash
# 1. セットアップ
cd AiAgentGame
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. APIキー設定
cp .env.example .env
echo 'ANTHROPIC_API_KEY=sk-ant-your-key-here' >> .env

# 3. 実行
python -m src.main "Create a platformer" --phase mock

# 4. 確認
cd output/code && python main.py
```

## 🎯 次のステップ

システムが動作することを確認できたら:

1. 異なるゲームタイプを試す
2. `--phase generate` で実際のアセット生成を試す（将来の拡張）
3. フィードバック機能を試す
4. カスタムAgentを追加する

---

問題が解決しない場合は、GitHubでIssueを作成してください。
