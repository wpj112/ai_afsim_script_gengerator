from types import SimpleNamespace

from core import executor, fixer, matcher
from core.agent import TaskRequest, run_task
from core.config import Config
from core.executor import ExecutionResult
from core.matcher import MatchResult


def _fake_llm(propose_result=None):
    return SimpleNamespace(propose_fix=lambda script, err, hint: propose_result)


def _match(rule_id="E001", matched="mover", lessons_list=("L001",)):
    return MatchResult(rule_id, "exact", matched, 1, {"description": "缺 end_mover"}, list(lessons_list))


def test_success_path(tmp_path, monkeypatch):
    monkeypatch.setattr(executor, "run", lambda p, w, c, options=None: ExecutionResult(0, "", ""))
    result = run_task(TaskRequest(script="platform_type p WSF_PLATFORM\n"), Config(max_retries=3), None, {}, tmp_path, "t1")
    assert result.status == "success"
    assert result.report == {"message": "mission loaded OK"}
    assert result.retries == []
    assert result.final_script == tmp_path / "scenario.txt"
    assert (tmp_path / "scenario.txt").exists()


def test_unknown_error_creates_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(executor, "run", lambda p, w, c, options=None: ExecutionResult(1, "", "boom unknown"))
    monkeypatch.setattr(matcher, "match_output", lambda out, err, rules: [])
    result = run_task(TaskRequest(script="x\n"), Config(max_retries=3), None, {}, tmp_path, "t2")
    assert result.status == "needs_review"
    assert result.report["unknown_error"] == "boom unknown"
    pending = list((tmp_path / "pending").glob("*.md"))
    assert len(pending) == 1
    assert "task t2" in pending[0].read_text()


def test_template_fix_then_success(tmp_path, monkeypatch):
    calls = {"n": 0}

    def fake_run(p, w, c, options=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return ExecutionResult(1, "", "ERROR: missing end_mover")
        return ExecutionResult(0, "", "")

    monkeypatch.setattr(executor, "run", fake_run)
    monkeypatch.setattr(matcher, "match_output", lambda out, err, rules: [_match()])
    monkeypatch.setattr(fixer, "apply_fix", lambda path, m: True)
    result = run_task(TaskRequest(script="mover\n"), Config(max_retries=3), None, {}, tmp_path, "t3")
    assert result.status == "success"
    assert len(result.retries) == 1
    assert result.retries[0].attempt == 1
    assert result.retries[0].matched_rule == "E001"
    assert result.retries[0].diff


def test_max_retries_exceeded(tmp_path, monkeypatch):
    config = Config(max_retries=3)
    monkeypatch.setattr(executor, "run", lambda p, w, c, options=None: ExecutionResult(1, "", "ERROR: bad"))
    monkeypatch.setattr(matcher, "match_output", lambda out, err, rules: [_match()])
    monkeypatch.setattr(fixer, "apply_fix", lambda path, m: False)
    result = run_task(TaskRequest(script="bad\n"), config, _fake_llm(None), {}, tmp_path, "t4")
    assert result.status == "failed"
    assert result.report == {"max_retries_exceeded": 3}
    assert len(result.retries) == config.max_retries
    for r in result.retries:
        assert r.diff


def test_script_given_skips_generate(tmp_path, monkeypatch):
    monkeypatch.setattr(executor, "run", lambda p, w, c, options=None: ExecutionResult(0, "", ""))

    class BoomLLM:
        def generate_script(self, prompt, ctx):
            raise AssertionError("generate_script must not be called")

    result = run_task(TaskRequest(script="ok\n", prompt="make scenario"), Config(max_retries=3), BoomLLM(), {}, tmp_path, "t5")
    assert result.status == "success"


def test_prompt_generates_script(tmp_path, monkeypatch):
    calls = {"prompt": None}
    monkeypatch.setattr(executor, "run", lambda p, w, c, options=None: ExecutionResult(0, "", ""))

    class FakeLLM:
        def generate_script(self, prompt, ctx):
            calls["prompt"] = prompt
            return "platform_type p WSF_PLATFORM\n"

    result = run_task(TaskRequest(prompt="make a platform"), Config(max_retries=3), FakeLLM(), {}, tmp_path, "t6")
    assert result.status == "success"
    assert calls["prompt"] == "make a platform"
    assert (tmp_path / "scenario.txt").read_text() == "platform_type p WSF_PLATFORM\n"
