"""
Debugger Agent - Bug analysis and fixing.
"""

from pathlib import Path
from typing import Dict, Any
from langchain_core.prompts import ChatPromptTemplate

from ..core.state import GameState
from ..core.llm import get_llm_for_agent
from ..tools import ClaudeCodeDelegate, FileTools, BashTools


class DebuggerAgent:
    """
    Debugger Agent analyzes and fixes bugs.

    Responsibilities:
    - Analyze error messages
    - Fix syntax errors
    - Fix import errors
    - Fix simple logic errors
    - Delegate complex issues to Claude Code
    """

    def __init__(self):
        """Initialize the Debugger Agent."""
        self.llm = get_llm_for_agent("debugger")
        self.output_dir = Path("output/code")
        self.claude_delegate = ClaudeCodeDelegate()
        self.file_tools = FileTools()
        self.bash_tools = BashTools()
        self.retry_count = 0
        self.max_retries = 3

    def run(self, state: GameState) -> Dict[str, Any]:
        """
        Execute debugging phase.

        Args:
            state: Current game state

        Returns:
            Dictionary with fixed_code
        """
        errors = state.get("errors", [])
        code_files = state.get("code_files", {})

        if not errors:
            print("✅ No errors to fix")
            return {"fixed_code": {}}

        print(f"🐛 Fixing {len(errors)} errors")

        fixed_code = {}

        # Group errors by file
        errors_by_file = {}
        for error in errors:
            filename = error.get("file", "unknown")
            if filename not in errors_by_file:
                errors_by_file[filename] = []
            errors_by_file[filename].append(error)

        # Fix each file
        for filename, file_errors in errors_by_file.items():
            if filename not in code_files:
                continue

            print(f"\n   Fixing {filename} ({len(file_errors)} errors)")

            # Try automatic fixes first
            auto_fixed = self._try_automatic_fixes(filename, code_files[filename], file_errors)

            if auto_fixed:
                fixed_code[filename] = auto_fixed
                print(f"   ✅ Automatically fixed {filename}")
            else:
                # Check if should delegate to Claude Code
                if self._should_delegate_debugging(file_errors, state):
                    delegated = self._delegate_to_claude_code(filename, code_files[filename], file_errors, state)
                    if delegated:
                        print(f"   🔄 Delegated {filename} to Claude Code")
                        continue

                # Use LLM to fix
                llm_fixed = self._fix_with_llm(filename, code_files[filename], file_errors)
                if llm_fixed:
                    fixed_code[filename] = llm_fixed
                    print(f"   ✅ Fixed {filename} with LLM")

        # Write fixed files
        for filename, content in fixed_code.items():
            file_path = self.output_dir / filename
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)

        return {"fixed_code": fixed_code}

    def _try_automatic_fixes(self, filename: str, code: str, errors: list) -> str:
        """Try to automatically fix simple errors."""

        # Check for missing import errors
        missing_imports = []
        for error in errors:
            if error.get("type") == "import_error":
                module = error.get("module", "")
                missing_imports.append(module)

        if missing_imports:
            # Add missing imports at the top
            lines = code.split("\n")
            import_lines = []

            for module in missing_imports:
                # Skip if already imported
                if f"import {module}" not in code:
                    import_lines.append(f"import {module}")

            if import_lines:
                # Find where to insert imports (after docstring if present)
                insert_pos = 0
                in_docstring = False

                for i, line in enumerate(lines):
                    stripped = line.strip()
                    if i == 0 and (stripped.startswith('"""') or stripped.startswith("'''")):
                        in_docstring = True
                    if in_docstring and (stripped.endswith('"""') or stripped.endswith("'''")):
                        insert_pos = i + 1
                        break
                    if not in_docstring and not stripped.startswith('#') and stripped:
                        insert_pos = i
                        break

                # Insert imports
                for import_line in reversed(import_lines):
                    lines.insert(insert_pos, import_line)

                return "\n".join(lines)

        return None

    def _fix_with_llm(self, filename: str, code: str, errors: list) -> str:
        """Use LLM to fix errors."""

        error_summary = "\n".join([
            f"- {e.get('type')}: {e.get('message')}"
            for e in errors
        ])

        prompt = ChatPromptTemplate.from_template("""You are a Python debugging expert.
Fix the following code based on the errors reported.

Filename: {filename}

Errors:
{errors}

Original Code:
```python
{code}
```

Return ONLY the fixed code, no explanations or markdown formatting.
Start directly with the code.""")

        chain = prompt | self.llm

        try:
            result = chain.invoke({
                "filename": filename,
                "errors": error_summary,
                "code": code
            })

            fixed_code = result.content if hasattr(result, 'content') else str(result)

            # Clean up output
            fixed_code = self._clean_code_output(fixed_code)

            return fixed_code

        except Exception as e:
            print(f"❌ Error fixing code with LLM: {e}")
            return code  # Return original code if fixing fails

    def _clean_code_output(self, code: str) -> str:
        """Clean up code output from LLM."""
        # Remove markdown code blocks if present
        if code.startswith("```"):
            lines = code.split("\n")
            lines = lines[1:]  # Remove first line
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]  # Remove last line
            code = "\n".join(lines)

        return code.strip()

    def _should_delegate_debugging(self, errors: list, state: GameState) -> bool:
        """
        Determine if debugging should be delegated to Claude Code.

        Args:
            errors: List of errors
            state: Current state

        Returns:
            True if should delegate
        """
        # Delegate if too many retries
        iteration = state.get("iteration", 0)
        if iteration >= self.max_retries:
            print(f"   ⚠️  Max retries ({self.max_retries}) reached")
            return True

        # Delegate if complex logic errors
        has_logic_errors = any(
            e.get("type") not in ["syntax_error", "import_error"]
            for e in errors
        )

        if has_logic_errors and len(errors) > 3:
            return True

        # Delegate if multiple files involved
        unique_files = set(e.get("file") for e in errors)
        if len(unique_files) >= 3:
            return True

        return False

    def _delegate_to_claude_code(
        self,
        filename: str,
        code: str,
        errors: list,
        state: GameState
    ) -> bool:
        """
        Delegate debugging to Claude Code.

        Args:
            filename: File to fix
            code: Current code
            errors: List of errors
            state: Current state

        Returns:
            True if delegated successfully
        """
        error_summary = "\n".join([
            f"- Line {e.get('line', '?')}: {e.get('message')}"
            for e in errors
        ])

        description = f"""Debug and fix errors in {filename}:

Errors found:
{error_summary}

Current code is in: output/code/{filename}

Requirements:
- Fix all errors
- Ensure code runs without errors
- Maintain existing functionality
- Add comments explaining fixes
"""

        # Create task
        task, _ = self.claude_delegate.create_task(
            task_type="debug",
            description=description,
            target_files=[f"output/code/{filename}"],
            context=f"Errors: {error_summary}",
            priority="high",
            wait_for_result=False
        )

        # Add to state
        state["claude_code_tasks"].append(task)

        return True
