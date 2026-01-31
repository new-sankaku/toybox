# セットアップガイド

## コンポーネント構成

| コンポーネント | 説明 | ディレクトリ |
|--------------|------|-------------|
| WebUI (Frontend) | Electron + React | `langgraph-studio/` |
| Backend | Flask + Socket.IO | `backend/` |
| Agent仕様 | 設計ドキュメント | `agents/` |

## クイックスタート

1. `00_install_all.bat` - 全てインストール（初回のみ）
2. `20_run_all_testdata.bat` - Backend + Frontend 同時起動
3. ブラウザアクセス: http://localhost:5173

## batファイル一覧

| ファイル | 説明 |
|---------|------|
| `00_install_all.bat` | フルインストール |
| `09_rebuild_all.bat` | リビルド |
| `02_backend_run_testdata.bat` | テストデータモード起動 |
| `03_backend_run_api.bat` | APIモード起動 |
| `12_frontend_run_dev.bat` | 開発サーバー起動 |
| `13_frontend_build.bat` | プロダクションビルド |
| `20_run_all_testdata.bat` | 同時起動 |

## 必要環境

- Backend: Python 3.10+
- Frontend: Node.js 18+

## エージェントモード

| モード | 説明 | 用途 |
|-------|------|------|
| testdata | シミュレーションデータ | フロントエンド開発・テスト |
| api | Claude APIで実際に生成 | 本番使用 |

### APIモード設定

```bash
cd backend && copy .env.example .env
# .env: ANTHROPIC_API_KEY=sk-ant-xxxxx, AGENT_MODE=api
```

## トラブルシューティング

| 問題 | 対処 |
|------|------|
| バックエンド起動失敗 | Python 3.10+確認、venv削除→再インストール |
| フロントエンド起動失敗 | Node.js 18+確認、node_modules削除→再インストール |
| WebSocket接続エラー | バックエンド起動確認、ポート5000確認、ファイアウォール確認 |
| APIモードエラー | .envファイル存在確認、APIキー設定確認 |
