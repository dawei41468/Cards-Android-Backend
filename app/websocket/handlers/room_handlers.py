"""
WebSocket event handlers for room-related operations.
"""
import logging
from typing import Any, Dict, Optional

from fastapi import HTTPException

from app.websocket.base_handler import BaseWebSocketHandler
from app.models.room import Room, PlayerInRoom, RoomResponse
from app.crud import crud_room

logger = logging.getLogger(__name__)

class RoomHandlers(BaseWebSocketHandler):
    """Handlers for room-related WebSocket events."""
    
    async def handle_join_room(self, sid: str, data: Dict[str, Any]) -> None:
        """Handle a client's request to join a game room.
        
        Args:
            sid: The session ID of the client
            data: Should contain {"room_id": "<room_id>"}
        """
        logger.info(f"join_room event from {sid} with data: {data}")
        
        try:
            # Validate input data
            await self.validate_room_data(data, ["room_id"])
            room_id = data["room_id"]
            
            # Get and validate session
            session = await self.validate_session(sid)
            guest_id = session.get('guest_id')
            nickname = session.get('nickname', 'Anonymous')
            
            if not guest_id:
                await self.emit_error(sid, "Invalid session: missing guest_id")
                return
                
            # Get room from database
            room = await crud_room.get_room(room_id)
            if not room:
                await self.emit_error(sid, f"Room {room_id} not found", "room_not_found")
                return
                
            # Check if room is full
            if len(room.players) >= room.max_players:
                await self.emit_error(sid, "Room is full", "room_full")
                return
                
            # Check if player is already in the room
            existing_player = next((p for p in room.players if p.guest_id == guest_id), None)
            
            if existing_player:
                # Player rejoining - update their SID
                existing_player.sid = sid
                logger.info(f"Player {guest_id} rejoined room {room_id} with new SID {sid}")
            else:
                # New player joining
                new_player = PlayerInRoom(
                    guest_id=guest_id,
                    nickname=nickname,
                    sid=sid,
                    is_host=False
                )
                room.players.append(new_player)
                logger.info(f"Player {guest_id} joined room {room_id}")
            
            # Update room in database
            updated_room = await crud_room.update_room(room_id, room)
            
            # Join the Socket.IO room
            await self.sio.enter_room(sid, room_id)
            
            # Update session with joined room
            joined_rooms = session.get('joined_rooms', [])
            if room_id not in joined_rooms:
                joined_rooms.append(room_id)
                await self.update_session(sid, {'joined_rooms': joined_rooms})
            
            # Prepare and send response
            room_response = RoomResponse.model_validate(updated_room).model_dump(by_alias=True)
            
            # Send full room state to the joining player
            await self.sio.emit('room_joined', room_response, to=sid)
            
            # Broadcast room update to all other players in the room
            await self.broadcast_room_update(
                room_id=room_id,
                data=room_response,
                skip_sid=sid  # Skip the joining player as they already got the full state
            )
            
            logger.info(f"Player {guest_id} successfully joined room {room_id}")
            
        except HTTPException as e:
            logger.error(f"HTTP error in join_room for sid {sid}: {str(e)}")
            await self.emit_error(sid, str(e.detail) if hasattr(e, 'detail') else "An error occurred")
        except ValueError as e:
            logger.error(f"Validation error in join_room for sid {sid}: {str(e)}")
            await self.emit_error(sid, str(e), "validation_error")
        except Exception as e:
            logger.error(f"Unexpected error in join_room for sid {sid}: {str(e)}", exc_info=True)
            await self.emit_error(sid, "An unexpected error occurred")
    
    async def handle_leave_room(self, sid: str, data: Dict[str, Any]) -> None:
        """Handle a client's request to leave a game room.
        
        Args:
            sid: The session ID of the client
            data: Should contain {"room_id": "<room_id>"}
        """
        logger.info(f"leave_room event from {sid} with data: {data}")
        
        try:
            # Validate input data
            await self.validate_room_data(data, ["room_id"])
            room_id = data["room_id"]
            
            # Get and validate session
            session = await self.validate_session(sid)
            guest_id = session.get('guest_id')
            
            if not guest_id:
                await self.emit_error(sid, "Invalid session: missing guest_id")
                return
                
            # Get room from database
            room = await crud_room.get_room(room_id)
            if not room:
                await self.emit_error(sid, f"Room {room_id} not found", "room_not_found")
                return
            
            # Check if player is in the room
            player_index = next((i for i, p in enumerate(room.players) if p.guest_id == guest_id), None)
            if player_index is None:
                await self.emit_error(sid, "You are not in this room", "not_in_room")
                return
                
            # Remove player from room
            room.players.pop(player_index)
            
            # Handle host reassignment if needed
            if guest_id == room.host_id and room.players:
                # Assign new host (first available player)
                room.host_id = room.players[0].guest_id
                room.players[0].is_host = True
                logger.info(f"Assigned new host {room.host_id} for room {room_id}")
            
            # Update room in database
            updated_room = await crud_room.update_room(room_id, room)
            
            # Leave the Socket.IO room
            await self.sio.leave_room(sid, room_id)
            
            # Update session to remove room from joined_rooms
            joined_rooms = session.get('joined_rooms', [])
            if room_id in joined_rooms:
                joined_rooms.remove(room_id)
                await self.update_session(sid, {'joined_rooms': joined_rooms})
            
            # Prepare and send response
            room_response = RoomResponse.model_validate(updated_room).model_dump(by_alias=True)
            
            # Notify the leaving player
            await self.sio.emit('room_left', {"room_id": room_id}, to=sid)
            
            # Broadcast room update to remaining players
            await self.broadcast_room_update(
                room_id=room_id,
                data=room_response,
                skip_sid=sid  # Skip the leaving player
            )
            
            logger.info(f"Player {guest_id} left room {room_id}")
            
        except HTTPException as e:
            logger.error(f"HTTP error in leave_room for sid {sid}: {str(e)}")
            await self.emit_error(sid, str(e.detail) if hasattr(e, 'detail') else "An error occurred")
        except ValueError as e:
            logger.error(f"Validation error in leave_room for sid {sid}: {str(e)}")
            await self.emit_error(sid, str(e), "validation_error")
        except Exception as e:
            logger.error(f"Unexpected error in leave_room for sid {sid}: {str(e)}", exc_info=True)
            await self.emit_error(sid, "An unexpected error occurred")
