# Evo-Server Claude Code 配置指南

> 在另一台电脑上配置 Claude Code，自动连接 evo-server (119.45.204.198:8090)

---

## 前提条件

- Python 3.8+ 已安装（`python --version` 确认）
- Claude Code 已安装（`claude --version` 确认）
- 能访问 `http://119.45.204.198:8090`（测试：`curl http://119.45.204.198:8090/health`）

---

## 第一步：放置 Hook 文件

在任意位置创建 hooks 目录，例如：

```
C:\Users\<你的用户名>\evo-hooks\
├── evo_hook_context.py      # Write/Edit 时注入知识
├── evo_hook_post_tool.py    # 追踪修改过的文件
├── evo_hook_stop.py         # 会话结束时提取技能/记忆
└── evo_hook_quality.py      # 代码质量分析（可选）
```

**获取方式**：从已配置的机器（D:\jh\hooks\）复制这 4 个文件。

如果 quality hook 报错（缺少 `quality_analyzer`），可以先不用它——其他 3 个 hook 不依赖它。

---

## 第二步：配置 Claude Code Settings

### 方法 A：全局配置（推荐，所有项目生效）

编辑 `%USERPROFILE%\.claude\settings.json`：

```json
{
  "env": {
    "EVO_SERVER": "http://119.45.204.198"
  },
  "hooks": {
    "PreToolUse": [
      {
        "hooks": [
          {
            "command": "python C:/Users/<你的用户名>/evo-hooks/evo_hook_context.py",
            "timeout": 5,
            "type": "command"
          }
        ],
        "matcher": "Write|Edit"
      }
    ],
    "PostToolUse": [
      {
        "hooks": [
          {
            "command": "python C:/Users/<你的用户名>/evo-hooks/evo_hook_post_tool.py",
            "timeout": 5,
            "type": "command"
          }
        ],
        "matcher": "Write|Edit"
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "command": "python C:/Users/<你的用户名>/evo-hooks/evo_hook_stop.py",
            "timeout": 15,
            "type": "command"
          }
        ]
      }
    ]
  }
}
```

**注意**：
- 把 `<你的用户名>` 替换为实际的 Windows 用户名
- 路径分隔符用 `/`（不是 `\`）
- 如果已有 `env` 或 `hooks` 字段，合并进去，不要覆盖

### 方法 B：项目级配置

在项目根目录创建 `.claude/settings.json`，内容同上。

---

## 第三步：配置环境变量（可选）

如果不想写死 VPS 地址到 settings.json，可以用环境变量：

```bash
# PowerShell
[System.Environment]::SetEnvironmentVariable("EVO_SERVER", "http://119.45.204.198", "User")

# 或 Git Bash
echo 'export EVO_SERVER="http://119.45.204.198"' >> ~/.bashrc
```

设置后 hook 会自动读取，settings.json 中可以省略 `env.EVO_SERVER`。

---

## 第四步：验证配置

### 4.1 验证 evo-server 可达

```bash
curl http://119.45.204.198:8090/health
```

应返回类似：
```json
{"ok": true, "stats": {"skills": 136, "patterns": 50, "memories_vec": 0}}
```

### 4.2 手动测试 context hook

```bash
echo '{"file_path":"test.py"}' | python C:/Users/<你的用户名>/evo-hooks/evo_hook_context.py
```

应输出类似：
```
## [!] Avoid These Mistakes
## Relevant Skills
## Past Memories
...
```

### 4.3 手动测试 stop hook

```bash
echo '{"session_id":"test-001","transcript_path":"","relevant_output":"test"}' | python C:/Users/<你的用户名>/evo-hooks/evo_hook_stop.py
```

应输出到 stderr：
```
[evo] Session test-001 logged (success, 0 files, 0 skills extracted)
```

### 4.4 在 Claude Code 中验证

启动 Claude Code，做一个 Edit 操作，观察：
- 终端底部是否闪过 hook 执行（通常不可见，正常）
- 编辑时 Claude 是否自动引用了项目知识（说明 context hook 生效）

---

## 各 Hook 功能说明

| Hook | 触发时机 | 功能 | 超时 |
|------|----------|------|------|
| `evo_hook_context.py` | Write/Edit 前 | 查询 VPS：失败模式、代码规范、技能、模式、最佳实践、**历史记忆** → 注入 Claude 上下文 | 5s |
| `evo_hook_post_tool.py` | Write/Edit 后 | 追踪修改过的文件列表（存临时文件，供 stop hook 使用） | 5s |
| `evo_hook_stop.py` | 会话结束 | 解析 transcript → 提取技能 + 记忆 → 上报 VPS | 15s |
| `evo_hook_quality.py` | Write/Edit 前后 | 代码质量分析（需 quality_analyzer.py） | 5-10s |

### 数据流

```
写文件时:
  Context hook → GET /skills/, /learn/failures, /memories/recall → 注入到 Claude 上下文
  PostToolUse hook → 记录修改了哪些文件

会话结束时:
  Stop hook → POST /session/log, POST /skills/, POST /memories/ → 学习并存储
```

---

## 常见问题

### Q: hook 执行超时怎么办？

A: 增大 timeout 值（seconds）。VPS 网络慢的话设为 8-10。但一般 5 秒够用。

### Q: 报错 `python: command not found`

A: Windows 上 Python 命令可能是 `python3` 或完整路径。改 command 为：
```json
"command": "\"C:/Program Files/Python312/python.exe\" C:/Users/<用户名>/evo-hooks/evo_hook_context.py"
```
或确认 `python` 在 PATH 中：`python --version`

### Q: quality hook 报错 `No module named 'quality_analyzer'`

A: quality hook 需要 `learning/quality_analyzer.py`。两个选择：
1. 也复制 `learning/` 目录到新机器
2. 从 settings.json 中移除 quality hook（不影响其他功能）

### Q: VPS 防火墙拦截了请求

A: 确认 VPS 安全组/iptables 放行 8090 端口。测试：
```bash
curl http://119.45.204.198:8090/health
```

### Q: 记忆注入太多/太少

A: 调整 `evo_hook_context.py` 中的 `min_weight` 参数（默认 0.3）：
- 降低 → 更多记忆（可能有噪音）
- 升高 → 更少记忆（更精准）

---

## 快速配置脚本

保存为 `setup-evo.ps1`，在 PowerShell 中运行：

```powershell
$hooksDir = "$env:USERPROFILE\evo-hooks"
New-Item -ItemType Directory -Force -Path $hooksDir | Out-Null

# 从 VPS 下载 hook 文件（需要先上传到 VPS 或从已配置机器复制）
# 这里假设从 D:\jh\hooks\ 复制（已配置的机器）
Copy-Item "D:\jh\hooks\evo_hook_*.py" -Destination $hooksDir -Force

Write-Host "Hook files copied to: $hooksDir"
Write-Host ""
Write-Host "Now edit: $env:USERPROFILE\.claude\settings.json"
Write-Host "Add the hooks configuration from the setup guide."
```
