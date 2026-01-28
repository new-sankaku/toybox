import os
import asyncio
import base64
from typing import Optional,Dict,Any,List
from .base import Skill,SkillResult,SkillContext,SkillCategory,SkillParameter


class ImageGenerateSkill(Skill):
 name="image_generate"
 description="画像を生成します（ComfyUI/Stable Diffusion）"
 category=SkillCategory.ASSET
 parameters=[
  SkillParameter(name="prompt",type="string",description="画像の説明（英語推奨）"),
  SkillParameter(name="negative_prompt",type="string",description="除外したい要素",required=False,default=""),
  SkillParameter(name="width",type="integer",description="幅",required=False,default=512),
  SkillParameter(name="height",type="integer",description="高さ",required=False,default=512),
  SkillParameter(name="output_path",type="string",description="出力ファイルパス",required=False),
  SkillParameter(name="style",type="string",description="スタイル: pixel_art, anime, realistic, cartoon",required=False,default=""),
 ]

 STYLE_PROMPTS={
  "pixel_art":"pixel art, 16-bit, retro game style, ",
  "anime":"anime style, cel shaded, vibrant colors, ",
  "realistic":"photorealistic, detailed, high quality, ",
  "cartoon":"cartoon style, bold outlines, colorful, ",
 }

 def __init__(self):
  super().__init__()

 async def execute(self,context:SkillContext,**kwargs)->SkillResult:
  prompt=kwargs.get("prompt","")
  negative_prompt=kwargs.get("negative_prompt","")
  width=kwargs.get("width",512)
  height=kwargs.get("height",512)
  output_path=kwargs.get("output_path")
  style=kwargs.get("style","")
  if not prompt:
   return SkillResult(success=False,error="prompt is required")
  if style and style in self.STYLE_PROMPTS:
   prompt=self.STYLE_PROMPTS[style]+prompt
  result=await asyncio.to_thread(self._generate_image,prompt,negative_prompt,width,height,output_path,context)
  return result

 def _generate_image(self,prompt:str,negative_prompt:str,width:int,height:int,output_path:Optional[str],context:SkillContext)->SkillResult:
  try:
   from providers.local_comfyui import LocalComfyUIProvider
   from providers.base import AIProviderConfig
   timeout=context.restrictions.get("timeout",context.timeout_seconds)
   config=AIProviderConfig(timeout=timeout)
   provider=LocalComfyUIProvider(config)
   test=provider.test_connection()
   if not test.get("success"):
    return SkillResult(success=False,error=f"ComfyUI接続失敗: {test.get('message')}")
   result=provider.generate_image(
    prompt=prompt,
    negative_prompt=negative_prompt,
    width=width,
    height=height,
   )
   if result.get("success"):
    return SkillResult(
     success=True,
     output=f"画像生成リクエスト送信完了 (prompt_id: {result.get('prompt_id')})",
     metadata={
      "prompt_id":result.get("prompt_id"),
      "prompt":prompt,
      "width":width,
      "height":height,
     }
    )
   return SkillResult(success=False,error=result.get("message","画像生成に失敗しました"))
  except ImportError:
   return SkillResult(success=False,error="ComfyUIプロバイダーが利用できません")
  except Exception as e:
   return SkillResult(success=False,error=str(e))


class BgmGenerateSkill(Skill):
 name="bgm_generate"
 description="BGM（背景音楽）を生成します"
 category=SkillCategory.ASSET
 parameters=[
  SkillParameter(name="prompt",type="string",description="音楽の説明（例: epic orchestral battle music）"),
  SkillParameter(name="duration",type="number",description="長さ（秒）",required=False,default=30.0),
  SkillParameter(name="output_path",type="string",description="出力ファイルパス",required=False),
  SkillParameter(name="style",type="string",description="スタイル: orchestral, electronic, ambient, rock, jazz",required=False,default=""),
 ]

 STYLE_PROMPTS={
  "orchestral":"orchestral, symphonic, cinematic, ",
  "electronic":"electronic, synth, EDM, ",
  "ambient":"ambient, atmospheric, calm, ",
  "rock":"rock, guitar, drums, energetic, ",
  "jazz":"jazz, smooth, saxophone, piano, ",
  "chiptune":"8-bit, chiptune, retro game music, ",
 }

 def __init__(self):
  super().__init__()

 async def execute(self,context:SkillContext,**kwargs)->SkillResult:
  prompt=kwargs.get("prompt","")
  duration=kwargs.get("duration",30.0)
  output_path=kwargs.get("output_path")
  style=kwargs.get("style","")
  if not prompt:
   return SkillResult(success=False,error="prompt is required")
  max_duration=context.restrictions.get("max_duration",120)
  if duration>max_duration:
   return SkillResult(success=False,error=f"Duration too long: {duration}s (limit: {max_duration}s)")
  if style and style in self.STYLE_PROMPTS:
   prompt=self.STYLE_PROMPTS[style]+prompt
  result=await asyncio.to_thread(self._generate_bgm,prompt,duration,output_path,context)
  return result

 def _generate_bgm(self,prompt:str,duration:float,output_path:Optional[str],context:SkillContext)->SkillResult:
  try:
   from providers.local_audiocraft import LocalAudioCraftProvider
   from providers.base import AIProviderConfig
   timeout=context.restrictions.get("timeout",context.timeout_seconds)
   config=AIProviderConfig(timeout=timeout)
   provider=LocalAudioCraftProvider(config)
   test=provider.test_connection()
   if not test.get("success"):
    return SkillResult(success=False,error=f"AudioCraft接続失敗: {test.get('message')}")
   result=provider.generate_music(prompt=prompt,duration=duration)
   if result.get("success"):
    output_info={"prompt":prompt,"duration":result.get("duration",duration)}
    if output_path and result.get("audio_base64"):
     full_path=os.path.join(context.working_dir,output_path) if not os.path.isabs(output_path) else output_path
     os.makedirs(os.path.dirname(full_path),exist_ok=True)
     with open(full_path,"wb") as f:
      f.write(base64.b64decode(result["audio_base64"]))
     output_info["saved_to"]=full_path
    return SkillResult(
     success=True,
     output=f"BGM生成完了: {prompt[:50]}...",
     metadata=output_info
    )
   return SkillResult(success=False,error=result.get("message","BGM生成に失敗しました"))
  except ImportError:
   return SkillResult(success=False,error="AudioCraftプロバイダーが利用できません")
  except Exception as e:
   return SkillResult(success=False,error=str(e))


class SfxGenerateSkill(Skill):
 name="sfx_generate"
 description="効果音を生成します"
 category=SkillCategory.ASSET
 parameters=[
  SkillParameter(name="prompt",type="string",description="効果音の説明（例: sword slash, explosion, footsteps）"),
  SkillParameter(name="duration",type="number",description="長さ（秒）",required=False,default=3.0),
  SkillParameter(name="output_path",type="string",description="出力ファイルパス",required=False),
 ]

 def __init__(self):
  super().__init__()

 async def execute(self,context:SkillContext,**kwargs)->SkillResult:
  prompt=kwargs.get("prompt","")
  duration=kwargs.get("duration",3.0)
  output_path=kwargs.get("output_path")
  if not prompt:
   return SkillResult(success=False,error="prompt is required")
  max_duration=context.restrictions.get("max_duration",10)
  if duration>max_duration:
   return SkillResult(success=False,error=f"Duration too long: {duration}s (limit: {max_duration}s)")
  result=await asyncio.to_thread(self._generate_sfx,prompt,duration,output_path,context)
  return result

 def _generate_sfx(self,prompt:str,duration:float,output_path:Optional[str],context:SkillContext)->SkillResult:
  try:
   from providers.local_audiocraft import LocalAudioCraftProvider
   from providers.base import AIProviderConfig
   timeout=context.restrictions.get("timeout",context.timeout_seconds)
   config=AIProviderConfig(timeout=timeout)
   provider=LocalAudioCraftProvider(config)
   test=provider.test_connection()
   if not test.get("success"):
    return SkillResult(success=False,error=f"AudioCraft接続失敗: {test.get('message')}")
   result=provider.generate_sfx(prompt=prompt,duration=duration)
   if result.get("success"):
    output_info={"prompt":prompt,"duration":result.get("duration",duration)}
    if output_path and result.get("audio_base64"):
     full_path=os.path.join(context.working_dir,output_path) if not os.path.isabs(output_path) else output_path
     os.makedirs(os.path.dirname(full_path),exist_ok=True)
     with open(full_path,"wb") as f:
      f.write(base64.b64decode(result["audio_base64"]))
     output_info["saved_to"]=full_path
    return SkillResult(
     success=True,
     output=f"効果音生成完了: {prompt[:50]}",
     metadata=output_info
    )
   return SkillResult(success=False,error=result.get("message","効果音生成に失敗しました"))
  except ImportError:
   return SkillResult(success=False,error="AudioCraftプロバイダーが利用できません")
  except Exception as e:
   return SkillResult(success=False,error=str(e))


class VoiceGenerateSkill(Skill):
 name="voice_generate"
 description="テキストから音声を生成します（TTS）"
 category=SkillCategory.ASSET
 parameters=[
  SkillParameter(name="text",type="string",description="読み上げるテキスト"),
  SkillParameter(name="language",type="string",description="言語: ja, en, zh, ko",required=False,default="ja"),
  SkillParameter(name="speaker",type="string",description="話者ID（プロバイダー依存）",required=False,default=""),
  SkillParameter(name="output_path",type="string",description="出力ファイルパス",required=False),
  SkillParameter(name="speed",type="number",description="話速（0.5-2.0）",required=False,default=1.0),
 ]

 def __init__(self):
  super().__init__()

 async def execute(self,context:SkillContext,**kwargs)->SkillResult:
  text=kwargs.get("text","")
  language=kwargs.get("language","ja")
  speaker=kwargs.get("speaker","")
  output_path=kwargs.get("output_path")
  speed=kwargs.get("speed",1.0)
  if not text:
   return SkillResult(success=False,error="text is required")
  result=await asyncio.to_thread(self._generate_voice,text,language,speaker,output_path,speed,context)
  return result

 def _generate_voice(self,text:str,language:str,speaker:str,output_path:Optional[str],speed:float,context:SkillContext)->SkillResult:
  try:
   from providers.local_coqui_tts import LocalCoquiTTSProvider
   from providers.base import AIProviderConfig
   timeout=context.restrictions.get("timeout",context.timeout_seconds)
   config=AIProviderConfig(timeout=timeout)
   provider=LocalCoquiTTSProvider(config)
   test=provider.test_connection()
   if not test.get("success"):
    return SkillResult(success=False,error=f"Coqui TTS接続失敗: {test.get('message')}")
   result=provider.synthesize(text=text,language=language,speaker_id=speaker if speaker else None,speed=speed)
   if result.get("success"):
    output_info={"text":text[:100],"language":language}
    if output_path and result.get("audio_base64"):
     full_path=os.path.join(context.working_dir,output_path) if not os.path.isabs(output_path) else output_path
     os.makedirs(os.path.dirname(full_path),exist_ok=True)
     with open(full_path,"wb") as f:
      f.write(base64.b64decode(result["audio_base64"]))
     output_info["saved_to"]=full_path
    return SkillResult(
     success=True,
     output=f"音声生成完了: {text[:30]}...",
     metadata=output_info
    )
   return SkillResult(success=False,error=result.get("message","音声生成に失敗しました"))
  except ImportError:
   return SkillResult(success=False,error="Coqui TTSプロバイダーが利用できません")
  except Exception as e:
   return SkillResult(success=False,error=str(e))
