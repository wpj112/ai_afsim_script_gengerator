from pathlib import Path

from core.generator import generate, retrieve_knowledge
from core.script_normalizer import normalize_script

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
    assert len(result) <= 5000


def test_retrieve_knowledge_selects_relevant_section_beyond_old_line_limit(tmp_path):
    refs = _make_refs(tmp_path, names=["commands_reference.md"])
    content = "# Commands\n\n" + "filler\n" * 130 + "\n## Radar Route\n\nRADAR_UNIQUE_SYNTAX\n"
    (refs / "commands_reference.md").write_text(content)
    result = retrieve_knowledge("route", refs)
    assert "RADAR_UNIQUE_SYNTAX" in result


def test_retrieve_knowledge_uses_explicit_official_doc_root(tmp_path, monkeypatch):
    refs_dir = tmp_path / "references"
    refs_dir.mkdir()
    refs = _make_refs(refs_dir)
    source_root = tmp_path / "official" / "html" / "_sources" / "docs"
    source_root.mkdir(parents=True)
    (source_root / "wsf_radar_sensor.rst.txt").write_text(
        "Radar official syntax\n\nWSF_RADAR_OFFICIAL_UNIQUE\n"
    )
    monkeypatch.setenv("AFSIM_DOC_ROOT", str(tmp_path / "official"))
    result = retrieve_knowledge("radar", refs)
    assert "WSF_RADAR_OFFICIAL_UNIQUE" in result


class _FakeLLM:
    def __init__(self):
        self.knowledge = None

    def generate_script(self, prompt, knowledge_context):
        self.knowledge = knowledge_context
        return "end_time 7200 sec"


def test_generate_injects_retrieved_knowledge(tmp_path, monkeypatch):
    refs = _make_refs(tmp_path)
    monkeypatch.setattr(
        "core.generator.retrieve_knowledge",
        lambda query, refs_dir: "sensor_types_reference.md content\n",
    )
    fake = _FakeLLM()
    generate(fake, "radar 场景", None)
    assert fake.knowledge and "sensor_types_reference.md" in fake.knowledge


def test_generate_normalizes_llm_output(monkeypatch):
    monkeypatch.setattr(
        "core.generator.retrieve_knowledge",
        lambda query, refs_dir: "rules",
    )

    class BadLLM:
        def generate_script(self, prompt, knowledge_context):
            return "```afsim\ntime\n   duration 600 sec\nend_time\n```\n"

    assert generate(BadLLM(), "生成场景", None) == "end_time 7200 sec\n"


def test_normalize_script_rewrites_time_block():
    text = "time\n   duration 600 sec\nend_time\n"
    assert normalize_script(text) == "end_time 7200 sec\n"


def test_normalize_script_rewrites_inline_time_command():
    assert normalize_script("time 300.0 sec;\n") == "end_time 7200 sec\n"


def test_normalize_script_rewrites_braced_time_block():
    text = "time\n{\n   stop 600 sec;\n}\nend_time\n"
    assert normalize_script(text) == "end_time 7200 sec\n"


def test_normalize_script_keeps_end_time_above_minimum():
    assert normalize_script("end_time 3 hr\n") == "end_time 3 hr\n"


def test_normalize_script_adds_missing_end_time():
    assert normalize_script("script_interface\n   debug\nend_script_interface\n").endswith("end_time 7200 sec\n")


def test_normalize_script_accepts_custom_minimum():
    assert normalize_script("end_time 10 sec\n", min_end_time_sec=30) == "end_time 30 sec\n"


def test_normalize_script_rewrites_enable_debug():
    text = "script_interface\n   enable_debug\nend_script_interface\n"
    assert "   debug\n" in normalize_script(text)


def test_normalize_script_rewrites_common_type_aliases():
    text = "sensor AIR_RADAR RADAR\nweapon AIM_9X AA_MISSILE\nweapon R77 missile\n"
    normalized = normalize_script(text)
    assert "sensor AIR_RADAR WSF_RADAR_SENSOR\n" in normalized
    assert "weapon AIM_9X WSF_EXPLICIT_WEAPON\n" in normalized
    assert "weapon R77 WSF_EXPLICIT_WEAPON\n" in normalized


def test_normalize_script_strips_afsim_wrapper_braces_only():
    text = (
        "platform BLUE\n{\n   side blue\n}\nend_platform\n"
        "script foo\n   if (x) {\n      x = 1;\n   }\nend_script\n"
    )
    normalized = normalize_script(text)
    assert "{\n   side blue" not in normalized
    assert "if (x) {" in normalized


def test_normalize_script_removes_block_header_brace_and_command_semicolon():
    text = (
        "sensor AIR_RADAR RADAR {\n"
        "   max_range 120.0 nm;\n"
        "}\n"
        "end_sensor\n"
        "on_update\n"
        "   count = count + 1;\n"
        "end_on_update\n"
    )
    normalized = normalize_script(text)
    assert "sensor AIR_RADAR WSF_RADAR_SENSOR\n" in normalized
    assert "one_m2_detect_range 120.0 nm\n" in normalized
    assert "count = count + 1;\n" in normalized


def test_normalize_script_wraps_direct_antenna_params():
    text = (
        "antenna_pattern radar_xband\n"
        "   gain 30 dBi\n"
        "   beamwidth 2 deg\n"
        "   frequency 10 GHz\n"
        "end_antenna_pattern\n"
    )
    normalized = normalize_script(text)
    assert "constant_pattern\n" in normalized
    assert "peak_gain 30 db\n" in normalized
    assert "azimuth_beamwidth 2 deg\n" in normalized
    assert "elevation_beamwidth 2 deg\n" in normalized
    assert "frequency 10 GHz" not in normalized


def test_normalize_script_rewrites_simplified_radar_sensor():
    text = (
        "sensor AIR_RADAR RADAR\n"
        "   antenna_pattern AIR_RADAR_PATTERN\n"
        "   max_range 120 nm\n"
        "end_sensor\n"
    )
    normalized = normalize_script(text)
    assert "sensor AIR_RADAR WSF_RADAR_SENSOR\n" in normalized
    assert "mode search\n" in normalized
    assert "transmitter\n" in normalized
    assert "receiver\n" in normalized
    assert "one_m2_detect_range 120 nm\n" in normalized


def test_normalize_script_drops_unverified_explicit_weapon_params():
    text = (
        "weapon AIM_9X AA_MISSILE\n"
        "   quantity 4\n"
        "   max_range 20 nm\n"
        "   seeker_type IR\n"
        "end_weapon\n"
    )
    normalized = normalize_script(text)
    assert "weapon AIM_9X WSF_EXPLICIT_WEAPON\n" in normalized
    assert "quantity 4\n" in normalized
    assert "max_range" not in normalized
    assert "seeker_type" not in normalized


def test_normalize_script_prunes_simple_platform_type_references():
    text = (
        "platform_type Fighter WSF_PLATFORM\n"
        "   mover WSF_AIR_MOVER\n"
        "   end_mover\n"
        "   sensor AIR_RADAR\n"
        "   weapon AIM_9X\n"
        "   processor engagement_proc\n"
        "end_platform_type\n"
    )
    normalized = normalize_script(text)
    assert "mover WSF_AIR_MOVER\n" in normalized
    assert "sensor AIR_RADAR" not in normalized
    assert "weapon AIM_9X" not in normalized
    assert "processor engagement_proc" not in normalized


def test_normalize_script_prunes_complex_platform_type_member_blocks():
    text = (
        "platform_type Fighter WSF_PLATFORM\n"
        "   mover WSF_AIR_MOVER\n"
        "   end_mover\n"
        "   processor engagement_proc WSF_SCRIPT_PROCESSOR\n"
        "      update_interval 1 sec\n"
        "   end_processor\n"
        "end_platform_type\n"
    )
    normalized = normalize_script(text)
    assert "mover WSF_AIR_MOVER\n" in normalized
    assert "WSF_SCRIPT_PROCESSOR" not in normalized
    assert "update_interval" not in normalized


def test_normalize_script_closes_platform_type_mover():
    text = "platform_type Fighter WSF_PLATFORM\n   mover WSF_AIR_MOVER\nend_platform_type\n"
    normalized = normalize_script(text)
    assert "   mover WSF_AIR_MOVER\nend_mover\nend_platform_type\n" in normalized


def test_normalize_script_moves_platform_type_to_header():
    text = "platform Blue1\n   type Fighter\n   side blue\nend_platform\n"
    normalized = normalize_script(text)
    assert "platform Blue1 Fighter\n" in normalized
    assert "type Fighter" not in normalized


def test_normalize_script_prunes_platform_instance_reference_blocks():
    text = (
        "platform Friendly1 Fighter\n"
        "   side blue\n"
        "   sensor RADAR_SENSOR\n"
        "   end_sensor\n"
        "   weapon AA_MISSILE\n"
        "   end_weapon\n"
        "end_platform\n"
    )
    normalized = normalize_script(text)
    assert "side blue\n" in normalized
    assert "sensor RADAR_SENSOR" not in normalized
    assert "weapon AA_MISSILE" not in normalized


def test_normalize_script_splits_shared_radar_and_missile_visual_types():
    text = (
        "platform_type RED_STATIC_PLATFORM WSF_PLATFORM\n"
        "   mover WSF_AIR_MOVER\n"
        "   end_mover\n"
        "end_platform_type\n"
        "platform red_radar1 RED_STATIC_PLATFORM\n"
        "   side red\n"
        "end_platform\n"
        "platform red_sam1 RED_STATIC_PLATFORM\n"
        "   side red\n"
        "end_platform\n"
    )
    normalized = normalize_script(text)
    assert "platform_type RED_STATIC_RADAR_PLATFORM WSF_PLATFORM\n" in normalized
    assert "   icon radar\n" in normalized
    assert "   category radar\n" in normalized
    assert "platform_type RED_STATIC_MISSILE_PLATFORM WSF_PLATFORM\n" in normalized
    assert "   icon missile\n" in normalized
    assert "   category missile\n" in normalized
    assert "platform red_radar1 RED_STATIC_RADAR_PLATFORM\n" in normalized
    assert "platform red_sam1 RED_STATIC_MISSILE_PLATFORM\n" in normalized


def test_normalize_script_adds_missing_single_role_visual_marker_once():
    text = (
        "platform_type BLUE_FIGHTER_PLATFORM WSF_PLATFORM\n"
        "   icon fighter\n"
        "   mover WSF_AIR_MOVER\n"
        "   end_mover\n"
        "end_platform_type\n"
        "platform blue_fighter1 BLUE_FIGHTER_PLATFORM\n"
        "   side blue\n"
        "end_platform\n"
    )
    normalized = normalize_script(text)
    assert normalized.count("icon fighter") == 1
    assert "   category aircraft\n" in normalized


def test_normalize_script_preserves_position_speed():
    text = "   position 38:44:52.3N 90:21:36.4W altitude 15000 ft speed 450 kts\n"
    normalized = normalize_script(text)
    assert "position 38:44:52.3N 90:21:36.4W altitude 15000 ft speed 450 kts\n" in normalized


def test_normalize_script_wraps_route_positions_in_navigation():
    text = "route\n   position 38:44:52.3N 90:21:36.4W altitude 15000 ft\nend_route\n"
    normalized = normalize_script(text)
    assert "   navigation\n" in normalized
    assert "      position 38:44:52.3N 90:21:36.4W altitude 15000 ft\n" in normalized
    assert "         speed 450 kts\n" in normalized
    assert "   end_navigation\n" in normalized


def test_normalize_script_uses_custom_route_speed():
    text = "route\n   position 38:44:52.3N 90:21:36.4W altitude 15000 ft\nend_route\n"
    normalized = normalize_script(text, default_route_speed="300 kts")
    assert "speed 300 kts\n" in normalized


def test_normalize_script_converts_waypoint_to_position():
    text = "      waypoint 38:45:00.0N 90:22:00.0W altitude 15000 ft speed 450 kts\n"
    normalized = normalize_script(text)
    assert "position 38:45:00.0N 90:22:00.0W altitude 15000 ft speed 450 kts\n" in normalized
    assert "waypoint" not in normalized


def test_normalize_script_preserves_navigation_and_adds_missing_speed():
    text = (
        "route\n"
        "   navigation\n"
        "      position 38:44:52.3N 90:21:36.4W altitude 15000 ft\n"
        "      position 38:45:52.3N 90:22:36.4W altitude 15000 ft\n"
        "         speed 420 kts\n"
        "   end_navigation\n"
        "end_route\n"
    )
    normalized = normalize_script(text)
    assert "      position 38:44:52.3N 90:21:36.4W altitude 15000 ft\n         speed 450 kts\n" in normalized
    assert "      position 38:45:52.3N 90:22:36.4W altitude 15000 ft\n         speed 420 kts\n" in normalized


def test_normalize_script_offsets_adjacent_duplicate_positions():
    text = (
        "route\n"
        "   navigation\n"
        "      position 30:00:00n 100:00:00w altitude 0 ft\n"
        "         speed 450 kts\n"
        "      position 30:00:00n 100:00:00w altitude 0 ft\n"
        "         speed 450 kts\n"
        "   end_navigation\n"
        "end_route\n"
    )
    normalized = normalize_script(text)
    assert "position 30:00:00n 100:00:00w altitude 0 ft\n" in normalized
    assert "position 30:00:00n 100:00:01w altitude 0 ft\n" in normalized


def test_normalize_script_only_offsets_adjacent_duplicate_positions():
    text = (
        "route\n"
        "   navigation\n"
        "      position 30:00:00n 100:00:00w altitude 0 ft\n"
        "         speed 450 kts\n"
        "      position 30:01:00n 100:01:00w altitude 0 ft\n"
        "         speed 450 kts\n"
        "      position 30:00:00n 100:00:00w altitude 0 ft\n"
        "         speed 450 kts\n"
        "   end_navigation\n"
        "end_route\n"
    )
    normalized = normalize_script(text)
    assert "position 30:00:00n 100:00:01w" not in normalized


def test_generate_uses_real_references_dir():
    from pathlib import Path

    refs_dir = Path(__file__).resolve().parent.parent.parent / "references"
    assert refs_dir.is_dir()
    result = retrieve_knowledge("radar", refs_dir)
    assert result
