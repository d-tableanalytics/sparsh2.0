from pydantic_settings import BaseSettings
import os
from dotenv import load_dotenv
from typing import Optional

# Explicitly load .env file (check for both .env and env)
load_dotenv(".env")
load_dotenv("env")

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
    
    # Maytapi (deprecated — replaced by Meta WhatsApp Cloud API below)
    MAYTAPI_PRODUCT_ID: Optional[str] = None
    MAYTAPI_PHONE_ID: Optional[str] = None
    MAYTAPI_TOKEN: Optional[str] = None

    # WhatsApp Cloud API (Meta) — official Business Platform
    WHATSAPP_PHONE_NUMBER_ID: Optional[str] = None
    WHATSAPP_BUSINESS_ACCOUNT_ID: Optional[str] = None
    WHATSAPP_ACCESS_TOKEN: Optional[str] = None
    WHATSAPP_API_VERSION: str = "v21.0"
    # Local numbers stored without a country code get this prefixed (India = 91).
    WHATSAPP_DEFAULT_COUNTRY_CODE: str = "91"

    # OpenAI
    OPENAI_API_KEY: Optional[str] = None
    AUDIO_TRANSCRIPTION_MODEL: str = "gpt-4o-transcribe"
    AUDIO_DIARIZATION_MODEL: str = "gpt-4o-transcribe-diarize"
    AUDIO_ENRICHMENT_MODEL: str = "gpt-4o-mini"
    ENABLE_AUDIO_DIARIZATION: bool = True

    # AWS
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_REGION: Optional[str] = None
    S3_BUCKET_NAME: Optional[str] = None

    # ── TEMPORARY: keep accepting uploads while S3 is unreachable ──
    # OFF by default, and deliberately so. Turning it on makes an upload fall back to this
    # server's own disk when S3 refuses, which keeps a form working during an outage or a
    # credential rotation -- at the cost of putting candidate CVs (personal data) on a box
    # that is probably not backed up and definitely is not the system of record.
    #
    # Enable it for a demo or an incident, migrate with
    # `scripts/migrate_local_uploads_to_s3.py`, then turn it off again. Every fallback write
    # is logged at WARNING and every stored key is prefixed `local/`, so what landed here is
    # always countable -- see app/services/local_upload_store.py.
    LOCAL_UPLOAD_FALLBACK: bool = False
    LOCAL_UPLOAD_DIR: str = "var/uploads"
    # How long a link to a locally-stored file stays valid. Mirrors the S3 presign TTL, so
    # callers that hand a URL to a browser behave the same either way.
    LOCAL_UPLOAD_URL_TTL_SECONDS: int = 3600

    # Attachment storage (multi-modal assistant uploads).
    # ATTACHMENT_STORAGE_PROVIDER overrides AssistantConfig.STORAGE_PROVIDER when set
    # ("local" for dev, "s3" for prod). LOCAL_STORAGE_DIR is where the local
    # backend writes raw files (served back via the download route).
    ATTACHMENT_STORAGE_PROVIDER: Optional[str] = None
    LOCAL_STORAGE_DIR: str = "uploads/assistant"

    # Optional explicit ffmpeg location (used for audio/video transcription when
    # the binary isn't on the process PATH). Set either the full binary path or
    # the directory containing it.
    FFMPEG_BINARY: Optional[str] = None
    FFMPEG_DIR: Optional[str] = None

    model_config = {
        "env_file": ".env",
        "extra": "ignore"
    }

settings = Settings()
