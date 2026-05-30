# Project Dashboard

> 最后更新: 2026-05-30
> 本文件是所有项目的入口，新开会话先读这里。

---

## 基础设施

### 代理 (edgetunnel)
- **状态**: ✅ 运行中，偶尔不稳定
- **架构**: Device → Clash Verge → edgetunnel (CF Workers) → Internet
- **管理后台**: https://vless.donglicao.com/admin
- **Clash 配置**: `C:\Users\zhugu\Desktop\Rt9gHjZ8DXsU.yaml`
- **备用**: moe233 机场节点
- **详见**: `docs/2026-05-29-cloudflare-proxy.md`

### VPS (119.45.204.198)
- **配置**: 2核 / 1.9GB RAM / 50GB 磁盘
- **SSH**: 密钥登录，fail2ban 已启用
- **Tailscale IP**: 100.94.119.7
- **运行服务**: mihomo(7890), nginx(80/443), PostgreSQL(5432), Python bots(8765-8770)
- **详见**: memory/vps-inventory.md

### 域名
- **donglicao.com**: Cloudflare 管理，已接入
- **eu.org**: ⏳ 申请中（待审批）

---

## 项目清单

### 1. esp32S_XYZ (AI 写字机)
- **状态**: ✅ 软件完成 (M0-M6), ⏳ 硬件待验证
- **测试**: 251 passed, 0 failed
- **架构**: U1(电机) + U8(AI语音) + Server(Python/Java) + 小程序(uni-app)
- **下一步**: 硬件在环测试
- **详见**: `esp32S_XYZ/STATUS.md`, `esp32S_XYZ/docs/`
- **AI 资源**: `docs/esp32-ai-resources.md` — ESP-Claw、MCP 工具清单、免费 AI API、打通计划

### 2. ai-quant (量化交易)
- **状态**: ✅ 运行中
- **位置**: VPS `/root/ai-quant/`
- **功能**: DCA 策略、热点追踪、视频生成、产品搜索
- **通知**: Telegram bot @claude_zhubot

### 3. MediaCrawler (媒体爬虫)
- **位置**: `MediaCrawler/`

---

## Claude Code 配置

### Memory 系统
- **位置**: `C:/Users/zhugu/.claude/projects/D--jh/memory/`
- **索引**: MEMORY.md (10 条记忆)
- **类型**: user-profile, project, feedback, reference

### MCP 服务器
- **本地**: CodeGraph, GitNexus, Context7, Playwright, Memory, Seq-Think
- **远程**: SSH-Manager (VPS), GitHub, Filesystem, Claw
- **详见**: `docs/vps-mcp-servers.md`

### Hooks
- **位置**: `hooks/`
- **功能**: auto_format, memory_stop, evo hooks

---

## 已知问题

| 问题 | 状态 | 说明 |
|------|------|------|
| 代理节点不稳定 | ⚠️ | CF Workers 被 GFW 限速 |
| eu.org 域名审批 | ⏳ | 等待中 |
| ESP32 硬件验证 | ⏳ | 需要实物 |
| DeviceServer 未部署 | 待定 | 等硬件验证后再部署 |

---

## 免费资源待配置

| 资源 | 优先级 | 状态 |
|------|--------|------|
| UptimeRobot 监控 | 高 | 未配置 |
| GitHub Actions CI/CD | 中 | 未配置 |
| Cloudflare Email Routing | 中 | 等 eu.org |
| Supabase 数据库 | 低 | 未配置 |

详见: `docs/free-resources-and-integration-plan.md`

---

## 快速命令

```bash
# VPS
ssh vps                     # SSH 到 VPS
mcp__ssh-manager__ssh_execute  # 通过 MCP 执行 VPS 命令

# 项目
cd esp32S_XYZ && make test  # ESP32 测试
cd edgetunnel/edgetunnel-main && npx wrangler deploy  # 部署 edgetunnel

# Git
git push                    # 推送到 GitHub
```
