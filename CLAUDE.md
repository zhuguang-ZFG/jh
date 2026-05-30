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

## AI 模型路由策略

VPS 上有 13 个免费 AI 模型（vps-ai-router MCP），按任务类型分流：

| 任务类型 | 优先模型 | 备选 |
|---------|---------|------|
| 简单代码生成 | xf-code (讯飞) | or-code (Qwen3 Coder) |
| 复杂推理/架构 | ds-reason (DeepSeek R1) | or-nemo (Nemotron 120B) |
| 通用问答 | ds-chat (DeepSeek V4) | mi-chat (MIMO) |
| 创意/文案 | or-l3 (Llama 3.3) | mi-pro (MIMO Pro) |

**使用规则：**
- 简单/重复性代码任务 → 优先用 `ai_ask` 调免费模型，节省 Claude 额度
- 架构设计、复杂调试、关键业务逻辑 → 用 Claude 直接处理
- 不确定的质量 → 多模型交叉验证（问 2 个模型，对比结果）

## 代码质量保证

无论用哪个模型生成的代码，必须经过以下流程：

1. **生成** → 免费模型或 Claude 写代码
2. **审查** → Claude review 代码逻辑和边界情况
3. **验证** → lint + test + VPS 实际运行
4. **提交** → 通过后才 commit

关键原则：**免费模型写初稿，Claude 把质量关。**

## VPS 验证闭环

写完 Python 代码后，主动用 `vps-code-exec` 的 `run_python` 或 `run_shell` 在 VPS 上验证。
原则：声称能跑 = 必须跑过。`lint` / `format` 在提交前主动调用。
