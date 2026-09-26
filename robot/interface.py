from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class RobotInterface(ABC):
    """Stable boundary shared by simulation and the future physical robot."""

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def get_state(self) -> dict[str, Any]: ...

    @abstractmethod
    def set_joint_targets(self, targets: dict[str, float]) -> None: ...

    @abstractmethod
    def move_tool(self, target_xyz: tuple[float, float, float]) -> dict[str, float]: ...

    @abstractmethod
    def set_gripper(self, opening: float) -> None: ...

    @abstractmethod
    def evaluate_grasp_pose(
        self, position: tuple[float, float, float], yaw: float
    ) -> dict[str, Any]: ...

    @abstractmethod
    def start_pick_and_place(
        self,
        object_name: str,
        target_xy: tuple[float, float],
        grasp_yaw: float | None = None,
    ) -> None: ...

    @abstractmethod
    def start_sorting(self) -> None: ...

    @abstractmethod
    def start_stacking(self) -> None: ...

    @abstractmethod
    def cancel_task(self) -> None: ...

    @abstractmethod
    def reset_scene(self) -> None: ...

    @abstractmethod
    def home(self) -> None: ...

    @abstractmethod
    def emergency_stop(self) -> None: ...

    @abstractmethod
    def resume(self) -> None: ...
