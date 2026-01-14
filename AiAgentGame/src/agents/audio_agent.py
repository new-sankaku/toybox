"""
Audio Agent - Audio asset generation.
"""

from pathlib import Path
from typing import Dict, Any
import struct
import wave

from ..core.state import DevelopmentPhase, Artifact, ArtifactStatus
from ..tools import AttributionManager
from ..utils.logger import get_logger

logger = get_logger()


class AudioAgent:
    """Audio Agent generates audio assets (BGM, SE, etc.)."""

    def __init__(self):
        """Initialize the Audio Agent."""
        self.output_dir = Path("output/audio")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        (self.output_dir / "bgm").mkdir(exist_ok=True)
        (self.output_dir / "se").mkdir(exist_ok=True)
        (self.output_dir / "mock").mkdir(exist_ok=True)

        self.attribution = AttributionManager()

    def generate(self, game_spec: Dict[str, Any], phase: DevelopmentPhase) -> Dict[str, Artifact]:
        """Generate audio assets based on game spec and phase."""
        artifacts = {}

        if phase == DevelopmentPhase.MOCK:
            artifacts.update(self._generate_mock_assets(game_spec))
        else:
            logger.debug("MOCKフェーズのみ実装済み")
            artifacts.update(self._generate_mock_assets(game_spec))

        return artifacts

    def _generate_mock_assets(self, game_spec: Dict[str, Any]) -> Dict[str, Artifact]:
        """Generate simple placeholder sounds for MOCK phase."""
        artifacts = {}

        se_path = self._create_beep("jump_se", 440, 0.1)

        artifacts["audio_jump_se"] = Artifact(
            id="audio_jump_se",
            type="audio",
            agent="audio_agent",
            file_path=str(se_path),
            status=ArtifactStatus.COMPLETED,
            feedback_history=[]
        )

        self.attribution.add_mock_attribution("audio_jump_se", "audio")

        logger.info(f"音声生成完了: {len(artifacts)}件")

        return artifacts

    def _create_beep(self, name: str, frequency: float, duration: float) -> Path:
        """Create a simple beep sound."""
        sample_rate = 44100
        num_samples = int(sample_rate * duration)

        samples = []
        for i in range(num_samples):
            value = 32767 * 0.3 * (
                (i % int(sample_rate / frequency)) < (sample_rate / frequency / 2)
            )
            packed_value = struct.pack('h', int(value))
            samples.append(packed_value)

        file_path = self.output_dir / "mock" / f"{name}.wav"

        with wave.open(str(file_path), 'w') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(b''.join(samples))

        return file_path
