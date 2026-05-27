# setup-evo.ps1 — 一键配置 Claude Code 连接 evo-server
# 在新机器上运行：powershell -ExecutionPolicy Bypass -File setup-evo.ps1

$ErrorActionPreference = "Stop"

$hooksDir = "$env:USERPROFILE\evo-hooks"
$settingsFile = "$env:USERPROFILE\.claude\settings.json"
$evoServer = "http://119.45.204.198"

Write-Host "=== Evo-Server Claude Code Setup ===" -ForegroundColor Cyan
Write-Host ""

# 1. Create hooks directory
Write-Host "[1/4] Creating hooks directory..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path $hooksDir | Out-Null
Write-Host "  -> $hooksDir" -ForegroundColor Green

# 2. Copy hook files from VPS via SCP
Write-Host "[2/4] Copying hook files from VPS..." -ForegroundColor Yellow
$hookFiles = @("evo_hook_context.py", "evo_hook_post_tool.py", "evo_hook_stop.py", "evo_hook_quality.py")
foreach ($file in $hookFiles) {
    $dest = Join-Path $hooksDir $file
    try {
        # Try SCP (requires SSH key or password auth)
        scp -o StrictHostKeyChecking=no root@119.45.204.198:/opt/evo-server/hooks/$file $dest 2>$null
        if (Test-Path $dest) {
            Write-Host "  -> $file copied" -ForegroundColor Green
            continue
        }
    } catch {}
    Write-Host "  -> $file SCP failed — copy manually from D:\jh\hooks\" -ForegroundColor DarkYellow
}

# 3. Generate settings.json snippet
Write-Host "[3/4] Generating settings configuration..." -ForegroundColor Yellow

$contextCmd = "python $hooksDir/evo_hook_context.py" -replace "\\", "/"
$postToolCmd = "python $hooksDir/evo_hook_post_tool.py" -replace "\\", "/"
$stopCmd = "python $hooksDir/evo_hook_stop.py" -replace "\\", "/"
$qualityCmd = "python $hooksDir/evo_hook_quality.py --post" -replace "\\", "/"
$qualityPreCmd = "python $hooksDir/evo_hook_quality.py --pre" -replace "\\", "/"

$hooksConfig = @"
{
  "env": {
    "EVO_SERVER": "$evoServer"
  },
  "hooks": {
    "PreToolUse": [
      {
        "hooks": [
          {
            "command": "$contextCmd",
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
            "command": "$postToolCmd",
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
            "command": "$stopCmd",
            "timeout": 15,
            "type": "command"
          }
        ]
      }
    ]
  }
}
"@

$snippetFile = "$hooksDir\settings-snippet.json"
$hooksConfig | Out-File -FilePath $snippetFile -Encoding UTF8
Write-Host "  -> Snippet saved to: $snippetFile" -ForegroundColor Green

# 4. Merge into existing settings or create new
Write-Host "[4/4] Updating Claude Code settings..." -ForegroundColor Yellow

if (Test-Path $settingsFile) {
    Write-Host "  -> Existing settings.json found" -ForegroundColor DarkYellow
    Write-Host "  -> Please manually merge $snippetFile into $settingsFile" -ForegroundColor DarkYellow
    Write-Host "     Or run: notepad $settingsFile" -ForegroundColor DarkYellow
} else {
    New-Item -ItemType Directory -Force -Path (Split-Path $settingsFile) | Out-Null
    $hooksConfig | Out-File -FilePath $settingsFile -Encoding UTF8
    Write-Host "  -> Created $settingsFile" -ForegroundColor Green
}

Write-Host ""
Write-Host "=== Setup Complete ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor White
Write-Host "  1. Verify evo-server is reachable:" -ForegroundColor White
Write-Host "     curl $evoServer/health" -ForegroundColor Gray
Write-Host ""
Write-Host "  2. Test context hook:" -ForegroundColor White
Write-Host "     echo '{`"file_path`":`"test.py`"}' | python $hooksDir/evo_hook_context.py" -ForegroundColor Gray
Write-Host ""
Write-Host "  3. Start Claude Code and edit a file to verify auto-injection" -ForegroundColor White
