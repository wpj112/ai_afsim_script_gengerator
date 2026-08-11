import json
from pathlib import Path

from core.matcher import match_output

REAL_RULES = json.loads(
    (Path(__file__).resolve().parent.parent.parent / "memory" / "error_rules.json").read_text(encoding="utf-8")
)

RULES = {"rules": [{"id": "E001", "keywords": ["Unknown command: platform_type"],
                    "patterns": ["Unknown command:\\s+(\\S+)"], "fix": {"type": "template"},
                    "lessons": ["L004", "L012"]}]}

def test_keyword_match():
    out = "ERROR: Unknown command: platform_type"
    res = match_output("", out, RULES)
    assert res[0].rule_id == "E001" and res[0].confidence == "exact"

def test_no_match():
    assert match_output("ok", "all good", RULES) == []

def test_line_number():
    out = "line1\nERROR: Unknown command: platform_type"
    assert match_output("", out, RULES)[0].line_no == 2

def test_pattern_match():
    rules = {"rules": [{"id": "E099", "keywords": [], "patterns": ["ERROR:\\s+(\\w+)"],
                        "fix": {"type": "template"}, "lessons": []}]}
    res = match_output("", "ERROR: something", rules)
    assert res[0].rule_id == "E099" and res[0].confidence == "pattern"

def test_single_result_per_rule():
    rules = {"rules": [{"id": "E001",
                        "keywords": ["Unknown command: platform_type", "Unknown command: radar_signature"],
                        "patterns": [], "fix": {"type": "template"}, "lessons": []}]}
    out = "Unknown command: platform_type\nUnknown command: radar_signature"
    assert len(match_output("", out, rules)) == 1

def test_stdout_stderr_line_numbers():
    rules = {"rules": [{"id": "E001", "keywords": ["Unknown command: platform_type"],
                        "patterns": [], "fix": {"type": "template"}, "lessons": []}]}
    out = "stdout line 1\nstdout line 2\nERROR: Unknown command: platform_type"
    assert match_output(out, "stderr only", rules)[0].line_no == 3

def test_unknown_error_with_platform_instances_not_matched_as_e019():
    res = match_output("echo: configuring platform instances", "unrelated failure", REAL_RULES)
    assert res == []

def test_unknown_weapon_still_matches_real_rules():
    res = match_output("", "ERROR: Unknown weapon: foo_missile", REAL_RULES)
    assert res
    assert res[0].rule_id == "E017"
    assert res[0].confidence == "pattern"
