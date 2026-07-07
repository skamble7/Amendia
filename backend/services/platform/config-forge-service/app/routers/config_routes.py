# app/routers/config_routes.py
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.db.mongodb import get_db
from app.dal.config_dal import (
    create_entry,
    get_entry_by_id,
    get_entry_by_ref,
    list_entries,
    update_entry,
    delete_entry,
)
from app.models.config_entry import ConfigEntry, ConfigEntryCreate, ConfigEntryUpdate

router = APIRouter(prefix="/config", tags=["config"])


@router.post("/", response_model=ConfigEntry, status_code=201)
async def create_config(payload: ConfigEntryCreate, db=Depends(get_db)):
    try:
        return await create_entry(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/", response_model=List[ConfigEntry])
async def list_configs(
    env: Optional[str] = Query(None),
    kind: Optional[str] = Query(None),
    provider: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    db=Depends(get_db),
):
    return await list_entries(db, env=env, kind=kind, provider=provider, platform=platform)


@router.get("/resolve/{ref:path}", response_model=ConfigEntry)
async def resolve_config(ref: str, db=Depends(get_db)):
    """Primary polyllm lookup endpoint — resolves a canonical ref to the full config entry."""
    entry = await get_entry_by_ref(db, ref)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Config not found: {ref}")
    return entry


@router.get("/{entry_id}", response_model=ConfigEntry)
async def get_config(entry_id: str, db=Depends(get_db)):
    entry = await get_entry_by_id(db, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Config entry not found")
    return entry


@router.put("/{entry_id}", response_model=ConfigEntry)
async def update_config(entry_id: str, patch: ConfigEntryUpdate, db=Depends(get_db)):
    entry = await update_entry(db, entry_id, patch)
    if not entry:
        raise HTTPException(status_code=404, detail="Config entry not found")
    return entry


@router.delete("/{entry_id}", status_code=204)
async def delete_config(entry_id: str, db=Depends(get_db)):
    ok = await delete_entry(db, entry_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Config entry not found")
    return None
