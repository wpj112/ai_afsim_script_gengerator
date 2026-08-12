import pytest
from types import SimpleNamespace

from core import agent, executor, fixer, matcher
from core.agent import TaskRequest, run_task
from core.config import Config
from core.executor import ExecutionResult
from core.matcher import MatchResult


@pytest.fixture(autouse=True)
def _archive_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "ARCHIVE_DIR", tmp_path / "verified")


def _fake_llm(propose_result=None):
    return SimpleNamespace(propose_fix=lambda script, err, hint: propose_result)


def _match(rule_id="E001", matched="mover", lessons_list=("L001",)):
    return MatchResult(rule_id, "exact", matched, 1, {"description": "缺 end_mover"}, list(lessons_list))


def test_success_path(tmp_path, monkeypatch):
    monkeypatch.setattr(executor, "run", lambda p, w, c, options=None: ExecutionResult(0, "", ""))
    script = "platform_type p WSF_PLATFORM\n"
    result = run_task(TaskRequest(script=script), Config(max_retries=3), None, {}, tmp_path, "t1")
    assert result.status == "success"
    assert result.report["message"] == "mission loaded OK"
    assert result.report["script_text"] == script + "end_time 7200 sec\n"
    archived = tmp_path / "verified" / "t1_scenario.txt"
    assert result.report["archived_to"] == str(archived)
    assert archived.exists()
    assert archived.read_text() == script + "end_time 7200 sec\n"
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


def test_user_script_is_normalized_before_mission(tmp_path, monkeypatch):
    monkeypatch.setattr(executor, "run", lambda p, w, c, options=None: ExecutionResult(0, "", ""))
    result = run_task(
        TaskRequest(script="```afsim\ntime\n   duration 12 sec\nend_time\n```\n"),
        Config(max_retries=3),
        None,
        {},
        tmp_path,
        "t5b",
    )
    assert result.status == "success"
    assert (tmp_path / "scenario.txt").read_text() == "end_time 7200 sec\n"


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
    assert (tmp_path / "scenario.txt").read_text() == "platform_type p WSF_PLATFORM\nend_time 7200 sec\n"


def test_empty_generated_script_fails_before_mission(tmp_path, monkeypatch):
    calls = {"run": 0}

    def fake_run(p, w, c, options=None):
        calls["run"] += 1
        return ExecutionResult(0, "", "")

    monkeypatch.setattr(executor, "run", fake_run)

    class EmptyLLM:
        def generate_script(self, prompt, ctx):
            return ""

    result = run_task(TaskRequest(prompt="make a platform"), Config(max_retries=3), EmptyLLM(), {}, tmp_path, "t7")
    assert result.status == "failed"
    assert result.report == {"error": "generated script is empty"}
    assert calls["run"] == 0


def test_empty_user_script_fails_before_mission(tmp_path, monkeypatch):
    calls = {"run": 0}

    def fake_run(p, w, c, options=None):
        calls["run"] += 1
        return ExecutionResult(0, "", "")

    monkeypatch.setattr(executor, "run", fake_run)
    result = run_task(TaskRequest(script=" \n"), Config(max_retries=3), None, {}, tmp_path, "t8")
    assert result.status == "failed"
    assert result.report == {"error": "generated script is empty"}
    assert calls["run"] == 0


def test_llm_patch_is_normalized_before_retry(tmp_path, monkeypatch):
    calls = {"n": 0}

    def fake_run(p, w, c, options=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return ExecutionResult(1, "", "ERROR: unhandled")
        assert p.read_text() == "end_time 7200 sec\n"
        return ExecutionResult(0, "", "")

    monkeypatch.setattr(executor, "run", fake_run)
    monkeypatch.setattr(matcher, "match_output", lambda out, err, rules: [_match()])
    monkeypatch.setattr(fixer, "apply_fix", lambda path, m: False)
    result = run_task(
        TaskRequest(script="bad\n"),
        Config(max_retries=3),
        _fake_llm("```afsim\ntime\n   duration 33 sec\nend_time\n```\n"),
        {},
        tmp_path,
        "t9",
    )
    assert result.status == "success"
