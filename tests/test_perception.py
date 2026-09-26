import pytest

from perception.simulated_camera import CameraCalibration, SimulatedCamera


def test_calibration_round_trip():
    calibration = CameraCalibration()
    for world in [(-0.2, -0.16), (-0.36, -0.18), (-0.2, 0.16), (0.0, 0.0)]:
        pixel = calibration.world_to_pixel(*world)
        assert calibration.pixel_to_world(*pixel) == pytest.approx(world)


def test_simulated_camera_detects_three_cubes():
    camera = SimulatedCamera()
    state = {
        "objects": {
            "red_cube": [-0.2, -0.16, 0.389],
            "blue_cube": [-0.28, -0.11, 0.389],
            "green_cube": [-0.36, -0.18, 0.389],
        },
        "object_orientations": {"red_cube": 0.5, "blue_cube": -0.3, "green_cube": 0.8},
    }
    snapshot = camera.snapshot(state)
    assert snapshot["source"] == "simulated_ground_truth"
    assert len(snapshot["detections"]) == 3
    red = next(item for item in snapshot["detections"] if item["object_name"] == "red_cube")
    assert list(camera.pixel_to_world(*red["pixel_center"]).values()) == pytest.approx(
        (-0.2, -0.16), abs=1e-4
    )
    assert red["orientation_yaw"] == pytest.approx(0.5)
    assert len(red["polygon"]) == 4
    assert red["dimensions"] == [0.028, 0.028]
