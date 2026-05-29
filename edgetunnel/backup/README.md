# Proxy Infrastructure Backup

## Architecture
```
User → VPS (119.45.204.198:10086, TLS) → Cloudflare Workers (vless.donglicao.com, 优选IP 104.16.132.229) → Internet
```

## Components
- **Cloudflare Workers**: edgetunnel-zhuguang (VLESS+WS+TLS)
- **VPS Relay**: Xray (VLESS+TCP+TLS → CF Workers)
- **Monitoring**: Telegram bot @claude_zhubot, every 5 min

## Credentials (in .env, NOT in git)
- CF Workers UUID: 见 edgetunnel 后台
- VPS Relay UUID: 见 VPS /etc/xray/config.json
- Admin password: 见 CF Workers secret
- Telegram Bot: 见 VPS /opt/proxy-monitor.sh

## Files
- `xray-config.json` — VPS Xray config (deploy to /etc/xray/config.json)
- `monitor.sh` — Health check script (deploy to /opt/proxy-monitor.sh)
- `../wrangler.toml` — Cloudflare Workers config

## Restore Steps
1. Install Xray on VPS
2. Copy xray-config.json to /etc/xray/config.json
3. Generate TLS cert: openssl req -new -newkey rsa:2048 -days 3650 -nodes -x509 -subj "/CN=vless.donglicao.com" -keyout /etc/xray/cert/key.pem -out /etc/xray/cert/cert.pem
4. systemctl enable --now xray
5. Copy monitor.sh to /opt/proxy-monitor.sh, chmod +x
6. Add cron: */5 * * * * /opt/proxy-monitor.sh
7. Deploy CF Workers: cd edgetunnel-main && npx wrangler deploy
