from pydantic_settings import BaseSettings
import os
from dotenv import load_dotenv
from typing import Optional

# Explicitly load .env file
load_dotenv()

class Settings(BaseSettings):
    MONGODB_URI: str = "mongodb://localhost:27017"
    DATABASE_NAME: str = "sparsh_erp"
    SECRET_KEY: str = "your-secret-key-change-it-in-prod"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # Notification Config
    SMTP_SERVER: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USERNAME: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    
    MAYTAPI_PRODUCT_ID: Optional[str] = None
    MAYTAPI_PHONE_ID: Optional[str] = None
    MAYTAPI_TOKEN: Optional[str] = None

    # OpenAI
    OPENAI_API_KEY: Optional[str] = None

    # AWS
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_REGION: Optional[str] = None
    S3_BUCKET_NAME: Optional[str] = None

    model_config = {
        "env_file": ".env",
        "extra": "ignore"
    }

settings = Settings()
