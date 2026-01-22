# 自己改善

## 概要

セッションログを振り返り、ユーザーの好みや成功/失敗パターンを抽出する。
定期的に改善提案を生成し、Human承認後にメモリファイルを更新する。

## 自己改善の2つのアプローチ

### アプローチ1: セッション終了時の振り返り

セッション終了後に、Reflectionエージェントが以下を抽出:
- うまくいったこと
- 失敗したこと
- 行った修正
- 学んだパターン

### アプローチ2: 定期的な積極的改善

15分ごとにエージェントが最近のやり取りをレビューし、改善を提案。
Human承認/却下のパターンから学習。

## セッション終了時の振り返り

### Reflectionエージェント

```python
class ReflectionAgent:
    def __init__(self, knowledge_base: KnowledgeBase):
        self.kb = knowledge_base

    async def reflect_on_session(self, session_log: SessionLog) -> ReflectionReport:
        """セッションを振り返り、学びを抽出"""

        # 1. 成功/失敗を分類
        successes = [t for t in session_log.tasks if t.result.success]
        failures = [t for t in session_log.tasks if not t.result.success]

        # 2. Human修正を分析
        corrections = session_log.human_corrections

        # 3. パターンを抽出
        success_patterns = self._extract_patterns(successes)
        failure_patterns = self._extract_patterns(failures)
        correction_insights = self._analyze_corrections(corrections)

        # 4. 改善提案を生成
        suggestions = self._generate_suggestions(
            success_patterns,
            failure_patterns,
            correction_insights
        )

        return ReflectionReport(
            session_id=session_log.session_id,
            successes=success_patterns,
            failures=failure_patterns,
            corrections=correction_insights,
            suggestions=suggestions
        )

    def _extract_patterns(self, tasks: List[Task]) -> List[Pattern]:
        """タスクからパターンを抽出"""
        patterns = []

        for task in tasks:
            # LLMを使用してパターンを抽出
            pattern = self._analyze_task(task)
            if pattern:
                patterns.append(pattern)

        # 類似パターンを統合
        return self._merge_similar_patterns(patterns)

    def _analyze_corrections(self, corrections: List[Correction]) -> List[Insight]:
        """Human修正から洞察を抽出"""
        insights = []

        for correction in corrections:
            insight = Insight(
                original=correction.original,
                corrected=correction.corrected,
                feedback=correction.feedback,
                lesson=self._extract_lesson(correction)
            )
            insights.append(insight)

        return insights
```

### ReflectionReport

```python
@dataclass
class ReflectionReport:
    session_id: str
    timestamp: datetime
    successes: List[Pattern]
    failures: List[Pattern]
    corrections: List[Insight]
    suggestions: List[Suggestion]

@dataclass
class Suggestion:
    suggestion_id: str
    type: str  # "skill", "pattern", "anti_pattern", "preference"
    title: str
    description: str
    content: str
    confidence: float  # 0.0 - 1.0
    evidence: List[str]  # 根拠となるタスクID
```

## 定期的な積極的改善

### ProactiveImprover

```python
class ProactiveImprover:
    def __init__(self, interval_minutes: int = 15):
        self.interval = interval_minutes
        self.suggestion_queue: List[Suggestion] = []
        self.approval_history: List[ApprovalRecord] = []

    async def run_loop(self):
        """定期的に改善提案を生成"""
        while True:
            await asyncio.sleep(self.interval * 60)

            # 最近のやり取りをレビュー
            recent_interactions = self._get_recent_interactions(self.interval)

            if not recent_interactions:
                continue

            # 改善提案を生成
            suggestions = await self._generate_suggestions(recent_interactions)

            for suggestion in suggestions:
                # Human承認を要求
                approved = await self._request_approval(suggestion)

                # 結果を記録
                self.approval_history.append(ApprovalRecord(
                    suggestion=suggestion,
                    approved=approved,
                    timestamp=datetime.utcnow()
                ))

                if approved:
                    await self._apply_suggestion(suggestion)

    async def _generate_suggestions(self, interactions: List[Interaction]) -> List[Suggestion]:
        """やり取りから改善提案を生成"""
        suggestions = []

        # 繰り返しパターンを検出
        repeated = self._find_repeated_patterns(interactions)
        for pattern in repeated:
            suggestions.append(Suggestion(
                type="skill",
                title=f"繰り返しパターン: {pattern.name}",
                description="このパターンが複数回出現しました。スキルとして保存しますか？",
                content=pattern.content,
                confidence=0.8
            ))

        # エラーパターンを検出
        errors = self._find_error_patterns(interactions)
        for error in errors:
            suggestions.append(Suggestion(
                type="anti_pattern",
                title=f"回避すべきパターン: {error.name}",
                description="このパターンで複数回エラーが発生しました。",
                content=error.content,
                confidence=0.7
            ))

        return suggestions

    def learn_from_approvals(self):
        """承認パターンから学習"""
        # 承認率の高いタイプを特定
        approval_rates = self._calculate_approval_rates()

        # 今後の提案に反映
        self.suggestion_filter = lambda s: approval_rates.get(s.type, 0.5) > 0.3
```

## メモリファイルの更新

### 更新プロセス

```python
class MemoryUpdater:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path

    def update_from_reflection(self, report: ReflectionReport):
        """振り返りレポートからメモリを更新"""

        memory = self._load_memory()

        # 成功パターンを追加
        for pattern in report.successes:
            if self._is_significant(pattern):
                memory["learned_patterns"].append({
                    "pattern": pattern.content,
                    "confidence": pattern.confidence,
                    "source_session": report.session_id
                })

        # 失敗パターンを追加
        for pattern in report.failures:
            memory["avoid_patterns"].append({
                "pattern": pattern.content,
                "reason": pattern.failure_reason,
                "source_session": report.session_id
            })

        # 修正から学んだことを追加
        for insight in report.corrections:
            memory["preferences"].append({
                "lesson": insight.lesson,
                "example": insight.corrected,
                "source_session": report.session_id
            })

        self._save_memory(memory)

    def apply_suggestion(self, suggestion: Suggestion):
        """承認された提案を適用"""

        if suggestion.type == "skill":
            self._add_skill(suggestion)
        elif suggestion.type == "pattern":
            self._add_pattern(suggestion)
        elif suggestion.type == "anti_pattern":
            self._add_anti_pattern(suggestion)
        elif suggestion.type == "preference":
            self._add_preference(suggestion)
```

### メモリファイル形式

```yaml
# memory/project_memory.yaml

project_id: "proj_001"
last_updated: "2024-01-15T16:00:00Z"

# ユーザーの好み
preferences:
  code_style:
    - lesson: "変数名は説明的に"
      example: "playerHealth vs hp"
      confidence: 0.9
    - lesson: "コメントは日本語で"
      confidence: 0.85

  workflow:
    - lesson: "大きな変更は分割して"
      confidence: 0.8

# 学んだパターン（成功）
learned_patterns:
  - pattern: "Singleton実装時はDontDestroyOnLoadを使用"
    confidence: 0.95
    times_used: 5
    success_rate: 1.0

  - pattern: "API呼び出しには必ずtry-catchを追加"
    confidence: 0.9
    times_used: 8
    success_rate: 0.875

# 避けるべきパターン（失敗）
avoid_patterns:
  - pattern: "Rigidbody使用時にtransform.positionを直接変更"
    reason: "物理演算と競合してバグが発生"
    times_failed: 3

  - pattern: "非同期処理でawaitを忘れる"
    reason: "予期しない動作になる"
    times_failed: 2

# 自動適用ルール
auto_rules:
  - trigger: "新しいMonoBehaviourクラス作成時"
    action: "Awake, Start, Updateメソッドのテンプレートを追加"
    enabled: true

  - trigger: "API呼び出しコード検出時"
    action: "エラーハンドリングの追加を提案"
    enabled: true
```

## Human連携

### 改善提案の表示

```typescript
interface ImprovementSuggestion {
  id: string;
  type: "skill" | "pattern" | "anti_pattern" | "preference";
  title: string;
  description: string;
  content: string;
  confidence: number;
  evidence: string[];
}

// WebUI表示
<ImprovementCard>
  <Title>{suggestion.title}</Title>
  <Description>{suggestion.description}</Description>
  <Content>{suggestion.content}</Content>
  <Confidence>{suggestion.confidence * 100}%</Confidence>
  <Actions>
    <Button onClick={approve}>承認</Button>
    <Button onClick={reject}>却下</Button>
    <Button onClick={modify}>修正して承認</Button>
  </Actions>
</ImprovementCard>
```

### 承認フロー

```
改善提案生成
    │
    v
Human表示
    │
    ├── 承認 ────────────────> メモリ更新
    │
    ├── 却下 ────────────────> 却下理由を記録
    │                          （同様の提案を避ける）
    │
    └── 修正して承認 ─────────> 修正内容でメモリ更新
                               （修正パターンを学習）
```

## 効果測定

### メトリクス

| メトリクス | 説明 |
|-----------|------|
| suggestion_approval_rate | 提案の承認率 |
| memory_hit_rate | メモリがタスク実行に使用された率 |
| error_reduction_rate | メモリ適用後のエラー削減率 |
| human_correction_reduction | Human修正の削減率 |

### ダッシュボード

```yaml
# 週次レポート例

week: "2024-01-08 ~ 2024-01-14"

reflection_stats:
  sessions_analyzed: 15
  patterns_extracted: 23
  suggestions_generated: 18
  suggestions_approved: 14
  approval_rate: 0.78

memory_impact:
  tasks_with_memory: 120
  tasks_without_memory: 30
  success_rate_with: 0.92
  success_rate_without: 0.73
  improvement: "+19%"

top_learnings:
  - "Unity AudioSource の PlayOnAwake をデフォルトでOFFにする"
  - "React コンポーネントには必ず key を指定"
  - "API レスポンスは必ず型チェック"
```
