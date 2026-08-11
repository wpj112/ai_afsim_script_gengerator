from pathlib import Path

from core.generator import generate, retrieve_knowledge

FILES = [
    "sensor_types_reference.md",
    "mover_reference.md",
    "commands_reference.md",
    "script_api_reference.md",
    "file_structure.md",
    "examples.md",
]


def _make_refs(tmp_path, names=None):
    for name in names or FILES:
        (tmp_path / name).write_text(f"{name} content\n")
    return tmp_path


def test_retrieve_knowledge_radar_hits_sensor_doc(tmp_path):
    refs = _make_refs(tmp_path)
    result = retrieve_knowledge("红方 radar 探测", refs)
    assert "sensor_types_reference.md" in result


def test_retrieve_knowledge_aircraft_hits_mover_doc(tmp_path):
    refs = _make_refs(tmp_path)
    result = retrieve_knowledge("aircraft 机动性能", refs)
    assert "mover_reference.md" in result


def test_retrieve_knowledge_default_returns_file_structure(tmp_path):
    refs = _make_refs(tmp_path)
    result = retrieve_knowledge("完全无关的查询词", refs)
    assert "file_structure.md" in result


def test_retrieve_knowledge_empty_dir_returns_empty(tmp_path):
    assert retrieve_knowledge("radar", tmp_path) == ""


def test_retrieve_knowledge_skips_missing_docs(tmp_path):
    refs = _make_refs(tmp_path, names=["sensor_types_reference.md"])
    result = retrieve_knowledge("aircraft 查询", refs)
    assert "sensor_types_reference.md" not in result
    assert "file_structure.md" not in result


def test_retrieve_knowledge_truncates_long_docs(tmp_path):
    refs = _make_refs(tmp_path, names=["sensor_types_reference.md"])
    (refs / "sensor_types_reference.md").write_text("x" * 5000)
    result = retrieve_knowledge("radar", refs)
    assert len(result) <= 2000


class _FakeLLM:
    def __init__(self):
        self.knowledge = None

    def generate_script(self, prompt, knowledge_context):
        self.knowledge = knowledge_context
        return "end_time 10 sec"


def test_generate_injects_retrieved_knowledge(tmp_path, monkeypatch):
    refs = _make_refs(tmp_path)
    monkeypatch.setattr(
        "core.generator.retrieve_knowledge",
        lambda query, refs_dir: "sensor_types_reference.md content\n",
    )
    fake = _FakeLLM()
    generate(fake, "radar 场景", None)
    assert fake.knowledge and "sensor_types_reference.md" in fake.knowledge


def test_generate_uses_real_references_dir():
    from pathlib import Path

    refs_dir = Path(__file__).resolve().parent.parent.parent / "references"
    assert refs_dir.is_dir()
    result = retrieve_knowledge("radar", refs_dir)
    assert result
