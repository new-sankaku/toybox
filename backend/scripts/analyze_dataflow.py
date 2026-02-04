                      
"""
Data Flow Analyzer
Generates a data flow report comparing:
  -Backend API endpoints (Python handlers+Pydantic schemas)
  -Frontend API calls (TypeScript apiService+type definitions)
  -WebSocket events (server emit vs client type expectations)

Usage:
  python scripts/analyze_dataflow.py                    # Full report
  python scripts/analyze_dataflow.py--format md        # Markdown output
  python scripts/analyze_dataflow.py--check            # Type mismatch check only
  python scripts/analyze_dataflow.py--output FILE      # Write to file
"""

import sys
import os
import io
import re
import argparse
from typing import Dict,List,Optional,Tuple,Any,Set
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-","")!="utf8":
    sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding="utf-8",errors="replace")
    sys.stderr=io.TextIOWrapper(sys.stderr.buffer,encoding="utf-8",errors="replace")

sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataflow.api_map import API_MAP
from dataflow.ws_map import WS_EVENTS


PYTHON_TO_TS_TYPE={
    "str":"string",
    "int":"number",
    "float":"number",
    "bool":"boolean",
    "datetime":"string",
    "Dict[str, Any]":"Record<string, unknown>",
    "Optional[Dict[str, Any]]":"Record<string, unknown> | null",
    "Optional[str]":"string | null",
    "Optional[int]":"number | null",
    "Optional[float]":"number | null",
    "Optional[bool]":"boolean | null",
    "Optional[datetime]":"string | null",
    "List[str]":"string[]",
    "List[int]":"number[]",
}


def parse_ts_interfaces(ts_dirs)->Dict[str,Dict[str,dict]]:
    interfaces={}
    if isinstance(ts_dirs,str):
        ts_dirs=[ts_dirs]
    ts_files=[]
    for d in ts_dirs:
        ts_files.extend(Path(d).glob("*.ts"))

    for ts_file in ts_files:
        content=ts_file.read_text(encoding="utf-8")

        iface_pattern=r"(?:export\s+)?interface\s+(\w+)(?:\s+extends\s+([\w,\s]+))?\s*\{"
        for match in re.finditer(iface_pattern,content):
            name=match.group(1)
            extends=match.group(2)
            body_start=match.end()

            depth=1
            pos=body_start
            while pos<len(content) and depth>0:
                if content[pos]=="{":
                    depth+=1
                elif content[pos]=="}":
                    depth-=1
                pos+=1

            body=content[body_start :pos-1]

            fields={}
            for line in body.split("\n"):
                line=line.strip()
                if not line or line.startswith("//") or line.startswith("/*"):
                    continue
                field_match=re.match(r"(\w+)(\?)?:\s*(.+)",line)
                if field_match:
                    field_name=field_match.group(1)
                    optional=field_match.group(2)=="?"
                    field_type=field_match.group(3).strip()
                    if field_type.endswith(";"):
                        field_type=field_type[:-1].strip()
                    fields[field_name]={
                        "type":field_type,
                        "optional":optional,
                    }

            parent_fields={}
            if extends:
                for parent in extends.split(","):
                    parent=parent.strip()
                    if parent in interfaces:
                        parent_fields.update(interfaces[parent])

            combined={**parent_fields,**fields}
            interfaces[name]=combined

    return interfaces


def get_pydantic_fields(schema_name:str)->Optional[Dict[str,dict]]:
    try:
        from schemas import (
            ProjectSchema,ProjectCreateSchema,ProjectUpdateSchema,
            AgentSchema,AgentCreateSchema,AgentUpdateSchema,
            CheckpointSchema,CheckpointCreateSchema,CheckpointResolveSchema,
            GlobalCostSettingsSchema,GlobalCostSettingsUpdateSchema,
            BudgetStatusSchema,CostHistoryItemSchema,CostHistoryResponseSchema,
            CostSummarySchema,CostSummaryByServiceSchema,CostSummaryByProjectSchema,
            WebSocketSettingsSchema,AdvancedSettingsSchema,
            ConcurrentLimitsSchema,PromptComponentSchema,AgentSystemPromptSchema,
        )
    except ImportError:
        return None

    schema_map={
        "ProjectSchema":ProjectSchema,
        "ProjectCreateSchema":ProjectCreateSchema,
        "ProjectUpdateSchema":ProjectUpdateSchema,
        "AgentSchema":AgentSchema,
        "AgentCreateSchema":AgentCreateSchema,
        "AgentUpdateSchema":AgentUpdateSchema,
        "CheckpointSchema":CheckpointSchema,
        "CheckpointCreateSchema":CheckpointCreateSchema,
        "CheckpointResolveSchema":CheckpointResolveSchema,
        "GlobalCostSettingsSchema":GlobalCostSettingsSchema,
        "GlobalCostSettingsUpdateSchema":GlobalCostSettingsUpdateSchema,
        "BudgetStatusSchema":BudgetStatusSchema,
        "CostHistoryItemSchema":CostHistoryItemSchema,
        "CostHistoryResponseSchema":CostHistoryResponseSchema,
        "CostSummarySchema":CostSummarySchema,
        "CostSummaryByServiceSchema":CostSummaryByServiceSchema,
        "CostSummaryByProjectSchema":CostSummaryByProjectSchema,
        "WebSocketSettingsSchema":WebSocketSettingsSchema,
        "AdvancedSettingsSchema":AdvancedSettingsSchema,
        "ConcurrentLimitsSchema":ConcurrentLimitsSchema,
        "PromptComponentSchema":PromptComponentSchema,
        "AgentSystemPromptSchema":AgentSystemPromptSchema,
    }

    if schema_name not in schema_map:
        return None

    schema_cls=schema_map[schema_name]
    fields={}

    for field_name,field_info in schema_cls.model_fields.items():
        annotation=field_info.annotation
        type_str=_annotation_to_str(annotation)
        is_required=field_info.is_required()
        is_nullable=type_str.startswith("Optional[")

        alias=None
        if hasattr(schema_cls,"model_config"):
            config=schema_cls.model_config
            alias_gen=config.get("alias_generator")
            if alias_gen:
                alias=alias_gen(field_name)

        fields[field_name]={
            "type":type_str,
            "required":is_required,
            "nullable":is_nullable,
            "alias":alias,
        }

    return fields


def _annotation_to_str(annotation)->str:
    if annotation is None:
        return"None"

    import typing

    origin=getattr(annotation,"__origin__",None)
    args=getattr(annotation,"__args__",())

    if origin is typing.Union:
        non_none=[a for a in args if a is not type(None)]
        if type(None) in args and len(non_none)==1:
            inner=_annotation_to_str(non_none[0])
            return f"Optional[{inner}]"
        inner=", ".join(_annotation_to_str(a) for a in args)
        return f"Union[{inner}]"

    if origin is list:
        inner=_annotation_to_str(args[0]) if args else"Any"
        return f"List[{inner}]"

    if origin is dict:
        key=_annotation_to_str(args[0]) if args else"str"
        val=_annotation_to_str(args[1]) if len(args)>1 else"Any"
        return f"Dict[{key}, {val}]"

    if origin is not None:
        type_name=getattr(origin,"__name__",str(origin))
        if args:
            inner=", ".join(_annotation_to_str(a) for a in args)
            return f"{type_name}[{inner}]"
        return type_name

    if hasattr(annotation,"__name__"):
        return annotation.__name__

    type_str=str(annotation)
    type_str=type_str.replace("typing.","")
    type_str=type_str.replace("<class '","").replace("'>","")
    return type_str


def _py_type_to_ts(py_type:str)->str:
    direct=PYTHON_TO_TS_TYPE.get(py_type)
    if direct:
        return direct

    optional_match=re.match(r"Optional\[(.+)\]$",py_type)
    if optional_match:
        inner=_py_type_to_ts(optional_match.group(1))
        return f"{inner} | null"

    list_match=re.match(r"List\[(.+)\]$",py_type)
    if list_match:
        inner=_py_type_to_ts(list_match.group(1))
        return f"{inner}[]"

    dict_match=re.match(r"Dict\[(.+),\s*(.+)\]$",py_type)
    if dict_match:
        key=_py_type_to_ts(dict_match.group(1))
        val_raw=dict_match.group(2).strip()
        val=_py_type_to_ts(val_raw)
        return f"Record<{key}, {val}>"

    direct_base=PYTHON_TO_TS_TYPE.get(py_type)
    if direct_base:
        return direct_base

    if py_type.endswith("Schema"):
        return py_type[:-len("Schema")]

    if py_type=="Any":
        return"unknown"

    return py_type


def compare_fields(
    py_fields:Dict[str,dict],
    ts_fields:Dict[str,dict],
    has_alias_generator:bool=False,
)->List[dict]:
    mismatches=[]

    py_to_ts_name={}
    for py_name,info in py_fields.items():
        if has_alias_generator and info.get("alias"):
            ts_name=info["alias"]
        else:
            ts_name=py_name
        py_to_ts_name[py_name]=ts_name

    for py_name,py_info in py_fields.items():
        ts_name=py_to_ts_name[py_name]
        if ts_name not in ts_fields:
            mismatches.append({
                "field":ts_name,
                "issue":"MISSING_IN_TS",
                "py_type":py_info["type"],
                "ts_type":None,
                "py_required":py_info["required"],
            })
            continue

        ts_info=ts_fields[ts_name]
        py_type_ts=_py_type_to_ts(py_info["type"])

        ts_type=ts_info["type"]
        if not _types_compatible(py_type_ts,ts_type):
            mismatches.append({
                "field":ts_name,
                "issue":"TYPE_MISMATCH",
                "py_type":f"{py_info['type']} → {py_type_ts}",
                "ts_type":ts_type,
            })

        py_nullable=py_info.get("nullable",False)
        ts_optional=ts_info.get("optional",False)
        ts_nullable="null" in ts_type or"undefined" in ts_type

        if py_nullable and not ts_optional and not ts_nullable:
            mismatches.append({
                "field":ts_name,
                "issue":"NULLABLE_MISMATCH",
                "py_type":f"nullable ({py_info['type']})",
                "ts_type":f"non-null ({ts_type})",
            })
        elif not py_nullable and (ts_optional or ts_nullable):
            mismatches.append({
                "field":ts_name,
                "issue":"NULLABLE_MISMATCH",
                "py_type":f"non-null ({py_info['type']})",
                "ts_type":f"nullable ({ts_type})",
            })

    ts_mapped_names=set(py_to_ts_name.values())
    for ts_name in ts_fields:
        if ts_name not in ts_mapped_names:
            mismatches.append({
                "field":ts_name,
                "issue":"MISSING_IN_PY",
                "py_type":None,
                "ts_type":ts_fields[ts_name]["type"],
            })

    return mismatches


def _normalize_ts_type(py_type:str)->str:
    t=py_type.strip()
    t=re.sub(r"Schema\b","",t)
    return t


def _types_compatible(py_ts_type:str,ts_type:str)->bool:
    py_clean=_normalize_ts_type(py_ts_type).lower()
    ts_clean=ts_type.strip().lower()

    if py_clean==ts_clean:
        return True

    nullable_py="| null" in py_clean or"| undefined" in py_clean
    nullable_ts="| null" in ts_clean or"| undefined" in ts_clean

    py_base=re.sub(r"\s*\|\s*(null|undefined)","",py_clean).strip()
    ts_base=re.sub(r"\s*\|\s*(null|undefined)","",ts_clean).strip()

    if py_base==ts_base:
        return True

    primitives={"string","number","boolean"}
    if py_base in primitives and ts_base==py_base:
        return True

    if"record<string" in py_base and"record<string" in ts_base:
        return True

    if py_base.endswith("[]") and ts_base.endswith("[]"):
        py_inner=py_base[:-2].strip()
        ts_inner=ts_base[:-2].strip()
        return _types_compatible(py_inner,ts_inner)

    return False


def generate_rest_table(api_map:list)->str:
    lines=[]
    lines.append("# REST API Data Flow\n")

    current_handler_file=""
    for entry in api_map:
        handler_file=entry["handler"].split("::")[0]
        if handler_file!=current_handler_file:
            current_handler_file=handler_file
            section_name=handler_file.replace("handlers/","").replace(".py","").replace("_"," ").title()
            lines.append(f"\n## {section_name}\n")
            lines.append("| Method | Endpoint | Handler | Req Schema | Res Schema | TS Response | WS Events |")
            lines.append("|--------|----------|---------|------------|------------|-------------|-----------|")

        method=entry["method"]
        endpoint=entry["endpoint"]
        handler=entry["handler"].split("::")[-1]
        req=entry["request_schema"] or"-"
        res=entry["response_schema"] or"**UNTYPED**"
        if entry["response_list"] and res!="**UNTYPED**" and res!="-":
            res=f"{res}[]"
        ts_res=entry["ts_response"]
        emits=", ".join(entry["emits"]) if entry["emits"] else"-"

        lines.append(f"| {method} | `{endpoint}` | {handler} | {req} | {res} | `{ts_res}` | {emits} |")

    return"\n".join(lines)


def generate_ws_table(ws_events:list)->str:
    lines=[]
    lines.append("\n# WebSocket Events\n")

    lines.append("## Server → Client\n")
    lines.append("| Event | TS Type | Data Fields | Room | Emit Sources |")
    lines.append("|-------|---------|-------------|------|-------------|")

    for ev in ws_events:
        if ev["direction"]!="server_to_client":
            continue
        event=ev["event"]
        ts_type=ev["ts_type"] or"**UNTYPED**"
        fields=", ".join(f"{k}: {v}" for k,v in ev["data_fields"].items())
        room=ev["room"]
        sources=", ".join(s.split("::")[-1] for s in ev["sources"])
        lines.append(f"| `{event}` | `{ts_type}` | {fields} | {room} | {sources} |")

    lines.append("\n## Client → Server\n")
    lines.append("| Event | TS Type | Data Fields |")
    lines.append("|-------|---------|-------------|")

    for ev in ws_events:
        if ev["direction"]!="client_to_server":
            continue
        event=ev["event"]
        ts_type=ev["ts_type"] or"**UNTYPED**"
        fields=", ".join(f"{k}: {v}" for k,v in ev["data_fields"].items())
        lines.append(f"| `{event}` | `{ts_type}` | {fields} |")

    return"\n".join(lines)


def generate_schema_coverage(api_map:list)->str:
    lines=[]
    lines.append("\n# Schema Coverage Report\n")

    total=len(api_map)
    with_schema=sum(1 for e in api_map if e["response_schema"])
    without_schema=total-with_schema

    lines.append(f"- Total endpoints: **{total}**")
    lines.append(f"- With Pydantic schema: **{with_schema}** ({with_schema*100//total}%)")
    lines.append(f"- Without schema (UNTYPED): **{without_schema}** ({without_schema*100//total}%)")

    if without_schema>0:
        lines.append("\n## Untyped Endpoints (need Pydantic schemas)\n")
        lines.append("| Method | Endpoint | Handler | TS Expected |")
        lines.append("|--------|----------|---------|-------------|")
        for entry in api_map:
            if not entry["response_schema"]:
                method=entry["method"]
                endpoint=entry["endpoint"]
                handler=entry["handler"].split("::")[-1]
                ts_res=entry["ts_response"]
                lines.append(f"| {method} | `{endpoint}` | {handler} | `{ts_res}` |")

    return"\n".join(lines)


def generate_ws_coverage(ws_events:list)->str:
    lines=[]
    lines.append("\n# WebSocket Type Coverage\n")

    server_events=[e for e in ws_events if e["direction"]=="server_to_client"]
    total=len(server_events)
    with_type=sum(1 for e in server_events if e["ts_type"])
    without_type=total-with_type

    lines.append(f"- Total server→client events: **{total}**")
    lines.append(f"- With TS type in WebSocketEventMap: **{with_type}** ({with_type*100//total if total else 0}%)")
    lines.append(f"- Without TS type: **{without_type}** ({without_type*100//total if total else 0}%)")

    if without_type>0:
        lines.append("\n## Untyped WS Events\n")
        lines.append("| Event | Server Fields | Sources |")
        lines.append("|-------|---------------|---------|")
        for ev in server_events:
            if not ev["ts_type"]:
                event=ev["event"]
                fields=", ".join(f"{k}: {v}" for k,v in ev["data_fields"].items())
                sources=", ".join(s.split("::")[-1] for s in ev["sources"])
                lines.append(f"| `{event}` | {fields} | {sources} |")

    return"\n".join(lines)


CRITICAL_ISSUES={"MISSING_IN_TS","MISSING_IN_PY"}

SCHEMA_TO_TS={
    "ProjectSchema":"Project",
    "AgentSchema":"Agent",
    "CheckpointSchema":"Checkpoint",
    "CheckpointResolveSchema":"CheckpointResolution",
    "GlobalCostSettingsSchema":"GlobalCostSettings",
    "BudgetStatusSchema":"BudgetStatus",
    "CostHistoryItemSchema":"CostHistoryItem",
    "CostHistoryResponseSchema":"CostHistoryResponse",
    "CostSummarySchema":"CostSummary",
    "PromptComponentSchema":"PromptComponent",
    "AgentSystemPromptSchema":"AgentSystemPrompt",
}


def generate_type_check_report(ts_dir:str)->Tuple[str,dict]:
    lines=[]
    lines.append("\n# Type Mismatch Report\n")

    ts_interfaces=parse_ts_interfaces(ts_dir)

    total_checked=0
    total_mismatches=0
    errors=0
    warnings=0

    for schema_name,ts_name in SCHEMA_TO_TS.items():
        py_fields=get_pydantic_fields(schema_name)
        if not py_fields:
            lines.append(f"## {schema_name} ↔ {ts_name}")
            lines.append(f"⚠ Could not load Pydantic schema `{schema_name}`\n")
            continue

        ts_fields=ts_interfaces.get(ts_name)
        if not ts_fields:
            lines.append(f"## {schema_name} ↔ {ts_name}")
            lines.append(f"⚠ TypeScript interface `{ts_name}` not found\n")
            continue

        has_alias=False
        if py_fields:
            first_field=next(iter(py_fields.values()),{})
            has_alias=first_field.get("alias") is not None

        mismatches=compare_fields(py_fields,ts_fields,has_alias_generator=has_alias)
        total_checked+=1

        if mismatches:
            total_mismatches+=len(mismatches)
            for m in mismatches:
                if m["issue"] in CRITICAL_ISSUES:
                    errors+=1
                else:
                    warnings+=1
            lines.append(f"## {schema_name} ↔ {ts_name} — {len(mismatches)} issue(s)\n")
            lines.append("| Field | Issue | Python | TypeScript |")
            lines.append("|-------|-------|--------|------------|")
            for m in mismatches:
                field=m["field"]
                issue=m["issue"]
                py_t=m.get("py_type","-") or"-"
                ts_t=m.get("ts_type","-") or"-"
                lines.append(f"| `{field}` | {issue} | {py_t} | {ts_t} |")
            lines.append("")
        else:
            lines.append(f"## {schema_name} ↔ {ts_name} — OK\n")

    lines.append(f"\n**Summary:** {total_checked} schemas checked, {total_mismatches} issues ({errors} errors, {warnings} warnings)\n")

    stats={"checked":total_checked,"total":total_mismatches,"errors":errors,"warnings":warnings}
    return"\n".join(lines),stats


def main():
    parser=argparse.ArgumentParser(description="Data Flow Analyzer")
    parser.add_argument("--format",choices=["md","text"],default="md")
    parser.add_argument("--check",action="store_true",help="Type mismatch check only")
    parser.add_argument("--ci",action="store_true",help="CI mode: exit 1 on MISSING_IN_TS/MISSING_IN_PY errors")
    parser.add_argument("--output","-o",help="Output file path")
    parser.add_argument("--ts-dir",default=None,help="TypeScript types directory")
    args=parser.parse_args()

    project_root=Path(__file__).parent.parent.parent
    src_root=project_root/"langgraph-studio"/"src"
    if args.ts_dir:
        ts_dir=[args.ts_dir]
    else:
        ts_dir=[str(src_root/"types"),str(src_root/"services")]

    sections=[]
    stats=None

    if args.check or args.ci:
        report_text,stats=generate_type_check_report(ts_dir)
        sections.append(report_text)
    else:
        sections.append(generate_rest_table(API_MAP))
        sections.append(generate_ws_table(WS_EVENTS))
        sections.append(generate_schema_coverage(API_MAP))
        sections.append(generate_ws_coverage(WS_EVENTS))
        report_text,stats=generate_type_check_report(ts_dir)
        sections.append(report_text)

    output="\n".join(sections)

    if args.output:
        Path(args.output).write_text(output,encoding="utf-8")
        print(f"Report written to: {args.output}")
    else:
        print(output)

    if args.ci and stats:
        if stats["errors"]>0:
            print(f"\nCI FAIL: {stats['errors']} field mismatch error(s) (MISSING_IN_TS/MISSING_IN_PY)")
            sys.exit(1)
        if stats["warnings"]>0:
            print(f"\nCI WARN: {stats['warnings']} type warning(s) (non-blocking)")
        sys.exit(0)


if __name__=="__main__":
    main()
