
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
import re
import sys

EXCLUDE_DIRS={'__pycache__','.git','venv','.venv','env','.env'}

def remove_spaces_and_comments(code:str)->str:
 preserved=[]
 index=[0]
 def save(match):
  preserved.append(match.group(0))
  result=f'__PRESERVED_{index[0]}__'
  index[0]+=1
  return result

 pattern=r'[fFrRbBuU]*"""[\s\S]*?"""|[fFrRbBuU]*\'\'\'[\s\S]*?\'\'\'|[fFrRbBuU]*"(?:[^"\\]|\\.)*"|[fFrRbBuU]*\'(?:[^\'\\]|\\.)*\''
 result=re.sub(pattern,save,code)
 # コメント削除（TODO/FIXME以外）
 result=re.sub(r'#(?!.*(?:TODO|FIXME)).*$','',result,flags=re.MULTILINE)

 result=re.sub(r'\s*->\s*','->',result)

 result=re.sub(r':[ \t]+(?=\S)',':',result)

 result=re.sub(r',[ \t]+',',',result)

 result=re.sub(r'[ \t]+$','',result,flags=re.MULTILINE)

 for i,s in enumerate(preserved):
  result=result.replace(f'__PRESERVED_{i}__',s)
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
 script_dir=os.path.dirname(os.path.abspath(__file__))
 target_dir=os.path.dirname(script_dir)
 print(f'Processing Python files in: {target_dir}')
 print(f'Excluding directories: {", ".join(EXCLUDE_DIRS)}')
 print()
 count=walk_dir(target_dir)
 print()
 print(f'Done! {count} files modified.')
