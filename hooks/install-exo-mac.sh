#!/usr/bin/env bash
# Exo distributed inference — macOS 설치 도우미
# Quetta 가 호출하거나 사용자가 직접 실행.
# Usage:
#   bash install-exo-mac.sh [--no-launchd]
#
# 여러 맥에 각각 실행하면 mDNS 로 자동 클러스터 구성.
# Thunderbolt 브리지로 묶을 경우 --discovery-method thunderbolt.

set -e
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info(){ echo -e "${CYAN}▶ $*${NC}"; }
ok()  { echo -e "${GREEN}✓ $*${NC}"; }
warn(){ echo -e "${YELLOW}⚠ $*${NC}"; }
die() { echo -e "${RED}✗ $*${NC}"; exit 1; }

[ "$(uname)" = "Darwin" ] || die "macOS 전용 스크립트입니다."
[ "$(uname -m)" = "arm64" ] || warn "Apple Silicon (arm64) 이 아닙니다 — 성능 제한될 수 있음."

NO_LAUNCHD=0
for arg in "$@"; do
  case "$arg" in
    --no-launchd) NO_LAUNCHD=1 ;;
  esac
done

# ── 1. Python 3.10+ 확인 ────────────────────────────────────────────────────
info "Python 3.10+ 확인..."
if ! command -v python3 >/dev/null 2>&1; then
  die "python3 가 없습니다. Homebrew: brew install python@3.12"
fi
PYVER=$(python3 -c 'import sys;print(".".join(map(str,sys.version_info[:2])))')
ok "python3 $PYVER"

# ── 2. Exo 설치 — exo-explore/exo (분산 LLM 추론). PyPI 의 동명 패키지와 구분 ──
# 기존에 PyPI `exo` (JSON 도구, by Prashant Kumar Kuntala) 가 잘못 깔린 경우 식별 후 제거.
EXO_REPO="git+https://github.com/exo-explore/exo.git"
EXO_GOOD=0
if command -v exo >/dev/null 2>&1; then
  # exo-explore 는 --help 출력에 "exo" 또는 "run a cluster" 문구 포함.
  # 잘못된 PyPI exo 는 banner + "Version: 0.1.x" 만 나옴.
  if exo --help 2>&1 | grep -qE "cluster|distributed|inference|partition"; then
    EXO_GOOD=1
    ok "Exo (exo-explore) 이미 설치됨: $(which exo)"
  else
    warn "exo 바이너리 존재하나 exo-explore/exo 가 아닙니다 — 제거 후 재설치"
    python3 -m pip uninstall -y exo 2>&1 | tail -2 || true
    command -v pipx >/dev/null 2>&1 && pipx uninstall exo 2>/dev/null || true
  fi
fi

if [ "$EXO_GOOD" = 0 ]; then
  info "exo-explore/exo 설치 중 (PyTorch 등 포함, 수분 소요 가능)..."
  if command -v pipx >/dev/null 2>&1; then
    pipx install "$EXO_REPO"
  else
    info "pipx 미설치 — python3 -m pip install --user 사용"
    python3 -m pip install --user --upgrade "$EXO_REPO"
    export PATH="$HOME/.local/bin:$HOME/Library/Python/$PYVER/bin:$PATH"
  fi
  command -v exo >/dev/null 2>&1 || die "Exo 설치 실패. https://github.com/exo-explore/exo 수동 설치 참고."
  ok "Exo (exo-explore) 설치 완료: $(which exo)"
fi

# ── 3. LaunchAgent 등록 (부팅 시 자동 실행) ─────────────────────────────────
if [ "$NO_LAUNCHD" = "1" ]; then
  warn "--no-launchd — 부팅 자동시작 건너뜀. 수동 실행: exo"
else
  AGENT_DIR="$HOME/Library/LaunchAgents"
  mkdir -p "$AGENT_DIR"
  PLIST="$AGENT_DIR/com.quetta.exo.plist"
  EXO_PATH=$(command -v exo)
  LOG_DIR="$HOME/Library/Logs/quetta-exo"
  mkdir -p "$LOG_DIR"

  cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.quetta.exo</string>
  <key>ProgramArguments</key>
  <array>
    <string>$EXO_PATH</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOG_DIR/out.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
</dict>
</plist>
PLIST

  launchctl unload "$PLIST" 2>/dev/null || true
  launchctl load "$PLIST"
  ok "LaunchAgent 등록 → 부팅 시 자동 실행 ($LOG_DIR)"
fi

# ── 4. 완료 안내 ────────────────────────────────────────────────────────────
echo ""
ok "Exo 설치 완료!"
echo ""
echo "  ▸ 수동 실행:   exo"
echo "  ▸ 상태 확인:   curl http://localhost:52415/v1/models"
echo "  ▸ 로그:       tail -f $HOME/Library/Logs/quetta-exo/*.log"
echo ""
echo "  여러 대를 클러스터로 묶으려면 각 맥에 동일 스크립트 실행."
echo "  mDNS 로 자동 발견되며, Thunderbolt bridge 권장:"
echo "    exo --discovery-method thunderbolt"
echo ""
echo "  Quetta Gateway 에 연결:"
echo "    .env 에 EXO_ENABLED=true / EXO_BASE_URL=http://<master-mac>.local:52415"
echo "    gateway 재시작 → quetta_auto 에서 '405B 로 ...' 같이 큰모델 요청 시 자동 라우팅"
