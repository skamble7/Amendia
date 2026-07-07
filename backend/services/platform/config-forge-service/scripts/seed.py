"""
Seed script — loads default LLM config templates for all polyllm providers into ConfigForge.

Covers the four providers registered in polyllm's registry:
  openai, google_genai, bedrock, google_vertexai (placeholder — not yet active)

Each entry uses env:* api_key_ref refs so no real secrets are stored here.
Swap env:* for literal:* to store the key directly, or vault:* when Vault is wired in.

Usage:
    cd services/config-forge-service
    python scripts/seed.py [--env dev] [--mongo-uri mongodb://localhost:27017] [--db ConfigForge]
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

from motor.motor_asyncio import AsyncIOMotorClient


# ---------------------------------------------------------------------------
# Seed definitions
# Each dict maps to ConfigEntryCreate fields.
# ---------------------------------------------------------------------------

def build_ref(env: str, kind: str, provider: Optional[str], platform: Optional[str], name: str) -> str:
    segments = [env, kind]
    if provider:
        segments.append(provider)
    if platform:
        segments.append(platform)
    segments.append(name)
    return ".".join(segments)


def make_seeds(env: str) -> List[Dict[str, Any]]:
    return [
        # ── OpenAI ────────────────────────────────────────────────────────
        {
            "env": env,
            "kind": "llm",
            "provider": "openai",
            "platform": None,
            "name": "default",
            "description": "Default OpenAI GPT-4o config. Resolves key from OPENAI_API_KEY env var.",
            "data": {
                "provider": "openai",
                "model": "gpt-4o",
                "temperature": 0.1,
                "api_key_ref": "env:OPENAI_API_KEY",
            },
        },
        {
            "env": env,
            "kind": "llm",
            "provider": "openai",
            "platform": None,
            "name": "fast",
            "description": "Fast/low-cost OpenAI GPT-4o-mini variant for high-throughput tasks.",
            "data": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "temperature": 0.1,
                "max_tokens": 4096,
                "api_key_ref": "env:OPENAI_API_KEY",
            },
        },
        {
            "env": env,
            "kind": "llm",
            "provider": "openai",
            "platform": None,
            "name": "reasoning",
            "description": "OpenAI o3 reasoning model for complex multi-step tasks.",
            "data": {
                "provider": "openai",
                "model": "o3",
                "temperature": 1.0,
                "api_key_ref": "env:OPENAI_API_KEY",
            },
        },
        # ── OpenAI-compatible gateway (e.g. Azure OpenAI, LiteLLM, etc.) ─
        {
            "env": env,
            "kind": "llm",
            "provider": "openai",
            "platform": None,
            "name": "gateway",
            "description": (
                "OpenAI-compatible gateway profile. "
                "Set OPENAI_GATEWAY_URL and OPENAI_GATEWAY_KEY in your environment, "
                "then update base_url and api_key_ref accordingly."
            ),
            "data": {
                "provider": "openai",
                "model": "gpt-4o",
                "temperature": 0.1,
                "base_url": "https://your-gateway-host/v1",
                "api_key_ref": "env:OPENAI_GATEWAY_KEY",
            },
        },
        # ── Google GenAI (Gemini via API key) ─────────────────────────────
        {
            "env": env,
            "kind": "llm",
            "provider": "google_genai",
            "platform": None,
            "name": "default",
            "description": "Default Google Gemini 1.5 Pro config. Resolves key from GOOGLE_API_KEY env var.",
            "data": {
                "provider": "google_genai",
                "model": "gemini-1.5-pro",
                "temperature": 0.1,
                "api_key_ref": "env:GOOGLE_API_KEY",
            },
        },
        {
            "env": env,
            "kind": "llm",
            "provider": "google_genai",
            "platform": None,
            "name": "flash",
            "description": "Fast Gemini 1.5 Flash variant for low-latency tasks.",
            "data": {
                "provider": "google_genai",
                "model": "gemini-1.5-flash",
                "temperature": 0.1,
                "max_tokens": 4096,
                "api_key_ref": "env:GOOGLE_API_KEY",
            },
        },
        # ── AWS Bedrock (ambient IAM / named profile) ─────────────────────
        {
            "env": env,
            "kind": "llm",
            "provider": "bedrock",
            "platform": None,
            "name": "default",
            "description": (
                "AWS Bedrock Claude 3.5 Sonnet. "
                "Uses ambient IAM credentials (instance role, env vars, or default ~/.aws profile). "
                "Set aws_region to your deployment region."
            ),
            "data": {
                "provider": "bedrock",
                "transport": "bedrock",
                "model": "anthropic.claude-3-5-sonnet-20241022-v2:0",
                "temperature": 0.1,
                "aws_region": "us-east-1",
            },
        },
        {
            "env": env,
            "kind": "llm",
            "provider": "bedrock",
            "platform": None,
            "name": "named-profile",
            "description": (
                "AWS Bedrock using a named ~/.aws/credentials profile. "
                "Set aws_profile to the desired profile name."
            ),
            "data": {
                "provider": "bedrock",
                "transport": "bedrock",
                "model": "anthropic.claude-3-5-sonnet-20241022-v2:0",
                "temperature": 0.1,
                "aws_region": "us-east-1",
                "aws_profile": "default",
            },
        },
        {
            "env": env,
            "kind": "llm",
            "provider": "bedrock",
            "platform": None,
            "name": "explicit-creds",
            "description": (
                "AWS Bedrock with explicit IAM key credentials via secret_refs. "
                "Resolves access_key and secret_key from env vars."
            ),
            "data": {
                "provider": "bedrock",
                "transport": "bedrock",
                "model": "anthropic.claude-3-5-sonnet-20241022-v2:0",
                "temperature": 0.1,
                "aws_region": "us-east-1",
                "secret_refs": {
                    "access_key": "env:AWS_ACCESS_KEY_ID",
                    "secret_key": "env:AWS_SECRET_ACCESS_KEY",
                },
            },
        },
        # ── Google Vertex AI (placeholder — adapter not yet active) ───────
        {
            "env": env,
            "kind": "llm",
            "provider": "google_vertexai",
            "platform": None,
            "name": "default",
            "description": (
                "Google Vertex AI Gemini template. "
                "NOTE: the google_vertexai adapter is not yet enabled in polyllm. "
                "This entry is a placeholder to be activated once ADC/service-account "
                "handling is implemented in the adapter."
            ),
            "data": {
                "provider": "google_vertexai",
                "transport": "vertex",
                "model": "gemini-1.5-pro",
                "temperature": 0.1,
                "gcp_project": "your-gcp-project-id",
                "gcp_location": "us-central1",
            },
        },
    ]


# ---------------------------------------------------------------------------
# Upsert logic
# ---------------------------------------------------------------------------

async def seed(mongo_uri: str, db_name: str, env: str, dry_run: bool) -> None:
    client = AsyncIOMotorClient(mongo_uri)
    db = client[db_name]
    col = db["config_entries"]

    # Ensure unique index exists
    await col.create_index("ref", unique=True)

    seeds = make_seeds(env)
    created = skipped = 0

    for entry in seeds:
        ref = build_ref(
            entry["env"],
            entry["kind"],
            entry.get("provider"),
            entry.get("platform"),
            entry["name"],
        )
        entry["ref"] = ref

        existing = await col.find_one({"ref": ref})
        if existing:
            print(f"  SKIP  {ref}  (already exists)")
            skipped += 1
            continue

        if dry_run:
            print(f"  DRY   {ref}")
            created += 1
            continue

        now = datetime.now(timezone.utc)
        doc = {
            "_id": str(uuid.uuid4()),
            "ref": ref,
            "env": entry["env"],
            "kind": entry["kind"],
            "provider": entry.get("provider"),
            "platform": entry.get("platform"),
            "name": entry["name"],
            "description": entry.get("description"),
            "data": entry["data"],
            "created_by": "seed",
            "created_at": now,
            "updated_at": now,
        }
        await col.insert_one(doc)
        print(f"  OK    {ref}")
        created += 1

    client.close()
    action = "Would create" if dry_run else "Created"
    print(f"\n{action} {created} entr{'y' if created == 1 else 'ies'}, skipped {skipped}.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Seed ConfigForge with default LLM configs.")
    p.add_argument("--env", default="dev", help="Target env segment (default: dev)")
    p.add_argument("--mongo-uri", default="mongodb://localhost:27017", help="MongoDB connection URI")
    p.add_argument("--db", default="ConfigForge", help="MongoDB database name")
    p.add_argument("--dry-run", action="store_true", help="Print what would be created without writing")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    print(f"Seeding ConfigForge  env={args.env}  db={args.db}  dry_run={args.dry_run}\n")
    asyncio.run(seed(args.mongo_uri, args.db, args.env, args.dry_run))
    sys.exit(0)
