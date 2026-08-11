import os
from core.config import load_config, Config

def test_load_config_defaults(tmp_path):
    cfg_file = tmp_path / "config.txt"
    cfg_file.write_text("AFSIM_INSTALL_DIR=/opt/afsim\nCONCURRENCY=4\nMAX_RETRIES=3\nLLM_TIMEOUT=120\nDEFAULT_END_TIME_SEC=7200\nDEFAULT_ROUTE_SPEED=500 kts\n")
    cfg = load_config(cfg_file)
    assert cfg.afsim_install_dir == "/opt/afsim"
    assert cfg.mission_exe == "/opt/afsim/bin/mission"
    assert cfg.concurrency == 4 and cfg.max_retries == 3
    assert cfg.llm_timeout == 120
    assert cfg.default_end_time_sec == 7200
    assert cfg.default_route_speed == "500 kts"
    assert cfg.llm_model == ""

def test_env_override(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.txt"
    cfg_file.write_text("LLM_MODEL=deepseek-chat\n")
    monkeypatch.setenv("LLM_MODEL", "env-model")
    monkeypatch.setenv("MAX_RETRIES", "10")
    monkeypatch.setenv("DEFAULT_END_TIME_SEC", "9000")
    monkeypatch.setenv("DEFAULT_ROUTE_SPEED", "300 kts")
    cfg = load_config(cfg_file)
    assert cfg.llm_model == "env-model"
    assert cfg.max_retries == 10
    assert cfg.default_end_time_sec == 9000
    assert cfg.default_route_speed == "300 kts"

def test_mission_exe_override_and_remote_config(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.txt"
    cfg_file.write_text(
        "AFSIM_INSTALL_DIR=/opt/afsim\n"
        "MISSION_EXE=/custom/mission\n"
        "EXECUTOR_MODE=remote\n"
        "AFSIM_RUNNER_URL=http://win-runner:9001\n"
    )
    cfg = load_config(cfg_file)
    assert cfg.mission_exe == "/custom/mission"
    assert cfg.executor_mode == "remote"
    assert cfg.afsim_runner_url == "http://win-runner:9001"

    monkeypatch.setenv("MISSION_EXE", "/env/mission")
    monkeypatch.setenv("EXECUTOR_MODE", "local")
    cfg = load_config(cfg_file)
    assert cfg.mission_exe == "/env/mission"
    assert cfg.executor_mode == "local"
