from __future__ import annotations

from pathlib import Path

from robot.interface import RobotInterface


def create_robot(config: dict, project_root: Path) -> RobotInterface:
    backend = config["robot"].get("backend", "mujoco")
    if backend == "mujoco":
        from robot.mujoco_robot import MuJoCoRobot

        model_path = project_root / config["simulation"]["model_path"]
        return MuJoCoRobot(model_path, control_hz=int(config["robot"].get("control_hz", 100)))
    if backend == "dofbot":
        from robot.dofbot_robot import DofbotRobot

        return DofbotRobot()
    raise ValueError(f"Unsupported robot backend: {backend}")
