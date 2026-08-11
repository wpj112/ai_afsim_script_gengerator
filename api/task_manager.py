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


class TaskManager:
    def __init__(self, config=None, db_path=None, llm=None, rules=None):
        self.config = config or Config()
        self.db_path = Path(db_path or self.config.db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.llm = llm or LLMClient(self.config.llm_base_url, self.config.llm_api_key, self.config.llm_model)
        self.rules = rules if rules is not None else self._load_default_rules()
        self._cache = {}
        self._cancel = set()
        self._state_lock = threading.Lock()
        self._db_lock = threading.Lock()
        self._init_db()
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
        self._executor.submit(self._run, task_id, request, workdir)
        return task_id

    def _run(self, task_id, request, workdir):
        self._set_state(task_id, "running")
        result = run_task(request, self.config, self.llm, self.rules, workdir, task_id)
        self._set_state(task_id, result.status, retries=[asdict(r) for r in result.retries], result=result.report)

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
