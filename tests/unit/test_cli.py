import pytest

import api.cli as cli
from api.task_manager import TaskStatus


class FakeManager:
    instances = []

    def __init__(self, config):
        self.config = config
        self.submitted = []
        self.task_id = "task123"
        FakeManager.instances.append(self)

    def submit(self, request):
        self.submitted.append(request)
        return self.task_id

    def get(self, task_id):
        return TaskStatus(
            task_id,
            "success",
            "2024-01-01T00:00:00",
            [{"attempt": 1, "rc": 1, "stderr": "boom", "matched_rule": "E001", "diff": "d"}],
            {"message": "mission loaded OK"},
        )


def test_help_lists_all_subcommands(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out + capsys.readouterr().err
    for name in ("serve", "run", "task", "lessons", "pending"):
        assert name in out


def test_run_prompt_submits_and_prints_report(monkeypatch, capsys):
    monkeypatch.setattr(cli, "TaskManager", FakeManager)
    cli.main(["run", "--prompt", "build a scenario"])
    out = capsys.readouterr().out
    manager = FakeManager.instances[-1]
    assert manager.submitted[0].prompt == "build a scenario"
    assert "state=success" in out
    assert "attempt 1" in out
    assert "mission loaded OK" in out


def test_run_script_submits_script(monkeypatch):
    monkeypatch.setattr(cli, "TaskManager", FakeManager)
    cli.main(["run", "--script", "scenario.txt"])
    manager = FakeManager.instances[-1]
    assert manager.submitted[0].script == "scenario.txt"
    assert manager.submitted[0].prompt is None


def test_run_without_prompt_or_script_exits_2(monkeypatch):
    monkeypatch.setattr(cli, "TaskManager", FakeManager)
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["run"])
    assert excinfo.value.code == 2


def test_task_prints_status(monkeypatch, capsys):
    monkeypatch.setattr(cli, "TaskManager", FakeManager)
    cli.main(["task", "task123"])
    out = capsys.readouterr().out
    assert "task123" in out
    assert "state=success" in out


def test_task_not_found(monkeypatch, capsys):
    class NotFoundManager(FakeManager):
        def get(self, task_id):
            return None

    monkeypatch.setattr(cli, "TaskManager", NotFoundManager)
    cli.main(["task", "missing"])
    assert "not found" in capsys.readouterr().out


def test_pending_promote_yes_calls_promote(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(cli.lessons, "promote", lambda *a, **k: calls.append(k) or True)
    cli.main(["pending", "--promote", "20240101_000000_unknown", "--yes"])
    assert calls == [{"confirm": True}]
    assert "promoted" in capsys.readouterr().out


def test_pending_promote_interactive_confirms(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr("builtins.input", lambda *a: "y")
    monkeypatch.setattr(cli.lessons, "promote", lambda *a, **k: calls.append(k) or True)
    cli.main(["pending", "--promote", "20240101_000000_unknown"])
    assert calls == [{"confirm": True}]


def test_pending_promote_interactive_aborts(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr("builtins.input", lambda *a: "n")
    monkeypatch.setattr(cli.lessons, "promote", lambda *a, **k: calls.append(k) or True)
    cli.main(["pending", "--promote", "20240101_000000_unknown"])
    assert calls == []
    assert "aborted" in capsys.readouterr().out


def test_serve_starts_uvicorn(monkeypatch):
    calls = []
    fake_uvicorn = type("FakeUvicorn", (), {"run": staticmethod(lambda *a, **k: calls.append((a, k)))})
    monkeypatch.setattr(cli, "uvicorn", fake_uvicorn)
    cli.main(["serve"])
    assert calls[0][0][0] is cli.app
    assert calls[0][1] == {"host": "0.0.0.0", "port": 8000}


def test_serve_port_override(monkeypatch):
    calls = []
    fake_uvicorn = type("FakeUvicorn", (), {"run": staticmethod(lambda *a, **k: calls.append((a, k)))})
    monkeypatch.setattr(cli, "uvicorn", fake_uvicorn)
    cli.main(["serve", "--port", "9000"])
    assert calls[0][1]["port"] == 9000
