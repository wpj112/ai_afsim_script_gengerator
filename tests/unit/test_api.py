import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from api.main import create_app
from api.task_manager import (
    ConversationFinished,
    ConversationNotFound,
    EmptyInstruction,
    NoCurrentScript,
    PromptHistoryItem,
    TaskStatus,
)
from core.config import Config


class FakeTaskManager:
    def __init__(self, config=None):
        self.config = config or Config(workspaces_dir="workspaces")
        self.statuses = {}
        self.submitted = []
        self.conversations = {}

    def submit(self, request):
        task_id = uuid.uuid4().hex
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

    def list_prompt_history(self, limit=50):
        return [
            PromptHistoryItem(
                task_id=task_id,
                prompt=req.prompt,
                options=req.options or [],
                created_at=self.statuses[task_id].created_at,
                state=self.statuses[task_id].state,
            )
            for task_id, req in zip(self.statuses, self.submitted)
            if req.prompt
        ][:limit]

    def create_conversation(self, request):
        conversation_id = uuid.uuid4().hex
        self.conversations[conversation_id] = {
            "created_at": "2026-08-12T00:00:00",
            "initial_prompt": request.prompt or None,
            "current_task_id": None,
            "state": "active",
            "turns": [],
        }
        task_id = self.submit(request)
        self.conversations[conversation_id]["turns"].append(
            {
                "round": 1,
                "task_id": task_id,
                "instruction": request.prompt or None,
                "state": "pending",
                "result": {},
            }
        )
        return conversation_id

    def list_conversations(self, limit=50):
        return [
            {
                "conversation_id": cid,
                "created_at": c["created_at"],
                "initial_prompt": c["initial_prompt"],
                "current_task_id": c["current_task_id"],
                "state": c["state"],
                "turn_count": len(c["turns"]),
            }
            for cid, c in self.conversations.items()
        ][:limit]

    def get_conversation(self, conversation_id):
        c = self.conversations.get(conversation_id)
        if c is None:
            return None
        return SimpleNamespace(
            conversation_id=conversation_id,
            created_at=c["created_at"],
            initial_prompt=c["initial_prompt"],
            current_task_id=c["current_task_id"],
            state=c["state"],
            turns=[SimpleNamespace(**t) for t in c["turns"]],
        )

    def add_turn(self, conversation_id, instruction, options=None):
        c = self.conversations.get(conversation_id)
        if c is None:
            raise ConversationNotFound(conversation_id)
        if c["state"] == "finished":
            raise ConversationFinished(conversation_id)
        if not (instruction or "").strip():
            raise EmptyInstruction(conversation_id)
        if not c["current_task_id"]:
            raise NoCurrentScript(conversation_id)
        task_id = self.submit(SimpleNamespace(
            prompt=None, script="cur", options=options, instruction=instruction
        ))
        c["turns"].append(
            {
                "round": len(c["turns"]) + 1,
                "task_id": task_id,
                "instruction": instruction,
                "state": "pending",
                "result": {},
            }
        )
        c["current_task_id"] = task_id
        return task_id

    def finish_conversation(self, conversation_id):
        c = self.conversations.get(conversation_id)
        if c is None or c["state"] == "finished":
            return False
        c["state"] = "finished"
        return True


@pytest.fixture
def client(tmp_path):
    manager = FakeTaskManager(config=Config(workspaces_dir=str(tmp_path / "workspaces")))
    return TestClient(create_app(task_manager=manager)), manager


def test_post_task_returns_task_id(client):
    test_client, manager = client
    resp = test_client.post("/api/tasks", json={"prompt": "生成编队", "options": ["-v"]})
    assert resp.status_code == 200
    body = resp.json()
    assert re.fullmatch(r"[0-9a-f]{32}", body["task_id"])
    assert manager.submitted[0].prompt == "生成编队"
    assert manager.submitted[0].options == ["-v"]


def test_get_task_returns_status(client):
    test_client, _ = client
    created = test_client.post("/api/tasks", json={"script": "mission\n"}).json()
    resp = test_client.get(f"/api/tasks/{created['task_id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["task_id"] == created["task_id"]
    assert body["state"] == "pending"
    assert body["created_at"] == "2026-08-11T00:00:00"


def test_get_missing_task_returns_404(client):
    test_client, _ = client
    assert test_client.get("/api/tasks/nope").status_code == 404


def test_healthz(client):
    test_client, _ = client
    resp = test_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_frontend_index_served(client):
    test_client, _ = client
    resp = test_client.get("/")
    assert resp.status_code == 200
    assert "AFSIM Agent" in resp.text
    assert "生成脚本" in resp.text
    assert "copyScript" in resp.text
    assert "Warlock 配置" in resp.text
    assert "步骤详情" in resp.text
    assert "当前执行流程" in resp.text
    assert "Prompt 历史" in resp.text


def test_frontend_static_js_served(client):
    test_client, _ = client
    resp = test_client.get("/static/app.js")
    assert resp.status_code == 200
    assert "submitTask" in resp.text
    assert "renderSteps" in resp.text
    assert "renderFlow" in resp.text
    assert "loadPromptHistory" in resp.text
    assert "copyScript" in resp.text
    assert "runWarlock" in resp.text


def test_task_scenario_endpoint_returns_script(client):
    test_client, manager = client
    created = test_client.post("/api/tasks", json={"prompt": "x"}).json()
    task_id = created["task_id"]
    workdir = Path(manager.config.workspaces_dir) / task_id
    workdir.mkdir(parents=True)
    (workdir / "scenario.txt").write_text("end_time 7200 sec\n", encoding="utf-8")
    resp = test_client.get(f"/api/tasks/{task_id}/scenario.txt")
    assert resp.status_code == 200
    assert resp.text == "end_time 7200 sec\n"
    assert resp.headers["content-type"].startswith("text/plain")


def test_task_scenario_endpoint_missing_returns_404(client):
    test_client, _ = client
    created = test_client.post("/api/tasks", json={"prompt": "x"}).json()
    resp = test_client.get(f"/api/tasks/{created['task_id']}/scenario.txt")
    assert resp.status_code == 404


def test_prompt_history_endpoint_returns_persisted_prompts(client):
    test_client, manager = client
    created = test_client.post("/api/tasks", json={"prompt": "生成编队", "options": ["-es"]}).json()
    test_client.post("/api/tasks", json={"script": "end_time 1 sec\n", "options": ["-es"]})
    resp = test_client.get("/api/prompt-history")
    assert resp.status_code == 200
    assert resp.json() == {
        "history": [
            {
                "task_id": created["task_id"],
                "prompt": "生成编队",
                "options": ["-es"],
                "created_at": "2026-08-11T00:00:00",
                "state": "pending",
            }
        ]
    }


def test_cancel_running_task(client):
    test_client, _ = client
    created = test_client.post("/api/tasks", json={"prompt": "x"}).json()
    resp = test_client.post(f"/api/tasks/{created['task_id']}/cancel")
    assert resp.status_code == 200
    assert resp.json() == {"cancelled": True}


def test_cancel_missing_task_returns_404(client):
    test_client, _ = client
    assert test_client.post("/api/tasks/nope/cancel").status_code == 404


def test_log_returns_workdir_file_list_as_degradation(client):
    test_client, manager = client
    created = test_client.post("/api/tasks", json={"prompt": "x"}).json()
    task_id = created["task_id"]
    workdir = Path(manager.config.workspaces_dir) / task_id
    workdir.mkdir(parents=True)
    (workdir / "scenario.txt").write_text("mission\n", encoding="utf-8")
    resp = test_client.get(f"/api/tasks/{task_id}/log")
    assert resp.status_code == 200
    assert "scenario.txt" in resp.json()["files"]
    assert resp.json()["scenario_text"] == "mission\n"


def test_log_missing_task_returns_404(client):
    test_client, _ = client
    assert test_client.get("/api/tasks/nope/log").status_code == 404


def test_log_no_files_returns_404(client):
    test_client, _ = client
    created = test_client.post("/api/tasks", json={"prompt": "x"}).json()
    assert test_client.get(f"/api/tasks/{created['task_id']}/log").status_code == 404


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


def test_log_invalid_task_id_returns_404(client):
    test_client, _ = client
    resp = test_client.get("/api/tasks/not-a-hex-task-id/log")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "task not found"}


def test_log_unknown_hex_task_id_returns_404(client):
    test_client, _ = client
    resp = test_client.get(f"/api/tasks/{'a' * 32}/log")
    assert resp.status_code == 404


def test_promote_rejects_dotdot_file_id(client, monkeypatch, tmp_path):
    import api.main as main

    monkeypatch.setattr(main, "ROOT", tmp_path)
    test_client, _ = client
    resp = test_client.post("/api/pending/%2E%2E/promote", json={"confirm": True})
    assert resp.status_code == 400
    assert resp.json() == {"detail": "invalid file id"}


def test_promote_rejects_traversal_file_id(client):
    test_client, _ = client
    route = next(
        r for r in test_client.app.routes
        if getattr(r, "path", "") == "/api/pending/{file_id}/promote"
    )

    class ConfirmBody(BaseModel):
        confirm: bool = True

    with pytest.raises(HTTPException) as exc_info:
        route.endpoint(file_id="../../core/agent.py", body=ConfirmBody())
    assert exc_info.value.status_code == 400
    with pytest.raises(HTTPException) as exc_info:
        route.endpoint(file_id="../unknown", body=ConfirmBody())
    assert exc_info.value.status_code == 400


def test_promote_rejects_non_unknown_file_id(client):
    test_client, _ = client
    resp = test_client.post(
        "/api/pending/20260811_101500_known/promote", json={"confirm": True}
    )
    assert resp.status_code == 400
    assert resp.json() == {"detail": "invalid file id"}


class BoomManager:
    def __init__(self):
        self.config = Config(workspaces_dir="workspaces")

    def submit(self, request):
        raise RuntimeError("boom")

    def get(self, task_id):
        raise RuntimeError("boom")

    def cancel(self, task_id):
        raise RuntimeError("boom")


def test_manager_error_returns_500_without_traceback():
    test_client = TestClient(
        create_app(task_manager=BoomManager()), raise_server_exceptions=False
    )
    resp = test_client.get("/api/tasks/whatever")
    assert resp.status_code == 500
    assert resp.json() == {"detail": "internal error"}
    assert "Traceback" not in resp.text


def test_lessons_missing_rules_returns_500(client, monkeypatch, tmp_path):
    import api.main as main

    monkeypatch.setattr(main, "ROOT", tmp_path)
    test_client, _ = client
    resp = test_client.get("/api/lessons")
    assert resp.status_code == 500
    assert resp.json() == {"detail": "error rules unavailable"}


def test_pending_missing_dir_returns_empty(client, monkeypatch, tmp_path):
    import api.main as main

    monkeypatch.setattr(main, "ROOT", tmp_path)
    test_client, _ = client
    resp = test_client.get("/api/pending")
    assert resp.status_code == 200
    assert resp.json() == {"pending": []}


def test_create_conversation_returns_conversation_and_first_task(client):
    test_client, manager = client
    resp = test_client.post("/api/conversations", json={"prompt": "生成空战场景", "options": ["-es"]})
    assert resp.status_code == 200
    body = resp.json()
    assert re.fullmatch(r"[0-9a-f]{32}", body["conversation_id"])
    assert re.fullmatch(r"[0-9a-f]{32}", body["task_id"])
    assert body["state"] == "active"


def test_list_conversations_empty(client):
    test_client, _ = client
    resp = test_client.get("/api/conversations")
    assert resp.status_code == 200
    assert resp.json() == {"conversations": []}


def test_get_conversation_detail(client):
    test_client, _ = client
    created = test_client.post("/api/conversations", json={"prompt": "x"}).json()
    conv_id = created["conversation_id"]
    resp = test_client.get(f"/api/conversations/{conv_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["conversation_id"] == conv_id
    assert body["state"] == "active"
    assert len(body["turns"]) == 1
    assert body["turns"][0]["task_id"] == created["task_id"]
    assert body["turns"][0]["instruction"] == "x"
    assert body["turns"][0]["state"] == "pending"


def test_get_conversation_missing_404(client):
    test_client, _ = client
    assert test_client.get("/api/conversations/nope").status_code == 404


def test_submit_conversation_turn(client):
    test_client, manager = client
    created = test_client.post("/api/conversations", json={"script": "end_time 1 sec\n"}).json()
    conv_id = created["conversation_id"]
    manager.conversations[conv_id]["current_task_id"] = "firsttask"
    resp = test_client.post(f"/api/conversations/{conv_id}/tasks", json={"instruction": "把速度改快"})
    assert resp.status_code == 200
    body = resp.json()
    assert re.fullmatch(r"[0-9a-f]{32}", body["task_id"])
    detail = test_client.get(f"/api/conversations/{conv_id}").json()
    assert len(detail["turns"]) == 2
    assert detail["turns"][1]["instruction"] == "把速度改快"


def test_submit_turn_missing_conversation_404(client):
    test_client, _ = client
    resp = test_client.post("/api/conversations/nope/tasks", json={"instruction": "x"})
    assert resp.status_code == 404


def test_submit_turn_empty_instruction_400(client):
    test_client, manager = client
    created = test_client.post("/api/conversations", json={"script": "x\n"}).json()
    conv_id = created["conversation_id"]
    manager.get_conversation(conv_id).current_task_id = "t1"
    resp = test_client.post(f"/api/conversations/{conv_id}/tasks", json={"instruction": "  "})
    assert resp.status_code == 400


def test_submit_turn_no_script_409(client):
    test_client, _ = client
    created = test_client.post("/api/conversations", json={"prompt": "x"}).json()
    conv_id = created["conversation_id"]
    resp = test_client.post(f"/api/conversations/{conv_id}/tasks", json={"instruction": "改"})
    assert resp.status_code == 409


def test_finish_conversation(client):
    test_client, _ = client
    created = test_client.post("/api/conversations", json={"prompt": "x"}).json()
    conv_id = created["conversation_id"]
    assert test_client.post(f"/api/conversations/{conv_id}/finish").json() == {"finished": True}
    resp = test_client.post(f"/api/conversations/{conv_id}/tasks", json={"instruction": "改"})
    assert resp.status_code == 409


def test_finish_missing_conversation_404(client):
    test_client, _ = client
    assert test_client.post("/api/conversations/nope/finish").status_code == 404
