import os
import re
import tempfile
from pathlib import Path

from core.matcher import MatchResult

_BLOCK_OPENERS = (
    "platform_type", "platform", "sensor", "weapon", "mover",
    "processor", "route", "antenna_pattern", "radar_signature", "optical_signature",
)

_BASE_TYPES = {"platform_type": "WSF_PLATFORM", "radar_signature": "WSF_RADAR_SIGNATURE"}

_UNITS = {"speed": "kts", "altitude": "ft msl"}

_POSITION_RE = re.compile(r"\bposition\s+(\d+)\s+(\d+)\b")

_BLOCK_KIND_RE = re.compile(r"\b(mover|sensor|weapon|processor)\b", re.IGNORECASE)

_BASE_TOKEN_RE = re.compile(r"\b(platform_type|radar_signature)\b")

_PARAM_RE = re.compile(r"\b(speed|altitude|[a-z_]+time)\b", re.IGNORECASE)


def validate_blocks(text):
    stack = []
    for line in text.splitlines():
        tokens = line.split()
        if not tokens:
            continue
        token = tokens[0]
        if token in _BLOCK_OPENERS:
            stack.append(token)
        elif token.startswith("end_"):
            name = token[4:]
            if name in _BLOCK_OPENERS and stack and stack[-1] == name:
                stack.pop()
    return stack


def patch_append_base_type(text, target_line, base_type):
    target = target_line.strip()
    lines = text.split("\n")
    for line in lines:
        if line.strip() == target + " " + base_type:
            return text
    for i, line in enumerate(lines):
        if line.strip() == target:
            lines[i] = line.rstrip() + " " + base_type
            return "\n".join(lines)
    return text


def patch_close_block(text, block_kind):
    end = "end_" + block_kind
    for line in reversed(text.splitlines()):
        if line.strip():
            if line.strip() == end:
                return text
            break
    if not text.endswith("\n"):
        text += "\n"
    return text + end + "\n"


def patch_position_format(text):
    def repl(m):
        return "position {}:00:00n {}:00:00e".format(m.group(1), m.group(2))
    return _POSITION_RE.sub(repl, text)


def patch_add_unit(text, param):
    unit = _UNITS.get(param)
    if unit is None and "time" in param:
        unit = "sec"
    if unit is None:
        return text
    lines = text.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(param + " ") and unit not in line:
            lines[i] = line.rstrip() + " " + unit
            return "\n".join(lines)
    return text


def apply_fix(script_path: Path, match: MatchResult) -> bool:
    p = Path(script_path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return False
    desc = match.fix.get("description", "")
    matched = match.matched_text
    if "基类型" in desc:
        token_match = _BASE_TOKEN_RE.search(matched)
        if not token_match:
            return False
        token = token_match.group(1)
        base_type = _BASE_TYPES.get(token)
        if not base_type:
            return False
        target_line = _find_target_line(text, token, base_type)
        if target_line is None:
            return False
        new_text = patch_append_base_type(text, target_line, base_type)
    elif "end_" in desc or "闭合" in desc:
        kind_match = _BLOCK_KIND_RE.search(matched)
        if not kind_match:
            return False
        new_text = patch_close_block(text, kind_match.group(1).lower())
    elif "坐标" in desc:
        new_text = patch_position_format(text)
    elif "单位" in desc:
        param = _parse_param(desc, matched)
        if param is None:
            return False
        new_text = patch_add_unit(text, param)
    else:
        return False
    if new_text == text:
        return False
    _print_diff(text, new_text)
    old_unclosed = set(validate_blocks(text))
    new_unclosed = set(validate_blocks(new_text))
    if new_unclosed - old_unclosed:
        return False
    try:
        _atomic_write(p, new_text)
    except OSError:
        return False
    return True


def _find_target_line(text, token, base_type):
    for line in text.splitlines():
        if line.split() and line.split()[0] == token and base_type not in line:
            return line
    return None


def _parse_param(desc, matched):
    for src in (desc, matched):
        m = _PARAM_RE.search(src)
        if m:
            return m.group(1).lower()
    return None


def _print_diff(old_text, new_text):
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    n = max(len(old_lines), len(new_lines))
    for i in range(n):
        old_line = old_lines[i] if i < len(old_lines) else ""
        new_line = new_lines[i] if i < len(new_lines) else ""
        if old_line != new_line:
            print(f"- {old_line}")
            print(f"+ {new_line}")


def _atomic_write(path, content):
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".fixer-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, str(path))
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
