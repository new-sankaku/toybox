from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import uuid4
from sqlalchemy.orm import Session
from models.tables import UploadedFile
from .base import BaseRepository


class UploadedFileRepository(BaseRepository[UploadedFile]):
    def __init__(self, session: Session):
        super().__init__(session, UploadedFile)

    def to_dict(self, f: UploadedFile) -> Dict[str, Any]:
        return {
            "id": f.id,
            "projectId": f.project_id,
            "filename": f.filename,
            "originalFilename": f.original_filename,
            "mimeType": f.mime_type,
            "category": f.category,
            "sizeBytes": f.size_bytes,
            "status": f.status,
            "description": f.description,
            "url": f.url,
            "uploadedAt": f.uploaded_at.isoformat() if f.uploaded_at else None,
        }

    def get_by_project(self, project_id: str) -> List[Dict]:
        files = self.session.query(UploadedFile).filter(UploadedFile.project_id == project_id).all()
        return [self.to_dict(f) for f in files]

    def get_dict(self, id: str) -> Optional[Dict]:
        f = self.get(id)
        return self.to_dict(f) if f else None

    def create_from_dict(self, data: Dict) -> Dict:
        uf = UploadedFile(
            id=data.get("id", f"file-{uuid4().hex[:8]}"),
            project_id=data["projectId"],
            filename=data["filename"],
            original_filename=data["originalFilename"],
            mime_type=data["mimeType"],
            category=data["category"],
            size_bytes=data["sizeBytes"],
            status="ready",
            description=data.get("description", ""),
            url=data.get("url", f"/uploads/{data['projectId']}/{data['filename']}"),
            uploaded_at=datetime.now(),
        )
        self.create(uf)
        return self.to_dict(uf)

    def update_from_dict(self, id: str, data: Dict) -> Optional[Dict]:
        f = self.get(id)
        if not f:
            return None
        if "status" in data:
            f.status = data["status"]
        if "description" in data:
            f.description = data["description"]
        self.update(f)
        return self.to_dict(f)
