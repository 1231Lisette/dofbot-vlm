from __future__ import annotations

import math
from typing import Any


class ClosedLoopSupervisor:
    """Verify planned pick-and-place tasks from camera-style detections."""

    PLACEMENT_TOLERANCE = 0.035

    def __init__(self, max_retries: int = 1) -> None:
        self.max_retries = max_retries
        self._sequence = 0
        self._tracked: dict[str, Any] | None = None
        self._metrics = {
            "commands": 0,
            "attempts": 0,
            "prechecks": 0,
            "verified": 0,
            "failed": 0,
            "retries": 0,
            "verification_samples": 0,
            "total_error_m": 0.0,
            "failure_reasons": {},
        }

    def begin(
        self,
        object_name: str,
        target_xy: tuple[float, float],
        observed_position: list[float] | tuple[float, ...],
    ) -> None:
        self._sequence += 1
        self._metrics["commands"] += 1
        self._metrics["prechecks"] += 1
        self._tracked = {
            "id": self._sequence,
            "task_id": None,
            "object": object_name,
            "target": [float(target_xy[0]), float(target_xy[1])],
            "precheck_position": [float(value) for value in observed_position[:3]],
            "status": "prechecked",
            "attempt": 0,
            "retries_used": 0,
            "retry_requested": False,
            "resolved": False,
            "position_error": None,
            "reason": None,
            "message": "抓取前视觉复检完成，已使用最新坐标重新规划",
        }

    def bind_task(self, task_id: int, *, retry: bool = False) -> None:
        if self._tracked is None:
            return
        self._tracked["task_id"] = int(task_id)
        self._tracked["attempt"] += 1
        self._tracked["retry_requested"] = False
        self._tracked["resolved"] = False
        self._tracked["status"] = "retrying" if retry else "executing"
        self._tracked["message"] = (
            "已根据最新视觉坐标启动第 2 次尝试"
            if retry
            else "抓取前复检通过，正在执行"
        )
        self._metrics["attempts"] += 1
        if retry:
            self._tracked["retries_used"] += 1
            self._metrics["retries"] += 1

    def retry_start_failed(self, reason: str) -> None:
        if self._tracked is None:
            return
        reasons = self._metrics["failure_reasons"]
        reasons["retry_unavailable"] = reasons.get("retry_unavailable", 0) + 1
        self._finish_failed("retry_unavailable", f"自动重试无法启动：{reason}")

    def clear_current(self, message: str = "视觉闭环已重置") -> None:
        if self._tracked is None:
            return
        self._tracked["status"] = "reset"
        self._tracked["resolved"] = True
        self._tracked["message"] = message

    def observe(
        self,
        robot_state: dict[str, Any],
        detections: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        tracked = self._tracked
        if tracked is None or tracked["resolved"] or tracked["task_id"] is None:
            return None
        task = robot_state.get("task", {})
        if task.get("id") != tracked["task_id"]:
            return None

        task_status = task.get("status")
        if task_status == "running":
            tracked["status"] = "executing"
            tracked["message"] = f"正在执行第 {tracked['attempt']} 次尝试 · {task.get('stage')}"
            return None
        if task_status == "paused":
            tracked["status"] = "paused"
            tracked["message"] = "任务已暂停，视觉监督器不会自动恢复"
            return None
        if task_status == "cancelled":
            tracked["status"] = "cancelled"
            tracked["resolved"] = True
            tracked["message"] = "任务已由用户取消，不进行自动重试"
            return None
        if task_status == "failed":
            reason = self._execution_reason(str(task.get("message", "执行失败")))
            return self._request_retry_or_fail(reason, str(task.get("message", "执行失败")))
        if task_status != "completed":
            return None

        tracked["status"] = "verifying"
        tracked["message"] = "动作完成，正在通过顶视视觉确认放置结果"
        detection = next(
            (
                item
                for item in detections
                if item.get("object_name") == tracked["object"]
            ),
            None,
        )
        if detection is None:
            return self._request_retry_or_fail("target_lost", "验证画面中未找到目标")

        observed = detection.get("world_center", ())
        if len(observed) < 2:
            return self._request_retry_or_fail("invalid_detection", "视觉坐标不完整")
        error = math.dist(
            (float(observed[0]), float(observed[1])),
            tuple(tracked["target"]),
        )
        tracked["position_error"] = round(error, 5)
        self._metrics["verification_samples"] += 1
        self._metrics["total_error_m"] += error
        if error <= self.PLACEMENT_TOLERANCE:
            tracked["status"] = "verified"
            tracked["resolved"] = True
            tracked["reason"] = None
            tracked["message"] = f"视觉验证通过，放置误差 {error * 1000:.1f} mm"
            self._metrics["verified"] += 1
            return None
        return self._request_retry_or_fail(
            "placement_error",
            f"放置偏差 {error * 1000:.1f} mm，超过 {self.PLACEMENT_TOLERANCE * 1000:.0f} mm",
        )

    def _request_retry_or_fail(self, reason: str, message: str) -> dict[str, Any] | None:
        assert self._tracked is not None
        if self._tracked["retries_used"] < self.max_retries:
            if self._tracked["retry_requested"]:
                return None
            reasons = self._metrics["failure_reasons"]
            reasons[reason] = reasons.get(reason, 0) + 1
            self._tracked["reason"] = reason
            self._tracked["status"] = "retry_pending"
            self._tracked["retry_requested"] = True
            self._tracked["message"] = f"{message}；准备自动重试"
            return {
                "type": "retry",
                "object_name": self._tracked["object"],
                "target_xy": tuple(self._tracked["target"]),
                "reason": reason,
            }
        reasons = self._metrics["failure_reasons"]
        reasons[reason] = reasons.get(reason, 0) + 1
        self._tracked["reason"] = reason
        self._finish_failed(reason, f"{message}；已达到最大重试次数")
        return None

    def _finish_failed(self, reason: str, message: str) -> None:
        assert self._tracked is not None
        self._tracked["status"] = "failed"
        self._tracked["resolved"] = True
        self._tracked["reason"] = reason
        self._tracked["message"] = message
        self._metrics["failed"] += 1

    @staticmethod
    def _execution_reason(message: str) -> str:
        if "超时" in message:
            return "motion_timeout"
        if "夹爪" in message or "抓取失败" in message:
            return "grasp_miss"
        if "碰撞" in message:
            return "collision"
        return "execution_failed"

    def snapshot(self) -> dict[str, Any]:
        metrics = dict(self._metrics)
        samples = int(metrics.pop("verification_samples"))
        total_error = float(metrics.pop("total_error_m"))
        finished = int(metrics["verified"]) + int(metrics["failed"])
        metrics["success_rate"] = round(metrics["verified"] / finished, 3) if finished else None
        metrics["average_error_mm"] = (
            round(total_error / samples * 1000, 2) if samples else None
        )
        metrics["failure_reasons"] = dict(metrics["failure_reasons"])
        current = dict(self._tracked) if self._tracked is not None else None
        if current is not None:
            current["max_attempts"] = self.max_retries + 1
        return {
            "enabled": True,
            "source": "simulated_camera",
            "max_retries": self.max_retries,
            "tolerance_mm": round(self.PLACEMENT_TOLERANCE * 1000, 1),
            "current": current,
            "metrics": metrics,
        }
