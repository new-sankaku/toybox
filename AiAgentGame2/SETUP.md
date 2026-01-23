# AiAgentGame2

## 技術スタック

| 項目 | 技術 |
|-----|------|
| Backend | Python 3.10+ / Flask + Socket.IO |
| Frontend | Node.js 18+ / Electron + React + Zustand |
| LLM | Claude API |

## クイックスタート

```bash
# 初回インストール
00_install_all.bat

# 起動（テストデータモード）
02_run_all_langgraph.bat

# アクセス
# Frontend: http://localhost:5173
# Backend:  http://localhost:5000
```

## APIモード設定

```bash
cd backend
copy .env.example .env
# ANTHROPIC_API_KEY=sk-ant-xxxxx を設定
```

## フォルダ構成

```
AiAgentGame2/
├── SETUP.md, CLAUDE.md
├── docs/                    # ドキュメント
│   ├── AGENT_SYSTEM.md      # Agentシステム設計
│   ├── WEBUI_*.md           # WebUI仕様
│   └── agent/               # Agent詳細仕様
├── backend/                 # Python Backend
│   ├── agents/              # AgentRunner実装
│   ├── handlers/            # APIハンドラー
│   └── main.py
└── langgraph-studio/        # React Frontend
    ├── src/components/
    ├── src/stores/
    └── src/services/
```

## トラブルシューティング

- **起動しない**: `00_install_all.bat` 再実行、venv/node_modules削除
- **WebSocket接続エラー**: Backend起動確認、ポート5000確認
- **APIエラー**: `.env` のAPIキー確認
