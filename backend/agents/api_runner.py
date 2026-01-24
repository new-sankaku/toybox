import asyncio
from datetime import datetime
from typing import Any,Dict,List,AsyncGenerator,Optional,Callable
import os
from dataclasses import dataclass,field

from .base import (
    AgentRunner,
    AgentContext,
    AgentOutput,
    AgentType,
    AgentStatus,
)


class ApiAgentRunner(AgentRunner):
    def __init__(
        self,
        api_key:Optional[str] = None,
        model:str = "claude-sonnet-4-20250514",
        max_tokens:int = 4096,
        **kwargs
    ):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model
        self.max_tokens = max_tokens
        self._llm_client = None
        self._graphs:Dict[AgentType,Any] = {}
        self._prompts = self._load_prompts()

    def _get_llm_client(self):
        if self._llm_client is None:
            try:
                from anthropic import Anthropic
                self._llm_client = Anthropic(api_key=self.api_key)
            except ImportError:
                raise ImportError(
                    "anthropic package is required. Install with: pip install anthropic"
                )
        return self._llm_client

    async def run_agent(self,context:AgentContext)->AgentOutput:
        started_at = datetime.now().isoformat()
        tokens_used = 0
        output = {}

        try:
            async for event in self.run_agent_stream(context):
                if event["type"] == "output":
                    output = event["data"]
                elif event["type"] == "tokens":
                    tokens_used += event["data"].get("count",0)

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
        context:AgentContext
    )->AsyncGenerator[Dict[str,Any],None]:
        agent_type = context.agent_type

        yield {
            "type":"log",
            "data":{
                "level":"info",
                "message":f"API Agent開始: {agent_type.value}",
                "timestamp":datetime.now().isoformat()
            }
        }

        yield {
            "type":"progress",
            "data":{"progress":10,"current_task":"プロンプト準備中"}
        }

        prompt = self._build_prompt(context)

        yield {
            "type":"progress",
            "data":{"progress":20,"current_task":"LLM呼び出し中"}
        }

        try:
            result = await self._call_llm(prompt,context)

            yield {
                "type":"tokens",
                "data":{
                    "count":result.get("tokens_used",0),
                    "total":result.get("tokens_used",0)
                }
            }

            yield {
                "type":"progress",
                "data":{"progress":80,"current_task":"出力処理中"}
            }

            output = self._process_output(result,context)

            yield {
                "type":"progress",
                "data":{"progress":90,"current_task":"承認準備"}
            }

            checkpoint_data = self._generate_checkpoint(context,output)
            yield {
                "type":"checkpoint",
                "data":checkpoint_data
            }

            if context.on_checkpoint:
                context.on_checkpoint(checkpoint_data["type"],checkpoint_data)

            yield {
                "type":"progress",
                "data":{"progress":100,"current_task":"完了"}
            }

            yield {
                "type":"output",
                "data":output
            }

        except Exception as e:
            yield {
                "type":"log",
                "data":{
                    "level":"error",
                    "message":f"LLM呼び出しエラー: {str(e)}",
                    "timestamp":datetime.now().isoformat()
                }
            }
            yield {
                "type":"error",
                "data":{"message":str(e)}
            }
            raise

        yield {
            "type":"log",
            "data":{
                "level":"info",
                "message":"API Agent完了",
                "timestamp":datetime.now().isoformat()
            }
        }

    async def _call_llm(self,prompt:str,context:AgentContext)->Dict[str,Any]:
        client = self._get_llm_client()

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda:client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[
                    {"role":"user","content":prompt}
                ]
            )
        )

        return {
            "content":response.content[0].text,
            "tokens_used":response.usage.input_tokens + response.usage.output_tokens,
            "model":response.model,
        }

    def _build_prompt(self,context:AgentContext)->str:
        agent_type = context.agent_type.value
        base_prompt = self._prompts.get(agent_type,self._default_prompt())
        prompt = base_prompt.format(
            project_concept=context.project_concept or "（未定義）",
            previous_outputs=self._format_previous_outputs(context.previous_outputs),
            config=context.config,
        )

        return prompt

    def _format_previous_outputs(self,outputs:Dict[str,Any])->str:
        if not outputs:
            return "（なし）"

        parts = []
        for agent,output in outputs.items():
            if isinstance(output,dict) and "content" in output:
                parts.append(f"## {agent}の出力\n{output['content']}")
            else:
                parts.append(f"## {agent}の出力\n{output}")

        return "\n\n".join(parts)

    def _process_output(self,result:Dict[str,Any],context:AgentContext)->Dict[str,Any]:
        return {
            "type":"document",
            "format":"markdown",
            "content":result.get("content",""),
            "metadata":{
                "model":result.get("model"),
                "tokens_used":result.get("tokens_used"),
                "agent_type":context.agent_type.value,
            }
        }

    def _generate_checkpoint(self,context:AgentContext,output:Dict[str,Any])->Dict[str,Any]:
        checkpoint_config = {

            AgentType.CONCEPT_LEADER:("concept_review","ゲームコンセプトのレビュー"),
            AgentType.DESIGN_LEADER:("design_review","ゲームデザインのレビュー"),
            AgentType.SCENARIO_LEADER:("scenario_review","シナリオのレビュー"),
            AgentType.CHARACTER_LEADER:("character_review","キャラクターのレビュー"),
            AgentType.WORLD_LEADER:("world_review","ワールド設定のレビュー"),
            AgentType.TASK_SPLIT_LEADER:("task_review","タスク分割のレビュー"),

            AgentType.CODE_LEADER:("code_plan_review","コード計画のレビュー"),
            AgentType.ASSET_LEADER:("asset_plan_review","アセット計画のレビュー"),

            AgentType.INTEGRATOR_LEADER:("integration_review","統合結果のレビュー"),
            AgentType.TESTER_LEADER:("test_review","テスト結果のレビュー"),
            AgentType.REVIEWER_LEADER:("final_review","最終レビュー"),
        }

        cp_type,title = checkpoint_config.get(
            context.agent_type,
            ("review","レビュー依頼")
        )

        return {
            "type":cp_type,
            "title":title,
            "description":f"{context.agent_type.value}エージェントの出力を確認してください",
            "output":output,
            "timestamp":datetime.now().isoformat()
        }

    def get_supported_agents(self)->List[AgentType]:
        return [

            AgentType.CONCEPT_LEADER,
            AgentType.DESIGN_LEADER,
            AgentType.SCENARIO_LEADER,
            AgentType.CHARACTER_LEADER,
            AgentType.WORLD_LEADER,
            AgentType.TASK_SPLIT_LEADER,

            AgentType.RESEARCH_WORKER,
            AgentType.IDEATION_WORKER,
            AgentType.CONCEPT_VALIDATION_WORKER,

            AgentType.ARCHITECTURE_WORKER,
            AgentType.COMPONENT_WORKER,
            AgentType.DATAFLOW_WORKER,

            AgentType.STORY_WORKER,
            AgentType.DIALOG_WORKER,
            AgentType.EVENT_WORKER,

            AgentType.MAIN_CHARACTER_WORKER,
            AgentType.NPC_WORKER,
            AgentType.RELATIONSHIP_WORKER,

            AgentType.GEOGRAPHY_WORKER,
            AgentType.LORE_WORKER,
            AgentType.SYSTEM_WORKER,

            AgentType.ANALYSIS_WORKER,
            AgentType.DECOMPOSITION_WORKER,
            AgentType.SCHEDULE_WORKER,

            AgentType.CODE_LEADER,
            AgentType.ASSET_LEADER,

            AgentType.CODE_WORKER,
            AgentType.ASSET_WORKER,

            AgentType.INTEGRATOR_LEADER,
            AgentType.TESTER_LEADER,
            AgentType.REVIEWER_LEADER,

            AgentType.DEPENDENCY_WORKER,
            AgentType.BUILD_WORKER,
            AgentType.INTEGRATION_VALIDATION_WORKER,

            AgentType.UNIT_TEST_WORKER,
            AgentType.INTEGRATION_TEST_WORKER,
            AgentType.E2E_TEST_WORKER,
            AgentType.PERFORMANCE_TEST_WORKER,

            AgentType.CODE_REVIEW_WORKER,
            AgentType.ASSET_REVIEW_WORKER,
            AgentType.GAMEPLAY_REVIEW_WORKER,
            AgentType.COMPLIANCE_WORKER,
        ]

    def validate_context(self,context:AgentContext)->bool:
        if not self.api_key:
            return False
        if context.agent_type not in self.get_supported_agents():
            return False
        return True

    def _load_prompts(self)->Dict[str,str]:
        return {



            "concept_leader":"""あなたはゲームコンセプト設計チームのリーダー「Concept Leader」です。
配下のWorkerを指揮してゲームコンセプトを策定することが役割です。

## あなたの専門性
- ゲーム企画として15年以上の経験
- 市場分析とトレンド予測
- コンセプト評価と意思決定

## 配下Worker
- ResearchWorker: 市場調査、類似ゲーム分析
- IdeationWorker: コンセプト要素生成
- ValidationWorker: 整合性・実現可能性チェック

## 行動指針
1. 各Workerにタスクを割り当て
2. Workerの成果物を品質チェック（最大3回リトライ）
3. 問題があればHuman確認を要求
4. 最終的なコンセプトドキュメントを統合・出力

## 入力情報
### プロジェクトコンセプト
{project_concept}

### 前の成果物
{previous_outputs}

## 出力形式（JSON）
```json
{{
  "worker_tasks": [
    {{"worker": "research", "task": "市場調査", "status": "completed"}},
    {{"worker": "ideation", "task": "コンセプト生成", "status": "completed"}},
    {{"worker": "validation", "task": "検証", "status": "completed"}}
  ],
  "concept_document": {{
    "title": "ゲームタイトル",
    "overview": "概要",
    "target_audience": "ターゲット層",
    "core_gameplay": "コアゲームプレイ",
    "unique_selling_points": ["USP1", "USP2"],
    "technical_requirements": ["要件1", "要件2"]
  }},
  "quality_checks": {{
    "market_fit": true,
    "feasibility": true,
    "originality": true
  }},
  "human_review_required": []
}}
```
""",


            "research_worker":"""あなたはマーケットリサーチャー「Research Worker」です。

## タスク
市場調査と類似ゲーム分析を行ってください。

## 入力
{project_concept}

## 出力形式（JSON）
```json
{{
  "market_analysis": {{
    "market_size": "市場規模",
    "trends": ["トレンド1", "トレンド2"],
    "opportunities": ["機会1", "機会2"]
  }},
  "competitor_analysis": [
    {{"name": "競合ゲーム名", "strengths": ["強み"], "weaknesses": ["弱み"]}}
  ],
  "recommendations": ["推奨事項"]
}}
```
""",

            "ideation_worker":"""あなたはゲームコンセプトクリエイター「Ideation Worker」です。

## タスク
ゲームコンセプトの要素を創出してください。

## 入力
{project_concept}

## 前の成果物
{previous_outputs}

## 出力形式（JSON）
```json
{{
  "game_concepts": [
    {{
      "title": "コンセプト案",
      "description": "説明",
      "mechanics": ["メカニクス"],
      "visual_style": "ビジュアルスタイル",
      "differentiation": "差別化ポイント"
    }}
  ],
  "recommended_concept": 0,
  "reasoning": "推奨理由"
}}
```
""",

            "concept_validation_worker":"""あなたはコンセプト検証スペシャリスト「Validation Worker」です。

## タスク
コンセプトの整合性と実現可能性を検証してください。

## 入力
{previous_outputs}

## 出力形式（JSON）
```json
{{
  "validation_results": {{
    "market_fit": {{"passed": true, "notes": "メモ"}},
    "technical_feasibility": {{"passed": true, "notes": "メモ"}},
    "resource_requirements": {{"passed": true, "notes": "メモ"}},
    "originality": {{"passed": true, "notes": "メモ"}}
  }},
  "risks": ["リスク1", "リスク2"],
  "recommendations": ["推奨事項"],
  "overall_verdict": "approved"
}}
```
""",




            "design_leader":"""あなたはゲームデザインチームのリーダー「Design Leader」です。
配下のWorkerを指揮してゲームの技術設計を行うことが役割です。

## あなたの専門性
- テクニカルディレクターとして15年以上の経験
- ゲームアーキテクチャ設計
- システム統合と最適化

## 配下Worker
- ArchitectureWorker: システムアーキテクチャ設計
- ComponentWorker: 個別コンポーネント設計
- DataFlowWorker: データフロー・状態管理設計

## 入力情報
### プロジェクトコンセプト
{project_concept}

### 前の成果物
{previous_outputs}

## 出力形式（JSON）
```json
{{
  "worker_tasks": [],
  "design_document": {{
    "architecture": {{}},
    "components": [],
    "data_flow": {{}},
    "ui_ux": {{}}
  }},
  "quality_checks": {{}},
  "human_review_required": []
}}
```
""",


            "architecture_worker":"""あなたはシステムアーキテクト「Architecture Worker」です。

## タスク
ゲームシステムのアーキテクチャを設計してください。

## 入力
{previous_outputs}

## 出力形式（JSON）
```json
{{
  "architecture": {{
    "pattern": "アーキテクチャパターン",
    "layers": ["レイヤー1", "レイヤー2"],
    "modules": [
      {{"name": "モジュール名", "responsibility": "責務", "dependencies": []}}
    ],
    "technology_stack": {{"framework": "Phaser", "language": "TypeScript"}}
  }}
}}
```
""",

            "component_worker":"""あなたはコンポーネント設計者「Component Worker」です。

## タスク
個別コンポーネントの詳細設計を行ってください。

## 入力
{previous_outputs}

## 出力形式（JSON）
```json
{{
  "components": [
    {{
      "name": "コンポーネント名",
      "type": "core/system/ui",
      "interface": {{"methods": [], "events": []}},
      "dependencies": [],
      "implementation_notes": "実装メモ"
    }}
  ]
}}
```
""",

            "dataflow_worker":"""あなたはデータフロー設計者「DataFlow Worker」です。

## タスク
データフローと状態管理を設計してください。

## 入力
{previous_outputs}

## 出力形式（JSON）
```json
{{
  "data_flow": {{
    "state_management": {{"pattern": "パターン", "stores": []}},
    "event_system": {{"type": "EventEmitter", "events": []}},
    "data_persistence": {{"storage": "localStorage", "schema": {{}}}}
  }}
}}
```
""",




            "scenario_leader":"""あなたはシナリオチームのリーダー「Scenario Leader」です。
配下のWorkerを指揮してゲームシナリオを作成することが役割です。

## あなたの専門性
- シナリオディレクターとして15年以上の経験
- ナラティブデザイン
- インタラクティブストーリーテリング

## 配下Worker
- StoryWorker: メインストーリー・章構成
- DialogWorker: ダイアログ・会話作成
- EventWorker: イベント・分岐設計

## 入力情報
### プロジェクトコンセプト
{project_concept}

### 前の成果物
{previous_outputs}

## 出力形式（JSON）
```json
{{
  "worker_tasks": [],
  "scenario_document": {{
    "world_setting": {{}},
    "main_story": {{}},
    "chapters": [],
    "dialogs": [],
    "events": []
  }},
  "quality_checks": {{}},
  "human_review_required": []
}}
```
""",


            "story_worker":"""あなたはストーリーライター「Story Worker」です。

## タスク
メインストーリーと章構成を作成してください。

## 入力
{previous_outputs}

## 出力形式（JSON）
```json
{{
  "main_story": {{
    "premise": "前提",
    "theme": "テーマ",
    "plot_summary": "あらすじ"
  }},
  "chapters": [
    {{"number": 1, "title": "章タイトル", "summary": "概要", "key_events": []}}
  ]
}}
```
""",

            "dialog_worker":"""あなたはダイアログライター「Dialog Worker」です。

## タスク
キャラクターの会話・ダイアログを作成してください。

## 入力
{previous_outputs}

## 出力形式（JSON）
```json
{{
  "dialogs": [
    {{
      "id": "dialog_001",
      "scene": "シーン名",
      "participants": ["キャラ1", "キャラ2"],
      "lines": [
        {{"speaker": "キャラ1", "text": "セリフ", "emotion": "感情"}}
      ]
    }}
  ]
}}
```
""",

            "event_worker":"""あなたはイベント設計者「Event Worker」です。

## タスク
ゲームイベントと分岐を設計してください。

## 入力
{previous_outputs}

## 出力形式（JSON）
```json
{{
  "events": [
    {{
      "id": "event_001",
      "type": "story/side/random",
      "trigger": "トリガー条件",
      "branches": [
        {{"choice": "選択肢", "outcome": "結果", "next_event": "次イベント"}}
      ]
    }}
  ]
}}
```
""",




            "character_leader":"""あなたはキャラクターデザインチームのリーダー「Character Leader」です。
配下のWorkerを指揮してキャラクター設計を行うことが役割です。

## あなたの専門性
- キャラクターデザインディレクターとして15年以上の経験
- 心理学とアーキタイプ理論の深い知識
- アニメーション・ビジュアル制作との連携経験

## 配下Worker
- MainCharacterWorker: 主要キャラクター設計
- NPCWorker: NPC・敵キャラ設計
- RelationshipWorker: キャラ間関係性設計

## 入力情報
### プロジェクトコンセプト
{project_concept}

### 前の成果物
{previous_outputs}

## 出力形式（JSON）
```json
{{
  "worker_tasks": [],
  "character_document": {{
    "player_character": {{}},
    "main_characters": [],
    "npcs": [],
    "enemies": {{}},
    "relationship_map": {{}}
  }},
  "asset_requirements": {{}},
  "quality_checks": {{}},
  "human_review_required": []
}}
```
""",


            "main_character_worker":"""あなたはメインキャラクターデザイナー「MainCharacter Worker」です。

## タスク
プレイヤーキャラクターと主要キャラクターを設計してください。

## 入力
{previous_outputs}

## 出力形式（JSON）
```json
{{
  "player_character": {{
    "id": "player",
    "role": "役割",
    "backstory_premise": "背景設定",
    "personality_traits": ["特性"],
    "visual_design": {{
      "silhouette_description": "シルエット特徴",
      "color_palette": {{"primary": "色1", "secondary": "色2"}},
      "distinctive_features": ["特徴"]
    }}
  }},
  "main_characters": [
    {{
      "id": "char_id",
      "name": "キャラクター名",
      "archetype": "アーキタイプ",
      "role_in_story": "ストーリー上の役割",
      "personality": {{"traits": [], "strengths": [], "flaws": []}},
      "visual_design": {{}}
    }}
  ]
}}
```
""",

            "npc_worker":"""あなたはNPC・敵キャラデザイナー「NPC Worker」です。

## タスク
NPC、敵キャラクター、ボスを設計してください。

## 入力
{previous_outputs}

## 出力形式（JSON）
```json
{{
  "npcs": [
    {{
      "id": "npc_id",
      "name": "NPC名",
      "role": "役割",
      "location": "出現場所",
      "function": "ゲーム内機能"
    }}
  ],
  "enemies": {{
    "regular": [
      {{"id": "enemy_id", "name": "敵名", "type": "タイプ", "behavior": "行動パターン"}}
    ],
    "bosses": [
      {{"id": "boss_id", "name": "ボス名", "chapter": 1, "mechanics": []}}
    ]
  }}
}}
```
""",

            "relationship_worker":"""あなたはキャラクター関係性デザイナー「Relationship Worker」です。

## タスク
キャラクター間の関係性と相関図を設計してください。

## 入力
{previous_outputs}

## 出力形式（JSON）
```json
{{
  "relationship_map": {{
    "connections": [
      {{"from": "char_id1", "to": "char_id2", "type": "関係タイプ", "description": "説明"}}
    ],
    "factions": [
      {{"name": "勢力名", "members": ["char_id"], "stance": "立場"}}
    ],
    "key_dynamics": ["重要な関係性1", "重要な関係性2"]
  }}
}}
```
""",




            "world_leader":"""あなたはワールドビルディングチームのリーダー「World Leader」です。
配下のWorkerを指揮して世界設計を行うことが役割です。

## あなたの専門性
- ワールドビルディングディレクターとして15年以上の経験
- レベルデザインとナラティブ環境の設計
- 世界のルールとゲームメカニクスの統合

## 配下Worker
- GeographyWorker: 地理・マップ・ロケーション設計
- LoreWorker: 歴史・設定・世界観設計
- SystemWorker: 経済・勢力システム設計

## 入力情報
### プロジェクトコンセプト
{project_concept}

### 前の成果物
{previous_outputs}

## 出力形式（JSON）
```json
{{
  "worker_tasks": [],
  "world_document": {{
    "world_rules": {{}},
    "geography": {{}},
    "locations": [],
    "factions": [],
    "economy": {{}},
    "lore": {{}}
  }},
  "asset_requirements": {{}},
  "quality_checks": {{}},
  "human_review_required": []
}}
```
""",


            "geography_worker":"""あなたは地理設計者「Geography Worker」です。

## タスク
地理・マップ・ロケーションを設計してください。

## 入力
{previous_outputs}

## 出力形式（JSON）
```json
{{
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
      "visual_concept": {{"key_features": [], "color_palette": []}}
    }}
  ]
}}
```
""",

            "lore_worker":"""あなたは設定・世界観ライター「Lore Worker」です。

## タスク
歴史・設定・世界観を設計してください。

## 入力
{previous_outputs}

## 出力形式（JSON）
```json
{{
  "world_rules": {{
    "physics": {{"description": "物理法則", "deviations": []}},
    "technology_or_magic": {{
      "system_name": "システム名",
      "rules": [],
      "limitations": []
    }}
  }},
  "lore": {{
    "timeline": [
      {{"era": "時代名", "events": ["出来事"]}}
    ],
    "mysteries": ["謎1", "謎2"],
    "legends": ["伝説"]
  }}
}}
```
""",

            "system_worker":"""あなたは経済・勢力システムデザイナー「System Worker」です。

## タスク
経済システムと勢力を設計してください。

## 入力
{previous_outputs}

## 出力形式（JSON）
```json
{{
  "economy": {{
    "currency": {{"name": "通貨名", "acquisition_methods": []}},
    "resources": [
      {{"name": "資源名", "rarity": "common/rare/legendary", "uses": []}}
    ],
    "trade_system": {{"shops": [], "trading_rules": []}}
  }},
  "factions": [
    {{
      "id": "faction_id",
      "name": "勢力名",
      "type": "government/corporation/guild",
      "goals": [],
      "territory": [],
      "relationship_to_player": {{"initial": "neutral", "can_change": true}}
    }}
  ]
}}
```
""",




            "task_split_leader":"""あなたはプロジェクト管理チームのリーダー「TaskSplit Leader」です。
配下のWorkerを指揮してタスク分解とスケジュール作成を行うことが役割です。

## あなたの専門性
- プロジェクトマネージャーとして15年以上の経験
- アジャイル/スクラム開発の実践者
- 技術的な実装工数の見積もり能力

## 配下Worker
- AnalysisWorker: 要件分析・機能抽出
- DecompositionWorker: タスク分解・依存関係分析
- ScheduleWorker: イテレーション計画・スケジュール作成

## 入力情報
### プロジェクトコンセプト
{project_concept}

### 前の成果物
{previous_outputs}

## 出力形式（JSON）
```json
{{
  "worker_tasks": [],
  "project_plan": {{
    "project_summary": {{}},
    "iterations": [],
    "dependency_map": {{}},
    "risks": [],
    "milestones": []
  }},
  "statistics": {{}},
  "quality_checks": {{}},
  "human_review_required": []
}}
```
""",


            "analysis_worker":"""あなたは要件分析者「Analysis Worker」です。

## タスク
企画成果物から要件を分析し、機能を抽出してください。

## 入力
{previous_outputs}

## 出力形式（JSON）
```json
{{
  "requirements": [
    {{
      "id": "req_001",
      "type": "functional/non-functional",
      "description": "要件説明",
      "source": "コンセプト/デザイン/シナリオ",
      "priority": "must/should/could"
    }}
  ],
  "features": [
    {{
      "id": "feat_001",
      "name": "機能名",
      "description": "説明",
      "requirements": ["req_001"],
      "complexity": "high/medium/low"
    }}
  ]
}}
```
""",

            "decomposition_worker":"""あなたはタスク分解スペシャリスト「Decomposition Worker」です。

## タスク
機能をコードタスクとアセットタスクに分解してください。

## 入力
{previous_outputs}

## 出力形式（JSON）
```json
{{
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
      "specifications": {{"format": "PNG", "dimensions": "32x32"}},
      "priority": "critical/high/medium/low",
      "estimated_hours": 4
    }}
  ],
  "dependency_map": {{
    "code_to_code": [],
    "asset_to_code": [],
    "critical_path": []
  }}
}}
```
""",

            "schedule_worker":"""あなたはスケジュール計画者「Schedule Worker」です。

## タスク
イテレーション計画とマイルストーンを作成してください。

## 入力
{previous_outputs}

## 出力形式（JSON）
```json
{{
  "iterations": [
    {{
      "number": 1,
      "name": "基盤構築",
      "goal": "目標",
      "deliverables": ["成果物"],
      "estimated_days": 12,
      "code_task_ids": ["code_001"],
      "asset_task_ids": ["asset_001"],
      "completion_criteria": ["完了条件"]
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
  "risks": [
    {{
      "risk": "リスク内容",
      "impact": "high/medium/low",
      "probability": "high/medium/low",
      "mitigation": "軽減策"
    }}
  ]
}}
```
""",




            "code_leader":"""あなたはゲーム開発チームのコードリーダー「Code Leader」です。
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




            "asset_leader":"""あなたはゲーム開発チームのアセットリーダー「Asset Leader」です。
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




            "integrator_leader":"""あなたは統合チームのリーダー「Integrator Leader」です。
配下のWorkerを指揮して成果物の統合とビルドを行うことが役割です。

## あなたの専門性
- DevOpsリードとして12年以上の経験
- CI/CDパイプラインの設計・構築・運用
- ビルドシステムの深い知識

## 配下Worker
- DependencyWorker: 依存関係解決・パッケージ管理
- BuildWorker: ビルド実行・バンドル生成
- IntegrationValidationWorker: 起動テスト・基本動作確認

## 入力情報
### プロジェクトコンセプト
{project_concept}

### 前の成果物
{previous_outputs}

## 出力形式（JSON）
```json
{{
  "worker_tasks": [],
  "build_report": {{
    "build_summary": {{}},
    "integrated_files": {{}},
    "dependency_resolution": {{}},
    "build_checks": {{}},
    "startup_checks": {{}}
  }},
  "build_artifacts": {{}},
  "issues": [],
  "quality_checks": {{}},
  "human_review_required": []
}}
```
""",


            "dependency_worker":"""あなたは依存関係管理者「Dependency Worker」です。

## タスク
依存関係の解決とパッケージ管理を行ってください。

## 入力
{previous_outputs}

## 出力形式（JSON）
```json
{{
  "dependency_resolution": {{
    "npm_packages": {{
      "installed": 24,
      "resolved": ["phaser@3.70.0"],
      "warnings": []
    }},
    "local_modules": {{"resolved": [], "unresolved": []}},
    "asset_references": {{"resolved": [], "unresolved": []}}
  }},
  "issues": []
}}
```
""",

            "build_worker":"""あなたはビルドエンジニア「Build Worker」です。

## タスク
ビルドの実行とバンドル生成を行ってください。

## 入力
{previous_outputs}

## 出力形式（JSON）
```json
{{
  "build_summary": {{
    "status": "success/failed/partial",
    "build_id": "build_id",
    "duration_seconds": 45,
    "output_dir": "dist/"
  }},
  "integrated_files": {{
    "code": [{{"source_path": "", "output_path": "", "size_kb": 0, "minified": true}}],
    "assets": [{{"source_path": "", "output_path": "", "size_kb": 0, "optimized": true}}]
  }},
  "build_checks": {{
    "typescript_compilation": {{"status": "passed", "errors": []}},
    "asset_validation": {{"status": "passed", "missing_assets": []}},
    "bundle_analysis": {{"total_size_kb": 0, "code_size_kb": 0, "asset_size_kb": 0}}
  }}
}}
```
""",

            "integration_validation_worker":"""あなたは統合検証者「IntegrationValidation Worker」です。

## タスク
起動テストと基本動作確認を行ってください。

## 入力
{previous_outputs}

## 出力形式（JSON）
```json
{{
  "startup_checks": {{
    "compilation": "passed/failed",
    "asset_loading": "passed/failed/partial",
    "startup": "passed/failed",
    "initial_render": "passed/failed",
    "console_errors": []
  }},
  "issues": [
    {{"severity": "error/warning", "category": "code/asset", "message": "", "suggestion": ""}}
  ]
}}
```
""",




            "tester_leader":"""あなたはテストチームのリーダー「Tester Leader」です。
配下のWorkerを指揮して包括的なテストを実行することが役割です。

## あなたの専門性
- QAリードとして10年以上の経験
- テスト戦略の設計・実装
- 品質メトリクスの分析・改善

## 配下Worker
- UnitTestWorker: ユニットテスト実行
- IntegrationTestWorker: 統合テスト実行
- E2ETestWorker: E2Eシナリオテスト実行
- PerformanceTestWorker: パフォーマンス・負荷テスト

## 入力情報
### プロジェクトコンセプト
{project_concept}

### 前の成果物
{previous_outputs}

## 出力形式（JSON）
```json
{{
  "worker_tasks": [],
  "test_report": {{
    "summary": {{}},
    "unit_test_results": {{}},
    "integration_test_results": {{}},
    "e2e_test_results": {{}},
    "performance_results": {{}}
  }},
  "bug_reports": [],
  "quality_gates": [],
  "quality_checks": {{}},
  "human_review_required": []
}}
```
""",


            "unit_test_worker":"""あなたはユニットテストエンジニア「UnitTest Worker」です。

## タスク
ユニットテストを実行し、カバレッジを測定してください。

## 入力
{previous_outputs}

## 出力形式（JSON）
```json
{{
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
    "failed_tests": [
      {{"name": "テスト名", "error": "エラー内容", "file": "ファイル"}}
    ],
    "uncovered_files": []
  }}
}}
```
""",

            "integration_test_worker":"""あなたは統合テストエンジニア「IntegrationTest Worker」です。

## タスク
統合テストを実行してください。

## 入力
{previous_outputs}

## 出力形式（JSON）
```json
{{
  "integration_test_results": {{
    "total": 20,
    "passed": 20,
    "failed": 0,
    "results": [
      {{"name": "テスト名", "status": "passed/failed", "duration_ms": 100}}
    ]
  }}
}}
```
""",

            "e2e_test_worker":"""あなたはE2Eテストエンジニア「E2ETest Worker」です。

## タスク
E2Eシナリオテストを実行してください。

## 入力
{previous_outputs}

## 出力形式（JSON）
```json
{{
  "e2e_test_results": {{
    "total": 15,
    "passed": 14,
    "failed": 1,
    "scenarios": [
      {{
        "name": "シナリオ名",
        "steps": ["ステップ"],
        "status": "passed/failed",
        "screenshot": "path/to/screenshot.png"
      }}
    ]
  }}
}}
```
""",

            "performance_test_worker":"""あなたはパフォーマンステストエンジニア「PerformanceTest Worker」です。

## タスク
パフォーマンステストと負荷テストを実行してください。

## 入力
{previous_outputs}

## 出力形式（JSON）
```json
{{
  "performance_results": {{
    "fps": {{"average": 58.5, "min": 42, "max": 62, "status": "passed/warning/failed"}},
    "load_time": {{"initial_load_ms": 2800, "status": "passed/warning/failed"}},
    "memory": {{"initial_mb": 45, "peak_mb": 128, "leak_detected": false, "status": "passed/warning/failed"}}
  }},
  "bottlenecks": [
    {{"location": "場所", "issue": "問題", "recommendation": "推奨対応"}}
  ]
}}
```
""",




            "reviewer_leader":"""あなたはレビューチームのリーダー「Reviewer Leader」です。
配下のWorkerを指揮して総合的なレビューを行いリリース判定することが役割です。

## あなたの専門性
- シニアレビューアとして15年以上の経験
- コードレビュー、アーキテクチャ評価のエキスパート
- 品質保証プロセスの設計・運用

## 配下Worker
- CodeReviewWorker: コード品質レビュー
- AssetReviewWorker: アセット品質レビュー
- GameplayReviewWorker: ゲームプレイ・UXレビュー
- ComplianceWorker: 仕様整合性チェック

## 入力情報
### プロジェクトコンセプト
{project_concept}

### 前の成果物
{previous_outputs}

## 出力形式（JSON）
```json
{{
  "worker_tasks": [],
  "review_report": {{
    "summary": {{}},
    "code_review": {{}},
    "asset_review": {{}},
    "gameplay_review": {{}},
    "specification_compliance": {{}}
  }},
  "release_decision": {{}},
  "risk_assessment": {{}},
  "improvement_suggestions": {{}},
  "quality_checks": {{}},
  "human_review_required": []
}}
```
""",


            "code_review_worker":"""あなたはコードレビューア「CodeReview Worker」です。

## タスク
コード品質をレビューしてください。

## 入力
{previous_outputs}

## 出力形式（JSON）
```json
{{
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
    "issues": [
      {{"file": "ファイル", "line": 10, "severity": "high/medium/low", "message": "問題"}}
    ],
    "tech_debt": [
      {{"location": "場所", "description": "説明", "priority": "high/medium/low"}}
    ]
  }}
}}
```
""",

            "asset_review_worker":"""あなたはアセットレビューア「AssetReview Worker」です。

## タスク
アセット品質をレビューしてください。

## 入力
{previous_outputs}

## 出力形式（JSON）
```json
{{
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
  }}
}}
```
""",

            "gameplay_review_worker":"""あなたはゲームプレイレビューア「GameplayReview Worker」です。

## タスク
ゲームプレイとUXをレビューしてください。

## 入力
{previous_outputs}

## 出力形式（JSON）
```json
{{
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
      "features_vs_spec": {{"specified": 15, "implemented": 14, "missing": []}}
    }}
  }}
}}
```
""",

            "compliance_worker":"""あなたは仕様整合性チェッカー「Compliance Worker」です。

## タスク
仕様との整合性をチェックしてください。

## 入力
{previous_outputs}

## 出力形式（JSON）
```json
{{
  "specification_compliance": {{
    "overall_compliance": 93,
    "feature_checklist": [
      {{"feature": "機能名", "status": "complete/partial/missing", "notes": "メモ"}}
    ],
    "deviations": [
      {{"spec": "仕様", "implementation": "実装", "severity": "high/medium/low"}}
    ]
  }},
  "risk_assessment": {{
    "overall_risk": "low/medium/high/critical",
    "technical_risks": [],
    "release_blockers": []
  }}
}}
```
""",
        }

    def _default_prompt(self)->str:
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


@dataclass
class QualityCheckResult:
    passed:bool
    issues:List[str] = field(default_factory=list)
    score:float = 1.0
    retry_needed:bool = False
    human_review_needed:bool = False


@dataclass
class WorkerTaskResult:
    worker_type:str
    status:str
    output:Dict[str,Any] = field(default_factory=dict)
    quality_check:Optional[QualityCheckResult] = None
    retries:int = 0
    error:Optional[str] = None


class LeaderWorkerOrchestrator:
    """Leaderの分析結果に基づいてWorkerを実行し、品質チェックに応じてリトライやHuman Review要求を行う"""

    def __init__(
        self,
        agent_runner:ApiAgentRunner,
        quality_settings:Dict[str,Any],
        on_progress:Optional[Callable[[str,int,str],None]] = None,
        on_checkpoint:Optional[Callable[[str,Dict],None]] = None,
    ):
        self.agent_runner = agent_runner
        self.quality_settings = quality_settings
        self.on_progress = on_progress
        self.on_checkpoint = on_checkpoint

    async def run_leader_with_workers(self,leader_context:AgentContext)->Dict[str,Any]:
        results = {
            "leader_output":{},
            "worker_results":[],
            "final_output":{},
            "checkpoint":None,
            "human_review_required":[],
        }


        self._emit_progress(leader_context.agent_type.value,10,"Leader分析開始")

        leader_output = await self.agent_runner.run_agent(leader_context)
        results["leader_output"] = leader_output.output

        if leader_output.status == AgentStatus.FAILED:
            return results


        worker_tasks = self._extract_worker_tasks(leader_output.output)

        self._emit_progress(leader_context.agent_type.value,30,f"Worker実行開始 ({len(worker_tasks)}タスク)")


        total_workers = len(worker_tasks)
        for i,worker_task in enumerate(worker_tasks):
            worker_type = worker_task.get("worker","")
            task_description = worker_task.get("task","")

            progress = 30 + int((i / total_workers) * 50)
            self._emit_progress(leader_context.agent_type.value,progress,f"{worker_type} 実行中: {task_description}")


            qc_config = self.quality_settings.get(worker_type,{})
            qc_enabled = qc_config.get("enabled",True)
            max_retries = qc_config.get("maxRetries",3)


            worker_result = await self._execute_worker(
                leader_context=leader_context,
                worker_type=worker_type,
                task=task_description,
                quality_check_enabled=qc_enabled,
                max_retries=max_retries,
            )

            results["worker_results"].append(worker_result.__dict__)


            if worker_result.status == "needs_human_review":
                results["human_review_required"].append({
                    "worker_type":worker_type,
                    "task":task_description,
                    "issues":worker_result.quality_check.issues if worker_result.quality_check else [],
                })


        self._emit_progress(leader_context.agent_type.value,85,"Leader統合中")

        final_output = await self._integrate_outputs(
            leader_context=leader_context,
            leader_output=leader_output.output,
            worker_results=results["worker_results"],
        )
        results["final_output"] = final_output


        self._emit_progress(leader_context.agent_type.value,95,"承認生成")

        checkpoint_data = {
            "type":f"{leader_context.agent_type.value}_review",
            "title":f"{leader_context.agent_type.value} 成果物レビュー",
            "output":final_output,
            "worker_summary":{
                "total":total_workers,
                "completed":sum(1 for r in results["worker_results"] if r["status"] == "completed"),
                "failed":sum(1 for r in results["worker_results"] if r["status"] == "failed"),
                "needs_review":len(results["human_review_required"]),
            },
            "human_review_required":results["human_review_required"],
        }
        results["checkpoint"] = checkpoint_data

        if self.on_checkpoint:
            self.on_checkpoint(checkpoint_data["type"],checkpoint_data)

        self._emit_progress(leader_context.agent_type.value,100,"完了")

        return results

    async def _execute_worker(
        self,
        leader_context:AgentContext,
        worker_type:str,
        task:str,
        quality_check_enabled:bool,
        max_retries:int,
    )->WorkerTaskResult:
        """
        Workerを実行（品質チェック有無で分岐）
        """
        result = WorkerTaskResult(worker_type=worker_type)

        try:

            try:
                agent_type = AgentType(worker_type)
            except ValueError:
                result.status = "failed"
                result.error = f"Unknown worker type: {worker_type}"
                return result

            worker_context = AgentContext(
                project_id=leader_context.project_id,
                agent_id=f"{leader_context.agent_id}-{worker_type}",
                agent_type=agent_type,
                project_concept=leader_context.project_concept,
                previous_outputs=leader_context.previous_outputs,
                config=leader_context.config,
            )

            if quality_check_enabled:
                result = await self._run_with_quality_check(
                    worker_context=worker_context,
                    worker_type=worker_type,
                    max_retries=max_retries,
                )
            else:
                output = await self.agent_runner.run_agent(worker_context)
                result.status = "completed" if output.status == AgentStatus.COMPLETED else "failed"
                result.output = output.output
                if output.error:
                    result.error = output.error

        except Exception as e:
            result.status = "failed"
            result.error = str(e)

        return result

    async def _run_with_quality_check(
        self,
        worker_context:AgentContext,
        worker_type:str,
        max_retries:int = 3,
    )->WorkerTaskResult:
        """失敗時は最大max_retries回リトライ、それでも失敗ならHuman Review要求"""
        result = WorkerTaskResult(worker_type=worker_type)

        for retry in range(max_retries):
            result.retries = retry
            output = await self.agent_runner.run_agent(worker_context)

            if output.status == AgentStatus.FAILED:
                result.error = output.error
                continue

            result.output = output.output
            qc_result = self._perform_quality_check(output.output,worker_type)
            result.quality_check = qc_result

            if qc_result.passed:
                result.status = "completed"
                return result

            if retry < max_retries - 1:
                result.status = "needs_retry"
                worker_context.previous_outputs[f"{worker_type}_previous_attempt"] = {
                    "output":output.output,
                    "issues":qc_result.issues,
                }
            else:
                result.status = "needs_human_review"
                result.quality_check.human_review_needed = True
                return result

        return result

    def _perform_quality_check(self,output:Dict[str,Any],worker_type:str)->QualityCheckResult:
        """簡易的なルールベースチェック（本番ではLLMで品質評価）"""
        issues = []
        score = 1.0
        content = output.get("content","")

        if not content or len(str(content)) < 50:
            issues.append("出力内容が不十分です")
            score -= 0.3

        if "```json" in str(content):
            import json
            import re
            json_match = re.search(r'```json\s*([\s\S]*?)\s*```',str(content))
            if json_match:
                try:
                    json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    issues.append("JSON形式が不正です")
                    score -= 0.2

        passed = score >= 0.7 and len(issues) == 0

        return QualityCheckResult(
            passed=passed,
            issues=issues,
            score=score,
            retry_needed=not passed,
        )

    def _extract_worker_tasks(self,leader_output:Dict[str,Any])->List[Dict[str,Any]]:
        content = leader_output.get("content","")
        import json
        import re

        json_match = re.search(r'```json\s*([\s\S]*?)\s*```',str(content))
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                return data.get("worker_tasks",[])
            except json.JSONDecodeError:
                pass

        if isinstance(leader_output,dict) and "worker_tasks" in leader_output:
            return leader_output.get("worker_tasks",[])

        return []

    async def _integrate_outputs(
        self,
        leader_context:AgentContext,
        leader_output:Dict[str,Any],
        worker_results:List[Dict[str,Any]],
    )->Dict[str,Any]:
        """Worker結果をマージ（本番ではLeaderに再度LLM呼び出しで統合）"""
        integrated = {
            "type":"document",
            "format":"markdown",
            "leader_summary":leader_output,
            "worker_outputs":{},
            "metadata":{
                "agent_type":leader_context.agent_type.value,
                "worker_count":len(worker_results),
                "completed_count":sum(1 for r in worker_results if r.get("status") == "completed"),
            }
        }

        for result in worker_results:
            worker_type = result.get("worker_type","unknown")
            integrated["worker_outputs"][worker_type] = {
                "status":result.get("status"),
                "output":result.get("output",{}),
            }

        return integrated

    def _emit_progress(self,agent_type:str,progress:int,message:str):
        if self.on_progress:
            self.on_progress(agent_type,progress,message)
