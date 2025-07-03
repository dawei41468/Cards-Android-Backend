"""
Main FastAPI application entry point.
"""
from contextlib import asynccontextmanager
import socketio
import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
import json
from app.db.mongodb_utils import connect_to_mongo, close_mongo_connection
from app.background.cleanup import clean_inactive_rooms
from app.websocket.game_event_handler import GameEventHandler
from app.websocket.manager import websocket_manager
from app.core.json_encoder import CustomJSONEncoder

# Custom JSON module for `python-socketio` to use `CustomJSONEncoder`.
# This ensures that custom Python objects (like Pydantic models) are correctly serialized to JSON.
class CustomJsonModule:
    def dumps(self, *args, **kwargs):
        kwargs['cls'] = CustomJSONEncoder
        return json.dumps(*args, **kwargs)

    def loads(self, *args, **kwargs):
        return json.loads(*args, **kwargs)

# Instance of the custom JSON module used by the Socket.IO server.
custom_json = CustomJsonModule()

# --- Background Task ---
async def run_cleanup_task():
    """Run the cleanup task periodically."""
    while True:
        await asyncio.sleep(60 * 15)  # Run every 15 minutes
        await clean_inactive_rooms()

# --- Application Lifespan Management ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown events."""
    await connect_to_mongo()
    
    # Set up the WebSocket manager with the SIO server instance
    websocket_manager.set_sio(sio)
    
    # Initialize ConnectionHandlers with the SIO server instance
    game_event_handler = GameEventHandler(sio)

    # Register connection and disconnection event handlers
    sio.on('connect', game_event_handler.handle_connect)
    sio.on('disconnect', game_event_handler.handle_disconnect)

    # Register custom game-related event handlers
    sio.on(game_event_handler.EVENT_JOIN_GAME_ROOM, game_event_handler.handle_join_game_room)
    sio.on(game_event_handler.EVENT_LEAVE_GAME_ROOM, game_event_handler.handle_leave_game_room)
    sio.on(game_event_handler.EVENT_START_GAME, game_event_handler.handle_start_game)
    sio.on(game_event_handler.EVENT_PLAYER_ACTION, game_event_handler.handle_player_action)

    # Start the background cleanup task
    cleanup_task = asyncio.create_task(run_cleanup_task())

    try:
        yield
    finally:
        cleanup_task.cancel()
        await close_mongo_connection()

# --- Socket.IO Server Setup ---
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins="*",
    logger=True,
    engineio_logger=True,
    json=custom_json
)

# --- FastAPI Application Setup ---
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Backend API for the Card Game Application",
    version="1.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# --- CORS Configuration ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Socket.IO app to FastAPI
app.mount("/socket.io", socketio.ASGIApp(sio, socketio_path=""))

# --- API Routers ---
from app.api.v1.endpoints import auth, rooms

app.include_router(
    auth.router,
    prefix=f"{settings.API_V1_STR}/auth",
    tags=["Authentication"]
)

app.include_router(
    rooms.router,
    prefix=f"{settings.API_V1_STR}/rooms",
    tags=["rooms"]
)

# --- Root Endpoint ---
@app.get("/", tags=["Root"])
async def root():
    """Root endpoint that indicates the service is running."""
    return {
        "message": f"{settings.PROJECT_NAME} is running!",
        "status": "healthy",
        "version": "1.0.0"
    }
