from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.core.config import settings

class DataBase:
    """
    A simple class to hold the MongoDB client and database instances.
    This allows for easy access and management of the database connection throughout the application.
    """
    client: Optional[AsyncIOMotorClient] = None
    db: Optional[AsyncIOMotorDatabase] = None

# Global instance of the DataBase class to manage the MongoDB connection.
db = DataBase()

async def connect_to_mongo():
    """
    Establishes a connection to the MongoDB database using the URI and database name from settings.
    The connection is stored in the global `db` object.
    """
    if not settings.MONGO_URI or not settings.MONGO_DB_NAME:
        return

    db.client = AsyncIOMotorClient(str(settings.MONGO_URI))
    db.db = db.client[settings.MONGO_DB_NAME]
    
    try:
        # The ismaster command is cheap and does not require auth.
        # It is used here to confirm that the connection is active.
        await db.client.admin.command('ismaster')
    except Exception:
        # If connection fails, reset client and db to None
        db.client = None
        db.db = None


async def close_mongo_connection():
    """
    Closes the MongoDB client connection if it is open.
    """
    if db.client:
        db.client.close()

def get_database() -> Optional[AsyncIOMotorDatabase]:
    """
    Retrieves the active MongoDB database instance.
    
    Returns:
        Optional[AsyncIOMotorDatabase]: The MongoDB database instance if connected, otherwise None.
    """
    return db.db
