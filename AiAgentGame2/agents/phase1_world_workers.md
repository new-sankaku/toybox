# World Workers（ワールドワーカー）

World Leaderの配下で動作するWorker群。

## Geography Worker
- **役割**: 地理・マップ・ロケーションを設計
- **出力**: geography（map_type, scale, regions）, locations（id, name, type, gameplay_functions）

## Lore Worker
- **役割**: 歴史・設定・世界観を設計
- **出力**: world_rules（physics, technology_or_magic）, lore（timeline, mysteries, legends）

## System Worker
- **役割**: 経済システムと勢力を設計
- **出力**: economy（currency, resources, trade_system）, factions（id, name, goals, relationship_to_player）

## Worker間連携
Geography → Lore → System → World Leader（統合・品質管理）

## スキーマ
参照: `_SCHEMAS.md`
