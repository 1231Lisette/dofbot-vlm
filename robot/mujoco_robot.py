from __future__ import annotations

import threading
import time
from itertools import pairwise
from pathlib import Path
from typing import Any, ClassVar

import mujoco
import numpy as np

from robot.interface import RobotInterface


class MuJoCoRobot(RobotInterface):
    """Dofbot simulation backend with joint, Cartesian and task-level control."""

    JOINTS = ("base", "shoulder", "elbow", "wrist_pitch", "wrist_roll")
    IK_JOINTS = ("base", "shoulder", "elbow", "wrist_pitch")
    OBJECTS = ("red_cube", "blue_cube", "green_cube")
    ARM_COLLISION_GEOMS = frozenset(
        {
            "arm_base_collision",
            "arm_link1_collision",
            "arm_link2_collision",
            "arm_link3_collision",
            "arm_link4_collision",
            "arm_link5_collision",
            "arm_link5_left_collision",
            "arm_link5_right_collision",
            "left_finger_collision",
            "right_finger_collision",
        }
    )
    FINGER_COLLISION_GEOMS = frozenset(
        {"left_finger_collision", "right_finger_collision"}
    )
    GRIPPER_COLLISION_GEOMS = FINGER_COLLISION_GEOMS | frozenset(
        {
            "arm_link5_collision",
            "arm_link5_left_collision",
            "arm_link5_right_collision",
        }
    )
    HOME = np.zeros(5, dtype=float)
    GRIPPER_TRAVEL = 0.012
    CUBE_SIZE = 0.028
    CUBE_CENTER_Z = 0.389
    GRASP_TOLERANCE = 0.025
    GRASP_HEIGHT_OFFSET = 0.016
    PATH_MIN_CLEARANCE = 0.003
    ARM_SWEEP_RADIUS = 0.012
    TABLE_TOP_Z = 0.375
    IK_POSITION_TOLERANCE = 0.012
    IK_VERTICAL_TOLERANCE = np.deg2rad(32.0)
    IK_ORIENTATION_WEIGHT = 0.08
    COLLISION_FAILURE_STEPS = 6
    COLLISION_PENETRATION_LIMIT = -0.001
    SETTLE_MIN_TIME = 0.35
    SETTLE_TIMEOUT = 2.0
    SETTLE_XY_TOLERANCE = 0.018
    SETTLE_Z_TOLERANCE = 0.009
    SETTLE_SPEED_TOLERANCE = 0.035
    SETTLE_STABLE_STEPS = 8
    RELEASE_CLEARANCE = 0.008
    SORT_TARGETS: ClassVar[dict[str, tuple[float, float]]] = {
        "red_cube": (-0.16, 0.05),
        "blue_cube": (-0.25, 0.05),
        "green_cube": (-0.45, 0.05),
    }
    STACK_TARGET = (-0.20, 0.05)

    def __init__(self, model_path: Path, control_hz: int = 100) -> None:
        self.model = mujoco.MjModel.from_xml_path(str(model_path))
        self.data = mujoco.MjData(self.model)
        self.control_hz = control_hz
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._running = False
        self._estopped = False
        self._target = self.HOME.copy()
        self._gripper_target = 0.0
        self._attached_object: str | None = None
        self._attached_yaw = 0.0
        self._collision_streak = 0
        self._task_counter = 0
        self._task_stats = {"completed": 0, "succeeded": 0, "failed": 0}
        self._task = self._idle_task()
        self._workflow_counter = 0
        self._queue: list[dict[str, Any]] = []
        self._history: list[dict[str, Any]] = []
        self._workflow = self._idle_workflow()
        self._collision_telemetry: dict[str, Any] = {
            "status": "clear",
            "active_contacts": 0,
            "robot_contacts": 0,
            "unexpected_contacts": [],
            "min_distance": None,
            "message": "未检测到异常碰撞",
            "consecutive_steps": 0,
            "latched": False,
        }

        self._joint_ids = np.array([self._id(mujoco.mjtObj.mjOBJ_JOINT, n) for n in self.JOINTS])
        self._actuator_ids = np.array(
            [self._id(mujoco.mjtObj.mjOBJ_ACTUATOR, f"{n}_motor") for n in self.JOINTS]
        )
        self._gripper_joint_ids = np.array(
            [self._id(mujoco.mjtObj.mjOBJ_JOINT, f"gripper_{side}") for side in ("left", "right")]
        )
        self._gripper_actuator_ids = np.array(
            [
                self._id(mujoco.mjtObj.mjOBJ_ACTUATOR, f"gripper_{side}_motor")
                for side in ("left", "right")
            ]
        )
        self._tool_site_id = self._id(mujoco.mjtObj.mjOBJ_SITE, "tool_center")
        self._arm_body_ids = np.array(
            [
                self._id(mujoco.mjtObj.mjOBJ_BODY, f"dofbot_link{index}")
                for index in range(1, 6)
            ]
        )
        self._object_body_ids = {
            name: self._id(mujoco.mjtObj.mjOBJ_BODY, name) for name in self.OBJECTS
        }
        self._object_joint_ids = {
            name: self._id(mujoco.mjtObj.mjOBJ_JOINT, f"{name}_joint")
            for name in self.OBJECTS
        }
        self._limits = {
            name: tuple(float(value) for value in self.model.jnt_range[joint_id])
            for name, joint_id in zip(self.JOINTS, self._joint_ids, strict=True)
        }
        self._initial_qpos = self.data.qpos.copy()
        self.reset_scene()

    def _id(self, object_type: mujoco.mjtObj, name: str) -> int:
        object_id = mujoco.mj_name2id(self.model, object_type, name)
        if object_id < 0:
            raise ValueError(f"MuJoCo model is missing {name!r}")
        return object_id

    @staticmethod
    def _idle_task() -> dict[str, Any]:
        return {
            "id": None,
            "type": "pick_and_place",
            "status": "idle",
            "stage": "IDLE",
            "progress": 0.0,
            "object": None,
            "target": None,
            "message": "等待任务",
        }

    @staticmethod
    def _idle_workflow() -> dict[str, Any]:
        return {
            "id": None,
            "mode": None,
            "status": "idle",
            "total": 0,
            "completed": 0,
            "succeeded": 0,
            "failed": 0,
            "progress": 0.0,
            "message": "等待批量任务",
        }

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="mujoco-loop", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        period = 1 / self.control_hz
        while self._running:
            started = time.perf_counter()
            with self._lock:
                self._step_once()
            remaining = period - (time.perf_counter() - started)
            if remaining > 0:
                time.sleep(remaining)

    def _step_once(self) -> None:
        """Advance one deterministic control step; also used by the test suite."""
        if self._estopped:
            return
        self._update_task()
        self.data.ctrl[self._actuator_ids] = self._target
        self.data.ctrl[self._gripper_actuator_ids] = self._gripper_target
        mujoco.mj_step(self.model, self.data)
        self._sync_attached_object()
        self._update_collision_telemetry()
        self._enforce_collision_safety()

    def step_simulation(self, steps: int = 1) -> None:
        """Advance without wall-clock waiting for tests and repeatable benchmarks."""
        if steps < 1:
            raise ValueError("steps must be positive")
        with self._lock:
            for _ in range(steps):
                self._step_once()

    def _joint_positions(self) -> np.ndarray:
        return np.array(
            [self.data.qpos[self.model.jnt_qposadr[joint_id]] for joint_id in self._joint_ids]
        )

    def _tool_position(self) -> np.ndarray:
        return self.data.site_xpos[self._tool_site_id].copy()

    def _object_position(self, name: str) -> np.ndarray:
        return self.data.xpos[self._object_body_ids[name]].copy()

    def _object_yaw(self, name: str) -> float:
        rotation = self.data.xmat[self._object_body_ids[name]].reshape(3, 3)
        return float(np.arctan2(rotation[1, 0], rotation[0, 0]))

    @staticmethod
    def _parallel_yaw_error(first: float, second: float) -> float:
        return abs((float(first) - float(second) + np.pi / 2) % np.pi - np.pi / 2)

    @staticmethod
    def _yaw_quaternion(yaw: float) -> tuple[float, float, float, float]:
        return (float(np.cos(yaw / 2)), 0.0, 0.0, float(np.sin(yaw / 2)))

    def _set_arm_target(self, targets: dict[str, float] | np.ndarray) -> None:
        values = targets if isinstance(targets, dict) else dict(zip(self.JOINTS, targets, strict=True))
        for name, raw_value in values.items():
            if name not in self.JOINTS:
                raise KeyError(f"Unknown joint: {name}")
            value = float(raw_value)
            low, high = self._limits[name]
            if not low <= value <= high:
                raise ValueError(
                    f"{name} target {value:.3f} is outside [{low:.3f}, {high:.3f}]"
                )
            self._target[self.JOINTS.index(name)] = value

    def get_state(self) -> dict[str, Any]:
        with self._lock:
            positions = self._joint_positions()
            joints = {
                name: round(float(value), 4)
                for name, value in zip(self.JOINTS, positions, strict=True)
            }
            targets = {
                name: round(float(value), 4)
                for name, value in zip(self.JOINTS, self._target, strict=True)
            }
            limits = {
                name: [round(low, 4), round(high, 4)]
                for name, (low, high) in self._limits.items()
            }
            objects = {
                name: [round(float(value), 4) for value in self._object_position(name)]
                for name in self.OBJECTS
            }
            object_orientations = {
                name: round(self._object_yaw(name), 6) for name in self.OBJECTS
            }
            gripper_positions = [
                float(
                    np.clip(
                        self.data.qpos[self.model.jnt_qposadr[joint_id]],
                        0.0,
                        self.GRIPPER_TRAVEL,
                    )
                )
                for joint_id in self._gripper_joint_ids
            ]
            gripper_opening = float(
                np.clip(1.0 - np.mean(gripper_positions) / self.GRIPPER_TRAVEL, 0.0, 1.0)
            )
            gripper_target_opening = float(
                np.clip(1.0 - self._gripper_target / self.GRIPPER_TRAVEL, 0.0, 1.0)
            )
            task_public = {
                key: self._task.get(key)
                for key in (
                    "id",
                    "type",
                    "status",
                    "stage",
                    "progress",
                    "object",
                    "target",
                    "target_z",
                    "message",
                    "workflow_id",
                    "queue_index",
                    "grasp",
                )
            }
            workflow = dict(self._workflow)
            if workflow["status"] in {"running", "paused"} and workflow["total"]:
                workflow["progress"] = round(
                    (workflow["completed"] + float(self._task.get("progress", 0.0)))
                    / workflow["total"],
                    3,
                )
            return {
                "backend": "mujoco",
                "model": "dofbot_urdf_mesh",
                "status": "estopped" if self._estopped else "running",
                "sim_time": round(float(self.data.time), 3),
                "joints": joints,
                "targets": targets,
                "limits": limits,
                "tool_position": [round(float(value), 4) for value in self._tool_position()],
                "gripper": {
                    "opening": round(gripper_opening, 3),
                    "target_opening": round(gripper_target_opening, 3),
                    "finger_positions": [round(value, 4) for value in gripper_positions],
                    "attached": self._attached_object,
                },
                "objects": objects,
                "object_orientations": object_orientations,
                "object_dimensions": {
                    name: [self.CUBE_SIZE, self.CUBE_SIZE] for name in self.OBJECTS
                },
                "target_zone": [*self.STACK_TARGET, self.CUBE_CENTER_Z],
                "collision": dict(self._collision_telemetry),
                "task": {**task_public, "stats": dict(self._task_stats)},
                "automation": {
                    "workflow": workflow,
                    "queue": [dict(item) for item in self._queue],
                    "history": [dict(item) for item in reversed(self._history[-12:])],
                    "sort_targets": {
                        name: [*target, self.CUBE_CENTER_Z]
                        for name, target in self.SORT_TARGETS.items()
                    },
                    "stack_target": [*self.STACK_TARGET, self.CUBE_CENTER_Z],
                },
            }

    def set_joint_targets(self, targets: dict[str, float]) -> None:
        with self._lock:
            if self._estopped:
                raise ValueError("Robot is emergency-stopped; resume before sending joint targets")
            if self._task["status"] == "running":
                raise ValueError("A pick-and-place task is running; cancel it before manual control")
            self._set_arm_target(targets)

    def _solve_ik(
        self,
        target_xyz: tuple[float, float, float],
        *,
        vertical: bool = False,
    ) -> dict[str, float]:
        target = np.asarray(target_xyz, dtype=float)
        if target.shape != (3,) or not np.all(np.isfinite(target)):
            raise ValueError("Tool target must contain three finite XYZ values")
        if not (-0.62 <= target[0] <= -0.09 and -0.26 <= target[1] <= 0.26):
            raise ValueError("Tool target is outside the configured Dofbot workspace")
        if not (0.36 <= target[2] <= 0.84):
            raise ValueError("Tool Z target is outside the configured Dofbot workspace")

        live_qpos = self.data.qpos.copy()
        current = self._joint_positions()
        side = -1.0 if target[1] > 0 else 1.0
        seeds = [
            current,
            self.HOME,
            np.array([0.52 * side, -1.10 * side, -0.30 * side, -0.75, 0.0]),
            np.array([0.65 * side, -1.45 * side, -0.50 * side, -0.40, 0.0]),
        ]
        if vertical:
            seeds.extend(
                np.array([0.60 * side, shoulder, elbow, wrist, 0.0])
                for shoulder, elbow, wrist in (
                    (-1.45, -0.05, -1.20),
                    (-1.30, -0.30, -1.00),
                    (-1.20, -0.50, -0.80),
                    (-1.50, 0.00, -1.40),
                    (-1.00, -0.80, -0.50),
                    (-0.70, -1.00, -0.40),
                )
            )
        ik_joint_ids = self._joint_ids[: len(self.IK_JOINTS)]
        dof_indices = np.array([self.model.jnt_dofadr[joint_id] for joint_id in ik_joint_ids])
        qpos_indices = np.array([self.model.jnt_qposadr[joint_id] for joint_id in ik_joint_ids])
        best_error = float("inf")
        best_q: np.ndarray | None = None
        best_tilt = float("inf")
        best_vertical_error = float("inf")
        best_vertical_q: np.ndarray | None = None

        for seed in seeds:
            ik_data = mujoco.MjData(self.model)
            ik_data.qpos[:] = live_qpos
            ik_data.qpos[qpos_indices] = seed[: len(self.IK_JOINTS)]
            ik_data.qpos[self.model.jnt_qposadr[self._joint_ids[-1]]] = 0.0
            for _ in range(450):
                mujoco.mj_forward(self.model, ik_data)
                error = target - ik_data.site_xpos[self._tool_site_id]
                error_norm = float(np.linalg.norm(error))
                rotation = ik_data.site_xmat[self._tool_site_id].reshape(3, 3)
                approach_axis = rotation[:, 2]
                tilt = float(np.arccos(np.clip(-approach_axis[2], -1.0, 1.0)))
                if error_norm < best_error:
                    best_error = error_norm
                    best_q = np.array(
                        [ik_data.qpos[self.model.jnt_qposadr[j]] for j in self._joint_ids]
                    )
                if (
                    vertical
                    and tilt <= self.IK_VERTICAL_TOLERANCE
                    and error_norm < best_vertical_error
                ):
                    best_vertical_error = error_norm
                    best_vertical_q = np.array(
                        [ik_data.qpos[self.model.jnt_qposadr[j]] for j in self._joint_ids]
                    )
                if error_norm <= self.IK_POSITION_TOLERANCE:
                    best_tilt = min(best_tilt, tilt)
                if error_norm < 0.003 and (not vertical or tilt < np.deg2rad(12.0)):
                    break
                jac_pos = np.zeros((3, self.model.nv))
                jac_rot = np.zeros((3, self.model.nv))
                mujoco.mj_jacSite(self.model, ik_data, jac_pos, jac_rot, self._tool_site_id)
                jacobian = jac_pos[:, dof_indices]
                objective = error
                if vertical:
                    orientation_error = np.cross(approach_axis, np.array([0.0, 0.0, -1.0]))
                    jacobian = np.vstack(
                        [jacobian, self.IK_ORIENTATION_WEIGHT * jac_rot[:, dof_indices]]
                    )
                    objective = np.concatenate(
                        [error, self.IK_ORIENTATION_WEIGHT * orientation_error]
                    )
                damping = 0.0015 * np.eye(jacobian.shape[0])
                delta = jacobian.T @ np.linalg.solve(
                    jacobian @ jacobian.T + damping,
                    objective,
                )
                delta = np.clip(delta, -0.12, 0.12)
                for index, joint_id in enumerate(ik_joint_ids):
                    low, high = self.model.jnt_range[joint_id]
                    ik_data.qpos[qpos_indices[index]] = np.clip(
                        ik_data.qpos[qpos_indices[index]] + delta[index], low, high
                    )

        if vertical:
            if (
                best_vertical_q is None
                or best_vertical_error > self.IK_POSITION_TOLERANCE
            ):
                raise ValueError(
                    "No vertical IK solution for XYZ "
                    f"{target.round(3).tolist()} (tilt {np.degrees(best_tilt):.1f} deg)"
                )
            best_q = best_vertical_q
        if best_q is None or best_error > 0.018:
            raise ValueError(
                f"No IK solution for XYZ {target.round(3).tolist()} (error {best_error:.3f} m)"
            )
        best_q[-1] = 0.0
        return {
            name: round(float(value), 6)
            for name, value in zip(self.JOINTS, best_q, strict=True)
        }

    def _solution_tilt(self, solution: dict[str, float]) -> float:
        test_data = mujoco.MjData(self.model)
        test_data.qpos[:] = self.data.qpos
        for name, joint_id in zip(self.JOINTS, self._joint_ids, strict=True):
            test_data.qpos[self.model.jnt_qposadr[joint_id]] = solution[name]
        mujoco.mj_forward(self.model, test_data)
        approach_axis = test_data.site_xmat[self._tool_site_id].reshape(3, 3)[:, 2]
        return float(np.arccos(np.clip(-approach_axis[2], -1.0, 1.0)))

    def _solution_approach_axis(self, solution: dict[str, float]) -> np.ndarray:
        test_data = mujoco.MjData(self.model)
        test_data.qpos[:] = self.data.qpos
        for name, joint_id in zip(self.JOINTS, self._joint_ids, strict=True):
            test_data.qpos[self.model.jnt_qposadr[joint_id]] = solution[name]
        mujoco.mj_forward(self.model, test_data)
        return test_data.site_xmat[self._tool_site_id].reshape(3, 3)[:, 2].copy()

    def move_tool(self, target_xyz: tuple[float, float, float]) -> dict[str, float]:
        with self._lock:
            if self._estopped:
                raise ValueError("Robot is emergency-stopped; resume before moving the tool")
            if self._task["status"] == "running":
                raise ValueError("A pick-and-place task is running; cancel it before Cartesian control")
            solution = self._solve_ik(target_xyz)
            self._set_arm_target(solution)
            return solution

    def set_gripper(self, opening: float) -> None:
        with self._lock:
            if self._estopped:
                raise ValueError("Robot is emergency-stopped; resume before moving the gripper")
            value = float(opening)
            if not 0.0 <= value <= 1.0:
                raise ValueError("Gripper opening must be between 0.0 (closed) and 1.0 (open)")
            self._gripper_target = (1.0 - value) * self.GRIPPER_TRAVEL

    def _solution_with_grasp_yaw(
        self,
        solution: dict[str, float],
        desired_yaw: float,
    ) -> tuple[dict[str, float], float, float]:
        test_data = mujoco.MjData(self.model)
        test_data.qpos[:] = self.data.qpos
        for name, joint_id in zip(self.JOINTS, self._joint_ids, strict=True):
            test_data.qpos[self.model.jnt_qposadr[joint_id]] = solution[name]
        wrist_joint_id = self._joint_ids[-1]
        wrist_qpos = self.model.jnt_qposadr[wrist_joint_id]
        low, high = self._limits["wrist_roll"]
        best_wrist = solution["wrist_roll"]
        best_yaw = 0.0
        best_error = float("inf")
        for wrist in np.linspace(low, high, 97):
            test_data.qpos[wrist_qpos] = wrist
            mujoco.mj_forward(self.model, test_data)
            rotation = test_data.site_xmat[self._tool_site_id].reshape(3, 3)
            closing_axis = rotation[:, 0]
            if np.linalg.norm(closing_axis[:2]) < 1e-6:
                continue
            actual_yaw = float(np.arctan2(closing_axis[1], closing_axis[0]))
            error = self._parallel_yaw_error(actual_yaw, desired_yaw)
            if error < best_error:
                best_error = error
                best_wrist = float(wrist)
                best_yaw = actual_yaw
        adjusted = dict(solution)
        adjusted["wrist_roll"] = round(best_wrist, 6)
        return adjusted, best_yaw, best_error

    @staticmethod
    def _point_segment_distance(point: np.ndarray, start: np.ndarray, end: np.ndarray) -> float:
        segment = end - start
        denominator = float(np.dot(segment, segment))
        if denominator < 1e-12:
            return float(np.linalg.norm(point - start))
        amount = float(np.clip(np.dot(point - start, segment) / denominator, 0.0, 1.0))
        return float(np.linalg.norm(point - (start + amount * segment)))

    def _sampled_path_clearance(
        self,
        waypoints: list[dict[str, float]],
        target_position: tuple[float, float, float],
    ) -> float:
        """Approximate swept-link clearance along a deterministic joint path."""
        test_data = mujoco.MjData(self.model)
        test_data.qpos[:] = self.data.qpos
        qpos_indices = np.array(
            [self.model.jnt_qposadr[joint_id] for joint_id in self._joint_ids]
        )
        start = self.HOME.copy()
        target_xy = np.asarray(target_position[:2], dtype=float)
        target_name = min(
            self.OBJECTS,
            key=lambda name: float(
                np.linalg.norm(self._object_position(name)[:2] - target_xy)
            ),
        )
        target_geom = f"{target_name}_geom"
        obstacles = [
            self._object_position(name)
            for name in self.OBJECTS
            if np.linalg.norm(self._object_position(name)[:2] - target_xy) > 0.035
        ]
        obstacle_radius = self.CUBE_SIZE / np.sqrt(2)
        minimum = 0.12

        for waypoint in waypoints:
            end = np.array([waypoint[name] for name in self.JOINTS], dtype=float)
            for amount in np.linspace(0.0, 1.0, 13):
                test_data.qpos[qpos_indices] = start + amount * (end - start)
                mujoco.mj_forward(self.model, test_data)
                points = [test_data.xpos[body_id].copy() for body_id in self._arm_body_ids]
                points.append(test_data.site_xpos[self._tool_site_id].copy())
                minimum = min(
                    minimum,
                    *(point[2] - self.TABLE_TOP_Z - self.ARM_SWEEP_RADIUS for point in points[:-1]),
                )
                for obstacle in obstacles:
                    for segment_start, segment_end in pairwise(points):
                        distance = self._point_segment_distance(
                            obstacle,
                            segment_start,
                            segment_end,
                        )
                        minimum = min(
                            minimum,
                            distance - obstacle_radius - self.ARM_SWEEP_RADIUS,
                        )
                for contact_index in range(test_data.ncon):
                    contact = test_data.contact[contact_index]
                    first = mujoco.mj_id2name(
                        self.model,
                        mujoco.mjtObj.mjOBJ_GEOM,
                        int(contact.geom1),
                    ) or ""
                    second = mujoco.mj_id2name(
                        self.model,
                        mujoco.mjtObj.mjOBJ_GEOM,
                        int(contact.geom2),
                    ) or ""
                    pair = {first, second}
                    touched_robot = pair & self.ARM_COLLISION_GEOMS
                    touched_gripper = touched_robot & self.GRIPPER_COLLISION_GEOMS
                    touches_forbidden = "table_surface" in pair or any(
                        f"{name}_geom" in pair
                        for name in self.OBJECTS
                        if f"{name}_geom" != target_geom
                    )
                    touches_target_with_arm = (
                        target_geom in pair and bool(touched_robot - touched_gripper)
                    )
                    if (touched_robot and touches_forbidden) or touches_target_with_arm:
                        minimum = min(minimum, float(contact.dist))
            start = end
        return float(minimum)

    def evaluate_grasp_pose(
        self, position: tuple[float, float, float], yaw: float
    ) -> dict[str, Any]:
        with self._lock:
            solution = self._solve_ik(position, vertical=True)
            solution, actual_yaw, yaw_error = self._solution_with_grasp_yaw(solution, yaw)
            pre_grasp_position = (
                position[0],
                position[1],
                min(0.58, position[2] + 0.12),
            )
            pre_grasp = self._solve_ik(pre_grasp_position)
            pre_grasp, _pre_yaw, _pre_error = self._solution_with_grasp_yaw(pre_grasp, yaw)
            path_clearance = self._sampled_path_clearance(
                [pre_grasp, solution],
                position,
            )
            margins = []
            for name, value in solution.items():
                low, high = self._limits[name]
                span = high - low
                margins.append(2 * min((value - low) / span, (high - value) / span))
            yaw_reachable = yaw_error <= np.deg2rad(18)
            vertical_tilt = self._solution_tilt(solution)
            vertical_reachable = vertical_tilt <= self.IK_VERTICAL_TOLERANCE
            collision_free = path_clearance >= self.PATH_MIN_CLEARANCE
            reachable = yaw_reachable and vertical_reachable and collision_free
            reason = None
            if not yaw_reachable:
                reason = "腕部无法对齐该抓取角度"
            elif not vertical_reachable:
                reason = f"夹爪倾角过大（{np.degrees(vertical_tilt):.1f}°）"
            elif not collision_free:
                reason = f"关节路径净空不足（{path_clearance * 1000:.1f} mm）"
            return {
                "reachable": bool(reachable),
                "reason": reason,
                "solution": solution,
                "actual_yaw": round(actual_yaw, 6),
                "yaw_error": round(float(yaw_error), 6),
                "vertical_tilt": round(vertical_tilt, 6),
                "vertical_tilt_deg": round(float(np.degrees(vertical_tilt)), 1),
                "joint_margin": round(float(np.mean(np.clip(margins, 0.0, 1.0))), 3),
                "path_clearance": round(path_clearance, 4),
                "collision_free": bool(collision_free),
            }

    def _update_collision_telemetry(self) -> None:
        contacts: list[dict[str, Any]] = []
        robot_contacts: list[dict[str, Any]] = []
        unexpected: list[dict[str, Any]] = []
        target = self._task.get("object") if self._task.get("status") == "running" else None
        min_distance: float | None = None

        for index in range(self.data.ncon):
            contact = self.data.contact[index]
            first = mujoco.mj_id2name(
                self.model,
                mujoco.mjtObj.mjOBJ_GEOM,
                int(contact.geom1),
            ) or f"geom_{int(contact.geom1)}"
            second = mujoco.mj_id2name(
                self.model,
                mujoco.mjtObj.mjOBJ_GEOM,
                int(contact.geom2),
            ) or f"geom_{int(contact.geom2)}"
            distance = float(contact.dist)
            min_distance = distance if min_distance is None else min(min_distance, distance)
            item = {
                "geoms": [first, second],
                "distance": round(distance, 5),
            }
            contacts.append(item)
            pair = {first, second}
            object_geoms = {f"{name}_geom" for name in self.OBJECTS}
            touched_objects = pair & object_geoms
            touched_robot = pair & self.ARM_COLLISION_GEOMS
            touched_gripper = touched_robot & self.GRIPPER_COLLISION_GEOMS
            touched_links = touched_robot - touched_gripper
            if touched_robot:
                robot_contacts.append(item)
            expected_target = (
                target is not None
                and f"{target}_geom" in touched_objects
                and bool(touched_gripper)
                and not touched_links
            )
            expected_stack_support = False
            if (
                self._workflow.get("mode") == "stacking"
                and (
                    self._task.get("stage")
                    in {"PLACE", "OPEN", "SETTLE", "SWING_CLEAR"}
                    or str(self._task.get("stage", "")).startswith("RETREAT_")
                )
                and bool(touched_gripper)
                and not touched_links
            ):
                target_z = float(self._task.get("target_z", self.CUBE_CENTER_Z))
                support_geom = next(
                    (
                        f"{name}_geom"
                        for name in self.OBJECTS
                        if name != target
                        and abs(
                            float(self._object_position(name)[2])
                            - (target_z - self.CUBE_SIZE)
                        )
                        <= self.SETTLE_Z_TOLERANCE
                    ),
                    None,
                )
                expected_stack_support = support_geom is not None and support_geom in pair
            object_on_table = "table_surface" in pair and bool(touched_objects)
            severe_contact = distance <= self.COLLISION_PENETRATION_LIMIT
            if (
                touched_robot
                and not expected_target
                and not expected_stack_support
                and severe_contact
            ):
                unexpected.append(item)
            elif object_on_table:
                continue

        self._collision_telemetry = {
            "status": "warning" if unexpected else "clear",
            "active_contacts": len(contacts),
            "robot_contacts": len(robot_contacts),
            "unexpected_contacts": unexpected[:6],
            "min_distance": None if min_distance is None else round(min_distance, 5),
            "message": (
                "检测到机械臂与环境异常接触" if unexpected else "未检测到异常碰撞"
            ),
            "consecutive_steps": self._collision_streak,
            "latched": self._collision_streak >= self.COLLISION_FAILURE_STEPS,
        }

    def _enforce_collision_safety(self) -> None:
        unexpected = self._collision_telemetry["unexpected_contacts"]
        if unexpected:
            self._collision_streak += 1
        else:
            self._collision_streak = 0
        self._collision_telemetry["consecutive_steps"] = self._collision_streak
        self._collision_telemetry["latched"] = (
            self._collision_streak >= self.COLLISION_FAILURE_STEPS
        )
        if (
            self._task.get("status") == "running"
            and self._collision_streak >= self.COLLISION_FAILURE_STEPS
        ):
            pair = unexpected[0]["geoms"]
            self._target[:] = self._joint_positions()
            self._finish_task(False, f"碰撞保护触发：{pair[0]} ↔ {pair[1]}")

    def _make_motion_stage(
        self,
        name: str,
        target_xyz: tuple[float, float, float],
        grasp_yaw: float | None = None,
        vertical: bool = False,
    ) -> dict[str, Any]:
        joints = self._solve_ik(target_xyz, vertical=vertical)
        if grasp_yaw is not None:
            joints, _actual_yaw, _yaw_error = self._solution_with_grasp_yaw(joints, grasp_yaw)
        return {
            "name": name,
            "kind": "motion",
            "joints": joints,
            "tool_target": target_xyz,
        }

    def start_pick_and_place(
        self,
        object_name: str,
        target_xy: tuple[float, float],
        grasp_yaw: float | None = None,
    ) -> None:
        with self._lock:
            if self._estopped:
                raise ValueError("Robot is emergency-stopped; resume before starting a task")
            if object_name not in self.OBJECTS:
                raise KeyError(f"Unknown object: {object_name}")
            if self._task["status"] in {"running", "paused"}:
                raise ValueError("Another task is already active")
            if self._workflow["status"] in {"running", "paused"}:
                raise ValueError("A batch workflow is already active")
            self._start_pick_and_place(object_name, target_xy, grasp_yaw=grasp_yaw)

    def _start_pick_and_place(
        self,
        object_name: str,
        target_xy: tuple[float, float],
        *,
        target_z: float | None = None,
        grasp_yaw: float | None = None,
        workflow_id: int | None = None,
        queue_index: int | None = None,
    ) -> None:
        target_x, target_y = (float(value) for value in target_xy)
        if not (-0.50 <= target_x <= -0.12 and -0.08 <= target_y <= 0.26):
            raise ValueError("Place target must be inside the highlighted target side of the table")

        source = self._object_position(object_name)
        selected_yaw = self._object_yaw(object_name) if grasp_yaw is None else float(grasp_yaw)
        table_z = self.CUBE_CENTER_Z
        destination_z = table_z if target_z is None else float(target_z)
        grasp = (
            float(source[0]),
            float(source[1]),
            max(table_z, float(source[2])) + self.GRASP_HEIGHT_OFFSET,
        )
        pre_grasp = (grasp[0], grasp[1], min(0.58, grasp[2] + 0.12))
        place = (target_x, target_y, destination_z + self.RELEASE_CLEARANCE)
        pre_place = (target_x, target_y, min(0.58, place[2] + 0.12))
        place_stage = self._make_motion_stage("PLACE", place, selected_yaw, vertical=True)
        approach_axis = self._solution_approach_axis(place_stage["joints"])
        retreat_distance = 0.03 if destination_z >= self.CUBE_CENTER_Z + 2 * self.CUBE_SIZE else 0.05
        retreat_distances = (
            (0.015, 0.03)
            if retreat_distance == 0.03
            else (0.02, 0.04, retreat_distance)
        )
        retreat_stages = [
            self._make_motion_stage(
                f"RETREAT_{index}",
                tuple(np.asarray(place) - distance * approach_axis),
                selected_yaw,
                vertical=True,
            )
            for index, distance in enumerate(retreat_distances, start=1)
        ]
        swing_clear_joints = dict(retreat_stages[-1]["joints"])
        swing_clear_joints["base"] = 0.0
        stages: list[dict[str, Any]] = [
            {"name": "HOME", "kind": "motion", "joints": dict(zip(self.JOINTS, self.HOME))},
            self._make_motion_stage("PRE_GRASP", pre_grasp, selected_yaw),
            self._make_motion_stage("APPROACH", grasp, selected_yaw, vertical=True),
            {"name": "CLOSE", "kind": "gripper", "opening": 0.0, "attach": object_name},
            self._make_motion_stage("LIFT", pre_grasp, selected_yaw),
            {"name": "TRANSFER", "kind": "motion", "joints": dict(zip(self.JOINTS, self.HOME))},
            self._make_motion_stage("PRE_PLACE", pre_place, selected_yaw),
            place_stage,
            {
                "name": "OPEN",
                "kind": "gripper",
                "opening": 1.0,
                "detach": True,
            },
            {
                "name": "SETTLE",
                "kind": "settle",
                "object": object_name,
                "target": [target_x, target_y, destination_z],
            },
            *retreat_stages,
            {"name": "CLOSE_CLEAR", "kind": "gripper", "opening": 0.0},
            {"name": "SWING_CLEAR", "kind": "motion", "joints": swing_clear_joints},
            {"name": "RETURN", "kind": "motion", "joints": dict(zip(self.JOINTS, self.HOME))},
            {
                "name": "VERIFY_PLACE",
                "kind": "settle",
                "object": object_name,
                "target": [target_x, target_y, destination_z],
            },
        ]
        self._task_counter += 1
        self._task = {
            "id": self._task_counter,
            "type": "pick_and_place",
            "status": "running",
            "stage": "HOME",
            "progress": 0.0,
            "object": object_name,
            "target": [target_x, target_y],
            "target_z": destination_z,
            "message": "任务已开始",
            "workflow_id": workflow_id,
            "queue_index": queue_index,
            "grasp": {
                "yaw": round(selected_yaw, 6),
                "yaw_deg": round(float(np.degrees(selected_yaw)), 1),
            },
            "stages": stages,
            "stage_index": 0,
            "entered": False,
            "stage_started": float(self.data.time),
            "task_started": float(self.data.time),
            "settle_streak": 0,
        }

    def start_sorting(self) -> None:
        jobs = [
            {
                "object": name,
                "target": list(self.SORT_TARGETS[name]),
                "target_z": self.CUBE_CENTER_Z,
                "label": f"{name} → 颜色区",
            }
            for name in self.OBJECTS
        ]
        self._start_workflow("sorting", jobs)

    def start_stacking(self) -> None:
        jobs = [
            {
                "object": name,
                "target": list(self.STACK_TARGET),
                "target_z": self.CUBE_CENTER_Z + index * self.CUBE_SIZE,
                "level": index + 1,
                "label": f"{name} → 第 {index + 1} 层",
            }
            for index, name in enumerate(self.OBJECTS)
        ]
        self._start_workflow("stacking", jobs)

    def _start_workflow(self, mode: str, jobs: list[dict[str, Any]]) -> None:
        with self._lock:
            if self._estopped:
                raise ValueError("Robot is emergency-stopped; resume before starting a workflow")
            if self._task["status"] in {"running", "paused"}:
                raise ValueError("Another task is already active")
            if self._workflow["status"] in {"running", "paused"}:
                raise ValueError("Another batch workflow is already active")
            self._workflow_counter += 1
            workflow_id = self._workflow_counter
            self._queue = [
                {**job, "workflow_id": workflow_id, "queue_index": index, "status": "queued"}
                for index, job in enumerate(jobs, start=1)
            ]
            self._workflow = {
                "id": workflow_id,
                "mode": mode,
                "status": "running",
                "total": len(jobs),
                "completed": 0,
                "succeeded": 0,
                "failed": 0,
                "progress": 0.0,
                "message": "分拣任务已开始" if mode == "sorting" else "堆垛任务已开始",
            }
            self._start_next_queued_task()

    def _start_next_queued_task(self) -> None:
        if not self._queue:
            self._workflow["status"] = "completed"
            self._workflow["progress"] = 1.0
            self._workflow["message"] = "批量任务完成"
            return
        job = self._queue.pop(0)
        self._start_pick_and_place(
            job["object"],
            tuple(job["target"]),
            target_z=job["target_z"],
            workflow_id=job["workflow_id"],
            queue_index=job["queue_index"],
        )
        self._workflow["message"] = f"正在执行 {job['label']}"

    def _update_task(self) -> None:
        if self._task["status"] != "running":
            return
        stages = self._task["stages"]
        index = self._task["stage_index"]
        if index >= len(stages):
            self._finish_task(True, "抓取放置完成")
            return
        stage = stages[index]
        self._task["stage"] = stage["name"]
        self._task["progress"] = round(index / len(stages), 3)

        if not self._task["entered"]:
            self._task["entered"] = True
            self._task["stage_started"] = float(self.data.time)
            self._task["message"] = f"正在执行 {stage['name']}"
            if stage["kind"] == "motion":
                self._set_arm_target(stage["joints"])
            elif stage["kind"] == "gripper":
                self._gripper_target = (1.0 - stage["opening"]) * self.GRIPPER_TRAVEL
            elif stage["kind"] == "settle":
                self._task["settle_streak"] = 0

        elapsed = float(self.data.time) - self._task["stage_started"]
        if stage["kind"] == "motion":
            joint_error = float(np.max(np.abs(self._joint_positions() - self._target)))
            tool_error = float("inf")
            if "tool_target" in stage:
                tool_error = float(
                    np.linalg.norm(self._tool_position() - np.asarray(stage["tool_target"]))
                )
            tool_tolerance = 0.012 if stage["name"] == "APPROACH" else 0.035
            if stage["name"] == "PLACE" or stage["name"].startswith("RETREAT_"):
                tool_tolerance = (
                    self.IK_POSITION_TOLERANCE
                    if stage["name"].startswith("RETREAT_")
                    else 0.008
                )
            arrived = (
                tool_error < tool_tolerance
                if "tool_target" in stage
                else joint_error < 0.055
            )
            if arrived:
                self._advance_task()
            elif elapsed > 6.0:
                self._finish_task(False, f"{stage['name']} 动作超时")
        elif elapsed >= 0.35:
            if stage["kind"] == "gripper":
                if "attach" in stage and not self._attach_object(stage["attach"]):
                    self._finish_task(False, "夹爪未靠近目标，抓取失败")
                    return
                if stage.get("detach"):
                    self._detach_object()
                self._advance_task()
            elif stage["kind"] == "settle":
                stable, details = self._placement_is_stable(
                    stage["object"],
                    np.asarray(stage["target"], dtype=float),
                )
                self._task["settle_streak"] = (
                    self._task.get("settle_streak", 0) + 1 if stable else 0
                )
                self._task["message"] = details
                if self._task["settle_streak"] >= self.SETTLE_STABLE_STEPS:
                    self._advance_task()
                elif elapsed > self.SETTLE_TIMEOUT:
                    self._finish_task(False, f"物理放置未稳定：{details}")

    def _advance_task(self) -> None:
        self._task["stage_index"] += 1
        self._task["entered"] = False
        if self._task["stage_index"] >= len(self._task["stages"]):
            self._finish_task(True, "抓取放置完成")

    def _attach_object(self, name: str) -> bool:
        distance = float(np.linalg.norm(self._tool_position() - self._object_position(name)))
        if distance > self.GRASP_TOLERANCE:
            return False
        self._attached_object = name
        self._attached_yaw = float(self._task.get("grasp", {}).get("yaw", 0.0))
        self._sync_attached_object()
        return True

    def _sync_attached_object(self) -> None:
        if self._attached_object is None:
            return
        joint_id = self._object_joint_ids[self._attached_object]
        qpos_address = self.model.jnt_qposadr[joint_id]
        dof_address = self.model.jnt_dofadr[joint_id]
        self.data.qpos[qpos_address : qpos_address + 3] = self._tool_position()
        self.data.qpos[qpos_address + 3 : qpos_address + 7] = self._yaw_quaternion(
            self._attached_yaw
        )
        self.data.qvel[dof_address : dof_address + 6] = 0.0
        mujoco.mj_forward(self.model, self.data)

    def _detach_object(self) -> None:
        if self._attached_object is None:
            return
        joint_id = self._object_joint_ids[self._attached_object]
        dof_address = self.model.jnt_dofadr[joint_id]
        self.data.qvel[dof_address : dof_address + 6] = 0.0
        self._attached_object = None
        self._attached_yaw = 0.0
        mujoco.mj_forward(self.model, self.data)

    def _placement_is_stable(
        self,
        object_name: str,
        target: np.ndarray,
    ) -> tuple[bool, str]:
        position = self._object_position(object_name)
        joint_id = self._object_joint_ids[object_name]
        dof_address = self.model.jnt_dofadr[joint_id]
        speed = float(np.linalg.norm(self.data.qvel[dof_address : dof_address + 3]))
        xy_error = float(np.linalg.norm(position[:2] - target[:2]))
        z_error = abs(float(position[2] - target[2]))
        geom_name = f"{object_name}_geom"
        support_names = {"table_surface"}
        if target[2] > self.CUBE_CENTER_Z + self.CUBE_SIZE / 2:
            support_names = {
                f"{name}_geom"
                for name in self.OBJECTS
                if name != object_name
                and abs(float(self._object_position(name)[2]) - (target[2] - self.CUBE_SIZE))
                <= self.SETTLE_Z_TOLERANCE
            }
        supported = False
        for index in range(self.data.ncon):
            contact = self.data.contact[index]
            pair = {
                mujoco.mj_id2name(
                    self.model, mujoco.mjtObj.mjOBJ_GEOM, int(contact.geom1)
                ),
                mujoco.mj_id2name(
                    self.model, mujoco.mjtObj.mjOBJ_GEOM, int(contact.geom2)
                ),
            }
            if geom_name in pair and bool(pair & support_names):
                supported = True
                break
        stable = (
            xy_error <= self.SETTLE_XY_TOLERANCE
            and z_error <= self.SETTLE_Z_TOLERANCE
            and speed <= self.SETTLE_SPEED_TOLERANCE
            and supported
        )
        return (
            stable,
            (
                "等待物理稳定 · "
                f"XY {xy_error * 1000:.1f} mm · Z {z_error * 1000:.1f} mm · "
                f"速度 {speed * 1000:.1f} mm/s · 支撑 {'OK' if supported else 'NO'}"
            ),
        )

    def _finish_task(self, succeeded: bool, message: str) -> None:
        self._task["status"] = "completed" if succeeded else "failed"
        self._task["stage"] = "DONE" if succeeded else "FAILED"
        self._task["progress"] = 1.0
        self._task["message"] = message
        self._task_stats["completed"] += 1
        self._task_stats["succeeded" if succeeded else "failed"] += 1
        result = {
            "id": self._task["id"],
            "workflow_id": self._task.get("workflow_id"),
            "queue_index": self._task.get("queue_index"),
            "object": self._task["object"],
            "target": list(self._task["target"]),
            "status": self._task["status"],
            "duration": round(float(self.data.time) - self._task["task_started"], 3),
            "message": message,
        }
        self._history.append(result)
        if not succeeded:
            self._detach_object()
            self._gripper_target = 0.0
        if self._workflow["status"] == "running" and (
            self._task.get("workflow_id") == self._workflow["id"]
        ):
            self._workflow["completed"] += 1
            self._workflow["succeeded" if succeeded else "failed"] += 1
            self._workflow["progress"] = round(
                self._workflow["completed"] / self._workflow["total"], 3
            )
            if succeeded:
                self._start_next_queued_task()
            else:
                self._queue.clear()
                self._workflow["status"] = "failed"
                self._workflow["message"] = f"批量任务已停止：{message}"

    def cancel_task(self) -> None:
        with self._lock:
            if self._task["status"] not in {"running", "paused"}:
                return
            self._detach_object()
            self._gripper_target = 0.0
            self._task["status"] = "cancelled"
            self._task["stage"] = "CANCELLED"
            self._task["message"] = "任务已取消"
            self._set_arm_target(self.HOME)
            if self._workflow["status"] in {"running", "paused"}:
                self._queue.clear()
                self._workflow["status"] = "cancelled"
                self._workflow["message"] = "批量任务已取消"

    def reset_scene(self) -> None:
        with self._lock:
            mujoco.mj_resetData(self.model, self.data)
            self.data.qpos[:] = self._initial_qpos
            self._target[:] = self.HOME
            self._gripper_target = 0.0
            self._attached_object = None
            self._attached_yaw = 0.0
            self._collision_streak = 0
            self._estopped = False
            self._task = self._idle_task()
            self._queue.clear()
            self._workflow = self._idle_workflow()
            self._collision_telemetry = {
                "status": "clear",
                "active_contacts": 0,
                "robot_contacts": 0,
                "unexpected_contacts": [],
                "min_distance": None,
                "message": "未检测到异常碰撞",
                "consecutive_steps": 0,
                "latched": False,
            }
            self.data.ctrl[self._actuator_ids] = self._target
            self.data.ctrl[self._gripper_actuator_ids] = self._gripper_target
            mujoco.mj_forward(self.model, self.data)

    def home(self) -> None:
        with self._lock:
            if self._task["status"] in {"running", "paused"}:
                self.cancel_task()
            self._estopped = False
            self._set_arm_target(self.HOME)
            self._gripper_target = 0.0

    def emergency_stop(self) -> None:
        with self._lock:
            self._estopped = True
            self._target[:] = self._joint_positions()
            if self._task["status"] == "running":
                self._task["status"] = "paused"
                self._task["message"] = "急停：任务已暂停"
            if self._workflow["status"] == "running":
                self._workflow["status"] = "paused"
                self._workflow["message"] = "急停：批量任务已暂停"

    def resume(self) -> None:
        with self._lock:
            self._estopped = False
            if self._task["status"] == "paused":
                self._task["status"] = "running"
                self._task["entered"] = False
                self._task["message"] = "任务继续"
            if self._workflow["status"] == "paused":
                self._workflow["status"] = "running"
                self._workflow["message"] = "批量任务继续"
