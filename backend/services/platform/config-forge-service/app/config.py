# app/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB: str = "ConfigForge"

    # ADR-058 fast-follow: broker for the outbound ConfigRefResolvedEvent (governed audit).
    RABBITMQ_URL: str = "amqp://guest:guest@rabbitmq:5672/"

    SERVICE_NAME: str = "config-forge-service"
    PORT: int = 8040
    ENV: str = "local"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()  # type: ignore
