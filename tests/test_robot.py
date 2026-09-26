import math
from pathlib import Path

import mujoco
import pytest

from robot.mujoco_robot import MuJoCoRobot

MODEL = Path(__file__).resolve().parents[1] / "simulation" / "scene.xml"


def test_scene_loads_and_exposes_dofbot_joints():
    robot = MuJoCoRobot(MODEL)
    state = robot.get_state()
    assert state["backend"] == "mujoco"
    assert set(state["joints"]) == {
        "base",
        "shoulder",
        "elbow",
        "wrist_pitch",
        "wrist_roll",
    }
    assert state["model"] == "dofbot_urdf_mesh"
    assert state["gripper"]["opening"] == 1.0
    assert set(state["objects"]) == {"red_cube", "blue_cube", "green_cube"}
    tool_site = mujoco.mj_name2id(robot.model, mujoco.mjtObj.mjOBJ_SITE, "tool_center")
    assert robot.model.site_pos[tool_site] == pytest.approx([0.0, -0.0015, 0.070])


def test_initial_workspace_layout_keeps_cubes_clear_of_robot_base():
    robot = MuJoCoRobot(MODEL)
    objects = robot.get_state()["objects"]
    assert objects["red_cube"][:2] == pytest.approx([-0.18, -0.17])
    assert objects["blue_cube"][:2] == pytest.approx([-0.30, -0.21])
    assert objects["green_cube"][:2] == pytest.approx([-0.47, -0.17])
    assert robot.get_state()["collision"]["status"] == "clear"


def test_joint_targets_are_validated():
    robot = MuJoCoRobot(MODEL)
    robot.set_joint_targets({"base": 0.4})
    assert robot.get_state()["targets"]["base"] == pytest.approx(0.4)
    with pytest.raises(ValueError):
        robot.set_joint_targets({"base": 99})
    with pytest.raises(KeyError):
        robot.set_joint_targets({"missing": 0})


def test_estop_requires_resume():
    robot = MuJoCoRobot(MODEL)
    robot.emergency_stop()
    with pytest.raises(ValueError):
        robot.set_joint_targets({"base": 0.2})
    robot.resume()
    robot.set_joint_targets({"base": 0.2})


def test_cartesian_ik_and_gripper_validation():
    robot = MuJoCoRobot(MODEL)
    solution = robot.move_tool((-0.2, -0.16, 0.575))
    assert set(solution) == set(robot.JOINTS)
    assert robot.get_state()["targets"]["base"] == pytest.approx(solution["base"], abs=1e-4)
    robot.set_gripper(0.0)
    assert robot._gripper_target == pytest.approx(robot.GRIPPER_TRAVEL)
    with pytest.raises(ValueError):
        robot.move_tool((0.4, 0.0, 0.5))
    with pytest.raises(ValueError):
        robot.set_gripper(1.2)


def test_grasp_pose_evaluator_aligns_wrist_with_parallel_yaw():
    robot = MuJoCoRobot(MODEL)
    evaluation = robot.evaluate_grasp_pose(
        (-0.2, -0.16, robot.CUBE_CENTER_Z + robot.GRASP_HEIGHT_OFFSET),
        math.radians(25),
    )
    assert evaluation["reachable"]
    assert evaluation["yaw_error"] < math.radians(3)
    assert evaluation["vertical_tilt"] <= robot.IK_VERTICAL_TOLERANCE
    assert 0.0 < evaluation["joint_margin"] <= 1.0
    assert evaluation["collision_free"]
    assert evaluation["path_clearance"] >= robot.PATH_MIN_CLEARANCE
    assert robot._limits["wrist_roll"][0] <= evaluation["solution"]["wrist_roll"]
    assert evaluation["solution"]["wrist_roll"] <= robot._limits["wrist_roll"][1]


def test_runtime_collision_telemetry_is_exposed():
    robot = MuJoCoRobot(MODEL)
    robot.step_simulation()
    collision = robot.get_state()["collision"]
    assert collision["status"] in {"clear", "warning"}
    assert isinstance(collision["active_contacts"], int)
    assert isinstance(collision["robot_contacts"], int)
    assert isinstance(collision["unexpected_contacts"], list)


def test_every_arm_section_has_an_enabled_collision_proxy():
    robot = MuJoCoRobot(MODEL)
    for name in robot.ARM_COLLISION_GEOMS:
        geom_id = mujoco.mj_name2id(robot.model, mujoco.mjtObj.mjOBJ_GEOM, name)
        assert geom_id >= 0
        assert robot.model.geom_contype[geom_id] == 2
        assert robot.model.geom_conaffinity[geom_id] == 1


def test_arm_link_contact_with_cube_is_reported_as_unexpected():
    robot = MuJoCoRobot(MODEL)
    link_geom_id = mujoco.mj_name2id(
        robot.model,
        mujoco.mjtObj.mjOBJ_GEOM,
        "arm_link3_collision",
    )
    cube_joint_id = robot._object_joint_ids["red_cube"]
    cube_qpos_address = robot.model.jnt_qposadr[cube_joint_id]
    robot.data.qpos[cube_qpos_address : cube_qpos_address + 3] = robot.data.geom_xpos[
        link_geom_id
    ]
    robot.data.qpos[cube_qpos_address + 3 : cube_qpos_address + 7] = [1, 0, 0, 0]
    mujoco.mj_forward(robot.model, robot.data)
    robot._update_collision_telemetry()

    collision = robot.get_state()["collision"]
    assert collision["status"] == "warning"
    assert collision["robot_contacts"] >= 1
    assert any(
        "arm_link3_collision" in contact["geoms"]
        and "red_cube_geom" in contact["geoms"]
        for contact in collision["unexpected_contacts"]
    )


@pytest.mark.parametrize("object_name", ["red_cube", "blue_cube", "green_cube"])
def test_pick_place_state_machine(object_name):
    robot = MuJoCoRobot(MODEL)
    robot.start_pick_and_place(object_name, robot.STACK_TARGET)
    saw_aligned_grasp = False
    for _ in range(900):
        robot.step_simulation()
        current = robot.get_state()
        if current["gripper"]["attached"] == object_name and not saw_aligned_grasp:
            distance = math.dist(current["tool_position"], current["objects"][object_name])
            assert distance <= robot.GRASP_TOLERANCE
            saw_aligned_grasp = True
        if current["task"]["status"] in {"completed", "failed"}:
            break
    state = robot.get_state()
    assert saw_aligned_grasp
    assert state["task"]["status"] == "completed"
    position = state["objects"][object_name]
    assert math.dist(position[:2], robot.STACK_TARGET) <= robot.SETTLE_XY_TOLERANCE
    assert position[2] == pytest.approx(robot.CUBE_CENTER_Z, abs=robot.SETTLE_Z_TOLERANCE)


def run_workflow(robot: MuJoCoRobot) -> dict:
    for _ in range(3500):
        robot.step_simulation()
        state = robot.get_state()
        if state["automation"]["workflow"]["status"] == "completed":
            return state
    pytest.fail("workflow did not complete")


def test_sorting_workflow_runs_three_queued_tasks():
    robot = MuJoCoRobot(MODEL)
    robot.start_sorting()
    initial = robot.get_state()
    assert initial["automation"]["workflow"]["mode"] == "sorting"
    assert len(initial["automation"]["queue"]) == 2

    state = run_workflow(robot)
    workflow = state["automation"]["workflow"]
    assert workflow["succeeded"] == 3
    assert workflow["failed"] == 0
    assert len(state["automation"]["history"]) == 3
    for name, xy in robot.SORT_TARGETS.items():
        position = state["objects"][name]
        assert math.dist(position[:2], xy) <= robot.SETTLE_XY_TOLERANCE
        assert position[2] == pytest.approx(
            robot.CUBE_CENTER_Z, abs=robot.SETTLE_Z_TOLERANCE
        )


def test_stacking_workflow_uses_one_cube_height_per_level():
    robot = MuJoCoRobot(MODEL)
    robot.start_stacking()
    state = run_workflow(robot)
    assert state["automation"]["workflow"]["succeeded"] == 3
    for level, name in enumerate(robot.OBJECTS):
        position = state["objects"][name]
        assert math.dist(position[:2], robot.STACK_TARGET) <= robot.SETTLE_XY_TOLERANCE
        assert position[2] == pytest.approx(
            robot.CUBE_CENTER_Z + level * robot.CUBE_SIZE,
            abs=robot.SETTLE_Z_TOLERANCE,
        )


def test_failed_batch_task_stops_remaining_queue():
    robot = MuJoCoRobot(MODEL)
    robot.start_stacking()
    with robot._lock:
        robot._finish_task(False, "测试失败")
    state = robot.get_state()
    assert state["automation"]["workflow"]["status"] == "failed"
    assert state["automation"]["workflow"]["failed"] == 1
    assert state["automation"]["queue"] == []
    assert state["task"]["object"] == "red_cube"


def test_sustained_collision_fails_active_task():
    robot = MuJoCoRobot(MODEL)
    robot.start_pick_and_place("red_cube", robot.STACK_TARGET)
    link_geom_id = mujoco.mj_name2id(
        robot.model, mujoco.mjtObj.mjOBJ_GEOM, "arm_link3_collision"
    )
    cube_joint_id = robot._object_joint_ids["blue_cube"]
    qpos_address = robot.model.jnt_qposadr[cube_joint_id]
    for _ in range(robot.COLLISION_FAILURE_STEPS):
        robot.data.qpos[qpos_address : qpos_address + 3] = robot.data.geom_xpos[link_geom_id]
        robot.data.qpos[qpos_address + 3 : qpos_address + 7] = [1, 0, 0, 0]
        mujoco.mj_forward(robot.model, robot.data)
        robot._update_collision_telemetry()
        robot._enforce_collision_safety()
    state = robot.get_state()
    assert state["task"]["status"] == "failed"
    assert "碰撞保护触发" in state["task"]["message"]


def test_completed_stack_is_not_coordinate_pinned():
    robot = MuJoCoRobot(MODEL)
    robot.start_stacking()
    state = run_workflow(robot)
    before = state["objects"]["green_cube"][0]
    joint_id = robot._object_joint_ids["green_cube"]
    dof_address = robot.model.jnt_dofadr[joint_id]
    robot.data.qvel[dof_address] = 0.05
    robot.step_simulation(5)
    after = robot.get_state()["objects"]["green_cube"][0]
    assert after > before
