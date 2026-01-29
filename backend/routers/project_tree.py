import os
import io
import zipfile
import shutil
import aiofiles
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse
from core.dependencies import get_data_store
from schemas import ProjectTreeResponse, TreeReplaceResponse

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


@router.get("/projects/{project_id}/tree", response_model=ProjectTreeResponse)
async def get_project_tree(project_id: str):
    data_store = get_data_store()
    project = data_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project_output = os.path.join(OUTPUT_FOLDER, project_id)
    if not os.path.exists(project_output):
        return {"tree": [], "project_id": project_id}
    tree = scan_directory(project_output, project_output)
    return {"tree": tree, "project_id": project_id}


@router.get("/projects/{project_id}/tree/download")
async def download_tree_file(project_id: str, path: Optional[str] = None):
    data_store = get_data_store()
    project = data_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not path:
        raise HTTPException(status_code=400, detail="path parameter is required")
    full_path = os.path.join(OUTPUT_FOLDER, project_id, path)
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="File not found")
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=400, detail="Not a file")
    return FileResponse(path=full_path, filename=os.path.basename(path))


@router.get("/projects/{project_id}/tree/download-all")
async def download_all_files(project_id: str):
    data_store = get_data_store()
    project = data_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project_output = os.path.join(OUTPUT_FOLDER, project_id)
    if not os.path.exists(project_output):
        raise HTTPException(status_code=404, detail="Project output folder not found")
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(project_output):
            for file in files:
                file_path = os.path.join(root, file)
                arc_name = os.path.relpath(file_path, project_output)
                zf.write(file_path, arc_name)
    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={project_id}.zip"},
    )


@router.post("/projects/{project_id}/tree/replace", response_model=TreeReplaceResponse)
async def replace_tree_file(project_id: str, file: UploadFile = File(...), path: str = Form(...)):
    data_store = get_data_store()
    project = data_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    full_path = os.path.join(OUTPUT_FOLDER, project_id, path)
    parent_dir = os.path.dirname(full_path)
    if not os.path.exists(parent_dir):
        os.makedirs(parent_dir, exist_ok=True)
    content = await file.read()
    async with aiofiles.open(full_path, "wb") as f:
        await f.write(content)
    return {"success": True, "path": path}


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
