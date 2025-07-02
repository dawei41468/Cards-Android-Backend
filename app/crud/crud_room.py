import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from motor.motor_asyncio import AsyncIOMotorDatabase, AsyncIOMotorCollection
from pymongo.errors import DuplicateKeyError

from app.models.room import Room, PlayerInRoom, Card, CardGameSpecificState
from app.db.mongodb_utils import get_database # To get the DB instance
import random

logger = logging.getLogger(__name__)

ROOM_COLLECTION = "rooms" # Name of the MongoDB collection for rooms

async def get_room_collection() -> AsyncIOMotorCollection:
    """Helper to get the rooms collection."""
    db = get_database()
    if db is None:
        raise RuntimeError("Database not initialized. Cannot get room collection.")
    return db[ROOM_COLLECTION]

async def create_room(room: Room) -> Optional[Room]:
    """
    Creates a new room in the database.
    Uses room.room_id as the MongoDB _id.
    """
    try:
        collection = await get_room_collection()
        # Pydantic's model_dump(by_alias=True) will convert room_id to _id
        room_dict = room.model_dump(by_alias=True) 
        
        # Ensure created_at and updated_at are set, though model defaults should handle this
        # room_dict['created_at'] = room.created_at
        # room_dict['updated_at'] = room.updated_at

        result = await collection.insert_one(room_dict)
        
        if result.inserted_id == room.room_id: # Check if our ID was used
            logger.info(f"Room created successfully with ID: {room.room_id}")
            return room
        else:
            # This case should ideally not happen if room_id is correctly aliased to _id
            # and MongoDB respects it. If MongoDB generates its own ObjectId,
            # it means our aliasing or insertion logic has an issue.
            logger.error(f"Room created, but inserted_id {result.inserted_id} does not match room.room_id {room.room_id}")
            # We might want to fetch the created document by result.inserted_id to return it
            # or handle this as an error. For now, let's assume our ID is used.
            # If not, we'd need to retrieve and reconstruct the Room object.
            # For simplicity, if our ID isn't used, we'll return None for now, indicating an issue.
            # A more robust approach would be to fetch by result.inserted_id.
            created_doc = await collection.find_one({"_id": result.inserted_id})
            if created_doc:
                 return Room(**created_doc) # Re-create Pydantic model
            return None

    except DuplicateKeyError:
        logger.warning(f"Failed to create room. Room with ID {room.room_id} already exists.")
        return None # Or raise a specific exception
    except RuntimeError as e: # Catch if DB is not initialized
        logger.error(f"Error creating room: {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred while creating room {room.room_id}: {e}")
        return None

async def get_room_by_id(room_id: str) -> Optional[Room]:
    """
    Retrieves a single room from the database by its room_id (_id in MongoDB).
    """
    try:
        collection = await get_room_collection()
        room_doc = await collection.find_one({"_id": room_id})
        if room_doc:
            # Pydantic will automatically map _id back to room_id due to alias and populate_by_name
            return Room(**room_doc)
        return None
    except RuntimeError as e: # Catch if DB is not initialized
        logger.error(f"Error getting room by ID: {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred while retrieving room {room_id}: {e}")
        return None

async def get_rooms(skip: int = 0, limit: int = 100) -> List[Room]:
    """
    Retrieves a list of rooms from the database with pagination.
    """
    rooms_list = []
    try:
        collection = await get_room_collection()
        # Sort by creation date, newest first, can be adjusted
        cursor = collection.find().sort("created_at", -1).skip(skip).limit(limit)
        async for room_doc in cursor:
            rooms_list.append(Room(**room_doc))
        return rooms_list
    except RuntimeError as e: # Catch if DB is not initialized
        logger.error(f"Error getting rooms: {e}")
        return [] # Return empty list on error
    except Exception as e:
        logger.error(f"An unexpected error occurred while retrieving rooms: {e}")
        return []

async def add_player_to_room(room_id: str, player: PlayerInRoom) -> Optional[Room]:
    """
    Adds a player to the specified room's player list if not already full and player not already in.
    Updates the room's updated_at timestamp.
    Uses $addToSet for adding new players and updates SID for existing players.
    """
    try:
        collection = await get_room_collection()
        now = datetime.now(timezone.utc)

        # First, try to update SID if player already exists
        # This also implicitly checks if the room exists.
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
            logger.info(f"add_player_to_room: Player {player.guest_id} SID updated in room {room_id}.")
            return Room(**updated_room_doc)

        # Player does not exist, try to add them using $addToSet
        # We also need to ensure the room is not full.
        # The condition for not full is: $expr: {$lt: [{$size: "$players"}, "$max_players"]}
        # However, max_players is a field on the document, not a static value known here without a read.
        # For simplicity and to avoid a read-modify-write for the count check, we'll fetch max_players first.
        # A more advanced query could do this in one go but is more complex.

        room_to_join = await collection.find_one({"_id": room_id})
        if not room_to_join:
            logger.warning(f"add_player_to_room: Room {room_id} not found for adding new player.")
            return None
        
        # Check if room is full before attempting $addToSet
        # Note: 'players' in room_to_join might be slightly stale if another player joined concurrently
        # after the SID update attempt but before this find_one. $addToSet is atomic for the add itself.
        room_settings = room_to_join.get("settings", {})
        max_players = room_settings.get("max_players", 0)

        if len(room_to_join.get("players", [])) >= max_players:
            logger.warning(f"add_player_to_room: Room {room_id} is full (max: {max_players}). Cannot add player {player.guest_id}.")
            return None

        # Add player if not full and player not already present (though $addToSet handles this, it's good for clarity)
        updated_room_doc_after_add = await collection.find_one_and_update(
            {
                "_id": room_id,
                # Condition to ensure player is not already there (though $addToSet handles this, it's good for clarity)
                "players.guest_id": {"$ne": player.guest_id},
                # Condition to ensure room is not full (approximate check, $addToSet is the final arbiter if many join)
                # This can be made more robust with $expr and $size in the query if needed.
            },
            {
                "$addToSet": {"players": player.model_dump()},
                "$set": {"updated_at": now}
            },
            return_document=True
        )

        if updated_room_doc_after_add:
            logger.info(f"Player {player.guest_id} added to room {room_id}. SID: {player.sid}")
            return Room(**updated_room_doc_after_add)
        else:
            # This could happen if: 
            # 1. Room became full between the read and this update.
            # 2. Player was added by another process between the SID check and this update (so guest_id was now present).
            # 3. Room was deleted.
            # Fetch the room again to understand the state if needed for more detailed logging.
            logger.warning(f"Failed to add player {player.guest_id} to room {room_id}. Room might be full, player already added, or room deleted.")
            # Optionally, re-fetch and return current state or None
            final_room_check = await get_room_by_id(room_id)
            return final_room_check # Return whatever the current state is, or None if deleted

    except RuntimeError as e: # Catch if DB is not initialized
        logger.error(f"Error adding player to room (DB not init): {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred while adding player {player.guest_id} to room {room_id}: {e}")
        return None

async def remove_player_from_room(room_id: str, guest_id: str) -> Optional[Room]:
    """
    Removes a player from the specified room's player list.
    Updates the room's updated_at timestamp.
    """
    try:
        collection = await get_room_collection()
        room_doc = await collection.find_one({"_id": room_id})

        if not room_doc:
            logger.warning(f"remove_player_from_room: Room {room_id} not found.")
            return None

        # Remove player from players list
        room = Room(**room_doc)
        room.players = [p for p in room.players if p.guest_id != guest_id]

        # If host left, assign new host if players remain
        if room.host_id == guest_id and room.players:
            room.host_id = room.players[0].guest_id

        # Update the room in the database
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
            logger.info(f"Player {guest_id} removed from room {room_id}.")
            return updated_room
        else:
            logger.warning(f"Failed to remove player {guest_id} from room {room_id}.")
            return None

    except Exception as e:
        logger.error(f"An unexpected error occurred while removing player {guest_id} from room {room_id}: {e}")
        return None

async def get_rooms_with_no_players() -> List[Room]:
    """
    Fetches all rooms that have no players.
    """
    try:
        collection = await get_room_collection()
        cursor = collection.find({"players": {"$size": 0}})
        rooms_list = []
        async for room_doc in cursor:
            rooms_list.append(Room(**room_doc))
        return rooms_list
    except Exception as e:
        logger.error(f"An error occurred while getting empty rooms: {e}")
        return []

async def get_rooms_inactive_since(threshold: datetime) -> List[Room]:
    """
    Fetches all rooms that have been inactive since the given threshold.
    """
    try:
        collection = await get_room_collection()
        cursor = collection.find({"last_activity": {"$lt": threshold}})
        rooms_list = []
        async for room_doc in cursor:
            rooms_list.append(Room(**room_doc))
        return rooms_list
    except Exception as e:
        logger.error(f"An error occurred while getting inactive rooms: {e}")
        return []

async def update_room_status(room_id: str, new_status: str) -> Optional[Room]:
    """
    Updates the status of a room.
    Returns the updated room or None if operation failed.
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
    except Exception as e:
        logger.error(f"Failed to update room status for {room_id}: {e}")
        return None

async def update_game_state(room_id: str, game_state: Dict[str, Any]) -> Optional[Room]:
    """
    Updates the game_state of the specified room and its updated_at timestamp.
    """
    try:
        collection = await get_room_collection()
        current_time = datetime.now(timezone.utc)
        
        # Prepare the update with current timestamp
        update_data = {
            "game_state": game_state,
            "updated_at": current_time
        }
        
        # Perform the update
        result = await collection.update_one(
            {"_id": room_id},
            {"$set": update_data}
        )
        
        if result.matched_count == 0:
            logger.warning(f"Room {room_id} not found for game state update")
            return None
            
        logger.info(f"Game state updated for room {room_id}")
        
        # Return the updated room
        updated_room = await collection.find_one({"_id": room_id})
        return Room.model_validate(updated_room) if updated_room else None
        
    except Exception as e:
        logger.error(f"Error updating game state for room {room_id}: {str(e)}", exc_info=True)
        raise

async def update_room(room_id: str, room: Room) -> Optional[Room]:
    """
    Updates the specified room with the provided room data and updates the updated_at timestamp.
    
    Args:
        room_id: The ID of the room to update
        room: The room data to update with
        
    Returns:
        The updated room if successful, None otherwise
    """
    try:
        collection = await get_room_collection()
        current_time = datetime.now(timezone.utc)
        
        # Convert room to dict and update timestamps
        room_dict = room.model_dump(by_alias=True, exclude_unset=True)
        room_dict['updated_at'] = current_time
        
        # Perform the update, preserving any fields not in the update
        result = await collection.update_one(
            {"_id": room_id},
            {"$set": room_dict}
        )
        
        if result.matched_count == 0:
            logger.warning(f"Room {room_id} not found for update")
            return None
            
        logger.info(f"Room {room_id} updated successfully")
        
        # Return the updated room
        updated_room = await collection.find_one({"_id": room_id})
        return Room.model_validate(updated_room) if updated_room else None
        
    except Exception as e:
        logger.error(f"Error updating room {room_id}: {str(e)}", exc_info=True)
        raise

async def toggle_player_ready(room_id: str, player_id: str) -> Optional[Room]:
    """
    Toggles the ready status of a player in a room.
    Returns the updated room or None if operation failed.
    """
    try:
        logger.debug(f"Attempting to toggle ready status for player {player_id} in room {room_id}")
        
        room = await get_room_by_id(room_id=room_id)
        if not room:
            logger.warning(f"Room {room_id} not found for toggle_player_ready")
            return None
            
        logger.debug(f"Current room players: {[p.guest_id for p in room.players]}")
        
        # Find and update the player's ready status
        updated_players = []
        player_found = False
        
        for player in room.players:
            if player.guest_id == player_id:
                logger.debug(f"Found player {player_id}, current ready status: {player.is_ready}")
                player.is_ready = not player.is_ready
                player_found = True
                logger.debug(f"New ready status: {player.is_ready}")
            updated_players.append(player)
        
        if not player_found:
            logger.warning(f"Player {player_id} not found in room {room_id}")
            return None
            
        # Update the room with modified players
        room.players = updated_players
        room.updated_at = datetime.now(timezone.utc)
        
        # Save to database
        try:
            collection = await get_room_collection()
            update_data = {
                "$set": {
                    "players": [p.model_dump() for p in room.players],
                    "updated_at": room.updated_at
                }
            }
            logger.debug(f"Preparing DB update: {update_data}")
            
            result = await collection.update_one({"_id": room_id}, update_data)
            
            if result.modified_count == 1:
                logger.info(f"Player {player_id} ready status toggled in room {room_id}.")
                return room
            else:
                logger.warning(f"toggle_player_ready: Room {room_id} not found or not modified. Matched: {result.matched_count}, Modified: {result.modified_count}")
                return None
        except Exception as e:
            logger.error(f"Database update failed for toggle_player_ready: {e}", exc_info=True)
            raise
            
    except Exception as e:
        logger.error(f"Unexpected error in toggle_player_ready: {e}", exc_info=True)
        raise

def _create_deck(settings) -> List[Card]:
    """Creates a standard deck of cards based on game settings."""
    suits = ["H", "D", "C", "S"]
    ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
    deck = [Card(id=f"{suit}{rank}-{i}", suit=suit, rank=rank, deckId=i) for i in range(settings.number_of_decks) for suit in suits for rank in ranks]
    if settings.include_jokers:
        for i in range(settings.number_of_decks):
            # Red Joker
            deck.append(Card(id=f"Joker-Red-{i}", suit="Red", rank="Joker", deckId=i))
            # Black Joker
            deck.append(Card(id=f"Joker-Black-{i}", suit="Black", rank="Joker", deckId=i))
    random.shuffle(deck)
    return deck


async def start_game(room_id: str) -> Optional[Room]:
    """Initializes the game state, deals cards, and updates the room."""
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
            current_player_index=0
        )
        room.status = "active"
        
        await collection.update_one(
            {"_id": room_id},
            {"$set": room.model_dump(by_alias=True)}
        )
        
        return await get_room_by_id(room_id)
    except Exception as e:
        logger.error(f"Error starting game for room {room_id}: {e}")
        return None

async def restart_game(room_id: str) -> Optional[Room]:
    """
    Resets the game state for the specified room and immediately starts a new game.
    This includes clearing player hands, deck, discard pile, and table piles,
    shuffling a new deck, dealing cards, and setting game status to 'active'.
    """
    try:
        collection = await get_room_collection()
        room = await get_room_by_id(room_id)
        if not room:
            logger.warning(f"Room {room_id} not found for restart_game.")
            return None

        # Reset player hands and set ready status to True for all players
        # as a restart implies they are ready for the next round.
        for player in room.players:
            player.hand = []
            player.is_ready = True # Automatically ready for restart

        # Create and shuffle a new deck
        deck = _create_deck(room.settings)
        
        # Deal cards to players
        player_hands = {p.guest_id: [deck.pop() for _ in range(room.settings.initial_deal_count)] for p in room.players}
        for player in room.players:
            player.hand = player_hands.get(player.guest_id, [])

        # Reset game state to active
        room.game_state = CardGameSpecificState(
            status="active",
            deck=deck,
            current_turn_guest_id=room.players[0].guest_id, # First player in the list starts
            turn_order=[p.guest_id for p in room.players],
            current_player_index=0,
            discard_pile=[],
            table=[],
            turn_number=0,
            last_action_description=None
        )
        room.status = "active" # Set room status to active after restart

        # Update the room in the database
        result = await collection.update_one(
            {"_id": room_id},
            {"$set": room.model_dump(by_alias=True)}
        )

        if result.modified_count == 1:
            logger.info(f"Game state for room {room_id} reset and restarted successfully.")
            return await get_room_by_id(room_id)
        else:
            logger.warning(f"Failed to restart game for room {room_id}. Matched: {result.matched_count}, Modified: {result.modified_count}")
            return None

    except Exception as e:
        logger.error(f"An unexpected error occurred while restarting game for room {room_id}: {e}", exc_info=True)
        return None

async def delete_room(room_id: str) -> bool:
    """
    Deletes a room from the database by its room_id.
    Returns True if deletion was successful, False otherwise.
    """
    try:
        collection = await get_room_collection()
        result = await collection.delete_one({"_id": room_id})
        
        if result.deleted_count == 1:
            logger.info(f"Room {room_id} deleted successfully.")
            return True
        else:
            logger.warning(f"Room {room_id} not found for deletion.")
            return False
            
    except Exception as e:
        logger.error(f"An unexpected error occurred while deleting room {room_id}: {e}")
        return False
