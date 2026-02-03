import json
import difflib
from typing import Any,Dict
from .base import Skill,SkillResult,SkillContext,SkillCategory,SkillParameter


class SchemaValidateSkill(Skill):
 name="schema_validate"
 description="JSON/YAMLデータをスキーマに対してバリデーションします"
 category=SkillCategory.PROJECT
 parameters=[
  SkillParameter(name="data",type="string",description="バリデーション対象のJSON/YAML文字列"),
  SkillParameter(name="schema",type="string",description="JSONスキーマ文字列"),
  SkillParameter(name="format",type="string",description="データ形式: json, yaml",required=False,default="json"),
 ]

 def __init__(self):
  super().__init__()

 async def execute(self,context:SkillContext,**kwargs)->SkillResult:
  data_str=kwargs.get("data","")
  schema_str=kwargs.get("schema","")
  fmt=kwargs.get("format","json")
  if not data_str:
   return SkillResult(success=False,error="data is required")
  if not schema_str:
   return SkillResult(success=False,error="schema is required")
  try:
   if fmt=="yaml":
    import yaml
    data=yaml.safe_load(data_str)
   else:
    data=json.loads(data_str)
  except Exception as e:
   return SkillResult(success=False,error=f"Failed to parse data ({fmt}): {e}")
  try:
   schema=json.loads(schema_str)
  except Exception as e:
   return SkillResult(success=False,error=f"Failed to parse schema: {e}")
  errors=self._validate(data,schema)
  if errors:
   return SkillResult(success=True,output={"valid":False,"errors":errors},metadata={"errorCount":len(errors)})
  return SkillResult(success=True,output={"valid":True,"errors":[]},metadata={"errorCount":0})

 def _validate(self,data:Any,schema:Dict)->list:
  errors=[]
  schema_type=schema.get("type")
  if schema_type:
   type_map={"string":str,"number":(int,float),"integer":int,"boolean":bool,"array":list,"object":dict,"null":type(None)}
   expected=type_map.get(schema_type)
   if expected and not isinstance(data,expected):
    errors.append(f"Expected type '{schema_type}', got '{type(data).__name__}'")
    return errors
  if isinstance(data,dict) and schema_type=="object":
   required=schema.get("required",[])
   for req in required:
    if req not in data:
     errors.append(f"Missing required field: '{req}'")
   properties=schema.get("properties",{})
   for prop_name,prop_schema in properties.items():
    if prop_name in data:
     sub_errors=self._validate(data[prop_name],prop_schema)
     for e in sub_errors:
      errors.append(f"{prop_name}.{e}")
  if isinstance(data,list) and schema_type=="array":
   items_schema=schema.get("items")
   if items_schema:
    for i,item in enumerate(data):
     sub_errors=self._validate(item,items_schema)
     for e in sub_errors:
      errors.append(f"[{i}].{e}")
   min_items=schema.get("minItems")
   max_items=schema.get("maxItems")
   if min_items is not None and len(data)<min_items:
    errors.append(f"Array has {len(data)} items, minimum is {min_items}")
   if max_items is not None and len(data)>max_items:
    errors.append(f"Array has {len(data)} items, maximum is {max_items}")
  if isinstance(data,(int,float)) and schema_type in ("number","integer"):
   minimum=schema.get("minimum")
   maximum=schema.get("maximum")
   if minimum is not None and data<minimum:
    errors.append(f"Value {data} is less than minimum {minimum}")
   if maximum is not None and data>maximum:
    errors.append(f"Value {data} is greater than maximum {maximum}")
  if isinstance(data,str) and schema_type=="string":
   enum_values=schema.get("enum")
   if enum_values and data not in enum_values:
    errors.append(f"Value '{data}' not in enum: {enum_values}")
   min_length=schema.get("minLength")
   max_length=schema.get("maxLength")
   if min_length is not None and len(data)<min_length:
    errors.append(f"String length {len(data)} is less than minLength {min_length}")
   if max_length is not None and len(data)>max_length:
    errors.append(f"String length {len(data)} is greater than maxLength {max_length}")
  return errors


class DiffPatchSkill(Skill):
 name="diff_patch"
 description="テキスト間の差分を生成、または差分を適用します"
 category=SkillCategory.FILE
 parameters=[
  SkillParameter(name="operation",type="string",description="操作: diff, apply"),
  SkillParameter(name="original",type="string",description="元のテキスト（diff時）",required=False),
  SkillParameter(name="modified",type="string",description="変更後のテキスト（diff時）",required=False),
  SkillParameter(name="patch",type="string",description="適用するパッチ（apply時）",required=False),
  SkillParameter(name="target",type="string",description="パッチ適用対象のテキスト（apply時）",required=False),
  SkillParameter(name="context_lines",type="integer",description="差分のコンテキスト行数",required=False,default=3),
 ]

 def __init__(self):
  super().__init__()

 async def execute(self,context:SkillContext,**kwargs)->SkillResult:
  operation=kwargs.get("operation","")
  if operation=="diff":
   return self._generate_diff(kwargs)
  elif operation=="apply":
   return self._apply_patch(kwargs)
  else:
   return SkillResult(success=False,error=f"Unknown operation: {operation}. Use: diff, apply")

 def _generate_diff(self,kwargs:Dict)->SkillResult:
  original=kwargs.get("original","")
  modified=kwargs.get("modified","")
  context_lines=kwargs.get("context_lines",3)
  original_lines=original.splitlines(keepends=True)
  modified_lines=modified.splitlines(keepends=True)
  diff=list(difflib.unified_diff(original_lines,modified_lines,fromfile="original",tofile="modified",n=context_lines))
  diff_text="".join(diff)
  stats={"additions":0,"deletions":0}
  for line in diff:
   if line.startswith("+") and not line.startswith("+++"):
    stats["additions"]+=1
   elif line.startswith("-") and not line.startswith("---"):
    stats["deletions"]+=1
  return SkillResult(success=True,output=diff_text,metadata=stats)

 def _apply_patch(self,kwargs:Dict)->SkillResult:
  patch_text=kwargs.get("patch","")
  target=kwargs.get("target","")
  if not patch_text:
   return SkillResult(success=False,error="patch is required for apply")
  if not target:
   return SkillResult(success=False,error="target is required for apply")
  try:
   target_lines=target.splitlines(keepends=True)
   patch_lines=patch_text.splitlines(keepends=True)
   result_lines=list(target_lines)
   offset=0
   hunk_start=None
   removes=[]
   adds=[]
   for line in patch_lines:
    if line.startswith("@@"):
     if hunk_start is not None:
      result_lines,offset=self._apply_hunk(result_lines,hunk_start,removes,adds,offset)
     parts=line.split()
     old_range=parts[1]
     start=int(old_range.split(",")[0].lstrip("-"))-1
     hunk_start=start
     removes=[]
     adds=[]
    elif line.startswith("---") or line.startswith("+++"):
     continue
    elif line.startswith("-"):
     removes.append(line[1:])
    elif line.startswith("+"):
     adds.append(line[1:])
    elif line.startswith(" "):
     removes.append(line[1:])
     adds.append(line[1:])
   if hunk_start is not None:
    result_lines,offset=self._apply_hunk(result_lines,hunk_start,removes,adds,offset)
   result_text="".join(result_lines)
   return SkillResult(success=True,output=result_text,metadata={"applied":True})
  except Exception as e:
   return SkillResult(success=False,error=f"Failed to apply patch: {e}")

 def _apply_hunk(self,lines:list,start:int,removes:list,adds:list,offset:int)->tuple:
  pos=start+offset
  for i,rem in enumerate(removes):
   if pos<len(lines):
    lines.pop(pos)
  for i,add in enumerate(adds):
   lines.insert(pos+i,add)
  new_offset=offset+len(adds)-len(removes)
  return lines,new_offset
