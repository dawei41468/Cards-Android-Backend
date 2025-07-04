from typing import List, Dict
"""
Core game logic for the card game.
"""
from app.models.room import Room, Card
import random
import uuid

def play_cards(room: Room, player_index: int, cards: list[Card]):
    """
    Moves specified cards from a player's hand to the game table.
    
    Args:
        room (Room): The current game room object.
        player_index (int): The index of the player performing the action.
        cards (list[Card]): The list of cards to play.
    """
    if not room.game_state:
        return
    player = room.players[player_index]
    for card in cards:
        if card in player.hand:
            player.hand.remove(card)
    room.game_state.table.append(cards)
    room.game_state.last_player_id = player.guest_id
    room.game_state.last_played_or_discarded_cards[player.guest_id] = cards

def discard_cards(room: Room, player_index: int, cards: list[Card]):
    """
    Moves specified cards from a player's hand to the discard pile.
    
    Args:
        room (Room): The current game room object.
        player_index (int): The index of the player performing the action.
        cards (list[Card]): The list of cards to discard.
    """
    if not room.game_state:
        return
    player = room.players[player_index]
    for card in cards:
        if card in player.hand:
            player.hand.remove(card)
            room.game_state.discard_pile.append(card)
    room.game_state.last_player_id = player.guest_id
    room.game_state.last_played_or_discarded_cards[player.guest_id] = cards

def recall_cards(room: Room, player_index: int):
    """
    Recalls the last played or discarded cards by a specific player from the table to their hand.
    
    Args:
        room (Room): The current game room object.
        player_index (int): The index of the player recalling cards.
    """
    if not room.game_state:
        return

    player = room.players[player_index]
    player_id = player.guest_id

    if room.game_state.last_player_id != player_id:
        return

    cards_to_recall = room.game_state.last_played_or_discarded_cards.get(player_id)

    if cards_to_recall:
        try:
            room.game_state.table.remove(cards_to_recall)
        except ValueError:
            pass

        player.hand.extend(cards_to_recall)
        room.game_state.last_played_or_discarded_cards.pop(player_id, None)
        room.game_state.last_player_id = None

def move_cards_to_player(room: Room, source_player_index: int, cards: List[Card], target_player_id: str):
    """
    Moves specified cards from one player's hand to another player's hand.
    
    Args:
        room (Room): The current game room object.
        source_player_index (int): The index of the player giving cards.
        cards (List[Card]): The list of cards to move.
        target_player_id (str): The ID of the player receiving cards.
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
    Creates a standard deck of cards based on the specified number of decks and joker inclusion.
    
    Args:
        num_decks (int): The number of standard 52-card decks to include.
        include_jokers (bool): Whether to include two jokers per deck.
        
    Returns:
        List[Card]: A list of Card objects representing the newly created deck.
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
    Shuffles the game deck, incorporating any cards currently on the table back into the deck.
    
    Args:
        room (Room): The current game room object.
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
    Deals a specified number of cards from the deck to each player in the room.
    
    Args:
        room (Room): The current game room object.
        count (int): The number of cards to deal to each player.
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
    Initializes a new game state for a room, including creating and shuffling a deck.
    
    Args:
        room_id (str): The ID of the room.
        settings (dict): Dictionary of game settings.
        players (list[dict]): List of player dictionaries.
        
    Returns:
        dict: The initialized game state dictionary.
    """
    num_decks = settings.get("number_of_decks", 1)
    include_jokers = settings.get("include_jokers", False)
    initial_deck = create_deck(num_decks, include_jokers)
    random.shuffle(initial_deck)

    return {
        "room_id": room_id,
        "status": "active",
        "players": players,
        "deck": [card.model_dump() for card in initial_deck],
        "table": [],
        "discard_pile": [],
        "current_turn": 0,
    }

def draw_card(room: Room, player_index: int):
    """
    Draws a single card from the deck and adds it to a player's hand.
    
    Args:
        room (Room): The current game room object.
        player_index (int): The index of the player drawing the card.
    """
    if not room.game_state or not room.game_state.deck:
        return
    player = room.players[player_index]
    card = room.game_state.deck.pop()
    player.hand.append(card)

def draw_to_discard(room: Room):
    """
    Draws a single card from the deck and places it directly into the discard pile.
    
    Args:
        room (Room): The current game room object.
    """
    if not room.game_state or not room.game_state.deck:
        return
    card = room.game_state.deck.pop()
    room.game_state.discard_pile.append(card)

def draw_from_discard(room: Room, player_index: int):
    """
    Draws the top card from the discard pile and adds it to a player's hand.
    
    Args:
        room (Room): The current game room object.
        player_index (int): The index of the player drawing the card.
    """
    if not room.game_state or not room.game_state.discard_pile:
        return
    player = room.players[player_index]
    card = room.game_state.discard_pile.pop()
    player.hand.append(card)