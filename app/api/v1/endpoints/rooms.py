from fastapi import APIRouter, Depends, HTTPException, status
import logging # <--- Ensure this is at the top level
from typing import List # Any might not be needed anymore

from app.models.room import Room, RoomCreateRequest, RoomResponse, PlayerInRoom, RoomSettings
from app.models.token import TokenData
from app.crud import crud_room
from app.core.security import get_current_guest_from_token
from app.core.utils import generate_unique_room_code
from app.websocket.manager import websocket_manager

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("", response_model=RoomResponse, status_code=status.HTTP_201_CREATED)
async def create_room(
    room_in: RoomCreateRequest,
    current_guest: TokenData = Depends(get_current_guest_from_token)
):
    if not current_guest.sub: 
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials for host",
        )

    # Create a full Room object. room_id, created_at, etc., will be auto-generated.
    # Create PlayerInRoom instance for the host
    host_player = PlayerInRoom(
        guest_id=current_guest.sub,
        nickname=room_in.nickname or current_guest.nickname or "Host",
        sid=None,
        is_ready=True  # Auto-set host as ready
    )

    new_room_id = await generate_unique_room_code()

    room_to_create = Room(
        _id=new_room_id,
        name=room_in.name,
        host_id=current_guest.sub,
        game_type=room_in.game_type,
        players=[host_player],
        settings=room_in.settings if room_in.settings is not None else RoomSettings()
    )

    # Persist to DB using CRUD operation
    persisted_room = await crud_room.create_room(room=room_to_create)

    if not persisted_room:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create room in database.",
        )

    logger.info(f"Room '{persisted_room.name}' (ID: {persisted_room.room_id}) created by host {current_guest.sub} and persisted to DB.")

    # Prepare data for the WebSocket event (should match client's expected RoomResponse structure)
    response = RoomResponse.from_orm(persisted_room)

    try:
        try:
            # Emit a global gameStateUpdate to notify all clients of the new room
            await websocket_manager.emit('gameStateUpdate', response.model_dump(mode='json'))
            logger.info(f"Emitted global 'gameStateUpdate' for new room {response.room_id}")
        except Exception as e:
            logger.error(f"Failed to emit 'gameStateUpdate' for new room {response.room_id}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Failed to emit 'room_created' event for room {response.room_id}: {e}", exc_info=True)

    return response

@router.get("/{room_id}", response_model=RoomResponse)
async def get_room(room_id: str, current_guest: TokenData = Depends(get_current_guest_from_token)):
    """
    Get details for a specific room by its ID.
    Requires authentication.
    """
    if not current_guest.sub: # Basic auth check
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authenticated")

    db_room = await crud_room.get_room_by_id(room_id=room_id)
    if db_room is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")
    
    return RoomResponse.from_orm(db_room)

@router.get("", response_model=List[RoomResponse])
async def list_rooms(
    skip: int = 0, 
    limit: int = 10, # Default to 10 rooms, can be overridden by query param
    current_guest: TokenData = Depends(get_current_guest_from_token)
):
    """
    List available game rooms with pagination.
    Requires authentication.
    """
    if not current_guest.sub: # Basic auth check
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authenticated")

    db_rooms = await crud_room.get_rooms(skip=skip, limit=limit)
    
    # Convert List[Room] to List[RoomResponse]
    response_rooms = [
        RoomResponse.from_orm(room) for room in db_rooms
    ]
    return response_rooms


@router.post("/{room_id}/join", response_model=RoomResponse)
async def join_room_http(
    room_id: str,
    current_guest: TokenData = Depends(get_current_guest_from_token)
):
    """
    Allows an authenticated guest to join an existing room via HTTP.
    The actual WebSocket room join and SID registration should be handled by a 'join_room' socket event.
    """
    if not current_guest.sub or not current_guest.nickname:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials for joining player",
        )

    # First, fetch the room to check its status and host_id
    existing_room_data = await crud_room.get_room_by_id(room_id=room_id)
    if not existing_room_data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")

    player_to_add = PlayerInRoom(
        guest_id=current_guest.sub,
        nickname=current_guest.nickname,
        sid=None
    )

    updated_room = await crud_room.add_player_to_room(room_id=room_id, player=player_to_add)

    if updated_room is None:
        # crud_room.add_player_to_room logs specific reasons (full, not found, DB error)
        # We can make this more specific if crud_room returns error codes/types
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, # Or 409 Conflict if room full, 404 if room disappeared
            detail="Failed to join room. Room may be full or an error occurred."
        )
    
    logger.info(f"Player {current_guest.nickname} (ID: {current_guest.sub}) successfully joined room {room_id} via HTTP.")

    response = RoomResponse.from_orm(updated_room)

    try:
        await websocket_manager.emit('gameStateUpdate', response.model_dump(mode='json'))
        logger.info(f"Emitted global 'gameStateUpdate' event to room {room_id} after player join.")
    except Exception as e:
        logger.error(f"Failed to emit 'room_updated' event for room {room_id}: {e}", exc_info=True)

    return response

@router.post("/{room_id}/toggle-ready", response_model=RoomResponse)
async def toggle_player_ready(
    room_id: str,
    current_guest: TokenData = Depends(get_current_guest_from_token)
):
    """
    Toggles a player's ready status in the room.
    Requires authentication.
    """
    if not current_guest.sub:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )

    try:
        # Get current room state
        room = await crud_room.get_room_by_id(room_id=room_id)
        if not room:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")

        # Toggle ready status for the player
        updated_room = await crud_room.toggle_player_ready(
            room_id=room_id,
            player_id=current_guest.sub
        )

        if not updated_room:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to toggle ready status"
            )

        # Prepare response and broadcast update
        response = RoomResponse.from_orm(updated_room)
        await websocket_manager.emit('gameStateUpdate', response.model_dump(mode='json'))
        logger.info(f"Emitted global 'gameStateUpdate' to room {room_id} after player toggled ready status.")
        
        return response

    except HTTPException:
        raise  # Re-raise HTTPExceptions we created
        
    except Exception as e:
        logger.error(f"Unexpected error in toggle_player_ready endpoint: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while toggling ready status"
        )

@router.post("/{room_id}/start", response_model=RoomResponse)
async def start_game(
    room_id: str,
    current_guest: TokenData = Depends(get_current_guest_from_token)
):
    """
    Starts the game in the specified room.
    Requires host authentication.
    """
    if not current_guest.sub:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )

    try:
        # Get current room state
        room = await crud_room.get_room_by_id(room_id=room_id)
        if not room:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")
            
        # Verify current user is the host
        if room.host_id != current_guest.sub:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the host can start the game"
            )
            
        # Verify all players are ready
        if not all(player.is_ready for player in room.players):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="All players must be ready to start the game"
            )
            
        # Start the game logic
        updated_room = await crud_room.start_game(room_id=room_id)

        if not updated_room:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to start game"
            )

        # Prepare response and broadcast update
        response = RoomResponse.from_orm(updated_room)
        await websocket_manager.emit('gameStateUpdate', response.model_dump(mode='json'), room=room_id)
        
        return response

    except HTTPException:
        raise
        
    except Exception as e:
        logger.error(f"Unexpected error in start_game endpoint: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while starting the game"
        )

@router.post("/{room_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_room(
    room_id: str,
    current_guest: TokenData = Depends(get_current_guest_from_token)
):
    """
    Allows an authenticated guest to leave a room.
    """
    if not current_guest.sub:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )

    try:
        updated_room = await crud_room.remove_player_from_room(room_id=room_id, guest_id=current_guest.sub)

        if updated_room:
            response = RoomResponse.from_orm(updated_room)
            await websocket_manager.emit('gameStateUpdate', response.model_dump(mode='json'))
            logger.info(f"Emitted global 'gameStateUpdate' to room {room_id} after player left.")
        
        return

    except Exception as e:
        logger.error(f"Unexpected error in leave_room endpoint: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while leaving the room"
        )

@router.delete("/clear-all-rooms", status_code=status.HTTP_204_NO_CONTENT)
async def clear_all_rooms():
    """
    Deletes all rooms from the database. For debugging purposes.
    """
    try:
        collection = await crud_room.get_room_collection()
        result = await collection.delete_many({})
        logger.info(f"Deleted {result.deleted_count} rooms.")
        return
    except Exception as e:
        logger.error(f"An unexpected error occurred while clearing rooms: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while clearing rooms."
        )
