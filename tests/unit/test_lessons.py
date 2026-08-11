from core.lessons import record, pend, promote, stats
from core.matcher import MatchResult

def test_pend_creates_file(tmp_path):
    p = pend("Unknown error: xyz", tmp_path / "pending", note="test")
    assert p.exists() and "test" in p.read_text()

def test_promote_appends_to_errors_ref(tmp_path):
    pending_file = pend("Unknown command: foo bar", tmp_path / "pending")
    ref = tmp_path / "errors-ref.md"
    ref.write_text("# AFSIM 报错索引\n\n---\n")
    assert promote(pending_file, ref, confirm=True) is True
    assert "Unknown command: foo bar" in ref.read_text()

def test_record_and_stats(tmp_path):
    hot = tmp_path / "hot"
    hot.mkdir()
    m = MatchResult("E001", "exact", "x", 1, {}, ["L004"])
    record([m], "2026-08-11", hot)
    assert stats({"rules": [{"id": "E001"}]}, hot) == {"E001": 1}
