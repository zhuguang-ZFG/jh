# Proxy Infrastructure

## Architecture
```
Device → Clash Verge → edgetunnel (CF Workers) → Internet
                           ↕
                    edgetunnel admin panel (unified management)
```

## Components
- **Cloudflare Workers**: edgetunnel-zhuguang (VLESS+WS+TLS)
- **Domain**: vless.donglicao.com
- **Admin**: https://vless.donglicao.com/admin
- **Subscription**: https://vless.donglicao.com/sub?token=<token>

## Features
- DNS encryption (DoH) in Clash
- Ad filtering rules
- Auto-select fastest node (url-test)
- CF Workers auto-deploy via wrangler

## Files
- `edgetunnel-main/` — CF Workers source code
- `edgetunnel-main/wrangler.toml` — Deploy config

## Restore Steps
1. Install wrangler: `npm i -g wrangler`
2. Login: `npx wrangler login`
3. Deploy: `cd edgetunnel-main && npx wrangler deploy`
4. Set ADMIN secret: `npx wrangler secret put ADMIN`
5. Import subscription in Clash Verge
