# Integrator Workers（インテグレーターワーカー）

Integrator Leaderの配下で動作するWorker群。

## Dependency Worker
- **役割**: 依存関係の解決とパッケージ管理
- **出力**: npm_packages, local_modules, asset_references（resolved/unresolved）

## Build Worker
- **役割**: ビルドの実行とバンドル生成
- **出力**: build_summary（status, duration）, integrated_files, build_checks

## IntegrationValidation Worker
- **役割**: 起動テストと基本動作確認
- **出力**: startup_checks（compilation, asset_loading, startup, initial_render）, issues

## Worker間連携
Dependency → Build → IntegrationValidation → Integrator Leader（統合・品質管理）

## スキーマ
参照: `_SCHEMAS.md`
