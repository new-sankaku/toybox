"""
Visual Agent - Visual asset generation.
"""

from pathlib import Path
from typing import Dict, Any
from PIL import Image, ImageDraw, ImageFont

from ..core.state import DevelopmentPhase, Artifact, ArtifactStatus
from ..tools import AttributionManager


class VisualAgent:
    """
    Visual Agent generates visual assets (images, sprites, etc.).

    For MOCK phase: Simple colored rectangles with labels
    For GENERATE phase: Would fetch free assets or generate with AI
    For POLISH phase: Would upscale and post-process
    For FINAL phase: Would generate high-quality versions
    """

    def __init__(self):
        """Initialize the Visual Agent."""
        self.output_dir = Path("output/images")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Create subdirectories
        (self.output_dir / "characters").mkdir(exist_ok=True)
        (self.output_dir / "backgrounds").mkdir(exist_ok=True)
        (self.output_dir / "effects").mkdir(exist_ok=True)
        (self.output_dir / "mock").mkdir(exist_ok=True)

        # Attribution manager
        self.attribution = AttributionManager()

    def generate(self, game_spec: Dict[str, Any], phase: DevelopmentPhase) -> Dict[str, Artifact]:
        """
        Generate visual assets based on game spec and phase.

        Args:
            game_spec: Game specification
            phase: Current development phase

        Returns:
            Dictionary of artifact ID to Artifact
        """
        artifacts = {}

        if phase == DevelopmentPhase.MOCK:
            # Generate simple placeholder images
            artifacts.update(self._generate_mock_assets(game_spec))
        else:
            # For other phases, still use mock for now (can be extended)
            print("   ℹ️  Note: Currently only MOCK phase is fully implemented")
            artifacts.update(self._generate_mock_assets(game_spec))

        return artifacts

    def _generate_mock_assets(self, game_spec: Dict[str, Any]) -> Dict[str, Artifact]:
        """Generate simple placeholder images for MOCK phase."""
        artifacts = {}

        # Generate player character
        player_path = self._create_colored_rectangle(
            "player",
            (50, 50),
            (0, 255, 0),  # Green
            "Player"
        )

        artifacts["visual_player"] = Artifact(
            id="visual_player",
            type="image",
            agent="visual_agent",
            file_path=str(player_path),
            status=ArtifactStatus.COMPLETED,
            feedback_history=[]
        )

        # Record attribution
        self.attribution.add_mock_attribution("visual_player", "image")

        # Generate enemy if game has enemies
        mechanics = game_spec.get("mechanics", [])
        if any(word in str(mechanics).lower() for word in ["enemy", "enemies", "opponent"]):
            enemy_path = self._create_colored_rectangle(
                "enemy",
                (50, 50),
                (255, 0, 0),  # Red
                "Enemy"
            )

            artifacts["visual_enemy"] = Artifact(
                id="visual_enemy",
                type="image",
                agent="visual_agent",
                file_path=str(enemy_path),
                status=ArtifactStatus.COMPLETED,
                feedback_history=[]
            )

            # Record attribution
            self.attribution.add_mock_attribution("visual_enemy", "image")

        # Generate background
        bg_path = self._create_background("background", (800, 600))

        artifacts["visual_background"] = Artifact(
            id="visual_background",
            type="image",
            agent="visual_agent",
            file_path=str(bg_path),
            status=ArtifactStatus.COMPLETED,
            feedback_history=[]
        )

        # Record attribution
        self.attribution.add_mock_attribution("visual_background", "image")

        print(f"   ✅ Generated {len(artifacts)} placeholder images")

        return artifacts

    def _create_colored_rectangle(
        self,
        name: str,
        size: tuple,
        color: tuple,
        label: str
    ) -> Path:
        """Create a simple colored rectangle with label."""
        img = Image.new('RGBA', size, color)
        draw = ImageDraw.Draw(img)

        # Add label text
        try:
            # Try to use default font
            font = ImageFont.load_default()
            # Get text size (compatible with both old and new Pillow)
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
            pass  # Skip text if font loading fails

        # Save image
        file_path = self.output_dir / "mock" / f"{name}.png"
        img.save(file_path)

        return file_path

    def _create_background(self, name: str, size: tuple) -> Path:
        """Create a simple gradient background."""
        img = Image.new('RGB', size, (50, 50, 150))  # Dark blue

        # Add simple gradient effect
        draw = ImageDraw.Draw(img)
        for y in range(size[1]):
            brightness = int(50 + (y / size[1]) * 100)
            color = (brightness // 2, brightness // 2, brightness)
            draw.line([(0, y), (size[0], y)], fill=color)

        # Save image
        file_path = self.output_dir / "backgrounds" / f"{name}.png"
        img.save(file_path)

        return file_path
