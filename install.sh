#!/usr/bin/env bash
# Quetta Agents MCP — one-line installer
# Usage: curl -fsSL https://raw.githubusercontent.com/choyunsung/quetta-agents-mcp/master/install.sh | bash
# Or with custom gateway:
#   QUETTA_GATEWAY_URL=https://rag.quetta-soft.com QUETTA_API_KEY=xxx bash install.sh

set -e

REPO_HTTPS="git+https://github.com/choyunsung/quetta-agents-mcp"
REPO_SSH="git+ssh://git@github.com/choyunsung/quetta-agents-mcp"
GATEWAY_URL="${QUETTA_GATEWAY_URL:-}"
# Secret Gist ID (관리자가 공유) — gh CLI 인증 또는 GH_TOKEN 필요
GIST_ID="${QUETTA_GIST_ID:-}"
INSTALL_TOKEN="${QUETTA_INSTALL_TOKEN:-}"
# 직접 키를 알고 있으면 아래도 override 가능
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

# ── 3. Config 조회 (GitHub Gist → Gateway 토큰 → 직접 env) ────────────────────
# 우선순위:
#  1. QUETTA_API_KEY (env로 직접 제공)
#  2. QUETTA_GIST_ID  (secret Gist에서 JSON 받아오기 — 권장)
#  3. QUETTA_INSTALL_TOKEN (Gateway /install/config 조회)
#  4. 둘 다 없으면 Gist ID 입력 프롬프트
#
# 반환 JSON은 두 가지 섹션을 가질 수 있음:
#  - 최상위 키 (gateway_url, api_key, rag_url …) → Quetta MCP 자체 설정
#  - companion_mcps : {name: {command, args, env}} → 보조 MCP 일괄 등록

load_from_gist() {
    local gist_id="$1"
    local gist_json
    # 방법 1: gh CLI 인증 (우선)
    if command -v gh &>/dev/null && gh auth status &>/dev/null; then
        gist_json=$(gh api "/gists/$gist_id" --jq '.files | to_entries[0].value.content' 2>/dev/null)
    fi
    # 방법 2: GH_TOKEN 환경변수
    if [ -z "$gist_json" ] && [ -n "${GH_TOKEN:-}${GITHUB_TOKEN:-}" ]; then
        local tok="${GH_TOKEN:-$GITHUB_TOKEN}"
        gist_json=$(curl -sf "https://api.github.com/gists/$gist_id" \
            -H "Authorization: token $tok" \
            -H "Accept: application/vnd.github+json" \
            | python3 -c "import sys,json;d=json.load(sys.stdin);print(next(iter(d['files'].values()))['content'])" 2>/dev/null)
    fi
    # 방법 3: public Gist (인증 불필요)
    if [ -z "$gist_json" ]; then
        gist_json=$(curl -sf "https://api.github.com/gists/$gist_id" \
            | python3 -c "import sys,json;d=json.load(sys.stdin);print(next(iter(d['files'].values()))['content'])" 2>/dev/null)
    fi
    echo "$gist_json"
}

if [ -z "$API_KEY" ] && [ -z "$GIST_ID" ] && [ -z "$INSTALL_TOKEN" ] \
   && [ -t 0 ] && [ "${QUETTA_NONINTERACTIVE:-0}" != "1" ]; then
    echo ""
    info "관리자에게 받은 **Gist ID** 또는 **초대 토큰**을 입력하세요."
    info "(Gist ID는 URL의 마지막 해시 부분: gist.github.com/user/<THIS>)"
    printf "${YELLOW}Gist ID (비우면 skip): ${NC}"
    read -r GIST_ID
    if [ -z "$GIST_ID" ]; then
        printf "${YELLOW}초대 토큰 (QUETTA_INSTALL_TOKEN): ${NC}"
        read -r INSTALL_TOKEN
    fi
fi

# 방법 A: Gist에서 config 로드
CONFIG_JSON=""
if [ -n "$GIST_ID" ] && [ -z "$API_KEY" ]; then
    info "GitHub Gist에서 설정 불러오는 중 ($GIST_ID)..."
    CONFIG_JSON=$(load_from_gist "$GIST_ID")
    if [ -z "$CONFIG_JSON" ]; then
        error "Gist 접근 실패 — 비공개 Gist면 'gh auth login' 또는 GH_TOKEN 필요"
    fi

    eval "$(python3 - "$CONFIG_JSON" <<'PYEOF'
import json, sys
try:
    d = json.loads(sys.argv[1])
except Exception as e:
    sys.exit(f"JSON 파싱 실패: {e}")
mapping = {
    "gateway_url": "QUETTA_CFG_GATEWAY_URL",
    "api_key": "QUETTA_CFG_API_KEY",
    "rag_url": "QUETTA_CFG_RAG_URL",
    "tusd_url": "QUETTA_CFG_TUSD_URL",
    "tusd_token": "QUETTA_CFG_TUSD_TOKEN",
    "rag_key": "QUETTA_CFG_RAG_KEY",
    "orchestrator_url": "QUETTA_CFG_ORCHESTRATOR_URL",
    "timeout": "QUETTA_CFG_TIMEOUT",
}
for k, var in mapping.items():
    v = d.get(k, "")
    print(f'{var}={json.dumps(v)}')
PYEOF
)"
    [ -n "$QUETTA_CFG_GATEWAY_URL" ] && GATEWAY_URL="$QUETTA_CFG_GATEWAY_URL"
    API_KEY="$QUETTA_CFG_API_KEY"
    RAG_URL="$QUETTA_CFG_RAG_URL"
    TUSD_URL="$QUETTA_CFG_TUSD_URL"
    TUSD_TOKEN="$QUETTA_CFG_TUSD_TOKEN"
    RAG_KEY="$QUETTA_CFG_RAG_KEY"
    ORCH_URL="$QUETTA_CFG_ORCHESTRATOR_URL"
    [ -n "$QUETTA_CFG_TIMEOUT" ] && TIMEOUT="$QUETTA_CFG_TIMEOUT"
    success "Gist 설정 로드 완료"
fi

# 방법 B: Gateway 초대 토큰
if [ -n "$INSTALL_TOKEN" ] && [ -z "$API_KEY" ]; then
    info "초대 토큰 검증 중..."
    [ -z "$GATEWAY_URL" ] && GATEWAY_URL="https://rag.quetta-soft.com"
    CONFIG_JSON=$(curl -sf "$GATEWAY_URL/install/config?token=$INSTALL_TOKEN")
    if [ -z "$CONFIG_JSON" ]; then
        error "초대 토큰 유효하지 않거나 Gateway 접근 불가"
    fi
    eval "$(python3 - "$CONFIG_JSON" <<'PYEOF'
import json, sys
d = json.loads(sys.argv[1])
for k, v in d.items():
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
    success "초대 토큰 검증 완료"
fi

# 필수값 체크
[ -z "$GATEWAY_URL" ] && GATEWAY_URL="https://rag.quetta-soft.com"
if [ -z "$API_KEY" ] && [[ "$GATEWAY_URL" =~ ^https:// ]]; then
    error "설정 필요: QUETTA_GIST_ID / QUETTA_INSTALL_TOKEN / QUETTA_API_KEY 중 하나"
fi

# 빈 값 기본값
[ -z "$RAG_URL" ]  && RAG_URL="$GATEWAY_URL"
[ -z "$TUSD_URL" ] && TUSD_URL="$GATEWAY_URL"
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

# ── 4.4. Companion MCPs 자동 등록 (사용자별 키 포함) ──────────────────────────
# CONFIG_JSON에 companion_mcps 블록이 있으면 각 MCP를 claude mcp add-json으로 일괄 등록.
# 스킵: QUETTA_SKIP_COMPANION=1

if [ "${QUETTA_SKIP_COMPANION:-0}" != "1" ] && [ -n "$CONFIG_JSON" ]; then
    # companion_mcps에서 (name, JSON) 튜플을 탭 구분으로 뽑는다
    COMPANION_TSV=$(python3 - "$CONFIG_JSON" <<'PYEOF' 2>/dev/null || true
import json, sys
try:
    d = json.loads(sys.argv[1])
except Exception:
    sys.exit(0)
for name, cfg in (d.get("companion_mcps") or {}).items():
    if not isinstance(cfg, dict) or "command" not in cfg:
        continue
    # args/env 기본값 보정
    cfg.setdefault("args", [])
    cfg.setdefault("env", {})
    print(name + "\t" + json.dumps(cfg, ensure_ascii=False))
PYEOF
)

    if [ -n "$COMPANION_TSV" ]; then
        info "Companion MCP 등록 중..."
        OK=0; FAIL=0
        while IFS=$'\t' read -r NAME JSON; do
            [ -z "$NAME" ] && continue

            # 기존 등록 제거 (env 갱신 목적 · 멱등)
            if command -v claude &>/dev/null; then
                claude mcp remove "$NAME" --scope user &>/dev/null || true
                if claude mcp add-json "$NAME" "$JSON" --scope user &>/dev/null; then
                    success "  $NAME 등록됨"
                    OK=$((OK+1))
                    continue
                fi
            fi

            # Fallback: settings.json 직접 편집
            python3 - "$SETTINGS" "$NAME" "$JSON" <<'PYEOF' && { success "  $NAME 등록됨 (settings.json)"; OK=$((OK+1)); } || { warn "  $NAME 등록 실패"; FAIL=$((FAIL+1)); }
import json, sys
path, name, cfg_json = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path) as f:
    cfg = json.load(f)
cfg.setdefault("mcpServers", {})[name] = json.loads(cfg_json)
with open(path, "w") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
PYEOF
        done <<< "$COMPANION_TSV"

        success "Companion MCP: $OK 등록, $FAIL 실패"
    fi
else
    [ "${QUETTA_SKIP_COMPANION:-0}" = "1" ] && info "Companion MCP 설치 스킵 (QUETTA_SKIP_COMPANION=1)"
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
## Quetta Agents MCP — 사용 규칙

### 역할 분리 (최우선 원칙)
**Claude Code 네이티브 기능은 항상 그대로 유지하고 우선 사용한다**:
- Agent / Task / Plan / Subagent 호출 (Explore, feature-dev, general-purpose 등)
- Read / Write / Edit / Grep / Glob / Bash
- 내장 skills: `/codex`, `/plan-ceo-review`, `/plan-eng-review`, `/autoplan`, `/review`, `/qa`, `/ship`, `/investigate` 등 — 코딩·설계·리뷰 어드바이저는 전부 Claude Code native 를 사용

**Quetta MCP는 "로컬에서 불가능한 외부 리소스"가 필요할 때만 호출**한다:
- 원격 Windows/맥 GPU 에이전트 실행
- 공유 RAG 메모리 · 세션간 기억
- 학술 DB 통합 검색 (PubMed/arXiv/Semantic Scholar)
- Nougat + Gemini 기반 PDF 수식 OCR/분석
- 다른 LLM 라우팅 (Gemma4 로컬, DeepSeek-R1 의료, Claude Opus 영상)

일반 코딩·파일 편집·리팩토링·로컬 탐색은 Claude Code 네이티브가 처리한다. Quetta에 위임하지 않는다.

### 진입점 선택
| 상황 | 사용할 도구 |
|------|-----------|
| 파일 편집, 코드 리뷰, 로컬 Grep/Read, 디버깅 | **Claude Code native** (Agent, Edit, Bash, …) |
| 아키텍처/계획 리뷰 | `/plan-ceo-review`, `/plan-eng-review`, `/autoplan` |
| 독립 제2의견 | `/codex` |
| "논문 검색해줘" (파일 없음) | `quetta_paper_search` |
| PDF/file_id 첨부 후 분석 | `quetta_analyze_paper` (파일 제공 시 자동) |
| 원격 GPU 필요 (CUDA/torch/학습) | `quetta_gpu_exec` |
| 원격 PC 스크린샷/셸 | `quetta_remote_screenshot` / `quetta_remote_shell` |
| 의료 임상/진단 질의 | `quetta_medical` (DeepSeek-R1) |
| 공유 메모리 저장/회상 | `quetta_memory_save` / `quetta_memory_recall` |
| 기타 외부 LLM 자유 질의 | `quetta_ask` |

`quetta_auto` 는 위 Quetta 범위 안에서 의도가 애매할 때만 사용 — Claude Code 네이티브로 처리 가능하면 그쪽 먼저 시도.

### 세션 시작
새 세션 첫 응답 전 **두 가지를 순서대로** 호출:
1. `quetta_session_init()` — 사용자 프로필·최근 맥락
2. `quetta_session_list(project_key="<git:orgrepo#branch>", within_hours=48)` — 최근 48시간 내 같은 프로젝트의 다른 기기 세션이 있으면 사용자에게 "어제 OOO PC 에서 하던 작업을 이어받을까요?" 확인 후 `quetta_session_resume(session_id=...)` 호출. 반환 요약 + 원본 + diff 를 배경 지식으로 반영.

### 멀티 세션 이어받기 / 요약 검증
- 실시간 **PostToolUse hook** 이 자동으로 `/v1/sessions/push` 호출 → MongoDB 저장 (설치 시 자동 등록됨, debounce 3s, TTL 30일)
- 세션 종료 전 중요한 맥락은 `quetta_session_summarize(session_id=..., summary_md="...")` 로 요약 업로드 — **서버가 원본 대비 핵심 항목 커버리지를 점수화** 하고, 누락 항목이 많으면 경고. 요약이 부실해도 원본은 그대로 보존되어 **유실 방지**.
- 영구 보존 필요 세션은 `quetta_session_pin(session_id=..., pinned=True)`.

### Apple Silicon 분산 추론 (Exo / MLX Distributed)
- 초대형 모델 (Llama 3.1 **405B**, DeepSeek-R1 **671B**) 요청 시 자동으로 **Exo 분산 클러스터**로 라우팅 (EXO_ENABLED=true + EXO_BASE_URL 설정 서버에서)
- Mac Remote Agent 설치 시 Exo + MLX Distributed 가 자동으로 함께 설치됨 (QUETTA_SKIP_MAC_EXTRA=1 로 비활성화 가능)
- `quetta_exo_status` — 클러스터 노드·모델 목록 조회
- `quetta_mlx_distribute(prompt, model, n_hosts)` — 연결된 맥 노드들을 `mpirun` 로 엮어 MLX 분산 추론 직접 실행
- 라우팅 트리거 키워드: `405b`, `671b`, `exo`, `mac cluster`, `분산 추론`, `mlx`, `metal`

### 하네스 동작 범위 (참고)
- `quetta_ask/code/medical/auto` 호출 시 Gateway가 **원격 LLM 프롬프트**에만 공유 메모리를 자동 주입
- Claude Code 자체의 추론·도구 호출·Agent/Task 흐름엔 영향 없음
- 별도 설정 불필요

### 어드바이저 구분
- **Claude Code native advisors** (`/codex`, `/plan-ceo-review`, `/review` 등) — 계획·리뷰·2차 의견은 모두 이쪽
- **`quetta_code`** — 외부 LLM(Gemma4/Claude)에 코딩 작업을 맡길 때만 사용하며 agent-skills 5종 자동 주입. 일반 Claude Code 코딩 흐름엔 사용하지 않음.

### 파일 유무 분기
- 파일 없이 "논문 검색" → `quetta_paper_search` (PubMed+arXiv+Semantic Scholar)
- `file_path`/`file_id` 제공 → `quetta_analyze_paper` 로 서버가 자동 override (Nougat+Gemini+Claude)

### 메모리 저장 기준
사용자 선호·프로젝트 결정·반복 참조될 사실만 `quetta_memory_save(text=..., tags=[...])`. 진행 중 대화 상태는 저장하지 않는다.

### dry_run
Quetta 라우팅 결과만 미리 보려면 `quetta_auto(..., dry_run=True)`.
<!-- quetta-agents-mcp:auto-init END -->
QUETTA_MD

success "CLAUDE.md 자동 초기화 지시 추가 ($CLAUDE_MD)"

# ── 4.6. PostToolUse hook 자동 등록 (멀티 세션 실시간 push) ─────────────────────
HOOK_DIR="$HOME/.claude/hooks"
HOOK_SH="$HOOK_DIR/quetta-session-push.sh"
mkdir -p "$HOOK_DIR"

# GitHub 에서 최신 훅 스크립트 다운로드 (repo raw URL)
info "PostToolUse hook 배포 중..."
HOOK_RAW="https://raw.githubusercontent.com/choyunsung/quetta-agents-mcp/master/hooks/quetta-session-push.sh"
if curl -fsSL "$HOOK_RAW" -o "$HOOK_SH" 2>/dev/null; then
    chmod +x "$HOOK_SH"
    success "hook 스크립트: $HOOK_SH"
else
    warn "hook 스크립트 다운로드 실패 — 네트워크 확인 후 수동 복사 필요"
fi

# settings.json 에 hook 항목 등록 (PostToolUse + Stop)
CLAUDE_SETTINGS="$HOME/.claude/settings.json"
if [ -f "$HOOK_SH" ]; then
    python3 - "$CLAUDE_SETTINGS" "$HOOK_SH" "$GATEWAY_URL" "$API_KEY" <<'PYEOF'
import json, os, sys, pathlib
settings_path, hook_sh, gw, key = sys.argv[1:5]
p = pathlib.Path(settings_path)
if p.exists():
    try:
        cfg = json.loads(p.read_text() or "{}")
    except Exception:
        cfg = {}
else:
    cfg = {}

hooks_cfg = cfg.setdefault("hooks", {})

# PostToolUse 와 Stop 두 이벤트 모두 등록 (중복 방지)
for event in ("PostToolUse", "Stop"):
    existing = hooks_cfg.get(event, []) or []
    # 이미 동일 경로 등록돼 있으면 스킵
    already = any(
        any(h.get("command") == hook_sh for h in (entry.get("hooks") or []))
        for entry in existing if isinstance(entry, dict)
    )
    if already:
        continue
    existing.append({
        "hooks": [{
            "type": "command",
            "command": hook_sh,
            "env": {
                "QUETTA_GATEWAY_URL": gw,
                "QUETTA_API_KEY":     key,
            },
        }]
    })
    hooks_cfg[event] = existing

p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
print("hooks registered")
PYEOF
    success "settings.json 에 PostToolUse/Stop hook 등록 완료"
fi

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
