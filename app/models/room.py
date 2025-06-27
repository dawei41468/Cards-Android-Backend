from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator, ConfigDict
from datetime import datetime, timezone
import uuid

class Card(BaseModel):
    id: str = Field(..., description="Unique ID for the card, e.g., 'H7', 'SK' (SuitRank)")
    suit: str = Field(..., description="Suit of the card: H, D, C, S")
    rank: str = Field(..., description="Rank of the card: 2-10, J, Q, K, A")
    deckId: int = Field(..., description="The deck ID this card belongs to")

class PlayerInRoom(BaseModel):
    guest_id: str = Field(...)
    nickname: Optional[str] = None
    sid: Optional[str] = None # Current Socket.IO session ID, can be updated when known
    is_ready: bool = Field(default=False, description="Whether player is ready to start")
    hand: List[Card] = Field(default_factory=list, description="The player's hand of cards")

class RoomSettings(BaseModel):
    """Settings for a game room, configurable by the host."""
    number_of_decks: int = Field(default=1, ge=1, le=4, description="Number of decks to use (1-4)")
    include_jokers: bool = Field(default=False, description="Whether to include jokers in the deck")
    max_players: int = Field(default=2, ge=2, le=8, description="Maximum number of players in the room")

# --- Game Specific Models ---

class CardGameSpecificState(BaseModel):
    status: str = Field(default="pending_start", description="Game status: pending_start, active, finished")
    current_turn_guest_id: Optional[str] = Field(default=None, description="Guest ID of the player whose turn it is")
    current_player_index: Optional[int] = Field(default=None, description="Index of the current player in the turn_order list")
    turn_number: int = Field(default=0, description="Current turn number")
    turn_order: List[str] = Field(default_factory=list, description="List of guest_ids in order of play")
    deck: List[Card] = Field(default_factory=list, description="Cards remaining in the deck")
    discard_pile: List[Card] = Field(default_factory=list, description="Cards that have been played")
    table: List[List[Card]] = Field(default_factory=list)
    last_action_description: Optional[str] = Field(default=None, description="Description of the last action taken")
    winner_guest_id: Optional[str] = Field(default=None, description="Guest ID of the winner, if any")

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True
    )

class Room(BaseModel):
    room_id: str = Field(..., alias='_id')
    name: Optional[str] = None
    host_id: str = Field(...)
    players: List[PlayerInRoom] = Field(default_factory=list)
    status: str = Field(default="waiting")
    game_type: Optional[str] = None
    settings: RoomSettings = Field(default_factory=RoomSettings)
    game_state: Optional[CardGameSpecificState] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(
        populate_by_name=True,
        json_encoders={datetime: lambda dt: dt.isoformat()}
    )

class RoomCreateRequest(BaseModel):
    name: Optional[str] = None
    nickname: Optional[str] = None
    game_type: Optional[str] = None
    settings: Optional[RoomSettings] = None

class RoomResponse(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={datetime: lambda dt: dt.isoformat()}
    )
    
    room_id: str = Field(..., description="Unique identifier for the room")
    name: Optional[str] = None
    host_id: str = Field(...)
    status: str = Field(default="waiting")
    game_type: Optional[str] = None
    settings: RoomSettings
    game_state: Optional[CardGameSpecificState] = None
    created_at: datetime
    current_players: int = Field(..., description="Number of players currently in the room")
    players: List[PlayerInRoom]
    last_activity: datetime

    @classmethod
    def from_orm(cls, obj: Any) -> "RoomResponse":
        """Custom from_orm to ensure all required fields are populated"""
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
