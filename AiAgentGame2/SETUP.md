# AiAgentGame2 セットアップガイド

## 概要

AiAgentGame2は以下のコンポーネントで構成されています：

| コンポーネント | 説明 | ディレクトリ |
|--------------|------|-------------|
| WebUI (Frontend) | Electron + React アプリ | `langgraph-studio/` |
| Backend | Flask + Socket.IO サーバー | `backend/` |
| Agent仕様 | 各エージェントの設計ドキュメント | `agents/` |

---

## クイックスタート

### 1. バックエンド起動

```bash
cd backend
00_install.bat      # 初回のみ
01_run_mock.bat     # モックモードで起動
```

### 2. フロントエンド起動

```bash
cd langgraph-studio
00_install.bat      # 初回のみ
01_run_dev.bat      # 開発サーバー起動
```

### 3. ブラウザでアクセス

- フロントエンド: http://localhost:5173
- バックエンドAPI: http://localhost:8765
- WebSocket: ws://localhost:8765

---

## 詳細セットアップ

### バックエンド (backend/)

#### 必要環境
- Python 3.10+

#### batファイル一覧

| ファイル | 説明 |
|---------|------|
| `00_install.bat` | 仮想環境作成 + 依存関係インストール |
| `01_run_mock.bat` | モックモードで起動（LLM呼び出しなし） |
| `02_run_langgraph.bat` | LangGraphモードで起動（Claude API使用） |

#### エージェントモード

| モード | 説明 | 用途 |
|-------|------|------|
| `mock` | シミュレーションデータを返す | フロントエンド開発・テスト |
| `langgraph` | Claude APIで実際に生成 | 本番使用 |

#### LangGraphモードの設定

1. `.env` ファイルを作成:
```bash
copy .env.example .env
```

2. APIキーを設定:
```env
ANTHROPIC_API_KEY=sk-ant-xxxxx
AGENT_MODE=langgraph
```

---

### フロントエンド (langgraph-studio/)

#### 必要環境
- Node.js 18+
- npm

#### batファイル一覧

| ファイル | 説明 |
|---------|------|
| `00_install.bat` | 依存関係インストール (npm install) |
| `01_run_dev.bat` | 開発サーバー起動 (Vite) |
| `02_build.bat` | プロダクションビルド |
| `03_preview.bat` | ビルド後プレビュー |
| `09_clean.bat` | node_modules削除 |

---

## プロジェクト構造

```
AiAgentGame2/
├── SETUP.md                 # このファイル
├── PROJECT.md               # プロジェクト概要
├── AGENT_SYSTEM.md          # エージェントシステム設計
├── WEBUI_DESIGN.md          # WebUIデザイン仕様
├── WEBUI_ARCHITECTURE.md    # WebUIアーキテクチャ
├── WebUI_API.md             # API仕様
├── DEVELOPMENT_RULES.md     # 開発ルール
│
├── backend/                 # バックエンドサーバー
│   ├── agents/             # AgentRunner実装
│   │   ├── base.py         # 抽象基底クラス
│   │   ├── mock_runner.py  # モック実装
│   │   └── langgraph_runner.py  # 本番実装
│   ├── handlers/           # APIハンドラー
│   ├── simulation/         # シミュレーションロジック
│   ├── config.py           # 設定管理
│   ├── server.py           # Flask + Socket.IO
│   └── main.py             # エントリーポイント
│
├── langgraph-studio/        # フロントエンド (Electron + React)
│   ├── src/
│   │   ├── components/     # UIコンポーネント
│   │   ├── stores/         # Zustand状態管理
│   │   ├── services/       # WebSocket等
│   │   ├── views/          # ページビュー
│   │   └── types/          # TypeScript型定義
│   └── electron/           # Electronメインプロセス
│
├── agents/                  # エージェント設計仕様書
│   ├── phase1_*.md         # Phase 1 エージェント仕様
│   ├── phase2_*.md         # Phase 2 エージェント仕様
│   └── phase3_*.md         # Phase 3 エージェント仕様
│
└── sample_webui/            # UIサンプル（参考用）
```

---

## トラブルシューティング

### バックエンドが起動しない

1. Python 3.10+ がインストールされているか確認
2. `00_install.bat` を再実行
3. `venv` フォルダを削除して再インストール

### フロントエンドが起動しない

1. Node.js 18+ がインストールされているか確認
2. `09_clean.bat` で node_modules を削除
3. `00_install.bat` を再実行

### WebSocket接続エラー

1. バックエンドが起動しているか確認
2. ポート8765が使用されていないか確認
3. ファイアウォール設定を確認

### LangGraphモードでエラー

1. `.env` ファイルが存在するか確認
2. `ANTHROPIC_API_KEY` が正しく設定されているか確認
3. APIキーの有効性を確認

---

## 開発フロー

1. **フロントエンド開発**: `mock` モードでバックエンドを起動
2. **エージェント開発**: `langgraph` モードでテスト
3. **統合テスト**: 両方を起動して動作確認

```bash
# ターミナル1: バックエンド
cd backend && 01_run_mock.bat

# ターミナル2: フロントエンド
cd langgraph-studio && 01_run_dev.bat
```
