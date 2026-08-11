from unittest import mock

from core.fixer import (
    apply_fix, validate_blocks, patch_append_base_type,
    patch_close_block, patch_position_format, patch_add_unit,
)
from core.matcher import MatchResult
import os
import tempfile


def _write_tmp(content):
    f = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
    f.write(content)
    f.close()
    return f.name


def test_patch_append_base_type():
    text = "platform_type MY_PLATFORM\n   side red\nend_platform_type\n"
    assert "WSF_PLATFORM" in patch_append_base_type(text, "platform_type MY_PLATFORM", "WSF_PLATFORM")


def test_validate_blocks_detects_unclosed():
    text = "mover WSF_AIR_MOVER\n   debug\nend_platform_type\n"
    assert "mover" in validate_blocks(text)


def test_apply_fix_template():
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("platform_type MY_PLATFORM\nend_platform_type\n")
        path = f.name
    m = MatchResult("E001", "exact", "Unknown command: platform_type", 1,
                    {"type": "template", "description": "追加基类型"}, [])
    assert apply_fix(path, m) is True
    assert "WSF_PLATFORM" in open(path).read()
    os.unlink(path)


def test_apply_fix_radar_signature():
    path = _write_tmp("radar_signature MY_SIG\nend_radar_signature\n")
    m = MatchResult("E002", "exact", "Unknown command: radar_signature", 1,
                    {"type": "template", "description": "缺少基类型 `WSF_RADAR_SIGNATURE`。"}, [])
    assert apply_fix(path, m) is True
    assert "WSF_RADAR_SIGNATURE" in open(path).read()
    os.unlink(path)


def test_apply_fix_close_block():
    path = _write_tmp("mover WSF_AIR_MOVER\n   speed 300\n")
    m = MatchResult("E003", "exact", "Mover not closed", 2,
                    {"type": "template", "description": "缺少对应的 `end_mover` / `end_sensor` / `end_weapon`。"}, [])
    assert apply_fix(path, m) is True
    assert open(path).read().rstrip().endswith("end_mover")
    assert validate_blocks(open(path).read()) == []
    os.unlink(path)


def test_apply_fix_position_format():
    path = _write_tmp("   position 30 120\nend_platform_type\n")
    m = MatchResult("E005", "exact", "Invalid position format", 1,
                    {"type": "template", "description": "坐标格式不正确。AFSIM 要求 `d:m:s N/S e/w`。"}, [])
    assert apply_fix(path, m) is True
    assert "position 30:00:00n 120:00:00e" in open(path).read()
    os.unlink(path)


def test_apply_fix_add_unit():
    path = _write_tmp("   speed 300\nend_platform_type\n")
    m = MatchResult("E006", "exact", "速度单位缺失", 1,
                    {"type": "template", "description": "speed 后缺少单位。"}, [])
    assert apply_fix(path, m) is True
    assert "speed 300 kts" in open(path).read()
    os.unlink(path)


def test_apply_fix_unknown_description_returns_false():
    path = _write_tmp("platform_type MY_PLATFORM\nend_platform_type\n")
    original = open(path).read()
    m = MatchResult("E099", "exact", "weird error", 1,
                    {"type": "template", "description": "无法识别的未知错误。"}, [])
    assert apply_fix(path, m) is False
    assert open(path).read() == original
    os.unlink(path)


def test_apply_fix_idempotent():
    path = _write_tmp("platform_type MY_PLATFORM\nend_platform_type\n")
    m = MatchResult("E001", "exact", "Unknown command: platform_type", 1,
                    {"type": "template", "description": "追加基类型"}, [])
    assert apply_fix(path, m) is True
    after_first = open(path).read()
    assert apply_fix(path, m) is False
    assert open(path).read() == after_first
    os.unlink(path)


def test_apply_fix_missing_file_returns_false():
    assert apply_fix("/nonexistent/definitely/missing.txt", None) is False


def test_patch_close_block_skips_existing():
    text = "mover M\nend_mover\n"
    assert patch_close_block(text, "mover") == text


def test_patch_position_format_idempotent():
    text = "   position 30 120\n"
    once = patch_position_format(text)
    assert "position 30:00:00n 120:00:00e" in once
    assert patch_position_format(once) == once


def test_patch_add_unit_altitude():
    text = "   altitude 10000\n"
    assert "altitude 10000 ft msl" in patch_add_unit(text, "altitude")


def test_patch_add_unit_time():
    text = "   end_time 3600\n"
    assert "end_time 3600 sec" in patch_add_unit(text, "end_time")


def test_patch_add_unit_skips_existing():
    text = "   speed 300 kts\n"
    assert patch_add_unit(text, "speed") == text


def test_validate_blocks_balanced_nested():
    text = ("platform_type A\n   mover M\n      sensor S\n   end_sensor\n"
            "   end_mover\nend_platform_type\n")
    assert validate_blocks(text) == []


def test_validate_blocks_reports_inner_unclosed():
    text = "platform_type A\n   sensor S\nend_platform_type\n"
    assert "sensor" in validate_blocks(text)


def test_apply_fix_rollback_on_new_unclosed():
    path = _write_tmp("platform_type MY_PLATFORM\nend_platform_type\n")
    original = open(path).read()
    m = MatchResult("E001", "exact", "Unknown command: platform_type", 1,
                    {"type": "template", "description": "追加基类型"}, [])
    broken = original + "sensor BAD\n"
    with mock.patch("core.fixer.patch_append_base_type", return_value=broken):
        assert apply_fix(path, m) is False
    assert open(path).read() == original
    os.unlink(path)


def test_apply_fix_e008_time_unit_via_description():
    path = _write_tmp("end_time 30\n")
    m = MatchResult("E008", "exact", "时间单位缺失", 1,
                    {"type": "template", "description": "end_time 等时间参数缺少单位。"}, [])
    assert apply_fix(path, m) is True
    assert "end_time 30 sec" in open(path).read()
    os.unlink(path)


def test_apply_fix_unknown_time_command_normalizes_script():
    path = _write_tmp("time\n   duration 600 sec\nend_time\n")
    m = MatchResult("E001", "exact", "Unknown command: time", 1,
                    {"type": "template", "description": "未知命令。"}, [])
    assert apply_fix(path, m) is True
    assert open(path).read() == "end_time 7200 sec\n"
    os.unlink(path)


def test_apply_fix_unknown_enable_debug_normalizes_script():
    path = _write_tmp("script_interface\n   enable_debug\nend_script_interface\n")
    m = MatchResult("E001", "exact", "Unknown command: enable_debug", 2,
                    {"type": "template", "description": "未知命令。"}, [])
    assert apply_fix(path, m) is True
    assert "   debug\n" in open(path).read()
    os.unlink(path)
