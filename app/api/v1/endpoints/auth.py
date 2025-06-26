import uuid
from fastapi import APIRouter, Body, Depends, HTTPException

from app.models.token import GuestLoginRequest, Token
from app.core.security import create_access_token
from app.core.config import settings # For token_type, if defined there, or just hardcode "bearer"

router = APIRouter()

@router.post("/guest", response_model=Token, summary="Guest Login")
async def guest_login(
    guest_request: GuestLoginRequest,
) -> Token:
    """
    Handles guest login.
    Generates a unique guest ID and returns a JWT access token.
    Optionally accepts a nickname.
    """
    guest_id = str(uuid.uuid4())
    nickname = guest_request.nickname

    # Data to be encoded in the JWT
    token_data = {"sub": guest_id}
    if nickname:
        token_data["nickname"] = nickname
    
    access_token = create_access_token(data=token_data)
    
    return Token(access_token=access_token, token_type="bearer", user_id=guest_id)
