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

# ── 1. Python 3.13+ 필수 (exo-explore 요구사항) ─────────────────────────────
# 설치된 Python 들 중 3.13 이상 찾고, 없으면 brew 로 python@3.13 설치.
PY=""
for c in python3.13 python3.14 python3; do
  if command -v "$c" >/dev/null 2>&1; then
    v=$("$c" -c 'import sys;print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
    if [ "$(printf '%s\n3.13' "$v" | sort -V | head -1)" = "3.13" ]; then
      PY="$(command -v "$c")"
      break
    fi
  fi
done

if [ -z "$PY" ]; then
  info "Python 3.13+ 미설치 — Homebrew 로 자동 설치"
  if ! command -v brew >/dev/null 2>&1; then
    die "brew 가 없습니다. https://brew.sh 에서 Homebrew 설치 후 재시도하세요."
  fi
  brew install python@3.13
  PY="$(brew --prefix)/opt/python@3.13/bin/python3.13"
  [ -x "$PY" ] || PY="$(command -v python3.13 || true)"
  [ -z "$PY" ] && die "python@3.13 설치 직후 바이너리 탐색 실패"
fi
PYVER=$("$PY" -c 'import sys;print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
ok "python $PYVER ($PY)"

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
  # Homebrew Python 은 PEP 668 로 pip --user 차단 → pipx 필수
  if ! command -v pipx >/dev/null 2>&1; then
    info "pipx 미설치 — Homebrew 로 자동 설치"
    if command -v brew >/dev/null 2>&1; then
      brew install pipx
      pipx ensurepath >/dev/null 2>&1 || true
      export PATH="$HOME/.local/bin:$(brew --prefix)/bin:$PATH"
    else
      die "brew 가 없습니다. 'brew install pipx' 또는 https://pypa.github.io/pipx/ 설치 후 재시도."
    fi
  fi

  info "exo-explore/exo 설치 중 (PyTorch 등 포함, 수분 소요 가능)..."
  if ! pipx install --python "$PY" --force "$EXO_REPO" 2>&1 | tee /tmp/quetta-exo-install.log; then
    warn "pipx 설치 실패 — exo-explore 는 현재 Rust PyO3 바인딩 전환 중이라 pip 설치가 불안정합니다."
    warn "  MLX 는 별도로 이미 설치되어 단일 맥 추론은 가능합니다."
    warn "  필요 시 공식 README 참고: https://github.com/exo-explore/exo"
    warn "  상세 로그: /tmp/quetta-exo-install.log"
    # LaunchAgent 가 이미 등록돼 있으면 실패 로그 방지용으로 언로드만
    if [ -f "$HOME/Library/LaunchAgents/com.quetta.exo.plist" ]; then
      launchctl unload "$HOME/Library/LaunchAgents/com.quetta.exo.plist" 2>/dev/null || true
    fi
    exit 0
  fi
  export PATH="$HOME/.local/bin:$PATH"
  command -v exo >/dev/null 2>&1 || {
    warn "exo 바이너리 미확인 — 설치 실패. 종료"
    exit 0
  }
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
