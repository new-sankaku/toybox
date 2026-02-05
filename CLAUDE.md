## 規則
・敬語の使用
・SubAgentはClaude Opusを使用
・カタカナはToken圧縮のため、英単語にします。

## 禁止事項
・SubAgentにHaikuは禁止

## 注意事項
・TaskはAgentの個別実行する作業単位。
・AgentとTaskは別物。
・HookやMCP、ScriptはWindows/Linuxで動作必須。

## 修正前の方針
・安易な解決策を採用しない。
・質問は意図を明確に。

## 修正の方針
・AI Service設定値はServer Config fileにする。
・代替案はuser承認必須。
・高度な実装はAlgorithmの選定を行う。
・業界標準のBest Practiceを使用する。
・CSSの固定幅指定は禁止。FlexibleなUIにする。
・CommentはTODO以外は不要
・Backendでprint()は禁止。必ず`from middleware.logger import get_logger`を使用する。
・StackTraceを残す。
・Documentはdoc folderに格納する。
・このProjectはAgent SystemのためPromptは普遍的な方針を記載し、Agentが判断できるようにする。
・文言は他の画面と統一する。（例：Planning・企画中・計画中など）
・Serverはsimulation（testdata）とAPI modeを修正する。

## 修正の禁止事項
・hard-codeは禁止。
・AI APIのProvider or Modelのhard cord。
・Fallback処理は誤認の元なので禁止。
・No fallback; fix underlying issue
・UserのFeedbackで問題が解決しない場合は調査範囲を拡大する。

## 修正後の作業
・doc/BUG_CHECKLIST.mdを確認して類似確認を行う。
・完全なdata flowの確認が必須、画面I/FからBackend、DBまで。
・`10_build_check.bat` を実行する（Server起動不要）。

### 修正後のScript実行
```bash
cd langgraph-studio && npm run build
cd langgraph-studio && npm run format
cd backend && python scripts/remove-spaces.py
```

## Script配置場所
`langgraph-studio/scripts/`
`backend/scripts/` 

## OpenAPI + TypeScript型自動生成
BackendのPydantic schemaからOpenAPI + TypeScript型自動生成の仕組み
**構成:**
`backend/schemas/`(Pydantic schema)→`backend/openapi/generator.py`(生成)→`langgraph-studio/src/types/openapi.json`→`langgraph-studio/src/types/api-generated.ts`
**schema追加時:**
`backend/schemas/`に作成→`__init__.py`でExport→`generator.py`に追加→「API型の整合性Check」実行

## CSS desighn rules
### Surface Class（必須）
背景色と文字色の視認性低下、**Surface Class**を使用する。定義が無い場合はSurface classを追加する。
`nier-surface-main`
`nier-surface-panel` card
`nier-surface-header`
`nier-surface-footer`
`nier-surface-selected`
`nier-surface-main-muted`
`nier-surface-panel-muted`
`nier-surface-selected-muted`

## API/WebSocket変更時のCheck list
**Backend:** 1.`backend/schemas/`更新 2.OpenAPI Spec再生成 3.WebSocket room指定確認
**Frontend:** 1.`apiService.ts`型更新 2.`websocket.ts`Event型更新 3.Store handler更新 4.WebSocketService接続確認
**よくあるミス:** WebSocket型不一致(×4) handler未接続(×1) event型field不足(×1) API型field未反映(×2)
