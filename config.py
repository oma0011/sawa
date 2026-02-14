"""
Sawa — Configuration via pydantic-settings
"""
from pydantic_settings import BaseSettings
from pydantic import Field, model_validator


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

    @model_validator(mode="after")
    def fix_database_url(self):
        """Render provides postgresql://, we need postgresql+asyncpg://"""
        url = self.database_url
        if url.startswith("postgres://"):
            self.database_url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://") and "+asyncpg" not in url:
            self.database_url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return self


settings = Settings()
