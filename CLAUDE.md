# CLAUDE.md
・常に敬語を使ってください。
・Sonnet Haikuは禁止。
・サブエージェントはOpusを使用する。
・TaskはAgentが実行する個別の作業単位。AgentとTaskは別物です。

## 修正前の方針
・安易な解決策を採用しない。
・質問するときは意図を明確にする。

## 修正の方針
・AIサービスはサーバー側設定ファイルとして持たせる。
・同じ設定を複数の設定ファイルに作らない。
・代替案を勝手に進めない。
・実装はアルゴリズムの選定を含めて行う。
・ベストプラクティスを採用する。
・CSSの固定幅指定は行わない。フレキシブルなUIにする。
・コメントはTODO以外は不要
・バックエンドでprint()は禁止。必ず`from middleware.logger import get_logger`を使用する。
・スタックトレースを残す。
・曖昧な可能性で直さず論理的な根拠を持って直す。
・ドキュメントはdocフォルダに格納する。
・本プロジェクトはエージェントシステムのためプロンプトは普遍的な方針を記載し、各エージェントが判断できるようにする。
・応急処置の禁止。インラインスタイル（`style={{ }}`）でのべた書きは禁止。必ずTailwindクラスまたはCSSファイルを使用すること。
・文言は統一する必要があるため、他の画面で似た文言が使われていないか確認する。（例：Planning・企画中・計画中など）
・サーバー側はシミュレーションモード（testdata）とAPI利用モードの両方を修正する。

## 修正の禁止事項
・AIサービスはクライアント・サーバー共にハードコーディングは禁止。
・AI APIのプロバイダー・モデルをコード内にハードコードは禁止。
・フォールバック処理は誤認の元なので禁止。
・フォールバックではなく根本的治療を行う。
・ユーザーのフィードバックで問題が解決していない場合は調査範囲を変更し、調査範囲の変更を説明する。

## 修正後の作業
・修正後はdoc/BUG_CHECKLIST.mdを確認してバグチェックを行う。
・完全なデータフローを確認してください。プログラムの開始から終了までをチェックし、漏れが無いか確認する。クライアントであれば入力からサーバー側のDB保存、DBからの取得まで水平確認する。

## 修正後の動作確認方法
コード修正後は `10_build_check.bat` を実行する（サーバー起動不要）。

### コミット前の追加作業
```bash
cd langgraph-studio && npm run build      # フルビルド確認
cd langgraph-studio && npm run format     # スペース削除
cd backend && python scripts/remove-spaces.py
```

## OpenAPI + TypeScript型自動生成
バックエンドのPydanticスキーマからOpenAPIスペックを生成し、フロントエンドのTypeScript型を自動生成する仕組み。
**構成:** `backend/schemas/`(Pydanticスキーマ)→`backend/openapi/generator.py`(生成)→`langgraph-studio/src/types/openapi.json`→`langgraph-studio/src/types/api-generated.ts`
**スキーマ追加時:** `backend/schemas/`に作成→`__init__.py`でエクスポート→`generator.py`に追加→「API型の整合性チェック」実行

## CSS/デザインルール
### サーフェスクラス（必須）
背景色と文字色の組み合わせミスを防ぐため、**サーフェスクラス**を優先的に使用する。
`nier-surface-main` メインエリア 
`nier-surface-panel` パネル/カード
`nier-surface-header` ヘッダー/ダーク領域 |
`nier-surface-footer` フッター 
`nier-surface-selected` 選択状態 

**使用ルール:** 1.UIコンポーネント優先 2.直接divを使う場合は`.nier-surface-*`クラス 3.`bg-nier-bg-*`と`text-nier-text-*`を直接組み合わせない

### コンポーネントクラス
`.nier-card`(カード外枠) `.nier-card-header`(ダーク背景) `.nier-card-body`(パネル背景) `.nier-btn`(標準) `.nier-btn-primary`(プライマリ) `.nier-btn-danger`(危険) `.nier-input`(入力)

### アクセントカラー
`--accent-red`(エラー) `--accent-orange`(実行中) `--accent-yellow`(待機) `--accent-green`(完了) `--accent-blue`(情報)

## API/WebSocket変更時のチェックリスト
**バックエンド:** 1.`backend/schemas/`更新 2.OpenAPIスペック再生成 3.WebSocket room指定確認
**フロントエンド:** 1.`apiService.ts`型更新 2.`websocket.ts`イベント型更新 3.Storeハンドラ更新 4.WebSocketService接続確認
**よくあるミス:** WebSocket型不一致(×4) ハンドラ未接続(×1) イベント型フィールド不足(×1) API型フィールド未反映(×2)
