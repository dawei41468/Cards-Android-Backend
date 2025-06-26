from datetime import datetime, timedelta, timezone
import logging
from typing import List

from app.crud import crud_room
from app.models.room import Room

logger = logging.getLogger(__name__)

async def clean_inactive_rooms():
    """Clean up inactive rooms that have no players or are inactive for too long."""
    logger.info("Running clean_inactive_rooms task")
    
    # Find rooms that have no players
    empty_rooms = await crud_room.get_rooms_with_no_players()
    for room in empty_rooms:
        await crud_room.delete_room(room.room_id)
        logger.info(f"Deleted empty room: {room.room_id}")

    # Find rooms that have been inactive for more than 60 minutes
    threshold = datetime.now(timezone.utc) - timedelta(minutes=60)
    inactive_rooms = await crud_room.get_rooms_inactive_since(threshold)
    for room in inactive_rooms:
        await crud_room.delete_room(room.room_id)
        logger.info(f"Deleted inactive room: {room.room_id} (last activity: {room.last_activity})")

    return {"deleted_empty_rooms": len(empty_rooms), "deleted_inactive_rooms": len(inactive_rooms)}