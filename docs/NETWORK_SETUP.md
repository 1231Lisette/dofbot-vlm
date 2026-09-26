# 游戏本与 Jetson 网线配置

## 推荐拓扑

```text
互联网 ← Wi-Fi → Ubuntu 游戏本 ← 网线 → Jetson / DOFBOT
```

正式控制使用固定地址：

| 设备 | IPv4 | 掩码 | 网关 | DNS |
|---|---|---|---|---|
| Ubuntu 游戏本 | `192.168.77.1` | `/24` | 留空 | 留空 |
| Jetson | `192.168.77.2` | `/24` | 留空 | 留空 |

直连网线的网关必须留空，避免系统把互联网流量错误地发向机械臂网络。游戏本继续使用 Wi-Fi
上网。

## 图形界面配置

在两台 Ubuntu 设备上打开“设置 → 网络 → 有线 → IPv4”，方法选择“手动”，分别填入表中
地址。断开并重新连接有线网络后检查：

```bash
ip -br addr
```

## 命令行配置

先在每台设备查看真实连接名称：

```bash
nmcli -t -f NAME,TYPE connection show
```

假设连接名是 `Wired connection 1`，游戏本执行：

```bash
sudo nmcli connection modify "Wired connection 1" ipv4.method manual ipv4.addresses 192.168.77.1/24 ipv4.gateway "" ipv4.dns ""
sudo nmcli connection up "Wired connection 1"
```

Jetson 执行：

```bash
sudo nmcli connection modify "Wired connection 1" ipv4.method manual ipv4.addresses 192.168.77.2/24 ipv4.gateway "" ipv4.dns ""
sudo nmcli connection up "Wired connection 1"
sudo systemctl enable --now ssh
```

不要照抄连接名；以 `nmcli` 输出为准。

## 连通性验收

游戏本执行：

```bash
ping -c 4 192.168.77.2
ssh 用户名@192.168.77.2
```

Jetson 执行：

```bash
ping -c 4 192.168.77.1
```

验收标准：双向 ping 无丢包，SSH 能登录，游戏本 Wi-Fi 互联网仍正常。

## 临时让 Jetson 通过游戏本联网

需要下载附件时，可以在游戏本把有线 IPv4 模式改成“共享给其他计算机”。Ubuntu 通常会
使用 `10.42.0.0/24` 给 Jetson 分配动态地址。下载完成后切回固定 `192.168.77.0/24`，避免
演示时地址变化。

## 后续服务端口建议

| 服务 | 运行位置 | 建议端口 |
|---|---|---:|
| SSH | Jetson | 22 |
| 硬件控制桥 | Jetson | 9000 |
| 摄像头流或帧接口 | Jetson | 9001 |
| FastAPI / Web | 游戏本 | 8000 |

硬件桥默认只监听有线地址 `192.168.77.2`，不要直接暴露到公共网络。协议至少携带命令序号、
时间戳和超时，断开连接后停止接受旧命令。
