from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from models.tables import Checkpoint
from .base import BaseRepository


class CheckpointRepository(BaseRepository[Checkpoint]):
    def __init__(self, session: Session):
        super().__init__(session, Checkpoint)

    def to_dict(self, c: Checkpoint) -> Dict[str, Any]:
        return {
            "id": c.id,
            "projectId": c.project_id,
            "agentId": c.agent_id,
            "type": c.type,
            "title": c.title,
            "description": c.description,
            "contentCategory": c.content_category,
            "output": c.output or {},
            "status": c.status,
            "feedback": c.feedback,
            "resolvedAt": c.resolved_at.isoformat() if c.resolved_at else None,
            "createdAt": c.created_at.isoformat() if c.created_at else None,
            "updatedAt": c.updated_at.isoformat() if c.updated_at else None,
        }

    def get_by_project(self, project_id: str) -> List[Dict]:
        cps = self.session.query(Checkpoint).filter(Checkpoint.project_id == project_id).all()
        return [self.to_dict(c) for c in cps]

    def get_by_agent(self, agent_id: str) -> List[Dict]:
        cps = self.session.query(Checkpoint).filter(Checkpoint.agent_id == agent_id).all()
        return [self.to_dict(c) for c in cps]

    def get_pending_by_agent(self, agent_id: str) -> List[Checkpoint]:
        return (
            self.session.query(Checkpoint).filter(Checkpoint.agent_id == agent_id, Checkpoint.status == "pending").all()
        )

    def get_dict(self, id: str) -> Optional[Dict]:
        c = self.get(id)
        return self.to_dict(c) if c else None

    def create_from_dict(self, data: Dict) -> Dict:
        from uuid import uuid4

        now = datetime.now()
        cp = Checkpoint(
            id=data.get("id", f"cp-{uuid4().hex[:8]}"),
            project_id=data["projectId"],
            agent_id=data["agentId"],
            type=data.get("type", "review"),
            title=data.get("title", "レビュー依頼"),
            description=data.get("description"),
            content_category=data.get("contentCategory", "document"),
            output=data.get("output", {}),
            status=data.get("status", "pending"),
            feedback=None,
            resolved_at=datetime.fromisoformat(data["resolvedAt"]) if data.get("resolvedAt") else None,
            created_at=now,
            updated_at=now,
        )
        self.create(cp)
        return self.to_dict(cp)

    def resolve(self, id: str, resolution: str, feedback: Optional[str] = None) -> Optional[Dict]:
        c = self.get(id)
        if not c:
            return None
        now = datetime.now()
        c.status = resolution
        c.feedback = feedback
        c.resolved_at = now
        c.updated_at = now
        self.update(c)
        return self.to_dict(c)

    def delete_by_project(self, project_id: str) -> int:
        count = self.session.query(Checkpoint).filter(Checkpoint.project_id == project_id).delete()
        self.session.flush()
        return count
