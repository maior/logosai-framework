#!/usr/bin/env bash
#
# LogosAI Installer
# Downloads and sets up the full LogosAI stack.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/maior/logosai-framework/main/install.sh | bash
#
# What it does:
#   1. Creates ~/logosai/ workspace
#   2. Clones all 4 repositories
#   3. Sets up Python venv + Node dependencies
#   4. Creates database + runs migrations
#   5. Generates start.sh / stop.sh scripts
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

TOTAL_STEPS=5

# ── Banner ──
echo ""
echo -e "${PURPLE}  ╔══════════════════════════════════════════╗${NC}"
echo -e "${PURPLE}  ║${NC}                                          ${PURPLE}║${NC}"
echo -e "${PURPLE}  ║${NC}   ${BOLD}LogosAI${NC}  Multi-Agent AI Platform       ${PURPLE}║${NC}"
echo -e "${PURPLE}  ║${NC}   ${DIM}Installer${NC}                               ${PURPLE}║${NC}"
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
PG_OK=0

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
    log "Node.js $(node --version)"
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
step 2 "Cloning repositories"

mkdir -p "$WORKDIR"
cd "$WORKDIR"
log "Directory: $WORKDIR"

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
# Step 3: Install dependencies
# ══════════════════════════════════════════
step 3 "Installing dependencies"

# Python
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
log "Python venv: .venv ($(python --version))"

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

# Node
echo -ne "  ${DIM}  Running npm install...${NC}\r"
(cd logosai-web && npm install --silent 2>/dev/null)
log "logos_web (Next.js)"

# ══════════════════════════════════════════
# Step 4: Database setup
# ══════════════════════════════════════════
step 4 "Setting up database"

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
        echo -ne "  ${DIM}  Waiting for PostgreSQL to be ready...${NC}\r"
        sleep 5
    else
        log "PostgreSQL Docker container already running"
    fi
fi

# Create database
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
echo -ne "  ${DIM}  Running database migrations...${NC}\r"
(cd logosai-api && python -m alembic upgrade head 2>/dev/null) \
    && log "Database migrations complete" \
    || warn "Migrations failed — check DATABASE_URL in logosai-api/.env"

# ══════════════════════════════════════════
# Step 5: Generate management scripts
# ══════════════════════════════════════════
step 5 "Creating management scripts"

mkdir -p logs

# ── start.sh ──
cat > "$WORKDIR/start.sh" << 'START_SCRIPT'
#!/usr/bin/env bash
#
# LogosAI — Start all services
#
DIR="$(cd "$(dirname "$0")" && pwd)"
source "$DIR/.venv/bin/activate"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
NC='\033[0m'
BOLD='\033[1m'
DIM='\033[2m'

echo ""
echo -e "${PURPLE}  LogosAI${NC} — Starting services..."
echo ""

mkdir -p "$DIR/logs"

# Kill existing processes on our ports
for PORT in 8888 8090 8010; do
    PID=$(lsof -ti :$PORT 2>/dev/null || true)
    if [ -n "$PID" ]; then
        kill $PID 2>/dev/null || true
        sleep 1
    fi
done

# ACP server (port 8888)
(cd "$DIR/logosai-framework/samples" && \
    nohup "$DIR/.venv/bin/python" sample_acp_server.py \
    >> "$DIR/logs/acp.log" 2>&1 &)
echo "$!" > "$DIR/logs/acp.pid"
sleep 2
echo -e "  ${GREEN}✓${NC} ACP server    ${BLUE}http://localhost:8888${NC}  (PID $(cat "$DIR/logs/acp.pid"))"

# logos_api (port 8090)
PYTHONPATH="$DIR/logosai-ontology:$DIR/logosai-framework:$PYTHONPATH" \
    nohup "$DIR/.venv/bin/python" -m uvicorn app.main:app \
    --host 0.0.0.0 --port 8090 \
    --app-dir "$DIR/logosai-api" \
    >> "$DIR/logs/api.log" 2>&1 &
echo "$!" > "$DIR/logs/api.pid"
sleep 3
echo -e "  ${GREEN}✓${NC} logos_api      ${BLUE}http://localhost:8090${NC}  (PID $(cat "$DIR/logs/api.pid"))"

# logos_web (port 8010)
(cd "$DIR/logosai-web" && \
    nohup npx next dev -p 8010 \
    >> "$DIR/logs/web.log" 2>&1 &)
echo "$!" > "$DIR/logs/web.pid"
sleep 5
echo -e "  ${GREEN}✓${NC} logos_web      ${BLUE}http://localhost:8010${NC}  (PID $(cat "$DIR/logs/web.pid"))"

echo ""
echo -e "  ${BOLD}API Docs:${NC}  ${BLUE}http://localhost:8090/docs${NC}"
echo -e "  ${BOLD}Logs:${NC}      $DIR/logs/"
echo -e "  ${BOLD}Stop:${NC}      $DIR/stop.sh"
echo ""

# Open browser
if command -v open &>/dev/null; then
    open "http://localhost:8010" 2>/dev/null || true
elif command -v xdg-open &>/dev/null; then
    xdg-open "http://localhost:8010" 2>/dev/null || true
fi
START_SCRIPT
chmod +x "$WORKDIR/start.sh"
log "start.sh"

# ── stop.sh ──
cat > "$WORKDIR/stop.sh" << 'STOP_SCRIPT'
#!/usr/bin/env bash
#
# LogosAI — Stop all services
#
DIR="$(cd "$(dirname "$0")" && pwd)"

RED='\033[0;31m'
NC='\033[0m'

echo ""
STOPPED=0
for f in "$DIR"/logs/*.pid; do
    [ -f "$f" ] || continue
    PID=$(cat "$f")
    NAME=$(basename "$f" .pid)
    if kill "$PID" 2>/dev/null; then
        echo -e "  ${RED}■${NC} Stopped $NAME (PID $PID)"
        STOPPED=$((STOPPED + 1))
    fi
    rm -f "$f"
done

if [ "$STOPPED" -eq 0 ]; then
    echo "  No services were running."
else
    echo ""
    echo "  $STOPPED service(s) stopped."
fi
echo ""
STOP_SCRIPT
chmod +x "$WORKDIR/stop.sh"
log "stop.sh"

# ── status.sh ──
cat > "$WORKDIR/status.sh" << 'STATUS_SCRIPT'
#!/usr/bin/env bash
#
# LogosAI — Check service status
#
DIR="$(cd "$(dirname "$0")" && pwd)"

GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'
BOLD='\033[1m'

echo ""
echo -e "  ${BOLD}LogosAI Service Status${NC}"
echo ""

check() {
    local name="$1" port="$2" pidfile="$DIR/logs/$3.pid"
    local status="${RED}■ stopped${NC}"
    if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
        status="${GREEN}● running${NC} (PID $(cat "$pidfile"))"
    fi
    printf "  %-16s %-30b ${BLUE}:%s${NC}\n" "$name" "$status" "$port"
}

check "ACP server"  8888 acp
check "logos_api"   8090 api
check "logos_web"   8010 web
echo ""
STATUS_SCRIPT
chmod +x "$WORKDIR/status.sh"
log "status.sh"

# ══════════════════════════════════════════
# Done!
# ══════════════════════════════════════════
echo ""
echo -e "${GREEN}  ╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}  ║${NC}                                          ${GREEN}║${NC}"
echo -e "${GREEN}  ║${NC}   ${BOLD}Installation complete!${NC}                 ${GREEN}║${NC}"
echo -e "${GREEN}  ║${NC}                                          ${GREEN}║${NC}"
echo -e "${GREEN}  ╚══════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}Workspace:${NC}  $WORKDIR"
echo ""
echo -e "  ${BOLD}Next steps:${NC}"
echo -e "    cd $WORKDIR"
echo -e "    ./start.sh          ${DIM}# Start all services${NC}"
echo -e "    ./stop.sh           ${DIM}# Stop all services${NC}"
echo -e "    ./status.sh         ${DIM}# Check service status${NC}"
echo ""
echo -e "  ${DIM}Tip: Edit logosai-api/.env for database and API key settings${NC}"
echo ""
