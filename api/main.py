import json
import re
from fnmatch import fnmatch
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from api.models import ConversationCreate, ConversationTurnSubmit, TaskResponse, TaskSubmit
from api.task_manager import (
    ConversationFinished,
    ConversationNotFound,
    EmptyInstruction,
    NoCurrentScript,
    TaskManager,
)
from core import lessons
from core.agent import TaskRequest
from core.config import load_config

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT / "frontend"

TASK_ID_PATTERN = re.compile(r"[0-9a-fA-F]{32}")


def create_app(task_manager=None):
    app = FastAPI()
    manager = task_manager or TaskManager(load_config())

    if FRONTEND_DIR.exists():
        app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    class PromoteBody(BaseModel):
        confirm: bool = False

    @app.post("/api/tasks")
    def submit_task(body: TaskSubmit):
        task_id = manager.submit(
            TaskRequest(prompt=body.prompt, script=body.script, options=body.options)
        )
        status = manager.get(task_id)
        return TaskResponse(
            task_id=task_id,
            state=status.state,
            created_at=status.created_at,
            retries=status.retries,
            result=status.result,
        )

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: str):
        status = manager.get(task_id)
        if status is None:
            raise HTTPException(status_code=404, detail="task not found")
        return TaskResponse(
            task_id=status.task_id,
            state=status.state,
            created_at=status.created_at,
            retries=status.retries,
            result=status.result,
        )

    @app.get("/api/prompt-history")
    def list_prompt_history(limit: int = 50):
        if not hasattr(manager, "list_prompt_history"):
            return {"history": []}
        items = manager.list_prompt_history(limit)
        return {
            "history": [
                {
                    "task_id": item.task_id,
                    "prompt": item.prompt,
                    "options": item.options,
                    "created_at": item.created_at,
                    "state": item.state,
                }
                for item in items
            ]
        }

    @app.get("/api/tasks/{task_id}/log")
    def get_task_log(task_id: str):
        if not TASK_ID_PATTERN.fullmatch(task_id):
            raise HTTPException(status_code=404, detail="task not found")
        status = manager.get(task_id)
        if status is None:
            raise HTTPException(status_code=404, detail="task not found")
        workspaces_root = Path(manager.config.workspaces_dir).resolve()
        workdir = (workspaces_root / task_id).resolve()
        if not workdir.is_relative_to(workspaces_root):
            raise HTTPException(status_code=404, detail="task not found")
        if workdir.exists():
            files = sorted(p.name for p in workdir.iterdir() if p.is_file())
            if files:
                scenario_path = workdir / "scenario.txt"
                scenario_text = ""
                if scenario_path.exists() and scenario_path.is_file():
                    scenario_text = scenario_path.read_text(encoding="utf-8", errors="replace")
                return {
                    "task_id": task_id,
                    "files": files,
                    "scenario_text": scenario_text,
                    "degraded": True,
                    "note": "executor 尚未落盘日志文件，返回工作目录文件列表作为降级",
                }
        raise HTTPException(status_code=404, detail="no log files yet")

    @app.get("/api/tasks/{task_id}/scenario.txt")
    def get_task_scenario(task_id: str):
        if not TASK_ID_PATTERN.fullmatch(task_id):
            raise HTTPException(status_code=404, detail="task not found")
        status = manager.get(task_id)
        if status is None:
            raise HTTPException(status_code=404, detail="task not found")
        workspaces_root = Path(manager.config.workspaces_dir).resolve()
        scenario_path = (workspaces_root / task_id / "scenario.txt").resolve()
        if not scenario_path.is_relative_to(workspaces_root) or not scenario_path.exists():
            raise HTTPException(status_code=404, detail="scenario not found")
        return PlainTextResponse(
            scenario_path.read_text(encoding="utf-8", errors="replace"),
            headers={"Content-Disposition": 'inline; filename="scenario.txt"'},
        )

    @app.post("/api/tasks/{task_id}/cancel")
    def cancel_task(task_id: str):
        if manager.cancel(task_id):
            return {"cancelled": True}
        raise HTTPException(status_code=404, detail="task not found or already terminal")

    @app.post("/api/conversations")
    def create_conversation(body: ConversationCreate):
        conversation_id = manager.create_conversation(
            TaskRequest(prompt=body.prompt, script=body.script, options=body.options)
        )
        conversation = manager.get_conversation(conversation_id)
        return {
            "conversation_id": conversation_id,
            "state": conversation.state,
            "task_id": conversation.turns[0].task_id,
        }

    @app.get("/api/conversations")
    def list_conversations(limit: int = 50):
        if not hasattr(manager, "list_conversations"):
            return {"conversations": []}
        return {"conversations": manager.list_conversations(limit)}

    @app.get("/api/conversations/{conversation_id}")
    def get_conversation(conversation_id: str):
        conversation = manager.get_conversation(conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        return {
            "conversation_id": conversation.conversation_id,
            "created_at": conversation.created_at,
            "initial_prompt": conversation.initial_prompt,
            "current_task_id": conversation.current_task_id,
            "state": conversation.state,
            "turns": [
                {
                    "round": t.round,
                    "task_id": t.task_id,
                    "instruction": t.instruction,
                    "state": t.state,
                    "result": t.result or {},
                }
                for t in conversation.turns
            ],
        }

    @app.post("/api/conversations/{conversation_id}/tasks")
    def submit_conversation_turn(conversation_id: str, body: ConversationTurnSubmit):
        try:
            task_id = manager.add_turn(conversation_id, body.instruction, body.options)
        except ConversationNotFound:
            raise HTTPException(status_code=404, detail="conversation not found")
        except ConversationFinished:
            raise HTTPException(status_code=409, detail="conversation already finished")
        except NoCurrentScript:
            raise HTTPException(status_code=409, detail="conversation has no successful script yet")
        except EmptyInstruction:
            raise HTTPException(status_code=400, detail="instruction required")
        return {"task_id": task_id}

    @app.post("/api/conversations/{conversation_id}/finish")
    def finish_conversation(conversation_id: str):
        if manager.finish_conversation(conversation_id):
            return {"finished": True}
        raise HTTPException(status_code=404, detail="conversation not found or already finished")

    @app.get("/api/lessons")
    def lesson_stats():
        try:
            rules_path = ROOT / "memory" / "error_rules.json"
            rules = json.loads(rules_path.read_text(encoding="utf-8"))
            return lessons.stats(rules, ROOT / "memory" / "hot")
        except Exception:
            raise HTTPException(status_code=500, detail="error rules unavailable")

    @app.get("/api/pending")
    def list_pending():
        try:
            pending_dir = ROOT / "memory" / "pending"
            items = []
            if pending_dir.exists():
                for f in sorted(pending_dir.glob("*unknown*.md")):
                    lines = f.read_text(encoding="utf-8").splitlines()
                    summary = next((line for line in lines if line.strip()), "")
                    items.append({"file": f.name, "summary": summary})
            return {"pending": items}
        except Exception:
            raise HTTPException(status_code=500, detail="pending unavailable")

    @app.post("/api/pending/{file_id}/promote")
    def promote_pending(file_id: str, body: PromoteBody):
        if not body.confirm:
            raise HTTPException(status_code=400, detail="confirm required")
        if not (file_id.endswith("unknown") or fnmatch(file_id, "*unknown*.md")):
            raise HTTPException(status_code=400, detail="invalid file id")
        pending_dir = ROOT / "memory" / "pending"
        pending_path = (pending_dir / file_id).resolve()
        if not pending_path.is_relative_to(pending_dir.resolve()):
            raise HTTPException(status_code=400, detail="invalid file id")
        if not pending_path.exists():
            pending_path = pending_dir / f"{file_id}.md"
        if not lessons.promote(pending_path, ROOT / "memory" / "errors-ref.md", confirm=True):
            raise HTTPException(status_code=404, detail="pending file not found")
        return {"promoted": True}

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/")
    def frontend_index():
        index_path = FRONTEND_DIR / "index.html"
        if not index_path.exists():
            raise HTTPException(status_code=404, detail="frontend not found")
        return FileResponse(index_path)

    @app.exception_handler(Exception)
    def unexpected_error(request, exc):
        return JSONResponse(status_code=500, content={"detail": "internal error"})

    return app


_manager = TaskManager(load_config())
app = create_app(task_manager=_manager)
