#!/usr/bin/env bash
#
# LogosAI Quick Start
# Sets up the full LogosAI stack: SDK + ACP Server + API + Frontend
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/maior/logosai-framework/main/quickstart.sh | bash
#   OR
#   git clone https://github.com/maior/logosai-framework.git && cd logosai-framework && ./quickstart.sh
#
# Prerequisites:
#   - Python 3.11+
#   - Node.js 18+
#   - PostgreSQL 14+ (running, with a 'logosai' database)
#   - Git
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
NC='\033[0m'
BOLD='\033[1m'

log()  { echo -e "${GREEN}[LogosAI]${NC} $1"; }
warn() { echo -e "${YELLOW}[LogosAI]${NC} $1"; }
err()  { echo -e "${RED}[LogosAI]${NC} $1"; }
step() { echo -e "\n${PURPLE}━━━ $1 ━━━${NC}"; }

# ── Banner ──
echo -e "${PURPLE}"
echo "  _                            _    ___ "
echo " | |    ___   __ _  ___  ___  / \  |_ _|"
echo " | |   / _ \ / _\` |/ _ \/ __|/ _ \  | | "
echo " | |__| (_) | (_| | (_) \__ / ___ \ | | "
echo " |_____\___/ \__, |\___/|__/_/   \_\___|"
echo "             |___/                       "
echo -e "${NC}"
echo -e "${BOLD}Multi-Agent AI Platform — Quick Start${NC}"
echo ""

WORKDIR="${LOGOSAI_DIR:-$(pwd)/logosai-stack}"

# ── Step 0: Check prerequisites ──
step "Checking prerequisites"

check_cmd() {
    if command -v "$1" &>/dev/null; then
        log "$1 ✓ ($(${@:2}))"
        return 0
    else
        err "$1 ✗ — not found"
        return 1
    fi
}

MISSING=0
check_cmd python3 python3 --version 2>&1 | head -1 || MISSING=1
check_cmd node node --version || MISSING=1
check_cmd npm npm --version || MISSING=1
check_cmd git git --version || MISSING=1

# Check Python version >= 3.11
PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]); then
    err "Python 3.11+ required (found $PY_VER)"
    MISSING=1
fi

# Check PostgreSQL
if command -v psql &>/dev/null; then
    log "psql ✓ ($(psql --version 2>&1 | head -1))"
else
    warn "psql not found — PostgreSQL is required for logos_api"
    echo ""
    echo "  Quick install options:"
    echo "    macOS:   brew install postgresql@15 && brew services start postgresql@15"
    echo "    Ubuntu:  sudo apt install postgresql && sudo systemctl start postgresql"
    echo "    Docker:  docker run -d --name logosai-pg -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:15"
    echo ""
    MISSING=1
fi

if [ "$MISSING" -eq 1 ]; then
    err "Missing prerequisites. Install them and try again."
    exit 1
fi

# ── Step 1: Create workspace ──
step "Creating workspace at $WORKDIR"
mkdir -p "$WORKDIR"
cd "$WORKDIR"

# ── Step 2: Clone repositories ──
step "Cloning repositories"

clone_repo() {
    local name="$1" url="$2"
    if [ -d "$name" ]; then
        log "$name already exists, pulling latest..."
        (cd "$name" && git pull --ff-only 2>/dev/null || true)
    else
        log "Cloning $name..."
        git clone --depth 1 "$url" "$name"
    fi
}

clone_repo logosai-framework  https://github.com/maior/logosai-framework.git
clone_repo logosai-ontology   https://github.com/maior/logosai-ontology.git
clone_repo logosai-api        https://github.com/maior/logosai-api.git
clone_repo logosai-web        https://github.com/maior/logosai-web.git

# ── Step 3: Python virtual environment ──
step "Setting up Python environment"

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    log "Virtual environment created"
fi
source .venv/bin/activate
log "Using Python: $(python --version)"

# ── Step 4: Install Python packages ──
step "Installing Python packages"

# Install logosai framework
log "Installing logosai..."
pip install -e logosai-framework/ --quiet 2>/dev/null

# Install ontology dependencies
if [ -f logosai-ontology/requirements.txt ]; then
    log "Installing ontology dependencies..."
    pip install -r logosai-ontology/requirements.txt --quiet 2>/dev/null
fi

# Install logos_api dependencies
log "Installing logos_api dependencies..."
pip install -e logosai-api/ --quiet 2>/dev/null

# ── Step 5: Configure environment ──
step "Configuring environment"

# logos_api .env
if [ ! -f logosai-api/.env ]; then
    cp logosai-api/.env.example logosai-api/.env
    log "Created logosai-api/.env from .env.example"
    warn "Edit logosai-api/.env to set your DATABASE_URL and API keys"
else
    log "logosai-api/.env already exists"
fi

# logos_web .env.local
if [ ! -f logosai-web/.env.local ]; then
    cp logosai-web/.env.example logosai-web/.env.local
    log "Created logosai-web/.env.local from .env.example"
else
    log "logosai-web/.env.local already exists"
fi

# ── Step 6: Setup database ──
step "Setting up database"

# Try to create the database (ignore if exists)
if command -v createdb &>/dev/null; then
    createdb logosai 2>/dev/null && log "Database 'logosai' created" || log "Database 'logosai' already exists"
fi

# Run migrations
log "Running migrations..."
(cd logosai-api && python -m alembic upgrade head 2>/dev/null) && log "Migrations complete" || warn "Migration failed — check DATABASE_URL in .env"

# ── Step 7: Install frontend dependencies ──
step "Installing frontend dependencies"

(cd logosai-web && npm install --silent 2>/dev/null)
log "Frontend dependencies installed"

# ── Step 8: Create logs directories ──
mkdir -p logosai-api/logs logosai-web/logs

# ── Step 9: Start services ──
step "Starting services"

# Function to start a background process
start_service() {
    local name="$1" cmd="$2" dir="$3" logfile="$4"
    log "Starting $name..."
    (cd "$dir" && nohup bash -c "$cmd" >> "$logfile" 2>&1 &)
    echo $! > "$dir/.pid"
    sleep 1
}

# Start ACP server (sample agents on port 8888)
log "Starting ACP server (sample agents, port 8888)..."
(cd logosai-framework/samples && nohup python sample_acp_server.py >> ../../logosai-api/logs/acp.log 2>&1 &)
ACP_PID=$!
sleep 2

# Start logos_api (port 8090)
log "Starting logos_api (port 8090)..."
(cd logosai-api && PYTHONPATH="$WORKDIR/logosai-ontology:$WORKDIR/logosai-framework:$PYTHONPATH" nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8090 >> logs/logos_api.log 2>&1 &)
API_PID=$!
sleep 3

# Start logos_web (port 8010)
log "Starting logos_web (port 8010)..."
(cd logosai-web && nohup npm run dev >> logs/logos_web.log 2>&1 &)
WEB_PID=$!
sleep 5

# ── Step 10: Health check ──
step "Checking services"

check_service() {
    local name="$1" url="$2"
    if curl -s --max-time 5 "$url" > /dev/null 2>&1; then
        log "$name ✓ — $url"
    else
        warn "$name ✗ — not responding at $url (check logs)"
    fi
}

check_service "ACP Server"  "http://localhost:8888/jsonrpc"
check_service "logos_api"    "http://localhost:8090/health"
check_service "logos_web"    "http://localhost:8010"

# ── Done ──
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}  LogosAI is ready!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  ${BLUE}Frontend${NC}     http://localhost:8010"
echo -e "  ${BLUE}API Docs${NC}     http://localhost:8090/docs"
echo -e "  ${BLUE}ACP Server${NC}   http://localhost:8888"
echo ""
echo -e "  ${BOLD}Stop all:${NC}    kill $ACP_PID $API_PID $WEB_PID"
echo -e "  ${BOLD}Logs:${NC}        tail -f logosai-api/logs/*.log"
echo ""
echo -e "  ${PURPLE}Open http://localhost:8010 to start chatting!${NC}"
echo ""

# Try to open browser
if command -v open &>/dev/null; then
    open "http://localhost:8010" 2>/dev/null || true
elif command -v xdg-open &>/dev/null; then
    xdg-open "http://localhost:8010" 2>/dev/null || true
fi
