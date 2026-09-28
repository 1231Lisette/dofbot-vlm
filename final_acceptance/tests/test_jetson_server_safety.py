import importlib.util
import copy
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


def control_enabled_config():
    settings = copy.deepcopy(config())
    settings["manual_control"]["enabled"] = True
    return settings


def test_all_sliders_use_vendor_nominal_ranges_with_bounded_steps():
    servos = config()["servos"]
    assert all(item["enabled"] for item in servos.values())
    for servo_id in ("1", "2", "3", "4", "6"):
        assert servos[servo_id]["min"] == 0
        assert servos[servo_id]["max"] == 180
    assert servos["5"]["min"] == 0
    assert servos["5"]["max"] == 270
    assert servos["2"] == {
        "name": "肩部", "enabled": True, "min": 0, "max": 180,
        "initial": 130, "max_step": 10,
    }
    assert servos["3"] == {
        "name": "肘部", "enabled": True, "min": 0, "max": 180,
        "initial": 0, "max_step": 10,
    }
    assert all(item["max_step"] == 10 for item in servos.values())


def test_gripper_direction_matches_measured_hardware():
    gripper = config()["gripper"]
    assert gripper["open_angle"] == 120
    assert gripper["closed_angle"] == 180


def test_servo_six_accepts_vendor_nominal_envelope():
    settings = config()
    SERVER.validate_move(settings, 6, 0, 2500)
    SERVER.validate_move(settings, 6, 180, 2500)
    with pytest.raises(ValueError, match="inside 0..180"):
        SERVER.validate_move(settings, 6, -1, 2500)
    with pytest.raises(ValueError, match="inside 0..180"):
        SERVER.validate_move(settings, 6, 181, 2500)


def test_standard_joint_rejects_outside_vendor_nominal_range():
    settings = config()
    SERVER.validate_move(settings, 2, 90, 2500)
    with pytest.raises(ValueError, match="inside 0..180"):
        SERVER.validate_move(settings, 2, -1, 2500)
    with pytest.raises(ValueError, match="inside 0..180"):
        SERVER.validate_move(settings, 2, 181, 2500)


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


def test_standby_pose_matches_user_confirmed_targets():
    pose = config()["standby_pose"]
    assert pose["enabled"] is True
    assert pose["angles"] == {
        "1": 90, "2": 130, "3": 0, "4": 40, "5": 90, "6": 180,
    }
    assert pose["duration_ms"] == 1500


def test_k1_pose_is_vendor_upright_reference():
    pose = config()["k1_pose"]
    assert pose["enabled"] is True
    assert pose["angles"] == {str(index): 90 for index in range(1, 7)}


def test_k1_sync_changes_only_software_state():
    class FakeArm:
        def __init__(self):
            self.calls = []

        def __getattr__(self, name):
            def unexpected_call(*args, **kwargs):
                self.calls.append((name, args, kwargs))
            return unexpected_call

    controller = SERVER.ArmController(control_enabled_config(), False)
    controller.enabled = True
    controller.arm = FakeArm()
    controller.last_angles = {
        "1": 90, "2": 130, "3": 0, "4": 40, "5": 90, "6": 180,
    }

    result = controller.sync_k1_pose()

    assert result == {str(index): 90 for index in range(1, 7)}
    assert controller.last_angles == result
    assert controller.arm.calls == []
    assert controller.events_snapshot()[-1]["type"] == "k1_pose_synced"


def test_four_gesture_actions_are_defined_and_enabled():
    gesture_actions = config()["gesture_actions"]
    assert gesture_actions["enabled"] is True
    assert set(gesture_actions["actions"]) == {
        "Thumb_Up", "Closed_Fist", "Victory", "Pointing_Up",
    }
    assert gesture_actions["actions"]["Thumb_Up"]["type"] == "gripper_open"
    assert gesture_actions["actions"]["Closed_Fist"]["type"] == "gripper_close"
    assert gesture_actions["actions"]["Victory"]["enabled"] is True
    assert gesture_actions["actions"]["Victory"]["type"] == "standby_then_sequence"
    assert gesture_actions["actions"]["Pointing_Up"]["enabled"] is True
    assert gesture_actions["actions"]["Pointing_Up"]["type"] == "standby"


def test_manual_control_still_requires_explicit_hardware_mode():
    controller = object.__new__(SERVER.ArmController)
    controller.config = config()
    controller.enabled = False
    controller.estopped = False
    controller.arm = None
    controller.lock = threading.Lock()
    controller.last_angles = {str(index): 90 for index in range(1, 7)}
    controller.active_servo_id = None
    controller.motion_until = 0.0

    with pytest.raises(RuntimeError, match="hardware mode is disabled"):
        controller.move(1, 91, 1500)
    with pytest.raises(RuntimeError, match="hardware mode is disabled"):
        controller.resume()


def test_event_log_records_targets_without_claiming_position_feedback():
    class FakeArm:
        def Arm_serial_servo_write(self, servo_id, angle, duration_ms):
            self.last_write = (servo_id, angle, duration_ms)

    controller = object.__new__(SERVER.ArmController)
    controller.config = control_enabled_config()
    controller.enabled = True
    controller.estopped = False
    controller.arm = FakeArm()
    controller.lock = threading.Lock()
    controller.event_lock = threading.Lock()
    controller.events = []
    controller.event_sequence = 0
    controller.last_angles = {
        servo_id: int(item["initial"])
        for servo_id, item in controller.config["servos"].items()
    }
    controller.servo_states = {
        servo_id: {
            "target_angle": int(item["initial"]),
            "actual_angle": None,
            "feedback": "unavailable",
            "command_state": "idle",
            "last_command_at": None,
            "last_message": "",
        }
        for servo_id, item in controller.config["servos"].items()
    }
    controller.active_servo_id = None
    controller.motion_until = 0.0

    controller.move(1, 95, 1500)

    event = controller.events_snapshot()[-1]
    assert event["type"] == "servo_command"
    assert event["details"]["from_angle"] == 90
    assert event["details"]["target_angle"] == 95
    state = controller.servo_states_snapshot()["1"]
    assert state["target_angle"] == 95
    assert state["actual_angle"] is None
    assert state["feedback"] == "unavailable"


def test_controller_rejects_switching_axes_during_active_move():
    class FakeArm:
        def Arm_serial_servo_write(self, servo_id, angle, duration_ms):
            self.last_write = (servo_id, angle, duration_ms)

    controller = object.__new__(SERVER.ArmController)
    controller.config = control_enabled_config()
    controller.enabled = True
    controller.estopped = False
    controller.arm = FakeArm()
    controller.lock = threading.Lock()
    controller.last_angles = {
        servo_id: int(item["initial"])
        for servo_id, item in controller.config["servos"].items()
    }
    controller.active_servo_id = None
    controller.motion_until = 0.0

    controller.move(1, 91, 1500)
    with pytest.raises(RuntimeError, match="servo 1 is still moving"):
        controller.move(2, 131, 1500)


def test_controller_rejects_retargeting_same_servo_during_active_move():
    class FakeArm:
        def Arm_serial_servo_write(self, servo_id, angle, duration_ms):
            self.last_write = (servo_id, angle, duration_ms)

    controller = object.__new__(SERVER.ArmController)
    controller.config = control_enabled_config()
    controller.enabled = True
    controller.estopped = False
    controller.arm = FakeArm()
    controller.lock = threading.Lock()
    controller.last_angles = {str(index): 90 for index in range(1, 7)}
    controller.active_servo_id = None
    controller.motion_until = 0.0

    controller.move(2, 91, 1500)
    with pytest.raises(RuntimeError, match="servo 2 is still moving"):
        controller.move(2, 92, 1500)


def test_all_servos_reject_more_than_ten_degrees_per_command():
    class FakeArm:
        def Arm_serial_servo_write(self, servo_id, angle, duration_ms):
            self.last_write = (servo_id, angle, duration_ms)

    controller = object.__new__(SERVER.ArmController)
    controller.config = control_enabled_config()
    controller.enabled = True
    controller.estopped = False
    controller.arm = FakeArm()
    controller.lock = threading.Lock()
    controller.last_angles = {"1": 90, "2": 90, "3": 90, "4": 90, "5": 90, "6": 180}
    controller.active_servo_id = None
    controller.motion_until = 0.0

    controller.move(2, 100, 1500)
    controller.motion_until = 0.0
    controller.move(3, 80, 1500)
    controller.motion_until = 0.0
    with pytest.raises(ValueError, match="at most 10 degree"):
        controller.move(2, 111, 1500)
    with pytest.raises(ValueError, match="at most 10 degree"):
        controller.move(3, 91, 1500)
