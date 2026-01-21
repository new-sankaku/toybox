import os
import uuid
from datetime import datetime
from typing import List,Dict,Optional,Set
from pathlib import Path

from config_loader import get_all_extension_categories, get_scan_directories, get_file_extensions_config


# キャッシュ用変数
_extension_categories: Optional[Dict[str, Set[str]]] = None


def _get_extension_categories() -> Dict[str, Set[str]]:
    """拡張子カテゴリマップを取得（キャッシュ付き）"""
    global _extension_categories
    if _extension_categories is None:
        _extension_categories = get_all_extension_categories()
    return _extension_categories


def get_file_type(filename:str)->str:
    ext = Path(filename).suffix.lower()
    categories = _get_extension_categories()

    for category, extensions in categories.items():
        if ext in extensions:
            return category

    return 'other'


def format_file_size(size_bytes:int)->str:
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f}MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.1f}GB"


def scan_directory(base_path:str,subdir:str)->List[Dict]:
    assets = []
    scan_path = os.path.join(base_path,subdir)

    if not os.path.exists(scan_path):
        print(f"[AssetScanner] Directory not found: {scan_path}")
        return assets

    for root,dirs,files in os.walk(scan_path):
        for filename in files:
            file_path = os.path.join(root,filename)
            relative_path = os.path.relpath(file_path,base_path)

            try:
                stat = os.stat(file_path)
                file_type = get_file_type(filename)
                folder_name = os.path.basename(os.path.dirname(file_path))
                if folder_name == subdir:
                    folder_name = ""

                asset = {
                    "id":f"asset-{uuid.uuid4().hex[:8]}",
                    "name":filename,
                    "type":file_type,
                    "agent":folder_name or subdir.capitalize(),
                    "size":format_file_size(stat.st_size),
                    "createdAt":datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "url":f"/testdata/{relative_path.replace(os.sep, '/')}",
                    "thumbnail":f"/testdata/{relative_path.replace(os.sep, '/')}" if file_type == 'image' else None,
                    "duration":None,
                    "approvalStatus":"pending",
                    "filePath":file_path,
                    "relativePath":relative_path.replace(os.sep,'/'),
                }
                assets.append(asset)
            except Exception as e:
                print(f"[AssetScanner] Error scanning {file_path}: {e}")

    return assets


def scan_all_testdata(testdata_path:str)->List[Dict]:
    all_assets = []
    scan_dirs = get_scan_directories()

    for subdir in scan_dirs:
        assets = scan_directory(testdata_path,subdir)
        all_assets.extend(assets)
        print(f"[AssetScanner] Found {len(assets)} files in {subdir}/")

    print(f"[AssetScanner] Total assets: {len(all_assets)}")
    return all_assets


def get_testdata_path()->str:
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(backend_dir)
    testdata_path = os.path.join(project_root,'testdata')
    return testdata_path


if __name__ == "__main__":

    testdata_path = get_testdata_path()
    print(f"Scanning: {testdata_path}")
    assets = scan_all_testdata(testdata_path)
    for asset in assets[:10]:
        print(f"  - {asset['name']} ({asset['type']}, {asset['size']})")
