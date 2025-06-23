# /Users/dawei/Coding/cardgame_backend/app/core/config.py

from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """
    Main settings for the application.
    Reads environment variables from a .env file or the system environment.
    """
    PROJECT_NAME: str = "CardGameApp Backend"
    API_V1_STR: str = "/api/v1"
    ALGORITHM: str = "HS256"
    
    # JWT Settings from your .env file
    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 # Default to 1 day

    # Database Settings from your .env file
    MONGO_URI: str
    MONGO_DB_NAME: str
    
    # CORS Settings
    CORS_ORIGINS: list[str] = ["*"]  # Default allows all origins in development
    
    # Debug Settings
    DEBUG: bool = False  # Controls debug mode and logging verbosity

    class Config:
        # This tells pydantic to load variables from a .env file
        env_file = ".env"
        env_file_encoding = "utf-8"
        # The path is relative to where you run the app, so we'll place .env in the root
        # For robustness, you could use an absolute path, but this is fine for now.

# Create a single, importable instance of the settings
settings = Settings()