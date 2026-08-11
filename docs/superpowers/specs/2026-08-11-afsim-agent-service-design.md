# AFSIM 智能体服务设计文档

> 日期：2026-08-11
> 状态：已获用户确认（Section 1-5 逐节批准）
> 目标项目：`afsim-script-generator`（原 GitHub 仓库：lookingforfeng/afsim-script-generator，现归属 wpj112/ai_afsim_script_gengerator）

## 1. 背景与目标

将 `afsim-script-generator`（v2，AI Skill 提示工程式 AFSIM 脚本生成器）改造为**端到端 AFSIM 智能体服务**：

- 吸收 `afsim-skill`（v1，海空兵棋）的教训体系、成果管理闭环、已验证语法白名单
- 以 v2 为主体单向增强，v1 项目保持原样
- 服务可独立运行：HTTP API + CLI，不依赖任何 IDE 会话
- 纠错闭环自动化：生成 → 执行 mission → 匹配错误 → 修正 → 重跑，N 次止损

## 2. 已确认的关键决策

| 决策项 | 结论 |
|--------|------|
| 集成形态 | 以 v2 为主体单向增强 |
| 集成方案 | 方案 A：模块化引擎（matcher/fixer/lessons 独立模块） |
| 错误匹配 | 程序化匹配 + LLM 修正 |
| 循环边界 | 自动重试 N 次（默认 3）后止损，交回人工 |
| 服务形态 | HTTP API + CLI |
| LLM 接入 | OpenAI 兼容 API 直连（/chat/completions） |
| 能力边界 | 端到端全流程（生成→验证→纠错→归档） |
| 并发模型 | 并发执行，每任务独立工作目录隔离 |
| 验证策略 | fixture 模拟 + Linux 真装 AFSIM |

## 3. 目录结构

```
afsim-script-generator/
├── SKILL.md                             # 更新：新增教训联动 + 自动纠错 + 归档流程
├── config.txt                           # 升级：跨平台 + LLM 配置
├── references/ ×9                       # 保留不动
├── api/                                 # 服务层（新增）
│   ├── main.py                          # FastAPI 入口
│   ├── models.py                        # Pydantic schema
│   ├── task_manager.py                  # 并发任务调度
│   └── cli.py                           # afsim-gen CLI 入口
├── core/                                # 引擎层（新增，scripts/ 提升）
│   ├── generator.py                     # LLM 生成脚本
│   ├── executor.py                      # mission 调用封装（并发安全）
│   ├── matcher.py                       # 程序化错误匹配器
│   ├── fixer.py                         # template 补丁 + llm_guided 编排
│   ├── agent.py                         # 端到端编排
│   ├── lessons.py                       # 教训生命周期
│   └── llm.py                           # OpenAI 兼容客户端封装
├── scripts/
│   ├── run_mission.py                   # 保留（executor 底层）
│   └── sync_error_rules.py              # errors-ref.md → error_rules.json 同步
├── memory/                              # v1 移植
│   ├── errors-ref.md                    # 人读索引（20 条 [E001]-[E020]）
│   ├── error_rules.json                 # 机读规则库（同步生成）
│   ├── pending/                         # 待确认教训队列
│   └── cold/                            # lesson-index.md + lesson-root-causes.md
├── output/
│   ├── staging/                         # 临时成果
│   └── verified/{scenario,component,template}/
├── workspaces/                          # 任务工作目录（并发隔离）
│   └── <task_id>/                       # 独立 cwd + 独立 log/output
├── tests/
│   ├── fixtures/                        # mission 报错样例
│   └── integration/                     # 集成测试脚本
├── requirements.txt
└── docs/superpowers/specs/              # 设计文档
```

## 4. 错误规则库 error_rules.json

由 `memory/errors-ref.md` 经 `sync_error_rules.py` 同步生成，schema：

```json
{
  "rules": [
    {
      "id": "E001",
      "keywords": ["Unknown command: platform_type"],
      "patterns": ["Unknown command:\\s+(\\S+)"],
      "root_cause": "缺少基类型 WSF_PLATFORM",
      "fix": {
        "type": "template | llm_guided",
        "description": "在 platform_type 行尾追加 WSF_PLATFORM"
      },
      "demo": "../Afsim_demoslists/engage项目汇总.md:330",
      "lessons": ["L004", "L012"]
    }
  ],
  "generated_at": "ISO 时间",
  "source": "memory/errors-ref.md"
}
```

- `fix.type`：`template`（程序化补丁）/ `llm_guided`（LLM 生成补丁）
- `lessons` 内联关联教训 ID
- 初始同步：20 条 [Exxx] 全量转 JSON；E001-E013 类多为 template，E014-E020 多为 llm_guided

## 5. 模块接口

### 5.1 matcher.py

```python
def match_output(stdout: str, stderr: str, rules: dict) -> list[MatchResult]: ...

@dataclass
class MatchResult:
    rule_id: str        # "E001"
    confidence: str     # "exact" | "pattern" | "contextual"
    matched_text: str   # 命中的原始报错行
    line_no: int        # mission 输出行号
    fix: dict           # 修正方案
    lessons: list[str]  # 关联教训 ID
```

匹配策略：先 keywords（大小写不敏感包含），再 patterns（正则）；多命中按规则 ID 顺序取前，同报错行只报一次。

### 5.2 auto_fix_loop 循环

```
for attempt in 1..N (N=MAX_RETRIES 默认3):
    rc, stdout, stderr = executor.run(script)
    if rc == 0 and "ERROR" not in stderr:  return 0   # 成功
    matches = matcher.match_output(...)
    if not matches:
        lessons.pend(stderr); return 2                 # 未知错误，需介入
    apply_fix(script, matches[0])
    lessons.record(...)                                # 教训记账
return 1                                               # 超限止损
```

退出码：`0` 成功 / `1` 超限失败 / `2` 未知错误需介入。

### 5.3 fixer.py 修正路径

| fix.type | 执行者 | 动作 |
|---|---|---|
| template | 程序 | 内置补丁器：追加基类型、补 end_*、改坐标分隔符、加单位；应用前打印 diff，应用前保守校验（end_* 配对计数、目标行唯一），校验不过降级 llm_guided |
| llm_guided | LLM | 打印规则提示 + 教训摘要，LLM 生成补丁；fixer 校验格式（end_* 配对、基类型存在、可解析性）不通过拒绝落盘，回退上一步快照 |

### 5.4 lessons.py 生命周期

- `record`：命中教训 → 追加 memory/hot/<date>.md
- `pend`：未知错误 → memory/pending/<date>_unknown.md
- `promote`：人工确认 → 升格 errors-ref.md + 重新同步 JSON
- `stats`：教训命中统计

升级闭环：`pending → (用户确认) → errors-ref.md → sync → error_rules.json`

## 6. 服务层

### 6.1 并发模型

- 每任务独立工作目录 `workspaces/<task_id>/`，mission 以该目录为 cwd 运行
- ThreadPoolExecutor(max_workers=config.concurrency) 调度；mission 本身是 subprocess 进程调用
- 任务状态机：`pending → running → fixing → success | failed | needs_review`，持久化 SQLite（workspaces/tasks.db），重启可恢复

### 6.2 HTTP API（FastAPI）

| 端点 | 方法 | 功能 |
|---|---|---|
| /api/tasks | POST | 提交需求（prompt 自然语言 或 script 直接给）→ task_id |
| /api/tasks/{id} | GET | 状态、纠错轮次历史（失败快照+修正 diff）、最终报告 |
| /api/tasks/{id}/log | GET | mission 原始 stdout/stderr |
| /api/tasks/{id}/cancel | POST | 取消运行中任务 |
| /api/lessons | GET | 教训命中统计 |
| /api/pending | GET | 未知错误待确认队列 |
| /api/pending/{id}/promote | POST | 教训升格（触发同步） |
| /healthz | GET | 存活检查 |

### 6.3 agent.py 服务内闭环

```
POST /api/tasks {prompt}
  → generator 调 LLM 生成脚本（注入 SKILL.md 关键规则 + references 摘要）
  → executor 跑 mission（工作目录隔离）
  → matcher 匹配 error_rules.json
      ├─ template 命中 → fixer 程序打补丁（diff 快照）→ 重跑
      ├─ llm_guided → 服务内调 LLM 生成补丁 → 校验 → 重跑
      └─ 未命中 → pending 队列 → needs_review（LLM 再尝试 1 次分析后放弃）
  → 成功 → 报告 → 提示归档 verified/ + 教训记账
  → 重试超 N → failed + 完整轨迹
```

### 6.4 CLI

```bash
afsim-gen serve
afsim-gen run --prompt "..." | --script x.txt
afsim-gen task <id>
afsim-gen lessons --stats
afsim-gen pending --promote <id>
```

## 7. 配置与 LLM 接入

### 7.1 config.txt

```
AFSIM_INSTALL_DIR=/opt/afsim
CONCURRENCY=4
MAX_RETRIES=3
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=
LLM_MODEL=deepseek-chat
WORKSPACES_DIR=./workspaces
DB_PATH=./workspaces/tasks.db
```

- 二进制自动探测：Windows `bin/mission.exe` / Linux `bin/mission`
- LLM 配置支持环境变量覆盖（LLM_BASE_URL/LLM_API_KEY/LLM_MODEL）

### 7.2 llm.py

```python
class LLMClient:
    def chat(self, messages, tools=None) -> str
    def generate_script(self, prompt, knowledge_context) -> str
    def propose_fix(self, script, error_report, lesson_hint) -> str | None
    def analyze_unknown(self, stderr, script) -> dict
```

- 统一 /chat/completions OpenAI 协议，可接 OpenAI/DeepSeek/Ollama/vLLM
- 生成/修正注入上下文：SKILL.md 关键规则摘要 + 命中错误库条目 + 关联教训段落（渐进披露，只注入命中部分）
- propose_fix 输出约束：只输出完整脚本或 diff，fixer 校验后再落盘

### 7.3 知识库接入

- 服务启动时 sync_error_rules.py 检查 errors-ref.md 与 JSON 哈希，变化自动重新同步
- generator 生成时按需求类型程序化检索 references/，匹配片段注入 prompt（"LLM 自行翻阅" → "程序化检索注入"）

## 8. 验证策略

### 8.1 三层验证

**L1 单元测试（纯 Linux，无 AFSIM）**
- matcher：fixture 报错样例（20 条 [Exxx] 真实风格输出）→ 断言命中规则/置信度/行号
- fixer：错误脚本 → 期望修正后脚本对，验证 end_* 配对、基类型追加、坐标替换
- lessons：pending → promote → 同步 JSON 生命周期
- sync_error_rules.py：MD → JSON 往返一致

**L2 集成测试（需真 AFSIM）**
- 预置 3-5 个故意写错场景，跑 auto_fix_loop 全流程，断言 mission 解析通过、rc=0
- Linux 真装 AFSIM 后执行，tests/integration/run.sh 自动发现 mission 二进制

**L3 端到端服务测试**
- 起服务 → POST 端到端需求 → 轮询到终态 → 校验报告结构 + 并发 2 任务工作目录隔离

### 8.2 风险与缓解

| 风险 | 缓解 |
|---|---|
| mission 输出格式不稳定 | keyword 优先，只依赖稳定子串；fixture 留多版本 |
| LLM 补丁破坏脚本 | fixer 校验（end_* 配对、基类型、可解析性）不通过拒绝落盘，回退快照 |
| 并发 mission 冲突 | 工作目录隔离 + 独立 log 文件名 + 并发上限可配 |
| Linux 无 AFSIM | L1 全覆盖，L2/L3 脚本就绪装好后一键跑 |

## 9. 实施顺序建议

1. git 基线（已完成：main + v1.0-baseline tag 推送至 wpj112/ai_afsim_script_gengerator）
2. memory/ 移植 + error_rules.json + sync_error_rules.py（L1 可测）
3. core/ 引擎层（matcher → fixer → executor → lessons → agent）
4. api/ 服务层 + CLI + SQLite 任务管理
5. config.txt 跨平台 + llm.py 接入
6. tests/ fixture + 三层测试
7. SKILL.md 更新 + README 更新
8. Linux 真装 AFSIM → L2/L3 验证
