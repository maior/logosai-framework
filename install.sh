#!/usr/bin/env bash
#
# ╔═══════════════════════════════════════════════════════════════════╗
# ║  LogosAI Installer                                                ║
# ║  Multi-Agent AI Platform — Full Stack Setup                       ║
# ║                                                                   ║
# ║  Usage:                                                           ║
# ║    curl -fsSL https://raw.githubusercontent.com/                  ║
# ║      maior/logosai-framework/main/install.sh | bash               ║
# ║                                                                   ║
# ║  Prerequisites: Python 3.11+, Node 18+, PostgreSQL 14+, Git      ║
# ║  Custom dir:    LOGOSAI_DIR=~/mydir curl ... | bash               ║
# ╚═══════════════════════════════════════════════════════════════════╝
#

set -e

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Theme
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
R='\033[0;31m'
G='\033[0;32m'
Y='\033[1;33m'
B='\033[0;34m'
P='\033[0;35m'
C='\033[0;36m'
W='\033[1;37m'
NC='\033[0m'
BOLD='\033[1m'
DIM='\033[2m'
ITAL='\033[3m'
BG_G='\033[42m'
BG_R='\033[41m'
BG_B='\033[44m'
BG_P='\033[45m'

ok()   { echo -e "  ${G}●${NC} $1"; }
info() { echo -e "  ${C}◆${NC} $1"; }
warn() { echo -e "  ${Y}▲${NC} $1"; }
fail() { echo -e "  ${R}✖${NC} $1"; }
dim()  { echo -e "  ${DIM}$1${NC}"; }

progress_bar() {
    local current=$1 total=$2 width=30
    local pct=$((current * 100 / total))
    local filled=$((current * width / total))
    local empty=$((width - filled))
    local bar=""
    for ((i=0; i<filled; i++)); do bar+="█"; done
    for ((i=0; i<empty; i++)); do bar+="░"; done
    echo -ne "\r  ${P}${bar}${NC} ${W}${pct}%${NC} "
}

TOTAL_STEPS=5
current_step=0
step() {
    current_step=$((current_step + 1))
    echo ""
    echo -e "  ${BG_P}${W} STEP ${current_step}/${TOTAL_STEPS} ${NC} ${BOLD}$1${NC}"
    echo -e "  ${DIM}$(printf '%.0s─' {1..50})${NC}"
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Banner
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
clear 2>/dev/null || true
echo ""
echo -e "${P}"
cat << 'ASCII'

    ██╗      ██████╗  ██████╗  ██████╗ ███████╗     █████╗ ██╗
    ██║     ██╔═══██╗██╔════╝ ██╔═══██╗██╔════╝    ██╔══██╗██║
    ██║     ██║   ██║██║  ███╗██║   ██║███████╗    ███████║██║
    ██║     ██║   ██║██║   ██║██║   ██║╚════██║    ██╔══██║██║
    ███████╗╚██████╔╝╚██████╔╝╚██████╔╝███████║    ██║  ██║██║
    ╚══════╝ ╚═════╝  ╚═════╝  ╚═════╝ ╚══════╝    ╚═╝  ╚═╝╚═╝

ASCII
echo -e "${NC}"
echo -e "  ${BOLD}${W}Multi-Agent AI Platform${NC}  ${DIM}v1.0${NC}"
echo -e "  ${DIM}Ontology-driven orchestration · Agent debate · Self-evolution${NC}"
echo ""
echo -e "  ${DIM}┌──────────────────────────────────────────────────────┐${NC}"
echo -e "  ${DIM}│${NC}  ${C}Frontend${NC} ─→ ${B}API${NC} ─→ ${Y}Ontology${NC} ─→ ${G}Agents${NC}             ${DIM}│${NC}"
echo -e "  ${DIM}│${NC}  ${C}:8010${NC}       ${B}:8090${NC}   ${Y}Brain${NC}      ${G}:8888${NC}              ${DIM}│${NC}"
echo -e "  ${DIM}└──────────────────────────────────────────────────────┘${NC}"
echo ""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Workspace
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WORKDIR="${LOGOSAI_DIR:-$HOME/logosai}"

echo -e "  ${W}Install directory${NC}  ${BOLD}$WORKDIR${NC}"
echo ""
echo -e "  ${DIM}What this installer does:${NC}"
echo -e "    ${DIM}1.${NC} Clone 4 open-source repositories"
echo -e "    ${DIM}2.${NC} Create Python virtual environment"
echo -e "    ${DIM}3.${NC} Install all dependencies (Python + Node.js)"
echo -e "    ${DIM}4.${NC} Set up PostgreSQL database & run migrations"
echo -e "    ${DIM}5.${NC} Generate ${W}start.sh${NC} / ${W}stop.sh${NC} / ${W}status.sh${NC}"
echo ""

# Confirm
if [ -t 0 ]; then
    echo -ne "  ${BOLD}Proceed with installation?${NC} ${DIM}[Y/n]${NC} "
    read -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Nn]$ ]]; then
        echo -e "\n  ${DIM}Installation cancelled.${NC}\n"
        exit 0
    fi
fi

TIMER_START=$(date +%s)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Step 1: Prerequisites
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
step "Checking prerequisites"

MISSING=0
PG_OK=0

# Python
if command -v python3 &>/dev/null; then
    PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 11 ]; then
        ok "Python ${W}$PY_VER${NC}"
    else
        fail "Python ${W}3.11+${NC} required ${DIM}(found $PY_VER)${NC}"
        MISSING=1
    fi
else
    fail "python3 not found"
    MISSING=1
fi

# Node
if command -v node &>/dev/null; then
    ok "Node.js ${W}$(node --version)${NC}"
else
    fail "Node.js not found ${DIM}— https://nodejs.org${NC}"
    MISSING=1
fi

# npm
if command -v npm &>/dev/null; then
    ok "npm ${W}$(npm --version)${NC}"
else
    fail "npm not found"
    MISSING=1
fi

# Git
if command -v git &>/dev/null; then
    ok "Git ${W}$(git --version | cut -d' ' -f3)${NC}"
else
    fail "git not found"
    MISSING=1
fi

# PostgreSQL
if command -v psql &>/dev/null; then
    ok "PostgreSQL ${W}$(psql --version | grep -oE '[0-9]+\.[0-9]+')${NC}"
    PG_OK=1
elif command -v docker &>/dev/null; then
    warn "psql not found — will use ${W}Docker${NC} for PostgreSQL"
    PG_OK=2
else
    fail "PostgreSQL not found"
    echo ""
    dim "  Install options:"
    dim "    macOS:   brew install postgresql@15 && brew services start postgresql@15"
    dim "    Ubuntu:  sudo apt install postgresql && sudo systemctl start postgresql"
    dim "    Docker:  docker run -d -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:15"
    echo ""
    MISSING=1
fi

if [ "$MISSING" -eq 1 ]; then
    echo ""
    fail "${BOLD}Missing prerequisites.${NC} Install them and try again."
    echo ""
    exit 1
fi

ok "${G}All prerequisites satisfied${NC}"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Step 2: Clone repositories
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
step "Cloning repositories"

mkdir -p "$WORKDIR"
cd "$WORKDIR"
info "Workspace → ${W}$WORKDIR${NC}"

REPOS=(
    "logosai-framework|https://github.com/maior/logosai-framework.git|Python SDK + Agent Runtime"
    "logosai-ontology|https://github.com/maior/logosai-ontology.git|Orchestration Engine (KG+LLM+GNN+RL)"
    "logosai-api|https://github.com/maior/logosai-api.git|FastAPI Backend Server"
    "logosai-web|https://github.com/maior/logosai-web.git|Next.js Frontend"
)

REPO_COUNT=0
REPO_TOTAL=${#REPOS[@]}

for entry in "${REPOS[@]}"; do
    IFS='|' read -r name url desc <<< "$entry"
    REPO_COUNT=$((REPO_COUNT + 1))

    if [ -d "$name" ]; then
        (cd "$name" && git pull --ff-only -q 2>/dev/null) || true
        ok "${W}$name${NC} ${DIM}(updated)${NC}"
    else
        progress_bar "$REPO_COUNT" "$REPO_TOTAL"
        echo -ne "${DIM}$name${NC}"
        git clone --depth 1 -q "$url" "$name"
        echo -ne "\r$(printf '%-60s' '')\r"
        ok "${W}$name${NC} — ${DIM}$desc${NC}"
    fi
done

echo ""
info "${W}4${NC} repositories ready"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Step 3: Install dependencies
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
step "Installing dependencies"

# Python venv
if [ ! -d ".venv" ]; then
    echo -ne "  ${DIM}Creating virtual environment...${NC}\r"
    python3 -m venv .venv
fi
source .venv/bin/activate
ok "Python venv ${DIM}(.venv — $(python --version))${NC}"

echo -ne "  ${DIM}Upgrading pip...${NC}\r"
pip install --upgrade pip -q 2>/dev/null
echo -ne "\r$(printf '%-60s' '')\r"

# logosai framework
echo -ne "  ${DIM}◇ Installing logosai framework...${NC}"
pip install -e logosai-framework/ -q 2>/dev/null
echo -ne "\r$(printf '%-60s' '')\r"
ok "${W}logosai${NC} framework ${DIM}(pip install -e)${NC}"

# ontology
if [ -f logosai-ontology/requirements.txt ]; then
    echo -ne "  ${DIM}◇ Installing ontology dependencies...${NC}"
    pip install -r logosai-ontology/requirements.txt -q 2>/dev/null
    echo -ne "\r$(printf '%-60s' '')\r"
    ok "${W}ontology${NC} dependencies"
fi

# logos_api
echo -ne "  ${DIM}◇ Installing logos_api dependencies...${NC}"
pip install -e logosai-api/ -q 2>/dev/null
echo -ne "\r$(printf '%-60s' '')\r"
ok "${W}logos_api${NC} dependencies ${DIM}(FastAPI, SQLAlchemy, etc.)${NC}"

# Node
echo -ne "  ${DIM}◇ Running npm install for logos_web...${NC}"
(cd logosai-web && npm install --silent 2>/dev/null)
echo -ne "\r$(printf '%-60s' '')\r"
ok "${W}logos_web${NC} dependencies ${DIM}(Next.js, React, Tailwind)${NC}"

echo ""
info "All dependencies installed"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Step 4: Database setup
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
step "Setting up database"

# Docker PostgreSQL if needed
if [ "$PG_OK" -eq 2 ]; then
    # Check if container exists but is stopped
    if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q logosai-pg; then
        if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -q logosai-pg; then
            echo -ne "  ${DIM}◇ Restarting stopped PostgreSQL container...${NC}"
            docker start logosai-pg >/dev/null 2>&1
            echo -ne "\r$(printf '%-60s' '')\r"
            ok "PostgreSQL ${DIM}(Docker: logosai-pg restarted)${NC}"
        else
            ok "PostgreSQL Docker container running"
        fi
    else
        echo -ne "  ${DIM}◇ Starting PostgreSQL via Docker...${NC}"
        docker run -d --name logosai-pg \
            -e POSTGRES_USER=postgres \
            -e POSTGRES_PASSWORD=postgres \
            -e POSTGRES_DB=logosai \
            -p 5432:5432 \
            postgres:15-alpine >/dev/null 2>&1
        echo -ne "\r$(printf '%-60s' '')\r"
        ok "PostgreSQL ${DIM}(Docker: logosai-pg — postgres:postgres@localhost:5432)${NC}"
    fi

    # Wait for PostgreSQL to accept connections
    echo -ne "  ${DIM}◇ Waiting for PostgreSQL to accept connections...${NC}"
    for i in $(seq 1 15); do
        if docker exec logosai-pg pg_isready -U postgres >/dev/null 2>&1; then
            echo -ne "\r$(printf '%-60s' '')\r"
            ok "PostgreSQL is ready"
            break
        fi
        sleep 1
    done
fi

# Create database
if [ "$PG_OK" -eq 1 ] && command -v createdb &>/dev/null; then
    # Local PostgreSQL — use createdb
    createdb logosai 2>/dev/null \
        && ok "Database ${W}logosai${NC} created" \
        || ok "Database ${W}logosai${NC} exists"
elif [ "$PG_OK" -eq 2 ]; then
    # Docker PostgreSQL — POSTGRES_DB=logosai already creates it
    # But verify it exists, create if somehow missing
    docker exec logosai-pg psql -U postgres -lqt 2>/dev/null | grep -qw logosai \
        && ok "Database ${W}logosai${NC} exists ${DIM}(Docker)${NC}" \
        || { docker exec logosai-pg createdb -U postgres logosai 2>/dev/null; ok "Database ${W}logosai${NC} created ${DIM}(Docker)${NC}"; }
fi

# .env files — set correct DATABASE_URL based on PostgreSQL mode
if [ ! -f logosai-api/.env ]; then
    cp logosai-api/.env.example logosai-api/.env
    ok "Config ${W}logosai-api/.env${NC} ${DIM}(from .env.example)${NC}"
else
    ok "Config ${W}logosai-api/.env${NC} exists"
fi

# Ensure DATABASE_URL is set correctly in .env
if [ "$PG_OK" -eq 2 ]; then
    # Docker mode — make sure .env points to localhost:5432 with postgres:postgres
    if grep -q "DATABASE_URL" logosai-api/.env 2>/dev/null; then
        dim "  DATABASE_URL: postgresql+asyncpg://postgres:postgres@localhost:5432/logosai"
    fi
elif [ "$PG_OK" -eq 1 ]; then
    dim "  DATABASE_URL: check logosai-api/.env matches your PostgreSQL credentials"
fi

if [ ! -f logosai-web/.env.local ]; then
    cp logosai-web/.env.example logosai-web/.env.local
    ok "Config ${W}logosai-web/.env.local${NC} ${DIM}(from .env.example)${NC}"
else
    ok "Config ${W}logosai-web/.env.local${NC} exists"
fi

# Migrations
echo -ne "  ${DIM}◇ Running Alembic migrations...${NC}"
MIGRATION_OUTPUT=$(cd logosai-api && python -m alembic upgrade head 2>&1) \
    && { echo -ne "\r$(printf '%-60s' '')\r"; ok "Database migrations ${G}complete${NC}"; } \
    || {
        echo -ne "\r$(printf '%-60s' '')\r"
        warn "Migrations failed"
        echo ""
        dim "  Possible causes:"
        dim "    - PostgreSQL is not running or not accepting connections"
        dim "    - DATABASE_URL in logosai-api/.env is incorrect"
        dim "    - Database 'logosai' does not exist"
        echo ""
        dim "  To fix manually:"
        dim "    1. Edit $WORKDIR/logosai-api/.env"
        dim "    2. Set DATABASE_URL=postgresql+asyncpg://USER:PASS@HOST:5432/logosai"
        dim "    3. Run: cd $WORKDIR/logosai-api && ../.venv/bin/python -m alembic upgrade head"
        echo ""
    }

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Step 5: Generate management scripts
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
step "Generating management scripts"

mkdir -p logs

# ── start.sh ──────────────────────────────
cat > "$WORKDIR/start.sh" << 'STARTEOF'
#!/usr/bin/env bash
DIR="$(cd "$(dirname "$0")" && pwd)"
source "$DIR/.venv/bin/activate"

G='\033[0;32m'; B='\033[0;34m'; P='\033[0;35m'; C='\033[0;36m'
W='\033[1;37m'; NC='\033[0m'; BOLD='\033[1m'; DIM='\033[2m'

echo ""
echo -e "${P}  ╔══════════════════════════════════════╗${NC}"
echo -e "${P}  ║${NC}  ${BOLD}LogosAI${NC} — Starting services          ${P}║${NC}"
echo -e "${P}  ╚══════════════════════════════════════╝${NC}"
echo ""

mkdir -p "$DIR/logs"

for PORT in 8888 8090 8010; do
    PID=$(lsof -ti :$PORT 2>/dev/null || true)
    [ -n "$PID" ] && kill $PID 2>/dev/null && sleep 1
done

# ACP server
(cd "$DIR/logosai-framework/samples" && \
    nohup "$DIR/.venv/bin/python" sample_acp_server.py \
    >> "$DIR/logs/acp.log" 2>&1 &)
echo "$!" > "$DIR/logs/acp.pid"
sleep 2
echo -e "  ${G}●${NC} ACP Server     ${B}http://localhost:8888${NC}  ${DIM}PID $(cat "$DIR/logs/acp.pid")${NC}"

# logos_api
PYTHONPATH="$DIR/logosai-ontology:$DIR/logosai-framework:$PYTHONPATH" \
    nohup "$DIR/.venv/bin/python" -m uvicorn app.main:app \
    --host 0.0.0.0 --port 8090 \
    --app-dir "$DIR/logosai-api" \
    >> "$DIR/logs/api.log" 2>&1 &
echo "$!" > "$DIR/logs/api.pid"
sleep 3
echo -e "  ${G}●${NC} logos_api       ${B}http://localhost:8090${NC}  ${DIM}PID $(cat "$DIR/logs/api.pid")${NC}"

# logos_web
(cd "$DIR/logosai-web" && \
    nohup npx next dev -p 8010 \
    >> "$DIR/logs/web.log" 2>&1 &)
echo "$!" > "$DIR/logs/web.pid"
sleep 5
echo -e "  ${G}●${NC} logos_web       ${B}http://localhost:8010${NC}  ${DIM}PID $(cat "$DIR/logs/web.pid")${NC}"

echo ""
echo -e "  ${DIM}──────────────────────────────────────${NC}"
echo -e "  ${W}Chat:${NC}      ${B}http://localhost:8010${NC}"
echo -e "  ${W}API Docs:${NC}  ${B}http://localhost:8090/docs${NC}"
echo -e "  ${W}Logs:${NC}      ${DIM}$DIR/logs/${NC}"
echo -e "  ${W}Stop:${NC}      ${DIM}./stop.sh${NC}"
echo ""

if command -v open &>/dev/null; then
    open "http://localhost:8010" 2>/dev/null || true
elif command -v xdg-open &>/dev/null; then
    xdg-open "http://localhost:8010" 2>/dev/null || true
fi
STARTEOF
chmod +x "$WORKDIR/start.sh"
ok "${W}start.sh${NC} — start all services"

# ── stop.sh ───────────────────────────────
cat > "$WORKDIR/stop.sh" << 'STOPEOF'
#!/usr/bin/env bash
DIR="$(cd "$(dirname "$0")" && pwd)"

R='\033[0;31m'; W='\033[1;37m'; P='\033[0;35m'; NC='\033[0m'; BOLD='\033[1m'; DIM='\033[2m'

echo ""
echo -e "${P}  ╔══════════════════════════════════════╗${NC}"
echo -e "${P}  ║${NC}  ${BOLD}LogosAI${NC} — Stopping services          ${P}║${NC}"
echo -e "${P}  ╚══════════════════════════════════════╝${NC}"
echo ""

STOPPED=0
for f in "$DIR"/logs/*.pid; do
    [ -f "$f" ] || continue
    PID=$(cat "$f")
    NAME=$(basename "$f" .pid)
    if kill "$PID" 2>/dev/null; then
        echo -e "  ${R}■${NC} $NAME ${DIM}(PID $PID)${NC}"
        STOPPED=$((STOPPED + 1))
    fi
    rm -f "$f"
done

if [ "$STOPPED" -eq 0 ]; then
    echo -e "  ${DIM}No services were running.${NC}"
else
    echo ""
    echo -e "  ${W}$STOPPED${NC} service(s) stopped."
fi
echo ""
STOPEOF
chmod +x "$WORKDIR/stop.sh"
ok "${W}stop.sh${NC} — stop all services"

# ── status.sh ─────────────────────────────
cat > "$WORKDIR/status.sh" << 'STATUSEOF'
#!/usr/bin/env bash
DIR="$(cd "$(dirname "$0")" && pwd)"

G='\033[0;32m'; R='\033[0;31m'; B='\033[0;34m'; P='\033[0;35m'
W='\033[1;37m'; NC='\033[0m'; BOLD='\033[1m'; DIM='\033[2m'

echo ""
echo -e "${P}  ╔══════════════════════════════════════╗${NC}"
echo -e "${P}  ║${NC}  ${BOLD}LogosAI${NC} — Service Status             ${P}║${NC}"
echo -e "${P}  ╚══════════════════════════════════════╝${NC}"
echo ""

check() {
    local name="$1" port="$2" pidfile="$DIR/logs/$3.pid" url="$4"
    local pid_status="" http_status=""

    if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
        pid_status="${G}● running${NC} ${DIM}(PID $(cat "$pidfile"))${NC}"
    else
        pid_status="${R}■ stopped${NC}"
    fi

    printf "  %-14s %-42b ${B}:%s${NC}\n" "$name" "$pid_status" "$port"
}

check "ACP Server"  8888 acp
check "logos_api"   8090 api
check "logos_web"   8010 web

echo ""
echo -e "  ${DIM}Chat:      http://localhost:8010${NC}"
echo -e "  ${DIM}API Docs:  http://localhost:8090/docs${NC}"
echo ""
STATUSEOF
chmod +x "$WORKDIR/status.sh"
ok "${W}status.sh${NC} — check service status"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Complete
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TIMER_END=$(date +%s)
ELAPSED=$((TIMER_END - TIMER_START))
MINUTES=$((ELAPSED / 60))
SECONDS=$((ELAPSED % 60))

echo ""
echo ""
echo -e "${G}"
cat << 'DONE'
    ╔═══════════════════════════════════════════════════════╗
    ║                                                       ║
    ║   ✓  Installation complete!                           ║
    ║                                                       ║
    ╚═══════════════════════════════════════════════════════╝
DONE
echo -e "${NC}"

echo -e "  ${DIM}Completed in ${W}${MINUTES}m ${SECONDS}s${NC}"
echo ""
echo -e "  ${DIM}┌──────────────────────────────────────────────────────┐${NC}"
echo -e "  ${DIM}│${NC}                                                      ${DIM}│${NC}"
echo -e "  ${DIM}│${NC}  ${W}Workspace${NC}    $WORKDIR$(printf '%*s' $((23 - ${#WORKDIR} + ${#HOME} + 2)) '')${DIM}│${NC}"
echo -e "  ${DIM}│${NC}                                                      ${DIM}│${NC}"
echo -e "  ${DIM}│${NC}  ${W}Next steps:${NC}                                        ${DIM}│${NC}"
echo -e "  ${DIM}│${NC}                                                      ${DIM}│${NC}"
echo -e "  ${DIM}│${NC}    ${C}cd $WORKDIR${NC}$(printf '%*s' $((33 - ${#WORKDIR} + ${#HOME} + 2)) '')${DIM}│${NC}"
echo -e "  ${DIM}│${NC}    ${G}./start.sh${NC}        Start all services              ${DIM}│${NC}"
echo -e "  ${DIM}│${NC}    ${R}./stop.sh${NC}         Stop all services               ${DIM}│${NC}"
echo -e "  ${DIM}│${NC}    ${B}./status.sh${NC}       Check service status            ${DIM}│${NC}"
echo -e "  ${DIM}│${NC}                                                      ${DIM}│${NC}"
echo -e "  ${DIM}│${NC}  ${DIM}Tip: Edit logosai-api/.env for DB & API keys${NC}        ${DIM}│${NC}"
echo -e "  ${DIM}│${NC}                                                      ${DIM}│${NC}"
echo -e "  ${DIM}└──────────────────────────────────────────────────────┘${NC}"
echo ""
echo -e "  ${DIM}Documentation:  https://github.com/maior/logosai-framework${NC}"
echo -e "  ${DIM}Issues:         https://github.com/maior/logosai-framework/issues${NC}"
echo ""
