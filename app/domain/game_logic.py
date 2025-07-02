from typing import List
"""
Core game logic for the card game.
"""
from app.models.room import Room, Card
import random
import uuid

def play_cards(room: Room, player_index: int, cards: list[Card]):
    """
    Move cards from a player's hand to the table.
    """
    if not room.game_state:
        return
    player = room.players[player_index]
    for card in cards:
        if card in player.hand:
            player.hand.remove(card)
    room.game_state.table.append(cards)

def discard_cards(room: Room, player_index: int, cards: list[Card]):
    """
    Move cards from a player's hand to the discard pile.
    """
    if not room.game_state:
        return
    player = room.players[player_index]
    for card in cards:
        if card in player.hand:
            player.hand.remove(card)
            room.game_state.discard_pile.append(card)

def recall_cards(room: Room, player_index: int):
    """
    Recall all cards from the table to a player's hand.
    """
    if not room.game_state:
        return
    player = room.players[player_index]
    for pile in room.game_state.table:
        for card in pile:
            player.hand.append(card)
    room.game_state.table.clear()

def move_cards_to_player(room: Room, source_player_index: int, cards: List[Card], target_player_id: str):
    """
    Move cards from one player's hand to another's.
    """
    source_player = room.players[source_player_index]
    target_player = next((p for p in room.players if p.guest_id == target_player_id), None)

    if target_player:
        for card in cards:
            if card in source_player.hand:
                source_player.hand.remove(card)
                target_player.hand.append(card)

def create_deck(num_decks: int = 1, include_jokers: bool = False) -> List[Card]:
    """
    Creates a standard deck of cards.
    """
    suits = ['H', 'D', 'C', 'S']
    ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
    deck = []
    for deck_id in range(num_decks):
        for suit in suits:
            for rank in ranks:
                card_id = f"{suit}{rank}-{deck_id}"
                deck.append(Card(id=card_id, suit=suit, rank=rank, deckId=deck_id))
        if include_jokers:
            deck.append(Card(id=f"Joker-Red-{deck_id}", suit="Red", rank="Joker", deckId=deck_id))
            deck.append(Card(id=f"Joker-Black-{deck_id}", suit="Black", rank="Joker", deckId=deck_id))
    return deck

def shuffle_deck(room: Room):
    """
    Shuffle the deck, incorporating cards from the table.
    """
    if not room.game_state:
        return
    cards_to_shuffle = []
    for pile in room.game_state.table:
        cards_to_shuffle.extend(pile)
    room.game_state.deck.extend(cards_to_shuffle)
    room.game_state.table.clear()
    random.shuffle(room.game_state.deck)


def deal_cards(room: Room, count: int):
    """
    Deal a specified number of cards to each player.
    """
    if not room.game_state:
        return
    for _ in range(count):
        for player in room.players:
            if room.game_state.deck:
                card = room.game_state.deck.pop()
                player.hand.append(card)


def initialize_game_state(room_id: str, settings: dict, players: list[dict]) -> dict:
    """
    Initialize a new game state.
    """
    num_decks = settings.get("number_of_decks", 1)
    include_jokers = settings.get("include_jokers", False)
    initial_deck = create_deck(num_decks, include_jokers)
    random.shuffle(initial_deck) # Shuffle the newly created deck

    return {
        "room_id": room_id,
        "status": "active",
        "players": players,
        "deck": [card.model_dump() for card in initial_deck], # Convert Card objects to dicts
        "table": [],
        "discard_pile": [],
        "current_turn": 0,
    }

def draw_card(room: Room, player_index: int):
    """
    Draw one card from the deck to a player's hand.
    """
    if not room.game_state or not room.game_state.deck:
        return
    player = room.players[player_index]
    card = room.game_state.deck.pop()
    player.hand.append(card)

def draw_to_discard(room: Room):
    """
    Draw one card from the deck to the discard pile.
    """
    if not room.game_state or not room.game_state.deck:
        return
    card = room.game_state.deck.pop()
    room.game_state.discard_pile.append(card)

def draw_from_discard(room: Room, player_index: int):
    """
    Draw one card from the discard pile to a player's hand.
    """
    if not room.game_state or not room.game_state.discard_pile:
        return
    player = room.players[player_index]
    card = room.game_state.discard_pile.pop()
    player.hand.append(card)