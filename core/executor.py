import io
import os
import shutil
import sys
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path

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
        rc, stdout, stderr = run_mission(str(dst), options, cfg_dict)
    return ExecutionResult(rc=rc, stdout=stdout, stderr=stderr)
