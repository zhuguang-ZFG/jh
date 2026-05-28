# 2026-05-28 工作记录：Tailscale 组网 + 全设备互通

## 概要

完成了多服务器 Tailscale 组网，实现所有设备一句话 SSH 互连，代理全家共享。

## 完成事项

### 1. Tailscale 组网

将 4 台服务器 + 2 台 PC 通过 Tailscale VPN 组成私有网络：

| 节点 | IP | 系统 | 说明 |
|------|-----|------|------|
| tencent-server | 100.94.119.7 | Linux (TencentOS) | 腾讯云 2C2G，主代理+后端 |
| lima-server | 100.103.82.78 | Linux (Alibaba Cloud) | 阿里云，AI路由+语音 |
| node | 100.83.32.95 | Windows | 本机开发机 |
| dsw | 100.104.249.100 | Linux (Ubuntu 22.04) | 魔搭 PAI-DSW 8C32G+GPU |
| highpc | FRP:12022 | Windows | 高配 PC（FRP跳板接入） |
| modal | 100.108.79.77 | Linux | Modal.com（不固定） |

### 2. SSH Config 统一配置

配置 `~/.ssh/config`，所有设备一句话可达：

```bash
ssh tencent   # → 腾讯云 (Tailscale 直连)
ssh lima      # → 阿里云 (Tailscale 直连)
ssh node      # → 本机
ssh dsw       # → 魔搭 PAI-DSW
ssh highpc    # → 高配 PC (FRP 跳板)
```

### 3. 服务器文件系统互挂（SSHFS）

腾讯云和阿里云通过 SSHFS 互挂根目录（只读）：

- 腾讯云 `/mnt/lima/` → 阿里云根目录
- 阿里云 `/mnt/tencent/` → 腾讯云根目录
- 开机自动挂载（fstab），断线自动重连

### 4. 代理全家共享

修改 mihomo 配置，监听从 `127.0.0.1` 改为 `0.0.0.0`：

- `allow-lan: true`
- `bind-address: '0.0.0.0'`
- `external-controller: '0.0.0.0:9090'`

所有设备通过 Tailscale 内网 `100.94.119.7:7890` 共用一个机场订阅。

### 5. 本机 SSH Server 安装

Windows 11 Home 不支持内置 OpenSSH Server，手动安装：

- 下载 OpenSSH-Win64 ZIP
- 解压到 `C:\Users\zhugu\OpenSSH-Win64`
- 注册为 Windows 服务（`sc create sshd`）
- 配置 `administrators_authorized_keys` 权限

### 6. PAI-DSW 接入

魔搭 PAI-DSW 以 userspace networking 模式加入 Tailscale：

```bash
tailscaled --tun=userspace-networking --socks5-server=localhost:1055 &
tailscale up
```

限制：容器环境无 TUN，只能走 DERP 中继（~320ms）。

## 调研事项

### 免费海外 VPS 调研

结论：2026 年不要信用卡的免费海外 VPS 基本不存在。

- Oracle Cloud 永久免费但要卡
- Fly.io 要卡
- Hax.co.id/Woiden.id 免费但不稳定
- 最便宜可行方案：RackNerd ~¥190/年

### 自建代理节点调研

结论：自建节点体验不如现有机场。

- 美国 VPS 延迟 150-250ms，看不了视频
- 亚洲 VPS（HK/JP）要 ¥300-800/年
- 现有机场 + Tailscale 共享已是最优方案

## 配置文件变更

- `~/.ssh/config` — 新增 tencent/lima/node/dsw/highpc 主机配置
- 腾讯云 `/root/.config/mihomo/config.yaml` — allow-lan 改为 true
- 腾讯云/阿里云 `/etc/fstab` — 新增 SSHFS 挂载条目
- 阿里云 `/etc/profile.d/proxy.sh` — 代理环境变量
- 本机 OpenSSH Server — 新安装并注册服务
