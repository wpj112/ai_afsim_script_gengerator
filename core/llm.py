import json
import re

import httpx


class LLMClient:
    def __init__(
        self,
        base_url,
        api_key,
        model,
        transport=None,
        timeout=300,
        default_end_time_sec=7200,
        default_route_speed="450 kts",
    ):
        self.model = model
        self.default_end_time_sec = default_end_time_sec
        self.default_route_speed = default_route_speed
        self.last_error = ""
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers=headers,
            transport=transport,
            timeout=timeout,
        )

    def chat(self, messages, tools=None):
        payload = {"model": self.model, "messages": messages}
        if tools is not None:
            payload["tools"] = tools
        try:
            resp = self._client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            self.last_error = ""
            return content if content is not None else ""
        except Exception as exc:
            self.last_error = str(exc)
            return ""

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

    def propose_fix(self, script, error_report, lesson_hint):
        system = (
            "你只输出修正后的完整 AFSIM 脚本内容，不含任何解释、注释或额外文字。"
        )
        user = (
            f"以下是报错的 AFSIM 脚本：\n{script}\n\n"
            f"错误报告：\n{error_report}\n\n"
            f"历史教训提示：\n{lesson_hint}"
        )
        result = self.chat([{"role": "system", "content": system}, {"role": "user", "content": user}])
        return result if result else None

    def analyze_unknown(self, stderr, script):
        system = "你只输出 JSON，格式为 {\"cause\": \"...\", \"suggestion\": \"...\"}，不要输出其他内容。"
        user = f"AFSIM 脚本运行报错（标准错误输出）：\n{stderr}\n\n脚本内容：\n{script}"
        content = self.chat([{"role": "system", "content": system}, {"role": "user", "content": user}])
        cause, suggestion = "", ""
        if content:
            body = content[content.find("{"):content.rfind("}") + 1]
            try:
                parsed = json.loads(body)
                cause = parsed.get("cause", "")
                suggestion = parsed.get("suggestion", "")
            except Exception:
                m_cause = re.search(r'"cause"\s*:\s*"([^"]*)"', content)
                m_suggestion = re.search(r'"suggestion"\s*:\s*"([^"]*)"', content)
                if m_cause:
                    cause = m_cause.group(1)
                if m_suggestion:
                    suggestion = m_suggestion.group(1)
        return {"cause": cause, "suggestion": suggestion}
