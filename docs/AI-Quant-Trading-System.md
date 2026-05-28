# AI Quantitative Trading System

BTC 智能量化交易系统 — 运行在腾讯云 VPS 上，支持多信号融合决策。

## 系统架构

```
VPS (腾讯云 2C2G - TencentOS 3.3)
├── mihomo (Clash Meta)        代理服务，9 节点自动切换
├── Freqtrade                  交易机器人（模拟盘）
│   ├── 多时间框架分析          1h + 4h + 日线联合判断
│   ├── AI 情绪分析             MiMo (小米) 分析 CoinGecko 热门
│   ├── 市场数据                Fear & Greed + 资金费率
│   ├── Hyperopt 优化           自动寻找最优参数
│   ├── 动态仓位管理            根据信号强度 50-200 USDT
│   ├── FreqUI 面板             Web 界面监控
│   └── Telegram 通知           @claude_zhubot 中文推送
├── DCA 定投机器人              每周定投 + 情绪过滤
└── 代理健康监控                每 2 分钟检查，自动重启
```

## 核心组件

### 1. 代理层 (mihomo)

大陆 VPS 无法直连交易所 API，通过 mihomo 代理访问。

- **节点数量**: 9 个（香港 x3、新加坡 x2、台湾、日本、Hysteria2 x2）
- **切换方式**: url-test 自动测速，每 120 秒检测，自动切换到最快节点
- **代理域名**: OKX、Binance、Telegram、CoinGecko、AI API
- **健康监控**: cron 每 2 分钟检查，连续 3 次失败自动重启 mihomo
- **开机自启**: systemd 服务

配置文件: `/root/.config/mihomo/config.yaml`

```bash
# 查看代理状态
systemctl status mihomo

# 查看健康日志
cat /root/ai-quant/logs/proxy_health.log

# 重启代理
systemctl restart mihomo
```

### 2. 交易机器人 (Freqtrade)

基于 Freqtrade 2026.4 框架，BTC/USDT 现货交易。

#### 策略逻辑

```
信号生成:
  1h K 线 → EMA(5) 交叉 EMA(47) → 买入信号
  RSI < 65 → 确认不超买
  成交量 > 20 周期均量 → 确认有量

多时间框架过滤:
  4h EMA(12) > EMA(26) → 4h 趋势看多
  日线 EMA(10) > EMA(30) → 日线趋势看多
  三个时间框架必须同时看多才允许买入

AI 情绪过滤:
  CoinGecko 热门 → MiMo AI 分析 → 情绪分数 (-1 ~ 1)
  score < -0.3 → 拦截买入（市场情绪太差）
  score < -0.7 → 强制卖出（恐慌状态）

市场数据:
  Fear & Greed Index (alternative.me): 反向指标
  资金费率 (Binance): 超买/超卖信号
  综合得分 = FNG 信号 × 0.4 + Funding 信号 × 0.3

动态仓位:
  综合信号 > 0.8 且 3/3 时间框架对齐 → 200 USDT (1.2x)
  综合信号 0.5-0.8 → 150 USDT
  综合信号 0.2-0.5 → 100 USDT
  综合信号 < 0.2 → 50 USDT
```

#### Hyperopt 优化结果 (90 天数据)

| 参数 | 默认值 | 优化值 | 说明 |
|------|--------|--------|------|
| EMA 快线 | 9 | **5** | 更灵敏 |
| EMA 慢线 | 21 | **47** | 更长周期过滤噪音 |
| RSI 买入上限 | 70 | **65** | 更严格入场 |
| RSI 卖出下限 | 75 | **63** | 更早止盈 |

| 指标 | 优化前 | 优化后 |
|------|--------|--------|
| 胜率 | 30% | **58.3%** |
| 总收益 | +1.92 USDT | **+6.80 USDT** |
| 平均持仓 | 19h | **5.5h** |

#### 风控设置

- 止损: -5%
- 追踪止盈: 盈利 4% 后启动，回撤 2% 止盈
- 模拟盘钱包: 1000 USDT
- 最大持仓: 1 个

### 3. AI 情绪分析模块

支持多个 AI 供应商，使用 OpenAI 兼容 API。

#### 支持的供应商

| 供应商 | 模型 | 说明 |
|--------|------|------|
| **MiMo** (默认) | mimo-v2.5 | 小米推理模型，免费额度 |
| DeepSeek | deepseek-chat | ¥1/百万 token |
| SiliconFlow | DeepSeek-V3 | 送 ¥14 免费额度 |
| OpenRouter | 多模型 | 一个 key 用所有模型 |
| MiniMax | MiniMax-Text-01 | 有免费额度 |
| Qwen | qwen-plus | 阿里通义 |

#### 工作流程

```
每小时触发一次:
  1. CoinGecko API → 获取热门币种 (免费，无需 key)
  2. 构造分析 prompt → 发送到 MiMo API
  3. MiMo 返回 JSON → {score, confidence, reason}
  4. 结果缓存，下一小时更新
```

#### 数据源

| 数据 | 来源 | 费用 | 代理 |
|------|------|------|------|
| 热门币种 | CoinGecko API | 免费 | 需要 |
| 情绪分析 | MiMo API | 免费额度 | 需要 |
| Fear & Greed | alternative.me | 免费 | 需要 |
| 资金费率 | Binance API | 免费 | 不需要 |
| 持仓量 | Binance API | 免费 | 不需要 |
| K 线数据 | OKX API | 免费 | 需要 |

### 4. FreqUI 面板

Web 界面，浏览器访问。

- 地址: `http://<VPS_IP>:8080`
- 用户名: admin
- 密码: (在 config.json 中配置)

功能:
- 实时 K 线图
- 交易历史和盈亏曲线
- 当前持仓状态
- 手动买入/卖出
- 策略参数查看

### 5. Telegram 通知

Freqtrade 内置 Telegram Bot，中文翻译版。

- Bot: @claude_zhubot
- 支持命令: /status, /profit, /balance, /showconfig, /start, /stop, /forcesell

通知内容:
- 买入/卖出信号
- 成交通知
- AI 情绪变化
- 系统状态变更

### 6. DCA 定投机器人

独立脚本，每周一定投 BTC，根据市场情绪调整金额。

```
逻辑:
  FNG < 25 (极度恐惧) → 买 200 USDT (逆向加仓)
  FNG 25-80 (正常)     → 买 100 USDT (正常定投)
  FNG > 80 (极度贪婪) → 跳过 (等待回调)

定时: 每周一 10:00 自动执行
通知: 每次执行后 Telegram 推送报告
```

模式:
- `--dry-run`: 只显示决策，不通知不买入
- `--dry-run-notify`: 显示决策 + 发 Telegram，不买入
- 无参数: 实际执行买入

## 文件结构

```
VPS 文件:
/root/freqtrade/                          # Freqtrade 项目
├── config.json                           # 主配置
├── run_hyperopt.sh                       # Hyperopt 脚本
└── user_data/
    ├── data/okx/                         # K 线数据
    ├── logs/                             # 日志
    └── strategies/
        ├── BtcTrendFollower.py           # 主策略
        ├── ai_sentiment.py               # AI 情绪模块
        └── market_data.py                # 市场数据模块

/root/ai-quant/                           # AI 量化项目
├── .env                                  # API 凭证 (不提交)
├── scripts/
│   ├── dca_bot.py                        # DCA 定投脚本
│   └── proxy_monitor.sh                  # 代理健康监控
└── logs/
    ├── proxy_health.log                  # 代理健康日志
    ├── hyperopt.log                      # Hyperopt 结果
    └── dca.log                           # DCA 定投日志

/root/.config/mihomo/                     # 代理配置
└── config.yaml                           # mihomo 配置

/etc/systemd/system/
├── mihomo.service                        # 代理服务
└── freqtrade.service                     # 交易服务
```

## 常用命令

### 服务管理

```bash
# Freqtrade
systemctl status freqtrade                # 查看状态
systemctl restart freqtrade               # 重启
systemctl stop freqtrade                  # 停止
journalctl -u freqtrade -f               # 实时日志

# mihomo 代理
systemctl status mihomo                   # 查看状态
systemctl restart mihomo                  # 重启
```

### 查看数据

```bash
# OKX 余额 (通过代理)
export https_proxy="http://127.0.0.1:7890"
python3.11 -c "
import ccxt
ex = ccxt.okx({'apiKey': 'YOUR_KEY', 'secret': 'YOUR_SECRET', 'password': 'YOUR_PASS', 'proxies': {'https': 'http://127.0.0.1:7890'}})
bal = ex.fetch_balance()
for c, a in bal['total'].items():
    if a and a > 0: print(f'{c}: {a}')
"

# BTC 实时价格
curl -s -x http://127.0.0.1:7890 "https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT" | python3.11 -c "import sys,json; print(json.load(sys.stdin)['data'][0]['last'])"

# Fear & Greed Index
curl -s "https://api.alternative.me/fng/?limit=1" | python3.11 -c "import sys,json; d=json.load(sys.stdin)['data'][0]; print(f'FNG: {d[\"value\"]}/100 ({d[\"value_classification\"]})')"
```

### Hyperopt 调参

```bash
export http_proxy="http://127.0.0.1:7890"
export https_proxy="http://127.0.0.1:7890"
cd /root/freqtrade

# 下载更多数据
python3.11 -m freqtrade download-data --config config.json --days 90 --timeframe 1h --prepend

# 运行优化
python3.11 -m freqtrade hyperopt \
  --config config.json \
  --strategy BtcTrendFollower \
  --hyperopt-loss SharpeHyperOptLoss \
  --spaces buy sell \
  --epochs 50

# 查看结果
cat /root/ai-quant/logs/hyperopt.log
```

### DCA 定投

```bash
# 测试模式 (不买入不通知)
python3.11 /root/ai-quant/scripts/dca_bot.py --dry-run

# 测试模式 (发 Telegram 通知)
python3.11 /root/ai-quant/scripts/dca_bot.py --dry-run-notify

# 实际执行 (买入 + 通知)
python3.11 /root/ai-quant/scripts/dca_bot.py
```

## 安全注意事项

- `.env` 文件包含 API 凭证，**不要提交到 Git**
- OKX API Key 只给「读取 + 交易」权限，**不给提币权限**
- 生产环境建议设置 IP 白名单（注意代理出口 IP 会变）
- API Key 泄露后立即在交易所重新生成
- `config.json` 包含密码，**不要提交到 Git**

## 依赖

- Python 3.11
- Freqtrade 2026.4
- ccxt 4.5.56
- TA-Lib
- mihomo (Clash Meta) v1.19.8

## 费用

| 项目 | 月费 |
|------|------|
| VPS (腾讯云 2C2G) | ~30 元 |
| 代理 (moe233) | 已有订阅 |
| MiMo API | 免费额度 |
| OKX 交易手续费 | 按交易量 |
| **总计** | **~30 元/月** |

## 风险提示

- 本系统仅供学习和研究，不构成投资建议
- 加密货币市场波动剧烈，可能造成资金损失
- 模拟盘表现不代表实盘结果
- 建议先跑 3-6 个月模拟盘再考虑实盘
- 量化交易不能保证盈利，大部分散户量化最终亏损
- 定投策略 (DCA) 长期来看比频繁交易更稳健

## 更新日志

- 2026-05-28: 初始搭建，完成全部组件
  - mihomo 代理 (9 节点自动切换)
  - Freqtrade 多时间框架 + AI 情绪策略
  - Hyperopt 参数优化
  - 动态仓位管理
  - FreqUI 面板
  - Telegram 中文通知
  - DCA 情绪定投
  - 代理健康监控
