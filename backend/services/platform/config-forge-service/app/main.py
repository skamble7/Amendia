# app/main.py
import uvicorn
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from app.routers.config_routes import router as config_router
from app.config import settings
from app.logging_conf import *  # configure root logger
from app.db.mongodb import close_db

app = FastAPI(
    title="ConfigForge — Platform Config Registry",
    version="0.1.0",
    default_response_class=ORJSONResponse,
)

app.include_router(config_router)


@app.get("/healthz")
async def health():
    return {"status": "ok", "service": settings.SERVICE_NAME}


@app.on_event("shutdown")
async def shutdown_event():
    await close_db()


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=True,
    )
