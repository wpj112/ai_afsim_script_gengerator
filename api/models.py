from typing import Optional

from pydantic import BaseModel


class TaskSubmit(BaseModel):
    prompt: Optional[str] = None
    script: Optional[str] = None
    options: Optional[list[str]] = None


class TaskResponse(BaseModel):
    task_id: str
    state: str
    created_at: str = ""
    retries: list = []
    result: dict = {}
