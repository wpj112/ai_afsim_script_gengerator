import subprocess

from fastapi.testclient import TestClient

from scripts.windows_runner import RunnerConfig, create_app


def test_windows_runner_executes_mission_in_isolated_workdir(tmp_path, monkeypatch):
    mission = tmp_path / "afsim" / "bin" / "mission.exe"
    mission.parent.mkdir(parents=True)
    mission.write_text("fake", encoding="utf-8")
    calls = {}

    def fake_run(cmd, capture_output, text, errors, cwd):
        calls["cmd"] = cmd
        calls["cwd"] = cwd
        return subprocess.CompletedProcess(cmd, 0, "loaded ok", "")

    monkeypatch.setattr("scripts.windows_runner.subprocess.run", fake_run)
    app = create_app(RunnerConfig(mission_exe=str(mission), workspaces_dir=str(tmp_path / "ws")))
    client = TestClient(app)
    resp = client.post(
        "/run",
        json={
            "script_name": "../bad.wsf",
            "script_text": "end_time 10 sec\n",
            "options": ["-es"],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["rc"] == 0
    assert resp.json()["stdout"] == "loaded ok"
    assert calls["cmd"][0] == str(mission)
    assert calls["cmd"][1] == "-es"
    assert calls["cmd"][2].endswith("bad.wsf.txt")
    assert str(tmp_path / "ws") in calls["cwd"]
    workdirs = list((tmp_path / "ws").iterdir())
    assert workdirs
    assert any((p / "output").is_dir() for p in workdirs)


def test_windows_runner_missing_mission_returns_rc_1(tmp_path):
    app = create_app(RunnerConfig(mission_exe=str(tmp_path / "missing.exe"), workspaces_dir=str(tmp_path / "ws")))
    client = TestClient(app)
    resp = client.post("/run", json={"script_name": "scenario.txt", "script_text": "end_time 10 sec\n"})
    assert resp.status_code == 200
    assert resp.json()["rc"] == 1
    assert "mission.exe not found" in resp.json()["stderr"]
