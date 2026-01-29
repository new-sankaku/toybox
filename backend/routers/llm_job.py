from fastapi import APIRouter, Request, HTTPException
from core.dependencies import get_data_store
from schemas import LlmJobSchema

router = APIRouter()


@router.get("/llm-jobs/{job_id}", response_model=LlmJobSchema)
async def get_llm_job(job_id: str, request: Request):
    llm_job_queue = request.app.state.llm_job_queue
    if not llm_job_queue:
        raise HTTPException(status_code=503, detail="LLM Job Queue is not available")
    job = llm_job_queue.get_job(job_id)
    if not job:
        data_store = get_data_store()
        job = data_store.get_llm_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")
    return job
