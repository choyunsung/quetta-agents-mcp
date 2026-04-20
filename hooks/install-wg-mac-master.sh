#!/usr/bin/env bash
# Quetta WireGuard — Mac **마스터** 피어 설치 (10.66.66.2)
#
# 사전 요구:
#   WG_CONF_B64  환경변수에 서버에서 생성한 wg0.conf base64 값 주입
#
# 자동 수행:
#   1. brew install wireguard-tools (없으면)
#   2. /opt/homebrew/etc/wireguard/wg0.conf 배포 (권한 600)
#   3. wg-quick down/up (이중 실행 대비)
#   4. LaunchDaemon /Library/LaunchDaemons/com.quetta.wg0.plist 등록 (부팅 자동 시작)
#   5. handshake 확인 + 내부 IP 출력
#
# sudo: 중간 여러 단계에서 필수. NOPASSWD 설정돼 있으면 완전 자동,
#       없으면 패스워드 프롬프트가 뜬다 (대화형 세션일 때만).

set -eu
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info(){ echo -e "${CYAN}▶ $*${NC}"; }
ok()  { echo -e "${GREEN}✓ $*${NC}"; }
warn(){ echo -e "${YELLOW}⚠ $*${NC}"; }
die() { echo -e "${RED}✗ $*${NC}" >&2; exit 1; }

[ "$(uname)" = "Darwin" ] || die "macOS 전용 스크립트입니다."
[ -n "${WG_CONF_B64:-}" ] || die "WG_CONF_B64 환경변수가 필요합니다 (서버에서 주입)."

# ── 1. wireguard-tools ───────────────────────────────────────────────────────
if ! command -v wg-quick >/dev/null 2>&1; then
  info "brew install wireguard-tools"
  if command -v brew >/dev/null 2>&1; then
    brew install wireguard-tools
  else
    die "Homebrew 가 없습니다. https://brew.sh 로 설치 후 재시도."
  fi
fi
ok "wireguard-tools: $(which wg-quick)"

# ── 2. wg0.conf 배포 ────────────────────────────────────────────────────────
WG_DIR="/opt/homebrew/etc/wireguard"
info "$WG_DIR/wg0.conf 배포"
sudo mkdir -p "$WG_DIR"
echo "$WG_CONF_B64" | base64 -d | sudo tee "$WG_DIR/wg0.conf" >/dev/null
sudo chmod 600 "$WG_DIR/wg0.conf"
ok "wg0.conf 작성"

# ── 3. wg0 활성화 ───────────────────────────────────────────────────────────
info "wg0 활성화"
sudo wg-quick down wg0 2>/dev/null || true
sudo wg-quick up wg0
ok "wg0 up"

# ── 4. LaunchDaemon (부팅 자동 시작) ────────────────────────────────────────
PLIST=/Library/LaunchDaemons/com.quetta.wg0.plist
info "LaunchDaemon 등록 ($PLIST)"
sudo tee "$PLIST" >/dev/null <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.quetta.wg0</string>
  <key>ProgramArguments</key>
  <array>
    <string>/opt/homebrew/bin/wg-quick</string>
    <string>up</string>
    <string>wg0</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>/var/log/quetta-wg.log</string>
  <key>StandardErrorPath</key><string>/var/log/quetta-wg.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
</dict>
</plist>
PLIST
sudo chown root:wheel "$PLIST"
sudo launchctl unload "$PLIST" 2>/dev/null || true
sudo launchctl load  "$PLIST"
ok "LaunchDaemon 로드"

# ── 5. handshake 확인 ───────────────────────────────────────────────────────
sleep 3
echo ""
echo "=== wg show wg0 ==="
sudo wg show wg0
echo ""
echo "=== WG 내부 IP ==="
ifconfig | grep -E "utun|wg0" -A2 | grep "inet 10.66.66" || echo "(아직 handshake 전 — 몇 초 뒤 재확인)"

echo ""
ok "WireGuard 마스터 피어 설치 완료"
echo "  ▸ 서버에서 ping 10.66.66.2 로 연결 확인 가능"
echo "  ▸ 재부팅 후에도 LaunchDaemon 이 자동으로 wg0 올림"
