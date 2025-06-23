"""
WebSocket game action handlers for the card game.
"""
import logging
import random
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from app.websocket.base_handler import BaseWebSocketHandler
from app.models.room import Card, CardGameSpecificState, PlayerInRoom, Room, RoomResponse
from app.crud import crud_room

logger = logging.getLogger(__name__)

class GameHandlers(BaseWebSocketHandler):
    """Handlers for game-related WebSocket events."""
    
    async def handle_start_game(self, sid: str, data: Dict) -> None:
        """
        Handle game start request from room host.
        
        Args:
            sid: The session ID of the client
            data: Event data containing room_id
        """
        logger.info(f"start_game event from {sid} with data: {data}")
        
        try:
            # Get session and validate
            session = await self._get_validated_session(sid)
            guest_id = session['guest_id']
            
            # Validate input
            if not data or 'room_id' not in data:
                raise ValueError("Missing required fields: room_id")
                
            room_id = data['room_id']
            
            # Get room and validate
            room = await self._get_room(room_id)
            self._validate_host(room, guest_id)
            
            # Check if game can be started
            if room.status == 'playing':
                raise ValueError("Game already started")
                
            if len(room.players) < 2:
                raise ValueError("At least 2 players are required to start")
            
            # Initialize game state
            game_state = await self._initialize_game_state(room)
            
            # Update room with game state
            room.status = 'playing'
            room.game_state = game_state
            updated_room = await crud_room.update_room(room_id, room)
            
            # Prepare and broadcast response
            room_response = RoomResponse.model_validate(updated_room).model_dump(by_alias=True)
            await self.sio.emit('room_updated', room_response, room=room_id)
            logger.info(f"Game started in room {room_id}")
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error in start_game for sid {sid}: {error_msg}", exc_info=True)
            await self.sio.emit('start_game_failed', {
                'room_id': data.get('room_id') if data else None,
                'error': error_msg
            }, to=sid)
    
    async def handle_player_action(self, sid: str, data: Dict) -> None:
        """
        Handle player game actions.
        
        Args:
            sid: The session ID of the client
            data: Event data containing action details
        """
        logger.info(f"player_action event from {sid} with data: {data}")
        
        try:
            # Get session and validate
            session = await self._get_validated_session(sid)
            guest_id = session['guest_id']
            
            # Validate input
            if not data or 'room_id' not in data or 'action_type' not in data:
                raise ValueError("Missing required fields: room_id and action_type")
                
            room_id = data['room_id']
            action_type = data['action_type']
            action_data = data.get('action_data', {})
            
            # Get room and validate
            room = await self._get_room(room_id)
            self._validate_player_in_room(room, guest_id)
            
            if room.status != 'playing':
                raise ValueError("Game not in progress")
                
            # Process action
            if action_type == 'play_card':
                await self._handle_play_card(room, guest_id, action_data)
            elif action_type == 'draw_card':
                await self._handle_draw_card(room, guest_id)
            elif action_type == 'call_uno':
                await self._handle_call_uno(room, guest_id)
            elif action_type == 'end_turn':
                await self._handle_end_turn(room, guest_id)
            else:
                raise ValueError(f"Unknown action type: {action_type}")
            
            # Save updated room state
            updated_room = await crud_room.update_room(room_id, room)
            
            # Broadcast game state update
            room_response = RoomResponse.model_validate(updated_room).model_dump(by_alias=True)
            await self.sio.emit('game_state_update', room_response, room=room_id)
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error in player_action for sid {sid}: {error_msg}", exc_info=True)
            await self.sio.emit('player_action_failed', {
                'room_id': data.get('room_id') if data else None,
                'error': error_msg
            }, to=sid)
    
    async def _handle_play_card(self, room: Room, guest_id: str, action_data: Dict) -> None:
        """
        Handle play card action.
        
        Args:
            room: The room where the game is being played
            guest_id: ID of the player making the move
            action_data: Dictionary containing 'card' and optionally 'color' for wild cards
            
        Raises:
            ValueError: If the card cannot be played
        """
        game_state = room.game_state
        
        # Get player data
        player_idx, player = next(
            (i, p) for i, p in enumerate(game_state['players'])
            if p['guest_id'] == guest_id
        )
        
        # Get card data
        card_data = action_data.get('card')
        if not card_data:
            raise ValueError("No card provided")
            
        # Find the card in player's hand
        card = next(
            (c for c in player['hand'] 
             if c['color'] == card_data.get('color') 
             and c['value'] == card_data.get('value') 
             and c['type'] == card_data.get('type')),
            None
        )
        
        if not card:
            raise ValueError("Card not found in player's hand")
            
        # Validate the card can be played
        last_card = game_state['last_played_card']
        if last_card and not self._is_valid_play(card, last_card, game_state):
            raise ValueError("Invalid card play")
        
        # Handle special cards
        if card['type'] in ['wild', 'wild_draw_four']:
            if 'color' not in action_data or action_data['color'] not in ['red', 'blue', 'green', 'yellow']:
                raise ValueError("Color must be specified for wild cards")
            card['color'] = action_data['color']
        
        # Move card from player's hand to discard pile
        player['hand'].remove(card)
        game_state['discard_pile'].append(card)
        game_state['last_played_card'] = card
        player['has_played_card_this_turn'] = True
        
        # Handle card effects
        await self._handle_card_effect(room, guest_id, card)
        
        # Check for UNO
        if len(player['hand']) == 1 and not player['uno_called']:
            # Player didn't call UNO with one card - draw penalty
            await self._draw_cards(game_state, guest_id, 2)
            game_state['last_action_description'] += " but forgot to say UNO! Draw 2 cards."
        
        # Check for win
        if not player['hand']:
            game_state['winner'] = guest_id
            game_state['game_over'] = True
            game_state['last_action_description'] = f"{player['nickname']} wins the game!"
            room.status = 'finished'
    
    async def _handle_draw_card(self, room: Room, guest_id: str) -> None:
        """
        Handle draw card action.
        
        Args:
            room: The room where the game is being played
            guest_id: ID of the player drawing a card
            
        Raises:
            ValueError: If the player cannot draw a card
        """
        game_state = room.game_state
        
        # Get player data
        player = next(p for p in game_state['players'] if p['guest_id'] == guest_id)
        
        # Check if player has already drawn the maximum cards this turn
        if player['cards_drawn_this_turn'] >= 3:
            raise ValueError("Maximum cards drawn this turn")
        
        # Draw a card
        drawn_card = await self._draw_card(game_state)
        if not drawn_card:
            raise ValueError("No cards left to draw")
            
        player['hand'].append(drawn_card)
        player['cards_drawn_this_turn'] += 1
        
        # Update game state
        game_state['last_action'] = 'draw_card'
        game_state['last_action_player'] = guest_id
        game_state['last_action_description'] = f"{player['nickname']} drew a card"
    
    async def _handle_call_uno(self, room: Room, guest_id: str) -> None:
        """
        Handle UNO call action.
        
        Args:
            room: The room where the game is being played
            guest_id: ID of the player calling UNO
            
        Raises:
            ValueError: If the player cannot call UNO
        """
        game_state = room.game_state
        
        # Get player data
        player = next(p for p in game_state['players'] if p['guest_id'] == guest_id)
        
        # Check if player has 1 or 2 cards
        if len(player['hand']) not in [1, 2]:
            raise ValueError("You can only call UNO when you have 1 or 2 cards")
        
        # Mark UNO as called
        player['uno_called'] = True
        
        # Update game state
        game_state['last_action'] = 'call_uno'
        game_state['last_action_player'] = guest_id
        game_state['last_action_description'] = f"{player['nickname']} called UNO!"
    
    async def _handle_end_turn(self, room: Room, guest_id: str) -> None:
        """
        Handle end turn action.
        
        Args:
            room: The room where the game is being played
            guest_id: ID of the player ending their turn
            
        Raises:
            ValueError: If the player cannot end their turn
        """
        game_state = room.game_state
        
        # Get player data
        player = next(p for p in game_state['players'] if p['guest_id'] == guest_id)
        
        # Check if player has taken any action this turn
        if not player['has_played_card_this_turn'] and player['cards_drawn_this_turn'] < 1:
            raise ValueError("You must play a card or draw a card before ending your turn")
        
        # Reset player turn flags
        player['has_played_card_this_turn'] = False
        player['cards_drawn_this_turn'] = 0
        player['uno_called'] = False  # Reset UNO call for next turn
        
        # Move to next player
        await self._advance_to_next_player(game_state)
        
        # Update game state
        game_state['last_action'] = 'end_turn'
        game_state['last_action_player'] = guest_id
        game_state['last_action_description'] = f"{player['nickname']} ended their turn"
    
    async def _initialize_game_state(self, room: Room) -> Dict:
        """
        Initialize game state using the game service
        Args:
            room: The room to initialize game for
        Returns:
            Dict: The initialized game state
        """
        from app.services.game_service import initialize_game_state
        
        players = [{
            'id': p.guest_id,
            'name': p.name,
            'is_host': p.guest_id == room.host_id
        } for p in room.players]
        
        return initialize_game_state(
            room_id=str(room.id),
            settings={
                'num_decks': room.settings.num_decks,
                'include_jokers': room.settings.include_jokers
            },
            players=players
        )
    
    def _create_shuffled_deck(self) -> List[Dict]:
        """
        Create and return a shuffled deck of UNO cards.
        
        Returns:
            List[Dict]: A list of card dictionaries representing the shuffled deck
            with fields that match the Card model (id, suit, rank, color, value, type)
        """
        colors = ['red', 'blue', 'green', 'yellow']
        color_to_suit = {
            'red': 'H',    # Hearts
            'blue': 'C',   # Clubs
            'green': 'S',  # Spades
            'yellow': 'D'  # Diamonds
        }
        numbers = list(range(10)) + list(range(1, 10))  # 0-9, 1-9 (two of each except 0)
        specials = ['skip', 'reverse', 'draw_two'] * 2  # Two of each special card per color
        wilds = ['wild', 'wild_draw_four'] * 4  # Four of each wild card
        
        deck = []
        
        # Create numbered cards
        for color in colors:
            suit = color_to_suit[color]
            for number in numbers:
                card_value = str(number)
                deck.append({
                    'id': f"{suit}{card_value}",
                    'suit': suit,
                    'rank': card_value,
                    'color': color,
                    'value': card_value,
                    'type': 'number'
                })
        
        # Create special cards (skip, reverse, draw_two)
        for color in colors:
            suit = color_to_suit[color]
            for special in specials:
                deck.append({
                    'id': f"{suit}{special[0].upper()}",  # First letter of special
                    'suit': suit,
                    'rank': special.upper(),
                    'color': color,
                    'value': special,
                    'type': special
                })
        
        # Create wild cards (no color initially)
        for wild in wilds:
            deck.append({
                'id': f"W{wild[0].upper()}",  # W for wild, first letter of type
                'suit': 'W',
                'rank': wild.upper(),
                'color': 'black',
                'value': wild,
                'type': wild
            })
        
        # Shuffle the deck
        random.shuffle(deck)
        return deck
        
    async def _draw_card(self, game_state: Dict) -> Optional[Dict]:
        """
        Draw a card from the draw pile.
        
        Args:
            game_state: The current game state
            
        Returns:
            Optional[Dict]: The drawn card, or None if no cards are left
        """
        if not game_state['draw_pile']:
            # If draw pile is empty, shuffle discard pile (except top card) into draw pile
            if len(game_state['discard_pile']) <= 1:
                return None
                
            # Keep the top card in discard pile
            top_card = game_state['discard_pile'].pop()
            game_state['draw_pile'] = game_state['discard_pile']
            game_state['discard_pile'] = [top_card]
            random.shuffle(game_state['draw_pile'])
            
        if not game_state['draw_pile']:
            return None
            
        return game_state['draw_pile'].pop()
    
    def _is_valid_play(self, card: Dict, last_card: Dict, game_state: Dict) -> bool:
        """
        Check if a card can be played on top of the last played card.
        
        Args:
            card: The card to play
            last_card: The last played card
            game_state: The current game state
            
        Returns:
            bool: True if the card can be played, False otherwise
        """
        # Wild cards can always be played
        if card['type'] in ['wild', 'wild_draw_four']:
            return True
            
        # Match color or value/type
        if card['color'] == last_card['color']:
            return True
            
        if card['value'] == last_card['value'] and card['type'] == last_card['type']:
            return True
            
        # Special case for wild cards that have been assigned a color
        if last_card['type'] in ['wild', 'wild_draw_four'] and 'color' in last_card:
            return card['color'] == last_card['color']
            
        return False
    
    async def _handle_card_effect(self, room: Room, guest_id: str, card: Dict) -> None:
        """
        Handle the effect of a played card.
        
        Args:
            room: The room where the game is being played
            guest_id: ID of the player who played the card
            card: The card that was played
        """
        game_state = room.game_state
        player = next(p for p in game_state['players'] if p['guest_id'] == guest_id)
        
        # Handle special card effects
        if card['type'] == 'skip':
            await self._skip_next_player(game_state)
            game_state['last_action_description'] = f"{player['nickname']} played a skip card!"
            
        elif card['type'] == 'reverse':
            game_state['direction'] *= -1
            game_state['last_action_description'] = f"{player['nickname']} reversed the direction!"
            
        elif card['type'] == 'draw_two':
            next_player = await self._get_next_player(game_state)
            await self._draw_cards(game_state, next_player['guest_id'], 2)
            await self._skip_next_player(game_state)
            game_state['last_action_description'] = f"{player['nickname']} made you draw 2 cards!"
            
        elif card['type'] == 'wild_draw_four':
            next_player = await self._get_next_player(game_state)
            await self._draw_cards(game_state, next_player['guest_id'], 4)
            await self._skip_next_player(game_state)
            game_state['last_action_description'] = f"{player['nickname']} played Wild Draw Four!"
        else:
            game_state['last_action_description'] = f"{player['nickname']} played a {card['color']} {card['value']}"
    
    async def _skip_next_player(self, game_state: Dict) -> None:
        """
        Skip the next player's turn.
        
        Args:
            game_state: The current game state
        """
        await self._advance_to_next_player(game_state)
        game_state['last_action'] = 'skip'
    
    async def _advance_to_next_player(self, game_state: Dict) -> None:
        """
        Advance to the next player's turn.
        
        Args:
            game_state: The current game state
        """
        current_idx = next(
            i for i, p in enumerate(game_state['players'])
            if p['guest_id'] == game_state['current_player_id']
        )
        
        # Calculate next player index based on direction
        next_idx = (current_idx + game_state['direction']) % len(game_state['players'])
        game_state['current_player_id'] = game_state['players'][next_idx]['guest_id']
        game_state['current_player_index'] = next_idx
    
    async def _get_next_player(self, game_state: Dict) -> Dict:
        """
        Get the next player in turn order.
        
        Args:
            game_state: The current game state
            
        Returns:
            Dict: The next player's data
        """
        current_idx = game_state['current_player_index']
        next_idx = (current_idx + game_state['direction']) % len(game_state['players'])
        return game_state['players'][next_idx]
    
    async def _draw_cards(self, game_state: Dict, player_id: str, count: int) -> List[Dict]:
        """
        Draw multiple cards for a player.
        
        Args:
            game_state: The current game state
            player_id: ID of the player to draw cards for
            count: Number of cards to draw
            
        Returns:
            List[Dict]: List of drawn cards
        """
        player = next(p for p in game_state['players'] if p['guest_id'] == player_id)
        drawn_cards = []
        
        for _ in range(count):
            card = await self._draw_card(game_state)
            if card:
                player['hand'].append(card)
                drawn_cards.append(card)
                
        return drawn_cards
    
    async def _get_validated_session(self, sid: str) -> Dict:
        """Get and validate the session for a socket ID."""
        try:
            # Get the session
            session = await self.sio.get_session(sid)
            logger.debug(f"Session for {sid}: {session}")
            
            # Check if session exists and has required fields
            if not session:
                logger.error(f"No session found for SID: {sid}")
                raise ValueError("No session found")
                
            if 'guest_id' not in session:
                logger.error(f"Session missing 'guest_id' for SID: {sid}. Session: {session}")
                raise ValueError("Session missing required 'guest_id' field")
                
            return session
            
        except Exception as e:
            logger.error(f"Error validating session for SID {sid}: {str(e)}", exc_info=True)
            raise ValueError(f"Invalid session: {str(e)}")
    
    async def _get_room(self, room_id: str) -> Room:
        """Get a room by ID or raise an error if not found."""
        room = await crud_room.get_room_by_id(room_id)
        if not room:
            raise ValueError(f"Room not found with ID: {room_id}")
        return room
    
    def _validate_host(self, room: Room, guest_id: str) -> None:
        """Validate that the guest is the host of the room."""
        if room.host_id != guest_id:
            raise ValueError("Only the host can perform this action")
    
    def _validate_player_in_room(self, room: Room, guest_id: str) -> None:
        """Validate that the guest is a player in the room."""
        if not any(p.guest_id == guest_id for p in room.players):
            raise ValueError("You are not a player in this room")
    
    def _get_current_timestamp(self) -> str:
        """Get current UTC timestamp as ISO format string."""
        from datetime import datetime
        return datetime.utcnow().isoformat()
