# LangGraph ゲーム開発システム - プロジェクト

## 技術スタック

| コンポーネント | 技術 |
|--------------|------|
| **オーケストレーション** | LangGraph |
| **LLM** | Claude / GPT-4 |
| **言語** | Python 3.11+ |
| **状態保存** | SQLite / PostgreSQL |
| **ゲームエンジン** | 未定（Phaser.js / Pygame等） |
| **画像生成** | DALL-E / Stable Diffusion |
| **音声生成** | Suno / ElevenLabs |

---

## フォルダ構成

```
AiAgentGame2/
├── PROJECT.md              # プロジェクト概要（このファイル）
├── SETUP.md                # セットアップガイド
├── CLAUDE.md               # Claude Code向けルール
├── docs/                   # ドキュメント
│   ├── AGENT_SYSTEM.md     # Agentシステム全体設計
│   ├── DEVELOPMENT_RULES.md # 開発規約
│   ├── WEBUI_DESIGN.md     # WebUIデザイン仕様
│   ├── WEBUI_ARCHITECTURE.md # WebUIアーキテクチャ
│   ├── WebUI_API.md        # API仕様
│   └── agent/              # 個別Agent仕様
│       ├── 01_AGENT_HIERARCHY.md
│       ├── ...
│       └── 16_MCP_AND_SKILLS.md
├── backend/                # バックエンドサーバー
└── langgraph-studio/       # フロントエンド (Electron + React)
```

---

## システム開発フェーズ

> ⚠️ これは**このシステム自体**の開発フェーズです。ゲーム開発のイテレーションとは別です。

### MVP（最小実行可能製品）
- [ ] Orchestrator（基本ルーティング）
- [ ] 企画 + 設計 Agent
- [ ] 単一Coder Agent（統合版）
- [ ] 3箇所のHuman承認

### v1.0
- [ ] 企画層の全Agent（6個）
- [ ] Code Leader + Asset Leader
- [ ] 並列開発の仕組み
- [ ] イテレーション管理

### v2.0
- [ ] アセット生成連携（DALL-E等）
- [ ] ゲームテンプレート対応
- [ ] Human確認用WebUI
