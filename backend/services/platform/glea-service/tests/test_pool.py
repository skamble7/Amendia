# tests/test_pool.py
"""Regression for the e2e blocker: a single shared clickhouse-connect client fails under concurrent
use ("Attempt to execute concurrent queries within the same session"). The pool must give each
concurrent operation its OWN client so the consumer's inserts and the read API never collide.

``FakeClient`` models the constraint: two overlapping calls on the SAME client raise the session error.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from app.clickhouse.client import StorageUnavailable
from app.clickhouse.provider import ClickHousePool


class SessionBusy(RuntimeError):
    """What clickhouse-connect raises when one session runs concurrent queries."""


class FakeClient:
    def __init__(self) -> None:
        self._active = 0
        self._lock = threading.Lock()
        self.calls = 0
        self.closed = False

    def _run(self) -> None:
        with self._lock:
            if self._active:  # a query is already in flight on THIS client → session collision
                raise SessionBusy("Attempt to execute concurrent queries within the same session.")
            self._active += 1
        try:
            time.sleep(0.02)  # widen the window so genuine overlap on a shared client is caught
            self.calls += 1
        finally:
            with self._lock:
                self._active -= 1

    def command(self, *a, **k):
        self._run()

    def insert(self, *a, **k):
        self._run()

    def query(self, *a, **k):
        self._run()
        return SimpleNamespace(column_names=["n"], result_rows=[[1]])

    def close(self):
        self.closed = True


def test_fake_models_shared_session_collision():
    """Sanity: the fake DOES collide when one client is used concurrently (the real bug)."""
    shared = FakeClient()
    barrier = threading.Barrier(6)
    errors: list[Exception] = []

    def use():
        barrier.wait()
        try:
            shared.query("x")
        except SessionBusy as exc:
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(lambda _: use(), range(6)))
    assert errors, "a shared client must collide under concurrency (models the e2e failure)"


def test_pool_gives_each_concurrent_op_its_own_client():
    """The fix: N concurrent inserts + concurrent reads never collide — the pool hands each its own
    client. Any shared-session/shared-client reuse would raise SessionBusy out of run_sync."""
    created: list[FakeClient] = []
    lock = threading.Lock()

    def factory() -> FakeClient:
        c = FakeClient()
        with lock:
            created.append(c)
        return c

    pool = ClickHousePool(connect_fn=factory, bootstrap_fn=lambda c: c.command("BOOT"))
    total = 20
    barrier = threading.Barrier(total)

    def op(i: int):
        barrier.wait()  # all fire at once → maximal concurrency
        if i % 5 == 0:
            pool.run_sync(lambda c: c.query("SELECT 1"))   # a read
        else:
            pool.run_sync(lambda c: c.insert("t", [[i]]))  # an insert

    with ThreadPoolExecutor(max_workers=total) as ex:
        futs = [ex.submit(op, i) for i in range(total)]
        for f in futs:
            f.result()  # re-raises SessionBusy if any client was used concurrently

    # Concurrency forced multiple distinct clients (a single shared one would have collided above).
    assert len(created) >= 2
    # No client leaked mid-use; idle ones are pooled (<= max_idle) or closed.
    assert all(c._active == 0 for c in created)


def test_bootstrap_runs_once_across_many_ops():
    boots: list[FakeClient] = []
    pool = ClickHousePool(connect_fn=FakeClient, bootstrap_fn=lambda c: boots.append(c))
    for _ in range(5):
        pool.run_sync(lambda c: c.query("x"))
    assert len(boots) == 1  # schema bootstrapped exactly once, then skipped


def test_failed_op_drops_the_client_and_propagates():
    made: list[FakeClient] = []
    pool = ClickHousePool(connect_fn=lambda: made.append(FakeClient()) or made[-1],
                          bootstrap_fn=lambda c: None)

    def boom(_c):
        raise StorageUnavailable("insert failed")

    with pytest.raises(StorageUnavailable):
        pool.run_sync(boom)
    assert made[0].closed is True  # a client that errored is closed, never returned to the pool
    pool.run_sync(lambda c: c.query("x"))
    assert len(made) == 2  # the next op builds a fresh client


def test_connect_failure_surfaces_storage_unavailable():
    def bad_connect():
        raise StorageUnavailable("clickhouse down")

    pool = ClickHousePool(connect_fn=bad_connect, bootstrap_fn=lambda c: None)
    with pytest.raises(StorageUnavailable):
        pool.run_sync(lambda c: None)


def test_pool_reuses_idle_clients_when_serial():
    made: list[FakeClient] = []
    pool = ClickHousePool(connect_fn=lambda: made.append(FakeClient()) or made[-1],
                          bootstrap_fn=lambda c: None, max_idle=4)
    for _ in range(10):
        pool.run_sync(lambda c: c.query("x"))  # serial → one client is borrowed + returned each time
    assert len(made) == 1  # no churn: the single idle client is reused
