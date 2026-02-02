import os
import json
from typing import Optional,Dict,Any,List
from .base import Skill,SkillResult,SkillContext,SkillCategory,SkillParameter
from .bash_skill import BashExecuteSkill


class CodeBuildSkill(Skill):
 name="code_build"
 description="プロジェクトをビルドします（npm/yarn/python/godot等）"
 category=SkillCategory.BUILD
 parameters=[
  SkillParameter(name="build_type",type="string",description="ビルドタイプ: npm, yarn, python, godot, make",required=False,default="auto"),
  SkillParameter(name="command",type="string",description="カスタムビルドコマンド（指定時はbuild_typeを無視）",required=False),
  SkillParameter(name="args",type="string",description="追加引数",required=False,default=""),
 ]

 BUILD_COMMANDS={
  "npm":"npm run build",
  "yarn":"yarn build",
  "pnpm":"pnpm build",
  "python":"python -m build",
  "pip":"pip install -e .",
  "godot":"godot --export-release",
  "make":"make",
  "cargo":"cargo build --release",
 }

 def __init__(self):
  super().__init__()
  self._bash=BashExecuteSkill()

 async def execute(self,context:SkillContext,**kwargs)->SkillResult:
  build_type=kwargs.get("build_type","auto")
  custom_command=kwargs.get("command")
  args=kwargs.get("args","")
  if custom_command:
   command=f"{custom_command} {args}".strip()
  elif build_type=="auto":
   detected=self._detect_build_type(context.working_dir)
   if not detected:
    return SkillResult(success=False,error="ビルドタイプを自動検出できませんでした")
   command=f"{self.BUILD_COMMANDS[detected]} {args}".strip()
  else:
   if build_type not in self.BUILD_COMMANDS:
    return SkillResult(success=False,error=f"不明なビルドタイプ: {build_type}")
   command=f"{self.BUILD_COMMANDS[build_type]} {args}".strip()
  result=await self._bash.execute(context,command=command,timeout=300)
  if result.success:
   return SkillResult(
    success=True,
    output=result.output,
    metadata={"command":command,"build_type":build_type}
   )
  return SkillResult(
   success=False,
   output=result.output,
   error=result.error or"ビルドに失敗しました",
   metadata={"command":command}
  )

 def _detect_build_type(self,working_dir:str)->Optional[str]:
  checks=[
   ("package.json","npm"),
   ("yarn.lock","yarn"),
   ("pnpm-lock.yaml","pnpm"),
   ("pyproject.toml","python"),
   ("setup.py","pip"),
   ("requirements.txt","pip"),
   ("project.godot","godot"),
   ("Makefile","make"),
   ("Cargo.toml","cargo"),
  ]
  for filename,build_type in checks:
   if os.path.exists(os.path.join(working_dir,filename)):
    return build_type
  return None


class CodeTestSkill(Skill):
 name="code_test"
 description="テストを実行します（pytest/jest/npm test等）"
 category=SkillCategory.BUILD
 parameters=[
  SkillParameter(name="test_type",type="string",description="テストタイプ: pytest, jest, npm, yarn, go, cargo",required=False,default="auto"),
  SkillParameter(name="command",type="string",description="カスタムテストコマンド",required=False),
  SkillParameter(name="path",type="string",description="テスト対象のパス",required=False,default=""),
  SkillParameter(name="args",type="string",description="追加引数（例: -v, --coverage）",required=False,default=""),
 ]

 TEST_COMMANDS={
  "pytest":"pytest",
  "python":"python -m pytest",
  "jest":"npx jest",
  "npm":"npm test",
  "yarn":"yarn test",
  "pnpm":"pnpm test",
  "go":"go test ./...",
  "cargo":"cargo test",
 }

 def __init__(self):
  super().__init__()
  self._bash=BashExecuteSkill()

 async def execute(self,context:SkillContext,**kwargs)->SkillResult:
  test_type=kwargs.get("test_type","auto")
  custom_command=kwargs.get("command")
  path=kwargs.get("path","")
  args=kwargs.get("args","")
  if custom_command:
   command=f"{custom_command} {path} {args}".strip()
  elif test_type=="auto":
   detected=self._detect_test_type(context.working_dir)
   if not detected:
    return SkillResult(success=False,error="テストタイプを自動検出できませんでした")
   base_cmd=self.TEST_COMMANDS[detected]
   command=f"{base_cmd} {path} {args}".strip()
  else:
   if test_type not in self.TEST_COMMANDS:
    return SkillResult(success=False,error=f"不明なテストタイプ: {test_type}")
   base_cmd=self.TEST_COMMANDS[test_type]
   command=f"{base_cmd} {path} {args}".strip()
  result=await self._bash.execute(context,command=command,timeout=180)
  test_summary=self._parse_test_output(result.output or"",test_type)
  return SkillResult(
   success=result.success,
   output=result.output,
   error=result.error if not result.success else None,
   metadata={"command":command,"test_type":test_type,"summary":test_summary}
  )

 def _detect_test_type(self,working_dir:str)->Optional[str]:
  checks=[
   ("pytest.ini","pytest"),
   ("pyproject.toml","pytest"),
   ("conftest.py","pytest"),
   ("jest.config.js","jest"),
   ("jest.config.ts","jest"),
   ("package.json","npm"),
   ("go.mod","go"),
   ("Cargo.toml","cargo"),
  ]
  for filename,test_type in checks:
   if os.path.exists(os.path.join(working_dir,filename)):
    return test_type
  if os.path.exists(os.path.join(working_dir,"tests")):
   return"pytest"
  return None

 def _parse_test_output(self,output:str,test_type:str)->Dict[str,Any]:
  summary={"passed":0,"failed":0,"skipped":0,"total":0}
  if"pytest" in test_type or test_type=="python":
   import re
   match=re.search(r'(\d+) passed',output)
   if match:
    summary["passed"]=int(match.group(1))
   match=re.search(r'(\d+) failed',output)
   if match:
    summary["failed"]=int(match.group(1))
   match=re.search(r'(\d+) skipped',output)
   if match:
    summary["skipped"]=int(match.group(1))
  summary["total"]=summary["passed"]+summary["failed"]+summary["skipped"]
  return summary


class CodeLintSkill(Skill):
 name="code_lint"
 description="リンターを実行してコードの問題を検出します"
 category=SkillCategory.BUILD
 parameters=[
  SkillParameter(name="lint_type",type="string",description="リンタータイプ: eslint, ruff, flake8, pylint, prettier, black",required=False,default="auto"),
  SkillParameter(name="command",type="string",description="カスタムリントコマンド",required=False),
  SkillParameter(name="path",type="string",description="チェック対象のパス",required=False,default="."),
  SkillParameter(name="fix",type="boolean",description="自動修正を試みるか",required=False,default=False),
 ]

 LINT_COMMANDS={
  "eslint":{"check":"npx eslint","fix":"npx eslint --fix"},
  "prettier":{"check":"npx prettier --check","fix":"npx prettier --write"},
  "ruff":{"check":"ruff check","fix":"ruff check --fix"},
  "black":{"check":"black --check","fix":"black"},
  "flake8":{"check":"flake8","fix":"flake8"},
  "pylint":{"check":"pylint","fix":"pylint"},
  "mypy":{"check":"mypy","fix":"mypy"},
 }

 def __init__(self):
  super().__init__()
  self._bash=BashExecuteSkill()

 async def execute(self,context:SkillContext,**kwargs)->SkillResult:
  lint_type=kwargs.get("lint_type","auto")
  custom_command=kwargs.get("command")
  path=kwargs.get("path",".")
  fix=kwargs.get("fix",False)
  if custom_command:
   command=f"{custom_command} {path}".strip()
  elif lint_type=="auto":
   detected=self._detect_lint_type(context.working_dir)
   if not detected:
    return SkillResult(success=False,error="リンタータイプを自動検出できませんでした")
   mode="fix" if fix else"check"
   base_cmd=self.LINT_COMMANDS[detected][mode]
   command=f"{base_cmd} {path}".strip()
  else:
   if lint_type not in self.LINT_COMMANDS:
    return SkillResult(success=False,error=f"不明なリンタータイプ: {lint_type}")
   mode="fix" if fix else"check"
   base_cmd=self.LINT_COMMANDS[lint_type][mode]
   command=f"{base_cmd} {path}".strip()
  result=await self._bash.execute(context,command=command,timeout=120)
  issues=self._parse_lint_output(result.output or"",lint_type)
  return SkillResult(
   success=result.success or len(issues)==0,
   output=result.output,
   error=result.error if not result.success and len(issues)>0 else None,
   metadata={"command":command,"lint_type":lint_type,"issues_count":len(issues),"fix_mode":fix}
  )

 def _detect_lint_type(self,working_dir:str)->Optional[str]:
  checks=[
   (".eslintrc.js","eslint"),
   (".eslintrc.json","eslint"),
   (".eslintrc","eslint"),
   (".prettierrc","prettier"),
   ("ruff.toml","ruff"),
   ("pyproject.toml","ruff"),
   (".flake8","flake8"),
   ("setup.cfg","flake8"),
   (".pylintrc","pylint"),
   ("mypy.ini","mypy"),
  ]
  for filename,lint_type in checks:
   if os.path.exists(os.path.join(working_dir,filename)):
    return lint_type
  if os.path.exists(os.path.join(working_dir,"package.json")):
   return"eslint"
  py_files=any(f.endswith(".py") for f in os.listdir(working_dir) if os.path.isfile(os.path.join(working_dir,f)))
  if py_files:
   return"ruff"
  return None

 def _parse_lint_output(self,output:str,lint_type:str)->List[Dict[str,Any]]:
  issues=[]
  lines=output.strip().split("\n")
  for line in lines:
   if any(x in line.lower() for x in ["error","warning","E:","W:"]):
    issues.append({"line":line})
  return issues[:50]
