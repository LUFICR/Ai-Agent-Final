"""Tests for the StorageInterface implemented in M5 (GAP_ANALYSIS.md).

Covers: interface contract, atomic writes, file locking, concurrent
writers (threads and processes), and backward compatibility of the
legacy module-level functions used by every engine.
Run from the repo root:  python tests/test_storage_interface.py
"""

import json
import multiprocessing
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wellness_agent.utils import storage
from wellness_agent.utils.storage import (
    StorageInterface,
    JsonFileStorage,
    default_storage,
    load_json,
    save_json,
    now_iso,
    days_since,
    merge_dicts,
)

FAILURES = []


def check(name, fn):
    try:
        fn()
        print("PASS  %s" % name)
    except Exception as e:  # noqa: BLE001
        FAILURES.append((name, e))
        print("FAIL  %s: %s" % (name, e))


def test_interface_contract():
    assert issubclass(JsonFileStorage, StorageInterface)
    assert isinstance(default_storage, StorageInterface)
    try:
        StorageInterface()
        assert False, "StorageInterface is abstract and must not instantiate"
    except TypeError:
        pass


def test_missing_file_returns_empty_dict():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "nope.json"
        assert load_json(p) == {}
        assert default_storage.load(p) == {}
        assert not p.exists()


def test_roundtrip_preserves_data():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "user.json"
        data = {
            "name": "Alice",
            "scores": [1, 2, 3],
            "nested": {"a": {"b": "c"}},
            "unicode": "wellbeing \u2014 \u00e9\u00e8\u00ea",
        }
        result = save_json(p, data)
        assert Path(result) == p
        assert load_json(p) == data
        assert default_storage.load(p) == data


def test_unicode_written_literally():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "uni.json"
        save_json(p, {"emoji": "\u2764\ufe0f"})
        text = p.read_text(encoding="utf-8")
        assert "\u2764" in text, "unicode must be written literally, not \\u escaped"


def test_overwrite_replaces_fully():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "file.json"
        save_json(p, {"a": 1, "leftover": True})
        save_json(p, {"a": 2})
        assert load_json(p) == {"a": 2}, "second save must fully replace the first"


def test_save_creates_missing_parent_dirs():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "deep" / "nested" / "dir" / "file.json"
        save_json(p, {"x": 1})
        assert load_json(p) == {"x": 1}


def test_no_temp_files_left_behind():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "file.json"
        for i in range(5):
            save_json(p, {"i": i})
        leftovers = [f.name for f in Path(tmp).iterdir() if ".tmp" in f.name]
        assert leftovers == [], "atomic writes must clean up temp files: %s" % leftovers


def test_concurrent_thread_writers_lose_no_data():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "contended.json"
        n_threads, n_writes = 8, 15
        barrier = threading.Barrier(n_threads)
        errors = []

        def writer(w):
            try:
                barrier.wait()
                for i in range(n_writes):
                    save_json(p, {"writer": w, "seq": i, "payload": "x" * 2000})
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(w,)) for w in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, "writer errors: %s" % errors
        doc = load_json(p)
        assert isinstance(doc, dict)
        assert "writer" in doc and 0 <= doc["writer"] < n_threads
        assert 0 <= doc["seq"] < n_writes
        assert len(doc["payload"]) == 2000
        assert load_json(p) == doc, "repeated loads must agree"


def test_file_lock_blocks_second_holder():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "locked.json"
        save_json(p, {"v": 1})
        release = threading.Event()
        entered = threading.Event()

        def holder():
            with storage._FileLock(p):
                entered.set()
                release.wait(5)

        t = threading.Thread(target=holder)
        t.start()
        assert entered.wait(5), "first holder never acquired the lock"
        blocked = {"done": False}

        def contender():
            load_json(p)
            blocked["done"] = True

        t2 = threading.Thread(target=contender)
        t2.start()
        time.sleep(0.4)
        assert not blocked["done"], "second reader must block while lock is held"
        release.set()
        t.join(5)
        t2.join(5)
        assert blocked["done"], "reader must proceed after the lock is released"


def _child_writer(path, pid):
    for i in range(8):
        save_json(path, {"pid": pid, "seq": i, "payload": "y" * 500})


def test_concurrent_process_writers_lose_no_data():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "multi_proc.json"
        save_json(p, {"seed": True})
        ctx = multiprocessing.get_context("spawn")
        procs = [
            ctx.Process(target=_child_writer, args=(str(p), i))
            for i in range(4)
        ]
        for pr in procs:
            pr.start()
        for pr in procs:
            pr.join(60)
        for pr in procs:
            assert pr.exitcode == 0, "process %d failed with %s" % (pr.pid, pr.exitcode)
        doc = load_json(p)
        assert isinstance(doc, dict)
        assert "pid" in doc and doc["pid"] in range(4)
        assert 0 <= doc["seq"] < 8
        assert len(doc["payload"]) == 500
        assert load_json(p) == doc


def test_legacy_api_compat():
    assert callable(load_json) and callable(save_json)
    assert callable(now_iso) and callable(days_since) and callable(merge_dicts)
    assert isinstance(now_iso(), str)
    assert isinstance(days_since(now_iso()), int)
    assert merge_dicts({"a": {"x": 1}, "k": 1}, {"a": {"y": 2}, "k": 2}) == {
        "a": {"x": 1, "y": 2},
        "k": 2,
    }
    assert storage.default_storage is default_storage


def test_engine_imports_unchanged():
    import importlib

    for mod in (
        "wellness_agent.memory",
        "wellness_agent.orchestrator",
        "wellness_agent.learning",
        "wellness_agent.belief_engine",
        "wellness_agent.hypothesis_engine",
        "wellness_agent.conversation_judge",
    ):
        importlib.import_module(mod)


def main():
    checks = [
        ("interface contract", test_interface_contract),
        ("missing file -> {}", test_missing_file_returns_empty_dict),
        ("save/load roundtrip", test_roundtrip_preserves_data),
        ("unicode written literally", test_unicode_written_literally),
        ("overwrite fully replaces", test_overwrite_replaces_fully),
        ("save creates missing parents", test_save_creates_missing_parent_dirs),
        ("no temp files left behind", test_no_temp_files_left_behind),
        ("8 threads x 15 writes lose no data", test_concurrent_thread_writers_lose_no_data),
        ("file lock blocks second holder", test_file_lock_blocks_second_holder),
        ("4 processes x 8 writes lose no data", test_concurrent_process_writers_lose_no_data),
        ("legacy API compat", test_legacy_api_compat),
        ("engine imports unchanged", test_engine_imports_unchanged),
    ]
    for name, fn in checks:
        check(name, fn)
    print("-" * 60)
    if FAILURES:
        print("FAILED: %d of %d" % (len(FAILURES), len(checks)))
        sys.exit(1)
    print("OK: all %d tests passed" % len(checks))


if __name__ == "__main__":
    main()
