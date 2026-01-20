# TaskSplit Workers（タスク分割ワーカー）

TaskSplit Leaderの配下で動作するWorker群。

## Analysis Worker
- **役割**: 企画成果物から要件を分析し、機能を抽出
- **出力**: requirements（id, type, description, priority）, features（id, name, complexity）

## Decomposition Worker
- **役割**: 機能をコードタスクとアセットタスクに分解
- **出力**: code_tasks, asset_tasks, dependency_map（code_to_code, asset_to_code, critical_path）

## Schedule Worker
- **役割**: イテレーション計画とマイルストーンを作成
- **出力**: iterations（number, goal, deliverables）, milestones, risks

## Worker間連携
Analysis → Decomposition → Schedule → TaskSplit Leader（統合・品質管理）

## スキーマ
参照: `_SCHEMAS.md`
