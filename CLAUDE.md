# CLAUDE.md

・修正後はdoc/BUG_CHECKLIST.mdを確認しバグを作り込んでいないか確認する。同様の問題が発生した場合は×1などの回数をインクリメントする。
・AIサービスはサーバー側設定ファイルとして持たせる。
・同じ設定を複数の設定ファイルに分割せず一つにする。
・画面側にAIサービスはハードコーディングしない。
・AI APIのプロバイダー・モデルをコード内にハードコードしない。設定ファイルまたはプロジェクト設定から動的に解決する。
・安易な解決策を採用するな。
・代替案は提示して許可をとれ。
・実装はアルゴリズムの選定を行え。
・ベストプラクティスを採用しろ。
・意味のない質問はするな。質問が必要なら意図を明確にして何故その質問をしたか書け。
・固定値は避けてフレキシブルなUIにする。
・AIサービスは固定でWeb上に表示しない。AIサービスはプロジェクトによって使う使わないがあるので、使わないものは表示しない。
・クライアント画面でのフォールバック処理はユーザーを誤認させるため行わない。誤認の心配がない場合は可能。
・フォールバック処理を行う前に根本的対策を行う。
・サーバーからデータが取得できないためのフォールバックは禁止。
・サーバー側に設定値を持たせ、クライアント側ではべた書きなど設定値は持たない。
・常に敬語を使う。
・コメントはTODO以外は不要
・バックエンドでprint()は禁止。必ず`from middleware.logger import get_logger`を使用し、`get_logger().info/warning/error()`で出力する。例外ハンドラ内のerrorログには`exc_info=True`を付与してスタックトレースを残す。
・Sonnet Haikuをサブエージェントとすることは禁止、サブエージェントはOpusを使用する。
・曖昧な可能性で直すな。論理的な根拠を持って直せ。
・ドキュメントは全てdocフォルダに格納する。
・エージェントシステムのため、プロンプトを固めるのではなく普遍的な方針を記載し、各エージェントが判断できるようにする。硬直化したプロンプトは記載しない。
・CSSの固定幅指定は行わない。フレキシブルデザインにする。
・TaskはAgentが実行する個別の作業単位。AgentとTaskは別物。
・nulファイルの作成禁止 Windowsで出力を破棄する場合、`> nul` を使用しない。代わりに `> /dev/null 2>&1` を使用するか、出力リダイレクトを使わない。
・応急処置の禁止。インラインスタイル（`style={{ }}`）でのべた書きは禁止。必ずTailwindクラスまたはCSSファイルを使用すること。
・推測での修正禁止。「たぶんこれだろう」で修正を始めない。必ず問題の要素を特定してから修正すること。
・同じ調査の繰り返し禁止。同じ問題が再度発生した場合、前回と同じ視点で調査しない。別の観点（親要素、子要素、関連コンポーネント、CSS継承、Tailwind設定など）から調べ直すこと。
・誤認させるデフォルト値禁止 - API取得失敗時などに、実際とは異なる値をデフォルト値として画面に表示しない。取得失敗時は「-」や空欄、または「取得失敗」等の明示的な表示にすること。ユーザーを誤認させる情報を表示してはならない。
・文言の統一、画面に表示する文言（ラベル、ボタン、メッセージ等）は他の画面と統一的な表現にすること。新しい文言を追加する前に、既存の画面で使われている表現を確認して合わせる。

## 修正後の動作確認方法
コード修正後は `10_build_check.bat` を実行する（サーバー起動不要）。
**10_build_check.batの内容:** Backend構文チェック→OpenAPIスペック生成→TypeScript型生成→ESLint→TypeScript型チェック

### コミット前の追加作業
```bash
cd langgraph-studio && npm run build      # フルビルド確認
cd langgraph-studio && npm run format     # スペース削除
cd backend && python scripts/remove-spaces.py
```
**圧縮ルール:** コロン/カンマ後スペースなし、アロー演算子前後スペースなし、コメント削除（TODO/FIXME以外）、TypeScriptインデント1スペース

## OpenAPI + TypeScript型自動生成
バックエンドのPydanticスキーマからOpenAPIスペックを生成し、フロントエンドのTypeScript型を自動生成する仕組み。
**構成:** `backend/schemas/`(Pydanticスキーマ)→`backend/openapi/generator.py`(生成)→`langgraph-studio/src/types/openapi.json`→`langgraph-studio/src/types/api-generated.ts`
**スキーマ追加時:** `backend/schemas/`に作成→`__init__.py`でエクスポート→`generator.py`に追加→「API型の整合性チェック」実行

## CSS/デザインルール
### サーフェスクラス（必須）
背景色と文字色の組み合わせミスを防ぐため、**サーフェスクラス**を優先的に使用する。
| クラス | 用途 | 背景 | 文字 |
|--------|------|------|------|
| `nier-surface-main` | メインエリア | 明るいベージュ | 暗い茶色 |
| `nier-surface-panel` | パネル/カード | やや暗いベージュ | 暗い茶色 |
| `nier-surface-header` | ヘッダー/ダーク領域 | 暗い茶色 | 明るいベージュ |
| `nier-surface-footer` | フッター | 暗い茶色 | 明るいベージュ |
| `nier-surface-selected` | 選択状態 | 中間ベージュ | 暗い茶色 |

**使用ルール:** 1.UIコンポーネント優先 2.直接divを使う場合は`.nier-surface-*`クラス 3.`bg-nier-bg-*`と`text-nier-text-*`を直接組み合わせない
```tsx
// NG: <div className="bg-nier-bg-header text-nier-text-main">
// OK: <div className="nier-surface-header">
// OK: <Card><CardHeader>...</CardHeader></Card>
```

### コンポーネントクラス
`.nier-card`(カード外枠) `.nier-card-header`(ダーク背景) `.nier-card-body`(パネル背景) `.nier-btn`(標準) `.nier-btn-primary`(プライマリ) `.nier-btn-danger`(危険) `.nier-input`(入力)

### アクセントカラー
`--accent-red`(エラー) `--accent-orange`(実行中) `--accent-yellow`(待機) `--accent-green`(完了) `--accent-blue`(情報)

## API/WebSocket変更時のチェックリスト
**バックエンド:** 1.`backend/schemas/`更新 2.OpenAPIスペック再生成 3.WebSocket room指定確認
**フロントエンド:** 1.`apiService.ts`型更新 2.`websocket.ts`イベント型更新 3.Storeハンドラ更新 4.WebSocketService接続確認
**よくあるミス:** WebSocket型不一致(×4) ハンドラ未接続(×1) イベント型フィールド不足(×1) API型フィールド未反映(×2)
