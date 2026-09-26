# DOFBOT 真机接收与首次启动

## 今晚完成标准

- 系统盘能够正常启动 Jetson。
- 游戏本能够通过网线 SSH 登录 Jetson。
- USB 摄像头至少有一个设备节点可以稳定出图。
- `Arm_Lib` 或课程提供的等效接口能够导入。
- 六路舵机角度能够只读获取。
- 仅在确认安全后完成一个关节的低速、小幅点动并回位。
- 记录系统、相机、舵机和原厂服务信息。

不要在首次启动时直接运行自动抓取、舞蹈、六舵机扫描或未经核对的 HOME 动作。

## 配件检查

- [ ] DOFBOT 机械臂、Jetson/主控板和扩展板
- [ ] 原装电源和铭牌照片
- [ ] TF 卡、U 盘或 SSD 系统盘及标签照片
- [ ] USB 摄像头和连接线
- [ ] 网线
- [ ] HDMI、显示器、键盘和鼠标
- [ ] Wi-Fi 天线或无线网卡
- [ ] 原厂积木、地图或标定板
- [ ] 登录用户名、密码、教程、源码和系统镜像地址
- [ ] 已知坏件、舵机偏移和原厂自动启动服务说明

## 断电接线顺序

1. 机械臂固定在平稳桌面，周围清空至少 50 cm。
2. 插入系统盘。
3. 连接显示器、键盘、鼠标和网线。
4. 连接 USB 摄像头。
5. 最后连接原装电源。
6. 首次动作时手始终靠近电源开关。

不要用不确定规格的适配器，不要用笔记本 USB 为整机供电，不要在舵机通电时强行掰动。

## 系统信息采集

在 Jetson 终端逐条执行，并把结果填入 `docs/CALIBRATION.md`：

```bash
cat /etc/os-release
uname -a
cat /etc/nv_tegra_release
python3 --version
hostname
hostname -I
ip -br addr
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS
df -h
free -h
printenv ROS_DISTRO
which roscore
which ros2
nvcc --version
```

部分旧 Jetson 没有 `ros2` 或 `nvidia-smi`，单个命令找不到不代表硬件损坏。首次基线完成前
不要执行系统大版本升级、JetPack 重刷或全局 Python 替换。

## 摄像头基线

```bash
lsusb
ls -l /dev/video*
v4l2-ctl --list-devices
```

如果没有 `v4l2-ctl`，先记录现状，不要为了这一条命令立刻升级整个系统。用原厂 USB camera
示例或现有 OpenCV 验证 640×480 图像、帧率、方向、曝光和实际设备编号。

## 原厂机械臂环境

```bash
find /home -maxdepth 4 -iname "Arm_Lib*" 2>/dev/null
find /home -maxdepth 4 -iname "*Dofbot*" 2>/dev/null
python3 -c "from Arm_Lib import Arm_Device; print('Arm_Lib OK')"
systemctl --type=service --state=running | grep -Ei "arm|dofbot|yahboom|jupyter|ros"
ps aux | grep -Ei "Arm_Lib|dofbot|yahboom|roslaunch"
```

如果已经有后台服务控制舵机，不要同时启动自定义控制程序。先记录服务名和原厂启动方式。

## 先读取，后移动

使用原厂“读取舵机角度”示例读取 1–6 号舵机，每个 ID 连续读取五次。暂时不要把所有舵机
写到 90°。将读数、实际关节名称和是否稳定填进 `docs/CALIBRATION.md`。

首次动作测试只能在确认当前角度和机械净空后进行：

- 一次测试一个关节。
- 目标只偏移 3–5°。
- 动作时间使用 1500–3000 ms。
- 记录真实方向后立即回到原读数。
- 最后才单独测试夹爪。

不要在首次接机时写入舵机偏移。偏移校准可能永久改变零位，应另行备份并在确认机械中位后执行。

## 系统盘备份

确认原厂系统能启动和控制硬件后再关机取盘，在游戏本上制作完整镜像。未确认设备名之前不要
使用 `dd`。系统镜像不提交 GitHub；记录镜像文件名、大小和 SHA-256 即可。
