import pytest
import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock,patch

import sys
sys.path.insert(0,str(Path(__file__).parent.parent.parent.parent))

from cache.content_cache import ProjectFileCache,FileEntry,DirEntry
from cache.config import FileCacheConfig


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def mock_config():
    config=MagicMock(spec=FileCacheConfig)
    config.enabled=True
    config.content_max_size_bytes=1024*1024*100
    config.max_file_size_bytes=1024*1024*10
    config.binary_extensions=[".png",".jpg",".exe"]
    config.ignore_dirs=["node_modules","__pycache__",".git"]
    return config


@pytest.fixture
def cache(mock_config,temp_dir):
    return ProjectFileCache(mock_config,"test-project",temp_dir)


class TestProjectFileCacheLoadAll:
    def test_load_empty_directory(self,cache,temp_dir):
        stats=cache.load_all()
        assert cache.is_loaded
        assert stats["files"]==0
        assert stats["dirs"]>=0

    def test_load_with_files(self,cache,temp_dir):
        with open(os.path.join(temp_dir,"file1.txt"),"w") as f:
            f.write("content1")
        with open(os.path.join(temp_dir,"file2.py"),"w") as f:
            f.write("print('hello')")
        stats=cache.load_all()
        assert cache.is_loaded
        assert stats["files"]==2

    def test_load_with_subdirectories(self,cache,temp_dir):
        os.makedirs(os.path.join(temp_dir,"subdir1"))
        os.makedirs(os.path.join(temp_dir,"subdir2","nested"))
        with open(os.path.join(temp_dir,"subdir1","file.txt"),"w") as f:
            f.write("content")
        stats=cache.load_all()
        assert stats["dirs"]>=2

    def test_load_ignores_configured_dirs(self,cache,temp_dir):
        os.makedirs(os.path.join(temp_dir,"node_modules"))
        with open(os.path.join(temp_dir,"node_modules","package.json"),"w") as f:
            f.write("{}")
        os.makedirs(os.path.join(temp_dir,"src"))
        with open(os.path.join(temp_dir,"src","main.py"),"w") as f:
            f.write("print()")
        stats=cache.load_all()
        cache_stats=cache.get_stats()
        assert cache_stats["text_files"]==1
        all_files=cache.get_all_files()
        assert"node_modules/package.json" not in all_files

    def test_load_handles_binary_files(self,cache,temp_dir):
        with open(os.path.join(temp_dir,"image.png"),"wb") as f:
            f.write(b'\x89PNG\r\n\x1a\n\x00\x00\x00')
        with open(os.path.join(temp_dir,"code.py"),"w") as f:
            f.write("print()")
        cache.load_all()
        cache_stats=cache.get_stats()
        assert cache_stats["binary_files"]==1
        assert cache_stats["text_files"]==1
        entry=cache.get_file("image.png")
        assert entry.is_binary
        assert entry.content is None

    def test_load_detects_binary_by_content(self,cache,temp_dir):
        with open(os.path.join(temp_dir,"unknown.dat"),"wb") as f:
            f.write(b'text\x00binary\x00data')
        cache.load_all()
        cache_stats=cache.get_stats()
        assert cache_stats["binary_files"]==1


class TestProjectFileCacheBinaryDetection:
    def test_is_binary_with_null_byte(self,cache):
        assert cache._is_binary_content(b'hello\x00world')

    def test_is_not_binary_text(self,cache):
        assert not cache._is_binary_content(b'hello world')

    def test_is_not_binary_utf8_bom(self,cache):
        assert not cache._is_binary_content(b'\xef\xbb\xbfhello')

    def test_is_not_binary_utf16le_bom(self,cache):
        assert not cache._is_binary_content(b'\xff\xfeh\x00e\x00l\x00l\x00o\x00')

    def test_is_not_binary_utf16be_bom(self,cache):
        assert not cache._is_binary_content(b'\xfe\xff\x00h\x00e\x00l\x00l\x00o')

    def test_is_not_binary_utf32le_bom(self,cache):
        assert not cache._is_binary_content(b'\xff\xfe\x00\x00h\x00\x00\x00')

    def test_is_not_binary_utf32be_bom(self,cache):
        assert not cache._is_binary_content(b'\x00\x00\xfe\xffh\x00\x00\x00')


class TestProjectFileCacheFileOperations:
    def test_put_and_get_file(self,cache):
        cache.put_file("test.txt","hello world")
        content=cache.get_file_content("test.txt")
        assert content=="hello world"

    def test_get_file_entry(self,cache):
        cache.put_file("test.txt","content")
        entry=cache.get_file("test.txt")
        assert isinstance(entry,FileEntry)
        assert entry.content=="content"
        assert entry.size==7

    def test_get_nonexistent_file(self,cache):
        content=cache.get_file_content("nonexistent.txt")
        assert content is None

    def test_remove_file(self,cache):
        cache.put_file("test.txt","content")
        cache.remove_file("test.txt")
        assert cache.get_file_content("test.txt") is None

    def test_update_file(self,cache):
        cache.put_file("test.txt","original")
        cache.put_file("test.txt","updated")
        assert cache.get_file_content("test.txt")=="updated"


class TestProjectFileCacheDirOperations:
    def test_add_and_get_dir(self,cache,temp_dir):
        os.makedirs(os.path.join(temp_dir,"subdir"))
        cache.add_dir("subdir")
        entry=cache.get_dir("subdir")
        assert isinstance(entry,DirEntry)
        assert entry.path=="subdir"

    def test_remove_dir_simple(self,cache,temp_dir):
        cache.load_all()
        os.makedirs(os.path.join(temp_dir,"subdir"))
        cache.add_dir("subdir")
        removed=cache.remove_dir("subdir")
        assert cache.get_dir("subdir") is None
        assert isinstance(removed,list)

    def test_remove_dir_with_files(self,cache,temp_dir):
        os.makedirs(os.path.join(temp_dir,"subdir"))
        with open(os.path.join(temp_dir,"subdir","file1.txt"),"w") as f:
            f.write("content1")
        with open(os.path.join(temp_dir,"subdir","file2.txt"),"w") as f:
            f.write("content2")
        cache.load_all()
        removed=cache.remove_dir("subdir")
        assert len(removed)==2
        assert"subdir/file1.txt" in removed
        assert"subdir/file2.txt" in removed
        assert cache.get_file_content("subdir/file1.txt") is None

    def test_remove_dir_with_nested_structure(self,cache,temp_dir):
        os.makedirs(os.path.join(temp_dir,"parent","child","grandchild"))
        with open(os.path.join(temp_dir,"parent","file1.txt"),"w") as f:
            f.write("1")
        with open(os.path.join(temp_dir,"parent","child","file2.txt"),"w") as f:
            f.write("2")
        with open(os.path.join(temp_dir,"parent","child","grandchild","file3.txt"),"w") as f:
            f.write("3")
        cache.load_all()
        removed=cache.remove_dir("parent")
        assert len(removed)==3
        assert cache.get_dir("parent") is None
        assert cache.get_dir("parent/child") is None
        assert cache.get_dir("parent/child/grandchild") is None

    def test_remove_nonexistent_dir(self,cache):
        removed=cache.remove_dir("nonexistent")
        assert removed==[]


class TestProjectFileCacheSearch:
    def test_search_files_by_pattern(self,cache,temp_dir):
        with open(os.path.join(temp_dir,"test1.py"),"w") as f:
            f.write("code")
        with open(os.path.join(temp_dir,"test2.py"),"w") as f:
            f.write("code")
        with open(os.path.join(temp_dir,"other.txt"),"w") as f:
            f.write("text")
        cache.load_all()
        results=cache.search_files("*.py")
        assert len(results)==2
        assert any("test1.py" in r for r in results)
        assert any("test2.py" in r for r in results)

    def test_search_files_no_match(self,cache,temp_dir):
        with open(os.path.join(temp_dir,"test.txt"),"w") as f:
            f.write("text")
        cache.load_all()
        results=cache.search_files("*.py")
        assert len(results)==0

    def test_search_content_pattern(self,cache,temp_dir):
        with open(os.path.join(temp_dir,"test.py"),"w") as f:
            f.write("def hello():\n    print('hello')\n\ndef world():\n    pass")
        cache.load_all()
        results=cache.search_content("def hello")
        assert len(results)==1
        assert results[0]["line_no"]==1

    def test_search_content_with_context(self,cache,temp_dir):
        with open(os.path.join(temp_dir,"test.py"),"w") as f:
            f.write("line1\nline2\nTARGET\nline4\nline5")
        cache.load_all()
        results=cache.search_content("TARGET",context_lines=2)
        assert len(results)==1
        context=results[0]["context"]
        assert len(context)==5

    def test_search_content_case_insensitive(self,cache,temp_dir):
        with open(os.path.join(temp_dir,"test.py"),"w") as f:
            f.write("HELLO world")
        cache.load_all()
        results=cache.search_content("hello",case_sensitive=False)
        assert len(results)==1

    def test_search_content_max_results(self,cache,temp_dir):
        with open(os.path.join(temp_dir,"test.py"),"w") as f:
            f.write("\n".join([f"match line {i}" for i in range(100)]))
        cache.load_all()
        results=cache.search_content("match",max_results=10)
        assert len(results)==10


class TestProjectFileCacheTree:
    def test_get_tree_flat(self,cache,temp_dir):
        with open(os.path.join(temp_dir,"file1.txt"),"w") as f:
            f.write("1")
        with open(os.path.join(temp_dir,"file2.txt"),"w") as f:
            f.write("2")
        cache.load_all()
        tree=cache.get_tree("",max_depth=1)
        assert len(tree)==2

    def test_get_tree_nested(self,cache,temp_dir):
        os.makedirs(os.path.join(temp_dir,"subdir"))
        with open(os.path.join(temp_dir,"top.txt"),"w") as f:
            f.write("top")
        with open(os.path.join(temp_dir,"subdir","nested.txt"),"w") as f:
            f.write("nested")
        cache.load_all()
        tree=cache.get_tree("",max_depth=2)
        assert len(tree)==2
        subdir_node=[n for n in tree if n["name"]=="subdir"][0]
        assert subdir_node["type"]=="directory"
        assert len(subdir_node.get("children",[]))>=1


class TestProjectFileCacheStats:
    def test_get_stats(self,cache,temp_dir):
        with open(os.path.join(temp_dir,"file.txt"),"w") as f:
            f.write("content")
        cache.load_all()
        stats=cache.get_stats()
        assert"files" in stats
        assert"dirs" in stats
        assert stats["loaded"]==True

    def test_clear(self,cache,temp_dir):
        with open(os.path.join(temp_dir,"file.txt"),"w") as f:
            f.write("content")
        cache.load_all()
        cache.clear()
        assert not cache.is_loaded
        stats=cache.get_stats()
        assert stats["files"]==0


class TestProjectFileCacheUpdateFromDisk:
    def test_update_file_from_disk(self,cache,temp_dir):
        file_path=os.path.join(temp_dir,"test.txt")
        with open(file_path,"w") as f:
            f.write("original")
        cache.load_all()
        with open(file_path,"w") as f:
            f.write("updated")
        cache.update_file_from_disk("test.txt")
        assert cache.get_file_content("test.txt")=="updated"

    def test_update_nonexistent_file(self,cache):
        cache.update_file_from_disk("nonexistent.txt")


class TestProjectFileCacheListDir:
    def test_list_dir(self,cache,temp_dir):
        with open(os.path.join(temp_dir,"file1.txt"),"w") as f:
            f.write("1")
        os.makedirs(os.path.join(temp_dir,"subdir"))
        cache.load_all()
        items=cache.list_dir("")
        assert len(items)==2
        names=[i["name"] for i in items]
        assert"file1.txt" in names
        assert"subdir" in names

    def test_list_dir_nonexistent(self,cache):
        cache._loaded=True
        items=cache.list_dir("nonexistent")
        assert items==[]
