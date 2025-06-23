from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

class DataBase:
    client: AsyncIOMotorClient = None
    db: AsyncIOMotorDatabase = None

db = DataBase() # Global database object

async def connect_to_mongo():
    logger.info("Attempting to connect to MongoDB...")
    if not settings.MONGO_URI or not settings.MONGO_DB_NAME:
        logger.error("MONGO_URI or MONGO_DB_NAME not configured. Cannot connect to MongoDB.")
        # Depending on strictness, you might want to raise an exception here
        # or allow the app to run without DB for certain functionalities.
        # For now, we'll log and proceed, but DB operations will fail.
        return

    db.client = AsyncIOMotorClient(str(settings.MONGO_URI))
    db.db = db.client[settings.MONGO_DB_NAME] # Access the database
    
    try:
        # The ismaster command is cheap and does not require auth.
        await db.client.admin.command('ismaster')
        logger.info(f"Successfully connected to MongoDB. Database: {settings.MONGO_DB_NAME}")
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
        # Handle connection failure (e.g., by setting db.client and db.db to None or re-raising)
        db.client = None
        db.db = None


async def close_mongo_connection():
    if db.client:
        logger.info("Closing MongoDB connection...")
        db.client.close()
        logger.info("MongoDB connection closed.")

def get_database() -> AsyncIOMotorDatabase:
    """
    Returns the database instance. 
    Ensure connect_to_mongo has been called.
    """
    if db.db is None:
        # This might happen if connection failed or was never established
        logger.warning("Database not initialized. Call connect_to_mongo first or check connection.")
        # Optionally, raise an exception or try to connect here,
        # but typically connection is managed at app startup.
    return db.db
