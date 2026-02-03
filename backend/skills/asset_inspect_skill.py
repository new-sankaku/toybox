import asyncio
import os
from typing import Dict
from .base import Skill,SkillResult,SkillContext,SkillCategory,SkillParameter
from .file_skills import FileSkillMixin


class AssetInspectSkill(FileSkillMixin,Skill):
 name="asset_inspect"
 description="画像・音声アセットのメタデータを検査します（サイズ、フォーマット、解像度等）"
 category=SkillCategory.ASSET
 parameters=[
  SkillParameter(name="path",type="string",description="検査対象ファイルのパス"),
  SkillParameter(name="detail",type="boolean",description="詳細情報を取得するか",required=False,default=False),
 ]

 IMAGE_EXTENSIONS={".png",".jpg",".jpeg",".gif",".bmp",".webp",".tiff",".tif",".ico",".svg"}
 AUDIO_EXTENSIONS={".wav",".mp3",".ogg",".flac",".aac",".m4a",".wma"}

 def __init__(self):
  super().__init__()

 async def execute(self,context:SkillContext,**kwargs)->SkillResult:
  path=kwargs.get("path","")
  detail=kwargs.get("detail",False)
  if not path:
   return SkillResult(success=False,error="path is required")
  full_path=self._resolve_path(path,context)
  if not self._is_allowed(full_path,context):
   return SkillResult(success=False,error=f"Access denied: {path}")
  if not os.path.exists(full_path):
   return SkillResult(success=False,error=f"File not found: {path}")
  ext=os.path.splitext(full_path)[1].lower()
  if ext in self.IMAGE_EXTENSIONS:
   return await asyncio.to_thread(self._inspect_image,full_path,detail)
  elif ext in self.AUDIO_EXTENSIONS:
   return await asyncio.to_thread(self._inspect_audio,full_path,detail)
  else:
   return await asyncio.to_thread(self._inspect_generic,full_path)

 def _inspect_image(self,path:str,detail:bool)->SkillResult:
  info:Dict={"path":path,"type":"image","fileSize":os.path.getsize(path)}
  try:
   from PIL import Image
   img=Image.open(path)
   info["width"]=img.width
   info["height"]=img.height
   info["mode"]=img.mode
   info["format"]=img.format
   if detail:
    info["dpi"]=img.info.get("dpi")
    info["hasAlpha"]="A" in img.mode
    info["isAnimated"]=getattr(img,"is_animated",False)
    if hasattr(img,"n_frames"):
     info["frameCount"]=img.n_frames
   return SkillResult(success=True,output=info,metadata={"assetType":"image"})
  except ImportError:
   info["warning"]="Pillow is not installed, limited info available"
   return SkillResult(success=True,output=info,metadata={"assetType":"image","limited":True})
  except Exception as e:
   return SkillResult(success=False,error=f"Failed to inspect image: {e}")

 def _inspect_audio(self,path:str,detail:bool)->SkillResult:
  info:Dict={"path":path,"type":"audio","fileSize":os.path.getsize(path)}
  ext=os.path.splitext(path)[1].lower()
  info["format"]=ext.lstrip(".")
  if ext==".wav":
   try:
    import wave
    with wave.open(path,"rb") as wf:
     info["channels"]=wf.getnchannels()
     info["sampleRate"]=wf.getframerate()
     info["sampleWidth"]=wf.getsampwidth()
     info["frames"]=wf.getnframes()
     info["duration"]=wf.getnframes()/wf.getframerate()
   except Exception as e:
    info["warning"]=f"Failed to parse WAV: {e}"
  return SkillResult(success=True,output=info,metadata={"assetType":"audio"})

 def _inspect_generic(self,path:str)->SkillResult:
  info={
   "path":path,
   "type":"unknown",
   "fileSize":os.path.getsize(path),
   "extension":os.path.splitext(path)[1],
  }
  return SkillResult(success=True,output=info,metadata={"assetType":"unknown"})
