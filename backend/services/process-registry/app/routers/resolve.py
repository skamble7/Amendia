# app/routers/resolve.py
"""Triage resolution endpoint (the lookup the ingestor calls).

ADR-063 Phase 2: this single call is now discriminated. Close-schema classification runs FIRST (a registered
cohort's end-of-process message must not triage to a pack); otherwise it falls through to triage exactly as
before. Back-compat: the trigger path returns the unchanged ``ResolveResponse`` (now carrying ``kind:
"trigger"``), and a no-match is still a 404.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.deps import get_cohort_classifier, get_resolver
from app.models.registry import CohortCloseResponse, NoMatchResponse, ResolveRequest, ResolveResponse
from app.services.cohort_classifier import CohortClassifier
from app.services.resolver import ResolveService

router = APIRouter(tags=["resolve"])


@router.post("/resolve", response_model=ResolveResponse)
async def resolve(
    req: ResolveRequest,
    resolver: ResolveService = Depends(get_resolver),
    classifier: CohortClassifier = Depends(get_cohort_classifier),
):
    # 1) close-message classification first — a recognised end-of-process message must never triage to a pack.
    close = await classifier.classify(req.envelope)
    if close is not None:
        body = CohortCloseResponse(**close)
        return JSONResponse(status_code=200, content=body.model_dump(mode="json"))

    # 2) normal triage over active packs (unchanged).
    result, considered = await resolver.resolve(req.envelope)
    if result is None:
        body = NoMatchResponse(considered_packs=considered)
        return JSONResponse(status_code=404, content=body.model_dump(mode="json"))
    return result
