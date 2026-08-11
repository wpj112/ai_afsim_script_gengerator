import argparse
import json
import re
from datetime import datetime
from pathlib import Path

FIX_TYPE_MAP = {
    "E001": "template", "E002": "template", "E003": "template",
    "E004": "template", "E005": "template", "E006": "template",
    "E007": "template", "E008": "template", "E012": "template",
}
DEFAULT_FIX_TYPE = "llm_guided"


def _parse_entries(text: str) -> list[dict]:
    entries = []
    for m in re.finditer(r"### \[(E\d+)\]\s+(.+?)(?=\n### \[|\Z)", text, re.S):
        rid, body = m.group(1), m.group(2)
        header = body.splitlines()[0].strip()
        keywords = [k.strip() for k in re.findall(r"`([^`]+)`", header)]
        if not keywords:
            keywords = [header.replace("`", "")]
        root = re.search(r"\*\*根因\*\*：(.+)", body)
        demo = re.search(r"Demo:\s*(.+)", body)
        entries.append({
            "id": rid,
            "keywords": keywords,
            "patterns": [re.sub(r"\s+\S+$", r"\\s+(\\S+)", keywords[0])],
            "root_cause": root.group(1).strip() if root else "",
            "fix": {"type": FIX_TYPE_MAP.get(rid, DEFAULT_FIX_TYPE),
                    "description": root.group(1).strip() if root else ""},
            "demo": demo.group(1).strip().replace("`", "").strip() if demo else "",
            "lessons": [],
        })
    return entries


def sync_rules(md_path: Path, lesson_index_path: Path) -> dict:
    text = md_path.read_text(encoding="utf-8")
    rules = _parse_entries(text)
    return {"rules": rules, "generated_at": datetime.now().isoformat(),
            "source": str(md_path)}


def main():
    parser = argparse.ArgumentParser(description="同步 error_rules.json")
    parser.add_argument("--write", action="store_true", help="写 memory/error_rules.json")
    parser.add_argument("--check", action="store_true", help="只打印条目数，不写文件")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    md_path = root / "memory" / "errors-ref.md"
    lesson_index_path = root / "memory" / "cold" / "lesson-index.md"
    result = sync_rules(md_path, lesson_index_path)
    count = len(result["rules"])

    if args.write and not args.check:
        out_path = root / "memory" / "error_rules.json"
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"[OK] {count} rules -> {out_path}")
    else:
        print(f"{count} rules from {md_path}")


if __name__ == "__main__":
    main()
