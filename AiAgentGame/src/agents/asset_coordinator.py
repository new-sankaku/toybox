"""
Asset Coordinator Agent - Coordinates asset generation.
"""

from typing import Dict, Any
from pathlib import Path

from ..core.state import GameState, DevelopmentPhase


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

        print(f"🎨 Coordinating asset generation")
        print(f"   Phase: {development_phase}")

        artifacts = {}

        # Import specialized agents
        from .visual_agent import VisualAgent
        from .audio_agent import AudioAgent
        from .ui_agent import UIAgent

        # Generate visual assets
        if game_spec.get("visual_style"):
            print("\n   🖼️  Generating visual assets...")
            visual_agent = VisualAgent()
            visual_artifacts = visual_agent.generate(game_spec, development_phase)
            artifacts.update(visual_artifacts)

        # Generate audio assets
        if game_spec.get("audio_style"):
            print("\n   🔊 Generating audio assets...")
            audio_agent = AudioAgent()
            audio_artifacts = audio_agent.generate(game_spec, development_phase)
            artifacts.update(audio_artifacts)

        # Generate UI assets
        print("\n   🎯 Generating UI assets...")
        ui_agent = UIAgent()
        ui_artifacts = ui_agent.generate(game_spec, development_phase)
        artifacts.update(ui_artifacts)

        print(f"\n✅ Generated {len(artifacts)} assets")

        return {"artifacts": artifacts}
