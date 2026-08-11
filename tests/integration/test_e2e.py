import re
import time
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from api.main import create_app
from api.task_manager import TaskManager
from core.config import Config

TERMINAL = ("success", "failed", "needs_review", "cancelled")


def _config(tmp_path):
    return Config(
        concurrency=2,
        max_retries=2,
        llm_base_url="http://127.0.0.1:1/v1",
        llm_model="fake",
        workspaces_dir=str(tmp_path / "workspaces"),
        db_path=str(tmp_path / "workspaces" / "tasks.db"),
        afsim_install_dir=str(tmp_path / "no_afsim"),
        mission_exe=str(tmp_path / "no_afsim" / "bin" / "mission"),
    )


def _wait_terminal(client, task_id, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/api/tasks/{task_id}")
        body = resp.json()
        if body["state"] in TERMINAL:
            return body
        time.sleep(0.05)
    return client.get(f"/api/tasks/{task_id}").json()


def test_two_concurrent_script_tasks_isolated_workdirs_and_report(tmp_path):
    config = _config(tmp_path)
    fake_llm = SimpleNamespace(propose_fix=lambda script, err, hint: None)
    manager = TaskManager(config, llm=fake_llm, rules={"rules": []})
    client = TestClient(create_app(task_manager=manager))

    script_a = "platform_type FIGHTER WSF_PLATFORM\nplatform A FIGHTER\nend_platform\n"
    script_b = "platform_type FIGHTER WSF_PLATFORM\nplatform B FIGHTER\nend_platform\n"
    r1 = client.post("/api/tasks", json={"script": script_a})
    r2 = client.post("/api/tasks", json={"script": script_b})
    assert r1.status_code == 200
    assert r2.status_code == 200
    id1 = r1.json()["task_id"]
    id2 = r2.json()["task_id"]
    assert re.fullmatch(r"[0-9a-f]{32}", id1)
    assert re.fullmatch(r"[0-9a-f]{32}", id2)
    assert id1 != id2

    s1 = _wait_terminal(client, id1)
    s2 = _wait_terminal(client, id2)
    assert s1["state"] in TERMINAL
    assert s2["state"] in TERMINAL
    assert isinstance(s1["result"], dict)
    assert isinstance(s2["result"], dict)

    workspaces = Path(config.workspaces_dir)
    assert workspaces.exists()
    assert (workspaces / id1).is_dir()
    assert (workspaces / id2).is_dir()
    assert str((workspaces / id1).resolve()) != str((workspaces / id2).resolve())
    assert (workspaces / id1 / "scenario.txt").exists()
    assert (workspaces / id2 / "scenario.txt").exists()
    assert (workspaces / id1 / "scenario.txt").read_text(encoding="utf-8") == script_a + "end_time 7200 sec\n"
    assert (workspaces / id2 / "scenario.txt").read_text(encoding="utf-8") == script_b + "end_time 7200 sec\n"
