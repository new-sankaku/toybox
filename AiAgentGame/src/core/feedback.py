"""
File-based feedback system for human-in-the-loop interaction.
"""

import json
import time
from pathlib import Path
from typing import Optional
from datetime import datetime

from .state import Feedback, GameState


class FeedbackManager:
    """Manages file-based feedback for artifacts."""

    def __init__(self, feedback_dir: str = "feedback", status_dir: str = "status"):
        """
        Initialize feedback manager.

        Args:
            feedback_dir: Directory for user feedback files
            status_dir: Directory for status files
        """
        self.feedback_dir = Path(feedback_dir)
        self.status_dir = Path(status_dir)

        # Create directories if they don't exist
        self.feedback_dir.mkdir(parents=True, exist_ok=True)
        self.status_dir.mkdir(parents=True, exist_ok=True)

    def notify_artifact_ready(
        self,
        artifact_id: str,
        artifact_type: str,
        file_path: str,
        timeout_seconds: int = 30
    ) -> None:
        """
        Notify user that an artifact is ready for review.

        Args:
            artifact_id: Artifact identifier
            artifact_type: Type of artifact (image, audio, code, etc.)
            file_path: Path to the artifact file
            timeout_seconds: How long to wait for feedback
        """
        print(f"\n✅ {artifact_type} '{artifact_id}' generated successfully")
        print(f"   📁 File: {file_path}")
        print(f"   ⏳ Awaiting feedback for {timeout_seconds} seconds...")
        print(f"   💡 To provide feedback, create: {self.feedback_dir / f'{artifact_id}.txt'}")
        print()

    def wait_for_feedback(
        self,
        artifact_id: str,
        timeout_seconds: int = 30,
        check_interval: float = 1.0
    ) -> Optional[Feedback]:
        """
        Wait for user feedback on an artifact.

        Args:
            artifact_id: Artifact identifier
            timeout_seconds: Maximum time to wait
            check_interval: How often to check for feedback file

        Returns:
            Feedback object if received, None if timeout
        """
        start_time = time.time()
        feedback_file_txt = self.feedback_dir / f"{artifact_id}.txt"
        feedback_file_json = self.feedback_dir / f"{artifact_id}.json"

        while time.time() - start_time < timeout_seconds:
            # Check for JSON feedback first (more detailed)
            if feedback_file_json.exists():
                feedback = self._parse_json_feedback(artifact_id, feedback_file_json)
                feedback_file_json.unlink()  # Remove file after reading
                print(f"📝 Feedback received for '{artifact_id}': {feedback['action']}")
                return feedback

            # Check for simple text feedback
            if feedback_file_txt.exists():
                feedback = self._parse_text_feedback(artifact_id, feedback_file_txt)
                feedback_file_txt.unlink()  # Remove file after reading
                print(f"📝 Feedback received for '{artifact_id}': {feedback['action']}")
                return feedback

            time.sleep(check_interval)

        print(f"⏰ Feedback timeout for '{artifact_id}' - proceeding with current version")
        return None

    def _parse_json_feedback(self, artifact_id: str, file_path: Path) -> Feedback:
        """Parse JSON feedback file."""
        with open(file_path, 'r') as f:
            data = json.load(f)

        return Feedback(
            artifact_id=artifact_id,
            action=data.get("action", "comment"),
            comment=data.get("comment", ""),
            timestamp=time.time(),
            processed=False
        )

    def _parse_text_feedback(self, artifact_id: str, file_path: Path) -> Feedback:
        """Parse simple text feedback file."""
        with open(file_path, 'r') as f:
            comment = f.read().strip()

        # Simple heuristic to determine action
        action = "comment"
        comment_lower = comment.lower()

        if any(word in comment_lower for word in ["redo", "regenerate", "再生成"]):
            action = "redo"
        elif any(word in comment_lower for word in ["fix", "修正"]):
            action = "fix"
        elif any(word in comment_lower for word in ["approve", "ok", "good", "承認"]):
            action = "approve"

        return Feedback(
            artifact_id=artifact_id,
            action=action,
            comment=comment,
            timestamp=time.time(),
            processed=False
        )

    def save_status(self, state: GameState) -> None:
        """
        Save current status to file.

        Args:
            state: Current game state
        """
        status_file = self.status_dir / "current.json"

        status = {
            "session_id": "game_session",
            "phase": state["current_phase"],
            "development_phase": state["development_phase"],
            "started_at": datetime.now().isoformat(),
            "artifacts": {
                artifact_id: {
                    "status": artifact["status"],
                    "file": artifact["file_path"],
                    "type": artifact["type"]
                }
                for artifact_id, artifact in state.get("artifacts", {}).items()
            },
            "tasks": [
                {
                    "id": task["id"],
                    "description": task["description"],
                    "status": task["status"]
                }
                for task in state.get("tasks", [])
            ]
        }

        with open(status_file, 'w') as f:
            json.dump(status, f, indent=2)

    def check_global_feedback(self) -> Optional[str]:
        """
        Check for global feedback that applies to all artifacts.

        Returns:
            Global feedback message if exists, None otherwise
        """
        global_feedback = self.feedback_dir / "_global.txt"

        if global_feedback.exists():
            with open(global_feedback, 'r') as f:
                message = f.read().strip()
            global_feedback.unlink()
            print(f"🌐 Global feedback received: {message}")
            return message

        return None
