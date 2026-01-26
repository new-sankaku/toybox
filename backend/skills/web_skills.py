import asyncio
import json
import re
from typing import Optional,Dict,Any
from .base import Skill,SkillResult,SkillContext,SkillCategory,SkillParameter


class WebFetchSkill(Skill):
 name="web_fetch"
 description="WebページやAPIからデータを取得します"
 category=SkillCategory.FILE
 parameters=[
  SkillParameter(name="url",type="string",description="取得するURL"),
  SkillParameter(name="method",type="string",description="HTTPメソッド: GET, POST",required=False,default="GET"),
  SkillParameter(name="headers",type="object",description="HTTPヘッダー",required=False),
  SkillParameter(name="body",type="string",description="リクエストボディ（POST時）",required=False),
  SkillParameter(name="timeout",type="integer",description="タイムアウト秒数",required=False,default=30),
  SkillParameter(name="extract_text",type="boolean",description="HTMLからテキストを抽出",required=False,default=False),
 ]

 BLOCKED_DOMAINS=[
  "localhost",
  "127.0.0.1",
  "0.0.0.0",
  "169.254.",
  "10.",
  "172.16.",
  "172.17.",
  "172.18.",
  "172.19.",
  "172.20.",
  "172.21.",
  "172.22.",
  "172.23.",
  "172.24.",
  "172.25.",
  "172.26.",
  "172.27.",
  "172.28.",
  "172.29.",
  "172.30.",
  "172.31.",
  "192.168.",
 ]

 def __init__(self):
  super().__init__()

 async def execute(self,context:SkillContext,**kwargs)->SkillResult:
  url=kwargs.get("url","")
  method=kwargs.get("method","GET").upper()
  headers=kwargs.get("headers",{})
  body=kwargs.get("body")
  timeout=kwargs.get("timeout",30)
  extract_text=kwargs.get("extract_text",False)
  if not url:
   return SkillResult(success=False,error="url is required")
  if not url.startswith(("http://","https://")):
   return SkillResult(success=False,error="URL must start with http:// or https://")
  if context.sandbox_enabled:
   block_reason=self._check_blocked_url(url)
   if block_reason:
    return SkillResult(success=False,error=f"URL blocked: {block_reason}")
  try:
   result=await asyncio.to_thread(
    self._fetch,url,method,headers,body,timeout,extract_text,context.max_output_size
   )
   return result
  except Exception as e:
   return SkillResult(success=False,error=str(e))

 def _check_blocked_url(self,url:str)->Optional[str]:
  from urllib.parse import urlparse
  try:
   parsed=urlparse(url)
   host=parsed.hostname or""
   for blocked in self.BLOCKED_DOMAINS:
    if host==blocked or host.startswith(blocked) or host.endswith("."+blocked):
     return f"Internal/private network access blocked: {host}"
  except Exception:
   pass
  return None

 def _fetch(self,url:str,method:str,headers:Dict,body:Optional[str],timeout:int,extract_text:bool,max_size:int)->SkillResult:
  import urllib.request
  import urllib.error
  default_headers={
   "User-Agent":"ToyboxAgent/1.0",
   "Accept":"text/html,application/json,application/xml,text/plain,*/*",
  }
  all_headers={**default_headers,**headers}
  try:
   data=body.encode("utf-8") if body else None
   req=urllib.request.Request(url,data=data,headers=all_headers,method=method)
   with urllib.request.urlopen(req,timeout=timeout) as response:
    content_type=response.headers.get("Content-Type","")
    encoding=self._get_encoding(content_type)
    raw_content=response.read(max_size)
    if len(raw_content)>=max_size:
     truncated=True
    else:
     truncated=False
    if"application/json" in content_type:
     try:
      content=json.loads(raw_content.decode(encoding))
      return SkillResult(
       success=True,
       output=content,
       metadata={"url":url,"content_type":content_type,"truncated":truncated}
      )
     except json.JSONDecodeError:
      pass
    content=raw_content.decode(encoding,errors="replace")
    if extract_text and"text/html" in content_type:
     content=self._extract_text_from_html(content)
    return SkillResult(
     success=True,
     output=content[:max_size],
     metadata={
      "url":url,
      "status":response.status,
      "content_type":content_type,
      "content_length":len(raw_content),
      "truncated":truncated,
     }
    )
  except urllib.error.HTTPError as e:
   return SkillResult(
    success=False,
    error=f"HTTP {e.code}: {e.reason}",
    metadata={"url":url,"status":e.code}
   )
  except urllib.error.URLError as e:
   return SkillResult(success=False,error=f"URL error: {e.reason}")
  except TimeoutError:
   return SkillResult(success=False,error=f"Request timed out after {timeout} seconds")

 def _get_encoding(self,content_type:str)->str:
  match=re.search(r'charset=([^\s;]+)',content_type,re.IGNORECASE)
  if match:
   return match.group(1)
  return"utf-8"

 def _extract_text_from_html(self,html:str)->str:
  text=re.sub(r'<script[^>]*>.*?</script>','',html,flags=re.DOTALL|re.IGNORECASE)
  text=re.sub(r'<style[^>]*>.*?</style>','',text,flags=re.DOTALL|re.IGNORECASE)
  text=re.sub(r'<[^>]+>','',text)
  text=re.sub(r'&nbsp;',' ',text)
  text=re.sub(r'&lt;','<',text)
  text=re.sub(r'&gt;','>',text)
  text=re.sub(r'&amp;','&',text)
  text=re.sub(r'&quot;','"',text)
  text=re.sub(r'&#39;',"'",text)
  text=re.sub(r'\s+',' ',text)
  return text.strip()
