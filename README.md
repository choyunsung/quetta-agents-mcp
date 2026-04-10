# quetta-agents-mcp

[Quetta Agents](https://github.com/choyunsung/quetta-agents) 스마트 LLM 게이트웨이를 Claude에서 바로 사용할 수 있는 MCP 서버.

질문 내용을 자동으로 분석해 가장 적합한 모델로 라우팅합니다:

| 질문 유형 | 라우팅 |
|----------|--------|
| 코드 개발/리뷰 | Gemma4 + agent-skills 5종 자동 주입 |
| 의료 임상/진단 | DeepSeek-R1 (로컬, 무료) |
| 의료 영상 분석 | Claude Opus |
| 복잡한 멀티스텝 | Gemma4 3개 병렬 실행 → Claude 종합 (SCION) |
| 일반 질문 | Gemma4 (로컬, 무료, 빠름) |

---

## 설치

### 원클릭 설치 (권장)

```bash
curl -fsSL https://raw.githubusercontent.com/choyunsung/quetta-agents-mcp/master/install.sh | bash
```

게이트웨이 URL과 API 키를 환경변수로 미리 지정할 수 있습니다:

```bash
QUETTA_GATEWAY_URL=https://rag.quetta-soft.com \
QUETTA_API_KEY=your_api_key \
bash <(curl -fsSL https://raw.githubusercontent.com/choyunsung/quetta-agents-mcp/master/install.sh)
```

설치 스크립트가 자동으로 처리하는 것:
1. `uv` 미설치 시 자동 설치
2. GitHub에서 패키지 다운로드 및 검증
3. `~/.claude/settings.json`에 MCP 서버 설정 추가 (기존 설정 보존)
4. URL·API 키 대화형 입력 (환경변수 미지정 시)

### 수동 설치

`~/.claude/settings.json`에 직접 추가:

```json
{
  "mcpServers": {
    "quetta-agents": {
      "command": "uvx",
      "args": ["--from", "git+ssh://git@github.com/choyunsung/quetta-agents-mcp", "quetta-agents-mcp"],
      "env": {
        "QUETTA_GATEWAY_URL": "https://rag.quetta-soft.com",
        "QUETTA_ORCHESTRATOR_URL": "https://rag.quetta-soft.com/orchestrator",
        "QUETTA_API_KEY": "발급받은_API_키",
        "QUETTA_TIMEOUT": "300"
      }
    }
  }
}
```

> **같은 서버에서 로컬 실행 시:** `QUETTA_GATEWAY_URL=http://localhost:8701`로 설정하고 `QUETTA_API_KEY`는 비워두면 됩니다.

설정 후 Claude Code를 재시작하면 적용됩니다.

---

## 업데이트

### Claude 채팅에서 (MCP 도구)

```
quetta_version  # 현재 버전 및 최신 커밋 확인
quetta_update   # 자동 업데이트 (재시작 필요)
```

### 터미널에서

```bash
curl -fsSL https://raw.githubusercontent.com/choyunsung/quetta-agents-mcp/master/update.sh | bash
```

> 업데이트 후 **Claude Code를 재시작**해야 새 버전이 적용됩니다.

---

## 사용 가능한 도구

| 도구 | 설명 |
|------|------|
| `quetta_ask` | 질문을 보내면 최적 모델이 자동으로 응답 |
| `quetta_code` | 코드 개발 작업 (agent-skills 5종 자동 주입) |
| `quetta_medical` | 의료 전문 질의 (DeepSeek-R1 임상 추론) |
| `quetta_multi_agent` | 복잡한 태스크를 병렬 에이전트로 처리 |
| `quetta_routing_info` | 쿼리가 어떤 모델로 라우팅될지 미리 확인 |
| `quetta_list_agents` | 등록된 전문 에이전트 목록 조회 |
| `quetta_run_agent` | 특정 에이전트에게 태스크 위임 |
| `quetta_analyze_file` | 파일 업로드 → 유형 자동 감지(medical/signal/document) → RAG 인제스트 → AI 분석 |
| `quetta_upload_file` | 파일 또는 텍스트를 서버에 업로드 (TUS 프로토콜, 대용량 지원) |
| `quetta_upload_list` | 업로드된 파일 목록 조회 |
| `quetta_upload_process` | 업로드된 파일을 RAG 지식베이스에 인제스트 |
| `quetta_upload_process_all` | 미처리 파일 전체를 RAG에 일괄 인제스트 |
| `quetta_version` | 현재 버전 및 GitHub 최신 커밋 확인 |
| `quetta_update` | GitHub 최신 버전으로 자동 업데이트 |

---

## 환경변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `QUETTA_GATEWAY_URL` | `http://localhost:8701` | 게이트웨이 API 주소 |
| `QUETTA_ORCHESTRATOR_URL` | `http://localhost:8700` | 오케스트레이터 주소 |
| `QUETTA_API_KEY` | _(없음)_ | 외부 접근 시 필요한 API 키 |
| `QUETTA_TIMEOUT` | `300` | 요청 타임아웃 (초) |
| `QUETTA_TUSD_URL` | `http://localhost:1080` | tusd 파일 업로드 서버 주소 |
| `QUETTA_RAG_URL` | `http://localhost:8400` | RAG API 서버 주소 |
| `QUETTA_TUSD_TOKEN` | _(없음)_ | tusd X-API-Token (nginx 경유 외부 접근 시) |
| `QUETTA_RAG_KEY` | `rag-claude-key-2026` | RAG API X-API-Key |
