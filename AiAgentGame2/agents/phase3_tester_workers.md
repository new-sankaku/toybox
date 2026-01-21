# Tester Workers（テスターワーカー）

Tester Leaderの配下で動作するWorker群。

## UnitTest Worker
- **役割**: ユニットテストを実行し、カバレッジを測定
- **出力**: total, passed, failed, coverage（statements/branches/functions/lines）, failed_tests

## IntegrationTest Worker
- **役割**: 統合テストを実行
- **出力**: total, passed, failed, results（name, status, duration_ms, error）

## E2ETest Worker
- **役割**: E2Eシナリオテストを実行
- **出力**: total, passed, failed, scenarios（name, steps, status, screenshot, error）

## PerformanceTest Worker
- **役割**: パフォーマンステストと負荷テストを実行
- **出力**: fps, load_time, memory（initial/peak/leak_detected）, bottlenecks

## Worker間連携
UnitTest → IntegrationTest → E2ETest → PerformanceTest → Tester Leader（統合・品質管理）

## スキーマ
参照: `_SCHEMAS.md`
