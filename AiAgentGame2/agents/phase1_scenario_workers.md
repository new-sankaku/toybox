# Scenario Workers（シナリオワーカー）

Scenario Leaderの配下で動作するWorker群。

## Story Worker
- **役割**: メインストーリーと章構成を作成
- **出力**: main_story（premise, theme, plot_summary）, chapters

## Dialog Worker
- **役割**: キャラクターの会話・ダイアログを作成
- **出力**: dialogs（id, scene, participants, lines）

## Event Worker
- **役割**: ゲームイベントと分岐を設計
- **出力**: events（id, type, trigger, branches）

## Worker間連携
Story → Dialog → Event → Scenario Leader（統合・品質管理）

## スキーマ
参照: `_SCHEMAS.md`
