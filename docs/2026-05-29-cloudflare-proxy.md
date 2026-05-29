# 2026-05-29 工作记录

## 完成事项

### 1. SSH Config 配置
配置了 `~/.ssh/config`，所有服务器一句话可达：
- `ssh tencent` → 腾讯云 (100.94.119.7)
- `ssh lima` → 阿里云 (100.103.82.78)
- `ssh dsw` → 魔搭 PAI-DSW (100.104.249.100)
- `ssh highpc` → 高配 PC (FRP 跳板)
- `ssh node` → 本机 (100.83.32.95)

### 2. Telegram 云存储脚本
创建了 `/root/ai-quant/scripts/telegram_storage.py`：
- `upload <file>` — 上传文件到 Telegram
- `backup <dir>` — 打包备份目录到 Telegram
- `msg <text>` — 发送文本消息

配置了每天凌晨 3 点自动备份 ai-quant 项目到 Telegram。

### 3. Cloudflare Pages + edgetunnel 部署
- 创建了 Cloudflare Pages 项目 `edgetunnel-zhuguang`
- 部署了 edgetunnel (VLESS 代理)
- 绑定了 KV namespace
- 设置了 ADMIN 环境变量
- 访问地址: https://edgetunnel-zhuguang.pages.dev/admin
- 管理密码: admin123456

### 4. 免费资源调研
- free-for.dev 完整调研
- 结论：免费海外 VPS 基本不存在（不要卡的话）
- 最便宜的海外 VPS 是 RackNerd ¥190/年
- 现有方案（机场 + Tailscale 共享）仍是最优解

## 待办
- [ ] edgetunnel admin 面板登录配置（浏览器操作）
- [ ] 获取 VLESS 订阅链接
- [ ] 配置 mihomo 使用 Cloudflare 代理节点
