from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

# Import settings and TokenData model
from app.core.config import settings
from app.models.token import TokenData 

# Define the OAuth2 scheme, pointing to the token URL (login endpoint)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/guest/login")

# We can define the credentials exception here to be reused
CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Creates a new JWT access token.

    Args:
        data: The data to encode in the token (e.g., {'sub': user_id, 'nickname': 'guest123'}).
        expires_delta: Optional timedelta for token expiry. If None, uses default from settings.

    Returns:
        The encoded JWT string.
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    # Add 'iat' (issued at) claim
    to_encode.update({"iat": datetime.now(timezone.utc)})
    
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

async def decode_access_token(token: str) -> TokenData:
    """
    Decodes a JWT access token and returns the contained data.
    This is a utility function for internal use.

    Args:
        token: The JWT string.

    Raises:
        CREDENTIALS_EXCEPTION: If the token is invalid or expired.

    Returns:
        TokenData: The decoded token data (sub, nickname).
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        guest_id: Optional[str] = payload.get("sub")
        nickname: Optional[str] = payload.get("nickname")

        if guest_id is None:
            raise CREDENTIALS_EXCEPTION

        return TokenData(sub=guest_id, nickname=nickname)
    except JWTError as e:
        # logger.error(f"JWT decoding error: {e}") 
        raise CREDENTIALS_EXCEPTION


async def get_current_guest_from_token(token: str = Depends(oauth2_scheme)) -> TokenData:
    """
    Decodes a JWT token and returns the guest data.
    This is a dependency for protected HTTP endpoints.
    """
    return await decode_access_token(token)
