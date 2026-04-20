#!/usr/bin/env bash
# MLX Distributed — macOS 설치 도우미.
# mlx + mlx-lm + mpi4py + Open MPI (Homebrew).
# 여러 맥에서 `mpirun --hostfile` 로 RDMA/Thunderbolt 분산 추론 가능.

set -e
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info(){ echo -e "${CYAN}▶ $*${NC}"; }
ok()  { echo -e "${GREEN}✓ $*${NC}"; }
warn(){ echo -e "${YELLOW}⚠ $*${NC}"; }
die() { echo -e "${RED}✗ $*${NC}"; exit 1; }

[ "$(uname)" = "Darwin" ] || die "macOS 전용 스크립트입니다."
[ "$(uname -m)" = "arm64" ] || die "Apple Silicon 필수."

# ── 1. Homebrew + Open MPI ──────────────────────────────────────────────────
if ! command -v brew >/dev/null 2>&1; then
  die "Homebrew 가 필요합니다. https://brew.sh"
fi

if ! command -v mpirun >/dev/null 2>&1; then
  info "Open MPI 설치..."
  brew install open-mpi
fi
ok "$(mpirun --version | head -1)"

# ── 2. Python + MLX ─────────────────────────────────────────────────────────
info "Python 패키지 설치 (mlx, mlx-lm, mpi4py)..."
python3 -m pip install --user --upgrade mlx mlx-lm mpi4py
ok "MLX 설치 완료"

# ── 3. hostfile 템플릿 생성 ─────────────────────────────────────────────────
HOSTFILE="$HOME/.mlx-hosts"
if [ ! -f "$HOSTFILE" ]; then
  cat > "$HOSTFILE" <<'HOSTS'
# MLX Distributed — 각 라인에 '<hostname> slots=<gpu 개수>' 형태로 추가
# (Apple Silicon 은 GPU 1대 = slots=1)
# 예:
#   mac-main.local slots=1
#   macbook-pro.local slots=1
#
# Thunderbolt bridge IP를 쓰면 bandwidth ↑:
#   169.254.1.1 slots=1
#   169.254.1.2 slots=1
localhost slots=1
HOSTS
  ok "hostfile 템플릿: $HOSTFILE (편집하여 클러스터 구성)"
else
  ok "hostfile 이미 존재: $HOSTFILE"
fi

# ── 4. 테스트 명령 안내 ─────────────────────────────────────────────────────
echo ""
ok "MLX Distributed 준비 완료!"
echo ""
echo "  ▸ 단일 노드 추론:"
echo "    python -m mlx_lm.generate --model mlx-community/Llama-3.2-3B-Instruct-4bit --prompt 'hello'"
echo ""
echo "  ▸ 2노드 분산 추론 (hostfile 편집 후):"
echo "    mpirun --hostfile $HOSTFILE -np 2 \\"
echo "      python -m mlx_lm.generate \\"
echo "        --model mlx-community/Llama-3.1-70B-Instruct-4bit \\"
echo "        --prompt 'explain ...'"
echo ""
echo "  Quetta Remote Agent 가 연결돼 있으면, Claude에서"
echo "  'mlx 분산으로 Llama 70B 돌려줘' 라고 하면 자동으로 mpirun 조립해 실행."
