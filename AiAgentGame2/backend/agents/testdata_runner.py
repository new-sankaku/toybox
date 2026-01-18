"""
TestData Agent Runner

フロントエンドテスト用のテストデータエージェント実装
実際のLLM呼び出しは行わず、シミュレーションデータを返す
"""

import asyncio
import random
from datetime import datetime
from typing import Any, Dict, List, AsyncGenerator, Optional

from .base import (
    AgentRunner,
    AgentContext,
    AgentOutput,
    AgentType,
    AgentStatus,
)


class TestDataAgentRunner(AgentRunner):
    """
    モックエージェントランナー

    フロントエンドのテスト用にシミュレーションデータを生成
    """

    def __init__(self, delay_range: tuple = (0.5, 1.5), **kwargs):
        """
        Args:
            delay_range: 進捗更新間の遅延範囲（秒）
        """
        self.delay_range = delay_range
        self._mock_outputs = self._init_mock_outputs()
        self._mock_tasks = self._init_mock_tasks()

    async def run_agent(self, context: AgentContext) -> AgentOutput:
        """エージェントを実行（非ストリーミング）"""
        started_at = datetime.now().isoformat()
        tokens_used = 0
        output = {}

        try:
            # シミュレーション実行
            async for event in self.run_agent_stream(context):
                if event["type"] == "progress":
                    pass  # 進捗は無視
                elif event["type"] == "output":
                    output = event["data"]
                elif event["type"] == "tokens":
                    tokens_used += event["data"]["count"]

            return AgentOutput(
                agent_id=context.agent_id,
                agent_type=context.agent_type,
                status=AgentStatus.COMPLETED,
                output=output,
                tokens_used=tokens_used,
                duration_seconds=(datetime.now() - datetime.fromisoformat(started_at)).total_seconds(),
                started_at=started_at,
                completed_at=datetime.now().isoformat(),
            )

        except Exception as e:
            return AgentOutput(
                agent_id=context.agent_id,
                agent_type=context.agent_type,
                status=AgentStatus.FAILED,
                error=str(e),
                tokens_used=tokens_used,
                started_at=started_at,
                completed_at=datetime.now().isoformat(),
            )

    async def run_agent_stream(
        self,
        context: AgentContext
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """エージェントをストリーミング実行"""

        agent_type = context.agent_type
        tasks = self._mock_tasks.get(agent_type.value, self._default_tasks())

        progress = 0
        total_tokens = 0
        checkpoint_created = False
        checkpoint_at = random.choice([30, 50, 70])

        # 開始ログ
        yield {
            "type": "log",
            "data": {
                "level": "info",
                "message": f"エージェント開始: {agent_type.value}",
                "timestamp": datetime.now().isoformat()
            }
        }

        while progress < 100:
            # 遅延
            await asyncio.sleep(random.uniform(*self.delay_range))

            # 進捗更新
            increment = random.randint(5, 15)
            progress = min(100, progress + increment)

            # 現在のタスク
            task_index = min(len(tasks) - 1, int(progress / (100 / len(tasks))))
            current_task = tasks[task_index]

            # トークン使用
            tokens = random.randint(100, 500)
            total_tokens += tokens

            # 進捗イベント
            yield {
                "type": "progress",
                "data": {
                    "progress": progress,
                    "current_task": current_task,
                    "timestamp": datetime.now().isoformat()
                }
            }

            # トークンイベント
            yield {
                "type": "tokens",
                "data": {
                    "count": tokens,
                    "total": total_tokens
                }
            }

            # ログイベント
            log_messages = [
                f"処理中: {current_task}",
                f"進捗: {progress}%",
                "データを分析しています...",
                "生成中...",
            ]
            yield {
                "type": "log",
                "data": {
                    "level": random.choice(["info", "debug"]),
                    "message": random.choice(log_messages),
                    "timestamp": datetime.now().isoformat()
                }
            }

            # チェックポイント（特定の進捗で1回だけ）
            if progress >= checkpoint_at and not checkpoint_created:
                checkpoint_created = True
                checkpoint_data = self._generate_checkpoint(context)

                yield {
                    "type": "checkpoint",
                    "data": checkpoint_data
                }

                # コールバック経由でチェックポイント通知
                if context.on_checkpoint:
                    context.on_checkpoint(
                        checkpoint_data["type"],
                        checkpoint_data
                    )

            # コールバック経由で進捗通知
            if context.on_progress:
                context.on_progress(progress, current_task)

            if context.on_log:
                context.on_log("info", f"進捗: {progress}%")

        # 最終出力
        output = self._mock_outputs.get(
            agent_type.value,
            {"type": "document", "content": "処理完了"}
        )

        yield {
            "type": "output",
            "data": output
        }

        # 完了ログ
        yield {
            "type": "log",
            "data": {
                "level": "info",
                "message": "エージェント完了",
                "timestamp": datetime.now().isoformat()
            }
        }

    def get_supported_agents(self) -> List[AgentType]:
        """全エージェントをサポート"""
        return list(AgentType)

    def validate_context(self, context: AgentContext) -> bool:
        """常にTrue（モックなので）"""
        return True

    def _generate_checkpoint(self, context: AgentContext) -> Dict[str, Any]:
        """チェックポイントデータを生成"""
        checkpoint_types = {
            AgentType.CONCEPT: ("concept_review", "ゲームコンセプトのレビュー"),
            AgentType.DESIGN: ("design_review", "ゲームデザインのレビュー"),
            AgentType.SCENARIO: ("scenario_review", "シナリオのレビュー"),
            AgentType.CHARACTER: ("character_review", "キャラクターのレビュー"),
            AgentType.WORLD: ("world_review", "ワールド設定のレビュー"),
            AgentType.TASK_SPLIT: ("task_review", "タスク分割のレビュー"),
            AgentType.CODE_LEADER: ("code_plan_review", "コード計画のレビュー"),
            AgentType.ASSET_LEADER: ("asset_plan_review", "アセット計画のレビュー"),
            AgentType.INTEGRATOR: ("integration_review", "統合結果のレビュー"),
            AgentType.TESTER: ("test_review", "テスト結果のレビュー"),
            AgentType.REVIEWER: ("final_review", "最終レビュー"),
        }

        cp_type, title = checkpoint_types.get(
            context.agent_type,
            ("review", "レビュー依頼")
        )

        return {
            "type": cp_type,
            "title": title,
            "description": f"{context.agent_type.value}エージェントの出力を確認してください",
            "output": self._mock_outputs.get(
                context.agent_type.value,
                {"type": "document", "content": "レビュー対象"}
            ),
            "timestamp": datetime.now().isoformat()
        }

    def _init_mock_outputs(self) -> Dict[str, Dict[str, Any]]:
        """モック出力データの初期化"""
        return {
            "concept": {
                "type": "document",
                "format": "markdown",
                "content": """# ゲームコンセプト

## ゲーム概要
プレイヤーが楽しめるシンプルで直感的なゲーム体験を提供します。

## ターゲット層
- カジュアルゲーマー
- 全年齢対象

## 主要機能
1. 直感的な操作システム
2. 段階的な難易度設計
3. リプレイ性の高いゲームプレイ
"""
            },
            "design": {
                "type": "document",
                "format": "markdown",
                "content": """# ゲームデザインドキュメント

## ゲームメカニクス
- 基本操作: 矢印キー / WASD
- アクション: スペースキー

## UI/UX設計
- ミニマルデザイン
- 直感的なナビゲーション
"""
            },
            "scenario": {
                "type": "document",
                "format": "markdown",
                "content": """# ゲームシナリオ

## プロローグ
平和な世界に突然現れた謎の脅威...

## 第1章: 始まりの地
冒険の始まり。基本操作を学ぶ。

## 第2章: 試練
本格的な挑戦が始まる。
"""
            },
        }

    def _init_mock_tasks(self) -> Dict[str, List[str]]:
        """タスクリストの初期化"""
        return {
            "concept": ["要件分析", "市場調査", "コンセプト定義", "ドキュメント作成", "レビュー準備"],
            "design": ["メカニクス設計", "UI/UX設計", "画面遷移設計", "バランス調整案", "ドキュメント統合"],
            "scenario": ["プロット作成", "キャラクター配置", "イベント設計", "台詞作成", "校正"],
            "character": ["キャラクター分析", "ビジュアル設計", "パラメータ設定", "関係性定義", "ドキュメント化"],
            "world": ["世界観設計", "マップ構造", "環境設定", "ロア作成", "統合"],
            "task_split": ["タスク分析", "依存関係整理", "優先度設定", "工数見積", "タスク生成"],
            "code_leader": ["アーキテクチャ設計", "タスク割り当て", "コードレビュー", "統合計画", "品質管理"],
            "asset_leader": ["アセット計画", "スタイルガイド", "タスク割り当て", "品質確認", "統合"],
        }

    def _default_tasks(self) -> List[str]:
        """デフォルトタスクリスト"""
        return ["初期化", "処理中", "検証", "完了準備", "完了"]
