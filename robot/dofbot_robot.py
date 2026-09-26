from __future__ import annotations

from typing import Any

from robot.interface import RobotInterface


class DofbotRobot(RobotInterface):
    """Future Jetson/Dofbot adapter with the same contract as MuJoCoRobot."""

    def _pending(self) -> None:
        raise RuntimeError("Dofbot backend is reserved for Milestone 7 and is not configured yet")

    def start(self) -> None:
        self._pending()

    def stop(self) -> None:
        self._pending()

    def get_state(self) -> dict[str, Any]:
        self._pending()

    def set_joint_targets(self, targets: dict[str, float]) -> None:
        self._pending()

    def move_tool(self, target_xyz: tuple[float, float, float]) -> dict[str, float]:
        self._pending()

    def set_gripper(self, opening: float) -> None:
        self._pending()

    def evaluate_grasp_pose(
        self, position: tuple[float, float, float], yaw: float
    ) -> dict[str, Any]:
        self._pending()

    def start_pick_and_place(
        self,
        object_name: str,
        target_xy: tuple[float, float],
        grasp_yaw: float | None = None,
    ) -> None:
        self._pending()

    def start_sorting(self) -> None:
        self._pending()

    def start_stacking(self) -> None:
        self._pending()

    def cancel_task(self) -> None:
        self._pending()

    def reset_scene(self) -> None:
        self._pending()

    def home(self) -> None:
        self._pending()

    def emergency_stop(self) -> None:
        self._pending()

    def resume(self) -> None:
        self._pending()
