# バックエンドアーキテクチャレビューレポート

**レビュー日時**: 2026-01-29
**対象**: `/home/user/toybox/backend/`

---

## 1. 総合評価

| カテゴリ | 評価 | コメント |
|---------|------|----------|
| レイヤー分離 | ◎ | handlers → services → repositories → models の明確な分離 |
| 設計パターン | ○ | Repository, Factory, Abstract Base Classの適切な使用 |
| 設定管理 | ◎ | YAML/JSON設定ファイルによる一元管理 |
| エラーハンドリング | ○ | 構造化されたエラーレスポンス、適切なログ |
| セキュリティ | △ | 暗号化実装に改善余地あり |
| テスト | △ | テスト構造はあるがカバレッジ不明 |
| コード品質 | △ | 一部ファイルの肥大化、CLAUDE.md違反あり |

**総合**: プロフェッショナルなアーキテクチャの基盤はあるが、いくつかの改善点が必要

---

## 2. アーキテクチャ構成

### 2.1 レイヤー構造

```
┌─────────────────────────────────────────────────────────────┐
│                    Presentation Layer                        │
│  handlers/ (22ファイル) - REST API + WebSocket               │
├─────────────────────────────────────────────────────────────┤
│                    Business Logic Layer                      │
│  services/ - AgentExecution, Backup, Recovery, etc.          │
│  agents/ - AgentRunner実装 (API, Mock, Skill)                │
├─────────────────────────────────────────────────────────────┤
│                    Data Access Layer                         │
│  repositories/ (16ファイル) - Repositoryパターン             │
│  datastore.py - ファサード (責務過多の懸念)                  │
├─────────────────────────────────────────────────────────────┤
│                    Infrastructure Layer                      │
│  models/ - SQLAlchemy ORM                                    │
│  providers/ - 外部AIサービス連携                             │
│  security/ - 暗号化                                          │
│  middleware/ - エラーハンドリング, ロギング, レート制限       │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 良い設計パターン

1. **Repositoryパターン** (`repositories/base.py`)
   - 汎用CRUDの基底クラス
   - 型ヒント付きジェネリック実装

2. **Factoryパターン** (`agents/factory.py`)
   - モードに応じたAgentRunner生成

3. **Abstract Base Class** (`agents/base.py`, `providers/base.py`)
   - AgentRunner, AIProviderの抽象化
   - 拡張性の高い設計

4. **設定の外部化** (`config_loader.py`, `config/`)
   - YAML/JSONによる設定管理
   - キャッシュ機構あり

---

## 3. 問題点と改善提案

### 3.1 🔴 CLAUDE.md違反: print()使用

**違反箇所**:
- `main.py:37-44` - サーバー起動時のprint
- `server.py:179-180` - サーバー起動メッセージのprint

**CLAUDE.mdルール**: 「バックエンドでprint()は禁止。必ず`from middleware.logger import get_logger`を使用」

**修正必要**: 高

---

### 3.2 🔴 datastore.pyの肥大化 (1518行)

**問題**:
- 責務過多: データアクセス + シミュレーション + WebSocket通知
- 単一責任原則違反
- テスト困難

**現状の責務**:
```
DataStore
├── プロジェクト管理 (CRUD)
├── エージェント管理 (CRUD)
├── チェックポイント管理
├── シミュレーションループ (testdataモード)
├── WebSocketイベント発信
├── サブスクリプション管理
├── 介入処理
└── メトリクス更新
```

**改善提案**:
```
DataStoreFacade (薄いファサード)
├── ProjectService
├── AgentService
├── CheckpointService
├── SimulationService (シミュレーション専用)
├── NotificationService (WebSocket通知)
└── InterventionService
```

**修正必要**: 中

---

### 3.3 🟡 Blueprint未使用

**問題**:
- `server.py`で22個の`register_*_routes()`を直接呼び出し
- ルートの整理・グループ化が困難

**現状** (`server.py:101-131`):
```python
register_project_routes(app,data_store,sio)
register_agent_routes(app,data_store,sio)
register_checkpoint_routes(app,data_store,sio)
# ... 19個以上続く
```

**改善提案**:
```python
from flask import Blueprint

api_v1 = Blueprint('api_v1', __name__, url_prefix='/api')

# handlers/project.py
project_bp = Blueprint('project', __name__)

@project_bp.route('/projects', methods=['GET'])
def list_projects():
    ...

# server.py
api_v1.register_blueprint(project_bp)
app.register_blueprint(api_v1)
```

**修正必要**: 低 (機能上の問題はなし)

---

### 3.4 🟡 マイグレーション管理

**問題** (`models/database.py:44-72`):
- 手動ALTER TABLEによるマイグレーション
- バージョン管理なし
- ロールバック不可

```python
def _run_migrations():
    if "system_prompt" not in columns:
        conn.execute(text("ALTER TABLE llm_jobs ADD COLUMN system_prompt TEXT"))
```

**改善提案**:
- Alembicの導入
- マイグレーションファイルによるバージョン管理

**修正必要**: 中 (運用時に問題になる可能性)

---

### 3.5 🟡 暗号化実装の懸念

**問題** (`security/encryption.py`):

1. **ハードコードされたデフォルトキー** (20-23行):
```python
def _generate_default_key()->bytes:
    seed="toybox-default-encryption-key-2024"  # 予測可能
    return hashlib.sha256(seed.encode()).digest()
```

2. **フォールバック暗号化** (56-62行):
- XOR暗号は弱い
- cryptographyライブラリがない場合のフォールバック

**改善提案**:
- 環境変数`ENCRYPTION_KEY`の必須化
- フォールバックを削除し、cryptography必須に

**修正必要**: 高 (セキュリティリスク)

---

### 3.6 🟡 非同期処理の混在

**問題** (`services/agent_execution_service.py:486-505`):
```python
def re_execute_agent(self,project_id:str,agent_id:str)->None:
    def _run():
        loop=asyncio.new_event_loop()  # イベントループを都度作成
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.execute_agent(...))
        finally:
            loop.close()
    thread=threading.Thread(target=_run,daemon=True)
    thread.start()
```

**問題点**:
- EventletとAsyncioの混在
- イベントループを毎回作成
- スレッド管理のオーバーヘッド

**改善提案**:
- Eventletに統一するか、async/awaitに完全移行
- バックグラウンドタスクキューの導入 (Celery等)

**修正必要**: 中

---

### 3.7 🟢 テスト構造

**現状**:
```
tests/
├── unit/
│   ├── agents/
│   ├── providers/
│   ├── repositories/
│   ├── security/
│   └── skills/
├── integration/
└── scenarios/
```

**評価**: 構造は良い。カバレッジの確認が必要。

---

## 4. 良い実装例

### 4.1 エラーハンドリング

`middleware/error_handler.py` は適切に実装:
- 構造化されたエラーレスポンス
- エラーコード体系
- デバッグ情報の制御
- `exc_info=True`でスタックトレース記録

### 4.2 セッション管理

`models/database.py` のコンテキストマネージャー:
```python
@contextmanager
def session_scope():
    session=SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

### 4.3 設定ローダー

`config_loader.py`:
- キャッシュ機構
- 型安全なアクセス関数
- YAML/JSON両対応

### 4.4 AIプロバイダー抽象化

`providers/base.py`:
- 明確なインターフェース定義
- ヘルスチェック機構
- 設定の外部読み込み

---

## 5. CLAUDE.md準拠チェック

| 指針 | 状況 | 対応 |
|------|------|------|
| print()禁止 | ❌ 違反 | main.py, server.pyで使用 |
| get_logger()使用 | ✅ 準拠 | 大部分で正しく使用 |
| 設定ファイル一元化 | ✅ 準拠 | ai_providers.yaml等 |
| フォールバック禁止 | ⚠️ 部分的 | 暗号化にフォールバックあり |
| エラーログにexc_info=True | ✅ 準拠 | 適切に実装 |

---

## 6. 推奨アクション

### 優先度: 高
1. **print()をget_logger()に置換** - CLAUDE.md違反
2. **暗号化のデフォルトキー削除** - セキュリティリスク

### 優先度: 中
3. **datastore.pyの分割** - 保守性向上
4. **Alembicマイグレーション導入** - 運用安定性
5. **非同期処理の統一** - パフォーマンス・安定性

### 優先度: 低
6. **Blueprint導入** - コード整理
7. **テストカバレッジ確認** - 品質保証

---

## 7. 結論

バックエンドアーキテクチャは**概ねプロフェッショナルな設計**になっています:

**強み**:
- レイヤー分離が明確
- 設計パターンの適切な使用
- 設定の外部化とキャッシュ
- 構造化されたエラーハンドリング
- AIプロバイダーの抽象化

**改善が必要な点**:
- CLAUDE.md違反 (print使用)
- datastore.pyの責務過多
- 暗号化のセキュリティ強化
- マイグレーション管理

優先度の高い項目から順次対応することを推奨します。
