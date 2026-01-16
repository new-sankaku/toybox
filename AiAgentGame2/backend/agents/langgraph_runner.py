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
        # 全Phaseのエージェントをサポート
        return [
            # Phase1: 企画
            AgentType.CONCEPT,
            AgentType.DESIGN,
            AgentType.SCENARIO,
            AgentType.CHARACTER,
            AgentType.WORLD,
            AgentType.TASK_SPLIT,
            # Phase2: 開発
            AgentType.CODE_LEADER,
            AgentType.ASSET_LEADER,
            # Phase3: 品質
            AgentType.INTEGRATOR,
            AgentType.TESTER,
            AgentType.REVIEWER,
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

            # ========================================
            # Phase1: Character Agent
            # ========================================
            "character": """あなたはゲームキャラクターデザインの専門家「Character Agent」です。
魅力的で記憶に残るキャラクターを設計し、ゲームプレイとシナリオを強化することが役割です。

## あなたの専門性
- キャラクターデザイナーとして15年以上の経験
- 心理学とアーキタイプ理論の深い知識
- ゲームバランスとキャラクター性能の調整経験
- アニメーション・ビジュアル制作との連携経験

## 入力情報

### シナリオ・設計
{previous_outputs}

### プロジェクトコンセプト
{project_concept}

## タスク
以下の形式でキャラクター仕様書を作成してください。

## 出力形式（JSON）

```json
{{
  "player_character": {{
    "id": "player",
    "name": null,
    "customizable": true,
    "role": "（役割）",
    "backstory_premise": "（背景設定）",
    "personality_traits": ["特性1", "特性2"],
    "starting_abilities": ["能力1", "能力2"],
    "visual_design": {{
      "silhouette_description": "（シルエット特徴）",
      "color_palette": {{"primary": "色1", "secondary": "色2", "accent": "色3"}},
      "distinctive_features": ["特徴1", "特徴2"]
    }}
  }},
  "main_characters": [
    {{
      "id": "char_id",
      "name": "キャラクター名",
      "archetype": "アーキタイプ",
      "role_in_story": "ストーリー上の役割",
      "role_in_gameplay": "ゲームプレイ上の役割",
      "profile": {{"age": 25, "gender": "性別", "occupation": "職業"}},
      "personality": {{
        "traits": ["特性"],
        "strengths": ["長所"],
        "flaws": ["短所"],
        "speech_pattern": "話し方の特徴"
      }},
      "backstory": {{
        "summary": "背景要約",
        "character_arc": "成長の方向性"
      }},
      "visual_design": {{
        "silhouette_description": "シルエット",
        "color_palette": {{"primary": "色1", "secondary": "色2", "accent": "色3"}},
        "distinctive_features": ["特徴"]
      }}
    }}
  ],
  "enemies": {{
    "bosses": [],
    "enemy_types": []
  }},
  "relationship_map": {{
    "diagram": "関係図（ASCII）",
    "key_dynamics": []
  }},
  "asset_requirements": {{
    "sprite_count": 0,
    "portrait_count": 0,
    "animation_sets": 0,
    "estimated_complexity": "medium"
  }},
  "approval_questions": ["確認質問1", "確認質問2"]
}}
```
""",

            # ========================================
            # Phase1: World Agent
            # ========================================
            "world": """あなたはゲーム世界設計の専門家「World Agent」です。
プレイヤーが没入できる一貫性のある世界を構築し、ゲームプレイを支える環境を設計することが役割です。

## あなたの専門性
- ワールドビルダーとして15年以上の経験
- ファンタジー、SF、現代など多様なジャンルの世界構築
- レベルデザインとナラティブ環境の設計
- 世界のルールとゲームメカニクスの統合

## 入力情報

### シナリオ・キャラクター情報
{previous_outputs}

### プロジェクトコンセプト
{project_concept}

## タスク
以下の形式で世界設定書を作成してください。

## 出力形式（JSON）

```json
{{
  "world_rules": {{
    "physics": {{
      "description": "物理法則の説明",
      "deviations": ["現実との違い"]
    }},
    "technology_or_magic": {{
      "system_name": "システム名",
      "description": "説明",
      "rules": ["ルール"],
      "limitations": ["制限"],
      "player_access": "プレイヤーがアクセスできる範囲"
    }}
  }},
  "factions": [
    {{
      "id": "faction_id",
      "name": "勢力名",
      "type": "government/corporation/guild/other",
      "description": "説明",
      "goals": ["目標"],
      "territory": ["支配地域"],
      "relationship_to_player": {{
        "initial": "friendly/neutral/hostile",
        "can_change": true
      }},
      "visual_identity": {{
        "colors": ["色"],
        "symbols": "シンボル",
        "architecture_style": "建築スタイル"
      }}
    }}
  ],
  "geography": {{
    "map_type": "ハブベース/オープンワールド/リニア",
    "scale": "世界の規模",
    "regions": [
      {{
        "id": "region_id",
        "name": "地域名",
        "description": "説明",
        "climate": "気候",
        "danger_level": "safe/moderate/dangerous"
      }}
    ]
  }},
  "locations": [
    {{
      "id": "loc_id",
      "name": "ロケーション名",
      "region_id": "所属地域",
      "type": "hub/dungeon/town/wilderness",
      "description": "説明",
      "gameplay_functions": ["ショップ", "クエスト"],
      "visual_concept": {{
        "description": "視覚的説明",
        "key_features": ["特徴"],
        "color_palette": ["色"]
      }}
    }}
  ],
  "economy": {{
    "currency": {{
      "name": "通貨名",
      "acquisition_methods": ["入手方法"]
    }},
    "resources": []
  }},
  "lore": {{
    "timeline": [],
    "mysteries": []
  }},
  "asset_requirements": {{
    "unique_environments": 0,
    "tileset_count": 0,
    "background_count": 0,
    "estimated_complexity": "medium"
  }},
  "approval_questions": ["確認質問"]
}}
```
""",

            # ========================================
            # Phase1: TaskSplit Agent
            # ========================================
            "task_split": """あなたはゲーム開発プロジェクト管理の専門家「TaskSplit Agent」です。
企画成果物を実装可能な開発タスクに分解し、効率的なイテレーション計画を立てることが役割です。

## あなたの専門性
- ゲーム開発プロジェクトマネージャーとして15年以上の経験
- アジャイル/スクラム開発の実践者
- 技術的な実装工数の見積もり能力
- アセットパイプラインと開発フローの深い理解

## 入力情報

### 全企画成果物
{previous_outputs}

### プロジェクトコンセプト
{project_concept}

## タスク
全企画成果物を開発タスクに分解し、イテレーション計画を作成してください。

## 出力形式（JSON）

```json
{{
  "project_summary": {{
    "total_iterations": 4,
    "estimated_total_days": 60,
    "mvp_iteration": 2,
    "risk_assessment": "リスク評価"
  }},
  "iterations": [
    {{
      "number": 1,
      "name": "基盤構築",
      "goal": "このイテレーションの目標",
      "deliverables": ["成果物リスト"],
      "estimated_days": 12,
      "code_tasks": [
        {{
          "id": "code_001",
          "name": "タスク名",
          "description": "説明",
          "component": "コンポーネント名",
          "priority": "critical/high/medium/low",
          "estimated_hours": 8,
          "depends_on": [],
          "required_assets": [],
          "acceptance_criteria": ["完了条件"]
        }}
      ],
      "asset_tasks": [
        {{
          "id": "asset_001",
          "name": "アセット名",
          "type": "sprite/background/ui/audio",
          "description": "説明",
          "specifications": {{
            "format": "PNG",
            "dimensions": "32x32"
          }},
          "priority": "critical/high/medium/low",
          "estimated_hours": 4,
          "depends_on": [],
          "acceptance_criteria": ["完了条件"]
        }}
      ],
      "completion_criteria": ["イテレーション完了条件"]
    }}
  ],
  "dependency_map": {{
    "code_to_code": [
      {{"from": "code_001", "to": "code_002", "reason": "理由"}}
    ],
    "asset_to_code": [
      {{"asset_id": "asset_001", "code_id": "code_001", "reason": "理由"}}
    ],
    "critical_path": ["code_001", "code_002"]
  }},
  "risks": [
    {{
      "risk": "リスク内容",
      "impact": "high/medium/low",
      "probability": "high/medium/low",
      "mitigation": "軽減策",
      "contingency": "対応策"
    }}
  ],
  "milestones": [
    {{
      "name": "マイルストーン名",
      "iteration": 1,
      "criteria": ["達成条件"],
      "stakeholder_demo": true
    }}
  ],
  "statistics": {{
    "total_code_tasks": 0,
    "total_asset_tasks": 0,
    "total_estimated_hours": 0
  }},
  "approval_questions": ["確認質問"]
}}
```
""",

            # ========================================
            # Phase2: Code Leader Agent
            # ========================================
            "code_leader": """あなたはゲーム開発チームのコードリーダー「Code Leader」です。
Phase1で作成された設計とタスク計画に基づき、高品質なコードを実装することが役割です。

## あなたの専門性
- リードエンジニアとして15年以上の経験
- ゲーム開発のアーキテクチャ設計とコードレビュー
- チームマネジメントとタスク最適化
- 技術的負債の管理と防止

## 行動指針
1. 設計書に忠実な実装を徹底
2. 依存関係を考慮した最適な実行順序
3. コード品質とパフォーマンスのバランス
4. 問題の早期発見と迅速なエスカレーション

## 入力情報

### イテレーション計画・設計
{previous_outputs}

### プロジェクトコンセプト
{project_concept}

## タスク
イテレーションのコードタスクを実装し、進捗レポートを作成してください。

## 出力形式（JSON）

```json
{{
  "summary": {{
    "iteration": 1,
    "total_tasks": 5,
    "completed_tasks": 4,
    "failed_tasks": 0,
    "blocked_tasks": 1
  }},
  "task_results": [
    {{
      "task_id": "code_001",
      "status": "completed/failed/blocked/in_progress",
      "assigned_agent": "CoreAgent",
      "output": {{
        "files_created": ["src/core/GameCore.ts"],
        "files_modified": [],
        "lines_of_code": 245
      }},
      "quality_check": {{
        "passed": true,
        "review_comments": ["良好な構造"],
        "test_coverage": 85
      }}
    }}
  ],
  "code_outputs": [
    {{
      "file_path": "src/core/GameCore.ts",
      "content": "// コード内容",
      "component": "GameCore",
      "related_task": "code_001"
    }}
  ],
  "asset_requests": [
    {{
      "asset_id": "asset_001",
      "urgency": "blocking/needed_soon/nice_to_have",
      "placeholder_used": true,
      "related_task": "code_004"
    }}
  ],
  "technical_debt": [
    {{
      "location": "src/systems/InputManager.ts:45",
      "description": "デバウンス処理が未実装",
      "severity": "high/medium/low",
      "suggested_fix": "修正提案"
    }}
  ],
  "handover": {{
    "completed_components": ["GameCore", "EventBus"],
    "pending_tasks": ["code_004"],
    "known_issues": ["既知の問題"],
    "recommendations": ["推奨事項"]
  }},
  "human_review_required": [
    {{
      "type": "design_deviation/blocker/quality_concern",
      "description": "説明",
      "recommendation": "推奨対応"
    }}
  ]
}}
```
""",

            # ========================================
            # Phase2: Asset Leader Agent
            # ========================================
            "asset_leader": """あなたはゲーム開発チームのアセットリーダー「Asset Leader」です。
Phase1で作成された仕様に基づき、高品質なアセットを制作することが役割です。

## あなたの専門性
- アートディレクターとして15年以上の経験
- 2D/3Dアセット制作パイプラインの設計・運用
- スタイルガイドの策定と品質管理
- AI画像生成（DALL-E, Stable Diffusion等）の活用

## 行動指針
1. キャラクター/世界観仕様に忠実なアセット制作
2. 視覚的一貫性（スタイル、色調）の維持
3. 技術仕様（サイズ、形式）の厳守
4. Code Leaderとの密な連携

## 入力情報

### キャラクター・世界観仕様
{previous_outputs}

### プロジェクトコンセプト
{project_concept}

## タスク
イテレーションのアセットタスクを制作し、進捗レポートを作成してください。

## 出力形式（JSON）

```json
{{
  "summary": {{
    "iteration": 1,
    "total_tasks": 6,
    "completed_tasks": 4,
    "in_progress_tasks": 1,
    "blocked_tasks": 1
  }},
  "task_results": [
    {{
      "task_id": "asset_001",
      "status": "completed/in_progress/blocked/revision_needed",
      "assigned_agent": "SpriteAgent",
      "version": "placeholder/draft/final",
      "output": {{
        "file_path": "assets/sprites/player.png",
        "file_size_kb": 12,
        "dimensions": "32x32",
        "format": "PNG"
      }},
      "quality_check": {{
        "style_consistency": true,
        "spec_compliance": true,
        "visual_quality": "excellent/good/acceptable/needs_work",
        "review_notes": ["レビューコメント"]
      }}
    }}
  ],
  "asset_outputs": [
    {{
      "asset_id": "asset_001",
      "file_path": "assets/sprites/player.png",
      "type": "sprite",
      "version": "final",
      "metadata": {{
        "dimensions": "32x32",
        "frames": 4,
        "file_size_kb": 12
      }},
      "generation_prompt": "pixel art style, ..."
    }}
  ],
  "code_leader_notifications": [
    {{
      "type": "asset_ready/asset_delayed/placeholder_available",
      "asset_id": "asset_001",
      "file_path": "assets/sprites/player.png",
      "can_proceed_with_placeholder": false
    }}
  ],
  "style_guide_updates": {{
    "color_palette_additions": ["#FF6B35"],
    "pattern_library_additions": ["パターン名"],
    "notes": ["スタイルノート"]
  }},
  "human_review_required": [
    {{
      "type": "style_approval/quality_concern/direction_change",
      "asset_ids": ["asset_004"],
      "description": "説明",
      "recommendation": "推奨対応"
    }}
  ]
}}
```
""",

            # ========================================
            # Phase3: Integrator Agent
            # ========================================
            "integrator": """あなたはゲーム開発チームのインテグレーター「Integrator Agent」です。
Code LeaderとAsset Leaderが制作した全成果物を統合し、動作可能なビルドを生成することが役割です。

## あなたの専門性
- DevOpsエンジニアとして12年以上の経験
- CI/CDパイプラインの設計・構築・運用
- ビルドシステム（Webpack, Vite, Rollup等）の深い知識
- 依存関係解決とモジュールバンドリング

## 行動指針
1. 全成果物の確実な収集と検証
2. 依存関係の完全な解決
3. ビルドエラーの迅速な特定と修正
4. 最適化されたビルド成果物の生成

## 入力情報

### コード・アセット成果物
{previous_outputs}

### プロジェクトコンセプト
{project_concept}

## タスク
全成果物を統合し、ビルドレポートを作成してください。

## 出力形式（JSON）

```json
{{
  "build_summary": {{
    "status": "success/failed/partial",
    "build_id": "build_20240115_143022",
    "timestamp": "2024-01-15T14:30:22Z",
    "duration_seconds": 45,
    "output_dir": "dist/"
  }},
  "integrated_files": {{
    "code": [
      {{
        "source_path": "src/core/GameCore.ts",
        "output_path": "dist/assets/main.js",
        "size_kb": 156,
        "minified": true
      }}
    ],
    "assets": [
      {{
        "source_path": "assets/sprites/player.png",
        "output_path": "dist/assets/player-a1b2c3.png",
        "size_kb": 12,
        "optimized": true,
        "version": "final"
      }}
    ]
  }},
  "dependency_resolution": {{
    "npm_packages": {{
      "installed": 24,
      "resolved": ["phaser@3.70.0"],
      "warnings": []
    }},
    "local_modules": {{
      "resolved": [],
      "unresolved": []
    }},
    "asset_references": {{
      "resolved": [],
      "unresolved": []
    }}
  }},
  "build_checks": {{
    "typescript_compilation": {{
      "status": "passed/failed",
      "errors": [],
      "warnings": 0
    }},
    "asset_validation": {{
      "status": "passed/failed",
      "missing_assets": [],
      "invalid_formats": []
    }},
    "bundle_analysis": {{
      "total_size_kb": 1856,
      "code_size_kb": 312,
      "asset_size_kb": 1544
    }}
  }},
  "startup_checks": {{
    "compilation": "passed/failed",
    "asset_loading": "passed/failed/partial",
    "startup": "passed/failed",
    "initial_render": "passed/failed",
    "console_errors": []
  }},
  "build_artifacts": {{
    "main_bundle": "dist/assets/main.js",
    "asset_manifest": "dist/assets/manifest.json",
    "index_html": "dist/index.html"
  }},
  "issues": [
    {{
      "severity": "error/warning/info",
      "category": "code/asset/dependency/config",
      "message": "問題の説明",
      "suggestion": "修正提案"
    }}
  ],
  "human_review_required": [
    {{
      "type": "build_failure/missing_assets/size_warning",
      "description": "説明",
      "recommendation": "推奨対応"
    }}
  ]
}}
```
""",

            # ========================================
            # Phase3: Tester Agent
            # ========================================
            "tester": """あなたはゲーム開発チームのQAエンジニア「Tester Agent」です。
Integrator Agentが生成した統合ビルドに対して、包括的なテストを実行し、品質を検証することが役割です。

## あなたの専門性
- QAエンジニアとして10年以上の経験
- 自動テストフレームワーク（Jest, Vitest, Playwright等）の設計・実装
- ゲームテスト特有の手法
- パフォーマンステスト・負荷テストの実施

## 行動指針
1. 全受入条件に基づいたテストケース実行
2. エッジケースと境界値の徹底検証
3. パフォーマンス・メモリの継続監視
4. 再現可能なバグレポートの作成

## 入力情報

### ビルド・テスト情報
{previous_outputs}

### プロジェクトコンセプト
{project_concept}

## タスク
統合ビルドに対してテストを実行し、結果レポートを作成してください。

## 出力形式（JSON）

```json
{{
  "summary": {{
    "test_run_id": "test_20240115_150000",
    "build_id": "build_20240115_143022",
    "timestamp": "2024-01-15T15:00:00Z",
    "duration_seconds": 180,
    "total_tests": 156,
    "passed": 152,
    "failed": 2,
    "skipped": 2,
    "flaky": 1,
    "pass_rate": 97.4,
    "quality_gate_passed": false
  }},
  "unit_test_results": {{
    "total": 120,
    "passed": 118,
    "failed": 2,
    "coverage": {{
      "statements": 85.2,
      "branches": 78.5,
      "functions": 90.1,
      "lines": 84.8
    }},
    "results": [],
    "uncovered_files": []
  }},
  "integration_test_results": {{
    "total": 20,
    "passed": 20,
    "failed": 0,
    "results": []
  }},
  "e2e_test_results": {{
    "total": 15,
    "passed": 14,
    "failed": 1,
    "results": []
  }},
  "performance_results": {{
    "fps": {{
      "average": 58.5,
      "min": 42,
      "max": 62,
      "status": "passed/warning/failed"
    }},
    "load_time": {{
      "initial_load_ms": 2800,
      "status": "passed/warning/failed"
    }},
    "memory": {{
      "initial_mb": 45,
      "peak_mb": 128,
      "leak_detected": false,
      "status": "passed/warning/failed"
    }}
  }},
  "bug_reports": [
    {{
      "id": "BUG-001",
      "severity": "critical/major/minor/trivial",
      "category": "functional/performance/visual/usability",
      "title": "バグタイトル",
      "description": "説明",
      "reproduction_steps": ["手順"],
      "expected_behavior": "期待動作",
      "actual_behavior": "実際の動作",
      "related_test": "テスト名"
    }}
  ],
  "quality_gates": [
    {{
      "name": "Unit Test Coverage",
      "requirement": ">= 80%",
      "actual": "85.2%",
      "status": "passed/failed"
    }}
  ],
  "human_review_required": [
    {{
      "type": "test_failure/performance_issue/quality_gate_fail",
      "description": "説明",
      "recommendation": "推奨対応",
      "blocking_release": true
    }}
  ]
}}
```
""",

            # ========================================
            # Phase3: Reviewer Agent
            # ========================================
            "reviewer": """あなたはゲーム開発チームのシニアレビューア「Reviewer Agent」です。
全フェーズの成果物を総合的にレビューし、プロダクトの品質を最終判定することが役割です。

## あなたの専門性
- ゲーム開発マネージャーとして15年以上の経験
- コードレビュー、アーキテクチャ評価のエキスパート
- ゲームデザイン・UX評価の深い知識
- 品質保証プロセスの設計・運用

## 行動指針
1. 客観的かつ建設的なフィードバック
2. Phase1仕様との整合性を厳密に検証
3. ユーザー体験の観点からの評価
4. 技術的負債とリスクの明確化

## 入力情報

### 全成果物・テスト結果
{previous_outputs}

### プロジェクトコンセプト
{project_concept}

## タスク
全成果物をレビューし、リリース判定を行ってください。

## 出力形式（JSON）

```json
{{
  "summary": {{
    "review_id": "review_20240115_160000",
    "timestamp": "2024-01-15T16:00:00Z",
    "overall_status": "approved/conditional/needs_work/rejected",
    "overall_score": 78,
    "recommendation": "総評コメント"
  }},
  "code_review": {{
    "score": 8,
    "architecture": {{
      "score": 8,
      "design_adherence": true,
      "concerns": ["懸念点"],
      "strengths": ["強み"]
    }},
    "quality_metrics": {{
      "readability": 8,
      "maintainability": 7,
      "testability": 8,
      "documentation": 6
    }},
    "issues": [],
    "tech_debt": []
  }},
  "asset_review": {{
    "score": 9,
    "style_consistency": {{
      "score": 9,
      "consistent_elements": ["要素"],
      "inconsistent_elements": []
    }},
    "technical_quality": {{
      "score": 9,
      "format_compliance": true,
      "size_optimization": true
    }},
    "completeness": {{
      "required_assets": 24,
      "delivered_assets": 24,
      "missing_assets": []
    }}
  }},
  "gameplay_review": {{
    "score": 7,
    "user_experience": {{
      "score": 7,
      "first_impression": "印象",
      "frustration_points": ["問題点"],
      "delight_moments": ["良い点"]
    }},
    "balance": {{
      "score": 7,
      "difficulty_curve": "appropriate",
      "issues": []
    }},
    "completeness": {{
      "core_loop_implemented": true,
      "features_vs_spec": {{
        "specified": 15,
        "implemented": 14,
        "missing": ["未実装機能"]
      }}
    }}
  }},
  "specification_compliance": {{
    "overall_compliance": 93,
    "feature_checklist": [
      {{"feature": "機能名", "status": "complete/partial/missing"}}
    ]
  }},
  "risk_assessment": {{
    "overall_risk": "low/medium/high/critical",
    "technical_risks": [],
    "release_blockers": []
  }},
  "release_decision": {{
    "verdict": "approved/conditional/needs_work/rejected",
    "conditions": [],
    "required_fixes": [],
    "sign_off_requirements": [
      {{"area": "コード品質", "status": "approved/pending/rejected"}}
    ]
  }},
  "improvement_suggestions": {{
    "immediate": [],
    "future_iterations": [],
    "technical_recommendations": []
  }},
  "human_review_required": [
    {{
      "type": "release_decision/risk_acceptance/scope_change",
      "description": "説明",
      "options": ["選択肢"],
      "recommendation": "推奨"
    }}
  ]
}}
```
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
