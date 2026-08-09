# src/pega_stub/app.py
"""The mock Pega orchestrator FastAPI app (ADR-063 cohort worked example — test/dev scaffolding).

Endpoints:
  POST /cases                  start a case (fires Segment A)
  POST /amendia/handback       what the MCP `notify_pega` calls; advances A → B → C → close
  GET  /cases, /cases/{id}     case state + history
  GET  /                       a tiny live status UI
  GET  /health
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import scenarios as S
from .config import settings
from .orchestrator import Orchestrator
from .registry_client import maybe_register_cohort_definition
from .store_client import StoreClient
from .ui import STATUS_PAGE

logger = logging.getLogger(__name__)


class StartCaseRequest(BaseModel):
    case_id: Optional[str] = None
    scenario: str


class HandbackRequest(BaseModel):
    case_id: str
    segment: Optional[str] = None
    event: Optional[str] = None
    result: Any = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = StoreClient(settings.trigger_store_url,
                        internal_token=settings.trigger_store_internal_token, source=settings.source)
    app.state.orchestrator = Orchestrator(submit=store.submit)
    await maybe_register_cohort_definition()  # flagged + fail-soft
    logger.info("pega_stub ready (trigger_store=%s)", settings.trigger_store_url)
    yield


def create_app() -> FastAPI:
    logging.basicConfig(level=settings.log_level)
    app = FastAPI(title="Amendia — Mock Pega Orchestrator", version="0.1.0", lifespan=lifespan)

    def orch(request: Request) -> Orchestrator:
        return request.app.state.orchestrator

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "trigger_store": settings.trigger_store_url}

    @app.get("/scenarios")
    async def scenarios() -> dict:
        return {"scenarios": sorted(S.SCENARIOS)}

    @app.post("/cases", status_code=201)
    async def start_case(body: StartCaseRequest, request: Request) -> dict:
        try:
            return await orch(request).start_case(body.scenario, body.case_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    @app.post("/amendia/handback")
    async def handback(body: HandbackRequest, request: Request) -> dict:
        case = await orch(request).handback(body.case_id, body.segment, body.result)
        if case is None:
            # Unknown case — benign (a handback with no matching case). 202 so the caller (fail-soft) is happy.
            logger.info("handback for unknown case %s — ignored", body.case_id)
            raise HTTPException(status_code=404, detail=f"unknown case '{body.case_id}'")
        return case

    @app.get("/cases")
    async def list_cases(request: Request) -> dict:
        return {"cases": orch(request).list()}

    @app.get("/cases/{case_id}")
    async def get_case(case_id: str, request: Request) -> dict:
        case = orch(request).get(case_id)
        if case is None:
            raise HTTPException(status_code=404, detail=f"unknown case '{case_id}'")
        return case

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return STATUS_PAGE

    return app


app = create_app()
