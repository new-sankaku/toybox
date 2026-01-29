# クライアントアーキテクチャレビュー

## 概要

`langgraph-studio/src/` のクライアント側コードベースを網羅的にレビューしました。

**ファイル総数**: 約110ファイル（TSX: 47, TS stores: 22, TS types: 11, その他）

---

## 評価サマリー

| カテゴリ | 評価 | コメント |
|---------|------|----------|
| ディレクトリ構造 | ◎ | 明確な責務分離 |
| 状態管理 | ○ | Zustand採用は適切、一部改善余地 |
| API通信 | △ | 巨大な単一ファイル |
| コンポーネント設計 | △ | 一部巨大コンポーネント |
| 型定義 | ○ | OpenAPI自動生成は良い |
| エラーハンドリング | ○ | 統一的な処理 |
| パフォーマンス | ○ | 基本的なベストプラクティス適用 |
| テスト | - | 未確認 |

---

## 良い点

### 1. ディレクトリ構造

```
src/
├── components/   # UI層（機能別に適切にサブ分割）
├── views/        # ページレベルコンポーネント
├── stores/       # Zustand状態管理（22ファイル）
├── services/     # API通信層
├── types/        # TypeScript型定義
├── constants/    # 定数定義
├── config/       # 設定
└── lib/          # ユーティリティ
```

責務が明確に分離されています。

### 2. 状態管理（Zustand）

- **軽量**: Redux等より軽量でシンプル
- **機能別分割**: 22のストアが適切に分割
- **派生セレクター**: `useActiveAgentsCount()` 等のカスタムフック提供
- **persist**: 必要なストアにのみ永続化ミドルウェア適用

```typescript
// 良い例: agentStore.ts
export const useActiveAgentsCount = () => {
  return useAgentStore((state) =>
    state.agents.filter((a) => a.status === 'running' || a.status === 'pending').length
  )
}
```

### 3. API定数管理

`constants/api.ts` でエンドポイントを一元管理:

```typescript
export const API_ENDPOINTS = {
  projects: {
    list: '/api/projects',
    get: (id: string) => `/api/projects/${id}`,
    // ...
  },
  // ...
}
```

### 4. 型変換レイヤー

API型とドメイン型を分離し、converterで変換:

```typescript
// services/converters/agentConverter.ts
export function convertApiAgent(apiAgent: ApiAgent): Agent {
  return { ... }
}
```

### 5. UIコンポーネント設計

- **CVA (Class Variance Authority)** 採用でバリアント管理
- **Tailwind** カスタマイズでデザインシステム統一
- **Radix UI** 採用でアクセシビリティ確保

```typescript
// Button.tsx - CVAによるバリアント管理
const buttonVariants = cva(
  'inline-flex items-center...',
  {
    variants: {
      variant: { default: '...', primary: '...', danger: '...' },
      size: { default: '...', sm: '...', lg: '...' }
    }
  }
)
```

### 6. エラーハンドリング

統一的なエラー抽出関数:

```typescript
export function extractApiError(error: unknown): ApiErrorDetail {
  if (axios.isAxiosError(error)) {
    // AxiosError専用処理
  }
  // 日本語メッセージへの変換
}
```

### 7. リアルタイム通信

- **Socket.IO** による双方向通信
- **型付きイベント**: `ServerToClientEvents`, `ClientToServerEvents`
- **再接続ロジック**: 設定可能なリトライ

---

## 改善が必要な点

### 1. 巨大コンポーネント（高優先度）

#### ProjectView.tsx: 1525行

**問題**:
- 20以上のローカル状態（useState）
- 作成フォーム・編集フォーム・詳細表示・複数ダイアログが1ファイルに
- フォームコードの重複（新規作成と編集で同じフィールドが2回記述）

**推奨アクション**:
```
views/ProjectView.tsx → 分割:
├── views/ProjectView.tsx (コンテナ)
├── components/project/ProjectList.tsx
├── components/project/ProjectForm.tsx (新規・編集共通)
├── components/project/ProjectDetail.tsx
├── components/project/ProjectControls.tsx
├── components/project/ProjectFiles.tsx
├── components/project/dialogs/InitializeDialog.tsx
├── components/project/dialogs/DeleteDialog.tsx
└── components/project/dialogs/BrushupDialog.tsx
```

### 2. 巨大APIサービス（高優先度）

#### apiService.ts: 1336行

**問題**:
- すべてのAPIエンドポイントが1ファイル
- 型定義が混在
- ドメイン別の分離なし

**推奨アクション**:
```
services/apiService.ts → 分割:
├── services/api/index.ts (axiosインスタンス、共通処理)
├── services/api/projectApi.ts
├── services/api/agentApi.ts
├── services/api/checkpointApi.ts
├── services/api/assetApi.ts
├── services/api/configApi.ts
└── services/api/types.ts (API固有の型)
```

### 3. hooksディレクトリ未活用（中優先度）

**問題**:
- `src/hooks/` ディレクトリが空
- カスタムフックがストアファイル内に定義

**推奨アクション**:
```typescript
// hooks/useAgents.ts
export function useAgentsByProject(projectId: string) { ... }
export function useActiveAgentsCount() { ... }

// hooks/useProjectForm.ts
export function useProjectForm(initialData?: Project) {
  // フォーム状態とハンドラーをカプセル化
}
```

### 4. 型定義の重複（中優先度）

**問題**:
- `types/agent.ts` に `Agent` 型
- `services/apiService.ts` に `ApiAgent` 型
- 構造がほぼ同一

**推奨アクション**:
- OpenAPI自動生成の型を正として使用
- ドメイン型が必要な場合のみ変換を維持

### 5. WebSocketServiceの責務（低優先度）

**問題**:
- WebSocketServiceがストアを直接操作
- 関心の分離が不十分

**現状**:
```typescript
// websocketService.ts
this.socket.on('agent:started', (data) => {
  useAgentStore.getState().addAgent(data.agent)  // 直接ストア操作
})
```

**推奨**:
```typescript
// イベントを発火し、リスナー側で処理
websocketService.on('agent:started', (data) => {
  agentStore.addAgent(data.agent)
})
```

### 6. パフォーマンス最適化（低優先度）

- 大きなリストに対する仮想化（react-window等）未適用
- useMemo/useCallbackの一貫した使用がない箇所あり

---

## 詳細分析

### コンポーネント行数

| ファイル | 行数 | 評価 |
|----------|------|------|
| views/ProjectView.tsx | 1525 | 要分割 |
| services/apiService.ts | 1336 | 要分割 |
| stores/aiServiceStore.ts | 305 | 許容範囲 |
| views/AgentsView.tsx | 221 | 適切 |
| services/websocketService.ts | 442 | 許容範囲 |
| components/ui/Button.tsx | 50 | 適切 |
| components/ui/Card.tsx | 70 | 適切 |

### ストア設計

| ストア | 状態 | 評価 |
|--------|------|------|
| projectStore | シンプル | ◎ |
| agentStore | 適度な複雑さ | ○ |
| aiServiceStore | persist使用 | ○ |
| connectionStore | シンプル | ◎ |
| navigationStore | シンプル | ◎ |

### 依存関係フロー

```
Views
  ↓
Stores (Zustand)
  ↓
Services (apiService, websocketService)
  ↓
Backend API
```

---

## 推奨アクションリスト

### 高優先度
1. [ ] ProjectView.tsxを8-10ファイルに分割
2. [ ] apiService.tsをドメイン別に分割
3. [ ] ProjectFormコンポーネントの共通化

### 中優先度
4. [ ] hooksディレクトリの活用（ストアからフック抽出）
5. [ ] 型定義の整理（重複削除）
6. [ ] ESLintルール追加（ファイル行数制限等）

### 低優先度
7. [ ] WebSocketServiceのイベント発火パターン導入
8. [ ] 大きなリストの仮想化
9. [ ] React.memo/useMemo/useCallbackの一貫した適用

---

## 結論

クライアントアーキテクチャは**概ねプロフェッショナルな水準**にあります。

**強み**:
- 明確なディレクトリ構造
- Zustandによる軽量な状態管理
- TypeScriptの厳格な型付け
- OpenAPI自動型生成
- デザインシステムの統一

**改善点**:
- 巨大ファイルの分割（ProjectView.tsx, apiService.ts）
- フォームコンポーネントの再利用性向上
- hooksパターンの活用

これらの改善を行うことで、保守性・可読性・拡張性がさらに向上します。
