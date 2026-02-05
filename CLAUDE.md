# CLAUDE.md
・常に敬語を使う。
・Sonnet Haikuは禁止。
・サブエージェントはOpusを使用する。
・TaskはAgentが実行する個別の作業単位。AgentとTaskは別物です。
・クライアント修正時にデータフローを調査してサーバーの修正が不要か検討してください。逆にサーバーを修正するときもクライアントを調査します。
・HookやMCPなどのスクリプトはWindows/Linuxで動作するようにしてください。

## 修正前の方針
・安易な解決策を採用しない。
・質問するときは意図を明確にする。

## 修正の方針
・AIサービスはサーバー側設定ファイルとして持たせる。
・代替案はユーザー承認必須。
・実装はアルゴリズムの選定を含めて行う。
・業界標準のベストプラクティスを採用する。
・CSSの固定幅指定は禁止。フレキシブルなUIにする。
・コメントはTODO以外は不要
・バックエンドでprint()は禁止。必ず`from middleware.logger import get_logger`を使用する。
・スタックトレースを残す。
・ドキュメントはdocフォルダに格納する。
・本プロジェクトはエージェントシステムのためプロンプトは普遍的な方針を記載し、各エージェントが判断できるようにする。
・文言は他の画面と統一する。（例：Planning・企画中・計画中など）
・サーバー側はシミュレーションモード（testdata）とAPI利用モードの両方を修正する。

## 修正の禁止事項
・AIサービスはクライアント・サーバー共にハードコーディングは禁止。
・AI APIのプロバイダー・モデルをコード内にハードコードは禁止。
・フォールバック処理は誤認の元なので禁止。
・フォールバックではなく根本的治療を行う。
・ユーザーのフィードバックで問題が解決していない場合は調査範囲を変更し、調査範囲の変更を説明する。

## 修正後の作業
・doc/BUG_CHECKLIST.mdを確認してバグチェックを行う。
・完全なデータフローを確認必須、画面I/Fからバックエンド、DBまで。
・`10_build_check.bat` を実行する（サーバー起動不要）。

### 修正後の作業のスクリプト適用
```bash
cd langgraph-studio && npm run build
cd langgraph-studio && npm run format
cd backend && python scripts/remove-spaces.py
```

## スクリプト配置場所
`langgraph-studio/scripts/`
`backend/scripts/` 

## OpenAPI + TypeScript型自動生成
バックエンドのPydanticスキーマからOpenAPI + TypeScript型自動生成の仕組み
**構成:**
`backend/schemas/`(Pydanticスキーマ)→`backend/openapi/generator.py`(生成)→`langgraph-studio/src/types/openapi.json`→`langgraph-studio/src/types/api-generated.ts`
**スキーマ追加時:**
`backend/schemas/`に作成→`__init__.py`でエクスポート→`generator.py`に追加→「API型の整合性チェック」実行

## CSS/デザインルール
### サーフェスクラス（必須）
背景色と文字色の組み合わせミスを防ぐため、**サーフェスクラス**を使用する。定義が無い場合はサーフェスクラスを追加する。
`nier-surface-main` メインエリア
`nier-surface-panel` パネル/カード
`nier-surface-header` ヘッダー/ダーク領域
`nier-surface-footer` フッター
`nier-surface-selected` 選択状態
`nier-surface-main-muted` メインエリア（補助テキスト）
`nier-surface-panel-muted` パネル（補助テキスト）
`nier-surface-selected-muted` 選択状態（補助テキスト）

## API/WebSocket変更時のチェックリスト
**バックエンド:** 1.`backend/schemas/`更新 2.OpenAPIスペック再生成 3.WebSocket room指定確認
**フロントエンド:** 1.`apiService.ts`型更新 2.`websocket.ts`イベント型更新 3.Storeハンドラ更新 4.WebSocketService接続確認
**よくあるミス:** WebSocket型不一致(×4) ハンドラ未接続(×1) イベント型フィールド不足(×1) API型フィールド未反映(×2)
