from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # App
    APP_ENV: str = "development"
    SECRET_KEY: str = "change-me"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://cricedge:cricedge@localhost:5432/cricedge"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Razorpay
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""

    # WhatsApp Business API
    WHATSAPP_API_TOKEN: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""

    # CORS
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000"]

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # External APIs
    CRICBUZZ_API_KEY: str = ""
    OPENWEATHER_API_KEY: str = ""
    TWITTER_BEARER_TOKEN: str = ""

    # Cricbuzz RapidAPI
    RAPIDAPI_KEY: str = ""
    RAPIDAPI_HOST: str = "cricbuzz-cricket.p.rapidapi.com"
    CRICBUZZ_MONTHLY_LIMIT: int = 200

    # IPL 2026 Constants
    IPL_2026_SERIES_ID: int = 9241

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
