import json
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from core.agent import run_task
from core.config import Config
from core.llm import LLMClient


@dataclass
class TaskStatus:
    task_id: str
    state: str
    created_at: str
    retries: list
    result: dict


@dataclass
class PromptHistoryItem:
    task_id: str
    prompt: str
    options: list
    created_at: str
    state: str | None = None


class TaskManager:
    def __init__(self, config=None, db_path=None, llm=None, rules=None):
        self.config = config or Config()
        self.db_path = Path(db_path or self.config.db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.llm = llm or LLMClient(
            self.config.llm_base_url,
            self.config.llm_api_key,
            self.config.llm_model,
            timeout=self.config.llm_timeout,
            default_end_time_sec=self.config.default_end_time_sec,
            default_route_speed=self.config.default_route_speed,
        )
        self.rules = rules if rules is not None else self._load_default_rules()
        self._cache = {}
        self._cancel = set()
        self._state_lock = threading.Lock()
        self._db_lock = threading.Lock()
        self._init_db()
        self._recover_stale()
        self._executor = ThreadPoolExecutor(max_workers=self.config.concurrency)

    def _load_default_rules(self):
        rules_path = Path(__file__).resolve().parent.parent / "memory" / "error_rules.json"
        with open(rules_path, encoding="utf-8") as f:
            return json.load(f)

    def _init_db(self):
        with self._db_lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS tasks (task_id TEXT PRIMARY KEY, state TEXT, created_at TEXT, updated_at TEXT, result TEXT)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS prompt_history ("
                "task_id TEXT PRIMARY KEY, prompt TEXT NOT NULL, options TEXT NOT NULL, created_at TEXT NOT NULL)"
            )
            conn.commit()
            conn.close()

    def submit(self, request):
        task_id = uuid.uuid4().hex
        workdir = Path(self.config.workspaces_dir) / task_id
        workdir.mkdir(parents=True, exist_ok=True)
        created_at = datetime.now().isoformat()
        status = TaskStatus(task_id, "pending", created_at, [], {})
        self._cache[task_id] = status
        self._persist(task_id, status, created_at)
        self._record_prompt_history(task_id, request, created_at)
        self._executor.submit(self._run, task_id, request, workdir)
        return task_id

    def list_prompt_history(self, limit=50):
        limit = max(1, min(int(limit or 50), 200))
        with self._db_lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            rows = conn.execute(
                "SELECT h.task_id, h.prompt, h.options, h.created_at, t.state "
                "FROM prompt_history h LEFT JOIN tasks t ON t.task_id = h.task_id "
                "ORDER BY h.created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            conn.close()
        items = []
        for task_id, prompt, options_raw, created_at, state in rows:
            try:
                options = json.loads(options_raw) if options_raw else []
            except json.JSONDecodeError:
                options = []
            items.append(PromptHistoryItem(task_id, prompt, options, created_at, state))
        return items

    def _record_prompt_history(self, task_id, request, created_at):
        prompt = (getattr(request, "prompt", None) or "").strip()
        if not prompt:
            return
        options = json.dumps(getattr(request, "options", None) or [], ensure_ascii=False)
        with self._db_lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute(
                "INSERT INTO prompt_history(task_id, prompt, options, created_at) VALUES(?,?,?,?) "
                "ON CONFLICT(task_id) DO UPDATE SET prompt=excluded.prompt, options=excluded.options, created_at=excluded.created_at",
                (task_id, prompt, options, created_at),
            )
            conn.commit()
            conn.close()

    def _run(self, task_id, request, workdir):
        self._set_state(task_id, "running")
        try:
            result = run_task(request, self.config, self.llm, self.rules, workdir, task_id)
        except Exception as exc:
            self._set_state(task_id, "failed", result={"error": str(exc)})
            return
        self._set_state(task_id, result.status, retries=[asdict(r) for r in result.retries], result=result.report)

    def _recover_stale(self):
        with self._db_lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            rows = conn.execute(
                "SELECT task_id, state, created_at, result FROM tasks WHERE state IN ('running','pending')"
            ).fetchall()
            conn.close()
        for task_id, state, created_at, payload_raw in rows:
            payload = json.loads(payload_raw) if payload_raw else {}
            result = dict(payload.get("result") or {})
            result["error"] = "stale task recovered after restart"
            status = TaskStatus(task_id, "failed", created_at, payload.get("retries", []), result)
            self._cache[task_id] = status
            self._persist(task_id, status, created_at)

    def _set_state(self, task_id, state, retries=None, result=None):
        with self._state_lock:
            if task_id in self._cancel:
                state = "cancelled"
            status = self._cache.get(task_id)
            if status is None:
                return
            status.state = state
            if retries is not None:
                status.retries = retries
            if result is not None:
                status.result = result
        self._persist(task_id, status, status.created_at)

    def _persist(self, task_id, status, created_at):
        payload = json.dumps({"retries": status.retries, "result": status.result}, ensure_ascii=False)
        with self._db_lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute(
                "INSERT INTO tasks(task_id, state, created_at, updated_at, result) VALUES(?,?,?,?,?) "
                "ON CONFLICT(task_id) DO UPDATE SET state=excluded.state, updated_at=excluded.updated_at, result=excluded.result",
                (task_id, status.state, created_at, datetime.now().isoformat(), payload),
            )
            conn.commit()
            conn.close()

    def get(self, task_id):
        if task_id in self._cache:
            return self._cache[task_id]
        with self._db_lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            row = conn.execute("SELECT task_id, state, created_at, result FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            conn.close()
        if row is None:
            return None
        payload = json.loads(row[3])
        status = TaskStatus(row[0], row[1], row[2], payload.get("retries", []), payload.get("result", {}))
        self._cache[task_id] = status
        return status

    def cancel(self, task_id):
        with self._state_lock:
            status = self._cache.get(task_id)
            if status is None or status.state in ("success", "failed", "needs_review", "cancelled"):
                return False
            self._cancel.add(task_id)
        self._set_state(task_id, "cancelled")
        return True
