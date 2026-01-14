"""
Visual Agent - Visual asset generation.
"""

from pathlib import Path
from typing import Dict, Any
from PIL import Image, ImageDraw, ImageFont

from ..core.state import DevelopmentPhase, Artifact, ArtifactStatus
from ..tools import AttributionManager
from ..utils.logger import get_logger

logger = get_logger()


class VisualAgent:
    """Visual Agent generates visual assets (images, sprites, etc.)."""

    def __init__(self):
        """Initialize the Visual Agent."""
        self.output_dir = Path("output/images")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        (self.output_dir / "characters").mkdir(exist_ok=True)
        (self.output_dir / "backgrounds").mkdir(exist_ok=True)
        (self.output_dir / "effects").mkdir(exist_ok=True)
        (self.output_dir / "mock").mkdir(exist_ok=True)

        self.attribution = AttributionManager()

    def generate(self, game_spec: Dict[str, Any], phase: DevelopmentPhase) -> Dict[str, Artifact]:
        """Generate visual assets based on game spec and phase."""
        artifacts = {}

        if phase == DevelopmentPhase.MOCK:
            artifacts.update(self._generate_mock_assets(game_spec))
        else:
            logger.debug("MOCKフェーズのみ実装済み")
            artifacts.update(self._generate_mock_assets(game_spec))

        return artifacts

    def _generate_mock_assets(self, game_spec: Dict[str, Any]) -> Dict[str, Artifact]:
        """Generate simple placeholder images for MOCK phase."""
        artifacts = {}

        player_path = self._create_colored_rectangle(
            "player", (50, 50), (0, 255, 0), "Player"
        )

        artifacts["visual_player"] = Artifact(
            id="visual_player",
            type="image",
            agent="visual_agent",
            file_path=str(player_path),
            status=ArtifactStatus.COMPLETED,
            feedback_history=[]
        )
        self.attribution.add_mock_attribution("visual_player", "image")

        mechanics = game_spec.get("mechanics", [])
        if any(word in str(mechanics).lower() for word in ["enemy", "enemies", "opponent"]):
            enemy_path = self._create_colored_rectangle(
                "enemy", (50, 50), (255, 0, 0), "Enemy"
            )

            artifacts["visual_enemy"] = Artifact(
                id="visual_enemy",
                type="image",
                agent="visual_agent",
                file_path=str(enemy_path),
                status=ArtifactStatus.COMPLETED,
                feedback_history=[]
            )
            self.attribution.add_mock_attribution("visual_enemy", "image")

        bg_path = self._create_background("background", (800, 600))

        artifacts["visual_background"] = Artifact(
            id="visual_background",
            type="image",
            agent="visual_agent",
            file_path=str(bg_path),
            status=ArtifactStatus.COMPLETED,
            feedback_history=[]
        )
        self.attribution.add_mock_attribution("visual_background", "image")

        logger.info(f"画像生成完了: {len(artifacts)}件")

        return artifacts

    def _create_colored_rectangle(
        self, name: str, size: tuple, color: tuple, label: str
    ) -> Path:
        """Create a simple colored rectangle with label."""
        img = Image.new('RGBA', size, color)
        draw = ImageDraw.Draw(img)

        try:
            font = ImageFont.load_default()
            if hasattr(draw, 'textbbox'):
                bbox = draw.textbbox((0, 0), label, font=font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
            else:
                text_width, text_height = draw.textsize(label, font=font)

            text_x = (size[0] - text_width) // 2
            text_y = (size[1] - text_height) // 2

            draw.text((text_x, text_y), label, fill=(0, 0, 0, 255), font=font)
        except:
            pass

        file_path = self.output_dir / "mock" / f"{name}.png"
        img.save(file_path)

        return file_path

    def _create_background(self, name: str, size: tuple) -> Path:
        """Create a simple gradient background."""
        img = Image.new('RGB', size, (50, 50, 150))

        draw = ImageDraw.Draw(img)
        for y in range(size[1]):
            brightness = int(50 + (y / size[1]) * 100)
            color = (brightness // 2, brightness // 2, brightness)
            draw.line([(0, y), (size[0], y)], fill=color)

        file_path = self.output_dir / "backgrounds" / f"{name}.png"
        img.save(file_path)

        return file_path
