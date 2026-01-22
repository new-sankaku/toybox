# Agentへの依頼の単一化

## 概要

WORKERへの依頼は必ず1つのタスクに限定する。
複数の依頼を同時に行うと精度が低下するため、LEADERが複合タスクを単一タスクに分解してからWORKERに渡す。

## 原則

```
1 WORKER = 1 TASK = 1 OUTPUT
```

| NG | OK |
|----|-----|
| 「ジャンプとダッシュを実装して」 | 「ジャンプを実装して」→「ダッシュを実装して」 |
| 「敵AIを作って、あとUIも」 | 「敵AIを作って」→「UIを作って」 |
| 「バグ修正とリファクタリング」 | 「バグ修正」→「リファクタリング」 |

## タスク定義フォーマット

### 必須項目

```yaml
task_id: "task_p2_code_003"

# 単一の目的（1文で表現できること）
objective: "PlayerControllerクラスにジャンプ機能を実装する"

# 入力（何を使って）
inputs:
  - file: "src/Player/PlayerController.cs"
    purpose: "既存のプレイヤー制御コード"
  - file: "docs/design/player_spec.md"
    purpose: "プレイヤー仕様書"

# 出力（何を生成するか）
output:
  type: "code_modification"
  target: "src/Player/PlayerController.cs"
  description: "ジャンプ機能が追加されたPlayerController"

# 完了条件（どうなったら完了か）
acceptance_criteria:
  - "Spaceキーでジャンプできる"
  - "ジャンプ高さは3ユニット"
  - "二段ジャンプは不可"
  - "地面にいるときのみジャンプ可能"

# 禁止事項（やってはいけないこと）
forbidden:
  - "ダッシュ機能の実装"
  - "既存のMove機能の変更"
  - "他ファイルの修正"
```

### スコープ制限

| 項目 | 制限 |
|------|------|
| 変更ファイル数 | 原則1ファイル、最大3ファイル |
| 追加行数 | 目安100行以内 |
| 所要時間 | 目安15分〜1時間 |
| 依存関係 | 明示的に記載されたもののみ |

## LEADERによるタスク分解

### 分解プロセス

```python
class TaskDecomposer:
    def decompose(self, complex_task: str) -> List[Task]:
        """複合タスクを単一タスクに分解"""

        # 1. タスクの要素を抽出
        elements = self._extract_elements(complex_task)

        # 2. 依存関係を分析
        dependencies = self._analyze_dependencies(elements)

        # 3. 単一タスクに分解
        tasks = []
        for element in elements:
            task = Task(
                task_id=self._generate_task_id(),
                objective=element["objective"],
                inputs=element["inputs"],
                output=element["output"],
                acceptance_criteria=element["criteria"],
                depends_on=[d for d in dependencies if d["target"] == element["id"]]
            )
            tasks.append(task)

        return tasks
```

### 分解例

**入力（複合タスク）:**
```
「プレイヤーキャラクターの移動システムを実装してください。
左右移動、ジャンプ、ダッシュができるようにしてください。」
```

**出力（単一タスク群）:**

```yaml
# タスク1
task_id: task_p2_code_001
objective: "PlayerControllerの基本クラス構造を作成する"
output: "src/Player/PlayerController.cs（基本構造のみ）"
depends_on: []

# タスク2
task_id: task_p2_code_002
objective: "左右移動機能を実装する"
output: "PlayerController.csにMove()メソッドを追加"
depends_on: [task_p2_code_001]

# タスク3
task_id: task_p2_code_003
objective: "ジャンプ機能を実装する"
output: "PlayerController.csにJump()メソッドを追加"
depends_on: [task_p2_code_001]

# タスク4
task_id: task_p2_code_004
objective: "ダッシュ機能を実装する"
output: "PlayerController.csにDash()メソッドを追加"
depends_on: [task_p2_code_002]  # 移動の拡張なので移動に依存
```

## 粒度の判断基準

### 適切な粒度

| 粒度 | 判断基準 | 例 |
|------|---------|-----|
| 細かすぎ | 5分以内で完了 | 「変数名を1つ変更」 |
| 適切 | 15分〜1時間 | 「ジャンプ機能を実装」 |
| 粗すぎ | 2時間以上 | 「プレイヤーシステム全体」 |

### 分解が必要なサイン

| サイン | 例 |
|-------|-----|
| 「と」「および」がある | 「ジャンプとダッシュ」 |
| 複数の動詞がある | 「作成して、テストして」 |
| 複数ファイルに言及 | 「PlayerとEnemyを」 |
| 条件分岐が多い | 「Aの場合はX、Bの場合はY」 |

## WORKERの実行

### 入力検証

```python
class Worker:
    def validate_task(self, task: Task) -> bool:
        """タスクが単一化されているか検証"""

        # 目的が1文か
        if len(task.objective.split("。")) > 1:
            raise TaskValidationError("目的は1文で記述してください")

        # 出力が1つか
        if isinstance(task.output, list) and len(task.output) > 1:
            raise TaskValidationError("出力は1つに限定してください")

        # 禁止事項が明確か
        if not task.forbidden:
            raise TaskValidationError("禁止事項を明示してください")

        return True
```

### 実行中のスコープ確認

```python
def execute(self, task: Task) -> Result:
    """タスクを実行"""

    # 変更対象ファイルを記録
    modified_files = []

    # 実行中に変更ファイルが増えたら警告
    def on_file_modify(filepath: str):
        if filepath not in task.inputs and filepath != task.output.target:
            if filepath not in modified_files:
                modified_files.append(filepath)
                if len(modified_files) > 3:
                    raise ScopeViolationError(
                        f"変更ファイル数が上限を超えました: {modified_files}"
                    )

    # ... 実行処理 ...
```

## エラーハンドリング

### スコープ超過時

```python
class Leader:
    def handle_scope_violation(self, worker: Worker, error: ScopeViolationError):
        """スコープ超過時の処理"""

        # 1. WORKERを停止
        worker.stop()

        # 2. タスクを再分解
        subtasks = self.decomposer.decompose_further(worker.task)

        # 3. 新しいWORKERに割り当て
        for subtask in subtasks:
            new_worker = self.scaler.request_worker(subtask)
            new_worker.execute(subtask)
```

### 複数出力時

```python
def handle_multiple_outputs(self, worker: Worker, outputs: List[Output]):
    """複数出力が発生した場合"""

    # 主出力以外は破棄し、新タスクとして登録
    primary_output = outputs[0]
    for secondary in outputs[1:]:
        new_task = Task(
            objective=f"{secondary.description}を完成させる",
            inputs=[secondary.partial_result],
            output=secondary
        )
        self.task_queue.append(new_task)

    return primary_output
```

## メリット

| メリット | 説明 |
|---------|------|
| 精度向上 | 1つのことに集中できる |
| デバッグ容易 | 問題の特定が簡単 |
| 並列化可能 | 依存のないタスクは並列実行 |
| 進捗把握 | 細かい単位で進捗がわかる |
| ロールバック容易 | 問題のあるタスクだけ取り消し |

## 既存ファイルとの関連

| ファイル | 変更内容 |
|---------|---------|
| agents/phase1_task_split.md | タスク分解の詳細ルールを追加 |
| agents/phase2_code_leader.md | タスク分解責務を明記 |
| agents/phase2_asset_leader.md | タスク分解責務を明記 |
| _SCHEMAS.md | Task型にforbiddenフィールドを追加 |
