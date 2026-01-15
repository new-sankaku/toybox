"""
Planner Agent - Game planning and specification creation.
"""

import json
from typing import Dict, Any
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from ..core.state import GameState, GameSpec, GameArchitecture, Task, DevelopmentPhase
from ..core.llm import get_llm_for_agent, get_app_language, track_llm_call
from ..utils.logger import get_logger
from ..dashboard.tracker import tracker

logger = get_logger()


class PlannerAgent:
    """
    Planner Agent creates game specifications and task breakdowns.

    Responsibilities:
    - Analyze user request
    - Define game mechanics
    - Create asset requirements
    - Break down into tasks
    """

    def __init__(self):
        """Initialize the Planner Agent."""
        self.llm = get_llm_for_agent("planner")
        self.parser = JsonOutputParser()

    def run(self, state: GameState) -> Dict[str, Any]:
        """
        Execute planning phase.

        Args:
            state: Current game state

        Returns:
            Dictionary with game_spec, architecture, and tasks
        """
        user_request = state["user_request"]
        development_phase = state["development_phase"]

        # Notify dashboard
        tracker.agent_start("planner", "ゲーム企画を分析中...")

        logger.info(f"分析中: {user_request}")
        logger.debug(f"フェーズ: {development_phase}")

        prompt = self._create_prompt(development_phase)

        # Format prompt for logging
        prompt_text = prompt.format(
            user_request=user_request,
            development_phase=development_phase
        )

        try:
            # Call LLM with token tracking
            response = self.llm.invoke(prompt_text)
            response_text = response.content if hasattr(response, 'content') else str(response)

            # Estimate tokens (rough approximation)
            input_tokens = len(prompt_text) // 4
            output_tokens = len(response_text) // 4

            # Track LLM interaction
            track_llm_call(
                agent_name="planner",
                prompt=prompt_text,
                response=response_text,
                input_tokens=input_tokens,
                output_tokens=output_tokens
            )

            # Also send to tracker for UI
            tracker.add_llm_interaction({
                "agent": "planner",
                "prompt": prompt_text[:500] + "..." if len(prompt_text) > 500 else prompt_text,
                "response": response_text[:1000] + "..." if len(response_text) > 1000 else response_text,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_input": input_tokens,
                "total_output": output_tokens
            })

            # Parse response
            logger.debug(f"LLMレスポンス: {response_text[:500]}...")
            result = self.parser.parse(response_text)

            game_spec = self._parse_game_spec(result.get("game_spec", {}))
            architecture = self._parse_architecture(result.get("architecture", {}), game_spec)
            tasks = self._parse_tasks(result.get("tasks", []))
            task_phases = result.get("task_phases", [])
            asset_categories = result.get("asset_categories", {})

            # Send to dashboard
            tracker.set_game_spec(game_spec)
            tracker.set_architecture(architecture)
            tracker.set_tasks(tasks)

            if task_phases:
                tracker.set_task_phases(task_phases)
            if asset_categories:
                tracker.set_asset_categories(asset_categories)

            tracker.agent_complete("planner", f"企画完了: {game_spec.get('title')}", {
                "game_spec": game_spec,
                "architecture": architecture,
                "task_count": len(tasks)
            })

            logger.info(f"仕様作成完了: {game_spec.get('title')} ({game_spec.get('genre')})")
            logger.info(f"タスク数: {len(tasks)}")

            return {
                "game_spec": game_spec,
                "architecture": architecture,
                "tasks": tasks
            }

        except Exception as e:
            import traceback
            logger.error(f"計画失敗: {e}")
            logger.error(f"詳細: {traceback.format_exc()}")
            tracker.agent_error("planner", f"計画失敗: {str(e)}")
            raise RuntimeError(f"計画フェーズでエラーが発生しました: {e}") from e

    def _create_prompt(self, development_phase: DevelopmentPhase) -> ChatPromptTemplate:
        """Create planning prompt based on development phase."""
        lang = get_app_language()

        if lang == "ja":
            return self._create_prompt_ja(development_phase)
        else:
            return self._create_prompt_en(development_phase)

    def _create_prompt_ja(self, development_phase: DevelopmentPhase) -> ChatPromptTemplate:
        """Create Japanese planning prompt."""
        phase_instructions = {
            DevelopmentPhase.MOCK: """
これはMOCKフェーズです - 最速の実装を目指します:
- プレースホルダーアセットを使用（色付き矩形、システムサウンド）
- ハードコードされた値を使った最小限のコード
- 目標: 数分で動くものを作る
""",
            DevelopmentPhase.GENERATE: """
これはGENERATEフェーズです - 実際のアセットを使用:
- フリーアセットを検索するかAIで生成
- 基本的なゲームメカニクスを実装
- 本物のゲームのような見た目と操作感
""",
            DevelopmentPhase.POLISH: """
これはPOLISHフェーズです - 品質を向上:
- 画像のアップスケール、音声の処理
- コードのリファクタリング、エラー処理の追加
- ゲームフィールとポリッシュの改善
""",
            DevelopmentPhase.FINAL: """
これはFINALフェーズです - 製品品質:
- 高解像度アセット
- 最適化された、ドキュメント付きのコード
- 完全なテストとエッジケースの処理
"""
        }

        template = f"""あなたはゲームデザイナーAIです。ユーザーのリクエストに基づいて詳細なゲーム仕様とアーキテクチャを作成してください。

{phase_instructions.get(development_phase, "")}

ユーザーリクエスト: {{user_request}}
開発フェーズ: {{development_phase}}

リクエストを分析し、以下の構造でゲーム仕様を作成してください:

{{{{
  "game_spec": {{{{
    "title": "ゲームタイトル",
    "genre": "ジャンル（例: プラットフォーマー、シューター、パズル）",
    "description": "ゲームの簡単な説明",
    "mechanics": ["メカニクス1", "メカニクス2"],
    "visual_style": "ビジュアルスタイルの説明",
    "audio_style": "オーディオスタイルの説明",
    "target_platform": "pygame または pyxel または html5"
  }}}},
  "architecture": {{{{
    "genre": "ジャンル（具体的に）",
    "target": "ターゲット層（例: カジュアルゲーマー）",
    "platform": "プラットフォーム（例: Web/HTML5）",
    "theme": "世界観・テーマ（例: ファンタジー冒険）",
    "coreFun": "コアの面白さ（例: 精密ジャンプアクション）",
    "rules": "ルール・勝敗条件（例: ゴール到達でクリア）",
    "controls": "操作方法（例: 矢印キー移動、スペースジャンプ）",
    "flow": "進行フロー（例: ステージ選択→プレイ→リザルト）",
    "difficulty": "難易度設計（例: 序盤易しく後半難しく）",
    "reward": "報酬・成長システム（例: コイン収集でアンロック）",
    "scenario": "シナリオ概要（例: 姫を救出）",
    "characters": "キャラクター設定（例: 勇者、敵モンスター）",
    "world": "世界設定（例: 中世ファンタジー王国）",
    "art": "アートスタイル（例: ピクセルアート16x16）",
    "ui": "UI方針（例: シンプル、大きなボタン）",
    "audio": "BGM・効果音方針（例: チップチューン）",
    "engine": "エンジン・開発環境（例: Pygame 2.x）",
    "resolution": "解像度・FPS（例: 800x600, 60fps）",
    "data": "データ・セーブ仕様（例: ローカルJSON）",
    "network": "通信仕様（例: オフライン専用）",
    "stages": "ステージ・マップ構成（例: 5ステージ）",
    "placement": "敵・アイテム配置（例: 各ステージ3敵）",
    "tutorial": "チュートリアル設計（例: ステージ1で操作説明）",
    "monetize": "マネタイズ方針（例: 無料）",
    "updates": "アップデート計画（例: 追加ステージ）",
    "support": "サポート体制（例: GitHub Issues）",
    "schedule": "開発期間（例: 2週間）",
    "budget": "人員・予算（例: 個人開発）",
    "outsource": "外注範囲（例: なし）"
  }}}},
  "tasks": [
    {{{{
      "id": "task_001",
      "type": "code",
      "description": "タスクの説明（日本語で）",
      "assigned_agent": "coder",
      "status": "pending",
      "dependencies": []
    }}}}
  ]
}}}}

ガイドライン:
1. シンプルで達成可能なものにする
2. MOCKフェーズではアセット要件を最小限に
3. 適切なプラットフォームを選択（複雑なゲームはpygame、レトロゲームはpyxel）
4. 論理的で順次的なタスクに分解
5. アーキテクチャの29項目すべてに具体的な値を設定

JSONのみを返してください。追加のテキストは不要です。"""

        return ChatPromptTemplate.from_template(template)

    def _create_prompt_en(self, development_phase: DevelopmentPhase) -> ChatPromptTemplate:
        """Create English planning prompt."""
        phase_instructions = {
            DevelopmentPhase.MOCK: """
This is MOCK phase - focus on fastest implementation:
- Use placeholder assets (colored rectangles, system sounds)
- Minimal code with hardcoded values
- Goal: Get something running in minutes
""",
            DevelopmentPhase.GENERATE: """
This is GENERATE phase - use real assets:
- Search for free assets or generate with AI
- Implement basic game mechanics
- Make it look and feel like a real game
""",
            DevelopmentPhase.POLISH: """
This is POLISH phase - improve quality:
- Upscale images, process audio
- Refactor code, add error handling
- Improve game feel and polish
""",
            DevelopmentPhase.FINAL: """
This is FINAL phase - production quality:
- High-resolution assets
- Optimized, well-documented code
- Complete testing and edge case handling
"""
        }

        template = f"""You are a game designer AI. Create a detailed game specification based on the user's request.

{phase_instructions.get(development_phase, "")}

User Request: {{user_request}}
Development Phase: {{development_phase}}

Analyze the request and create a game specification with the following structure:

{{{{
  "game_spec": {{{{
    "title": "Game title",
    "genre": "Genre (e.g., platformer, shooter, puzzle)",
    "description": "Brief description of the game",
    "mechanics": ["mechanic1", "mechanic2", "..."],
    "visual_style": "Visual style description",
    "audio_style": "Audio style description",
    "target_platform": "pygame or pyxel or html5"
  }}}},
  "tasks": [
    {{{{
      "id": "task_001",
      "type": "code",
      "description": "Task description",
      "assigned_agent": "coder",
      "status": "pending",
      "dependencies": []
    }}}},
    ...
  ]
}}}}

Guidelines:
1. Keep it simple and achievable
2. For MOCK phase, minimize asset requirements
3. Choose appropriate platform (pygame for complex games, pyxel for retro games)
4. Break down into logical, sequential tasks
5. Identify parallel tasks (independent asset generation)

Return ONLY the JSON, no additional text."""

        return ChatPromptTemplate.from_template(template)

    def _parse_game_spec(self, spec_data: Dict[str, Any]) -> GameSpec:
        """Parse game specification from LLM output."""
        return GameSpec(
            title=spec_data.get("title", "Untitled Game"),
            genre=spec_data.get("genre", "casual"),
            description=spec_data.get("description", ""),
            mechanics=spec_data.get("mechanics", []),
            visual_style=spec_data.get("visual_style", "simple"),
            audio_style=spec_data.get("audio_style", "minimal"),
            target_platform=spec_data.get("target_platform", "pygame")
        )

    def _parse_architecture(self, arch_data: Dict[str, Any], game_spec: GameSpec) -> GameArchitecture:
        """Parse game architecture from LLM output, with fallbacks from game_spec."""
        return GameArchitecture(
            # 基本コンセプト
            genre=arch_data.get("genre", game_spec.get("genre", "-")),
            target=arch_data.get("target", "-"),
            platform=arch_data.get("platform", game_spec.get("target_platform", "-")),
            theme=arch_data.get("theme", game_spec.get("description", "-")),
            coreFun=arch_data.get("coreFun", "-"),
            # ゲームメカニクス
            rules=arch_data.get("rules", "-"),
            controls=arch_data.get("controls", "-"),
            flow=arch_data.get("flow", "-"),
            difficulty=arch_data.get("difficulty", "-"),
            reward=arch_data.get("reward", "-"),
            # ストーリー・キャラクター
            scenario=arch_data.get("scenario", "-"),
            characters=arch_data.get("characters", "-"),
            world=arch_data.get("world", "-"),
            # ビジュアル・オーディオ
            art=arch_data.get("art", game_spec.get("visual_style", "-")),
            ui=arch_data.get("ui", "-"),
            audio=arch_data.get("audio", game_spec.get("audio_style", "-")),
            # 技術仕様
            engine=arch_data.get("engine", "-"),
            resolution=arch_data.get("resolution", "-"),
            data=arch_data.get("data", "-"),
            network=arch_data.get("network", "-"),
            # レベルデザイン
            stages=arch_data.get("stages", "-"),
            placement=arch_data.get("placement", "-"),
            tutorial=arch_data.get("tutorial", "-"),
            # 収益・運営
            monetize=arch_data.get("monetize", "-"),
            updates=arch_data.get("updates", "-"),
            support=arch_data.get("support", "-"),
            # スケジュール・リソース
            schedule=arch_data.get("schedule", "-"),
            budget=arch_data.get("budget", "-"),
            outsource=arch_data.get("outsource", "-")
        )

    def _parse_tasks(self, tasks_data: list) -> list[Task]:
        """Parse task list from LLM output."""
        tasks = []
        for i, task_data in enumerate(tasks_data):
            task = Task(
                id=task_data.get("id", f"task_{i:03d}"),
                type=task_data.get("type", "code"),
                description=task_data.get("description", ""),
                assigned_agent=task_data.get("assigned_agent", "coder"),
                status=task_data.get("status", "pending"),
                dependencies=task_data.get("dependencies", [])
            )
            tasks.append(task)
        return tasks
