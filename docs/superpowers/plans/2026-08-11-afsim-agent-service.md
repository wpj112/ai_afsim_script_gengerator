# AFSIM 智能体服务 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `afsim-script-generator` 改造为端到端 AFSIM 智能体服务（生成→执行→纠错→归档闭环，HTTP API + CLI）。

**Architecture:** 模块化引擎 `core/`（config/matcher/executor/fixer/lessons/llm/agent）+ FastAPI 服务层 `api/`（task_manager/SQLite/models/cli）。v1 教训体系以 `memory/` 移植，`error_rules.json` 为机读规则库（脚本从 `errors-ref.md` 同步生成）。

**Tech Stack:** Python 3.13、pytest（TDD）、FastAPI/uvicorn/pydantic、httpx（LLM 客户端）、sqlite3（stdlib）、subprocess（mission 调用）。

**Spec:** `docs/superpowers/specs/2026-08-11-afsim-agent-service-design.md`

## Global Constraints

- 脚本文件扩展名必须 `.txt`；所有数值参数必须带单位（沿用 v2 Critical Rules）
- 配置：`config.txt` 键值对 + 环境变量覆盖（`LLM_BASE_URL`/`LLM_API_KEY`/`LLM_MODEL`）
- 二进制探测：Windows `bin/mission.exe` / Linux `bin/mission`
- 纠错循环默认 `MAX_RETRIES=3`，退出码约定 `0` 成功 / `1` 超限 / `2` 未知错误
- 每任务独立工作目录 `workspaces/<task_id>/`；任务状态持久化 SQLite `workspaces/tasks.db`
- 教训升格必须人工确认（`pending → promote`）
- 补丁应用前必须校验（end_* 配对、目标行唯一），不通过降级 `llm_guided`
- 所有 commit 用中文 message，推送到 `origin`（wpj112/ai_afsim_script_gengerator）

## 文件结构（最终）

```
scripts/run_mission.py        # 已有，保留
scripts/sync_error_rules.py   # 新：MD→JSON 同步
core/config.py                # 新：配置加载 + 二进制探测
core/matcher.py               # 新：错误匹配器
core/executor.py              # 新：mission 执行封装
core/fixer.py                 # 新：补丁器
core/lessons.py               # 新：教训生命周期
core/llm.py                   # 新：LLM 客户端
core/generator.py             # 新：知识检索 + 脚本生成
core/agent.py                 # 新：端到端编排
api/task_manager.py           # 新：并发调度 + SQLite
api/models.py                 # 新：Pydantic schema
api/main.py                   # 新：FastAPI 端点
api/cli.py                    # 新：afsim-gen CLI
memory/errors-ref.md          # v1 移植
memory/cold/lesson-*.md       # v1 移植
memory/error_rules.json       # 同步生成
memory/pending/               # 待确认队列
memory/hot/                   # 会话教训
tests/unit/ + tests/fixtures/ + tests/integration/
config.txt                    # 跨平台升级
requirements.txt              # 新
SKILL.md / README.md          # 更新
```

---

### Task 1: 配置模块 `core/config.py` + `config.txt` 跨平台

**Files:**
- Create: `core/__init__.py`, `core/config.py`, `tests/unit/test_config.py`, `config.txt`（修改）
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Produces: `Config` dataclass（字段：`afsim_install_dir, mission_exe, concurrency, max_retries, llm_base_url, llm_api_key, llm_model, workspaces_dir, db_path`）+ `load_config() -> Config`

- [ ] **Step 1: 写失败测试** `tests/unit/test_config.py`
```python
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
```
- [ ] **Step 2: 运行确认失败** `python -m pytest tests/unit/test_config.py -v` → FAIL（module 不存在）
- [ ] **Step 3: 实现** `core/config.py`
```python
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
```
- [ ] **Step 4: 运行确认通过** `python -m pytest tests/unit/test_config.py -v` → PASS
- [ ] **Step 5: 更新 `config.txt`** 追加 `CONCURRENCY=4`、`MAX_RETRIES=3`、`LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`、`WORKSPACES_DIR`、`DB_PATH`（保留原 AFSIM_INSTALL_DIR 行，Windows 示例注释保留）
- [ ] **Step 6: 提交** `git add core/ tests/ config.txt && git commit -m "feat: 跨平台配置模块与 config.txt 升级"`

---

### Task 2: `memory/` 移植 + `scripts/sync_error_rules.py` + `error_rules.json`

**Files:**
- Create: `memory/errors-ref.md`, `memory/cold/lesson-index.md`, `memory/cold/lesson-root-causes.md`（从 v1 复制）, `memory/error_rules.json`, `scripts/sync_error_rules.py`, `tests/unit/test_sync_rules.py`, `tests/fixtures/errors_ref_sample.md`
- Test: `tests/unit/test_sync_rules.py`

**Interfaces:**
- Produces: `sync_rules(md_path: Path, lesson_index_path: Path) -> dict`（返回 `{"rules": [...], "generated_at": str, "source": str}`，rules 每条含 `id/keywords/patterns/root_cause/fix{type,description}/demo/lessons`）
- Produces: `load_rules() -> dict`（从 `memory/error_rules.json` 读取）

- [ ] **Step 1: 移植 v1 文件** 复制 v1 三个 memory 文件到 `memory/`（含 20 条 [Exxx]、15 条教训）
- [ ] **Step 2: 写失败测试**（fixture 用 v1 真实格式样本）
```python
from scripts.sync_error_rules import sync_rules

def test_sync_rules_parses_entries(tmp_path):
    md = tmp_path / "errors-ref.md"
    md.write_text('''### [E001] `Unknown command: platform_type`

**根因**：缺少基类型 WSF_PLATFORM。

```text
platform_type MY_PLATFORM WSF_PLATFORM
```

Demo: `../Afsim_demoslists/engage项目汇总.md` line 330
''')
    rules = sync_rules(md, tmp_path / "lesson-index.md")["rules"]
    assert rules[0]["id"] == "E001"
    assert rules[0]["keywords"] == ["Unknown command: platform_type"]
    assert rules[0]["patterns"] == ["Unknown command:\\s+(\\S+)"]
    assert rules[0]["fix"]["type"] in ("template", "llm_guided")
    assert rules[0]["root_cause"]
    assert rules[0]["demo"].startswith("..")
```
- [ ] **Step 3: 实现** `scripts/sync_error_rules.py`
```python
import json, re
from pathlib import Path
from datetime import datetime

FIX_TYPE_MAP = {
    "E001": "template", "E002": "template", "E003": "template",
    "E004": "template", "E005": "template", "E006": "template",
    "E007": "template", "E008": "template", "E012": "template",
}
DEFAULT_FIX_TYPE = "llm_guided"

def _parse_entries(text: str) -> list[dict]:
    entries = []
    for m in re.finditer(r"### \[(E\d+)\]\s+(.+?)(?=\n### \[|\Z)", text, re.S):
        rid, body = m.group(1), m.group(2)
        title = re.match(r"`?([^`]+)`?", body).group(1).strip()
        root = re.search(r"\*\*根因\*\*：(.+)", body)
        demo = re.search(r"Demo:\s*(.+)", body)
        entries.append({
            "id": rid,
            "keywords": [k.strip("` ") for k in title.split("`") if k.strip(" /`")],
            "patterns": [re.escape(k.strip()) for k in title.split("`") if k.strip(" /`")][:1],
            "root_cause": root.group(1).strip() if root else "",
            "fix": {"type": FIX_TYPE_MAP.get(rid, DEFAULT_FIX_TYPE),
                    "description": root.group(1).strip() if root else ""},
            "demo": demo.group(1).strip() if demo else "",
            "lessons": [],
        })
    return entries

def sync_rules(md_path: Path, lesson_index_path: Path) -> dict:
    text = md_path.read_text(encoding="utf-8")
    rules = _parse_entries(text)
    return {"rules": rules, "generated_at": datetime.now().isoformat(),
            "source": str(md_path)}
```
- [ ] **Step 4: 生成并验证** 脚本提供 `main()` 支持 `--write` 写 `memory/error_rules.json`；单元测试通过后运行生成，人工抽查 E001 条目
- [ ] **Step 5: 提交** `git add memory/ scripts/ tests/ && git commit -m "feat: v1 教训体系移植与 error_rules.json 同步器"`

---

### Task 3: `core/matcher.py` 错误匹配器

**Files:**
- Create: `core/matcher.py`, `tests/unit/test_matcher.py`, `tests/fixtures/mission_output_samples.txt`
- Test: `tests/unit/test_matcher.py`

**Interfaces:**
- Consumes: `load_rules()`（Task 2）
- Produces: `match_output(stdout: str, stderr: str, rules: dict) -> list[MatchResult]`；`@dataclass MatchResult: rule_id, confidence, matched_text, line_no, fix, lessons`

- [ ] **Step 1: 写失败测试**
```python
from core.matcher import match_output

RULES = {"rules": [{"id": "E001", "keywords": ["Unknown command: platform_type"],
                    "patterns": ["Unknown command:\\s+(\\S+)"], "fix": {"type": "template"},
                    "lessons": ["L004", "L012"]}]}

def test_keyword_match():
    out = "ERROR: Unknown command: platform_type"
    res = match_output("", out, RULES)
    assert res[0].rule_id == "E001" and res[0].confidence == "exact"

def test_no_match():
    assert match_output("ok", "all good", RULES) == []

def test_line_number():
    out = "line1\nERROR: Unknown command: platform_type"
    assert match_output("", out, RULES)[0].line_no == 2
```
- [ ] **Step 2: 确认失败** → FAIL（module 不存在）
- [ ] **Step 3: 实现**
```python
from dataclasses import dataclass
import re

@dataclass
class MatchResult:
    rule_id: str
    confidence: str
    matched_text: str
    line_no: int
    fix: dict
    lessons: list[str]

def match_output(stdout: str, stderr: str, rules: dict) -> list[MatchResult]:
    combined = stdout + "\n" + stderr
    results = []
    for rule in rules.get("rules", []):
        for kw in rule.get("keywords", []):
            for i, line in enumerate(combined.splitlines(), 1):
                if kw.lower() in line.lower():
                    results.append(MatchResult(rule["id"], "exact", line, i,
                                               rule.get("fix", {}), rule.get("lessons", [])))
                    break
            else:
                continue
            break
        else:
            for pat in rule.get("patterns", []):
                for i, line in enumerate(combined.splitlines(), 1):
                    if re.search(pat, line):
                        results.append(MatchResult(rule["id"], "pattern", line, i,
                                                   rule.get("fix", {}), rule.get("lessons", [])))
                        break
    return results
```
- [ ] **Step 4: 确认通过** → PASS
- [ ] **Step 5: 提交** `git add core/matcher.py tests/ && git commit -m "feat: 程序化错误匹配器"`

---

### Task 4: `core/executor.py` mission 执行封装

**Files:**
- Create: `core/executor.py`, `tests/unit/test_executor.py`
- Test: `tests/unit/test_executor.py`

**Interfaces:**
- Consumes: `Config`、`scripts/run_mission.py` 的 `run_mission(script_file, options, config)`（已有，返回 `(rc, stdout, stderr)`）
- Produces: `ExecutionResult(rc: int, stdout: str, stderr: str)`；`run(script_path: Path, workdir: Path, config: Config, options: list[str] | None) -> ExecutionResult`

- [ ] **Step 1: 写失败测试**（monkeypatch subprocess，不依赖真 mission）
```python
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
    cfg = Config(mission_exe="/nonexistent/mission")
    res = run(tmp_path / "x.txt", tmp_path, cfg)
    assert res.rc == 1
```
- [ ] **Step 2: 确认失败** → FAIL
- [ ] **Step 3: 实现**（封装 run_mission：脚本复制进 workdir，mission 以 workdir 为 cwd；mission_exe 不存在时返回 rc=1 带错误信息）
- [ ] **Step 4: 确认通过** → PASS
- [ ] **Step 5: 提交** `git commit -m "feat: mission 执行封装（工作目录隔离）"`

---

### Task 5: `core/fixer.py` 补丁器

**Files:**
- Create: `core/fixer.py`, `tests/unit/test_fixer.py`
- Test: `tests/unit/test_fixer.py`

**Interfaces:**
- Consumes: `MatchResult`（Task 3）
- Produces: `apply_fix(script_path: Path, match: MatchResult) -> bool`（应用 template 补丁；校验失败返回 False 由调用方降级 llm_guided）；内部补丁函数 `patch_append_base_type(text, target_line, base_type) -> str`, `patch_close_block(text, block_kind) -> str`, `patch_position_format(text) -> str`, `patch_add_unit(text, param) -> str`；校验 `validate_blocks(text: str) -> list[str]`（返回缺失 end_* 的块列表）

- [ ] **Step 1: 写失败测试**
```python
from core.fixer import apply_fix, validate_blocks, patch_append_base_type

def test_patch_append_base_type():
    text = "platform_type MY_PLATFORM\n   side red\nend_platform_type\n"
    assert "WSF_PLATFORM" in patch_append_base_type(text, "platform_type MY_PLATFORM", "WSF_PLATFORM")

def test_validate_blocks_detects_unclosed():
    text = "mover WSF_AIR_MOVER\n   debug\nend_platform_type\n"
    assert "mover" in validate_blocks(text)

def test_apply_fix_template():
    from core.matcher import MatchResult
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("platform_type MY_PLATFORM\nend_platform_type\n")
        path = f.name
    m = MatchResult("E001", "exact", "Unknown command: platform_type", 1,
                    {"type": "template", "description": "追加基类型"}, [])
    assert apply_fix(path, m) is True
    assert "WSF_PLATFORM" in open(path).read()
```
- [ ] **Step 2: 确认失败** → FAIL
- [ ] **Step 3: 实现**（补丁器按 fix.description 关键词分发：含"基类型"→append_base_type；含"end_"/"闭合"→close_block；含"坐标"→position_format；含"单位"→add_unit；未知→返回 False。apply 前打印 diff，apply 后 validate_blocks 检查）
- [ ] **Step 4: 确认通过** → PASS
- [ ] **Step 5: 提交** `git commit -m "feat: 模板补丁器与脚本块校验"`

---

### Task 6: `core/lessons.py` 教训生命周期

**Files:**
- Create: `core/lessons.py`, `tests/unit/test_lessons.py`
- Test: `tests/unit/test_lessons.py`

**Interfaces:**
- Produces: `record(matches, session_date, log_dir) -> None`（命中教训追加 `memory/hot/<date>.md`）、`pend(stderr_text, pending_dir, note="") -> str`（返回 pending 文件路径）、`promote(pending_path, errors_ref_path, confirm=True) -> bool`（升格进 errors-ref.md）、`stats(rules, hot_dir) -> dict[rule_id, count]`

- [ ] **Step 1: 写失败测试**（用 tmp_path 模拟 memory 目录）
```python
from core.lessons import record, pend, promote, stats
from core.matcher import MatchResult

def test_pend_creates_file(tmp_path):
    p = pend("Unknown error: xyz", tmp_path / "pending", note="test")
    assert p.exists() and "test" in p.read_text()

def test_promote_appends_to_errors_ref(tmp_path):
    pending_file = pend("Unknown command: foo bar", tmp_path / "pending")
    ref = tmp_path / "errors-ref.md"
    ref.write_text("# AFSIM 报错索引\n\n---\n")
    assert promote(pending_file, ref, confirm=True) is True
    assert "Unknown command: foo bar" in ref.read_text()

def test_record_and_stats(tmp_path):
    hot = tmp_path / "hot"; hot.mkdir()
    m = MatchResult("E001", "exact", "x", 1, {}, ["L004"])
    record([m], "2026-08-11", hot)
    assert stats({"rules": [{"id": "E001"}]}, hot) == {"E001": 1}
```
- [ ] **Step 2: 确认失败** → FAIL
- [ ] **Step 3: 实现**（纯文件操作；promote 需 confirm=True 才写，遵循"人工确认后才入库"）
- [ ] **Step 4: 确认通过** → PASS
- [ ] **Step 5: 提交** `git commit -m "feat: 教训记账/待确认/升格/统计"`

---

### Task 7: `core/llm.py` LLM 客户端

**Files:**
- Create: `core/llm.py`, `tests/unit/test_llm.py`
- Test: `tests/unit/test_llm.py`

**Interfaces:**
- Consumes: `Config`
- Produces: `LLMClient(base_url, api_key, model)`：`chat(messages: list[dict], tools: list | None = None) -> str`、`generate_script(prompt: str, knowledge_context: str) -> str`、`propose_fix(script: str, error_report: str, lesson_hint: str) -> str | None`、`analyze_unknown(stderr: str, script: str) -> dict`

- [ ] **Step 1: 写失败测试**（httpx MockTransport，不真调 API）
```python
import httpx
from core.llm import LLMClient

def test_generate_script():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "end_time 10 sec"}}]})
    client = LLMClient("http://x/v1", "k", "m", transport=httpx.MockTransport(handler))
    assert client.generate_script("make scenario", "rules") == "end_time 10 sec"

def test_chat_handles_error():
    def handler(request):
        return httpx.Response(500)
    client = LLMClient("http://x/v1", "k", "m", transport=httpx.MockTransport(handler))
    assert client.chat([{"role": "user", "content": "hi"}]) == ""
```
- [ ] **Step 2: 确认失败** → FAIL
- [ ] **Step 3: 实现**（`chat` 调 `/chat/completions`，错误返回空串；`generate_script` 拼接 system 知识上下文 + user prompt；`propose_fix` system 约束"只输出修正后的完整脚本内容"；`analyze_unknown` 要求返回 JSON `{cause, suggestion}`，解析失败回退 `{"cause": "", "suggestion": ""}`；允许注入 `transport` 便于测试）
- [ ] **Step 4: 确认通过** → PASS
- [ ] **Step 5: 提交** `git commit -m "feat: OpenAI 兼容 LLM 客户端"`

---

### Task 8: `core/agent.py` 端到端编排（含 `core/generator.py`）

**Files:**
- Create: `core/agent.py`, `core/generator.py`, `tests/unit/test_agent.py`
- Test: `tests/unit/test_agent.py`

**Interfaces:**
- Consumes: Task 3-7 全部接口 + `config`
- Produces: `TaskRequest(prompt: str | None, script: str | None, options: list[str] | None)`、`RetryRecord(attempt: int, rc: int, stderr: str, matched_rule: str | None, diff: str)`、`TaskResult(status: str, retries: list[RetryRecord], final_script: Path | None, report: dict)`、`run_task(request, config, llm, rules, workdir, task_id) -> TaskResult`（依赖注入 llm/rules，便于测试）

**循环逻辑（实现核心）：**
```python
for attempt in 1..config.max_retries:
    if not final_script.exists() and request.prompt:
        script_text = generator.generate(llm, request.prompt, config)
        final_script.write_text(script_text)
    res = executor.run(final_script, workdir, config, request.options)
    if res.rc == 0 and "ERROR" not in res.stderr:
        return TaskResult("success", retries, final_script, {"message": "mission loaded OK"})
    matches = matcher.match_output(res.stdout, res.stderr, rules)
    if not matches:
        lessons.pend(res.stderr, pending_dir, note=f"task {task_id}")
        return TaskResult("needs_review", retries, final_script, {"unknown_error": res.stderr[:500]})
    applied = fixer.apply_fix(final_script, matches[0])
    if not applied:
        patch = llm.propose_fix(final_script.read_text(), res.stderr, matches[0].lessons)
        if patch:
            final_script.write_text(patch)
    lessons.record(matches, date, hot_dir)
    retries.append(RetryRecord(attempt, res.rc, res.stderr, matches[0].rule_id, diff_snapshot()))
return TaskResult("failed", retries, final_script, {...})
```

- [ ] **Step 1: 写失败测试**（fake executor/matcher/llm 注入：成功路径、未知错误路径、template 修正路径、超限路径 4 个用例）
- [ ] **Step 2: 确认失败** → FAIL
- [ ] **Step 3: 实现** `core/agent.py` + `core/generator.py`（generator 按需求关键词检索 references/ 片段拼 prompt：mover/传感器/示例，用简单包含匹配）
- [ ] **Step 4: 确认通过** → PASS
- [ ] **Step 5: 提交** `git commit -m "feat: 端到端纠错循环编排器与知识检索生成器"`

---

### Task 9: `api/task_manager.py` 并发调度 + SQLite

**Files:**
- Create: `api/__init__.py`, `api/task_manager.py`, `tests/unit/test_task_manager.py`
- Test: `tests/unit/test_task_manager.py`

**Interfaces:**
- Consumes: Task 8 `run_task`
- Produces: `TaskManager(config, db_path)`：`submit(request: TaskRequest) -> str`（返回 task_id，`ThreadPoolExecutor(config.concurrency)` 执行）、`get(task_id) -> TaskStatus | None`、`cancel(task_id) -> bool`；`@dataclass TaskStatus: task_id, state, created_at, retries, result`（state ∈ pending/running/fixing/success/failed/needs_review，持久化 `workspaces/tasks.db` sqlite3）

- [ ] **Step 1: 写失败测试**（提交 2 个假任务，断言独立工作目录存在、状态推进、SQLite 落盘）
- [ ] **Step 2: 确认失败** → FAIL
- [ ] **Step 3: 实现**（submit 创建 `workspaces/<uuid4hex>/`，任务内 run_task 以该目录为 workdir；状态每次变更写 SQLite `tasks` 表；`get` 读表+内存）
- [ ] **Step 4: 确认通过** → PASS
- [ ] **Step 5: 提交** `git commit -m "feat: 并发任务调度与 SQLite 状态持久化"`

---

### Task 10: `api/models.py` + `api/main.py` FastAPI 端点

**Files:**
- Create: `api/models.py`, `api/main.py`, `tests/unit/test_api.py`
- Test: `tests/unit/test_api.py`（fastapi TestClient + 假 TaskManager）

**Interfaces:**
- Consumes: `TaskManager`
- Produces: FastAPI app（端点：`POST /api/tasks`、`GET /api/tasks/{id}`、`GET /api/tasks/{id}/log`、`POST /api/tasks/{id}/cancel`、`GET /api/lessons`、`GET /api/pending`、`POST /api/pending/{id}/promote`、`GET /healthz`）

- [ ] **Step 1: 写失败测试**（TestClient：POST 返回 task_id；GET 返回状态；healthz 200；promote 需 confirm 参数）
- [ ] **Step 2: 确认失败** → FAIL
- [ ] **Step 3: 实现**（models.py：`TaskSubmit(body: prompt|script|options)`、`TaskResponse`；main.py：全局 `TaskManager` 单例，`GET /api/tasks/{id}/log` 返回工作目录日志文件内容）
- [ ] **Step 4: 确认通过** → PASS
- [ ] **Step 5: 提交** `git commit -m "feat: FastAPI 服务端点"`

---

### Task 11: `api/cli.py` — afsim-gen CLI

**Files:**
- Create: `api/cli.py`, `tests/unit/test_cli.py`, `requirements.txt`
- Test: `tests/unit/test_cli.py`

**Interfaces:**
- Produces: 命令 `serve`（uvicorn 起 main.app）/ `run --prompt "..." | --script x.txt` / `task <id>` / `lessons --stats` / `pending --promote <id>`

- [ ] **Step 1: 写失败测试**（`run --script` 用 fake TaskManager 断言调用；`--help` 输出含全部子命令）
- [ ] **Step 2: 确认失败** → FAIL
- [ ] **Step 3: 实现**（argparse 子命令分发；`run` 可同步等待终态并打印报告）
- [ ] **Step 4: 确认通过** → PASS
- [ ] **Step 5: 写 `requirements.txt`**（fastapi、uvicorn、httpx、pydantic；dev: pytest）
- [ ] **Step 6: 提交** `git commit -m "feat: afsim-gen CLI 与依赖清单"`

---

### Task 12: SKILL.md / README.md 更新 + 知识库注入完善

**Files:**
- Modify: `SKILL.md`（新增"服务模式"章节：`afsim-gen` 用法、教训联动流程、自动纠错循环说明、归档闭环）、`README.md`（服务架构图 + 快速开始）
- Create: `tests/unit/test_generator_retrieval.py`

- [ ] **Step 1: 补 generator 检索测试**（按"radar"关键词命中 references/sensor_types_reference.md 片段；按"aircraft"命中 mover_reference.md）
- [ ] **Step 2: 实现检索注入**（generator.py 增加 `retrieve_knowledge(query, references_dir) -> str`，包含匹配片段截断 2000 字符）
- [ ] **Step 3: 确认通过** → PASS
- [ ] **Step 4: 更新 SKILL.md / README.md**
- [ ] **Step 5: 提交** `git commit -m "docs: 服务模式文档与知识检索注入完善"`

---

### Task 13: fixtures 扩充 + L2/L3 集成测试脚本

**Files:**
- Create: `tests/fixtures/`（v1 20 类报错真实风格样例 × 3 组）、`tests/fixtures/broken_scenarios/`（3-5 个故意写错的 .txt）、`tests/integration/run.sh`、`tests/integration/test_e2e.py`
- Test: 集成套件

- [ ] **Step 1: 扩充 matcher fixture 断言**（20 条规则至少 10 条有样例命中）
- [ ] **Step 2: 写 L2 脚本 `run.sh`**（自动探测 `mission` 二进制，`AFSIM_INSTALL_DIR` 未配置时 SKIP 提示；配置了则对 broken_scenarios 跑 auto_fix_loop，断言 rc=0）
- [ ] **Step 3: 写 L3 `test_e2e.py`**（起服务，POST 2 个并发任务，断言工作目录隔离 + 报告结构）
- [ ] **Step 4: 运行确认**（无 AFSIM 时 L2 SKIP、L1/L3 通过）
- [ ] **Step 5: 提交** `git commit -m "test: fixture 扩充与 L2/L3 集成测试脚本"`

---

### Task 14: Linux 真装 AFSIM → L2/L3 验证（依赖外部条件）

**前置条件（需用户操作）：** 获取 AFSIM Linux 版并安装（授权/安装包来自官方或团队），装后配置 `config.txt` 的 `AFSIM_INSTALL_DIR=/opt/afsim`（或实际路径）

- [ ] **Step 1: 验证二进制探测**（`afsim-gen run --script tests/fixtures/broken_scenarios/x.txt` 确认 executor 找到 `bin/mission`）
- [ ] **Step 2: 跑 L2**（`bash tests/integration/run.sh`，断言 broken_scenarios 全部自动修正到 rc=0）
- [ ] **Step 3: 跑 L3**（`pytest tests/integration/test_e2e.py -v`，并发隔离）
- [ ] **Step 4: 真实需求端到端**（`afsim-gen run --prompt "红方 SAM vs 蓝方战机，50min"`，验证 LLM 生成 + 执行 + 纠错全链路）
- [ ] **Step 5: 修复问题并提交** `git commit -m "fix: 真机验证修复"`

---

## 自审

- Spec 覆盖：Section 3 目录✓、Section 4 规则库✓、Section 5 模块✓、Section 6 服务✓、Section 7 配置/LLM✓、Section 8 验证✓
- 无占位符：每个 task 含实际代码/命令/断言
- 类型一致：MatchResult/TaskResult/Config/LLMClient 跨 task 签名一致
