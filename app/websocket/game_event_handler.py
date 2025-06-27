"""
WebSocket game event handlers for the card game.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import HTTPException

import socketio
from app.core.security import decode_access_token
from app.crud import crud_room
from app.domain.game_logic import initialize_game_state
from app.models.room import Card, CardGameSpecificState, Room, RoomResponse, PlayerInRoom

from app.websocket.actions.player_actions import (
    DealCardsAction,
    DiscardCardsAction,
    MoveCardToPlayerAction,
    PlayCardsAction,
    RecallCardsAction,
    ShuffleDeckAction,
)
logger = logging.getLogger(__name__)

class GameEventHandler:
    """Handlers for all WebSocket events."""

    EVENT_JOIN_GAME_ROOM = 'join_game_room'
    EVENT_LEAVE_GAME_ROOM = 'leave_game_room'
    EVENT_START_GAME = 'start_game'
    EVENT_PLAYER_ACTION = 'playerAction'
    EVENT_GAME_STATE_UPDATE = 'gameStateUpdate'
    EVENT_PLAYER_JOINED = 'playerJoined'
    EVENT_PLAYER_LEFT = 'playerLeft'

    def __init__(self, sio: socketio.AsyncServer):
        self.sio = sio
        self.sio.on(self.EVENT_PLAYER_ACTION, self.handle_player_action)

    async def handle_connect(self, sid: str, environ: Dict, auth: Any) -> bool:
        """Handle new Socket.IO connections."""
        logger.info(f"Connection attempt from {sid}")
        token = (auth or {}).get("token")

        if not token:
            logger.warning(f"Connection from {sid} rejected: missing token.")
            return False

        try:
            token_data = await decode_access_token(token)
            if not token_data or not token_data.sub:
                raise HTTPException(status_code=401, detail="Invalid token")

            await self.sio.save_session(sid, {
                'guest_id': token_data.sub,
                'nickname': token_data.nickname or 'Anonymous',
            })
            logger.info(f"Client {sid} (Guest ID: {token_data.sub}) connected.")
            return True
        except HTTPException as e:
            logger.warning(f"Auth failed for {sid}: {e.detail}")
            return False
        except Exception as e:
            logger.error(f"Connection error for {sid}: {e}", exc_info=True)
            return False

    async def handle_disconnect(self, sid: str):
        """
        Handle Socket.IO disconnections.
        """
        try:
            session = await self.sio.get_session(sid)
            guest_id = session.get('guest_id', 'Unknown Guest')
            nickname = session.get('nickname', 'N/A')
            
            logger.info(f"Client {sid} (Guest ID: {guest_id}, Nickname: {nickname}) disconnected.")

            joined_rooms_list = session.get('joined_rooms', [])
            if not joined_rooms_list:
                logger.info(f"Disconnect: Guest {guest_id} (SID: {sid}) was not in any tracked rooms.")
                return

            logger.info(f"Disconnect: Guest {guest_id} (SID: {sid}) was in rooms: {joined_rooms_list}. Processing leave for each.")
            
            for room_id_to_leave in list(joined_rooms_list):
                logger.info(f"Disconnect: Processing auto-leave for guest {guest_id} from room {room_id_to_leave}")
                try:
                    updated_room = await crud_room.remove_player_from_room(
                        room_id=room_id_to_leave, 
                        guest_id=guest_id
                    )
                    
                    if not updated_room:
                        logger.warning(f"Disconnect: Room {room_id_to_leave} not found or DB error during auto-leave for {guest_id}.")
                        continue
                    
                    # After removing the player, fetch the complete room state to ensure a consistent update
                    # Instead of fetching the full state, just notify that a player left.
                    await self.sio.emit(
                        self.EVENT_PLAYER_LEFT,
                        {'guest_id': guest_id},
                        room=room_id_to_leave,
                        skip_sid=sid  # The disconnected client doesn't need this
                    )
                    logger.info(f"Disconnect: Broadcasted '{self.EVENT_PLAYER_LEFT}' for room {room_id_to_leave} after {guest_id} left.")
                    
                    # Update last activity time
                    updated_room.last_activity = datetime.now(timezone.utc)
                    await crud_room.update_room(room_id_to_leave, updated_room)
                    
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
            await self.sio.enter_room(sid, room_id)
            logger.info(f"Client {sid} successfully joined Socket.IO room: {room_id}")

            if 'joined_rooms' not in session:
                session['joined_rooms'] = []
            if room_id not in session['joined_rooms']:
                session['joined_rooms'].append(room_id)
            await self.sio.save_session(sid, session)
            logger.info(f"Updated session for {sid} to include joined_room: {room_id}. Current joined_rooms: {session['joined_rooms']}")

            player_to_add = PlayerInRoom(
                guest_id=guest_id,
                nickname=nickname,
                sid=sid
            )
            updated_room = await crud_room.add_player_to_room(room_id=room_id, player=player_to_add)

            if not updated_room:
                logger.warning(f"Failed to add player {guest_id} to room {room_id} in DB.")
                await self.sio.emit('error', {'message': f'Failed to join room {room_id}.'}, to=sid)
                return

            # After adding the player, re-fetch the room to get the complete and updated player list
            final_room_state = await crud_room.get_room_by_id(room_id)
            if not final_room_state:
                logger.error(f"Could not retrieve final room state for {room_id} after player join.")
                await self.sio.emit('error', {'message': 'Could not confirm join.'}, to=sid)
                return

            room_data_for_client = RoomResponse.from_orm(final_room_state).model_dump(by_alias=True)

            # Send the full state ONLY to the player who just joined.
            await self.sio.emit(
                self.EVENT_GAME_STATE_UPDATE,
                room_data_for_client,
                to=sid
            )

            # Notify OTHER players in the room that a new player has joined.
            await self.sio.emit(
                self.EVENT_PLAYER_JOINED,
                player_to_add.model_dump(),
                room=room_id,
                skip_sid=sid
            )
            logger.info(f"Sent state to new player {guest_id} and notified room {room_id}. Current players: {len(final_room_state.players)}")

            # Update last activity time
            updated_room.last_activity = datetime.now(timezone.utc)
            await crud_room.update_room(room_id, updated_room)

        except Exception as e:
            logger.error(f"Error in handle_join_game_room for sid {sid}, room {room_id}: {e}", exc_info=True)
            await self.sio.emit('error', {'message': f'Error joining room {room_id}.'}, to=sid)

    async def handle_leave_game_room(self, sid: str, data: Dict[str, Any]) -> None:
        """
        Handle a client's request to leave a specific game room's Socket.IO room.
        """
        session = await self.sio.get_session(sid)
        guest_id = session.get('guest_id', 'Unknown Guest')
        room_id = data.get('room_id')

        if not room_id:
            logger.warning(f"Client {sid} (Guest: {guest_id}) sent '{self.EVENT_LEAVE_GAME_ROOM}' without a room_id.")
            return

        logger.info(f"Client {sid} (Guest: {guest_id}) attempting to leave Socket.IO room: {room_id}")
        try:
            await self.sio.leave_room(sid, room_id)
            logger.info(f"Client {sid} successfully left Socket.IO room: {room_id}")

            if 'joined_rooms' in session and room_id in session['joined_rooms']:
                session['joined_rooms'].remove(room_id)
                await self.sio.save_session(sid, session)
                logger.info(f"Updated session for {sid} to remove joined_room: {room_id}. Current joined_rooms: {session['joined_rooms']}")

        except Exception as e:
            logger.error(f"Error in handle_leave_game_room for sid {sid}, room {room_id}: {e}", exc_info=True)


    async def handle_start_game(self, sid: str, data: Dict) -> None:
        """
        Handle game start request from room host.
        """
        logger.info(f"start_game event from {sid} with data: {data}")
        
        try:
            session = await self._get_validated_session(sid)
            guest_id = session['guest_id']
            
            if not data or 'room_id' not in data:
                raise ValueError("Missing required fields: room_id")
                
            room_id = data['room_id']
            
            room = await self._get_room(room_id)
            self._validate_host(room, guest_id)
            
            if room.status == 'active':
                raise ValueError("Game already started")
                
            if len(room.players) < 2:
                raise ValueError("At least 2 players are required to start")
            
            game_state_dict = initialize_game_state(room.room_id, room.settings.model_dump(), [p.model_dump() for p in room.players])
            
            # Update last activity time before saving
            room.last_activity = datetime.now(timezone.utc)
            room.status = 'active'
            room.game_state = CardGameSpecificState(**game_state_dict)
            room.game_state.status = 'active'

            # Set initial turn
            if room.game_state.turn_order:
                room.game_state.current_turn_guest_id = room.game_state.turn_order[0]
                room.game_state.current_player_index = 0
            
            updated_room = await crud_room.update_room(room_id, room)
            
            room_response = RoomResponse.from_orm(updated_room).model_dump(by_alias=True)
            await self.sio.emit(self.EVENT_GAME_STATE_UPDATE, room_response, room=room_id)
            logger.info(f"Game started in room {room_id}")
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error in start_game for sid {sid}: {error_msg}", exc_info=True)
            await self.sio.emit('start_game_failed', {
                'room_id': data.get('room_id') if data else None,
                'error': error_msg
            }, to=sid)

    async def handle_player_action(self, sid: str, data: Dict) -> None:
        """
        Handle player game actions.
        """
        logger.info(f"player_action event from {sid} with data: {data}")
        
        try:
            session = await self._get_validated_session(sid)
            guest_id = session['guest_id']
            
            if not data or 'room_id' not in data or 'action_type' not in data:
                raise ValueError("Missing required fields: room_id and action_type")
                
            room_id = data['room_id']
            action_type = data['action_type']
            action_data = data.get('action_data', {})
            
            room = await self._get_room(room_id)
            self._validate_player_in_room(room, guest_id)
            
            if room.status != 'active' or not room.game_state:
                raise ValueError("Game not in progress")
                
            action_classes = {
                'PLAY_CARDS': PlayCardsAction,
                'DISCARD_CARDS': DiscardCardsAction,
                'RECALL_CARDS': RecallCardsAction,
                'MOVE_CARD_TO_PLAYER': MoveCardToPlayerAction,
                'SHUFFLE_DECK': ShuffleDeckAction,
                'DEAL_CARDS': DealCardsAction,
            }
            
            action_class = action_classes.get(action_type)
            if not action_class:
                raise ValueError(f"Unknown action type: {action_type}")

            action = action_class(**action_data)
            
            player_index = -1
            for i, p in enumerate(room.players):
                if p.guest_id == guest_id:
                    player_index = i
                    break
            
            action.validate_action(player_index, room.game_state, room)
            action.apply(room.game_state, player_index, room)

            # --- Advance Turn ---
            if room.game_state.turn_order:
                current_index = room.game_state.current_player_index or 0
                next_index = (current_index + 1) % len(room.game_state.turn_order)
                room.game_state.current_player_index = next_index
                room.game_state.current_turn_guest_id = room.game_state.turn_order[next_index]
                room.game_state.turn_number += 1
            
            # Update last activity time before saving
            room.last_activity = datetime.now(timezone.utc)
            updated_room = await crud_room.update_room(room_id, room)
            
            room_response = RoomResponse.from_orm(updated_room).model_dump(by_alias=True)
            await self.sio.emit(self.EVENT_GAME_STATE_UPDATE, room_response, room=room_id)
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error in player_action for sid {sid}: {error_msg}", exc_info=True)
            await self.sio.emit('player_action_failed', {
                'room_id': data.get('room_id') if data else None,
                'error': error_msg
            }, to=sid)

    async def _get_validated_session(self, sid: str) -> Dict:
        session = await self.sio.get_session(sid)
        if not session or 'guest_id' not in session:
            raise ValueError("Invalid session")
        return session

    async def _get_room(self, room_id: str) -> Room:
        room = await crud_room.get_room_by_id(room_id)
        if not room:
            raise ValueError("Room not found")
        return room

    def _validate_host(self, room: Room, guest_id: str) -> None:
        if room.host_id != guest_id:
            raise ValueError("Only the host can perform this action")

    def _validate_player_in_room(self, room: Room, guest_id: str) -> None:
        if not any(p.guest_id == guest_id for p in room.players):
            raise ValueError("Player not in room")