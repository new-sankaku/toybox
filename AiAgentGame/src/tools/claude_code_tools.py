"""
Claude Code delegation tools for complex tasks.
"""

import json
import time
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

from ..core.state import ClaudeCodeTask, ClaudeCodeResult


class ClaudeCodeDelegate:
    """
    Tool for delegating complex tasks to Claude Code via file-based communication.

    How it works:
    1. Agent creates a task file in claude_tasks/
    2. Claude Code (in another session) picks up the task
    3. Claude Code writes result to claude_results/
    4. Agent picks up the result and continues
    """

    def __init__(self):
        """Initialize Claude Code delegate."""
        self.tasks_dir = Path("claude_tasks")
        self.results_dir = Path("claude_results")

        # Create directories
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)

    def create_task(
        self,
        task_type: str,
        description: str,
        target_files: list[str],
        context: str = "",
        priority: str = "medium",
        wait_for_result: bool = False,
        timeout: int = 300
    ) -> ClaudeCodeTask:
        """
        Create a task for Claude Code to execute.

        Args:
            task_type: Type of task ("refactor", "debug", "test", "review")
            description: Detailed task description
            target_files: List of files to work on
            context: Additional context information
            priority: Task priority ("high", "medium", "low")
            wait_for_result: Whether to wait for result
            timeout: Timeout in seconds if waiting

        Returns:
            ClaudeCodeTask object
        """
        # Generate task ID
        task_id = f"{task_type}_{int(time.time() * 1000)}"

        # Create task object
        task = ClaudeCodeTask(
            task_id=task_id,
            task_type=task_type,
            description=description,
            target_files=target_files,
            context=context,
            priority=priority,
            created_at=datetime.now().isoformat(),
            status="pending"
        )

        # Write task file
        task_file = self.tasks_dir / f"{task_id}.json"
        with open(task_file, 'w') as f:
            json.dump(task, f, indent=2)

        print(f"\n📝 Claude Code task created: {task_id}")
        print(f"   Type: {task_type}")
        print(f"   Files: {', '.join(target_files)}")
        print(f"   Task file: {task_file}")
        print(f"\n   ⏳ Waiting for Claude Code to process this task...")
        print(f"   💡 To process: Open another terminal and run Claude Code on this task file")

        if wait_for_result:
            result = self.wait_for_result(task_id, timeout)
            return task, result

        return task, None

    def wait_for_result(
        self,
        task_id: str,
        timeout: int = 300,
        check_interval: float = 2.0
    ) -> Optional[ClaudeCodeResult]:
        """
        Wait for Claude Code to complete a task.

        Args:
            task_id: Task identifier
            timeout: Maximum wait time in seconds
            check_interval: How often to check for results

        Returns:
            ClaudeCodeResult if completed, None if timeout
        """
        result_file = self.results_dir / f"{task_id}_result.json"
        start_time = time.time()

        print(f"   ⏰ Waiting up to {timeout}s for result...")

        while time.time() - start_time < timeout:
            if result_file.exists():
                with open(result_file, 'r') as f:
                    result = json.load(f)

                print(f"\n   ✅ Claude Code completed task: {task_id}")
                if result.get("success"):
                    print(f"   📄 Modified files: {', '.join(result.get('modified_files', []))}")
                else:
                    print(f"   ❌ Task failed: {', '.join(result.get('errors', []))}")

                # Remove result file after reading
                result_file.unlink()

                return ClaudeCodeResult(**result)

            time.sleep(check_interval)

        print(f"\n   ⏰ Timeout waiting for Claude Code result")
        print(f"   💡 You can continue manually by creating: {result_file}")
        return None

    def check_result(self, task_id: str) -> Optional[ClaudeCodeResult]:
        """
        Check if a result is available for a task (non-blocking).

        Args:
            task_id: Task identifier

        Returns:
            ClaudeCodeResult if available, None otherwise
        """
        result_file = self.results_dir / f"{task_id}_result.json"

        if result_file.exists():
            with open(result_file, 'r') as f:
                result = json.load(f)
            result_file.unlink()
            return ClaudeCodeResult(**result)

        return None

    def should_delegate(
        self,
        estimated_lines: int = 0,
        file_count: int = 0,
        complexity_score: float = 0.0,
        task_type: str = ""
    ) -> bool:
        """
        Determine if a task should be delegated to Claude Code.

        Args:
            estimated_lines: Estimated lines of code
            file_count: Number of files involved
            complexity_score: Complexity score (0.0-1.0)
            task_type: Type of task

        Returns:
            True if should delegate, False otherwise
        """
        # Load thresholds from config (or use defaults)
        thresholds = {
            "lines_of_code": 100,
            "file_count": 3,
            "complexity_score": 0.7
        }

        # Check delegation criteria
        if estimated_lines >= thresholds["lines_of_code"]:
            print(f"   🔄 Delegating to Claude Code: LOC ({estimated_lines}) exceeds threshold")
            return True

        if file_count >= thresholds["file_count"]:
            print(f"   🔄 Delegating to Claude Code: File count ({file_count}) exceeds threshold")
            return True

        if complexity_score >= thresholds["complexity_score"]:
            print(f"   🔄 Delegating to Claude Code: Complexity ({complexity_score:.2f}) exceeds threshold")
            return True

        # Always delegate certain types
        if task_type in ["refactor_large", "optimize", "security_audit"]:
            print(f"   🔄 Delegating to Claude Code: Task type requires expert attention")
            return True

        return False

    def create_example_task(self) -> None:
        """Create an example task file for testing."""
        example_task = {
            "task_id": "example_refactor_001",
            "task_type": "refactor",
            "description": "Refactor the game loop to use a proper state machine",
            "target_files": ["output/code/main.py"],
            "context": "The current implementation uses nested if-statements. Convert to a state machine pattern.",
            "priority": "medium",
            "created_at": datetime.now().isoformat(),
            "status": "pending"
        }

        task_file = self.tasks_dir / "example_refactor_001.json"
        with open(task_file, 'w') as f:
            json.dump(example_task, f, indent=2)

        print(f"✅ Created example task: {task_file}")

    def create_example_result(self) -> None:
        """Create an example result file for testing."""
        example_result = {
            "task_id": "example_refactor_001",
            "success": True,
            "modified_files": ["output/code/main.py"],
            "summary": "Refactored game loop to use state machine pattern. Created GameState enum and updated main loop logic.",
            "errors": [],
            "completed_at": datetime.now().isoformat()
        }

        result_file = self.results_dir / "example_refactor_001_result.json"
        with open(result_file, 'w') as f:
            json.dump(example_result, f, indent=2)

        print(f"✅ Created example result: {result_file}")
