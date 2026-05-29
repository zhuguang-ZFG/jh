#!/bin/bash
BOT_TOKEN="YOUR_BOT_TOKEN"
CHAT_ID="YOUR_CHAT_ID"
LOG="/var/log/proxy-monitor.log"
PROXY="http://127.0.0.1:7890"

send_alert() {
    curl -s --max-time 10 -x "$PROXY" -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
        -d chat_id="${CHAT_ID}" -d text="$1" > /dev/null
    echo "$(date '+%Y-%m-%d %H:%M:%S') ALERT: $1" >> "$LOG"
}

if ! systemctl is-active --quiet xray; then
    send_alert "🔴 Xray 已停止，正在重启..."
    systemctl restart xray
    sleep 2
    systemctl is-active --quiet xray && send_alert "✅ Xray 重启成功" || send_alert "❌ Xray 重启失败"
fi

CF_CODE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 10 "https://vless.donglicao.com/" 2>/dev/null)
[ "$CF_CODE" != "200" ] && send_alert "🔴 CF Workers 不可达! HTTP: ${CF_CODE}"

! ss -tlnp | grep -q ":10086" && send_alert "🔴 端口 10086 未监听!"

echo "$(date '+%Y-%m-%d %H:%M:%S') OK - xray:$(systemctl is-active xray) cf:${CF_CODE}" >> "$LOG"
