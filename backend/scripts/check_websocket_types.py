#!/usr/bin/env python3
"""
WebSocketイベント型整合性チェックスクリプト

バックエンドのWebSocket emit呼び出しとフロントエンドのWebSocketEventMap型定義を比較し、
不整合を検出する。
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

BACKEND_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_ROOT = BACKEND_ROOT.parent / "langgraph-studio"

EMIT_PATTERNS = [
    re.compile(r'emit_to_project\(\s*["\']([^"\']+)["\']'),
    re.compile(r'emit_to_room\(\s*["\']([^"\']+)["\']'),
    re.compile(r'\.emit\(\s*["\']([^"\']+)["\']'),
    re.compile(r'_emit_event\(\s*["\']([^"\']+)["\']'),
    re.compile(r'_emit_event\(\s*f"([^"]+)"'),
]

DYNAMIC_EVENT_PATTERN = re.compile(r'_emit_event\(\s*f"agent:\{([^}]+)\}"')


def extract_backend_events() -> Dict[str, List[Tuple[str, int, Dict[str, str]]]]:
    """バックエンドのemit呼び出しからイベント名とデータ構造を抽出する"""
    events: Dict[str, List[Tuple[str, int, Dict[str, str]]]] = {}

    search_dirs = ["routers", "services", "core", "handlers"]
    search_files = ["datastore.py"]

    all_files: List[Path] = []
    for dir_name in search_dirs:
        dir_path = BACKEND_ROOT / dir_name
        if dir_path.is_dir():
            all_files.extend(dir_path.glob("*.py"))
    for file_name in search_files:
        file_path = BACKEND_ROOT / file_name
        if file_path.is_file():
            all_files.append(file_path)

    for py_file in all_files:
        if py_file.name.startswith("__"):
            continue
        if "test" in py_file.name.lower():
            continue

        with open(py_file, "r", encoding="utf-8") as f:
            content = f.read()
            lines = content.split("\n")

        for i, line in enumerate(lines, 1):
            for pattern in EMIT_PATTERNS:
                match = pattern.search(line)
                if match:
                    event_name = match.group(1)
                    if "{" in event_name:
                        continue
                    if event_name in ("connect", "disconnect", "subscribe:project", "unsubscribe:project"):
                        continue
                    data_fields = extract_data_fields(lines, i - 1)
                    try:
                        rel_path = str(py_file.relative_to(BACKEND_ROOT))
                    except ValueError:
                        rel_path = str(py_file)
                    location = (rel_path, i, data_fields)
                    if event_name not in events:
                        events[event_name] = []
                    events[event_name].append(location)

            dyn_match = DYNAMIC_EVENT_PATTERN.search(line)
            if dyn_match:
                possible_statuses = ["started", "completed", "failed", "paused", "resumed", "running"]
                for status in possible_statuses:
                    event_name = f"agent:{status}"
                    if event_name not in events:
                        events[event_name] = []

        multiline_events = extract_multiline_emit_events(content)
        for event_name, line_num, data_fields in multiline_events:
            if event_name in ("connect", "disconnect", "subscribe:project", "unsubscribe:project"):
                continue
            try:
                rel_path = str(py_file.relative_to(BACKEND_ROOT))
            except ValueError:
                rel_path = str(py_file)
            location = (rel_path, line_num, data_fields)
            if event_name not in events:
                events[event_name] = []
            already_exists = any(loc[0] == rel_path and loc[1] == line_num for loc in events[event_name])
            if not already_exists:
                events[event_name].append(location)

    return events


def extract_multiline_emit_events(content: str) -> List[Tuple[str, int, Dict[str, str]]]:
    """複数行にまたがるemit呼び出しからイベントを抽出する"""
    results: List[Tuple[str, int, Dict[str, str]]] = []
    lines = content.split("\n")

    emit_call_pattern = re.compile(r"(emit_to_project|emit_to_room|_emit_event)\s*\(")
    event_name_pattern = re.compile(r'["\']([a-z_]+:[a-z_]+)["\']')

    i = 0
    while i < len(lines):
        line = lines[i]
        if emit_call_pattern.search(line):
            combined = line
            start_line = i + 1
            paren_count = line.count("(") - line.count(")")

            j = i + 1
            while paren_count > 0 and j < len(lines) and j < i + 20:
                combined += "\n" + lines[j]
                paren_count += lines[j].count("(") - lines[j].count(")")
                j += 1

            event_match = event_name_pattern.search(combined)
            if event_match:
                event_name = event_match.group(1)
                if "{" not in event_name:
                    data_fields = extract_data_fields_from_text(combined)
                    results.append((event_name, start_line, data_fields))
        i += 1

    return results


def extract_data_fields_from_text(text: str) -> Dict[str, str]:
    """テキストからデータフィールドを抽出する"""
    fields: Dict[str, str] = {}
    field_pattern = re.compile(r'["\'](\w+)["\']:\s*(?:[^,}]+|"[^"]*"|\'[^\']*\')')
    for match in field_pattern.finditer(text):
        field_name = match.group(1)
        fields[field_name] = "any"
    return fields


def extract_data_fields(lines: List[str], start_idx: int) -> Dict[str, str]:
    """emit呼び出しからデータフィールドを抽出する"""
    fields: Dict[str, str] = {}
    combined = ""
    brace_count = 0
    started = False

    for i in range(start_idx, min(start_idx + 30, len(lines))):
        line = lines[i]
        combined += line + "\n"

        for char in line:
            if char == "{":
                brace_count += 1
                started = True
            elif char == "}":
                brace_count -= 1
                if started and brace_count == 0:
                    break
        if started and brace_count == 0:
            break

    field_pattern = re.compile(r'["\'](\w+)["\']:\s*(?:[^,}]+|"[^"]*"|\'[^\']*\')')
    for match in field_pattern.finditer(combined):
        field_name = match.group(1)
        fields[field_name] = "any"

    return fields


def extract_frontend_events() -> Dict[str, Dict[str, str]]:
    """フロントエンドのWebSocketEventMapから型定義を抽出する"""
    events: Dict[str, Dict[str, str]] = {}

    ws_file = FRONTEND_ROOT / "src" / "types" / "websocket.ts"
    if not ws_file.exists():
        print(f"Error: {ws_file} not found")
        sys.exit(1)

    with open(ws_file, "r", encoding="utf-8") as f:
        content = f.read()

    start_match = re.search(r"export interface WebSocketEventMap\s*\{", content)
    if not start_match:
        print("Error: WebSocketEventMap not found in websocket.ts")
        sys.exit(1)

    start_idx = start_match.end()
    brace_count = 1
    end_idx = start_idx

    for i in range(start_idx, len(content)):
        if content[i] == "{":
            brace_count += 1
        elif content[i] == "}":
            brace_count -= 1
            if brace_count == 0:
                end_idx = i
                break

    event_map_content = content[start_idx:end_idx]

    event_pattern = re.compile(r"'([^']+)':\s*(\{[^}]+\}|\w+)")

    for match in event_pattern.finditer(event_map_content):
        event_name = match.group(1)
        type_def = match.group(2).strip()
        fields = extract_type_fields(content, type_def)
        events[event_name] = fields

    return events


def extract_type_fields(full_content: str, type_def: str) -> Dict[str, str]:
    """型定義からフィールドを抽出する"""
    fields: Dict[str, str] = {}

    if type_def.startswith("{"):
        inline_pattern = re.compile(r"(\w+)\s*[?]?:\s*([^;,}]+)")
        for match in inline_pattern.finditer(type_def):
            fields[match.group(1)] = match.group(2).strip()
    else:
        type_name = type_def.strip()
        interface_pattern = re.compile(
            rf"export interface {re.escape(type_name)}\s*\{{([^}}]+)\}}", re.DOTALL
        )
        interface_match = interface_pattern.search(full_content)
        if interface_match:
            interface_content = interface_match.group(1)
            field_pattern = re.compile(r"(\w+)\s*[?]?:\s*([^\n;]+)")
            for match in field_pattern.finditer(interface_content):
                fields[match.group(1)] = match.group(2).strip()

    return fields


def to_camel_case(snake_str: str) -> str:
    """snake_caseをcamelCaseに変換"""
    components = snake_str.split("_")
    return components[0] + "".join(x.title() for x in components[1:])


def check_field_consistency(
    event_name: str, backend_fields: Dict[str, str], frontend_fields: Dict[str, str]
) -> List[str]:
    """フィールドの整合性をチェックする"""
    issues = []

    backend_camel = {to_camel_case(k): k for k in backend_fields.keys()}

    for backend_field, original in backend_camel.items():
        if backend_field not in frontend_fields:
            issues.append(f"  Missing field in frontend: '{backend_field}' (backend: '{original}')")

    return issues


def check_consistency() -> bool:
    """整合性チェックを実行"""
    backend_events = extract_backend_events()
    frontend_events = extract_frontend_events()

    print("=" * 60)
    print("WebSocket Event Consistency Check")
    print("=" * 60)

    backend_event_names = set(backend_events.keys())
    frontend_event_names = set(frontend_events.keys())

    missing_in_frontend = backend_event_names - frontend_event_names
    unused_in_backend = frontend_event_names - backend_event_names

    has_issues = False

    print("\n[Backend events missing in frontend]")
    print(f"Count: {len(missing_in_frontend)}")
    print("-" * 60)
    if missing_in_frontend:
        has_issues = True
        for event in sorted(missing_in_frontend):
            locations = backend_events[event]
            print(f"  {event}")
            for loc, line_num, _ in locations[:3]:
                print(f"    -> {loc}:{line_num}")
            if len(locations) > 3:
                print(f"    -> ... and {len(locations) - 3} more")
    else:
        print("  None")

    print("\n[Frontend events not used in backend]")
    print(f"Count: {len(unused_in_backend)}")
    print("-" * 60)
    if unused_in_backend:
        for event in sorted(unused_in_backend):
            print(f"  {event}")
    else:
        print("  None")

    print("\n[Field consistency check]")
    print("-" * 60)
    common_events = backend_event_names & frontend_event_names
    field_issues = []

    for event in sorted(common_events):
        all_backend_fields: Dict[str, str] = {}
        for _, _, fields in backend_events[event]:
            all_backend_fields.update(fields)

        frontend_fields = frontend_events[event]
        issues = check_field_consistency(event, all_backend_fields, frontend_fields)
        if issues:
            field_issues.append((event, issues))

    if field_issues:
        for event, issues in field_issues:
            print(f"  {event}:")
            for issue in issues:
                print(issue)
    else:
        print("  No field mismatches found")

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"Backend events: {len(backend_event_names)}")
    print(f"Frontend events: {len(frontend_event_names)}")
    print(f"Missing in frontend: {len(missing_in_frontend)}")
    print(f"Unused in backend: {len(unused_in_backend)}")
    print(f"Events with field issues: {len(field_issues)}")

    if has_issues:
        print("\n[WARNING] WebSocket event inconsistencies detected!")
        print("Please update frontend types or backend emit calls.")

    return not has_issues


def main():
    success = check_consistency()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
