#!/usr/bin/env bash
# Quetta Agents MCP — updater
# Usage: curl -fsSL https://raw.githubusercontent.com/choyunsung/quetta-agents-mcp/master/update.sh | bash

set -e

REPO_SSH="git+ssh://git@github.com/choyunsung/quetta-agents-mcp"
REPO_HTTPS="git+https://github.com/choyunsung/quetta-agents-mcp"

CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${CYAN}▶ $*${NC}"; }
success() { echo -e "${GREEN}✓ $*${NC}"; }
error()   { echo -e "${RED}✗ $*${NC}"; exit 1; }

echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}   Quetta Agents MCP Updater${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# ── Find uvx ─────────────────────────────────────────────────────────────────
UVX=""
for candidate in uvx "$HOME/.local/bin/uvx" /usr/local/bin/uvx; do
    if command -v "$candidate" &>/dev/null 2>&1; then
        UVX="$candidate"; break
    fi
done

if [ -z "$UVX" ]; then
    info "uvx not found — installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    UVX="uvx"
fi

success "uvx: $($UVX --version 2>&1 | head -1)"

# ── Reinstall ─────────────────────────────────────────────────────────────────
info "GitHub에서 최신 버전 설치 중..."

UPDATED=false
for REPO in "$REPO_SSH" "$REPO_HTTPS"; do
    if $UVX --reinstall --from "$REPO" quetta-agents-mcp --version 2>/dev/null; then
        UPDATED=true; break
    fi
done

if [ "$UPDATED" = false ]; then
    error "업데이트 실패. GitHub 접근 권한(SSH 키 또는 HTTPS 토큰)을 확인하세요."
fi

success "업데이트 완료"

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}   Update complete!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  ${YELLOW}Claude Code를 재시작해야 새 버전이 적용됩니다.${NC}"
echo ""
