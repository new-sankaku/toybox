import os
import sys
from pathlib import Path
from collections import defaultdict

def count_lines(file_path:Path)->int:
    try:
        with open(file_path,"r",encoding="utf-8",errors="ignore") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0

def get_files(base_dir:Path,extensions:list[str],exclude_dirs:list[str])->list[Path]:
    files=[]
    for ext in extensions:
        for file_path in base_dir.rglob(f"*{ext}"):
            if not any(excl in file_path.parts for excl in exclude_dirs):
                files.append(file_path)
    return files

def count_category(files:list[Path])->tuple[int,int]:
    total_lines=sum(count_lines(f) for f in files)
    return len(files),total_lines

def print_top_files(title:str,files:list[Path],base_dir:Path,top_n:int=10):
    print("="*60)
    print(f"  {title}")
    print("="*60)
    file_lines=[(f,count_lines(f)) for f in files]
    sorted_files=sorted(file_lines,key=lambda x:x[1],reverse=True)[:top_n]
    for file_path,lines in sorted_files:
        try:
            rel_path=file_path.relative_to(base_dir)
        except ValueError:
            rel_path=file_path.name
        print(f"  {lines:>6}  {rel_path}")
    print()

def print_by_directory(title:str,files:list[Path],base_dir:Path):
    print("="*60)
    print(f"  {title}")
    print("="*60)
    by_dir=defaultdict(lambda:{"files":0,"lines":0})
    for file_path in files:
        lines=count_lines(file_path)
        try:
            rel_path=file_path.relative_to(base_dir)
            dir_name=rel_path.parts[0] if len(rel_path.parts)>1 else"(root)"
        except ValueError:
            dir_name="(other)"
        by_dir[dir_name]["files"]+=1
        by_dir[dir_name]["lines"]+=lines

    for dir_name,stats in sorted(by_dir.items(),key=lambda x:x[1]["lines"],reverse=True):
        print(f"  {stats['lines']:>6}  ({stats['files']:>3} files)  {dir_name}/")
    print()

def main():
    root=Path(__file__).parent.parent.parent

    backend_dir=root/"backend"
    frontend_dir=root/"langgraph-studio"
    frontend_src=frontend_dir/"src"
    doc_dir=root/"doc"

    exclude=["venv","__pycache__",".git","node_modules","dist","build",".next"]

    backend_py=get_files(backend_dir,[".py"],exclude)
    frontend_ts=get_files(frontend_src,[".ts",".tsx"],exclude)
    frontend_css=get_files(frontend_src,[".css"],exclude)
    frontend_html=get_files(frontend_dir,[".html"],exclude)

    config_yaml=get_files(root,[".yaml",".yml"],exclude)
    config_json=get_files(root,[".json"],exclude)
    config_json=[f for f in config_json if"package-lock" not in f.name]

    scripts_bat=get_files(root,[".bat"],exclude)
    scripts_sh=get_files(root,[".sh"],exclude)
    scripts_js=get_files(root,[".cjs",".mjs"],exclude)

    docs_md=get_files(root,[".md"],exclude)

    py_count,py_lines=count_category(backend_py)
    ts_count,ts_lines=count_category(frontend_ts)
    css_count,css_lines=count_category(frontend_css)
    html_count,html_lines=count_category(frontend_html)
    yaml_count,yaml_lines=count_category(config_yaml)
    json_count,json_lines=count_category(config_json)
    bat_count,bat_lines=count_category(scripts_bat)
    sh_count,sh_lines=count_category(scripts_sh)
    js_count,js_lines=count_category(scripts_js)
    md_count,md_lines=count_category(docs_md)

    code_files=py_count+ts_count+css_count+html_count
    code_lines=py_lines+ts_lines+css_lines+html_lines

    config_files=yaml_count+json_count
    config_lines=yaml_lines+json_lines

    script_files=bat_count+sh_count+js_count
    script_lines=bat_lines+sh_lines+js_lines

    print("="*60)
    print("  Line Count Report")
    print("="*60)
    print()

    print(f"{'Category':<35} {'Files':>8} {'Lines':>10}")
    print("-"*55)
    print()
    print("  [Code]")
    print(f"{'    Backend (Python .py)':<35} {py_count:>8} {py_lines:>10}")
    print(f"{'    Frontend (TypeScript .ts/.tsx)':<35} {ts_count:>8} {ts_lines:>10}")
    print(f"{'    Frontend (CSS .css)':<35} {css_count:>8} {css_lines:>10}")
    print(f"{'    Frontend (HTML .html)':<35} {html_count:>8} {html_lines:>10}")
    print(f"{'  Subtotal (Code)':<35} {code_files:>8} {code_lines:>10}")
    print()
    print("  [Config]")
    print(f"{'    YAML (.yaml/.yml)':<35} {yaml_count:>8} {yaml_lines:>10}")
    print(f"{'    JSON (.json)':<35} {json_count:>8} {json_lines:>10}")
    print(f"{'  Subtotal (Config)':<35} {config_files:>8} {config_lines:>10}")
    print()
    print("  [Scripts]")
    print(f"{'    Batch (.bat)':<35} {bat_count:>8} {bat_lines:>10}")
    print(f"{'    Shell (.sh)':<35} {sh_count:>8} {sh_lines:>10}")
    print(f"{'    JavaScript (.cjs/.mjs)':<35} {js_count:>8} {js_lines:>10}")
    print(f"{'  Subtotal (Scripts)':<35} {script_files:>8} {script_lines:>10}")
    print()
    print("  [Documentation]")
    print(f"{'    Markdown (.md)':<35} {md_count:>8} {md_lines:>10}")
    print()
    print("-"*55)
    total_files=code_files+config_files+script_files+md_count
    total_lines=code_lines+config_lines+script_lines+md_lines
    print(f"{'TOTAL':<35} {total_files:>8} {total_lines:>10}")
    print(f"{'TOTAL (Code only)':<35} {code_files:>8} {code_lines:>10}")
    print()

    print_top_files("Top 10 Largest Files - Backend (Python)",backend_py,backend_dir)
    print_top_files("Top 10 Largest Files - Frontend (TypeScript)",frontend_ts,frontend_src)

    if css_lines>0:
        print_top_files("CSS Files",frontend_css,frontend_src)

    if html_lines>0:
        print_top_files("HTML Files",frontend_html,frontend_dir)

    print_by_directory("By Directory - Backend",backend_py,backend_dir)
    print_by_directory("By Directory - Frontend",frontend_ts,frontend_src)

if __name__=="__main__":
    main()
