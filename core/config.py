from dataclasses import dataclass
import os
from pathlib import Path

@dataclass
class Config:
    afsim_install_dir: str = ""
    mission_exe: str = ""
    concurrency: int = 2
    max_retries: int = 3
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = ""
    llm_model: str = ""
    workspaces_dir: str = "workspaces"
    db_path: str = "workspaces/tasks.db"

def _detect_mission_exe(install_dir: str) -> str:
    if os.name == "nt":
        return os.path.join(install_dir, "bin", "mission.exe")
    return os.path.join(install_dir, "bin", "mission")

def load_config(config_path: Path = Path("config.txt")) -> Config:
    cfg = Config()
    if config_path.exists():
        for line in config_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = [x.strip() for x in line.split("=", 1)]
            setattr(cfg, k.lower(), v)
    for k, v in [("llm_base_url", "LLM_BASE_URL"), ("llm_api_key", "LLM_API_KEY"), ("llm_model", "LLM_MODEL")]:
        env = os.environ.get(v)
        if env:
            setattr(cfg, k, env)
    for f in ("concurrency", "max_retries"):
        try:
            setattr(cfg, f, int(getattr(cfg, f)))
        except ValueError:
            pass
    cfg.mission_exe = _detect_mission_exe(cfg.afsim_install_dir)
    return cfg
