from pydantic import BaseModel


class UploadVideoResponse(BaseModel):
    video_id: str
    job_id: str
    status: str


class JobStatusResponse(BaseModel):
    job_id: str
    video_id: str
    status: str
    progress_percent: int
    clips_completed: int
    clips_expected: int
    error: str | None = None


class ClipOut(BaseModel):
    id: str
    start_sec: int
    end_sec: int
    virality_score: int
    vertical_url: str


class ClipListResponse(BaseModel):
    video_id: str
    clips: list[ClipOut]
