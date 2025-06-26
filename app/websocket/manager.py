"""
Manages the Socket.IO server instance and provides centralized event emission.
"""
import logging
import socketio
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

class WebSocketManager:
    """A wrapper for the Socket.IO server to manage event emissions."""
    def __init__(self):
        self.sio: Optional[socketio.AsyncServer] = None

    def set_sio(self, sio: socketio.AsyncServer):
        """Sets the Socket.IO server instance."""
        self.sio = sio

    async def emit(self, event: str, data: Any, room: Optional[str] = None, skip_sid: Optional[str] = None):
        """Emits a WebSocket event."""
        if not self.sio:
            logger.error("Socket.IO server not initialized. Cannot emit event.")
            return
        try:
            await self.sio.emit(event, data, room=room, skip_sid=skip_sid)
            logger.info(f"Emitted '{event}' to room '{room}' (skip_sid: {skip_sid})")
        except Exception as e:
            logger.error(f"Failed to emit '{event}' to room '{room}': {e}", exc_info=True)

# Create a singleton instance of the manager
websocket_manager = WebSocketManager()