# DOFBOT LAB

一个面向《综合设计 IV》的跨平台项目：FastAPI 同时提供 Web 控制台、REST 和 WebSocket，MuJoCo 负责 Dofbot 五关节模型、夹爪、物体和自动任务。当前已完成 Milestone 0–6.11。

## 当前可用功能

- FastAPI 健康检查、状态、关节/末端/夹爪控制、归位、恢复和急停接口。
- WebSocket 双向控制与 15 Hz 状态推送。
- MuJoCo 场景：Dofbot URDF/STL 网格、5 个臂关节、2 个真实网格夹指执行器、桌面、3 个 28 mm 可抓取方块和目标区；底座及全部活动连杆均有独立物理碰撞代理。
- 默认工作区采用展开弧形布局：红 `(-0.18,-0.17)`、蓝 `(-0.30,-0.21)`、绿 `(-0.47,-0.17)`，默认视角中不再被机械臂底座遮挡。
- Jacobian 阻尼最小二乘逆运动学，抓取与放置阶段同时约束末端位置、平面 yaw 和接近轴倾角。
- 安全任务状态机：抓取、搬运、物理释放、稳定检测、沿接近轴分段撤离、最终复检；任一子任务失败会立即终止批量队列。
- 现代响应式 Web 控制台：首屏中文自然语言输入、结构化任务预览、吸顶分区导航、Three.js 实时三维模型、碰撞状态、任务进度和安全操作。
- 640×480 仿真顶视相机、三类方块真值检测框、像素/世界坐标映射和点击目标抓取。
- 视觉模块明确标记为 `SIM GROUND TRUTH`；后续可在不改变任务层的情况下替换为真实摄像头与 YOLO。
- RGB 平面抓取规划器：根据目标中心、轮廓方向和尺寸生成轮廓主/副轴与世界 X/Y 候选，输出 `x/y/z/yaw/width/score`。
- 候选评分综合轮廓对齐、夹爪开度、方向相关的夹指占用区、IK、关节余量、腕部角度和整段运动路径净空；不可达候选显示拒绝原因。
- 执行前采样检查 HOME → PRE_GRASP → APPROACH 的关节路径，并使用 MuJoCo 真实接触检测淘汰会擦桌或碰到非目标方块的夹取角度。
- 运行中实时监测整台机械臂的接触；超过 1 mm 且连续 6 帧的异常接触会冻结当前关节目标并让任务失败，正常夹持、落桌和堆垛支撑接触不会误触发。
- 仿真视觉闭环：抓取前用最新检测重新规划，放置后通过顶视检测验证目标 XY；偏差、目标丢失或执行失败时最多自动重试一次。
- 闭环实验指标：当前尝试次数、放置误差、验证成功数、重试数及分类失败原因实时显示。
- 顶视相机同步绘制旋转轮廓、全部候选、最佳抓取、评分、夹指净空和路径净空；点击目标后执行当前最高分安全姿态。
- 批量任务编排：按颜色连续分拣三块方块，或按 28 mm 层高完成三层物理堆垛；释放后不再固定方块坐标，由重力、接触和支撑关系决定结果。
- 队列与统计：当前项、等待项、总体进度、最近历史、成功数和成功率实时显示。
- 本地中文规则解析器：先把自然语言显示为结构化任务，再由用户确认执行；未知、缺参数或歧义指令不会驱动机械臂。
- 浏览器端 MediaPipe 三手势识别：张开手掌急停、点赞执行待确认任务、V 手势归位；模型与 WebAssembly 已随项目本地化。
- 后端连续帧防抖、置信度阈值、动作锁存与释放再触发；急停只需 3 帧并可抢占，普通手势需 6 帧。
- 明确标记的模拟手势输入，便于没有摄像头或未授权摄像头的环境完成链路验收。
- `RobotInterface`、`MuJoCoRobot` 和 `DofbotRobot` 边界，方便后续切换真机。
- 基础接口和仿真测试。

详细课程路线见 [课设执行计划.md](课设执行计划.md)。

换电脑、交给新的 Codex 任务或开始真机接入前，请先阅读：

- [项目交接](docs/HANDOFF.md)
- [课程要求摘要](docs/COURSE_REQUIREMENTS.md)
- [真机首次启动](docs/HARDWARE_SETUP.md)
- [游戏本与 Jetson 网线配置](docs/NETWORK_SETUP.md)
- [真机标定记录](docs/CALIBRATION.md)

## 环境要求

- macOS Apple Silicon 或 Linux x86_64
- Python 3.11（项目声明兼容 3.11–3.12）

## 一次性安装

在项目根目录执行：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Windows PowerShell 激活环境时使用：

```powershell
.venv\Scripts\Activate.ps1
```

## 启动

```bash
source .venv/bin/activate
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

然后打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)。API 文档位于 [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)。

页面首屏就是自然语言输入框，可输入“把红色方块放到右边”等中文指令。按 `Enter` 解析任务，检查结构化预览后点击“确认并执行”；也可按 `Command/Ctrl + Enter` 执行已经通过解析的任务。解析后的任务还可以用点赞手势确认。仿真面板右侧可直接执行单次抓取、颜色分拣或三层堆垛。首次点击“开启摄像头识别”时，需要在浏览器中允许 `127.0.0.1` 使用摄像头；不授权时可用三个“模拟”按钮验收动作链路。顶视相机会显示当前目标的平面抓取候选，青色实线是自动选择的最佳姿态，黄色虚线是其他可达姿态，红色候选表示被安全约束拒绝。点击检测目标即可按最佳姿态抓取。“重置场景”会恢复三个方块的初始位置，但保留本次服务运行期间的任务历史。

三个手势的使用方式：

| 手势 | 动作 | 触发条件 |
|---|---|---|
| ✋ `Open_Palm` | 急停并暂停当前任务 | 置信度 ≥ 0.70，连续 3 帧，最高优先级 |
| 👍 `Thumb_Up` | 执行最近一次已解析的合法中文任务 | 置信度 ≥ 0.70，连续 6 帧 |
| ✌️ `Victory` | 取消当前任务并归位 | 置信度 ≥ 0.70，连续 6 帧 |

触发后需要把手放下或移出画面，才会重新解锁同一个手势，防止长时间保持姿势造成重复动作。

## 验证

```bash
source .venv/bin/activate
python scripts/check_scene.py
python -m pytest -q
python -m scripts.benchmark_pick_place
```

预期：53 项自动化测试全部通过；其中包含失败即停、持续碰撞保护、末端倾角、物理堆垛稳定性和“完成后不再坐标锁定”测试。基准脚本交替抓取三个不同初始角度的红/蓝/绿方块 10 次，当前基线为 `10/10 (100%)`，平均约 `6.16 sim-s`。

## Dofbot 模型来源与替换

当前 URDF/STL 来自公开的 Dofbot 模型仓库，具体版本、来源和再分发提示见
`simulation/dofbot_description/SOURCE.md`。该资源用于先完成课程仿真验证。

拿到课程系统中的官方模型后，可以覆盖 `simulation/dofbot_description/urdf` 与
`simulation/dofbot_description/meshes`，再按文件名或 `<mesh>` 配置更新场景。

## API 摘要

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/health` | 后端和机器人类型 |
| GET | `/api/state` | 当前关节、目标、限位、仿真时间和运行时碰撞监测 |
| GET | `/api/perception/detections` | 相机标定信息与当前检测结果 |
| GET | `/api/grasp-plans` | 三个目标的平面抓取候选、评分、最佳姿态和拒绝原因 |
| GET | `/api/verification` | 当前视觉闭环状态、放置误差、重试与失败统计 |
| POST | `/api/perception/pixel-to-world` | 将 640×480 像素坐标映射到桌面 XY |
| POST | `/api/language/parse` | 只解析中文指令，不执行动作 |
| POST | `/api/language/execute` | 解析并执行白名单任务意图 |
| GET | `/api/gestures/state` | 手势防抖、锁存与待确认任务状态 |
| POST | `/api/gestures/frame` | 提交一帧手势类别、置信度与时间戳 |
| DELETE | `/api/gestures/pending` | 清除待手势确认的自然语言任务 |
| POST | `/api/gestures/reset` | 重置手势防抖状态 |
| POST | `/api/joints` | 设置一个或多个关节目标 |
| POST | `/api/tool` | 设置末端 XYZ 目标并返回 IK 解 |
| POST | `/api/gripper` | 设置夹爪开度（0=关，1=开） |
| POST | `/api/tasks/pick-place` | 启动自动抓取放置 |
| POST | `/api/tasks/sort` | 连续执行红/蓝/绿颜色分拣 |
| POST | `/api/tasks/stack` | 连续执行三层方块堆垛 |
| POST | `/api/tasks/cancel` | 取消当前任务 |
| POST | `/api/scene/reset` | 重置机械臂、方块和任务 |
| POST | `/api/home` | 回到预设姿态 |
| POST | `/api/stop` | 急停并锁定目标 |
| POST | `/api/resume` | 解除急停 |
| WS | `/ws` | 双向控制与状态推送 |

REST 关节控制示例：

```bash
curl -X POST http://127.0.0.1:8000/api/joints \
  -H 'Content-Type: application/json' \
  -d '{"targets":{"base":0.5,"shoulder":-0.3}}'
```

WebSocket 消息示例：

```json
{"type":"set_joints","targets":{"elbow":0.7}}
```

Pick-and-Place REST 示例：

```bash
curl -X POST http://127.0.0.1:8000/api/tasks/pick-place \
  -H 'Content-Type: application/json' \
  -d '{"object_name":"red_cube","target_xy":[-0.2,0.05]}'
```

## 配置与真机迁移

默认配置在 `configs/config.toml`。目前使用：

```toml
[robot]
backend = "mujoco"
```

Milestone 7 会完成 `robot/dofbot_robot.py`。届时只需把配置切为 `dofbot`，上层 API、Web 控制台和规划器无需改写。真实机械臂接入前必须补充软限位、速度限制、通信超时和硬件急停测试。

## 接下来的开发顺序

1. 在 Ubuntu 上训练/接入 YOLO-Seg，把真实轮廓送入现有 `RGBPlanarGraspPlanner`。
2. Milestone 7：Jetson/Dofbot 真机迁移与低速安全测试。
3. Milestone 8：真实视觉实验、手势多人测试、指标统计与答辩材料。
