from __future__ import annotations

from pathlib import Path

from robot.mujoco_robot import MuJoCoRobot

root = Path(__file__).resolve().parents[1]
robot = MuJoCoRobot(root / "simulation" / "scene.xml")
objects = ("red_cube", "blue_cube", "green_cube")
results: list[tuple[int, str, str, float]] = []

for run in range(1, 11):
    robot.reset_scene()
    object_name = objects[(run - 1) % len(objects)]
    started = robot.get_state()["sim_time"]
    robot.start_pick_and_place(object_name, robot.STACK_TARGET)
    for _ in range(900):
        robot.step_simulation()
        state = robot.get_state()
        if state["task"]["status"] in {"completed", "failed"}:
            break
    duration = state["sim_time"] - started
    results.append((run, object_name, state["task"]["status"], duration))

for run, object_name, status, duration in results:
    print(f"{run:02d}  {object_name:<10}  {status:<9}  {duration:.2f} sim-s")

succeeded = sum(status == "completed" for _, _, status, _ in results)
average = sum(duration for *_, duration in results) / len(results)
print(f"success: {succeeded}/{len(results)} ({succeeded / len(results):.0%})")
print(f"average duration: {average:.2f} sim-s")
