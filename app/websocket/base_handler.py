"""
Base WebSocket handler class providing common functionality for all WebSocket event handlers.
"""
import logging
from typing import Any, Dict, Optional
import socketio

from fastapi import HTTPException

logger = logging.getLogger(__name__)

class BaseWebSocketHandler:
    """Base class for WebSocket event handlers."""
    
    def __init__(self, sio: socketio.AsyncServer):
        """Initialize with the Socket.IO server instance."""
        self.sio = sio
    
    async def get_session(self, sid: str) -> Dict[str, Any]:
        """Get session data for a given socket ID."""
        return await self.sio.get_session(sid)
    
    async def update_session(self, sid: str, data: Dict[str, Any]) -> None:
        """Update session data for a given socket ID."""
        session = await self.get_session(sid)
        session.update(data)
        self.sio.save_session(sid, session)
    
    async def emit_error(self, sid: str, error_message: str, error_type: str = "error") -> None:
        """Emit an error message to a specific client."""
        logger.error(f"Error for sid {sid}: {error_message}")
        await self.sio.emit('error', {
            'type': error_type,
            'message': error_message
        }, to=sid)
    
    async def validate_session(self, sid: str) -> Dict[str, Any]:
        """Validate that the session exists and contains required data."""
        try:
            session = await self.get_session(sid)
            if not session:
                raise HTTPException(status_code=401, detail="Session not found")
            return session
        except Exception as e:
            logger.error(f"Session validation failed for sid {sid}: {str(e)}")
            raise HTTPException(status_code=401, detail="Invalid session") from e
    
    async def validate_room_data(self, data: Dict[str, Any], required_fields: list) -> None:
        """Validate that required fields exist in the data dictionary."""
        if not data:
            raise ValueError("No data provided")
            
        missing = [field for field in required_fields if field not in data]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")

    async def broadcast_room_update(self, room_id: str, data: Dict[str, Any], skip_sid: Optional[str] = None) -> None:
        """Broadcast a room update to all clients in the room except skip_sid."""
        logger.debug(f"Broadcasting update to room {room_id}: {data}")
        await self.sio.emit('room_update', data, room=room_id, skip_sid=skip_sid)

    async def broadcast_game_state_update(self, room_id: str, game_state: Dict[str, Any], skip_sid: Optional[str] = None) -> None:
        """Broadcast a game state update to all clients in the room except skip_sid."""
        logger.debug(f"Broadcasting game state update to room {room_id}")
        await self.sio.emit('game_state_update', game_state, room=room_id, skip_sid=skip_sid)
