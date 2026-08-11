import sqlite3
import threading
import time
from pathlib import Path

import api.task_manager as tm
from core.agent import RetryRecord, TaskRequest, TaskResult
from core.config import Config

TERMINAL = ("success", "failed", "needs_review", "cancelled")


def _config(tmp_path):
    return Config(
        concurrency=2,
        max_retries=3,
        workspaces_dir=str(tmp_path / "workspaces"),
        db_path=str(tmp_path / "tasks.db"),
    )


def _wait_terminal(manager, task_id, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = manager.get(task_id)
        if status and status.state in TERMINAL:
            return status
        time.sleep(0.01)
    return manager.get(task_id)


def test_submit_two_tasks_isolated_workdirs_and_persistence(tmp_path, monkeypatch):
    config = _config(tmp_path)
    seen = {}

    def fake_run_task(request, config, llm, rules, workdir, task_id):
        seen[task_id] = workdir
        Path(workdir).mkdir(parents=True, exist_ok=True)
        (Path(workdir) / "scenario.txt").write_text(request.script or "")
        if request.script == "a\n":
            return TaskResult(
                "success",
                [RetryRecord(1, 1, "boom", "E001", "diff-line")],
                None,
                {"message": "mission loaded OK"},
            )
        return TaskResult("failed", [], None, {"max_retries_exceeded": 3})

    monkeypatch.setattr(tm, "run_task", fake_run_task)
    manager = tm.TaskManager(config, llm=object(), rules={"rules": []})
    id1 = manager.submit(TaskRequest(script="a\n"))
    id2 = manager.submit(TaskRequest(script="b\n"))
    assert id1 != id2
    s1 = _wait_terminal(manager, id1)
    s2 = _wait_terminal(manager, id2)
    assert s1.state == "success"
    assert s2.state == "failed"
    assert s1.retries == [
        {"attempt": 1, "rc": 1, "stderr": "boom", "matched_rule": "E001", "diff": "diff-line"}
    ]
    assert len(seen) == 2
    workdirs = list(seen.values())
    assert len(set(str(w) for w in workdirs)) == 2
    for w in workdirs:
        assert (Path(w) / "scenario.txt").exists()
        assert str(Path(w).parent) == config.workspaces_dir
    conn = sqlite3.connect(config.db_path)
    rows = conn.execute("SELECT task_id, state FROM tasks").fetchall()
    conn.close()
    assert len(rows) == 2
    assert {r[1] for r in rows} == {"success", "failed"}


def test_cancel_marks_task_cancelled(tmp_path, monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def blocking_run_task(request, config, llm, rules, workdir, task_id):
        started.set()
        release.wait(10)
        return TaskResult("success", [], None, {"message": "ok"})

    monkeypatch.setattr(tm, "run_task", blocking_run_task)
    manager = tm.TaskManager(_config(tmp_path), llm=object(), rules={"rules": []})
    task_id = manager.submit(TaskRequest(script="a\n"))
    assert started.wait(5)
    assert manager.cancel(task_id) is True
    assert manager.get(task_id).state == "cancelled"
    assert manager.cancel(task_id) is False
    release.set()
    _wait_terminal(manager, task_id)
    assert manager.get(task_id).state == "cancelled"


def test_run_exception_marks_task_failed(tmp_path, monkeypatch):
    def exploding_run_task(request, config, llm, rules, workdir, task_id):
        raise RuntimeError("disk full")

    monkeypatch.setattr(tm, "run_task", exploding_run_task)
    manager = tm.TaskManager(_config(tmp_path), llm=object(), rules={"rules": []})
    task_id = manager.submit(TaskRequest(script="a\n"))
    status = _wait_terminal(manager, task_id)
    assert status.state == "failed"
    assert status.result.get("error") == "disk full"


def test_restart_recovers_stale_running_row(tmp_path):
    config = _config(tmp_path)
    tm.TaskManager(config, llm=object(), rules={"rules": []})
    conn = sqlite3.connect(config.db_path)
    conn.execute(
        "INSERT INTO tasks(task_id, state, created_at, updated_at, result) VALUES(?,?,?,?,?)",
        ("stale1", "running", "2024-01-01T00:00:00", "2024-01-01T00:00:00",
         '{"retries": [], "result": {}}'),
    )
    conn.commit()
    conn.close()
    restarted = tm.TaskManager(config, llm=object(), rules={"rules": []})
    recovered = restarted.get("stale1")
    assert recovered.state == "failed"
    assert "stale" in recovered.result.get("error", "")


def test_restart_recovers_persisted_state(tmp_path, monkeypatch):
    config = _config(tmp_path)

    def fake_run_task(request, config, llm, rules, workdir, task_id):
        Path(workdir).mkdir(parents=True, exist_ok=True)
        return TaskResult("failed", [], None, {"max_retries_exceeded": 3})

    monkeypatch.setattr(tm, "run_task", fake_run_task)
    manager = tm.TaskManager(config, llm=object(), rules={"rules": []})
    task_id = manager.submit(TaskRequest(script="a\n"))
    status = _wait_terminal(manager, task_id)
    assert status.state == "failed"
    restarted = tm.TaskManager(config, llm=object(), rules={"rules": []})
    recovered = restarted.get(task_id)
    assert recovered is not None
    assert recovered.task_id == task_id
    assert recovered.state == "failed"
    assert recovered.result == {"max_retries_exceeded": 3}
