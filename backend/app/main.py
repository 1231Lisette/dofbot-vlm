from __future__ import annotations

import asyncio
import contextlib
import os
import tomllib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.schemas import (
    CommandMessage,
    GestureFrame,
    GripperCommand,
    JointCommand,
    NaturalLanguageCommand,
    PickPlaceCommand,
    PixelCoordinate,
    ToolCommand,
)
from perception.closed_loop import ClosedLoopSupervisor
from perception.gesture_controller import GestureController
from perception.simulated_camera import SimulatedCamera
from planner.grasp_planner import RGBPlanarGraspPlanner
from planner.rule_parser import RuleBasedTaskParser, TaskIntent
from robot.factory import create_robot
from robot.interface import RobotInterface

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = PROJECT_ROOT / "frontend"
MODEL_ASSETS_DIR = PROJECT_ROOT / "simulation" / "dofbot_description" / "meshes"
CONFIG_PATH = Path(os.getenv("DOFBOT_CONFIG", PROJECT_ROOT / "configs" / "config.toml"))


def load_config() -> dict:
    with CONFIG_PATH.open("rb") as handle:
        return tomllib.load(handle)


async def state_publisher(app: FastAPI) -> None:
    interval = 1 / float(app.state.config["robot"].get("state_hz", 15))
    while True:
        await asyncio.sleep(interval)
        payload = {"type": "state", "data": enriched_state(app)}
        if not app.state.clients:
            continue
        disconnected: list[WebSocket] = []
        for client in tuple(app.state.clients):
            try:
                await client.send_json(payload)
            except (WebSocketDisconnect, RuntimeError):
                disconnected.append(client)
        for client in disconnected:
            app.state.clients.discard(client)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_config()
    robot = create_robot(config, PROJECT_ROOT)
    app.state.config = config
    app.state.robot = robot
    app.state.camera = SimulatedCamera()
    app.state.grasp_planner = RGBPlanarGraspPlanner()
    app.state.grasp_plan_cache: dict = {}
    app.state.grasp_plan_key = None
    app.state.closed_loop = ClosedLoopSupervisor(max_retries=1)
    app.state.language_parser = RuleBasedTaskParser()
    app.state.gesture_controller = GestureController()
    app.state.pending_intent: TaskIntent | None = None
    app.state.pending_text: str | None = None
    app.state.clients: set[WebSocket] = set()
    robot.start()
    publisher = asyncio.create_task(state_publisher(app))
    try:
        yield
    finally:
        publisher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await publisher
        robot.stop()


app = FastAPI(title="Dofbot VLM API", version="0.6.11", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
app.mount("/model-assets", StaticFiles(directory=MODEL_ASSETS_DIR), name="model-assets")


def robot_from(app: FastAPI) -> RobotInterface:
    return app.state.robot


def enriched_state(app: FastAPI) -> dict:
    state = robot_from(app).get_state()
    perception = app.state.camera.snapshot(state)
    perception["grasp_plans"] = grasp_plans(app, state, perception)
    decision = app.state.closed_loop.observe(state, perception["detections"])
    if decision and decision["type"] == "retry":
        try:
            start_planned_pick(
                app,
                decision["object_name"],
                decision["target_xy"],
                retry=True,
            )
        except (KeyError, ValueError) as exc:
            app.state.closed_loop.retry_start_failed(str(exc))
        state = robot_from(app).get_state()
        perception = app.state.camera.snapshot(state)
        perception["grasp_plans"] = grasp_plans(app, state, perception)
    return {
        **state,
        "perception": perception,
        "gesture": gesture_state(app),
        "verification": app.state.closed_loop.snapshot(),
    }


def grasp_plans(app: FastAPI, state: dict, perception: dict) -> dict:
    task_active = state["task"]["status"] in {"running", "paused"}
    if task_active and app.state.grasp_plan_cache:
        return app.state.grasp_plan_cache
    key = tuple(
        (
            name,
            *(round(float(value), 3) for value in position),
            round(float(state.get("object_orientations", {}).get(name, 0.0)), 3),
        )
        for name, position in sorted(state.get("objects", {}).items())
    )
    if key != app.state.grasp_plan_key:
        app.state.grasp_plan_cache = app.state.grasp_planner.plan_scene(
            perception["detections"], robot_from(app).evaluate_grasp_pose
        )
        app.state.grasp_plan_key = key
    return app.state.grasp_plan_cache


def start_planned_pick(
    app: FastAPI,
    object_name: str,
    target_xy: tuple[float, float],
    *,
    retry: bool = False,
) -> None:
    state = robot_from(app).get_state()
    perception = app.state.camera.snapshot(state)
    plan = grasp_plans(app, state, perception).get(object_name)
    if not plan or plan["selected"] is None:
        raise ValueError(f"No safe grasp candidate is available for {object_name}")
    detection = next(
        item for item in perception["detections"] if item["object_name"] == object_name
    )
    robot_from(app).start_pick_and_place(
        object_name,
        target_xy,
        grasp_yaw=float(plan["selected"]["yaw"]),
    )
    task_id = robot_from(app).get_state()["task"]["id"]
    if retry:
        app.state.closed_loop.bind_task(task_id, retry=True)
    else:
        app.state.closed_loop.begin(object_name, target_xy, detection["world_center"])
        app.state.closed_loop.bind_task(task_id)


def gesture_state(app: FastAPI) -> dict:
    snapshot = app.state.gesture_controller.snapshot()
    pending = app.state.pending_intent
    return {
        **snapshot,
        "pending": pending.to_dict() if pending is not None else None,
        "pending_text": app.state.pending_text,
    }


def set_pending_intent(app: FastAPI, text: str, intent: TaskIntent) -> None:
    app.state.pending_intent = intent if intent.valid else None
    app.state.pending_text = text if intent.valid else None


def clear_pending_intent(app: FastAPI) -> None:
    app.state.pending_intent = None
    app.state.pending_text = None


def process_gesture_frame(app: FastAPI, frame: GestureFrame) -> dict:
    result = app.state.gesture_controller.feed(
        frame.gesture,
        frame.confidence,
        timestamp_ms=frame.timestamp_ms,
        source=frame.source,
    )
    action = result["triggered"]
    if action is None:
        return {**result, "state": gesture_state(app)}

    controller = app.state.gesture_controller
    robot = robot_from(app)
    try:
        if action == "emergency_stop":
            robot.emergency_stop()
            controller.record_result("张开手掌：机械臂已急停")
        elif action == "home":
            robot.home()
            controller.record_result("V 手势：机械臂正在归位")
        elif action == "execute_pending":
            intent = app.state.pending_intent
            if intent is None:
                controller.record_result("点赞已确认，但当前没有待执行任务")
            else:
                execute_intent(app, intent)
                controller.record_result(f"点赞确认：{intent.summary}")
                clear_pending_intent(app)
    except (KeyError, ValueError) as exc:
        controller.record_result(f"动作被安全策略阻止：{exc}")
    return {**result, "state": gesture_state(app), "robot_state": enriched_state(app)}


def execute_intent(app: FastAPI, intent: TaskIntent) -> None:
    if not intent.valid or intent.action is None:
        raise ValueError(intent.error or "Invalid task intent")
    if intent.action == "pick_and_place":
        if intent.object_name is None or intent.target_xy is None:
            raise ValueError("Pick-and-place intent is missing required parameters")
        start_planned_pick(app, intent.object_name, intent.target_xy)
    elif intent.action == "sort":
        robot_from(app).start_sorting()
    elif intent.action == "stack":
        robot_from(app).start_stacking()
    elif intent.action == "home":
        robot_from(app).home()
    elif intent.action == "cancel":
        robot_from(app).cancel_task()
    elif intent.action == "emergency_stop":
        robot_from(app).emergency_stop()
    elif intent.action == "resume":
        robot_from(app).resume()
    else:
        raise ValueError(f"Unsupported task action: {intent.action}")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "backend": app.state.config["robot"]["backend"]}


@app.get("/api/state")
async def state() -> dict:
    return enriched_state(app)


@app.get("/api/perception/detections")
async def perception_detections() -> dict:
    state = robot_from(app).get_state()
    perception = app.state.camera.snapshot(state)
    perception["grasp_plans"] = grasp_plans(app, state, perception)
    return perception


@app.get("/api/grasp-plans")
async def get_grasp_plans() -> dict:
    state = robot_from(app).get_state()
    perception = app.state.camera.snapshot(state)
    return grasp_plans(app, state, perception)


@app.get("/api/verification")
async def verification_state() -> dict:
    return app.state.closed_loop.snapshot()


@app.post("/api/perception/pixel-to-world")
async def pixel_to_world(coordinate: PixelCoordinate) -> dict:
    try:
        world = app.state.camera.pixel_to_world(coordinate.u, coordinate.v)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"pixel": {"u": coordinate.u, "v": coordinate.v}, "world": world}


@app.post("/api/language/parse")
async def parse_language(command: NaturalLanguageCommand) -> dict:
    response = app.state.language_parser.response(command.text)
    intent = app.state.language_parser.parse(command.text)
    set_pending_intent(app, command.text, intent)
    return {**response, "gesture_pending": intent.valid}


@app.post("/api/language/execute")
async def execute_language(command: NaturalLanguageCommand) -> dict:
    response = app.state.language_parser.response(command.text)
    intent = app.state.language_parser.parse(command.text)
    try:
        execute_intent(app, intent)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail={**response, "execution_error": str(exc)}) from exc
    clear_pending_intent(app)
    return {**response, "state": enriched_state(app)}


@app.get("/api/gestures/state")
async def get_gesture_state() -> dict:
    return gesture_state(app)


@app.post("/api/gestures/frame")
async def gesture_frame(frame: GestureFrame) -> dict:
    return process_gesture_frame(app, frame)


@app.delete("/api/gestures/pending")
async def clear_gesture_pending() -> dict:
    clear_pending_intent(app)
    return gesture_state(app)


@app.post("/api/gestures/reset")
async def reset_gesture_state() -> dict:
    app.state.gesture_controller.reset()
    return gesture_state(app)


@app.post("/api/joints")
async def set_joints(command: JointCommand) -> dict:
    try:
        robot_from(app).set_joint_targets(command.targets)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return robot_from(app).get_state()


@app.post("/api/tool")
async def move_tool(command: ToolCommand) -> dict:
    try:
        solution = robot_from(app).move_tool(command.xyz)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"solution": solution, "state": robot_from(app).get_state()}


@app.post("/api/gripper")
async def set_gripper(command: GripperCommand) -> dict:
    try:
        robot_from(app).set_gripper(command.opening)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return robot_from(app).get_state()


@app.post("/api/tasks/pick-place")
async def start_pick_place(command: PickPlaceCommand) -> dict:
    try:
        start_planned_pick(app, command.object_name, command.target_xy)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return robot_from(app).get_state()


@app.post("/api/tasks/sort")
async def start_sorting() -> dict:
    try:
        robot_from(app).start_sorting()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return robot_from(app).get_state()


@app.post("/api/tasks/stack")
async def start_stacking() -> dict:
    try:
        robot_from(app).start_stacking()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return robot_from(app).get_state()


@app.post("/api/tasks/cancel")
async def cancel_task() -> dict:
    robot_from(app).cancel_task()
    return robot_from(app).get_state()


@app.post("/api/scene/reset")
async def reset_scene() -> dict:
    robot_from(app).reset_scene()
    app.state.closed_loop.clear_current("场景已重置，当前视觉闭环已结束")
    return robot_from(app).get_state()


@app.post("/api/home")
async def home() -> dict:
    robot_from(app).home()
    return robot_from(app).get_state()


@app.post("/api/stop")
async def emergency_stop() -> dict:
    robot_from(app).emergency_stop()
    return robot_from(app).get_state()


@app.post("/api/resume")
async def resume() -> dict:
    robot_from(app).resume()
    return robot_from(app).get_state()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    app.state.clients.add(websocket)
    await websocket.send_json({"type": "state", "data": enriched_state(app)})
    try:
        while True:
            raw = await websocket.receive_json()
            message = CommandMessage.model_validate(raw)
            if message.type == "set_joints":
                robot_from(app).set_joint_targets(message.targets or {})
            elif message.type == "move_tool" and message.xyz is not None:
                robot_from(app).move_tool(message.xyz)
            elif message.type == "set_gripper" and message.opening is not None:
                robot_from(app).set_gripper(message.opening)
            elif message.type == "pick_place":
                start_planned_pick(
                    app,
                    message.object_name or "red_cube",
                    message.target_xy or (-0.2, 0.05),
                )
            elif message.type == "sort_all":
                robot_from(app).start_sorting()
            elif message.type == "stack_all":
                robot_from(app).start_stacking()
            elif message.type == "language_command" and message.text is not None:
                response = app.state.language_parser.response(message.text)
                intent = app.state.language_parser.parse(message.text)
                if intent.valid:
                    execute_intent(app, intent)
                await websocket.send_json({"type": "language_result", "data": response})
            elif message.type == "gesture_frame" and message.confidence is not None:
                result = process_gesture_frame(
                    app,
                    GestureFrame(
                        gesture=message.gesture,
                        confidence=message.confidence,
                        timestamp_ms=message.timestamp_ms,
                        source=message.source or "camera",
                    ),
                )
                await websocket.send_json({"type": "gesture_result", "data": result})
            elif message.type == "cancel_task":
                robot_from(app).cancel_task()
            elif message.type == "reset_scene":
                robot_from(app).reset_scene()
                app.state.closed_loop.clear_current("场景已重置，当前视觉闭环已结束")
            elif message.type == "home":
                robot_from(app).home()
            elif message.type == "stop":
                robot_from(app).emergency_stop()
            elif message.type == "resume":
                robot_from(app).resume()
            elif message.type != "ping":
                await websocket.send_json({"type": "error", "message": "unknown command"})
    except (WebSocketDisconnect, RuntimeError):
        pass
    except (KeyError, ValueError) as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
    finally:
        app.state.clients.discard(websocket)
