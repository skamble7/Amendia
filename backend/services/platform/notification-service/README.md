# notification-service

Consumes RAINA events from RabbitMQ (`raina.events` exchange, topic), and broadcasts them to WebSocket clients grouped by `(tenant_id, workspace_id)`.

## Run locally

```bash
export RABBITMQ_URL=amqp://guest:guest@localhost:5672/
uvicorn app.main:app --reload --port 8013
