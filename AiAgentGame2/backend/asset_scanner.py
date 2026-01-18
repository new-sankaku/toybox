"""
Asset Scanner - Scan testdata folders for real media files
"""

import os
import uuid
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path


# Supported extensions
IMAGE_EXTENSIONS = {'.webp', '.png', '.jpg', '.jpeg', '.gif', '.bmp'}
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.ogg', '.flac', '.m4a'}
VIDEO_EXTENSIONS = {'.mp4', '.webm', '.avi', '.mov', '.mkv'}
DOCUMENT_EXTENSIONS = {'.md', '.txt', '.json', '.yaml', '.yml'}
CODE_EXTENSIONS = {'.py', '.js', '.ts', '.tsx', '.jsx', '.html', '.css'}


def get_file_type(filename: str) -> str:
    """Determine asset type from file extension"""
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return 'image'
    elif ext in AUDIO_EXTENSIONS:
        return 'audio'
    elif ext in VIDEO_EXTENSIONS:
        return 'video'
    elif ext in DOCUMENT_EXTENSIONS:
        return 'document'
    elif ext in CODE_EXTENSIONS:
        return 'code'
    return 'other'


def format_file_size(size_bytes: int) -> str:
    """Format file size to human readable string"""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f}MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.1f}GB"


def scan_directory(base_path: str, subdir: str) -> List[Dict]:
    """
    Recursively scan a directory for media files

    Args:
        base_path: Root path of testdata
        subdir: Subdirectory to scan (e.g., 'image', 'mp3', 'movie')

    Returns:
        List of asset dictionaries
    """
    assets = []
    scan_path = os.path.join(base_path, subdir)

    if not os.path.exists(scan_path):
        print(f"[AssetScanner] Directory not found: {scan_path}")
        return assets

    for root, dirs, files in os.walk(scan_path):
        for filename in files:
            file_path = os.path.join(root, filename)
            relative_path = os.path.relpath(file_path, base_path)

            try:
                stat = os.stat(file_path)
                file_type = get_file_type(filename)

                # Get folder name as category
                folder_name = os.path.basename(os.path.dirname(file_path))
                if folder_name == subdir:
                    folder_name = ""

                asset = {
                    "id": f"asset-{uuid.uuid4().hex[:8]}",
                    "name": filename,
                    "type": file_type,
                    "agent": folder_name or subdir.capitalize(),
                    "size": format_file_size(stat.st_size),
                    "createdAt": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "url": f"/testdata/{relative_path.replace(os.sep, '/')}",
                    "thumbnail": f"/testdata/{relative_path.replace(os.sep, '/')}" if file_type == 'image' else None,
                    "duration": None,  # Would need to parse audio/video for real duration
                    "approvalStatus": "pending",
                    "filePath": file_path,  # Full path for server reference
                    "relativePath": relative_path.replace(os.sep, '/'),
                }
                assets.append(asset)
            except Exception as e:
                print(f"[AssetScanner] Error scanning {file_path}: {e}")

    return assets


def scan_all_testdata(testdata_path: str) -> List[Dict]:
    """
    Scan all testdata folders (image, mp3, movie)

    Args:
        testdata_path: Path to testdata folder

    Returns:
        List of all assets
    """
    all_assets = []

    # Scan each folder
    for subdir in ['image', 'mp3', 'movie']:
        assets = scan_directory(testdata_path, subdir)
        all_assets.extend(assets)
        print(f"[AssetScanner] Found {len(assets)} files in {subdir}/")

    print(f"[AssetScanner] Total assets: {len(all_assets)}")
    return all_assets


def get_testdata_path() -> str:
    """Get the testdata path relative to the backend"""
    # Go up one level from backend to find testdata
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(backend_dir)
    testdata_path = os.path.join(project_root, 'testdata')
    return testdata_path


if __name__ == "__main__":
    # Test scan
    testdata_path = get_testdata_path()
    print(f"Scanning: {testdata_path}")
    assets = scan_all_testdata(testdata_path)
    for asset in assets[:10]:
        print(f"  - {asset['name']} ({asset['type']}, {asset['size']})")
