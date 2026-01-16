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

### 1. 全てインストール（初回のみ）

```bash
00_install_all.bat
```

### 2. Backend + Frontend 同時起動

```bash
20_run_all_mock.bat     # モックモード（開発用）
21_run_all_langgraph.bat # LangGraphモード（本番用）
```

### 3. ブラウザでアクセス

- フロントエンド: http://localhost:5173
- バックエンドAPI: http://localhost:8765
- WebSocket: ws://localhost:8765

---

## batファイル一覧

### インストール

| ファイル | 説明 |
|---------|------|
| `00_install_all.bat` | Backend + Frontend 両方インストール |
| `01_backend_install.bat` | Backend のみインストール |
| `11_frontend_install.bat` | Frontend のみインストール |

### Backend 起動

| ファイル | 説明 |
|---------|------|
| `02_backend_run_mock.bat` | モックモードで起動（LLM呼び出しなし） |
| `03_backend_run_langgraph.bat` | LangGraphモードで起動（Claude API使用） |

### Frontend 起動

| ファイル | 説明 |
|---------|------|
| `12_frontend_run_dev.bat` | 開発サーバー起動 (Vite) |
| `13_frontend_build.bat` | プロダクションビルド |
| `14_frontend_preview.bat` | ビルド後プレビュー |
| `19_frontend_clean.bat` | node_modules 削除 |

### 同時起動

| ファイル | 説明 |
|---------|------|
| `20_run_all_mock.bat` | Backend (mock) + Frontend 同時起動 |
| `21_run_all_langgraph.bat` | Backend (langgraph) + Frontend 同時起動 |

---

## 必要環境

- **Backend**: Python 3.10+
- **Frontend**: Node.js 18+, npm

---

## エージェントモード

| モード | 説明 | 用途 |
|-------|------|------|
| `mock` | シミュレーションデータを返す | フロントエンド開発・テスト |
| `langgraph` | Claude APIで実際に生成 | 本番使用 |

### LangGraphモードの設定

1. `.env` ファイルを作成:
```bash
cd backend
copy .env.example .env
```

2. APIキーを設定:
```env
ANTHROPIC_API_KEY=sk-ant-xxxxx
AGENT_MODE=langgraph
```

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
