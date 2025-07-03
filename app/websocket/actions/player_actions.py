from typing import TYPE_CHECKING, List
from app.models.room import Card, CardGameSpecificState
from app.websocket.actions.base import HostAction, PlayerAction
from app.domain import game_logic

if TYPE_CHECKING:
    from app.models.room import Room


class BasePlayerAction(PlayerAction):
    def validate_game_started(self, game_state: CardGameSpecificState):
        if not game_state:
            raise ValueError("Game not started")

    def validate_player_exists(self, player_index: int, room: 'Room'):
        if not room.players or player_index < 0 or player_index >= len(room.players):
            raise ValueError("Player not found in room")
        return room.players[player_index]

    def validate_card_ownership(self, player, cards: List[Card]):
        if not all(card in player.hand for card in cards):
            raise ValueError("Player does not have all of these cards")

    def validate_cards_on_table(self, game_state: CardGameSpecificState):
        if not game_state.table:
            raise ValueError("No cards on the table to recall")

    def validate_deck_not_empty(self, game_state: CardGameSpecificState):
        if not game_state.deck:
            raise ValueError("No cards in deck to draw")

    def validate_discard_pile_not_empty(self, game_state: CardGameSpecificState):
        if not game_state.discard_pile:
            raise ValueError("No cards in discard pile to draw")

    def validate_target_player(self, target_player_id: str, room: 'Room'):
        if not any(p.guest_id == target_player_id for p in room.players):
            raise ValueError("Target player not found in the room")


class PlayCardsAction(BasePlayerAction):
    cards: List[Card]

    def validate_action(self, player_index: int, game_state: CardGameSpecificState, room: 'Room'):
        self.validate_game_started(game_state)
        player = self.validate_player_exists(player_index, room)
        self.validate_card_ownership(player, self.cards)

    def apply(self, game_state: CardGameSpecificState, player_index: int, room: 'Room'):
        game_logic.play_cards(room, player_index, self.cards)


class DiscardCardsAction(BasePlayerAction):
    cards: list[Card]

    def validate_action(self, player_index: int, game_state: CardGameSpecificState, room: 'Room'):
        player = self.validate_player_exists(player_index, room)
        self.validate_card_ownership(player, self.cards)

    def apply(self, game_state: CardGameSpecificState, player_index: int, room: 'Room'):
        game_logic.discard_cards(room, player_index, self.cards)


class RecallCardsAction(BasePlayerAction):
    def validate_action(self, player_index: int, game_state: CardGameSpecificState, room: 'Room'):
        self.validate_game_started(game_state)
        self.validate_cards_on_table(game_state)

    def apply(self, game_state: CardGameSpecificState, player_index: int, room: 'Room'):
        game_logic.recall_cards(room, player_index)


class MoveCardsToPlayerAction(BasePlayerAction):
    cards: List[Card]
    target_player_id: str

    class Config:
        populate_by_name = True
        alias_generator = lambda field_name: "".join([word.capitalize() if i > 0 else word for i, word in enumerate(field_name.split("_"))])

    def validate_action(self, player_index: int, game_state: CardGameSpecificState, room: 'Room'):
        player = self.validate_player_exists(player_index, room)
        self.validate_card_ownership(player, self.cards)
        self.validate_target_player(self.target_player_id, room)

    def apply(self, game_state: CardGameSpecificState, player_index: int, room: 'Room'):
        game_logic.move_cards_to_player(room, player_index, self.cards, self.target_player_id)


class ShuffleDeckAction(HostAction):
    def apply(self, game_state: CardGameSpecificState, player_index: int, room: 'Room'):
        game_logic.shuffle_deck(room)


class DealCardsAction(HostAction):
    count: int

    def apply(self, game_state: CardGameSpecificState, player_index: int, room: 'Room'):
        game_logic.deal_cards(room, self.count)

class DrawCardAction(BasePlayerAction):
    def validate_action(self, player_index: int, game_state: CardGameSpecificState, room: 'Room'):
        self.validate_game_started(game_state)
        self.validate_player_exists(player_index, room)

    def apply(self, game_state: CardGameSpecificState, player_index: int, room: 'Room'):
        game_logic.draw_card(room, player_index)


class DrawToDiscardAction(BasePlayerAction):
    def validate_action(self, player_index: int, game_state: CardGameSpecificState, room: 'Room'):
        self.validate_game_started(game_state)
        self.validate_deck_not_empty(game_state)

    def apply(self, game_state: CardGameSpecificState, player_index: int, room: 'Room'):
        game_logic.draw_to_discard(room)


class DrawFromDiscardAction(BasePlayerAction):
    def validate_action(self, player_index: int, game_state: CardGameSpecificState, room: 'Room'):
        self.validate_game_started(game_state)
        self.validate_discard_pile_not_empty(game_state)

    def apply(self, game_state: CardGameSpecificState, player_index: int, room: 'Room'):
        game_logic.draw_from_discard(room, player_index)


class UpdateHandOrderAction(BasePlayerAction):
    cards: List[Card]

    def validate_action(self, player_index: int, game_state: CardGameSpecificState, room: 'Room'):
        self.validate_player_exists(player_index, room)

    def apply(self, game_state: CardGameSpecificState, player_index: int, room: 'Room'):
        player = room.players[player_index]
        player.hand = self.cards
