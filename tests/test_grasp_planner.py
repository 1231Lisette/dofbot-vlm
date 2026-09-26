import math

import pytest

from planner.grasp_planner import RGBPlanarGraspPlanner, normalize_parallel_yaw


def reachable(_position, yaw):
    return {
        "reachable": True,
        "joint_margin": 0.7 - abs(yaw) * 0.08,
        "yaw_error": 0.01,
        "solution": {"wrist_roll": yaw},
    }


DEFAULT_YAW = math.radians(30)


def detection(name="red_cube", yaw=DEFAULT_YAW, x=-0.2, y=-0.16):
    return {
        "object_name": name,
        "world_center": [x, y, 0.391],
        "orientation_yaw": yaw,
        "dimensions": [0.028, 0.028],
    }


def test_parallel_yaw_normalization():
    assert normalize_parallel_yaw(math.pi) == pytest.approx(0.0)
    assert normalize_parallel_yaw(3 * math.pi / 4) == pytest.approx(-math.pi / 4)


def test_planner_generates_scores_and_selects_one_candidate():
    planner = RGBPlanarGraspPlanner()
    target = detection()
    plan = planner.plan(target, [target, detection("blue_cube", x=-0.31, y=-0.1)], reachable)

    assert plan["selected_id"]
    assert len(plan["candidates"]) >= 3
    assert sum(item["status"] == "selected" for item in plan["candidates"]) == 1
    assert plan["selected"]["width"] == pytest.approx(0.03)
    assert plan["selected"]["score"] > 0.5


def test_planner_rejects_width_and_unreachable_candidates():
    planner = RGBPlanarGraspPlanner()
    target = {**detection(), "dimensions": [0.07, 0.07]}

    def unreachable(_position, _yaw):
        return {"reachable": False, "reason": "IK 无解"}

    plan = planner.plan(target, [target], unreachable)
    assert plan["selected"] is None
    assert all(item["score"] == 0 for item in plan["candidates"])
    assert all("夹爪开度不足" in item["reasons"] for item in plan["candidates"])


def test_collision_footprint_rejects_only_the_blocked_orientation():
    planner = RGBPlanarGraspPlanner()
    target = detection(yaw=0.0, x=-0.2, y=-0.16)
    nearby = detection("blue_cube", yaw=0.0, x=-0.2, y=-0.11)
    plan = planner.plan(target, [target, nearby], reachable)
    by_yaw = {round(abs(item["yaw_deg"])): item for item in plan["candidates"]}

    assert by_yaw[0]["status"] == "rejected"
    assert "夹指净空不足" in by_yaw[0]["reasons"][0]
    assert by_yaw[90]["status"] == "selected"
    assert by_yaw[90]["components"]["collision_margin"] >= planner.MIN_COLLISION_MARGIN
