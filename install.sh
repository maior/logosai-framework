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

# Helper: read from /dev/tty (works even when piped from curl)
ask() {
    local prompt="$1" var="$2"
    echo -ne "$prompt" >/dev/tty
    read -r $var </dev/tty 2>/dev/null || true
}

# Confirm
if [ -e /dev/tty ]; then
    echo -ne "  ${BOLD}Proceed with installation?${NC} ${DIM}[Y/n]${NC} " >/dev/tty
    read -n 1 -r REPLY </dev/tty 2>/dev/null || REPLY="y"
    echo "" >/dev/tty
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
OS_TYPE="unknown"
if [ -f /etc/os-release ]; then
    OS_TYPE="linux"
    . /etc/os-release 2>/dev/null
    DISTRO="${ID:-linux}"
elif [[ "$(uname)" == "Darwin" ]]; then
    OS_TYPE="macos"
    DISTRO="macos"
fi

# Helper: show install instructions per OS
install_hint() {
    local pkg="$1"
    case "$pkg" in
        python)
            if [ "$DISTRO" = "ubuntu" ] || [ "$DISTRO" = "debian" ]; then
                dim "    Install: ${W}sudo apt install python3.11 python3.11-venv python3-pip${NC}"
            elif [ "$DISTRO" = "macos" ]; then
                dim "    Install: ${W}brew install python@3.11${NC}"
            else
                dim "    Install: https://www.python.org/downloads/"
            fi
            ;;
        node)
            if [ "$DISTRO" = "ubuntu" ] || [ "$DISTRO" = "debian" ]; then
                dim "    Install: ${W}curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash - && sudo apt install nodejs${NC}"
            elif [ "$DISTRO" = "macos" ]; then
                dim "    Install: ${W}brew install node@18${NC}"
            else
                dim "    Install: https://nodejs.org/"
            fi
            ;;
        git)
            if [ "$DISTRO" = "ubuntu" ] || [ "$DISTRO" = "debian" ]; then
                dim "    Install: ${W}sudo apt install git${NC}"
            elif [ "$DISTRO" = "macos" ]; then
                dim "    Install: ${W}xcode-select --install${NC}"
            fi
            ;;
        postgresql)
            if [ "$DISTRO" = "ubuntu" ] || [ "$DISTRO" = "debian" ]; then
                dim "    Install: ${W}sudo apt install postgresql && sudo systemctl start postgresql${NC}"
            elif [ "$DISTRO" = "macos" ]; then
                dim "    Install: ${W}brew install postgresql@15 && brew services start postgresql@15${NC}"
            fi
            dim "    Or Docker: ${W}docker run -d -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:15${NC}"
            ;;
    esac
}

# ── Python ──
if command -v python3 &>/dev/null; then
    PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 11 ]; then
        ok "Python ${W}$PY_VER${NC}"

        # Check venv module (Ubuntu requires python3.x-venv package)
        if ! python3 -c "import venv" 2>/dev/null; then
            fail "Python venv module not found"
            if [ "$DISTRO" = "ubuntu" ] || [ "$DISTRO" = "debian" ]; then
                dim "    Install: ${W}sudo apt install python${PY_VER}-venv${NC}"
            fi
            MISSING=1
        fi

        # Check pip
        if ! python3 -m pip --version &>/dev/null; then
            fail "pip not found"
            if [ "$DISTRO" = "ubuntu" ] || [ "$DISTRO" = "debian" ]; then
                dim "    Install: ${W}sudo apt install python3-pip${NC}"
            fi
            MISSING=1
        fi
    else
        fail "Python ${W}3.11+${NC} required ${DIM}(found $PY_VER)${NC}"
        install_hint python
        MISSING=1
    fi
else
    fail "python3 not found"
    install_hint python
    MISSING=1
fi

# ── Node.js ──
if command -v node &>/dev/null; then
    NODE_VER_RAW=$(node --version | sed 's/^v//')
    NODE_MAJOR=$(echo "$NODE_VER_RAW" | cut -d. -f1)
    if [ "$NODE_MAJOR" -ge 18 ]; then
        ok "Node.js ${W}v${NODE_VER_RAW}${NC}"
    else
        fail "Node.js ${W}18+${NC} required ${DIM}(found v${NODE_VER_RAW})${NC}"
        install_hint node
        MISSING=1
    fi
else
    fail "Node.js not found"
    install_hint node
    MISSING=1
fi

# ── npm ──
if command -v npm &>/dev/null; then
    ok "npm ${W}$(npm --version)${NC}"
else
    fail "npm not found ${DIM}(usually installed with Node.js)${NC}"
    MISSING=1
fi

# ── Git ──
if command -v git &>/dev/null; then
    ok "Git ${W}$(git --version | cut -d' ' -f3)${NC}"
else
    fail "git not found"
    install_hint git
    MISSING=1
fi

# ── PostgreSQL ──
if command -v psql &>/dev/null; then
    PG_VER=$(psql --version | grep -oE '[0-9]+\.[0-9]+' | head -1)
    PG_MAJOR=$(echo "$PG_VER" | cut -d. -f1)
    if [ "$PG_MAJOR" -ge 14 ]; then
        ok "PostgreSQL ${W}$PG_VER${NC}"
    else
        warn "PostgreSQL ${W}14+${NC} recommended ${DIM}(found $PG_VER)${NC}"
    fi
    PG_OK=1

    # Check if PostgreSQL is actually running
    if command -v pg_isready &>/dev/null; then
        if pg_isready -q 2>/dev/null; then
            ok "PostgreSQL server ${W}running${NC}"
        else
            warn "PostgreSQL installed but ${Y}not running${NC}"
            if [ "$DISTRO" = "ubuntu" ] || [ "$DISTRO" = "debian" ]; then
                dim "    Start: ${W}sudo systemctl start postgresql${NC}"
            elif [ "$DISTRO" = "macos" ]; then
                dim "    Start: ${W}brew services start postgresql@15${NC}"
            fi
        fi
    fi
elif command -v docker &>/dev/null; then
    ok "Docker ${W}$(docker --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)${NC}"
    warn "PostgreSQL not found — will use ${W}Docker${NC} automatically"
    PG_OK=2
else
    fail "PostgreSQL and Docker both not found"
    echo ""
    install_hint postgresql
    echo ""
    MISSING=1
fi

if [ "$MISSING" -eq 1 ]; then
    echo ""
    fail "${BOLD}Missing prerequisites.${NC} Install them and try again."
    if [ "$DISTRO" = "ubuntu" ] || [ "$DISTRO" = "debian" ]; then
        echo ""
        dim "  Quick install all (Ubuntu/Debian):"
        dim "    ${W}sudo apt update && sudo apt install -y python3.11 python3.11-venv python3-pip git postgresql${NC}"
        dim "    ${W}curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash - && sudo apt install -y nodejs${NC}"
        dim "    ${W}sudo systemctl start postgresql${NC}"
    elif [ "$DISTRO" = "macos" ]; then
        echo ""
        dim "  Quick install all (macOS):"
        dim "    ${W}brew install python@3.11 node@18 postgresql@15 git${NC}"
        dim "    ${W}brew services start postgresql@15${NC}"
    fi
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

info "Upgrading pip and build tools..."
pip install --upgrade pip setuptools wheel hatchling -q 2>&1 | tail -1
echo ""

# logosai framework
info "Installing logosai framework..."
pip install -e logosai-framework/ --progress-bar on 2>&1 | grep -E "Installing|Successfully|Requirement|error|ERROR" | tail -5
ok "${W}logosai${NC} framework"

# ontology
if [ -f logosai-ontology/requirements.txt ]; then
    info "Installing ontology dependencies..."
    pip install -r logosai-ontology/requirements.txt --progress-bar on 2>&1 | grep -E "Installing|Successfully|Requirement|error|ERROR" | tail -5
    ok "${W}ontology${NC} dependencies"
fi

# logos_api
info "Installing logos_api dependencies..."
dim "  (FastAPI, SQLAlchemy, asyncpg, etc. — this may take 1-2 minutes)"
pip install -e logosai-api/ --progress-bar on 2>&1 | grep -E "Installing|Successfully|Requirement|Downloading|error|ERROR" | tail -10
ok "${W}logos_api${NC} dependencies"

# Node
info "Installing logos_web dependencies..."
dim "  (Next.js, React, Tailwind — this may take 1-2 minutes)"
(cd logosai-web && npm install 2>&1 | tail -5)
ok "${W}logos_web${NC} dependencies"

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
    ok "Config ${W}logosai-api/.env${NC} ${DIM}(created from .env.example)${NC}"
else
    ok "Config ${W}logosai-api/.env${NC} exists"
fi

# Ensure DATABASE_URL is set correctly in .env
if [ "$PG_OK" -eq 2 ]; then
    if grep -q "DATABASE_URL" logosai-api/.env 2>/dev/null; then
        dim "  DATABASE_URL: postgresql+asyncpg://postgres:postgres@localhost:5432/logosai"
    fi
elif [ "$PG_OK" -eq 1 ]; then
    dim "  DATABASE_URL: check logosai-api/.env matches your PostgreSQL credentials"
fi

if [ ! -f logosai-web/.env.local ]; then
    cp logosai-web/.env.example logosai-web/.env.local
    ok "Config ${W}logosai-web/.env.local${NC} ${DIM}(created from .env.example)${NC}"
else
    ok "Config ${W}logosai-web/.env.local${NC} exists"
fi

# ── API Key Configuration ──
# Ask for API keys if not already set (reads from /dev/tty so works with curl|bash)
_needs_key_setup=false
for placeholder in "your-google-api-key" "your-openai-api-key" "your-anthropic-api-key"; do
    grep -q "$placeholder" logosai-api/.env 2>/dev/null && _needs_key_setup=true
done
# Also check if GOOGLE_API_KEY is empty or missing
if ! grep -q "^GOOGLE_API_KEY=.\+" logosai-api/.env 2>/dev/null; then
    _needs_key_setup=true
fi

# ── Configuration Setup ──
if [ -e /dev/tty ]; then
    echo ""
    info "Configuration ${DIM}(press Enter to skip / keep default)${NC}"
    echo ""

    set_env_key() {
        local key="$1" value="$2" file="$3"
        if grep -q "^${key}=" "$file" 2>/dev/null; then
            sed -i.bak "s|^${key}=.*|${key}=${value}|" "$file"
        else
            echo "${key}=${value}" >> "$file"
        fi
        rm -f "${file}.bak"
    }

    ask_config() {
        local key="$1" label="$2" file="$3" required="$4"
        local current=$(grep "^${key}=" "$file" 2>/dev/null | cut -d= -f2-)
        if [ -n "$current" ] && ! echo "$current" | grep -qE "^your-|^generate-"; then
            return
        fi
        local marker=""
        [ "$required" = "required" ] && marker="${Y}*${NC}" || marker="${DIM}optional${NC}"
        ask "  ${C}◆${NC} ${label} [${marker}]: " _INPUT
        if [ -n "$_INPUT" ]; then
            set_env_key "$key" "$_INPUT" "$file"
            ok "${label} saved"
        else
            if [ "$required" = "required" ]; then
                dim "  Skipped — set ${key} in $(basename $file) later"
            fi
        fi
    }

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Usage Mode Selection
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    dim "  ── Usage Mode ──"
    echo ""
    echo -e "    ${W}1)${NC} ${G}Personal${NC}  — Single user, no Google OAuth needed" >/dev/tty
    echo -e "    ${W}2)${NC} ${B}Team${NC}      — Multi-user with Google OAuth login" >/dev/tty
    echo "" >/dev/tty
    ask "  ${C}◆${NC} Select mode ${DIM}[1]:${NC} " USAGE_MODE
    USAGE_MODE="${USAGE_MODE:-1}"

    if [ "$USAGE_MODE" = "1" ]; then
        # ── Personal Mode ──
        ok "Personal mode selected"
        echo ""
        ask "  ${C}◆${NC} Your email ${DIM}(for login):${NC} " PERSONAL_EMAIL
        if [ -n "$PERSONAL_EMAIL" ]; then
            set_env_key "AUTH_MODE" "personal" "logosai-api/.env"
            set_env_key "PERSONAL_USER_EMAIL" "$PERSONAL_EMAIL" "logosai-api/.env"
            set_env_key "NEXT_PUBLIC_AUTH_MODE" "personal" "logosai-web/.env.local"
            set_env_key "NEXT_PUBLIC_PERSONAL_USER_EMAIL" "$PERSONAL_EMAIL" "logosai-web/.env.local"
            ok "Personal mode: ${W}${PERSONAL_EMAIL}${NC}"
        else
            warn "No email provided — you can set PERSONAL_USER_EMAIL in .env later"
            set_env_key "AUTH_MODE" "personal" "logosai-api/.env"
            set_env_key "NEXT_PUBLIC_AUTH_MODE" "personal" "logosai-web/.env.local"
        fi
    else
        # ── Team Mode ──
        ok "Team mode selected"
        set_env_key "AUTH_MODE" "team" "logosai-api/.env"
        set_env_key "NEXT_PUBLIC_AUTH_MODE" "team" "logosai-web/.env.local"

        echo ""

        # Google OAuth (required for team mode)
        dim "  ── Google OAuth (for login) ──"
        ask_config "GOOGLE_CLIENT_ID" "Google Client ID" "logosai-api/.env" "required"
        ENTERED_CLIENT_ID=$(grep "^GOOGLE_CLIENT_ID=" logosai-api/.env 2>/dev/null | cut -d= -f2-)
        if [ -n "$ENTERED_CLIENT_ID" ] && ! echo "$ENTERED_CLIENT_ID" | grep -q "^your-"; then
            set_env_key "GOOGLE_CLIENT_ID" "$ENTERED_CLIENT_ID" "logosai-web/.env.local"
        fi

        ask_config "GOOGLE_CLIENT_SECRET" "Google Client Secret" "logosai-api/.env" "required"
        ENTERED_CLIENT_SECRET=$(grep "^GOOGLE_CLIENT_SECRET=" logosai-api/.env 2>/dev/null | cut -d= -f2-)
        if [ -n "$ENTERED_CLIENT_SECRET" ] && ! echo "$ENTERED_CLIENT_SECRET" | grep -q "^your-"; then
            set_env_key "GOOGLE_CLIENT_SECRET" "$ENTERED_CLIENT_SECRET" "logosai-web/.env.local"
        fi
    fi

    echo ""

    # ── Database ──
    dim "  ── Database ──"
    ask_config "DATABASE_URL" "Database URL" "logosai-api/.env" "required"

    echo ""

    # ── LLM API Keys ──
    dim "  ── LLM API Keys ──"
    ask_config "GOOGLE_API_KEY" "Google API Key (Gemini)" "logosai-api/.env" "required"
    ask_config "OPENAI_API_KEY" "OpenAI API Key" "logosai-api/.env" "optional"
    ask_config "ANTHROPIC_API_KEY" "Anthropic API Key" "logosai-api/.env" "optional"

    echo ""

    # ── Security (auto-generated) ──
    JWT_CURRENT=$(grep "^JWT_SECRET_KEY=" logosai-api/.env 2>/dev/null | cut -d= -f2-)
    if [ -z "$JWT_CURRENT" ] || echo "$JWT_CURRENT" | grep -q "^your-"; then
        JWT_GENERATED=$(openssl rand -base64 32 2>/dev/null || python3 -c "import secrets; print(secrets.token_urlsafe(32))")
        set_env_key "JWT_SECRET_KEY" "$JWT_GENERATED" "logosai-api/.env"
        ok "JWT secret auto-generated"
    fi

    NEXTAUTH_CURRENT=$(grep "^NEXTAUTH_SECRET=" logosai-web/.env.local 2>/dev/null | cut -d= -f2-)
    if [ -z "$NEXTAUTH_CURRENT" ] || echo "$NEXTAUTH_CURRENT" | grep -q "^generate-"; then
        NEXTAUTH_GENERATED=$(openssl rand -base64 32 2>/dev/null || python3 -c "import secrets; print(secrets.token_urlsafe(32))")
        set_env_key "NEXTAUTH_SECRET" "$NEXTAUTH_GENERATED" "logosai-web/.env.local"
        ok "NextAuth secret auto-generated"
    fi

    echo ""

    # ── Server URL Detection ──
    dim "  ── Server URL ──"

    SERVER_IP=""
    if command -v hostname &>/dev/null; then
        SERVER_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
    fi
    if [ -z "$SERVER_IP" ]; then
        SERVER_IP=$(ip -4 addr show scope global 2>/dev/null | grep -oP 'inet \K[0-9.]+' | head -1)
    fi
    if [ -z "$SERVER_IP" ]; then
        SERVER_IP="localhost"
    fi

    DEFAULT_URL="http://${SERVER_IP}:8010"
    CURRENT_NEXTAUTH_URL=$(grep "^NEXTAUTH_URL=" logosai-web/.env.local 2>/dev/null | cut -d= -f2-)

    if [ "$CURRENT_NEXTAUTH_URL" = "http://localhost:8010" ] || [ -z "$CURRENT_NEXTAUTH_URL" ]; then
        dim "  Detected server IP: ${W}${SERVER_IP}${NC}"
        ask "  ${C}◆${NC} Server URL ${DIM}(default: ${DEFAULT_URL}):${NC} " INPUT_URL
        FINAL_URL="${INPUT_URL:-$DEFAULT_URL}"

        set_env_key "NEXTAUTH_URL" "$FINAL_URL" "logosai-web/.env.local"
        set_env_key "NEXT_PUBLIC_API_URL" "http://${SERVER_IP}:8090" "logosai-web/.env.local"

        CURRENT_CORS=$(grep "^CORS_ORIGINS=" logosai-api/.env 2>/dev/null | cut -d= -f2-)
        if ! echo "$CURRENT_CORS" | grep -q "$FINAL_URL"; then
            NEW_CORS="[\"http://localhost:3000\",\"http://localhost:8000\",\"http://localhost:8010\",\"${FINAL_URL}\"]"
            set_env_key "CORS_ORIGINS" "$NEW_CORS" "logosai-api/.env"
        fi

        ok "Server URL: ${W}${FINAL_URL}${NC}"
        dim "  API URL: http://${SERVER_IP}:8090"
        dim "  CORS updated"

        if [ "$USAGE_MODE" != "1" ]; then
            echo ""
            warn "Google OAuth redirect URI must include:"
            dim "  ${W}${FINAL_URL}/api/auth/callback/google${NC}"
            dim "  Add this in Google Cloud Console → Credentials → OAuth Client ID"
        fi
    fi

    echo ""
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

# Check for missing API keys before starting
_check_env_key() {
    local key="$1" label="$2" required="$3" file="$DIR/logosai-api/.env"
    local val=$(grep "^${key}=" "$file" 2>/dev/null | cut -d= -f2-)
    if [ -z "$val" ] || echo "$val" | grep -q "^your-"; then
        if [ "$required" = "required" ]; then
            echo -e "  ${Y}▲${NC} ${label} is not set" >/dev/tty
        fi
        echo -ne "  ${C}◆${NC} Enter ${label}: " >/dev/tty
        local input=""
        read -r input </dev/tty 2>/dev/null || true
        if [ -n "$input" ]; then
            if grep -q "^${key}=" "$file" 2>/dev/null; then
                sed -i.bak "s|^${key}=.*|${key}=${input}|" "$file"
            else
                echo "${key}=${input}" >> "$file"
            fi
            rm -f "${file}.bak"
            echo -e "  ${G}●${NC} ${label} saved" >/dev/tty
        fi
    fi
}

# Only check if /dev/tty is available (interactive)
if [ -e /dev/tty ]; then
    _google_key=$(grep "^GOOGLE_API_KEY=" "$DIR/logosai-api/.env" 2>/dev/null | cut -d= -f2-)
    if [ -z "$_google_key" ] || echo "$_google_key" | grep -q "^your-"; then
        echo -e "  ${DIM}──── Configuration ────${NC}" >/dev/tty
        _check_env_key "GOOGLE_API_KEY" "Google API Key (Gemini)" "required"
        echo "" >/dev/tty
    fi
fi

kill_port() {
    local port=$1
    if command -v fuser &>/dev/null; then
        fuser -k $port/tcp 2>/dev/null && sleep 1 || true
    elif command -v lsof &>/dev/null; then
        local pid=$(lsof -ti :$port 2>/dev/null || true)
        [ -n "$pid" ] && kill $pid 2>/dev/null && sleep 1 || true
    else
        # Fallback: use ss (available on all Linux)
        local pids=$(ss -tlnp 2>/dev/null | grep ":$port " | grep -oP 'pid=\K[0-9]+' | sort -u)
        for pid in $pids; do
            kill $pid 2>/dev/null || true
        done
        [ -n "$pids" ] && sleep 1 || true
    fi
}
for PORT in 8888 8090 8010; do
    kill_port $PORT
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
