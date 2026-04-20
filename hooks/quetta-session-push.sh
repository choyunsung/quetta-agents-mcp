#!/usr/bin/env bash
# Claude Code PostToolUse / Stop hook — 현재 세션의 JSONL을 Quetta 서버에 증분 push.
#
# 환경변수:
#   QUETTA_GATEWAY_URL  (필수) — 예: https://rag.quetta-soft.com
#   QUETTA_API_KEY       (필수)
#   QUETTA_MACHINE_ID    (선택) — 기본 `hostname`
#   QUETTA_SESSION_DEBOUNCE (선택, 기본 3초)
#
# 호출: Claude Code 가 PostToolUse / Stop 이벤트 시 자동 실행.
# stdin 으로 JSON 메타데이터가 들어오지만 여기선 파일 기반으로 동작 (hook spec 독립).

set -eu

# ── config ───────────────────────────────────────────────────────────────────
: "${QUETTA_GATEWAY_URL:=https://rag.quetta-soft.com}"
: "${QUETTA_API_KEY:=}"
: "${QUETTA_MACHINE_ID:=$(hostname 2>/dev/null || echo unknown)}"
: "${QUETTA_SESSION_DEBOUNCE:=3}"

[ -z "$QUETTA_API_KEY" ] && exit 0   # 키 없으면 조용히 종료

# ── lock + debounce ──────────────────────────────────────────────────────────
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/quetta-session-push"
mkdir -p "$STATE_DIR"
LOCK="$STATE_DIR/lock"
LAST="$STATE_DIR/last_push"

# 이미 3초 내 push 했으면 skip
if [ -f "$LAST" ]; then
  NOW=$(date +%s)
  PREV=$(cat "$LAST" 2>/dev/null || echo 0)
  DELTA=$((NOW - PREV))
  if [ "$DELTA" -lt "$QUETTA_SESSION_DEBOUNCE" ]; then
    exit 0
  fi
fi

# 단일 실행 보장
exec 9>"$LOCK"
command -v flock >/dev/null 2>&1 && flock -n 9 || exit 0

# ── 현재 Claude Code 세션 JSONL 찾기 ────────────────────────────────────────
# ~/.claude/projects/<cwd-hash>/<session_uuid>.jsonl — 최신 파일 1개
CLAUDE_DIR="${CLAUDE_HOME:-$HOME/.claude}"
PROJECT_DIR="$CLAUDE_DIR/projects"
[ -d "$PROJECT_DIR" ] || exit 0

# 현재 cwd 해시 디렉터리 찾기 (Claude Code 규칙: cwd → 특수문자 치환)
CWD=$(pwd)
CWD_HASH=$(echo "$CWD" | sed 's|/|-|g; s|^-||' | sed 's|:|-|g')
SESSION_FILE=""
if [ -d "$PROJECT_DIR/$CWD_HASH" ]; then
  SESSION_FILE=$(ls -t "$PROJECT_DIR/$CWD_HASH"/*.jsonl 2>/dev/null | head -1)
fi

# fallback: 전역에서 최신 JSONL 검색 (최근 5분 내 수정)
if [ -z "$SESSION_FILE" ]; then
  SESSION_FILE=$(find "$PROJECT_DIR" -name '*.jsonl' -mmin -5 2>/dev/null | head -1)
fi

[ -z "$SESSION_FILE" ] || [ ! -f "$SESSION_FILE" ] && exit 0

SESSION_ID=$(basename "$SESSION_FILE" .jsonl)

# ── git / 프로젝트 메타 ──────────────────────────────────────────────────────
PROJECT_KEY=""
GIT_REMOTE=""
GIT_HEAD=""
DIFF=""
if git -C "$CWD" rev-parse --git-dir >/dev/null 2>&1; then
  GIT_REMOTE=$(git -C "$CWD" config --get remote.origin.url 2>/dev/null || true)
  GIT_HEAD=$(git -C "$CWD" rev-parse HEAD 2>/dev/null || true)
  BRANCH=$(git -C "$CWD" symbolic-ref --short HEAD 2>/dev/null || echo "DETACHED")
  DIFF=$(git -C "$CWD" diff HEAD 2>/dev/null | head -c 30000 || true)
  if [ -n "$GIT_REMOTE" ]; then
    PROJECT_KEY="git:$(echo "$GIT_REMOTE" | sed -E 's|.*[:/]([^/]+/[^/.]+)(\.git)?$|\1|')#$BRANCH"
  fi
fi
[ -z "$PROJECT_KEY" ] && PROJECT_KEY="cwd:$(basename "$CWD")"

# ── JSONL → messages 배열 + open_files 추출 ────────────────────────────────
PAYLOAD=$(python3 - "$SESSION_FILE" <<'PYEOF'
import json, sys, pathlib
path = pathlib.Path(sys.argv[1])
messages = []
open_files = set()
for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
    if not ln.strip():
        continue
    try:
        obj = json.loads(ln)
    except Exception:
        continue
    # Claude Code JSONL schema — message/tool_use entries
    t = obj.get("type") or obj.get("role")
    if t in ("user", "assistant", "system"):
        messages.append({
            "role":    t,
            "content": obj.get("message", {}).get("content") or obj.get("content") or "",
            "ts":      obj.get("timestamp") or obj.get("ts"),
        })
    elif obj.get("toolUseResult"):
        # tool_result
        messages.append({
            "role":    "tool",
            "content": obj.get("toolUseResult"),
            "ts":      obj.get("timestamp"),
        })
    # open_files 휴리스틱
    txt = json.dumps(obj)[:5000]
    import re
    for m in re.finditer(r'"file_path":\s*"([^"]+)"', txt):
        open_files.add(m.group(1))
print(json.dumps({"messages": messages, "open_files": sorted(open_files)[:20]}))
PYEOF
)

# ── POST /v1/sessions/push ──────────────────────────────────────────────────
BODY=$(python3 - "$SESSION_ID" "$PROJECT_KEY" "$QUETTA_MACHINE_ID" "$CWD" "$GIT_REMOTE" "$GIT_HEAD" "$DIFF" "$PAYLOAD" <<'PYEOF'
import json, sys
sid, pkey, mid, cwd, gr, gh, diff, payload = sys.argv[1:9]
p = json.loads(payload)
print(json.dumps({
    "session_id":       sid,
    "project_key":      pkey,
    "machine_id":       mid,
    "cwd":              cwd,
    "messages":         p.get("messages", []),
    "open_files":       p.get("open_files", []),
    "git_remote":       gr,
    "git_head":         gh,
    "uncommitted_diff": diff,
}))
PYEOF
)

# fire-and-forget: curl 타임아웃 5초, 실패해도 exit 0
curl -fsS --max-time 5 \
  -X POST "$QUETTA_GATEWAY_URL/v1/sessions/push" \
  -H "Authorization: Bearer $QUETTA_API_KEY" \
  -H "Content-Type: application/json" \
  -d "$BODY" >/dev/null 2>&1 || true

date +%s > "$LAST"
exit 0
