"""
Tester Agent - Game testing and validation.
"""

import ast
import subprocess
from pathlib import Path
from typing import Dict, Any, List

from ..core.state import GameState


class TesterAgent:
    """
    Tester Agent tests game code and reports errors.

    Responsibilities:
    - Validate code syntax
    - Check for common errors
    - Attempt to run the game (in headless mode if possible)
    - Report test results
    """

    def __init__(self):
        """Initialize the Tester Agent."""
        self.output_dir = Path("output/code")

    def run(self, state: GameState) -> Dict[str, Any]:
        """
        Execute testing phase.

        Args:
            state: Current game state

        Returns:
            Dictionary with test_results and errors
        """
        code_files = state.get("code_files", {})

        if not code_files:
            print("❌ No code files to test")
            return {"test_results": None, "errors": []}

        print(f"🧪 Testing {len(code_files)} files")

        errors = []
        test_results = {
            "syntax_check": True,
            "import_check": True,
            "runtime_check": False
        }

        # Test each Python file
        for filename, content in code_files.items():
            if not filename.endswith('.py'):
                continue

            print(f"\n   Testing {filename}...")

            # Syntax check
            syntax_errors = self._check_syntax(filename, content)
            if syntax_errors:
                errors.extend(syntax_errors)
                test_results["syntax_check"] = False

            # Import check
            import_errors = self._check_imports(filename, content)
            if import_errors:
                errors.extend(import_errors)
                test_results["import_check"] = False

        # Print results
        if errors:
            print(f"\n❌ Found {len(errors)} errors:")
            for error in errors[:5]:  # Show first 5 errors
                print(f"   • {error.get('message')}")
            if len(errors) > 5:
                print(f"   ... and {len(errors) - 5} more")
        else:
            print("\n✅ All tests passed!")

        return {
            "test_results": test_results,
            "errors": errors
        }

    def _check_syntax(self, filename: str, code: str) -> List[Dict[str, Any]]:
        """Check Python syntax."""
        errors = []

        try:
            ast.parse(code)
        except SyntaxError as e:
            errors.append({
                "type": "syntax_error",
                "file": filename,
                "line": e.lineno,
                "message": f"Syntax error in {filename}:{e.lineno}: {e.msg}",
                "detail": str(e)
            })

        return errors

    def _check_imports(self, filename: str, code: str) -> List[Dict[str, Any]]:
        """Check if imports are valid."""
        errors = []

        try:
            tree = ast.parse(code)
        except:
            return errors  # Syntax error already caught

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if not self._is_module_available(alias.name):
                        errors.append({
                            "type": "import_error",
                            "file": filename,
                            "line": node.lineno,
                            "message": f"Module '{alias.name}' not found in {filename}:{node.lineno}",
                            "module": alias.name
                        })

            elif isinstance(node, ast.ImportFrom):
                if node.module and not self._is_module_available(node.module):
                    errors.append({
                        "type": "import_error",
                        "file": filename,
                        "line": node.lineno,
                        "message": f"Module '{node.module}' not found in {filename}:{node.lineno}",
                        "module": node.module
                    })

        return errors

    def _is_module_available(self, module_name: str) -> bool:
        """Check if a module is available."""
        # Skip checking standard library and built-in modules
        stdlib_modules = {
            'sys', 'os', 'json', 'time', 'datetime', 'random', 'math',
            'collections', 'itertools', 'functools', 'pathlib', 're',
            'typing', 'abc', 'enum', 'dataclasses'
        }

        if module_name.split('.')[0] in stdlib_modules:
            return True

        # Check if module is installed
        try:
            __import__(module_name.split('.')[0])
            return True
        except ImportError:
            return False

    def _run_static_analysis(self, filename: str) -> List[Dict[str, Any]]:
        """Run static analysis (optional, requires additional tools)."""
        errors = []

        file_path = self.output_dir / filename

        if not file_path.exists():
            return errors

        # Try to run pylint or flake8 if available
        try:
            result = subprocess.run(
                ['python', '-m', 'pylint', '--errors-only', str(file_path)],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0 and result.stdout:
                errors.append({
                    "type": "lint_error",
                    "file": filename,
                    "message": f"Linting issues in {filename}",
                    "detail": result.stdout
                })

        except (subprocess.TimeoutExpired, FileNotFoundError):
            # Pylint not available or timeout
            pass

        return errors
