#!/usr/bin/env python3
"""
API整合性チェックスクリプト

フロントエンドのAPI_ENDPOINTSとバックエンドのルート定義を比較し、
不整合を検出する。
"""

import os
import re
import sys
import json
from typing import Dict, List, Set, Tuple
from pathlib import Path

BACKEND_ROOT = Path(__file__).parent.parent
FRONTEND_ROOT = BACKEND_ROOT.parent / "langgraph-studio"

ROUTER_PREFIX = "/api"


def extract_backend_routes() -> Dict[str, Set[str]]:
    """バックエンドの全ルートを抽出する"""
    routes: Dict[str, Set[str]] = {}
    routers_dir = BACKEND_ROOT / "routers"

    route_pattern = re.compile(r'@router\.(get|post|put|patch|delete)\s*\(\s*["\']([^"\']+)["\']')

    for router_file in routers_dir.glob("*.py"):
        if router_file.name.startswith("__"):
            continue

        with open(router_file, "r", encoding="utf-8") as f:
            content = f.read()

        for match in route_pattern.finditer(content):
            method = match.group(1).upper()
            path = match.group(2)
            if path.startswith("/api/"):
                full_path = path
            else:
                full_path = f"{ROUTER_PREFIX}{path}"
            full_path = normalize_path(full_path)

            if full_path not in routes:
                routes[full_path] = set()
            routes[full_path].add(method)

    return routes


def normalize_path(path: str) -> str:
    """パスを正規化する（パラメータ部分を統一）"""
    path = re.sub(r"\{[^}]+:path\}", "{path}", path)
    path = re.sub(r"\{[^}]+\}", "{id}", path)
    return path


def extract_frontend_endpoints() -> Dict[str, List[Tuple[str, str]]]:
    """フロントエンドのAPI_ENDPOINTSを抽出する"""
    api_file = FRONTEND_ROOT / "src" / "constants" / "api.ts"
    if not api_file.exists():
        print(f"Error: {api_file} not found")
        sys.exit(1)

    with open(api_file, "r", encoding="utf-8") as f:
        content = f.read()

    endpoints: Dict[str, List[Tuple[str, str]]] = {}

    static_pattern = re.compile(r":\s*['\"](/api/[^'\"]+)['\"]")
    for match in static_pattern.finditer(content):
        path = normalize_path(match.group(1))
        if path not in endpoints:
            endpoints[path] = []
        endpoints[path].append(("UNKNOWN", "static"))

    return endpoints


def extract_frontend_api_calls() -> Dict[str, Set[str]]:
    """フロントエンドのAPIサービスから実際の呼び出しを抽出する"""
    api_service_file = FRONTEND_ROOT / "src" / "services" / "apiService.ts"
    if not api_service_file.exists():
        print(f"Error: {api_service_file} not found")
        sys.exit(1)

    with open(api_service_file, "r", encoding="utf-8") as f:
        content = f.read()

    calls: Dict[str, Set[str]] = {}

    call_pattern = re.compile(r"api\.(get|post|put|patch|delete)\s*\(\s*API_ENDPOINTS\.([a-zA-Z_.]+(?:\([^)]*\))?)")

    for match in call_pattern.finditer(content):
        method = match.group(1).upper()
        endpoint_ref = match.group(2)
        calls[endpoint_ref] = calls.get(endpoint_ref, set())
        calls[endpoint_ref].add(method)

    return calls


def load_frontend_endpoints_mapping() -> Dict[str, str]:
    """フロントエンドのエンドポイント定義を読み込む"""
    api_file = FRONTEND_ROOT / "src" / "constants" / "api.ts"
    with open(api_file, "r", encoding="utf-8") as f:
        content = f.read()

    mapping = {}

    lines = content.split("\n")
    current_path = []
    brace_count = 0

    for line in lines:
        stripped = line.strip()

        if ":{" in stripped or ": {" in stripped:
            key_match = re.match(r"(\w+)\s*:\s*\{", stripped)
            if key_match:
                current_path.append(key_match.group(1))
                brace_count += 1
            continue

        if stripped == "},":
            if current_path:
                current_path.pop()
            brace_count -= 1
            continue

        static_match = re.match(r"(\w+)\s*:\s*['\"]([^'\"]+)['\"]", stripped)
        if static_match:
            key = static_match.group(1)
            value = static_match.group(2)
            full_key = ".".join(current_path + [key])
            mapping[full_key] = value

        func_match = re.match(r"(\w+)\s*:\s*\([^)]*\)\s*=>\s*`([^`]+)`", stripped)
        if func_match:
            key = func_match.group(1)
            value = func_match.group(2)
            value = re.sub(r"\$\{[^}]+\}", "{id}", value)
            full_key = ".".join(current_path + [key])
            mapping[full_key] = value

    return mapping


def check_consistency():
    """整合性チェックを実行"""
    backend_routes = extract_backend_routes()
    frontend_mapping = load_frontend_endpoints_mapping()

    print("=" * 60)
    print("API整合性チェック結果")
    print("=" * 60)

    missing_in_backend = []
    extra_in_backend = []

    frontend_paths = set()
    for key, path in frontend_mapping.items():
        normalized = normalize_path(path)
        frontend_paths.add(normalized)

    backend_paths = set(backend_routes.keys())

    for path in sorted(frontend_paths - backend_paths):
        key = None
        for k, v in frontend_mapping.items():
            if normalize_path(v) == path:
                key = k
                break
        missing_in_backend.append((path, key))

    for path in sorted(backend_paths - frontend_paths):
        extra_in_backend.append(path)

    print(f"\n【フロントエンドで定義されているがバックエンドに存在しないエンドポイント】")
    print(f"件数: {len(missing_in_backend)}")
    print("-" * 60)
    if missing_in_backend:
        for path, key in missing_in_backend:
            print(f"  {path}")
            if key:
                print(f"    └─ フロントエンド定義: {key}")
    else:
        print("  なし")

    print(f"\n【バックエンドに存在するがフロントエンドで定義されていないエンドポイント】")
    print(f"件数: {len(extra_in_backend)}")
    print("-" * 60)
    if extra_in_backend:
        for path in extra_in_backend:
            methods = ", ".join(sorted(backend_routes[path]))
            print(f"  {path} [{methods}]")
    else:
        print("  なし")

    print("\n" + "=" * 60)
    print("サマリー")
    print("=" * 60)
    print(f"バックエンドルート数: {len(backend_paths)}")
    print(f"フロントエンドエンドポイント数: {len(frontend_paths)}")
    print(f"不足（バックエンドに追加が必要）: {len(missing_in_backend)}")
    print(f"未使用（フロントエンドで未定義）: {len(extra_in_backend)}")

    return len(missing_in_backend) == 0


def main():
    success = check_consistency()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
