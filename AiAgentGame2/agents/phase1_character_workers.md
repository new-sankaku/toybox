# Character Workers（キャラクターワーカー）

Character Leaderの配下で動作するWorker群。

## MainCharacter Worker
- **役割**: プレイヤーキャラクターと主要キャラクターを設計
- **出力**: player_character, main_characters（id, name, archetype, role, personality, visual_design）

## NPC Worker
- **役割**: NPC、敵キャラクター、ボスを設計
- **出力**: npcs（id, name, role, location, function）, enemies（regular, bosses）

## Relationship Worker
- **役割**: キャラクター間の関係性と相関図を設計
- **出力**: connections, factions, key_dynamics

## Worker間連携
MainCharacter → NPC → Relationship → Character Leader（統合・品質管理）

## スキーマ
参照: `_SCHEMAS.md`
