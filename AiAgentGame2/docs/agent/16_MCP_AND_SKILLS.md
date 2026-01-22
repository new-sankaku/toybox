# MCPとスキルの活用

## 概要

MCP（Model Context Protocol）を活用しつつ、コンテキストウィンドウを節約するため、頻繁に使う機能はスキルコマンドとしてCLIラップする。
MCPのスキーマ情報を毎回読み込む必要がなくなり、コンテキストを実作業に使える。

## MCPとスキルコマンドの使い分け

| 用途 | MCP | スキルコマンド | 推奨 |
|------|-----|---------------|------|
| 複雑なAPI操作 | o | x | MCP |
| 頻繁に使う操作 | x | o | スキルコマンド |
| 対話的な操作 | o | x | MCP |
| 定型的な操作 | x | o | スキルコマンド |
| 新しいサービス | o | x | MCP |
| 安定したサービス | x | o | スキルコマンド |

## スキルコマンド

### 概念

```
MCP Server
    │
    └── ツール定義（毎回コンテキストを消費）

    ↓ 変換

スキルコマンド
    │
    └── CLIラッパー（コンテキスト消費なし）
```

### フォルダ構造

```
skills/
├── commands/
│   ├── gh-pr.yaml
│   ├── gh-issue.yaml
│   ├── git.yaml
│   ├── supabase.yaml
│   └── vercel.yaml
│
├── scripts/
│   ├── gh-pr.sh
│   ├── gh-issue.sh
│   └── ...
│
└── README.md
```

### コマンド定義形式

#### skills/commands/gh-pr.yaml

```yaml
command: "/gh-pr"
description: "GitHub Pull Request操作"
version: "1.0"

subcommands:
  create:
    description: "PRを作成"
    usage: "/gh-pr create [--title TITLE] [--body BODY] [--base BASE]"
    script: |
      gh pr create \
        --title "${title:-}" \
        --body "${body:-}" \
        --base "${base:-main}"
    parameters:
      - name: title
        type: string
        required: false
        description: "PRのタイトル"
      - name: body
        type: string
        required: false
        description: "PRの本文"
      - name: base
        type: string
        required: false
        default: "main"
        description: "マージ先ブランチ"

  list:
    description: "PR一覧を表示"
    usage: "/gh-pr list [--state STATE]"
    script: |
      gh pr list --json number,title,state,author \
        --state "${state:-open}"
    parameters:
      - name: state
        type: string
        required: false
        default: "open"
        enum: ["open", "closed", "merged", "all"]

  view:
    description: "PRの詳細を表示"
    usage: "/gh-pr view NUMBER"
    script: |
      gh pr view ${number} --json title,body,state,comments
    parameters:
      - name: number
        type: integer
        required: true
        description: "PR番号"

  merge:
    description: "PRをマージ"
    usage: "/gh-pr merge NUMBER [--squash]"
    script: |
      gh pr merge ${number} ${squash:+--squash}
    parameters:
      - name: number
        type: integer
        required: true
      - name: squash
        type: boolean
        required: false
        default: false

  review:
    description: "PRをレビュー"
    usage: "/gh-pr review NUMBER --approve|--comment BODY"
    script: |
      if [ -n "${approve}" ]; then
        gh pr review ${number} --approve
      elif [ -n "${comment}" ]; then
        gh pr review ${number} --comment --body "${comment}"
      fi
    parameters:
      - name: number
        type: integer
        required: true
      - name: approve
        type: boolean
        required: false
      - name: comment
        type: string
        required: false
```

#### skills/commands/supabase.yaml

```yaml
command: "/supabase"
description: "Supabase操作"
version: "1.0"

subcommands:
  db-push:
    description: "マイグレーションを適用"
    usage: "/supabase db-push"
    script: |
      supabase db push

  db-reset:
    description: "データベースをリセット"
    usage: "/supabase db-reset"
    script: |
      supabase db reset

  gen-types:
    description: "TypeScript型を生成"
    usage: "/supabase gen-types [--output PATH]"
    script: |
      supabase gen types typescript \
        --local \
        > "${output:-src/types/supabase.ts}"
    parameters:
      - name: output
        type: string
        required: false
        default: "src/types/supabase.ts"

  functions-deploy:
    description: "Edge Functionsをデプロイ"
    usage: "/supabase functions-deploy [NAME]"
    script: |
      if [ -n "${name}" ]; then
        supabase functions deploy ${name}
      else
        supabase functions deploy
      fi
    parameters:
      - name: name
        type: string
        required: false
```

## スキルコマンド実行

### SkillCommandExecutor

```python
import yaml
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass

@dataclass
class CommandResult:
    success: bool
    output: str
    error: Optional[str]

class SkillCommandExecutor:
    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self.commands = self._load_commands()

    def _load_commands(self) -> Dict[str, dict]:
        """コマンド定義を読み込み"""
        commands = {}
        commands_dir = self.skills_dir / "commands"

        for yaml_file in commands_dir.glob("*.yaml"):
            with open(yaml_file) as f:
                cmd_def = yaml.safe_load(f)
                commands[cmd_def["command"]] = cmd_def

        return commands

    def execute(self, command_str: str) -> CommandResult:
        """コマンドを実行"""
        # コマンドをパース
        parts = command_str.split()
        cmd_name = parts[0]  # 例: /gh-pr
        subcommand = parts[1] if len(parts) > 1 else None
        args = self._parse_args(parts[2:])

        # コマンド定義を取得
        cmd_def = self.commands.get(cmd_name)
        if not cmd_def:
            return CommandResult(
                success=False,
                output="",
                error=f"Unknown command: {cmd_name}"
            )

        # サブコマンド定義を取得
        if subcommand:
            subcmd_def = cmd_def.get("subcommands", {}).get(subcommand)
            if not subcmd_def:
                return CommandResult(
                    success=False,
                    output="",
                    error=f"Unknown subcommand: {subcommand}"
                )
        else:
            return CommandResult(
                success=False,
                output="",
                error=f"Subcommand required for {cmd_name}"
            )

        # スクリプトを実行
        return self._run_script(subcmd_def["script"], args)

    def _parse_args(self, args: list) -> Dict[str, Any]:
        """引数をパース"""
        result = {}
        i = 0
        while i < len(args):
            arg = args[i]
            if arg.startswith("--"):
                key = arg[2:]
                if i + 1 < len(args) and not args[i + 1].startswith("--"):
                    result[key] = args[i + 1]
                    i += 2
                else:
                    result[key] = True
                    i += 1
            else:
                # 位置引数
                result[f"arg{i}"] = arg
                i += 1
        return result

    def _run_script(self, script: str, args: Dict[str, Any]) -> CommandResult:
        """スクリプトを実行"""
        # 環境変数として引数を設定
        env = {k: str(v) for k, v in args.items()}

        try:
            result = subprocess.run(
                ["bash", "-c", script],
                capture_output=True,
                text=True,
                env={**os.environ, **env},
                timeout=60
            )

            return CommandResult(
                success=result.returncode == 0,
                output=result.stdout,
                error=result.stderr if result.returncode != 0 else None
            )

        except subprocess.TimeoutExpired:
            return CommandResult(
                success=False,
                output="",
                error="Command timed out"
            )
```

## MCP活用ガイドライン

### 使用すべきMCP

| MCP | 用途 | スキル化の推奨 |
|-----|------|---------------|
| Filesystem | ファイル操作 | 不要（標準ツール） |
| GitHub | 複雑なAPI操作 | 頻繁な操作のみ |
| Supabase | DB操作 | CLI操作のみ |
| Vercel | デプロイ | CLI操作のみ |
| Slack | 通知 | 定型通知のみ |

### MCPを使わない方が良いケース

| ケース | 代替手段 |
|-------|---------|
| 単純なGit操作 | gitコマンド直接 |
| 単純なnpm操作 | npmコマンド直接 |
| ファイル読み書き | 標準ツール |
| 環境変数設定 | exportコマンド |

## 登録済みスキルコマンド一覧

| コマンド | 説明 | サブコマンド |
|---------|------|-------------|
| /gh-pr | GitHub PR操作 | create, list, view, merge, review |
| /gh-issue | GitHub Issue操作 | create, list, view, close |
| /git | Git操作 | status, add, commit, push, pull |
| /supabase | Supabase操作 | db-push, db-reset, gen-types |
| /vercel | Vercel操作 | deploy, logs, env |
| /test | テスト実行 | run, watch, coverage |
| /lint | Lint実行 | check, fix |
| /format | フォーマット | check, fix |

## コンテキスト節約効果

### 比較

| 操作 | MCPスキーマ | スキルコマンド | 節約 |
|------|-----------|---------------|------|
| GitHub PR作成 | ~2,000 tokens | ~50 tokens | 97.5% |
| Supabase型生成 | ~1,500 tokens | ~30 tokens | 98% |
| Vercelデプロイ | ~1,200 tokens | ~40 tokens | 96.7% |

### 全体効果

```
1セッションでの推定節約:
- MCP使用時: 10,000 tokens（スキーマ読み込み）
- スキルコマンド: 500 tokens（コマンド実行）
- 節約: 9,500 tokens（95%削減）
- コスト換算: 約$0.03/セッション節約
```

## 新規スキルコマンドの追加

### 手順

1. `skills/commands/{name}.yaml` を作成
2. サブコマンドとスクリプトを定義
3. テスト実行
4. ドキュメントを更新

### テンプレート

```yaml
command: "/{command_name}"
description: "{説明}"
version: "1.0"

subcommands:
  {subcommand}:
    description: "{サブコマンドの説明}"
    usage: "/{command_name} {subcommand} [OPTIONS]"
    script: |
      # シェルスクリプト
      {cli_command} ${param1} ${param2}
    parameters:
      - name: param1
        type: string
        required: true
        description: "{パラメータの説明}"
```

## 設定

```yaml
# config/skills.yaml

skills:
  enabled: true
  commands_dir: "skills/commands"

  # 自動読み込み
  auto_load: true

  # MCP併用
  mcp_fallback: true  # スキルコマンドで対応できない場合MCPを使用

  # カスタムコマンド登録
  custom_commands:
    - name: "/deploy"
      script: "npm run deploy"
      description: "アプリをデプロイ"
```
