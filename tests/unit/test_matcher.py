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
