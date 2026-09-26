import pytest
from fastapi.testclient import TestClient

from backend.app.main import app


def test_health_and_joint_control():
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["backend"] == "mujoco"

        state = client.get("/api/state").json()
        assert len(state["perception"]["detections"]) == 3

        response = client.post("/api/joints", json={"targets": {"base": 0.3}})
        assert response.status_code == 200
        assert response.json()["targets"]["base"] == 0.3

        tool = client.post("/api/tool", json={"xyz": [-0.2, -0.16, 0.575]})
        assert tool.status_code == 200
        assert set(tool.json()["solution"]) == {
            "base",
            "shoulder",
            "elbow",
            "wrist_pitch",
            "wrist_roll",
        }

        gripper = client.post("/api/gripper", json={"opening": 0.0})
        assert gripper.status_code == 200


def test_perception_endpoints():
    with TestClient(app) as client:
        detections = client.get("/api/perception/detections")
        assert detections.status_code == 200
        assert detections.json()["frame"] == {"width": 640, "height": 480}

        mapped = client.post(
            "/api/perception/pixel-to-world", json={"u": 221.5385, "v": 325.3333}
        )
        assert mapped.status_code == 200
        assert mapped.json()["world"]["x"] == pytest.approx(-0.2, abs=1e-4)
        assert mapped.json()["world"]["y"] == pytest.approx(-0.16, abs=1e-4)

        outside = client.post(
            "/api/perception/pixel-to-world", json={"u": -1, "v": 20}
        )
        assert outside.status_code == 422


def test_grasp_plan_endpoint_selects_a_safe_candidate():
    with TestClient(app) as client:
        response = client.get("/api/grasp-plans")
        assert response.status_code == 200
        plans = response.json()
        assert set(plans) == {"red_cube", "blue_cube", "green_cube"}
        red = plans["red_cube"]
        assert red["selected_id"]
        assert red["selected"]["status"] == "selected"
        assert red["selected"]["score"] > 0.5
        assert red["selected"]["components"]["collision_margin"] > 0
        assert red["selected"]["components"]["path_clearance"] > 0
        assert len(red["candidates"]) >= 3


def test_pick_place_and_reset_endpoints():
    with TestClient(app) as client:
        selected = client.get("/api/grasp-plans").json()["red_cube"]["selected"]
        response = client.post(
            "/api/tasks/pick-place",
            json={"object_name": "red_cube", "target_xy": [-0.2, 0.05]},
        )
        assert response.status_code == 200
        assert response.json()["task"]["status"] == "running"
        assert response.json()["task"]["grasp"]["yaw_deg"] == pytest.approx(
            selected["yaw_deg"], abs=0.2
        )
        verification = client.get("/api/verification")
        assert verification.status_code == 200
        assert verification.json()["current"]["object"] == "red_cube"
        assert verification.json()["current"]["attempt"] == 1
        assert verification.json()["metrics"]["prechecks"] == 1

        cancel = client.post("/api/tasks/cancel")
        assert cancel.status_code == 200
        assert cancel.json()["task"]["status"] == "cancelled"

        reset = client.post("/api/scene/reset")
        assert reset.status_code == 200
        assert reset.json()["task"]["status"] == "idle"
        assert client.get("/api/verification").json()["current"]["status"] == "reset"


def test_completed_pick_is_verified_from_simulated_camera():
    with TestClient(app) as client:
        response = client.post(
            "/api/tasks/pick-place",
            json={"object_name": "blue_cube", "target_xy": [-0.2, 0.05]},
        )
        assert response.status_code == 200
        app.state.robot.step_simulation(900)

        state = client.get("/api/state").json()
        assert state["task"]["status"] == "completed"
        assert state["verification"]["current"]["status"] == "verified"
        assert state["verification"]["current"]["position_error"] <= 0.01
        assert state["verification"]["metrics"]["verified"] == 1


def test_sorting_and_stacking_endpoints():
    with TestClient(app) as client:
        sorting = client.post("/api/tasks/sort")
        assert sorting.status_code == 200
        assert sorting.json()["automation"]["workflow"]["mode"] == "sorting"
        assert len(sorting.json()["automation"]["queue"]) == 2
        client.post("/api/tasks/cancel")
        client.post("/api/scene/reset")

        stacking = client.post("/api/tasks/stack")
        assert stacking.status_code == 200
        assert stacking.json()["automation"]["workflow"]["mode"] == "stacking"
        client.post("/api/tasks/cancel")


def test_language_parse_and_execute_endpoints():
    with TestClient(app) as client:
        parsed = client.post("/api/language/parse", json={"text": "把红色方块放到右边"})
        assert parsed.status_code == 200
        assert parsed.json()["intent"]["action"] == "pick_and_place"
        assert parsed.json()["intent"]["target_xy"] == [-0.16, 0.05]

        executed = client.post("/api/language/execute", json={"text": "开始颜色分拣"})
        assert executed.status_code == 200
        assert executed.json()["state"]["automation"]["workflow"]["mode"] == "sorting"
        client.post("/api/tasks/cancel")
        client.post("/api/scene/reset")

        rejected = client.post("/api/language/execute", json={"text": "帮我随便弄一下"})
        assert rejected.status_code == 422
        assert not rejected.json()["detail"]["intent"]["valid"]


def test_websocket_initial_state_and_command():
    with TestClient(app) as client, client.websocket_connect("/ws") as websocket:
        first = websocket.receive_json()
        assert first["type"] == "state"
        websocket.send_json({"type": "set_joints", "targets": {"elbow": 0.5}})
        for _ in range(4):
            update = websocket.receive_json()
            if update["data"]["targets"]["elbow"] == 0.5:
                break
        assert update["data"]["targets"]["elbow"] == 0.5


def test_websocket_language_command_result():
    with TestClient(app) as client, client.websocket_connect("/ws") as websocket:
        websocket.receive_json()
        websocket.send_json({"type": "language_command", "text": "机械臂归位"})
        for _ in range(6):
            response = websocket.receive_json()
            if response["type"] == "language_result":
                break
        assert response["data"]["intent"]["action"] == "home"
