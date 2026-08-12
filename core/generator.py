import re
import os
from pathlib import Path

from core.script_normalizer import normalize_script

_KEYWORD_DOCS = [
    (["radar", "sensor", "esm", "eoir", "雷达", "传感器", "电子支援"], "sensor_types_reference.md"),
    (["aircraft", "air", "plane", "mover", "战斗机", "飞机", "无人机", "机动"], "mover_reference.md"),
    (["weapon", "missile", "武器", "导弹", "炸弹"], "commands_reference.md"),
    (["processor", "script", "api", "处理器", "脚本", "函数", "变量"], "script_api_reference.md"),
    (["route", "position", "航路", "航线", "航点", "位置", "坐标"], "commands_reference.md"),
    (["syntax", "grammar", "语法", "函数", "变量", "事件", "processor", "处理器"], "language_grammar.md"),
]
_ALWAYS_DOCS = ["file_structure.md", "script_syntax_critical.md", "common_mistakes.md"]
_DEFAULT_DOCS = ["examples.md"]
_CHAR_LIMIT = 5000
_OFFICIAL_CHAR_LIMIT = 7000
_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+?)\s*$")

_OFFICIAL_DOCS = {
    "platform": ("platform.rst.txt", "platform_type.rst.txt"),
    "route": ("user_manual/p2-2_primer_mover_routes.rst.txt", "mover.rst.txt"),
    "mover": ("mover.rst.txt", "predefined_mover_types.rst.txt"),
    "sensor": ("wsf_radar_sensor.rst.txt", "sensor_related_commands.rst.txt"),
    "radar": ("wsf_radar_sensor.rst.txt", "sensor_related_commands.rst.txt"),
    "weapon": ("weapon.rst.txt", "weapon_related_commands.rst.txt"),
    "missile": ("weapon.rst.txt", "weapon_related_commands.rst.txt"),
    "script": ("scripting_language_grammar.rst.txt", "script_commands.rst.txt"),
    "processor": ("wsf_script_processor.rst.txt", "script_commands.rst.txt"),
    "warlock": ("warlock_user_configurations.rst.txt",),
}

_OFFICIAL_ALIASES = {
    "platform": ("platform", "平台", "飞机", "战斗机", "无人机"),
    "route": ("route", "航路", "航线", "航点", "位置", "坐标"),
    "mover": ("mover", "机动", "飞行", "速度"),
    "sensor": ("sensor", "传感器", "雷达", "探测"),
    "radar": ("radar", "雷达"),
    "weapon": ("weapon", "武器", "导弹", "炸弹"),
    "missile": ("missile", "导弹"),
    "script": ("script", "脚本", "语法", "函数", "变量"),
    "processor": ("processor", "处理器"),
    "warlock": ("warlock", "可视化", "图标"),
}


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
        text = path.read_text(encoding="utf-8", errors="replace")
        fragment = f"{doc}:\n{_select_relevant_sections(text, query, _CHAR_LIMIT)}"
        fragments.append(fragment[:_CHAR_LIMIT])
    official_root = _resolve_official_docs_root(references_dir)
    if official_root:
        fragments.extend(_retrieve_official_docs(query, official_root))
    return "\n\n".join(fragments)


def _select_relevant_sections(text: str, query: str, limit: int) -> str:
    """Keep relevant complete sections instead of blindly taking the first N lines."""
    lines = text.splitlines()
    sections = []
    current = []
    title = ""
    for line in lines:
        match = _HEADING_RE.match(line)
        if match and current:
            sections.append((title, current))
            current = []
        if match:
            title = match.group(2)
        current.append(line)
    if current:
        sections.append((title, current))
    if not sections:
        return text[:limit]
    tokens = [token for token in re.split(r"[^a-z0-9_\u4e00-\u9fff]+", query) if len(token) > 1]
    ranked = []
    for index, (title, section) in enumerate(sections):
        haystack = "\n".join(section).lower()
        score = sum(haystack.count(token) for token in tokens)
        if index == 0:
            score += 1
        ranked.append((score, -index, section))
    selected = []
    used = 0
    for _, _, section in sorted(ranked, reverse=True):
        block = "\n".join(section)
        if selected and used + len(block) + 2 > limit:
            continue
        selected.append(block)
        used += len(block) + 2
        if used >= limit:
            break
    return "\n\n".join(selected)[:limit]


def _resolve_official_docs_root(references_dir: Path) -> Path | None:
    configured = os.environ.get("AFSIM_DOC_ROOT", "").strip()
    refs = Path(references_dir).resolve()
    if not configured and refs.name == "references":
        try:
            from core.config import load_config
            configured = str(load_config().afsim_doc_root or "").strip()
        except Exception:
            configured = ""
    candidates = []
    if configured:
        candidates.append(Path(configured).expanduser())
    if refs.name != "references" and not configured:
        return None
    candidates.extend([
        refs.parent.parent / "afsimDoc",
        refs.parent / "afsimDoc",
    ])
    for candidate in candidates:
        source_root = candidate / "html" / "_sources" / "docs"
        if source_root.is_dir():
            return source_root
    return None


def _retrieve_official_docs(query: str, source_root: Path) -> list[str]:
    query = query.lower()
    tokens = [token for token in re.split(r"[^a-z0-9_\u4e00-\u9fff]+", query) if len(token) > 1]
    selected_names = []
    for key, aliases in _OFFICIAL_ALIASES.items():
        if any(alias in query for alias in aliases):
            selected_names.extend(_OFFICIAL_DOCS.get(key, ()))
    for token in tokens:
        for key, names in _OFFICIAL_DOCS.items():
            if token == key or key in token or token in key:
                selected_names.extend(names)
    if not selected_names:
        selected_names.extend(("scripting_language_grammar.rst.txt", "platform.rst.txt"))
    result = []
    seen = set()
    for name in selected_names:
        if name in seen:
            continue
        seen.add(name)
        path = source_root / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        result.append(f"official:{name}:\n{_select_relevant_sections(text, query, _OFFICIAL_CHAR_LIMIT)}")
    return result


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


def modify(llm, script, instruction, config):
    refs_dir = Path(__file__).resolve().parent.parent / "references"
    knowledge_context = retrieve_knowledge(instruction, refs_dir)
    min_end_time_sec = getattr(config, "default_end_time_sec", 7200) if config is not None else 7200
    default_route_speed = getattr(config, "default_route_speed", "450 kts") if config is not None else "450 kts"
    return normalize_script(
        llm.modify_script(script, instruction, knowledge_context),
        min_end_time_sec=min_end_time_sec,
        default_route_speed=default_route_speed,
    )
