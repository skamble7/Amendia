# app/settings.py
from pydantic_settings import BaseSettings
from typing import List

class Settings(BaseSettings):
    # Service
    SERVICE_NAME: str = "notification-service"
    ENV: str = "dev"

    # RabbitMQ (topic exchange)
    RABBITMQ_URL: str = "amqp://raina:raina@rabbitmq:5672/"
    RABBITMQ_EXCHANGE: str = "raina.events"
    RABBITMQ_EXCHANGE_TYPE: str = "topic"

    # Durable queue for this service (survives restarts)
    RABBITMQ_QUEUE: str = "notification-service.v1"

    # Bind ONLY to versioned keys: <org>.<service>.<event>.v1
    RABBITMQ_BINDINGS: List[str] = [
        "*.workspace.*.v1",
        "*.artifact.*.v1",
        "*.discovery.*.v1",
        "*.learning.*.v1",
        "*.conductor.*.v1",
        "*.conductor.*.*.v1",
        "*.planner.*.v1",
        "*.planner.*.*.v1",
        "*.guidance.*.v1",
        "*.capability.*.v1",
        "*.notification.*.v1",
        "*.audit.*.v1",
        "*.error.*.v1",
    ]

    # WebSocket
    WS_PATH: str = "/ws"                 # e.g., ws://host:port/ws
    WS_ALLOW_ORIGINS: List[str] = ["*"]  # tighten in prod if needed

    # Optional replay buffer per workspace (not implemented in this snippet)
    BUFFER_SIZE_PER_WORKSPACE: int = 200

    class Config:
        env_file = ".env"

settings = Settings()
