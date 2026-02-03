import asyncio
import os
from typing import List
from .base import Skill,SkillResult,SkillContext,SkillCategory,SkillParameter
from middleware.logger import get_logger

BLOCKED_COMMANDS={"push","force-push","reset --hard","clean -f","checkout .","restore ."}
ALLOWED_OPERATIONS={"status","diff","log","blame","commit"}


class GitOperationSkill(Skill):
 name="git_operation"
 description="Gitリポジトリ操作を実行します（status/diff/log/blame/commit）"
 category=SkillCategory.EXECUTE
 parameters=[
  SkillParameter(name="operation",type="string",description="操作: status, diff, log, blame, commit"),
  SkillParameter(name="args",type="array",description="追加引数（例: ファイルパス、オプション）",required=False,default=[]),
  SkillParameter(name="message",type="string",description="コミットメッセージ（commit時のみ）",required=False),
 ]

 def __init__(self):
  super().__init__()

 async def execute(self,context:SkillContext,**kwargs)->SkillResult:
  operation=kwargs.get("operation","")
  args=kwargs.get("args",[])
  message=kwargs.get("message","")
  if operation not in ALLOWED_OPERATIONS:
   return SkillResult(success=False,error=f"Unsupported operation: {operation}. Allowed: {', '.join(sorted(ALLOWED_OPERATIONS))}")
  cmd_str=" ".join([operation]+args)
  for blocked in BLOCKED_COMMANDS:
   if blocked in cmd_str:
    return SkillResult(success=False,error=f"Blocked command detected: {blocked}")
  git_cmd=self._build_command(operation,args,message)
  if not git_cmd:
   return SkillResult(success=False,error=f"Failed to build command for: {operation}")
  try:
   result=await self._run_git(git_cmd,context.working_dir,context.timeout_seconds)
   return result
  except Exception as e:
   get_logger().error(f"git_operation failed: {e}",exc_info=True)
   return SkillResult(success=False,error=str(e))

 def _build_command(self,operation:str,args:List[str],message:str)->List[str]:
  if operation=="status":
   return ["git","status","--porcelain"]+args
  elif operation=="diff":
   return ["git","diff"]+args
  elif operation=="log":
   default_args=["--oneline","-20"] if not args else args
   return ["git","log"]+default_args
  elif operation=="blame":
   if not args:
    return []
   return ["git","blame"]+args
  elif operation=="commit":
   if not message:
    return []
   return ["git","commit","-m",message]+args
  return []

 async def _run_git(self,cmd:List[str],working_dir:str,timeout:int)->SkillResult:
  try:
   process=await asyncio.create_subprocess_exec(
    *cmd,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
    cwd=working_dir,
   )
   stdout,stderr=await asyncio.wait_for(process.communicate(),timeout=timeout)
   stdout_str=stdout.decode("utf-8",errors="replace")
   stderr_str=stderr.decode("utf-8",errors="replace")
   if process.returncode==0:
    return SkillResult(success=True,output=stdout_str,metadata={"returncode":0,"command":" ".join(cmd)})
   else:
    return SkillResult(success=False,error=f"Git command failed (exit {process.returncode}): {stderr_str}",metadata={"returncode":process.returncode,"stdout":stdout_str,"stderr":stderr_str})
  except asyncio.TimeoutError:
   return SkillResult(success=False,error=f"Git command timed out after {timeout}s")
