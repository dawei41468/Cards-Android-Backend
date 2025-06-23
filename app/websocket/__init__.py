"""
WebSocket package initialization.
"""
from typing import Optional
import socketio

from .handlers.room_handlers import RoomHandlers
from .handlers.connection_handlers import ConnectionHandlers
from .handlers.game_handlers import GameHandlers

def setup_socketio(sio: socketio.AsyncServer) -> None:
    """
    Set up WebSocket event handlers.
    
    Args:
        sio: The Socket.IO server instance
    """
    # Initialize handlers
    connection_handlers = ConnectionHandlers(sio)
    room_handlers = RoomHandlers(sio)
    game_handlers = GameHandlers(sio)
    
    # Register connection event handlers
    sio.on("connect", connection_handlers.handle_connect)
    sio.on("disconnect", connection_handlers.handle_disconnect)
    
    # Register room event handlers
    sio.on("join_room", room_handlers.handle_join_room)
    sio.on("leave_room", room_handlers.handle_leave_room)
    
    # Register game event handlers
    sio.on("start_game", game_handlers.handle_start_game)
    sio.on("player_action", game_handlers.handle_player_action)
