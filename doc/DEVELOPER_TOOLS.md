# 開発ツール

## 概要

このプロジェクトでは、開発時に問題を早期発見するための各種ツールを導入しています。

## ツール一覧

### ビルドチェック（10_build_check.bat）に含まれるツール

| ツール | 対象 | 目的 |
|--------|------|------|
| Ruff | Backend | Pythonリンター |
| mypy | Backend | Python型チェック |
| pytest | Backend | ユニット/統合テスト |
| 循環import検出 | Backend | 循環依存の検出 |
| pip-audit | Backend | セキュリティ脆弱性チェック |
| ESLint | Frontend | TypeScriptリンター |
| TypeScript | Frontend | 型チェック |
| madge | Frontend | 循環依存の検出 |
| Vitest | Frontend | ユニットテスト |

### 手動実行ツール

| ツール | 対象 | 目的 |
|--------|------|------|
| vulture | Backend | Dead Code（未使用コード）検出 |
| knip | Frontend | 未使用export/依存関係の検出 |
| rollup-plugin-visualizer | Frontend | バンドルサイズ分析 |
| Playwright | Frontend | E2Eテスト |
| Schemathesis | Backend | API契約テスト |
| husky | 全体 | Git pre-commit hooks |
| lint-staged | 全体 | ステージ済みファイルのリント |

## 実行方法

### 一括チェック（推奨）

```bash
# 全チェック実行（サーバー起動不要）
10_build_check.bat
```

実行内容（12ステップ）:
1. Ruff Lint
2. mypy Type Check
3. Import Test
4. pytest Unit Tests
5. Circular Import Check (Python)
6. Security Audit (pip-audit)
7. OpenAPI Spec Generation
8. TypeScript Type Generation
9. ESLint
10. TypeScript Type Check
11. Circular Import Check (madge)
12. Vitest Unit Tests

### 個別実行

#### Backend

```bash
cd backend
source venv/bin/activate  # Linux/Mac
# または
call venv\Scripts\activate.bat  # Windows

# Ruff（リント）
ruff check .

# Ruff（フォーマット）
ruff format .

# mypy（型チェック）
mypy . --config-file pyproject.toml

# pytest（テスト）
pytest tests/ -v

# 循環import検出
python scripts/detect_circular_imports.py

# セキュリティ監査
pip-audit

# Dead Code検出
vulture .

# API契約テスト
pytest tests/contract/ -v
```

#### Frontend

```bash
cd langgraph-studio

# ESLint
npm run lint

# TypeScript型チェック
npm run typecheck

# Vitestユニットテスト
npm run test:unit

# Vitest（watchモード）
npm run test:unit:watch

# Vitest（カバレッジ）
npm run test:unit:coverage

# 循環依存検出
npm run analyze:circular

# Dead Code検出
npm run analyze:deadcode

# バンドルサイズ分析（HTMLレポート生成）
npm run analyze:bundle

# Playwright E2Eテスト
npm run test
```

## 設定ファイル

| ファイル | 説明 |
|----------|------|
| `backend/pyproject.toml` | Ruff、mypy、pytest、vulture設定 |
| `langgraph-studio/vitest.config.ts` | Vitest設定 |
| `langgraph-studio/vite.config.ts` | Vite + visualizer設定 |
| `langgraph-studio/eslint.config.mjs` | ESLint設定 |
| `langgraph-studio/knip.json` | knip設定 |
| `langgraph-studio/playwright.config.ts` | Playwright設定 |
| `package.json`（ルート） | husky、lint-staged設定 |
| `.husky/pre-commit` | pre-commitフック |

## Pre-commit Hooks

コミット時に自動で以下が実行されます:

- **Python (.py)**: `ruff check --fix` + `ruff format`
- **TypeScript (.ts/.tsx)**: `eslint --fix`

### セットアップ

```bash
# ルートディレクトリで
npm install
npm run prepare  # huskyをセットアップ
```

## 分析ツールの詳細

### pip-audit（セキュリティ監査）

インストール済みパッケージの既知の脆弱性をチェックします。

```bash
cd backend
pip-audit
```

脆弱性が見つかった場合は、パッケージのアップデートを検討してください。

### vulture（Dead Code検出）

使用されていないコード（関数、変数、クラス等）を検出します。

```bash
cd backend
vulture .
```

設定は `pyproject.toml` の `[tool.vulture]` セクションで管理されています。

### madge（循環依存検出 - Frontend）

TypeScript/JavaScriptの循環importを検出・可視化します。

```bash
cd langgraph-studio
npm run analyze:circular
```

### knip（未使用コード検出 - Frontend）

未使用のexport、ファイル、依存関係を検出します。

```bash
cd langgraph-studio
npm run analyze:deadcode
```

設定は `knip.json` で管理されています。

### rollup-plugin-visualizer（バンドル分析）

ビルド後のバンドルサイズを可視化し、最適化の余地を特定します。

```bash
cd langgraph-studio
npm run analyze:bundle
```

`dist/stats.html` にレポートが生成され、ブラウザで自動的に開きます。

## テストの書き方

### Vitest（フロントエンド）

```typescript
// src/test/example.test.ts
import {describe,it,expect} from 'vitest'

describe('MyComponent',()=>{
 it('should render correctly',()=>{
  // テストコード
 })
})
```

### pytest（バックエンド）

```python
# tests/unit/test_example.py
import pytest

def test_example():
    assert 1 + 1 == 2
```

### API契約テスト

OpenAPIスキーマとAPIレスポンスの整合性を検証:

```python
# tests/contract/test_api_contract.py
# Schemathesisを使用してOpenAPIスキーマに基づくテストを実行
```

## インストール

新しい依存関係をインストールするには:

```bash
# Backend
cd backend
pip install -r requirements.txt

# Frontend
cd langgraph-studio
npm install

# Root（husky）
cd ..
npm install
```
