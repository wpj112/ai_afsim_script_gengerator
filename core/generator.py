from pathlib import Path

_KEYWORD_DOCS = [
    (["radar", "sensor", "esm", "eoir"], "sensor_types_reference.md"),
    (["aircraft", "air", "plane", "mover"], "mover_reference.md"),
    (["weapon", "missile"], "commands_reference.md"),
    (["processor", "script", "api"], "script_api_reference.md"),
    (["route", "position"], "commands_reference.md"),
]
_DEFAULT_DOCS = ["file_structure.md", "examples.md"]
_CHAR_LIMIT = 2000
_LINE_LIMIT = 40


def retrieve_knowledge(query: str, references_dir: Path) -> str:
    refs = Path(references_dir)
    if not refs.is_dir():
        return ""
    query = (query or "").lower()
    docs = []
    for keywords, doc in _KEYWORD_DOCS:
        if any(kw in query for kw in keywords):
            docs.append(doc)
    if not docs:
        docs = list(_DEFAULT_DOCS)
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
    return llm.generate_script(prompt, knowledge_context)
