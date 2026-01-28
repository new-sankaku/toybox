# Admin Console 計画書

## 1. 背景・課題

### 現状の問題点

| 問題 | 詳細 |
|------|------|
| **APIキーのスコープが不明** | `api_key_store`テーブルはグローバル（プロバイダー単位で1レコード）だが、UIは`ApiKeySettings`コンポーネントが`projectId`をpropsで受け取っており、プロジェクト単位に見える |
| **漏洩リスク** | APIキー管理がメインUIの設定画面に同居。作業中に誤操作・画面共有等でヒント情報が露出する可能性 |
| **権限分離なし** | 管理操作（キー管理、DB保守、バックアップ）と日常操作（プロジェクト作業）が同一UIに混在 |
| **メンテナンス機能の散在** | バックアップ・アーカイブ・クリーンアップがメインUI内に散在 |

### 解決方針

**管理用Admin Consoleを別Webアプリとして新設**し、セキュリティ感度の高い操作と保守操作をメインUIから分離する。

---

## 2. アーキテクチャ

```
┌─────────────────────────────────────────────────────────┐
│                     Backend (Flask)                       │
│                                                          │
│  ┌──────────────┐   ┌──────────────────────────────┐    │
│  │ /api/*       │   │ /admin-api/*                  │    │
│  │ メインAPI     │   │ Admin専用API                   │    │
│  │ (既存)       │   │ (トークン認証)                  │    │
│  └──────┬───────┘   └──────────┬───────────────────┘    │
│         │                      │                         │
│         └──────────┬───────────┘                         │
│                    │                                     │
│              ┌─────┴─────┐                               │
│              │  SQLite   │                               │
│              │  DB       │                               │
│              └───────────┘                               │
└─────────────────────────────────────────────────────────┘
        ▲                           ▲
        │                           │
┌───────┴───────┐          ┌────────┴────────┐
│  Main Web UI  │          │  Admin Console  │
│  (port 5173)  │          │  (port 5174)    │
│  langgraph-   │          │  admin-console/ │
│  studio/      │          │                 │
└───────────────┘          └─────────────────┘
```

### ポイント

- **同一バックエンド**を共有し、Admin用APIエンドポイントを`/admin-api/`プレフィックスで追加
- Admin APIはトークン認証で保護（環境変数`ADMIN_TOKEN`で設定）
- Admin Consoleは別Viteアプリとして`admin-console/`ディレクトリに作成
- メインUIからAPIキー管理・保守系UIを削除

---

## 3. Admin Console 機能一覧

### Phase 1: APIキー管理の移設・改善

| 機能 | 説明 | 優先度 |
|------|------|--------|
| **グローバルAPIキー管理** | 現在の`ApiKeySettings`の機能をAdmin Consoleに移設 | 必須 |
| **スコープの明示** | 「全プロジェクト共通」であることをUIで明示 | 必須 |
| **キー登録・削除・検証** | 既存機能を移設 | 必須 |
| **メインUIからキー管理を除去** | `ApiKeySettings`コンポーネントを削除し、「Admin Consoleで設定してください」の案内に変更 | 必須 |
| **Admin認証** | トークンベースのシンプル認証 | 必須 |

### Phase 2: DB保守機能の移設

| 機能 | 説明 | 優先度 |
|------|------|--------|
| **バックアップ管理** | 作成・一覧・復元・削除を移設 | 必須 |
| **アーカイブ管理** | トレースのアーカイブ・クリーンアップ・エクスポートを移設 | 必須 |
| **データ統計** | DB容量、テーブル別レコード数、プロジェクト別統計 | 推奨 |
| **保持期間設定** | アーカイブ保持期間の設定 | 必須 |

### Phase 3: 運用監視・拡張

| 機能 | 説明 | 優先度 |
|------|------|--------|
| **プロバイダーヘルス一覧** | 全プロバイダーの接続状態・レイテンシを一覧表示 | 推奨 |
| **API使用量ダッシュボード** | プロバイダー別・プロジェクト別トークン使用量 | 任意 |
| **ログビューア** | システムログの検索・フィルタ・閲覧 | 任意 |

---

## 4. Admin認証設計

```
環境変数: ADMIN_TOKEN=<ランダム文字列>

認証フロー:
1. Admin Console起動 → トークン入力画面
2. トークンを入力 → POST /admin-api/auth/verify
3. 検証成功 → セッションストレージにトークン保持
4. 以降のAdmin API呼び出しに Authorization: Bearer <token> ヘッダを付与
5. バックエンドでミドルウェアがトークン照合
```

### 設計判断

- **ユーザー管理は不要**（個人/小規模チーム想定）
- トークンは環境変数で管理、DBには保存しない
- ブラウザ閉じると再認証（セッションストレージ使用）

---

## 5. バックエンド変更

### 5.1 新規ファイル

```
backend/
├── handlers/
│   └── admin.py              # Admin APIエンドポイント
├── middleware/
│   └── admin_auth.py         # Admin認証ミドルウェア
```

### 5.2 Admin APIエンドポイント一覧

```
# 認証
POST   /admin-api/auth/verify          # トークン検証

# APIキー管理（既存/api/api-keys/*を移設）
GET    /admin-api/api-keys             # 一覧（ヒントのみ）
PUT    /admin-api/api-keys/:providerId # 保存
DELETE /admin-api/api-keys/:providerId # 削除
POST   /admin-api/api-keys/:providerId/validate # 検証

# バックアップ管理（既存/api/backups/*を移設）
GET    /admin-api/backups              # 一覧
POST   /admin-api/backups              # 作成
POST   /admin-api/backups/:name/restore # 復元
DELETE /admin-api/backups/:name        # 削除

# アーカイブ管理（既存/api/archive/*を移設）
GET    /admin-api/archive/stats        # 統計
POST   /admin-api/archive/cleanup      # クリーンアップ
PUT    /admin-api/archive/retention    # 保持期間設定
POST   /admin-api/archive/export       # エクスポート
GET    /admin-api/archives             # アーカイブ一覧
DELETE /admin-api/archives/:name       # 削除
GET    /admin-api/archives/:name/download # ダウンロード

# システム情報
GET    /admin-api/system/status        # DB容量、テーブル統計
GET    /admin-api/providers/health     # プロバイダーヘルス一覧
```

### 5.3 既存API変更

| 変更 | 詳細 |
|------|------|
| `/api/api-keys/*` | **廃止予定**（Phase 1完了後に削除） |
| `/api/backups/*`, `/api/archive/*` | **廃止予定**（Phase 2完了後に削除） |

メインAPIからの段階的削除とし、Admin Console稼働確認後に移行する。

---

## 6. フロントエンド構成

### 6.1 Admin Console（新規）

```
admin-console/
├── index.html
├── package.json
├── vite.config.ts
├── tsconfig.json
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── pages/
│   │   ├── LoginPage.tsx         # トークン認証画面
│   │   ├── ApiKeyPage.tsx        # APIキー管理
│   │   ├── BackupPage.tsx        # バックアップ管理
│   │   ├── ArchivePage.tsx       # アーカイブ管理
│   │   └── SystemStatusPage.tsx  # システム情報
│   ├── components/
│   │   ├── layout/
│   │   │   ├── AdminLayout.tsx   # 共通レイアウト
│   │   │   └── Sidebar.tsx       # サイドナビ
│   │   └── ui/                   # 共通UIコンポーネント
│   ├── services/
│   │   └── adminApi.ts           # Admin API呼び出し
│   ├── stores/
│   │   └── authStore.ts          # 認証状態管理
│   └── lib/
│       └── utils.ts
```

### 6.2 メインUI変更

| ファイル | 変更内容 |
|----------|----------|
| `ApiKeySettings.tsx` | キー入力UI削除 → 「Admin Consoleで管理」案内 + ステータス表示のみ残す |
| 設定画面 | バックアップ・アーカイブ関連セクションをPhase 2で削除 |

APIキーの**ステータス**（検証済み/未検証）はメインUIで参照表示だけは残す。登録・削除操作はAdmin Consoleのみ。

---

## 7. 移行戦略

```
Phase 1（APIキー管理移設）
├── 1-1. Admin認証ミドルウェア追加
├── 1-2. /admin-api/api-keys/* エンドポイント追加
├── 1-3. Admin Console基盤（Vite + React + 認証画面）
├── 1-4. ApiKeyPage実装
├── 1-5. メインUIのApiKeySettingsを参照表示に変更
└── 1-6. /api/api-keys/* の変更操作（PUT/DELETE）を廃止

Phase 2（DB保守機能移設）
├── 2-1. /admin-api/backups/*, /admin-api/archive/* 追加
├── 2-2. BackupPage, ArchivePage実装
├── 2-3. SystemStatusPage実装
├── 2-4. メインUIから保守UIを削除
└── 2-5. 既存保守APIを廃止

Phase 3（運用拡張）
├── 3-1. プロバイダーヘルスダッシュボード
├── 3-2. API使用量集計
└── 3-3. ログビューア
```

---

## 8. UIデザイン方針

- メインUIと**同じカラーシステム**（`--bg-main`, `--text-main`等）を使用
- メインUIと同じTailwindベースのコンポーネント設計
- Admin専用のアクセントとして、ヘッダー等に区別用のマーカー（例: `[ADMIN]`ラベル）を付与
- 共通UIコンポーネント（Button, Card等）はメインUIからコピーまたはmonorepo化で共有

---

## 9. セキュリティ考慮事項

| 項目 | 対策 |
|------|------|
| APIキー漏洩 | Admin Console分離により、通常作業画面にキー入力UIが存在しない |
| Admin不正アクセス | トークン認証必須。トークンは環境変数管理 |
| CORS | Admin ConsoleのOriginのみ`/admin-api/*`へのアクセスを許可 |
| APIキー表示 | Admin Consoleでもヒント表示のみ。復号化キー全文は一切表示しない |
| セッション管理 | sessionStorage使用（タブ閉じで消失） |
