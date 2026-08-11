#!/usr/bin/env bash
# L2 集成测试：需要真实 AFSIM 安装（mission 二进制）
# AFSIM 未配置时 SKIP；配置后对每个 broken scenario 跑纠错循环并断言任务到达终态
set -euo pipefail
cd "$(dirname "$0")/../.."

if [ -z "${AFSIM_INSTALL_DIR:-}" ]; then
  if [ -f config.txt ]; then
    AFSIM_INSTALL_DIR=$(grep -E '^AFSIM_INSTALL_DIR=' config.txt | head -1 | cut -d= -f2)
  fi
fi

if [ -z "${AFSIM_INSTALL_DIR:-}" ] || [ ! -x "$AFSIM_INSTALL_DIR/bin/mission" ]; then
  echo "SKIP: AFSIM not installed (set AFSIM_INSTALL_DIR or config.txt)"
  exit 0
fi

for f in tests/fixtures/broken_scenarios/*.txt; do
  echo "=== $f ==="
  # 导出 AFSIM_INSTALL_DIR 供 Python 侧 load_config 后覆盖派生 mission_exe
  export AFSIM_INSTALL_DIR SCRIPT_PATH="$(pwd)/$f"
  python - <<'PY'
import json
import os
from types import SimpleNamespace

from core.agent import TaskRequest, run_task
from core.config import load_config

with open("memory/error_rules.json", encoding="utf-8") as fh:
    rules = json.load(fh)
cfg = load_config()
# load_config 不读 AFSIM_INSTALL_DIR 环境变量，此处覆盖并补全 mission_exe
cfg.afsim_install_dir = os.environ["AFSIM_INSTALL_DIR"]
if not cfg.mission_exe or not os.path.exists(cfg.mission_exe):
    cfg.mission_exe = os.path.join(cfg.afsim_install_dir, "bin", "mission")
fake_llm = SimpleNamespace(propose_fix=lambda script, err, hint: None)
script_path = os.environ["SCRIPT_PATH"]
with open(script_path, encoding="utf-8") as fh:
    script = fh.read()
workdir = os.path.join("workspaces", "l2_" + os.path.basename(script_path))
result = run_task(TaskRequest(script=script), cfg, fake_llm, rules, workdir, "l2")
assert result.status in ("success", "needs_review", "failed"), result.status
assert result.final_script is not None and os.path.exists(result.final_script)
print(f"state={result.status} retries={len(result.retries)}")
PY
done
echo "L2 OK"
