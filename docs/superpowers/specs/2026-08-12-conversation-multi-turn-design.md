# 多轮会话（基于已有脚本的对话式修改）设计

日期：2026-08-12
状态：已批准

## 背景与目标

当前服务是任务式模型：`POST /api/tasks` → 轮询 task_id → 单个最终脚本，任务之间完全独立，无会话/多轮概念。LLM 每次调用都是独立的 2 条消息（system + user），无对话历史。

目标：支持"基于一个脚本进行多轮对话修改"——会话第一轮生成或上传初始脚本，后续每轮输入自然语言修改指令，基于当前脚本产出修改后的新脚本，每轮均经 mission 验证。

## 已确认的关键决策

| 决策点 | 结论 |
|---|---|
| 验证时机 | 每轮修改都跑 mission 验证 + matcher/fixer 修复循环 |
| LLM 上下文 | 仅发【当前脚本全文 + 本轮修改指令】，不带历史 |
| 会话建模 | 新建 conversation 概念，SQLite 新增 conversations 表 |
| 初始脚本来源 | 两者都支持：自然语言 prompt 生成，或直接上传已有脚本 |
| 修改产出方式 | 方案 A：整脚本重写（LLM 输出完整修改后脚本，复用现有管线） |
| 前端 | 现有仪表盘加"会话模式"视图（对话流 + 脚本预览），不重构 |

## 架构设计

### 数据模型

SQLite 新增一张表 + tasks 表加一列：

```sql
CREATE TABLE conversations (
    id TEXT PRIMARY KEY,            -- uuid hex，与 task_id 同格式
    created_at TEXT NOT NULL,
    initial_prompt TEXT,            -- 首轮 prompt（script 入口时为 NULL）
    current_task_id TEXT,           -- 最后成功的一轮任务（修改轮失败不更新）
    state TEXT NOT NULL             -- active / finished
);

ALTER TABLE tasks ADD COLUMN conversation_id TEXT;
-- conversation_id 为 NULL 表示旧式独立任务，完全兼容
```

- `workspaces/` 目录结构不变：每轮仍独立 `workspaces/<task_id>/`，会话只是逻辑串联
- 每轮修改基于上一轮成功产出的脚本（`workspaces/<current_task_id>/scenario.txt` 或 `result.script_text`）

### API 端点（现有端点全部保留兼容）

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/conversations` | POST | 创建会话。body: `{prompt \| script, options}`，内部创建首轮 task 并返回 `{conversation_id, task_id, state}` |
| `/api/conversations` | GET | 列出会话（含初始 prompt、轮数、当前状态） |
| `/api/conversations/{id}` | GET | 会话详情：各轮 `[{round, task_id, instruction, state, result}]` |
| `/api/conversations/{id}/tasks` | POST | 新一轮修改。body: `{instruction, options}`，内部用会话当前脚本+指令创建新 task，返回 task_id |
| `/api/conversations/{id}/finish` | POST | 结束会话（可再后续轮询/查看） |

### 每轮修改流程

```
POST /api/conversations/{id}/tasks {instruction}
  → 查会话 → 读当前脚本（workspaces/current_task/scenario.txt 或 result.script_text）
  → 新建 task（conversation_id=该会话，kind="modify"）
  → agent 修改管线：
       LLM(system规则 + 当前脚本 + 指令) → 新脚本 → normalize
       → mission 验证 → matcher/fixer 循环（与生成完全相同）
  → 成功后更新 conversations.current_task_id
```

### LLM prompt 组装

`core/llm.py` 新增方法 `modify_script(script, instruction, knowledge_context) -> str`：

- 消息结构：`[system(现有完整规则清单+知识), user("这是当前脚本：\n{script}\n\n请根据以下修改要求输出修改后的完整 AFSIM 脚本：\n{instruction}")]`
- 只发当前脚本+指令，不发历史
- `core/agent.py` 新增分支：task 带 `instruction` 时走修改管线（LLM 产出新脚本 → normalize → 验证循环）；首轮带 `prompt`/`script` 时走现有管线
- 复用现有 `retrieve_knowledge` 按指令关键词检索知识文档，追加到 system

### CLI 支持

`cli.py run` 增加 `--conversation <id> --instruction "..."`：对已有会话提交修改指令并阻塞轮询。

### 前端会话视图

现有仪表盘加"会话模式"（tab：`单次任务` / `会话`）：

- 创建会话：prompt 或上传脚本
- 对话流：每轮用户指令 + 系统结果（验证通过/失败摘要）
- 输入框提交修改指令；空指令禁用提交
- 会话结束后只能查看不能修改
- 脚本预览：当前轮 scenario.txt
- 会话列表侧栏，点击加载对话流
- 每轮提交复用现有 `POST /api/tasks` 轮询逻辑（1200ms）

## 错误处理与边界

- 会话不存在 → 404；对已 `finished` 会话提交修改 → 409
- 会话无当前脚本（首轮 failed 且从未成功）→ 拒绝修改轮，提示先重建
- 修改轮失败不影响会话状态，可基于**上一轮成功脚本**重试修改
- 重启恢复：stale 会话保留，`current_task_id` 指向最后成功轮
- task_id/conversation_id 均沿用 32 位 hex 模式与防穿越校验

## 测试计划

- 单测 `test_llm.py`：modify_script 消息结构（system 规则 + 当前脚本 + 指令）
- 单测 `test_task_manager.py`：会话 CRUD、持久化、重启恢复、失败重试
- 单测 `test_agent.py`：instruction 分支走修改管线（monkeypatch LLM/executor/matcher/fixer）
- 单测 `test_api.py`：新端点状态码与响应结构、404/409 边界
- 集成 `test_e2e.py`：会话创建 → 首轮 → 修改轮全链路
- 沿用现有 FakeLLM + monkeypatch 模式，无需真 AFSIM/LLM
