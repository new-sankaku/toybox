#!/usr/bin/env python
"""
Check that all router endpoints have response_model specified.
This ensures OpenAPI spec generation includes proper response types.
"""

import ast
import sys
from pathlib import Path


def check_router_file(file_path: Path) -> list[tuple[str, int, str]]:
    """Check a router file for endpoints missing response_model."""
    issues = []
    try:
        with open(file_path, encoding="utf-8") as f:
            content = f.read()
        tree = ast.parse(content)
    except SyntaxError:
        return [(str(file_path), 0, "Syntax error")]

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            if not isinstance(decorator.func, ast.Attribute):
                continue
            method = decorator.func.attr
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            has_response_model = any(
                isinstance(kw.arg, str) and kw.arg == "response_model" for kw in decorator.keywords
            )
            has_status_code_204 = any(
                isinstance(kw.arg, str) and kw.arg == "status_code" and isinstance(kw.value, ast.Constant) and kw.value.value == 204
                for kw in decorator.keywords
            )
            if has_status_code_204:
                continue
            is_file_download = _is_file_download_endpoint(node)
            is_streaming = _is_streaming_endpoint(node)
            if is_file_download or is_streaming:
                continue
            if not has_response_model:
                path_arg = ""
                if decorator.args:
                    first_arg = decorator.args[0]
                    if isinstance(first_arg, ast.Constant):
                        path_arg = first_arg.value
                issues.append(
                    (str(file_path.name), node.lineno, f"{method.upper()} {path_arg} - {node.name}()")
                )
    return issues


def _is_file_download_endpoint(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Check if endpoint returns FileResponse."""
    for child in ast.walk(node):
        if isinstance(child, ast.Return):
            if child.value and isinstance(child.value, ast.Call):
                if isinstance(child.value.func, ast.Name):
                    if child.value.func.id in ("FileResponse", "StreamingResponse"):
                        return True
    return False


def _is_streaming_endpoint(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Check if endpoint returns StreamingResponse."""
    for child in ast.walk(node):
        if isinstance(child, ast.Return):
            if child.value and isinstance(child.value, ast.Call):
                if isinstance(child.value.func, ast.Name):
                    if child.value.func.id == "StreamingResponse":
                        return True
    return False


def main():
    routers_dir = Path(__file__).parent.parent / "routers"
    if not routers_dir.exists():
        print(f"Error: {routers_dir} not found")
        sys.exit(1)

    all_issues = []
    for router_file in sorted(routers_dir.glob("*.py")):
        if router_file.name == "__init__.py":
            continue
        issues = check_router_file(router_file)
        all_issues.extend(issues)

    if all_issues:
        print("=" * 60)
        print("Endpoints missing response_model")
        print("=" * 60)
        print()
        for file_name, line, desc in all_issues:
            print(f"  {file_name}:{line} - {desc}")
        print()
        print(f"Total: {len(all_issues)} endpoints without response_model")
        print()
        print("Fix: Add response_model=SchemaClass to each endpoint decorator")
        print("Example: @router.get('/path', response_model=MySchema)")
        print()
        return 1
    else:
        print("All endpoints have response_model specified")
        return 0


if __name__ == "__main__":
    sys.exit(main())
