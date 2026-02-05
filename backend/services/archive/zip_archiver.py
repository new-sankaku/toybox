import json
import os
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict,List

from middleware.logger import get_logger


class ZipArchiver:
    def __init__(self,archive_dir:str|None=None):
        self._archive_dir=archive_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "data",
            "archives",
        )
        Path(self._archive_dir).mkdir(parents=True,exist_ok=True)
        self._logger=get_logger()

    @property
    def archive_dir(self)->str:
        return self._archive_dir

    def create_archive(
        self,
        filename:str,
        files:Dict[str,any],
    )->str:
        zip_path=os.path.join(self._archive_dir,filename)

        with zipfile.ZipFile(
            zip_path,"w",zipfile.ZIP_DEFLATED,compresslevel=9
        ) as zf:
            for name,content in files.items():
                if isinstance(content,(dict,list)):
                    zf.writestr(
                        name,json.dumps(content,ensure_ascii=False,indent=2)
                    )
                else:
                    zf.writestr(name,str(content))

        self._logger.info(f"ZipArchiver: created archive {zip_path}")
        return zip_path

    def generate_filename(
        self,
        prefix:str,
        project_id:str|None=None,
        agent_id:str|None=None,
    )->str:
        timestamp=datetime.now().strftime("%Y%m%d_%H%M%S")
        parts=[prefix]
        if project_id:
            parts.append(project_id)
        if agent_id:
            parts.append(agent_id)
        parts.append(timestamp)
        return"_".join(parts)+".zip"

    def list_archives(self)->List[Dict]:
        archives=[]
        if not os.path.exists(self._archive_dir):
            return archives

        for filename in os.listdir(self._archive_dir):
            if filename.endswith(".zip"):
                filepath=os.path.join(self._archive_dir,filename)
                stat=os.stat(filepath)
                archives.append(
                    {
                        "name":filename,
                        "path":filepath,
                        "size":stat.st_size,
                        "createdAt":datetime.fromtimestamp(
                            stat.st_mtime
                        ).isoformat(),
                    }
                )

        archives.sort(key=lambda x:x["createdAt"],reverse=True)
        return archives

    def delete_archive(self,archive_name:str)->bool:
        archive_path=os.path.join(self._archive_dir,archive_name)
        if not os.path.exists(archive_path):
            return False

        os.remove(archive_path)
        self._logger.info(f"ZipArchiver: deleted archive {archive_name}")
        return True

    def get_archive_size(self,archive_path:str)->int:
        return os.path.getsize(archive_path)

    def get_info(self)->Dict[str,any]:
        archives=self.list_archives()
        total_size=sum(a["size"] for a in archives)
        return {
            "archiveDir":self._archive_dir,
            "archiveCount":len(archives),
            "totalSizeBytes":total_size,
        }
