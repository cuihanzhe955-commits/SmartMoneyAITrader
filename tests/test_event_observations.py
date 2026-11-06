import copy
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from events.observations import CaptureQuery, ObservationJournal
from terminal.api import create_app
from test_event_costs import service
from test_event_research import NOW

KEY = "12345678-1234-1234-1234-123456789012"


def query(**kw):
    return CaptureQuery(market_id="1", request_id=KEY, **kw)


def journal(tmp_path):
    return ObservationJournal(tmp_path / "terminal.db", service(), clock=lambda: NOW)


def test_append_only_snapshot_survives_restart_without_replacing_source_time(tmp_path):
    j = journal(tmp_path); result = j.capture(query())
    j = ObservationJournal(j.path, Mock(), clock=lambda: NOW + 9999)
    recovered = j.list()
    assert recovered["total"] == 1 and recovered["rows"][0]["snapshot"] == result["snapshot"]
    assert recovered["rows"][0]["snapshot"]["source_timestamp"] == NOW
    assert recovered["rows"][0]["environment"] == "research"
    assert not result["execution_enabled"] and not result["simulation_ready"]
    assert len(result["snapshot_sha256"]) == 64
    j.details.assert_not_called()


def test_retry_recovers_original_snapshot_without_external_fetch_even_when_expired(tmp_path):
    j = journal(tmp_path); first = j.capture(query())
    j = ObservationJournal(j.path, Mock(), clock=lambda: NOW + 9999)
    second = j.capture(query())
    assert second["duplicate"] and second["snapshot_sha256"] == first["snapshot_sha256"]
    assert second["captured_at"] == first["captured_at"]
    j.details.cost.assert_not_called()
    assert j.list()["total"] == 1


def test_idempotency_key_cannot_change_inputs(tmp_path):
    j = journal(tmp_path); j.capture(query())
    with pytest.raises(ValueError, match="其他参数"):
        j.capture(query(budget=20))
    assert j.list()["total"] == 1


def test_network_failure_does_not_create_successful_or_partial_records(tmp_path):
    j = journal(tmp_path); j.details.cost = Mock(side_effect=ValueError("source unavailable"))
    with pytest.raises(ValueError, match="unavailable"): j.capture(query())
    assert j.list()["total"] == 0
    with sqlite3.connect(j.path) as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='event_research_observations'").fetchone()


@pytest.mark.parametrize("field,value",[("source_timestamp", NOW-30), ("source_timestamp", NOW+1),
    ("provider", "gate"), ("product", "spot"), ("market_id", "99"),
    ("execution_enabled", True), ("simulation_ready", True)])
def test_invalid_or_stale_snapshots_are_not_persisted(tmp_path, field, value):
    j = journal(tmp_path); data = j.details.cost(query()); data[field] = value
    j.details.cost = Mock(return_value=data)
    with pytest.raises(ValueError, match="未保存"): j.capture(query())
    assert j.list()["total"] == 0


def test_data_checksum_detects_corruption_and_does_not_silently_repair(tmp_path):
    j = journal(tmp_path); j.capture(query())
    with sqlite3.connect(j.path) as db:
        db.execute("UPDATE event_research_observations SET data='{}'")
    with pytest.raises(ValueError, match="校验失败"): j.list()
    with pytest.raises(ValueError, match="校验失败"): j.capture(query())


def test_existing_tables_and_rows_are_preserved_and_list_is_bounded(tmp_path):
    j = journal(tmp_path)
    with sqlite3.connect(j.path) as db:
        db.execute("CREATE TABLE existing_spot(data TEXT)"); db.execute("INSERT INTO existing_spot VALUES('keep')")
    assert j.list()["total"] == 0
    first = j.capture(query())
    second_query = query().model_copy(update={"request_id": "22345678-1234-1234-1234-123456789012"})
    j.capture(second_query)
    assert j.list(1)["total"] == 2 and len(j.list(1)["rows"]) == 1
    with sqlite3.connect(j.path) as db:
        assert db.execute("SELECT * FROM existing_spot").fetchall() == [("keep",)]
    for n in (0, 51, True):
        with pytest.raises(ValueError): j.list(n)


def test_busy_database_fails_cleanly_and_retry_does_not_duplicate(tmp_path):
    j = journal(tmp_path); j.capture(query())
    q = query().model_copy(update={"request_id": "22345678-1234-1234-1234-123456789012"})
    with sqlite3.connect(j.path) as locked:
        locked.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="数据库忙"): j.capture(q)
        locked.rollback()
    assert j.list()["total"] == 1
    assert not j.capture(q)["duplicate"]
    assert j.capture(q)["duplicate"] and j.list()["total"] == 2


@pytest.mark.parametrize("data",[dict(request_id="bad"), dict(request_id=KEY, execution_enabled=True),
    dict(request_id=KEY, snapshot={}), dict(request_id=KEY, provider="gate")])
def test_client_cannot_supply_snapshot_or_execution_authority(data):
    with pytest.raises(ValidationError): CaptureQuery(market_id="1", **data)


def test_api_saves_only_research_and_is_restored_with_same_runtime(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        app.state.event_observations.details = service(); app.state.event_observations.clock = lambda: NOW
        before = client.get("/api/state").json()
        assert client.get("/api/research/events/observations").json()["total"] == 0
        r = client.post("/api/research/events/observations", json=query().model_dump())
        assert r.status_code == 200 and not r.json()["execution_enabled"]
        assert client.get("/api/state").json() == before
        for table in ("challenges", "simulated_orders", "fills", "positions"):
            assert app.state.rt.db.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert client.get("/api/research/events/observations?limit=51").status_code == 422
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/research/events/observations").json()["total"] == 1
        assert client.post("/api/research/events/observations", json=query().model_dump()).json()["duplicate"]


def test_concurrent_retries_commit_one_snapshot(tmp_path):
    j = journal(tmp_path); snapshot = j.details.cost(query()); barrier = threading.Barrier(2)
    def cost(_):
        barrier.wait(timeout=3)
        return copy.deepcopy(snapshot)
    j.details.cost = Mock(side_effect=cost)
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: j.capture(query()), range(2)))
    assert sorted(r["duplicate"] for r in results) == [False, True]
    assert j.list()["total"] == 1


def test_failed_transaction_rolls_back_and_retry_can_commit(tmp_path):
    j = journal(tmp_path); j.capture(query())
    q = query().model_copy(update={"request_id": "22345678-1234-1234-1234-123456789012"})
    with sqlite3.connect(j.path) as db:
        db.execute("CREATE TRIGGER fail_research BEFORE INSERT ON event_research_observations BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
    with pytest.raises(ValueError, match="暂不可用"): j.capture(q)
    assert j.list()["total"] == 1
    with sqlite3.connect(j.path) as db: db.execute("DROP TRIGGER fail_research")
    assert not j.capture(q)["duplicate"] and j.list()["total"] == 2


def test_slow_capture_does_not_take_runtime_lock_or_block_health(tmp_path):
    app = create_app(tmp_path); started = threading.Event(); release = threading.Event()
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as worker:
        j = app.state.event_observations; j.clock = lambda: NOW
        snapshot = service().cost(query())
        def cost(_):
            started.set(); assert release.wait(3)
            return snapshot
        j.details = Mock(); j.details.cost.side_effect = cost
        pending = worker.submit(client.post, "/api/research/events/observations", json=query().model_dump())
        try:
            assert started.wait(2)
            assert app.state.rt.lock.acquire(timeout=.2)
            app.state.rt.lock.release()
            assert client.get("/api/health").status_code == 200
        finally: release.set()
        assert pending.result(timeout=3).status_code == 200
