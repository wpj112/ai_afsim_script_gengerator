import re

_FENCE_RE = re.compile(r"^\s*```(?:\w+)?\s*$")
_TIME_BLOCK_START_RE = re.compile(r"^\s*time\s*$", re.IGNORECASE)
DEFAULT_END_TIME_SEC = 7200
DEFAULT_ROUTE_SPEED = "450 kts"

_TIME_INLINE_RE = re.compile(
    r"^\s*time\s+([0-9]+(?:\.[0-9]+)?)\s*(sec|second|seconds|min|minute|minutes|hr|hour|hours)?\s*;?\s*$",
    re.IGNORECASE,
)
_TIME_VALUE_RE = re.compile(
    r"^\s*(?:duration|stop|end|end_time)\s+([0-9]+(?:\.[0-9]+)?)\s*(sec|second|seconds|min|minute|minutes|hr|hour|hours)?\s*;?\s*$",
    re.IGNORECASE,
)
_END_TIME_RE = re.compile(r"^\s*end_time\b", re.IGNORECASE)
_ENABLE_DEBUG_RE = re.compile(r"^(\s*)enable_debug\s*$", re.IGNORECASE)
_SENSOR_ALIAS_RE = re.compile(r"^(\s*sensor\s+\S+\s+)(radar)(\s*)$", re.IGNORECASE)
_WEAPON_ALIAS_RE = re.compile(r"^(\s*weapon\s+\S+\s+)(missile|aa_missile)(\s*)$", re.IGNORECASE)
_EXPLICIT_WEAPON_ALLOWED_RE = re.compile(
    r"^\s*(location|quantity|firing_interval|launched_platform_type|weapon_effects|category)\b",
    re.IGNORECASE,
)

_AFSIM_BLOCK_START_RE = re.compile(
    r"^\s*(script_interface|event_output|dis_interface|antenna_pattern|sensor|weapon|"
    r"weapon_effects|aero|processor|platform_type|platform|route|mover|script_variables|script)\b",
    re.IGNORECASE,
)
_AFSIM_BLOCK_END_RE = re.compile(r"^\s*end_[a-z_]+\b", re.IGNORECASE)
_CODE_SECTION_START_RE = re.compile(
    r"^\s*(script|script_variables|on_initialize|on_update|on_message|on_process_message|on_entry|on_exit)\b",
    re.IGNORECASE,
)
_CODE_SECTION_END_RE = re.compile(
    r"^\s*end_(script|script_variables|on_initialize|on_update|on_message|on_process_message|on_entry|on_exit)\b",
    re.IGNORECASE,
)
_CONTROL_CODE_RE = re.compile(r"^\s*(if|else|while|for|foreach|switch)\b", re.IGNORECASE)
_END_TIME_VALUE_RE = re.compile(
    r"^(\s*end_time\s+)([0-9]+(?:\.[0-9]+)?)(\s*)(sec|second|seconds|min|minute|minutes|hr|hour|hours)?(\s*)$",
    re.IGNORECASE,
)
_PLATFORM_TYPE_HEADER_RE = re.compile(r"^\s*platform_type\s+(\S+)\s+\S+\b", re.IGNORECASE)
_PLATFORM_HEADER_RE = re.compile(r"^(\s*platform\s+)(\S+)(\s+)(\S+)(\b.*)$", re.IGNORECASE)
_VISUAL_MARKERS = {
    "radar": ("radar", "radar"),
    "missile": ("missile", "missile"),
    "aircraft": ("fighter", "aircraft"),
}


def normalize_script(
    text: str,
    min_end_time_sec: int = DEFAULT_END_TIME_SEC,
    default_route_speed: str = DEFAULT_ROUTE_SPEED,
) -> str:
    """Clean common LLM formatting and AFSIM syntax mistakes before mission runs."""
    lines = _strip_markdown_fences((text or "").splitlines())
    lines = _normalize_afsim_punctuation(lines)
    lines = _normalize_type_aliases(lines)
    lines = _normalize_antenna_patterns(lines)
    lines = _normalize_radar_sensors(lines)
    lines = _normalize_explicit_weapons(lines)
    lines = _prune_platform_type_references(lines)
    lines = _close_platform_type_movers(lines)
    lines = _normalize_platform_instance_types(lines)
    lines = _prune_platform_instance_references(lines)
    lines = _apply_platform_visual_markers(lines)
    lines = _normalize_waypoints(lines)
    lines = _normalize_route_navigation(lines, default_route_speed)
    lines = _dedupe_adjacent_route_positions(lines)
    lines = _normalize_time_blocks(lines)
    lines = _enforce_min_end_time(lines, min_end_time_sec)
    lines = _normalize_debug(lines)
    lines = _strip_afsim_wrapper_braces(lines)
    normalized = "\n".join(lines).strip()
    return normalized + "\n" if normalized else ""


def _strip_markdown_fences(lines):
    return [line for line in lines if not _FENCE_RE.match(line)]


def _normalize_time_blocks(lines):
    result = []
    i = 0
    while i < len(lines):
        inline_match = _TIME_INLINE_RE.match(lines[i])
        if inline_match:
            result.append(f"end_time {inline_match.group(1)} {_canonical_time_unit(inline_match.group(2))}")
            i += 1
            continue

        if not _TIME_BLOCK_START_RE.match(lines[i]):
            result.append(lines[i])
            i += 1
            continue

        duration, unit = None, "sec"
        j = i + 1
        while j < len(lines):
            stripped = lines[j].strip()
            if not stripped or stripped in ("{", "}"):
                j += 1
                continue
            if stripped.lower() == "end_time":
                j += 1
                break
            match = _TIME_VALUE_RE.match(lines[j])
            if match:
                duration = match.group(1)
                unit = _canonical_time_unit(match.group(2))
            j += 1
        if duration is not None:
            result.append(f"end_time {duration} {unit}")
            i = j
        else:
            result.append(lines[i])
            i += 1
    return result


def _canonical_time_unit(unit):
    value = (unit or "sec").lower()
    if value.startswith("second"):
        return "sec"
    if value.startswith("minute"):
        return "min"
    if value.startswith("hour"):
        return "hr"
    return value


def _normalize_debug(lines):
    return [_ENABLE_DEBUG_RE.sub(r"\1debug", line) for line in lines]


def _enforce_min_end_time(lines, min_seconds):
    if not any(line.strip() for line in lines):
        return lines
    try:
        min_seconds = int(min_seconds)
    except (TypeError, ValueError):
        min_seconds = DEFAULT_END_TIME_SEC
    if min_seconds <= 0:
        return lines
    result = []
    has_end_time = False
    for line in lines:
        match = _END_TIME_VALUE_RE.match(line)
        if not match:
            result.append(line)
            continue
        has_end_time = True
        seconds = _to_seconds(float(match.group(2)), match.group(4))
        if seconds < min_seconds:
            result.append(f"{match.group(1)}{min_seconds} sec")
        else:
            result.append(line)
    if not has_end_time:
        result.append(f"end_time {min_seconds} sec")
    return result


def _to_seconds(value, unit):
    unit = (unit or "sec").lower()
    if unit.startswith("min"):
        return value * 60
    if unit.startswith("hr") or unit.startswith("hour"):
        return value * 3600
    return value


def _normalize_type_aliases(lines):
    normalized = []
    for line in lines:
        line = _SENSOR_ALIAS_RE.sub(r"\1WSF_RADAR_SENSOR\3", line)
        line = _WEAPON_ALIAS_RE.sub(r"\1WSF_EXPLICIT_WEAPON\3", line)
        normalized.append(line)
    return normalized


def _normalize_explicit_weapons(lines):
    result = []
    i = 0
    while i < len(lines):
        if not re.match(r"^\s*weapon\s+\S+\s+WSF_EXPLICIT_WEAPON\b", lines[i], re.IGNORECASE):
            result.append(lines[i])
            i += 1
            continue
        block = [lines[i]]
        j = i + 1
        found_end = False
        while j < len(lines):
            block.append(lines[j])
            if re.match(r"^\s*end_weapon\b", lines[j], re.IGNORECASE):
                found_end = True
                break
            j += 1
        if not found_end:
            result.append(lines[i])
            i += 1
            continue
        result.extend(_rewrite_explicit_weapon_block(block))
        i = j + 1
    return result


def _prune_platform_type_references(lines):
    result = []
    in_platform_type = False
    skip_block = ""
    for line in lines:
        stripped = line.strip()
        if skip_block:
            if stripped.lower().startswith(f"end_{skip_block}"):
                skip_block = ""
            continue
        if re.match(r"^\s*platform_type\b", line, re.IGNORECASE):
            in_platform_type = True
            result.append(line)
            continue
        if in_platform_type and re.match(r"^\s*end_platform_type\b", line, re.IGNORECASE):
            in_platform_type = False
            result.append(line)
            continue
        if in_platform_type and _is_simple_platform_reference(stripped):
            continue
        if in_platform_type and _is_complex_platform_member_start(stripped):
            skip_block = stripped.split()[0].lower()
            continue
        result.append(line)
    return result


def _is_simple_platform_reference(stripped):
    tokens = stripped.split()
    if len(tokens) != 2:
        return False
    return tokens[0].lower() in {"sensor", "weapon", "weapon_effects", "processor", "aero"}


def _is_complex_platform_member_start(stripped):
    tokens = stripped.split()
    if len(tokens) < 3:
        return False
    return tokens[0].lower() in {"sensor", "weapon", "weapon_effects", "processor", "aero"}


def _close_platform_type_movers(lines):
    result = []
    in_platform_type = False
    pending_mover = False
    for line in lines:
        if re.match(r"^\s*platform_type\b", line, re.IGNORECASE):
            in_platform_type = True
            pending_mover = False
            result.append(line)
            continue
        if in_platform_type and re.match(r"^\s*mover\b", line, re.IGNORECASE):
            pending_mover = True
            result.append(line)
            continue
        if in_platform_type and re.match(r"^\s*end_mover\b", line, re.IGNORECASE):
            pending_mover = False
            result.append(line)
            continue
        if in_platform_type and re.match(r"^\s*end_platform_type\b", line, re.IGNORECASE):
            if pending_mover:
                result.append(_end_line_for(line, "mover"))
                pending_mover = False
            in_platform_type = False
            result.append(line)
            continue
        result.append(line)
    return result


def _normalize_platform_instance_types(lines):
    result = []
    i = 0
    while i < len(lines):
        header_match = re.match(r"^(\s*platform\s+\S+)\s*$", lines[i], re.IGNORECASE)
        if not header_match:
            result.append(lines[i])
            i += 1
            continue
        block = [lines[i]]
        j = i + 1
        found_end = False
        platform_type = ""
        while j < len(lines):
            block.append(lines[j])
            type_match = re.match(r"^\s*type\s+(\S+)\s*$", lines[j], re.IGNORECASE)
            if type_match and not platform_type:
                platform_type = type_match.group(1)
            if re.match(r"^\s*end_platform\b", lines[j], re.IGNORECASE):
                found_end = True
                break
            j += 1
        if not found_end or not platform_type:
            result.append(lines[i])
            i += 1
            continue
        result.append(f"{header_match.group(1)} {platform_type}")
        result.extend(line for line in block[1:] if not re.match(r"^\s*type\s+\S+\s*$", line, re.IGNORECASE))
        i = j + 1
    return result


def _prune_platform_instance_references(lines):
    result = []
    in_platform = False
    skip_block = ""
    for line in lines:
        stripped = line.strip()
        if skip_block:
            if stripped.lower().startswith(f"end_{skip_block}"):
                skip_block = ""
            continue
        if re.match(r"^\s*platform\s+\S+\s+\S+\b", line, re.IGNORECASE):
            in_platform = True
            result.append(line)
            continue
        if in_platform and re.match(r"^\s*end_platform\b", line, re.IGNORECASE):
            in_platform = False
            result.append(line)
            continue
        if in_platform and _is_simple_platform_reference(stripped):
            skip_block = stripped.split()[0].lower()
            continue
        if in_platform and _is_complex_platform_member_start(stripped):
            skip_block = stripped.split()[0].lower()
            continue
        result.append(line)
    return result


def _apply_platform_visual_markers(lines):
    type_blocks = _collect_platform_type_blocks(lines)
    if not type_blocks:
        return lines

    roles_by_type = {}
    for line in lines:
        match = _PLATFORM_HEADER_RE.match(line)
        if not match:
            continue
        role = _infer_platform_visual_role(match.group(2), match.group(4))
        if role and match.group(4) in type_blocks:
            roles_by_type.setdefault(match.group(4), set()).add(role)
    if not roles_by_type:
        return lines

    existing_names = set(type_blocks)
    rewrites = {}
    replacement_blocks = {}
    for type_name, roles in roles_by_type.items():
        block = type_blocks[type_name]["block"]
        if len(roles) == 1:
            role = next(iter(roles))
            replacement_blocks[type_name] = [_with_visual_marker(block, role)]
            rewrites[(type_name, role)] = type_name
            continue
        blocks = []
        for role in sorted(roles):
            new_type = _visual_type_name(type_name, role, existing_names)
            existing_names.add(new_type)
            rewrites[(type_name, role)] = new_type
            blocks.append(_rename_platform_type_block(_with_visual_marker(block, role, force=True), new_type))
        replacement_blocks[type_name] = blocks

    result = []
    i = 0
    while i < len(lines):
        type_match = _PLATFORM_TYPE_HEADER_RE.match(lines[i])
        if type_match and type_match.group(1) in replacement_blocks:
            original_type = type_match.group(1)
            for block_index, block in enumerate(replacement_blocks[original_type]):
                if block_index:
                    result.append("")
                result.extend(block)
            i = type_blocks[original_type]["end"] + 1
            continue

        platform_match = _PLATFORM_HEADER_RE.match(lines[i])
        if platform_match:
            platform_name = platform_match.group(2)
            platform_type = platform_match.group(4)
            role = _infer_platform_visual_role(platform_name, platform_type)
            new_type = rewrites.get((platform_type, role))
            if new_type and new_type != platform_type:
                line = "".join((
                    platform_match.group(1),
                    platform_name,
                    platform_match.group(3),
                    new_type,
                    platform_match.group(5),
                ))
                result.append(line)
                i += 1
                continue

        result.append(lines[i])
        i += 1
    return result


def _collect_platform_type_blocks(lines):
    blocks = {}
    i = 0
    while i < len(lines):
        match = _PLATFORM_TYPE_HEADER_RE.match(lines[i])
        if not match:
            i += 1
            continue
        start = i
        block = [lines[i]]
        j = i + 1
        while j < len(lines):
            block.append(lines[j])
            if re.match(r"^\s*end_platform_type\b", lines[j], re.IGNORECASE):
                break
            j += 1
        blocks[match.group(1)] = {"start": start, "end": j, "block": block}
        i = j + 1
    return blocks


def _infer_platform_visual_role(platform_name, platform_type):
    text = f"{platform_name} {platform_type}".lower()
    tokens = set(re.split(r"[^a-z0-9]+", text))
    if "radar" in tokens or any(token.startswith("radar") or token.endswith("radar") for token in tokens):
        return "radar"
    if tokens & {"sam", "missile", "launcher"} or any(
        token.startswith(("sam", "missile", "launcher")) or token.endswith("missile")
        for token in tokens
    ):
        return "missile"
    if tokens & {"fighter", "aircraft", "plane", "jet", "ucav", "uav", "bomber", "awacs"} or any(
        token.startswith(("fighter", "aircraft", "plane", "jet", "ucav", "uav", "bomber", "awacs"))
        for token in tokens
    ):
        return "aircraft"
    return ""


def _with_visual_marker(block, role, force=False):
    icon, category = _VISUAL_MARKERS[role]
    result = [block[0]]
    seen_icon = False
    seen_category = False
    for line in block[1:-1]:
        if re.match(r"^\s*icon\b", line, re.IGNORECASE):
            seen_icon = True
            if force:
                result.append(f"{_line_indent(line)}icon {icon}")
            else:
                result.append(line)
            continue
        if re.match(r"^\s*category\b", line, re.IGNORECASE):
            seen_category = True
            if force:
                result.append(f"{_line_indent(line)}category {category}")
            else:
                result.append(line)
            continue
        result.append(line)
    insert_at = 1
    indent = _child_indent(block[0])
    if not seen_icon:
        result.insert(insert_at, f"{indent}icon {icon}")
        insert_at += 1
    if not seen_category:
        result.insert(insert_at, f"{indent}category {category}")
    result.append(block[-1])
    return result


def _rename_platform_type_block(block, new_type):
    header = re.sub(
        r"^(\s*platform_type\s+)\S+",
        lambda match: f"{match.group(1)}{new_type}",
        block[0],
        flags=re.IGNORECASE,
    )
    return [header, *block[1:]]


def _visual_type_name(type_name, role, existing_names):
    base = re.sub(r"[^A-Za-z0-9_]", "_", type_name).strip("_") or "PLATFORM"
    role_token = {"radar": "RADAR", "missile": "MISSILE", "aircraft": "AIRCRAFT"}[role]
    if base.upper().endswith("_PLATFORM"):
        candidate = f"{base[:-9]}_{role_token}_PLATFORM"
    else:
        candidate = f"{base}_{role_token}"
    if candidate not in existing_names:
        return candidate
    suffix = 2
    while f"{candidate}_{suffix}" in existing_names:
        suffix += 1
    return f"{candidate}_{suffix}"


def _normalize_route_navigation(lines, default_speed):
    result = []
    speed = str(default_speed or DEFAULT_ROUTE_SPEED).strip() or DEFAULT_ROUTE_SPEED
    i = 0
    while i < len(lines):
        if not re.match(r"^\s*route\b", lines[i], re.IGNORECASE):
            result.append(lines[i])
            i += 1
            continue

        block = [lines[i]]
        j = i + 1
        found_end = False
        while j < len(lines):
            block.append(lines[j])
            if re.match(r"^\s*end_route\b", lines[j], re.IGNORECASE):
                found_end = True
                break
            j += 1
        if not found_end:
            result.append(lines[i])
            i += 1
            continue

        result.extend(_rewrite_route_block(block, speed))
        i = j + 1
    return result


def _rewrite_route_block(block, default_speed):
    if any(re.match(r"^\s*navigation\b", line, re.IGNORECASE) for line in block):
        return _ensure_navigation_position_speed(block, default_speed)

    header = block[0]
    end = block[-1]
    indent = _child_indent(header)
    position_indent = indent + "   "
    position_lines = []
    passthrough = []
    for line in block[1:-1]:
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r"^\s*position\b", line, re.IGNORECASE):
            position_lines.extend(_position_with_speed_child(line, default_speed, position_indent))
        else:
            passthrough.append(line)
    if not position_lines:
        return block
    return [header, f"{indent}navigation", *position_lines, f"{indent}end_navigation", *passthrough, end]


def _ensure_navigation_position_speed(block, default_speed):
    result = []
    in_navigation = False
    pending_position_line = ""
    pending_position_indent = ""
    for line in block:
        stripped = line.strip()
        if re.match(r"^\s*navigation\b", line, re.IGNORECASE):
            in_navigation = True
            result.append(line)
            continue
        if in_navigation and re.match(r"^\s*end_navigation\b", line, re.IGNORECASE):
            if pending_position_line:
                result.append(pending_position_line)
                result.append(f"{pending_position_indent}   speed {default_speed}")
                pending_position_line = ""
                pending_position_indent = ""
            in_navigation = False
            result.append(line)
            continue
        if in_navigation and re.match(r"^\s*position\b", line, re.IGNORECASE):
            if pending_position_line:
                result.append(pending_position_line)
                result.append(f"{pending_position_indent}   speed {default_speed}")
            match = re.match(r"^(\s*position\b.+?)\s+speed\s+(.+?)\s*$", line, re.IGNORECASE)
            if match:
                result.extend(_position_with_speed_child(line, default_speed))
                pending_position_line = ""
                pending_position_indent = ""
            else:
                pending_position_line = line.rstrip()
                pending_position_indent = _line_indent(line)
            continue
        if in_navigation and re.match(r"^\s*speed\b", line, re.IGNORECASE):
            if pending_position_line:
                result.append(pending_position_line)
                pending_position_line = ""
                result.append(f"{pending_position_indent}   {stripped}")
                pending_position_indent = ""
                continue
            pending_position_indent = ""
            result.append(line)
            continue
        if in_navigation and pending_position_line and stripped:
            result.append(pending_position_line)
            result.append(f"{pending_position_indent}   speed {default_speed}")
            pending_position_line = ""
            pending_position_indent = ""
        result.append(line)
    return result


def _position_with_speed_child(line, default_speed, indent_override=None):
    indent = indent_override if indent_override is not None else _line_indent(line)
    stripped = line.strip()
    match = re.match(r"^(\s*position\b.+?)\s+speed\s+(.+?)\s*$", line, re.IGNORECASE)
    if match:
        position_text = re.sub(r"\s+speed\s+.+?\s*$", "", stripped, flags=re.IGNORECASE)
        return [f"{indent}{position_text}", f"{indent}   speed {match.group(2)}"]
    return [f"{indent}{stripped}", f"{indent}   speed {default_speed}"]


def _line_indent(line):
    return line[: len(line) - len(line.lstrip())]


def _dedupe_adjacent_route_positions(lines):
    result = []
    in_route = False
    last_coords = None
    duplicate_count = 0
    for line in lines:
        if re.match(r"^\s*route\b", line, re.IGNORECASE):
            in_route = True
            last_coords = None
            duplicate_count = 0
            result.append(line)
            continue
        if in_route and re.match(r"^\s*end_route\b", line, re.IGNORECASE):
            in_route = False
            last_coords = None
            duplicate_count = 0
            result.append(line)
            continue
        if in_route and re.match(r"^\s*position\b", line, re.IGNORECASE):
            coords = _position_coords(line)
            if coords and coords == last_coords:
                duplicate_count += 1
                line = _offset_position_lon(line, duplicate_count)
                coords = _position_coords(line)
            else:
                duplicate_count = 0
            last_coords = coords
            result.append(line)
            continue
        result.append(line)
    return result


def _position_coords(line):
    tokens = line.strip().split()
    if len(tokens) < 3 or tokens[0].lower() != "position":
        return None
    return (tokens[1].lower(), tokens[2].lower())


def _offset_position_lon(line, offset_seconds):
    match = re.match(r"^(\s*position\s+\S+\s+)(\S+)(.*)$", line, re.IGNORECASE)
    if not match:
        return line
    return f"{match.group(1)}{_offset_coord_token(match.group(2), offset_seconds)}{match.group(3)}"


def _offset_coord_token(token, offset_seconds):
    match = re.match(r"^(\d+(?:\.\d+)?)(?::(\d+(?:\.\d+)?))?(?::(\d+(?:\.\d+)?))?([nsew])$", token, re.IGNORECASE)
    if not match:
        return token
    deg = match.group(1)
    minute = match.group(2) or "00"
    second = float(match.group(3) or 0) + max(1, int(offset_seconds))
    suffix = match.group(4)
    if second >= 60:
        second = 59.0
    second_text = str(int(second)) if second.is_integer() else f"{second:.3f}".rstrip("0").rstrip(".")
    return f"{deg}:{minute}:{second_text.zfill(2)}{suffix}"


def _normalize_waypoints(lines):
    result = []
    pattern = re.compile(r"^(\s*)waypoint\s+(.+?)\s*$", re.IGNORECASE)
    for line in lines:
        match = pattern.match(line)
        if not match:
            result.append(line)
            continue
        result.append(f"{match.group(1)}position {match.group(2)}")
    return result


def _rewrite_explicit_weapon_block(block):
    kept = [line for line in block[1:-1] if _EXPLICIT_WEAPON_ALLOWED_RE.match(line)]
    return [block[0], *kept, block[-1]]


def _normalize_antenna_patterns(lines):
    result = []
    i = 0
    while i < len(lines):
        if not re.match(r"^\s*antenna_pattern\b", lines[i], re.IGNORECASE):
            result.append(lines[i])
            i += 1
            continue

        block = [lines[i]]
        j = i + 1
        while j < len(lines):
            block.append(lines[j])
            if re.match(r"^\s*end_antenna_pattern\b", lines[j], re.IGNORECASE):
                break
            j += 1
        result.extend(_rewrite_antenna_block(block))
        i = j + 1
    return result


def _normalize_radar_sensors(lines):
    result = []
    i = 0
    while i < len(lines):
        if not re.match(r"^\s*sensor\s+\S+\s+WSF_RADAR_SENSOR\b", lines[i], re.IGNORECASE):
            result.append(lines[i])
            i += 1
            continue

        block = [lines[i]]
        j = i + 1
        found_end = False
        while j < len(lines):
            block.append(lines[j])
            if re.match(r"^\s*end_sensor\b", lines[j], re.IGNORECASE):
                found_end = True
                break
            j += 1
        if not found_end:
            result.append(lines[i])
            i += 1
            continue
        result.extend(_rewrite_radar_sensor_block(block))
        i = j + 1
    return result


def _rewrite_radar_sensor_block(block):
    if any(re.match(r"^\s*mode\b", line, re.IGNORECASE) for line in block):
        return block
    header = block[0]
    antenna = _first_block_value(block, "antenna_pattern") or "RADAR_ANTENNA"
    detect_range = _first_block_value(block, "max_range") or "100 nm"
    indent = _child_indent(header)
    b2 = indent + "   "
    b3 = b2 + "   "
    b4 = b3 + "   "
    return [
        header,
        f"{indent}mode search",
        f"{b2}frame_time 10 sec",
        f"{b2}beam 1",
        f"{b3}transmitter",
        f"{b4}antenna_pattern {antenna}",
        f"{b4}power 500 kw",
        f"{b4}pulse_width 2.0e-6 sec",
        f"{b4}pulse_repetition_frequency 400 hz",
        f"{b4}frequency 1285 mhz",
        f"{b3}end_transmitter",
        f"{b3}receiver",
        f"{b4}antenna_pattern {antenna}",
        f"{b4}bandwidth 1 mhz",
        f"{b4}internal_loss 19 db",
        f"{b4}noise_figure 3 db",
        f"{b3}end_receiver",
        f"{b3}one_m2_detect_range {detect_range}",
        f"{b2}end_beam",
        f"{indent}end_mode",
        block[-1],
    ]


def _first_block_value(block, key):
    pattern = re.compile(rf"^\s*{re.escape(key)}\s+(.+?)\s*$", re.IGNORECASE)
    for line in block[1:-1]:
        match = pattern.match(line)
        if match:
            return match.group(1)
    return ""


def _rewrite_antenna_block(block):
    if any(re.match(r"^\s*constant_pattern\b", line, re.IGNORECASE) for line in block):
        return block
    params = []
    passthrough = []
    for line in block[1:-1]:
        rewritten = _rewrite_antenna_param(line)
        if rewritten:
            params.extend(rewritten)
        elif line.strip() and not re.match(r"^\s*frequency\b", line, re.IGNORECASE):
            passthrough.append(line)
    if not params:
        return block
    indent = _child_indent(block[0])
    deeper = indent + "   "
    return [block[0], f"{indent}constant_pattern", *[deeper + p for p in params],
            f"{indent}end_constant_pattern", *passthrough, block[-1]]


def _rewrite_antenna_param(line):
    stripped = line.strip()
    parts = stripped.split(maxsplit=1)
    if len(parts) != 2:
        return []
    key, value = parts[0].lower(), parts[1].replace("dBi", "db").replace("dB", "db")
    if key == "gain":
        return [f"peak_gain {value}"]
    if key == "peak_gain":
        return [f"peak_gain {value}"]
    if key == "beamwidth":
        return [f"azimuth_beamwidth {value}", f"elevation_beamwidth {value}"]
    if key in ("azimuth_beamwidth", "elevation_beamwidth"):
        return [f"{key} {value}"]
    return []


def _child_indent(line):
    return line[: len(line) - len(line.lstrip())] + "   "


def _normalize_afsim_punctuation(lines):
    result = []
    brace_stack = []
    plain_code_depth = 0
    code_brace_depth = 0
    for idx, line in enumerate(lines):
        stripped = line.strip()
        brace_code = _stack_in_code(brace_stack)
        in_code = plain_code_depth > 0 or brace_code
        normalized = line

        if stripped == "{":
            token = _line_block_token(result[-1]) if result else ""
            if token and not in_code:
                brace_stack.append((token, _is_code_section(token)))
            elif in_code:
                code_brace_depth += 1
                result.append(line)
            continue

        if stripped == "}":
            if brace_code and code_brace_depth > 0:
                code_brace_depth -= 1
                result.append(line)
                continue
            if brace_stack:
                token, _ = brace_stack.pop()
                if not _next_is_matching_end(lines, idx, token):
                    result.append(_end_line_for(line, token))
                continue
            if in_code:
                result.append(line)
            continue

        if not in_code:
            normalized = _remove_non_code_semicolon(normalized)
            token = _line_block_token(normalized)
            if normalized.strip().endswith("{") and token and not _CONTROL_CODE_RE.match(stripped):
                normalized = _remove_non_code_open_brace(normalized)
                brace_stack.append((token, _is_code_section(token)))
        elif brace_code and _CONTROL_CODE_RE.match(stripped) and stripped.endswith("{"):
            code_brace_depth += 1

        result.append(normalized)

        if not brace_code and _CODE_SECTION_START_RE.match(stripped) and not stripped.endswith("{"):
            plain_code_depth += 1
        if _CODE_SECTION_END_RE.match(stripped) and plain_code_depth > 0:
            plain_code_depth -= 1
    return result


def _stack_in_code(stack):
    return bool(stack and stack[-1][1])


def _line_block_token(line):
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return ""
    token = stripped.split()[0].lower()
    if token.endswith("{"):
        token = token[:-1]
    return token


def _is_code_section(token):
    return bool(_CODE_SECTION_START_RE.match(token))


def _next_is_matching_end(lines, idx, token):
    expected = f"end_{token}".lower()
    for i in range(idx + 1, len(lines)):
        stripped = lines[i].strip().lower()
        if stripped:
            return stripped == expected
    return False


def _end_line_for(line, token):
    indent = line[: len(line) - len(line.lstrip())]
    return f"{indent}end_{token}"


def _remove_non_code_open_brace(line):
    stripped = line.strip()
    if _CONTROL_CODE_RE.match(stripped):
        return line
    if stripped.endswith("{"):
        return line[: line.rfind("{")].rstrip()
    return line


def _remove_non_code_semicolon(line):
    stripped = line.rstrip()
    if stripped.endswith(";"):
        return stripped[:-1].rstrip()
    return line


def _strip_afsim_wrapper_braces(lines):
    result = []
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "{" and _previous_is_afsim_block_start(lines, idx):
            continue
        if stripped == "}" and _next_is_afsim_block_end(lines, idx):
            continue
        result.append(line)
    return result


def _previous_is_afsim_block_start(lines, idx):
    for i in range(idx - 1, -1, -1):
        if lines[i].strip():
            return bool(_AFSIM_BLOCK_START_RE.match(lines[i]))
    return False


def _next_is_afsim_block_end(lines, idx):
    for i in range(idx + 1, len(lines)):
        if lines[i].strip():
            return bool(_AFSIM_BLOCK_END_RE.match(lines[i]))
    return False
