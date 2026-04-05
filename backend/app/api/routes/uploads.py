from fastapi import APIRouter, BackgroundTasks, Depends, File, Header, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.entities import ClipJob, JobStatus, Video
from app.schemas.clips import UploadVideoResponse
from app.services.job_runner import process_video_job_local
from app.services.quota import can_create_clip, consume_clip_quota, reset_monthly_quota_if_needed
from app.services.uploads import save_uploaded_video
from app.services.users import get_or_create_user

router = APIRouter(prefix='/videos', tags=['videos'])


@router.post('/upload', response_model=UploadVideoResponse)
async def upload_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    x_user_email: str = Header(default='free-user@example.com', alias='x-user-email'),
    db: AsyncSession = Depends(get_db),
) -> UploadVideoResponse:
    user = await get_or_create_user(db, x_user_email)
    reset_monthly_quota_if_needed(user)
    if not can_create_clip(user):
        raise HTTPException(status_code=403, detail='Clip quota reached for your plan.')

    saved_path = await save_uploaded_video(file)
    video = Video(user_id=user.id, source_url=saved_path)
    db.add(video)
    await db.flush()

    job = ClipJob(video_id=video.id, status=JobStatus.QUEUED)
    db.add(job)

    # Reserve up to 5 output clips per upload job.
    consume_clip_quota(user, clip_count=5)

    await db.commit()
    background_tasks.add_task(process_video_job_local, job.id, video.id, saved_path)
    return UploadVideoResponse(video_id=video.id, job_id=job.id, status=job.status.value)
