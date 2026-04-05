from datetime import datetime, timedelta
from enum import Enum
from uuid import uuid4

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class MembershipTier(str, Enum):
    FREE = 'free'
    PRO = 'pro'


class JobStatus(str, Enum):
    QUEUED = 'queued'
    RUNNING = 'running'
    DONE = 'done'
    FAILED = 'failed'


class User(Base):
    __tablename__ = 'users'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    membership_tier: Mapped[MembershipTier] = mapped_column(SqlEnum(MembershipTier), default=MembershipTier.FREE)
    is_admin: Mapped[bool] = mapped_column(default=False)
    clips_used_total: Mapped[int] = mapped_column(Integer, default=0)
    clips_used_period: Mapped[int] = mapped_column(Integer, default=0)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    videos: Mapped[list['Video']] = relationship(back_populates='user')

    def ensure_period(self) -> None:
        if self.current_period_end is None:
            self.current_period_end = datetime.utcnow() + timedelta(days=30)


class Video(Base):
    __tablename__ = 'videos'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    source_url: Mapped[str] = mapped_column(Text)
    transcript: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped['User'] = relationship(back_populates='videos')
    clips: Mapped[list['Clip']] = relationship(back_populates='video')


class Clip(Base):
    __tablename__ = 'clips'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    video_id: Mapped[str] = mapped_column(ForeignKey('videos.id'), index=True)
    start_sec: Mapped[int] = mapped_column(Integer)
    end_sec: Mapped[int] = mapped_column(Integer)
    virality_score: Mapped[int] = mapped_column(Integer, index=True)
    vertical_url: Mapped[str] = mapped_column(Text)

    video: Mapped['Video'] = relationship(back_populates='clips')


class ClipJob(Base):
    __tablename__ = 'clip_jobs'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    video_id: Mapped[str] = mapped_column(ForeignKey('videos.id'), index=True)
    status: Mapped[JobStatus] = mapped_column(SqlEnum(JobStatus), default=JobStatus.QUEUED)
    error: Mapped[str | None] = mapped_column(Text, default=None)
