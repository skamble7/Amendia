# tests/test_e2e.py
"""End-to-end acceptance test against the running docker-compose stack.

Marked ``integration`` and auto-skipped when the stack is unreachable, so the
default unit run stays hermetic. Every call carries a real Keycloak bearer minted
via the dev-only CLI client; identity comes from the token (no {user_id, role}
body). Run the stack first:
    docker compose -f backend/deploy/docker-compose.yml up --build
then:  uv run --extra dev pytest -m integration
"""
from __future__ import annotations

import os
import time

import httpx
import pytest

STUB = os.getenv("STUB", "http://localhost:8081")
INGESTOR = os.getenv("INGESTOR", "http://localhost:8082")
RUNTIME = os.getenv("RUNTIME", "http://localhost:8083")
KEYCLOAK = os.getenv("KEYCLOAK", "http://localhost:8087")
REALM = os.getenv("REALM", "amendia-dev")
CLI_CLIENT = os.getenv("CLI_CLIENT", "amendia-dev-cli")
CLI_SECRET = os.getenv("CLI_SECRET", "dev-cli-secret")
DEV_PASSWORD = os.getenv("DEV_PASSWORD", "dev-password")

# Keycloak persona per Amendia role (roles are seeded/attached on first login).
USER_FOR_ROLE = {
    "role.payments.ops_analyst": "riya",
    "role.payments.ops_approver": "marcus",
}

_TOKENS: dict[str, str] = {}


def _token(username: str) -> str:
    if username not in _TOKENS:
        r = httpx.post(
            f"{KEYCLOAK}/realms/{REALM}/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": CLI_CLIENT,
                "client_secret": CLI_SECRET,
                "username": username,
                "password": DEV_PASSWORD,
                "scope": "openid",
            },
            timeout=10,
        )
        r.raise_for_status()
        _TOKENS[username] = r.json()["access_token"]
    return _TOKENS[username]


def _auth(username: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(username)}"}


def _reachable() -> bool:
    for base in (STUB, INGESTOR, RUNTIME):
        try:
            httpx.get(f"{base}/health", timeout=1.0)
        except Exception:  # noqa: BLE001
            return False
    try:
        httpx.get(f"{KEYCLOAK}/realms/{REALM}/.well-known/openid-configuration", timeout=1.0)
    except Exception:  # noqa: BLE001
        return False
    return True


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _reachable(), reason="docker-compose stack (incl. Keycloak) not reachable"),
]


def _generate(reason_code: str) -> str:
    r = httpx.post(f"{STUB}/exceptions/generate",
                   json={"reason_code": reason_code, "count": 1}, headers=_auth("riya"), timeout=10)
    r.raise_for_status()
    return r.json()["created"][0]["exception"]["exception_id"]


def _poll(url: str, pred, *, timeout=90):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            resp = httpx.get(url, headers=_auth("riya"), timeout=5)
            if resp.status_code == 200:
                last = resp.json()
                if pred(last):
                    return last
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1)
    raise AssertionError(f"timeout polling {url} (last={last})")


def _resolve_all_gates(pid: str, *, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        inst = httpx.get(f"{RUNTIME}/instances/{pid}", headers=_auth("riya"), timeout=5).json()
        if inst["status"] in ("completed", "failed"):
            return inst["status"]
        tasks = httpx.get(f"{RUNTIME}/hitl-tasks", headers=_auth("riya"),
                          params={"status": "open", "process_instance_id": pid}, timeout=5).json()
        if not tasks:
            time.sleep(1)
            continue
        task = tasks[0]
        who = USER_FOR_ROLE.get(task["role"], "riya")
        decision = "complete" if task["hitl_mode"] == "manual" else "approve"
        # Identity comes from the bearer — claim has no body, decide carries only the decision.
        httpx.post(f"{RUNTIME}/hitl-tasks/{task['task_id']}/claim",
                   headers=_auth(who), timeout=5).raise_for_status()
        httpx.post(f"{RUNTIME}/hitl-tasks/{task['task_id']}/decide",
                   json={"decision": decision}, headers=_auth(who), timeout=5).raise_for_status()
    raise AssertionError("timed out resolving gates")


def test_ac01_end_to_end_completes():
    exc_id = _generate("AC01")
    ing = _poll(f"{INGESTOR}/ingestions/{exc_id}", lambda d: d.get("status") == "accepted")
    pid = ing["process_instance_id"]
    assert ing["resolution"]["pack_key"] == "wire-repair-standard"

    final = _resolve_all_gates(pid)
    assert final == "completed", f"instance ended {final}"

    detail = httpx.get(f"{RUNTIME}/instances/{pid}", headers=_auth("riya"), timeout=5).json()
    assert detail["outcome"] == "End_Resolved"
    # the full expected actor_log sequence of human-decided gates
    human_elements = [e["element_id"] for e in detail["actor_log"] if e["kind"] == "human"]
    assert human_elements == [
        "Task_AssessRepairability", "Task_DraftRepair", "Task_ApproveRepair",
        "Task_SanctionsRescreen", "Task_ApplyRepair", "Task_NotifyParties",
    ]
    # decisions are recorded against Amendia user ids (usr-…), never the raw persona name.
    human_actors = {e["actor"] for e in detail["actor_log"] if e["kind"] == "human"}
    assert all(a.startswith("usr-") for a in human_actors), human_actors

    state = httpx.get(f"{RUNTIME}/instances/{pid}/state", headers=_auth("riya"), timeout=5).json()
    assert set(state["artifacts"]) >= {"dossier", "beneficiary", "repair", "screening", "resolution"}

    # ingestion reflects accepted + the process instance id
    ing2 = httpx.get(f"{INGESTOR}/ingestions/{exc_id}", headers=_auth("riya"), timeout=5).json()
    assert ing2["status"] == "accepted"
    assert ing2["process_instance_id"] == pid


def test_be04_reaches_obtain_info_manual_task():
    exc_id = _generate("BE04")
    ing = _poll(f"{INGESTOR}/ingestions/{exc_id}", lambda d: d.get("status") == "accepted")
    pid = ing["process_instance_id"]

    # approve the first (assess) gate, then the flow must park at the ObtainInfo manual task
    def _open_task():
        return _poll(
            f"{RUNTIME}/hitl-tasks?status=open&process_instance_id={pid}",
            lambda tasks: len(tasks) > 0,
        )

    first = _open_task()[0]
    assert first["element_id"] == "Task_AssessRepairability"
    httpx.post(f"{RUNTIME}/hitl-tasks/{first['task_id']}/claim",
               headers=_auth("riya"), timeout=5).raise_for_status()
    httpx.post(f"{RUNTIME}/hitl-tasks/{first['task_id']}/decide",
               json={"decision": "approve"}, headers=_auth("riya"), timeout=5).raise_for_status()

    second = _open_task()[0]
    assert second["element_id"] == "Task_ObtainInfo"
    assert second["hitl_mode"] == "manual"
