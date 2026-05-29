# Project: jh — Development Environment & Tooling

## Memory

跨会话记忆使用文件记忆系统（`C:/Users/zhugu/.claude/projects/D--jh/memory/`），由 Claude Code 自动管理。
本地 memory MCP 提供知识图谱级别的记忆查询。

## Project Structure

- `MediaCrawler/` — 媒体爬虫
- `esp32S_XYZ/` — ESP32 相关项目
- `edgetunnel/` — Cloudflare Workers 代理
- `scripts/` — 辅助脚本
- `hooks/` — Claude Code hooks（evo_server）
- `*.py` — MCP server 脚本和工具

## Key Conventions

- Python 优先，FastAPI 做 API 服务
- VPS 部署走 `deploy.sh` 或 scp 到 119.45.204.198
- Telegram bot 通知走 VPS evo-server
- Git: 当前在 master 分支，按需创建 feature 分支

## VPS 验证闭环

写完 Python 代码后，主动用 `vps-code-exec` 的 `run_python` 或 `run_shell` 在 VPS 上验证。
原则：声称能跑 = 必须跑过。`lint` / `format` 在提交前主动调用。
