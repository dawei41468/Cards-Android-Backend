import pytest
import httpx
from httpx import ASGITransport # <--- Added import
from jose import jwt

# Import your FastAPI app instance, settings, and relevant models
from app.main import app
from app.core.config import settings
from app.models.token import Token # To validate response structure

# pytest-asyncio is usually handled automatically by modern pytest if it detects async tests.
# If you encounter issues, you might need to explicitly enable it (e.g. in pytest.ini or conftest.py)

@pytest.mark.asyncio
async def test_guest_login_with_nickname():
    """
    Test guest login endpoint with a nickname.
    Ensures a 200 OK response and correct token structure.
    """
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client: # <--- Changed here
        response = await client.post(
            f"{settings.API_V1_STR}/guest/login",
            json={"guest_request": {"nickname": "TestGuest123"}}
        )
    assert response.status_code == 200
    token_response_data = response.json()
    
    # Validate the response structure using the Token model
    # This will raise a Pydantic ValidationError if the structure is incorrect
    Token(**token_response_data) 
    
    assert "access_token" in token_response_data
    assert token_response_data["token_type"] == "bearer"

@pytest.mark.asyncio
async def test_guest_login_without_nickname():
    """
    Test guest login endpoint without providing a nickname.
    Ensures a 200 OK response and correct token structure.
    """
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client: # <--- Changed here
        response = await client.post(
            f"{settings.API_V1_STR}/guest/login",
            json={"guest_request": {}} # Sending an empty guest_request object
        )
    assert response.status_code == 200
    token_response_data = response.json()
    Token(**token_response_data)
    assert "access_token" in token_response_data
    assert token_response_data["token_type"] == "bearer"

@pytest.mark.asyncio
async def test_guest_login_token_payload_with_nickname():
    """
    Test that the generated JWT contains the correct payload when a nickname is provided.
    """
    test_nickname = "PayloadTester"
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client: # <--- Changed here
        response = await client.post(
            f"{settings.API_V1_STR}/guest/login",
            json={"guest_request": {"nickname": test_nickname}}
        )
    assert response.status_code == 200
    token_response_data = response.json()
    access_token = token_response_data["access_token"]
    
    # Decode the token to inspect its payload
    # For testing, we might not need to verify expiry strictly here, focus on content.
    payload = jwt.decode(
        access_token, 
        settings.SECRET_KEY, 
        algorithms=[settings.ALGORITHM],
        # Options to bypass time-based checks for this specific test if needed,
        # but default verification of signature is good.
        options={"verify_aud": False} 
    )
    
    assert "sub" in payload  # 'sub' (subject) should be the guest ID
    assert payload["sub"] is not None 
    assert "nickname" in payload
    assert payload["nickname"] == test_nickname
    assert "exp" in payload # Expiration time claim
    assert "iat" in payload # Issued at time claim

@pytest.mark.asyncio
async def test_guest_login_token_payload_without_nickname():
    """
    Test that the generated JWT contains the correct payload when no nickname is provided.
    The 'nickname' claim should be absent or None.
    """
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client: # <--- Changed here
        response = await client.post(
            f"{settings.API_V1_STR}/guest/login",
            json={"guest_request": {}}
        )
    assert response.status_code == 200
    token_response_data = response.json()
    access_token = token_response_data["access_token"]
    
    payload = jwt.decode(
        access_token, 
        settings.SECRET_KEY, 
        algorithms=[settings.ALGORITHM],
        options={"verify_aud": False}
    )
    
    assert "sub" in payload
    assert payload["sub"] is not None
    # Nickname should either be None if the key exists, or the key might be absent.
    # payload.get("nickname") handles both cases gracefully, returning None if absent.
    assert payload.get("nickname") is None 
    assert "exp" in payload
    assert "iat" in payload
