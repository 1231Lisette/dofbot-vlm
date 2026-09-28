# DOFBOT 最终验收包

这个目录是项目最终答辩和现场验收的最小独立代码包，只包含已经用于 Jetson 真机系统的内容。

## 目录

```text
final_acceptance/
├── README.md
├── commands.md
├── docs/
│   └── TECHNICAL_REPORT.md
├── jetson_app/
│   ├── server.py
│   └── hardware_config.json
├── frontend/
│   ├── hardware-control.html
│   ├── hardware-control.css
│   ├── hardware-control.js
│   └── vendor/mediapipe/
│       ├── gesture_recognizer.task
│       ├── vision_bundle.mjs
│       ├── SOURCE.md
│       └── wasm/
└── tests/
    └── test_jetson_server_safety.py
```

## 每个部分的用途

- `commands.md`：从上电、SSH、启动网页、正式验收到安全关机的完整命令。
- `docs/TECHNICAL_REPORT.md`：最终真机系统技术报告。
- `jetson_app/server.py`：Jetson 摄像头、状态、事件和机械臂控制服务。
- `jetson_app/hardware_config.json`：六轴、夹爪、K1、等候姿势与手势动作配置。
- `frontend/hardware-control.*`：最终真机控制网页。
- `frontend/vendor/mediapipe/`：浏览器本地手势模型、JavaScript 模块和 WASM。
- `tests/test_jetson_server_safety.py`：后端配置、限步、互锁和 K1 同步安全测试。

## 最快验收入口

完整流程必须看 [`commands.md`](commands.md)。当前 Jetson 已部署时，核心步骤是：

```bash
ssh jetson@192.168.1.149
```

检查服务：

```bash
pgrep -af '^python3 /home/jetson/dofbot-web/server.py '
```

没有输出时启动：

```bash
cd /home/jetson/dofbot-web
export DOFBOT_HARDWARE_CONFIRM=POWER_CUTOFF_READY
nohup python3 /home/jetson/dofbot-web/server.py \
  --host 0.0.0.0 \
  --port 8765 \
  --web-root /home/jetson/dofbot-web/web \
  --enable-hardware \
  > /home/jetson/dofbot-web/server.log 2>&1 < /dev/null &
```

浏览器打开：

```text
http://192.168.1.149:8765/
```

## 从这个目录重新部署

在游戏本中进入本目录：

```bash
cd /home/pyy/dofbot-vlm/final_acceptance
```

上传后端：

```bash
scp jetson_app/server.py \
    jetson_app/hardware_config.json \
    jetson@192.168.1.149:/home/jetson/dofbot-web/
```

上传网页：

```bash
scp frontend/hardware-control.html \
    frontend/hardware-control.css \
    frontend/hardware-control.js \
    jetson@192.168.1.149:/home/jetson/dofbot-web/web/
```

MediaPipe 文件缺失时再上传：

```bash
scp -r frontend/vendor/mediapipe \
    jetson@192.168.1.149:/home/jetson/dofbot-web/web/vendor/
```

## 安全边界

- 不要带电插拔舵机线。
- 每次按过物理 K1 后，必须点击网页“已按 K1：同步直立姿势”。
- K1 同步按钮本身只修改软件基准，不发送舵机命令。
- 急停会关闭扭矩，机械臂可能下坠，执行前必须托住整臂。
- 状态表中的目标不是实测到位反馈。
- 最终验收不要运行旧 ID、读取、偏移或极限标定脚本。
- 不要在同一时间运行原厂 Notebook、App、手柄动作组和本网页服务。
