#!/usr/bin/env bash
# Quetta Agents MCP — one-line installer
# Usage: curl -fsSL https://raw.githubusercontent.com/choyunsung/quetta-agents-mcp/master/install.sh | bash
# Or with custom gateway:
#   QUETTA_GATEWAY_URL=https://rag.quetta-soft.com QUETTA_API_KEY=xxx bash install.sh

set -e

REPO_HTTPS="git+https://github.com/choyunsung/quetta-agents-mcp"
REPO_SSH="git+ssh://git@github.com/choyunsung/quetta-agents-mcp"
GATEWAY_URL="${QUETTA_GATEWAY_URL:-https://rag.quetta-soft.com}"
API_KEY="${QUETTA_API_KEY:-}"
TIMEOUT="${QUETTA_TIMEOUT:-300}"
SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"

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
    # Mac Homebrew path
    [ -x "/opt/homebrew/bin/uvx" ] && export PATH="/opt/homebrew/bin:$PATH"
    if ! command -v uvx &>/dev/null; then
        error "uv install failed. Install manually: https://docs.astral.sh/uv/getting-started/installation/"
    fi
    success "uv installed ($(uvx --version 2>&1 | head -1))"
else
    success "uv found ($(uvx --version 2>&1 | head -1))"
fi

UVX_PATH=$(command -v uvx)

# ── 2. Pick working repo URL (HTTPS first for Mac/public access) ─────────────
info "Verifying package install..."
REPO=""
if $UVX_PATH --from "$REPO_HTTPS" quetta-agents-mcp --version &>/dev/null; then
    REPO="$REPO_HTTPS"
    success "HTTPS repo accessible"
elif $UVX_PATH --from "$REPO_SSH" quetta-agents-mcp --version &>/dev/null; then
    REPO="$REPO_SSH"
    success "SSH repo accessible"
else
    error "Cannot install from GitHub. Check network or GitHub access."
fi

# ── 3. Prompt for config if not set and stdin is a TTY ────────────────────────
if [ -z "$API_KEY" ] && [ -t 0 ]; then
    echo ""
    printf "${YELLOW}Gateway URL [${GATEWAY_URL}]: ${NC}"
    read -r input_url
    [ -n "$input_url" ] && GATEWAY_URL="$input_url"

    printf "${YELLOW}API Key (empty for local/no-auth): ${NC}"
    read -rs input_key
    echo ""
    [ -n "$input_key" ] && API_KEY="$input_key"
fi

ORCH_URL="${GATEWAY_URL%/}/orchestrator"

# ── 4. Register with Claude Code ─────────────────────────────────────────────
# Prefer `claude mcp add-json` (official CLI method — works for both Mac and Linux)
# Fall back to direct settings.json edit.

REGISTERED=""

if command -v claude &>/dev/null; then
    info "Registering via 'claude mcp add-json' (user scope)..."

    # Remove existing entry to avoid conflict
    claude mcp remove quetta-agents --scope user &>/dev/null || true

    JSON=$(python3 - "$UVX_PATH" "$REPO" "$GATEWAY_URL" "$ORCH_URL" "$API_KEY" "$TIMEOUT" <<'PYEOF'
import json, sys
uvx, repo, gw, orch, key, to = sys.argv[1:7]
config = {
    "command": uvx,
    "args": ["--from", repo, "quetta-agents-mcp"],
    "env": {
        "QUETTA_GATEWAY_URL":      gw,
        "QUETTA_ORCHESTRATOR_URL": orch,
        "QUETTA_API_KEY":          key,
        "QUETTA_TIMEOUT":          to,
    },
}
print(json.dumps(config))
PYEOF
)

    if claude mcp add-json quetta-agents "$JSON" --scope user &>/dev/null; then
        success "Registered via claude CLI (scope: user)"
        REGISTERED="claude-cli"
    else
        warn "claude mcp add-json failed — falling back to settings.json edit"
    fi
fi

if [ -z "$REGISTERED" ]; then
    info "Updating $SETTINGS ..."
    mkdir -p "$(dirname "$SETTINGS")"
    [ ! -f "$SETTINGS" ] && echo '{}' > "$SETTINGS"

    python3 - "$SETTINGS" "$UVX_PATH" "$REPO" "$GATEWAY_URL" "$ORCH_URL" "$API_KEY" "$TIMEOUT" <<'PYEOF'
import json, sys
settings, uvx, repo, gw, orch, key, to = sys.argv[1:8]
with open(settings) as f:
    cfg = json.load(f)
cfg.setdefault("mcpServers", {})["quetta-agents"] = {
    "command": uvx,
    "args": ["--from", repo, "quetta-agents-mcp"],
    "env": {
        "QUETTA_GATEWAY_URL":      gw,
        "QUETTA_ORCHESTRATOR_URL": orch,
        "QUETTA_API_KEY":          key,
        "QUETTA_TIMEOUT":          to,
    },
}
with open(settings, "w") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
PYEOF
    success "settings.json updated"
    REGISTERED="settings-json"
fi

# ── 5. Done ──────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}   Installation complete!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  Gateway : ${CYAN}${GATEWAY_URL}${NC}"
echo -e "  Repo    : ${CYAN}${REPO}${NC}"
echo -e "  Auth    : ${CYAN}$([ -n "$API_KEY" ] && echo "API key set" || echo "none (local)")${NC}"
echo -e "  Method  : ${CYAN}${REGISTERED}${NC}"
echo ""
echo -e "  ${YELLOW}Verify:${NC}   claude mcp list | grep quetta"
echo -e "  ${YELLOW}Restart:${NC}  restart Claude Code to load the MCP."
echo ""
