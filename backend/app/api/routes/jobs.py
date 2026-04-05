from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.entities import Clip, ClipJob, JobStatus
from app.schemas.clips import JobStatusResponse

router = APIRouter(prefix='/jobs', tags=['jobs'])


@router.get('/{job_id}', response_model=JobStatusResponse)
async def get_job_status(job_id: str, db: AsyncSession = Depends(get_db)) -> JobStatusResponse:
    result = await db.execute(select(ClipJob).where(ClipJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail='Job not found')

    clip_count_result = await db.execute(select(func.count(Clip.id)).where(Clip.video_id == job.video_id))
    clips_completed = int(clip_count_result.scalar() or 0)
    clips_expected = 5

    if job.status == JobStatus.DONE:
        progress_percent = 100
    elif job.status == JobStatus.FAILED:
        progress_percent = max(1, min(99, int((clips_completed / clips_expected) * 100)))
    elif job.status == JobStatus.RUNNING:
        progress_percent = max(5, min(95, int((clips_completed / clips_expected) * 100)))
    else:
        progress_percent = 0

    return JobStatusResponse(
        job_id=job.id,
        video_id=job.video_id,
        status=job.status.value,
        progress_percent=progress_percent,
        clips_completed=clips_completed,
        clips_expected=clips_expected,
        error=job.error,
    )
