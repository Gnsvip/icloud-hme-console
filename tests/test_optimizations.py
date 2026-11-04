import concurrent.futures
import json
import queue
import socket
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from inventory_manager import InventoryManager
from imap_runtime import MailExecutor, open_imap, wait_for_mail


def test_inventory_atomic_failure_preserves_remarks(tmp_path):
    inv = InventoryManager(tmp_path / "inventory.json")
    inv.update_item("one@icloud.com", remark="keep this")
    before = inv.path.read_bytes()
    with patch("inventory_manager.os.replace", side_effect=OSError("disk failure")):
        with pytest.raises(OSError):
            inv.update_item("one@icloud.com", remark="new")
    assert inv.path.read_bytes() == before
    assert inv.load()["items"]["one@icloud.com"]["remark"] == "keep this"
    assert not list(tmp_path.glob(".inventory-*"))


def test_inventory_corruption_blocks_sync_without_overwriting(tmp_path):
    inv = InventoryManager(tmp_path / "inventory.json")
    inv.update_item("one@icloud.com", remark="keep this")
    inv.path.write_text('{"items":', encoding="utf-8")
    with pytest.raises(RuntimeError, match="保留原文件"):
        inv.sync_aliases([{"email": "one@icloud.com"}])
    assert inv.path.read_text(encoding="utf-8") == '{"items":'


def test_inventory_concurrent_reads_and_writes_keep_every_record(tmp_path):
    inv = InventoryManager(tmp_path / "inventory.json")
    inv.update_item("seed@icloud.com", remark="seed")

    def write(i):
        inv.update_item(f"box{i}@icloud.com", remark=str(i))
        rows, _ = inv.list_items()
        assert any(row["email"] == "seed@icloud.com" for row in rows)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(40)))
    assert len(InventoryManager(inv.path).load()["items"]) == 41


def test_inventory_cached_queries_refresh_after_external_write(tmp_path):
    inv = InventoryManager(tmp_path / "inventory.json")
    inv.update_item("one@icloud.com", remark="before")
    with patch.object(inv, "_filter_items", wraps=inv._filter_items) as scan:
        inv.list_items(query="one")
        inv.list_items(query="one")
        assert scan.call_count == 1
        other = InventoryManager(inv.path)
        other.update_item("one@icloud.com", remark="after")
        rows, _ = inv.list_items(query="one")
        assert rows[0]["remark"] == "after"
        assert scan.call_count == 2


def test_logs_remain_bounded_and_keep_latest(tmp_path, monkeypatch):
    import app_core as core
    monkeypatch.setattr(core, "_log_queue", queue.Queue(maxsize=3))
    monkeypatch.setattr(core, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(core, "RUNTIME_LOG_FILE", tmp_path / "runtime.log")
    monkeypatch.setattr(core, "_last_log_cleanup", time.monotonic())
    for i in range(10):
        core._emit_log("info", str(i))
    assert core._log_queue.qsize() == 3
    assert [core._log_queue.get_nowait()["msg"] for _ in range(3)] == ["7", "8", "9"]
    assert len(core._read_runtime_logs()) == 10


def test_mail_deadline_closes_socket_and_releases_worker(monkeypatch):
    import imap_runtime
    left, right = socket.socketpair()
    conn = SimpleNamespace(sock=left, _command=lambda *args: None)
    monkeypatch.setattr(imap_runtime.imaplib, "IMAP4_SSL", lambda *a, **k: conn)
    executor = MailExecutor(1, 0, "deadline-test")
    started = threading.Event()

    def stalled():
        opened = open_imap("test.invalid")
        started.set()
        try:
            opened.sock.recv(1)
        except OSError:
            pass

    try:
        job = executor.submit(stalled, timeout=0.2)
        assert started.wait(1)
        with pytest.raises(TimeoutError):
            wait_for_mail(job)
        # The worker, not just its caller, must finish after cancellation.
        with pytest.raises(TimeoutError):
            job.result(timeout=1)
        assert wait_for_mail(executor.submit(lambda: "next")) == "next"
        assert left.fileno() == -1
    finally:
        right.close()
        left.close()
        executor.shutdown()


def test_mail_queue_rejects_excess_jobs_and_expired_work_never_starts():
    release, started = threading.Event(), threading.Event()
    executor = MailExecutor(1, 1, "queue-test")
    calls = []
    try:
        first = executor.submit(lambda: (started.set(), release.wait(2)), timeout=3)
        assert started.wait(1)
        expired = executor.submit(lambda: calls.append("ran"), timeout=0.02)
        with pytest.raises(RuntimeError, match="繁忙"):
            executor.submit(lambda: None)
        with pytest.raises(TimeoutError):
            wait_for_mail(expired)
        # Cancellation must not make room for unlimited dead queue entries.
        with pytest.raises(RuntimeError, match="繁忙"):
            executor.submit(lambda: None)
        release.set()
        wait_for_mail(first)
        assert calls == []
    finally:
        release.set()
        executor.shutdown()


def test_completed_mail_job_keeps_successful_result():
    executor = MailExecutor(1, 1, "completed-test")
    try:
        job = executor.submit(lambda: "done")
        assert job.result(timeout=1) == "done"
        assert wait_for_mail(job) == "done"
    finally:
        executor.shutdown()


def test_account_clients_disconnect_on_failure(monkeypatch):
    from account_manager import AccountManager
    mgr = AccountManager()
    client = Mock()
    client.check_inbox.side_effect = RuntimeError("offline")
    client.find_by_recipient.side_effect = RuntimeError("offline")
    monkeypatch.setattr(mgr, "get_mail_client", lambda _: client)
    monkeypatch.setattr(mgr._cache, "get_inbox", lambda _: [])
    monkeypatch.setattr(mgr._cache, "get_alias_mail", lambda *args: [])
    with pytest.raises(RuntimeError):
        mgr.check_inbox("one", force=True)
    with pytest.raises(RuntimeError):
        mgr.check_alias_mail("one", "box@icloud.com", force=True)
    assert client.disconnect.call_count == 2


def test_cache_limits_expiry_and_disk_reload(tmp_path, monkeypatch):
    import mail_cache as module
    monkeypatch.setattr(module, "CACHE_FILE", tmp_path / "cache.json")
    monkeypatch.setattr(module, "MAX_MESSAGE_BODIES", 2)
    monkeypatch.setattr(module, "MAX_ALIAS_MESSAGES", 2)
    monkeypatch.setattr(module, "MAX_ACCOUNT_ALIAS_MESSAGES", 3)
    cache = module.MailCache()
    cache.set_messages("one", {str(i): {"id": str(i), "body": "hello"} for i in range(5)})
    cache.set_alias_mail_batch("one", {f"a{i}@icloud.com": [{"id": str(j)} for j in range(4)] for i in range(2)})
    assert len(cache._data["one"]["message_bodies"]) == 2
    assert sum(len(rows) for rows in cache.get_all_alias_mail("one").values()) == 3
    assert all(len(rows) <= 2 for rows in cache.get_all_alias_mail("one").values())
    assert module.MailCache().get_message("one", "4")["body"] == "hello"
    later = time.time() + 31 * 86400
    with patch.object(module.time, "time", return_value=later):
        cache._cleanup()
        cache.set_message("one", "fresh", {"body": "new"})
    reloaded = module.MailCache()
    assert reloaded.get_message("one", "4") is None
    assert reloaded.get_message("one", "fresh")["body"] == "new"
    assert reloaded.get_all_alias_mail("one") == {}


def test_cache_byte_limit_and_corruption_protection(tmp_path, monkeypatch):
    import mail_cache as module
    monkeypatch.setattr(module, "CACHE_FILE", tmp_path / "cache.json")
    monkeypatch.setattr(module, "MAX_BODY_BYTES", 100)
    monkeypatch.setattr(module, "MAX_LIST_BYTES", 100)
    cache = module.MailCache()
    cache.set_messages("one", {"1": {"body": "x" * 1000}, "2": {"body": "ok"}})
    assert cache.get_message("one", "1") is None
    assert cache.get_message("one", "2")["body"] == "ok"
    cache.set_alias_mail("one", "box@icloud.com", [{"id": "1", "body": "x" * 1000}, {"id": "2", "body": "ok"}])
    assert [row["id"] for row in cache.get_alias_mail("one", "box@icloud.com")] == ["2"]
    module.CACHE_FILE.write_text("broken", encoding="utf-8")
    with pytest.raises(RuntimeError, match="保留原文件"):
        module.MailCache()
    assert module.CACHE_FILE.read_text(encoding="utf-8") == "broken"
