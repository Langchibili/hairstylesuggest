# setup.ps1
# ─────────────────────────────────────────────────────────────────────────────
# HairstyleSuggest — Windows Day 1 Setup Script
# Run from the project root:  .\setup.ps1
# Requires: Docker Desktop, Node.js 18+, Python 3.11+
# ─────────────────────────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"

function Check-Command($cmd) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Error "❌  '$cmd' is not installed or not in PATH. Please install it first."
        exit 1
    }
}

Write-Host "`n🚀  HairstyleSuggest Setup" -ForegroundColor Cyan
Write-Host "─────────────────────────────────────────────────────" -ForegroundColor DarkGray

# ── 1. Check prerequisites ────────────────────────────────────────────────────
Write-Host "`n[1/5] Checking prerequisites..." -ForegroundColor Yellow
Check-Command "docker"
Check-Command "node"
Check-Command "npm"
Check-Command "python"

$nodeVersion = (node --version)
Write-Host "  ✅  Docker : $(docker --version)"
Write-Host "  ✅  Node   : $nodeVersion"
Write-Host "  ✅  Python : $(python --version)"

# ── 2. Start MySQL via Docker ─────────────────────────────────────────────────
Write-Host "`n[2/5] Starting MySQL 8 via Docker..." -ForegroundColor Yellow

docker compose up -d mysql

Write-Host "  Waiting for MySQL to be healthy..." -ForegroundColor DarkGray
$retries = 0
do {
    Start-Sleep -Seconds 3
    $health = docker inspect --format "{{.State.Health.Status}}" hairstylesuggest_mysql 2>$null
    $retries++
    Write-Host "  ⏳  Status: $health ($retries/20)"
} while ($health -ne "healthy" -and $retries -lt 20)

if ($health -ne "healthy") {
    Write-Error "❌  MySQL did not become healthy in time. Check: docker logs hairstylesuggest_mysql"
}

Write-Host "  ✅  MySQL is ready on localhost:3306" -ForegroundColor Green

# ── 3. Scaffold Strapi ────────────────────────────────────────────────────────
Write-Host "`n[3/5] Setting up Strapi backend..." -ForegroundColor Yellow

if (Test-Path ".\backend\node_modules") {
    Write-Host "  ⏩  node_modules already exists — skipping npm install"
} else {
    Write-Host "  📦  Installing Strapi dependencies (this takes 2-3 min)..."
    Set-Location backend
    npm install
    Set-Location ..
    Write-Host "  ✅  Dependencies installed" -ForegroundColor Green
}

# Copy .env if it doesn't exist
if (-not (Test-Path ".\backend\.env")) {
    Copy-Item ".\backend\.env.example" ".\backend\.env"
    Write-Host "  📄  Created backend\.env — EDIT THIS FILE with your real values!" -ForegroundColor Magenta
} else {
    Write-Host "  ⏩  backend\.env already exists"
}

# ── 4. Set up Python AI service ───────────────────────────────────────────────
Write-Host "`n[4/5] Setting up Python AI service..." -ForegroundColor Yellow

if (-not (Test-Path ".\ai-service\.env")) {
    Copy-Item ".\ai-service\.env.example" ".\ai-service\.env"
    Write-Host "  📄  Created ai-service\.env — EDIT THIS FILE with your real values!" -ForegroundColor Magenta
} else {
    Write-Host "  ⏩  ai-service\.env already exists"
}

if (-not (Test-Path ".\ai-service\venv")) {
    Write-Host "  🐍  Creating Python virtual environment..."
    Set-Location ai-service
    python -m venv venv
    .\venv\Scripts\Activate.ps1
    pip install --upgrade pip
    pip install -r requirements.txt
    deactivate
    Set-Location ..
    Write-Host "  ✅  Python venv ready" -ForegroundColor Green
} else {
    Write-Host "  ⏩  venv already exists"
}

# ── 5. Summary ────────────────────────────────────────────────────────────────
Write-Host "`n[5/5] Setup complete!" -ForegroundColor Green
Write-Host "─────────────────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host ""
Write-Host "NEXT STEPS:" -ForegroundColor Cyan
Write-Host ""
Write-Host "  1. Edit backend\.env   with your R2, JWT secrets, INTERNAL_SERVICE_KEY"
Write-Host "  2. Edit ai-service\.env with matching values"
Write-Host ""
Write-Host "  3. Start Strapi:" -ForegroundColor Yellow
Write-Host "       cd backend"
Write-Host "       npm run develop"
Write-Host ""
Write-Host "  4. Create your admin account at http://localhost:1337/admin"
Write-Host ""
Write-Host "  5. Run the seed script (in a new terminal):" -ForegroundColor Yellow
Write-Host "       cd backend"
Write-Host "       npx strapi admin:create-user (or use the UI)"
Write-Host "     Then:"
Write-Host "       `$env:STRAPI_URL='http://localhost:1337'"
Write-Host "       `$env:JWT_TOKEN='your_jwt_here'"
Write-Host "       node ..\scripts\seed.js"
Write-Host ""
Write-Host "  6. Start the AI service (in a new terminal):" -ForegroundColor Yellow
Write-Host "       cd ai-service"
Write-Host "       .\venv\Scripts\Activate.ps1"
Write-Host "       uvicorn main:app --reload --port 8000"
Write-Host ""
Write-Host "  7. Verify everything:" -ForegroundColor Yellow
Write-Host "       curl http://localhost:1337/api/hairstyles   (should list 10 styles)"
Write-Host "       curl http://localhost:8000/health           (should return ok)"
Write-Host ""
