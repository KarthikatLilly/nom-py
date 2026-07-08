<#
.SYNOPSIS
  Restores nom-py, nom-py-bob, and incident-responder MCP servers into Claude Desktop's config.
.DESCRIPTION
  Idempotent — safe to run any time. Preserves existing Claude preferences.
  Auto-detects the MSIX sandbox path.
.EXAMPLE
  .\scripts\restore_claude_config.ps1
#>

# Auto-detect current MSIX Claude sandbox (adapts if the package hash changes)
$claudePkg = Get-ChildItem "$env:LOCALAPPDATA\Packages" -Directory `
    -Filter "Claude_*" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1 -ExpandProperty FullName

if (-not $claudePkg) {
    Write-Host "ERROR: Claude Desktop MSIX sandbox not found." -ForegroundColor Red
    Write-Host "Is Claude Desktop installed?" -ForegroundColor Yellow
    exit 1
}

$configDir = Join-Path $claudePkg "LocalCache\Roaming\Claude"
$configPath = Join-Path $configDir "claude_desktop_config.json"

New-Item -ItemType Directory -Path $configDir -Force | Out-Null

# Load existing config if present, else start fresh
if (Test-Path $configPath) {
    $existing = Get-Content $configPath -Raw | ConvertFrom-Json
    Write-Host "Loaded existing config, will merge mcpServers" -ForegroundColor Gray
} else {
    $existing = [PSCustomObject]@{}
    Write-Host "No existing config — starting fresh" -ForegroundColor Gray
}

# The mcpServers block (raw JSON for reliability)
$mcpServersJson = @'
{
  "incident-responder": {
    "command": "C:\\Users\\L132478\\mcp\\mcp-incident-responder\\venv\\Scripts\\python.exe",
    "args": ["C:\\Users\\L132478\\mcp\\mcp-incident-responder\\server_stdio.py"]
  },
  "nom-py-alice": {
    "command": "C:\\Users\\L132478\\nom-py\\.venv\\Scripts\\python.exe",
    "args": ["C:\\Users\\L132478\\nom-py\\cmd\\stdio_bridge\\main.py"],
    "env": {
      "NOM_URL": "http://localhost:8001/mcp",
      "NOM_TOKEN": "tok-alice",
      "SystemRoot": "C:\\Windows",
      "PATH": "C:\\Users\\L132478\\nom-py\\.venv\\Scripts;C:\\Windows\\System32;C:\\Windows"
    }
  },
  "nom-py-bob": {
    "command": "C:\\Users\\L132478\\nom-py\\.venv\\Scripts\\python.exe",
    "args": ["C:\\Users\\L132478\\nom-py\\cmd\\stdio_bridge\\main.py"],
    "env": {
      "NOM_URL": "http://localhost:8001/mcp",
      "NOM_TOKEN": "tok-bob",
      "SystemRoot": "C:\\Windows",
      "PATH": "C:\\Users\\L132478\\nom-py\\.venv\\Scripts;C:\\Windows\\System32;C:\\Windows"
    }
  }
}
'@

$mcpServers = $mcpServersJson | ConvertFrom-Json
$existing | Add-Member -MemberType NoteProperty -Name mcpServers -Value $mcpServers -Force

$outputJson = $existing | ConvertTo-Json -Depth 100
[System.IO.File]::WriteAllText($configPath, $outputJson, [System.Text.UTF8Encoding]::new($false))

Write-Host ""
Write-Host "Config restored at:" -ForegroundColor Green
Write-Host "  $configPath" -ForegroundColor Gray
Write-Host ""
Write-Host "MCP servers now configured:" -ForegroundColor Cyan
($existing.mcpServers | Get-Member -MemberType NoteProperty).Name | ForEach-Object { Write-Host "  - $_" }
Write-Host ""
Write-Host "Next: fully quit Claude Desktop from the system tray, then relaunch." -ForegroundColor Yellow