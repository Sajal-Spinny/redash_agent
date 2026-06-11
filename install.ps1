# =============================================================================
# Spinny Air — Redash Data Fetcher Agent Installer
# Usage: irm https://sp-gitea.mngt.ispinnyworks.in/spinny/spinny-air/raw/branch/main/install.ps1 | iex
# =============================================================================

$ErrorActionPreference = "Stop"

# ---------- config (edit these to match your Gitea repo) ----------
$GITEA_CLONE_URL = "https://sp-gitea.mngt.ispinnyworks.in/spinny/spinny-air.git"
$INSTALL_DIR     = "$env:USERPROFILE\spinny-air"
$DORIS_HOST      = "sp-query-engine.mngt.ispinnyworks.in"
$DORIS_PORT      = "9030"
$MIN_PYTHON_VER  = [version]"3.9"
# ------------------------------------------------------------------

function Write-Step($msg)  { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg)  { Write-Host "    [!!] $msg" -ForegroundColor Yellow }
function Write-Fail($msg)  { Write-Host "`n[FAILED] $msg" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "  Spinny Air — Redash Data Fetcher Agent" -ForegroundColor Magenta
Write-Host "  ----------------------------------------" -ForegroundColor Magenta
Write-Host ""

# =============================================================================
# 1. Check / install Python
# =============================================================================
Write-Step "Checking Python..."

$pythonExe = $null
foreach ($cmd in @("python", "python3")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python (\d+\.\d+)") {
            if ([version]$Matches[1] -ge $MIN_PYTHON_VER) {
                $pythonExe = $cmd
                Write-Ok "Found $ver"
                break
            } else {
                Write-Warn "$ver is below minimum $MIN_PYTHON_VER"
            }
        }
    } catch { }
}

if (-not $pythonExe) {
    Write-Warn "Python $MIN_PYTHON_VER+ not found. Installing via winget..."
    try {
        winget install --id Python.Python.3.9.13 --silent --accept-source-agreements --accept-package-agreements
        # Refresh PATH
        $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" +
                    [System.Environment]::GetEnvironmentVariable("PATH", "User")
        $pythonExe = "python"
        Write-Ok "Python installed. You may need to reopen PowerShell if later steps fail."
    } catch {
        Write-Fail "Could not install Python automatically.`nPlease install Python 3.9.13 from https://python.org and re-run this installer."
    }
}

# =============================================================================
# 2. Check / install Git
# =============================================================================
Write-Step "Checking Git..."

$hasGit = $false
try { git --version | Out-Null; $hasGit = $true; Write-Ok "Git found" } catch { }

if (-not $hasGit) {
    Write-Warn "Git not found. Installing via winget..."
    try {
        winget install --id Git.Git --silent --accept-source-agreements --accept-package-agreements
        $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" +
                    [System.Environment]::GetEnvironmentVariable("PATH", "User")
        Write-Ok "Git installed."
    } catch {
        Write-Fail "Could not install Git automatically.`nPlease install from https://git-scm.com and re-run."
    }
}

# =============================================================================
# 3. Clone or update repo
# =============================================================================
Write-Step "Setting up repo at $INSTALL_DIR ..."

if (Test-Path "$INSTALL_DIR\.git") {
    Write-Warn "Repo already exists — pulling latest..."
    Push-Location $INSTALL_DIR
    git pull --ff-only
    Pop-Location
    Write-Ok "Updated."
} else {
    git clone $GITEA_CLONE_URL $INSTALL_DIR
    Write-Ok "Cloned."
}

# =============================================================================
# 4. Install Python dependencies
# =============================================================================
Write-Step "Installing Python dependencies..."

& $pythonExe -m pip install --quiet --upgrade pip
& $pythonExe -m pip install --quiet -r "$INSTALL_DIR\requirements.txt"
& $pythonExe -m pip install --quiet mcp

Write-Ok "Dependencies installed."

# =============================================================================
# 5. Prompt for Doris credentials
# =============================================================================
Write-Step "Doris credentials setup..."
Write-Host "    These are saved as Windows user env vars (only visible to you)." -ForegroundColor Gray
Write-Host ""

$dorisUser = Read-Host "    Enter your Doris username"
$dorisPassSecure = Read-Host "    Enter your Doris password" -AsSecureString
$dorisPass = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($dorisPassSecure)
)

[System.Environment]::SetEnvironmentVariable("DORIS_HOST",     $DORIS_HOST, "User")
[System.Environment]::SetEnvironmentVariable("DORIS_PORT",     $DORIS_PORT, "User")
[System.Environment]::SetEnvironmentVariable("DORIS_USER",     $dorisUser,  "User")
[System.Environment]::SetEnvironmentVariable("DORIS_PASSWORD", $dorisPass,  "User")
[System.Environment]::SetEnvironmentVariable("DORIS_DB",       "",          "User")

Write-Ok "Credentials saved to user environment variables."

# =============================================================================
# 6. Test Doris connection
# =============================================================================
Write-Step "Testing Doris connection..."

$testScript = @"
import os, sys
os.environ['DORIS_HOST']     = '$DORIS_HOST'
os.environ['DORIS_PORT']     = '$DORIS_PORT'
os.environ['DORIS_USER']     = '$dorisUser'
os.environ['DORIS_PASSWORD'] = '$dorisPass'
import pymysql
try:
    c = pymysql.connect(host=os.environ['DORIS_HOST'], port=int(os.environ['DORIS_PORT']),
                        user=os.environ['DORIS_USER'], password=os.environ['DORIS_PASSWORD'],
                        connect_timeout=10)
    c.close()
    print('OK')
except Exception as e:
    print(f'FAIL:{e}')
"@

$testResult = & $pythonExe -c $testScript
if ($testResult -eq "OK") {
    Write-Ok "Connected to Doris successfully."
} else {
    Write-Warn "Could not connect to Doris: $($testResult -replace 'FAIL:','')"
    Write-Warn "Continuing install — check your credentials later with:"
    Write-Warn "  python scripts\run_query.py `"SHOW DATABASES`""
}

# =============================================================================
# 7. Register MCP server in Claude Desktop config
# =============================================================================
Write-Step "Registering MCP server in Claude Desktop..."

$claudeConfigDir  = "$env:APPDATA\Claude"
$claudeConfigFile = "$claudeConfigDir\claude_desktop_config.json"
$mcpServerPath    = "$INSTALL_DIR\mcp_server.py"

# Resolve python full path for the config (relative paths break Claude Desktop)
$pythonFullPath = (Get-Command $pythonExe -ErrorAction SilentlyContinue).Source
if (-not $pythonFullPath) { $pythonFullPath = $pythonExe }

$newServer = @{
    command = $pythonFullPath
    args    = @($mcpServerPath)
    env     = @{
        DORIS_HOST     = $DORIS_HOST
        DORIS_PORT     = $DORIS_PORT
        DORIS_USER     = $dorisUser
        DORIS_PASSWORD = $dorisPass
        DORIS_DB       = ""
    }
}

# Read existing config or start fresh
if (Test-Path $claudeConfigFile) {
    $config = Get-Content $claudeConfigFile -Raw | ConvertFrom-Json
} else {
    New-Item -ItemType Directory -Force -Path $claudeConfigDir | Out-Null
    $config = [PSCustomObject]@{ mcpServers = [PSCustomObject]@{} }
}

if (-not $config.mcpServers) {
    $config | Add-Member -MemberType NoteProperty -Name "mcpServers" -Value ([PSCustomObject]@{})
}

$config.mcpServers | Add-Member -MemberType NoteProperty -Name "redash-doris-agent" -Value $newServer -Force

$config | ConvertTo-Json -Depth 10 | Set-Content $claudeConfigFile -Encoding UTF8
Write-Ok "Registered 'redash-doris-agent' in Claude Desktop config."

# =============================================================================
# 8. Done
# =============================================================================
Write-Host ""
Write-Host "  =============================================" -ForegroundColor Magenta
Write-Host "   Installation complete!" -ForegroundColor Green
Write-Host "  =============================================" -ForegroundColor Magenta
Write-Host ""
Write-Host "  Next steps:" -ForegroundColor White
Write-Host "   1. Restart Claude Desktop completely (quit from system tray, reopen)" -ForegroundColor Gray
Write-Host "   2. Start a new chat — click the hammer icon to see your tools" -ForegroundColor Gray
Write-Host "   3. Type /mcp to verify the server is connected" -ForegroundColor Gray
Write-Host ""
Write-Host "  Installed at : $INSTALL_DIR" -ForegroundColor Gray
Write-Host "  MCP server   : $mcpServerPath" -ForegroundColor Gray
Write-Host "  Config file  : $claudeConfigFile" -ForegroundColor Gray
Write-Host ""
Write-Host "  To update later, re-run this installer or: cd $INSTALL_DIR && git pull" -ForegroundColor Gray
Write-Host ""
