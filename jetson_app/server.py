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

    def start(self):
        import cv2
        self.cv2 = cv2
        self.capture = cv2.VideoCapture(int(self.config.get("device", 0)))
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, int(self.config.get("width", 640)))
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, int(self.config.get("height", 480)))
        if not self.capture.isOpened():
            self.error = "cannot open camera"
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop)
        self.thread.daemon = True
        self.thread.start()

    def _loop(self):
        interval = 1.0 / max(1, int(self.config.get("max_fps", 12)))
        quality = int(self.config.get("jpeg_quality", 82))
        while self.running:
            started = time.time()
            ok, image = self.capture.read()
            if not ok:
                self.error = "camera frame read failed"
                time.sleep(0.1)
                continue
            ok, encoded = self.cv2.imencode(
                ".jpg", image, [self.cv2.IMWRITE_JPEG_QUALITY, quality]
            )
            if ok:
                with self.lock:
                    self.frame = encoded.tobytes()
                    self.error = None
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
        self.last_angles = dict(
            (servo_id, int(item["initial"]))
            for servo_id, item in config["servos"].items()
        )
        if enabled:
            from Arm_Lib import Arm_Device
            self.arm = Arm_Device()

    def require_hardware(self):
        if not self.enabled or self.arm is None:
            raise RuntimeError("hardware mode is disabled on the server")
        if self.estopped:
            raise RuntimeError("torque is disabled; resume deliberately before moving")

    def move(self, servo_id, angle, duration_ms):
        validate_move(self.config, servo_id, angle, duration_ms)
        self.require_hardware()
        with self.lock:
            now = time.monotonic()
            if now < self.motion_until and self.active_servo_id != servo_id:
                remaining = self.motion_until - now
                raise RuntimeError(
                    "servo {} is still moving; wait {:.1f}s before changing servo {}".format(
                        self.active_servo_id, remaining, servo_id
                    )
                )
            self.arm.Arm_serial_servo_write(servo_id, angle, duration_ms)
            self.last_angles[str(servo_id)] = angle
            self.active_servo_id = servo_id
            self.motion_until = now + duration_ms / 1000.0

    def gripper(self, state):
        item = self.config["gripper"]
        angle_key = "open_angle" if state == "open" else "closed_angle"
        servo_id = int(item["servo_id"])
        angle = int(item[angle_key])
        duration_ms = int(item.get("move_time_ms", self.config["move_time_ms"]))
        self.move(servo_id, angle, duration_ms)
        return angle

    def emergency_stop(self):
        if not self.enabled or self.arm is None:
            raise RuntimeError("hardware mode is disabled on the server")
        with self.lock:
            self.arm.Arm_serial_set_torque(0)
            self.estopped = True
            self.last_torque_command = "off"

    def resume(self):
        if not self.enabled or self.arm is None:
            raise RuntimeError("hardware mode is disabled on the server")
        with self.lock:
            self.arm.Arm_serial_set_torque(1)
            self.estopped = False
            self.last_torque_command = "on"

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
        return send_from_directory(web_root, "hardware-control.html")

    @app.route("/web/<path:name>")
    def web_file(name):
        return send_from_directory(web_root, name)

    @app.route("/api/status")
    def status():
        return jsonify({
            "hardware_enabled": controller.enabled,
            "estopped": controller.estopped,
            "last_torque_command": controller.last_torque_command,
            "camera_ready": camera.jpeg() is not None,
            "camera_error": camera.error,
            "servos": config["servos"],
            "last_angles": controller.last_angles,
            "active_servo_id": controller.active_servo_id,
            "move_time_ms": config["move_time_ms"],
            "live_move_time_ms": config["live_move_time_ms"],
            "gripper": config["gripper"],
            "victory_pose": config["victory_pose"],
        })

    @app.route("/api/camera/frame.jpg")
    def camera_frame():
        frame = camera.jpeg()
        if frame is None:
            return jsonify({"error": camera.error or "camera is starting"}), 503
        return app.response_class(frame, mimetype="image/jpeg", headers={"Cache-Control": "no-store"})

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
