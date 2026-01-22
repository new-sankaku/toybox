# AIコスト対策（LLM動的選択）

## 概要

タスクの難易度や性質に応じて、Haiku/Sonnet/Opusを動的に選択する。
コスト効率を最大化しつつ、必要な品質を確保する。

## モデル特性とコスト

| モデル | 入力 ($/1M tokens) | 出力 ($/1M tokens) | 特性 |
|--------|-------------------|-------------------|------|
| Haiku | $0.25 | $1.25 | 高速、単純タスク向け |
| Sonnet | $3.00 | $15.00 | バランス型 |
| Opus | $15.00 | $75.00 | 高精度、複雑タスク向け |

### コスト比較

| 比較 | 倍率 |
|------|------|
| Haiku vs Sonnet | 約12倍安い |
| Haiku vs Opus | 約60倍安い |
| Sonnet vs Opus | 約5倍安い |

## 選択戦略

### Agent種別ごとのデフォルト

| Agent種別 | デフォルトモデル | 理由 |
|----------|----------------|------|
| ORCHESTRATOR | Opus | 全体判断、重要な意思決定 |
| DIRECTOR | Sonnet | Phase統括、中程度の判断 |
| LEADER | Sonnet | タスク分解、チーム管理 |
| WORKER | Haiku | 単一タスク実行 |

### タスク種別ごとの選択

| タスク種別 | 推奨モデル | 理由 |
|-----------|-----------|------|
| コード生成（単純） | Haiku | 定型的な実装 |
| コード生成（複雑） | Sonnet | 設計判断が必要 |
| アーキテクチャ設計 | Opus | 長期的影響の判断 |
| バグ修正（単純） | Haiku | 明確な修正 |
| バグ修正（複雑） | Sonnet/Opus | 原因調査が必要 |
| リファクタリング | Sonnet | バランスが必要 |
| セキュリティ関連 | Opus | 慎重な判断が必要 |
| テスト作成 | Haiku | 定型的 |
| レビュー | Sonnet | 品質判断 |
| ドキュメント生成 | Haiku | 定型的 |

## 動的昇格・降格

### 昇格条件（より高性能なモデルへ）

| 条件 | アクション |
|------|-----------|
| Haikuで2回連続失敗 | Sonnetに昇格 |
| Sonnetで2回連続失敗 | Opusに昇格 |
| 変更ファイル数 >= 5 | Sonnet以上を使用 |
| セキュリティ関連キーワード検出 | Opus |
| Human修正指示 >= 2回 | 1段階昇格 |

### 降格条件（よりコスト効率の良いモデルへ）

| 条件 | アクション |
|------|-----------|
| 同種タスクで3回連続成功（Sonnet） | 次回Haikuを試行 |
| 反復的なタスク | Haiku |
| 指示が非常に明確 | Haiku |

## 実装

### モデルセレクター

```python
from enum import Enum
from dataclasses import dataclass
from typing import Optional

class LLMModel(Enum):
    HAIKU = "haiku"
    SONNET = "sonnet"
    OPUS = "opus"

@dataclass
class ModelSelectionContext:
    task_type: str
    file_count: int
    is_security_related: bool
    previous_failures: int
    previous_model: Optional[LLMModel]
    is_architecture_decision: bool
    instruction_clarity: float  # 0.0 - 1.0

class ModelSelector:
    def __init__(self):
        self.task_history: Dict[str, List[bool]] = {}  # task_type -> [success/fail]

    def select_model(self, context: ModelSelectionContext) -> LLMModel:
        """タスクに最適なモデルを選択"""

        # セキュリティ関連は常にOpus
        if context.is_security_related:
            return LLMModel.OPUS

        # アーキテクチャ決定はOpus
        if context.is_architecture_decision:
            return LLMModel.OPUS

        # 5ファイル以上の変更はSonnet以上
        if context.file_count >= 5:
            return LLMModel.SONNET if context.previous_failures < 2 else LLMModel.OPUS

        # 失敗履歴による昇格
        if context.previous_failures >= 2:
            if context.previous_model == LLMModel.HAIKU:
                return LLMModel.SONNET
            elif context.previous_model == LLMModel.SONNET:
                return LLMModel.OPUS

        # 指示が明確で単純なタスクはHaiku
        if context.instruction_clarity > 0.8 and context.file_count <= 2:
            # 過去の成功率を確認
            if self._get_success_rate(context.task_type, LLMModel.HAIKU) > 0.8:
                return LLMModel.HAIKU

        # デフォルトはSonnet
        return LLMModel.SONNET

    def _get_success_rate(self, task_type: str, model: LLMModel) -> float:
        """特定タスク種別・モデルの成功率を取得"""
        key = f"{task_type}_{model.value}"
        history = self.task_history.get(key, [])
        if not history:
            return 0.5  # データなしは中立
        return sum(history) / len(history)

    def record_result(self, task_type: str, model: LLMModel, success: bool):
        """結果を記録"""
        key = f"{task_type}_{model.value}"
        if key not in self.task_history:
            self.task_history[key] = []
        self.task_history[key].append(success)
        # 直近100件のみ保持
        self.task_history[key] = self.task_history[key][-100:]
```

### コスト計算

```python
@dataclass
class TokenUsage:
    input_tokens: int
    output_tokens: int
    model: LLMModel

class CostCalculator:
    PRICES = {
        LLMModel.HAIKU: {"input": 0.25, "output": 1.25},
        LLMModel.SONNET: {"input": 3.00, "output": 15.00},
        LLMModel.OPUS: {"input": 15.00, "output": 75.00},
    }

    def calculate(self, usage: TokenUsage) -> float:
        """コストを計算（USD）"""
        prices = self.PRICES[usage.model]
        input_cost = (usage.input_tokens / 1_000_000) * prices["input"]
        output_cost = (usage.output_tokens / 1_000_000) * prices["output"]
        return input_cost + output_cost

    def estimate_savings(self, usages: List[TokenUsage]) -> dict:
        """節約額を計算"""
        actual_cost = sum(self.calculate(u) for u in usages)

        # すべてOpusだった場合
        opus_cost = sum(
            self.calculate(TokenUsage(u.input_tokens, u.output_tokens, LLMModel.OPUS))
            for u in usages
        )

        return {
            "actual_cost": actual_cost,
            "opus_only_cost": opus_cost,
            "savings": opus_cost - actual_cost,
            "savings_percent": (opus_cost - actual_cost) / opus_cost * 100
        }
```

## 設定

### システム設定

```yaml
# config/llm_strategy.yaml

llm:
  default_models:
    orchestrator: opus
    director: sonnet
    leader: sonnet
    worker: haiku

  promotion_rules:
    consecutive_failures_to_promote: 2
    file_count_threshold: 5
    security_keywords:
      - "password"
      - "secret"
      - "token"
      - "auth"
      - "encrypt"
      - "credential"

  demotion_rules:
    consecutive_successes_to_demote: 3

  budget:
    daily_limit_usd: 100
    warning_threshold_percent: 80
    auto_pause_on_limit: true
```

### WebUIからの設定

| 設定項目 | UIコンポーネント |
|---------|----------------|
| デフォルトモデル | ドロップダウン（Agent種別ごと） |
| 日次予算上限 | 数値入力 |
| 自動昇格ON/OFF | トグル |
| セキュリティキーワード | テキストリスト |

## 監視とレポート

### リアルタイム監視

| メトリクス | 説明 |
|-----------|------|
| current_model_usage | 現在使用中のモデル分布 |
| cost_per_hour | 時間あたりコスト |
| promotion_count | 昇格回数 |
| demotion_count | 降格回数 |
| budget_remaining | 残予算 |

### 日次レポート

```json
{
  "date": "2024-01-15",
  "total_cost_usd": 45.23,
  "model_breakdown": {
    "haiku": {"calls": 150, "cost": 2.50, "success_rate": 0.85},
    "sonnet": {"calls": 80, "cost": 25.00, "success_rate": 0.92},
    "opus": {"calls": 15, "cost": 17.73, "success_rate": 0.95}
  },
  "savings_vs_opus_only": {
    "amount": 120.50,
    "percent": 72.7
  },
  "top_cost_tasks": [
    {"task_id": "task_p2_code_015", "cost": 5.20, "model": "opus"},
    {"task_id": "task_p2_code_008", "cost": 3.80, "model": "sonnet"}
  ]
}
```

## 予算制御

### 予算超過時の動作

```python
class BudgetController:
    def __init__(self, daily_limit: float):
        self.daily_limit = daily_limit
        self.current_spend = 0.0

    def can_execute(self, estimated_cost: float) -> bool:
        """実行可能か判定"""
        return self.current_spend + estimated_cost <= self.daily_limit

    def on_budget_warning(self):
        """警告閾値到達時"""
        # 1. Opusの使用を停止、Sonnetに降格
        # 2. 通知を送信
        pass

    def on_budget_exceeded(self):
        """予算超過時"""
        # 1. 新規タスクの受付を停止
        # 2. Human承認を要求
        pass
```
