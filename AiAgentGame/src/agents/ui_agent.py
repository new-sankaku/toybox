"""
UI Agent - UI asset generation.
"""

from pathlib import Path
from typing import Dict, Any
from PIL import Image, ImageDraw, ImageFont

from ..core.state import DevelopmentPhase, Artifact, ArtifactStatus
from ..tools import AttributionManager
from ..utils.logger import get_logger

logger = get_logger()


class UIAgent:
    """UI Agent generates UI assets (icons, buttons, etc.)."""

    def __init__(self):
        """Initialize the UI Agent."""
        self.output_dir = Path("output/ui")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        (self.output_dir / "icons").mkdir(exist_ok=True)
        (self.output_dir / "buttons").mkdir(exist_ok=True)
        (self.output_dir / "mock").mkdir(exist_ok=True)

        self.attribution = AttributionManager()

    def generate(self, game_spec: Dict[str, Any], phase: DevelopmentPhase) -> Dict[str, Artifact]:
        """Generate UI assets based on game spec and phase."""
        artifacts = {}

        if phase == DevelopmentPhase.MOCK:
            artifacts.update(self._generate_mock_assets(game_spec))
        else:
            logger.debug("MOCKフェーズのみ実装済み")
            artifacts.update(self._generate_mock_assets(game_spec))

        return artifacts

    def _generate_mock_assets(self, game_spec: Dict[str, Any]) -> Dict[str, Artifact]:
        """Generate simple placeholder UI elements for MOCK phase."""
        artifacts = {}

        button_path = self._create_button("play_button", "PLAY")

        artifacts["ui_play_button"] = Artifact(
            id="ui_play_button",
            type="ui",
            agent="ui_agent",
            file_path=str(button_path),
            status=ArtifactStatus.COMPLETED,
            feedback_history=[]
        )
        self.attribution.add_mock_attribution("ui_play_button", "ui")

        icon_path = self._create_icon("game_icon", game_spec.get("title", "Game")[0])

        artifacts["ui_game_icon"] = Artifact(
            id="ui_game_icon",
            type="ui",
            agent="ui_agent",
            file_path=str(icon_path),
            status=ArtifactStatus.COMPLETED,
            feedback_history=[]
        )
        self.attribution.add_mock_attribution("ui_game_icon", "ui")

        logger.info(f"UI生成完了: {len(artifacts)}件")

        return artifacts

    def _create_button(self, name: str, text: str) -> Path:
        """Create a simple button image."""
        img = Image.new('RGBA', (120, 40), (100, 100, 200, 255))
        draw = ImageDraw.Draw(img)

        draw.rectangle([(0, 0), (119, 39)], outline=(200, 200, 255, 255), width=2)

        try:
            font = ImageFont.load_default()
            if hasattr(draw, 'textbbox'):
                bbox = draw.textbbox((0, 0), text, font=font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
            else:
                text_width, text_height = draw.textsize(text, font=font)

            text_x = (120 - text_width) // 2
            text_y = (40 - text_height) // 2

            draw.text((text_x, text_y), text, fill=(255, 255, 255, 255), font=font)
        except:
            pass

        file_path = self.output_dir / "mock" / f"{name}.png"
        img.save(file_path)

        return file_path

    def _create_icon(self, name: str, letter: str) -> Path:
        """Create a simple icon with a letter."""
        img = Image.new('RGBA', (64, 64), (50, 150, 50, 255))
        draw = ImageDraw.Draw(img)

        draw.ellipse([(4, 4), (60, 60)], fill=(50, 150, 50, 255), outline=(100, 200, 100, 255), width=3)

        try:
            font = ImageFont.load_default()
            if hasattr(draw, 'textbbox'):
                bbox = draw.textbbox((0, 0), letter, font=font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
            else:
                text_width, text_height = draw.textsize(letter, font=font)

            text_x = (64 - text_width) // 2
            text_y = (64 - text_height) // 2

            draw.text((text_x, text_y), letter, fill=(255, 255, 255, 255), font=font)
        except:
            pass

        file_path = self.output_dir / "icons" / f"{name}.png"
        img.save(file_path)

        return file_path
