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


class TestSkillRegistry:
 def test_register_and_get(self):
  registry=SkillRegistry()
  skill=FileReadSkill()
  registry.register(skill)
  assert registry.get("file_read") is skill

 def test_list_all(self):
  registry=get_skill_registry()
  skills=registry.list_all()
  assert len(skills)>=6
  names=registry.list_names()
  assert"file_read" in names
  assert"file_write" in names
  assert"bash_execute" in names


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
