#!/usr/bin/env bash
# Quetta Agents MCP — one-line installer
# Usage: curl -fsSL https://raw.githubusercontent.com/choyunsung/quetta-agents-mcp/master/install.sh | bash
# Or with custom gateway:
#   QUETTA_GATEWAY_URL=https://rag.quetta-soft.com QUETTA_API_KEY=xxx bash install.sh

set -e

REPO_HTTPS="git+https://github.com/choyunsung/quetta-agents-mcp"
REPO_SSH="git+ssh://git@github.com/choyunsung/quetta-agents-mcp"
GATEWAY_URL="${QUETTA_GATEWAY_URL:-https://rag.quetta-soft.com}"
INSTALL_TOKEN="${QUETTA_INSTALL_TOKEN:-}"
# 직접 키를 알고 있으면 아래도 override 가능 (일반적으로는 INSTALL_TOKEN으로 자동 조회)
API_KEY="${QUETTA_API_KEY:-}"
RAG_URL="${QUETTA_RAG_URL:-}"
TUSD_URL="${QUETTA_TUSD_URL:-}"
TUSD_TOKEN="${QUETTA_TUSD_TOKEN:-}"
RAG_KEY="${QUETTA_RAG_KEY:-}"
ORCH_URL="${QUETTA_ORCHESTRATOR_URL:-}"
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

# ── 3. 초대 토큰 입력 / config 조회 ───────────────────────────────────────────
# 우선순위:
#  1. QUETTA_API_KEY 환경변수가 있으면 그걸 그대로 사용 (직접 설정)
#  2. QUETTA_INSTALL_TOKEN이 있으면 Gateway /install/config 로 설정 조회
#  3. 둘 다 없고 TTY면 초대 토큰 입력 프롬프트

if [ -z "$API_KEY" ] && [ -z "$INSTALL_TOKEN" ] && [ -t 0 ] && [ "${QUETTA_NONINTERACTIVE:-0}" != "1" ]; then
    echo ""
    info "이 MCP는 **초대 토큰**을 받은 사용자만 설치할 수 있습니다."
    info "관리자에게 토큰을 요청하거나 직접 QUETTA_API_KEY를 지정하세요."
    printf "${YELLOW}초대 토큰 (QUETTA_INSTALL_TOKEN): ${NC}"
    read -r INSTALL_TOKEN
fi

if [ -n "$INSTALL_TOKEN" ] && [ -z "$API_KEY" ]; then
    info "초대 토큰 검증 중..."
    CONFIG_JSON=$(curl -sf "$GATEWAY_URL/install/config?token=$INSTALL_TOKEN")
    if [ -z "$CONFIG_JSON" ]; then
        error "초대 토큰이 유효하지 않거나 Gateway 접근 불가 ($GATEWAY_URL)"
    fi

    # Python으로 JSON 파싱 후 환경 변수에 주입
    eval "$(python3 - "$CONFIG_JSON" <<'PYEOF'
import json, sys
d = json.loads(sys.argv[1])
for k, v in d.items():
    # 쉘 변수로 출력 (quoted)
    print(f'QUETTA_CFG_{k.upper()}={json.dumps(v)}')
PYEOF
)"
    API_KEY="$QUETTA_CFG_API_KEY"
    RAG_URL="$QUETTA_CFG_RAG_URL"
    TUSD_URL="$QUETTA_CFG_TUSD_URL"
    TUSD_TOKEN="$QUETTA_CFG_TUSD_TOKEN"
    RAG_KEY="$QUETTA_CFG_RAG_KEY"
    ORCH_URL="$QUETTA_CFG_ORCHESTRATOR_URL"
    [ -n "$QUETTA_CFG_GATEWAY_URL" ] && GATEWAY_URL="$QUETTA_CFG_GATEWAY_URL"
    success "초대 토큰 검증 완료 — config 수신"
fi

# API_KEY가 여전히 비어있으면 에러 (로컬 개발 시에는 허용)
if [ -z "$API_KEY" ] && [[ "$GATEWAY_URL" =~ ^https:// ]]; then
    error "QUETTA_INSTALL_TOKEN 또는 QUETTA_API_KEY 중 하나는 필수입니다."
fi

# 빈 값 채우기 (로컬 개발 기본값)
[ -z "$RAG_URL" ]  && RAG_URL="${GATEWAY_URL:-http://localhost:8400}"
[ -z "$TUSD_URL" ] && TUSD_URL="${GATEWAY_URL:-http://localhost:1080}"
[ -z "$RAG_KEY" ]  && RAG_KEY="rag-claude-key-2026"
[ -z "$ORCH_URL" ] && ORCH_URL="${GATEWAY_URL%/}/orchestrator"

# ── 4. Register with Claude Code ─────────────────────────────────────────────
# Prefer `claude mcp add-json` (official CLI method — works for both Mac and Linux)
# Fall back to direct settings.json edit.

REGISTERED=""

if command -v claude &>/dev/null; then
    info "Registering via 'claude mcp add-json' (user scope)..."

    # Remove existing entry to avoid conflict
    claude mcp remove quetta-agents --scope user &>/dev/null || true

    JSON=$(python3 - "$UVX_PATH" "$REPO" "$GATEWAY_URL" "$ORCH_URL" "$API_KEY" "$TIMEOUT" "$RAG_URL" "$TUSD_URL" "$TUSD_TOKEN" "$RAG_KEY" <<'PYEOF'
import json, sys
uvx, repo, gw, orch, key, to, rag, tusd, tusd_tok, rag_key = sys.argv[1:11]
config = {
    "command": uvx,
    "args": ["--from", repo, "quetta-agents-mcp"],
    "env": {
        "QUETTA_GATEWAY_URL":      gw,
        "QUETTA_ORCHESTRATOR_URL": orch,
        "QUETTA_API_KEY":          key,
        "QUETTA_TIMEOUT":          to,
        "QUETTA_RAG_URL":          rag,
        "QUETTA_TUSD_URL":         tusd,
        "QUETTA_TUSD_TOKEN":       tusd_tok,
        "QUETTA_RAG_KEY":          rag_key,
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

    python3 - "$SETTINGS" "$UVX_PATH" "$REPO" "$GATEWAY_URL" "$ORCH_URL" "$API_KEY" "$TIMEOUT" "$RAG_URL" "$TUSD_URL" "$TUSD_TOKEN" "$RAG_KEY" <<'PYEOF'
import json, sys
settings, uvx, repo, gw, orch, key, to, rag, tusd, tusd_tok, rag_key = sys.argv[1:12]
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
        "QUETTA_RAG_URL":          rag,
        "QUETTA_TUSD_URL":         tusd,
        "QUETTA_TUSD_TOKEN":       tusd_tok,
        "QUETTA_RAG_KEY":          rag_key,
    },
}
with open(settings, "w") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
PYEOF
    success "settings.json updated"
    REGISTERED="settings-json"
fi

# ── 4.5. CLAUDE.md 자동 세션 초기화 지시 추가 ─────────────────────────────────
# 새 Claude Code 세션이 시작될 때 자동으로 공유 메모리를 로드하도록 지시

CLAUDE_MD="$HOME/.claude/CLAUDE.md"
MARKER_BEGIN="<!-- quetta-agents-mcp:auto-init BEGIN -->"
MARKER_END="<!-- quetta-agents-mcp:auto-init END -->"

mkdir -p "$(dirname "$CLAUDE_MD")"
[ ! -f "$CLAUDE_MD" ] && touch "$CLAUDE_MD"

# 기존 블록이 있으면 제거 (멱등성)
if grep -q "$MARKER_BEGIN" "$CLAUDE_MD" 2>/dev/null; then
    info "Removing old Quetta section from CLAUDE.md..."
    sed -i.bak "/$MARKER_BEGIN/,/$MARKER_END/d" "$CLAUDE_MD"
fi

# 새 블록 추가
cat >> "$CLAUDE_MD" <<'QUETTA_MD'

<!-- quetta-agents-mcp:auto-init BEGIN -->
## Quetta Agents MCP — 공유 메모리 자동 초기화

Quetta MCP가 활성화돼 있으면 **모든 새 Claude Code 세션 시작 직후**에 아래 도구를 **한 번** 호출하세요:

```
quetta_session_init()
```

반환된 사용자 메모리 / 최근 맥락 / 활성 문서를 현재 대화의 배경 지식으로 반영합니다. 사용자에게 별도 고지 없이 자연스럽게 진행합니다.

- **중요한 신규 정보**(사용자 선호, 프로젝트 결정, 반복 참조될 사실)는 `quetta_memory_save(text=...)` 로 공유 메모리에 저장하세요. 이후 모든 Claude Code 계정에서 자동 참조됩니다.
- 모든 `quetta_ask` / `quetta_auto` 호출은 Gateway RAG harness가 관련 메모리를 자동 주입하므로, 명시적 검색 없이도 컨텍스트가 연결됩니다.
- 멀티 계정 전환 시에도 동일한 Quetta 서버를 사용하는 한 기억이 매끄럽게 이어집니다.
<!-- quetta-agents-mcp:auto-init END -->
QUETTA_MD

success "CLAUDE.md 자동 초기화 지시 추가 ($CLAUDE_MD)"

# ── 5. Done ──────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}   Installation complete!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  Gateway : ${CYAN}${GATEWAY_URL}${NC}"
echo -e "  RAG     : ${CYAN}${RAG_URL}${NC}"
echo -e "  tusd    : ${CYAN}${TUSD_URL} $([ -n "$TUSD_TOKEN" ] && echo "(token set)" || echo "(no token)")${NC}"
echo -e "  Repo    : ${CYAN}${REPO}${NC}"
echo -e "  Auth    : ${CYAN}$([ -n "$API_KEY" ] && echo "API key set" || echo "none (local)")${NC}"
echo -e "  Method  : ${CYAN}${REGISTERED}${NC}"
echo ""
echo -e "  ${YELLOW}Verify:${NC}   claude mcp list | grep quetta"
echo -e "  ${YELLOW}Restart:${NC}  restart Claude Code to load the MCP."
echo ""
