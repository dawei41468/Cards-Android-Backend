from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator, ConfigDict
import datetime
import uuid

class PlayerInRoom(BaseModel):
    guest_id: str = Field(...)
    nickname: Optional[str] = None
    sid: Optional[str] = None # Current Socket.IO session ID, can be updated when known
    is_ready: bool = Field(default=False, description="Whether player is ready to start")

class RoomSettings(BaseModel):
    """Settings for a game room, configurable by the host."""
    number_of_decks: int = Field(default=1, ge=1, le=4, description="Number of decks to use (1-4)")
    include_jokers: bool = Field(default=False, description="Whether to include jokers in the deck")

# --- Game Specific Models ---

class Card(BaseModel):
    id: str = Field(..., description="Unique ID for the card, e.g., 'H7', 'SK' (SuitRank)")
    suit: str = Field(..., description="Suit of the card: H, D, C, S")
    rank: str = Field(..., description="Rank of the card: 2-10, J, Q, K, A")

class CardGameSpecificState(BaseModel):
    status: str = Field(default="pending_start", description="Game status: pending_start, active, finished")
    current_turn_guest_id: Optional[str] = Field(default=None, description="Guest ID of the player whose turn it is")
    turn_number: int = Field(default=0, description="Current turn number")
    turn_order: List[str] = Field(default_factory=list, description="List of guest_ids in order of play")
    deck: List[Card] = Field(default_factory=list, description="Cards remaining in the deck")
    player_hands: Dict[str, List[Card]] = Field(default_factory=dict, description="Mapping of guest_id to their list of cards")
    discard_pile: List[Card] = Field(default_factory=list, description="Cards that have been played")
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
    max_players: int = Field(default=2, ge=2, le=8)
    status: str = Field(default="waiting")
    game_type: Optional[str] = None
    settings: RoomSettings = Field(default_factory=RoomSettings)
    game_state: Optional[CardGameSpecificState] = None
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    updated_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)

    model_config = ConfigDict(
        populate_by_name=True,
        json_encoders={datetime.datetime: lambda dt: dt.isoformat()}
    )

class RoomCreateRequest(BaseModel):
    name: Optional[str] = None
    max_players: int = Field(default=2, ge=2, le=8)
    game_type: Optional[str] = None
    settings: Optional[RoomSettings] = None

class RoomResponse(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={datetime.datetime: lambda dt: dt.isoformat()}
    )
    
    room_id: str = Field(..., description="Unique identifier for the room")
    name: Optional[str] = None
    host_id: str = Field(...)
    max_players: int = Field(default=2, ge=2, le=8)
    status: str = Field(default="waiting")
    game_type: Optional[str] = None
    settings: RoomSettings
    game_state: Optional[CardGameSpecificState] = None
    created_at: datetime.datetime
    current_players: int = Field(..., description="Number of players currently in the room")
    players: List[PlayerInRoom]
    
    @classmethod
    def from_orm(cls, room: Room) -> "RoomResponse":
        """Custom from_orm to ensure all required fields are populated"""
        return cls(
            room_id=room.room_id,
            name=room.name,
            host_id=room.host_id,
            max_players=room.max_players,
            status=room.status,
            game_type=room.game_type,
            settings=room.settings,
            game_state=room.game_state,
            created_at=room.created_at,
            current_players=len(room.players) if room.players else 0,
            players=room.players
        )
