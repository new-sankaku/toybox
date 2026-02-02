# 自己改善

## 概要

セッションログを振り返り、ユーザーの好みや成功/失敗パターンを抽出する。
定期的に改善提案を生成し、Human承認後にメモリファイルを更新する。

## 自己改善の2つのアプローチ

### アプローチ1: セッション終了時の振り返り

セッション終了後に、Reflectionエージェントが以下を抽出:
- うまくいったこと
- 失敗したこと
- 行った修正
- 学んだパターン

### アプローチ2: 定期的な積極的改善

15分ごとにエージェントが最近のやり取りをレビューし、改善を提案。
Human承認/却下のパターンから学習。

## セッション終了時の振り返り

### Reflectionエージェントの処理

1. 成功/失敗を分類
2. Human修正を分析
3. パターンを抽出（成功パターン、失敗パターン、修正からの洞察）
4. 改善提案を生成

### ReflectionReport

| フィールド | 説明 |
|-----------|------|
| session_id | セッションID |
| timestamp | タイムスタンプ |
| successes | 成功パターンのリスト |
| failures | 失敗パターンのリスト |
| corrections | Human修正からの洞察 |
| suggestions | 改善提案のリスト |

### Suggestion（改善提案）

| フィールド | 説明 |
|-----------|------|
| suggestion_id | 提案ID |
| type | skill / pattern / anti_pattern / preference |
| title | タイトル |
| description | 説明 |
| content | 内容 |
| confidence | 確信度（0.0 - 1.0） |
| evidence | 根拠となるタスクID |

## メモリファイルの更新

### 更新内容

| 対象 | 追加先 |
|------|-------|
| 成功パターン | learned_patterns |
| 失敗パターン | avoid_patterns |
| Human修正から学んだこと | preferences |

### メモリファイル構造（project_memory.yaml）

| セクション | 説明 |
|-----------|------|
| preferences | ユーザーの好み（code_style, workflow等） |
| learned_patterns | 成功パターン |
| avoid_patterns | 避けるべきパターン |
| auto_rules | 自動適用ルール（trigger, action, enabled） |

## Human連携

### 承認フロー

1. 改善提案生成
2. Human表示（WebUI）
3. 承認 → メモリ更新 / 却下 → 却下理由を記録 / 修正して承認 → 修正内容でメモリ更新

### 効果測定

| メトリクス | 説明 |
|-----------|------|
| suggestion_approval_rate | 提案の承認率 |
| memory_hit_rate | メモリがタスク実行に使用された率 |
| error_reduction_rate | メモリ適用後のエラー削減率 |
| human_correction_reduction | Human修正の削減率 |
