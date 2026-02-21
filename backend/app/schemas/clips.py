from pydantic import BaseModel, HttpUrl


class UploadVideoResponse(BaseModel):
    video_id: str
    job_id: str
    status: str


class ClipOut(BaseModel):
    id: str
    start_sec: int
    end_sec: int
    virality_score: int
    vertical_url: HttpUrl


class ClipListResponse(BaseModel):
    video_id: str
    clips: list[ClipOut]
