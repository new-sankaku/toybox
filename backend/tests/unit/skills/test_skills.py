import pytest
import asyncio
import os
import tempfile
from pathlib import Path

import sys
sys.path.insert(0,str(Path(__file__).parent.parent.parent.parent))

from skills.base import Skill,SkillResult,SkillContext,SkillCategory
from skills.registry import SkillRegistry,get_skill_registry
from skills.file_skills import FileReadSkill,FileWriteSkill,FileListSkill
from skills.bash_skill import BashExecuteSkill
from skills.python_skill import PythonExecuteSkill
from skills.project_skill import ProjectAnalyzeSkill
from skills.build_skills import CodeBuildSkill,CodeTestSkill,CodeLintSkill
from skills.search_skills import CodeSearchSkill,FileSearchSkill
from skills.web_skills import WebFetchSkill
from skills.executor import SkillExecutor,SkillExecutionConfig,create_skill_executor


@pytest.fixture
def temp_dir():
 with tempfile.TemporaryDirectory() as d:
  yield d


@pytest.fixture
def skill_context(temp_dir):
 return SkillContext(
  project_id="test-project",
  agent_id="test-agent",
  working_dir=temp_dir,
  sandbox_enabled=True,
  timeout_seconds=30,
  max_output_size=10000,
 )


class TestFileReadSkill:
 @pytest.mark.asyncio
 async def test_read_existing_file(self,temp_dir,skill_context):
  test_file=os.path.join(temp_dir,"test.txt")
  with open(test_file,"w") as f:
   f.write("Hello, World!")
  skill=FileReadSkill()
  result=await skill.execute(skill_context,path="test.txt")
  assert result.success
  assert result.output=="Hello, World!"

 @pytest.mark.asyncio
 async def test_read_nonexistent_file(self,skill_context):
  skill=FileReadSkill()
  result=await skill.execute(skill_context,path="nonexistent.txt")
  assert not result.success
  assert"not found" in result.error.lower()

 @pytest.mark.asyncio
 async def test_read_outside_sandbox_blocked(self,skill_context):
  skill=FileReadSkill()
  result=await skill.execute(skill_context,path="/etc/passwd")
  assert not result.success
  assert"denied" in result.error.lower()


class TestFileWriteSkill:
 @pytest.mark.asyncio
 async def test_write_new_file(self,temp_dir,skill_context):
  skill=FileWriteSkill()
  result=await skill.execute(skill_context,path="output.txt",content="Test content")
  assert result.success
  with open(os.path.join(temp_dir,"output.txt")) as f:
   assert f.read()=="Test content"

 @pytest.mark.asyncio
 async def test_write_creates_directories(self,temp_dir,skill_context):
  skill=FileWriteSkill()
  result=await skill.execute(skill_context,path="subdir/output.txt",content="Nested content")
  assert result.success
  with open(os.path.join(temp_dir,"subdir","output.txt")) as f:
   assert f.read()=="Nested content"


class TestFileListSkill:
 @pytest.mark.asyncio
 async def test_list_directory(self,temp_dir,skill_context):
  Path(temp_dir,"file1.txt").touch()
  Path(temp_dir,"file2.txt").touch()
  os.makedirs(os.path.join(temp_dir,"subdir"))
  skill=FileListSkill()
  result=await skill.execute(skill_context,path=".")
  assert result.success
  assert len(result.output)==3
  names=[item["name"] for item in result.output]
  assert"file1.txt" in names
  assert"file2.txt" in names
  assert"subdir" in names


class TestBashExecuteSkill:
 @pytest.mark.asyncio
 async def test_simple_command(self,skill_context):
  skill=BashExecuteSkill()
  result=await skill.execute(skill_context,command="echo 'Hello'")
  assert result.success
  assert"Hello" in result.output

 @pytest.mark.asyncio
 async def test_blocked_dangerous_command(self,skill_context):
  skill=BashExecuteSkill()
  result=await skill.execute(skill_context,command="rm -rf /")
  assert not result.success
  assert"blocked" in result.error.lower()

 @pytest.mark.asyncio
 async def test_command_with_error(self,skill_context):
  skill=BashExecuteSkill()
  result=await skill.execute(skill_context,command="ls /nonexistent_directory_12345")
  assert not result.success


class TestPythonExecuteSkill:
 @pytest.mark.asyncio
 async def test_simple_code(self,skill_context):
  skill=PythonExecuteSkill()
  result=await skill.execute(skill_context,code="print(1 + 2)")
  assert result.success
  assert"3" in result.output

 @pytest.mark.asyncio
 async def test_blocked_import(self,skill_context):
  skill=PythonExecuteSkill()
  result=await skill.execute(skill_context,code="import subprocess")
  assert not result.success
  assert"blocked" in result.error.lower()


class TestProjectAnalyzeSkill:
 @pytest.mark.asyncio
 async def test_analyze_project(self,temp_dir,skill_context):
  Path(temp_dir,"main.py").touch()
  Path(temp_dir,"utils.py").touch()
  with open(os.path.join(temp_dir,"requirements.txt"),"w") as f:
   f.write("flask\n")
  skill=ProjectAnalyzeSkill()
  result=await skill.execute(skill_context,path=".")
  assert result.success
  assert"Python" in result.output.get("languages",{}) or"Python" in str(result.output.get("project_type",""))


class TestCodeBuildSkill:
 @pytest.mark.asyncio
 async def test_auto_detect_no_project(self,skill_context):
  skill=CodeBuildSkill()
  result=await skill.execute(skill_context,build_type="auto")
  assert not result.success
  assert"検出できません" in result.error

 @pytest.mark.asyncio
 async def test_detect_npm_project(self,temp_dir,skill_context):
  with open(os.path.join(temp_dir,"package.json"),"w") as f:
   f.write('{"name":"test"}')
  skill=CodeBuildSkill()
  detected=skill._detect_build_type(temp_dir)
  assert detected=="npm"

 @pytest.mark.asyncio
 async def test_detect_python_project(self,temp_dir,skill_context):
  with open(os.path.join(temp_dir,"pyproject.toml"),"w") as f:
   f.write('[project]\nname="test"')
  skill=CodeBuildSkill()
  detected=skill._detect_build_type(temp_dir)
  assert detected=="python"


class TestCodeTestSkill:
 @pytest.mark.asyncio
 async def test_auto_detect_no_project(self,skill_context):
  skill=CodeTestSkill()
  result=await skill.execute(skill_context,test_type="auto")
  assert not result.success
  assert"検出できません" in result.error

 @pytest.mark.asyncio
 async def test_detect_pytest(self,temp_dir,skill_context):
  with open(os.path.join(temp_dir,"pytest.ini"),"w") as f:
   f.write("[pytest]")
  skill=CodeTestSkill()
  detected=skill._detect_test_type(temp_dir)
  assert detected=="pytest"

 @pytest.mark.asyncio
 async def test_detect_jest(self,temp_dir,skill_context):
  with open(os.path.join(temp_dir,"jest.config.js"),"w") as f:
   f.write("module.exports = {}")
  skill=CodeTestSkill()
  detected=skill._detect_test_type(temp_dir)
  assert detected=="jest"


class TestCodeLintSkill:
 @pytest.mark.asyncio
 async def test_auto_detect_no_project(self,skill_context):
  skill=CodeLintSkill()
  result=await skill.execute(skill_context,lint_type="auto")
  assert not result.success
  assert"検出できません" in result.error

 @pytest.mark.asyncio
 async def test_detect_eslint(self,temp_dir,skill_context):
  with open(os.path.join(temp_dir,".eslintrc.json"),"w") as f:
   f.write("{}")
  skill=CodeLintSkill()
  detected=skill._detect_lint_type(temp_dir)
  assert detected=="eslint"

 @pytest.mark.asyncio
 async def test_detect_ruff(self,temp_dir,skill_context):
  with open(os.path.join(temp_dir,"ruff.toml"),"w") as f:
   f.write("")
  skill=CodeLintSkill()
  detected=skill._detect_lint_type(temp_dir)
  assert detected=="ruff"


class TestCodeSearchSkill:
 @pytest.mark.asyncio
 async def test_search_pattern(self,temp_dir,skill_context):
  with open(os.path.join(temp_dir,"test.py"),"w") as f:
   f.write("def hello():\n    print('hello')\n\ndef world():\n    print('world')")
  skill=CodeSearchSkill()
  result=await skill.execute(skill_context,pattern="def hello",file_pattern="*.py")
  assert result.success
  assert len(result.output)==1
  assert result.output[0]["line_no"]==1

 @pytest.mark.asyncio
 async def test_search_no_match(self,temp_dir,skill_context):
  with open(os.path.join(temp_dir,"test.py"),"w") as f:
   f.write("print('hello')")
  skill=CodeSearchSkill()
  result=await skill.execute(skill_context,pattern="nonexistent_pattern")
  assert result.success
  assert len(result.output)==0

 @pytest.mark.asyncio
 async def test_search_case_insensitive(self,temp_dir,skill_context):
  with open(os.path.join(temp_dir,"test.py"),"w") as f:
   f.write("HELLO = 'world'")
  skill=CodeSearchSkill()
  result=await skill.execute(skill_context,pattern="hello",case_sensitive=False)
  assert result.success
  assert len(result.output)==1


class TestFileSearchSkill:
 @pytest.mark.asyncio
 async def test_search_by_pattern(self,temp_dir,skill_context):
  Path(temp_dir,"test1.py").touch()
  Path(temp_dir,"test2.py").touch()
  Path(temp_dir,"other.txt").touch()
  skill=FileSearchSkill()
  result=await skill.execute(skill_context,pattern="*.py")
  assert result.success
  assert len(result.output)==2
  names=[f["name"] for f in result.output]
  assert"test1.py" in names
  assert"test2.py" in names

 @pytest.mark.asyncio
 async def test_search_recursive(self,temp_dir,skill_context):
  os.makedirs(os.path.join(temp_dir,"subdir"))
  Path(temp_dir,"top.py").touch()
  Path(temp_dir,"subdir","nested.py").touch()
  skill=FileSearchSkill()
  result=await skill.execute(skill_context,pattern="*.py")
  assert result.success
  assert len(result.output)==2

 @pytest.mark.asyncio
 async def test_search_no_match(self,temp_dir,skill_context):
  Path(temp_dir,"test.txt").touch()
  skill=FileSearchSkill()
  result=await skill.execute(skill_context,pattern="*.py")
  assert result.success
  assert len(result.output)==0


class TestWebFetchSkill:
 @pytest.mark.asyncio
 async def test_blocked_localhost(self,skill_context):
  skill=WebFetchSkill()
  result=await skill.execute(skill_context,url="http://localhost:8080/api")
  assert not result.success
  assert"blocked" in result.error.lower()

 @pytest.mark.asyncio
 async def test_blocked_private_ip(self,skill_context):
  skill=WebFetchSkill()
  result=await skill.execute(skill_context,url="http://192.168.1.1/admin")
  assert not result.success
  assert"blocked" in result.error.lower()

 @pytest.mark.asyncio
 async def test_invalid_url(self,skill_context):
  skill=WebFetchSkill()
  result=await skill.execute(skill_context,url="not-a-url")
  assert not result.success
  assert"http" in result.error.lower()

 @pytest.mark.asyncio
 async def test_missing_url(self,skill_context):
  skill=WebFetchSkill()
  result=await skill.execute(skill_context)
  assert not result.success
  assert"required" in result.error.lower()


class TestSkillRegistry:
 def test_register_and_get(self):
  registry=SkillRegistry()
  skill=FileReadSkill()
  registry.register(skill)
  assert registry.get("file_read") is skill

 def test_list_all(self):
  registry=get_skill_registry()
  skills=registry.list_all()
  assert len(skills)>=16
  names=registry.list_names()
  assert"file_read" in names
  assert"file_write" in names
  assert"bash_execute" in names
  assert"code_search" in names
  assert"web_fetch" in names

 def test_get_by_category(self):
  registry=get_skill_registry()
  file_skills=registry.get_by_category(SkillCategory.FILE)
  assert len(file_skills)>=3
  names=[s.name for s in file_skills]
  assert"file_read" in names


class TestSkillExecutor:
 @pytest.mark.asyncio
 async def test_execute_allowed_skill(self,temp_dir):
  config=SkillExecutionConfig(
   working_dir=temp_dir,
   allowed_skills=["file_read","file_write"],
   sandbox_enabled=True,
  )
  executor=SkillExecutor("proj","agent",config)
  test_file=os.path.join(temp_dir,"test.txt")
  with open(test_file,"w") as f:
   f.write("content")
  result=await executor.execute_skill("file_read",path="test.txt")
  assert result.success

 @pytest.mark.asyncio
 async def test_execute_disallowed_skill(self,temp_dir):
  config=SkillExecutionConfig(
   working_dir=temp_dir,
   allowed_skills=["file_read"],
   sandbox_enabled=True,
  )
  executor=SkillExecutor("proj","agent",config)
  result=await executor.execute_skill("bash_execute",command="echo test")
  assert not result.success
  assert"not allowed" in result.error.lower()

 def test_get_skill_schemas_for_llm(self,temp_dir):
  config=SkillExecutionConfig(
   working_dir=temp_dir,
   allowed_skills=["file_read","bash_execute"],
   sandbox_enabled=True,
  )
  executor=SkillExecutor("proj","agent",config)
  schemas=executor.get_skill_schemas_for_llm()
  assert len(schemas)==2
  names=[s["name"] for s in schemas]
  assert"file_read" in names
  assert"bash_execute" in names

 @pytest.mark.asyncio
 async def test_execution_history(self,temp_dir):
  config=SkillExecutionConfig(
   working_dir=temp_dir,
   allowed_skills=["file_read","file_write"],
   sandbox_enabled=True,
  )
  executor=SkillExecutor("proj","agent",config)
  await executor.execute_skill("file_write",path="test.txt",content="hello")
  await executor.execute_skill("file_read",path="test.txt")
  history=executor.get_execution_history()
  assert len(history)==2
  assert history[0]["skill"]=="file_write"
  assert history[1]["skill"]=="file_read"


class TestCreateSkillExecutor:
 def test_create_for_code_worker(self,temp_dir):
  executor=create_skill_executor(
   project_id="test",
   agent_id="agent1",
   agent_type="code_worker",
   working_dir=temp_dir,
  )
  skills=executor.get_available_skills()
  names=[s["name"] for s in skills]
  assert"file_read" in names
  assert"bash_execute" in names
  assert"code_build" in names

 def test_create_for_asset_worker(self,temp_dir):
  executor=create_skill_executor(
   project_id="test",
   agent_id="agent1",
   agent_type="asset_worker",
   working_dir=temp_dir,
  )
  skills=executor.get_available_skills()
  names=[s["name"] for s in skills]
  assert"file_read" in names
  assert"image_generate" in names
  assert"bash_execute" not in names
