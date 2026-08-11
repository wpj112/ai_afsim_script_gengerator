import json
import re

import httpx


class LLMClient:
    def __init__(self, base_url, api_key, model, transport=None):
        self.model = model
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            transport=transport,
        )

    def chat(self, messages, tools=None):
        payload = {"model": self.model, "messages": messages}
        if tools is not None:
            payload["tools"] = tools
        try:
            resp = self._client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return content if content is not None else ""
        except Exception:
            return ""

    def generate_script(self, prompt, knowledge_context):
        system = (
            "你是 AFSIM 脚本生成专家。严格遵循以下规则："
            "1) 脚本文件必须以 .txt 扩展名保存；"
            "2) 速度、时间、高度、距离等参数必须带单位（如 kts、sec、ft msl）；"
            "3) 所有块必须以对应的 end_ 关键字闭合（如 end_platform_type、end_mover）；"
            "4) 坐标使用 d:m:s N/S e/w 格式。"
            "以下是与本次生成相关的知识上下文：\n" + knowledge_context
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        return self.chat(messages)

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
