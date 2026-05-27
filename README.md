# Evo-Server

个人编程进化平台 — 跨会话长期记忆 + 自主学习 + 自评进化 + Telegram 交互。

## 架构

```
本地 Windows (Claude Code / Codex CLI)
    │ API calls
    ▼
腾讯云 VPS (2C2G, 南京)
    ├── evo-server (FastAPI, port 8090, ~35MB RAM)
    │   ├── REST API: /memory, /session, /skills, /evolutions
    │   ├── Telegram Bot (webhook, inline keyboard 审批)
    │   ├── APScheduler (每周进化 + 每日维护)
    │   └── SQLite WAL (evo.db)
    ├── Nginx (反代 + SSL)
    └── CF Worker (Telegram API 代理, GFW bypass)
```

## 核心能力

### 统一记忆系统

| 层级 | 名称 | 用途 | 衰减策略 |
|------|------|------|----------|
| L0 | meta_rules | 不可变规则（编码规范、架构约束） | 无 |
| L1 | skills | 已验证的编程技能 | EMA 权重（成功 +5%，失败 -10%） |
| L2 | patterns | 从开源项目学到的代码模式 | 按置信度排序 |
| L3 | sessions | 会话摘要（自动压缩 >30 天） | 保留 lessons，清除 files |
| L4 | evolution | 进化提案和评估记录 | 三重门控审批 |

### 进化闭环

```
编码会话 → 记录结果 → 分析统计 → 提出改进 → Telegram 审批 → 应用变更
    ↑                                                        │
    └──────────────── 改进后的策略/技能/模式 ←────────────────┘
```

**三重门控**：
- 证据数 ≥ 3（至少 3 个会话支撑）
- 通过率 ≥ 80%
- 人工确认（Telegram inline keyboard）

### GitHub 自主学习

每日自动：
1. 搜索 GitHub trending repos（按技术栈过滤）
2. 克隆 top 项目，扫描代码模式
3. 提取架构模式、最佳实践
4. 写入 patterns 表

### 双 CLI 集成

- **Claude Code**: hooks 注入/提取记忆
- **Codex CLI**: shell wrapper 自动记录

## 技术栈

- **服务端**: Python 3.11 + FastAPI + Uvicorn
- **数据库**: SQLite (WAL mode)
- **调度**: APScheduler (异步)
- **HTTP 客户端**: httpx (异步)
- **Telegram**: 原生 Bot API (webhook)
- **TTS**: 小米 MiMo (免费语音模型)
- **部署**: systemd + Nginx + Cloudflare Worker
- **CI/CD**: GitHub Actions

## 部署

### VPS 要求

- 2C2G / 50GB SSD / TencentOS
- Python 3.11+
- Nginx
- 公网 IP: 119.45.204.198

### 环境变量

```bash
# .env
EVO_HOST=0.0.0.0
EVO_PORT=8090
EVO_DB_PATH=/opt/evo-server/data/evo.db
EVO_API_KEY=your-api-key

TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_WEBHOOK_SECRET=your-secret
TELEGRAM_OWNER_ID=0
TELEGRAM_API_BASE=https://tg.zhuguang.ccwu.cc

MIMO_API_KEY=your-mimo-key

GITHUB_TOKEN=your-github-token
EVO_LEARN_LANGUAGES=python,rust,go,typescript
```

### 快速部署

```bash
# 1. 克隆项目
git clone https://github.com/zhuguang-ZFG/jh.git
cd jh

# 2. 安装依赖
pip install -r evo_server/requirements.txt

# 3. 配置环境变量
cp .env.example .env
vim .env

# 4. 启动服务
python -m uvicorn evo_server.main:app --host 0.0.0.0 --port 8090

# 5. 配置 systemd (生产环境)
cp deploy/evo-server.service /etc/systemd/system/
systemctl enable --now evo-server
```

## API 端点

| 方法 | 路径 | 用途 | 认证 |
|------|------|------|------|
| GET | `/health` | 健康检查 + 统计 | 无 |
| POST | `/memory/query` | 查询记忆 | API Key |
| POST | `/memory/add` | 添加记忆 | API Key |
| POST | `/session/log` | 记录会话 | API Key |
| GET | `/skills` | 列出技能 | API Key |
| POST | `/skills/recall` | 召回技能 | API Key |
| POST | `/skills/update` | EMA 权重更新 | API Key |
| GET | `/patterns` | 列出模式 | API Key |
| POST | `/patterns/learn` | 学习新模式 | API Key |
| GET | `/evolutions` | 列出提案 | API Key |
| POST | `/evolutions/{id}/approve` | 审批提案 | API Key |
| POST | `/evolutions/create` | 创建提案 | API Key |
| POST | `/telegram/webhook` | Telegram webhook | Secret Token |

## Telegram 命令

| 命令 | 功能 |
|------|------|
| `/status` | 系统状态（记忆数、技能数、会话数） |
| `/memory <query>` | 搜索记忆 |
| `/skills` | 高权重技能列表 |
| `/patterns [domain]` | 学到的代码模式 |
| `/evo` | 待审批提案（inline 审批按钮） |
| `/approve <id>` | 审批通过 |
| `/reject <id>` | 审批拒绝 |
| `/digest` | 周摘要（会话数、通过率、领域分布） |
| `/run` | 手动触发进化分析 |
| `/say <text>` | 文字转语音（MiMo v2.5） |
| `/voice [model] <text>` | 选择语音模型 |
| `/help` | 帮助信息 |

## 项目结构

```
jh/
├── evo_server/                # 服务端核心
│   ├── main.py                # FastAPI 入口 + APScheduler
│   ├── config.py              # 环境变量配置
│   ├── db.py                  # SQLite 连接 + Schema
│   ├── models.py              # Pydantic 数据模型
│   ├── api_memory.py          # /memory CRUD
│   ├── api_session.py         # /session 记录
│   ├── api_skills.py          # /skills EMA 管理
│   ├── api_evo.py             # /evolutions 审批
│   ├── evolution_engine.py    # 进化引擎核心
│   ├── telegram_bot.py        # Telegram Bot
│   ├── tts.py                 # MiMo TTS 客户端
│   └── requirements.txt       # 依赖
├── learning/                  # GitHub 学习引擎
│   ├── github_learner.py      # Trending 搜索 + 分析
│   ├── pattern_extractor.py   # 代码模式提取
│   └── requirements.txt
├── hooks/                     # CLI 集成
│   ├── evo_hook.py            # Claude Code hook
│   └── evo_codex.sh           # Codex wrapper
├── deploy/                    # 部署配置
│   ├── setup_vps.sh           # VPS 初始化
│   ├── evo-server.service     # systemd unit
│   ├── nginx.conf             # Nginx 反代
│   ├── litestream.yml         # SQLite 备份
│   └── cf_worker.js           # CF Worker (TG 代理)
├── .github/workflows/         # CI/CD
├── .env.example               # 环境变量模板
└── README.md
```

## 演进路线

- [x] M0: 本地项目初始化 + SQLite + 核心 API
- [x] M1: VPS 部署 + Nginx + systemd
- [x] M2: Telegram Bot + CF Worker (GFW bypass)
- [x] M3: CLI Hooks (Claude Code + Codex)
- [x] M4: GitHub 学习引擎
- [x] M5: 进化引擎 + Telegram 审批流
- [ ] M6: 端到端测试 + 性能优化
- [ ] M7: 多用户支持 + 权限管理
- [ ] M8: Web Dashboard

## License

Private — 仅供个人使用。
