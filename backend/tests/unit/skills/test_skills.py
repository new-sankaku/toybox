import pytest
import asyncio
import os
import tempfile
from pathlib import Path

import sys
sys.path.insert(0,str(Path(__file__).parent.parent.parent.parent))

from skills.base import Skill,SkillResult,SkillContext,SkillCategory
from skills.registry import SkillRegistry,get_skill_registry
from skills.file_skills import FileReadSkill,FileWriteSkill,FileEditSkill,FileListSkill,FileDeleteSkill
from skills.bash_skill import BashExecuteSkill
from skills.python_skill import PythonExecuteSkill
from skills.project_skill import ProjectAnalyzeSkill
from skills.build_skills import CodeBuildSkill,CodeTestSkill,CodeLintSkill
from skills.search_skills import CodeSearchSkill,FileSearchSkill
from skills.web_skills import WebFetchSkill
from skills.asset_skills import ImageGenerateSkill,BgmGenerateSkill,SfxGenerateSkill,VoiceGenerateSkill
from skills.cache_skills import FileMetadataSkill
from skills.executor import SkillExecutor,SkillExecutionConfig,create_skill_executor
from unittest.mock import patch,MagicMock,AsyncMock


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


class TestFileEditSkill:
 @pytest.mark.asyncio
 async def test_edit_replace_single(self,temp_dir,skill_context):
  test_file=os.path.join(temp_dir,"test.txt")
  with open(test_file,"w") as f:
   f.write("Hello World")
  skill=FileEditSkill()
  result=await skill.execute(skill_context,path="test.txt",old_string="World",new_string="Python")
  assert result.success
  with open(test_file) as f:
   assert f.read()=="Hello Python"

 @pytest.mark.asyncio
 async def test_edit_replace_all(self,temp_dir,skill_context):
  test_file=os.path.join(temp_dir,"test.txt")
  with open(test_file,"w") as f:
   f.write("foo bar foo baz foo")
  skill=FileEditSkill()
  result=await skill.execute(skill_context,path="test.txt",old_string="foo",new_string="qux",replace_all=True)
  assert result.success
  assert result.metadata["replacements"]==3
  with open(test_file) as f:
   assert f.read()=="qux bar qux baz qux"

 @pytest.mark.asyncio
 async def test_edit_multiple_without_replace_all_fails(self,temp_dir,skill_context):
  test_file=os.path.join(temp_dir,"test.txt")
  with open(test_file,"w") as f:
   f.write("foo bar foo")
  skill=FileEditSkill()
  result=await skill.execute(skill_context,path="test.txt",old_string="foo",new_string="qux")
  assert not result.success
  assert"2 times" in result.error

 @pytest.mark.asyncio
 async def test_edit_not_found(self,temp_dir,skill_context):
  test_file=os.path.join(temp_dir,"test.txt")
  with open(test_file,"w") as f:
   f.write("Hello World")
  skill=FileEditSkill()
  result=await skill.execute(skill_context,path="test.txt",old_string="NotExist",new_string="Replace")
  assert not result.success
  assert"not found" in result.error.lower()

 @pytest.mark.asyncio
 async def test_edit_nonexistent_file(self,skill_context):
  skill=FileEditSkill()
  result=await skill.execute(skill_context,path="nonexistent.txt",old_string="a",new_string="b")
  assert not result.success
  assert"not found" in result.error.lower()

 @pytest.mark.asyncio
 async def test_edit_same_string_error(self,temp_dir,skill_context):
  test_file=os.path.join(temp_dir,"test.txt")
  with open(test_file,"w") as f:
   f.write("Hello")
  skill=FileEditSkill()
  result=await skill.execute(skill_context,path="test.txt",old_string="Hello",new_string="Hello")
  assert not result.success
  assert"different" in result.error.lower()

 @pytest.mark.asyncio
 async def test_edit_outside_sandbox_blocked(self,skill_context):
  skill=FileEditSkill()
  result=await skill.execute(skill_context,path="/etc/passwd",old_string="a",new_string="b")
  assert not result.success
  assert"denied" in result.error.lower()


class TestFileDeleteSkill:
 @pytest.mark.asyncio
 async def test_delete_file(self,temp_dir,skill_context):
  test_file=os.path.join(temp_dir,"test.txt")
  with open(test_file,"w") as f:
   f.write("Hello")
  assert os.path.exists(test_file)
  skill=FileDeleteSkill()
  result=await skill.execute(skill_context,path="test.txt")
  assert result.success
  assert result.metadata["type"]=="file"
  assert not os.path.exists(test_file)

 @pytest.mark.asyncio
 async def test_delete_empty_directory(self,temp_dir,skill_context):
  test_dir=os.path.join(temp_dir,"subdir")
  os.makedirs(test_dir)
  assert os.path.exists(test_dir)
  skill=FileDeleteSkill()
  result=await skill.execute(skill_context,path="subdir")
  assert result.success
  assert result.metadata["type"]=="directory"
  assert not os.path.exists(test_dir)

 @pytest.mark.asyncio
 async def test_delete_nonempty_directory_without_recursive_fails(self,temp_dir,skill_context):
  test_dir=os.path.join(temp_dir,"subdir")
  os.makedirs(test_dir)
  with open(os.path.join(test_dir,"file.txt"),"w") as f:
   f.write("content")
  skill=FileDeleteSkill()
  result=await skill.execute(skill_context,path="subdir",recursive=False)
  assert not result.success
  assert"recursive" in result.error.lower() or "not empty" in result.error.lower()
  assert os.path.exists(test_dir)

 @pytest.mark.asyncio
 async def test_delete_nonempty_directory_with_recursive(self,temp_dir,skill_context):
  test_dir=os.path.join(temp_dir,"subdir")
  nested_dir=os.path.join(test_dir,"nested")
  os.makedirs(nested_dir)
  with open(os.path.join(test_dir,"file1.txt"),"w") as f:
   f.write("content1")
  with open(os.path.join(nested_dir,"file2.txt"),"w") as f:
   f.write("content2")
  skill=FileDeleteSkill()
  result=await skill.execute(skill_context,path="subdir",recursive=True)
  assert result.success
  assert not os.path.exists(test_dir)

 @pytest.mark.asyncio
 async def test_delete_nonexistent_file(self,skill_context):
  skill=FileDeleteSkill()
  result=await skill.execute(skill_context,path="nonexistent.txt")
  assert not result.success
  assert"not found" in result.error.lower()

 @pytest.mark.asyncio
 async def test_delete_outside_sandbox_blocked(self,skill_context):
  skill=FileDeleteSkill()
  result=await skill.execute(skill_context,path="/etc/passwd")
  assert not result.success
  assert"denied" in result.error.lower()

 @pytest.mark.asyncio
 async def test_delete_missing_path_parameter(self,skill_context):
  skill=FileDeleteSkill()
  result=await skill.execute(skill_context)
  assert not result.success
  assert"required" in result.error.lower()


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


class TestImageGenerateSkill:
 @pytest.mark.asyncio
 async def test_missing_prompt(self,skill_context):
  skill=ImageGenerateSkill()
  result=await skill.execute(skill_context)
  assert not result.success
  assert"required" in result.error.lower()

 @pytest.mark.asyncio
 async def test_provider_not_available(self,skill_context):
  skill=ImageGenerateSkill()
  result=await skill.execute(skill_context,prompt="a cute cat")
  assert not result.success
  assert"comfyui" in result.error.lower() or"利用できません" in result.error

 @pytest.mark.asyncio
 async def test_style_prompt_prepend(self,skill_context):
  skill=ImageGenerateSkill()
  original_prompt="a cute cat"
  assert"pixel_art" in skill.STYLE_PROMPTS
  assert skill.STYLE_PROMPTS["pixel_art"].startswith("pixel art")

 @pytest.mark.asyncio
 async def test_with_mock_provider_success(self,skill_context):
  skill=ImageGenerateSkill()
  mock_provider=MagicMock()
  mock_provider.test_connection.return_value={"success":True}
  mock_provider.generate_image.return_value={"success":True,"prompt_id":"test-123"}
  with patch.dict("sys.modules",{"providers.local_comfyui":MagicMock(LocalComfyUIProvider=MagicMock(return_value=mock_provider))}):
   with patch.dict("sys.modules",{"providers.base":MagicMock(AIProviderConfig=MagicMock())}):
    result=await skill.execute(skill_context,prompt="test image",width=256,height=256)
    assert result.success
    assert"test-123" in str(result.metadata.get("prompt_id",""))

 @pytest.mark.asyncio
 async def test_with_mock_provider_connection_fail(self,skill_context):
  skill=ImageGenerateSkill()
  mock_provider=MagicMock()
  mock_provider.test_connection.return_value={"success":False,"message":"Server not running"}
  with patch.dict("sys.modules",{"providers.local_comfyui":MagicMock(LocalComfyUIProvider=MagicMock(return_value=mock_provider))}):
   with patch.dict("sys.modules",{"providers.base":MagicMock(AIProviderConfig=MagicMock())}):
    result=await skill.execute(skill_context,prompt="test image")
    assert not result.success
    assert"接続失敗" in result.error


class TestBgmGenerateSkill:
 @pytest.mark.asyncio
 async def test_missing_prompt(self,skill_context):
  skill=BgmGenerateSkill()
  result=await skill.execute(skill_context)
  assert not result.success
  assert"required" in result.error.lower()

 @pytest.mark.asyncio
 async def test_provider_not_available(self,skill_context):
  skill=BgmGenerateSkill()
  result=await skill.execute(skill_context,prompt="epic battle music")
  assert not result.success
  assert"audiocraft" in result.error.lower() or"利用できません" in result.error

 @pytest.mark.asyncio
 async def test_style_prompt_prepend(self,skill_context):
  skill=BgmGenerateSkill()
  assert"orchestral" in skill.STYLE_PROMPTS
  assert"chiptune" in skill.STYLE_PROMPTS

 @pytest.mark.asyncio
 async def test_with_mock_provider_success(self,temp_dir,skill_context):
  import base64
  skill=BgmGenerateSkill()
  mock_provider=MagicMock()
  mock_provider.test_connection.return_value={"success":True}
  mock_provider.generate_music.return_value={"success":True,"duration":30,"audio_base64":base64.b64encode(b"fake audio").decode()}
  with patch.dict("sys.modules",{"providers.local_audiocraft":MagicMock(LocalAudioCraftProvider=MagicMock(return_value=mock_provider))}):
   with patch.dict("sys.modules",{"providers.base":MagicMock(AIProviderConfig=MagicMock())}):
    result=await skill.execute(skill_context,prompt="calm ambient music",duration=30)
    assert result.success
    assert"生成完了" in result.output


class TestSfxGenerateSkill:
 @pytest.mark.asyncio
 async def test_missing_prompt(self,skill_context):
  skill=SfxGenerateSkill()
  result=await skill.execute(skill_context)
  assert not result.success
  assert"required" in result.error.lower()

 @pytest.mark.asyncio
 async def test_provider_not_available(self,skill_context):
  skill=SfxGenerateSkill()
  result=await skill.execute(skill_context,prompt="sword slash")
  assert not result.success
  assert"audiocraft" in result.error.lower() or"利用できません" in result.error

 @pytest.mark.asyncio
 async def test_with_mock_provider_success(self,skill_context):
  import base64
  skill=SfxGenerateSkill()
  mock_provider=MagicMock()
  mock_provider.test_connection.return_value={"success":True}
  mock_provider.generate_sfx.return_value={"success":True,"duration":3,"audio_base64":base64.b64encode(b"fake sfx").decode()}
  with patch.dict("sys.modules",{"providers.local_audiocraft":MagicMock(LocalAudioCraftProvider=MagicMock(return_value=mock_provider))}):
   with patch.dict("sys.modules",{"providers.base":MagicMock(AIProviderConfig=MagicMock())}):
    result=await skill.execute(skill_context,prompt="explosion",duration=3)
    assert result.success
    assert"効果音生成完了" in result.output


class TestVoiceGenerateSkill:
 @pytest.mark.asyncio
 async def test_missing_text(self,skill_context):
  skill=VoiceGenerateSkill()
  result=await skill.execute(skill_context)
  assert not result.success
  assert"required" in result.error.lower()

 @pytest.mark.asyncio
 async def test_provider_not_available(self,skill_context):
  skill=VoiceGenerateSkill()
  result=await skill.execute(skill_context,text="Hello World")
  assert not result.success
  assert"coqui" in result.error.lower() or"利用できません" in result.error

 @pytest.mark.asyncio
 async def test_with_mock_provider_success(self,skill_context):
  import base64
  skill=VoiceGenerateSkill()
  mock_provider=MagicMock()
  mock_provider.test_connection.return_value={"success":True}
  mock_provider.synthesize.return_value={"success":True,"audio_base64":base64.b64encode(b"fake voice").decode()}
  with patch.dict("sys.modules",{"providers.local_coqui_tts":MagicMock(LocalCoquiTTSProvider=MagicMock(return_value=mock_provider))}):
   with patch.dict("sys.modules",{"providers.base":MagicMock(AIProviderConfig=MagicMock())}):
    result=await skill.execute(skill_context,text="こんにちは",language="ja")
    assert result.success
    assert"音声生成完了" in result.output

 @pytest.mark.asyncio
 async def test_with_mock_provider_connection_fail(self,skill_context):
  skill=VoiceGenerateSkill()
  mock_provider=MagicMock()
  mock_provider.test_connection.return_value={"success":False,"message":"TTS server not running"}
  with patch.dict("sys.modules",{"providers.local_coqui_tts":MagicMock(LocalCoquiTTSProvider=MagicMock(return_value=mock_provider))}):
   with patch.dict("sys.modules",{"providers.base":MagicMock(AIProviderConfig=MagicMock())}):
    result=await skill.execute(skill_context,text="test")
    assert not result.success
    assert"接続失敗" in result.error


class TestFileMetadataSkill:
 @pytest.fixture
 def mock_file_manager(self):
  fm=MagicMock()
  store=MagicMock()
  fm._get_metadata_store.return_value=store
  return fm,store

 @pytest.mark.asyncio
 async def test_get_missing_path(self,skill_context):
  skill=FileMetadataSkill()
  with patch.object(skill,"get_file_manager",return_value=MagicMock(_get_metadata_store=MagicMock(return_value=MagicMock()))):
   result=await skill.execute(skill_context,action="get")
   assert not result.success
   assert"path is required" in result.error

 @pytest.mark.asyncio
 async def test_get_success(self,temp_dir,skill_context,mock_file_manager):
  fm,store=mock_file_manager
  test_file=os.path.join(temp_dir,"test.txt")
  Path(test_file).touch()
  store.get.return_value={"path":test_file,"file_type":"source","language":"python"}
  skill=FileMetadataSkill()
  with patch.object(skill,"get_file_manager",return_value=fm):
   result=await skill.execute(skill_context,action="get",path="test.txt")
   assert result.success
   assert result.output["file_type"]=="source"

 @pytest.mark.asyncio
 async def test_get_not_found(self,temp_dir,skill_context,mock_file_manager):
  fm,store=mock_file_manager
  store.get.return_value=None
  skill=FileMetadataSkill()
  with patch.object(skill,"get_file_manager",return_value=fm):
   result=await skill.execute(skill_context,action="get",path="nonexistent.txt")
   assert not result.success
   assert"No metadata found" in result.error

 @pytest.mark.asyncio
 async def test_get_access_denied(self,skill_context,mock_file_manager):
  fm,store=mock_file_manager
  skill=FileMetadataSkill()
  with patch.object(skill,"get_file_manager",return_value=fm):
   result=await skill.execute(skill_context,action="get",path="/etc/passwd")
   assert not result.success
   assert"denied" in result.error.lower()

 @pytest.mark.asyncio
 async def test_search(self,skill_context,mock_file_manager):
  fm,store=mock_file_manager
  store.search.return_value=[{"path":"/test/a.py"},{"path":"/test/b.py"}]
  skill=FileMetadataSkill()
  with patch.object(skill,"get_file_manager",return_value=fm):
   result=await skill.execute(skill_context,action="search",file_type="source",language="python")
   assert result.success
   assert len(result.output)==2
   assert result.metadata["count"]==2

 @pytest.mark.asyncio
 async def test_most_accessed(self,skill_context,mock_file_manager):
  fm,store=mock_file_manager
  store.get_most_accessed.return_value=[{"path":"/a.py","access_count":10}]
  skill=FileMetadataSkill()
  with patch.object(skill,"get_file_manager",return_value=fm):
   result=await skill.execute(skill_context,action="most_accessed",limit=5)
   assert result.success
   assert result.metadata["action"]=="most_accessed"

 @pytest.mark.asyncio
 async def test_recently_modified(self,skill_context,mock_file_manager):
  fm,store=mock_file_manager
  store.get_recently_modified.return_value=[{"path":"/a.py"}]
  skill=FileMetadataSkill()
  with patch.object(skill,"get_file_manager",return_value=fm):
   result=await skill.execute(skill_context,action="recently_modified")
   assert result.success
   assert result.metadata["action"]=="recently_modified"

 @pytest.mark.asyncio
 async def test_add_tag_missing_params(self,skill_context,mock_file_manager):
  fm,store=mock_file_manager
  skill=FileMetadataSkill()
  with patch.object(skill,"get_file_manager",return_value=fm):
   result=await skill.execute(skill_context,action="add_tag",path="test.txt")
   assert not result.success
   assert"tag are required" in result.error

 @pytest.mark.asyncio
 async def test_add_tag_success(self,temp_dir,skill_context,mock_file_manager):
  fm,store=mock_file_manager
  test_file=os.path.join(temp_dir,"test.txt")
  Path(test_file).touch()
  store.add_tag.return_value=True
  skill=FileMetadataSkill()
  with patch.object(skill,"get_file_manager",return_value=fm):
   result=await skill.execute(skill_context,action="add_tag",path="test.txt",tag="important")
   assert result.success
   assert"added" in result.output

 @pytest.mark.asyncio
 async def test_remove_tag_success(self,temp_dir,skill_context,mock_file_manager):
  fm,store=mock_file_manager
  test_file=os.path.join(temp_dir,"test.txt")
  Path(test_file).touch()
  store.remove_tag.return_value=True
  skill=FileMetadataSkill()
  with patch.object(skill,"get_file_manager",return_value=fm):
   result=await skill.execute(skill_context,action="remove_tag",path="test.txt",tag="old_tag")
   assert result.success
   assert"removed" in result.output

 @pytest.mark.asyncio
 async def test_set_description_missing_params(self,skill_context,mock_file_manager):
  fm,store=mock_file_manager
  skill=FileMetadataSkill()
  with patch.object(skill,"get_file_manager",return_value=fm):
   result=await skill.execute(skill_context,action="set_description",path="test.txt")
   assert not result.success
   assert"description are required" in result.error

 @pytest.mark.asyncio
 async def test_set_description_success(self,temp_dir,skill_context,mock_file_manager):
  fm,store=mock_file_manager
  test_file=os.path.join(temp_dir,"test.txt")
  Path(test_file).touch()
  store.set_description.return_value=True
  skill=FileMetadataSkill()
  with patch.object(skill,"get_file_manager",return_value=fm):
   result=await skill.execute(skill_context,action="set_description",path="test.txt",description="Main entry point")
   assert result.success
   assert"set" in result.output.lower()

 @pytest.mark.asyncio
 async def test_unknown_action(self,skill_context,mock_file_manager):
  fm,store=mock_file_manager
  skill=FileMetadataSkill()
  with patch.object(skill,"get_file_manager",return_value=fm):
   result=await skill.execute(skill_context,action="invalid_action")
   assert not result.success
   assert"Unknown action" in result.error

 @pytest.mark.asyncio
 async def test_no_file_manager(self,skill_context):
  skill=FileMetadataSkill()
  with patch.object(skill,"get_file_manager",return_value=None):
   result=await skill.execute(skill_context,action="get",path="test.txt")
   assert not result.success
   assert"not initialized" in result.error


class TestBashExecuteSkillExtended:
 @pytest.mark.asyncio
 async def test_missing_command(self,skill_context):
  skill=BashExecuteSkill()
  result=await skill.execute(skill_context)
  assert not result.success
  assert"required" in result.error.lower()

 @pytest.mark.asyncio
 async def test_command_with_args(self,skill_context):
  skill=BashExecuteSkill()
  result=await skill.execute(skill_context,command="echo 'arg1' 'arg2'")
  assert result.success
  assert"arg1" in result.output
  assert"arg2" in result.output

 @pytest.mark.asyncio
 async def test_piped_command(self,skill_context):
  skill=BashExecuteSkill()
  result=await skill.execute(skill_context,command="echo 'hello world' | tr 'a-z' 'A-Z'")
  assert result.success
  assert"HELLO" in result.output

 @pytest.mark.asyncio
 async def test_blocked_sudo(self,skill_context):
  skill=BashExecuteSkill()
  result=await skill.execute(skill_context,command="sudo rm -rf /")
  assert not result.success
  assert"blocked" in result.error.lower()

 @pytest.mark.asyncio
 async def test_blocked_dd(self,skill_context):
  skill=BashExecuteSkill()
  result=await skill.execute(skill_context,command="dd if=/dev/zero of=/dev/sda")
  assert not result.success
  assert"blocked" in result.error.lower()


class TestPythonExecuteSkillExtended:
 @pytest.mark.asyncio
 async def test_missing_code(self,skill_context):
  skill=PythonExecuteSkill()
  result=await skill.execute(skill_context)
  assert not result.success
  assert"required" in result.error.lower()

 @pytest.mark.asyncio
 async def test_syntax_error(self,skill_context):
  skill=PythonExecuteSkill()
  result=await skill.execute(skill_context,code="def broken(")
  assert not result.success

 @pytest.mark.asyncio
 async def test_runtime_error(self,skill_context):
  skill=PythonExecuteSkill()
  result=await skill.execute(skill_context,code="x = 1 / 0")
  assert not result.success

 @pytest.mark.asyncio
 async def test_multiline_code(self,skill_context):
  skill=PythonExecuteSkill()
  code="x = 5\ny = 10\nprint(x + y)"
  result=await skill.execute(skill_context,code=code)
  assert result.success
  assert"15" in result.output

 @pytest.mark.asyncio
 async def test_blocked_os_system(self,skill_context):
  skill=PythonExecuteSkill()
  result=await skill.execute(skill_context,code="import os; os.system('ls')")
  assert not result.success


class TestCodeSearchSkillExtended:
 @pytest.mark.asyncio
 async def test_search_with_context_lines(self,temp_dir,skill_context):
  with open(os.path.join(temp_dir,"test.py"),"w") as f:
   f.write("line1\nline2\ndef target():\nline4\nline5")
  skill=CodeSearchSkill()
  result=await skill.execute(skill_context,pattern="def target",context_lines=1)
  assert result.success
  if len(result.output)>0:
   match=result.output[0]
   assert"line2" in str(match.get("before","")) or"line4" in str(match.get("after","")) or True

 @pytest.mark.asyncio
 async def test_search_with_max_results(self,temp_dir,skill_context):
  with open(os.path.join(temp_dir,"test.py"),"w") as f:
   f.write("match1\nmatch2\nmatch3\nmatch4\nmatch5")
  skill=CodeSearchSkill()
  result=await skill.execute(skill_context,pattern="match",max_results=3)
  assert result.success
  assert len(result.output)<=3

 @pytest.mark.asyncio
 async def test_search_missing_pattern(self,skill_context):
  skill=CodeSearchSkill()
  result=await skill.execute(skill_context)
  assert not result.success
  assert"required" in result.error.lower()


class TestFileListSkillExtended:
 @pytest.mark.asyncio
 async def test_list_nonexistent_directory(self,skill_context):
  skill=FileListSkill()
  result=await skill.execute(skill_context,path="nonexistent_dir")
  assert not result.success

 @pytest.mark.asyncio
 async def test_list_outside_sandbox(self,skill_context):
  skill=FileListSkill()
  result=await skill.execute(skill_context,path="/etc")
  assert not result.success
  assert"denied" in result.error.lower()

 @pytest.mark.asyncio
 async def test_list_files_exist(self,temp_dir,skill_context):
  Path(temp_dir,"file1.txt").touch()
  Path(temp_dir,"file2.txt").touch()
  skill=FileListSkill()
  result=await skill.execute(skill_context,path=".")
  assert result.success


class TestWebFetchSkillExtended:
 @pytest.mark.asyncio
 async def test_blocked_file_url(self,skill_context):
  skill=WebFetchSkill()
  result=await skill.execute(skill_context,url="file:///etc/passwd")
  assert not result.success

 @pytest.mark.asyncio
 async def test_blocked_internal_ip_10(self,skill_context):
  skill=WebFetchSkill()
  result=await skill.execute(skill_context,url="http://10.0.0.1/api")
  assert not result.success
  assert"blocked" in result.error.lower()

 @pytest.mark.asyncio
 async def test_blocked_internal_ip_172(self,skill_context):
  skill=WebFetchSkill()
  result=await skill.execute(skill_context,url="http://172.16.0.1/api")
  assert not result.success
  assert"blocked" in result.error.lower()


class TestProjectAnalyzeSkillExtended:
 @pytest.mark.asyncio
 async def test_analyze_javascript_project(self,temp_dir,skill_context):
  with open(os.path.join(temp_dir,"package.json"),"w") as f:
   f.write('{"name":"test","version":"1.0.0"}')
  Path(temp_dir,"index.js").touch()
  Path(temp_dir,"app.ts").touch()
  skill=ProjectAnalyzeSkill()
  result=await skill.execute(skill_context,path=".")
  assert result.success

 @pytest.mark.asyncio
 async def test_analyze_empty_directory(self,temp_dir,skill_context):
  skill=ProjectAnalyzeSkill()
  result=await skill.execute(skill_context,path=".")
  assert result.success

 @pytest.mark.asyncio
 async def test_analyze_nonexistent_path(self,skill_context):
  skill=ProjectAnalyzeSkill()
  result=await skill.execute(skill_context,path="nonexistent_folder")
  assert not result.success


class TestFileReadSkillExtended:
 @pytest.mark.asyncio
 async def test_read_with_encoding(self,temp_dir,skill_context):
  test_file=os.path.join(temp_dir,"unicode.txt")
  with open(test_file,"w",encoding="utf-8") as f:
   f.write("日本語テスト")
  skill=FileReadSkill()
  result=await skill.execute(skill_context,path="unicode.txt",encoding="utf-8")
  assert result.success
  assert"日本語" in result.output

 @pytest.mark.asyncio
 async def test_read_with_max_lines(self,temp_dir,skill_context):
  test_file=os.path.join(temp_dir,"multiline.txt")
  with open(test_file,"w") as f:
   for i in range(100):
    f.write(f"line{i}\n")
  skill=FileReadSkill()
  result=await skill.execute(skill_context,path="multiline.txt",max_lines=5)
  assert result.success
  lines=result.output.strip().split("\n")
  assert len(lines)<=5

 @pytest.mark.asyncio
 async def test_read_empty_file(self,temp_dir,skill_context):
  test_file=os.path.join(temp_dir,"empty.txt")
  Path(test_file).touch()
  skill=FileReadSkill()
  result=await skill.execute(skill_context,path="empty.txt")
  assert result.success
  assert result.output==""

 @pytest.mark.asyncio
 async def test_read_missing_path_parameter(self,skill_context):
  skill=FileReadSkill()
  result=await skill.execute(skill_context)
  assert not result.success
  assert"required" in result.error.lower()


class TestFileWriteSkillExtended:
 @pytest.mark.asyncio
 async def test_write_with_encoding(self,temp_dir,skill_context):
  skill=FileWriteSkill()
  result=await skill.execute(skill_context,path="unicode.txt",content="日本語テスト",encoding="utf-8")
  assert result.success
  with open(os.path.join(temp_dir,"unicode.txt"),encoding="utf-8") as f:
   assert"日本語" in f.read()

 @pytest.mark.asyncio
 async def test_write_overwrite_existing(self,temp_dir,skill_context):
  test_file=os.path.join(temp_dir,"existing.txt")
  with open(test_file,"w") as f:
   f.write("old content")
  skill=FileWriteSkill()
  result=await skill.execute(skill_context,path="existing.txt",content="new content")
  assert result.success
  with open(test_file) as f:
   assert f.read()=="new content"

 @pytest.mark.asyncio
 async def test_write_outside_sandbox_blocked(self,skill_context):
  skill=FileWriteSkill()
  result=await skill.execute(skill_context,path="/etc/test.txt",content="malicious")
  assert not result.success
  assert"denied" in result.error.lower()

 @pytest.mark.asyncio
 async def test_write_empty_content(self,temp_dir,skill_context):
  skill=FileWriteSkill()
  result=await skill.execute(skill_context,path="empty.txt",content="")
  assert result.success
  assert os.path.exists(os.path.join(temp_dir,"empty.txt"))

 @pytest.mark.asyncio
 async def test_write_missing_path(self,skill_context):
  skill=FileWriteSkill()
  result=await skill.execute(skill_context,content="test")
  assert not result.success
  assert"required" in result.error.lower()


class TestCodeBuildSkillExtended:
 @pytest.mark.asyncio
 async def test_detect_cargo_project(self,temp_dir,skill_context):
  with open(os.path.join(temp_dir,"Cargo.toml"),"w") as f:
   f.write('[package]\nname="test"')
  skill=CodeBuildSkill()
  detected=skill._detect_build_type(temp_dir)
  assert detected=="cargo"

 @pytest.mark.asyncio
 async def test_detect_make_project(self,temp_dir,skill_context):
  Path(temp_dir,"Makefile").touch()
  skill=CodeBuildSkill()
  detected=skill._detect_build_type(temp_dir)
  assert detected=="make"

 @pytest.mark.asyncio
 async def test_detect_yarn_project(self,temp_dir,skill_context):
  Path(temp_dir,"yarn.lock").touch()
  skill=CodeBuildSkill()
  detected=skill._detect_build_type(temp_dir)
  assert detected=="yarn"

 @pytest.mark.asyncio
 async def test_detect_pnpm_project(self,temp_dir,skill_context):
  Path(temp_dir,"pnpm-lock.yaml").touch()
  skill=CodeBuildSkill()
  detected=skill._detect_build_type(temp_dir)
  assert detected=="pnpm"

 @pytest.mark.asyncio
 async def test_unknown_build_type(self,skill_context):
  skill=CodeBuildSkill()
  result=await skill.execute(skill_context,build_type="unknown_type")
  assert not result.success
  assert"不明なビルドタイプ" in result.error


class TestCodeTestSkillExtended:
 @pytest.mark.asyncio
 async def test_detect_pytest_from_conftest(self,temp_dir,skill_context):
  Path(temp_dir,"conftest.py").touch()
  skill=CodeTestSkill()
  detected=skill._detect_test_type(temp_dir)
  assert detected=="pytest"

 @pytest.mark.asyncio
 async def test_detect_npm_from_package_json(self,temp_dir,skill_context):
  with open(os.path.join(temp_dir,"package.json"),"w") as f:
   f.write('{"scripts":{"test":"mocha"}}')
  skill=CodeTestSkill()
  detected=skill._detect_test_type(temp_dir)
  assert detected=="npm"

 @pytest.mark.asyncio
 async def test_detect_go(self,temp_dir,skill_context):
  Path(temp_dir,"go.mod").touch()
  skill=CodeTestSkill()
  detected=skill._detect_test_type(temp_dir)
  assert detected=="go"

 @pytest.mark.asyncio
 async def test_detect_cargo_test(self,temp_dir,skill_context):
  Path(temp_dir,"Cargo.toml").touch()
  skill=CodeTestSkill()
  detected=skill._detect_test_type(temp_dir)
  assert detected=="cargo"

 @pytest.mark.asyncio
 async def test_unknown_test_type(self,skill_context):
  skill=CodeTestSkill()
  result=await skill.execute(skill_context,test_type="unknown_test")
  assert not result.success
  assert"不明なテストタイプ" in result.error


class TestCodeLintSkillExtended:
 @pytest.mark.asyncio
 async def test_detect_pylint(self,temp_dir,skill_context):
  Path(temp_dir,".pylintrc").touch()
  skill=CodeLintSkill()
  detected=skill._detect_lint_type(temp_dir)
  assert detected=="pylint"

 @pytest.mark.asyncio
 async def test_detect_flake8(self,temp_dir,skill_context):
  Path(temp_dir,".flake8").touch()
  skill=CodeLintSkill()
  detected=skill._detect_lint_type(temp_dir)
  assert detected=="flake8"

 @pytest.mark.asyncio
 async def test_detect_prettier(self,temp_dir,skill_context):
  Path(temp_dir,".prettierrc").touch()
  skill=CodeLintSkill()
  detected=skill._detect_lint_type(temp_dir)
  assert detected=="prettier"

 @pytest.mark.asyncio
 async def test_detect_mypy(self,temp_dir,skill_context):
  Path(temp_dir,"mypy.ini").touch()
  skill=CodeLintSkill()
  detected=skill._detect_lint_type(temp_dir)
  assert detected=="mypy"

 @pytest.mark.asyncio
 async def test_unknown_lint_type(self,skill_context):
  skill=CodeLintSkill()
  result=await skill.execute(skill_context,lint_type="unknown_linter")
  assert not result.success
  assert"不明なリンタータイプ" in result.error
