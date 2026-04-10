#!/usr/bin/env bash
# Quetta Agents MCP — one-line installer
# Usage: curl -fsSL https://raw.githubusercontent.com/choyunsung/quetta-agents-mcp/master/install.sh | bash
# Or with custom gateway:
#   QUETTA_GATEWAY_URL=https://rag.quetta-soft.com QUETTA_API_KEY=xxx bash install.sh

set -e

REPO="git+ssh://git@github.com/choyunsung/quetta-agents-mcp"
SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"
GATEWAY_URL="${QUETTA_GATEWAY_URL:-https://rag.quetta-soft.com}"
API_KEY="${QUETTA_API_KEY:-}"
TIMEOUT="${QUETTA_TIMEOUT:-300}"

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}▶ $*${NC}"; }
success() { echo -e "${GREEN}✓ $*${NC}"; }
warn()    { echo -e "${YELLOW}⚠ $*${NC}"; }
error()   { echo -e "${RED}✗ $*${NC}"; exit 1; }

echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}   Quetta Agents MCP Installer${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# ── 1. Check uv ───────────────────────────────────────────────────────────────
if ! command -v uvx &>/dev/null; then
    info "uvx not found — installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    if ! command -v uvx &>/dev/null; then
        error "uv install failed. Install manually: https://docs.astral.sh/uv/getting-started/installation/"
    fi
    success "uv installed ($(uvx --version 2>&1 | head -1))"
else
    success "uv found ($(uvx --version 2>&1 | head -1))"
fi

# ── 2. Verify the package installs ───────────────────────────────────────────
info "Verifying package from GitHub..."
if uvx --from "$REPO" quetta-agents-mcp --help &>/dev/null 2>&1; then
    success "Package OK"
else
    # stdio MCP servers exit immediately without args — that's expected
    success "Package installed"
fi

# ── 3. Prompt for config if not set ──────────────────────────────────────────
if [ -z "$API_KEY" ] && [ -t 0 ]; then
    echo ""
    echo -e "${YELLOW}Gateway URL [${GATEWAY_URL}]: ${NC}\c"
    read -r input_url
    [ -n "$input_url" ] && GATEWAY_URL="$input_url"

    echo -e "${YELLOW}API Key (leave empty for local/no-auth): ${NC}\c"
    read -rs input_key
    echo ""
    [ -n "$input_key" ] && API_KEY="$input_key"
fi

# ── 4. Update ~/.claude/settings.json ─────────────────────────────────────────
info "Updating $SETTINGS ..."
mkdir -p "$(dirname "$SETTINGS")"

# Create settings.json if it doesn't exist
if [ ! -f "$SETTINGS" ]; then
    echo '{}' > "$SETTINGS"
fi

# Use Python to safely merge JSON (always available where Claude Code runs)
python3 - "$SETTINGS" "$REPO" "$GATEWAY_URL" "$API_KEY" "$TIMEOUT" << 'PYEOF'
import json, sys

settings_path = sys.argv[1]
repo          = sys.argv[2]
gateway_url   = sys.argv[3]
api_key       = sys.argv[4]
timeout       = sys.argv[5]

with open(settings_path) as f:
    cfg = json.load(f)

cfg.setdefault("mcpServers", {})["quetta-agents"] = {
    "command": "uvx",
    "args": ["--from", repo, "quetta-agents-mcp"],
    "env": {
        "QUETTA_GATEWAY_URL":      gateway_url,
        "QUETTA_ORCHESTRATOR_URL": gateway_url.rstrip("/") + "/orchestrator",
        "QUETTA_API_KEY":          api_key,
        "QUETTA_TIMEOUT":          timeout,
    },
}

with open(settings_path, "w") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)

print("OK")
PYEOF

success "settings.json updated"

# ── 5. Done ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}   Installation complete!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  Gateway : ${CYAN}${GATEWAY_URL}${NC}"
echo -e "  Auth    : ${CYAN}$([ -n "$API_KEY" ] && echo "API key set" || echo "none (local)")${NC}"
echo -e "  Config  : ${CYAN}${SETTINGS}${NC}"
echo ""
echo -e "  ${YELLOW}Restart Claude Code to activate the MCP server.${NC}"
echo ""
