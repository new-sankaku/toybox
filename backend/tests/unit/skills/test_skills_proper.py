"""
Skillsの適切なユニットテスト

各テストは以下を検証:
-入力→出力の正確性
-副作用（ファイル作成、キャッシュ更新等）
-メタデータの正確性
-エラー条件の正確なメッセージ
"""
import pytest
import os
import tempfile
from pathlib import Path
from unittest.mock import patch,MagicMock

import sys
sys.path.insert(0,str(Path(__file__).parent.parent.parent.parent))

from skills.base import SkillContext
from skills.file_skills import FileReadSkill,FileWriteSkill,FileEditSkill,FileListSkill,FileDeleteSkill
from skills.bash_skill import BashExecuteSkill
from skills.python_skill import PythonExecuteSkill


@pytest.fixture(autouse=True)
def reset_file_manager():
    """テスト間でFileManagerをリセット"""
    from skills.file_skills import FileSkillMixin
    FileSkillMixin.set_file_manager(None)
    yield
    FileSkillMixin.set_file_manager(None)


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def ctx(temp_dir):
    return SkillContext(
        project_id="test",
        agent_id="agent1",
        working_dir=temp_dir,
        sandbox_enabled=True,
        timeout_seconds=30,
        max_output_size=100000,
    )


class TestFileReadSkillDataVerification:
    """FileReadSkillが正しいデータを返すかを検証"""

    @pytest.mark.asyncio
    async def test_output_equals_file_content(self,temp_dir,ctx):
        """outputがファイルの実際の内容と一致するか"""
        content="line1\nline2\nline3"
        Path(temp_dir,"test.txt").write_text(content)
        skill=FileReadSkill()
        result=await skill.execute(ctx,path="test.txt")
        assert result.success
        assert result.output==content,"outputがファイル内容と一致しない"

    @pytest.mark.asyncio
    async def test_metadata_lines_count_correct(self,temp_dir,ctx):
        """metadata['lines']がファイルの行数と一致するか"""
        content="line1\nline2\nline3"
        Path(temp_dir,"test.txt").write_text(content)
        skill=FileReadSkill()
        result=await skill.execute(ctx,path="test.txt")
        assert result.metadata["lines"]==3,"行数が正しくない"

    @pytest.mark.asyncio
    async def test_metadata_size_correct(self,temp_dir,ctx):
        """metadata['size']がファイルサイズと一致するか"""
        content="hello world"
        Path(temp_dir,"test.txt").write_text(content)
        skill=FileReadSkill()
        result=await skill.execute(ctx,path="test.txt")
        expected_size=os.path.getsize(os.path.join(temp_dir,"test.txt"))
        assert result.metadata["size"]==expected_size,"ファイルサイズが正しくない"

    @pytest.mark.asyncio
    async def test_max_lines_truncates_output(self,temp_dir,ctx):
        """max_linesで指定した行数で切り詰められるか"""
        lines=[f"line{i}" for i in range(100)]
        Path(temp_dir,"test.txt").write_text("\n".join(lines))
        skill=FileReadSkill()
        result=await skill.execute(ctx,path="test.txt",max_lines=5)
        output_lines=result.output.strip().split("\n")
        assert len([l for l in output_lines if l.startswith("line")])<=5,"max_linesで切り詰められていない"

    @pytest.mark.asyncio
    async def test_metadata_truncated_true_when_truncated(self,temp_dir,ctx):
        """切り詰め時にmetadata['truncated']==Trueか"""
        lines=[f"line{i}" for i in range(100)]
        Path(temp_dir,"test.txt").write_text("\n".join(lines))
        skill=FileReadSkill()
        result=await skill.execute(ctx,path="test.txt",max_lines=5)
        assert result.metadata["truncated"]==True,"truncatedフラグが設定されていない"

    @pytest.mark.asyncio
    async def test_metadata_truncated_false_when_not_truncated(self,temp_dir,ctx):
        """切り詰め無しでmetadata['truncated']==Falseか"""
        Path(temp_dir,"test.txt").write_text("short")
        skill=FileReadSkill()
        result=await skill.execute(ctx,path="test.txt",max_lines=1000)
        assert result.metadata["truncated"]==False,"truncatedフラグが誤ってTrueになっている"

    @pytest.mark.asyncio
    async def test_utf8_content_preserved(self,temp_dir,ctx):
        """UTF-8の日本語が正しく読めるか"""
        content="日本語テスト\n한국어\n中文"
        Path(temp_dir,"unicode.txt").write_text(content,encoding="utf-8")
        skill=FileReadSkill()
        result=await skill.execute(ctx,path="unicode.txt",encoding="utf-8")
        assert result.output==content,"UTF-8内容が正しく読めていない"


class TestFileWriteSkillDataVerification:
    """FileWriteSkillが正しくファイルを作成するかを検証"""

    @pytest.mark.asyncio
    async def test_file_created_with_exact_content(self,temp_dir,ctx):
        """ファイルが正確な内容で作成されるか"""
        content="test content here"
        skill=FileWriteSkill()
        result=await skill.execute(ctx,path="output.txt",content=content)
        assert result.success
        actual=Path(temp_dir,"output.txt").read_text()
        assert actual==content,"ファイル内容が一致しない"

    @pytest.mark.asyncio
    async def test_metadata_size_equals_bytes(self,temp_dir,ctx):
        """metadata['size']がバイト数と一致するか"""
        content="hello"
        skill=FileWriteSkill()
        result=await skill.execute(ctx,path="test.txt",content=content)
        expected_bytes=len(content.encode("utf-8"))
        assert result.metadata["size"]==expected_bytes,"サイズがバイト数と一致しない"

    @pytest.mark.asyncio
    async def test_parent_directory_created(self,temp_dir,ctx):
        """親ディレクトリが作成されるか"""
        skill=FileWriteSkill()
        result=await skill.execute(ctx,path="subdir/nested/file.txt",content="test")
        assert result.success
        assert os.path.exists(os.path.join(temp_dir,"subdir","nested","file.txt")),"親ディレクトリが作成されていない"

    @pytest.mark.asyncio
    async def test_overwrites_existing_file(self,temp_dir,ctx):
        """既存ファイルを上書きするか"""
        path=Path(temp_dir,"existing.txt")
        path.write_text("old content")
        skill=FileWriteSkill()
        result=await skill.execute(ctx,path="existing.txt",content="new content")
        assert result.success
        assert path.read_text()=="new content","既存ファイルが上書きされていない"

    @pytest.mark.asyncio
    async def test_utf8_written_correctly(self,temp_dir,ctx):
        """UTF-8が正しく書き込まれるか"""
        content="日本語テスト"
        skill=FileWriteSkill()
        result=await skill.execute(ctx,path="unicode.txt",content=content,encoding="utf-8")
        assert result.success
        actual=Path(temp_dir,"unicode.txt").read_text(encoding="utf-8")
        assert actual==content,"UTF-8が正しく書き込まれていない"


class TestFileEditSkillDataVerification:
    """FileEditSkillが正しくファイルを編集するかを検証"""

    @pytest.mark.asyncio
    async def test_single_replacement_correct(self,temp_dir,ctx):
        """単一置換が正しく行われるか"""
        Path(temp_dir,"test.txt").write_text("hello world")
        skill=FileEditSkill()
        result=await skill.execute(ctx,path="test.txt",old_string="world",new_string="python")
        assert result.success
        actual=Path(temp_dir,"test.txt").read_text()
        assert actual=="hello python","置換結果が正しくない"

    @pytest.mark.asyncio
    async def test_metadata_replacements_count(self,temp_dir,ctx):
        """metadata['replacements']が正しいか"""
        Path(temp_dir,"test.txt").write_text("foo bar foo baz foo")
        skill=FileEditSkill()
        result=await skill.execute(ctx,path="test.txt",old_string="foo",new_string="qux",replace_all=True)
        assert result.metadata["replacements"]==3,"置換回数が正しくない"

    @pytest.mark.asyncio
    async def test_replace_all_changes_all_occurrences(self,temp_dir,ctx):
        """replace_all=Trueで全ての出現箇所が置換されるか"""
        Path(temp_dir,"test.txt").write_text("a-b-a-b-a")
        skill=FileEditSkill()
        result=await skill.execute(ctx,path="test.txt",old_string="a",new_string="X",replace_all=True)
        actual=Path(temp_dir,"test.txt").read_text()
        assert actual=="X-b-X-b-X","全ての出現箇所が置換されていない"

    @pytest.mark.asyncio
    async def test_error_when_multiple_matches_without_replace_all(self,temp_dir,ctx):
        """複数マッチでreplace_all=Falseの時のエラーメッセージ検証"""
        Path(temp_dir,"test.txt").write_text("foo bar foo")
        skill=FileEditSkill()
        result=await skill.execute(ctx,path="test.txt",old_string="foo",new_string="baz")
        assert not result.success
        assert"2 times" in result.error,"エラーメッセージに出現回数が含まれていない"

    @pytest.mark.asyncio
    async def test_file_unchanged_on_no_match(self,temp_dir,ctx):
        """マッチしない場合にファイルが変更されないか"""
        original="hello world"
        Path(temp_dir,"test.txt").write_text(original)
        skill=FileEditSkill()
        result=await skill.execute(ctx,path="test.txt",old_string="nonexistent",new_string="x")
        assert not result.success
        actual=Path(temp_dir,"test.txt").read_text()
        assert actual==original,"ファイルが変更されてしまっている"


class TestFileListSkillDataVerification:
    """FileListSkillが正しいファイル一覧を返すかを検証"""

    @pytest.mark.asyncio
    async def test_returns_all_files_in_directory(self,temp_dir,ctx):
        """ディレクトリ内の全ファイルが返されるか"""
        Path(temp_dir,"file1.txt").touch()
        Path(temp_dir,"file2.txt").touch()
        Path(temp_dir,"file3.py").touch()
        skill=FileListSkill()
        result=await skill.execute(ctx,path=".")
        names=[item["name"] for item in result.output]
        assert set(names)=={"file1.txt","file2.txt","file3.py"},"全ファイルが返されていない"

    @pytest.mark.asyncio
    async def test_pattern_filters_correctly(self,temp_dir,ctx):
        """パターンでフィルタリングされるか"""
        Path(temp_dir,"test1.py").touch()
        Path(temp_dir,"test2.py").touch()
        Path(temp_dir,"other.txt").touch()
        skill=FileListSkill()
        result=await skill.execute(ctx,path=".",pattern="*.py")
        names=[item["name"] for item in result.output]
        assert set(names)=={"test1.py","test2.py"},"パターンフィルタリングが正しくない"
        assert"other.txt" not in names,"フィルタされるべきファイルが含まれている"

    @pytest.mark.asyncio
    async def test_recursive_includes_subdirectory_files(self,temp_dir,ctx):
        """再帰検索でサブディレクトリのファイルが含まれるか"""
        Path(temp_dir,"top.txt").touch()
        subdir=Path(temp_dir,"subdir")
        subdir.mkdir()
        (subdir/"nested.txt").touch()
        skill=FileListSkill()
        result=await skill.execute(ctx,path=".",pattern="*.txt",recursive=True)
        paths=[item["path"] for item in result.output]
        assert any("top.txt" in p for p in paths),"トップレベルファイルがない"
        assert any("nested.txt" in p for p in paths),"ネストしたファイルがない"

    @pytest.mark.asyncio
    async def test_item_type_correct(self,temp_dir,ctx):
        """ファイルとディレクトリのtype区別が正しいか"""
        Path(temp_dir,"file.txt").touch()
        Path(temp_dir,"folder").mkdir()
        skill=FileListSkill()
        result=await skill.execute(ctx,path=".")
        items={item["name"]:item["type"] for item in result.output}
        assert items["file.txt"]=="file","ファイルのtypeが正しくない"
        assert items["folder"]=="directory","ディレクトリのtypeが正しくない"

    @pytest.mark.asyncio
    async def test_max_items_limits_output(self,temp_dir,ctx):
        """max_itemsで結果が制限されるか"""
        for i in range(20):
            Path(temp_dir,f"file{i}.txt").touch()
        skill=FileListSkill()
        result=await skill.execute(ctx,path=".",max_items=5)
        assert len(result.output)<=5,"max_itemsで制限されていない"
        assert result.metadata["truncated"]==True,"truncatedフラグが設定されていない"


class TestFileDeleteSkillDataVerification:
    """FileDeleteSkillが正しく削除するかを検証"""

    @pytest.mark.asyncio
    async def test_file_actually_deleted(self,temp_dir,ctx):
        """ファイルが実際に削除されるか"""
        path=Path(temp_dir,"todelete.txt")
        path.write_text("content")
        assert path.exists()
        skill=FileDeleteSkill()
        result=await skill.execute(ctx,path="todelete.txt")
        assert result.success
        assert not path.exists(),"ファイルが削除されていない"

    @pytest.mark.asyncio
    async def test_empty_directory_deleted(self,temp_dir,ctx):
        """空ディレクトリが削除されるか"""
        path=Path(temp_dir,"emptydir")
        path.mkdir()
        skill=FileDeleteSkill()
        result=await skill.execute(ctx,path="emptydir")
        assert result.success
        assert not path.exists(),"空ディレクトリが削除されていない"

    @pytest.mark.asyncio
    async def test_recursive_deletes_nonempty_directory(self,temp_dir,ctx):
        """recursive=Trueで非空ディレクトリが削除されるか"""
        dirpath=Path(temp_dir,"nonempty")
        dirpath.mkdir()
        (dirpath/"file1.txt").write_text("a")
        (dirpath/"subdir").mkdir()
        (dirpath/"subdir"/"file2.txt").write_text("b")
        skill=FileDeleteSkill()
        result=await skill.execute(ctx,path="nonempty",recursive=True)
        assert result.success
        assert not dirpath.exists(),"非空ディレクトリが削除されていない"

    @pytest.mark.asyncio
    async def test_nonempty_without_recursive_fails(self,temp_dir,ctx):
        """非空ディレクトリでrecursive=Falseが失敗するか"""
        dirpath=Path(temp_dir,"nonempty")
        dirpath.mkdir()
        (dirpath/"file.txt").write_text("content")
        skill=FileDeleteSkill()
        result=await skill.execute(ctx,path="nonempty",recursive=False)
        assert not result.success,"非空ディレクトリがrecursive=Falseで成功してしまっている"
        assert dirpath.exists(),"ディレクトリが削除されてしまっている"

    @pytest.mark.asyncio
    async def test_metadata_type_correct(self,temp_dir,ctx):
        """metadata['type']が正しいか"""
        Path(temp_dir,"file.txt").touch()
        skill=FileDeleteSkill()
        result=await skill.execute(ctx,path="file.txt")
        assert result.metadata["type"]=="file","metadata['type']が正しくない"


class TestBashExecuteSkillBlockedPatterns:
    """BashExecuteSkillのブロックパターンを網羅的に検証"""

    @pytest.mark.asyncio
    async def test_blocked_rm_rf_root(self,ctx):
        """'rm -rf /'がブロックされるか"""
        skill=BashExecuteSkill()
        result=await skill.execute(ctx,command="rm -rf /")
        assert not result.success
        assert"blocked" in result.error.lower()

    @pytest.mark.asyncio
    async def test_blocked_rm_rf_root_star(self,ctx):
        """'rm -rf /*'がブロックされるか"""
        skill=BashExecuteSkill()
        result=await skill.execute(ctx,command="rm -rf /*")
        assert not result.success
        assert"blocked" in result.error.lower()

    @pytest.mark.asyncio
    async def test_blocked_sudo_prefix(self,ctx):
        """'sudo 'で始まるコマンドがブロックされるか"""
        skill=BashExecuteSkill()
        result=await skill.execute(ctx,command="sudo apt update")
        assert not result.success
        assert"blocked" in result.error.lower()

    @pytest.mark.asyncio
    async def test_blocked_dd_devzero(self,ctx):
        """'dd if=/dev/zero'がブロックされるか"""
        skill=BashExecuteSkill()
        result=await skill.execute(ctx,command="dd if=/dev/zero of=/dev/sda")
        assert not result.success
        assert"blocked" in result.error.lower()

    @pytest.mark.asyncio
    async def test_blocked_mkfs(self,ctx):
        """'mkfs'がブロックされるか"""
        skill=BashExecuteSkill()
        result=await skill.execute(ctx,command="mkfs.ext4 /dev/sda1")
        assert not result.success
        assert"blocked" in result.error.lower()

    @pytest.mark.asyncio
    async def test_blocked_fork_bomb(self,ctx):
        """フォーク爆弾がブロックされるか"""
        skill=BashExecuteSkill()
        result=await skill.execute(ctx,command=":(){ :|:& };:")
        assert not result.success
        assert"blocked" in result.error.lower()

    @pytest.mark.asyncio
    async def test_blocked_chmod_777_root(self,ctx):
        """'chmod -R 777 /'がブロックされるか（パターン完全一致）"""
        skill=BashExecuteSkill()
        result=await skill.execute(ctx,command="chmod -R 777 /")
        assert not result.success
        assert"blocked" in result.error.lower() or"dangerous" in result.error.lower()

    @pytest.mark.asyncio
    async def test_blocked_pipe_sudo(self,ctx):
        """'| sudo'パイプがブロックされるか"""
        skill=BashExecuteSkill()
        result=await skill.execute(ctx,command="echo test | sudo tee /etc/passwd")
        assert not result.success
        assert"blocked" in result.error.lower()

    @pytest.mark.asyncio
    async def test_blocked_curl_pipe_bash_exact(self,ctx):
        """'curl | bash'パターンがブロックされるか（パターン完全一致）"""
        skill=BashExecuteSkill()
        result=await skill.execute(ctx,command="curl | bash")
        assert not result.success
        assert"blocked" in result.error.lower() or"dangerous" in result.error.lower()

    @pytest.mark.asyncio
    async def test_blocked_wget_pipe_sh(self,ctx):
        """'wget | sh'パターンがブロックされるか"""
        skill=BashExecuteSkill()
        result=await skill.execute(ctx,command="wget | sh")
        assert not result.success
        assert"blocked" in result.error.lower() or"dangerous" in result.error.lower()


class TestBashExecuteSkillOutputVerification:
    """BashExecuteSkillの出力検証"""

    @pytest.mark.asyncio
    async def test_stdout_captured(self,ctx):
        """stdoutが正しくキャプチャされるか"""
        skill=BashExecuteSkill()
        result=await skill.execute(ctx,command="echo 'hello world'")
        assert result.success
        assert"hello world" in result.output,"stdoutがキャプチャされていない"

    @pytest.mark.asyncio
    async def test_return_code_zero_on_success(self,ctx):
        """成功時にreturn_code==0か"""
        skill=BashExecuteSkill()
        result=await skill.execute(ctx,command="echo test")
        assert result.metadata["return_code"]==0,"return_codeが0でない"

    @pytest.mark.asyncio
    async def test_return_code_nonzero_on_failure(self,ctx):
        """失敗時にreturn_code!=0か"""
        skill=BashExecuteSkill()
        result=await skill.execute(ctx,command="exit 42")
        assert not result.success
        assert result.metadata["return_code"]==42,"return_codeが正しくない"

    @pytest.mark.asyncio
    async def test_stderr_in_error_on_failure(self,ctx):
        """失敗時にstderrがerrorに含まれるか"""
        skill=BashExecuteSkill()
        result=await skill.execute(ctx,command="ls /nonexistent_path_12345")
        assert not result.success
        assert"No such file" in result.error or"cannot access" in result.error,"stderrがerrorに含まれていない"


class TestPythonExecuteSkillOutputVerification:
    """PythonExecuteSkillの出力検証"""

    @pytest.mark.asyncio
    async def test_print_output_captured(self,ctx):
        """print出力がキャプチャされるか"""
        skill=PythonExecuteSkill()
        result=await skill.execute(ctx,code="print('hello')")
        assert result.success
        assert"hello" in result.output,"print出力がキャプチャされていない"

    @pytest.mark.asyncio
    async def test_expression_result_captured(self,ctx):
        """式の結果がキャプチャされるか"""
        skill=PythonExecuteSkill()
        result=await skill.execute(ctx,code="print(2 + 3)")
        assert result.success
        assert"5" in result.output,"式の結果がキャプチャされていない"

    @pytest.mark.asyncio
    async def test_syntax_error_message(self,ctx):
        """構文エラーメッセージが含まれるか"""
        skill=PythonExecuteSkill()
        result=await skill.execute(ctx,code="def broken(")
        assert not result.success
        assert"SyntaxError" in result.error or"syntax" in result.error.lower(),"構文エラーメッセージがない"

    @pytest.mark.asyncio
    async def test_runtime_error_message(self,ctx):
        """実行時エラーメッセージが含まれるか"""
        skill=PythonExecuteSkill()
        result=await skill.execute(ctx,code="1/0")
        assert not result.success
        assert"ZeroDivision" in result.error or"division" in result.error.lower(),"実行時エラーメッセージがない"


class TestSandboxEnforcement:
    """サンドボックス制約の検証"""

    @pytest.mark.asyncio
    async def test_read_outside_sandbox_denied(self,ctx):
        """サンドボックス外の読み取りが拒否されるか"""
        skill=FileReadSkill()
        result=await skill.execute(ctx,path="/etc/passwd")
        assert not result.success
        assert"denied" in result.error.lower(),"サンドボックス外読み取りが拒否されていない"

    @pytest.mark.asyncio
    async def test_write_outside_sandbox_denied(self,ctx):
        """サンドボックス外の書き込みが拒否されるか"""
        skill=FileWriteSkill()
        result=await skill.execute(ctx,path="/tmp/outside.txt",content="test")
        assert not result.success
        assert"denied" in result.error.lower(),"サンドボックス外書き込みが拒否されていない"

    @pytest.mark.asyncio
    async def test_delete_outside_sandbox_denied(self,ctx):
        """サンドボックス外の削除が拒否されるか"""
        skill=FileDeleteSkill()
        result=await skill.execute(ctx,path="/etc/passwd")
        assert not result.success
        assert"denied" in result.error.lower(),"サンドボックス外削除が拒否されていない"

    @pytest.mark.asyncio
    async def test_list_outside_sandbox_denied(self,ctx):
        """サンドボックス外のリストが拒否されるか"""
        skill=FileListSkill()
        result=await skill.execute(ctx,path="/etc")
        assert not result.success
        assert"denied" in result.error.lower(),"サンドボックス外リストが拒否されていない"

    @pytest.mark.asyncio
    async def test_traversal_attack_blocked(self,ctx):
        """パストラバーサル攻撃が防がれるか"""
        skill=FileReadSkill()
        result=await skill.execute(ctx,path="../../../etc/passwd")
        assert not result.success
        assert"denied" in result.error.lower(),"パストラバーサルが防がれていない"


class TestCacheIntegration:
    """キャッシュ連携の検証

    FileManagerを使用した場合に:
    -読み込み時にfrom_cache==Trueが返るか
    -書き込み後にキャッシュに反映されるか
    を検証する
    """

    @pytest.fixture
    def clear_global_caches(self):
        """テスト間でグローバルキャッシュをクリア"""
        import cache.file_manager as fm_module
        fm_module._project_caches.clear()
        fm_module._project_watchers.clear()
        fm_module._project_metadata_stores.clear()
        yield
        fm_module._project_caches.clear()
        fm_module._project_watchers.clear()
        fm_module._project_metadata_stores.clear()

    @pytest.fixture
    def file_manager(self,temp_dir,clear_global_caches):
        """FileManagerインスタンスを作成"""
        from cache import FileManager
        fm=FileManager(project_id="test_cache_project",working_dir=temp_dir)
        fm.initialize()
        return fm

    @pytest.fixture
    def ctx_with_cache(self,temp_dir,file_manager):
        """キャッシュ付きのコンテキストを設定"""
        from skills.file_skills import FileSkillMixin
        FileSkillMixin.set_file_manager(file_manager)
        ctx=SkillContext(
            project_id="test",
            agent_id="agent1",
            working_dir=temp_dir,
            sandbox_enabled=True,
            timeout_seconds=30,
            max_output_size=100000,
        )
        yield ctx
        FileSkillMixin.set_file_manager(None)

    @pytest.mark.asyncio
    async def test_read_sets_from_cache_false_on_first_read(self,temp_dir,ctx_with_cache):
        """初回読み込み時にfrom_cache==Falseか"""
        content="test content for cache"
        Path(temp_dir,"cached.txt").write_text(content)
        skill=FileReadSkill()
        result=await skill.execute(ctx_with_cache,path="cached.txt")
        assert result.success
        assert result.output==content
        assert result.metadata.get("from_cache")==False,"初回読み込みでfrom_cacheがFalseでない"

    @pytest.mark.asyncio
    async def test_read_sets_from_cache_true_on_second_read(self,temp_dir,ctx_with_cache):
        """2回目読み込み時にfrom_cache==Trueか"""
        content="test content for cache hit"
        Path(temp_dir,"cached2.txt").write_text(content)
        skill=FileReadSkill()
        result1=await skill.execute(ctx_with_cache,path="cached2.txt")
        assert result1.success
        result2=await skill.execute(ctx_with_cache,path="cached2.txt")
        assert result2.success
        assert result2.output==content
        assert result2.metadata.get("from_cache")==True,"2回目読み込みでfrom_cacheがTrueでない"

    @pytest.mark.asyncio
    async def test_write_updates_cache(self,temp_dir,ctx_with_cache,file_manager):
        """書き込み後にキャッシュが更新されるか"""
        skill_write=FileWriteSkill()
        skill_read=FileReadSkill()
        content="written and cached"
        result=await skill_write.execute(ctx_with_cache,path="newfile.txt",content=content)
        assert result.success
        result2=await skill_read.execute(ctx_with_cache,path="newfile.txt")
        assert result2.success
        assert result2.output==content,"書き込み後の読み込みで内容が一致しない"
        assert result2.metadata.get("from_cache")==True,"書き込み後の読み込みでキャッシュがヒットしない"

    @pytest.mark.asyncio
    async def test_edit_updates_cache(self,temp_dir,ctx_with_cache):
        """編集後にキャッシュが更新されるか"""
        Path(temp_dir,"edit_cache.txt").write_text("hello world")
        skill_edit=FileEditSkill()
        skill_read=FileReadSkill()
        result=await skill_edit.execute(ctx_with_cache,path="edit_cache.txt",old_string="world",new_string="cache")
        assert result.success
        result2=await skill_read.execute(ctx_with_cache,path="edit_cache.txt")
        assert result2.success
        assert result2.output=="hello cache","編集後の内容が正しくない"
        assert result2.metadata.get("from_cache")==True,"編集後の読み込みでキャッシュがヒットしない"

    @pytest.mark.asyncio
    async def test_delete_removes_from_cache(self,temp_dir,ctx_with_cache,file_manager):
        """削除後にキャッシュから除去されるか"""
        path=Path(temp_dir,"to_delete_cache.txt")
        path.write_text("will be deleted")
        skill_read=FileReadSkill()
        result1=await skill_read.execute(ctx_with_cache,path="to_delete_cache.txt")
        assert result1.success
        skill_delete=FileDeleteSkill()
        result2=await skill_delete.execute(ctx_with_cache,path="to_delete_cache.txt")
        assert result2.success
        cache=file_manager._get_cache()
        full_path=os.path.join(temp_dir,"to_delete_cache.txt")
        cached_entry=cache.get_file(full_path)
        assert cached_entry is None,"削除後にキャッシュにファイルが残っている"

    @pytest.mark.asyncio
    async def test_cache_content_equals_file_content(self,temp_dir,ctx_with_cache,file_manager):
        """キャッシュの内容がファイル内容と一致するか"""
        content="exact content verification"
        Path(temp_dir,"verify.txt").write_text(content)
        skill=FileReadSkill()
        await skill.execute(ctx_with_cache,path="verify.txt")
        cache=file_manager._get_cache()
        cached_content=cache.get_file_content("verify.txt")
        assert cached_content is not None,"キャッシュにファイルがない"
        assert cached_content==content,"キャッシュの内容がファイル内容と一致しない"

    @pytest.mark.asyncio
    async def test_cache_metadata_accurate(self,temp_dir,ctx_with_cache,file_manager):
        """キャッシュのメタデータが正確か"""
        content="metadata test"
        path=Path(temp_dir,"meta.txt")
        path.write_text(content)
        full_path=os.path.join(temp_dir,"meta.txt")
        skill=FileReadSkill()
        await skill.execute(ctx_with_cache,path="meta.txt")
        cache=file_manager._get_cache()
        cached=cache.get_file("meta.txt")
        assert cached is not None,"キャッシュにファイルがない"
        assert cached.size==os.path.getsize(full_path),"キャッシュのサイズが実際のサイズと一致しない"
