# 開発ツール

## 概要

このプロジェクトでは、開発時に問題を早期発見するための各種ツールを導入しています。

## ツール一覧

| ツール | 対象 | 目的 | ビルドチェック |
|--------|------|------|----------------|
| Ruff | Backend | Pythonリンター | 含む |
| mypy | Backend | Python型チェック | 含む |
| ESLint | Frontend | TypeScriptリンター | 含む |
| TypeScript | Frontend | 型チェック | 含む |
| Vitest | Frontend | ユニットテスト | 含む |
| Playwright | Frontend | E2Eテスト | 手動 |
| pytest | Backend | ユニット/統合テスト | 手動 |
| Schemathesis | Backend | API契約テスト | 手動 |
| husky | 全体 | Git pre-commit hooks | 自動 |
| lint-staged | 全体 | ステージ済みファイルのリント | 自動 |

## 実行方法

### 一括チェック（推奨）

```bash
# 全チェック実行（サーバー起動不要）
10_build_check.bat
```

実行内容:
1. Ruff Lint
2. mypy Type Check
3. OpenAPI Spec Generation
4. TypeScript Type Generation
5. ESLint
6. TypeScript Type Check
7. Vitest Unit Tests

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
mypy . --ignore-missing-imports

# pytest（テスト）
pytest tests/ -v

# API契約テスト
pytest tests/contract/ -v
# または
schemathesis run openapi/openapi.json --base-url http://localhost:5000
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

# Playwright E2Eテスト
npm run test
```

## 設定ファイル

| ファイル | 説明 |
|----------|------|
| `backend/pyproject.toml` | Ruff、mypy、pytest設定 |
| `langgraph-studio/vitest.config.ts` | Vitest設定 |
| `langgraph-studio/eslint.config.mjs` | ESLint設定 |
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
