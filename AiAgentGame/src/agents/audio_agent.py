"""
Audio Agent - Audio asset generation.
"""

from pathlib import Path
from typing import Dict, Any
import struct
import wave

from ..core.state import DevelopmentPhase, Artifact, ArtifactStatus
from ..tools import AttributionManager


class AudioAgent:
    """
    Audio Agent generates audio assets (BGM, SE, etc.).

    For MOCK phase: Simple beep sounds
    For GENERATE phase: Would fetch free assets or generate with AI
    For POLISH phase: Would process and normalize audio
    For FINAL phase: Would generate high-quality audio
    """

    def __init__(self):
        """Initialize the Audio Agent."""
        self.output_dir = Path("output/audio")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Create subdirectories
        (self.output_dir / "bgm").mkdir(exist_ok=True)
        (self.output_dir / "se").mkdir(exist_ok=True)
        (self.output_dir / "mock").mkdir(exist_ok=True)

        # Attribution manager
        self.attribution = AttributionManager()

    def generate(self, game_spec: Dict[str, Any], phase: DevelopmentPhase) -> Dict[str, Artifact]:
        """
        Generate audio assets based on game spec and phase.

        Args:
            game_spec: Game specification
            phase: Current development phase

        Returns:
            Dictionary of artifact ID to Artifact
        """
        artifacts = {}

        if phase == DevelopmentPhase.MOCK:
            # Generate simple placeholder sounds
            artifacts.update(self._generate_mock_assets(game_spec))
        else:
            # For other phases, still use mock for now
            print("   ℹ️  Note: Currently only MOCK phase is fully implemented")
            artifacts.update(self._generate_mock_assets(game_spec))

        return artifacts

    def _generate_mock_assets(self, game_spec: Dict[str, Any]) -> Dict[str, Artifact]:
        """Generate simple placeholder sounds for MOCK phase."""
        artifacts = {}

        # Generate a simple beep sound effect
        se_path = self._create_beep("jump_se", 440, 0.1)  # 440 Hz, 0.1 second

        artifacts["audio_jump_se"] = Artifact(
            id="audio_jump_se",
            type="audio",
            agent="audio_agent",
            file_path=str(se_path),
            status=ArtifactStatus.COMPLETED,
            feedback_history=[]
        )

        # Record attribution
        self.attribution.add_mock_attribution("audio_jump_se", "audio")

        print(f"   ✅ Generated {len(artifacts)} placeholder sounds")

        return artifacts

    def _create_beep(self, name: str, frequency: float, duration: float) -> Path:
        """Create a simple beep sound."""
        sample_rate = 44100
        num_samples = int(sample_rate * duration)

        # Generate sine wave
        samples = []
        for i in range(num_samples):
            value = 32767 * 0.3 * (  # 30% volume
                (i % int(sample_rate / frequency)) < (sample_rate / frequency / 2)
            )
            # Convert to 16-bit PCM
            packed_value = struct.pack('h', int(value))
            samples.append(packed_value)

        # Save as WAV file
        file_path = self.output_dir / "mock" / f"{name}.wav"

        with wave.open(str(file_path), 'w') as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(b''.join(samples))

        return file_path
