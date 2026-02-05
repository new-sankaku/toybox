import os
import re
import struct
import zlib
import asyncio
from typing import Any,Dict,Tuple
from dataclasses import dataclass

from skills import SkillResult


@dataclass
class AssetGenerationResult:
    success:bool
    output:str
    metadata:Dict[str,Any]
    error:str=""


class MockAssetGenerator:

    STYLE_COLORS:Dict[str,Tuple[int,int,int]]={
        "pixel_art":(100,180,100),
        "anime":(180,130,200),
        "realistic":(130,160,200),
        "cartoon":(200,180,100),
    }
    DEFAULT_COLOR:Tuple[int,int,int]=(180,170,150)

    def __init__(self,base_output_dir:str):
        self._base_output_dir=base_output_dir

    async def generate_image(
        self,
        params:Dict[str,Any],
        default_output_dir:str="assets/images",
        output_format:str="png",
    )->SkillResult:
        prompt=params.get("prompt","placeholder")
        width=params.get("width",512)
        height=params.get("height",512)
        style=params.get("style","")
        output_path=params.get("output_path")
        full_path=self._resolve_output_path(
            output_path,prompt,output_format,default_output_dir
        )
        os.makedirs(os.path.dirname(full_path),exist_ok=True)
        png_data=self._create_minimal_png(width,height,style)
        await asyncio.to_thread(self._write_binary,full_path,png_data)
        relative_path=self._get_relative_path(full_path)
        return SkillResult(
            success=True,
            output=f"画像生成完了（モック）: {relative_path} ({width}x{height})",
            metadata={
                "path":full_path,
                "prompt":prompt,
                "width":width,
                "height":height,
                "style":style,
                "mock":True,
            },
        )

    def generate_audio(
        self,
        params:Dict[str,Any],
        audio_type:str="audio",
        output_format:str="wav",
        default_output_dir:str="assets/audio",
    )->SkillResult:
        prompt=params.get("prompt","") or params.get("text","")
        duration=params.get("duration",3.0)
        output_path=params.get("output_path")
        filename_prefix=f"{audio_type}_" if audio_type!="audio" else""
        full_path=self._resolve_output_path(
            output_path,
            prompt,
            output_format,
            default_output_dir,
            filename_prefix,
        )
        os.makedirs(os.path.dirname(full_path),exist_ok=True)
        wav_data=self._create_silent_wav(duration)
        self._write_binary(full_path,wav_data)
        relative_path=self._get_relative_path(full_path)
        return SkillResult(
            success=True,
            output=f"{audio_type}生成完了（モック）: {relative_path} ({duration}秒)",
            metadata={
                "path":full_path,
                "prompt":prompt,
                "duration":duration,
                "audio_type":audio_type,
                "mock":True,
            },
        )

    def _resolve_output_path(
        self,
        output_path:str|None,
        prompt:str,
        ext:str,
        default_dir:str,
        prefix:str="",
    )->str:
        if not output_path:
            safe_name=re.sub(r"[^\w\-]","_",prompt[:30])
            output_path=f"{default_dir}/{prefix}{safe_name}.{ext}"
        if os.path.isabs(output_path):
            return output_path
        return os.path.join(self._base_output_dir,output_path)

    def _get_relative_path(self,full_path:str)->str:
        if full_path.startswith(self._base_output_dir):
            return os.path.relpath(full_path,self._base_output_dir)
        return full_path

    def _create_minimal_png(self,width:int,height:int,style:str)->bytes:
        r,g,b=self.STYLE_COLORS.get(style,self.DEFAULT_COLOR)
        raw_data=b""
        for _ in range(height):
            raw_data+=b"\x00"
            for _ in range(width):
                raw_data+=bytes([r,g,b])
        return self._build_png(width,height,raw_data)

    def _build_png(self,width:int,height:int,raw_data:bytes)->bytes:
        sig=b"\x89PNG\r\n\x1a\n"
        ihdr=struct.pack(">IIBBBBB",width,height,8,2,0,0,0)
        compressed=zlib.compress(raw_data)
        return (
            sig
            +self._png_chunk(b"IHDR",ihdr)
            +self._png_chunk(b"IDAT",compressed)
            +self._png_chunk(b"IEND",b"")
        )

    def _png_chunk(self,chunk_type:bytes,data:bytes)->bytes:
        chunk=chunk_type+data
        crc=zlib.crc32(chunk)&0xFFFFFFFF
        return struct.pack(">I",len(data))+chunk+struct.pack(">I",crc)

    def _create_silent_wav(self,duration:float)->bytes:
        sample_rate=22050
        num_samples=int(sample_rate*duration)
        data_size=num_samples*2
        header=struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            36+data_size,
            b"WAVE",
            b"fmt ",
            16,
            1,
            1,
            sample_rate,
            sample_rate*2,
            2,
            16,
            b"data",
            data_size,
        )
        return header+b"\x00"*data_size

    def _write_binary(self,path:str,data:bytes)->None:
        with open(path,"wb") as f:
            f.write(data)
