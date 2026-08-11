from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.task_manager import TaskStatus
from core.config import Config


class FakeTaskManager:
    def __init__(self, config=None):
        self.config = config or Config(workspaces_dir="workspaces")
        self.statuses = {}
        self.submitted = []

    def submit(self, request):
        task_id = f"task-{len(self.submitted) + 1}"
        self.submitted.append(request)
        self.statuses[task_id] = TaskStatus(task_id, "pending", "2026-08-11T00:00:00", [], {})
        return task_id

    def get(self, task_id):
        return self.statuses.get(task_id)

    def cancel(self, task_id):
        status = self.statuses.get(task_id)
        if status and status.state in ("pending", "running"):
            status.state = "cancelled"
            return True
        return False


@pytest.fixture
def client(tmp_path):
    manager = FakeTaskManager(config=Config(workspaces_dir=str(tmp_path / "workspaces")))
    return TestClient(create_app(task_manager=manager)), manager


def test_post_task_returns_task_id(client):
    test_client, manager = client
    resp = test_client.post("/api/tasks", json={"prompt": "生成编队", "options": ["-v"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["task_id"] == "task-1"
    assert body["state"] == "pending"
    assert manager.submitted[0].prompt == "生成编队"
    assert manager.submitted[0].options == ["-v"]


def test_get_task_returns_status(client):
    test_client, _ = client
    test_client.post("/api/tasks", json={"script": "mission\n"})
    resp = test_client.get("/api/tasks/task-1")
    assert resp.status_code == 200
    assert resp.json()["task_id"] == "task-1"
    assert resp.json()["state"] == "pending"
    assert resp.json()["created_at"] == "2026-08-11T00:00:00"


def test_get_missing_task_returns_404(client):
    test_client, _ = client
    assert test_client.get("/api/tasks/nope").status_code == 404


def test_healthz(client):
    test_client, _ = client
    resp = test_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_cancel_running_task(client):
    test_client, _ = client
    test_client.post("/api/tasks", json={"prompt": "x"})
    resp = test_client.post("/api/tasks/task-1/cancel")
    assert resp.status_code == 200
    assert resp.json() == {"cancelled": True}


def test_cancel_missing_task_returns_404(client):
    test_client, _ = client
    assert test_client.post("/api/tasks/nope/cancel").status_code == 404


def test_log_returns_workdir_file_list_as_degradation(client):
    test_client, manager = client
    workdir = Path(manager.config.workspaces_dir) / "task-1"
    workdir.mkdir(parents=True)
    (workdir / "scenario.txt").write_text("mission\n", encoding="utf-8")
    test_client.post("/api/tasks", json={"prompt": "x"})
    resp = test_client.get("/api/tasks/task-1/log")
    assert resp.status_code == 200
    assert "scenario.txt" in resp.json()["files"]


def test_log_missing_task_returns_404(client):
    test_client, _ = client
    assert test_client.get("/api/tasks/nope/log").status_code == 404


def test_log_no_files_returns_404(client):
    test_client, _ = client
    test_client.post("/api/tasks", json={"prompt": "x"})
    assert test_client.get("/api/tasks/task-1/log").status_code == 404


def test_promote_requires_confirm(client):
    test_client, _ = client
    resp = test_client.post("/api/pending/20260811_101500_unknown/promote", json={})
    assert resp.status_code == 400


def test_promote_confirm_false_returns_400(client):
    test_client, _ = client
    resp = test_client.post(
        "/api/pending/20260811_101500_unknown/promote", json={"confirm": False}
    )
    assert resp.status_code == 400


def test_promote_confirm_true_returns_200(client, monkeypatch, tmp_path):
    import api.main as main

    monkeypatch.setattr(main, "ROOT", tmp_path)
    pending_dir = tmp_path / "memory" / "pending"
    pending_dir.mkdir(parents=True)
    (pending_dir / "20260811_101500_unknown.md").write_text(
        "note: x\n原始 stderr:\nUnknown command: foo\n", encoding="utf-8"
    )
    test_client, _ = client
    resp = test_client.post(
        "/api/pending/20260811_101500_unknown/promote", json={"confirm": True}
    )
    assert resp.status_code == 200
    assert resp.json() == {"promoted": True}
    assert "Unknown command: foo" in (tmp_path / "memory" / "errors-ref.md").read_text(encoding="utf-8")


def test_promote_missing_file_returns_404(client, monkeypatch, tmp_path):
    import api.main as main

    monkeypatch.setattr(main, "ROOT", tmp_path)
    test_client, _ = client
    resp = test_client.post(
        "/api/pending/20260811_101500_unknown/promote", json={"confirm": True}
    )
    assert resp.status_code == 404


def test_pending_lists_unknown_files_with_summary(client, monkeypatch, tmp_path):
    import api.main as main

    monkeypatch.setattr(main, "ROOT", tmp_path)
    pending_dir = tmp_path / "memory" / "pending"
    pending_dir.mkdir(parents=True)
    (pending_dir / "20260811_101500_unknown.md").write_text(
        "note: x\n时间: 2026-08-11\n原始 stderr:\nboom\n", encoding="utf-8"
    )
    test_client, _ = client
    resp = test_client.get("/api/pending")
    assert resp.status_code == 200
    assert resp.json()["pending"] == [
        {"file": "20260811_101500_unknown.md", "summary": "note: x"}
    ]


def test_lessons_stats_returns_rule_counts(client):
    test_client, _ = client
    resp = test_client.get("/api/lessons")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)
