from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator, ConfigDict
from datetime import datetime, timezone
import uuid

class Card(BaseModel):
    """Represents a single playing card."""
    id: str = Field(..., description="Unique ID for the card (e.g., 'H7', 'SK')")
    suit: str = Field(..., description="Suit of the card (H, D, C, S)")
    rank: str = Field(..., description="Rank of the card (2-10, J, Q, K, A)")
    deckId: int = Field(..., description="The ID of the deck this card belongs to (for multi-deck games)")

class PlayerInRoom(BaseModel):
    """Represents a player within a specific game room."""
    guest_id: str = Field(..., description="Unique identifier for the guest player.")
    nickname: Optional[str] = Field(None, description="Player's chosen nickname.")
    sid: Optional[str] = Field(None, description="Current Socket.IO session ID of the player.")
    is_ready: bool = Field(default=False, description="Indicates if the player is ready to start the game.")
    hand: List[Card] = Field(default_factory=list, description="The list of cards currently in the player's hand.")

class RoomSettings(BaseModel):
    """Configurable settings for a game room."""
    number_of_decks: int = Field(default=1, ge=1, le=4, description="Number of standard decks to use (1-4).")
    include_jokers: bool = Field(default=False, description="Whether to include jokers in the deck.")
    max_players: int = Field(default=2, ge=2, le=8, description="Maximum number of players allowed in the room.")
    initial_deal_count: int = Field(default=0, ge=0, le=17, description="Number of cards dealt to each player at game start.")

class PlayedHand(BaseModel):
    """Represents a set of cards played by a player in a single turn."""
    player_id: str = Field(..., description="The ID of the player who played this hand.")
    cards: List[Card] = Field(default_factory=list, description="The cards played in this hand.")

class CardGameSpecificState(BaseModel):
    """Represents the dynamic state of an ongoing card game within a room."""
    status: str = Field(default="pending_start", description="Current status of the game (e.g., 'pending_start', 'active', 'finished').")
    current_turn_guest_id: Optional[str] = Field(None, description="The guest ID of the player whose turn it currently is.")
    current_player_index: Optional[int] = Field(None, description="The index of the current player in the turn order list.")
    turn_number: int = Field(default=0, description="The current turn number in the game.")
    turn_order: List[str] = Field(default_factory=list, description="Ordered list of guest IDs defining the turn sequence.")
    deck: List[Card] = Field(default_factory=list, description="Cards remaining in the main draw deck.")
    discard_pile: List[Card] = Field(default_factory=list, description="Cards in the discard pile.")
    table: List[List[Card]] = Field(default_factory=list, description="Cards currently on the table, organized by played sets.")
    last_action_description: Optional[str] = Field(None, description="A brief description of the last significant game action.")
    winner_guest_id: Optional[str] = Field(None, description="The guest ID of the game winner, if the game has finished.")
    last_player_id: Optional[str] = Field(None, description="The guest ID of the player who last played or discarded cards.")
    last_played_or_discarded_cards: Dict[str, List[Card]] = Field(default_factory=dict, description="A map storing the last cards played or discarded by each player, for recall functionality.")

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True
    )

class Room(BaseModel):
    """Represents a game room, storing its configuration, players, and current game state."""
    room_id: str = Field(..., alias='_id', description="Unique identifier for the room (MongoDB _id alias).")
    name: Optional[str] = Field(None, description="The name of the game room.")
    host_id: str = Field(..., description="The guest ID of the room's host.")
    players: List[PlayerInRoom] = Field(default_factory=list, description="List of players currently in the room.")
    status: str = Field(default="waiting", description="Current status of the room (e.g., 'waiting', 'active').")
    game_type: Optional[str] = Field(None, description="The type of card game being played in this room.")
    settings: RoomSettings = Field(default_factory=RoomSettings, description="Configurable settings for the game room.")
    game_state: Optional[CardGameSpecificState] = Field(None, description="The current state of the game if it has started.")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Timestamp when the room was created.")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Timestamp of the last update to the room.")
    last_activity: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Timestamp of the last activity in the room, used for cleanup.")

    model_config = ConfigDict(
        populate_by_name=True,
        json_encoders={datetime: lambda dt: dt.isoformat()}
    )

class RoomCreateRequest(BaseModel):
    """Request model for creating a new game room."""
    name: Optional[str] = Field(None, description="Desired name for the new room.")
    nickname: Optional[str] = Field(None, description="Nickname of the host creating the room.")
    game_type: Optional[str] = Field(None, description="The type of game to be played in the room.")
    settings: Optional[RoomSettings] = Field(None, description="Optional game settings for the new room.")

class RoomResponse(BaseModel):
    """Response model for returning room details to clients."""
    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={datetime: lambda dt: dt.isoformat()}
    )
    
    room_id: str = Field(..., description="Unique identifier for the room.")
    name: Optional[str] = Field(None, description="The name of the game room.")
    host_id: str = Field(..., description="The guest ID of the room's host.")
    status: str = Field(default="waiting", description="Current status of the room.")
    game_type: Optional[str] = Field(None, description="The type of card game being played.")
    settings: RoomSettings = Field(..., description="Configurable settings for the game room.")
    game_state: Optional[CardGameSpecificState] = Field(None, description="The current state of the game if active.")
    created_at: datetime = Field(..., description="Timestamp when the room was created.")
    current_players: int = Field(..., description="Number of players currently in the room.")
    players: List[PlayerInRoom] = Field(..., description="List of players in the room.")
    last_activity: datetime = Field(..., description="Timestamp of the last activity in the room.")

    @classmethod
    def from_orm(cls, obj: Any) -> "RoomResponse":
        """
        Creates a RoomResponse instance from a Room ORM object.
        This custom method ensures all fields, including derived ones like `current_players`, are populated.
        """
        return cls(
            room_id=str(obj.room_id),
            name=obj.name,
            host_id=obj.host_id,
            status=obj.status,
            game_type=obj.game_type,
            settings=obj.settings,
            game_state=obj.game_state,
            created_at=obj.created_at,
            current_players=len(obj.players) if obj.players else 0,
            players=obj.players,
            last_activity=obj.last_activity
        )
