# app/routers/messages.py
"""Inbound business-message intake (ADR-031 Phase 2.4).

Any source (external system, mcp_stub, operator, tests) POSTs a message; the runtime correlates it
by business anchor (exception_id / correlation_id) + message_name to a parked instance and resumes
it. Guarded by ``principal_or_internal`` — external callers use ``X-Amendia-Internal``; an operator
may use a bearer.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from amendia_auth import principal_or_internal

from app.deps import get_engine

router = APIRouter(prefix="/messages", tags=["messages"])


class MessageIn(BaseModel):
    message_name: str
    exception_id: Optional[str] = None
    correlation_id: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None


@router.post("", status_code=202)
async def post_message(body: MessageIn, _principal=Depends(principal_or_internal), engine=Depends(get_engine)):
    if body.exception_id is None and body.correlation_id is None:
        raise HTTPException(status_code=422, detail={
            "error": "anchor_required",
            "message": "exactly one business anchor (exception_id or correlation_id) is required"})
    if engine is None:
        raise HTTPException(status_code=503, detail="execution engine not available")
    result = await engine.deliver_message(
        body.message_name, exception_id=body.exception_id,
        correlation_id=body.correlation_id, payload=body.payload)
    status = result.get("status")
    if status == "delivered":
        return {"status": "delivered", "process_instance_id": result.get("process_instance_id")}
    if status == "already_consumed":
        raise HTTPException(status_code=409, detail={"error": "already_consumed"})
    if status == "invalid_payload":
        raise HTTPException(status_code=422, detail={"error": "invalid_payload", "message": result.get("detail")})
    raise HTTPException(status_code=404, detail={"error": "no_matching_subscription"})
