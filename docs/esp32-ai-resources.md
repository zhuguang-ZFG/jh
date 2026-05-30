# ESP32 + AI 资源清单

> Updated: 2026-05-30
> 为 esp32S_XYZ 项目收集的 AI 相关资源

---

## Espressif 官方 AI 资源

### ESP-Claw ⭐⭐⭐ (1400 stars)
- **地址**: https://github.com/espressif/esp-claw
- **说明**: Espressif 官方 AI Agent 框架，支持 ESP32-S3
- **特性**:
  - MCP 双向通信（Server + Client）
  - 动态 Lua 加载，对话编程
  - 支持 Telegram/微信/QQ 控制
  - 设备上结构化记忆
  - 事件驱动，毫秒级响应
  - 浏览器一键烧录
  - 支持 OpenAI/Claude/DeepSeek/Qwen
- **对项目的价值**:
  - 借鉴 MCP 集成思路
  - Telegram 远程控制写字机
  - 浏览器烧录降低开发门槛
- **当前状态**: 研究阶段，等硬件验证后接入

### ESP-DL
- **地址**: https://github.com/espressif/esp-dl
- **说明**: 高性能深度学习推理库
- **用途**: 在 ESP32-S3 上跑神经网络（手写识别、图像分类）

### ESP-WHO
- **地址**: https://github.com/espressif/esp-who
- **说明**: 人脸检测/识别框架
- **用途**: U8 摄像头 AI 功能

### ESP-ADF
- **地址**: https://github.com/espressif/esp-adf
- **说明**: 音频开发框架（2200 stars）
- **用途**: U8 语音交互增强

### ESP-NN
- **地址**: https://github.com/espressif/esp-nn
- **说明**: 神经网络加速库
- **用途**: 推理性能优化

### MCP 门户
- **地址**: https://mcp.espressif.com
- **说明**: Espressif MCP 服务器门户

---

## U8 现有 MCP 工具（已实现）

U8 固件已内置 MCP Server，暴露以下工具：

### 通用工具
| 工具名 | 说明 |
|--------|------|
| `self.get_device_status` | 获取设备状态 |
| `self.camera.take_photo` | 拍照 |
| `self.audio_speaker.set_volume` | 设置音量 |
| `self.screen.set_brightness` | 设置亮度 |
| `self.screen.set_theme` | 设置主题 |

### 用户专用工具
| 工具名 | 说明 |
|--------|------|
| `self.get_system_info` | 系统信息 |
| `self.reboot` | 重启设备 |
| `self.upgrade_firmware` | OTA 升级固件 |
| `self.screen.get_info` | 屏幕信息 |
| `self.screen.snapshot` | 截屏上传 |
| `self.screen.preview_image` | 预览图片 |

### 写字机专用工具（zhuguang 板）
| 工具名 | 说明 |
|--------|------|
| `self.motor.home` | 回原点 |
| `self.motor.get_status` | 电机状态 |
| `self.motor.get_device_info` | 设备信息 |
| `self.motor.move_abs` | 绝对定位移动 |
| `self.motor.move_rel` | 相对移动 |
| `self.motor.run_path` | 执行路径 |
| `self.motor.pause` | 暂停 |
| `self.motor.resume` | 恢复 |
| `self.motor.stop` | 停止 |

### MCP 通信协议
- 基于 JSON-RPC 2.0
- 通过 WebSocket 或 MQTT 传输
- 消息结构: `{session_id, type: "mcp", payload: {jsonrpc, method, params, id}}`
- 详见: `firmware/u8-xiaozhi/docs/mcp-protocol_zh.md`

---

## 免费 AI API（已接入 VPS ai_router_mcp）

| 后端 | 模型 ID | 说明 |
|------|---------|------|
| DeepSeek | ds-chat | DeepSeek V4 Chat |
| DeepSeek | ds-reason | DeepSeek R1 推理 |
| OpenRouter | or-qwen3 | Qwen3 80B |
| OpenRouter | or-code | Qwen3 Coder |
| OpenRouter | or-nemo | Nemotron 120B |
| OpenRouter | or-l3 | Llama 3.3 70B |
| OpenRouter | or-deepseek | DS V4 Flash |
| OpenRouter | or-gptoss | GPT-OSS 120B |
| OpenRouter | or-glm | GLM-4.5 |
| 讯飞星火 | xf-code | 代码生成/分析 |
| 小米 MIMO | mi-pro | MIMO Pro 推理 |
| 小米 MIMO | mi-chat | MIMO 对话 |
| 小米 MIMO | mi-omni | MIMO 多模态 |

---

## Claude Code 插件（已安装）

| 插件 | 说明 |
|------|------|
| **context-mode** | 大输出省 98% 上下文，跨会话记忆 |
| **backlog-mcp** | 跨会话任务管理 |

---

## 打通计划（等硬件验证后）

### Phase 1: 基础连通
1. 硬件验证 U8 + U1
2. 部署 DeviceServer 到 VPS
3. 小程序连通

### Phase 2: MCP 桥接
4. 在 DeviceServer 上加 WebSocket→MCP HTTP 桥接
5. Claude Code 通过 MCP 直接操控设备
6. Telegram 远程控制

### Phase 3: AI 增强
7. 接入免费 AI 模型做语音/图像分析
8. 手写识别（ESP-DL 或云端 AI）
9. 智能纠错和教学建议

### Phase 4: 产品化
10. 小程序上线
11. 多设备管理
12. OTA 远程升级

---

## 相关文档
- `esp32S_XYZ/STATUS.md` — 项目状态
- `esp32S_XYZ/firmware/u8-xiaozhi/docs/mcp-protocol_zh.md` — MCP 协议文档
- `docs/free-resources-and-integration-plan.md` — 免费资源总览
- `docs/PROJECT-DASHBOARD.md` — 项目仪表盘
