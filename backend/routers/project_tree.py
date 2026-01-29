import os
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from typing import List, Dict, Any
from core.dependencies import get_data_store

router = APIRouter()

OUTPUT_FOLDER = os.path.join(os.path.dirname(os.path.dirname(__file__)), "outputs")


def scan_directory(path: str, base_path: str) -> List[Dict[str, Any]]:
    items = []
    if not os.path.exists(path):
        return items
    for name in sorted(os.listdir(path)):
        full_path = os.path.join(path, name)
        relative_path = os.path.relpath(full_path, base_path)
        if os.path.isdir(full_path):
            items.append(
                {
                    "name": name,
                    "path": relative_path,
                    "type": "directory",
                    "children": scan_directory(full_path, base_path),
                }
            )
        else:
            stat = os.stat(full_path)
            items.append(
                {"name": name, "path": relative_path, "type": "file", "size": stat.st_size, "modified": stat.st_mtime}
            )
    return items


@router.get("/projects/{project_id}/tree")
async def get_project_tree(project_id: str):
    data_store = get_data_store()
    project = data_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project_output = os.path.join(OUTPUT_FOLDER, project_id)
    if not os.path.exists(project_output):
        return {"tree": [], "projectId": project_id}
    tree = scan_directory(project_output, project_output)
    return {"tree": tree, "projectId": project_id}


@router.get("/projects/{project_id}/files/{file_path:path}")
async def get_project_file(project_id: str, file_path: str):
    data_store = get_data_store()
    project = data_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    full_path = os.path.join(OUTPUT_FOLDER, project_id, file_path)
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="File not found")
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=400, detail="Not a file")
    return FileResponse(path=full_path, filename=os.path.basename(file_path))
