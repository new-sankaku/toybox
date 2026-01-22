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

## WORKERの依頼確認

WORKERは依頼を受け取ったら、まず内容が明確か確認する。
不足や曖昧な点があればLEADERに明確化を依頼する。

### 確認プロセス

```python
class Worker:
    def receive_task(self, task: Task) -> Union[Task, ClarificationRequest]:
        """タスクを受け取り、明確か確認"""

        unclear_points = self._check_clarity(task)

        if unclear_points:
            # 不明点があればLEADERに確認を依頼
            return ClarificationRequest(
                task_id=task.task_id,
                questions=unclear_points
            )

        # 明確であれば実行開始
        return task

    def _check_clarity(self, task: Task) -> List[str]:
        """依頼内容の明確性をチェック"""
        unclear = []

        # 目的が具体的か
        if not task.objective:
            unclear.append("目的（objective）が指定されていません")

        # 入力が明示されているか
        if not task.inputs:
            unclear.append("入力ファイルが指定されていません")

        # 出力先が明示されているか
        if not task.output or not task.output.target:
            unclear.append("出力先が指定されていません")

        # 完了条件が明示されているか
        if not task.acceptance_criteria:
            unclear.append("完了条件（acceptance_criteria）が指定されていません")

        return unclear
```

### LEADERの応答

```python
class Leader:
    def handle_clarification_request(self, request: ClarificationRequest) -> Task:
        """WORKERからの確認依頼に応答"""

        # 不明点を補完したタスクを生成
        clarified_task = self._clarify_task(
            task_id=request.task_id,
            questions=request.questions
        )

        # 再度WORKERに送信
        return clarified_task
```

## タスク定義フォーマット

### 必須項目

```yaml
task_id: "task_p2_code_003"
priority: 1  # 優先度（1が最高）

# 具体的な目的
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

## スコープ制限（DB管理）

スコープ制限の閾値はDBで管理し、WebUIから調整可能。

```sql
CREATE TABLE task_scope_config (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    value INTEGER NOT NULL,
    description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 初期値
INSERT INTO task_scope_config (key, value, description) VALUES
    ('max_modified_files', 3, '1タスクで変更可能な最大ファイル数'),
    ('max_added_lines', 200, '1タスクで追加可能な最大行数'),
    ('max_dependencies', 5, '1タスクの最大依存数');
```

### WebUI設定画面

| 設定項目 | DB key | 説明 |
|---------|--------|------|
| 変更ファイル上限 | max_modified_files | スライダー（1〜10） |
| 追加行数上限 | max_added_lines | 数値入力 |
| 依存数上限 | max_dependencies | スライダー（1〜10） |

## LEADERによるタスク分解

### 分解プロセス

```python
class TaskDecomposer:
    def __init__(self, db: Database):
        self.db = db

    def decompose(self, complex_task: str) -> List[Task]:
        """複合タスクを単一タスクに分解し、優先度を付与"""

        # 1. タスクの要素を抽出
        elements = self._extract_elements(complex_task)

        # 2. 依存関係を分析
        dependencies = self._analyze_dependencies(elements)

        # 3. 優先度を決定（依存されているものほど高優先度）
        priorities = self._calculate_priorities(elements, dependencies)

        # 4. 単一タスクに分解
        tasks = []
        for element in elements:
            task = Task(
                task_id=self._generate_task_id(),
                priority=priorities[element["id"]],
                objective=element["objective"],
                inputs=element["inputs"],
                output=element["output"],
                acceptance_criteria=element["criteria"],
                depends_on=[d for d in dependencies if d["target"] == element["id"]]
            )
            tasks.append(task)

        # 優先度順にソート
        tasks.sort(key=lambda t: t.priority)

        return tasks

    def _calculate_priorities(
        self, elements: List[dict], dependencies: List[dict]
    ) -> Dict[str, int]:
        """優先度を計算（依存されている数が多いほど高優先度）"""
        priority_map = {}

        for element in elements:
            # このelementに依存しているタスクの数
            dependent_count = sum(
                1 for d in dependencies if d["depends_on"] == element["id"]
            )
            # 依存されているほど優先度が高い（数値が小さい）
            priority_map[element["id"]] = len(elements) - dependent_count

        return priority_map
```

### 分解例

**入力（複合タスク）:**
```
「プレイヤーキャラクターの移動システムを実装してください。
左右移動、ジャンプ、ダッシュができるようにしてください。」
```

**出力（単一タスク群・優先度付き）:**

```yaml
# タスク1（最優先：他のタスクの基盤）
task_id: task_p2_code_001
priority: 1
objective: "PlayerControllerの基本クラス構造を作成する"
output: "src/Player/PlayerController.cs（基本構造のみ）"
depends_on: []

# タスク2
task_id: task_p2_code_002
priority: 2
objective: "左右移動機能を実装する"
output: "PlayerController.csにMove()メソッドを追加"
depends_on: [task_p2_code_001]

# タスク3（移動と同優先度・並列実行可能）
task_id: task_p2_code_003
priority: 2
objective: "ジャンプ機能を実装する"
output: "PlayerController.csにJump()メソッドを追加"
depends_on: [task_p2_code_001]

# タスク4（移動に依存するため後）
task_id: task_p2_code_004
priority: 3
objective: "ダッシュ機能を実装する"
output: "PlayerController.csにDash()メソッドを追加"
depends_on: [task_p2_code_002]  # 移動の拡張なので移動に依存
```

## メリット

| メリット | 説明 |
|---------|------|
| 精度向上 | 1つのことに集中できる |
| デバッグ容易 | 問題の特定が簡単 |
| 並列化可能 | 依存のないタスクは並列実行 |
| 進捗把握 | 細かい単位で進捗がわかる |
| ロールバック容易 | 問題のあるタスクだけ取り消し |
