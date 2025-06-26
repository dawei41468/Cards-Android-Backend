"""
Game Logic - Core game logic implementation
"""
from typing import List, Dict, Any
import random
from datetime import datetime

from app.models.room import Card


def generate_deck(num_decks: int = 1, include_jokers: bool = False) -> List[Card]:
    """Generate one or more standard decks of cards"""
    deck = []
    suits = ['H', 'D', 'C', 'S']
    ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
    
    for _ in range(num_decks):
        for suit in suits:
            for rank in ranks:
                deck.append(Card(id=f'{suit}{rank}', suit=suit, rank=rank))
        
        if include_jokers:
            deck.extend([
                Card(id='JOKER1', suit='JOKER', rank='JOKER'),
                Card(id='JOKER2', suit='JOKER', rank='JOKER')
            ])
    
    return deck


def shuffle_deck(deck: List[Card]) -> List[Card]:
    """Shuffle a deck of cards"""
    random.shuffle(deck)
    return deck


def deal_cards(deck: List[Card], players: List[str], cards_per_player: int = 7) -> tuple:
    """
    Deal cards to players from the deck
    Returns:
        (updated_deck, player_hands)
    """
    player_hands = {player_id: [] for player_id in players}
    
    for _ in range(cards_per_player):
        for player_id in players:
            if deck:
                player_hands[player_id].append(deck.pop())
    
    return deck, player_hands


def initialize_game_state(room_id: str, settings: Dict[str, Any], players: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Initialize a new game state with shuffled deck and dealt cards
    Args:
        room_id: Room identifier
        settings: Game settings (num_decks, include_jokers, etc)
        players: List of player dicts with id and name
    """
    deck = generate_deck(
        num_decks=settings.get('number_of_decks', 1),
        include_jokers=settings.get('include_jokers', False)
    )
    shuffled_deck = shuffle_deck(deck)
    
    player_ids = [p['guest_id'] for p in players]
    remaining_deck, player_hands = deal_cards(shuffled_deck, player_ids)
    
    return {
        'status': 'active',
        'current_turn_guest_id': random.choice(player_ids),
        'turn_order': player_ids,
        'deck': remaining_deck,
        'player_hands': player_hands,
        'discard_pile': [],
        'last_action_description': 'Game started.'
    }