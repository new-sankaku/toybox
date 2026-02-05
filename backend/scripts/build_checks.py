import sys
import os
import re
from pathlib import Path

def get_backend_root():
    return Path(__file__).parent.parent

def check_syntax(backend_root:Path)->bool:
    import py_compile
    errors=[]
    for py_file in backend_root.rglob("*.py"):
        if"venv" in py_file.parts or"__pycache__" in py_file.parts:
            continue
        try:
            py_compile.compile(str(py_file),doraise=True)
        except py_compile.PyCompileError as e:
            errors.append(str(e))
    if errors:
        for e in errors:
            print(f"Syntax Error: {e}")
        return False
    return True

def check_print_usage(backend_root:Path)->bool:
    print_pattern=re.compile(r'^[^#]*\bprint\s*\(')
    found=[]
    exclude_dirs={"venv","__pycache__","tests","scripts","seeds","skills"}
    exclude_files={"main.py","server.py","asset_scanner.py"}
    for py_file in backend_root.rglob("*.py"):
        if any(d in py_file.parts for d in exclude_dirs):
            continue
        if py_file.name in exclude_files:
            continue
        try:
            with open(py_file,"r",encoding="utf-8") as f:
                for i,line in enumerate(f,1):
                    if print_pattern.search(line):
                        found.append((py_file,i,line.strip()))
        except Exception:
            pass
    if found:
        for path,line_no,line in found:
            rel=path.relative_to(backend_root)
            safe_line=line.replace("(","[").replace(")","]")
            print(f"  {rel}:{line_no}: {safe_line}")
        return False
    return True

def check_nul_files(project_root:Path)->bool:
    nul_files=[]
    for item in project_root.rglob("nul"):
        if item.is_file():
            nul_files.append(item)
    if nul_files:
        for f in nul_files:
            print(f"  Found: {f}")
        return False
    return True

def check_websocket_events(backend_root:Path)->bool:
    project_root=backend_root.parent
    frontend_ws=project_root/"langgraph-studio"/"src"/"services"/"websocketService.ts"
    if not frontend_ws.exists():
        print("  websocketService.ts not found")
        return False
    with open(frontend_ws,"r",encoding="utf-8") as f:
        ws_content=f.read()
    interface_match=re.search(r'interface ServerToClientEvents\s*\{([\s\S]*?)\n\}',ws_content)
    if not interface_match:
        print("  ServerToClientEvents interface not found")
        return False
    frontend_events=set(re.findall(r"'([^']+)':",interface_match.group(1)))
    builtin_events={"connect","disconnect","error"}
    frontend_events-=builtin_events
    backend_events=set()
    emit_patterns=[
        re.compile(r"\.emit\s*\(\s*['\"]([^'\"]+)['\"]"),
        re.compile(r"_emit_event\s*\(\s*['\"]([^'\"]+)['\"]"),
        re.compile(r"\._emit\s*\(\s*['\"]([^'\"]+)['\"]"),
        re.compile(r"_emit_socket\s*\(\s*['\"]([^'\"]+)['\"]"),
    ]
    dynamic_patterns=["f\"agent:{","f'agent:{"]
    for py_file in backend_root.rglob("*.py"):
        if"venv" in py_file.parts or"__pycache__" in py_file.parts:
            continue
        try:
            with open(py_file,"r",encoding="utf-8") as f:
                content=f.read()
                for pattern in emit_patterns:
                    for match in pattern.finditer(content):
                        backend_events.add(match.group(1))
                for dp in dynamic_patterns:
                    if dp in content:
                        backend_events.update(["agent:running","agent:completed","agent:failed","agent:paused"])
        except Exception:
            pass
    internal_events={"provider_health_changed","project:paused","project:status_changed","project:initialized","assets:bulk_updated","asset:regeneration_requested","error:state","agent:budget_exceeded"}
    backend_public=backend_events-internal_events
    missing_in_frontend=backend_public-frontend_events
    missing_in_backend=frontend_events-backend_events
    errors=[]
    if missing_in_frontend:
        errors.append(f"  Backend emits but Frontend missing: {missing_in_frontend}")
    if missing_in_backend:
        errors.append(f"  Frontend defines but Backend never emits: {missing_in_backend}")
    if errors:
        for e in errors:
            print(e)
        return False
    return True

def check_schema_usage(backend_root:Path)->bool:
    generator_path=backend_root/"openapi"/"generator.py"
    if not generator_path.exists():
        print("  generator.py not found")
        return False
    with open(generator_path,"r",encoding="utf-8") as f:
        gen_content=f.read()
    list_match=re.search(r'schemas_list\s*=\s*\[([\s\S]*?)\]',gen_content)
    if not list_match:
        print("  schemas_list not found")
        return False
    registered=set(re.findall(r'\("(\w+)"',list_match.group(1)))
    paths_section=gen_content[gen_content.find("def _add_"):]
    used_in_paths=set(re.findall(r'#/components/schemas/(\w+)',paths_section))
    utility_schemas={"ApiErrorSchema"}
    unused=registered-used_in_paths-utility_schemas
    if unused:
        print(f"  Warning: Schemas in schemas_list but not used in API paths: {unused}")
    return True

def check_imports(backend_root:Path)->bool:
    import subprocess
    modules_to_check=[
        "container",
        "server",
    ]
    errors=[]
    for module in modules_to_check:
        result=subprocess.run(
            [sys.executable,"-c",f"import {module}"],
            cwd=str(backend_root),
            capture_output=True,
            text=True
        )
        if result.returncode!=0:
            error_lines=result.stderr.strip().split("\n")
            last_line=error_lines[-1] if error_lines else "Unknown error"
            errors.append(f"  {module}: {last_line}")
    if errors:
        for e in errors:
            print(e)
        return False
    return True

def check_unused_imports(backend_root:Path)->bool:
    import subprocess
    reexport_modules=["ai_config.py","config_loader.py"]
    result=subprocess.run(
        [sys.executable,"-m","ruff","check",".",
         "--exclude","venv,__pycache__,tests,seeds,scripts",
         "--select","F401",
         "--output-format","text"],
        cwd=str(backend_root),
        capture_output=True,
        text=True
    )
    if result.returncode!=0:
        lines=result.stdout.strip().split("\n")
        violations=[]
        for line in lines:
            if not line.strip():
                continue
            is_reexport=any(mod in line for mod in reexport_modules)
            if not is_reexport:
                violations.append(line)
        if violations:
            for v in violations:
                print(f"  {v}")
            return False
    return True

def check_schema_chain(backend_root:Path)->bool:
    init_path=backend_root/"schemas"/"__init__.py"
    generator_path=backend_root/"openapi"/"generator.py"
    if not init_path.exists() or not generator_path.exists():
        print("  Required files not found")
        return False
    with open(init_path,"r",encoding="utf-8") as f:
        init_content=f.read()
    all_match=re.search(r'__all__\s*=\s*\[([\s\S]*?)\]',init_content)
    if not all_match:
        print("  __all__ not found in schemas/__init__.py")
        return False
    exported=set(re.findall(r'"(\w+)"',all_match.group(1)))
    with open(generator_path,"r",encoding="utf-8") as f:
        gen_content=f.read()
    list_match=re.search(r'schemas_list\s*=\s*\[([\s\S]*?)\]',gen_content)
    if not list_match:
        print("  schemas_list not found in generator.py")
        return False
    registered=set(re.findall(r'\("(\w+)"',list_match.group(1)))
    import_match=re.search(r'from schemas import \(([\s\S]*?)\)',gen_content)
    if not import_match:
        print("  schemas import not found in generator.py")
        return False
    imported=set(re.findall(r'(\w+Schema\w*)',import_match.group(1)))
    skip_schemas={"BaseSchema","ApiErrorSchema"}
    exported_schemas={s for s in exported if s.endswith("Schema") and s not in skip_schemas}
    missing_import=exported_schemas-imported
    missing_register=imported-registered-skip_schemas
    errors=[]
    if missing_import:
        errors.append(f"  Not imported in generator.py: {missing_import}")
    if missing_register:
        errors.append(f"  Imported but not in schemas_list: {missing_register}")
    if errors:
        for e in errors:
            print(e)
        return False
    return True

if __name__=="__main__":
    if len(sys.argv)<2:
        print("Usage: build_checks.py <check_type>")
        sys.exit(1)
    check_type=sys.argv[1]
    backend_root=get_backend_root()
    project_root=backend_root.parent
    if check_type=="syntax":
        sys.exit(0 if check_syntax(backend_root) else 1)
    elif check_type=="imports":
        sys.exit(0 if check_imports(backend_root) else 1)
    elif check_type=="print":
        sys.exit(0 if check_print_usage(backend_root) else 1)
    elif check_type=="nul":
        sys.exit(0 if check_nul_files(project_root) else 1)
    elif check_type=="schema":
        sys.exit(0 if check_schema_chain(backend_root) else 1)
    elif check_type=="websocket-events":
        sys.exit(0 if check_websocket_events(backend_root) else 1)
    elif check_type=="schema-usage":
        sys.exit(0 if check_schema_usage(backend_root) else 1)
    elif check_type=="unused-imports":
        sys.exit(0 if check_unused_imports(backend_root) else 1)
    else:
        print(f"Unknown check: {check_type}")
        sys.exit(1)
