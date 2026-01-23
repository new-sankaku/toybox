# 翻訳戦略 (Translation Strategy)

## 概要

本プロジェクトでは、翻訳・ラベル管理を「責任」で分離する。

- **動的に変わるもの** → バックエンドで管理
- **固定のもの** → フロントエンドで管理

## 分類

### バックエンド管理（動的）

| 項目 | 管理場所 | 取得方法 |
|------|---------|---------|
| エージェント名 | `backend/agent_settings.py` | `agent.metadata.displayName` |
| エージェントフェーズ | `backend/agent_settings.py` | API: `/api/settings/quality-check/defaults` |
| 高コストエージェント一覧 | `backend/agent_settings.py` | 同上 |

#### 理由

- エージェントはビジネスロジックで動的に追加・変更される
- プロンプト設定（`agents/*.md`）と連動
- 将来的にYAML/設定ファイルからの読み込みに移行しやすい

#### 実装

```python
# backend/agent_settings.py
AGENT_DISPLAY_NAMES: Dict[str, str] = {
    "concept_leader": "コンセプトリーダー",
    "design_leader": "デザインリーダー",
    # ... 新しいエージェントはここに追加
}
```

```python
# backend/mock_data.py - エージェント作成時
agent["metadata"]["displayName"] = AGENT_DISPLAY_NAMES.get(agent_type, agent_type)
```

### フロントエンド管理（固定）

| 項目 | 管理場所 | 備考 |
|------|---------|------|
| ステータス名 | 各コンポーネント | pending/running/completed/failed/blocked の5種 |
| UIラベル | 各コンポーネント | ボタン、見出し、説明文等 |
| エラーメッセージ | 各コンポーネント | バリデーション、通信エラー等 |

#### 理由

- ステータスはWebSocketプロトコルで固定（変更 = 破壊的変更）
- UIラベルは画面の責務
- 変更頻度が低く、フロントのみで完結

#### 実装

```tsx
// 固定: ステータス（システム定義）
const statusConfig = {
  pending: { text: '待機中', icon: Clock },
  running: { text: '実行中', icon: Play },
  completed: { text: '完了', icon: CheckCircle },
  failed: { text: 'エラー', icon: XCircle },
  blocked: { text: 'ブロック', icon: Pause },
}

// 動的: エージェント名（バックエンドから取得）
const displayName = agent.metadata?.displayName || agent.type
```

## 禁止事項

1. **フロントエンドでエージェント名をハードコードしない**
   - ❌ `agentTypeLabels['concept'] = 'コンセプト'`
   - ✅ `agent.metadata.displayName`

2. **バックエンドでUIラベルを返さない**
   - ❌ API response に `{ buttonLabel: '承認する' }`
   - ✅ フロントで固定文言として持つ

3. **翻訳の二重管理をしない**
   - 同じ情報をバックエンドとフロントエンド両方に持たない

## フォールバック

バックエンドから `displayName` が取得できない場合:

```tsx
// 1. metadata.displayName を優先
// 2. なければ type をそのまま表示（英語）
const getDisplayName = (agent: Agent): string => {
  return (agent.metadata?.displayName as string) || agent.type
}
```

## 将来の拡張

### 多言語対応が必要になった場合

1. バックエンドは言語コードを受け取り、対応する言語の `displayName` を返す
2. または、フロントエンドでi18nライブラリを導入し、固定文言のみ多言語化
3. エージェント名は引き続きバックエンドがマスター

```python
# 将来の例
AGENT_DISPLAY_NAMES = {
    "concept_leader": {
        "ja": "コンセプトリーダー",
        "en": "Concept Leader",
    },
}
```

## 関連ファイル

- `backend/agent_settings.py` - エージェント表示名のマスター
- `backend/handlers/settings.py` - displayNames を返すAPI
- `langgraph-studio/src/components/agents/AgentCard.tsx` - 表示コンポーネント
