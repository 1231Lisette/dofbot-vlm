from perception.closed_loop import ClosedLoopSupervisor


def state(task_id, status, message=""):
    return {"task": {"id": task_id, "status": status, "stage": "DONE", "message": message}}


def detection(x, y):
    return [{"object_name": "red_cube", "world_center": [x, y, 0.389]}]


def test_visual_verification_passes_inside_tolerance():
    supervisor = ClosedLoopSupervisor()
    supervisor.begin("red_cube", (-0.2, 0.16), [-0.2, -0.16, 0.389])
    supervisor.bind_task(1)

    assert supervisor.observe(state(1, "running"), detection(-0.2, -0.16)) is None
    assert supervisor.observe(state(1, "completed"), detection(-0.19, 0.16)) is None
    snapshot = supervisor.snapshot()
    assert snapshot["current"]["status"] == "verified"
    assert snapshot["metrics"]["verified"] == 1
    assert snapshot["metrics"]["success_rate"] == 1.0
    assert snapshot["metrics"]["average_error_mm"] == 10.0


def test_failed_verification_requests_only_one_retry():
    supervisor = ClosedLoopSupervisor(max_retries=1)
    supervisor.begin("red_cube", (-0.2, 0.16), [-0.2, -0.16, 0.389])
    supervisor.bind_task(1)

    action = supervisor.observe(state(1, "completed"), detection(-0.1, 0.16))
    assert action == {
        "type": "retry",
        "object_name": "red_cube",
        "target_xy": (-0.2, 0.16),
        "reason": "placement_error",
    }
    assert supervisor.observe(state(1, "completed"), detection(-0.1, 0.16)) is None

    supervisor.bind_task(2, retry=True)
    assert supervisor.observe(state(2, "completed"), detection(-0.1, 0.16)) is None
    snapshot = supervisor.snapshot()
    assert snapshot["current"]["status"] == "failed"
    assert snapshot["metrics"]["retries"] == 1
    assert snapshot["metrics"]["failed"] == 1
    assert snapshot["metrics"]["failure_reasons"]["placement_error"] == 2


def test_cancelled_task_never_retries():
    supervisor = ClosedLoopSupervisor()
    supervisor.begin("red_cube", (-0.2, 0.16), [-0.2, -0.16, 0.389])
    supervisor.bind_task(3)

    assert supervisor.observe(state(3, "cancelled"), detection(-0.2, -0.16)) is None
    assert supervisor.snapshot()["current"]["status"] == "cancelled"
    assert supervisor.snapshot()["metrics"]["retries"] == 0


def test_scene_reset_resolves_current_verification():
    supervisor = ClosedLoopSupervisor()
    supervisor.begin("red_cube", (-0.2, 0.16), [-0.2, -0.16, 0.389])
    supervisor.bind_task(4)
    supervisor.clear_current("场景已重置")

    snapshot = supervisor.snapshot()
    assert snapshot["current"]["status"] == "reset"
    assert snapshot["current"]["resolved"]


def test_retry_planning_failure_is_counted():
    supervisor = ClosedLoopSupervisor()
    supervisor.begin("red_cube", (-0.2, 0.16), [-0.2, -0.16, 0.389])
    supervisor.bind_task(5)
    supervisor.retry_start_failed("没有安全抓取候选")

    snapshot = supervisor.snapshot()
    assert snapshot["current"]["status"] == "failed"
    assert snapshot["metrics"]["failed"] == 1
    assert snapshot["metrics"]["failure_reasons"]["retry_unavailable"] == 1
