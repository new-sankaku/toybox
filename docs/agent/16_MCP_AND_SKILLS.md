# MCPとスキルの活用

## 概要

MCP（Model Context Protocol）を活用しつつ、コンテキストウィンドウを節約するため、頻繁に使う機能はスキルコマンドとしてCLIラップする。
MCPのスキーマ情報を毎回読み込む必要がなくなり、コンテキストを実作業に使える。

## MCPとスキルコマンドの使い分け

| 用途 | MCP | スキルコマンド | 推奨 |
|------|-----|---------------|------|
| 複雑なAPI操作 | o | x | MCP |
| 頻繁に使う操作 | x | o | スキルコマンド |
| 対話的な操作 | o | x | MCP |
| 定型的な操作 | x | o | スキルコマンド |
| 新しいサービス | o | x | MCP |
| 安定したサービス | x | o | スキルコマンド |

## スキルコマンド

### 概念

MCP Server → ツール定義（毎回コンテキストを消費） → スキルコマンドに変換 → CLIラッパー（コンテキスト消費なし）

### フォルダ構造

| パス | 内容 |
|------|------|
| skills/commands/*.yaml | コマンド定義 |
| skills/scripts/*.sh | 実行スクリプト |

## コマンド定義形式（YAML）

| フィールド | 説明 |
|-----------|------|
| command | コマンド名（例: /gh-pr） |
| description | 説明 |
| version | バージョン |
| subcommands | サブコマンド定義 |

### サブコマンド定義

| フィールド | 説明 |
|-----------|------|
| description | サブコマンドの説明 |
| usage | 使用方法 |
| script | 実行するシェルスクリプト |
| parameters | パラメータ定義（name, type, required, default, description） |

## 登録済みスキルコマンド一覧

| コマンド | 説明 | サブコマンド |
|---------|------|-------------|
| /gh-pr | GitHub PR操作 | create, list, view, merge, review |
| /gh-issue | GitHub Issue操作 | create, list, view, close |
| /git | Git操作 | status, add, commit, push, pull |
| /supabase | Supabase操作 | db-push, db-reset, gen-types |
| /vercel | Vercel操作 | deploy, logs, env |
| /test | テスト実行 | run, watch, coverage |
| /lint | Lint実行 | check, fix |
| /format | フォーマット | check, fix |

## MCPを使わない方が良いケース

| ケース | 代替手段 |
|-------|---------|
| 単純なGit操作 | gitコマンド直接 |
| 単純なnpm操作 | npmコマンド直接 |
| ファイル読み書き | 標準ツール |
| 環境変数設定 | exportコマンド |

## コンテキスト節約効果

| 操作 | MCPスキーマ | スキルコマンド | 節約 |
|------|-----------|---------------|------|
| GitHub PR作成 | ~2,000 tokens | ~50 tokens | 97.5% |
| Supabase型生成 | ~1,500 tokens | ~30 tokens | 98% |
| Vercelデプロイ | ~1,200 tokens | ~40 tokens | 96.7% |

### 全体効果

1セッションでの推定:
- MCP使用時: 10,000 tokens（スキーマ読み込み）
- スキルコマンド: 500 tokens（コマンド実行）
- 節約: 9,500 tokens（95%削減）
- コスト換算: 約$0.03/セッション節約

## 新規スキルコマンドの追加

### 手順

1. skills/commands/{name}.yaml を作成
2. サブコマンドとスクリプトを定義
3. テスト実行
4. ドキュメントを更新
