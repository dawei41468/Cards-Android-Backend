from fastapi import APIRouter, Depends, HTTPException, status
import logging # <--- Ensure this is at the top level
from typing import List # Any might not be needed anymore

from app.models.room import Room, RoomCreateRequest, RoomResponse, PlayerInRoom, RoomSettings
from app.models.token import TokenData
from app.crud import crud_room
from app.core.security import get_current_guest_from_token
from app.main import sio # Import the Socket.IO server instance

logger = logging.getLogger(__name__) # Initialize logger at module level
router = APIRouter()

import random
import string

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


@router.post("/", response_model=RoomResponse, status_code=status.HTTP_201_CREATED)
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
        nickname=current_guest.nickname or "Host",
        sid=None,
        is_ready=True  # Auto-set host as ready
    )

    new_room_id = await generate_unique_room_code()

    room_to_create = Room(
        room_id=new_room_id,
        name=room_in.name,
        host_id=current_guest.sub,
        max_players=room_in.max_players,
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
    response = RoomResponse(
        room_id=persisted_room.room_id,
        name=persisted_room.name,
        host_id=persisted_room.host_id,
        max_players=persisted_room.max_players,
        status=persisted_room.status,
        game_type=persisted_room.game_type,
        settings=persisted_room.settings,
        game_state=persisted_room.game_state,
        created_at=persisted_room.created_at,
        current_players=len(persisted_room.players),
        players=persisted_room.players
    )

    try:
        await sio.emit('room_created', response.model_dump(mode='json'))
        logger.info(f"Emitted 'room_created' event for new room {response.room_id}")
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
    
    return RoomResponse(
        room_id=db_room.room_id,
        name=db_room.name,
        host_id=db_room.host_id,
        max_players=db_room.max_players,
        status=db_room.status,
        game_type=db_room.game_type,
        settings=db_room.settings,
        game_state=db_room.game_state,
        created_at=db_room.created_at,
        current_players=len(db_room.players),
        players=db_room.players
    )

@router.get("/", response_model=List[RoomResponse]) # Note the path is "/" for the router's root
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
        RoomResponse(
            room_id=room.room_id,
            name=room.name,
            host_id=room.host_id,
            max_players=room.max_players,
            status=room.status,
            game_type=room.game_type,
            settings=room.settings,
            game_state=room.game_state,
            created_at=room.created_at,
            current_players=len(room.players)
        ) for room in db_rooms
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

    response = RoomResponse(
        room_id=updated_room.room_id,
        name=updated_room.name,
        host_id=updated_room.host_id,
        max_players=updated_room.max_players,
        status=updated_room.status,
        game_type=updated_room.game_type,
        settings=updated_room.settings,
        game_state=updated_room.game_state,
        created_at=updated_room.created_at,
        current_players=len(updated_room.players),
        players=updated_room.players
    )

    try:
        await sio.emit('room_updated', response.model_dump(mode='json'), room=room_id)
        logger.info(f"Emitted 'room_updated' event for room {room_id} after player join.")
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
        await sio.emit('room_updated', response.model_dump(mode='json'), room=room_id)
        
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
            
        # Update room status to STARTING
        updated_room = await crud_room.update_room_status(
            room_id=room_id,
            new_status="starting"
        )

        if not updated_room:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to start game"
            )

        # Prepare response and broadcast update
        response = RoomResponse.from_orm(updated_room)
        await sio.emit('room_updated', response.model_dump(mode='json'), room=room_id)
        
        return response

    except HTTPException:
        raise
        
    except Exception as e:
        logger.error(f"Unexpected error in start_game endpoint: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while starting the game"
        )
