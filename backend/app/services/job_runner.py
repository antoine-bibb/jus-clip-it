from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.entities import Clip, ClipJob, JobStatus
from app.services.ai_pipeline import (
    RankedClip,
    extract_audio,
    render_vertical_clip,
    score_segments_with_gpt,
    transcribe_audio,
)

MIN_CLIP_SECONDS = 30.0
MAX_CLIP_SECONDS = 180.0
MAX_CLIPS_PER_VIDEO = 5


def _normalize_ranked_clips(
    ranked: list[RankedClip],
    video_duration: float,
) -> list[RankedClip]:
    normalized: list[RankedClip] = []
    for clip in ranked:
        start_time = max(0.0, min(float(clip.start_time), max(video_duration - MIN_CLIP_SECONDS, 0.0)))
        end_time = max(start_time + MIN_CLIP_SECONDS, float(clip.end_time))
        end_time = min(end_time, start_time + MAX_CLIP_SECONDS, video_duration)
        if end_time - start_time < MIN_CLIP_SECONDS:
            continue
        normalized.append(replace(clip, start_time=start_time, end_time=end_time))

    normalized.sort(key=lambda c: c.virality_score, reverse=True)
    return normalized[:MAX_CLIPS_PER_VIDEO]


def _probe_duration_seconds(video_path: str) -> float:
    import subprocess

    result = subprocess.run(
        [
            'ffprobe',
            '-v',
            'error',
            '-show_entries',
            'format=duration',
            '-of',
            'default=noprint_wrappers=1:nokey=1',
            video_path,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return 0.0
    try:
        return max(0.0, float(result.stdout.strip()))
    except ValueError:
        return 0.0


async def _set_job_status(job_id: str, status: JobStatus, error: str | None = None) -> None:
    async with SessionLocal() as db:
        result = await db.execute(select(ClipJob).where(ClipJob.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            return
        job.status = status
        job.error = error
        await db.commit()


async def _persist_clip(
    video_id: str,
    start_time: float,
    end_time: float,
    virality_score: float,
    vertical_url: str,
) -> None:
    async with SessionLocal() as db:
        clip = Clip(
            video_id=video_id,
            start_sec=int(start_time),
            end_sec=int(end_time),
            virality_score=int(round(virality_score)),
            vertical_url=vertical_url,
        )
        db.add(clip)
        await db.commit()


async def _process_video_job_async(job_id: str, video_id: str, source_path: str) -> None:
    await _set_job_status(job_id, JobStatus.RUNNING, error=None)

    try:
        audio_path = await asyncio.to_thread(extract_audio, source_path)
        transcript_segments = await asyncio.to_thread(transcribe_audio, audio_path)
        ranked = await asyncio.to_thread(score_segments_with_gpt, transcript_segments)
        duration = await asyncio.to_thread(_probe_duration_seconds, source_path)
        if duration <= 0 and ranked:
            duration = max(c.end_time for c in ranked)

        normalized = _normalize_ranked_clips(ranked, duration if duration > 0 else 0.0)
        if not normalized:
            await _set_job_status(job_id, JobStatus.FAILED, error='No valid clips found in 30-180 second range.')
            return

        for clip in normalized:
            rendered = await asyncio.to_thread(
                render_vertical_clip,
                source_path,
                clip.start_time,
                clip.end_time,
                transcript_segments,
            )
            await _persist_clip(
                video_id=video_id,
                start_time=clip.start_time,
                end_time=clip.end_time,
                virality_score=clip.virality_score,
                vertical_url=Path(rendered.final_vertical_path).as_uri(),
            )

        await _set_job_status(job_id, JobStatus.DONE, error=None)
    except Exception as exc:
        await _set_job_status(job_id, JobStatus.FAILED, error=str(exc))


def process_video_job_local(job_id: str, video_id: str, source_path: str) -> None:
    asyncio.run(_process_video_job_async(job_id=job_id, video_id=video_id, source_path=source_path))
