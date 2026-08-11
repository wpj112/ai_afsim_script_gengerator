import difflib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core import executor, fixer, lessons, matcher
from core.generator import generate


@dataclass
class TaskRequest:
    prompt: str | None = None
    script: str | None = None
    options: list[str] | None = None


@dataclass
class RetryRecord:
    attempt: int
    rc: int
    stderr: str
    matched_rule: str | None
    diff: str


@dataclass
class TaskResult:
    status: str
    retries: list[RetryRecord]
    final_script: Path | None
    report: dict


def run_task(request, config, llm, rules, workdir, task_id):
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    final_script = workdir / "scenario.txt"
    retries = []
    date = datetime.now().strftime("%Y-%m-%d")
    hot_dir = Path(__file__).resolve().parent.parent / "memory" / "hot"
    hot_dir.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, config.max_retries + 1):
        if not final_script.exists():
            if request.script:
                final_script.write_text(request.script)
            elif request.prompt:
                final_script.write_text(generate(llm, request.prompt, config))
            else:
                return TaskResult("failed", retries, None, {"error": "no prompt or script"})
        res = executor.run(final_script, workdir, config, request.options)
        if res.rc == 0 and "ERROR" not in res.stderr:
            return TaskResult("success", retries, final_script, {"message": "mission loaded OK"})
        matches = matcher.match_output(res.stdout, res.stderr, rules)
        if not matches:
            lessons.pend(res.stderr, workdir / "pending", note=f"task {task_id}")
            return TaskResult("needs_review", retries, final_script, {"unknown_error": res.stderr[:500]})
        before = final_script.read_text()
        applied = fixer.apply_fix(final_script, matches[0])
        if not applied:
            patch = llm.propose_fix(before, res.stderr, matches[0].lessons)
            if patch:
                final_script.write_text(patch)
        after = final_script.read_text()
        lessons.record(matches, date, hot_dir)
        retries.append(RetryRecord(attempt, res.rc, res.stderr, matches[0].rule_id,
                                   _diff_snapshot(before, after, attempt, matches[0].rule_id)))
    return TaskResult("failed", retries, final_script, {"max_retries_exceeded": config.max_retries})


def _diff_snapshot(before, after, attempt, rule_id):
    diff = "\n".join(difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm=""))
    if not diff.strip():
        return f"attempt {attempt}: no change applied for {rule_id}"
    return diff
