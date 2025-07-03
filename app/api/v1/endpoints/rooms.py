from fastapi import APIRouter, Depends, HTTPException, status
from typing import List

from app.models.room import Room, RoomCreateRequest, RoomResponse, PlayerInRoom, RoomSettings
from app.models.token import TokenData
from app.crud import crud_room
from app.core.security import get_current_guest_from_token
from app.core.utils import generate_unique_room_code
from app.websocket.manager import websocket_manager

router = APIRouter()

@router.post("", response_model=RoomResponse, status_code=status.HTTP_201_CREATED)
async def create_room(
    room_in: RoomCreateRequest,
    current_guest: TokenData = Depends(get_current_guest_from_token)
):
    """
    Creates a new game room. The authenticated guest creating the room is automatically set as the host.
    
    Args:
        room_in (RoomCreateRequest): Details for the new room, including name, game type, and settings.
        current_guest (TokenData): Authenticated guest data, injected via dependency.
        
    Returns:
        RoomResponse: The newly created room's details.
        
    Raises:
        HTTPException: 403 Forbidden if host credentials are invalid, 500 Internal Server Error if DB creation fails.
    """
    if not current_guest.sub:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials for host",
        )

    host_player = PlayerInRoom(
        guest_id=current_guest.sub,
        nickname=room_in.nickname or current_guest.nickname or "Host",
        sid=None,
        is_ready=True
    )

    new_room_id = await generate_unique_room_code()

    room_to_create = Room(
        _id=new_room_id,
        name=room_in.name,
        host_id=current_guest.sub,
        game_type=room_in.game_type,
        players=[host_player],
        settings=room_in.settings if room_in.settings is not None else RoomSettings(),
        game_state=None # Explicitly set game_state to None for new rooms
    )

    persisted_room = await crud_room.create_room(room=room_to_create)

    if not persisted_room:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create room in database.",
        )

    response = RoomResponse.from_orm(persisted_room)

    # Emit a global gameStateUpdate to notify all clients of the new room
    await websocket_manager.emit('gameStateUpdate', response.model_dump(mode='json'))

    return response

@router.get("/{room_id}", response_model=RoomResponse)
async def get_room(room_id: str, current_guest: TokenData = Depends(get_current_guest_from_token)):
    """
    Retrieves details for a specific room by its ID.
    
    Args:
        room_id (str): The ID of the room to retrieve.
        current_guest (TokenData): Authenticated guest data.
        
    Returns:
        RoomResponse: The room's details.
        
    Raises:
        HTTPException: 403 Forbidden if not authenticated, 404 Not Found if room does not exist.
    """
    if not current_guest.sub:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authenticated")

    db_room = await crud_room.get_room_by_id(room_id=room_id)
    if db_room is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")
    
    return RoomResponse.from_orm(db_room)

@router.get("", response_model=List[RoomResponse])
async def list_rooms(
    skip: int = 0,
    limit: int = 10,
    current_guest: TokenData = Depends(get_current_guest_from_token)
):
    """
    Lists available game rooms with pagination.
    
    Args:
        skip (int): Number of rooms to skip for pagination.
        limit (int): Maximum number of rooms to return.
        current_guest (TokenData): Authenticated guest data.
        
    Returns:
        List[RoomResponse]: A list of available rooms.
        
    Raises:
        HTTPException: 403 Forbidden if not authenticated.
    """
    if not current_guest.sub:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authenticated")

    db_rooms = await crud_room.get_rooms(skip=skip, limit=limit)
    
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
    
    Args:
        room_id (str): The ID of the room to join.
        current_guest (TokenData): Authenticated guest data.
        
    Returns:
        RoomResponse: The updated room details after the player joins.
        
    Raises:
        HTTPException: 403 Forbidden if credentials invalid, 404 Not Found if room not found,
                       400 Bad Request if joining fails (e.g., room full).
    """
    if not current_guest.sub or not current_guest.nickname:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials for joining player",
        )

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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to join room. Room may be full or an error occurred."
        )
    
    response = RoomResponse.from_orm(updated_room)
    await websocket_manager.emit('gameStateUpdate', response.model_dump(mode='json'))

    return response

@router.post("/{room_id}/toggle-ready", response_model=RoomResponse)
async def toggle_player_ready(
    room_id: str,
    current_guest: TokenData = Depends(get_current_guest_from_token)
):
    """
    Toggles a player's ready status in the room.
    
    Args:
        room_id (str): The ID of the room.
        current_guest (TokenData): Authenticated guest data.
        
    Returns:
        RoomResponse: The updated room details.
        
    Raises:
        HTTPException: 403 Forbidden if not authenticated, 404 Not Found if room not found,
                       400 Bad Request if toggling fails, 500 Internal Server Error for unexpected errors.
    """
    if not current_guest.sub:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )

    try:
        room = await crud_room.get_room_by_id(room_id=room_id)
        if not room:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")

        updated_room = await crud_room.toggle_player_ready(
            room_id=room_id,
            player_id=current_guest.sub
        )

        if not updated_room:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to toggle ready status"
            )

        response = RoomResponse.from_orm(updated_room)
        await websocket_manager.emit('gameStateUpdate', response.model_dump(mode='json'))
        
        return response

    except HTTPException:
        raise
        
    except Exception as e:
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
    Starts the game in the specified room. Only the host can start the game, and all players must be ready.
    
    Args:
        room_id (str): The ID of the room where the game will start.
        current_guest (TokenData): Authenticated guest data.
        
    Returns:
        RoomResponse: The updated room details with the game started.
        
    Raises:
        HTTPException: 403 Forbidden if not authenticated or not host, 404 Not Found if room not found,
                       400 Bad Request if not all players are ready or game fails to start,
                       500 Internal Server Error for unexpected errors.
    """
    if not current_guest.sub:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )

    try:
        room = await crud_room.get_room_by_id(room_id=room_id)
        if not room:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")
            
        if room.host_id != current_guest.sub:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the host can start the game"
            )
            
        if not all(player.is_ready for player in room.players):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="All players must be ready to start the game"
            )
            
        updated_room = await crud_room.start_game(room_id=room_id)

        if not updated_room:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to start game"
            )

        response = RoomResponse.from_orm(updated_room)
        await websocket_manager.emit('gameStateUpdate', response.model_dump(mode='json'), room=room_id)
        
        return response

    except HTTPException:
        raise
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while starting the game"
        )

@router.post("/{room_id}/restart", response_model=RoomResponse)
async def restart_game(
    room_id: str,
    current_guest: TokenData = Depends(get_current_guest_from_token)
):
    """
    Restarts the game in the specified room, resetting its state. Only the host can restart the game.
    
    Args:
        room_id (str): The ID of the room to restart.
        current_guest (TokenData): Authenticated guest data.
        
    Returns:
        RoomResponse: The updated room details with the game restarted.
        
    Raises:
        HTTPException: 403 Forbidden if not authenticated or not host, 404 Not Found if room not found,
                       400 Bad Request if restarting fails, 500 Internal Server Error for unexpected errors.
    """
    if not current_guest.sub:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )

    try:
        room = await crud_room.get_room_by_id(room_id=room_id)
        if not room:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")

        if room.host_id != current_guest.sub:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the host can restart the game"
            )

        updated_room = await crud_room.restart_game(room_id=room_id)

        if not updated_room:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to restart game"
            )

        response = RoomResponse.from_orm(updated_room)
        await websocket_manager.emit('gameStateUpdate', response.model_dump(mode='json'), room=room_id)
        
        return response

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while restarting the game"
        )

@router.post("/{room_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_room(
    room_id: str,
    current_guest: TokenData = Depends(get_current_guest_from_token)
):
    """
    Allows an authenticated guest to leave a room.
    
    Args:
        room_id (str): The ID of the room to leave.
        current_guest (TokenData): Authenticated guest data.
        
    Returns:
        None: Returns 204 No Content on success.
        
    Raises:
        HTTPException: 403 Forbidden if not authenticated, 500 Internal Server Error for unexpected errors.
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
        
        return

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while leaving the room"
        )

@router.delete("/clear-all-rooms", status_code=status.HTTP_204_NO_CONTENT)
async def clear_all_rooms():
    """
    Deletes all rooms from the database. This endpoint is for debugging and development purposes only.
    
    Returns:
        None: Returns 204 No Content on success.
        
    Raises:
        HTTPException: 500 Internal Server Error for unexpected errors during deletion.
    """
    try:
        collection = await crud_room.get_room_collection()
        result = await collection.delete_many({})
        return
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while clearing rooms."
        )
