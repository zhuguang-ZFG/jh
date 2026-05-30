# 2026 免费资源大全

> 采集时间: 2026-05-30 | 来源: VPS 免费模型并行搜索 + Web 抓取

---

## 1. 免费 AI 模型与 API

### 永久免费（无需付费）

| 服务 | 免费额度 | 支持模型 | 注册要求 |
|------|---------|---------|---------|
| **OpenRouter** | 20 req/min, 50 req/day (充值$10可达1000/day) | Hermes 3 405B, Llama 3.2/3.3, DeepSeek V4 Flash, Qwen3-Coder, 20+ 模型 | 无 |
| **Google AI Studio** | 5-30 req/min, 20-14400 req/day, 10K-250K tokens/min | Gemini 3/3.1/2.5 Flash, Gemma 3 (1B-27B) | Google 账号 |
| **NVIDIA NIM** | 40 req/min | 各种开源模型 | 手机验证 |
| **Groq** | 250-14400 req/day, 6K-70K tokens/min | Llama 系列, Whisper, Qwen3-32B, GPT-OSS | 无 |
| **Cerebras** | 30 req/min, 60K tokens/min, 14400 req/day | GPT-OSS-120B, Llama 3.1 8B | 无 |
| **Cohere** | 20 req/min, 1000 req/month | Command A/R/R+, Aya 系列, 共11个模型 | 无 |
| **GitHub Models** | 基于 Copilot 层级 | 40+ 模型含 GPT-5, o系列, DeepSeek-R1, Llama 4 | GitHub 账号 |
| **Cloudflare Workers AI** | 10,000 neurons/day | 40+ 模型含 Llama 3/4, Gemma, Mistral, GPT-OSS | 无 |
| **Mistral La Plateforme** | 1 req/sec, 500K tokens/min, 1B tokens/month | 全部 Mistral 模型 | 手机验证 |
| **HuggingFace** | $0.10/月额度 | 各种开源模型 | 无 |
| **Alibaba Cloud Model Studio** | 1M tokens/模型 | Qwen 系列 | 阿里云账号 |

### 试用额度（用完需付费）

| 服务 | 免费额度 | 支持模型 |
|------|---------|---------|
| **Fireworks** | $1 | 各种开源模型 |
| **Baseten** | $30 | 任意支持的模型 |
| **Nebius** | $1 | 各种开源模型 |
| **Novita** | $0.50 (1年有效) | 各种开源模型 |
| **AI21** | $10 (3个月) | Jamba 系列 |
| **Upstage** | $10 (3个月) | Solar Pro/Mini |
| **Hyperbolic** | $1 | DeepSeek V3, Llama 3.3, Qwen3-Coder |
| **SambaNova Cloud** | $5 (3个月) | DeepSeek, Llama, GPT-OSS |
| **Scaleway** | 1M 免费 tokens | Llama 3.3, Gemma, Mistral, Qwen |
| **Vercel AI Gateway** | $5/月 | 路由到各支持的 provider |

> Sources: [free-llm-api-resources](https://github.com/cheahjs/free-llm-api-resources)

---

## 2. 免费云服务 / VPS / 存储

### 免费 VPS / 计算

| 服务 | 免费规格 | 限制条件 |
|------|---------|---------|
| **Oracle Cloud Forever Free** | 2x AMD VM (1/8 OCPU, 1GB) 或 4 Arm 核, 24GB 内存; 200GB 存储; 10TB 出站流量/月 | 永久免费，区域限制 |
| **Google Cloud** | 1 e2-micro VM, 30GB HDD; Cloud Shell 60h/周; Cloud Run 2M req/月 | e2-micro 限特定区域 |
| **AWS** | 750h/月 t2/t3.micro (12个月); Lambda 1M req/月 (永久) | EC2 限12个月，Lambda 永久 |
| **Azure** | 1 B1S Linux VM + 1 B1S Windows VM (12个月); Azure Pipelines 10个并行 job | VM 限12个月 |
| **IBM Cloud** | Cloudant 1GB, Db2 100MB, API Connect 50K calls/月 | 有限功能 |

### 免费数据库托管

| 服务 | 免费规格 | 数据库类型 |
|------|---------|-----------|
| **Supabase** | 500MB 数据库, 50K MAU, 1GB 文件存储 | PostgreSQL |
| **Neon** | 0.5GB 存储, 191.9h 计算时间/月 | PostgreSQL |
| **PlanetScale** | 5GB 存储, 1B 行读取/月 | MySQL |
| **Upstash Redis** | 10K 命令/天, 256MB | Redis |
| **Upstash Kafka** | 10K 命令/天 | Kafka |
| **MongoDB Atlas** | 512MB 存储 | MongoDB |
| **Cloudflare D1** | 5M 行读取/天, 100K 行写入/天, 1GB | SQLite |
| **Oracle Cloud DB** | 2 个数据库, 各 20GB | Oracle/MySQL |

### 免费对象存储 / CDN

| 服务 | 免费规格 | 限制 |
|------|---------|------|
| **Cloudflare R2** | 10GB/月, 1M Class A, 10M Class B 操作 | 无出站流量费 |
| **Cloudflare CDN** | 无限带宽, 免费 SSL, DDoS 防护, WAF | 无限制 |
| **AWS S3** | 5GB Standard, 20K GET/2K PUT (12个月) | 限12个月 |
| **Google Cloud Storage** | 5GB, 1GB 网络出口 | 限特定区域 |
| **Oracle Cloud Storage** | 10GB | 永久免费 |
| **Azure Blob** | 5GB LRS (12个月) | 限12个月 |
| **Cloudflare Pages** | 500 构建/月, 100 自定义域名, 免费 SSL | 无限带宽 |
| **Vercel** | 100GB 带宽/月, 无限部署 | 个人项目 |
| **Netlify** | 100GB 带宽/月, 300 构建分钟 | 个人项目 |

> Sources: [free-for-dev](https://github.com/ripienaar/free-for-dev)

---

## 3. 免费开发工具

### CI/CD

| 服务 | 免费额度 |
|------|---------|
| **GitHub Actions** | 公共仓库无限; 私有仓库 2000 min/月 (Linux) |
| **GitLab CI/CD** | 400 min/月 (公共), 200 min/月 (私有) |
| **CircleCI** | 6,000 min/月, 无限协作者 |
| **Azure Pipelines** | 10 个并行 job, 无限分钟 (开源) |
| **Bitbucket Pipelines** | 50 min/月 |
| **Bitrise** | 200 构建/月, 10min 构建时间 |
| **Buildkite** | 3 用户, 5K job 分钟/月 |

### 监控 / 日志 / 错误追踪

| 服务 | 免费额度 |
|------|---------|
| **Sentry** | 5K errors/月, 10K transactions/月 |
| **Grafana Cloud** | 10K 指标, 50GB logs, 50GB traces |
| **Datadog** | 5 台主机, 100 万 traces |
| **Papertrail** | 100MB 日志, 7天保留 |
| **Checkly** | 50K check runs/月 |
| **UptimeRobot** | 50 个监控, 5分钟间隔 |

### SSL / 域名 / DNS

| 服务 | 免费额度 | 限制 |
|------|---------|------|
| **Let's Encrypt** | 无限 SSL 证书 | 90天有效，需自动续期 |
| **ZeroSSL** | 3 个证书 | 90天有效 |
| **Cloudflare DNS** | 无限域名, 免费 DDoS/WAF | 需 NS 指向 CF |
| **Freenom** | .tk/.ml/.ga/.cf/.gq (已暂停新注册) | 域名可能被回收 |
| **afraid.org** | 免费子域名 | 有限 TLD |
| **nip.io / sslip.io** | 免费通配符 DNS | 基于 IP 的子域名 |

### 邮箱 / 消息

| 服务 | 免费额度 |
|------|---------|
| **SendGrid** | 100 封/天 (永久) |
| **Mailgun** | 1,000 封/月 (前3个月), 需信用卡 |
| **Brevo (Sendinblue)** | 300 封/天 |
| **AWS SES** | 3,000 封/月 (12个月, 需 EC2) |
| **Resend** | 100 封/天, 1个自定义域名 |
| **ProtonMail** | 500MB 存储, 150 封/天 |
| **Tutanota** | 1GB 存储 |

### 代码质量 / 安全

| 服务 | 免费额度 |
|------|---------|
| **SonarCloud** | 开源项目免费 |
| **Codecov** | 开源项目免费, 1 私有仓库 |
| **Codacy** | 无限公有/私有仓库 |
| **GitGuardian** | 个人/25人以下团队免费 |
| **Dependabot** | GitHub 内置, 永久免费 |
| **Snyk** | 200 次测试/月, 开源项目无限 |
| **Mozilla Observatory** | 免费安全扫描 |

---

## 4. 免费代理 / 网络 / 隧道

### 托管隧道服务

| 工具 | 免费额度 | 协议 | 特点 |
|------|---------|------|------|
| **Cloudflare Tunnel** | 完全免费 | HTTP, TCP, UDP | 生产级，无需开端口 |
| **ngrok** | 1 个隧道, 随机域名 | HTTP, TCP, TLS | 需注册 |
| **localhost.run** | 免费 | SSH-based | 无需安装 |
| **Serveo** | 免费 | HTTP(S), TCP | SSH-based |
| **Pinggy** | 60 分钟超时 | HTTPS, TCP, TLS | 需重新连接 |
| **Microsoft Dev Tunnels** | 免费 | HTTP, TCP | 无自定义域名 |
| **zrok** | 免费层可用 | HTTP, TCP, 文件 | Apache 2.0 |
| **Tabserve.dev** | 免费 | HTTPS | 浏览器内运行 |

### 自托管隧道

| 工具 | 协议 | 特点 |
|------|------|------|
| **frp** | TCP, UDP, QUIC, KCP | 最流行的自托管方案 |
| **rathole** | TCP | Rust 编写, 轻量 |
| **bore** | TCP | 极简, ~400 行 |
| **sish** | SSH, WebSocket | SSH 驱动 |
| **wstunnel** | WebSocket | 协议伪装 |
| **gost** | TCP, UDP, TAP/TUN | 功能最全面 |
| **localtunnel** | HTTP | Node.js |

### VPN / 叠加网络

| 工具 | 免费额度 | 协议 |
|------|---------|------|
| **Tailscale** | 100 台设备, 3 用户 | WireGuard |
| **Headscale** | 自托管无限 | WireGuard (开源 Tailscale) |
| **NetBird** | 自托管无限 | WireGuard |
| **Netmaker** | 自托管无限 | WireGuard |
| **Nebula** | 自托管无限 | 自定义协议 |
| **WireGuard** | 完全免费开源 | WireGuard |
| **ZeroTier** | 25 台设备免费 | 自定义 |

### DDoS 防护 / WAF

| 服务 | 免费额度 |
|------|---------|
| **Cloudflare** | 无限 DDoS 防护, 免费 WAF, 免费 SSL, 无限 CDN |
| **AWS Shield Standard** | 免费基础 DDoS 防护 |
| **Google Cloud Armor** | 免费基础策略 |

> Sources: [awesome-tunneling](https://github.com/anderspitman/awesome-tunneling)

---

## 5. 免费综合资源

### 代码仓库 / 项目管理

| 服务 | 免费额度 |
|------|---------|
| **GitHub** | 无限公有/私有仓库, Actions, Pages, Copilot |
| **GitLab** | 无限仓库, 5 协作者, CI/CD, 容器注册 |
| **Gitee** | 5 人团队, 1000 仓库 |
| **Bitbucket** | 无限仓库, 5 用户, CI/CD |
| **Codeberg** | 无限仓库, 静态托管, CI/CD |
| **Linear** | 无限成员(小团队), 无限 issues |
| **Notion** | 无限页面, 5MB 文件上传 |
| **Huly** | 无限用户, 10GB 存储 |

### 设计 / 素材

| 服务 | 免费额度 |
|------|---------|
| **Figma** | 3 个文件, 无限查看者 |
| **Canva** | 基础功能免费 |
| **Unsplash** | 免费高质量图片, 无版权限制 |
| **Pexels** | 免费图片和视频 |
| **Pixabay** | 免费图片/视频/音乐 |
| **Font Awesome** | 2000+ 免费图标 |
| **Iconfont** | 阿里图标库, 完全免费 |
| **Google Fonts** | 免费字体 |
| **Heroicons** | 免费 SVG 图标 |
| **undraw.co** | 免费插图 |

### 向量数据库 / 消息队列

| 服务 | 免费额度 |
|------|---------|
| **Pinecone** | 2GB 存储, 100万次查询/月 |
| **Qdrant Cloud** | 1GB 存储, 1个集群 |
| **Zilliz (Milvus)** | 免费层可用 |
| **Turso (LibSQL)** | 500 数据库, 9GB 存储, 1B 行读取/月 |
| **Upstash** | Redis/Kafka/QStash 各有免费层 |
| **Cloudflare Queues** | 1M 操作/月 |

### Webhook / API 工具

| 服务 | 免费额度 |
|------|---------|
| **Svix** | 50K webhook 消息/月 |
| **Webhook.site** | 免费 webhook 调试 |
| **RequestBin** | 免费请求检查 |
| **Postman** | 基础功能免费 |
| **Hoppscotch** | 开源, 完全免费 |
| **Insomnia** | 基础功能免费 |
| **Tavily AI** | 1,000 请求/月 (AI 搜索) |
| **News API** | 100 查询/天 |
| **OCR.Space** | 25K 请求/月, 1MB 限制 |

### 团队协作

| 服务 | 免费额度 |
|------|---------|
| **Slack** | 无限用户 (功能限制) |
| **Discord** | 无限用户, 语音/视频/屏幕共享 |
| **Telegram** | 免费消息和通话 |
| **Zoom** | 40 分钟会议 |
| **Cal.com** | 无限会议, 自托管免费 |
| **Calendly** | 1 个日历连接, 无限会议 |
| **Miro** | 3 个白板 |

---

## 你已经在用的免费资源

根据项目现状整理：

| 资源 | 用途 | 免费额度 |
|------|------|---------|
| **Cloudflare** | CDN/DNS/DDoS/ECH/Workers | 已在用 edgetunnel + cfnew |
| **OpenRouter** | 免费 AI 模型路由 | 25+ 免费模型 (VPS AI Router) |
| **GitHub** | 代码仓库 + Actions CI/CD | 已在用 |
| **VPS (119.45.204.198)** | 免费 AI 模型路由 + 代理 | 自建基础设施 |
| **Tailscale** | VPN 内网 | 已在用 |
| **Let's Encrypt** | SSL 证书 | 已在用 |

---

## 可以立即接入的推荐

按实用程度排序：

1. **Supabase** — 免费 PostgreSQL 托管 (500MB), 可替代自建数据库场景
2. **Cloudflare R2** — 10GB 免费 S3 兼容存储, 零出站费用
3. **Sentry** — 免费错误追踪 (5K/月)
4. **Grafana Cloud** — 免费监控全家桶 (10K指标 + 50GB日志)
5. **SendGrid** — 免费邮件发送 (100封/天)
6. **Cloudflare Pages** — 免费静态站托管 (无限带宽)
7. **GitHub Actions** — 免费 CI/CD (公共仓库无限)
8. **Neon** — 免费 Serverless PostgreSQL (0.5GB)
9. **Upstash** — 免费 Serverless Redis + Kafka
10. **Resend** — 免费邮件 API (100封/天)
