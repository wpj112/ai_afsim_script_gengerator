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


def test_chat_posts_to_chat_completions_with_tools():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["body"] = request.read()
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = LLMClient("http://x/v1", "k", "m", transport=httpx.MockTransport(handler))
    assert client.chat([{"role": "user", "content": "hi"}], tools=[{"type": "function"}]) == "ok"
    assert captured["url"].endswith("/chat/completions")
    assert b'"tools":[' in captured["body"]


def test_chat_content_none_returns_empty():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": None}}]})

    client = LLMClient("http://x/v1", "k", "m", transport=httpx.MockTransport(handler))
    assert client.chat([{"role": "user", "content": "hi"}]) == ""


def test_propose_fix_returns_script():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "fixed script"}}]})

    client = LLMClient("http://x/v1", "k", "m", transport=httpx.MockTransport(handler))
    assert client.propose_fix("bad script", "E001", "add base type") == "fixed script"


def test_propose_fix_returns_none_on_error():
    def handler(request):
        return httpx.Response(500)

    client = LLMClient("http://x/v1", "k", "m", transport=httpx.MockTransport(handler))
    assert client.propose_fix("bad script", "E001", "hint") is None


def test_analyze_unknown_parses_json():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"cause": "bad cmd", "suggestion": "use end_platform_type"}'}}]})

    client = LLMClient("http://x/v1", "k", "m", transport=httpx.MockTransport(handler))
    result = client.analyze_unknown("stderr out", "script")
    assert result == {"cause": "bad cmd", "suggestion": "use end_platform_type"}


def test_analyze_unknown_falls_back_on_bad_response():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})

    client = LLMClient("http://x/v1", "k", "m", transport=httpx.MockTransport(handler))
    assert client.analyze_unknown("stderr out", "script") == {"cause": "", "suggestion": ""}


def test_generate_script_includes_knowledge_context():
    captured = {}

    def handler(request):
        captured["body"] = request.read()
        return httpx.Response(200, json={"choices": [{"message": {"content": "script"}}]})

    client = LLMClient("http://x/v1", "k", "m", transport=httpx.MockTransport(handler))
    client.generate_script("make scenario", "rules")
    body = captured["body"]
    assert b"rules" in body
    assert b"make scenario" in body
    assert b".txt" in body
