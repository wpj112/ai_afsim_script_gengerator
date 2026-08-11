import io
import os
import shutil
import sys
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.run_mission import run_mission

@dataclass
class ExecutionResult:
    rc: int
    stdout: str
    stderr: str

def run(script_path, workdir, config, options=None):
    script_path = Path(script_path)
    workdir = Path(workdir)
    if not script_path.exists():
        return ExecutionResult(rc=1, stdout="", stderr=f"Script file not found: {script_path}")
    workdir.mkdir(parents=True, exist_ok=True)
    mode = str(getattr(config, "executor_mode", "local") if config is not None else "local").lower()
    if mode == "remote":
        return run_remote(script_path, workdir, config, options)
    return run_local(script_path, workdir, config, options)


def run_local(script_path, workdir, config, options=None):
    script_path = Path(script_path)
    workdir = Path(workdir)
    (workdir / "output").mkdir(parents=True, exist_ok=True)
    dst = workdir / script_path.name
    if script_path.resolve() != dst.resolve():
        shutil.copy2(script_path, dst)
    if config is None:
        cfg_dict = {"mission_exe": str(dst), "afsim_install_dir": "", "documentation_dir": None}
    else:
        if not os.path.exists(config.mission_exe):
            return ExecutionResult(rc=1, stdout="", stderr=f"mission.exe not found: {config.mission_exe}")
        cfg_dict = {"mission_exe": config.mission_exe,
                    "afsim_install_dir": config.afsim_install_dir,
                    "documentation_dir": None}
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc, stdout, stderr = run_mission(str(dst.resolve()), options, cfg_dict)
    return ExecutionResult(rc=rc, stdout=stdout, stderr=stderr)


def run_remote(script_path, workdir, config, options=None):
    runner_url = getattr(config, "afsim_runner_url", "")
    if not runner_url:
        return ExecutionResult(rc=1, stdout="", stderr="AFSIM_RUNNER_URL is required for remote executor")
    try:
        payload = {
            "script_name": Path(script_path).name,
            "script_text": Path(script_path).read_text(encoding="utf-8"),
            "options": options or [],
        }
        resp = httpx.post(runner_url.rstrip("/") + "/run", json=payload, timeout=None)
        resp.raise_for_status()
        body = resp.json()
        return ExecutionResult(
            rc=int(body.get("rc", 1)),
            stdout=str(body.get("stdout", "")),
            stderr=str(body.get("stderr", "")),
        )
    except Exception as exc:
        return ExecutionResult(rc=1, stdout="", stderr=f"remote runner failed: {exc}")
