import json
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from core.agent import TaskRequest, run_task
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


class ConversationNotFound(Exception):
    pass


class ConversationFinished(Exception):
    pass


class NoCurrentScript(Exception):
    pass


class EmptyInstruction(Exception):
    pass


@dataclass
class ConversationTurn:
    round: int
    task_id: str
    instruction: str | None
    state: str | None = None
    result: dict | None = None


@dataclass
class ConversationStatus:
    conversation_id: str
    created_at: str
    initial_prompt: str | None
    current_task_id: str | None
    state: str
    turns: list[ConversationTurn]


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
            conn.execute(
                "CREATE TABLE IF NOT EXISTS conversations ("
                "conversation_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, initial_prompt TEXT, "
                "current_task_id TEXT, state TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS conversation_turns ("
                "conversation_id TEXT NOT NULL, round INTEGER NOT NULL, task_id TEXT NOT NULL, "
                "instruction TEXT, PRIMARY KEY (conversation_id, round))"
            )
            cols = [row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()]
            if "conversation_id" not in cols:
                conn.execute("ALTER TABLE tasks ADD COLUMN conversation_id TEXT")
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
        with self._state_lock:
            cancelled = task_id in self._cancel
        if result.status == "success" and getattr(request, "conversation_id", None) and not cancelled:
            self._update_current_task(request.conversation_id, task_id)
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

    def create_conversation(self, request):
        conversation_id = uuid.uuid4().hex
        created_at = datetime.now().isoformat()
        initial_prompt = (getattr(request, "prompt", None) or "").strip() or None
        with self._db_lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute(
                "INSERT INTO conversations(conversation_id, created_at, initial_prompt, current_task_id, state) "
                "VALUES(?,?,?,?,?)",
                (conversation_id, created_at, initial_prompt, None, "active"),
            )
            conn.commit()
            conn.close()
        request.conversation_id = conversation_id
        task_id = self.submit(request)
        self._record_turn(conversation_id, 1, task_id, initial_prompt)
        return conversation_id

    def list_conversations(self, limit=50):
        limit = max(1, min(int(limit or 50), 200))
        with self._db_lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            rows = conn.execute(
                "SELECT c.conversation_id, c.created_at, c.initial_prompt, c.current_task_id, c.state, "
                "(SELECT COUNT(*) FROM conversation_turns t WHERE t.conversation_id = c.conversation_id) "
                "FROM conversations c ORDER BY c.created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            conn.close()
        return [
            {
                "conversation_id": r[0],
                "created_at": r[1],
                "initial_prompt": r[2],
                "current_task_id": r[3],
                "state": r[4],
                "turn_count": r[5],
            }
            for r in rows
        ]

    def get_conversation(self, conversation_id):
        with self._db_lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            row = conn.execute(
                "SELECT conversation_id, created_at, initial_prompt, current_task_id, state "
                "FROM conversations WHERE conversation_id=?",
                (conversation_id,),
            ).fetchone()
            turn_rows = []
            if row is not None:
                turn_rows = conn.execute(
                    "SELECT round, task_id, instruction FROM conversation_turns "
                    "WHERE conversation_id=? ORDER BY round",
                    (conversation_id,),
                ).fetchall()
            conn.close()
        if row is None:
            return None
        turns = []
        for t_round, t_task_id, t_instruction in turn_rows:
            status = self.get(t_task_id)
            turns.append(
                ConversationTurn(
                    round=t_round,
                    task_id=t_task_id,
                    instruction=t_instruction,
                    state=status.state if status else None,
                    result=status.result if status else None,
                )
            )
        return ConversationStatus(row[0], row[1], row[2], row[3], row[4], turns)

    def add_turn(self, conversation_id, instruction, options=None):
        instruction = (instruction or "").strip()
        if not instruction:
            raise EmptyInstruction(conversation_id)
        conversation = self.get_conversation(conversation_id)
        if conversation is None:
            raise ConversationNotFound(conversation_id)
        if conversation.state == "finished":
            raise ConversationFinished(conversation_id)
        script = self._current_script(conversation)
        request = TaskRequest(script=script, instruction=instruction, options=options, conversation_id=conversation_id)
        task_id = self.submit(request)
        with self._db_lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            state = conn.execute(
                "SELECT state FROM conversations WHERE conversation_id=?", (conversation_id,)
            ).fetchone()
            if state is not None and state[0] == "finished":
                conn.close()
                raise ConversationFinished(conversation_id)
            max_round = conn.execute(
                "SELECT MAX(round) FROM conversation_turns WHERE conversation_id=?", (conversation_id,)
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO conversation_turns(conversation_id, round, task_id, instruction) VALUES(?,?,?,?)",
                (conversation_id, (max_round or 0) + 1, task_id, instruction),
            )
            conn.commit()
            conn.close()
        return task_id

    def finish_conversation(self, conversation_id):
        with self._db_lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            cur = conn.execute(
                "UPDATE conversations SET state='finished' WHERE conversation_id=? AND state='active'",
                (conversation_id,),
            )
            conn.commit()
            conn.close()
        return cur.rowcount > 0

    def _current_script(self, conversation):
        if not conversation.current_task_id:
            raise NoCurrentScript(conversation.conversation_id)
        scenario = Path(self.config.workspaces_dir) / conversation.current_task_id / "scenario.txt"
        if scenario.exists():
            return scenario.read_text(encoding="utf-8", errors="replace")
        status = self.get(conversation.current_task_id)
        if status and status.result.get("script_text"):
            return status.result["script_text"]
        raise NoCurrentScript(conversation.conversation_id)

    def _record_turn(self, conversation_id, turn_round, task_id, instruction):
        with self._db_lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute(
                "INSERT INTO conversation_turns(conversation_id, round, task_id, instruction) VALUES(?,?,?,?)",
                (conversation_id, turn_round, task_id, instruction),
            )
            conn.commit()
            conn.close()

    def _update_current_task(self, conversation_id, task_id):
        with self._db_lock:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute(
                "UPDATE conversations SET current_task_id=? WHERE conversation_id=?",
                (task_id, conversation_id),
            )
            conn.commit()
            conn.close()
