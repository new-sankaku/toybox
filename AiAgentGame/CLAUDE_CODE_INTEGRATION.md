# Claude Code Integration Guide

## 🔄 ファイルベース委譲システム

AI Agent Game CreatorはClaude Codeと連携して複雑なタスクを委譲できます。

## 📋 仕組み

```
┌─────────────────────────────────────────────────┐
│  1. Agent が複雑なタスクを検出                  │
│     - 100行以上のコード                         │
│     - 3ファイル以上の変更                       │
│     - 高い複雑度スコア                          │
│     - リトライ上限到達                          │
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│  2. タスクファイルを生成                        │
│     claude_tasks/task_xxx.json                  │
│     {                                            │
│       "task_type": "refactor",                  │
│       "description": "...",                     │
│       "target_files": ["output/code/main.py"],  │
│       "priority": "high"                        │
│     }                                            │
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│  3. Claude Code が処理 (別セッション)           │
│     - タスクファイルを読み込み                  │
│     - 指定されたファイルを編集                  │
│     - 結果ファイルを出力                        │
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│  4. Agent が結果を取得                          │
│     claude_results/task_xxx_result.json         │
│     {                                            │
│       "success": true,                          │
│       "modified_files": [...],                  │
│       "summary": "..."                          │
│     }                                            │
└─────────────────────────────────────────────────┘
```

## 🚀 使い方

### 自動委譲（推奨）

システムが自動的に複雑なタスクを検出して委譲します：

```bash
# 複雑なゲームを生成
python -m src.main "Create a complex RPG with inventory system" --phase generate

# 出力例:
# 💻 CODER AGENT
# 📊 Complexity detected: 150 LOC, 5 mechanics
# 🔄 Delegating to Claude Code: LOC (150) exceeds threshold
#
# 📝 Claude Code task created: code_generation_1234567890
#    Task file: claude_tasks/code_generation_1234567890.json
#    ⏳ Waiting for Claude Code to process this task...
```

### 手動で処理

1. **タスクファイルを確認**:
```bash
ls -l claude_tasks/
# code_generation_1234567890.json
```

2. **別のターミナルでClaude Codeを起動**:
```bash
# タスクファイルの内容を読む
cat claude_tasks/code_generation_1234567890.json

# Claude Codeで処理
# 例: 指定されたファイルを編集、テスト、確認
```

3. **結果ファイルを作成**:
```bash
cat > claude_results/code_generation_1234567890_result.json << 'EOF'
{
  "task_id": "code_generation_1234567890",
  "success": true,
  "modified_files": ["output/code/main.py", "output/code/inventory.py"],
  "summary": "Implemented RPG system with inventory management",
  "errors": [],
  "completed_at": "2025-01-14T10:00:00Z"
}
EOF
```

4. **システムが自動的に結果を検出**（ポーリング中の場合）

## 📝 タスクファイル形式

### code_generation タスク
```json
{
  "task_id": "code_generation_1234567890",
  "task_type": "code_generation",
  "description": "Generate a complete pygame game:\n\nTitle: My RPG\nGenre: rpg\n...",
  "target_files": [
    "output/code/main.py",
    "output/code/README.md"
  ],
  "context": "Game spec: {...}",
  "priority": "high",
  "created_at": "2025-01-14T09:00:00Z",
  "status": "pending"
}
```

### debug タスク
```json
{
  "task_id": "debug_1234567890",
  "task_type": "debug",
  "description": "Debug and fix errors in main.py:\n\nErrors found:\n- Line 45: NameError...",
  "target_files": [
    "output/code/main.py"
  ],
  "context": "Errors: ...",
  "priority": "high",
  "created_at": "2025-01-14T09:10:00Z",
  "status": "pending"
}
```

## 🔍 委譲条件

### Coder Agent
自動的に委譲される条件：
- 推定コード行数: 100行以上
- 対象ファイル数: 3ファイル以上
- 複雑度スコア: 0.7以上（メカニクス数に基づく）
- 特殊タスク: refactor_large, optimize, security_audit

### Debugger Agent
自動的に委譲される条件：
- リトライ回数: 3回以上
- 複雑なロジックエラー: 3つ以上
- 複数ファイルに跨るエラー: 3ファイル以上

## 📊 結果ファイル形式

成功時:
```json
{
  "task_id": "code_generation_1234567890",
  "success": true,
  "modified_files": [
    "output/code/main.py",
    "output/code/inventory.py",
    "output/code/battle.py"
  ],
  "summary": "Implemented RPG system with:\n- Inventory management\n- Battle system\n- Save/Load functionality",
  "errors": [],
  "completed_at": "2025-01-14T10:00:00Z"
}
```

失敗時:
```json
{
  "task_id": "debug_1234567890",
  "success": false,
  "modified_files": [],
  "summary": "Could not fix all errors",
  "errors": [
    "Line 45: Unresolved NameError",
    "Module 'pygame' not found"
  ],
  "completed_at": "2025-01-14T10:05:00Z"
}
```

## 🛠️ テスト

### 例題タスクの生成
```python
from src.tools import ClaudeCodeDelegate

delegate = ClaudeCodeDelegate()

# 例題タスクを作成
delegate.create_example_task()
# ✅ Created example task: claude_tasks/example_refactor_001.json

# 例題結果を作成
delegate.create_example_result()
# ✅ Created example result: claude_results/example_refactor_001_result.json

# 結果を確認
result = delegate.check_result("example_refactor_001")
print(f"Success: {result['success']}")
print(f"Summary: {result['summary']}")
```

### 手動テスト
```bash
# 1. 例題を生成
python -c "from src.tools import ClaudeCodeDelegate; d = ClaudeCodeDelegate(); d.create_example_task(); d.create_example_result()"

# 2. タスクファイルを確認
cat claude_tasks/example_refactor_001.json

# 3. 結果ファイルを確認
cat claude_results/example_refactor_001_result.json

# 4. システムから読み込み
python -c "from src.tools import ClaudeCodeDelegate; d = ClaudeCodeDelegate(); result = d.check_result('example_refactor_001'); print(result)"
```

## ⚙️ 設定

委譲閾値は `config/agent_config.yaml` で変更可能:

```yaml
claude_code:
  enabled: true
  delegation_threshold:
    lines_of_code: 100      # デフォルト: 100
    file_count: 3           # デフォルト: 3
    complexity_score: 0.7   # デフォルト: 0.7
```

## 🔐 セキュリティ

- タスクファイルは読み取り専用として扱う
- 結果ファイルは検証後に削除される
- サンドボックス環境での実行を推奨

## 📚 関連ファイル

- `src/tools/claude_code_tools.py` - Claude Code連携ツール
- `src/agents/coder.py` - Coder Agentの委譲ロジック
- `src/agents/debugger.py` - Debugger Agentの委譲ロジック
- `config/agent_config.yaml` - 委譲閾値設定

---

**💡 Tip**: Claude Codeセッションを別ウィンドウで起動しておくと、リアルタイムで処理できます！
