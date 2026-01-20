# Design Workers（デザインワーカー）

Design Leaderの配下で動作するWorker群。

## Architecture Worker
- **役割**: システムアーキテクチャの設計
- **設計観点**: アーキテクチャパターン、レイヤー構成、モジュール分割、技術スタック

## Component Worker
- **役割**: 個別コンポーネントの詳細設計
- **設計観点**: インターフェース定義、依存関係、実装メモ

## DataFlow Worker
- **役割**: データフローと状態管理の設計
- **設計観点**: 状態管理パターン、イベントシステム、データ永続化

## Worker間連携
Architecture → Component → DataFlow → Design Leader（統合・品質管理）

## スキーマ
参照: `_SCHEMAS.md`
