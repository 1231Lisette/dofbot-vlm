from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any, ClassVar

GraspEvaluator = Callable[[tuple[float, float, float], float], dict[str, Any]]


def normalize_parallel_yaw(angle: float) -> float:
    """Normalize a parallel-gripper angle to [-pi/2, pi/2)."""
    return (float(angle) + math.pi / 2) % math.pi - math.pi / 2


class RGBPlanarGraspPlanner:
    """Generate and score top-down planar grasps from RGB-style detections."""

    MAX_GRIPPER_WIDTH = 0.041
    FINGER_CLEARANCE = 0.002
    MIN_COLLISION_MARGIN = 0.006
    GRIPPER_SIDE_PADDING = 0.007
    FINGER_REACH = 0.045
    GRASP_HEIGHT_OFFSET = 0.016
    LABELS: ClassVar[tuple[str, ...]] = ("轮廓主轴", "轮廓副轴", "世界 X", "世界 Y")

    def plan_scene(
        self,
        detections: list[dict[str, Any]],
        evaluator: GraspEvaluator,
    ) -> dict[str, dict[str, Any]]:
        return {
            detection["object_name"]: self.plan(detection, detections, evaluator)
            for detection in detections
        }

    def plan(
        self,
        detection: dict[str, Any],
        scene_detections: list[dict[str, Any]],
        evaluator: GraspEvaluator,
    ) -> dict[str, Any]:
        world_center = tuple(float(value) for value in detection["world_center"])
        center = (
            world_center[0],
            world_center[1],
            world_center[2] + self.GRASP_HEIGHT_OFFSET,
        )
        object_yaw = float(detection.get("orientation_yaw", 0.0))
        length, width = (float(value) for value in detection.get("dimensions", (0.028, 0.028)))
        raw_yaws = (object_yaw, object_yaw + math.pi / 2, 0.0, math.pi / 2)
        candidates: list[dict[str, Any]] = []
        used: list[float] = []

        for index, (label, raw_yaw) in enumerate(zip(self.LABELS, raw_yaws, strict=True), start=1):
            yaw = normalize_parallel_yaw(raw_yaw)
            if any(abs(normalize_parallel_yaw(yaw - previous)) < math.radians(2) for previous in used):
                continue
            used.append(yaw)
            delta = normalize_parallel_yaw(yaw - object_yaw)
            required_width = (
                abs(math.cos(delta)) * length + abs(math.sin(delta)) * width
                + self.FINGER_CLEARANCE
            )
            alignment = max(abs(math.cos(2 * delta)), 0.0)
            collision_margin = self._collision_margin(
                detection,
                scene_detections,
                yaw,
                required_width,
            )
            reasons: list[str] = []
            evaluation: dict[str, Any] = {}

            if required_width > self.MAX_GRIPPER_WIDTH:
                reasons.append("夹爪开度不足")
            if collision_margin < self.MIN_COLLISION_MARGIN:
                reasons.append(f"夹指净空不足（{collision_margin * 1000:.1f} mm）")
            try:
                evaluation = evaluator(center, yaw)
                if not evaluation.get("reachable", False):
                    reasons.append(str(evaluation.get("reason", "IK 无解")))
            except (KeyError, ValueError) as exc:
                reasons.append(str(exc))

            joint_margin = float(evaluation.get("joint_margin", 0.0))
            yaw_error = float(evaluation.get("yaw_error", math.pi / 2))
            yaw_quality = max(0.0, 1.0 - yaw_error / math.radians(25))
            path_clearance = float(evaluation.get("path_clearance", 0.0))
            clearance_quality = min(max(collision_margin / 0.05, 0.0), 1.0)
            path_quality = min(max(path_clearance / 0.04, 0.0), 1.0)
            width_quality = min(max((self.MAX_GRIPPER_WIDTH - required_width) / 0.015, 0.0), 1.0)
            score = (
                0.25 * alignment
                + 0.20 * joint_margin
                + 0.15 * yaw_quality
                + 0.20 * clearance_quality
                + 0.10 * path_quality
                + 0.10 * width_quality
            )
            if reasons:
                score = 0.0
            candidates.append(
                {
                    "id": f"G{index}",
                    "label": label,
                    "position": [round(value, 4) for value in center],
                    "yaw": round(yaw, 6),
                    "yaw_deg": round(math.degrees(yaw), 1),
                    "width": round(required_width, 4),
                    "score": round(score, 3),
                    "status": "rejected" if reasons else "valid",
                    "reasons": reasons,
                    "components": {
                        "alignment": round(alignment, 3),
                        "joint_margin": round(joint_margin, 3),
                        "yaw_quality": round(yaw_quality, 3),
                        "clearance": round(clearance_quality, 3),
                        "collision_margin": round(collision_margin, 4),
                        "path_clearance": round(path_clearance, 4),
                        "width_margin": round(width_quality, 3),
                    },
                    "solution": evaluation.get("solution"),
                }
            )

        valid = [candidate for candidate in candidates if candidate["status"] == "valid"]
        selected = max(valid, key=lambda item: item["score"], default=None)
        if selected is not None:
            selected["status"] = "selected"
        return {
            "object_name": detection["object_name"],
            "planner": "rgb_planar",
            "selected_id": selected["id"] if selected else None,
            "selected": selected,
            "candidates": candidates,
            "message": "已选择最高评分顶部抓取" if selected else "没有安全可达的抓取候选",
        }

    def _collision_margin(
        self,
        target: dict[str, Any],
        scene_detections: list[dict[str, Any]],
        yaw: float,
        required_width: float,
    ) -> float:
        """Signed clearance around a yaw-aligned top-grasp footprint.

        Other objects are approximated by bounding circles while the open gripper is
        represented by an oriented rectangle. Unlike center distance, this catches a
        finger corridor that is safe at one yaw but blocked after a 90-degree turn.
        """
        tx, ty, *_ = target["world_center"]
        half_closing = required_width / 2 + self.GRIPPER_SIDE_PADDING
        half_reach = self.FINGER_REACH
        cos_yaw = math.cos(yaw)
        sin_yaw = math.sin(yaw)
        margins = []
        for other in scene_detections:
            if other["object_name"] == target["object_name"]:
                continue
            ox, oy, *_ = other["world_center"]
            dx = float(ox) - float(tx)
            dy = float(oy) - float(ty)
            local_closing = abs(dx * cos_yaw + dy * sin_yaw)
            local_reach = abs(-dx * sin_yaw + dy * cos_yaw)
            outside_closing = max(local_closing - half_closing, 0.0)
            outside_reach = max(local_reach - half_reach, 0.0)
            inside = min(
                max(local_closing - half_closing, local_reach - half_reach),
                0.0,
            )
            rectangle_distance = math.hypot(outside_closing, outside_reach) + inside
            other_length, other_width = (
                float(value) for value in other.get("dimensions", (0.028, 0.028))
            )
            obstacle_radius = math.hypot(other_length, other_width) / 2
            margins.append(rectangle_distance - obstacle_radius)
        return min(margins, default=0.12)
