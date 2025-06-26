"""
Core utility functions for the application.
"""
import logging
import random
import string
from app.crud import crud_room

logger = logging.getLogger(__name__)

async def generate_unique_room_code(length: int = 4) -> str:
    """Generates a unique, short alphanumeric room code."""
    # Exclude confusing characters like O, 0, I, 1
    chars = [c for c in string.ascii_lowercase + string.digits if c not in 'o0i1']
    while True:
        code = ''.join(random.choices(chars, k=length))
        # Check if a room with this code already exists using the CRUD function
        existing_room = await crud_room.get_room_by_id(room_id=code)
        if not existing_room:
            logger.info(f"Generated unique room code: {code}")
            return code
        else:
            logger.info(f"Generated room code {code} already exists. Retrying...")