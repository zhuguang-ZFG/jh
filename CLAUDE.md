# Project: jh — Development Environment & Tooling

## 项目仪表盘

**新开会话先读**: `docs/PROJECT-DASHBOARD.md` — 包含所有项目状态、基础设施、已知问题。

## Memory

跨会话记忆使用文件记忆系统（`C:/Users/zhugu/.claude/projects/D--jh/memory/`），由 Claude Code 自动管理。
本地 memory MCP 提供知识图谱级别的记忆查询。

## Project Structure

- `esp32S_XYZ/` — AI 写字机（双 ESP32-S3，主力项目）
- `edgetunnel/` — Cloudflare Workers 代理节点
- `MediaCrawler/` — 媒体爬虫
- `scripts/` — 辅助脚本
- `hooks/` — Claude Code hooks
- `docs/` — 项目文档、工作记录、资源清单
- `*.py` — MCP server 脚本和工具

## Key Conventions

- Python 优先，FastAPI 做 API 服务
- VPS 部署走 `deploy.sh` 或 scp 到 119.45.204.198
- Telegram bot 通知走 @claude_zhubot
- Git: 当前在 master 分支，按需创建 feature 分支
- 代理: edgetunnel 订阅为主，机场备用

## VPS 验证闭环

写完 Python 代码后，主动用 `vps-code-exec` 的 `run_python` 或 `run_shell` 在 VPS 上验证。
原则：声称能跑 = 必须跑过。`lint` / `format` 在提交前主动调用。
