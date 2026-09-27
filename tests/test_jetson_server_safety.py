import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).parents[1] / "jetson_app" / "server.py"
SPEC = importlib.util.spec_from_file_location("jetson_server", MODULE_PATH)
SERVER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(SERVER)


def config():
    return SERVER.load_config(Path(__file__).parents[1] / "jetson_app" / "hardware_config.json")


def test_only_servo_six_is_enabled():
    servos = config()["servos"]
    assert [servo_id for servo_id, item in servos.items() if item["enabled"]] == ["6"]


def test_gripper_direction_matches_measured_hardware():
    gripper = config()["gripper"]
    assert gripper["open_angle"] == 170
    assert gripper["closed_angle"] == 180


def test_servo_six_accepts_only_commissioned_envelope():
    settings = config()
    SERVER.validate_move(settings, 6, 170, 2500)
    SERVER.validate_move(settings, 6, 180, 2500)
    with pytest.raises(ValueError, match="inside 170..180"):
        SERVER.validate_move(settings, 6, 169, 2500)
    with pytest.raises(ValueError, match="inside 170..180"):
        SERVER.validate_move(settings, 6, 181, 2500)


def test_uncalibrated_servo_is_locked():
    with pytest.raises(ValueError, match="locked until calibration"):
        SERVER.validate_move(config(), 2, 90, 2500)


def test_fast_motion_is_rejected():
    with pytest.raises(ValueError, match="1500..5000"):
        SERVER.validate_move(config(), 6, 175, 500)
