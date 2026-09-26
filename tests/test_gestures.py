from fastapi.testclient import TestClient

from backend.app.main import app
from perception.gesture_controller import GestureController


def feed_sequence(
    controller: GestureController,
    gesture: str,
    frames: int,
    *,
    start_ms: float = 0.0,
) -> list[dict]:
    return [
        controller.feed(
            gesture,
            0.95,
            timestamp_ms=start_ms + index * 100,
            source="test",
        )
        for index in range(frames)
    ]


def test_regular_gesture_requires_six_stable_frames_and_release():
    controller = GestureController()
    results = feed_sequence(controller, "Thumb_Up", 6)

    assert all(item["triggered"] is None for item in results[:5])
    assert results[-1]["triggered"] == "execute_pending"
    assert controller.snapshot()["latched"] == "Thumb_Up"

    held = controller.feed("Thumb_Up", 0.99, timestamp_ms=2000, source="test")
    assert held["triggered"] is None
    controller.feed(None, 0.0, timestamp_ms=2100, source="test")
    retriggered = feed_sequence(controller, "Thumb_Up", 6, start_ms=2200)
    assert retriggered[-1]["triggered"] == "execute_pending"


def test_noise_resets_streak_and_low_confidence_is_ignored():
    controller = GestureController()
    feed_sequence(controller, "Victory", 4)
    reset = controller.feed("Victory", 0.30, timestamp_ms=500, source="test")
    assert reset["state"]["streak"] == 0
    assert reset["triggered"] is None
    assert feed_sequence(controller, "Victory", 5, start_ms=600)[-1]["triggered"] is None


def test_open_palm_preempts_a_latched_gesture_in_three_frames():
    controller = GestureController()
    assert feed_sequence(controller, "Thumb_Up", 6)[-1]["triggered"] == "execute_pending"
    emergency = feed_sequence(controller, "Open_Palm", 3, start_ms=600)
    assert emergency[-1]["triggered"] == "emergency_stop"


def test_thumb_up_executes_prepared_language_task():
    with TestClient(app) as client:
        parsed = client.post("/api/language/parse", json={"text": "把红色方块放到右边"})
        assert parsed.status_code == 200
        assert parsed.json()["gesture_pending"] is True

        response = None
        for index in range(6):
            response = client.post(
                "/api/gestures/frame",
                json={
                    "gesture": "Thumb_Up",
                    "confidence": 0.96,
                    "timestamp_ms": index * 100,
                    "source": "test",
                },
            )
        assert response is not None
        assert response.status_code == 200
        assert response.json()["triggered"] == "execute_pending"
        assert response.json()["robot_state"]["task"]["status"] == "running"
        assert response.json()["state"]["pending"] is None


def test_open_palm_endpoint_emergency_stops_robot():
    with TestClient(app) as client:
        response = None
        for index in range(3):
            response = client.post(
                "/api/gestures/frame",
                json={
                    "gesture": "Open_Palm",
                    "confidence": 0.94,
                    "timestamp_ms": index * 100,
                    "source": "test",
                },
            )
        assert response is not None
        assert response.json()["triggered"] == "emergency_stop"
        assert response.json()["robot_state"]["status"] == "estopped"
