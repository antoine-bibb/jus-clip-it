from datetime import datetime, timedelta

from app.models.entities import MembershipTier, User

FREE_TOTAL_LIMIT = 5
PRO_MONTHLY_LIMIT = 50


def reset_monthly_quota_if_needed(user: User) -> bool:
    if user.membership_tier != MembershipTier.PRO:
        return False

    now = datetime.utcnow()
    if user.current_period_end is None:
        user.current_period_end = now + timedelta(days=30)
        user.clips_used_period = 0
        return True

    if now >= user.current_period_end:
        user.clips_used_period = 0
        user.current_period_end = now + timedelta(days=30)
        return True
    return False


def can_create_clip(user: User) -> bool:
    # Admins have unlimited uploads
    if user.is_admin:
        return True

    if user.membership_tier == MembershipTier.FREE:
        return user.clips_used_total < FREE_TOTAL_LIMIT
    return user.clips_used_period < PRO_MONTHLY_LIMIT


def consume_clip_quota(user: User, clip_count: int) -> None:
    # Admins don't consume quota
    if user.is_admin:
        return

    user.clips_used_total += clip_count
    if user.membership_tier == MembershipTier.PRO:
        user.clips_used_period += clip_count
