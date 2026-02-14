"""
Sawa — Configuration via pydantic-settings
"""
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # Twilio
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_number: str = "whatsapp:+14155238886"

    # Database
    database_url: str = "postgresql+asyncpg://localhost/sawa"

    # Claude AI
    anthropic_api_key: str = ""

    # Security
    secret_key: str = "change-this-to-random-string"
    skip_twilio_validation: bool = False

    # App
    environment: str = "production"
    debug: bool = False
    port: int = 8000

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
