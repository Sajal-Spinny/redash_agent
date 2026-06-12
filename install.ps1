# setup.ps1 — Redash Agent Setup
Write-Host "Setting up Redash Agent..." -ForegroundColor Cyan

# 1. Check Python
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Python not found. Please install Python 3.9+ from https://python.org" -ForegroundColor Red
    exit 1
}

# 2. Check Git
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "Git not found. Please install from https://git-scm.com" -ForegroundColor Red
    exit 1
}

# 3. Clone repo
git clone https://github.com/Sajal-Spinny/redash_agent.git
Set-Location redash_agent

# 4. Install dependencies
pip install -r requirements.txt

# 5. Set fixed env vars
[System.Environment]::SetEnvironmentVariable("DORIS_HOST", "sp-query-engine.mngt.ispinnyworks.in", "User")
[System.Environment]::SetEnvironmentVariable("DORIS_PORT", "9030", "User")

# 6. Prompt only for personal credentials
$user_val  = Read-Host "Enter your DORIS_USER (e.g. firstname.lastname)"
$pass_val  = Read-Host "Enter your DORIS_PASSWORD" -AsSecureString
$pass_plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
                [Runtime.InteropServices.Marshal]::SecureStringToBSTR($pass_val))

[System.Environment]::SetEnvironmentVariable("DORIS_USER",     $user_val,  "User")
[System.Environment]::SetEnvironmentVariable("DORIS_PASSWORD", $pass_plain, "User")

Write-Host ""
Write-Host "Setup complete! Close and reopen your terminal, then run:" -ForegroundColor Green
Write-Host '  cd redash_agent' -ForegroundColor Yellow
Write-Host '  python scripts\run_query.py "SHOW DATABASES"' -ForegroundColor Yellow
Write-Host ""
Write-Host "Then start the agent with:  claude" -ForegroundColor Yellow
