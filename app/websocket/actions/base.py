from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from pydantic import BaseModel
from app.models.room import CardGameSpecificState

if TYPE_CHECKING:
    from app.models.room import Room


class PlayerAction(BaseModel, ABC):
    @abstractmethod
    def validate_action(self, player_index: int, game_state: CardGameSpecificState, room: 'Room'):
        raise NotImplementedError

    @abstractmethod
    def apply(self, game_state: CardGameSpecificState, player_index: int, room: 'Room'):
        raise NotImplementedError


class HostAction(PlayerAction):
    def validate_action(self, player_index: int, game_state: CardGameSpecificState, room: 'Room'):
        player = room.players[player_index]
        if player.guest_id != room.host_id:
            raise ValueError("Only the host can perform this action.")