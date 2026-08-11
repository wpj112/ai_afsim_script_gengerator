import os
from core.config import load_config, Config

def test_load_config_defaults(tmp_path):
    cfg_file = tmp_path / "config.txt"
    cfg_file.write_text("AFSIM_INSTALL_DIR=/opt/afsim\nCONCURRENCY=4\nMAX_RETRIES=3\n")
    cfg = load_config(cfg_file)
    assert cfg.afsim_install_dir == "/opt/afsim"
    assert cfg.mission_exe == "/opt/afsim/bin/mission"
    assert cfg.concurrency == 4 and cfg.max_retries == 3
    assert cfg.llm_model == ""

def test_env_override(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.txt"
    cfg_file.write_text("LLM_MODEL=deepseek-chat\n")
    monkeypatch.setenv("LLM_MODEL", "env-model")
    cfg = load_config(cfg_file)
    assert cfg.llm_model == "env-model"
