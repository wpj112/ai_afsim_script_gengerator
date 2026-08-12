# 多轮会话（基于已有脚本的对话式修改）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让服务支持"基于一个脚本进行多轮对话修改"——会话首轮用 prompt 生成或上传脚本，后续每轮输入自然语言指令，基于当前脚本产出新脚本并每轮经 mission 验证。

**Architecture:** 在现有任务式模型上叠加"会话"概念：SQLite 新增 `conversations`、`conversation_turns` 两表，`tasks` 表迁移加 `conversation_id` 列。修改轮复用现有 agent 验证/修复管线：`TaskRequest` 新增 `instruction` 字段，agent 在 `instruction + script` 同时存在时走"LLM 整脚本重写 → normalize → mission 验证 → matcher/fixer 修复循环"。LLM 上下文只发【当前脚本全文 + 本轮指令】，不携带历史。

**Tech Stack:** Python 3.10+，FastAPI，SQLite（threading + lock 并发模型），httpx，pytest；前端为原生 HTML/JS（无框架）。

## Global Constraints

- 现有 `/api/tasks` 等全部端点必须保留且行为不变；`tasks.conversation_id` 为 NULL 表示旧式独立任务
- `conversations.current_task_id` 只指向**最后成功**的一轮（`_run` 中 `result.status == "success"` 时才更新；失败轮不更新）
- 修改轮 LLM 上下文只含【当前脚本全文 + 本轮指令 + 知识上下文】，绝不携带历史轮次
- 每轮修改都走完整验证循环（normalize → executor → matcher/fixer），与现有生成任务相同
- task_id / conversation_id 均沿用 32 位十六进制 uuid4 hex；路径操作沿用现有 `is_relative_to` 防穿越校验
- 所有测试不得依赖真实 AFSIM 或真实 LLM（沿用现有 monkeypatch + FakeLLM 模式）
- 不提交 `.env`、`output/`（已在 .gitignore）
- 每步必须真实运行 pytest 验证通过后再 commit

---

### Task 1: LLM 客户端新增 modify_script

**Files:**
- Modify: `core/llm.py`
- Test: `tests/unit/test_llm.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `LLMClient._build_system_prompt(knowledge_context: str) -> str`（私有，提取现有 system 规则）
  - `LLMClient.modify_script(script: str, instruction: str, knowledge_context: str) -> str`（LLM 失败时返回 `""`，`last_error` 置位）

- [ ] **Step 1: 写失败测试**，追加到 `tests/unit/test_llm.py` 末尾：

```python
def test_modify_script_message_structure():
    captured = {}

    def handler(request):
        captured["body"] = request.read()
        return httpx.Response(200, json={"choices": [{"message": {"content": "modified"}}]})

    client = LLMClient("http://x/v1", "k", "m", transport=httpx.MockTransport(handler))
    assert client.modify_script("platform A FIGHTER\n", "把速度改成450节", "rules") == "modified"
    body = captured["body"]
    assert b"platform A FIGHTER" in body
    assert b"\xe6\x8a\x8a\xe9\x80\x9f\xe5\xba\xa6\xe6\x94\xb9\xe6\x88\x90450\xe8\x8a\x82" in body
    assert b"rules" in body
    assert b"7200 sec" in body
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_llm.py::test_modify_script_message_structure -v`
Expected: FAIL，`AttributeError: 'LLMClient' object has no attribute 'modify_script'`

- [ ] **Step 3: 实现**。修改 `core/llm.py`：将 `generate_script` 中的 system 规则提取为 `_build_system_prompt`，并新增 `modify_script`：

```python
    def _build_system_prompt(self, knowledge_context):
        return (
            "你是 AFSIM 脚本生成专家。严格遵循以下规则："
            "只输出完整 AFSIM 脚本正文，不要输出 Markdown 代码围栏、解释、推理过程或空内容；"
            "必须使用 AFSIM/WSF 文本块语法：块以关键字开头，以 end_关键字结束；"
            "严禁使用 C/JSON 风格的大括号 `{}` 或方括号 `[]` 包裹 AFSIM 块；"
            "平台实例使用 route/end_route 和 position ... altitude ... speed ...，不要使用 start_location；"
            "仿真结束必须写成单行 `end_time <duration> sec`，禁止生成 `time ... end_time` 时间块；"
            f"仿真结束时间至少为 `{self.default_end_time_sec} sec`；短于该值时必须写 `end_time {self.default_end_time_sec} sec`；"
            f"`route` 必须采用官方 `navigation` 子块：`route -> navigation -> position ... -> speed {self.default_route_speed} -> end_navigation -> end_route`；"
            "同一个 `route/navigation` 内相邻两个 `position` 的经纬度不能完全相同；"
            "`script_interface` 内启用调试只能写 `debug`，不要写 `enable_debug`；"
            "传感器类型必须使用完整 WSF 类型名，如 `sensor RADAR_NAME WSF_RADAR_SENSOR`，不要写 `sensor ... RADAR`；"
            "当前 Linux AFSIM 镜像已验证的通用武器类型使用 `weapon NAME WSF_EXPLICIT_WEAPON`；不要写 `weapon ... missile`、`AA_MISSILE` 或 `WSF_AIR_TO_AIR_MISSILE`；"
            "`antenna_pattern` 内必须写 `constant_pattern ... end_constant_pattern`，增益写 `peak_gain`，不要写裸 `gain` 或 `beamwidth`；"
            "默认优先生成可加载骨架：`platform_type` 内只写 `mover WSF_AIR_MOVER ... end_mover`；不要用 `sensor NAME`、`weapon NAME`、`processor NAME` 这种外部引用行；"
            "`platform` 实例内也不要用 `sensor NAME/end_sensor` 或 `weapon NAME/end_weapon` 这种挂载块；先只写 side 和 route；"
            "Warlock 可视化标识写在 `platform_type` 中：雷达平台使用 `icon radar` 和 `category radar`；SAM/导弹平台使用 `icon missile` 和 `category missile`；战斗机/飞机平台使用 `icon fighter` 和 `category aircraft`；"
            "雷达平台和 SAM/导弹平台不能共用同一个 `platform_type`，否则 Warlock 会显示成同一种图标；"
            "优先生成最小可运行场景；不确定的传感器、武器、通信、气动参数直接省略，不要编造命令；"
            "1) 脚本文件必须以 .txt 扩展名保存；"
            "2) 速度、时间、高度、距离等参数必须带单位（如 kts、sec、ft msl）；"
            "3) 所有块必须以对应的 end_ 关键字闭合（如 end_platform_type、end_mover）；"
            "4) 坐标使用 d:m:s N/S e/w 格式；"
            "5) 至少包含 end_time，且脚本不能为空。"
            "以下是与本次生成相关的知识上下文：\n" + knowledge_context
        )

    def generate_script(self, prompt, knowledge_context):
        messages = [
            {"role": "system", "content": self._build_system_prompt(knowledge_context)},
            {"role": "user", "content": prompt},
        ]
        return self.chat(messages)

    def modify_script(self, script, instruction, knowledge_context):
        user = (
            f"这是当前 AFSIM 脚本：\n{script}\n\n"
            f"请根据以下修改要求，输出修改后的完整 AFSIM 脚本。"
            f"仅输出修改后的完整脚本正文，保持原有结构与有效参数：\n{instruction}"
        )
        return self.chat([
            {"role": "system", "content": self._build_system_prompt(knowledge_context)},
            {"role": "user", "content": user},
        ])
```

- [ ] **Step 4: 运行全部 llm 测试确认通过**

Run: `python -m pytest tests/unit/test_llm.py -v`
Expected: 全部 PASS（含原有 11 个用例 + 新用例）

- [ ] **Step 5: Commit**

```bash
git add core/llm.py tests/unit/test_llm.py
git commit -m "feat: LLM 客户端新增 modify_script 多轮修改方法"
```

---

### Task 2: 生成器 modify 与 agent 修改管线

**Files:**
- Modify: `core/generator.py`
- Modify: `core/agent.py`
- Test: `tests/unit/test_agent.py`

**Interfaces:**
- Consumes: `LLMClient.modify_script(script, instruction, knowledge_context) -> str`（Task 1）
- Produces:
  - `generator.modify(llm, script: str, instruction: str, config) -> str`（LLM 输出经 normalize_script 归一化后的完整脚本）
  - `agent.TaskRequest.instruction: str | None = None`（新字段，追加到 dataclass 末尾）
  - `agent.TaskRequest.conversation_id: str | None = None`（新字段，追加到 dataclass 末尾）
  - `run_task` 行为：`instruction` 非空且 `script` 非空时，首轮走修改管线（modify），不再走 generate；`instruction` 非空但 `script` 为空时直接返回 `TaskResult("failed", [], None, {"error": "no script for instruction"})`

- [ ] **Step 1: 写失败测试**，追加到 `tests/unit/test_agent.py` 末尾：

```python
def test_instruction_uses_modify_script_not_generate(tmp_path, monkeypatch):
    calls = {"modify": None, "generate": 0}
    monkeypatch.setattr(executor, "run", lambda p, w, c, options=None: ExecutionResult(0, "", ""))

    class ModifyLLM:
        def generate_script(self, prompt, ctx):
            calls["generate"] += 1
            raise AssertionError("generate_script must not be called")

        def modify_script(self, script, instruction, ctx):
            calls["modify"] = (script, instruction)
            return "platform A FIGHTER\n"

    result = run_task(
        TaskRequest(script="platform B FIGHTER\n", instruction="把 A 改成 B"),
        Config(max_retries=3),
        ModifyLLM(),
        {},
        tmp_path,
        "t10",
    )
    assert result.status == "success"
    assert calls["generate"] == 0
    assert calls["modify"] == ("platform B FIGHTER\n", "把 A 改成 B")
    assert (tmp_path / "scenario.txt").read_text() == "platform A FIGHTER\nend_time 7200 sec\n"


def test_instruction_without_script_fails(tmp_path, monkeypatch):
    calls = {"run": 0}

    def fake_run(p, w, c, options=None):
        calls["run"] += 1
        return ExecutionResult(0, "", "")

    monkeypatch.setattr(executor, "run", fake_run)
    result = run_task(
        TaskRequest(instruction="改成红方"),
        Config(max_retries=3),
        SimpleNamespace(modify_script=lambda s, i, c: "x\n"),
        {},
        tmp_path,
        "t11",
    )
    assert result.status == "failed"
    assert result.report == {"error": "no script for instruction"}
    assert calls["run"] == 0
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_agent.py::test_instruction_uses_modify_script_not_generate tests/unit/test_agent.py::test_instruction_without_script_fails -v`
Expected: FAIL（TaskRequest 无 instruction 属性 / generator 无 modify）

- [ ] **Step 3: 实现**。`core/generator.py` 在 `generate` 函数后新增：

```python
def modify(llm, script, instruction, config):
    refs_dir = Path(__file__).resolve().parent.parent / "references"
    knowledge_context = retrieve_knowledge(instruction, refs_dir)
    min_end_time_sec = getattr(config, "default_end_time_sec", 7200) if config is not None else 7200
    default_route_speed = getattr(config, "default_route_speed", "450 kts") if config is not None else "450 kts"
    return normalize_script(
        llm.modify_script(script, instruction, knowledge_context),
        min_end_time_sec=min_end_time_sec,
        default_route_speed=default_route_speed,
    )
```

`core/agent.py` 修改三处：

1. import 处（L8）：`from core.generator import generate` → `from core.generator import generate, modify`
2. `TaskRequest` dataclass（L14-18）追加两个字段：

```python
@dataclass
class TaskRequest:
    prompt: str | None = None
    script: str | None = None
    options: list[str] | None = None
    instruction: str | None = None
    conversation_id: str | None = None
```

3. `run_task` 的 `for attempt` 循环内（L48-61），在 `if not final_script.exists():` 块的最前面插入修改分支：

```python
        if not final_script.exists():
            if request.instruction:
                if not request.script:
                    return TaskResult("failed", retries, None, {"error": "no script for instruction"})
                final_script.write_text(
                    modify(llm, request.script, request.instruction, config),
                    encoding="utf-8",
                )
            elif request.script:
```

（原有 `elif request.script:` 及其后续分支保持不变）

- [ ] **Step 4: 运行全部 agent 测试确认通过**

Run: `python -m pytest tests/unit/test_agent.py -v`
Expected: 全部 PASS（原有 10 个 + 新 2 个）

- [ ] **Step 5: Commit**

```bash
git add core/generator.py core/agent.py tests/unit/test_agent.py
git commit -m "feat: agent 支持 instruction 修改管线（整脚本重写+验证循环）"
```

---

### Task 3: TaskManager 会话存储与 CRUD

**Files:**
- Modify: `api/task_manager.py`
- Test: `tests/unit/test_task_manager.py`

**Interfaces:**
- Consumes: `agent.TaskRequest.instruction`、`agent.TaskRequest.conversation_id`（Task 2）
- Produces:
  - 异常类（模块级）：`ConversationNotFound(Exception)`、`ConversationFinished(Exception)`、`NoCurrentScript(Exception)`、`EmptyInstruction(Exception)`
  - `@dataclass ConversationTurn: round: int, task_id: str, instruction: str | None, state: str | None = None, result: dict | None = None`
  - `@dataclass ConversationStatus: conversation_id: str, created_at: str, initial_prompt: str | None, current_task_id: str | None, state: str, turns: list[ConversationTurn]`
  - `TaskManager.create_conversation(request) -> str`（返回 conversation_id；内部创建首轮任务并记录 turn，round=1，instruction=request.prompt 或 None）
  - `TaskManager.list_conversations(limit=50) -> list[dict]`，每项：`{conversation_id, created_at, initial_prompt, current_task_id, state, turn_count}`
  - `TaskManager.get_conversation(conversation_id) -> ConversationStatus | None`（turns 的 state/result 实时从 tasks 表取）
  - `TaskManager.add_turn(conversation_id, instruction, options=None) -> str`（返回新 task_id；异常见上）
  - `TaskManager.finish_conversation(conversation_id) -> bool`
  - `_run` 内部：成功后（`result.status == "success"`）若 `request.conversation_id` 非空则更新该会话 `current_task_id`

- [ ] **Step 1: 写失败测试**，追加到 `tests/unit/test_task_manager.py` 末尾：

```python
def test_conversation_create_first_turn_and_persist(tmp_path, monkeypatch):
    config = _config(tmp_path)

    def fake_run_task(request, config, llm, rules, workdir, task_id):
        Path(workdir).mkdir(parents=True, exist_ok=True)
        (Path(workdir) / "scenario.txt").write_text(request.script or "generated\n", encoding="utf-8")
        return TaskResult("success", [], None, {"message": "mission loaded OK"})

    monkeypatch.setattr(tm, "run_task", fake_run_task)
    manager = tm.TaskManager(config, llm=object(), rules={"rules": []})
    conv_id = manager.create_conversation(TaskRequest(prompt="生成空战场景", options=["-es"]))

    conversation = manager.get_conversation(conv_id)
    assert conversation is not None
    assert conversation.state == "active"
    assert conversation.initial_prompt == "生成空战场景"
    assert len(conversation.turns) == 1
    assert conversation.turns[0].round == 1
    assert conversation.turns[0].instruction == "生成空战场景"
    assert conversation.turns[0].state == "success"
    assert conversation.current_task_id == conversation.turns[0].task_id

    restarted = tm.TaskManager(config, llm=object(), rules={"rules": []})
    again = restarted.get_conversation(conv_id)
    assert again is not None
    assert again.current_task_id == conversation.turns[0].task_id
    assert len(again.turns) == 1


def test_conversation_add_turn_uses_previous_script(tmp_path, monkeypatch):
    config = _config(tmp_path)
    seen = {}

    def fake_run_task(request, config, llm, rules, workdir, task_id):
        Path(workdir).mkdir(parents=True, exist_ok=True)
        content = request.script or "end_time 7200 sec\n"
        (Path(workdir) / "scenario.txt").write_text(content, encoding="utf-8")
        seen[task_id] = (request.script, request.instruction)
        return TaskResult("success", [], None, {"message": "mission loaded OK"})

    monkeypatch.setattr(tm, "run_task", fake_run_task)
    manager = tm.TaskManager(config, llm=object(), rules={"rules": []})
    conv_id = manager.create_conversation(TaskRequest(script="platform A FIGHTER\n"))
    first_task_id = manager.get_conversation(conv_id).current_task_id
    _wait_terminal(manager, first_task_id)

    task_id = manager.add_turn(conv_id, "再加一架飞机")
    _wait_terminal(manager, task_id)
    conversation = manager.get_conversation(conv_id)
    assert len(conversation.turns) == 2
    assert conversation.turns[1].round == 2
    assert conversation.turns[1].instruction == "再加一架飞机"
    assert conversation.current_task_id == task_id
    assert seen[task_id][0] == "platform A FIGHTER\n"
    assert seen[task_id][1] == "再加一架飞机"


def test_conversation_failed_turn_keeps_previous_current(tmp_path, monkeypatch):
    config = _config(tmp_path)
    calls = {"n": 0}

    def fake_run_task(request, config, llm, rules, workdir, task_id):
        calls["n"] += 1
        Path(workdir).mkdir(parents=True, exist_ok=True)
        (Path(workdir) / "scenario.txt").write_text(request.script or "x\n", encoding="utf-8")
        if calls["n"] == 1:
            return TaskResult("success", [], None, {"message": "mission loaded OK"})
        return TaskResult("failed", [], None, {"max_retries_exceeded": 3})

    monkeypatch.setattr(tm, "run_task", fake_run_task)
    manager = tm.TaskManager(config, llm=object(), rules={"rules": []})
    conv_id = manager.create_conversation(TaskRequest(script="a\n"))
    first_task_id = manager.get_conversation(conv_id).current_task_id
    _wait_terminal(manager, first_task_id)

    bad_task_id = manager.add_turn(conv_id, "改成失败")
    _wait_terminal(manager, bad_task_id)
    conversation = manager.get_conversation(conv_id)
    assert conversation.current_task_id == first_task_id
    assert len(conversation.turns) == 2
    assert conversation.turns[1].state == "failed"


def test_conversation_finish_and_errors(tmp_path, monkeypatch):
    config = _config(tmp_path)

    def fake_run_task(request, config, llm, rules, workdir, task_id):
        Path(workdir).mkdir(parents=True, exist_ok=True)
        return TaskResult("success", [], None, {"message": "ok"})

    monkeypatch.setattr(tm, "run_task", fake_run_task)
    manager = tm.TaskManager(config, llm=object(), rules={"rules": []})
    conv_id = manager.create_conversation(TaskRequest(script="a\n"))
    first_task_id = manager.get_conversation(conv_id).current_task_id
    _wait_terminal(manager, first_task_id)

    assert manager.finish_conversation(conv_id) is True
    assert manager.get_conversation(conv_id).state == "finished"
    assert manager.finish_conversation(conv_id) is False

    with pytest.raises(tm.ConversationNotFound):
        manager.add_turn("nope", "x")
    with pytest.raises(tm.ConversationFinished):
        manager.add_turn(conv_id, "x")
    with pytest.raises(tm.EmptyInstruction):
        manager.add_turn(conv_id, "   ")
    with pytest.raises(tm.NoCurrentScript):
        fresh = manager.create_conversation(TaskRequest(script="a\n"))
        manager.add_turn(fresh, "x")


def test_list_conversations_returns_turn_counts(tmp_path, monkeypatch):
    config = _config(tmp_path)

    def fake_run_task(request, config, llm, rules, workdir, task_id):
        Path(workdir).mkdir(parents=True, exist_ok=True)
        return TaskResult("success", [], None, {"message": "ok"})

    monkeypatch.setattr(tm, "run_task", fake_run_task)
    manager = tm.TaskManager(config, llm=object(), rules={"rules": []})
    conv_a = manager.create_conversation(TaskRequest(prompt="场景A"))
    conv_b = manager.create_conversation(TaskRequest(prompt="场景B"))
    _wait_terminal(manager, manager.get_conversation(conv_a).turns[0].task_id)
    _wait_terminal(manager, manager.get_conversation(conv_b).turns[0].task_id)
    manager.add_turn(conv_a, "改一下")

    items = manager.list_conversations()
    by_id = {i["conversation_id"]: i for i in items}
    assert by_id[conv_a]["turn_count"] == 2
    assert by_id[conv_b]["turn_count"] == 1
    assert by_id[conv_a]["state"] == "active"
    assert by_id[conv_a]["initial_prompt"] == "场景A"
```

（需要 import pytest：在 `tests/unit/test_task_manager.py` 顶部 `import pytest` 旁已有 `import sqlite3` 等，若缺则加 `import pytest`）

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_task_manager.py -v`
Expected: FAIL（TaskManager 无 create_conversation 等属性）

- [ ] **Step 3: 实现** `api/task_manager.py`：

1. 模块级新增异常与 dataclass（放在 `PromptHistoryItem` 之后）：

```python
class ConversationNotFound(Exception):
    pass


class ConversationFinished(Exception):
    pass


class NoCurrentScript(Exception):
    pass


class EmptyInstruction(Exception):
    pass


@dataclass
class ConversationTurn:
    round: int
    task_id: str
    instruction: str | None
    state: str | None = None
    result: dict | None = None


@dataclass
class ConversationStatus:
    conversation_id: str
    created_at: str
    initial_prompt: str | None
    current_task_id: str | None
    state: str
    turns: list[ConversationTurn]
```

2. `_init_db`（L60-71）中，在 `prompt_history` 建表语句后追加两段建表 + tasks 表迁移（保持 `self._db_lock` 内）：

```python
            conn.execute(
                "CREATE TABLE IF NOT EXISTS conversations ("
                "conversation_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, initial_prompt TEXT, "
                "current_task_id TEXT, state TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS conversation_turns ("
                "conversation_id TEXT NOT NULL, round INTEGER NOT NULL, task_id TEXT NOT NULL, "
                "instruction TEXT, PRIMARY KEY (conversation_id, round))"
            )
            cols = [row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()]
            if "conversation_id" not in cols:
                conn.execute("ALTER TABLE tasks ADD COLUMN conversation_id TEXT")
```

3. `_run`（L120-127）末尾追加会话更新（在 `self._set_state(...)` 之后）：

```python
        if result.status == "success" and getattr(request, "conversation_id", None):
            self._update_current_task(request.conversation_id, task_id)
```

4. 文件末尾（`cancel` 之后）新增会话方法：

```python
    def create_conversation(self, request):
        conversation_id = uuid.uuid4().hex
        created_at = datetime.now().isoformat()
        initial_prompt = (getattr(request, "prompt", None) or "").strip() or None
        with self._db_lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute(
                "INSERT INTO conversations(conversation_id, created_at, initial_prompt, current_task_id, state) "
                "VALUES(?,?,?,?,?)",
                (conversation_id, created_at, initial_prompt, None, "active"),
            )
            conn.commit()
            conn.close()
        request.conversation_id = conversation_id
        task_id = self.submit(request)
        self._record_turn(conversation_id, 1, task_id, initial_prompt)
        return conversation_id

    def list_conversations(self, limit=50):
        limit = max(1, min(int(limit or 50), 200))
        with self._db_lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            rows = conn.execute(
                "SELECT c.conversation_id, c.created_at, c.initial_prompt, c.current_task_id, c.state, "
                "(SELECT COUNT(*) FROM conversation_turns t WHERE t.conversation_id = c.conversation_id) "
                "FROM conversations c ORDER BY c.created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            conn.close()
        return [
            {
                "conversation_id": r[0],
                "created_at": r[1],
                "initial_prompt": r[2],
                "current_task_id": r[3],
                "state": r[4],
                "turn_count": r[5],
            }
            for r in rows
        ]

    def get_conversation(self, conversation_id):
        with self._db_lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            row = conn.execute(
                "SELECT conversation_id, created_at, initial_prompt, current_task_id, state "
                "FROM conversations WHERE conversation_id=?",
                (conversation_id,),
            ).fetchone()
            turn_rows = []
            if row is not None:
                turn_rows = conn.execute(
                    "SELECT round, task_id, instruction FROM conversation_turns "
                    "WHERE conversation_id=? ORDER BY round",
                    (conversation_id,),
                ).fetchall()
            conn.close()
        if row is None:
            return None
        turns = []
        for t_round, t_task_id, t_instruction in turn_rows:
            status = self.get(t_task_id)
            turns.append(
                ConversationTurn(
                    round=t_round,
                    task_id=t_task_id,
                    instruction=t_instruction,
                    state=status.state if status else None,
                    result=status.result if status else None,
                )
            )
        return ConversationStatus(row[0], row[1], row[2], row[3], row[4], turns)

    def add_turn(self, conversation_id, instruction, options=None):
        instruction = (instruction or "").strip()
        if not instruction:
            raise EmptyInstruction(conversation_id)
        conversation = self.get_conversation(conversation_id)
        if conversation is None:
            raise ConversationNotFound(conversation_id)
        if conversation.state == "finished":
            raise ConversationFinished(conversation_id)
        script = self._current_script(conversation)
        next_round = max((t.round for t in conversation.turns), default=0) + 1
        request = TaskRequest(script=script, instruction=instruction, options=options, conversation_id=conversation_id)
        task_id = self.submit(request)
        self._record_turn(conversation_id, next_round, task_id, instruction)
        return task_id

    def finish_conversation(self, conversation_id):
        with self._db_lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            cur = conn.execute(
                "UPDATE conversations SET state='finished' WHERE conversation_id=? AND state='active'",
                (conversation_id,),
            )
            conn.commit()
            conn.close()
        return cur.rowcount > 0

    def _current_script(self, conversation):
        if not conversation.current_task_id:
            raise NoCurrentScript(conversation.conversation_id)
        scenario = Path(self.config.workspaces_dir) / conversation.current_task_id / "scenario.txt"
        if scenario.exists():
            return scenario.read_text(encoding="utf-8", errors="replace")
        status = self.get(conversation.current_task_id)
        if status and status.result.get("script_text"):
            return status.result["script_text"]
        raise NoCurrentScript(conversation.conversation_id)

    def _record_turn(self, conversation_id, turn_round, task_id, instruction):
        with self._db_lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute(
                "INSERT INTO conversation_turns(conversation_id, round, task_id, instruction) VALUES(?,?,?,?)",
                (conversation_id, turn_round, task_id, instruction),
            )
            conn.commit()
            conn.close()

    def _update_current_task(self, conversation_id, task_id):
        with self._db_lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute(
                "UPDATE conversations SET current_task_id=? WHERE conversation_id=?",
                (task_id, conversation_id),
            )
            conn.commit()
            conn.close()
```

注意：`test_conversation_finish_and_errors` 中 `create_conversation(TaskRequest(script="a\n"))` 后直接 `add_turn(fresh, "x")` 期望 `NoCurrentScript`——因为 fake_run_task 未执行完时 current_task_id 未更新（submit 是异步的，`_wait_terminal` 未调用）。这正是 NoCurrentScript 语义：会话尚无成功轮。若测试偶发竞态（线程跑太快先更新了 current），可将该断言前的 create 换成从未 submit 成功的会话（如直接 `manager.add_turn` 一个只创建过会话的 id 仍存在竞态）。为消除竞态，`fresh` 用 `create_conversation` 后**不等待**并直接 `add_turn`，此竞态窗口极小但存在。稳妥做法：该断言改为构造"无成功轮"的会话——`add_turn` 前先确认 `get_conversation(fresh).current_task_id is None`，若已被线程更新则 sleep 后重试（见 Step 4 说明）。执行时若偶发失败，将 `fresh` 分支改为：

```python
    with pytest.raises(tm.NoCurrentScript):
        fresh = manager.create_conversation(TaskRequest(script="a\n"))
        time.sleep(0.05)
        manager.add_turn(fresh, "x")
```

（若 `current_task_id` 已非 None，则说明测试跑得过快导致成功轮已落库，此时应改为等待后断言 `add_turn` 成功——以实际运行输出为准。）

- [ ] **Step 4: 运行全部 task_manager 测试确认通过**

Run: `python -m pytest tests/unit/test_task_manager.py -v`
Expected: 全部 PASS（原有 7 个 + 新 5 个）

- [ ] **Step 5: Commit**

```bash
git add api/task_manager.py tests/unit/test_task_manager.py
git commit -m "feat: TaskManager 会话存储与 CRUD（conversations/turns 表 + 迁移）"
```

---

### Task 4: API 会话端点

**Files:**
- Modify: `api/models.py`
- Modify: `api/main.py`
- Modify: `tests/unit/test_api.py`（扩展 FakeTaskManager + 新端点测试）
- Test: `tests/unit/test_api.py`

**Interfaces:**
- Consumes: Task 3 的 `ConversationNotFound/ConversationFinished/NoCurrentScript/EmptyInstruction`、`create_conversation/list_conversations/get_conversation/add_turn/finish_conversation`
- Produces:
  - `api.models.ConversationCreate(BaseModel): prompt: Optional[str] = None, script: Optional[str] = None, options: Optional[list[str]] = None`
  - `api.models.ConversationTurnSubmit(BaseModel): instruction: str, options: Optional[list[str]] = None`
  - 端点 `POST /api/conversations` → `{"conversation_id", "state", "task_id"}`（task_id 为首轮任务）
  - 端点 `GET /api/conversations?limit=` → `{"conversations": [ {conversation_id, created_at, initial_prompt, current_task_id, state, turn_count} ]}`
  - 端点 `GET /api/conversations/{conversation_id}` → `{"conversation_id", "created_at", "initial_prompt", "current_task_id", "state", "turns": [{round, task_id, instruction, state, result}]}`；不存在 → 404
  - 端点 `POST /api/conversations/{conversation_id}/tasks` body `ConversationTurnSubmit` → `{"task_id"}`；404 会话不存在；409 已结束或无成功脚本；400 空指令
  - 端点 `POST /api/conversations/{conversation_id}/finish` → `{"finished": True}`；失败 → 404

- [ ] **Step 1: 写失败测试**。先扩展 `tests/unit/test_api.py` 的 `FakeTaskManager`，在 `__init__` 中加 `self.conversations = {}`，并新增方法（替换原有 class 定义）：

```python
class FakeTaskManager:
    def __init__(self, config=None):
        self.config = config or Config(workspaces_dir="workspaces")
        self.statuses = {}
        self.submitted = []
        self.conversations = {}

    def submit(self, request):
        task_id = uuid.uuid4().hex
        self.submitted.append(request)
        self.statuses[task_id] = TaskStatus(task_id, "pending", "2026-08-11T00:00:00", [], {})
        return task_id

    def get(self, task_id):
        return self.statuses.get(task_id)

    def cancel(self, task_id):
        status = self.statuses.get(task_id)
        if status and status.state in ("pending", "running"):
            status.state = "cancelled"
            return True
        return False

    def list_prompt_history(self, limit=50):
        return [
            PromptHistoryItem(
                task_id=task_id,
                prompt=req.prompt,
                options=req.options or [],
                created_at=self.statuses[task_id].created_at,
                state=self.statuses[task_id].state,
            )
            for task_id, req in zip(self.statuses, self.submitted)
            if req.prompt
        ][:limit]

    def create_conversation(self, request):
        conversation_id = uuid.uuid4().hex
        self.conversations[conversation_id] = {
            "created_at": "2026-08-12T00:00:00",
            "initial_prompt": request.prompt or None,
            "current_task_id": None,
            "state": "active",
            "turns": [],
        }
        task_id = self.submit(request)
        self.conversations[conversation_id]["turns"].append(
            {
                "round": 1,
                "task_id": task_id,
                "instruction": request.prompt or None,
                "state": "pending",
                "result": {},
            }
        )
        return conversation_id

    def list_conversations(self, limit=50):
        return [
            {
                "conversation_id": cid,
                "created_at": c["created_at"],
                "initial_prompt": c["initial_prompt"],
                "current_task_id": c["current_task_id"],
                "state": c["state"],
                "turn_count": len(c["turns"]),
            }
            for cid, c in self.conversations.items()
        ][:limit]

    def get_conversation(self, conversation_id):
        c = self.conversations.get(conversation_id)
        if c is None:
            return None
        return SimpleNamespace(
            conversation_id=conversation_id,
            created_at=c["created_at"],
            initial_prompt=c["initial_prompt"],
            current_task_id=c["current_task_id"],
            state=c["state"],
            turns=[SimpleNamespace(**t) for t in c["turns"]],
        )

    def add_turn(self, conversation_id, instruction, options=None):
        c = self.conversations.get(conversation_id)
        if c is None:
            raise ConversationNotFound(conversation_id)
        if c["state"] == "finished":
            raise ConversationFinished(conversation_id)
        if not (instruction or "").strip():
            raise EmptyInstruction(conversation_id)
        if not c["current_task_id"]:
            raise NoCurrentScript(conversation_id)
        task_id = self.submit(SimpleNamespace(
            prompt=None, script="cur", options=options, instruction=instruction
        ))
        c["turns"].append(
            {
                "round": len(c["turns"]) + 1,
                "task_id": task_id,
                "instruction": instruction,
                "state": "pending",
                "result": {},
            }
        )
        c["current_task_id"] = task_id
        return task_id

    def finish_conversation(self, conversation_id):
        c = self.conversations.get(conversation_id)
        if c is None or c["state"] == "finished":
            return False
        c["state"] = "finished"
        return True
```

顶部 import 增加：`from types import SimpleNamespace`、`from api.task_manager import ConversationFinished, ConversationNotFound, EmptyInstruction, NoCurrentScript`

然后追加新端点测试到 `tests/unit/test_api.py` 末尾：

```python
def test_create_conversation_returns_conversation_and_first_task(client):
    test_client, manager = client
    resp = test_client.post("/api/conversations", json={"prompt": "生成空战场景", "options": ["-es"]})
    assert resp.status_code == 200
    body = resp.json()
    assert re.fullmatch(r"[0-9a-f]{32}", body["conversation_id"])
    assert re.fullmatch(r"[0-9a-f]{32}", body["task_id"])
    assert body["state"] == "active"


def test_list_conversations_empty(client):
    test_client, _ = client
    resp = test_client.get("/api/conversations")
    assert resp.status_code == 200
    assert resp.json() == {"conversations": []}


def test_get_conversation_detail(client):
    test_client, _ = client
    created = test_client.post("/api/conversations", json={"prompt": "x"}).json()
    conv_id = created["conversation_id"]
    resp = test_client.get(f"/api/conversations/{conv_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["conversation_id"] == conv_id
    assert body["state"] == "active"
    assert len(body["turns"]) == 1
    assert body["turns"][0]["task_id"] == created["task_id"]
    assert body["turns"][0]["instruction"] == "x"
    assert body["turns"][0]["state"] == "pending"


def test_get_conversation_missing_404(client):
    test_client, _ = client
    assert test_client.get("/api/conversations/nope").status_code == 404


def test_submit_conversation_turn(client):
    test_client, manager = client
    created = test_client.post("/api/conversations", json={"script": "end_time 1 sec\n"}).json()
    conv_id = created["conversation_id"]
    manager.get_conversation(conv_id).current_task_id = "firsttask"
    resp = test_client.post(f"/api/conversations/{conv_id}/tasks", json={"instruction": "把速度改快"})
    assert resp.status_code == 200
    body = resp.json()
    assert re.fullmatch(r"[0-9a-f]{32}", body["task_id"])
    detail = test_client.get(f"/api/conversations/{conv_id}").json()
    assert len(detail["turns"]) == 2
    assert detail["turns"][1]["instruction"] == "把速度改快"


def test_submit_turn_missing_conversation_404(client):
    test_client, _ = client
    resp = test_client.post("/api/conversations/nope/tasks", json={"instruction": "x"})
    assert resp.status_code == 404


def test_submit_turn_empty_instruction_400(client):
    test_client, manager = client
    created = test_client.post("/api/conversations", json={"script": "x\n"}).json()
    conv_id = created["conversation_id"]
    manager.get_conversation(conv_id).current_task_id = "t1"
    resp = test_client.post(f"/api/conversations/{conv_id}/tasks", json={"instruction": "  "})
    assert resp.status_code == 400


def test_submit_turn_no_script_409(client):
    test_client, _ = client
    created = test_client.post("/api/conversations", json={"prompt": "x"}).json()
    conv_id = created["conversation_id"]
    resp = test_client.post(f"/api/conversations/{conv_id}/tasks", json={"instruction": "改"})
    assert resp.status_code == 409


def test_finish_conversation(client):
    test_client, _ = client
    created = test_client.post("/api/conversations", json={"prompt": "x"}).json()
    conv_id = created["conversation_id"]
    assert test_client.post(f"/api/conversations/{conv_id}/finish").json() == {"finished": True}
    resp = test_client.post(f"/api/conversations/{conv_id}/tasks", json={"instruction": "改"})
    assert resp.status_code == 409


def test_finish_missing_conversation_404(client):
    test_client, _ = client
    assert test_client.post("/api/conversations/nope/finish").status_code == 404
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_api.py -v`
Expected: FAIL（main.py 无 /api/conversations 路由）

- [ ] **Step 3: 实现**。`api/models.py` 追加：

```python
class ConversationCreate(BaseModel):
    prompt: Optional[str] = None
    script: Optional[str] = None
    options: Optional[list[str]] = None


class ConversationTurnSubmit(BaseModel):
    instruction: str
    options: Optional[list[str]] = None
```

`api/main.py` 修改：
1. import 处（L9 后）加：`from pydantic import BaseModel` 已存在；L14 之后加 `from api.models import ConversationCreate, ConversationTurnSubmit`；在 `from core.agent import TaskRequest` 后加 `from api.task_manager import ConversationFinished, ConversationNotFound, EmptyInstruction, NoCurrentScript`
2. 在 `cancel_task` 端点之后（L125 后）插入会话端点：

```python
    @app.post("/api/conversations")
    def create_conversation(body: ConversationCreate):
        conversation_id = manager.create_conversation(
            TaskRequest(prompt=body.prompt, script=body.script, options=body.options)
        )
        conversation = manager.get_conversation(conversation_id)
        return {
            "conversation_id": conversation_id,
            "state": conversation.state,
            "task_id": conversation.turns[0].task_id,
        }

    @app.get("/api/conversations")
    def list_conversations(limit: int = 50):
        if not hasattr(manager, "list_conversations"):
            return {"conversations": []}
        return {"conversations": manager.list_conversations(limit)}

    @app.get("/api/conversations/{conversation_id}")
    def get_conversation(conversation_id: str):
        conversation = manager.get_conversation(conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        return {
            "conversation_id": conversation.conversation_id,
            "created_at": conversation.created_at,
            "initial_prompt": conversation.initial_prompt,
            "current_task_id": conversation.current_task_id,
            "state": conversation.state,
            "turns": [
                {
                    "round": t.round,
                    "task_id": t.task_id,
                    "instruction": t.instruction,
                    "state": t.state,
                    "result": t.result or {},
                }
                for t in conversation.turns
            ],
        }

    @app.post("/api/conversations/{conversation_id}/tasks")
    def submit_conversation_turn(conversation_id: str, body: ConversationTurnSubmit):
        try:
            task_id = manager.add_turn(conversation_id, body.instruction, body.options)
        except ConversationNotFound:
            raise HTTPException(status_code=404, detail="conversation not found")
        except ConversationFinished:
            raise HTTPException(status_code=409, detail="conversation already finished")
        except NoCurrentScript:
            raise HTTPException(status_code=409, detail="conversation has no successful script yet")
        except EmptyInstruction:
            raise HTTPException(status_code=400, detail="instruction required")
        return {"task_id": task_id}

    @app.post("/api/conversations/{conversation_id}/finish")
    def finish_conversation(conversation_id: str):
        if manager.finish_conversation(conversation_id):
            return {"finished": True}
        raise HTTPException(status_code=404, detail="conversation not found or already finished")
```

- [ ] **Step 4: 运行全部 api 测试确认通过**

Run: `python -m pytest tests/unit/test_api.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add api/models.py api/main.py tests/unit/test_api.py
git commit -m "feat: 新增会话 API 端点（创建/列表/详情/修改轮/结束）"
```

---

### Task 5: CLI 支持会话修改轮

**Files:**
- Modify: `api/cli.py`
- Test: `tests/unit/test_cli.py`

**Interfaces:**
- Consumes: `TaskManager.add_turn(conversation_id, instruction, options=None) -> str`（Task 3）
- Produces: `run --conversation <id> --instruction "..."`：对会话提交修改轮并阻塞轮询打印报告；`--instruction` 必须与 `--conversation` 搭配

- [ ] **Step 1: 写失败测试**，追加到 `tests/unit/test_cli.py` 末尾：

```python
def test_run_conversation_submits_turn(monkeypatch, capsys):
    class ConvManager(FakeManager):
        def add_turn(self, conversation_id, instruction, options=None):
            self.turn = (conversation_id, instruction, options)
            return self.task_id

    monkeypatch.setattr(cli, "TaskManager", ConvManager)
    cli.main(["run", "--conversation", "abc123", "--instruction", "把速度改快", "--options", "-es"])
    manager = ConvManager.instances[-1]
    assert manager.turn == ("abc123", "把速度改快", ["-es"])
    assert "turn abc123 submitted as task task123" in capsys.readouterr().out
```

需要确认：当前 `run` 没有 `--options` 参数——`cmd_run` 中 `TaskRequest(prompt=args.prompt, script=script)` 没有 options。看现有 CLI：没有 options 参数。所以上面测试里不该传 `--options`。修正：`cli.main(["run", "--conversation", "abc123", "--instruction", "把速度改快"])`，`manager.turn == ("abc123", "把速度改快", None)`。用修正版：

```python
def test_run_conversation_submits_turn(monkeypatch, capsys):
    class ConvManager(FakeManager):
        def add_turn(self, conversation_id, instruction, options=None):
            self.turn = (conversation_id, instruction, options)
            return self.task_id

    monkeypatch.setattr(cli, "TaskManager", ConvManager)
    cli.main(["run", "--conversation", "abc123", "--instruction", "把速度改快"])
    manager = ConvManager.instances[-1]
    assert manager.turn == ("abc123", "把速度改快", None)
    assert "turn abc123 submitted as task task123" in capsys.readouterr().out


def test_run_instruction_without_conversation_exits_2(monkeypatch):
    monkeypatch.setattr(cli, "TaskManager", FakeManager)
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["run", "--instruction", "改"])
    assert excinfo.value.code == 2
```

（注意：`run` 目前未定义 `--options`，不要使用它。）

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_cli.py -v`
Expected: FAIL（`run` 无 `--conversation` 参数 / 输出不匹配）

- [ ] **Step 3: 实现** `api/cli.py`：

1. `cmd_run`（L26-45）改为：

```python
def cmd_run(args):
    manager = TaskManager(load_config())
    if args.conversation:
        task_id = manager.add_turn(args.conversation, args.instruction)
        print(f"turn {args.conversation} submitted as task {task_id}")
    else:
        script = None
        if args.script:
            try:
                script = Path(args.script).read_text(encoding="utf-8")
            except OSError:
                print(f"script file {args.script} not found")
                return 2
        request = TaskRequest(prompt=args.prompt, script=script)
        task_id = manager.submit(request)
        print(f"task {task_id} submitted")
    deadline = time.time() + POLL_TIMEOUT
    status = manager.get(task_id)
    while status.state not in TERMINAL_STATES and time.time() < deadline:
        time.sleep(POLL_INTERVAL)
        status = manager.get(task_id)
    if status.state not in TERMINAL_STATES:
        print(f"task {task_id} still {status.state} after {POLL_TIMEOUT}s timeout")
    _print_report(task_id, status)
```

2. `build_parser` 的 `p_run`（L122-125）改为：

```python
    p_run = sub.add_parser("run", help="submit a task and wait for the result")
    group = p_run.add_mutually_exclusive_group(required=True)
    group.add_argument("--prompt", help="task prompt")
    group.add_argument("--script", help="path to an existing scenario script")
    group.add_argument("--conversation", help="conversation id to extend with a modification turn")
    p_run.add_argument("--instruction", help="modification instruction (requires --conversation)")
```

3. `cmd_run` 末尾增加校验：若 `args.instruction` 但无 `args.conversation`，argparse 已保证 group required；`--instruction` 单独出现时 group 为空 → argparse 报 required 错误退出码 2，无需额外校验。`--instruction` 配 `--prompt`/`--script` 时忽略（保持简单，不额外报错）。

- [ ] **Step 4: 运行全部 cli 测试确认通过**

Run: `python -m pytest tests/unit/test_cli.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add api/cli.py tests/unit/test_cli.py
git commit -m "feat: CLI run 支持 --conversation/--instruction 提交修改轮"
```

---

### Task 6: 前端会话视图

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/app.js`
- Test: `tests/unit/test_api.py`（前端内容断言更新）

**Interfaces:**
- Consumes: 全部会话端点（Task 4）
- Produces: 前端会话模式（tab 切换 + 会话列表 + 对话流 + 修改指令提交 + 结束会话）

- [ ] **Step 1: 写失败测试**，修改 `tests/unit/test_api.py` 中两个前端断言测试，追加新元素断言：

`test_frontend_index_served` 中 `assert "Prompt 历史" in resp.text` 后追加：

```python
    assert "会话" in resp.text
    assert "convThread" in resp.text
```

`test_frontend_static_js_served` 中 `assert "runWarlock" in resp.text` 后追加：

```python
    assert "createConversation" in resp.text
    assert "loadConversationDetail" in resp.text
    assert "submitTurn" in resp.text
    assert "finishConv" in resp.text
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_api.py::test_frontend_index_served tests/unit/test_api.py::test_frontend_static_js_served -v`
Expected: FAIL（断言失败，元素缺失）

- [ ] **Step 3: 实现**。

`frontend/index.html` 修改两处：

1. tabs 区（L23-26）加第三个 tab：

```html
          <div class="tabs" role="tablist" aria-label="提交类型">
            <button class="tab active" id="promptTab" type="button">Prompt</button>
            <button class="tab" id="scriptTab" type="button">Script</button>
            <button class="tab" id="convTab" type="button">会话</button>
          </div>
```

2. `</section>`（workspace section 结束后、`<section class="detail-grid">` 之前，即 L93 与 L95 之间）插入会话面板：

```html
      <section id="convPanel" class="workspace" style="display:none">
        <div class="submit-panel">
          <div class="panel-head">
            <h2>创建会话</h2>
            <label><input id="convScriptMode" type="checkbox" />内容为已有脚本</label>
          </div>
          <textarea id="convCreateInput" spellcheck="false" placeholder="输入自然语言需求，或勾选上方后粘贴已有 AFSIM 脚本"></textarea>
          <label>
            mission 选项
            <input id="convCreateOptions" value="-es" />
          </label>
          <div class="button-row">
            <button class="primary" id="createConv" type="button">创建会话</button>
          </div>
        </div>
        <div class="status-panel">
          <div class="panel-head">
            <h2>会话 <span id="convState" class="badge">-</span></h2>
            <div class="panel-actions">
              <button id="refreshConvs" type="button">刷新列表</button>
              <button id="finishConv" type="button">结束会话</button>
            </div>
          </div>
          <div id="convList" class="list empty">暂无会话</div>
          <div id="convThread" class="list empty">选择或创建会话</div>
          <textarea id="convInstruction" placeholder="输入修改指令，如：把蓝军速度改成 450 节"></textarea>
          <div class="button-row">
            <button class="primary" id="submitTurn" type="button">提交修改</button>
          </div>
        </div>
      </section>
```

`frontend/app.js` 修改：

1. 模块顶部（L1-5 后）加状态：

```js
let currentConversationId = "";
let convPollTimer = null;
```

2. 新增函数（放在 `switchMode` 之后、`parseOptions` 之前）：

```js
function switchPanel(next) {
  $("promptTab").classList.toggle("active", next === "single-prompt");
  $("scriptTab").classList.toggle("active", next === "single-script");
  $("convTab").classList.toggle("active", next === "conversation");
  $("taskForm").closest(".submit-panel").style.display = next === "conversation" ? "none" : "";
  $("convPanel").style.display = next === "conversation" ? "" : "none";
  if (next === "single-prompt") switchMode("prompt");
  if (next === "single-script") switchMode("script");
  if (next === "conversation") loadConversations();
}

function parseConvOptions() {
  return $("convCreateOptions")
    .value.split(/\s+/)
    .map((x) => x.trim())
    .filter(Boolean);
}

async function createConversation() {
  const text = $("convCreateInput").value;
  const payload = { options: parseConvOptions() };
  if ($("convScriptMode").checked) {
    payload.script = text;
  } else {
    payload.prompt = text;
  }
  try {
    const data = await api("/api/conversations", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    currentConversationId = data.conversation_id;
    await loadConversations();
    await loadConversationDetail(data.conversation_id);
    pollConversationTurn(data.task_id);
  } catch (err) {
    $("convThread").className = "list empty";
    $("convThread").textContent = err.message;
  }
}

async function loadConversations() {
  try {
    const data = await api("/api/conversations");
    const items = data.conversations || [];
    const box = $("convList");
    if (!items.length) {
      box.className = "list empty";
      box.textContent = "暂无会话";
      return;
    }
    box.className = "list";
    box.innerHTML = items
      .map((c) => {
        const title = (c.initial_prompt || "(script)").slice(0, 60);
        return `<button class="history-item" type="button" data-conv="${escapeHtml(c.conversation_id)}"><strong>${escapeHtml(title)}</strong><span>${escapeHtml(c.created_at)} / ${escapeHtml(c.state)} / ${c.turn_count} 轮</span></button>`;
      })
      .join("");
    box.querySelectorAll(".history-item").forEach((btn) => {
      btn.addEventListener("click", () => loadConversationDetail(btn.dataset.conv));
    });
  } catch (err) {
    $("convList").className = "list empty";
    $("convList").textContent = err.message;
  }
}

function renderConvThread(turns) {
  const box = $("convThread");
  if (!turns.length) {
    box.className = "list empty";
    box.textContent = "暂无轮次";
    return;
  }
  box.className = "list";
  box.innerHTML = turns
    .map((t) => {
      const label = t.instruction ? `第${t.round}轮: ${t.instruction}` : `第${t.round}轮: 初始脚本`;
      const summary = t.result
        ? t.result.message || t.result.error || t.result.unknown_error || ""
        : "";
      return `<button class="history-item" type="button" data-task="${escapeHtml(t.task_id)}"><strong>${escapeHtml(label)}</strong><span>${escapeHtml(t.state || "-")} ${escapeHtml(summary)}</span></button>`;
    })
    .join("");
  box.querySelectorAll(".history-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      loadTask(btn.dataset.task);
    });
  });
}

async function loadConversationDetail(conversationId) {
  try {
    const data = await api(`/api/conversations/${encodeURIComponent(conversationId)}`);
    currentConversationId = data.conversation_id;
    $("convState").textContent = data.state;
    $("convState").className = `badge ${data.state}`;
    renderConvThread(data.turns || []);
    if (data.current_task_id) {
      const status = await api(`/api/tasks/${data.current_task_id}`);
      setTask(status);
    }
  } catch (err) {
    $("convThread").className = "list empty";
    $("convThread").textContent = err.message;
  }
}

function pollConversationTurn(taskId) {
  clearInterval(pollTimer);
  clearInterval(convPollTimer);
  convPollTimer = setInterval(async () => {
    try {
      const status = await api(`/api/tasks/${taskId}`);
      if (terminalStates.has(status.state)) {
        clearInterval(convPollTimer);
        setTask(status);
        if (currentConversationId) loadConversationDetail(currentConversationId);
      }
    } catch (err) {
      clearInterval(convPollTimer);
      notice(err.message);
    }
  }, 1200);
}

async function submitTurn() {
  const instruction = $("convInstruction").value.trim();
  if (!currentConversationId || !instruction) {
    notice("请先创建或选择会话，并输入修改指令");
    return;
  }
  try {
    const data = await api(`/api/conversations/${encodeURIComponent(currentConversationId)}/tasks`, {
      method: "POST",
      body: JSON.stringify({ instruction, options: parseConvOptions() }),
    });
    $("convInstruction").value = "";
    await loadConversationDetail(currentConversationId);
    pollConversationTurn(data.task_id);
  } catch (err) {
    notice(err.message);
  }
}

async function finishConv() {
  if (!currentConversationId) return;
  try {
    await api(`/api/conversations/${encodeURIComponent(currentConversationId)}/finish`, {
      method: "POST",
    });
    await loadConversationDetail(currentConversationId);
    await loadConversations();
  } catch (err) {
    notice(err.message);
  }
}
```

3. 事件绑定区（L395-404）替换三行并追加：

```js
$("promptTab").addEventListener("click", () => switchPanel("single-prompt"));
$("scriptTab").addEventListener("click", () => switchPanel("single-script"));
$("convTab").addEventListener("click", () => switchPanel("conversation"));
$("createConv").addEventListener("click", createConversation);
$("submitTurn").addEventListener("click", submitTurn);
$("finishConv").addEventListener("click", finishConv);
$("refreshConvs").addEventListener("click", loadConversations);
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/unit/test_api.py -v`
Expected: 全部 PASS（含前端断言）

- [ ] **Step 5: Commit**

```bash
git add frontend/index.html frontend/app.js tests/unit/test_api.py
git commit -m "feat: 前端新增会话模式（会话列表/对话流/修改指令）"
```

---

### Task 7: 集成测试（会话全链路）

**Files:**
- Modify: `tests/integration/test_e2e.py`
- Test: `tests/integration/test_e2e.py`

**Interfaces:**
- Consumes: 全部前面任务的成果

- [ ] **Step 1: 写测试**，追加到 `tests/integration/test_e2e.py` 末尾。需要 `executor` import：

```python
from core import executor
```

并追加：

```python
def test_conversation_create_modify_and_finish(tmp_path, monkeypatch):
    config = _config(tmp_path)

    class FakeLLM:
        def generate_script(self, prompt, ctx):
            return "platform_type FIGHTER WSF_PLATFORM\nplatform A FIGHTER\nend_platform\n"

        def modify_script(self, script, instruction, ctx):
            assert "把 A 改成 B" in instruction
            return script.replace("platform A FIGHTER", "platform B FIGHTER")

        def propose_fix(self, script, err, hint):
            return None

    monkeypatch.setattr(executor, "run", lambda p, w, c, options=None: SimpleNamespace(rc=0, stdout="", stderr=""))
    manager = TaskManager(config, llm=FakeLLM(), rules={"rules": []})
    client = TestClient(create_app(task_manager=manager))

    created = client.post("/api/conversations", json={"prompt": "生成一个平台"}).json()
    conv_id = created["conversation_id"]
    first = _wait_terminal(client, created["task_id"])
    assert first["state"] == "success"

    turn = client.post(f"/api/conversations/{conv_id}/tasks", json={"instruction": "把 A 改成 B"}).json()
    second = _wait_terminal(client, turn["task_id"])
    assert second["state"] == "success"
    assert "platform B FIGHTER" in second["result"]["script_text"]
    assert "platform A FIGHTER" not in second["result"]["script_text"]

    detail = client.get(f"/api/conversations/{conv_id}").json()
    assert detail["state"] == "active"
    assert len(detail["turns"]) == 2
    assert detail["turns"][1]["instruction"] == "把 A 改成 B"
    assert detail["turns"][1]["state"] == "success"
    assert detail["current_task_id"] == turn["task_id"]

    assert client.post(f"/api/conversations/{conv_id}/finish").json() == {"finished": True}
    assert client.post(f"/api/conversations/{conv_id}/tasks", json={"instruction": "x"}).status_code == 409

    listed = client.get("/api/conversations").json()
    assert len(listed["conversations"]) == 1
    assert listed["conversations"][0]["turn_count"] == 2
    assert listed["conversations"][0]["state"] == "finished"
```

- [ ] **Step 2: 运行确认通过**

Run: `python -m pytest tests/integration/test_e2e.py -v`
Expected: 全部 PASS（原有 1 个 + 新 1 个）

- [ ] **Step 3: 回归全部测试**

Run: `python -m pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_e2e.py
git commit -m "test: 会话创建→修改轮→结束 全链路集成测试"
```

---

## 自审记录

- **Spec 覆盖**：数据模型（conversations/turns 表 + tasks 迁移）→ Task 3；5 个 API 端点 → Task 4；每轮修改流程（LLM 整脚本重写 → normalize → 验证循环）→ Task 1/2；CLI → Task 5；前端会话视图 → Task 6；错误处理（404/409/400）→ Task 3/4；重启恢复（current_task_id 持久化在 DB）→ Task 3 测试 `test_conversation_create_first_turn_and_persist`；集成测试 → Task 7
- **占位符扫描**：无 TBD/TODO；所有代码步骤均含完整代码
- **类型一致性**：`modify_script(script, instruction, knowledge_context)` 三处引用一致；`add_turn(conversation_id, instruction, options=None)` 在 Task 3/4/5 签名一致；`ConversationNotFound/ConversationFinished/NoCurrentScript/EmptyInstruction` 四异常在 Task 3/4 一致
