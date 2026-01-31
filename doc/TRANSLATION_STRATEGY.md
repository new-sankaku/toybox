# 翻訳戦略 (Translation Strategy)

## 概要

翻訳・ラベル管理を「責任」で分離する。

| 種別 | 管理場所 | 理由 |
|------|---------|------|
| 動的に変わるもの | バックエンド | ビジネスロジックで追加・変更、プロンプト設定と連動 |
| 固定のもの | フロントエンド | ステータスはプロトコル固定、UIラベルは画面の責務 |

## バックエンド管理（動的）

| 項目 | 管理場所 | 取得方法 |
|------|---------|---------|
| エージェント名 | `backend/agent_settings.py` | `agent.metadata.displayName` |
| エージェントフェーズ | `backend/agent_settings.py` | API経由 |
| 高コストエージェント一覧 | `backend/agent_settings.py` | API経由 |

## フロントエンド管理（固定）

| 項目 | 備考 |
|------|------|
| ステータス名 | pending/running/completed/failed/blocked の5種 |
| UIラベル | ボタン、見出し、説明文等 |
| エラーメッセージ | バリデーション、通信エラー等 |

## 禁止事項

1. フロントエンドでエージェント名をハードコードしない → `agent.metadata.displayName`を使用
2. バックエンドでUIラベルを返さない → フロントで固定文言として持つ
3. 翻訳の二重管理をしない → 同じ情報を両方に持たない

## フォールバック

1. `metadata.displayName` を優先
2. なければ `type` をそのまま表示（英語）

## 将来の拡張（多言語対応）

- バックエンドが言語コードを受け取り対応言語の`displayName`を返す
- またはフロントエンドでi18nライブラリ導入（固定文言のみ）
- エージェント名は引き続きバックエンドがマスター

## 関連ファイル

- `backend/agent_settings.py` - エージェント表示名のマスター
- `backend/handlers/settings.py` - displayNames を返すAPI
- `langgraph-studio/src/components/agents/AgentCard.tsx` - 表示コンポーネント
