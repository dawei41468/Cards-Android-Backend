from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from motor.motor_asyncio import AsyncIOMotorDatabase, AsyncIOMotorCollection
from pymongo.errors import DuplicateKeyError

from app.models.room import Room, PlayerInRoom, Card, CardGameSpecificState
from app.db.mongodb_utils import get_database # To get the DB instance
import random


ROOM_COLLECTION = "rooms" # Name of the MongoDB collection for rooms

async def get_room_collection() -> AsyncIOMotorCollection:
    """
    Retrieves the MongoDB collection for rooms.
    
    Returns:
        AsyncIOMotorCollection: The MongoDB collection for rooms.
        
    Raises:
        RuntimeError: If the database is not initialized.
    """
    db = get_database()
    if db is None:
        raise RuntimeError("Database not initialized. Cannot get room collection.")
    return db[ROOM_COLLECTION]

async def create_room(room: Room) -> Optional[Room]:
    """
    Creates a new room entry in the database.
    
    Args:
        room (Room): The Room object to be created.
        
    Returns:
        Optional[Room]: The created Room object if successful, None otherwise.
    """
    try:
        collection = await get_room_collection()
        room_dict = room.model_dump(by_alias=True)
        
        result = await collection.insert_one(room_dict)
        
        if result.inserted_id == room.room_id:
            return room
        else:
            created_doc = await collection.find_one({"_id": result.inserted_id})
            if created_doc:
                 return Room(**created_doc)
            return None

    except DuplicateKeyError:
        return None
    except RuntimeError:
        return None
    except Exception:
        return None

async def get_room_by_id(room_id: str) -> Optional[Room]:
    """
    Retrieves a single room from the database by its unique room ID.
    
    Args:
        room_id (str): The ID of the room to retrieve.
        
    Returns:
        Optional[Room]: The retrieved Room object if found, None otherwise.
    """
    try:
        collection = await get_room_collection()
        room_doc = await collection.find_one({"_id": room_id})
        if room_doc:
            return Room(**room_doc)
        return None
    except RuntimeError:
        return None
    except Exception:
        return None

async def get_rooms(skip: int = 0, limit: int = 100) -> List[Room]:
    """
    Retrieves a list of rooms from the database with pagination support.
    
    Args:
        skip (int): The number of documents to skip.
        limit (int): The maximum number of documents to return.
        
    Returns:
        List[Room]: A list of Room objects. Returns an empty list on error.
    """
    rooms_list = []
    try:
        collection = await get_room_collection()
        cursor = collection.find().sort("created_at", -1).skip(skip).limit(limit)
        async for room_doc in cursor:
            rooms_list.append(Room(**room_doc))
        return rooms_list
    except RuntimeError:
        return []
    except Exception:
        return []

async def add_player_to_room(room_id: str, player: PlayerInRoom) -> Optional[Room]:
    """
    Adds a player to the specified room's player list.
    If the player already exists, their SID is updated.
    If the room is full, no player is added.
    
    Args:
        room_id (str): The ID of the room to add the player to.
        player (PlayerInRoom): The PlayerInRoom object representing the player to add.
        
    Returns:
        Optional[Room]: The updated Room object if the player was added or updated, None otherwise.
    """
    try:
        collection = await get_room_collection()
        now = datetime.now(timezone.utc)

        # Try to update SID if player already exists
        updated_room_doc = await collection.find_one_and_update(
            {
                "_id": room_id,
                "players.guest_id": player.guest_id
            },
            {
                "$set": {
                    "players.$.sid": player.sid,
                    "updated_at": now
                }
            },
            return_document=True
        )

        if updated_room_doc:
            return Room(**updated_room_doc)

        # If player does not exist, check if room is full and then add them
        room_to_join = await collection.find_one({"_id": room_id})
        if not room_to_join:
            return None
        
        room_settings = room_to_join.get("settings", {})
        max_players = room_settings.get("max_players", 0)

        if len(room_to_join.get("players", [])) >= max_players:
            return None

        updated_room_doc_after_add = await collection.find_one_and_update(
            {
                "_id": room_id,
                "players.guest_id": {"$ne": player.guest_id},
            },
            {
                "$addToSet": {"players": player.model_dump()},
                "$set": {"updated_at": now}
            },
            return_document=True
        )

        if updated_room_doc_after_add:
            return Room(**updated_room_doc_after_add)
        else:
            final_room_check = await get_room_by_id(room_id)
            return final_room_check

    except RuntimeError:
        return None
    except Exception:
        return None

async def remove_player_from_room(room_id: str, guest_id: str) -> Optional[Room]:
    """
    Removes a player from the specified room's player list.
    If the host leaves, a new host is assigned if other players remain.
    
    Args:
        room_id (str): The ID of the room.
        guest_id (str): The ID of the guest to remove.
        
    Returns:
        Optional[Room]: The updated Room object if the player was removed, None otherwise.
    """
    try:
        collection = await get_room_collection()
        room_doc = await collection.find_one({"_id": room_id})

        if not room_doc:
            return None

        room = Room(**room_doc)
        room.players = [p for p in room.players if p.guest_id != guest_id]

        if room.host_id == guest_id and room.players:
            room.host_id = room.players[0].guest_id

        now = datetime.now(timezone.utc)
        result = await collection.update_one(
            {"_id": room_id},
            {"$set": {
                "players": [p.model_dump() for p in room.players],
                "host_id": room.host_id,
                "updated_at": now
            }}
        )

        if result.modified_count == 1:
            updated_room = await get_room_by_id(room_id)
            return updated_room
        else:
            return None

    except Exception:
        return None

async def get_rooms_with_no_players() -> List[Room]:
    """
    Retrieves all rooms from the database that currently have no players.
    
    Returns:
        List[Room]: A list of Room objects with no players. Returns an empty list on error.
    """
    try:
        collection = await get_room_collection()
        cursor = collection.find({"players": {"$size": 0}})
        rooms_list = []
        async for room_doc in cursor:
            rooms_list.append(Room(**room_doc))
        return rooms_list
    except Exception:
        return []

async def get_rooms_inactive_since(threshold: datetime) -> List[Room]:
    """
    Fetches all rooms that have not had any activity since the specified timestamp.
    
    Args:
        threshold (datetime): The datetime threshold for inactivity.
        
    Returns:
        List[Room]: A list of inactive Room objects. Returns an empty list on error.
    """
    try:
        collection = await get_room_collection()
        cursor = collection.find({"last_activity": {"$lt": threshold}})
        rooms_list = []
        async for room_doc in cursor:
            rooms_list.append(Room(**room_doc))
        return rooms_list
    except Exception:
        return []

async def update_room_status(room_id: str, new_status: str) -> Optional[Room]:
    """
    Updates the status of a specific room in the database.
    
    Args:
        room_id (str): The ID of the room to update.
        new_status (str): The new status to set for the room.
        
    Returns:
        Optional[Room]: The updated Room object if successful, None otherwise.
    """
    try:
        collection = await get_room_collection()
        update_data = {
            "$set": {
                "status": new_status,
                "updated_at": datetime.now(timezone.utc)
            }
        }
        
        result = await collection.update_one(
            {"_id": room_id},
            update_data
        )
        
        if result.modified_count == 1:
            return await get_room_by_id(room_id)
        return None
    except Exception:
        return None

async def update_game_state(room_id: str, game_state: Dict[str, Any]) -> Optional[Room]:
    """
    Updates the `game_state` field of a specified room and its `updated_at` timestamp.
    
    Args:
        room_id (str): The ID of the room to update.
        game_state (Dict[str, Any]): The new game state dictionary.
        
    Returns:
        Optional[Room]: The updated Room object if successful, None otherwise.
    """
    try:
        collection = await get_room_collection()
        current_time = datetime.now(timezone.utc)
        
        update_data = {
            "game_state": game_state,
            "updated_at": current_time
        }
        
        result = await collection.update_one(
            {"_id": room_id},
            {"$set": update_data}
        )
        
        if result.matched_count == 0:
            return None
            
        updated_room = await collection.find_one({"_id": room_id})
        return Room.model_validate(updated_room) if updated_room else None
        
    except Exception:
        raise

async def update_room(room_id: str, room: Room) -> Optional[Room]:
    """
    Updates an existing room with new data.
    
    Args:
        room_id (str): The ID of the room to update.
        room (Room): The Room object containing the updated data.
        
    Returns:
        Optional[Room]: The updated Room object if successful, None otherwise.
    """
    try:
        collection = await get_room_collection()
        current_time = datetime.now(timezone.utc)
        
        room_dict = room.model_dump(by_alias=True, exclude_unset=True)
        room_dict['updated_at'] = current_time
        
        result = await collection.update_one(
            {"_id": room_id},
            {"$set": room_dict}
        )
        
        if result.matched_count == 0:
            return None
            
        updated_room = await collection.find_one({"_id": room_id})
        return Room.model_validate(updated_room) if updated_room else None
        
    except Exception:
        raise

async def toggle_player_ready(room_id: str, player_id: str) -> Optional[Room]:
    """
    Toggles the ready status of a specific player within a room.
    
    Args:
        room_id (str): The ID of the room.
        player_id (str): The ID of the player whose ready status to toggle.
        
    Returns:
        Optional[Room]: The updated Room object if the status was toggled, None otherwise.
    """
    try:
        room = await get_room_by_id(room_id=room_id)
        if not room:
            return None
            
        updated_players = []
        player_found = False
        
        for player in room.players:
            if player.guest_id == player_id:
                player.is_ready = not player.is_ready
                player_found = True
            updated_players.append(player)
        
        if not player_found:
            return None
            
        room.players = updated_players
        room.updated_at = datetime.now(timezone.utc)
        
        try:
            collection = await get_room_collection()
            update_data = {
                "$set": {
                    "players": [p.model_dump() for p in room.players],
                    "updated_at": room.updated_at
                }
            }
            
            result = await collection.update_one({"_id": room_id}, update_data)
            
            if result.modified_count == 1:
                return room
            else:
                return None
        except Exception:
            raise
            
    except Exception:
        raise

def _create_deck(settings) -> List[Card]:
    """
    Creates a standard deck of cards based on the provided game settings.
    
    Args:
        settings: The game settings, including number of decks and joker inclusion.
        
    Returns:
        List[Card]: A shuffled list of Card objects representing the deck.
    """
    suits = ["H", "D", "C", "S"]
    ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
    deck = [Card(id=f"{suit}{rank}-{i}", suit=suit, rank=rank, deckId=i) for i in range(settings.number_of_decks) for suit in suits for rank in ranks]
    if settings.include_jokers:
        for i in range(settings.number_of_decks):
            deck.append(Card(id=f"Joker-Red-{i}", suit="Red", rank="Joker", deckId=i))
            deck.append(Card(id=f"Joker-Black-{i}", suit="Black", rank="Joker", deckId=i))
    random.shuffle(deck)
    return deck


async def start_game(room_id: str) -> Optional[Room]:
    """
    Initializes the game state for a room, deals initial cards, and sets the game status to 'active'.
    
    Args:
        room_id (str): The ID of the room to start the game in.
        
    Returns:
        Optional[Room]: The updated Room object with the initialized game state, None if room not found or error.
    """
    try:
        collection = await get_room_collection()
        room = await get_room_by_id(room_id)
        if not room:
            return None

        deck = _create_deck(room.settings)
        
        player_hands = {p.guest_id: [deck.pop() for _ in range(room.settings.initial_deal_count)] for p in room.players}

        for player in room.players:
            player.hand = player_hands.get(player.guest_id, [])

        room.game_state = CardGameSpecificState(
            status="active",
            deck=deck,
            current_turn_guest_id=room.players[0].guest_id,
            turn_order=[p.guest_id for p in room.players],
            current_player_index=0,
            last_action_description=None,
            winner_guest_id=None,
            last_player_id=None,
            last_played_or_discarded_cards={}
        )
        room.status = "active"
        
        await collection.update_one(
            {"_id": room_id},
            {"$set": room.model_dump(by_alias=True)}
        )
        
        return await get_room_by_id(room_id)
    except Exception:
        return None

async def restart_game(room_id: str) -> Optional[Room]:
    """
    Resets the game state for the specified room and immediately starts a new game.
    This includes clearing player hands, deck, discard pile, and table piles,
    shuffling a new deck, dealing cards, and setting game status to 'active'.
    
    Args:
        room_id (str): The ID of the room to restart.
        
    Returns:
        Optional[Room]: The updated Room object with the restarted game state, None if room not found or error.
    """
    try:
        collection = await get_room_collection()
        room = await get_room_by_id(room_id)
        if not room:
            return None

        for player in room.players:
            player.hand = []
            player.is_ready = True

        deck = _create_deck(room.settings)
        
        player_hands = {p.guest_id: [deck.pop() for _ in range(room.settings.initial_deal_count)] for p in room.players}
        for player in room.players:
            player.hand = player_hands.get(player.guest_id, [])

        room.game_state = CardGameSpecificState(
            status="active",
            deck=deck,
            current_turn_guest_id=room.players[0].guest_id,
            turn_order=[p.guest_id for p in room.players],
            current_player_index=0,
            discard_pile=[],
            table=[],
            turn_number=0,
            last_action_description=None,
            winner_guest_id=None,
            last_player_id=None,
            last_played_or_discarded_cards={}
        )
        room.status = "active"

        result = await collection.update_one(
            {"_id": room_id},
            {"$set": room.model_dump(by_alias=True)}
        )

        if result.modified_count == 1:
            return await get_room_by_id(room_id)
        else:
            return None

    except Exception:
        return None

async def delete_room(room_id: str) -> bool:
    """
    Deletes a room from the database by its room ID.
    
    Args:
        room_id (str): The ID of the room to delete.
        
    Returns:
        bool: True if deletion was successful, False otherwise.
    """
    try:
        collection = await get_room_collection()
        result = await collection.delete_one({"_id": room_id})
        
        if result.deleted_count == 1:
            return True
        else:
            return False
    except Exception as e:
        return False
