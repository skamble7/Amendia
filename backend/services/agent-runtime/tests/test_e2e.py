# tests/test_e2e.py
"""End-to-end acceptance test against the running docker-compose stack.

Marked ``integration`` and auto-skipped when the stack is unreachable, so the
default unit run stays hermetic. Run the stack first:
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

ROLE_USER = {
    "role.payments.ops_analyst": "analyst-1",
    "role.payments.ops_approver": "approver-1",
}


def _reachable() -> bool:
    for base in (STUB, INGESTOR, RUNTIME):
        try:
            httpx.get(f"{base}/health", timeout=1.0)
        except Exception:  # noqa: BLE001
            return False
    return True


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _reachable(), reason="docker-compose stack not reachable"),
]


def _generate(reason_code: str) -> str:
    r = httpx.post(f"{STUB}/exceptions/generate",
                   json={"reason_code": reason_code, "count": 1}, timeout=10)
    r.raise_for_status()
    return r.json()["created"][0]["exception"]["exception_id"]


def _poll(url: str, pred, *, timeout=90):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            resp = httpx.get(url, timeout=5)
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
        inst = httpx.get(f"{RUNTIME}/instances/{pid}", timeout=5).json()
        if inst["status"] in ("completed", "failed"):
            return inst["status"]
        tasks = httpx.get(f"{RUNTIME}/hitl-tasks",
                          params={"status": "open", "process_instance_id": pid}, timeout=5).json()
        if not tasks:
            time.sleep(1)
            continue
        task = tasks[0]
        role = task["role"]
        user = ROLE_USER.get(role, "user-x")
        decision = "complete" if task["hitl_mode"] == "manual" else "approve"
        httpx.post(f"{RUNTIME}/hitl-tasks/{task['task_id']}/claim",
                   json={"user_id": user, "role": role}, timeout=5).raise_for_status()
        httpx.post(f"{RUNTIME}/hitl-tasks/{task['task_id']}/decide",
                   json={"user_id": user, "decision": decision}, timeout=5).raise_for_status()
    raise AssertionError("timed out resolving gates")


def test_ac01_end_to_end_completes():
    exc_id = _generate("AC01")
    ing = _poll(f"{INGESTOR}/ingestions/{exc_id}", lambda d: d.get("status") == "accepted")
    pid = ing["process_instance_id"]
    assert ing["resolution"]["pack_key"] == "wire-repair-standard"

    final = _resolve_all_gates(pid)
    assert final == "completed", f"instance ended {final}"

    detail = httpx.get(f"{RUNTIME}/instances/{pid}", timeout=5).json()
    assert detail["outcome"] == "End_Resolved"
    # the full expected actor_log sequence of human-decided gates
    human_elements = [e["element_id"] for e in detail["actor_log"] if e["kind"] == "human"]
    assert human_elements == [
        "Task_AssessRepairability", "Task_DraftRepair", "Task_ApproveRepair",
        "Task_SanctionsRescreen", "Task_ApplyRepair", "Task_NotifyParties",
    ]

    state = httpx.get(f"{RUNTIME}/instances/{pid}/state", timeout=5).json()
    assert set(state["artifacts"]) >= {"dossier", "beneficiary", "repair", "screening", "resolution"}

    # ingestion reflects accepted + the process instance id
    ing2 = httpx.get(f"{INGESTOR}/ingestions/{exc_id}", timeout=5).json()
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
               json={"user_id": "analyst-1", "role": first["role"]}, timeout=5).raise_for_status()
    httpx.post(f"{RUNTIME}/hitl-tasks/{first['task_id']}/decide",
               json={"user_id": "analyst-1", "decision": "approve"}, timeout=5).raise_for_status()

    second = _open_task()[0]
    assert second["element_id"] == "Task_ObtainInfo"
    assert second["hitl_mode"] == "manual"
