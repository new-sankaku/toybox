"""
Pythonファイルから不要なスペースとコメントを削除するスクリプト
使用方法: python scripts/remove-spaces.py

削除対象:
- コメント（TODO/FIXME以外）
- カンマ後のスペース
- コロン後のスペース
- アロー演算子周りのスペース

保持対象:
- 文字列リテラル内のスペース
- TODO/FIXMEコメント
- インデント
"""
import os
import sys
import atexit
import tokenize
import io

EXCLUDE_DIRS={'__pycache__','.git','venv','.venv','env','.env'}
LOCK_FILE=os.path.join(os.path.dirname(os.path.abspath(__file__)),'.remove-spaces.lock')

def is_process_running(pid:int)->bool:
 """指定PIDのプロセスが実行中か確認"""
 try:
  os.kill(pid,0)
  return True
 except OSError:
  return False

def acquire_lock()->bool:
 """ロック取得。既に実行中ならFalse"""
 if os.path.exists(LOCK_FILE):
  try:
   with open(LOCK_FILE,'r') as f:
    old_pid=int(f.read().strip())
   if is_process_running(old_pid):
    return False
   print(f'Stale lock file found (PID {old_pid} not running). Removing.')
  except (ValueError,IOError):
   print('Invalid lock file found. Removing.')
  os.remove(LOCK_FILE)
 with open(LOCK_FILE,'w') as f:
  f.write(str(os.getpid()))
 return True

def release_lock():
 """ロック解放"""
 try:
  if os.path.exists(LOCK_FILE):
   os.remove(LOCK_FILE)
 except IOError:
  pass

def remove_spaces_and_comments(code:str)->str:
 """tokenizeモジュールを使用して安全にスペースとコメントを削除"""
 try:
  tokens=list(tokenize.generate_tokens(io.StringIO(code).readline))
 except tokenize.TokenizeError as e:
  print(f'  Tokenize error: {e}')
  return code

 result_tokens=[]
 prev_token=None

 for tok in tokens:
  tok_type,tok_string,start,end,line=tok

  if tok_type==tokenize.COMMENT:
   if 'TODO' in tok_string or 'FIXME' in tok_string:
    result_tokens.append(tok)
   continue

  if tok_type==tokenize.OP and tok_string=='->':
   if result_tokens and result_tokens[-1][0]==tokenize.NL:
    pass
   elif result_tokens and result_tokens[-1][1].endswith(' '):
    last=result_tokens[-1]
    result_tokens[-1]=(last[0],last[1].rstrip(' '),last[2],last[3],last[4])
   result_tokens.append(tok)
   prev_token=tok
   continue

  if prev_token and prev_token[1]=='->':
   if tok_type==tokenize.NAME or tok_type==tokenize.OP:
    pass
  if tok_type==tokenize.NL or tok_type==tokenize.NEWLINE:
   if result_tokens and result_tokens[-1][0] not in (tokenize.NL,tokenize.NEWLINE,tokenize.INDENT,tokenize.DEDENT,tokenize.ENCODING):
    last=result_tokens[-1]
    if last[1].endswith(' '):
     result_tokens[-1]=(last[0],last[1].rstrip(' '),last[2],last[3],last[4])

  result_tokens.append(tok)
  prev_token=tok

 try:
  result=tokenize.untokenize(result_tokens)
 except:
  return code

 lines=result.split('\n')
 processed_lines=[]
 for line in lines:
  if not line.strip():
   processed_lines.append(line)
   continue

  indent_match=len(line)-len(line.lstrip())
  indent=line[:indent_match]
  content=line[indent_match:]

  new_content=_compress_line(content)
  processed_lines.append(indent+new_content)

 return '\n'.join(processed_lines)

def _compress_line(content:str)->str:
 """行内のスペースを圧縮（文字列リテラルを保護）"""
 segments=[]
 current=''
 i=0
 in_string=False
 string_char=None
 triple_quote=False

 while i<len(content):
  c=content[i]

  if not in_string:
   if content[i:i+3] in ('"""',"'''"):
    if current:
     segments.append(('code',current))
     current=''
    string_char=content[i:i+3]
    triple_quote=True
    in_string=True
    current=string_char
    i+=3
    continue
   elif c in ('"',"'"):
    if i>0 and content[i-1] in 'fFrRbBuU':
     pass
    if current:
     segments.append(('code',current))
     current=''
    string_char=c
    triple_quote=False
    in_string=True
    current=c
    i+=1
    continue
   else:
    current+=c
    i+=1
  else:
   if triple_quote:
    if content[i:i+3]==string_char:
     current+=string_char
     segments.append(('string',current))
     current=''
     in_string=False
     triple_quote=False
     string_char=None
     i+=3
     continue
    else:
     current+=c
     i+=1
   else:
    if c=='\\' and i+1<len(content):
     current+=c+content[i+1]
     i+=2
     continue
    elif c==string_char:
     current+=c
     segments.append(('string',current))
     current=''
     in_string=False
     string_char=None
     i+=1
     continue
    else:
     current+=c
     i+=1

 if current:
  if in_string:
   segments.append(('string',current))
  else:
   segments.append(('code',current))

 result_parts=[]
 for seg_type,seg_content in segments:
  if seg_type=='string':
   result_parts.append(seg_content)
  else:
   compressed=_compress_operators(seg_content)
   result_parts.append(compressed)

 return ''.join(result_parts)

def _compress_operators(code:str)->str:
 """演算子周りのスペースを削除"""
 import re
 result=code
 result=result.replace(' ->','->').replace('-> ','->')
 result=result.replace(': ',':').replace(':\t',':')
 result=result.replace(', ',',').replace(',\t',',')
 ops=['==','!=','<=','>=','+=','-=','*=','/=','//=','%=','**=','&=','|=','^=','>>=','<<=','@=',':=','//','**','<<','>>']
 for op in ops:
  result=result.replace(f' {op} ',op).replace(f' {op}',op).replace(f'{op} ',op)
 single_ops=['=','+','-','*','/','%','<','>','&','|','^','@']
 for op in single_ops:
  new_result=[]
  i=0
  while i<len(result):
   if result[i:i+1]==op:
    if i>0 and result[i-1]==' ':
     if new_result and new_result[-1]==' ':
      new_result.pop()
    new_result.append(op)
    if i+1<len(result) and result[i+1]==' ':
     i+=1
   else:
    new_result.append(result[i])
   i+=1
  result=''.join(new_result)
 result=result.rstrip(' \t')
 return result

def process_file(file_path:str)->bool:
 try:
  with open(file_path,'r',encoding='utf-8') as f:
   code=f.read()
  processed=remove_spaces_and_comments(code)
  if code!=processed:
   with open(file_path,'w',encoding='utf-8') as f:
    f.write(processed)
   print(f'Processed: {file_path}')
   return True
  return False
 except Exception as e:
  print(f'Error processing {file_path}: {e}',file=sys.stderr)
  return False

def walk_dir(directory:str)->int:
 count=0
 for root,dirs,files in os.walk(directory):
  dirs[:]=[d for d in dirs if d not in EXCLUDE_DIRS]
  for file in files:
   if file.endswith('.py'):
    full_path=os.path.join(root,file)
    if process_file(full_path):
     count+=1
 return count

if __name__=='__main__':
 if not acquire_lock():
  print('Another instance is already running. Skipping.')
  sys.exit(0)
 atexit.register(release_lock)
 script_dir=os.path.dirname(os.path.abspath(__file__))
 target_dir=os.path.dirname(script_dir)
 print(f'Processing Python files in: {target_dir}')
 print(f'Excluding directories: {", ".join(EXCLUDE_DIRS)}')
 print()
 count=walk_dir(target_dir)
 print()
 print(f'Done! {count} files modified.')
