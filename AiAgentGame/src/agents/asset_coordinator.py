"""
Asset Coordinator Agent - Coordinates asset generation.
"""

from typing import Dict, Any
from pathlib import Path

from ..core.state import GameState, DevelopmentPhase
from ..utils.logger import get_logger

logger = get_logger()


class AssetCoordinatorAgent:
    """
    Asset Coordinator delegates asset generation to specialized agents.

    Responsibilities:
    - Analyze asset requirements
    - Delegate to Visual/Audio/UI agents
    - Coordinate parallel generation
    - Track attribution information
    """

    def __init__(self):
        """Initialize the Asset Coordinator Agent."""
        self.output_dir = Path("output")

    def run(self, state: GameState) -> Dict[str, Any]:
        """
        Execute asset coordination phase.

        Args:
            state: Current game state

        Returns:
            Dictionary with artifacts
        """
        game_spec = state.get("game_spec", {})
        development_phase = state["development_phase"]

        logger.info(f"アセット調整中 (フェーズ: {development_phase})")

        artifacts = {}

        from .visual_agent import VisualAgent
        from .audio_agent import AudioAgent
        from .ui_agent import UIAgent

        if game_spec.get("visual_style"):
            logger.debug("ビジュアルアセット生成中")
            visual_agent = VisualAgent()
            visual_artifacts = visual_agent.generate(game_spec, development_phase)
            artifacts.update(visual_artifacts)

        if game_spec.get("audio_style"):
            logger.debug("オーディオアセット生成中")
            audio_agent = AudioAgent()
            audio_artifacts = audio_agent.generate(game_spec, development_phase)
            artifacts.update(audio_artifacts)

        logger.debug("UIアセット生成中")
        ui_agent = UIAgent()
        ui_artifacts = ui_agent.generate(game_spec, development_phase)
        artifacts.update(ui_artifacts)

        logger.info(f"アセット生成完了: {len(artifacts)}件")

        return {"artifacts": artifacts}
