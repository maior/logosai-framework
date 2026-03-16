#!/usr/bin/env bash
#
# LogosAI Quick Start
# One command to set up the full LogosAI stack.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/maior/logosai-framework/main/quickstart.sh | bash
#
# What it does:
#   1. Creates ~/logosai/ workspace
#   2. Clones all 4 repositories
#   3. Sets up Python venv + Node dependencies
#   4. Creates database + runs migrations
#   5. Starts ACP server, API, and frontend
#   6. Opens the browser
#
# Prerequisites: Python 3.11+, Node.js 18+, PostgreSQL 14+, Git
#
# Options:
#   LOGOSAI_DIR=~/my-folder  curl ... | bash   # Custom install directory
#

set -e

# ── Colors ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'
DIM='\033[2m'

log()  { echo -e "${GREEN}  ✓${NC} $1"; }
warn() { echo -e "${YELLOW}  !${NC} $1"; }
err()  { echo -e "${RED}  ✗${NC} $1"; }
step() { echo -e "\n${CYAN}[$1/$TOTAL_STEPS]${NC} ${BOLD}$2${NC}"; }

TOTAL_STEPS=7

# ── Banner ──
echo ""
echo -e "${PURPLE}  ╔══════════════════════════════════════════╗${NC}"
echo -e "${PURPLE}  ║${NC}                                          ${PURPLE}║${NC}"
echo -e "${PURPLE}  ║${NC}   ${BOLD}LogosAI${NC}  Multi-Agent AI Platform       ${PURPLE}║${NC}"
echo -e "${PURPLE}  ║${NC}   ${DIM}Open Source Quick Start${NC}                 ${PURPLE}║${NC}"
echo -e "${PURPLE}  ║${NC}                                          ${PURPLE}║${NC}"
echo -e "${PURPLE}  ╚══════════════════════════════════════════╝${NC}"
echo ""

# ── Workspace ──
WORKDIR="${LOGOSAI_DIR:-$HOME/logosai}"

echo -e "  ${DIM}Install directory:${NC} ${BOLD}$WORKDIR${NC}"
echo -e "  ${DIM}This script will:${NC}"
echo -e "    1. Clone 4 repos into ${BOLD}$WORKDIR${NC}"
echo -e "    2. Install Python + Node dependencies"
echo -e "    3. Set up PostgreSQL database"
echo -e "    4. Start all services"
echo ""

# Confirm if running interactively
if [ -t 0 ]; then
    read -p "  Continue? [Y/n] " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Nn]$ ]]; then
        echo "  Cancelled."
        exit 0
    fi
fi

# ══════════════════════════════════════════
# Step 1: Check prerequisites
# ══════════════════════════════════════════
step 1 "Checking prerequisites"

MISSING=0

# Python
if command -v python3 &>/dev/null; then
    PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 11 ]; then
        log "Python $PY_VER"
    else
        err "Python 3.11+ required (found $PY_VER)"
        MISSING=1
    fi
else
    err "python3 not found"
    MISSING=1
fi

# Node
if command -v node &>/dev/null; then
    NODE_VER=$(node --version)
    log "Node.js $NODE_VER"
else
    err "node not found — install from https://nodejs.org"
    MISSING=1
fi

# Git
if command -v git &>/dev/null; then
    log "Git $(git --version | cut -d' ' -f3)"
else
    err "git not found"
    MISSING=1
fi

# PostgreSQL
PG_OK=0
if command -v psql &>/dev/null; then
    log "PostgreSQL $(psql --version | grep -oE '[0-9]+\.[0-9]+')"
    PG_OK=1
elif command -v docker &>/dev/null; then
    warn "psql not found, but Docker is available"
    echo -e "    ${DIM}Will start PostgreSQL via Docker${NC}"
    PG_OK=2
else
    err "PostgreSQL not found"
    echo ""
    echo -e "    ${BOLD}Install one of:${NC}"
    echo -e "    ${DIM}macOS:${NC}   brew install postgresql@15 && brew services start postgresql@15"
    echo -e "    ${DIM}Ubuntu:${NC}  sudo apt install postgresql && sudo systemctl start postgresql"
    echo -e "    ${DIM}Docker:${NC}  docker run -d -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:15"
    echo ""
    MISSING=1
fi

if [ "$MISSING" -eq 1 ]; then
    echo ""
    err "Missing prerequisites. Install them and run this script again."
    exit 1
fi

# ══════════════════════════════════════════
# Step 2: Create workspace & clone repos
# ══════════════════════════════════════════
step 2 "Setting up workspace"

mkdir -p "$WORKDIR"
cd "$WORKDIR"
log "Directory: $WORKDIR"

# Save this script into the workspace
SCRIPT_PATH="$WORKDIR/quickstart.sh"
if [ ! -f "$SCRIPT_PATH" ] || [ "$(cat "$0" 2>/dev/null | wc -l)" -gt 10 ]; then
    # Copy self into workspace (only if piped from curl)
    if [ ! -f "$SCRIPT_PATH" ]; then
        cat "$0" > "$SCRIPT_PATH" 2>/dev/null || true
        chmod +x "$SCRIPT_PATH" 2>/dev/null || true
    fi
fi

clone_or_pull() {
    local name="$1" url="$2"
    if [ -d "$name" ]; then
        log "$name (exists, pulling latest)"
        (cd "$name" && git pull --ff-only 2>/dev/null) || true
    else
        echo -ne "  ${DIM}  Cloning $name...${NC}\r"
        git clone --depth 1 -q "$url" "$name"
        log "$name"
    fi
}

clone_or_pull logosai-framework  https://github.com/maior/logosai-framework.git
clone_or_pull logosai-ontology   https://github.com/maior/logosai-ontology.git
clone_or_pull logosai-api        https://github.com/maior/logosai-api.git
clone_or_pull logosai-web        https://github.com/maior/logosai-web.git

# ══════════════════════════════════════════
# Step 3: Python environment
# ══════════════════════════════════════════
step 3 "Installing Python dependencies"

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
log "Virtual env: .venv ($(python --version))"

pip install --upgrade pip -q 2>/dev/null

echo -ne "  ${DIM}  Installing logosai framework...${NC}\r"
pip install -e logosai-framework/ -q 2>/dev/null
log "logosai framework"

if [ -f logosai-ontology/requirements.txt ]; then
    echo -ne "  ${DIM}  Installing ontology deps...${NC}\r"
    pip install -r logosai-ontology/requirements.txt -q 2>/dev/null
    log "ontology dependencies"
fi

echo -ne "  ${DIM}  Installing logos_api deps...${NC}\r"
pip install -e logosai-api/ -q 2>/dev/null
log "logos_api dependencies"

# ══════════════════════════════════════════
# Step 4: Node dependencies
# ══════════════════════════════════════════
step 4 "Installing frontend dependencies"

echo -ne "  ${DIM}  Running npm install...${NC}\r"
(cd logosai-web && npm install --silent 2>/dev/null)
log "logos_web (Next.js)"

# ══════════════════════════════════════════
# Step 5: Database setup
# ══════════════════════════════════════════
step 5 "Setting up database"

# Start PostgreSQL via Docker if needed
if [ "$PG_OK" -eq 2 ]; then
    if ! docker ps --format '{{.Names}}' | grep -q logosai-pg; then
        docker run -d --name logosai-pg \
            -e POSTGRES_USER=postgres \
            -e POSTGRES_PASSWORD=postgres \
            -e POSTGRES_DB=logosai \
            -p 5432:5432 \
            postgres:15-alpine >/dev/null 2>&1
        log "PostgreSQL started via Docker"
        echo -ne "  ${DIM}  Waiting for PostgreSQL...${NC}\r"
        sleep 5
    else
        log "PostgreSQL Docker container already running"
    fi
fi

# Create database (ignore if exists)
if command -v createdb &>/dev/null; then
    createdb logosai 2>/dev/null && log "Database 'logosai' created" || log "Database 'logosai' exists"
fi

# Configure .env files
if [ ! -f logosai-api/.env ]; then
    cp logosai-api/.env.example logosai-api/.env
    log "Created logosai-api/.env"
else
    log "logosai-api/.env exists"
fi

if [ ! -f logosai-web/.env.local ]; then
    cp logosai-web/.env.example logosai-web/.env.local
    log "Created logosai-web/.env.local"
else
    log "logosai-web/.env.local exists"
fi

# Run migrations
echo -ne "  ${DIM}  Running migrations...${NC}\r"
(cd logosai-api && python -m alembic upgrade head 2>/dev/null) \
    && log "Database migrations complete" \
    || warn "Migrations failed — check DATABASE_URL in logosai-api/.env"

# ══════════════════════════════════════════
# Step 6: Start services
# ══════════════════════════════════════════
step 6 "Starting services"

mkdir -p logs

# Kill any existing processes on our ports
for PORT in 8888 8090 8010; do
    PID=$(lsof -ti :$PORT 2>/dev/null || true)
    if [ -n "$PID" ]; then
        kill $PID 2>/dev/null || true
        sleep 1
    fi
done

# Start ACP server
(cd logosai-framework/samples && \
    nohup "$WORKDIR/.venv/bin/python" sample_acp_server.py \
    >> "$WORKDIR/logs/acp.log" 2>&1 &)
ACP_PID=$!
echo "$ACP_PID" > "$WORKDIR/logs/acp.pid"
sleep 2
log "ACP server (PID $ACP_PID, port 8888)"

# Start logos_api
PYTHONPATH="$WORKDIR/logosai-ontology:$WORKDIR/logosai-framework:$PYTHONPATH" \
    nohup "$WORKDIR/.venv/bin/python" -m uvicorn app.main:app \
    --host 0.0.0.0 --port 8090 \
    --app-dir "$WORKDIR/logosai-api" \
    >> "$WORKDIR/logs/api.log" 2>&1 &
API_PID=$!
echo "$API_PID" > "$WORKDIR/logs/api.pid"
sleep 3
log "logos_api (PID $API_PID, port 8090)"

# Start logos_web
(cd logosai-web && \
    nohup npx next dev -p 8010 \
    >> "$WORKDIR/logs/web.log" 2>&1 &)
WEB_PID=$!
echo "$WEB_PID" > "$WORKDIR/logs/web.pid"
sleep 5
log "logos_web (PID $WEB_PID, port 8010)"

# ══════════════════════════════════════════
# Step 7: Health check
# ══════════════════════════════════════════
step 7 "Verifying"

check() {
    local name="$1" url="$2"
    if curl -sf --max-time 5 "$url" > /dev/null 2>&1; then
        log "$name — $url"
    else
        warn "$name — not responding yet (check logs/$3)"
    fi
}

check "ACP Server"  "http://localhost:8888/jsonrpc" "acp.log"
check "logos_api"    "http://localhost:8090/health"  "api.log"
check "logos_web"    "http://localhost:8010"          "web.log"

# ══════════════════════════════════════════
# Done!
# ══════════════════════════════════════════
echo ""
echo -e "${GREEN}  ╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}  ║${NC}                                          ${GREEN}║${NC}"
echo -e "${GREEN}  ║${NC}   ${BOLD}LogosAI is ready!${NC}                      ${GREEN}║${NC}"
echo -e "${GREEN}  ║${NC}                                          ${GREEN}║${NC}"
echo -e "${GREEN}  ╚══════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}Services:${NC}"
echo -e "    Frontend      ${BLUE}http://localhost:8010${NC}"
echo -e "    API Docs      ${BLUE}http://localhost:8090/docs${NC}"
echo -e "    ACP Server    ${BLUE}http://localhost:8888${NC}"
echo ""
echo -e "  ${BOLD}Workspace:${NC}        $WORKDIR"
echo -e "  ${BOLD}Logs:${NC}             $WORKDIR/logs/"
echo -e "  ${BOLD}Python venv:${NC}      source $WORKDIR/.venv/bin/activate"
echo ""
echo -e "  ${BOLD}Stop all:${NC}"
echo -e "    kill \$(cat $WORKDIR/logs/*.pid)"
echo ""
echo -e "  ${BOLD}Restart:${NC}"
echo -e "    cd $WORKDIR && ./quickstart.sh"
echo ""

# Create a stop script
cat > "$WORKDIR/stop.sh" << 'STOP'
#!/usr/bin/env bash
DIR="$(cd "$(dirname "$0")" && pwd)"
for f in "$DIR"/logs/*.pid; do
    [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null && rm "$f"
done
echo "All LogosAI services stopped."
STOP
chmod +x "$WORKDIR/stop.sh"

# Open browser
if command -v open &>/dev/null; then
    open "http://localhost:8010" 2>/dev/null || true
elif command -v xdg-open &>/dev/null; then
    xdg-open "http://localhost:8010" 2>/dev/null || true
fi
