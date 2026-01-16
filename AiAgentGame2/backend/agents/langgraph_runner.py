"""
LangGraph Agent Runner

本番用のLangGraphベースエージェント実装
Claude APIを使用して実際のコンテンツを生成
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, AsyncGenerator, Optional
import os

from .base import (
    AgentRunner,
    AgentContext,
    AgentOutput,
    AgentType,
    AgentStatus,
)


class LangGraphAgentRunner(AgentRunner):
    """
    LangGraphベースのエージェントランナー

    各エージェントタイプに対応するLangGraphノードを実行し、
    Claude APIを使用してコンテンツを生成する
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 4096,
        **kwargs
    ):
        """
        Args:
            api_key: Anthropic API Key (環境変数ANTHROPIC_API_KEYから取得も可)
            model: 使用するClaudeモデル
            max_tokens: 最大トークン数
        """
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model
        self.max_tokens = max_tokens

        # LangGraphとLLMクライアントは遅延初期化
        self._llm_client = None
        self._graphs: Dict[AgentType, Any] = {}

        # プロンプトテンプレート
        self._prompts = self._load_prompts()

    def _get_llm_client(self):
        """LLMクライアントを取得（遅延初期化）"""
        if self._llm_client is None:
            try:
                from anthropic import Anthropic
                self._llm_client = Anthropic(api_key=self.api_key)
            except ImportError:
                raise ImportError(
                    "anthropic package is required. Install with: pip install anthropic"
                )
        return self._llm_client

    async def run_agent(self, context: AgentContext) -> AgentOutput:
        """エージェントを実行（非ストリーミング）"""
        started_at = datetime.now().isoformat()
        tokens_used = 0
        output = {}

        try:
            async for event in self.run_agent_stream(context):
                if event["type"] == "output":
                    output = event["data"]
                elif event["type"] == "tokens":
                    tokens_used += event["data"].get("count", 0)

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

        # 開始ログ
        yield {
            "type": "log",
            "data": {
                "level": "info",
                "message": f"LangGraph Agent開始: {agent_type.value}",
                "timestamp": datetime.now().isoformat()
            }
        }

        # 進捗: 準備中
        yield {
            "type": "progress",
            "data": {"progress": 10, "current_task": "プロンプト準備中"}
        }

        # プロンプト取得
        prompt = self._build_prompt(context)

        yield {
            "type": "progress",
            "data": {"progress": 20, "current_task": "LLM呼び出し中"}
        }

        # LLM呼び出し
        try:
            result = await self._call_llm(prompt, context)

            yield {
                "type": "tokens",
                "data": {
                    "count": result.get("tokens_used", 0),
                    "total": result.get("tokens_used", 0)
                }
            }

            yield {
                "type": "progress",
                "data": {"progress": 80, "current_task": "出力処理中"}
            }

            # 出力を整形
            output = self._process_output(result, context)

            yield {
                "type": "progress",
                "data": {"progress": 90, "current_task": "チェックポイント準備"}
            }

            # チェックポイント生成
            checkpoint_data = self._generate_checkpoint(context, output)
            yield {
                "type": "checkpoint",
                "data": checkpoint_data
            }

            if context.on_checkpoint:
                context.on_checkpoint(checkpoint_data["type"], checkpoint_data)

            yield {
                "type": "progress",
                "data": {"progress": 100, "current_task": "完了"}
            }

            # 最終出力
            yield {
                "type": "output",
                "data": output
            }

        except Exception as e:
            yield {
                "type": "log",
                "data": {
                    "level": "error",
                    "message": f"LLM呼び出しエラー: {str(e)}",
                    "timestamp": datetime.now().isoformat()
                }
            }
            yield {
                "type": "error",
                "data": {"message": str(e)}
            }
            raise

        # 完了ログ
        yield {
            "type": "log",
            "data": {
                "level": "info",
                "message": "LangGraph Agent完了",
                "timestamp": datetime.now().isoformat()
            }
        }

    async def _call_llm(self, prompt: str, context: AgentContext) -> Dict[str, Any]:
        """Claude APIを呼び出し"""
        client = self._get_llm_client()

        # 非同期で実行（anthropicはsyncなのでrun_in_executorで）
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
        )

        return {
            "content": response.content[0].text,
            "tokens_used": response.usage.input_tokens + response.usage.output_tokens,
            "model": response.model,
        }

    def _build_prompt(self, context: AgentContext) -> str:
        """プロンプトを構築"""
        agent_type = context.agent_type.value
        base_prompt = self._prompts.get(agent_type, self._default_prompt())

        # コンテキスト情報を埋め込み
        prompt = base_prompt.format(
            project_concept=context.project_concept or "（未定義）",
            previous_outputs=self._format_previous_outputs(context.previous_outputs),
            config=context.config,
        )

        return prompt

    def _format_previous_outputs(self, outputs: Dict[str, Any]) -> str:
        """前のエージェントの出力をフォーマット"""
        if not outputs:
            return "（なし）"

        parts = []
        for agent, output in outputs.items():
            if isinstance(output, dict) and "content" in output:
                parts.append(f"## {agent}の出力\n{output['content']}")
            else:
                parts.append(f"## {agent}の出力\n{output}")

        return "\n\n".join(parts)

    def _process_output(self, result: Dict[str, Any], context: AgentContext) -> Dict[str, Any]:
        """LLM出力を処理・整形"""
        return {
            "type": "document",
            "format": "markdown",
            "content": result.get("content", ""),
            "metadata": {
                "model": result.get("model"),
                "tokens_used": result.get("tokens_used"),
                "agent_type": context.agent_type.value,
            }
        }

    def _generate_checkpoint(self, context: AgentContext, output: Dict[str, Any]) -> Dict[str, Any]:
        """チェックポイントデータを生成"""
        checkpoint_config = {
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

        cp_type, title = checkpoint_config.get(
            context.agent_type,
            ("review", "レビュー依頼")
        )

        return {
            "type": cp_type,
            "title": title,
            "description": f"{context.agent_type.value}エージェントの出力を確認してください",
            "output": output,
            "timestamp": datetime.now().isoformat()
        }

    def get_supported_agents(self) -> List[AgentType]:
        """サポートしているエージェントタイプ"""
        # 現在は全タイプをサポート（プロンプトがあるもの）
        return [
            AgentType.CONCEPT,
            AgentType.DESIGN,
            AgentType.SCENARIO,
            AgentType.CHARACTER,
            AgentType.WORLD,
            AgentType.TASK_SPLIT,
        ]

    def validate_context(self, context: AgentContext) -> bool:
        """コンテキストのバリデーション"""
        if not self.api_key:
            return False
        if context.agent_type not in self.get_supported_agents():
            return False
        return True

    def _load_prompts(self) -> Dict[str, str]:
        """プロンプトテンプレートをロード"""
        return {
            "concept": """あなたはゲームコンセプト設計の専門家です。

以下のゲーム企画について、詳細なコンセプトドキュメントを作成してください。

## ユーザーの企画内容
{project_concept}

## 出力形式
以下の形式でMarkdownドキュメントを作成してください：

# ゲームコンセプト

## ゲーム概要
（ゲームの基本的な説明）

## ターゲット層
（想定するプレイヤー層）

## コアゲームプレイ
（中心となるゲーム体験）

## ユニークセールスポイント
（このゲームならではの魅力）

## 技術要件
（必要な技術スタック）
""",
            "design": """あなたはゲームデザイナーです。

以下のコンセプトに基づいて、詳細なゲームデザインドキュメントを作成してください。

## コンセプト
{previous_outputs}

## 出力形式
以下の形式でMarkdownドキュメントを作成：

# ゲームデザインドキュメント

## ゲームメカニクス
（操作方法、ルール）

## ゲームフロー
（画面遷移、進行）

## UI/UX設計
（インターフェース設計）

## バランス設計
（難易度、報酬設計）
""",
            "scenario": """あなたはゲームシナリオライターです。

以下のゲーム設計に基づいて、シナリオを作成してください。

## ゲーム設計
{previous_outputs}

## 出力形式

# ゲームシナリオ

## 世界観
（舞台設定）

## ストーリー概要
（あらすじ）

## 章構成
（各章の概要）
""",
        }

    def _default_prompt(self) -> str:
        """デフォルトプロンプト"""
        return """あなたはゲーム開発の専門家です。

以下の情報に基づいて、適切なドキュメントを作成してください。

## プロジェクト情報
{project_concept}

## 前のエージェントの出力
{previous_outputs}

## 要件
詳細で実用的なドキュメントを作成してください。
"""
