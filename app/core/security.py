from datetime import datetime, timedelta, timezone
from typing import Optional
import logging
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
    # If an explicit expires_delta is not provided, default to 1 day.
    # Revert to a standard 1-day expiration now that the client can handle 401s.
    effective_expires_delta = expires_delta or timedelta(days=1)
    logging.info(f"V3: Creating token with lifetime: {effective_expires_delta}") # V3 Logging
    
    # Calculate expiration time based on the current server time.
    expire = datetime.now(timezone.utc) + effective_expires_delta
    
    # Set the 'exp' (expiration) claim as an integer timestamp.
    to_encode["exp"] = int(expire.timestamp())
    
    # The 'iat' claim is optional and is causing issues due to server clock skew.
    # By removing it, we simplify the token and rely only on the 'exp' claim for validation.
    if "iat" in to_encode:
        del to_encode["iat"]
    
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
        # --- Start Enhanced Logging ---
        current_time_utc = datetime.now(timezone.utc)
        
        try:
            # Manually decode payload for logging without validation
            import base64
            import json
            payload_unverified = json.loads(base64.urlsafe_b64decode(token.split('.')[1] + '==').decode())
            exp_time = datetime.fromtimestamp(payload_unverified.get('exp', 0), tz=timezone.utc)
            iat_time = datetime.fromtimestamp(payload_unverified.get('iat', 0), tz=timezone.utc)
        except Exception as e:
            logging.error(f"Could not manually decode payload for logging: {e}")
        # --- End Enhanced Logging ---

        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"leeway": 60}
        )
        guest_id: Optional[str] = payload.get("sub")
        nickname: Optional[str] = payload.get("nickname")

        logging.info(f"Extracted guest_id: {guest_id}")
        if guest_id is None:
            raise CREDENTIALS_EXCEPTION

        return TokenData(sub=guest_id, nickname=nickname)
    except JWTError as e:
        logging.error(f"JWT decoding error: {e}")
        raise CREDENTIALS_EXCEPTION


async def get_current_guest_from_token(token: str = Depends(oauth2_scheme)) -> TokenData:
    """
    Decodes a JWT token and returns the guest data.
    This is a dependency for protected HTTP endpoints.
    """
    return await decode_access_token(token)
