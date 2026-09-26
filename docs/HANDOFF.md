# DOFBOT LAB handoff

更新日期：2026-09-26

远程仓库：<https://github.com/1231Lisette/dofbot-vlm>

仿真基线提交：`c0f730d`

仿真基线版本：`0.6.11`

## 项目目标

实现一个由摄像头感知、目标识别、坐标标定、任务解析、抓取规划、Dofbot 控制和
Web 上位机构成的课程设计系统，完成分拣、堆垛与三手势交互。仿真和真机共享
`RobotInterface`，上层 API 与 UI 不因后端切换而重写。

## 当前已经完成

- FastAPI、REST、WebSocket 与响应式 Web 控制台。
- Dofbot URDF/STL 的 MuJoCo 场景，五个臂关节、双指夹爪、桌面、方块和目标区。
- 基础关节控制、EEF/夹爪对齐、位置 IK 与平面 yaw 规划。
- 单物体抓取、三色分拣和三层物理堆垛。
- 运行前路径检查、运行时碰撞保护和失败即停止队列。
- 仿真顶视相机、检测框、平面像素/世界映射和视觉闭环验证。
- 中文规则任务输入和结构化确认。
- MediaPipe 三手势：张开手掌急停、点赞执行、V 手势归位。
- 53 项自动化测试；仿真基准 10/10，平均约 6.16 仿真秒。

## 当前还没有完成

- `robot/dofbot_robot.py` 仍是占位实现，不能连接真实机械臂。
- USB 物体摄像头还没有接入后端感知接口。
- 尚未采集真机舵机 ID、零位、方向、软限位和安全 HOME。
- 尚未完成相机内参、桌面单应矩阵和相机到机械臂坐标标定。
- 尚未接入 YOLO-Seg 真实检测结果。
- 尚未完成真实抓取、分拣、堆垛的重复实验与数据分析。

## 新电脑恢复

```bash
git clone https://github.com/1231Lisette/dofbot-vlm.git
cd dofbot-vlm
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pytest -q
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

浏览器打开 <http://127.0.0.1:8000>。预期测试为 `53 passed`；如果数量增加，应以全部
通过为准。

## 当前架构

```text
Ubuntu 游戏本
├── FastAPI / Web / WebSocket
├── YOLO-Seg 与坐标标定
├── 任务解析与抓取规划
└── MuJoCoRobot 或 DofbotRobot

固定网线 192.168.77.0/24

Jetson / DOFBOT
├── USB 摄像头采集
├── Arm_Lib / 原厂总线驱动
├── 低速插值与软限位
└── 轻量硬件控制服务
```

建议把运算、Web 和 YOLO 放在游戏本；Jetson 保留原厂系统，只运行摄像头与机械臂
硬件桥。这样不必在旧版 JetPack 上强装 Python 3.11。

## Milestone 7 执行顺序

1. 按 `docs/HARDWARE_SETUP.md` 完成设备、系统盘和原厂功能基线。
2. 按 `docs/NETWORK_SETUP.md` 建立游戏本到 Jetson 的固定网线连接。
3. 将系统和硬件实测值填入 `docs/CALIBRATION.md`。
4. 只读验证六路舵机，确认没有第二个进程占用控制总线。
5. 逐轴做 3–5°、1500–3000 ms 的低速点动并立即回位。
6. 实现 Jetson 硬件桥：状态读取、单关节目标、夹爪、HOME、STOP 和超时保护。
7. 实现 `DofbotRobot`，但默认仍使用 `backend = "mujoco"`。
8. 用 mock 硬件测试角度映射、限位、断线和急停。
9. 切换真机后先验证固定姿态，再测试固定点抓取。
10. 接入相机标定和 YOLO-Seg，最后测试自动分拣与堆垛。

## 真机实现必须满足

- 明确的关节名到舵机 ID 映射。
- MuJoCo 弧度到舵机角度的零偏、方向与范围转换。
- 每个舵机独立软限位，越界命令拒绝执行。
- 速度/时间限制，首次联调禁止瞬时动作。
- 命令序号、通信超时、断线停止和单控制器所有权。
- 急停不依赖任务状态，能够抢占普通命令。
- 真机后端失败不得自动退回仿真并伪装成功。

## 给新 Codex 任务的启动提示

```text
请先阅读 AGENTS.md、README.md、docs/HANDOFF.md、docs/COURSE_REQUIREMENTS.md、
docs/HARDWARE_SETUP.md 和 docs/CALIBRATION.md。先运行现有测试，不重写已经通过的仿真
功能。继续 Milestone 7：根据 CALIBRATION.md 中的实测信息实现安全的 Jetson 硬件桥和
DofbotRobot；在明确软限位前不得发送多舵机动作。
```

## 已知注意事项

- GitHub 仓库为私有仓库。课程 PPT 不应在公开仓库重新分发。
- 当前 STL 来源没有明确许可证，课程内部使用可以保留，公开发布前换成官方授权资产。
- 一个固定俯视 USB 摄像头适合 YOLO 抓取，但不适合同时正面识别手势；只有一台相机时
  可以分时演示，或增加第二台摄像头。
- 本机曾存在失效的 `GH_TOKEN`。如果 `gh` 命令忽略已保存登录，可先在当前终端执行
  `unset GH_TOKEN`，不要把 token 写入仓库。
