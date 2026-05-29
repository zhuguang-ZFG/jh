# VPS MCP Server Infrastructure

> 腾讯云 VPS (119.45.204.198 / Tailscale 100.94.119.7) 上的 MCP 服务器集群，为 Claude Code 提供远程工具能力。

## 架构概览

```
Windows 11 (Claude Code)
    │ Tailscale
    ▼
┌─ VPS (TencentOS 4, 4C8G) ──────────────────────────┐
│                                                      │
│  :8765  memory-mcp      SQLite FTS5 + fastembed      │
│  :8767  web-mcp         Bing 搜索 / URL 抓取 / 翻译  │
│  :8768  db-mcp          MySQL + PostgreSQL 查询       │
│  :8769  ai-router       多模型智能路由                │
│  :8770  code-exec-mcp   Python / Shell / Lint / 格式化│
│                                                      │
│  :7890  mihomo (Clash Meta) — 全局代理               │
└──────────────────────────────────────────────────────┘
```

## 服务清单

| 服务 | 端口 | systemd 服务 | 工具 |
|------|------|-------------|------|
| vps-memory | 8765 | `memory-mcp.service` | `add_memory`, `search_memories`, `get_recent`, `get_all`, `delete_memory`, `memory_stats` |
| vps-web-search | 8767 | `web-mcp.service` | `web_search`, `fetch_url`, `translate` |
| vps-database | 8768 | `db-mcp.service` | `db_query`, `db_list_tables`, `db_describe` |
| vps-ai-router | 8769 | `ai-router.service` | `ai_auto`, `ai_ask`, `ai_list_models` |
| vps-code-exec | 8770 | `code-exec-mcp.service` | `run_python`, `run_shell`, `lint`, `format` |

## 客户端配置

`~/.claude/.mcp.json`:

```json
{
  "mcpServers": {
    "vps-web-search": {
      "type": "http",
      "url": "http://100.94.119.7:8767/",
      "description": "Web: web_search(Bing), fetch_url, translate(Google)"
    },
    "vps-database": {
      "type": "http",
      "url": "http://100.94.119.7:8768/",
      "description": "DB: db_query, db_list_tables, db_describe MySQL+PostgreSQL"
    },
    "vps-ai-router": {
      "type": "http",
      "url": "http://100.94.119.7:8769/",
      "description": "AI Router: ai_auto (smart routing), ai_ask (pick model), ai_list_models"
    },
    "vps-memory": {
      "type": "http",
      "url": "http://100.94.119.7:8765/",
      "description": "Memory v2.0: add_memory, search_memories(FTS5+vector), get_recent, get_all, delete_memory, memory_stats"
    },
    "vps-code-exec": {
      "type": "http",
      "url": "http://100.94.119.7:8770/",
      "description": "Code Exec: run_python, run_shell, lint, format"
    }
  }
}
```

## vps-memory v2.0 混合搜索

### 架构

- **存储**: SQLite (`/opt/memory-mcp/data/memories.db`)，WAL 模式
- **全文搜索**: FTS5 — 中英文关键词匹配，零延迟
- **语义搜索**: fastembed (`BAAI/bge-small-en-v1.5`) — 384 维向量，中英文跨语言语义匹配
- **混合排序**: FTS5 rank (40%) + 向量余弦相似度 (60%)

### 搜索模式

| 查询 | FTS5 | 向量 | 模式 |
|------|------|------|------|
| 精确关键词匹配 | ✅ 命中 | ✅ 命中 | `hybrid` |
| 中文查英文 / 英文查中文 | ❌ | ✅ 命中 | `hybrid` |
| 模糊语义 | ❌ | ✅ 命中 | `hybrid` |
| 模型未加载 | ✅ | ❌ | `FTS-only` |

### 示例

```
查询: "deploy workflow"
结果: [hybrid]
  [workflow] 部署流程：先验证再推GitHub再部署到VPS    ← 向量命中
  [workflow] VPS deploy workflow: verify then push...  ← FTS5 命中
```

### 依赖

```
pip install fastembed  # ~50MB，含 ONNX Runtime
# 模型 BAAI/bge-small-en-v1.5 自动下载到 ~/.cache/fastembed/
# 首次下载通过 HF_ENDPOINT=https://hf-mirror.com 加速
```

## systemd 服务配置

所有服务统一放置在 `/etc/systemd/system/`，配置 `Restart=always` 实现崩溃自动恢复。

### memory-mcp.service

```ini
[Unit]
Description=Memory MCP Server
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3.12 /opt/memory-mcp/memory_mcp_server.py
Restart=always
RestartSec=10
Environment=HF_ENDPOINT=https://hf-mirror.com

[Install]
WantedBy=multi-user.target
```

### code-exec-mcp.service

```ini
[Unit]
Description=VPS Code Execution MCP Server
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3.12 /opt/memory-mcp/code_exec_mcp.py 8770
Restart=always
RestartSec=5
User=root
WorkingDirectory=/tmp

[Install]
WantedBy=multi-user.target
```

### web-mcp.service

```ini
[Unit]
Description=Web Search MCP Server
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3.12 /opt/memory-mcp/web_mcp_server.py 8767
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

## 运维命令

```bash
# 查看所有 MCP 服务状态
systemctl status memory-mcp web-mcp db-mcp ai-router code-exec-mcp

# 重启单个服务
systemctl restart memory-mcp

# 查看日志
journalctl -u memory-mcp -f --no-pager

# 端口检查
ss -tlnp | grep -E '876[5-9]|8770'

# 测试 MCP 协议
curl -s -X POST http://localhost:8765/ -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

## 源码位置

| 文件 | VPS 路径 | 本地副本 |
|------|----------|----------|
| memory_mcp_server.py | `/opt/memory-mcp/memory_mcp_server.py` | `memory_mcp_server.py` |
| web_mcp_server.py | `/opt/memory-mcp/web_mcp_server.py` | `web_mcp_server.py` |
| db_mcp_server.py | `/opt/memory-mcp/db_mcp_server.py` | `db_mcp_server.py` |
| ai_router_mcp.py | `/opt/memory-mcp/ai_router_mcp.py` | `ai_router_mcp.py` |
| code_exec_mcp.py | `/opt/memory-mcp/code_exec_mcp.py` | `code_exec_mcp.py` |

## 注意事项

- 所有 MCP 服务器通过 Tailscale 内网访问，不暴露公网
- code-exec-mcp 以 root 身份运行，可执行任意 VPS 命令
- fastembed 模型缓存在 `~/.cache/fastembed/`，约 130MB
- 修改 `.mcp.json` 后需重启 Claude Code 才能加载新服务器
