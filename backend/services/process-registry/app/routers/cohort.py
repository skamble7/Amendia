# app/routers/cohort.py
"""ADR-063 Phase 2 — cohort DEFINITION registration/query (registry-owned)."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from amendia_auth import require_roles

from app.dal.base import DuplicateError
from app.dal.cohort_def_repo import CohortDefinitionRepository
from app.deps import get_cohort_def_repo
from app.models.cohort import CohortDefinition, CohortDefinitionCreate

router = APIRouter(prefix="/cohort", tags=["cohort"])

# Definition authoring is process-owner only (mirrors pack authoring).
_OWNER = Depends(require_roles("role.process.owner"))


@router.post("/definitions", response_model=CohortDefinition, status_code=201, dependencies=[_OWNER])
async def register_definition(
    body: CohortDefinitionCreate, repo: CohortDefinitionRepository = Depends(get_cohort_def_repo)
):
    # The close schema must be a well-formed JSON Schema (it gates close-message recognition at /resolve).
    try:
        Draft202012Validator.check_schema(body.close_schema)
    except SchemaError as exc:
        raise HTTPException(status_code=422, detail=f"close_schema is not a valid JSON Schema: {exc.message}")
    if not body.close_correlation_path:
        raise HTTPException(status_code=422, detail="close_correlation_path is required")
    try:
        return await repo.insert(CohortDefinition(**body.model_dump()))
    except DuplicateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/definitions", response_model=List[CohortDefinition])
async def list_definitions(repo: CohortDefinitionRepository = Depends(get_cohort_def_repo)):
    return await repo.list()


@router.get("/definitions/{cohort_def_id}", response_model=CohortDefinition)
async def get_definition(cohort_def_id: str, repo: CohortDefinitionRepository = Depends(get_cohort_def_repo)):
    d = await repo.get(cohort_def_id)
    if d is None:
        raise HTTPException(status_code=404, detail=f"unknown cohort definition '{cohort_def_id}'")
    return d


@router.delete("/definitions/{cohort_def_id}", status_code=204, dependencies=[_OWNER])
async def delete_definition(cohort_def_id: str, repo: CohortDefinitionRepository = Depends(get_cohort_def_repo)):
    await repo.delete(cohort_def_id)  # idempotent
