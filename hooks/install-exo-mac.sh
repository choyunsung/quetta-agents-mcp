#!/usr/bin/env bash
# exo-explore/exo — macOS Apple Silicon 공식 설치 (uv 기반).
# 여러 Mac 에 동일 스크립트를 실행하면 mDNS 자동 발견으로 클러스터가 된다.
# Thunderbolt bridge 권장 (--discovery-method thunderbolt).
#
# 사전 요구: Xcode CLT, Homebrew.
# 설치 요소: uv, node (brew), Rust nightly (rustup), macmon, git clone + npm build + uv 의존성.
# 결과: LaunchAgent 로 부팅 시 자동 시작. OpenAI-호환 API http://<host>.local:52415

set -e
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info(){ echo -e "${CYAN}▶ $*${NC}"; }
ok()  { echo -e "${GREEN}✓ $*${NC}"; }
warn(){ echo -e "${YELLOW}⚠ $*${NC}"; }
die() { echo -e "${RED}✗ $*${NC}"; exit 1; }

[ "$(uname)" = "Darwin" ] || die "macOS 전용 스크립트입니다."
[ "$(uname -m)" = "arm64" ] || warn "Apple Silicon (arm64) 이 아닙니다 — 성능 제한될 수 있음."

NO_LAUNCHD=0
NO_NPM=0
for arg in "$@"; do
  case "$arg" in
    --no-launchd) NO_LAUNCHD=1 ;;
    --no-npm)     NO_NPM=1 ;;
  esac
done

# ── 1. Xcode CLT ────────────────────────────────────────────────────────────
if ! xcode-select -p >/dev/null 2>&1; then
  info "Xcode Command Line Tools 미설치 — 설치 진행 (창이 뜨면 동의)"
  xcode-select --install || true
  die "Xcode CLT 설치 완료 후 이 스크립트를 재실행하세요."
fi
ok "Xcode CLT: $(xcode-select -p)"

# ── 2. Homebrew + uv + node ─────────────────────────────────────────────────
command -v brew >/dev/null 2>&1 || die "Homebrew 필요: https://brew.sh"

for pkg in uv node; do
  if ! brew list --formula "$pkg" >/dev/null 2>&1; then
    info "brew install $pkg"
    brew install "$pkg"
  fi
done
ok "uv $(uv --version 2>&1)"
ok "node $(node --version 2>&1)"

# ── 3. Rust nightly + macmon ────────────────────────────────────────────────
if ! command -v rustup >/dev/null 2>&1; then
  info "rustup 설치"
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain none
fi
# shellcheck disable=SC1091
[ -f "$HOME/.cargo/env" ] && . "$HOME/.cargo/env"
rustup toolchain list | grep -q nightly || rustup toolchain install nightly
ok "rustc nightly 준비"

if ! command -v macmon >/dev/null 2>&1; then
  info "macmon 설치 (cargo, 수분)"
  cargo install --git https://github.com/vladkels/macmon \
      --rev a1cd06b6cc0d5e61db24fd8832e74cd992097a7d macmon --force
fi
ok "macmon 설치됨"

# ── 4. exo 저장소 clone + dashboard 빌드 ───────────────────────────────────
EXO_DIR="${EXO_DIR:-$HOME/src/exo}"
mkdir -p "$(dirname "$EXO_DIR")"
if [ ! -d "$EXO_DIR/.git" ]; then
  info "git clone exo-explore/exo → $EXO_DIR"
  git clone https://github.com/exo-explore/exo "$EXO_DIR"
else
  info "exo 저장소 업데이트 (git pull)"
  git -C "$EXO_DIR" pull --ff-only || warn "git pull 실패 — 기존 소스로 진행"
fi

if [ "$NO_NPM" = 0 ]; then
  info "dashboard 빌드 (npm install + build, 수분)"
  (cd "$EXO_DIR/dashboard" && npm install --no-audit --no-fund && npm run build)
  ok "dashboard 빌드 완료"
fi

# ── 5. uv 의존성 프리페치 (첫 실행 지연 방지) ───────────────────────────────
info "uv 의존성 해결 (첫 실행 수분 소요)"
(cd "$EXO_DIR" && uv sync 2>&1 | tail -5) || warn "uv sync 부분 실패 — 실행 시 자동 재해결"
ok "uv 환경 준비"

# ── 6. LaunchAgent 등록 (부팅 시 자동 시작) ─────────────────────────────────
if [ "$NO_LAUNCHD" = "1" ]; then
  warn "--no-launchd — 부팅 자동시작 건너뜀. 수동 실행: cd $EXO_DIR && uv run exo"
else
  UV_PATH="$(command -v uv)"
  LOG_DIR="$HOME/Library/Logs/quetta-exo"
  mkdir -p "$LOG_DIR"
  AGENT_DIR="$HOME/Library/LaunchAgents"
  mkdir -p "$AGENT_DIR"
  PLIST="$AGENT_DIR/com.quetta.exo.plist"
  CARGO_BIN="$HOME/.cargo/bin"

  cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.quetta.exo</string>
  <key>WorkingDirectory</key><string>$EXO_DIR</string>
  <key>ProgramArguments</key>
  <array>
    <string>$UV_PATH</string>
    <string>run</string>
    <string>exo</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOG_DIR/out.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$CARGO_BIN</string>
    <key>HOME</key><string>$HOME</string>
  </dict>
</dict>
</plist>
PLIST

  launchctl unload "$PLIST" 2>/dev/null || true
  launchctl load "$PLIST"
  ok "LaunchAgent 등록 → 부팅 자동 시작 ($LOG_DIR)"

  sleep 8
  if launchctl list | grep -q com.quetta.exo; then
    pid=$(launchctl list | awk '$3=="com.quetta.exo"{print $1}')
    if [ -n "$pid" ] && [ "$pid" != "-" ]; then
      ok "exo 프로세스 가동 중 (PID: $pid)"
    else
      warn "exo LaunchAgent 등록됐으나 프로세스 미기동 — 로그 확인: tail -f $LOG_DIR/err.log"
    fi
  fi
fi

echo ""
ok "exo 설치 완료!"
echo ""
echo "  ▸ 수동 실행:     cd $EXO_DIR && uv run exo"
echo "  ▸ 상태 확인:     curl http://localhost:52415/v1/models"
echo "  ▸ 토폴로지:      curl http://localhost:52415/topology"
echo "  ▸ 로그:         tail -f $HOME/Library/Logs/quetta-exo/*.log"
echo ""
echo "  여러 Mac 클러스터:"
echo "    각 Mac 에 동일 스크립트 실행 → mDNS 자동 발견."
echo "    Thunderbolt bridge 권장: plist 의 ProgramArguments 에 --discovery-method thunderbolt 추가"
echo ""
echo "  Quetta Gateway 연결 (마스터 노드 하나 선정 후):"
echo "    서버 .env 에 EXO_ENABLED=true / EXO_BASE_URL=http://<master-mac>.local:52415"
echo "    podman-compose restart quetta-gateway → quetta_exo_status 도구로 확인"
