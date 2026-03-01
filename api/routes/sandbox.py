"""
Sandbox Routes
Pause, resume, and status endpoints for a job's OpenSandbox.
"""
import logging
import re

from fastapi import APIRouter, HTTPException, Depends

from ..job_queue import get_sandbox_id
from ..dependencies import get_sandbox_client
from ..auth import get_current_user

router = APIRouter(prefix="/sandbox", tags=["sandbox"])
logger = logging.getLogger(__name__)

# Job ID validation (same pattern as draft_pr)
UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


def _validate_job_id(job_id: str) -> str:
    """Validate and sanitize job_id."""
    if not job_id:
        raise HTTPException(status_code=400, detail="Job ID cannot be empty")
    safe = job_id.replace("/", "_").replace("\\", "_").replace("..", "_").replace("\x00", "_").strip(". ")
    if not safe:
        raise HTTPException(status_code=400, detail="Invalid job ID format")
    if len(safe) > 100:
        raise HTTPException(status_code=400, detail="Job ID too long")
    return safe


@router.post("/jobs/{job_id}/pause")
async def pause_sandbox(job_id: str, _: str = Depends(get_current_user)):
    """
    Pause the sandbox associated with the given job (for debugging).
    Returns 404 if no sandbox is linked to the job, 501 if the SDK does not support pause.
    """
    job_id = _validate_job_id(job_id)
    sandbox_id = await get_sandbox_id(job_id)
    if not sandbox_id:
        raise HTTPException(status_code=404, detail="No sandbox associated with this job")
    client = get_sandbox_client()
    if not client:
        raise HTTPException(status_code=503, detail="OpenSandbox is not enabled")
    try:
        from src.sandbox_client import SandboxClientError

        await client.pause_sandbox(sandbox_id)
        return {"job_id": job_id, "sandbox_id": sandbox_id, "status": "paused"}
    except Exception as e:
        err_msg = str(e)
        if "does not support pause" in err_msg or "not support" in err_msg.lower():
            raise HTTPException(status_code=501, detail=err_msg)
        raise HTTPException(status_code=500, detail=err_msg)


@router.post("/jobs/{job_id}/resume")
async def resume_sandbox(job_id: str, _: str = Depends(get_current_user)):
    """
    Resume a paused sandbox associated with the given job.
    Returns 404 if no sandbox is linked to the job, 501 if the SDK does not support resume.
    """
    job_id = _validate_job_id(job_id)
    sandbox_id = await get_sandbox_id(job_id)
    if not sandbox_id:
        raise HTTPException(status_code=404, detail="No sandbox associated with this job")
    client = get_sandbox_client()
    if not client:
        raise HTTPException(status_code=503, detail="OpenSandbox is not enabled")
    try:
        await client.resume_sandbox(sandbox_id)
        return {"job_id": job_id, "sandbox_id": sandbox_id, "status": "resumed"}
    except Exception as e:
        err_msg = str(e)
        if "does not support resume" in err_msg or "not support" in err_msg.lower():
            raise HTTPException(status_code=501, detail=err_msg)
        raise HTTPException(status_code=500, detail=err_msg)


@router.get("/jobs/{job_id}/status")
async def sandbox_status(job_id: str, _: str = Depends(get_current_user)):
    """
    Get the status of the sandbox associated with the given job (e.g. RUNNING, PAUSED).
    Returns 404 if no sandbox is linked to the job.
    """
    job_id = _validate_job_id(job_id)
    sandbox_id = await get_sandbox_id(job_id)
    if not sandbox_id:
        raise HTTPException(status_code=404, detail="No sandbox associated with this job")
    client = get_sandbox_client()
    if not client:
        raise HTTPException(status_code=503, detail="OpenSandbox is not enabled")
    try:
        status = await client.get_sandbox_status(sandbox_id)
        if status is None:
            raise HTTPException(
                status_code=404,
                detail="Sandbox not found (may have been destroyed)",
            )
        return {"job_id": job_id, "sandbox_id": sandbox_id, **status}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
