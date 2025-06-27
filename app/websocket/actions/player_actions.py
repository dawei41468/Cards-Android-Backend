from typing import TYPE_CHECKING, List
from app.models.room import Card, CardGameSpecificState
from app.websocket.actions.base import HostAction, PlayerAction
from app.domain import game_logic

if TYPE_CHECKING:
    from app.models.room import Room


class PlayCardsAction(PlayerAction):
    cards: List[Card]

    def validate_action(self, player_index: int, game_state: CardGameSpecificState, room: 'Room'):
        if not game_state:
            raise ValueError("Game not started")
        player = room.players[player_index]
        if game_state.current_turn_guest_id != player.guest_id:
            raise ValueError("Not your turn")
        if not all(card in player.hand for card in self.cards):
            raise ValueError("Player does not have all of these cards")

    def apply(self, game_state: CardGameSpecificState, player_index: int, room: 'Room'):
        game_logic.play_cards(room, player_index, self.cards)


class DiscardCardsAction(PlayerAction):
    cards: list[Card]

    def validate_action(self, player_index: int, game_state: CardGameSpecificState, room: 'Room'):
        player = room.players[player_index]
        if not all(card in player.hand for card in self.cards):
            raise ValueError("Player does not have all of these cards")

    def apply(self, game_state: CardGameSpecificState, player_index: int, room: 'Room'):
        game_logic.discard_cards(room, player_index, self.cards)


class RecallCardsAction(PlayerAction):
    def validate_action(self, player_index: int, game_state: CardGameSpecificState, room: 'Room'):
        if not game_state or not game_state.table:
            raise ValueError("No cards on the table to recall")

    def apply(self, game_state: CardGameSpecificState, player_index: int, room: 'Room'):
        game_logic.recall_cards(room, player_index)


class MoveCardToPlayerAction(PlayerAction):
    card: Card
    target_player_id: str

    def validate_action(self, player_index: int, game_state: CardGameSpecificState, room: 'Room'):
        player = room.players[player_index]
        if self.card not in player.hand:
            raise ValueError("Player does not have this card to move")
        
        target_player_exists = any(p.guest_id == self.target_player_id for p in room.players)
        if not target_player_exists:
            raise ValueError("Target player not found in the room")

    def apply(self, game_state: CardGameSpecificState, player_index: int, room: 'Room'):
        game_logic.move_card_to_player(room, player_index, self.card, self.target_player_id)


class ShuffleDeckAction(HostAction):
    def apply(self, game_state: CardGameSpecificState, player_index: int, room: 'Room'):
        game_logic.shuffle_deck(room)


class DealCardsAction(HostAction):
    count: int

    def apply(self, game_state: CardGameSpecificState, player_index: int, room: 'Room'):
        game_logic.deal_cards(room, self.count)