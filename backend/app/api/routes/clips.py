from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.entities import Clip
from app.schemas.clips import ClipListResponse, ClipOut

router = APIRouter(prefix='/clips', tags=['clips'])


@router.get('/{video_id}', response_model=ClipListResponse)
async def get_ranked_clips(video_id: str, db: AsyncSession = Depends(get_db)) -> ClipListResponse:
    result = await db.execute(
        select(Clip).where(Clip.video_id == video_id).order_by(Clip.virality_score.desc())
    )
    clips = [
        ClipOut(
            id=clip.id,
            start_sec=clip.start_sec,
            end_sec=clip.end_sec,
            virality_score=clip.virality_score,
            vertical_url=clip.vertical_url,
        )
        for clip in result.scalars().all()
    ]
    return ClipListResponse(video_id=video_id, clips=clips)
