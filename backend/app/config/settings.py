from pydantic_settings import BaseSettings
import os
from dotenv import load_dotenv

# Explicitly load .env file
load_dotenv()

class Settings(BaseSettings):
    MONGODB_URI: str = "mongodb://localhost:27017"
    DATABASE_NAME: str = "sparsh_erp"
    SECRET_KEY: str = "your-secret-key-change-it-in-prod"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    model_config = {
        "env_file": ".env",
        "extra": "ignore"
    }

settings = Settings()
