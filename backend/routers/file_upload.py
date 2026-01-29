import os
import uuid
import shutil
import aiofiles
from fastapi import APIRouter,HTTPException,UploadFile,File,Form
from fastapi.responses import FileResponse
from typing import Optional
from core.dependencies import get_data_store

router=APIRouter()

ALLOWED_EXTENSIONS={
 'txt','md','py','js','ts','jsx','tsx','html','css','json','xml','yaml','yml',
 'java','c','cpp','h','cs','go','rs','rb','php','swift','kt',
 'png','jpg','jpeg','gif','webp','svg','bmp','ico',
 'mp3','wav','ogg','flac','aac','m4a','wma',
 'mp4','webm','mov','avi','mkv','wmv',
 'pdf','zip','tar','gz','tgz','7z','rar',
}

CATEGORY_MAP={
 'txt':'document','md':'document','pdf':'document',
 'py':'code','js':'code','ts':'code','jsx':'code','tsx':'code',
 'html':'code','css':'code','json':'code','xml':'code','yaml':'code','yml':'code',
 'java':'code','c':'code','cpp':'code','h':'code','cs':'code',
 'go':'code','rs':'code','rb':'code','php':'code','swift':'code','kt':'code',
 'png':'image','jpg':'image','jpeg':'image','gif':'image',
 'webp':'image','svg':'image','bmp':'image','ico':'image',
 'mp3':'audio','wav':'audio','ogg':'audio','flac':'audio',
 'aac':'audio','m4a':'audio','wma':'audio',
 'mp4':'video','webm':'video','mov':'video','avi':'video',
 'mkv':'video','wmv':'video',
 'zip':'archive','tar':'archive','gz':'archive','tgz':'archive',
 '7z':'archive','rar':'archive',
}

UPLOAD_FOLDER=os.path.join(os.path.dirname(os.path.dirname(__file__)),'uploads')
os.makedirs(UPLOAD_FOLDER,exist_ok=True)


def allowed_file(filename:str)->bool:
 return'.' in filename and filename.rsplit('.',1)[1].lower() in ALLOWED_EXTENSIONS


def get_category(filename:str)->str:
 if'.' not in filename:
  return'other'
 ext=filename.rsplit('.',1)[1].lower()
 return CATEGORY_MAP.get(ext,'other')


def get_mime_type(filename:str)->str:
 ext=filename.rsplit('.',1)[1].lower() if'.' in filename else''
 mime_types={
  'txt':'text/plain','md':'text/markdown','json':'application/json',
  'py':'text/x-python','js':'text/javascript','ts':'text/typescript',
  'html':'text/html','css':'text/css','xml':'application/xml',
  'png':'image/png','jpg':'image/jpeg','jpeg':'image/jpeg',
  'gif':'image/gif','webp':'image/webp','svg':'image/svg+xml',
  'mp3':'audio/mpeg','wav':'audio/wav','ogg':'audio/ogg',
  'flac':'audio/flac','m4a':'audio/mp4',
  'mp4':'video/mp4','webm':'video/webm','mov':'video/quicktime',
  'pdf':'application/pdf',
 }
 return mime_types.get(ext,'application/octet-stream')


@router.get("/projects/{project_id}/files")
async def list_uploaded_files(project_id:str):
 data_store=get_data_store()
 project=data_store.get_project(project_id)
 if not project:
  raise HTTPException(status_code=404,detail="Project not found")
 return data_store.get_uploaded_files_by_project(project_id)


@router.post("/projects/{project_id}/files")
async def upload_file(
 project_id:str,
 file:UploadFile=File(...),
 description:str=Form("")
):
 data_store=get_data_store()
 project=data_store.get_project(project_id)
 if not project:
  raise HTTPException(status_code=404,detail="Project not found")
 if not file.filename:
  raise HTTPException(status_code=400,detail="No filename provided")
 if not allowed_file(file.filename):
  raise HTTPException(status_code=400,detail="File type not allowed")
 original_filename=file.filename
 ext=original_filename.rsplit('.',1)[1].lower() if'.' in original_filename else''
 unique_filename=f"{uuid.uuid4().hex}.{ext}" if ext else uuid.uuid4().hex
 project_folder=os.path.join(UPLOAD_FOLDER,project_id)
 os.makedirs(project_folder,exist_ok=True)
 file_path=os.path.join(project_folder,unique_filename)
 content=await file.read()
 size_bytes=len(content)
 async with aiofiles.open(file_path,'wb') as f:
  await f.write(content)
 category=get_category(original_filename)
 mime_type=get_mime_type(original_filename)
 uploaded_file=data_store.create_uploaded_file(
  project_id=project_id,
  filename=unique_filename,
  original_filename=original_filename,
  mime_type=mime_type,
  category=category,
  size_bytes=size_bytes,
  description=description
 )
 return uploaded_file


@router.get("/files/{file_id}")
async def get_file_info(file_id:str):
 data_store=get_data_store()
 file_info=data_store.get_uploaded_file(file_id)
 if not file_info:
  raise HTTPException(status_code=404,detail="File not found")
 return file_info


@router.get("/files/{file_id}/download")
async def download_file(file_id:str):
 data_store=get_data_store()
 file_info=data_store.get_uploaded_file(file_id)
 if not file_info:
  raise HTTPException(status_code=404,detail="File not found")
 project_id=file_info["projectId"]
 filename=file_info["filename"]
 file_path=os.path.join(UPLOAD_FOLDER,project_id,filename)
 if not os.path.exists(file_path):
  raise HTTPException(status_code=404,detail="File not found on disk")
 return FileResponse(
  path=file_path,
  filename=file_info["originalFilename"],
  media_type=file_info.get("mimeType","application/octet-stream")
 )


@router.delete("/files/{file_id}",status_code=204)
async def delete_file(file_id:str):
 data_store=get_data_store()
 file_info=data_store.get_uploaded_file(file_id)
 if not file_info:
  raise HTTPException(status_code=404,detail="File not found")
 project_id=file_info["projectId"]
 filename=file_info["filename"]
 file_path=os.path.join(UPLOAD_FOLDER,project_id,filename)
 if os.path.exists(file_path):
  os.remove(file_path)
 data_store.delete_uploaded_file(file_id)
 return None
