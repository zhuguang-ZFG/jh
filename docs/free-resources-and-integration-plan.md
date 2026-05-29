# Free Resources & Project Integration Plan

> Updated: 2026-05-29

## Current Infrastructure

### Proxy (edgetunnel)
- **Architecture**: Device → Clash Verge → edgetunnel (CF Workers) → Internet
- **Admin**: https://vless.donglicao.com/admin
- **Domain**: vless.donglicao.com (Cloudflare)
- **Features**: DNS encryption (DoH), ad filtering, auto-select fastest node

### VPS (119.45.204.198)
- **OS**: TencentOS Server 3.3
- **Services**: mihomo (Clash), nginx, PostgreSQL, Tailscale, Python bots
- **SSH**: Key-only auth, fail2ban enabled
- **Purpose**: Quant bots, monitoring, evo-server, ESP32 backend (planned)

---

## Free Resources (No Credit Card Required)

### Already Using
| Resource | Purpose |
|----------|---------|
| GitHub | Source code, CI/CD |
| Cloudflare | DNS, Workers, KV (edgetunnel) |
| Tailscale | VPN mesh network (100 devices) |
| Telegram Bot | Monitoring notifications |
| Claude Code | AI-assisted development |
| CodeGraph | Code knowledge graph |
| GitNexus | Code relationship analysis |
| Context7 | Real-time documentation |

### To Set Up

#### High Priority
| Resource | Purpose | Free Tier |
|----------|---------|-----------|
| **eu.org** | Free domain | Permanent, looks like real domain |
| **UptimeRobot** | VPS/node monitoring | 50 monitors, email/Telegram alerts |
| **GitHub Actions** | CI/CD automation | 2000 min/month |
| **Cloudflare Pages** | Static site hosting | Unlimited sites |

#### Medium Priority
| Resource | Purpose | Free Tier |
|----------|---------|-----------|
| **Cloudflare Email Routing** | Email forwarding | Free with domain |
| **Supabase** | PostgreSQL database | 500MB |
| **Neon** | PostgreSQL database | 512MB |
| **healthchecks.io** | Cron job monitoring | 20 checks |
| **cron-job.org** | Online scheduled tasks | Unlimited |
| **Backblaze B2** | Object storage | 10GB |

#### ESP32/AI Related
| Resource | Purpose | Free Tier |
|----------|---------|-----------|
| **Edge Impulse** | ML model training for ESP32 | Free for developers |
| **ESP-DL** | Deep learning on ESP32-S3 | Open source |
| **TensorFlow Lite Micro** | On-device inference | Open source |
| **Google Colab** | Free GPU for training | K80 GPU |
| **Kaggle** | GPU + datasets | 30 GPU hours/week |

#### Vibe Coding
| Resource | Purpose | Free Tier |
|----------|---------|-----------|
| **OpenRouter** | Free AI models (DeepSeek/Llama) | Multiple free models |
| **v0.dev** | AI UI generation | 200 credits/month |
| **Langfuse** | LLM observability | 50K observations/month |
| **Pollinations.AI** | Free image generation | Unlimited |

#### Monitoring (for VPS)
| Resource | Purpose | Free Tier |
|----------|---------|-----------|
| **Grafana Cloud** | Metrics dashboard | 10K series, 14 days |
| **New Relic** | APM monitoring | 100GB/month |
| **Better Stack** | Status pages + monitoring | 10 monitors |

#### Financial Data (for Quant Bots)
| Resource | Purpose | Free Tier |
|----------|---------|-----------|
| **Financial Data API** | Stock market data | 300 requests/day |
| **CoinMarketCap** | Crypto data | 10K calls/month |
| **Tomorrow.io** | Weather data | Free plan |

---

## ESP32 + AI + Mini Program Integration

### Project: esp32S_XYZ (AI Writing Machine)
- **U1 (MOTOR_MCU)**: Grbl-based motion control (writing/drawing/engraving)
- **U8 (AI_MCU)**: XiaoZhi voice interaction, camera, audio, BLE/WiFi, LCD
- **Server**: Python DeviceServer + Java BusinessServer + Vue Admin + uni-app Mini Program

### Communication Flow
```
微信小程序 ←Edge-A→ BusinessServer ←Edge-B→ DeviceServer ←Edge-C→ U8 ←Edge-D→ U1
```

### Integration Plan

#### Phase 1: Deploy DeviceServer to VPS
- Deploy Python DeviceServer to VPS (already has Python + FastAPI)
- Set up nginx reverse proxy with SSL
- Configure domain (donglicao.com subdomain or eu.org)

#### Phase 2: Connect Mini Program
- Mini program connects to VPS via API
- User authentication via WeChat login
- Real-time device status via WebSocket

#### Phase 3: AI Enhancement
- **Voice**: Edge Impulse trained wake word model on U8
- **Vision**: ESP32-S3 camera + TFLite for object recognition
- **Cloud AI**: VPS calls AI APIs for complex tasks
- **Smart Features**: Handwriting recognition, drawing analysis

#### Phase 4: Production
- CI/CD via GitHub Actions
- Monitoring via UptimeRobot + Grafana
- Data backup to Supabase/Neon

---

## TODO
- [ ] Apply for eu.org domain
- [ ] Set up UptimeRobot monitoring
- [ ] Deploy DeviceServer to VPS
- [ ] Configure GitHub Actions CI/CD
- [ ] Set up Cloudflare Email Routing
- [ ] Train Edge Impulse model for U8
- [ ] Connect mini program to VPS backend
