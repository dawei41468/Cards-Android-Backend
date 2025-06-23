"""
Main FastAPI application entry point.
"""
import logging
from contextlib import asynccontextmanager
import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.db.mongodb_utils import connect_to_mongo, close_mongo_connection
from app.websocket.handlers.connection_handlers import ConnectionHandlers
from app.websocket.handlers import game_handlers 
from app.websocket import setup_socketio

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Application Lifespan Management ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown events."""
    logger.info("Application startup: Connecting to MongoDB...")
    await connect_to_mongo()
    
    # Initialize ConnectionHandlers with the SIO server instance
    connection_handlers = ConnectionHandlers(sio)

    # Register connection and disconnection event handlers
    sio.on('connect', connection_handlers.handle_connect)
    sio.on('disconnect', connection_handlers.handle_disconnect)

    # Register custom game-related event handlers
    sio.on(ConnectionHandlers.EVENT_JOIN_GAME_ROOM, connection_handlers.handle_join_game_room)

    try:
        yield
    finally:
        logger.info("Application shutdown: Closing MongoDB connection...")
        await close_mongo_connection()

# --- Socket.IO Server Setup ---
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins="*",
    logger=True,
    engineio_logger=True
)

# Set up Socket.IO event handlers
setup_socketio(sio)

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
from app.api.v1.endpoints import auth as auth_router
from app.api.v1.endpoints import rooms as rooms_router

app.include_router(
    auth_router.router,
    prefix=f"{settings.API_V1_STR}/auth/guest",
    tags=["guest-auth"]
)

app.include_router(
    rooms_router.router,
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
