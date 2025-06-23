"""
Game Service - Core game logic implementation
"""
from typing import List, Dict
import random
from datetime import datetime

from app.models.domain.card import Card, Suit, Rank


def generate_deck(deck_id: int = 0, num_decks: int = 1, include_jokers: bool = False) -> List[Dict]:
    """Generate one or more standard decks of cards"""
    deck = []
    suits = ['HEARTS', 'DIAMONDS', 'CLUBS', 'SPADES']
    ranks = ['ACE', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'JACK', 'QUEEN', 'KING']
    
    for _ in range(num_decks):
        for suit in suits:
            for rank in ranks:
                deck.append({
                    'deckId': deck_id,
                    'suit': suit,
                    'rank': rank
                })
        
        if include_jokers:
            deck.extend([{'deckId': deck_id, 'suit': 'JOKER', 'rank': 'JOKER'}] * 2)
    
    return deck


def shuffle_deck(deck: List[Dict]) -> List[Dict]:
    """Shuffle a deck of cards"""
    return random.sample(deck, len(deck))


def deal_cards(deck: List[Dict], players: List[str], cards_per_player: int = 7) -> tuple:
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


def initialize_game_state(room_id: str, settings: dict, players: List[dict]) -> dict:
    """
    Initialize a new game state with shuffled deck and dealt cards
    Args:
        room_id: Room identifier
        settings: Game settings (num_decks, include_jokers, etc)
        players: List of player dicts with id and name
    """
    deck = generate_deck(
        deck_id=0,
        num_decks=settings.get('num_decks', 1),
        include_jokers=settings.get('include_jokers', False)
    )
    shuffled_deck = shuffle_deck(deck)
    
    player_ids = [p['id'] for p in players]
    remaining_deck, player_hands = deal_cards(shuffled_deck, player_ids)
    
    return {
        'room_id': room_id,
        'status': 'STARTING',
        'settings': settings,
        'players': [{
            'id': p['id'],
            'name': p['name'],
            'is_host': p.get('is_host', False),
            'hand': player_hands[p['id']],
            'score': 0
        } for p in players],
        'deck': remaining_deck,
        'table_piles': {'main': []},
        'discard_pile': [],
        'current_player_turn': None,
        'turn_order': player_ids,
        'created_at': datetime.utcnow(),
        'updated_at': datetime.utcnow()
    }
