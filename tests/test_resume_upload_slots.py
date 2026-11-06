"""Saved-resume limits include concurrent uploads, not only completed ones."""

import asyncio
import io
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import Headers, UploadFile
from starlette.requests import Request

import api.store as store_module
from api import db
from api.auth import CurrentUser, get_optional_user
from api.config import settings
from api.errors import ApiError
from api.main import app
from api.routes import resumes as routes
from api.store import Store
from engine.normalize.parser import (
    DecompressionLimitError,
    ParserConcurrencyError,
    ParserTimeoutError,
)
from engine.normalize.schema import utcnow


@pytest.fixture
def upload_store(monkeypatch):
    isolated = Store()
    monkeypatch.setattr(store_module, "store", isolated)
    monkeypatch.setattr(routes, "store", isolated)
    monkeypatch.setattr(settings, "enforce_quotas", True)
    user = CurrentUser(id="slot-user", email="candidate@example.test")
    monkeypatch.setitem(app.dependency_overrides, get_optional_user, lambda: user)
    monkeypatch.setattr(routes, "parse_resume_bytes_async", AsyncMock(return_value="Resume text"))
    return isolated


def _upload(client):
    return client.post("/api/resumes", files={"file": ("resume.pdf", b"resume", "application/pdf")})


def test_simultaneous_uploads_cannot_bypass_free_plan(upload_store, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    calls = []

    async def slow_parse(*args):
        calls.append(args)
        entered.set()
        assert await asyncio.to_thread(release.wait, 5)
        return "Resume text"

    monkeypatch.setattr(routes, "parse_resume_bytes_async", slow_parse)
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=4) as pool:
        first = pool.submit(_upload, client)
        try:
            assert entered.wait(5)
            others = [pool.submit(_upload, client) for _ in range(3)]
            for future in others:
                response = future.result(timeout=5)
                assert response.status_code == 402
                assert response.json()["detail"]["kind"] == "saved_resumes"
        finally:
            release.set()
        assert first.result(timeout=5).status_code == 200
        assert _upload(client).status_code == 402
    assert len(calls) == 1
    assert len(upload_store.resumes) == 1
    assert not upload_store._resume_slots


@pytest.mark.parametrize("error,status", [
    (ParserTimeoutError("timeout"), 422),
    (ParserConcurrencyError("busy"), 429),
    (DecompressionLimitError("too large"), 413),
    (ValueError("invalid document"), 422),
])
def test_failed_parse_releases_slot_for_retry(upload_store, monkeypatch, error, status):
    parser = AsyncMock(side_effect=[error, "Valid resume"])
    monkeypatch.setattr(routes, "parse_resume_bytes_async", parser)
    with TestClient(app) as client:
        assert _upload(client).status_code == status
        assert not upload_store._resume_slots
        assert not upload_store.resumes
        assert _upload(client).status_code == 200
    assert len(upload_store.resumes) == 1


def test_save_failure_releases_slot_for_retry(upload_store, monkeypatch):
    original = upload_store.add_resume
    save = MagicMock(side_effect=db.DatabasePersistenceError("synthetic failure"))
    monkeypatch.setattr(upload_store, "add_resume", save)
    with TestClient(app) as client:
        response = _upload(client)
        assert response.status_code == 503
        assert not upload_store._resume_slots
        assert not upload_store.resumes
        monkeypatch.setattr(upload_store, "add_resume", original)
        assert _upload(client).status_code == 200


def test_canceled_parse_releases_slot(upload_store, monkeypatch):
    async def scenario():
        entered = asyncio.Event()

        async def wait_forever(*args):
            entered.set()
            await asyncio.Future()

        monkeypatch.setattr(routes, "parse_resume_bytes_async", wait_forever)
        request = Request({"type": "http", "client": ("127.0.0.1", 1234), "headers": []})
        file = UploadFile(io.BytesIO(b"resume"), filename="resume.pdf", headers=Headers({"content-type": "application/pdf"}))
        task = asyncio.create_task(routes.upload_resume(request, file, CurrentUser(id="slot-user")))
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not upload_store._resume_slots
        assert not upload_store.resumes

    asyncio.run(scenario())


def test_offline_reservations_are_atomic():
    local = Store()
    with ThreadPoolExecutor(max_workers=8) as pool:
        slots = list(pool.map(lambda _: local.reserve_resume_slot("user", 1), range(8)))
    assert sum(slot is not None for slot in slots) == 1
    assert local.reserve_resume_slot("another-user", 1) is not None


def test_expired_or_released_slots_cannot_save_late():
    local = Store()
    expired = local.reserve_resume_slot("user", 1)
    assert expired
    local._resume_slots[expired] = ("user", utcnow() - timedelta(seconds=1))
    replacement = local.reserve_resume_slot("user", 1)
    assert replacement
    with pytest.raises(ApiError) as error:
        local.add_resume("resume.pdf", "application/pdf", 1, user_id="user", slot_id=expired)
    assert error.value.status_code == 409
    local.release_resume_slot("user", replacement)
    with pytest.raises(ApiError):
        local.add_resume("resume.pdf", "application/pdf", 1, user_id="user", slot_id=replacement)
    assert not local.resumes
    assert local.reserve_resume_slot("user", 1)


def test_slot_owner_is_checked_and_saved_resume_keeps_using_quota():
    local = Store()
    slot = local.reserve_resume_slot("owner", 1)
    local.release_resume_slot("another-user", slot)
    with pytest.raises(ApiError):
        local.add_resume("resume.pdf", "application/pdf", 1, user_id="another-user", slot_id=slot)
    record = local.add_resume("resume.pdf", "application/pdf", 1, user_id="owner", slot_id=slot)
    assert record.id == slot
    assert not local._resume_slots
    assert local.reserve_resume_slot("owner", 1) is None


@pytest.mark.parametrize("stage", ["reserve", "save", "release"])
@pytest.mark.parametrize("failure", ["exception", "malformed"])
def test_database_slot_failures_never_fall_back_to_memory(monkeypatch, stage, failure):
    client = MagicMock()
    monkeypatch.setattr(db, "get_supabase_client", lambda: client)
    monkeypatch.setattr(store_module, "get_supabase_client", lambda: client)
    if failure == "exception":
        client.rpc.return_value.execute.side_effect = RuntimeError("private provider details")
    else:
        client.rpc.return_value.execute.return_value.data = {"allowed": "true", "saved": "true"}
    local = Store()
    with pytest.raises(db.DatabasePersistenceError) as error:
        if stage == "reserve":
            local.reserve_resume_slot("user", 1)
        elif stage == "save":
            local.add_resume("resume.pdf", "application/pdf", 1, user_id="user", slot_id="slot")
        else:
            local.release_resume_slot("user", "slot")
    assert "private provider details" not in str(error.value)
    assert not local.resumes
    assert not local._resume_slots
    client.table.assert_not_called()


def test_separate_workers_use_database_reservations_and_atomic_save(monkeypatch):
    # Exercise the persistence contract; PostgreSQL locking lives in migration 006.
    client = MagicMock()
    monkeypatch.setattr(db, "get_supabase_client", lambda: client)
    monkeypatch.setattr(store_module, "get_supabase_client", lambda: client)
    client.rpc.return_value.execute.return_value.data = {"allowed": True}
    first, second = Store(), Store()
    slot = first.reserve_resume_slot("user", 1)
    assert client.rpc.call_args.args[0] == "reserve_resume_slot"
    assert client.rpc.call_args.args[1]["p_limit"] == 1
    client.rpc.return_value.execute.return_value.data = {"allowed": False}
    assert second.reserve_resume_slot("user", 1) is None
    client.rpc.return_value.execute.return_value.data = {"saved": True}
    record = second.add_resume("resume.pdf", "application/pdf", 6, raw_text="Resume", user_id="user", slot_id=slot)
    assert record.id == slot
    assert client.rpc.call_args.args == ("commit_resume_slot", {
        "p_user_id": "user", "p_slot_id": slot,
        "p_resume": {"filename": "resume.pdf", "content_type": "application/pdf", "size_bytes": 6,
                     "raw_text": "Resume", "normalized": None},
    })
    client.table.assert_not_called()
    assert not first._resume_slots and not second._resume_slots


def test_rejected_database_commit_never_caches_resume(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(db, "get_supabase_client", lambda: client)
    monkeypatch.setattr(store_module, "get_supabase_client", lambda: client)
    client.rpc.return_value.execute.return_value.data = {"saved": False}
    local = Store()
    with pytest.raises(ApiError) as error:
        local.add_resume("resume.pdf", "application/pdf", 1, user_id="user", slot_id="expired")
    assert error.value.status_code == 409
    assert not local.resumes
