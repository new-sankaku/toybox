from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
from pydantic import BaseModel
from core.dependencies import get_data_store

router = APIRouter()


class AutoApprovalRulesUpdate(BaseModel):
    rules: List[Dict[str, Any]]


@router.get("/projects/{project_id}/auto-approval-rules")
async def get_auto_approval_rules(project_id: str):
    data_store = get_data_store()
    project = data_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    rules = data_store.get_auto_approval_rules(project_id)
    return {"rules": rules}


@router.put("/projects/{project_id}/auto-approval-rules")
async def update_auto_approval_rules(project_id: str, data: AutoApprovalRulesUpdate):
    data_store = get_data_store()
    project = data_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    updated_rules = data_store.set_auto_approval_rules(project_id, data.rules)
    return {"rules": updated_rules}
