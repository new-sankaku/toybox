import pytest
import asyncio
import os
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock,patch,AsyncMock

import sys
sys.path.insert(0,str(Path(__file__).parent.parent.parent.parent))


@pytest.fixture(autouse=True)
def clear_global_caches():
    import cache.file_manager as fm_module
    fm_module._project_caches.clear()
    fm_module._project_watchers.clear()
    fm_module._project_metadata_stores.clear()
    yield
    fm_module._project_caches.clear()
    fm_module._project_watchers.clear()
    fm_module._project_metadata_stores.clear()


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def mock_config():
    config=MagicMock()
    config.enabled=True
    config.content_max_size_bytes=1024*1024*100
    config.max_file_size_bytes=1024*1024*10
    config.binary_extensions=[".png",".jpg"]
    config.ignore_dirs=["node_modules","__pycache__"]
    config.watcher_enabled=False
    config.track_access_stats=False
    return config


class TestFileManagerDeleteFile:
    @pytest.mark.asyncio
    async def test_delete_file_success(self,temp_dir,mock_config):
        with patch("cache.file_manager.get_file_cache_config",return_value=mock_config):
            from cache.file_manager import FileManager
            fm=FileManager("test-project",temp_dir)
            test_file=os.path.join(temp_dir,"test.txt")
            with open(test_file,"w") as f:
                f.write("content")
            result=await fm.delete_file(test_file)
            assert result["success"]
            assert result["type"]=="file"
            assert not os.path.exists(test_file)

    @pytest.mark.asyncio
    async def test_delete_empty_directory(self,temp_dir,mock_config):
        with patch("cache.file_manager.get_file_cache_config",return_value=mock_config):
            from cache.file_manager import FileManager
            fm=FileManager("test-project",temp_dir)
            test_dir=os.path.join(temp_dir,"subdir")
            os.makedirs(test_dir)
            result=await fm.delete_file(test_dir)
            assert result["success"]
            assert result["type"]=="directory"
            assert not os.path.exists(test_dir)

    @pytest.mark.asyncio
    async def test_delete_nonempty_directory_without_recursive(self,temp_dir,mock_config):
        with patch("cache.file_manager.get_file_cache_config",return_value=mock_config):
            from cache.file_manager import FileManager
            fm=FileManager("test-project",temp_dir)
            test_dir=os.path.join(temp_dir,"subdir")
            os.makedirs(test_dir)
            with open(os.path.join(test_dir,"file.txt"),"w") as f:
                f.write("content")
            result=await fm.delete_file(test_dir,recursive=False)
            assert not result["success"]
            assert os.path.exists(test_dir)

    @pytest.mark.asyncio
    async def test_delete_nonempty_directory_with_recursive(self,temp_dir,mock_config):
        with patch("cache.file_manager.get_file_cache_config",return_value=mock_config):
            from cache.file_manager import FileManager
            fm=FileManager("test-project",temp_dir)
            test_dir=os.path.join(temp_dir,"subdir")
            nested=os.path.join(test_dir,"nested")
            os.makedirs(nested)
            with open(os.path.join(test_dir,"file1.txt"),"w") as f:
                f.write("1")
            with open(os.path.join(nested,"file2.txt"),"w") as f:
                f.write("2")
            result=await fm.delete_file(test_dir,recursive=True)
            assert result["success"]
            assert not os.path.exists(test_dir)

    @pytest.mark.asyncio
    async def test_delete_nonexistent_file(self,temp_dir,mock_config):
        with patch("cache.file_manager.get_file_cache_config",return_value=mock_config):
            from cache.file_manager import FileManager
            fm=FileManager("test-project",temp_dir)
            result=await fm.delete_file(os.path.join(temp_dir,"nonexistent.txt"))
            assert not result["success"]
            assert"not found" in result["error"].lower()


class TestFileManagerWithCache:
    @pytest.mark.asyncio
    async def test_delete_removes_from_cache(self,temp_dir,mock_config):
        with patch("cache.file_manager.get_file_cache_config",return_value=mock_config):
            from cache.file_manager import FileManager
            fm=FileManager("test-project",temp_dir)
            test_file=os.path.join(temp_dir,"test.txt")
            with open(test_file,"w") as f:
                f.write("content")
            fm.initialize()
            cache=fm._get_cache()
            assert cache.get_file_content("test.txt") is not None
            await fm.delete_file(test_file)
            assert cache.get_file_content("test.txt") is None

    @pytest.mark.asyncio
    async def test_delete_directory_removes_all_files_from_cache(self,temp_dir,mock_config):
        with patch("cache.file_manager.get_file_cache_config",return_value=mock_config):
            from cache.file_manager import FileManager
            fm=FileManager("test-project",temp_dir)
            test_dir=os.path.join(temp_dir,"subdir")
            os.makedirs(test_dir)
            with open(os.path.join(test_dir,"file1.txt"),"w") as f:
                f.write("1")
            with open(os.path.join(test_dir,"file2.txt"),"w") as f:
                f.write("2")
            fm.initialize()
            cache=fm._get_cache()
            assert cache.get_file_content("subdir/file1.txt") is not None
            assert cache.get_file_content("subdir/file2.txt") is not None
            await fm.delete_file(test_dir,recursive=True)
            assert cache.get_file_content("subdir/file1.txt") is None
            assert cache.get_file_content("subdir/file2.txt") is None


class TestFileManagerReadFile:
    @pytest.mark.asyncio
    async def test_read_from_cache(self,temp_dir,mock_config):
        with patch("cache.file_manager.get_file_cache_config",return_value=mock_config):
            from cache.file_manager import FileManager
            fm=FileManager("test-project",temp_dir)
            test_file=os.path.join(temp_dir,"test.txt")
            with open(test_file,"w") as f:
                f.write("cached content")
            fm.initialize()
            result=await fm.read_file(test_file)
            assert result["success"]
            assert result["content"]=="cached content"
            assert result["from_cache"]==True

    @pytest.mark.asyncio
    async def test_read_with_max_lines(self,temp_dir,mock_config):
        with patch("cache.file_manager.get_file_cache_config",return_value=mock_config):
            from cache.file_manager import FileManager
            fm=FileManager("test-project",temp_dir)
            test_file=os.path.join(temp_dir,"test.txt")
            with open(test_file,"w") as f:
                f.write("\n".join([f"line{i}" for i in range(100)]))
            fm.initialize()
            result=await fm.read_file(test_file,max_lines=5)
            assert result["success"]
            lines=result["content"].split("\n")
            assert len(lines)==5


class TestFileManagerWriteFile:
    @pytest.mark.asyncio
    async def test_write_updates_cache(self,temp_dir,mock_config):
        with patch("cache.file_manager.get_file_cache_config",return_value=mock_config):
            from cache.file_manager import FileManager
            fm=FileManager("test-project",temp_dir)
            fm.initialize()
            test_file=os.path.join(temp_dir,"new.txt")
            result=await fm.write_file(test_file,"new content")
            assert result["success"]
            cache=fm._get_cache()
            assert cache.get_file_content("new.txt")=="new content"

    @pytest.mark.asyncio
    async def test_write_creates_parent_directories(self,temp_dir,mock_config):
        with patch("cache.file_manager.get_file_cache_config",return_value=mock_config):
            from cache.file_manager import FileManager
            fm=FileManager("test-project",temp_dir)
            fm.initialize()
            test_file=os.path.join(temp_dir,"subdir","nested","file.txt")
            result=await fm.write_file(test_file,"nested content")
            assert result["success"]
            assert os.path.exists(test_file)


class TestFileManagerEditFile:
    @pytest.mark.asyncio
    async def test_edit_updates_cache(self,temp_dir,mock_config):
        with patch("cache.file_manager.get_file_cache_config",return_value=mock_config):
            from cache.file_manager import FileManager
            fm=FileManager("test-project",temp_dir)
            test_file=os.path.join(temp_dir,"test.txt")
            with open(test_file,"w") as f:
                f.write("Hello World")
            fm.initialize()
            result=await fm.edit_file(test_file,"World","Python")
            assert result["success"]
            cache=fm._get_cache()
            assert cache.get_file_content("test.txt")=="Hello Python"


class TestFileManagerSearch:
    def test_search_files(self,temp_dir,mock_config):
        with patch("cache.file_manager.get_file_cache_config",return_value=mock_config):
            from cache.file_manager import FileManager
            fm=FileManager("test-project",temp_dir)
            with open(os.path.join(temp_dir,"test1.py"),"w") as f:
                f.write("code")
            with open(os.path.join(temp_dir,"test2.py"),"w") as f:
                f.write("code")
            fm.initialize()
            results=fm.search_files("*.py")
            assert len(results)==2

    def test_search_content(self,temp_dir,mock_config):
        with patch("cache.file_manager.get_file_cache_config",return_value=mock_config):
            from cache.file_manager import FileManager
            fm=FileManager("test-project",temp_dir)
            with open(os.path.join(temp_dir,"test.py"),"w") as f:
                f.write("def hello():\n    pass")
            fm.initialize()
            results=fm.search_content("def hello")
            assert len(results)==1


class TestFileManagerInitialize:
    def test_initialize_loads_cache(self,temp_dir,mock_config):
        with patch("cache.file_manager.get_file_cache_config",return_value=mock_config):
            from cache.file_manager import FileManager
            fm=FileManager("test-project",temp_dir)
            with open(os.path.join(temp_dir,"test.txt"),"w") as f:
                f.write("content")
            stats=fm.initialize()
            assert stats["files"]==1
            cache=fm._get_cache()
            assert cache.is_loaded

    def test_initialize_disabled_config(self,temp_dir,mock_config):
        mock_config.enabled=False
        with patch("cache.file_manager.get_file_cache_config",return_value=mock_config):
            from cache.file_manager import FileManager
            fm=FileManager("test-project",temp_dir)
            result=fm.initialize()
            assert result=={"enabled":False}
