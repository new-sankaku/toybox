# CLAUDE.md

## コメント規約

安易な解決策を採用するな。
代替案は提示して許可をとれ。
実装はアルゴリズムの選定を行え。
ベストプラクティスを採用しろ。
意味のない質問はするな。質問が必要なら意図を明確にして何故その質問をしたか書け。

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
