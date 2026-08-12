from dataclasses import dataclass
import os
from pathlib import Path

@dataclass
class Config:
    afsim_install_dir: str = ""
    mission_exe: str = ""
    executor_mode: str = "local"
    afsim_runner_url: str = ""
    concurrency: int = 2
    max_retries: int = 3
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout: int = 300
    default_end_time_sec: int = 7200
    default_route_speed: str = "450 kts"
    afsim_doc_root: str = ""
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
    env_overrides = [
        ("afsim_install_dir", "AFSIM_INSTALL_DIR"),
        ("mission_exe", "MISSION_EXE"),
        ("executor_mode", "EXECUTOR_MODE"),
        ("afsim_runner_url", "AFSIM_RUNNER_URL"),
        ("llm_base_url", "LLM_BASE_URL"),
        ("llm_api_key", "LLM_API_KEY"),
        ("llm_model", "LLM_MODEL"),
        ("llm_timeout", "LLM_TIMEOUT"),
        ("default_end_time_sec", "DEFAULT_END_TIME_SEC"),
        ("default_route_speed", "DEFAULT_ROUTE_SPEED"),
        ("afsim_doc_root", "AFSIM_DOC_ROOT"),
        ("concurrency", "CONCURRENCY"),
        ("max_retries", "MAX_RETRIES"),
    ]
    for k, v in env_overrides:
        env = os.environ.get(v)
        if env:
            setattr(cfg, k, env)
    for f in ("concurrency", "max_retries", "llm_timeout", "default_end_time_sec"):
        try:
            setattr(cfg, f, int(getattr(cfg, f)))
        except ValueError:
            pass
    cfg.executor_mode = str(cfg.executor_mode or "local").lower()
    if not cfg.mission_exe:
        cfg.mission_exe = _detect_mission_exe(cfg.afsim_install_dir)
    return cfg
