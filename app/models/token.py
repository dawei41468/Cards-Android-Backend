from pydantic import BaseModel
from typing import Optional

class GuestLoginRequest(BaseModel):
    """
    Request model for guest login.
    Allows the client to optionally provide a nickname.
    """
    nickname: Optional[str] = None

class Token(BaseModel):
    """
    Response model for a successfully generated token.
    """
    access_token: str
    token_type: str
    user_id: str

class TokenData(BaseModel):
    """
    Data encoded within the JWT.
    'sub' (subject) will hold the unique guest identifier.
    """
    sub: str # Subject (unique guest ID, e.g., a UUID string)
    nickname: Optional[str] = None
