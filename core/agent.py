import difflib
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core import executor, fixer, lessons, matcher
from core.generator import generate, modify
from core.script_normalizer import normalize_script

ARCHIVE_DIR = Path(__file__).resolve().parent.parent / "output" / "verified" / "scenario"


@dataclass
class TaskRequest:
    prompt: str | None = None
    script: str | None = None
    options: list[str] | None = None
    instruction: str | None = None
    conversation_id: str | None = None


@dataclass
class RetryRecord:
    attempt: int
    rc: int
    stdout: str
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
            if request.instruction:
                if not request.script:
                    return TaskResult("failed", retries, None, {"error": "no script for instruction"})
                final_script.write_text(
                    modify(llm, request.script, request.instruction, config),
                    encoding="utf-8",
                )
            elif request.script:
                final_script.write_text(
                    normalize_script(
                        request.script,
                        min_end_time_sec=config.default_end_time_sec,
                        default_route_speed=config.default_route_speed,
                    ),
                    encoding="utf-8",
                )
            elif request.prompt:
                final_script.write_text(generate(llm, request.prompt, config), encoding="utf-8")
            else:
                return TaskResult("failed", retries, None, {"error": "no prompt or script"})
        script_text = final_script.read_text(encoding="utf-8", errors="replace")
        if not script_text.strip():
            report = {"error": "generated script is empty"}
            llm_error = getattr(llm, "last_error", "")
            if llm_error:
                report["llm_error"] = llm_error
            return TaskResult("failed", retries, final_script, report)
        res = executor.run(final_script, workdir, config, request.options)
        if res.rc == 0 and "ERROR" not in res.stderr:
            report = {"message": "mission loaded OK", "script_text": script_text}
            try:
                ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
                archived = ARCHIVE_DIR / f"{task_id}_{final_script.name}"
                shutil.copy2(final_script, archived)
                report["archived_to"] = str(archived)
            except OSError:
                report["archived_to"] = None
            return TaskResult("success", retries, final_script, report)
        matches = matcher.match_output(res.stdout, res.stderr, rules)
        if not matches:
            combined_error = (res.stderr or res.stdout or "")[:1000]
            lessons.pend(res.stderr or res.stdout, workdir / "pending", note=f"task {task_id}")
            return TaskResult("needs_review", retries, final_script, {"unknown_error": combined_error})
        before = final_script.read_text()
        applied = fixer.apply_fix(final_script, matches[0])
        if not applied:
            patch = llm.propose_fix(before, res.stderr, matches[0].lessons)
            if patch:
                final_script.write_text(
                    normalize_script(
                        patch,
                        min_end_time_sec=config.default_end_time_sec,
                        default_route_speed=config.default_route_speed,
                    ),
                    encoding="utf-8",
                )
        after = final_script.read_text()
        lessons.record(matches, date, hot_dir)
        retries.append(RetryRecord(attempt, res.rc, res.stdout, res.stderr, matches[0].rule_id,
                                   _diff_snapshot(before, after, attempt, matches[0].rule_id)))
    return TaskResult("failed", retries, final_script, {"max_retries_exceeded": config.max_retries})


def _diff_snapshot(before, after, attempt, rule_id):
    diff = "\n".join(difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm=""))
    if not diff.strip():
        return f"attempt {attempt}: no change applied for {rule_id}"
    return diff
