from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.entities import MembershipTier, User
from app.services.ai_pipeline import (
    extract_audio,
    render_vertical_clip,
    score_segments_with_gpt,
    transcribe_audio,
)
from app.workers.celery_app import celery_app


@celery_app.task
def process_video_job(video_id: str, source_url: str) -> list[dict[str, float | str]]:
    """Background pipeline: transcribe -> rank -> render platform-optimized vertical clips."""
    audio_path = extract_audio(source_url)
    transcript_segments = transcribe_audio(audio_path)
    ranked_clips = score_segments_with_gpt(transcript_segments)

    payload = []
    for clip in ranked_clips:
        rendered = render_vertical_clip(
            video_path=source_url,
            start_time=clip.start_time,
            end_time=clip.end_time,
            transcript_segments=transcript_segments,
        )
        payload.append(
            {
                'video_id': video_id,
                'start_time': clip.start_time,
                'end_time': clip.end_time,
                'virality_score': clip.virality_score,
                'reasoning': clip.reasoning,
                'suggested_title': clip.suggested_title,
                'suggested_caption': clip.suggested_caption,
                'tiktok_path': rendered.tiktok_path,
                'reels_path': rendered.reels_path,
                'shorts_path': rendered.shorts_path,
                'duration': rendered.duration,
                'resolution': rendered.resolution,
                'frame_coordinate_map_path': rendered.frame_coordinate_map_path,
                'final_vertical_path': rendered.final_vertical_path,
            }
        )
    return payload


@celery_app.task
def reset_pro_monthly_quotas() -> int:
    """Reset monthly clip usage for users whose billing period expired."""

    async def _run() -> int:
        now = datetime.utcnow()
        async with SessionLocal() as db:
            result = await db.execute(select(User).where(User.membership_tier == MembershipTier.PRO))
            users = result.scalars().all()
            reset_count = 0
            for user in users:
                if user.current_period_end and now >= user.current_period_end:
                    user.clips_used_period = 0
                    user.current_period_end = now + timedelta(days=30)
                    reset_count += 1
            await db.commit()
            return reset_count

    return __import__('asyncio').run(_run())
