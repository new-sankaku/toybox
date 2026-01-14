"""
Bash execution tools.
"""

import subprocess
from typing import Optional, Dict


class BashTools:
    """Tools for executing bash commands."""

    @staticmethod
    def execute(
        command: str,
        timeout: int = 30,
        capture_output: bool = True
    ) -> Dict[str, any]:
        """
        Execute a bash command.

        Args:
            command: Command to execute
            timeout: Timeout in seconds
            capture_output: Whether to capture output

        Returns:
            Dictionary with returncode, stdout, stderr
        """
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=capture_output,
                text=True,
                timeout=timeout
            )

            return {
                "success": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": result.stdout if capture_output else "",
                "stderr": result.stderr if capture_output else ""
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "returncode": -1,
                "stdout": "",
                "stderr": f"Command timed out after {timeout}s"
            }

        except Exception as e:
            return {
                "success": False,
                "returncode": -1,
                "stdout": "",
                "stderr": str(e)
            }

    @staticmethod
    def pip_install(package: str) -> bool:
        """
        Install a Python package via pip.

        Args:
            package: Package name

        Returns:
            True if successful, False otherwise
        """
        print(f"📦 Installing {package}...")
        result = BashTools.execute(f"pip install -q {package}", timeout=120)

        if result["success"]:
            print(f"   ✅ Installed {package}")
            return True
        else:
            print(f"   ❌ Failed to install {package}: {result['stderr']}")
            return False

    @staticmethod
    def check_command_exists(command: str) -> bool:
        """
        Check if a command exists.

        Args:
            command: Command to check

        Returns:
            True if exists, False otherwise
        """
        result = BashTools.execute(f"which {command}", timeout=5)
        return result["success"]

    @staticmethod
    def run_python_file(file_path: str, timeout: int = 10) -> Dict[str, any]:
        """
        Run a Python file and capture output.

        Args:
            file_path: Path to Python file
            timeout: Timeout in seconds

        Returns:
            Dictionary with execution results
        """
        return BashTools.execute(f"python {file_path}", timeout=timeout)
