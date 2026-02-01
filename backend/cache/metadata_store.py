from typing import Any,Dict,List,Optional
from datetime import datetime
class FileMetadataStore:
 def __init__(self,project_id:str):
  self._project_id=project_id
 def get(self,path:str)->Optional[Dict[str,Any]]:
  try:
   from models.database import session_scope
   from models.tables import FileMetadata
   with session_scope() as session:
    row=session.query(FileMetadata).filter_by(project_id=self._project_id,path=path).first()
    if row is None:
     return None
    return self._row_to_dict(row)
  except Exception:
   return None
 def upsert(self,metadata:Dict[str,Any])->bool:
  try:
   from models.database import session_scope
   from models.tables import FileMetadata
   path=metadata.get("path")
   if not path:
    return False
   with session_scope() as session:
    existing=session.query(FileMetadata).filter_by(project_id=self._project_id,path=path).first()
    if existing:
     for key,value in metadata.items():
      if key!="path" and hasattr(existing,key):
       setattr(existing,key,value)
     existing.modified_at=datetime.now()
    else:
     row=FileMetadata(
      project_id=self._project_id,
      path=path,
      file_type=metadata.get("file_type"),
      mime_type=metadata.get("mime_type"),
      size=metadata.get("size",0),
      hash=metadata.get("hash"),
      encoding=metadata.get("encoding","utf-8"),
      language=metadata.get("language"),
      line_count=metadata.get("line_count",0),
      dependencies=metadata.get("dependencies"),
      dependents=metadata.get("dependents"),
      tags=metadata.get("tags"),
      description=metadata.get("description"),
      agent_modified=metadata.get("agent_modified"),
      access_count=0,
     )
     session.add(row)
   return True
  except Exception:
   return False
 def delete(self,path:str)->bool:
  try:
   from models.database import session_scope
   from models.tables import FileMetadata
   with session_scope() as session:
    session.query(FileMetadata).filter_by(project_id=self._project_id,path=path).delete()
   return True
  except Exception:
   return False
 def record_access(self,path:str)->None:
  try:
   from models.database import session_scope
   from models.tables import FileMetadata
   with session_scope() as session:
    row=session.query(FileMetadata).filter_by(project_id=self._project_id,path=path).first()
    if row:
     row.access_count=(row.access_count or 0)+1
     row.last_accessed_at=datetime.now()
  except Exception:
   pass
 def search(self,file_type:str=None,language:str=None,tags:List[str]=None,description:str=None,limit:int=100)->List[Dict[str,Any]]:
  try:
   from models.database import session_scope
   from models.tables import FileMetadata
   with session_scope() as session:
    query=session.query(FileMetadata).filter_by(project_id=self._project_id)
    if file_type:
     query=query.filter_by(file_type=file_type)
    if language:
     query=query.filter_by(language=language)
    if description:
     query=query.filter(FileMetadata.description.ilike(f"%{description}%"))
    rows=query.limit(limit).all()
    results=[]
    for row in rows:
     if tags:
      row_tags=row.tags or []
      if not any(t in row_tags for t in tags):
       continue
     results.append(self._row_to_dict(row))
    return results
  except Exception:
   return []
 def get_most_accessed(self,limit:int=20)->List[Dict[str,Any]]:
  try:
   from models.database import session_scope
   from models.tables import FileMetadata
   with session_scope() as session:
    rows=session.query(FileMetadata).filter_by(project_id=self._project_id).order_by(FileMetadata.access_count.desc()).limit(limit).all()
    return [self._row_to_dict(row) for row in rows]
  except Exception:
   return []
 def get_recently_modified(self,limit:int=20)->List[Dict[str,Any]]:
  try:
   from models.database import session_scope
   from models.tables import FileMetadata
   with session_scope() as session:
    rows=session.query(FileMetadata).filter_by(project_id=self._project_id).order_by(FileMetadata.modified_at.desc()).limit(limit).all()
    return [self._row_to_dict(row) for row in rows]
  except Exception:
   return []
 def add_tag(self,path:str,tag:str)->bool:
  try:
   from models.database import session_scope
   from models.tables import FileMetadata
   with session_scope() as session:
    row=session.query(FileMetadata).filter_by(project_id=self._project_id,path=path).first()
    if row:
     current_tags=row.tags or []
     if tag not in current_tags:
      current_tags.append(tag)
      row.tags=current_tags
     return True
   return False
  except Exception:
   return False
 def remove_tag(self,path:str,tag:str)->bool:
  try:
   from models.database import session_scope
   from models.tables import FileMetadata
   with session_scope() as session:
    row=session.query(FileMetadata).filter_by(project_id=self._project_id,path=path).first()
    if row:
     current_tags=row.tags or []
     if tag in current_tags:
      current_tags.remove(tag)
      row.tags=current_tags
     return True
   return False
  except Exception:
   return False
 def set_description(self,path:str,description:str)->bool:
  try:
   from models.database import session_scope
   from models.tables import FileMetadata
   with session_scope() as session:
    row=session.query(FileMetadata).filter_by(project_id=self._project_id,path=path).first()
    if row:
     row.description=description
     return True
   return False
  except Exception:
   return False
 def update_dependencies(self,path:str,dependencies:List[str],dependents:List[str]=None)->bool:
  try:
   from models.database import session_scope
   from models.tables import FileMetadata
   with session_scope() as session:
    row=session.query(FileMetadata).filter_by(project_id=self._project_id,path=path).first()
    if row:
     row.dependencies=dependencies
     if dependents is not None:
      row.dependents=dependents
     return True
   return False
  except Exception:
   return False
 def clear_all(self)->bool:
  try:
   from models.database import session_scope
   from models.tables import FileMetadata
   with session_scope() as session:
    session.query(FileMetadata).filter_by(project_id=self._project_id).delete()
   return True
  except Exception:
   return False
 def _row_to_dict(self,row)->Dict[str,Any]:
  return {
   "id":row.id,
   "project_id":row.project_id,
   "path":row.path,
   "file_type":row.file_type,
   "mime_type":row.mime_type,
   "size":row.size,
   "hash":row.hash,
   "encoding":row.encoding,
   "language":row.language,
   "line_count":row.line_count,
   "dependencies":row.dependencies,
   "dependents":row.dependents,
   "tags":row.tags,
   "description":row.description,
   "agent_modified":row.agent_modified,
   "access_count":row.access_count,
   "created_at":row.created_at.isoformat() if row.created_at else None,
   "modified_at":row.modified_at.isoformat() if row.modified_at else None,
   "last_accessed_at":row.last_accessed_at.isoformat() if row.last_accessed_at else None,
  }
