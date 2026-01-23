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
20_run_all_testdata.bat  # テストデータモード（開発用）
```

### 3. ブラウザでアクセス

- フロントエンド: http://localhost:5173
- バックエンドAPI: http://localhost:5000
- WebSocket: ws://localhost:5000

---

## batファイル一覧

### インストール・リビルド

| ファイル | 説明 |
|---------|------|
| `00_install_all.bat` | Backend + Frontend フルインストール（初回/クリーン時） |
| `09_rebuild_all.bat` | Backend + Frontend リビルド（依存関係更新時） |

### Backend 起動

| ファイル | 説明 |
|---------|------|
| `02_backend_run_testdata.bat` | テストデータモードで起動（API呼び出しなし） |
| `03_backend_run_api.bat` | APIモードで起動（Claude API使用） |

### Frontend 起動

| ファイル | 説明 |
|---------|------|
| `12_frontend_run_dev.bat` | 開発サーバー起動 (Vite) |
| `13_frontend_build.bat` | プロダクションビルド |

### 同時起動

| ファイル | 説明 |
|---------|------|
| `20_run_all_testdata.bat` | Backend (testdata) + Frontend 同時起動 |

---

## 必要環境

- **Backend**: Python 3.10+
- **Frontend**: Node.js 18+, npm

---

## エージェントモード

| モード | 説明 | 用途 |
|-------|------|------|
| `testdata` | シミュレーションデータを返す | フロントエンド開発・テスト |
| `api` | Claude APIで実際に生成 | 本番使用 |

### APIモードの設定

1. `.env` ファイルを作成:
```bash
cd backend
copy .env.example .env
```

2. APIキーを設定:
```env
ANTHROPIC_API_KEY=sk-ant-xxxxx
AGENT_MODE=api
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
│   │   ├── testdata_runner.py  # テストデータ実装
│   │   └── api_runner.py   # API実装
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
2. `00_install_all.bat` を再実行
3. `backend/venv` フォルダを削除して再インストール

### フロントエンドが起動しない

1. Node.js 18+ がインストールされているか確認
2. `langgraph-studio/node_modules` を削除
3. `00_install_all.bat` を再実行

### WebSocket接続エラー

1. バックエンドが起動しているか確認
2. ポート5000が使用されていないか確認
3. ファイアウォール設定を確認

### APIモードでエラー

1. `.env` ファイルが存在するか確認
2. `ANTHROPIC_API_KEY` が正しく設定されているか確認
3. APIキーの有効性を確認
