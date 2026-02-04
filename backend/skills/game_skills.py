import asyncio
import json
import os
from typing import Dict,Optional
from .base import Skill,SkillResult,SkillContext,SkillCategory,SkillParameter
from .file_skills import FileSkillMixin
from middleware.logger import get_logger


class GameDataTransformSkill(Skill):
 name="game_data_transform"
 description="ゲームデータのフォーマット変換（JSON⇔YAML、データ構造変換）"
 category=SkillCategory.PROJECT
 parameters=[
  SkillParameter(name="operation",type="string",description="操作: json_to_yaml, yaml_to_json, transform"),
  SkillParameter(name="data",type="string",description="変換対象のデータ文字列"),
  SkillParameter(name="template",type="string",description="変換テンプレート（transform時）",required=False),
 ]

 def __init__(self):
  super().__init__()

 async def execute(self,context:SkillContext,**kwargs)->SkillResult:
  operation=kwargs.get("operation","")
  data_str=kwargs.get("data","")
  template=kwargs.get("template","")
  if not data_str:
   return SkillResult(success=False,error="data is required")
  if operation=="json_to_yaml":
   return self._json_to_yaml(data_str)
  elif operation=="yaml_to_json":
   return self._yaml_to_json(data_str)
  elif operation=="transform":
   return self._transform(data_str,template)
  else:
   return SkillResult(success=False,error=f"Unknown operation: {operation}. Use: json_to_yaml, yaml_to_json, transform")

 def _json_to_yaml(self,data_str:str)->SkillResult:
  try:
   data=json.loads(data_str)
   import yaml
   yaml_str=yaml.dump(data,allow_unicode=True,default_flow_style=False,sort_keys=False)
   return SkillResult(success=True,output=yaml_str,metadata={"format":"yaml"})
  except json.JSONDecodeError as e:
   return SkillResult(success=False,error=f"Invalid JSON: {e}")
  except ImportError:
   return SkillResult(success=False,error="PyYAML is not installed")

 def _yaml_to_json(self,data_str:str)->SkillResult:
  try:
   import yaml
   data=yaml.safe_load(data_str)
   json_str=json.dumps(data,ensure_ascii=False,indent=2)
   return SkillResult(success=True,output=json_str,metadata={"format":"json"})
  except Exception as e:
   return SkillResult(success=False,error=f"Invalid YAML: {e}")

 def _transform(self,data_str:str,template:str)->SkillResult:
  try:
   data=json.loads(data_str)
  except json.JSONDecodeError:
   try:
    import yaml
    data=yaml.safe_load(data_str)
   except Exception as e:
    return SkillResult(success=False,error=f"Failed to parse data: {e}")
  if not template:
   if isinstance(data,list):
    result={"items":data,"count":len(data)}
   elif isinstance(data,dict):
    result={"keys":list(data.keys()),"data":data}
   else:
    result={"value":data}
   return SkillResult(success=True,output=result,metadata={"transformed":True})
  try:
   tmpl=json.loads(template)
   result=self._apply_template(data,tmpl)
   return SkillResult(success=True,output=result,metadata={"transformed":True})
  except Exception as e:
   return SkillResult(success=False,error=f"Template application failed: {e}")

 def _apply_template(self,data,template):
  if isinstance(template,str) and template.startswith("$."):
   path=template[2:].split(".")
   result=data
   for key in path:
    if isinstance(result,dict):
     result=result.get(key)
    elif isinstance(result,list) and key.isdigit():
     result=result[int(key)]
    else:
     return None
   return result
  elif isinstance(template,dict):
   return {k:self._apply_template(data,v) for k,v in template.items()}
  elif isinstance(template,list):
   return [self._apply_template(data,item) for item in template]
  return template


class SpriteSheetSkill(FileSkillMixin,Skill):
 name="sprite_sheet"
 description="スプライトシートの生成・分割・情報取得を行います"
 category=SkillCategory.ASSET
 parameters=[
  SkillParameter(name="operation",type="string",description="操作: info, split, pack"),
  SkillParameter(name="path",type="string",description="スプライトシート画像のパス"),
  SkillParameter(name="frame_width",type="integer",description="フレーム幅（split時）",required=False),
  SkillParameter(name="frame_height",type="integer",description="フレーム高さ（split時）",required=False),
  SkillParameter(name="output_dir",type="string",description="出力ディレクトリ（split時）",required=False),
  SkillParameter(name="input_dir",type="string",description="入力ディレクトリ（pack時）",required=False),
  SkillParameter(name="columns",type="integer",description="列数（pack時）",required=False,default=4),
 ]

 def __init__(self):
  super().__init__()

 async def execute(self,context:SkillContext,**kwargs)->SkillResult:
  operation=kwargs.get("operation","")
  path=kwargs.get("path","")
  if operation in ("info","split") and not path:
   return SkillResult(success=False,error="path is required")
  if operation=="info":
   full_path=self._resolve_path(path,context)
   if not self._is_allowed(full_path,context):
    return SkillResult(success=False,error=f"Access denied: {path}")
   return await asyncio.to_thread(self._get_info,full_path)
  elif operation=="split":
   full_path=self._resolve_path(path,context)
   if not self._is_allowed(full_path,context):
    return SkillResult(success=False,error=f"Access denied: {path}")
   frame_width=kwargs.get("frame_width")
   frame_height=kwargs.get("frame_height")
   output_dir=kwargs.get("output_dir","")
   if not frame_width or not frame_height:
    return SkillResult(success=False,error="frame_width and frame_height are required for split")
   out_path=self._resolve_path(output_dir or os.path.dirname(path),context)
   return await asyncio.to_thread(self._split,full_path,frame_width,frame_height,out_path)
  elif operation=="pack":
   input_dir=kwargs.get("input_dir","")
   if not input_dir:
    return SkillResult(success=False,error="input_dir is required for pack")
   full_input=self._resolve_path(input_dir,context)
   full_output=self._resolve_path(path or"spritesheet.png",context)
   if not self._is_allowed(full_input,context) or not self._is_allowed(full_output,context):
    return SkillResult(success=False,error="Access denied")
   columns=kwargs.get("columns",4)
   return await asyncio.to_thread(self._pack,full_input,full_output,columns)
  else:
   return SkillResult(success=False,error=f"Unknown operation: {operation}. Use: info, split, pack")

 def _get_info(self,path:str)->SkillResult:
  try:
   from PIL import Image
   img=Image.open(path)
   return SkillResult(success=True,output={
    "width":img.width,"height":img.height,"mode":img.mode,"format":img.format,
   },metadata={"path":path})
  except ImportError:
   return SkillResult(success=False,error="Pillow is not installed. Install with: pip install Pillow")
  except Exception as e:
   return SkillResult(success=False,error=f"Failed to read image: {e}")

 def _split(self,path:str,frame_w:int,frame_h:int,output_dir:str)->SkillResult:
  try:
   from PIL import Image
   img=Image.open(path)
   os.makedirs(output_dir,exist_ok=True)
   cols=img.width//frame_w
   rows=img.height//frame_h
   frames=[]
   for row in range(rows):
    for col in range(cols):
     x=col*frame_w
     y=row*frame_h
     frame=img.crop((x,y,x+frame_w,y+frame_h))
     fname=f"frame_{row:03d}_{col:03d}.png"
     frame.save(os.path.join(output_dir,fname))
     frames.append(fname)
   return SkillResult(success=True,output=f"Split into {len(frames)} frames",metadata={"frames":frames,"rows":rows,"cols":cols})
  except ImportError:
   return SkillResult(success=False,error="Pillow is not installed. Install with: pip install Pillow")
  except Exception as e:
   return SkillResult(success=False,error=f"Failed to split sprite sheet: {e}")

 def _pack(self,input_dir:str,output_path:str,columns:int)->SkillResult:
  try:
   from PIL import Image
   files=sorted([f for f in os.listdir(input_dir) if f.lower().endswith((".png",".jpg",".jpeg",".bmp"))])
   if not files:
    return SkillResult(success=False,error="No image files found in input directory")
   images=[Image.open(os.path.join(input_dir,f)) for f in files]
   frame_w=max(img.width for img in images)
   frame_h=max(img.height for img in images)
   rows=(len(images)+columns-1)//columns
   sheet=Image.new("RGBA",(frame_w*columns,frame_h*rows),(0,0,0,0))
   for i,img in enumerate(images):
    col=i%columns
    row=i//columns
    sheet.paste(img,(col*frame_w,row*frame_h))
   os.makedirs(os.path.dirname(output_path) or".",exist_ok=True)
   sheet.save(output_path)
   return SkillResult(success=True,output=f"Packed {len(images)} images into sprite sheet",metadata={
    "outputPath":output_path,"frameCount":len(images),"sheetWidth":sheet.width,"sheetHeight":sheet.height,
    "frameWidth":frame_w,"frameHeight":frame_h,"columns":columns,"rows":rows,
   })
  except ImportError:
   return SkillResult(success=False,error="Pillow is not installed. Install with: pip install Pillow")
  except Exception as e:
   return SkillResult(success=False,error=f"Failed to pack sprite sheet: {e}")
