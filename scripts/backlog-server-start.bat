@echo off
netstat -ano | findstr ":3030.*LISTENING" >nul 2>&1 && exit /b 0
set BACKLOG_VIEWER_PORT=3030
"C:\Program Files\nodejs\node.exe" "C:\Users\zhugu\AppData\Roaming\npm\node_modules\backlog-mcp\dist\node-server.mjs" >nul 2>&1
