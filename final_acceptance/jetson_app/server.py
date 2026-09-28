#!/usr/bin/env python3
"""Small Python 3.6-compatible DOFBOT camera and guarded servo server."""

from __future__ import print_function

import argparse
import atexit
import fcntl
import json
import os
import threading
import time

CONFIRMATION = "POWER_CUTOFF_READY"


def load_config(path):
    with open(path, "r") as handle:
        config = json.load(handle)
    validate_config(config)
    return config


def validate_config(config):
    manual_control = config.get("manual_control", {})
    if "enabled" not in manual_control or "reason" not in manual_control:
        raise ValueError("config must define the manual control safety lock")
    servos = config.get("servos", {})
    if sorted(servos) != ["1", "2", "3", "4", "5", "6"]:
        raise ValueError("config must define servo IDs 1 through 6")
    for servo_id, item in servos.items():
        lower = int(item["min"])
        upper = int(item["max"])
        initial = int(item["initial"])
        absolute_upper = 270 if servo_id == "5" else 180
        if not 0 <= lower <= initial <= upper <= absolute_upper:
            raise ValueError("invalid limits for servo {}".format(servo_id))
        max_step = int(item.get("max_step", upper - lower))
        if max_step < 1 or max_step > upper - lower:
            raise ValueError("invalid max_step for servo {}".format(servo_id))
    standby_pose = config.get("standby_pose", {})
    standby_angles = standby_pose.get("angles", {})
    if standby_pose.get("enabled", False) and sorted(standby_angles) != ["1", "2", "3", "4", "5", "6"]:
        raise ValueError("standby pose must define servo IDs 1 through 6")
    if not standby_pose.get("enabled", False) and standby_angles:
        raise ValueError("disabled standby pose must not retain unverified angles")
    standby_duration = int(standby_pose.get("duration_ms", config["move_time_ms"]))
    for servo_id, angle in standby_angles.items():
        validate_move(config, int(servo_id), int(angle), standby_duration)
    k1_pose = config.get("k1_pose", {})
    k1_angles = k1_pose.get("angles", {})
    if k1_pose.get("enabled", False) and sorted(k1_angles) != ["1", "2", "3", "4", "5", "6"]:
        raise ValueError("K1 pose must define servo IDs 1 through 6")
    for servo_id, angle in k1_angles.items():
        item = servos[servo_id]
        if int(angle) < int(item["min"]) or int(angle) > int(item["max"]):
            raise ValueError("invalid K1 angle for servo {}".format(servo_id))
    gesture_actions = config.get("gesture_actions", {})
    actions = gesture_actions.get("actions", {})
    expected = {"Thumb_Up", "Closed_Fist", "Victory", "Pointing_Up"}
    if set(actions) != expected:
        raise ValueError("gesture actions must define exactly four supported gestures")
    for gesture_name, action in actions.items():
        action_type = action.get("type")
        if action_type not in (
            "gripper_open", "gripper_close", "sequence", "standby", "standby_then_sequence"
        ):
            raise ValueError("invalid action type for gesture {}".format(gesture_name))
        if action_type in ("sequence", "standby_then_sequence"):
            for step in action.get("steps", []):
                validate_move(
                    config,
                    int(step["servo_id"]),
                    int(step["angle"]),
                    int(step.get("duration_ms", config["move_time_ms"])),
                )


def validate_move(config, servo_id, angle, duration_ms):
    if servo_id < 1 or servo_id > 6:
        raise ValueError("servo ID must be 1..6")
    item = config["servos"][str(servo_id)]
    if not item.get("enabled", False):
        raise ValueError("servo {} is locked until calibration".format(servo_id))
    lower = int(item["min"])
    upper = int(item["max"])
    if angle < lower or angle > upper:
        raise ValueError("target must stay inside {}..{} degrees".format(lower, upper))
    if duration_ms < 1500 or duration_ms > 5000:
        raise ValueError("duration must be 1500..5000 ms")
    return item


class Camera(object):
    def __init__(self, config):
        self.config = config
        self.capture = None
        self.frame = None
        self.error = None
        self.running = False
        self.lock = threading.Lock()
        self.thread = None
        self.cv2 = None
        devices = config.get("devices")
        if devices is None:
            devices = [config.get("device", 0)]
        self.devices = [int(device) for device in devices]
        self.selected_device = None

    def _open_first_working_device(self):
        if self.capture is not None:
            self.capture.release()
            self.capture = None
        self.selected_device = None
        width = int(self.config.get("width", 640))
        height = int(self.config.get("height", 480))
        backend = getattr(self.cv2, "CAP_V4L2", None)
        for device in self.devices:
            if backend is None:
                capture = self.cv2.VideoCapture(device)
            else:
                capture = self.cv2.VideoCapture(device, backend)
            if not capture.isOpened():
                capture.release()
                continue
            capture.set(self.cv2.CAP_PROP_FRAME_WIDTH, width)
            capture.set(self.cv2.CAP_PROP_FRAME_HEIGHT, height)
            for _attempt in range(5):
                ok, image = capture.read()
                if ok and image is not None:
                    self.capture = capture
                    self.selected_device = device
                    self.error = None
                    return image
                time.sleep(0.05)
            capture.release()
        self.error = "no camera frame from {}".format(
            ", ".join("/dev/video{}".format(device) for device in self.devices)
        )
        return None

    def start(self):
        import cv2
        self.cv2 = cv2
        first_image = self._open_first_working_device()
        if first_image is None:
            return
        self._store_frame(first_image)
        self.running = True
        self.thread = threading.Thread(target=self._loop)
        self.thread.daemon = True
        self.thread.start()

    def _store_frame(self, image):
        quality = int(self.config.get("jpeg_quality", 82))
        ok, encoded = self.cv2.imencode(
            ".jpg", image, [self.cv2.IMWRITE_JPEG_QUALITY, quality]
        )
        if ok:
            with self.lock:
                self.frame = encoded.tobytes()
                self.error = None
        return ok

    def _loop(self):
        interval = 1.0 / max(1, int(self.config.get("max_fps", 12)))
        failures = 0
        while self.running:
            started = time.time()
            if self.capture is None:
                image = self._open_first_working_device()
                ok = image is not None
            else:
                ok, image = self.capture.read()
            if not ok or image is None:
                failures += 1
                self.error = "camera frame read failed"
                if failures >= 8:
                    with self.lock:
                        self.frame = None
                    image = self._open_first_working_device()
                    ok = image is not None
                    failures = 0
                if not ok:
                    time.sleep(0.1)
                    continue
            else:
                failures = 0
            if not self._store_frame(image):
                self.error = "camera JPEG encode failed"
                time.sleep(0.1)
                continue
            remaining = interval - (time.time() - started)
            if remaining > 0:
                time.sleep(remaining)

    def jpeg(self):
        with self.lock:
            return self.frame

    def stop(self):
        self.running = False
        if self.thread is not None:
            self.thread.join(timeout=1.0)
        if self.capture is not None:
            self.capture.release()


class ArmController(object):
    def __init__(self, config, enabled):
        self.config = config
        self.enabled = enabled
        self.estopped = False
        self.last_torque_command = "none"
        self.arm = None
        self.lock = threading.Lock()
        self.active_servo_id = None
        self.motion_until = 0.0
        self.events = []
        self.event_sequence = 0
        self.event_lock = threading.Lock()
        self.last_angles = dict(
            (servo_id, int(item["initial"]))
            for servo_id, item in config["servos"].items()
        )
        self.servo_states = dict(
            (
                servo_id,
                {
                    "target_angle": int(item["initial"]),
                    "actual_angle": None,
                    "feedback": "unavailable",
                    "command_state": "idle",
                    "last_command_at": None,
                    "last_message": "尚未下发命令",
                },
            )
            for servo_id, item in config["servos"].items()
        )
        if enabled:
            from Arm_Lib import Arm_Device
            self.arm = Arm_Device()
        self.record_event(
            "warning" if enabled else "info",
            "server_start",
            "真机服务已启动；角度反馈未启用，状态表只显示命令目标",
            {"hardware_enabled": bool(enabled)},
        )

    def record_event(self, level, event_type, message, details=None):
        if not hasattr(self, "event_lock"):
            self.event_lock = threading.Lock()
            self.events = []
            self.event_sequence = 0
        with self.event_lock:
            self.event_sequence += 1
            event = {
                "sequence": self.event_sequence,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "level": level,
                "type": event_type,
                "message": message,
                "details": details or {},
            }
            self.events.append(event)
            if len(self.events) > 200:
                self.events = self.events[-200:]
            return event

    def events_snapshot(self):
        if not hasattr(self, "event_lock"):
            return []
        with self.event_lock:
            return [dict(event) for event in self.events]

    def servo_states_snapshot(self):
        if not hasattr(self, "servo_states"):
            return {}
        with self.lock:
            return dict((key, dict(value)) for key, value in self.servo_states.items())

    def require_hardware(self):
        manual_control = self.config["manual_control"]
        if not manual_control.get("enabled", False):
            raise RuntimeError(manual_control["reason"])
        if not self.enabled or self.arm is None:
            raise RuntimeError("hardware mode is disabled on the server")
        if self.estopped:
            raise RuntimeError("torque is disabled; resume deliberately before moving")

    def move(self, servo_id, angle, duration_ms):
        current_angle = self.last_angles.get(str(servo_id))
        try:
            item = validate_move(self.config, servo_id, angle, duration_ms)
            self.require_hardware()
            with self.lock:
                current_angle = int(self.last_angles[str(servo_id)])
                max_step = int(item.get("max_step", int(item["max"]) - int(item["min"])))
                if abs(angle - current_angle) > max_step:
                    raise ValueError(
                        "servo {} may move at most {} degree per command; current={} target={}".format(
                            servo_id, max_step, current_angle, angle
                        )
                    )
                now = time.monotonic()
                if now < self.motion_until:
                    remaining = self.motion_until - now
                    raise RuntimeError(
                        "servo {} is still moving; wait {:.1f}s before commanding servo {}".format(
                            self.active_servo_id, remaining, servo_id
                        )
                    )
                self.arm.Arm_serial_servo_write(servo_id, angle, duration_ms)
                self.last_angles[str(servo_id)] = angle
                self.active_servo_id = servo_id
                self.motion_until = now + duration_ms / 1000.0
                if hasattr(self, "servo_states"):
                    self.servo_states[str(servo_id)].update({
                        "target_angle": angle,
                        "command_state": "commanded",
                        "last_command_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "last_message": "已写入控制板，无到位反馈",
                    })
            self.record_event(
                "info",
                "servo_command",
                "S{} {}\u00b0 -> {}\u00b0，{} ms；已写入控制板，无到位反馈".format(
                    servo_id, current_angle, angle, duration_ms
                ),
                {
                    "servo_id": servo_id,
                    "from_angle": current_angle,
                    "target_angle": angle,
                    "duration_ms": duration_ms,
                },
            )
        except (ValueError, RuntimeError) as error:
            if hasattr(self, "servo_states") and str(servo_id) in self.servo_states:
                with self.lock:
                    self.servo_states[str(servo_id)].update({
                        "command_state": "rejected",
                        "last_command_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "last_message": str(error),
                    })
            self.record_event(
                "error",
                "servo_rejected",
                "S{} 目标 {}\u00b0 被拒绝：{}".format(servo_id, angle, error),
                {"servo_id": servo_id, "target_angle": angle, "duration_ms": duration_ms},
            )
            raise

    def gripper(self, state):
        item = self.config["gripper"]
        angle_key = "open_angle" if state == "open" else "closed_angle"
        servo_id = int(item["servo_id"])
        angle = int(item[angle_key])
        duration_ms = int(item.get("move_time_ms", self.config["move_time_ms"]))
        servo_id_text = str(servo_id)
        max_step = int(self.config["servos"][servo_id_text]["max_step"])
        while int(self.last_angles[servo_id_text]) != angle:
            current = int(self.last_angles[servo_id_text])
            delta = max(-max_step, min(max_step, angle - current))
            self.move(servo_id, current + delta, duration_ms)
            time.sleep(duration_ms / 1000.0)
        return angle

    def emergency_stop(self):
        if not self.enabled or self.arm is None:
            raise RuntimeError("hardware mode is disabled on the server")
        with self.lock:
            self.arm.Arm_serial_set_torque(0)
            self.estopped = True
            self.last_torque_command = "off"
        self.record_event("critical", "torque_off", "已请求关闭全部舵机扭矩，机械臂可能下坠")

    def resume(self):
        manual_control = self.config["manual_control"]
        if not manual_control.get("enabled", False):
            error = RuntimeError(manual_control["reason"])
            self.record_event("error", "torque_on_rejected", "恢复扭矩被拒绝：{}".format(error))
            raise error
        if not self.enabled or self.arm is None:
            raise RuntimeError("hardware mode is disabled on the server")
        with self.lock:
            self.arm.Arm_serial_set_torque(1)
            self.estopped = False
            self.last_torque_command = "on"
        self.record_event("warning", "torque_on", "已请求开启全部舵机扭矩")

    def execute_gesture(self, gesture_name):
        gesture_config = self.config["gesture_actions"]
        action = gesture_config["actions"].get(gesture_name)
        if action is None:
            raise ValueError("unsupported gesture {}".format(gesture_name))
        if not gesture_config.get("enabled", False):
            raise RuntimeError(gesture_config.get("reason", "gesture actions are disabled"))
        if not action.get("enabled", False):
            raise RuntimeError(action.get("reason", "gesture action is locked"))
        self.record_event(
            "info", "gesture_trigger", "手势 {} 已触发：{}".format(gesture_name, action["label"])
        )
        if action["type"] == "gripper_open":
            return {"angle": self.gripper("open")}
        if action["type"] == "gripper_close":
            return {"angle": self.gripper("close")}
        if action["type"] == "standby":
            return {"standby": self.standby_pose()}
        standby = None
        if action["type"] == "standby_then_sequence":
            standby = self.standby_pose()
        for step in action.get("steps", []):
            servo_id = int(step["servo_id"])
            angle = int(step["angle"])
            duration_ms = int(step.get("duration_ms", self.config["move_time_ms"]))
            self.move(servo_id, angle, duration_ms)
            time.sleep((duration_ms + int(step.get("pause_ms", 0))) / 1000.0)
        return {"standby": standby, "steps": len(action.get("steps", []))}

    def standby_pose(self):
        pose = self.config["standby_pose"]
        if not pose.get("enabled", False):
            error = RuntimeError(pose.get("reason", "standby pose is locked"))
            self.record_event("error", "standby_rejected", "等候姿势被拒绝：{}".format(error))
            raise error
        self.require_hardware()
        duration_ms = int(pose.get("duration_ms", self.config["move_time_ms"]))
        targets = dict((servo_id, int(angle)) for servo_id, angle in pose["angles"].items())
        self.record_event(
            "warning", "standby_start", "开始执行等候姿势；逐轴、单步不超过配置限制", targets
        )
        for servo_id_text in ("1", "2", "3", "4", "5", "6"):
            servo_id = int(servo_id_text)
            target = targets[servo_id_text]
            while int(self.last_angles[servo_id_text]) != target:
                current = int(self.last_angles[servo_id_text])
                max_step = int(self.config["servos"][servo_id_text]["max_step"])
                delta = max(-max_step, min(max_step, target - current))
                self.move(servo_id, current + delta, duration_ms)
                time.sleep(duration_ms / 1000.0)
        self.record_event("info", "standby_complete", "等候姿势目标序列已全部写入；无到位反馈")
        return targets

    def sync_k1_pose(self):
        """Synchronize software state after an operator physically presses K1.

        This intentionally sends no Arm_Lib command. The expansion-board K1 event is
        invisible to the Jetson, so the operator must invoke this explicitly.
        """
        pose = self.config["k1_pose"]
        if not pose.get("enabled", False):
            raise RuntimeError(pose.get("reason", "K1 synchronization is disabled"))
        self.require_hardware()
        with self.lock:
            now = time.monotonic()
            if now < self.motion_until:
                raise RuntimeError(
                    "servo {} is still moving; wait {:.1f}s before K1 synchronization".format(
                        self.active_servo_id, self.motion_until - now
                    )
                )
            angles = dict((servo_id, int(angle)) for servo_id, angle in pose["angles"].items())
            self.last_angles.update(angles)
            self.active_servo_id = None
            for servo_id, angle in angles.items():
                self.servo_states[servo_id].update({
                    "target_angle": angle,
                    "actual_angle": None,
                    "feedback": "operator_confirmed_k1",
                    "command_state": "synced",
                    "last_command_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "last_message": "操作者确认已按 K1；仅同步软件基准，未发送舵机命令",
                })
        self.record_event(
            "warning",
            "k1_pose_synced",
            "已按操作者确认同步 K1 直立基准；未发送舵机命令",
            angles,
        )
        return angles

    def victory_pose(self):
        pose = self.config["victory_pose"]
        if not pose.get("enabled", False):
            raise RuntimeError(pose.get("reason", "Victory pose is locked"))
        steps = pose.get("steps", [])
        if not steps:
            raise RuntimeError("Victory pose has no calibrated steps")
        validated = []
        for step in steps:
            servo_id = int(step["servo_id"])
            angle = int(step["angle"])
            duration_ms = int(step.get("duration_ms", self.config["move_time_ms"]))
            validate_move(self.config, servo_id, angle, duration_ms)
            validated.append((servo_id, angle, duration_ms, int(step.get("pause_ms", 0))))
        self.require_hardware()
        for servo_id, angle, duration_ms, pause_ms in validated:
            self.move(servo_id, angle, duration_ms)
            time.sleep((duration_ms + pause_ms) / 1000.0)

    def close(self):
        if self.arm is not None:
            self.arm.bus.close()


def acquire_hardware_lock(enabled):
    if not enabled:
        return None
    handle = open("/tmp/dofbot_web_hardware.lock", "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        handle.close()
        raise RuntimeError("another DOFBOT web controller already owns the hardware lock")
    return handle


def create_app(config, web_root, hardware_enabled):
    from flask import Flask, jsonify, request, send_from_directory

    app = Flask(__name__, static_folder=None)
    camera = Camera(config["camera"])
    controller = ArmController(config, hardware_enabled)
    app.config["DOFBOT_CAMERA"] = camera
    app.config["DOFBOT_ARM"] = controller

    @app.route("/")
    def index():
        response = send_from_directory(web_root, "hardware-control.html")
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response

    @app.route("/web/<path:name>")
    def web_file(name):
        response = send_from_directory(web_root, name)
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response

    @app.route("/api/status")
    def status():
        return jsonify({
            "hardware_enabled": controller.enabled,
            "estopped": controller.estopped,
            "last_torque_command": controller.last_torque_command,
            "camera_ready": camera.jpeg() is not None,
            "camera_error": camera.error,
            "camera_device": camera.selected_device,
            "servos": config["servos"],
            "last_angles": controller.last_angles,
            "active_servo_id": controller.active_servo_id,
            "move_time_ms": config["move_time_ms"],
            "live_move_time_ms": config["live_move_time_ms"],
            "standby_pose": config["standby_pose"],
            "k1_pose": config["k1_pose"],
            "gripper": config["gripper"],
            "victory_pose": config["victory_pose"],
            "gesture_actions": config["gesture_actions"],
            "manual_control": config["manual_control"],
            "servo_states": controller.servo_states_snapshot(),
        })

    @app.route("/api/telemetry")
    def telemetry():
        return jsonify({
            "estopped": controller.estopped,
            "last_torque_command": controller.last_torque_command,
            "active_servo_id": controller.active_servo_id,
            "last_angles": controller.last_angles,
            "servo_states": controller.servo_states_snapshot(),
            "events": controller.events_snapshot(),
        })

    @app.route("/api/camera/frame.jpg")
    def camera_frame():
        frame = camera.jpeg()
        if frame is None:
            return jsonify({"error": camera.error or "camera is starting"}), 503
        device = camera.selected_device
        headers = {
            "Cache-Control": "no-store",
            "X-DOFBOT-Camera-Device": "" if device is None else "/dev/video{}".format(device),
        }
        return app.response_class(frame, mimetype="image/jpeg", headers=headers)

    @app.route("/api/servos/<int:servo_id>", methods=["POST"])
    def move_servo(servo_id):
        payload = request.get_json(force=True, silent=False) or {}
        angle = int(payload["angle"])
        duration_ms = int(payload.get("duration_ms", config["move_time_ms"]))
        controller.move(servo_id, angle, duration_ms)
        return jsonify({"ok": True, "servo_id": servo_id, "angle": angle, "duration_ms": duration_ms})

    @app.route("/api/gripper/<state>", methods=["POST"])
    def gripper(state):
        if state not in ("open", "close"):
            return jsonify({"error": "state must be open or close"}), 400
        angle = controller.gripper(state)
        return jsonify({"ok": True, "state": state, "angle": angle})

    @app.route("/api/emergency-stop", methods=["POST"])
    def emergency_stop():
        controller.emergency_stop()
        return jsonify({"ok": True, "estopped": True})

    @app.route("/api/resume", methods=["POST"])
    def resume():
        controller.resume()
        return jsonify({"ok": True, "estopped": False})

    @app.route("/api/victory", methods=["POST"])
    def victory():
        controller.victory_pose()
        return jsonify({"ok": True})

    @app.route("/api/standby", methods=["POST"])
    def standby():
        angles = controller.standby_pose()
        return jsonify({"ok": True, "angles": angles})

    @app.route("/api/sync-k1", methods=["POST"])
    def sync_k1():
        angles = controller.sync_k1_pose()
        return jsonify({"ok": True, "angles": angles, "hardware_command_sent": False})

    @app.route("/api/gestures/<gesture_name>", methods=["POST"])
    def trigger_gesture(gesture_name):
        try:
            result = controller.execute_gesture(gesture_name)
        except (ValueError, RuntimeError) as error:
            controller.record_event(
                "error", "gesture_rejected", "手势 {} 被拒绝：{}".format(gesture_name, error)
            )
            raise
        return jsonify({"ok": True, "gesture": gesture_name, "result": result})

    @app.errorhandler(ValueError)
    @app.errorhandler(RuntimeError)
    def guarded_error(error):
        return jsonify({"error": str(error)}), 423

    camera.start()
    atexit.register(camera.stop)
    atexit.register(controller.close)
    return app


def main():
    parser = argparse.ArgumentParser()
    base = os.path.dirname(os.path.abspath(__file__))
    parser.add_argument("--config", default=os.path.join(base, "hardware_config.json"))
    parser.add_argument("--web-root", default=os.path.join(base, "..", "frontend"))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--enable-hardware", action="store_true")
    args = parser.parse_args()

    confirmed = os.environ.get("DOFBOT_HARDWARE_CONFIRM") == CONFIRMATION
    hardware_enabled = bool(args.enable_hardware and confirmed)
    if args.enable_hardware and not confirmed:
        raise SystemExit("Refusing hardware mode: set DOFBOT_HARDWARE_CONFIRM={}".format(CONFIRMATION))

    lock_handle = acquire_hardware_lock(hardware_enabled)
    config = load_config(args.config)
    app = create_app(config, os.path.abspath(args.web_root), hardware_enabled)
    try:
        app.run(host=args.host, port=args.port, threaded=True, debug=False, use_reloader=False)
    finally:
        if lock_handle is not None:
            lock_handle.close()


if __name__ == "__main__":
    main()
