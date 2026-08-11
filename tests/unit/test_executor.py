import subprocess
import httpx
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
    assert calls["cmd"][-1].startswith("/")
    assert calls["cmd"][-1].endswith("scenario.txt")
    assert (tmp_path / "ws" / "output").is_dir()

def test_mission_missing(tmp_path):
    from core.config import Config
    script = tmp_path / "scripts" / "x.txt"
    script.parent.mkdir()
    script.write_text("end_time 10 sec\n")
    cfg = Config(mission_exe="/nonexistent/mission")
    res = run(script, tmp_path, cfg)
    assert res.rc == 1
    assert "mission.exe" in res.stderr

def test_remote_executor_posts_script(tmp_path, monkeypatch):
    from core.config import Config

    script = tmp_path / "scenario.txt"
    script.write_text("end_time 10 sec\n")
    calls = {}

    def fake_post(url, json, timeout):
        calls["url"] = url
        calls["json"] = json
        calls["timeout"] = timeout
        return httpx.Response(
            200,
            json={"rc": 0, "stdout": "remote ok", "stderr": ""},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("core.executor.httpx.post", fake_post)
    cfg = Config(executor_mode="remote", afsim_runner_url="http://win-runner:9001")
    res = run(script, tmp_path / "ws", cfg, options=["-es"])
    assert res == ExecutionResult(rc=0, stdout="remote ok", stderr="")
    assert calls["url"] == "http://win-runner:9001/run"
    assert calls["json"]["script_name"] == "scenario.txt"
    assert calls["json"]["script_text"] == "end_time 10 sec\n"
    assert calls["json"]["options"] == ["-es"]

def test_remote_executor_requires_url(tmp_path):
    from core.config import Config

    script = tmp_path / "scenario.txt"
    script.write_text("end_time 10 sec\n")
    cfg = Config(executor_mode="remote")
    res = run(script, tmp_path / "ws", cfg)
    assert res.rc == 1
    assert "AFSIM_RUNNER_URL" in res.stderr
