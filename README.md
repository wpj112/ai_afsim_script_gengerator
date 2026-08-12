# AFSIM Script Generator

AFSIM/WSF 脚本生成服务。项目当前已经从原始 Skill 扩展为一个可独立部署的服务，提供：

- 基于 LLM 的 AFSIM 场景脚本生成
- 已有脚本的多轮对话式修改
- AFSIM 脚本规范化和常见错误修复
- `mission` 执行、重试和错误规则匹配
- 任务状态、Prompt 历史和多轮会话持久化
- 原生 HTML/CSS/JavaScript 前端
- Linux 本地执行或 Windows AFSIM Runner 远程执行
- 生成脚本查看、复制和下载
- Warlock 启动 URL 配置

当前系统的成功判定主要是“脚本被 mission 接受并执行返回成功”。`evt`、`rep` 等仿真输出的业务逻辑验收仍在 Codex TODO List 中，尚不能据此宣称雷达探测、导弹命中等业务行为已经验证。

## 当前架构

```text
浏览器 / CLI / HTTP 客户端
              |
              v
        FastAPI 服务
              |
              v
        TaskManager + SQLite
              |
              v
生成或修改脚本 -> 规范化 -> mission 执行
              |
              +-> 错误规则匹配 / 自动修复 / 重试
              +-> workspaces、任务历史、脚本归档
```

多轮会话的流程是：先创建一个会话并生成初始脚本，后续提交修改指令时读取上一轮成功脚本，生成修改版本并再次执行。只有成功的任务才会成为会话的当前脚本。

## 目录结构

```text
afsim-script-generator/
├── api/                         FastAPI、CLI、任务管理
├── core/                        生成、执行、修复、规则匹配
├── frontend/                    原生前端
├── references/                  当前项目整理的 AFSIM 知识和规则
├── memory/                      错误规则、教训和待审核记录
├── scripts/
│   ├── run_mission.py           mission 执行包装器
│   ├── windows_runner.py        Windows 远程执行服务
│   └── start_windows_runner.bat Windows 一键启动脚本
├── workspaces/                  任务工作目录和 SQLite 数据库
├── output/verified/scenario/    成功脚本归档
├── afsimDoc/                    可选的本地 AFSIM 官方文档目录
├── config.txt                   本地配置
└── docker-compose.yml            Docker Compose 配置
```

## 快速启动

### Docker Compose

项目默认使用本地 `afsim:2.9.0` 镜像构建服务镜像。宿主机端口默认是 `18006`，容器端口是 `8000`。

```bash
docker compose up -d --build
curl http://localhost:18006/healthz
```

前端地址：

```text
http://localhost:18006/
```

Docker Compose 会持久化挂载：

```text
./config.txt -> /app/config.txt
./workspaces -> /app/workspaces
./memory     -> /app/memory
./output     -> /app/output
```

宿主机已有服务占用 `18006` 时，可在 `.env` 中修改：

```ini
AFSIM_GEN_PORT=18007
```

### Python 直接启动

```bash
pip install -r requirements.txt
python -m api.cli serve --port 8000
```

也可以直接提交任务：

```bash
python -m api.cli run --prompt "生成一个红方雷达探测蓝方战斗机的场景"
python -m api.cli task <task_id>
```

## 配置

配置来源是 `config.txt`，环境变量优先级更高。常用配置如下：

```ini
EXECUTOR_MODE=local
AFSIM_INSTALL_DIR=/opt/afsim
MISSION_EXE=/opt/afsim/bin/mission
AFSIM_RUNNER_URL=

LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=
LLM_MODEL=gpt-oss:120b
LLM_TIMEOUT=300

CONCURRENCY=4
MAX_RETRIES=10
DEFAULT_END_TIME_SEC=7200
DEFAULT_ROUTE_SPEED=450 kts
WORKSPACES_DIR=workspaces
DB_PATH=workspaces/tasks.db
```

服务会检索 `references/*.md`，并在存在 `AFSIM_DOC_ROOT` 或同级 `afsimDoc` 时补充 AFSIM 官方源文档。官方文档按请求主题选择相关源文件和章节，不会把整个文档库一次性发送给 LLM。

## AFSIM 执行方式

### Linux 本地执行

适用于 AFSIM 已移植到 Linux，或本地已有可执行的 `mission`：

```ini
EXECUTOR_MODE=local
AFSIM_INSTALL_DIR=/opt/afsim
MISSION_EXE=/opt/afsim/bin/mission
```

### Windows Runner 远程执行

适用于服务部署在 Linux、AFSIM 仍安装在 Windows 的情况。

Windows 机器上编辑 [scripts/start_windows_runner.bat](scripts/start_windows_runner.bat) 顶部配置：

```bat
set "AFSIM_INSTALL_DIR=D:\Program Files\afsim2.9.0"
set "MISSION_EXE=%AFSIM_INSTALL_DIR%\bin\mission.exe"
set "RUNNER_HOST=0.0.0.0"
set "RUNNER_PORT=9001"
set "RUNNER_WORKSPACES=D:\afsim-runner\workspaces"
set "PYTHON_EXE=python"
```

双击启动后，在 Linux 服务端配置：

```ini
EXECUTOR_MODE=remote
AFSIM_RUNNER_URL=http://<windows-ip>:9001
```

Windows 依赖安装：

```powershell
python -m pip install -r requirements.txt
```

Runner 健康检查：

```text
http://<windows-ip>:9001/healthz
```

`RUNNER_WORKSPACES` 是 Windows Runner 保存每次任务临时脚本和 mission 输出的根目录，不是 LLM 知识库，也不是 Linux 服务端的工作目录。

## HTTP API

普通任务：

```http
POST /api/tasks
GET  /api/tasks/{task_id}
GET  /api/tasks/{task_id}/scenario.txt
GET  /api/tasks/{task_id}/log
POST /api/tasks/{task_id}/cancel
```

创建任务示例：

```bash
curl -X POST http://localhost:18006/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"prompt":"生成一个带航路的蓝方战斗机和红方雷达场景"}'
```

多轮会话：

```http
POST /api/conversations
GET  /api/conversations
GET  /api/conversations/{conversation_id}
POST /api/conversations/{conversation_id}/tasks
POST /api/conversations/{conversation_id}/finish
```

辅助接口：

```http
GET /api/prompt-history
GET /api/lessons
GET /api/pending
POST /api/pending/{file_id}/promote
GET /healthz
```

## 当前验证边界

当前任务成功的主要条件是：

1. 生成结果非空。
2. 脚本经过项目规范化处理。
3. `mission` 返回成功，且没有匹配到错误输出。
4. 成功脚本被保存到工作目录并归档。

当前还不能仅凭 `mission loaded OK` 证明：

- 平台确实按需求移动
- 雷达确实探测到目标
- 导弹确实发射或命中
- Warlock 图标和可视化效果正确

这些属于后续端到端业务验证范围。

## 知识来源

当前项目的知识来源分为两部分：

- `references/*.md`：项目整理的语法规则、官方 Demo 提炼内容和已验证错误经验。
- `afsimDoc/`：本地 AFSIM 2.9.0 文档包，包含 HTML、`html/_sources/docs` 官方源文档、命令索引、类索引、模型索引和 Demo 索引。

官方文档接入后，以官方文档和官方 Demo 为主要依据，以项目 MD 和 mission 验证规则作为补充。当前仍未接入完整 `afsim-script-skill` 工作流，只使用官方源文档做主题检索。

## 测试

```bash
PYTHONPATH=. pytest
```

真实 AFSIM 集成测试需要配置可执行的 `mission`，然后运行：

```bash
tests/integration/run.sh
```

## Codex TODO List

> 当前状态：opencode 已完成后端多轮会话接口；Codex 已补齐前端会话状态刷新和文档检索基础能力。

1. [x] 检查多轮修改是否始终基于当前脚本，不会重新生成并破坏已有内容。
2. [x] 修复知识检索只读取 MD 前 120 行的问题。
3. [x] 将 `language_grammar.md` 纳入语法类请求检索。
4. [x] 清理 `references/commands.md` 中与实际 AFSIM 语法冲突的 `{}` 示例。
5. [ ] 检查并统一 `SKILL.md`、其余 `references/*.md` 之间的规则冲突。
6. [x] 接入 `afsimDoc` 官方源文档的主题检索。
7. [ ] 接入完整 `afsim-script-skill` 工作流和官方 Demo 选择机制。
8. [ ] 区分官方文档、官方 Demo、项目验证规则和 LLM 推测内容，并在上下文中标注来源。
9. [ ] 检查雷达、导弹、战斗机的 `icon` / `category` 是否符合官方 Warlock 配置。
10. [ ] 增加 AFSIM 脚本结构和引用关系静态检查。
11. [ ] 设计用户需求到结构化验收条件的转换机制。
12. [ ] 解析 `evt`、`rep`、stdout 等仿真输出。
13. [ ] 增加平台移动、雷达探测、导弹发射、命中和平台摧毁等端到端业务验证。
14. [ ] 在前端展示每项业务验收条件的通过、失败和原因。
15. [x] 为文档检索和多轮会话补充基础测试。
16. [ ] 使用真实 AFSIM 2.9.0 Demo 完成端到端验证，并重新运行完整测试。
