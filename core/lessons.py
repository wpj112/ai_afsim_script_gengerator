import re
from datetime import datetime
from pathlib import Path


def record(matches, session_date, log_dir):
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"## [{session_date}] 教训命中记录 {ts}"]
    for m in matches:
        lessons = ", ".join(m.lessons)
        text = m.matched_text.replace("\n", " ").strip()
        lines.append(f"- {m.rule_id} ({m.confidence}) {text} → lessons: {lessons}")
    with open(log_dir / f"{session_date}.md", "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n\n")


def pend(stderr_text, pending_dir, note=""):
    pending_dir = Path(pending_dir)
    pending_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = pending_dir / f"{ts}_unknown.md"
    path.write_text(
        f"note: {note}\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"原始 stderr:\n{stderr_text}\n",
        encoding="utf-8",
    )
    return path


def promote(pending_path, errors_ref_path, confirm=True):
    if not confirm:
        return False
    pending_path = Path(pending_path)
    if not pending_path.exists():
        return False
    errors_ref_path = Path(errors_ref_path)
    stderr_text = pending_path.read_text(encoding="utf-8")
    parts = stderr_text.split("原始 stderr:", 1)
    stderr_part = parts[1] if len(parts) > 1 else stderr_text
    title = ""
    for line in stderr_part.splitlines():
        if line.strip():
            title = line.strip()
            break
    if not title:
        title = "未知错误"
    next_id = _next_rule_id(errors_ref_path)
    entry = (
        f"### [{next_id}] {title}\n\n"
        f"**根因**：待确认\n\n"
        f"**修正方案**：待验证\n\n"
        f"Demo: 无\n"
    )
    with open(errors_ref_path, "a", encoding="utf-8") as f:
        if errors_ref_path.exists() and errors_ref_path.stat().st_size > 0:
            f.write("\n\n---\n\n" + entry)
        else:
            f.write(entry)
    return True


def stats(rules, hot_dir):
    hot_dir = Path(hot_dir)
    counts = {}
    for rule in rules.get("rules", []):
        rule_id = rule["id"]
        pattern = re.compile(rf"\b{rule_id}\b")
        count = 0
        for f in hot_dir.glob("*.md"):
            count += len(pattern.findall(f.read_text(encoding="utf-8")))
        counts[rule_id] = count
    return dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))


def _next_rule_id(errors_ref_path):
    errors_ref_path = Path(errors_ref_path)
    if errors_ref_path.exists():
        nums = [int(n) for n in re.findall(r"\[E(\d+)\]", errors_ref_path.read_text(encoding="utf-8"))]
        if nums:
            return f"E{max(nums) + 1:03d}"
    return f"E{datetime.now().strftime('%Y%m%d%H%M%S')}"
