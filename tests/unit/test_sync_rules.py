from pathlib import Path

from scripts.sync_error_rules import sync_rules

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "errors_ref_sample.md"


def test_sync_rules_parses_entries(tmp_path):
    md = tmp_path / "errors-ref.md"
    md.write_text('''### [E001] `Unknown command: platform_type`

**根因**：缺少基类型 WSF_PLATFORM。

```text
platform_type MY_PLATFORM WSF_PLATFORM
```

Demo: `../Afsim_demoslists/engage项目汇总.md` line 330
''')
    rules = sync_rules(md, tmp_path / "lesson-index.md")["rules"]
    assert rules[0]["id"] == "E001"
    assert rules[0]["keywords"] == ["Unknown command: platform_type"]
    assert rules[0]["patterns"] == ["Unknown command:\\s+(\\S+)"]
    assert rules[0]["fix"]["type"] in ("template", "llm_guided")
    assert rules[0]["root_cause"]
    assert rules[0]["demo"].startswith("..")


def test_sync_rules_parses_v1_fixture():
    result = sync_rules(FIXTURE, FIXTURE.parent / "lesson-index.md")
    rules = result["rules"]
    assert len(rules) >= 2
    assert [r["id"] for r in rules[:2]] == ["E001", "E002"]
    assert all(r["fix"]["type"] in ("template", "llm_guided") for r in rules)
    assert all(r["keywords"] and r["root_cause"] and r["demo"] for r in rules)
    assert all(r["patterns"] for r in rules)
