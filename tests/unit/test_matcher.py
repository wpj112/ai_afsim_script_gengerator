from core.matcher import match_output

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
