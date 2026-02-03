import os
import sys
from pathlib import Path
from collections import defaultdict

def count_lines(file_path: Path) -> int:
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0

def get_files(base_dir: Path, extensions: list[str], exclude_dirs: list[str]) -> list[Path]:
    files = []
    for ext in extensions:
        for file_path in base_dir.rglob(f"*{ext}"):
            if not any(excl in file_path.parts for excl in exclude_dirs):
                files.append(file_path)
    return files

def main():
    root = Path(__file__).parent.parent.parent

    backend_dir = root / "backend"
    frontend_dir = root / "langgraph-studio" / "src"

    backend_exclude = ["venv", "__pycache__", ".git", "node_modules"]
    frontend_exclude = ["node_modules", ".git", "dist", "build"]

    backend_files = get_files(backend_dir, [".py"], backend_exclude)
    frontend_files = get_files(frontend_dir, [".ts", ".tsx"], frontend_exclude)

    backend_lines = [(f, count_lines(f)) for f in backend_files]
    frontend_lines = [(f, count_lines(f)) for f in frontend_files]

    backend_total = sum(lines for _, lines in backend_lines)
    frontend_total = sum(lines for _, lines in frontend_lines)

    print("=" * 60)
    print("  Line Count Report")
    print("=" * 60)
    print()

    print(f"{'Category':<30} {'Files':>10} {'Lines':>10}")
    print("-" * 50)
    print(f"{'Backend (Python)':<30} {len(backend_files):>10} {backend_total:>10}")
    print(f"{'Frontend (TypeScript)':<30} {len(frontend_files):>10} {frontend_total:>10}")
    print("-" * 50)
    print(f"{'TOTAL':<30} {len(backend_files) + len(frontend_files):>10} {backend_total + frontend_total:>10}")
    print()

    print("=" * 60)
    print("  Top 10 Largest Files - Backend")
    print("=" * 60)
    backend_sorted = sorted(backend_lines, key=lambda x: x[1], reverse=True)[:10]
    for file_path, lines in backend_sorted:
        rel_path = file_path.relative_to(backend_dir)
        print(f"  {lines:>6}  {rel_path}")
    print()

    print("=" * 60)
    print("  Top 10 Largest Files - Frontend")
    print("=" * 60)
    frontend_sorted = sorted(frontend_lines, key=lambda x: x[1], reverse=True)[:10]
    for file_path, lines in frontend_sorted:
        rel_path = file_path.relative_to(frontend_dir)
        print(f"  {lines:>6}  {rel_path}")
    print()

    print("=" * 60)
    print("  By Directory - Backend")
    print("=" * 60)
    backend_by_dir = defaultdict(lambda: {"files": 0, "lines": 0})
    for file_path, lines in backend_lines:
        rel_path = file_path.relative_to(backend_dir)
        dir_name = rel_path.parts[0] if len(rel_path.parts) > 1 else "(root)"
        backend_by_dir[dir_name]["files"] += 1
        backend_by_dir[dir_name]["lines"] += lines

    for dir_name, stats in sorted(backend_by_dir.items(), key=lambda x: x[1]["lines"], reverse=True):
        print(f"  {stats['lines']:>6}  ({stats['files']:>3} files)  {dir_name}/")
    print()

    print("=" * 60)
    print("  By Directory - Frontend")
    print("=" * 60)
    frontend_by_dir = defaultdict(lambda: {"files": 0, "lines": 0})
    for file_path, lines in frontend_lines:
        rel_path = file_path.relative_to(frontend_dir)
        dir_name = rel_path.parts[0] if len(rel_path.parts) > 1 else "(root)"
        frontend_by_dir[dir_name]["files"] += 1
        frontend_by_dir[dir_name]["lines"] += lines

    for dir_name, stats in sorted(frontend_by_dir.items(), key=lambda x: x[1]["lines"], reverse=True):
        print(f"  {stats['lines']:>6}  ({stats['files']:>3} files)  {dir_name}/")
    print()

if __name__ == "__main__":
    main()
