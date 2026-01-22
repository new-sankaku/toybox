# フィードバック・継続学習

## 概要

Agentが発見した知見（デバッグ技術、回避策、プロジェクト固有パターン）をスキルとして保存し、次回同様の問題発生時に自動的に読み込む。
同じ試行錯誤の繰り返しを防ぎ、トークン・時間・コストを節約する。

## 知識の階層

```
knowledge_base/
├── global/                    # 全体共通（全プロジェクトで使用）
│   ├── patterns/              # 成功パターン
│   ├── anti_patterns/         # 失敗パターン（避けるべき）
│   └── skills/                # 汎用スキル
│
├── groups/                    # グループ単位
│   ├── phase1/                # 企画フェーズの知見
│   ├── phase2/                # 開発フェーズの知見
│   │   ├── code/              # コード関連
│   │   └── asset/             # アセット関連
│   └── phase3/                # 品質フェーズの知見
│
└── projects/                  # プロジェクト固有
    └── {project_id}/
        └── learned/           # このプロジェクトで学んだこと
```

## スキルファイル形式

### skills/{skill_id}.yaml

```yaml
skill_id: "unity_jump_implementation"
name: "Unityでのジャンプ実装"
version: 3
created_at: "2024-01-10T10:00:00Z"
updated_at: "2024-01-15T14:30:00Z"

# 自動読み込み条件
triggers:
  keywords:
    - "ジャンプ"
    - "jump"
    - "Jump"
  file_patterns:
    - "*Controller.cs"
    - "*Movement.cs"
  task_types:
    - "code_implementation"
    - "feature_addition"

# スキル内容
content: |
  ## Unityでジャンプを実装する際のベストプラクティス

  ### 1. 地面判定を先に実装する
  - Raycastを使用（足元から下方向）
  - Physics.CheckSphereも有効

  ### 2. ジャンプ実装
  ```csharp
  if (isGrounded && Input.GetButtonDown("Jump"))
  {
      rb.velocity = new Vector3(rb.velocity.x, jumpForce, rb.velocity.z);
  }
  ```

  ### 3. よくある間違い
  - velocity.yを直接設定すると他の物理挙動に影響
  - AddForceの場合はForceMode.Impulseを使用

  ### 4. 避けるべきアプローチ
  - transform.positionを直接操作（物理エンジンと競合）
  - Update内で継続的に力を加える（不安定）

# 使用統計
stats:
  times_loaded: 15
  success_rate: 0.93
  avg_tokens_saved: 2500

# 関連スキル
related_skills:
  - "unity_ground_detection"
  - "unity_character_controller"
```

### patterns/{pattern_id}.yaml

```yaml
pattern_id: "singleton_service"
name: "シングルトンサービスパターン"
type: "success"

context: |
  ゲーム全体で1つのインスタンスのみ必要なサービス
  （AudioManager, GameManager等）

solution: |
  ```csharp
  public class GameManager : MonoBehaviour
  {
      public static GameManager Instance { get; private set; }

      void Awake()
      {
          if (Instance != null && Instance != this)
          {
              Destroy(gameObject);
              return;
          }
          Instance = this;
          DontDestroyOnLoad(gameObject);
      }
  }
  ```

evidence:
  - project: "proj_001"
    task: "task_p2_code_010"
    result: "success"
  - project: "proj_002"
    task: "task_p2_code_005"
    result: "success"

tags:
  - "unity"
  - "design_pattern"
  - "singleton"
```

### anti_patterns/{pattern_id}.yaml

```yaml
pattern_id: "direct_position_manipulation"
name: "Transform直接操作（物理使用時）"
type: "failure"

context: |
  Rigidbodyを使用しているオブジェクトの移動

bad_approach: |
  ```csharp
  // NG: 物理エンジンと競合する
  transform.position += direction * speed * Time.deltaTime;
  ```

why_bad: |
  - Rigidbodyの物理計算と競合
  - 衝突判定が正しく動作しない
  - 予期しないテレポートが発生

correct_approach: |
  ```csharp
  // OK: Rigidbodyを通して操作
  rb.MovePosition(rb.position + direction * speed * Time.deltaTime);
  // または
  rb.velocity = direction * speed;
  ```

evidence:
  - project: "proj_001"
    task: "task_p2_code_003"
    error: "キャラクターが壁を貫通"
  - project: "proj_002"
    task: "task_p2_code_007"
    error: "衝突判定が不安定"
```

## スキルの自動読み込み

### トリガーマッチング

```python
class SkillMatcher:
    def __init__(self, knowledge_base_path: Path):
        self.skills = self._load_all_skills(knowledge_base_path)

    def find_relevant_skills(self, task: Task) -> List[Skill]:
        """タスクに関連するスキルを検索"""
        relevant = []

        for skill in self.skills:
            score = self._calculate_relevance(skill, task)
            if score > 0.5:  # 閾値
                relevant.append((skill, score))

        # スコア順にソート
        relevant.sort(key=lambda x: x[1], reverse=True)

        # 上位5件を返す
        return [s for s, _ in relevant[:5]]

    def _calculate_relevance(self, skill: Skill, task: Task) -> float:
        score = 0.0

        # キーワードマッチ
        task_text = f"{task.objective} {task.description}"
        for keyword in skill.triggers.keywords:
            if keyword.lower() in task_text.lower():
                score += 0.3

        # ファイルパターンマッチ
        for pattern in skill.triggers.file_patterns:
            for file in task.modifies_files:
                if fnmatch.fnmatch(file, pattern):
                    score += 0.2

        # タスクタイプマッチ
        if task.type in skill.triggers.task_types:
            score += 0.2

        # 成功率で重み付け
        score *= skill.stats.success_rate

        return min(score, 1.0)
```

### コンテキスト注入

```python
class ContextBuilder:
    def __init__(self, skill_matcher: SkillMatcher):
        self.skill_matcher = skill_matcher

    def build_context(self, task: Task) -> str:
        """タスク用のコンテキストを構築"""

        # 関連スキルを取得
        skills = self.skill_matcher.find_relevant_skills(task)

        # 関連パターンを取得
        patterns = self._find_patterns(task)
        anti_patterns = self._find_anti_patterns(task)

        context = f"""
## 参考スキル
以下は過去に成功したアプローチです：

{self._format_skills(skills)}

## 成功パターン
{self._format_patterns(patterns)}

## 避けるべきアプローチ
以下は過去に失敗したアプローチです。これらは避けてください：

{self._format_anti_patterns(anti_patterns)}
"""
        return context
```

## 学習プロセス

### タスク完了時の学習

```python
class LearningAgent:
    def __init__(self, knowledge_base: KnowledgeBase):
        self.kb = knowledge_base

    def learn_from_task(self, task: Task, result: Result, context: TaskContext):
        """タスク完了から学習"""

        if result.success:
            self._extract_success_pattern(task, result, context)
        else:
            self._extract_failure_pattern(task, result, context)

    def _extract_success_pattern(self, task: Task, result: Result, context: TaskContext):
        """成功パターンを抽出"""

        # 新しいアプローチかどうか確認
        if self._is_novel_approach(task, result):
            pattern = Pattern(
                pattern_id=self._generate_id(),
                name=self._generate_name(task),
                type="success",
                context=task.objective,
                solution=result.output,
                evidence=[{
                    "project": context.project_id,
                    "task": task.task_id,
                    "result": "success"
                }]
            )
            self.kb.add_pattern(pattern)

    def _extract_failure_pattern(self, task: Task, result: Result, context: TaskContext):
        """失敗パターンを抽出"""

        anti_pattern = AntiPattern(
            pattern_id=self._generate_id(),
            name=f"失敗: {task.objective[:50]}",
            type="failure",
            context=task.objective,
            bad_approach=result.attempted_approach,
            why_bad=result.error_message,
            evidence=[{
                "project": context.project_id,
                "task": task.task_id,
                "error": result.error_message
            }]
        )
        self.kb.add_anti_pattern(anti_pattern)
```

### 定期的な振り返り

```python
class ReflectionAgent:
    def __init__(self, interval_minutes: int = 15):
        self.interval = interval_minutes

    async def run_reflection_loop(self):
        """定期的に振り返りを実行"""
        while True:
            await asyncio.sleep(self.interval * 60)
            await self.reflect()

    async def reflect(self):
        """最近のセッションを振り返り、改善を提案"""

        # 最近のタスク結果を取得
        recent_tasks = self._get_recent_tasks(minutes=self.interval)

        # パターンを分析
        analysis = self._analyze_patterns(recent_tasks)

        if analysis.has_suggestions:
            # 改善提案を生成
            suggestions = self._generate_suggestions(analysis)

            # Human承認を要求
            for suggestion in suggestions:
                approved = await self._request_approval(suggestion)
                if approved:
                    self._apply_suggestion(suggestion)
```

## Humanフィードバックの学習

### 修正指示からの学習

```python
def learn_from_human_feedback(self, original: Result, feedback: str, corrected: Result):
    """Human修正指示から学習"""

    # 何が間違っていたかを分析
    diff = self._analyze_diff(original.output, corrected.output)

    # 修正パターンを記録
    correction = Correction(
        original_approach=original.output,
        feedback=feedback,
        corrected_approach=corrected.output,
        diff_summary=diff
    )

    # 類似の間違いを防ぐためのスキルを生成
    skill = self._generate_skill_from_correction(correction)

    if skill:
        self.kb.add_skill(skill)
```

## メモリファイルの更新

### 自動更新

```python
class MemoryUpdater:
    def update_memory(self, session_log: SessionLog):
        """セッションログからメモリを更新"""

        # 成功したアプローチを抽出
        successes = [t for t in session_log.tasks if t.result.success]

        # 失敗したアプローチを抽出
        failures = [t for t in session_log.tasks if not t.result.success]

        # Human修正を抽出
        corrections = session_log.human_corrections

        # メモリファイルを更新
        self._update_success_patterns(successes)
        self._update_failure_patterns(failures)
        self._update_from_corrections(corrections)
```

### メモリファイル形式

```yaml
# memory/{project_id}/project_memory.yaml

project_id: "proj_001"
last_updated: "2024-01-15T16:00:00Z"

preferences:
  code_style:
    - "関数は30行以内"
    - "変数名はcamelCase"
  architecture:
    - "シングルトンパターンを推奨"
    - "依存性注入を使用"

learned_behaviors:
  - trigger: "UIコンポーネント作成時"
    behavior: "必ずCanvasGroupを追加する"
    reason: "フェードイン/アウトに必要"

  - trigger: "API呼び出し時"
    behavior: "エラーハンドリングを必ず追加"
    reason: "過去にエラー処理漏れでバグ発生"

known_issues:
  - description: "AudioSourceのPlayOnAwakeが意図せずON"
    workaround: "プレハブ作成時に明示的にOFF"
```

## 効果測定

### メトリクス

| メトリクス | 説明 |
|-----------|------|
| skill_hit_rate | スキルが使用された割合 |
| retry_reduction | リトライ回数の削減率 |
| token_savings | 節約されたトークン数 |
| time_savings | 節約された時間 |
| human_correction_reduction | Human修正回数の削減率 |

### レポート

```json
{
  "period": "2024-01-01 ~ 2024-01-15",
  "metrics": {
    "total_tasks": 500,
    "skills_loaded": 380,
    "skill_hit_rate": 0.76,
    "first_try_success_rate": {
      "with_skills": 0.85,
      "without_skills": 0.62
    },
    "estimated_token_savings": 125000,
    "estimated_cost_savings_usd": 18.75
  }
}
```
