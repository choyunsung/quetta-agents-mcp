# 09. 설치 & 설정

## 설치

### 원클릭 설치 (Mac / Linux)

```bash
curl -fsSL https://raw.githubusercontent.com/choyunsung/quetta-agents-mcp/master/install.sh | bash
```

환경변수로 미리 지정 가능:

```bash
QUETTA_GATEWAY_URL=https://rag.quetta-soft.com \
QUETTA_API_KEY=발급받은_API_키 \
bash <(curl -fsSL https://raw.githubusercontent.com/choyunsung/quetta-agents-mcp/master/install.sh)
```

install.sh가 자동으로:
1. `uv` 미설치 시 설치
2. GitHub에서 패키지 다운로드 및 검증
3. `claude mcp add-json` CLI로 등록 (user scope)
4. Gateway URL이 `https://`면 RAG/TUSD URL 자동 설정

### 수동 설치

```bash
claude mcp add-json quetta-agents '{
  "command": "uvx",
  "args": ["--from", "git+https://github.com/choyunsung/quetta-agents-mcp", "quetta-agents-mcp"],
  "env": {
    "QUETTA_GATEWAY_URL": "https://rag.quetta-soft.com",
    "QUETTA_ORCHESTRATOR_URL": "https://rag.quetta-soft.com/orchestrator",
    "QUETTA_API_KEY": "발급받은_API_키"
  }
}' --scope user
```

### 설치 확인

```bash
claude mcp list | grep quetta
```

## 환경변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `QUETTA_GATEWAY_URL` | `http://localhost:8701` | Gateway API 주소 |
| `QUETTA_ORCHESTRATOR_URL` | `http://localhost:8700` | Orchestrator 주소 |
| `QUETTA_API_KEY` | _(없음)_ | 외부 접근 시 필요 |
| `QUETTA_TIMEOUT` | `300` | 요청 타임아웃 (초) |
| `QUETTA_REMOTE_AGENT_ID` | _(없음)_ | 기본 원격 에이전트 ID |
| `GEMINI_CLI` | `gemini` | Gemini CLI 실행 파일 경로 |
| `GEMINI_MODEL` | `gemini-2.5-pro` | 사용할 Gemini 모델 |

## Gemini CLI 설치 (선택)

논문·설계도 분석 시 시각 분석 품질 향상:

```bash
npm i -g @google/gemini-cli
gemini  # 첫 실행 시 Google OAuth (브라우저 열림)
```

- 무료 쿼터: 1000 requests/day
- 별도 API 키 불필요 (OAuth 캐시 사용)
- 미설치 시 자동 건너뜀 (파이프라인은 정상 동작)

## 업데이트

### Claude 채팅에서
```
quetta_version   # 현재 버전 확인
quetta_update    # 자동 업데이트
```
→ 업데이트 후 **Claude Code 재시작** 필요.

### 터미널에서
```bash
curl -fsSL https://raw.githubusercontent.com/choyunsung/quetta-agents-mcp/master/update.sh | bash
```

## 제거

```bash
claude mcp remove quetta-agents
```
