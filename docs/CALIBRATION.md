# 真机标定记录

这份文件只记录可提交的硬件事实和标定数值。不要写入登录密码、Wi-Fi 密码、Token 或私有
系统镜像链接。

## 设备信息

| 项目 | 实测值 |
|---|---|
| DOFBOT 型号 | 待采集（本次未读取机械臂控制板） |
| Jetson 型号/版本 | NVIDIA Jetson Nano Developer Kit；设备树兼容标识 `p3448-0002-b00 + p3449-0000-b00`，Tegra210 |
| 扩展板型号 | 待采集 |
| 电源规格 | 待采集 |
| 系统盘类型/容量 | USB Mass Storage，`/dev/sda` 58.6 GiB；根分区 `/dev/sda1` ext4，约 53 GiB |
| Ubuntu 版本 | Ubuntu 18.04.6 LTS (Bionic) |
| JetPack / L4T | L4T R32.4.4；`nvidia-l4t-core 32.4.4-20201016124427`；未发现已安装的 `nvidia-jetpack` 元包 |
| Python | Python 3.6.9 |
| ROS | ROS 1 Melodic；ROS master 已由 `arm.service` 启动 |
| 原厂代码目录 | `/home/jetson/Dofbot`、`/home/jetson/Arm`、`/home/jetson/dofbot_ws`、`/home/jetson/catkin_ws` |
| `Arm_Lib` 版本/路径 | 0.0.5；`/usr/local/lib/python3.6/dist-packages/Arm_Lib-0.0.5-py3.6.egg`；源码副本 `/home/jetson/Dofbot/0.py_install/Arm_Lib/Arm_Lib.py` |
| 原厂后台服务 | `arm.service`、`dofbot_oled.service`、`jetson_jupyter.service` 均 enabled 且 running |
| Jetson 当前网络 | Wi-Fi `wlan0 = 192.168.1.149/24`；`eth0` 已 UP 但没有 IPv4 地址 |
| Jetson 计划有线 IP | `192.168.77.2`（尚未配置） |

## 舵机映射

角度范围必须来自逐轴低速实测，不能只抄官方标称范围。

| ID | 实际关节 | 初始读数 ° | 中位 ° | 正方向 | 安全最小 ° | 安全最大 ° | 仿真零位 rad | 状态 |
|---:|---|---:|---:|---|---:|---:|---:|---|
| 1 | 待采集 |  |  |  |  |  |  | 未验证 |
| 2 | 待采集 |  |  |  |  |  |  | 未验证 |
| 3 | 待采集 |  |  |  |  |  |  | 未验证 |
| 4 | 待采集 |  |  |  |  |  |  | 未验证 |
| 5 | 待采集 |  |  |  |  |  |  | 未验证 |
| 6 | 待采集 |  |  |  |  |  |  | 未验证 |

2026-09-26 的查询尝试不能作为初始角度标定值：返回结果不稳定，而且查询期间机械臂发生了
意外运动。原始结果和停用结论见下方“舵机查询安全事件”。

## 安全姿态

| 姿态 | S1 | S2 | S3 | S4 | S5 | S6 | 验证结果 |
|---|---:|---:|---:|---:|---:|---:|---|
| 上电初始 |  |  |  |  |  |  | 待采集 |
| 安全 HOME |  |  |  |  |  |  | 待验证 |
| 运输姿态 |  |  |  |  |  |  | 待验证 |

## USB 摄像头

| 项目 | 实测值 |
|---|---|
| 品牌/型号 | Sonix Technology Co., Ltd. `USB 2.0 Camera`；USB ID 数据库显示为 Microdia，具体商品型号待看实物标签 |
| USB ID | `0c45:6340` |
| 设备节点 | `/dev/video0`，`uvcvideo` 驱动 |
| 分辨率/帧率 | YUYV；640×480 支持 5/10/15/20/25/30 FPS，检查时为 25 FPS |
| 是否镜像/倒置 | 待采集 |
| 安装位置 | 待采集 |
| 到桌面高度 | 待采集 |
| 曝光/白平衡设置 | 未修改；本次只读取 V4L2 当前控制值 |
| 其他能力 | 同一 USB 设备提供 USB Audio 麦克风，ALSA 显示为 card 2 `Camera` |

## 相机内参

```text
image_width:
image_height:
fx:
fy:
cx:
cy:
distortion:
reprojection_error:
```

## 桌面与坐标标定

```text
桌面坐标原点：
机械臂底座在桌面坐标中的位置：
桌面有效 X 范围：
桌面有效 Y 范围：
抓取平面 Z：
像素到桌面单应矩阵 H：
标定点数量：
平均平面误差：
最大平面误差：
```

## 首次逐轴测试记录

| 日期 | 操作者 | ID | 起始 ° | 目标 ° | 时间 ms | 实际方向 | 是否回位 | 异常 |
|---|---|---:|---:|---:|---:|---|---|---|
| 待采集 |  |  |  |  |  |  |  |  |
| 2026-09-26 | Codex 远程查询 | 未确认 | 未确认 | 未发送角度目标 | 不适用 | 未确认 | 未确认 | 调用厂家查询 API 期间机械臂意外运动；立即停止全部硬件查询并退出 SSH |

## 固定点验证

| 点位 | 目标 XYZ/mm | 重复次数 | 平均误差/mm | 最大误差/mm | 碰撞/限位 | 结论 |
|---|---|---:|---:|---:|---|---|
| HOME |  |  |  |  |  | 待验证 |
| PRE_GRASP |  |  |  |  |  | 待验证 |
| GRASP_CENTER |  |  |  |  |  | 待验证 |
| PLACE_CENTER |  |  |  |  |  | 待验证 |

## 系统盘备份

| 项目 | 记录 |
|---|---|
| 镜像文件名 | 待采集 |
| 原盘容量 | 待采集 |
| 镜像大小 | 待采集 |
| SHA-256 | 待采集 |
| 恢复验证日期 | 待验证 |

## Jetson 首次只读基线

检查时间：2026-09-26 22:26–22:34 CST
检查方式：SSH，只执行查询命令；未使用 `sudo`，未安装软件，未启停服务，未写远端文件，
未导入或实例化 `Arm_Device`，未访问舵机查询或控制寄存器。

### 系统与算力环境

| 项目 | 只读检查结果 |
|---|---|
| 主机名 | `jetson-desktop` |
| 内核 | `4.9.140-tegra`，AArch64 |
| 内存 | 3.9 GiB；检查时约 1.9 GiB available |
| Swap | 5.9 GiB，检查时未使用 |
| 根分区 | `/dev/sda1`，约 53 GiB，检查时使用约 25 GiB |
| 板载/TF 设备 | `/dev/mmcblk0` 14.7 GiB，存在多个分区，但当前根文件系统不在该设备上 |
| CUDA | 10.2，`nvcc V10.2.89` |
| 电源模式 | `MAXN`；普通用户查询部分 EMC 参数时权限不足 |
| NumPy | 1.19.4 |
| OpenCV Python | 4.9.0.80 |
| PyTorch | 1.6.0 |
| Torchvision | 0.7.0a0+78ed10c |
| JupyterLab | 2.2.8，监听 `0.0.0.0:8888` |

启动参数同时出现过 `root=/dev/mmcblk0p1` 和后置的 `root=/dev/sda1`；实际挂载结果确认根文件系统为
`/dev/sda1`。制作系统备份前必须再次核对两个设备，不能仅依据启动参数中的第一个 `root=`。

### 当前网络与开放服务

- SSH 监听 `0.0.0.0:22` 和 IPv6 22 端口。
- JupyterLab 监听所有接口的 8888 端口。
- ROS master 监听 11311 端口。
- Vino 远程桌面监听 5900 端口。
- Docker 已安装且服务运行，但 `docker0` 当前无载波。
- 当前默认路由通过 Wi-Fi `wlan0`；有线接口尚未配置课程计划中的固定地址。

### 原厂机械臂软件

- `Arm_Lib 0.0.5` 使用 `smbus.SMBus(1)`，控制板地址为 `0x15`。
- 库中 ID 1–6 为六路舵机；ID 2、3、4 的角度方向在库内反转，ID 5 使用 0–270°换算，
  其余接口使用 0–180°换算。这些只是厂家库逻辑，不等于已经验证的机械安全范围。
- `Arm_serial_servo_read(id)` 名称虽然是“读取”，实现会先调用
  `write_byte_data(0x15, id + 0x30, 0x00)`，再读取结果。因此它会向 I²C 控制板写查询寄存器，
  本次严格只读基线没有调用该函数。
- 厂家读取示例位于 `/home/jetson/Dofbot/3.ctrl_Arm/4.read_servo.ipynb`，其中也会实例化
  `Arm_Device()`；本次没有运行 Notebook。
- `arm.service` 以 root 启动 ROS 1，当前节点只有 `/kin` 和 `/rosout`；`/kin` 提供
  `/get_kinemarics` 服务，未发现它直接发布舵机控制 topic。
- `dofbot_oled.service` 正在运行 PID 7114，并占用 `/dev/i2c-1`。OLED 与 Arm_Lib 共用 I²C-1，
  即使地址可能不同，在确认并发访问和控制所有权前也不应启动自定义 Arm_Lib 进程。
- `/dev/video0`、`/dev/ttyTHS1`、`/dev/ttyTHS2` 在检查时没有发现占用进程。

### 当前安全结论

1. 系统、USB 根盘、摄像头、CUDA、ROS 和厂家 Arm_Lib 均存在，原厂镜像基础功能较完整。
2. 还没有确认扩展板型号、电源规格、控制板硬件版本、六路舵机读数、实际关节映射或安全范围。
3. 当前不能运行自动归中、全舵机 90°、舞蹈、扫描、抓取或任何写角度示例。
4. `Arm_serial_servo_read` 必须视为硬件写事务，而不是纯文件读取。
5. 本节完成时尚未进行总线测试；随后获准进行的查询发生意外运动，现已全面暂停，见下方事件记录。

## 舵机查询安全事件（2026-09-26）

### 事件经过

在用户允许继续采集待确认信息后，远程执行了厂家 `Arm_Lib 0.0.5` 的查询接口。执行前确认
没有发现另一个 `Arm_Device`、舵机示例或动作程序运行；当时只有原厂 ROS 运动学节点和 OLED
进程。没有调用任何角度写入、扭矩、ID、偏移、归中、动作组或复位接口。

调用顺序如下：

1. `Arm_get_hardversion()` 一次；
2. `Arm_serial_servo_read(1..6)`，每个 ID 五次；
3. `Arm_ping_servo(1..6)`，每个 ID 五次；
4. `Arm_serial_servo_read(1..6)`，每个 ID 三次、较低频率复读。

用户随后报告：“刚刚你读的时候它动了一下”。无法从现有信息确定动作发生在上述哪个具体查询，
也不能确定移动的是哪个关节。收到报告后立即停止全部硬件访问并退出 SSH，没有继续诊断。
随后用户确认机械臂已经静止。

### 原始返回值

这些值只用于故障分析，**不是标定值**：

| 查询 | 返回结果 |
|---|---|
| 控制板版本 | `0.2` |
| 首轮 ID 1 | `None, None, None, None, None` |
| 首轮 ID 2 | `None, None, None, None, None` |
| 首轮 ID 3 | `None, None, None, None, None` |
| 首轮 ID 4 | `13, 13, 13, 13, 13` |
| 首轮 ID 5 | `90, 90, 90, 90, 90` |
| 首轮 ID 6 | `None, 180, None, None, None` |
| Ping ID 1 | 五次均返回 `0xDA` |
| Ping ID 2–6 | 全部返回 `None` |
| 低频复读 ID 1 | `69, 69, 69` |
| 低频复读 ID 2–6 | 全部返回 `None` |

### 安全判断

- 当前控制板固件/协议、总线状态或厂家库行为与预期不一致；原因尚未确认。
- 即使函数名包含 `read` 或 `ping`，也会先向控制板写寄存器，现场已经证明可能伴随机械运动。
- **禁止再次运行 `Arm_get_hardversion`、`Arm_serial_servo_read`、`Arm_serial_servo_read_any`、
  `Arm_ping_servo` 或任何其他 Arm_Lib 方法。**
- 在查明原因前，不得使用软件命令尝试回位、停止、关闭扭矩或补做读数。
- 后续诊断必须在执行器动力被物理隔离、机械臂被安全支撑且电源切断手段触手可及的条件下进行。
  应先离线审查控制板协议和厂家对应版本示例，再决定是否进行带电测试。

## 设备信息补充检查（2026-09-26）

在用户确认机械臂已经静止后，再次进行纯系统文件检查。本轮没有打开 `/dev/i2c-*`，没有导入
`Arm_Lib`，没有查询控制板或舵机，也没有启动摄像头取流。

### 已由系统确认

- 设备树型号为 `NVIDIA Jetson Nano Developer Kit`，兼容字符串包含
  `nvidia,p3449-0000-b00+p3448-0002-b00`、`nvidia,jetson-nano` 和 `nvidia,tegra210`。
- 设备树插件 ID 为 `3448-0002-401`；`/etc/nv_boot_control.conf` 的 TNSPEC 为
  `3448-300---1-0-jetson-nano-qspi-sd-mmcblk0p1`。两套标识来源不同，保留原值，不据此猜测
  模块销售版本。
- Tegra chip ID 为 `0x21`（十进制 33）。设备序列号已能从系统读取，但不写入可提交文档。
- I²C-0 到 I²C-5 是 Tegra 控制器，I²C-6 是 Tegra I²C adapter，I²C-7/8 是 I²C-6
  多路复用通道。本轮只读取 sysfs 中的适配器名称，没有访问总线设备。
- 摄像头 USB 描述符厂商为 Sonix Technology Co., Ltd.，产品名为 `USB 2.0 Camera`，通过
  VIA Labs USB 2.0 Hub 连接；视频接口和 USB Audio 麦克风均已枚举。
- 系统没有在 `/sys/class/power_supply` 暴露可用于确认外部适配器规格的信息。
- 原厂目录存在时间跨度较大：`Arm`、`dofbot_ws`、`catkin_ws` 的目录时间为 2022 年，
  `Dofbot` 目录时间为 2025 年。目录时间不能代表软件版本，仅用于镜像来源核对。
- `/etc/NetworkManager/system-connections` 下存在 Yahboom/Dofbot 厂家连接配置；为避免读取或
  泄露网络凭据，本次只确认文件名，没有查看内容。

### 必须现场查看后填写

下列项目无法通过 SSH 安全、可靠地确定：

1. DOFBOT 机身或包装上的准确型号；
2. 扩展板 PCB 正反面的型号、版本和丝印；
3. 电源适配器铭牌上的输出电压、电流、极性和功率；
4. 摄像头外壳或包装上的商品型号；
5. 摄像头实际安装位置、朝向、是否镜像/倒置以及到桌面的高度。

拍照时应避免把 Wi-Fi 密码、登录密码、设备序列号或课程私密信息收入可提交文档。
