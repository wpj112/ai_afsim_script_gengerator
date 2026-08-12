import sqlite3
import threading
import time
from pathlib import Path

import pytest

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
                [RetryRecord(1, 1, "out", "boom", "E001", "diff-line")],
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
        {"attempt": 1, "rc": 1, "stdout": "out", "stderr": "boom", "matched_rule": "E001", "diff": "diff-line"}
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


def test_prompt_history_records_prompt_tasks_only(tmp_path, monkeypatch):
    config = _config(tmp_path)

    def fake_run_task(request, config, llm, rules, workdir, task_id):
        return TaskResult("success", [], None, {"message": "ok"})

    monkeypatch.setattr(tm, "run_task", fake_run_task)
    manager = tm.TaskManager(config, llm=object(), rules={"rules": []})
    prompt_id = manager.submit(TaskRequest(prompt="生成空战场景", options=["-es"]))
    manager.submit(TaskRequest(script="end_time 1 sec\n", options=["-es"]))
    _wait_terminal(manager, prompt_id)

    history = manager.list_prompt_history()
    assert len(history) == 1
    assert history[0].task_id == prompt_id
    assert history[0].prompt == "生成空战场景"
    assert history[0].options == ["-es"]
    assert history[0].state == "success"


def test_prompt_history_persists_after_restart(tmp_path, monkeypatch):
    config = _config(tmp_path)

    def fake_run_task(request, config, llm, rules, workdir, task_id):
        return TaskResult("success", [], None, {"message": "ok"})

    monkeypatch.setattr(tm, "run_task", fake_run_task)
    manager = tm.TaskManager(config, llm=object(), rules={"rules": []})
    task_id = manager.submit(TaskRequest(prompt="巡逻场景", options=[]))
    _wait_terminal(manager, task_id)

    restarted = tm.TaskManager(config, llm=object(), rules={"rules": []})
    history = restarted.list_prompt_history()
    assert [(item.task_id, item.prompt) for item in history] == [(task_id, "巡逻场景")]


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


def test_conversation_create_first_turn_and_persist(tmp_path, monkeypatch):
    config = _config(tmp_path)

    def fake_run_task(request, config, llm, rules, workdir, task_id):
        Path(workdir).mkdir(parents=True, exist_ok=True)
        (Path(workdir) / "scenario.txt").write_text(request.script or "generated\n", encoding="utf-8")
        return TaskResult("success", [], None, {"message": "mission loaded OK"})

    monkeypatch.setattr(tm, "run_task", fake_run_task)
    manager = tm.TaskManager(config, llm=object(), rules={"rules": []})
    conv_id = manager.create_conversation(TaskRequest(prompt="生成空战场景", options=["-es"]))
    _wait_terminal(manager, manager.get_conversation(conv_id).turns[0].task_id)

    conversation = manager.get_conversation(conv_id)
    assert conversation is not None
    assert conversation.state == "active"
    assert conversation.initial_prompt == "生成空战场景"
    assert len(conversation.turns) == 1
    assert conversation.turns[0].round == 1
    assert conversation.turns[0].instruction == "生成空战场景"
    assert conversation.turns[0].state == "success"
    assert conversation.current_task_id == conversation.turns[0].task_id

    restarted = tm.TaskManager(config, llm=object(), rules={"rules": []})
    again = restarted.get_conversation(conv_id)
    assert again is not None
    assert again.current_task_id == conversation.turns[0].task_id
    assert len(again.turns) == 1


def test_conversation_add_turn_uses_previous_script(tmp_path, monkeypatch):
    config = _config(tmp_path)
    seen = {}

    def fake_run_task(request, config, llm, rules, workdir, task_id):
        Path(workdir).mkdir(parents=True, exist_ok=True)
        content = request.script or "end_time 7200 sec\n"
        (Path(workdir) / "scenario.txt").write_text(content, encoding="utf-8")
        seen[task_id] = (request.script, request.instruction)
        return TaskResult("success", [], None, {"message": "mission loaded OK"})

    monkeypatch.setattr(tm, "run_task", fake_run_task)
    manager = tm.TaskManager(config, llm=object(), rules={"rules": []})
    conv_id = manager.create_conversation(TaskRequest(script="platform A FIGHTER\n"))
    first_task_id = manager.get_conversation(conv_id).turns[0].task_id
    _wait_terminal(manager, first_task_id)

    task_id = manager.add_turn(conv_id, "再加一架飞机")
    _wait_terminal(manager, task_id)
    conversation = manager.get_conversation(conv_id)
    assert len(conversation.turns) == 2
    assert conversation.turns[1].round == 2
    assert conversation.turns[1].instruction == "再加一架飞机"
    assert conversation.current_task_id == task_id
    assert seen[task_id][0] == "platform A FIGHTER\n"
    assert seen[task_id][1] == "再加一架飞机"


def test_conversation_failed_turn_keeps_previous_current(tmp_path, monkeypatch):
    config = _config(tmp_path)
    calls = {"n": 0}

    def fake_run_task(request, config, llm, rules, workdir, task_id):
        calls["n"] += 1
        Path(workdir).mkdir(parents=True, exist_ok=True)
        (Path(workdir) / "scenario.txt").write_text(request.script or "x\n", encoding="utf-8")
        if calls["n"] == 1:
            return TaskResult("success", [], None, {"message": "mission loaded OK"})
        return TaskResult("failed", [], None, {"max_retries_exceeded": 3})

    monkeypatch.setattr(tm, "run_task", fake_run_task)
    manager = tm.TaskManager(config, llm=object(), rules={"rules": []})
    conv_id = manager.create_conversation(TaskRequest(script="a\n"))
    first_task_id = manager.get_conversation(conv_id).turns[0].task_id
    _wait_terminal(manager, first_task_id)

    bad_task_id = manager.add_turn(conv_id, "改成失败")
    _wait_terminal(manager, bad_task_id)
    conversation = manager.get_conversation(conv_id)
    assert conversation.current_task_id == first_task_id
    assert len(conversation.turns) == 2
    assert conversation.turns[1].state == "failed"


def test_conversation_finish_and_errors(tmp_path, monkeypatch):
    config = _config(tmp_path)

    def fake_run_task(request, config, llm, rules, workdir, task_id):
        Path(workdir).mkdir(parents=True, exist_ok=True)
        return TaskResult("success", [], None, {"message": "ok"})

    monkeypatch.setattr(tm, "run_task", fake_run_task)
    manager = tm.TaskManager(config, llm=object(), rules={"rules": []})
    conv_id = manager.create_conversation(TaskRequest(script="a\n"))
    first_task_id = manager.get_conversation(conv_id).turns[0].task_id
    _wait_terminal(manager, first_task_id)

    assert manager.finish_conversation(conv_id) is True
    assert manager.get_conversation(conv_id).state == "finished"
    assert manager.finish_conversation(conv_id) is False

    with pytest.raises(tm.ConversationNotFound):
        manager.add_turn("nope", "x")
    with pytest.raises(tm.ConversationFinished):
        manager.add_turn(conv_id, "x")
    with pytest.raises(tm.EmptyInstruction):
        manager.add_turn(conv_id, "   ")
    with pytest.raises(tm.NoCurrentScript):
        fresh = manager.create_conversation(TaskRequest(script="a\n"))
        manager.add_turn(fresh, "x")


def test_list_conversations_returns_turn_counts(tmp_path, monkeypatch):
    config = _config(tmp_path)

    def fake_run_task(request, config, llm, rules, workdir, task_id):
        Path(workdir).mkdir(parents=True, exist_ok=True)
        (Path(workdir) / "scenario.txt").write_text(request.script or "generated\n", encoding="utf-8")
        return TaskResult("success", [], None, {"message": "ok"})

    monkeypatch.setattr(tm, "run_task", fake_run_task)
    manager = tm.TaskManager(config, llm=object(), rules={"rules": []})
    conv_a = manager.create_conversation(TaskRequest(prompt="场景A"))
    conv_b = manager.create_conversation(TaskRequest(prompt="场景B"))
    _wait_terminal(manager, manager.get_conversation(conv_a).turns[0].task_id)
    _wait_terminal(manager, manager.get_conversation(conv_b).turns[0].task_id)
    manager.add_turn(conv_a, "改一下")

    items = manager.list_conversations()
    by_id = {i["conversation_id"]: i for i in items}
    assert by_id[conv_a]["turn_count"] == 2
    assert by_id[conv_b]["turn_count"] == 1
    assert by_id[conv_a]["state"] == "active"
    assert by_id[conv_a]["initial_prompt"] == "场景A"
