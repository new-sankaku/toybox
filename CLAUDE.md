# CLAUDE.md

安易な解決策を採用するな。
代替案は提示して許可をとれ。
実装はアルゴリズムの選定を行え。
ベストプラクティスを採用しろ。
意味のない質問はするな。質問が必要なら意図を明確にして何故その質問をしたか書け。
固定値は避けてフレキシブルなUIにする。
AIサービスは固定でWeb上に表示しない。AIサービスはプロジェクトによって使う使わないがあるので、使わないものは表示しない。
Web画面でのフォールバック処理はユーザーを誤認させるため行わない。誤認の心配がない場合は可能。
サーバーからデータが取得できないためフォールバックなどは禁止。
常に敬語を使う。

## コメント規約

**不要なコメントは書かない**

- コードを読めば分かる内容はコメント不要
- 引数・戻り値の型や名前で意図が明確なら説明不要
- docstringも自明な関数には不要

**コメントが必要なケース:**

- 複雑なロジックの意図（なぜそうしたか）
- 外部APIやライブラリの制約・仕様
- TODO/FIXME（一時的なもの）

## コード圧縮

トークン削減のためコードを圧縮する:

```bash
# TypeScript（langgraph-studio）
cd langgraph-studio
npm run lint:fix    # ESLint適用（インデント1スペース等）
npm run format      # 演算子スペース削除

# Python（backend）
cd backend
python scripts/remove-spaces.py
```

**圧縮ルール（共通）:**
- コロン/カンマ後: スペースなし
- アロー演算子前後: スペースなし
- コメント: 削除（TODO/FIXME以外）
- 文字列内: 保持

**TypeScript追加ルール:**
- インデント: 1スペース

## 命名規則

### Backend

**ディレクトリ構造:**
- `handlers/` - HTTPルートハンドラー（Flask routes）
- `services/` - ビジネスロジック（DBアクセス含む）
- `repositories/` - データアクセス層
- `models/` - SQLAlchemyモデル定義
- `config/` - YAML/JSON設定ファイル

**ファイル命名:**
- ハンドラー: `{機能}_handler.py` または `{機能}.py`
- サービス: `{機能}_service.py`
- 設定: `{機能}.yaml` または `{機能}.json`

**設定ロード:**
- 全設定は `config_loader.py` 経由で読み込む
- モジュールレベルキャッシュでパフォーマンス確保

### Frontend

**ディレクトリ構造:**
- `stores/` - Zustand状態管理
- `views/` - ページコンポーネント
- `components/` - 再利用可能コンポーネント
- `services/` - API呼び出し
- `types/` - TypeScript型定義

**Export規則:**
- `stores/index.ts` - 全storeをre-export
- `views/index.ts` - 全viewをre-export
- 新規store/viewは必ずindex.tsに追加
