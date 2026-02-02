export type FileCategory='code'|'image'|'bgm'|'sfx'|'voice'|'audio'|'video'|'document'|'archive'|'other'

export type UploadedFileStatus='uploading'|'ready'|'processing'|'error'

export interface UploadedFile{
 id:string
 projectId:string
 filename:string
 originalFilename:string
 mimeType:string
 category:FileCategory
 sizeBytes:number
 status:UploadedFileStatus
 description?:string
 uploadedAt:string
 url?:string
}

export interface FileUploadInput{
 projectId:string
 file:File
 description?:string
}

export interface FileUploadResult{
 success:boolean
 file?:UploadedFile
 error?:string
}

export const ALLOWED_MIME_TYPES:Record<FileCategory,string[]>={
 code:[
  'text/plain',
  'text/javascript',
  'text/typescript',
  'application/json',
  'text/html',
  'text/css',
  'text/x-python',
  'text/x-java',
  'text/x-c',
  'text/x-csharp',
  'text/markdown'
],
 image:[
  'image/png',
  'image/jpeg',
  'image/gif',
  'image/webp',
  'image/svg+xml',
  'image/bmp'
],
 audio:[
  'audio/mpeg',
  'audio/wav',
  'audio/ogg',
  'audio/webm',
  'audio/flac',
  'audio/aac'
],
 bgm:[
  'audio/mpeg',
  'audio/wav',
  'audio/ogg',
  'audio/flac'
],
 sfx:[
  'audio/mpeg',
  'audio/wav',
  'audio/ogg'
],
 voice:[
  'audio/mpeg',
  'audio/wav',
  'audio/ogg'
],
 video:[
  'video/mp4',
  'video/webm',
  'video/ogg',
  'video/quicktime',
  'video/x-msvideo'
],
 document:[
  'application/pdf',
  'text/plain',
  'text/markdown'
],
 archive:[
  'application/zip',
  'application/x-tar',
  'application/gzip',
  'application/x-7z-compressed',
  'application/x-rar-compressed'
],
 other:[]
}

export const FILE_EXTENSIONS:Record<string,FileCategory>={
 '.txt':'document',
 '.md':'document',
 '.pdf':'document',
 '.js':'code',
 '.ts':'code',
 '.jsx':'code',
 '.tsx':'code',
 '.py':'code',
 '.java':'code',
 '.c':'code',
 '.cpp':'code',
 '.h':'code',
 '.cs':'code',
 '.html':'code',
 '.css':'code',
 '.json':'code',
 '.xml':'code',
 '.yaml':'code',
 '.yml':'code',
 '.png':'image',
 '.jpg':'image',
 '.jpeg':'image',
 '.gif':'image',
 '.webp':'image',
 '.svg':'image',
 '.bmp':'image',
 '.mp3':'audio',
 '.wav':'audio',
 '.ogg':'audio',
 '.flac':'audio',
 '.aac':'audio',
 '.m4a':'audio',
 '.mp4':'video',
 '.webm':'video',
 '.mov':'video',
 '.avi':'video',
 '.mkv':'video',
 '.zip':'archive',
 '.tar':'archive',
 '.gz':'archive',
 '.tgz':'archive',
 '.7z':'archive',
 '.rar':'archive'
}

export function getCategoryFromFilename(filename:string):FileCategory{
 const ext=filename.toLowerCase().slice(filename.lastIndexOf('.'))
 return FILE_EXTENSIONS[ext]||'other'
}
