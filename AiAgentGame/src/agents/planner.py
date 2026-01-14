"""
Planner Agent - Game planning and specification creation.
"""

import json
from typing import Dict, Any
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from ..core.state import GameState, GameSpec, Task, DevelopmentPhase
from ..core.llm import get_llm_for_agent


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
            Dictionary with game_spec and tasks
        """
        user_request = state["user_request"]
        development_phase = state["development_phase"]

        print(f"📋 Analyzing request: {user_request}")
        print(f"🔧 Development phase: {development_phase}")

        # Create prompt based on development phase
        prompt = self._create_prompt(development_phase)

        # Generate game specification
        chain = prompt | self.llm | self.parser

        try:
            result = chain.invoke({
                "user_request": user_request,
                "development_phase": development_phase
            })

            game_spec = self._parse_game_spec(result.get("game_spec", {}))
            tasks = self._parse_tasks(result.get("tasks", []))

            print(f"\n✅ Game specification created:")
            print(f"   Title: {game_spec.get('title')}")
            print(f"   Genre: {game_spec.get('genre')}")
            print(f"   Platform: {game_spec.get('target_platform')}")
            print(f"   Tasks: {len(tasks)}")

            return {
                "game_spec": game_spec,
                "tasks": tasks
            }

        except Exception as e:
            print(f"❌ Error in planning: {e}")
            # Return minimal spec on error
            return {
                "game_spec": self._create_fallback_spec(user_request),
                "tasks": []
            }

    def _create_prompt(self, development_phase: DevelopmentPhase) -> ChatPromptTemplate:
        """Create planning prompt based on development phase."""

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

{{
  "game_spec": {{
    "title": "Game title",
    "genre": "Genre (e.g., platformer, shooter, puzzle)",
    "description": "Brief description of the game",
    "mechanics": ["mechanic1", "mechanic2", "..."],
    "visual_style": "Visual style description",
    "audio_style": "Audio style description",
    "target_platform": "pygame or pyxel or html5"
  }},
  "tasks": [
    {{
      "id": "task_001",
      "type": "code",
      "description": "Task description",
      "assigned_agent": "coder",
      "status": "pending",
      "dependencies": []
    }},
    ...
  ]
}}

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

    def _create_fallback_spec(self, user_request: str) -> GameSpec:
        """Create a minimal fallback specification."""
        return GameSpec(
            title="Simple Game",
            genre="casual",
            description=user_request,
            mechanics=["basic_movement"],
            visual_style="simple",
            audio_style="minimal",
            target_platform="pygame"
        )
