import subprocess
from core.executor import run, ExecutionResult

def test_run_calls_mission_in_workdir(tmp_path, monkeypatch):
    script = tmp_path / "scenario.txt"
    script.write_text("end_time 10 sec\n")
    calls = {}
    def fake_run(cmd, capture_output, text, cwd, **kw):
        calls["cmd"] = cmd; calls["cwd"] = cwd
        return subprocess.CompletedProcess(cmd, 0, "loaded ok", "")
    monkeypatch.setattr(subprocess, "run", fake_run)
    res = run(script, tmp_path / "ws", None, options=None)
    assert res.rc == 0 and "loaded ok" in res.stdout
    assert str(tmp_path / "ws") in calls["cwd"]

def test_mission_missing(tmp_path):
    from core.config import Config
    script = tmp_path / "scripts" / "x.txt"
    script.parent.mkdir()
    script.write_text("end_time 10 sec\n")
    cfg = Config(mission_exe="/nonexistent/mission")
    res = run(script, tmp_path, cfg)
    assert res.rc == 1
    assert "mission.exe" in res.stderr
