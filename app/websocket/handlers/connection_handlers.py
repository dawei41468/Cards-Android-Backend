"""
WebSocket connection and disconnection event handlers.
"""
import logging
from typing import Any, Dict, Optional

from fastapi import HTTPException

from app.websocket.base_handler import BaseWebSocketHandler
# Removed: from app.main import sio - causes circular import
from app.core.security import decode_access_token
from app.crud import crud_room

logger = logging.getLogger(__name__)

class ConnectionHandlers(BaseWebSocketHandler):
    EVENT_JOIN_GAME_ROOM = 'join_game_room'
    EVENT_INITIAL_ROOM_STATE = 'initial_room_state'
    EVENT_ROOM_UPDATED = 'room_updated' # Consistent event name
    """Handlers for WebSocket connection and disconnection events."""
    
    async def handle_connect(self, sid: str, environ: Dict, auth: Any) -> bool:
        """
        Handle new Socket.IO connections.
        
        Args:
            sid: The session ID of the connecting client
            environ: The WSGI environment dictionary
            auth: Authentication data (may contain JWT token)
            
        Returns:
            bool: True if connection is accepted, False otherwise
        """
        logger.info(f"Socket.IO connection attempt from sid: {sid} with auth: {auth}")
        token = None

        # 1. Try to get token from 'auth' dictionary (preferred for socket.io clients)
        if auth and isinstance(auth, dict):
            token = auth.get("token")
            if token:
                logger.info(f"Token found in 'auth' dict for sid {sid}.")

        # 2. If not in 'auth', try to get from HTTP 'Authorization' header in 'environ'
        if not token and environ:
            auth_header = environ.get('HTTP_AUTHORIZATION')
            if auth_header:
                logger.info(f"Authorization header found in environ for sid {sid}")
                parts = auth_header.split()
                if len(parts) == 2 and parts[0].lower() == "bearer":
                    token = parts[1]
                    logger.info(f"Token extracted from Authorization header for sid {sid}.")
                else:
                    logger.warning(f"Malformed Authorization header for sid {sid}")
            else:
                logger.info(f"No HTTP_AUTHORIZATION header in environ for sid {sid}.")

        if not token:
            logger.warning(f"Connection attempt from {sid} without a valid token. Rejecting.")
            try:
                await self.sio.emit('unauthorized', {'message': 'Authentication token required.'}, to=sid)
            except Exception as emit_exc:
                logger.error(f"Failed to emit 'unauthorized' to {sid}: {emit_exc}")
            return False

        try:
            # Validate and decode the JWT token
            token_data = await decode_access_token(token)
            if not token_data or not token_data.sub:
                raise HTTPException(status_code=401, detail="Invalid token")
                
            # Save session data
            await self.sio.save_session(sid, {
                'guest_id': token_data.sub,
                'nickname': token_data.nickname or 'Anonymous',
                'sid': sid,
                'joined_rooms': []
            })
            
            logger.info(f"Client {sid} (Guest ID: {token_data.sub}, Nickname: {token_data.nickname}) connected successfully.")
            return True
            
        except HTTPException as e:
            logger.warning(f"Authentication HTTPException for {sid}: {e.detail}")
            try:
                await self.sio.emit('unauthorized', {'message': e.detail}, to=sid)
            except Exception as emit_exc:
                logger.error(f"Failed to emit 'unauthorized' (HTTPException) to {sid}: {emit_exc}")
            return False
            
        except Exception as e:
            logger.error(f"Unexpected error during connect for {sid}: {e}", exc_info=True)
            try:
                await self.sio.emit('connect_error', {'message': 'Server error during connection.'}, to=sid)
            except Exception as emit_exc:
                logger.error(f"Failed to emit 'connect_error' to {sid}: {emit_exc}")
            return False

    async def handle_disconnect(self, sid: str) -> None:
        """
        Handle Socket.IO disconnections.
        
        Args:
            sid: The session ID of the disconnecting client
        """
        try:
            # Get session data
            session = await self.sio.get_session(sid)
            guest_id = session.get('guest_id', 'Unknown Guest')
            nickname = session.get('nickname', 'N/A')
            
            logger.info(f"Client {sid} (Guest ID: {guest_id}, Nickname: {nickname}) disconnected.")

            # Handle cleanup for rooms the user was in
            joined_rooms_list = session.get('joined_rooms', [])
            if not joined_rooms_list:
                logger.info(f"Disconnect: Guest {guest_id} (SID: {sid}) was not in any tracked rooms.")
                return

            logger.info(f"Disconnect: Guest {guest_id} (SID: {sid}) was in rooms: {joined_rooms_list}. Processing leave for each.")
            
            for room_id_to_leave in list(joined_rooms_list):
                logger.info(f"Disconnect: Processing auto-leave for guest {guest_id} from room {room_id_to_leave}")
                try:
                    # Remove player from room in database
                    updated_room = await crud_room.remove_player_from_room(
                        room_id=room_id_to_leave, 
                        guest_id=guest_id
                    )
                    
                    if not updated_room:
                        logger.warning(f"Disconnect: Room {room_id_to_leave} not found or DB error during auto-leave for {guest_id}.")
                        continue
                    
                    # Broadcast room update to remaining players
                    room_response = {
                        'room_id': room_id_to_leave,
                        'players': [{
                            'guest_id': p.guest_id,
                            'nickname': p.nickname,
                            'is_host': p.is_host
                        } for p in updated_room.players]
                    }
                    
                    await self.broadcast_room_update(
                        room_id=room_id_to_leave,
                        data=room_response,
                        skip_sid=sid
                    )
                    
                    logger.info(f"Disconnect: Broadcasted room_update for room {room_id_to_leave} after {guest_id} left.")
                    
                except Exception as e_disconnect_leave:
                    logger.error(
                        f"Disconnect: Error during auto-leave for guest {guest_id} "
                        f"from room {room_id_to_leave}: {e_disconnect_leave}",
                        exc_info=True
                    )
                    
        except Exception as e:
            logger.error(f"Error in disconnect handler for sid {sid}: {e}", exc_info=True)

    async def handle_join_game_room(self, sid: str, data: Dict[str, Any]) -> None:
        """
        Handle a client's request to join a specific game room's Socket.IO room.
        Args:
            sid: The session ID of the client.
            data: A dictionary expected to contain 'room_id'.
        """
        session = await self.sio.get_session(sid)
        guest_id = session.get('guest_id', 'Unknown Guest')
        nickname = session.get('nickname', 'N/A')
        room_id = data.get('room_id')

        if not room_id:
            logger.warning(f"Client {sid} (Guest: {guest_id}) sent '{self.EVENT_JOIN_GAME_ROOM}' without a room_id.")
            await self.sio.emit('error', {'message': 'room_id is required to join.'}, to=sid)
            return

        logger.info(f"Client {sid} (Guest: {guest_id}, Nickname: {nickname}) attempting to join Socket.IO room: {room_id}")

        try:
            # Add client to the Socket.IO room
            await self.sio.enter_room(sid, room_id)
            logger.info(f"Client {sid} successfully joined Socket.IO room: {room_id}")

            # Update session to track joined rooms
            if 'joined_rooms' not in session:
                session['joined_rooms'] = [] # Initialize if not present
            if room_id not in session['joined_rooms']:
                session['joined_rooms'].append(room_id)
            await self.sio.save_session(sid, session)
            logger.info(f"Updated session for {sid} to include joined_room: {room_id}. Current joined_rooms: {session['joined_rooms']}")

            # Fetch current room state to send back to the client
            db_room = await crud_room.get_room_by_id(room_id=room_id)
            if not db_room:
                logger.warning(f"Room {room_id} not found in DB when {sid} tried to join its Socket.IO room.")
                await self.sio.emit('error', {'message': f'Room {room_id} not found.'}, to=sid)
                # Optionally, leave the Socket.IO room if the game room doesn't exist
                # await self.sio.leave_room(sid, room_id)
                return

            # Prepare room data (consistent with what room_updated sends)
            room_data_for_client = {
                "room_id": db_room.room_id,
                "name": db_room.name,
                "host_id": db_room.host_id,
                "max_players": db_room.max_players,
                "status": db_room.status, # Already a string
                "game_type": db_room.game_type,
                "created_at": db_room.created_at.isoformat(),
                "updated_at": db_room.updated_at.isoformat() if db_room.updated_at else None,
                "players": [p.model_dump() for p in db_room.players], # Assuming PlayerInRoom is Pydantic
                "game_state": db_room.game_state.model_dump() if db_room.game_state else None
            }

            # Send the initial room state back to the client who just joined
            await self.sio.emit(self.EVENT_ROOM_UPDATED, room_data_for_client, to=sid) # Reuse room_updated
            logger.info(f"Sent initial room state ({self.EVENT_ROOM_UPDATED}) for room {room_id} to client {sid}.")

        except Exception as e:
            logger.error(f"Error in handle_join_game_room for sid {sid}, room {room_id}: {e}", exc_info=True)
            await self.sio.emit('error', {'message': f'Error joining room {room_id}.'}, to=sid)
