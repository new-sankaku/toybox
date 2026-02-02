import asyncio
import sys
import io
import os
from contextlib import redirect_stdout,redirect_stderr
from typing import Optional,Dict,Any
from .base import Skill,SkillResult,SkillContext,SkillCategory,SkillParameter


class PythonExecuteSkill(Skill):
 name="python_execute"
 description="Pythonコードを実行します"
 category=SkillCategory.EXECUTE
 parameters=[
  SkillParameter(name="code",type="string",description="実行するPythonコード"),
  SkillParameter(name="timeout",type="integer",description="タイムアウト秒数",required=False,default=30),
 ]

 BLOCKED_IMPORTS=[
  "subprocess",
  "os.system",
  "os.popen",
  "commands",
  "pty",
  "ctypes",
  "multiprocessing",
 ]

 BLOCKED_FUNCTIONS=[
  "exec(",
  "eval(",
  "compile(",
  "__import__(",
  "open('/etc",
  "open('/dev",
  "open('/proc",
 ]

 def __init__(self):
  super().__init__()
  self._globals:Dict[str,Any]={}

 async def execute(self,context:SkillContext,**kwargs)->SkillResult:
  code=kwargs.get("code","")
  timeout=kwargs.get("timeout",30)
  if not code:
   return SkillResult(success=False,error="code is required")
  if context.sandbox_enabled:
   block_reason=self._check_blocked(code)
   if block_reason:
    return SkillResult(success=False,error=f"Code blocked: {block_reason}")
  try:
   result=await asyncio.wait_for(
    asyncio.to_thread(self._execute_code,code,context),
    timeout=timeout
   )
   return result
  except asyncio.TimeoutError:
   return SkillResult(success=False,error=f"Execution timed out after {timeout} seconds")
  except Exception as e:
   return SkillResult(success=False,error=str(e))

 def _check_blocked(self,code:str)->Optional[str]:
  for blocked in self.BLOCKED_IMPORTS:
   if f"import {blocked}" in code or f"from {blocked}" in code:
    return f"Blocked import: {blocked}"
  for blocked in self.BLOCKED_FUNCTIONS:
   if blocked in code:
    return f"Blocked function: {blocked}"
  return None

 def _execute_code(self,code:str,context:SkillContext)->SkillResult:
  stdout_capture=io.StringIO()
  stderr_capture=io.StringIO()
  local_vars={"__name__":"__main__","__file__":"<agent>"}
  local_vars["print"]=lambda*args,**kw:print(*args,file=stdout_capture,**kw)
  safe_builtins=self._get_safe_builtins()
  local_vars["__builtins__"]=safe_builtins
  original_cwd=os.getcwd()
  try:
   os.chdir(context.working_dir)
   with redirect_stdout(stdout_capture),redirect_stderr(stderr_capture):
    exec(code,local_vars)
   stdout_str=stdout_capture.getvalue()[:context.max_output_size]
   stderr_str=stderr_capture.getvalue()[:context.max_output_size]
   return SkillResult(
    success=True,
    output=stdout_str or"(no output)",
    metadata={
     "stderr":stderr_str if stderr_str else None,
     "variables":{k:repr(v)[:100] for k,v in local_vars.items()
                  if not k.startswith("_") and k not in safe_builtins}
    }
   )
  except SyntaxError as e:
   return SkillResult(success=False,error=f"Syntax error: {e}")
  except Exception as e:
   stderr_str=stderr_capture.getvalue()
   return SkillResult(
    success=False,
    output=stdout_capture.getvalue()[:context.max_output_size],
    error=f"{type(e).__name__}: {e}",
    metadata={"stderr":stderr_str if stderr_str else None}
   )
  finally:
   os.chdir(original_cwd)

 def _get_safe_builtins(self)->dict:
  import builtins
  safe={}
  allowed=[
   "abs","all","any","ascii","bin","bool","bytearray","bytes",
   "callable","chr","dict","dir","divmod","enumerate","filter",
   "float","format","frozenset","getattr","hasattr","hash","hex",
   "id","int","isinstance","issubclass","iter","len","list","map",
   "max","min","next","object","oct","ord","pow","print","range",
   "repr","reversed","round","set","slice","sorted","str","sum",
   "tuple","type","vars","zip",
   "True","False","None",
   "Exception","ValueError","TypeError","KeyError","IndexError",
   "AttributeError","RuntimeError","StopIteration",
  ]
  for name in allowed:
   if hasattr(builtins,name):
    safe[name]=getattr(builtins,name)
  return safe
