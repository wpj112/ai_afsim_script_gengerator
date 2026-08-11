#!/usr/bin/env python3
"""
Small AFSIM runner service for Windows hosts.

Run this on the machine where the Windows AFSIM package is installed. The Linux
afsim-gen service can call POST /run when EXECUTOR_MODE=remote.
"""

import argparse
import os
import subprocess
import uuid
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    script_name: str = "scenario.txt"
    script_text: str
    options: list[str] = Field(default_factory=list)


class RunnerConfig:
    def __init__(self, afsim_install_dir="", mission_exe="", workspaces_dir="runner_workspaces"):
        self.afsim_install_dir = afsim_install_dir
        self.mission_exe = mission_exe or self._detect_mission_exe(afsim_install_dir)
        self.workspaces_dir = Path(workspaces_dir)

    @staticmethod
    def _detect_mission_exe(install_dir):
        if not install_dir:
            return ""
        return str(Path(install_dir) / "bin" / "mission.exe")


def create_app(config):
    app = FastAPI()

    @app.get("/healthz")
    def healthz():
        return {
            "status": "ok",
            "mission_exe": config.mission_exe,
            "mission_exists": Path(config.mission_exe).exists(),
        }

    @app.post("/run")
    def run(req: RunRequest):
        try:
            mission = Path(config.mission_exe)
            if not mission.exists():
                return {"rc": 1, "stdout": "", "stderr": f"mission.exe not found: {mission}", "files": []}
            safe_name = Path(req.script_name).name or "scenario.txt"
            if not safe_name.endswith(".txt"):
                safe_name += ".txt"
            workdir = config.workspaces_dir / uuid.uuid4().hex
            workdir.mkdir(parents=True, exist_ok=True)
            (workdir / "output").mkdir(parents=True, exist_ok=True)
            script_path = workdir / safe_name
            script_path.write_text(req.script_text, encoding="utf-8")
            cmd = [str(mission)] + list(req.options or []) + [str(script_path)]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                errors="replace",
                cwd=str(workdir),
            )
            files = [
                {"name": p.name, "size": p.stat().st_size}
                for p in sorted(workdir.iterdir())
                if p.is_file()
            ]
            return {
                "rc": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "files": files,
            }
        except Exception as exc:
            return {"rc": 1, "stdout": "", "stderr": str(exc), "files": []}

    return app


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run a Windows AFSIM mission runner service")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9001)
    parser.add_argument("--afsim-install-dir", default=os.environ.get("AFSIM_INSTALL_DIR", ""))
    parser.add_argument("--mission-exe", default=os.environ.get("MISSION_EXE", ""))
    parser.add_argument("--workspaces-dir", default=os.environ.get("AFSIM_RUNNER_WORKSPACES", "runner_workspaces"))
    args = parser.parse_args(argv)
    config = RunnerConfig(
        afsim_install_dir=args.afsim_install_dir,
        mission_exe=args.mission_exe,
        workspaces_dir=args.workspaces_dir,
    )
    uvicorn.run(create_app(config), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
