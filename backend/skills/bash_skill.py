import asyncio
import os
import platform
import shlex
from typing import List, Optional
from .base import Skill, SkillResult, SkillContext, SkillCategory, SkillParameter


class BashExecuteSkill(Skill):
    name = "bash_execute"
    description = "シェルコマンドを実行します"
    category = SkillCategory.EXECUTE
    parameters = [
        SkillParameter(name="command", type="string", description="実行するコマンド"),
        SkillParameter(name="timeout", type="integer", description="タイムアウト秒数", required=False, default=60),
    ]

    BLOCKED_COMMANDS_LINUX = [
        "rm -rf /",
        "rm -rf /*",
        "mkfs",
        "dd if=/dev/zero",
        ":(){ :|:& };:",
        "> /dev/sda",
        "chmod -R 777 /",
        "chown -R",
    ]

    BLOCKED_PATTERNS_LINUX = [
        "sudo ",
        "su ",
        "> /dev/",
        "| sudo",
        "&& sudo",
        "; sudo",
    ]

    BLOCKED_COMMANDS_WINDOWS = [
        "format c:",
        "format d:",
        "del /s /q c:\\",
        "del /s /q c:/",
        "rmdir /s /q c:\\",
        "rmdir /s /q c:/",
        "rd /s /q c:\\",
        "rd /s /q c:/",
        "reg delete hklm",
        "reg delete hkcu",
        "shutdown /s",
        "shutdown /r",
        "bcdedit",
        "diskpart",
    ]

    BLOCKED_PATTERNS_WINDOWS = [
        "format ",
        "del /s /q c:",
        "rmdir /s /q c:",
        "rd /s /q c:",
        "reg delete ",
        "net user ",
        "net localgroup ",
        "runas ",
    ]

    BLOCKED_COMMANDS_COMMON = [
        "curl | sh",
        "curl | bash",
        "wget | sh",
        "wget | bash",
    ]

    def __init__(self):
        super().__init__()
        self._is_windows = platform.system().lower() == "windows"

    async def execute(self, context: SkillContext, **kwargs) -> SkillResult:
        command = kwargs.get("command", "")
        timeout = kwargs.get("timeout", context.timeout_seconds)
        if not command:
            return SkillResult(success=False, error="command is required")
        if context.sandbox_enabled:
            block_reason = self._check_blocked(command)
            if block_reason:
                return SkillResult(success=False, error=f"Command blocked: {block_reason}")
        try:
            result = await self._run_command(command, context.working_dir, timeout, context.max_output_size)
            return result
        except asyncio.TimeoutError:
            return SkillResult(success=False, error=f"Command timed out after {timeout} seconds")
        except Exception as e:
            return SkillResult(success=False, error=str(e))

    def _check_blocked(self, command: str) -> Optional[str]:
        cmd_lower = command.lower().strip()
        for blocked in self.BLOCKED_COMMANDS_COMMON:
            if blocked in cmd_lower:
                return f"Dangerous command pattern: {blocked}"
        if self._is_windows:
            blocked_commands = self.BLOCKED_COMMANDS_WINDOWS
            blocked_patterns = self.BLOCKED_PATTERNS_WINDOWS
        else:
            blocked_commands = self.BLOCKED_COMMANDS_LINUX
            blocked_patterns = self.BLOCKED_PATTERNS_LINUX
        for blocked in blocked_commands:
            if blocked in cmd_lower:
                return f"Dangerous command pattern: {blocked}"
        for pattern in blocked_patterns:
            if pattern in cmd_lower:
                return f"Blocked pattern: {pattern}"
        return None

    async def _run_command(self, command: str, cwd: str, timeout: int, max_output: int) -> SkillResult:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=self._get_safe_env(),
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise
        stdout_str = stdout.decode("utf-8", errors="replace")[:max_output]
        stderr_str = stderr.decode("utf-8", errors="replace")[:max_output]
        return_code = process.returncode
        if return_code == 0:
            return SkillResult(
                success=True,
                output=stdout_str,
                metadata={
                    "return_code": return_code,
                    "stderr": stderr_str if stderr_str else None,
                },
            )
        else:
            return SkillResult(
                success=False,
                output=stdout_str,
                error=stderr_str or f"Command failed with return code {return_code}",
                metadata={"return_code": return_code},
            )

    def _get_safe_env(self) -> dict:
        env = os.environ.copy()
        sensitive_keys = ["AWS_SECRET", "API_KEY", "PASSWORD", "TOKEN", "SECRET"]
        for key in list(env.keys()):
            for sensitive in sensitive_keys:
                if sensitive in key.upper():
                    del env[key]
                    break
        return env
