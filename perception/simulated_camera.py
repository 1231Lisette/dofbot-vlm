from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, ClassVar


@dataclass(frozen=True)
class CameraCalibration:
    width: int = 640
    height: int = 480
    x_min: float = -0.65
    x_max: float = 0.65
    y_min: float = -0.45
    y_max: float = 0.45

    def world_to_pixel(self, x: float, y: float) -> tuple[float, float]:
        u = (x - self.x_min) / (self.x_max - self.x_min) * self.width
        v = (self.y_max - y) / (self.y_max - self.y_min) * self.height
        return u, v

    def pixel_to_world(self, u: float, v: float) -> tuple[float, float]:
        x = self.x_min + u / self.width * (self.x_max - self.x_min)
        y = self.y_max - v / self.height * (self.y_max - self.y_min)
        return x, y

    @property
    def homography(self) -> list[list[float]]:
        sx = self.width / (self.x_max - self.x_min)
        sy = -self.height / (self.y_max - self.y_min)
        return [
            [round(sx, 6), 0.0, round(-self.x_min * sx, 6)],
            [0.0, round(sy, 6), round(-self.y_max * sy, 6)],
            [0.0, 0.0, 1.0],
        ]


class SimulatedCamera:
    """Top-down calibrated camera using simulator object poses as detections."""

    LABELS: ClassVar[dict[str, tuple[str, str]]] = {
        "red_cube": ("红色方块", "#ef5264"),
        "blue_cube": ("蓝色方块", "#4188ef"),
        "green_cube": ("绿色方块", "#3ed88c"),
    }
    CUBE_SIZE_METERS = 0.028

    def __init__(self, calibration: CameraCalibration | None = None) -> None:
        self.calibration = calibration or CameraCalibration()

    def pixel_to_world(self, u: float, v: float) -> dict[str, float]:
        if not (0 <= u <= self.calibration.width and 0 <= v <= self.calibration.height):
            raise ValueError("Pixel coordinate is outside the simulated camera frame")
        x, y = self.calibration.pixel_to_world(u, v)
        return {"x": round(x, 6), "y": round(y, 6)}

    def detections(self, robot_state: dict[str, Any]) -> list[dict[str, Any]]:
        output = []
        for object_name, position in robot_state.get("objects", {}).items():
            if object_name not in self.LABELS:
                continue
            x, y, z = position
            u, v = self.calibration.world_to_pixel(x, y)
            label, color = self.LABELS[object_name]
            yaw = float(robot_state.get("object_orientations", {}).get(object_name, 0.0))
            dimensions = robot_state.get("object_dimensions", {}).get(
                object_name, [self.CUBE_SIZE_METERS, self.CUBE_SIZE_METERS]
            )
            length, width = (float(value) for value in dimensions)
            cosine, sine = math.cos(yaw), math.sin(yaw)
            polygon_world = []
            for local_x, local_y in (
                (-length / 2, -width / 2),
                (length / 2, -width / 2),
                (length / 2, width / 2),
                (-length / 2, width / 2),
            ):
                polygon_world.append(
                    (
                        x + local_x * cosine - local_y * sine,
                        y + local_x * sine + local_y * cosine,
                    )
                )
            polygon = [self.calibration.world_to_pixel(px, py) for px, py in polygon_world]
            pixel_x = [point[0] for point in polygon]
            pixel_y = [point[1] for point in polygon]
            output.append(
                {
                    "object_name": object_name,
                    "label": label,
                    "confidence": 0.99,
                    "color": color,
                    "bbox": [
                        round(min(pixel_x), 2),
                        round(min(pixel_y), 2),
                        round(max(pixel_x), 2),
                        round(max(pixel_y), 2),
                    ],
                    "polygon": [[round(px, 2), round(py, 2)] for px, py in polygon],
                    "pixel_center": [round(u, 2), round(v, 2)],
                    "world_center": [round(x, 4), round(y, 4), round(z, 4)],
                    "orientation_yaw": round(yaw, 6),
                    "orientation_deg": round(math.degrees(yaw), 1),
                    "dimensions": [round(length, 4), round(width, 4)],
                }
            )
        return output

    def snapshot(self, robot_state: dict[str, Any]) -> dict[str, Any]:
        calibration = self.calibration
        return {
            "source": "simulated_ground_truth",
            "frame": {"width": calibration.width, "height": calibration.height},
            "world_bounds": {
                "x": [calibration.x_min, calibration.x_max],
                "y": [calibration.y_min, calibration.y_max],
            },
            "homography_world_to_pixel": calibration.homography,
            "detections": self.detections(robot_state),
        }
