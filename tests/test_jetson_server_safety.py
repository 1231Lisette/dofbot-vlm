import importlib.util
import threading
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).parents[1] / "jetson_app" / "server.py"
SPEC = importlib.util.spec_from_file_location("jetson_server", MODULE_PATH)
SERVER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(SERVER)


def config():
    return SERVER.load_config(Path(__file__).parents[1] / "jetson_app" / "hardware_config.json")


def test_all_sliders_use_bounded_commissioning_ranges():
    servos = config()["servos"]
    assert all(item["enabled"] for item in servos.values())
    for servo_id in ("1", "2", "3", "4", "5"):
        assert servos[servo_id]["min"] == 85
        assert servos[servo_id]["max"] == 95
    assert servos["6"]["min"] == 90
    assert servos["6"]["max"] == 180


def test_gripper_direction_matches_measured_hardware():
    gripper = config()["gripper"]
    assert gripper["open_angle"] == 170
    assert gripper["closed_angle"] == 180


def test_servo_six_accepts_only_commissioned_envelope():
    settings = config()
    SERVER.validate_move(settings, 6, 90, 2500)
    SERVER.validate_move(settings, 6, 180, 2500)
    with pytest.raises(ValueError, match="inside 90..180"):
        SERVER.validate_move(settings, 6, 89, 2500)
    with pytest.raises(ValueError, match="inside 90..180"):
        SERVER.validate_move(settings, 6, 181, 2500)


def test_commissioning_joint_rejects_outside_narrow_range():
    settings = config()
    SERVER.validate_move(settings, 2, 90, 2500)
    with pytest.raises(ValueError, match="inside 85..95"):
        SERVER.validate_move(settings, 2, 84, 2500)
    with pytest.raises(ValueError, match="inside 85..95"):
        SERVER.validate_move(settings, 2, 96, 2500)


def test_fast_motion_is_rejected():
    with pytest.raises(ValueError, match="1500..5000"):
        SERVER.validate_move(config(), 6, 175, 500)


def test_live_drag_uses_slow_bounded_duration():
    settings = config()
    assert settings["live_move_time_ms"] == 1500
    SERVER.validate_move(settings, 6, 135, settings["live_move_time_ms"])


def test_victory_pose_stays_locked_until_joint_calibration():
    pose = config()["victory_pose"]
    assert pose["enabled"] is False
    assert pose["steps"] == []


def test_controller_rejects_switching_axes_during_active_move():
    class FakeArm:
        def Arm_serial_servo_write(self, servo_id, angle, duration_ms):
            self.last_write = (servo_id, angle, duration_ms)

    controller = object.__new__(SERVER.ArmController)
    controller.config = config()
    controller.enabled = True
    controller.estopped = False
    controller.arm = FakeArm()
    controller.lock = threading.Lock()
    controller.last_angles = {str(index): 90 for index in range(1, 7)}
    controller.active_servo_id = None
    controller.motion_until = 0.0

    controller.move(1, 91, 1500)
    with pytest.raises(RuntimeError, match="servo 1 is still moving"):
        controller.move(2, 91, 1500)
