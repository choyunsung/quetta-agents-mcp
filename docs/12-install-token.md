# 12. 비공개 설치 시스템 (2가지 방식)

Quetta MCP는 아무나 설치할 수 없습니다. 설치 권한을 배포하는 2가지 방식을 지원합니다.

## 방식 A: GitHub Secret Gist (권장)

관리자가 GitHub에 **secret Gist**로 설정값을 올리고, Gist ID를 팀원에게 전달.

### 팀원 설치

```bash
# 방법 1: gh CLI 인증 사용 (자동)
gh auth login  # 한 번만
QUETTA_GIST_ID="de6ac976511b92dd39115a0ac39626ff" \
bash <(curl -fsSL https://raw.githubusercontent.com/choyunsung/quetta-agents-mcp/master/install.sh)

# 방법 2: GitHub PAT 사용
GH_TOKEN=ghp_xxx QUETTA_GIST_ID="de6ac976..." \
bash <(curl -fsSL https://raw.githubusercontent.com/choyunsung/quetta-agents-mcp/master/install.sh)
```

### 관리자가 Gist 생성

```bash
# 1. config.json 준비
cat > quetta-install-config.json <<EOF
{
  "gateway_url": "https://rag.quetta-soft.com",
  "orchestrator_url": "https://rag.quetta-soft.com/orchestrator",
  "api_key": "YOUR_API_KEY",
  "rag_url": "https://rag.quetta-soft.com",
  "tusd_url": "https://rag.quetta-soft.com",
  "tusd_token": "YOUR_TUSD_TOKEN",
  "rag_key": "rag-claude-key-2026",
  "timeout": "300"
}
EOF

# 2. Secret Gist 생성 (secret = default)
gh gist create quetta-install-config.json -d "Quetta MCP install config"
# → https://gist.github.com/USER/<GIST_ID>

# 3. 팀원에게 Gist ID 전달
# 팀원은 gh CLI로 해당 Gist 읽기 권한이 있어야 함 (비공개 Gist는 소유자 + 공유받은 사람만)
```

### 장점
- 관리가 GitHub UI에서 이루어짐 — 편집, 취소, 권한 관리
- 팀원 인증이 GitHub 계정으로 통합됨
- 설정 파일 버전 관리 (Gist revisions)

### 주의
- "Secret Gist"는 **URL을 아는 누구나 접근 가능**. 진짜 비공개는 Gist를 만든 계정만 접근 가능한 건 아님 — URL 추측 불가.
- 완전 비공개가 필요하면 private GitHub repo + team 권한 사용

---

## 방식 B: Gateway 초대 토큰 (GitHub 불필요)

관리자가 Gateway에서 직접 토큰 발급 → 팀원에게 전달.

### 팀원 설치

```bash
QUETTA_INSTALL_TOKEN="<받은_토큰>" \
bash <(curl -fsSL https://raw.githubusercontent.com/choyunsung/quetta-agents-mcp/master/install.sh)
```

**install.sh 동작:**
1. Gateway `GET /install/config?token=<토큰>` 호출
2. 토큰이 유효하면 설정값(API 키, URL 등) 수신
3. `claude mcp add-json` 으로 Claude Code에 등록
4. `~/.claude/CLAUDE.md` 에 세션 자동 초기화 지시 추가
5. **끝** — 사용자는 API 키를 직접 볼 필요도, 관리할 필요도 없음

토큰 미지정 시 대화형 입력 프롬프트가 나옵니다.

## 관리자 흐름 (토큰 발급)

### 1. 토큰 생성

```bash
# 서버에서 (또는 API_KEY 있는 곳에서)
/data/quetta-agents/scripts/invite.sh create "팀원A"
```

출력:
```
✅ 초대 토큰 발급 완료 (팀원A, 365일)

┌────────────────────────────────────────────────────────────────────┐
│ 아래 명령어를 팀원에게 전달하세요:                                   │
└────────────────────────────────────────────────────────────────────┘

  QUETTA_INSTALL_TOKEN="KjX9sQ_pLm..." \
  bash <(curl -fsSL https://raw.githubusercontent.com/choyunsung/quetta-agents-mcp/master/install.sh)
```

이 명령어를 Slack / 메일 / DM으로 팀원에게 전달합니다.

### 2. 유효기간 지정

```bash
# 7일만 유효
/data/quetta-agents/scripts/invite.sh create "임시-테스터" 7

# 무기한 (0)
/data/quetta-agents/scripts/invite.sh create "영구-사용자" 0
```

### 3. 목록 조회

```bash
/data/quetta-agents/scripts/invite.sh list
```

출력:
```
라벨                  prefix          uses   상태   만료
--------------------------------------------------------------------------------
팀원A                KjX9sQ_pLm      3     ✓active  2027-04-13
임시-테스터          9mNxYp0qRt      1     ✓active  2026-04-20
영구-사용자          Ab3Cd5Ef7g      12    ✓active  ∞
전직_인턴            Zx2Yw4Vu6t      8     ❌revoked 2026-10-10
```

### 4. 토큰 취소

```bash
# prefix 12자로 지정 (충돌 방지)
/data/quetta-agents/scripts/invite.sh revoke KjX9sQ_pLm
```

취소된 토큰은 **즉시 무효화** — 이미 설치된 사용자도 다음 요청부터 실패합니다(설치된 MCP의 실제 API 키가 따로 유효하면 계속 사용 가능, 영구 차단은 master 키 교체).

## REST API (직접 호출)

### 토큰 발급 (admin)
```bash
curl -X POST https://rag.quetta-soft.com/install/invite \
  -H "Authorization: Bearer <MASTER_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"label":"팀원A","expires_days":365}'
```

### 토큰으로 config 조회 (public — 인증 불필요)
```bash
curl https://rag.quetta-soft.com/install/config?token=<INVITE_TOKEN>
```

### 토큰 목록 (admin)
```bash
curl https://rag.quetta-soft.com/install/invites \
  -H "Authorization: Bearer <MASTER_API_KEY>"
```

### 토큰 취소 (admin)
```bash
curl -X DELETE https://rag.quetta-soft.com/install/invite/<PREFIX> \
  -H "Authorization: Bearer <MASTER_API_KEY>"
```

## 보안 고려사항

| 항목 | 설명 |
|------|------|
| 토큰 저장 | Gateway 호스트 `/data/quetta-agents/storage/install_tokens.json` |
| 토큰 형식 | `secrets.token_urlsafe(24)` — 32자, URL-safe |
| 토큰 검증 | O(1) lookup (JSON memory + disk persistence) |
| 만료 | 발급 시 지정 (기본 365일) |
| 사용 기록 | `uses`, `last_used` 필드에 기록 |
| Rate limit | nginx-level 권장 (`/install/config` 엔드포인트) |
| 토큰 유출 시 | `revoke` 또는 master API 키 회전 |

## 토큰 vs 직접 API 키

| 방식 | 용도 | 장점 | 단점 |
|------|------|------|------|
| **초대 토큰** | 팀원 배포 | 키 노출 없음, 취소 가능, 사용 추적 | Gateway 접근 필요 |
| **직접 API 키** (`QUETTA_API_KEY`) | 서버-to-서버 | 완전 오프라인 사용 가능 | 키 관리 필요 |

일반 사용자에게는 **초대 토큰**을 권장합니다. 자동화/스크립트에는 직접 API 키.

## 관련 문서

- [설치 & 설정](./09-configuration.md)
- [공유 메모리](./11-shared-memory.md)
