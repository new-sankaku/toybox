# 機械的作業戦略

## 概要

LLMを使用せずに機械的に実行できる作業はScriptで処理する。
画像の色調調整やファイルのフォーマット等、決定論的な処理はLLMよりScriptの方が高速・安価・確実。

## 判断基準

### LLM vs Script

| 作業種別 | LLM | Script | 理由 |
|---------|-----|--------|------|
| 画像リサイズ | x | o | パラメータ化可能 |
| 画像色調調整 | x | o | 決定論的処理 |
| 画像フォーマット変換 | x | o | 決定論的処理 |
| コードフォーマット | x | o | lint/prettier |
| ファイル一括置換 | x | o | sed/awk |
| テスト実行 | x | o | pytest/jest |
| ビルド実行 | x | o | npm/gradle |
| Gitコミット | x | o | コマンド実行 |
| デザイン生成 | o | x | 創造性が必要 |
| コード設計 | o | x | 判断が必要 |
| バグ修正 | o | x | 理解が必要 |
| レビュー | o | x | 判断が必要 |

### 判断フロー

タスクを受け取る → 機械的に実行可能か？ → Yes: Script実行 / No: LLMに依頼

## Scriptライブラリ

| カテゴリ | スクリプト例 |
|---------|------------|
| image/ | resize.py, color_adjust.py, format_convert.py, batch_process.py |
| code/ | format.sh, lint.sh, bulk_rename.py, dependency_update.py |
| test/ | run_tests.sh, coverage_report.py, benchmark.py |
| build/ | build.sh, package.py, deploy.sh |
| git/ | commit.sh, merge.sh, branch_cleanup.py |
| util/ | file_operations.py, json_yaml_converter.py |

## WORKERからのScript呼び出し

### ScriptExecutor

| メソッド | 説明 |
|---------|------|
| execute(script_name, args, timeout) | Scriptを実行 |
| find_script(name) | Scriptを検索 |
| build_command(script_path, args) | コマンドを構築 |

### ScriptResult

| フィールド | 説明 |
|-----------|------|
| success | 成功/失敗 |
| output | 標準出力 |
| error | エラー出力 |
| return_code | 終了コード |

## タスク種別判定

### マッピング

| タスク種別 | Script |
|-----------|--------|
| image_resize | image/resize |
| image_color_adjust | image/color_adjust |
| image_format_convert | image/format_convert |
| code_format | code/format |
| code_lint | code/lint |
| test_run | test/run_tests |
| build | build/build |

### WORKER内での分岐

1. タスクの種別を判定
2. Script実行可能 → ScriptExecutorで実行（トークン消費なし、コスト0）
3. Script実行不可 → LLMで実行

## コスト比較

| 処理 | LLM (トークン) | LLM (コスト) | Script | 速度比 |
|------|--------------|-------------|--------|--------|
| 画像リサイズ×10枚 | 5,000 | $0.015 | $0 | 100x |
| コードフォーマット | 2,000 | $0.006 | $0 | 50x |
| テスト実行 | 1,000 | $0.003 | $0 | 10x |
| 一括置換×100箇所 | 10,000 | $0.030 | $0 | 200x |

## 監視メトリクス

| メトリクス | 説明 |
|-----------|------|
| script_execution_count | Script実行回数 |
| script_success_rate | Script成功率 |
| tokens_saved | 節約されたトークン数 |
| cost_saved | 節約されたコスト |
