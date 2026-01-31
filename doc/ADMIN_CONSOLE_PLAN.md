# Admin Console 計画書

## 1. 背景・課題

| 問題 | 詳細 |
|------|------|
| APIキーのスコープが不明 | テーブルはグローバルだがUIはプロジェクト単位に見える |
| 漏洩リスク | キー管理がメインUIに同居、画面共有等で露出リスク |
| 権限分離なし | 管理操作と日常操作が同一UIに混在 |
| メンテナンス機能の散在 | バックアップ・アーカイブ・クリーンアップがメインUI内に散在 |

**解決方針**: 管理用Admin Consoleを別Webアプリとして新設

## 2. アーキテクチャ

| コンポーネント | 説明 |
|---------------|------|
| Main Web UI | port 5173, langgraph-studio/ |
| Admin Console | port 5174, admin-console/ |
| Backend | 同一Flask、Admin APIは`/admin-api/*`プレフィックス |
| 認証 | トークン認証（環境変数`ADMIN_TOKEN`） |

## 3. Admin Console 機能一覧

### Phase 1: APIキー管理の移設

| 機能 | 優先度 |
|------|--------|
| グローバルAPIキー管理（登録・削除・検証） | 必須 |
| スコープの明示（「全プロジェクト共通」表示） | 必須 |
| メインUIからキー管理を除去 | 必須 |
| Admin認証（トークンベース） | 必須 |

### Phase 2: DB保守機能の移設

| 機能 | 優先度 |
|------|--------|
| バックアップ管理（作成・復元・削除） | 必須 |
| アーカイブ管理（クリーンアップ・エクスポート） | 必須 |
| データ統計（DB容量、レコード数） | 推奨 |
| 保持期間設定 | 必須 |

### Phase 3: 運用監視・拡張

| 機能 | 優先度 |
|------|--------|
| プロバイダーヘルス一覧 | 推奨 |
| API使用量ダッシュボード | 任意 |
| ログビューア | 任意 |

## 4. Admin認証設計

1. Admin Console起動 → トークン入力画面
2. POST /admin-api/auth/verify で検証
3. 検証成功 → セッションストレージにトークン保持
4. 以降のAdmin APIに`Authorization: Bearer <token>`付与

**設計判断**: ユーザー管理不要（個人/小規模チーム想定）、トークンは環境変数管理

## 5. Admin APIエンドポイント

| カテゴリ | エンドポイント |
|---------|---------------|
| 認証 | POST /admin-api/auth/verify |
| APIキー | GET/PUT/DELETE /admin-api/api-keys, POST validate |
| バックアップ | GET/POST /admin-api/backups, POST restore, DELETE |
| アーカイブ | GET stats, POST cleanup, PUT retention, POST export |
| システム | GET /admin-api/system/status, GET providers/health |

## 6. 移行戦略

Phase 1 → Admin認証ミドルウェア追加 → /admin-api/api-keys/* 追加 → Admin Console基盤 → ApiKeyPage実装 → メインUI変更 → 既存API廃止

Phase 2 → バックアップ・アーカイブAPI追加 → ページ実装 → メインUIから削除

Phase 3 → ダッシュボード・ログビューア追加

## 7. セキュリティ考慮事項

| 項目 | 対策 |
|------|------|
| APIキー漏洩 | Admin Console分離、通常作業画面にキー入力UIなし |
| Admin不正アクセス | トークン認証必須、環境変数管理 |
| CORS | Admin ConsoleのOriginのみ許可 |
| APIキー表示 | ヒント表示のみ、全文は一切表示しない |
| セッション | sessionStorage使用（タブ閉じで消失） |
