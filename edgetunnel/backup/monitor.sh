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

STATUS="OK"

# Check Xray process
if ! pgrep -x xray > /dev/null 2>&1; then
    send_alert "🔴 Xray 进程不存在，正在重启..."
    systemctl restart xray
    sleep 3
    pgrep -x xray > /dev/null 2>&1 && send_alert "✅ Xray 重启成功" || { send_alert "❌ Xray 重启失败"; STATUS="FAIL"; }
fi

# Check CF Workers
CF_CODE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 10 "https://vless.donglicao.com/" 2>/dev/null)
[ "$CF_CODE" != "200" ] && { send_alert "🔴 CF Workers 不可达! HTTP: ${CF_CODE}"; STATUS="FAIL"; }

echo "$(date '+%Y-%m-%d %H:%M:%S') ${STATUS} - xray:$(pgrep -x xray > /dev/null 2>&1 && echo active || echo dead) cf:${CF_CODE}" >> "$LOG"
