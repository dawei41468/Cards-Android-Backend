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


class MoveCardsToPlayerAction(PlayerAction):
    cards: List[Card]
    target_player_id: str

    class Config:
        populate_by_name = True
        alias_generator = lambda field_name: "".join([word.capitalize() if i > 0 else word for i, word in enumerate(field_name.split("_"))])

    def validate_action(self, player_index: int, game_state: CardGameSpecificState, room: 'Room'):
        player = room.players[player_index]
        if not all(card in player.hand for card in self.cards):
            raise ValueError("Player does not have all of these cards to move")
        
        target_player_exists = any(p.guest_id == self.target_player_id for p in room.players)
        if not target_player_exists:
            raise ValueError("Target player not found in the room")

    def apply(self, game_state: CardGameSpecificState, player_index: int, room: 'Room'):
        game_logic.move_cards_to_player(room, player_index, self.cards, self.target_player_id)


class ShuffleDeckAction(HostAction):
    def apply(self, game_state: CardGameSpecificState, player_index: int, room: 'Room'):
        game_logic.shuffle_deck(room)


class DealCardsAction(HostAction):
    count: int

    def apply(self, game_state: CardGameSpecificState, player_index: int, room: 'Room'):
        game_logic.deal_cards(room, self.count)

class DrawCardAction(PlayerAction):
    def validate_action(self, player_index: int, game_state: CardGameSpecificState, room: 'Room'):
        if not game_state:
            raise ValueError("Game not started")
        player = room.players[player_index]

    def apply(self, game_state: CardGameSpecificState, player_index: int, room: 'Room'):
        game_logic.draw_card(room, player_index)


class DrawToDiscardAction(PlayerAction):
    def validate_action(self, player_index: int, game_state: CardGameSpecificState, room: 'Room'):
        if not game_state or not game_state.deck:
            raise ValueError("No cards in deck to draw")

    def apply(self, game_state: CardGameSpecificState, player_index: int, room: 'Room'):
        game_logic.draw_to_discard(room)


class DrawFromDiscardAction(PlayerAction):
    def validate_action(self, player_index: int, game_state: CardGameSpecificState, room: 'Room'):
        if not game_state or not game_state.discard_pile:
            raise ValueError("No cards in discard pile to draw")

    def apply(self, game_state: CardGameSpecificState, player_index: int, room: 'Room'):
        game_logic.draw_from_discard(room, player_index)
