import sys
import os
import re
from pathlib import Path

def get_backend_root():
    return Path(__file__).parent.parent

def check_syntax(backend_root: Path) -> bool:
    import py_compile
    errors = []
    for py_file in backend_root.rglob("*.py"):
        if "venv" in py_file.parts or "__pycache__" in py_file.parts:
            continue
        try:
            py_compile.compile(str(py_file), doraise=True)
        except py_compile.PyCompileError as e:
            errors.append(str(e))
    if errors:
        for e in errors:
            print(f"Syntax Error: {e}")
        return False
    return True

def check_print_usage(backend_root: Path) -> bool:
    print_pattern = re.compile(r'^[^#]*\bprint\s*\(')
    found = []
    exclude_dirs = {"venv", "__pycache__", "tests", "scripts", "seeds", "skills"}
    exclude_files = {"main.py", "server.py", "asset_scanner.py"}
    for py_file in backend_root.rglob("*.py"):
        if any(d in py_file.parts for d in exclude_dirs):
            continue
        if py_file.name in exclude_files:
            continue
        try:
            with open(py_file, "r", encoding="utf-8") as f:
                for i, line in enumerate(f, 1):
                    if print_pattern.search(line):
                        found.append((py_file, i, line.strip()))
        except Exception:
            pass
    if found:
        for path, line_no, line in found:
            rel = path.relative_to(backend_root)
            safe_line = line.replace("(", "[").replace(")", "]")
            print(f"  {rel}:{line_no}: {safe_line}")
        return False
    return True

def check_nul_files(project_root: Path) -> bool:
    nul_files = []
    for item in project_root.rglob("nul"):
        if item.is_file():
            nul_files.append(item)
    if nul_files:
        for f in nul_files:
            print(f"  Found: {f}")
        return False
    return True

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: build_checks.py <check_type>")
        sys.exit(1)
    check_type = sys.argv[1]
    backend_root = get_backend_root()
    project_root = backend_root.parent
    if check_type == "syntax":
        sys.exit(0 if check_syntax(backend_root) else 1)
    elif check_type == "print":
        sys.exit(0 if check_print_usage(backend_root) else 1)
    elif check_type == "nul":
        sys.exit(0 if check_nul_files(project_root) else 1)
    else:
        print(f"Unknown check: {check_type}")
        sys.exit(1)
