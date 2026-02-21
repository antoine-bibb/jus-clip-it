import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.models.entities import MembershipTier, User
from app.schemas.billing import CheckoutSessionRequest, CheckoutSessionResponse
from app.services.users import get_or_create_user

router = APIRouter(prefix='/billing', tags=['billing'])
stripe.api_key = settings.stripe_secret_key


@router.post('/checkout', response_model=CheckoutSessionResponse)
async def create_checkout_session(payload: CheckoutSessionRequest, db: AsyncSession = Depends(get_db)) -> CheckoutSessionResponse:
    if not settings.stripe_price_pro_monthly:
        raise HTTPException(status_code=500, detail='Missing STRIPE_PRICE_PRO_MONTHLY configuration.')

    user = await get_or_create_user(db, payload.email)
    session = stripe.checkout.Session.create(
        mode='subscription',
        line_items=[{'price': settings.stripe_price_pro_monthly, 'quantity': 1}],
        customer_email=user.email,
        metadata={'user_id': user.id},
        success_url=f'{settings.app_base_url}/dashboard?billing=success',
        cancel_url=f'{settings.app_base_url}/dashboard?billing=cancelled',
    )
    return CheckoutSessionResponse(checkout_url=session.url, session_id=session.id)


@router.post('/webhooks/stripe')
async def handle_stripe_webhook(
    request: Request,
    stripe_signature: str = Header(alias='stripe-signature'),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(payload, stripe_signature, settings.stripe_webhook_secret)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f'Invalid webhook: {exc}') from exc

    event_type = event.get('type')
    obj = event.get('data', {}).get('object', {})

    if event_type == 'checkout.session.completed':
        user_id = obj.get('metadata', {}).get('user_id')
        customer_id = obj.get('customer')
        subscription_id = obj.get('subscription')
        if user_id:
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if user:
                user.membership_tier = MembershipTier.PRO
                user.stripe_customer_id = customer_id
                user.stripe_subscription_id = subscription_id
                user.clips_used_period = 0

    if event_type in {'customer.subscription.deleted', 'customer.subscription.updated'}:
        subscription_id = obj.get('id')
        status = obj.get('status')
        if subscription_id and status in {'canceled', 'unpaid', 'incomplete_expired'}:
            result = await db.execute(select(User).where(User.stripe_subscription_id == subscription_id))
            user = result.scalar_one_or_none()
            if user:
                user.membership_tier = MembershipTier.FREE
                user.stripe_subscription_id = None

    await db.commit()
    return {'received': True}
