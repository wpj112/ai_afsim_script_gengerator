from pathlib import Path

from core.script_normalizer import normalize_script

_KEYWORD_DOCS = [
    (["radar", "sensor", "esm", "eoir"], "sensor_types_reference.md"),
    (["aircraft", "air", "plane", "mover"], "mover_reference.md"),
    (["weapon", "missile"], "commands_reference.md"),
    (["processor", "script", "api"], "script_api_reference.md"),
    (["route", "position"], "commands_reference.md"),
]
_ALWAYS_DOCS = ["file_structure.md", "script_syntax_critical.md", "common_mistakes.md"]
_DEFAULT_DOCS = ["examples.md"]
_CHAR_LIMIT = 5000
_LINE_LIMIT = 120


def retrieve_knowledge(query: str, references_dir: Path) -> str:
    refs = Path(references_dir)
    if not refs.is_dir():
        return ""
    query = (query or "").lower()
    docs = list(_ALWAYS_DOCS)
    for keywords, doc in _KEYWORD_DOCS:
        if any(kw in query for kw in keywords) and doc not in docs:
            docs.append(doc)
    if len(docs) == len(_ALWAYS_DOCS):
        docs.extend(_DEFAULT_DOCS)
    fragments = []
    for doc in docs:
        path = refs / doc
        if not path.is_file():
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        fragment = f"{doc}:\n" + "\n".join(lines[:_LINE_LIMIT])
        fragments.append(fragment[:_CHAR_LIMIT])
    return "\n\n".join(fragments)


def generate(llm, prompt, config):
    refs_dir = Path(__file__).resolve().parent.parent / "references"
    knowledge_context = retrieve_knowledge(prompt, refs_dir)
    min_end_time_sec = getattr(config, "default_end_time_sec", 7200) if config is not None else 7200
    default_route_speed = getattr(config, "default_route_speed", "450 kts") if config is not None else "450 kts"
    return normalize_script(
        llm.generate_script(prompt, knowledge_context),
        min_end_time_sec=min_end_time_sec,
        default_route_speed=default_route_speed,
    )
