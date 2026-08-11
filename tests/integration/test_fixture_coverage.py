import json
import shutil
from pathlib import Path

from core.fixer import apply_fix
from core.matcher import match_output

ROOT = Path(__file__).resolve().parent.parent.parent
RULES = json.loads((ROOT / "memory" / "error_rules.json").read_text(encoding="utf-8"))
SAMPLES = (ROOT / "tests" / "fixtures" / "mission_output_samples.txt").read_text(encoding="utf-8")
BROKEN = ROOT / "tests" / "fixtures" / "broken_scenarios"

EXPECTED_COVERED = {
    "E001", "E002", "E003", "E004", "E005",
    "E009", "E010", "E014", "E016", "E017", "E018", "E019",
}

SCENARIOS = {
    "missing_end_block.txt": ("E003", "ERROR: Mover not closed", "end_mover"),
    "missing_base_type.txt": ("E001", "ERROR: Unknown command: platform_type", "WSF_PLATFORM"),
    "bad_position_format.txt": ("E005", "ERROR: Invalid position format: 30 120", "30:00:00n"),
    "missing_unit.txt": ("E006", "ERROR: 速度单位缺失", "kts"),
}


def _hit_rule_ids(text):
    return {m.rule_id for m in match_output(text, "", RULES)}


def test_mission_samples_cover_at_least_ten_rules():
    hit = _hit_rule_ids(SAMPLES)
    assert len(hit) >= 10
    assert EXPECTED_COVERED <= hit


def test_broken_scenarios_have_header_documenting_error_type():
    for name in SCENARIOS:
        lines = (BROKEN / name).read_text(encoding="utf-8").splitlines()
        assert lines[0].startswith("#")
        assert SCENARIOS[name][0] in lines[0]


def test_broken_scenarios_template_fixable(tmp_path):
    for name, (rule_id, stderr, expected_token) in SCENARIOS.items():
        dst = tmp_path / name
        shutil.copy2(BROKEN / name, dst)
        matches = match_output("", stderr, RULES)
        assert any(m.rule_id == rule_id for m in matches), name
        match = next(m for m in matches if m.rule_id == rule_id)
        assert apply_fix(dst, match), name
        assert expected_token in dst.read_text(encoding="utf-8"), name
