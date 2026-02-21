from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import MembershipTier, User


async def get_or_create_user(db: AsyncSession, email: str) -> User:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user:
        return user

    user = User(
        email=email,
        membership_tier=MembershipTier.FREE,
        clips_used_total=0,
        clips_used_period=0,
        current_period_end=datetime.utcnow() + timedelta(days=30),
    )
    db.add(user)
    await db.flush()
    return user
