from pydantic import BaseModel, EmailStr


class CheckoutSessionRequest(BaseModel):
    email: EmailStr


class CheckoutSessionResponse(BaseModel):
    checkout_url: str
    session_id: str
