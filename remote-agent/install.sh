#!/usr/bin/env bash
# Quetta Remote Agent 설치 스크립트
# 사용: curl -fsSL https://raw.githubusercontent.com/choyunsung/quetta-agents-mcp/master/remote-agent/install.sh | bash
set -e

AGENT_URL="https://raw.githubusercontent.com/choyunsung/quetta-agents-mcp/master/remote-agent/agent.py"
INSTALL_DIR="$HOME/.quetta-remote-agent"
PORT="${QUETTA_AGENT_PORT:-7701}"
TOKEN="${QUETTA_AGENT_TOKEN:-}"

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║     Quetta Remote Agent 설치 시작            ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ── Python 확인 ──────────────────────────────────────────────────
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        VER=$("$cmd" -c "import sys; print(sys.version_info >= (3,9))" 2>/dev/null)
        if [ "$VER" = "True" ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "❌ Python 3.9+ 가 필요합니다."
    echo "   설치: https://www.python.org/downloads/"
    exit 1
fi
echo "✅ Python: $($PYTHON --version)"

# ── 설치 디렉토리 ─────────────────────────────────────────────────
mkdir -p "$INSTALL_DIR"

# ── agent.py 다운로드 ─────────────────────────────────────────────
echo "⬇  agent.py 다운로드..."
if command -v curl &>/dev/null; then
    curl -fsSL "$AGENT_URL" -o "$INSTALL_DIR/agent.py"
else
    $PYTHON -c "
import urllib.request
urllib.request.urlretrieve('$AGENT_URL', '$INSTALL_DIR/agent.py')
"
fi
echo "✅ $INSTALL_DIR/agent.py"

# ── 의존성 설치 ──────────────────────────────────────────────────
echo "📦 의존성 설치 중..."
$PYTHON -m pip install --quiet --upgrade \
    fastapi "uvicorn[standard]" pillow pyautogui mss 2>/dev/null || \
$PYTHON -m pip install --quiet --user --upgrade \
    fastapi "uvicorn[standard]" pillow pyautogui mss

# Linux headless 환경에서 pyautogui 지원
if [ "$(uname)" = "Linux" ]; then
    if ! python3 -c "import Xlib" 2>/dev/null; then
        echo "   (선택) Linux GUI: sudo apt install python3-tk scrot xdotool"
    fi
fi

echo "✅ 의존성 설치 완료"

# ── 토큰 생성 ────────────────────────────────────────────────────
if [ -z "$TOKEN" ]; then
    TOKEN=$($PYTHON -c "import secrets; print(secrets.token_hex(20))")
fi

# ── 설정 파일 저장 ────────────────────────────────────────────────
cat > "$INSTALL_DIR/.env" << EOF
QUETTA_AGENT_TOKEN=$TOKEN
QUETTA_AGENT_PORT=$PORT
EOF

# ── 실행 스크립트 ─────────────────────────────────────────────────
cat > "$INSTALL_DIR/start.sh" << 'STARTSCRIPT'
#!/usr/bin/env bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/.env" 2>/dev/null || true
exec python3 "$DIR/agent.py" "$@"
STARTSCRIPT
chmod +x "$INSTALL_DIR/start.sh"

# ── 로컬 IP 확인 ─────────────────────────────────────────────────
LOCAL_IP=$($PYTHON -c "
import socket
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(('8.8.8.8', 80))
    print(s.getsockname()[0])
except:
    print('127.0.0.1')
")

# ── 결과 출력 ────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║          ✅ 설치 완료!                               ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  실행 명령어:                                         ║"
echo "║    $INSTALL_DIR/start.sh"
echo "║"
echo "║  Claude Code settings.json 에 추가할 환경변수:        ║"
echo "║"
echo "║  QUETTA_REMOTE_AGENT_URL=http://$LOCAL_IP:$PORT"
echo "║  QUETTA_REMOTE_AGENT_TOKEN=$TOKEN"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "  → 위 값을 복사해서 Claude Code 서버의 settings.json에 추가하세요."
echo ""

# ── 즉시 실행 여부 ───────────────────────────────────────────────
if [ "${QUETTA_AGENT_START:-0}" = "1" ]; then
    echo "▶ 에이전트 시작..."
    exec "$INSTALL_DIR/start.sh"
fi

echo "  에이전트를 지금 시작하려면:"
echo "    $INSTALL_DIR/start.sh"
echo ""
echo "  백그라운드 실행:"
echo "    nohup $INSTALL_DIR/start.sh > $INSTALL_DIR/agent.log 2>&1 &"
echo ""
