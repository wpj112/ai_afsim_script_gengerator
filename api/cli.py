import argparse
import json
import sys
import time
from pathlib import Path

import uvicorn

from api.main import app
from api.task_manager import TaskManager
from core import lessons
from core.agent import TaskRequest
from core.config import load_config

ROOT = Path(__file__).resolve().parent.parent

TERMINAL_STATES = ("success", "failed", "needs_review", "cancelled")
POLL_INTERVAL = 0.5
POLL_TIMEOUT = 300


def cmd_serve(args):
    uvicorn.run(app, host="0.0.0.0", port=args.port)


def cmd_run(args):
    manager = TaskManager(load_config())
    request = TaskRequest(prompt=args.prompt, script=args.script)
    task_id = manager.submit(request)
    print(f"task {task_id} submitted")
    deadline = time.time() + POLL_TIMEOUT
    status = manager.get(task_id)
    while status.state not in TERMINAL_STATES and time.time() < deadline:
        time.sleep(POLL_INTERVAL)
        status = manager.get(task_id)
    if status.state not in TERMINAL_STATES:
        print(f"task {task_id} still {status.state} after {POLL_TIMEOUT}s timeout")
    _print_report(task_id, status)


def cmd_task(args):
    manager = TaskManager(load_config())
    status = manager.get(args.task_id)
    if status is None:
        print(f"task {args.task_id} not found")
        return 1
    _print_report(args.task_id, status)
    return 0


def cmd_lessons(args):
    rules_path = ROOT / "memory" / "error_rules.json"
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    counts = lessons.stats(rules, ROOT / "memory" / "hot")
    for rule_id, count in counts.items():
        print(f"{rule_id}: {count}")


def cmd_pending(args):
    if args.promote:
        _promote(args.promote, args.yes)
        return
    pending_dir = ROOT / "memory" / "pending"
    items = []
    if pending_dir.exists():
        for f in sorted(pending_dir.glob("*unknown*.md")):
            lines = f.read_text(encoding="utf-8").splitlines()
            summary = next((line for line in lines if line.strip()), "")
            items.append(f"{f.name}: {summary}")
    for item in items:
        print(item)
    if not items:
        print("no pending items")


def _promote(file_id, yes):
    confirm = yes
    if not confirm:
        answer = input(f"promote {file_id}? [y/N] ")
        confirm = answer.strip().lower() in ("y", "yes")
    if not confirm:
        print("aborted")
        return
    pending_dir = ROOT / "memory" / "pending"
    pending_path = (pending_dir / file_id).resolve()
    if not pending_path.exists():
        pending_path = pending_dir / f"{file_id}.md"
    if lessons.promote(pending_path, ROOT / "memory" / "errors-ref.md", confirm=confirm):
        print(f"promoted {pending_path.name}")
    else:
        print("pending file not found")


def _print_report(task_id, status):
    print(f"task {task_id} state={status.state}")
    if status.retries:
        print("retries:")
        for r in status.retries:
            print(
                f"  attempt {r.get('attempt')}: rc={r.get('rc')} "
                f"rule={r.get('matched_rule')} stderr={r.get('stderr', '')[:200]}"
            )
    if status.result:
        print(f"final: {status.result}")


def build_parser():
    parser = argparse.ArgumentParser(prog="afsim-gen")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="start the API server")
    p_serve.add_argument("--port", type=int, default=8000)

    p_run = sub.add_parser("run", help="submit a task and wait for the result")
    group = p_run.add_mutually_exclusive_group(required=True)
    group.add_argument("--prompt", help="task prompt")
    group.add_argument("--script", help="path to an existing scenario script")

    p_task = sub.add_parser("task", help="query task status")
    p_task.add_argument("task_id")

    p_lessons = sub.add_parser("lessons", help="lesson tools")
    p_lessons.add_argument("--stats", action="store_true", help="print lesson hit statistics")

    p_pending = sub.add_parser("pending", help="manage the pending queue")
    p_pending.add_argument("--promote", help="pending file id to promote")
    p_pending.add_argument("--yes", action="store_true", help="skip confirmation")

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "serve": cmd_serve,
        "run": cmd_run,
        "task": cmd_task,
        "lessons": cmd_lessons,
        "pending": cmd_pending,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    main()
