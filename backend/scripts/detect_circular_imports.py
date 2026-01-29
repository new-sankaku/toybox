#!/usr/bin/env python3
"""Detect circular imports in Python codebase."""
import ast
import sys
from pathlib import Path
from collections import defaultdict

TARGET_DIRS = ["handlers", "middleware", "repositories", "routers", "schemas", "services", "providers", "agents", "skills"]
EXCLUDE_DIRS = {"venv", ".venv", "__pycache__", "tests", "models"}

def get_module_name(file_path: Path, base_path: Path) -> str:
    relative = file_path.relative_to(base_path)
    parts = list(relative.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1].replace(".py", "")
    return ".".join(parts)

def extract_imports(file_path: Path, base_path: Path) -> list[str]:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError):
        return []
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module.split(".")[0])
    return list(set(imports))

def find_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    cycles = []
    visited = set()
    rec_stack = set()
    path = []
    def dfs(node: str) -> None:
        visited.add(node)
        rec_stack.add(node)
        path.append(node)
        for neighbor in graph.get(node, set()):
            if neighbor not in visited:
                dfs(neighbor)
            elif neighbor in rec_stack:
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:] + [neighbor]
                if cycle not in cycles:
                    cycles.append(cycle)
        path.pop()
        rec_stack.remove(node)
    for node in graph:
        if node not in visited:
            dfs(node)
    return cycles

def main() -> int:
    base_path = Path(__file__).parent.parent
    graph = defaultdict(set)
    local_modules = set()
    for target_dir in TARGET_DIRS:
        dir_path = base_path / target_dir
        if not dir_path.exists():
            continue
        for py_file in dir_path.rglob("*.py"):
            if any(ex in py_file.parts for ex in EXCLUDE_DIRS):
                continue
            module_name = get_module_name(py_file, base_path)
            local_modules.add(module_name.split(".")[0])
    for target_dir in TARGET_DIRS:
        dir_path = base_path / target_dir
        if not dir_path.exists():
            continue
        for py_file in dir_path.rglob("*.py"):
            if any(ex in py_file.parts for ex in EXCLUDE_DIRS):
                continue
            module_name = get_module_name(py_file, base_path)
            imports = extract_imports(py_file, base_path)
            for imp in imports:
                if imp in local_modules and imp != module_name.split(".")[0]:
                    graph[module_name.split(".")[0]].add(imp)
    cycles = find_cycles(graph)
    if cycles:
        print("Circular imports detected:")
        for cycle in cycles:
            print(f"  {' -> '.join(cycle)}")
        return 1
    print("No circular imports detected")
    return 0

if __name__ == "__main__":
    sys.exit(main())
