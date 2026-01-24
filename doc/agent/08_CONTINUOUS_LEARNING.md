# フィードバック・継続学習

## 概要

Agentが発見した知見（デバッグ技術、回避策、プロジェクト固有パターン）をスキルとして保存し、次回同様の問題発生時に自動的に読み込む。
同じ試行錯誤の繰り返しを防ぎ、トークン・時間・コストを節約する。

## 知識の階層

| 階層 | パス | 説明 |
|------|------|------|
| グローバル | knowledge_base/global/ | 全プロジェクト共通 |
| グループ | knowledge_base/groups/{phase}/ | フェーズ単位の知見 |
| プロジェクト | knowledge_base/projects/{project_id}/ | プロジェクト固有 |

## スキルファイル形式（YAML）

| フィールド | 説明 |
|-----------|------|
| skill_id | スキルID |
| name | スキル名 |
| version | バージョン |
| triggers | 自動読み込み条件（keywords, file_patterns, task_types） |
| content | スキル内容（Markdown） |
| stats | 使用統計（times_loaded, success_rate, avg_tokens_saved） |
| related_skills | 関連スキルID |

## パターンファイル形式

### 成功パターン（patterns/）

| フィールド | 説明 |
|-----------|------|
| pattern_id | パターンID |
| name | パターン名 |
| type | "success" |
| context | 適用コンテキスト |
| solution | 解決策 |
| evidence | 成功事例のリスト |
| tags | タグ |

### 失敗パターン（anti_patterns/）

| フィールド | 説明 |
|-----------|------|
| pattern_id | パターンID |
| name | パターン名 |
| type | "failure" |
| context | 適用コンテキスト |
| bad_approach | 悪いアプローチ |
| why_bad | 悪い理由 |
| correct_approach | 正しいアプローチ |
| evidence | 失敗事例のリスト |

## スキルの自動読み込み

### トリガーマッチング

1. タスクのobjective、descriptionからキーワードをマッチ
2. 変更対象ファイルのパターンをマッチ
3. タスクタイプをマッチ
4. スコアの高いスキルを上位5件まで読み込み

### コンテキスト注入

タスク実行時に関連スキル、成功パターン、失敗パターンをコンテキストに追加。

## 学習プロセス

### タスク完了時

1. 成功 → 成功パターンを抽出（新しいアプローチの場合）
2. 失敗 → 失敗パターンを記録

### Human修正からの学習

1. 修正内容の差分を分析
2. 修正パターンを記録
3. 類似の間違いを防ぐスキルを生成

### メモリファイル更新

- 成功パターン → learned_patterns に追加
- 失敗パターン → avoid_patterns に追加
- Human修正 → preferences に追加

## 効果測定

| メトリクス | 説明 |
|-----------|------|
| skill_hit_rate | スキルが使用された割合 |
| retry_reduction | リトライ回数の削減率 |
| token_savings | 節約されたトークン数 |
| human_correction_reduction | Human修正回数の削減率 |
