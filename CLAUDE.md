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
・誤認させるデフォルト値禁止** - API取得失敗時などに、実際とは異なる値をデフォルト値として画面に表示しない。取得失敗時は「-」や空欄、または「取得失敗」等の明示的な表示にすること。ユーザーを誤認させる情報を表示してはならない。
・文言の統一、画面に表示する文言（ラベル、ボタン、メッセージ等）は他の画面と統一的な表現にすること。新しい文言を追加する前に、既存の画面で使われている表現を確認して合わせる。


## 修正後の動作確認方法

コード修正後は `10_build_check.bat` を実行する（サーバー起動不要）。

**10_build_check.batの内容:**
1. Backend構文チェック
2. OpenAPIスペック生成
3. TypeScript型生成
4. ESLint
5. TypeScript型チェック

### コミット前の追加作業
```bash
# フルビルド確認
cd langgraph-studio && npm run build

# コード圧縮
cd langgraph-studio && npm run format   # スペース削除
cd backend && python scripts/remove-spaces.py
```

**圧縮ルール:**
- コロン/カンマ後: スペースなし
- アロー演算子前後: スペースなし
- コメント: 削除（TODO/FIXME以外）
- TypeScriptインデント: 1スペース


## OpenAPI + TypeScript型自動生成

バックエンドのPydanticスキーマからOpenAPIスペックを生成し、フロントエンドのTypeScript型を自動生成する仕組み。

**構成:**
- `backend/schemas/` - Pydanticスキーマ（camelCase alias自動生成）
- `backend/openapi/generator.py` - OpenAPIスペック生成
- `backend/scripts/generate_openapi.py` - OpenAPIスペックをJSONファイルに出力
- `langgraph-studio/src/types/openapi.json` - 生成されたOpenAPIスペック（.gitignore対象）
- `langgraph-studio/src/types/api-generated.ts` - 自動生成されるTypeScript型（.gitignore対象）

**スキーマ追加時:**
- `backend/schemas/` に新規スキーマファイルを作成
- `backend/schemas/__init__.py` でエクスポート
- `backend/openapi/generator.py` のスキーマリストとパス定義に追加
- 「API型の整合性チェック」を実行して確認

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

**使用ルール:**
1. UIコンポーネント（Card, Button等）を優先的に使用する
2. 直接divを使う場合は `.nier-surface-*` クラスを使用する
3. `bg-nier-bg-*` と `text-nier-text-*` を直接組み合わせない（組み合わせミスの原因）

**禁止パターン:**
```tsx
// NG: 背景と文字を別々に指定（ミスしやすい）
<div className="bg-nier-bg-header text-nier-text-main">

// OK: サーフェスクラスを使用
<div className="nier-surface-header">

// OK: コンポーネントを使用
<Card><CardHeader>...</CardHeader></Card>
```

### コンポーネントクラス

| クラス | 用途 |
|--------|------|
| `.nier-card` | カード外枠 |
| `.nier-card-header` | カードヘッダー（ダーク背景） |
| `.nier-card-body` | カード本体（パネル背景） |
| `.nier-btn` | 標準ボタン |
| `.nier-btn-primary` | プライマリボタン |
| `.nier-btn-danger` | 危険アクションボタン |
| `.nier-input` | 入力フィールド |

### アクセントカラー（状態表示用）

| 変数 | 用途 |
|------|------|
| `--accent-red` | エラー/Critical |
| `--accent-orange` | 実行中/Warning |
| `--accent-yellow` | 待機中/Pending |
| `--accent-green` | 完了/Success |
| `--accent-blue` | 情報/Info |

## API/WebSocket変更時のチェックリスト

APIやWebSocketイベントを変更・追加する際は、以下を必ず確認する。

**バックエンド変更時:**
1. `backend/schemas/` の型定義を更新
2. OpenAPIスペック再生成（`10_build_check.bat`で自動実行）
3. WebSocketイベントを送信している場合、room指定が正しいか確認

**フロントエンド変更時:**
1. `langgraph-studio/src/services/apiService.ts` の型定義を更新
2. `langgraph-studio/src/types/websocket.ts` のイベント型を更新（WebSocket関連の場合）
3. 該当Storeのイベントハンドラを更新
4. WebSocketServiceの接続処理を確認

**よくあるミス（BUG_CHECKLIST.mdより）:**
- WebSocket型定義がサーバー側イベントと一致していない（×4）
- WebSocketイベントハンドラが未接続（×1）
- WebSocketイベント型にフィールドが不足（×1）
- API型定義にサーバー側で追加されたフィールドが反映されていない（×2）
