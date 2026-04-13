# 자율 다중 에이전트 연구 시스템: 워크스페이스 격리 영속 메모리와 멀티 계정 연속성을 갖춘 통합 인프라

**저자:** 조윤성 (Quetta Soft)
**버전:** 1.0 — 2026-04-13
**저장소:** https://github.com/choyunsung/quetta-agents-mcp

## 초록

본 논문은 거대언어모델(LLM) 라우팅, 원격 GPU 연산, 검색증강생성(RAG), 그리고 멀티 계정 영속 메모리를 단일 MCP(Model Context Protocol) 서버에 통합한 **Quetta 자동연구 시스템(ARS)**을 제안한다. **ARS 자체가 하나의 연구 산출물**이다 — 시스템의 설계, 반복적 디버깅 추적, 운영 데이터가 모두 자기가 관리하는 동일한 지식베이스에 버전 관리·인제스트되어, 시스템이 자기 자신의 개발 과정을 문서화하는 메타-재귀적 검증 구조를 이룬다. ARS는 서로 다른 사용자 계정·운영체제·지리적 위치에 걸친 여러 Claude Code 인스턴스가 단일 지식베이스를 공유하면서도, 워크스페이스 단위 ACL을 통해 계정별 접근 제어를 보존하도록 한다. 본 시스템은 두 개의 병행 연구 프로그램에 배포되었다: **(1) 5,620 recording, 2,649 피험자, 3개 병원으로 구성된 심자도(MCG) 임상 연구** — 4개의 연구 이니셔티브(RID-001~004)를 병렬로 실행; 그리고 **(2) ARS 인프라 프로젝트 자체** — 단일 24시간 개발 스프린트에서 14차례의 릴리스 사이클(v0.1.0 → v0.14.1)을 시스템 스스로 매개. 실험적으로 ARS는 장기 연구의 cold-start 비용을 O(시간 단위 인간 브리핑)에서 O(`quetta_session_init` 한 번 호출)로 단축하고, 단일 워커 uvicorn 배포 하에서 100% WebSocket 원격 에이전트 안정성을 달성하며, 한 번의 도구 호출로 임의의 학술 PDF를 RAG에 인제스트되어 질의 가능한 지식으로 변환하는 Nougat-OCR + Gemini-Vision + Claude-Synthesis 파이프라인을 지원한다.

**키워드:** 자율 연구, 다중 에이전트 시스템, 검색증강생성, MCP, 영속 메모리, 워크스페이스 격리, 심자도

---

## 1. 서론

### 1.1 두 개의 병행 연구 프로그램

ARS는 자기 설계 철학을 보여주는 두 연구 활동의 교차점에 존재한다:

**프로그램 A — 도메인 연구 (MCG 임상 연구).** 3개 병원 사이트에 걸친 96채널 SQUID 심자도 연구로, 시스템이 신호 품질 분석, 전처리 파이프라인, CAD 분류기 학습, beat-by-beat 변동성 추출을 수천 건의 recording에 대해 오케스트레이션한다.

**프로그램 B — 인프라 연구 (ARS 자체).** ARS의 개발은 일급 연구 프로젝트로 취급된다 — 모든 아키텍처 결정, 디버깅 세션, 트레이드오프가 도메인 연구자가 사용하는 동일 RAG 스토어에 기록된다. 결과적으로 "*왜 uvicorn을 단일 워커로 제한했는가?*"를 질의하면 실제 인시던트 보고서로 직접 인용을 받을 수 있는, 자기 문서화하는 인프라가 된다.

이 이중 구조는 **엔지니어링 지식 포착 비용은 엔지니어링 프로세스 자체가 지식 포착 시스템을 통해 흐를 때 0에 수렴한다**는 핵심 주장을 검증한다. 두 프로그램은 동일한 Gateway, 동일한 RAG 스토어, 동일한 워크스페이스 분리 프리미티브를 공유 — 다만 워크스페이스 태그(`mcg-research` vs `quetta-mcp-engineering`)만 다르다.

### 1.2 현대 AI 보조 연구의 마찰점

현대의 AI 보조 연구 워크플로우는 세 가지 지속적 마찰점을 겪는다:

1. **세션 망각.** 새 채팅마다 이전 세션의 컨텍스트, 결정사항, 부분 결과를 잃는다.
2. **계정 분절.** Claude Code 계정 전환(예: 개인 vs 팀, 무료 vs 엔터프라이즈) 시 연속성 단절.
3. **도구 다양성.** 로컬 LLM(Gemma4, DeepSeek-R1), 상용 API(Claude Sonnet/Opus, Gemini), 원격 GPU 작업 사이의 라우팅을 수동 조율 필요.

**ARS는 이를 다음으로 해결한다:**
- 사용자 해시 액세스 토큰으로 키잉된 공유 RAG 스토어에 메모리 **중앙화** — 동일 게이트웨이를 사용하는 어떤 계정이든 동일하게 누적된 지식 조회.
- 개발/업무/프로젝트별 지식을 분리하는 **워크스페이스 ACL** — 비개발자는 자기 워크스페이스만, 관리자는 통합 가시성 유지.
- 우선순위 기반 의도 분류로 자연어 요청을 적절한 하위 도구(LLM 모델, 논문 분석기, 설계도 분석기, GPU 실행기 등)로 라우팅하는 **스마트 디스패처** (`quetta_auto`).
- 인바운드 포트 포워딩 없이 GPU 보유 PC가 게이트웨이에 등록할 수 있게 하는 **역방향 WebSocket 원격 에이전트** 계층.

---

## 2. 시스템 아키텍처

### 2.1 3계층 토폴로지

```
계층 1 ── Claude Code (모든 계정, 모든 OS)
            │  stdio MCP
            ▼
계층 2 ── quetta-agents-mcp (Python, uvx)
            │  HTTP/HTTPS + WebSocket
            ▼
계층 3 ── Quetta Gateway (FastAPI)
            ├── LLM 라우터 (Ollama / Anthropic / Gemini CLI)
            ├── RAG 하네스 (관련 컨텍스트 자동 주입)
            ├── 역방향 WS 릴레이 (원격 GPU 에이전트)
            ├── 워크스페이스 ACL + 초대 토큰
            ├── 대화 히스토리 (MongoDB)
            └── 파일 업로드 (TUS 프로토콜)
```

### 2.2 영속화 스택

| 계층 | 저장소 | 용도 |
|------|------|------|
| 벡터 지식 | Qdrant (RAG) | 과거 Q&A, 논문, 설계도, 메모의 의미 검색 |
| 관계형 | PostgreSQL | 오케스트레이터 상태, 에이전트 레지스트리, 태스크 큐 |
| 문서 | MongoDB | 사용자 해시 익명화된 대화 이력 |
| 키-값 | JSON 파일 (`/data/quetta-agents/storage/`) | 워크스페이스 ACL, 초대 토큰, 릴레이 토큰 (멱등) |
| 파일 블롭 | tusd (재개 가능 업로드) | 대용량 논문, 설계 파일, 데이터셋 |

### 2.3 다중 에이전트 오케스트레이션

협력적 전문화 원칙에 따라, ARS는 5개의 논리 에이전트를 배치한다:

| 에이전트 | 역할 | 영속화 접점 |
|------|------|---------------------|
| A1 | 연구 이니셔티브 #1 (예: 신호 품질) | RID 문서 + RAG 인제스트 |
| A2 | 연구 이니셔티브 #2 (예: 전처리) | RID 문서 + 지식 그래프 갱신 |
| A3 | 연구 이니셔티브 #3 (예: 분류기) | 모델 체크포인트 + 벤치마크 RAG |
| A4 | 연구 이니셔티브 #4 (예: 변동성) | 파이프라인 설계 + 결과 인제스트 |
| A5 | State Master | 원자적 상태 갱신, git commit/push, RAG 동기화 |

각 에이전트는 동일한 게이트웨이를 사용하면서, `X-Session-Id`와 `X-Workspace` 헤더로만 자신을 구별한다.

---

## 3. 방법

### 3.1 Self-Bootstrapping 프로토콜

세션 시작 시, 각 Claude Code 인스턴스는 (설치 시 `~/.claude/CLAUDE.md`에 자동 주입된 지시에 의해) 다음을 호출한다:

```
quetta_session_init()
```

원자적으로 반환되는 것:
- 사용자의 영속 메모리 항목 (`source=user-memory`)
- 최근 대화 컨텍스트 (MongoDB의 마지막 N개 Q&A)
- 접근 가능한 워크스페이스에 인제스트된 활성 문서(논문, 설계도) 목록

이 한 번의 호출이 이전에는 수십 번의 수동 프롬프트 재브리핑을 대체한다.

### 3.2 워크스페이스 격리 RAG

**워크스페이스**를 지식 그래프의 명명된 파티션으로 정의한다. 게이트웨이 하네스 내부의 `_pick_agent` 스타일 라우팅 로직이 `metadata.workspace ∈ allowedSet(user)`를 사용하여 검색 결과를 필터링한다. 기본 워크스페이스:

- `development` — 코드, 아키텍처, 트러블슈팅 (엔지니어 기본값)
- `business` — 회의록, 결정사항, 일정 (비엔지니어 기본값)

관리자가 임의 워크스페이스를 생성할 수 있다. 사용자는 `quetta_workspace_request(workspace, reason)`으로 접근을 요청하고, 관리자가 `quetta_admin_resolve`로 해결한다. 이로써 비엔지니어가 "시스템이 무엇을 하나요?"라고 질의할 때 개발자만을 위한 코드 수준 세부사항을 절대 보지 못하도록 보장하여 인지 부하를 제거한다.

### 3.3 의도 분류를 통한 스마트 디스패치

`quetta_auto(request)`는 13개 의도에 대해 우선순위 순위 키워드 분류기를 실행한다:

```
memory_save → memory_recall → memory_list →
blueprint_query → blueprint_analysis →
paper_query → paper_analysis →
gpu_compute → screenshot → remote_shell →
file_analysis → medical → code → multi_agent → question
```

각 의도는 하나의 전문 도구 호출(`quetta_memory_save`, `quetta_analyze_blueprint`, `quetta_gpu_exec` 등)에 매핑된다. 매칭되지 않는 요청은 `quetta_ask`로 fall-through되어, LLM 게이트웨이를 통해 최적의 백엔드(저렴한 로컬 추론은 Gemma4, 복잡한 추론은 Claude Sonnet, 임상 질문은 DeepSeek-R1, 비전은 Gemini CLI)로 라우팅된다.

### 3.4 역방향 WebSocket 원격 에이전트

연구자의 자택/연구실 PC의 GPU 자원을 인바운드 포트 노출 없이 사용하기 위해, GPU 호스트의 에이전트가 `wss://gateway/agent/ws`로 아웃바운드 WebSocket을 연다. 운영 안정성을 위해 우리가 발견한 핵심 구현 세부사항:

1. **단일 uvicorn 워커** — 다중 워커 모드는 `_agents` 딕셔너리 분절을 일으켜 GPU 조회에서 50% 간헐적 실패율을 발생시켰다.
2. **`stdout = open(devnull)`** — `pythonw.exe`는 콘솔이 없어 어떤 `print()`도 `AttributeError`를 일으켜 프로세스를 종료시켰다.
3. **`stdout.reconfigure(encoding="utf-8")`** — Windows cp949 코덱이 이모지 문자(`✓`, `✗`, `⚠`)를 거부해 NSSM 서비스 모드 내부에서 즉시 충돌을 일으켰다.
4. **JSON 파일 토큰 영속화** — `/data/quetta-agents/storage/relay_tokens.json`에 저장된 설치 토큰이 컨테이너 재시작 후에도 유지된다.

이 수정사항을 적용한 후, 100% 연결 안정성(50/50 폴링 성공)과 인증 실패 0건을 관찰했다.

### 3.5 문서 인제스트 파이프라인

학술 논문의 경우, 파이프라인은 다음과 같다:

```
PDF → TUS 업로드 → GPU 에이전트가 nougat-OCR 실행 (LaTeX 품질 수식)
                 → Gemini CLI 비전 분석 (그림, 표)
                 → Claude Sonnet이 둘 다 한글 리포트로 종합
                 → 세 산출물 모두 RAG에 인제스트
                   (source = paper:<filename>, paper:<filename>#synthesis, paper:<filename>#gemini)
```

엔지니어링 설계도(기계, 전기, CPLD/FPGA)의 경우, 파이프라인은 Nougat 대신 PyMuPDF 벡터 텍스트 추출을 사용하고 타입별 Gemini 프롬프트(기계는 GD&T, 전기는 단선결선도, 디지털 논리는 RTL/FSM)를 사용한다.

---

## 4. 구현

### 4.1 Quetta Agents MCP (v0.14.1)

MCP 서버는 9개 카테고리에 걸쳐 30+개 도구를 노출한다:

| 카테고리 | 도구 수 | 예시 |
|---------|-----------|---------|
| LLM 게이트웨이 | 7 | `quetta_ask`, `quetta_code`, `quetta_medical`, `quetta_multi_agent` |
| 스마트 디스패처 | 1 | `quetta_auto` |
| 원격 제어 | 6 | `quetta_remote_screenshot`, `quetta_remote_shell` |
| GPU 라우팅 | 3 | `quetta_gpu_exec`, `quetta_gpu_python`, `quetta_gpu_status` |
| 논문 분석 | 2 | `quetta_analyze_paper`, `quetta_paper_query` |
| 설계도 분석 | 2 | `quetta_analyze_blueprint`, `quetta_blueprint_query` |
| 파일 & RAG | 5 | `quetta_upload_file`, `quetta_analyze_file` |
| 공유 메모리 | 4 | `quetta_memory_save/recall/list/session_init` |
| 히스토리 | 3 | `quetta_history_list/get/stats` |
| 워크스페이스 | 6 | `quetta_workspace_list/request`, `quetta_admin_*` |
| 버전 | 2 | `quetta_version`, `quetta_update` |

### 4.2 Gateway 엔드포인트

REST와 WebSocket 표면이 관심사별로 분리된다:

| 경로 | 용도 |
|------|---------|
| `POST /v1/chat/completions` | OpenAI 호환 LLM (자동 라우팅 + RAG 하네스) |
| `WS /agent/ws?token=…` | 원격 에이전트의 역방향 WebSocket |
| `GET /agent/agents` | 연결된 에이전트 목록 |
| `POST /agent/{id}/cmd` | 에이전트에 명령 전송 (셸, 스크린샷 등) |
| `GET /agent/install-link` | 7일 유효 설치 토큰 발급 |
| `GET /install/config?token=…` | 초대 토큰을 설치 config로 해석 |
| `GET/POST /workspace/*` | 워크스페이스 ACL CRUD |
| `GET /history/sessions` | 대화 이력 (MongoDB) |
| `POST /rag/search`, `POST /rag/ingest` | 직접 RAG 접근 |

### 4.3 Claude Code 연결 메커니즘

ARS와 Claude Code 사이의 통합은 4계층 책임 분리로 설계되었다:

#### 4.3.1 stdio 기반 MCP 프로토콜

Claude Code는 MCP(Model Context Protocol) 사양에 따라 자식 프로세스로 MCP 서버를 실행하고, 표준 입출력(stdio)으로 JSON-RPC 메시지를 주고받는다. quetta-agents-mcp는 `uvx --from git+https://github.com/choyunsung/quetta-agents-mcp quetta-agents-mcp` 명령으로 기동되며, Python 가상환경 격리와 의존성 자동 설치를 `uv` 패키지 매니저가 담당한다.

```
Claude Code 프로세스
   │ stdin: { "method": "tools/call", "params": { "name": "quetta_ask", ... } }
   │ stdout: { "result": { "content": [...] } }
   ▼
quetta-agents-mcp (uvx 자식 프로세스)
   │ httpx 비동기 HTTP
   ▼
Quetta Gateway → LLM / RAG / 원격 GPU
```

#### 4.3.2 도구 등록 (`claude mcp add-json`)

설치 시 `claude mcp add-json quetta-agents '{...}' --scope user` 명령으로 사용자 스코프에 등록된다. 이로써 **모든 프로젝트의 Claude Code 세션이 동일한 quetta MCP 인스턴스를 공유**한다 — 즉 사용자가 어느 디렉토리에서 Claude Code를 실행하든 quetta 도구가 자동 가용.

설정 위치:
- macOS/Linux: `~/.claude.json`
- Windows: `%USERPROFILE%\.claude.json`

설정 내용 예시:
```json
{
  "mcpServers": {
    "quetta-agents": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/choyunsung/quetta-agents-mcp", "quetta-agents-mcp"],
      "env": {
        "QUETTA_GATEWAY_URL": "https://rag.quetta-soft.com",
        "QUETTA_API_KEY": "<발급된 키>",
        "QUETTA_RAG_URL": "https://rag.quetta-soft.com",
        "QUETTA_TUSD_URL": "https://rag.quetta-soft.com",
        "QUETTA_TUSD_TOKEN": "<TUSD 토큰>"
      }
    }
  }
}
```

#### 4.3.3 CLAUDE.md 자동 주입을 통한 세션 부트스트랩

설치 스크립트는 `~/.claude/CLAUDE.md`에 마커 기반 멱등성 블록을 추가한다:

```markdown
<!-- quetta-agents-mcp:auto-init BEGIN -->
## Quetta Agents MCP — 공유 메모리 자동 초기화

새 Claude Code 세션 시작 직후에 아래 도구를 한 번 호출:
    quetta_session_init()

반환된 사용자 메모리 / 최근 맥락 / 활성 문서를 현재 대화 컨텍스트에 반영합니다.
- 중요 정보는 quetta_memory_save(text="...") 로 영구 저장
- quetta_ask / quetta_auto는 RAG harness가 자동 컨텍스트 주입
<!-- quetta-agents-mcp:auto-init END -->
```

Claude Code는 모든 새 세션에서 CLAUDE.md를 자동 로드하므로, 이 지시문이 **사용자 측 추가 명령 없이도 quetta_session_init()을 호출**하게 만든다. 결과적으로 채팅을 시작하자마자 공유 메모리가 컨텍스트로 주입되어 멀티 계정 / 멀티 세션 연속성이 자동 달성된다.

#### 4.3.4 Claude CLI를 통한 LLM 백엔드 통합

Gateway의 LLM 라우터는 Claude 응답을 두 가지 경로로 받을 수 있다:

| 경로 | 인증 | 사용 시나리오 |
|------|------|------------|
| **Anthropic API SDK** | `ANTHROPIC_API_KEY` | 전통적 API 호출 (별도 결제) |
| **Claude CLI subprocess** | OAuth 캐시 (`~/.claude/.credentials.json`) | Claude Code Pro/Max 구독 활용 |

기본 구성은 **Claude CLI subprocess 방식**이다 — 즉 `~/.claude/.credentials.json`을 컨테이너에 `:rw` 마운트하여 Claude CLI가 OAuth 토큰을 자동 갱신할 수 있도록 한다. 이 방식의 핵심 장점:

- **별도 API 키 발급 불필요** — 사용자의 기존 Claude Code 구독을 그대로 활용
- **자동 토큰 갱신** — refresh token이 만료되면 CLI가 백그라운드에서 갱신
- **사용량 통합** — Claude Code의 일반 사용량과 합산되어 Anthropic 콘솔에서 단일 뷰 제공

이 통합 방식은 Quetta가 자체 LLM API 비용을 부담하지 않고도 팀 전체의 Claude 호출을 라우팅할 수 있게 하는 핵심 설계 결정이다.

#### 4.3.5 양방향 정보 흐름

요약하면 Claude Code ↔ ARS의 양방향 흐름은 다음과 같다:

```
[Claude Code 세션 시작]
    ↓
CLAUDE.md 자동 로드
    ↓
"quetta_session_init()" 자동 호출
    ↓
[Gateway] /v1/chat/completions → RAG harness가 사용자 워크스페이스의 메모리 검색
    ↓
[Claude] 컨텍스트가 주입된 상태로 응답
    ↓
응답 + Q&A → MongoDB 히스토리 + RAG 자동 인제스트 (다음 세션을 위한 기억 축적)
```

이 사이클이 모든 채팅마다 반복되며, 사용자는 별도 도구 호출 없이도 모든 과거 작업이 컨텍스트로 자동 결합되는 경험을 얻는다.

### 4.4 배포 메커니즘

분산된 팀의 채택을 용이하게 하기 위해, 직교적인 3가지 설치 경로를 제공한다:

1. **GitHub Secret Gist** — 관리자가 config JSON을 secret Gist로 발행, 설치 스크립트가 `gh` CLI로 가져옴.
2. **Gateway 초대 토큰** — 관리자가 `invite.sh create "username"`을 실행하여 받은 한 줄 설치 명령을 공유.
3. **직접 API 키** — 헤드리스/CI 환경용.

크로스 플랫폼 설치 스크립트(Mac/Linux는 `install.sh`, Windows는 `install.ps1`; NSSM 기반 Windows 서비스용은 `install-service.ps1`)로 동일 워크플로우가 모든 환경에 적용되도록 보장한다.

---

## 5. 사례 연구

ARS 단일 인스턴스에서 동시 실행된 두 사례 연구를 제시하여 **도메인 연구**와 **인프라 연구** 양쪽 모드를 보여준다.

### 5A. 사례 연구 1 — ARS 자체의 자기-호스팅 엔지니어링 (프로그램 B)

24시간 개발 스프린트에서 ARS 인프라의 14개 릴리스 버전(v0.1.0 → v0.14.1)이 생성되었다. 각 릴리스는 두 GitHub 저장소(`quetta-agents-mcp`, `quetta-agents`)에 커밋되었고, 모든 중요한 결정이 동시에 시스템 자체의 RAG 스토어에 `source = user-memory`, `tags = [release-notes, build-log]`로 인제스트되었다.

| 릴리스 | 기능 | 트리거 이벤트 |
|---------|-----------|---------------|
| v0.7.0 | GPU 자동 라우팅 | 연구자가 `nvidia-smi` 분석 요청 |
| v0.8.0 | 스마트 디스패처 (`quetta_auto`) | 자연어 도구 라우팅 필요성 |
| v0.9.0 | 논문 분석기 (Nougat) | PMB 리뷰어 반박 준비 |
| v0.10.0 | 분석 결과의 RAG 자동 인제스트 | 지식 영속성 요구 |
| v0.12.0 | 공유 메모리 + 워크스페이스 프리미티브 | 멀티 계정 팀 시나리오 |
| v0.13.0 | NoSQL 대화 이력 + 초대 토큰 | 감사 추적 + 접근 제어 |
| v0.13.1 | GitHub Gist 설치기 | 마찰 없는 팀 온보딩 |
| v0.13.2 | Windows PowerShell 설치기 | 크로스 플랫폼 대등성 |
| v0.14.0 | 워크스페이스 ACL + admin 도구 | 엔지니어링 vs 업무 지식 분리 |
| v0.14.1 | Windows Service 모드 (NSSM) | 재부팅 생존 요구 |

이 기간에 디버깅된 14건의 인시던트는 **모두 14건이 RAG에 그대로 포착**되었으며, 그 근본 원인과 수정사항을 포함한다:
- `OLLAMA_HOST=127.0.0.1` → `0.0.0.0:11434` (컨테이너 도달 가능성)
- `RAG harness "results" → "sources"` 필드명 불일치
- `--bare` Claude CLI 플래그가 OAuth 우회
- `pythonw stdout = None` → `AttributeError` 연쇄
- Windows `cp949` 코덱이 이모지 거부
- uvicorn `--workers 2`가 `_agents` 딕셔너리 분절 야기
- nginx `/agent/` `proxy_read_timeout`이 Nougat 설치에 부족

이들은 이제 모든 팀 계정에서 `quetta_memory_recall`을 통해 검색 가능하다.

### 5B. 사례 연구 2 — MCG-DATA 임상 연구 프로그램 (프로그램 A)

#### 5B.1 데이터셋

- **5,620 recording**, **2,649 피험자** 3개 병원 사이트(GIL, CMCEP, Severance)
- 96채널 SQUID 자력계 (KRISS DROS), 1024 Hz, 획득당 120 s
- 데이터 규모: **101.8 GB NPZ 캐시**

#### 5B.2 자율적으로 실행된 연구 이니셔티브

| RID | 제목 | 상태 | 결과 |
|-----|-------|--------|---------|
| RID-001 | 신호 품질 전수 조사 | 완료 | 5,620 중 1,314 분석; 노이즈 감소 후 82.8% 사용 가능 |
| RID-002 | 전처리 파이프라인 설계 | 완료 | 6단계 파이프라인을 3개 사이트 모두에서 검증 |
| RID-003 | CAD 이진 분류기 베이스라인 | 설계 완료 | 2,611 피험자, LOSO 검증 계획 |
| RID-004 | Beat-by-Beat 변동성 분석 | 설계 완료 | Slavic R-peak + 다채널 합의 |

#### 5B.3 지식 그래프 인사이트

| ID | 인사이트 | 영향 |
|----|---------|--------|
| KI-001 | 60 Hz 노이즈가 모든 사이트에 편재 | 모든 파이프라인에 notch 필터 필요 |
| KI-002 | Severance는 이질적 샘플링 레이트 (500/1000/1500 Hz) | 사이트 간 분석에 리샘플링 필요 |
| KI-003 | ML 학습용 ~1,082 CAD 피험자 사용 가능 | 이진 분류기에 충분 |
| KI-004 | GIL/CMCEP는 REST+STRESS 쌍 보유 | 대조 ischemia 분석 가능 |
| KI-005 | NPZ 캐시가 임상 recording 100% 커버 | 빠른 배치 로딩 가능 |

#### 5B.4 주목할 만한 실증 결과 (RID-005)

T-wave 형태학의 공간 패턴 분석 결과:
- **T-wave spatial skew**: AUC 0.672 (p = 0.0002), 가장 강력한 MCG 단독 마커
- **T-wave spatial range/dipole**: AUC 0.630 (p = 0.005)
- **Inter-channel correlation std**: AUC 0.610 (p = 0.015)

이 결과들은 RAG에 그대로 인제스트되어 모든 팀 계정에서 질의 가능한 상태로 유지된다.

---

## 6. 결과

### 6.1 안정성 지표

| 지표 | 수정 전 | 수정 후 |
|------|---------|---------|
| 원격 에이전트 연결 안정성 | ~50% (워커 race) | **100% (50/50)** |
| 서비스 모드 충돌율 (Windows pythonw) | 0.2초 내 100% | 0% |
| RAG 하네스 컨텍스트 주입 | 0 청크 (필드명 버그) | 쿼리당 4 청크 |
| 컨테이너 재시작 후 설치 토큰 보존 | 0% (메모리) | 100% (파일 영속) |

### 6.2 기능 비교

| 기능 | 기본 Claude Code | ARS 증강 Claude Code |
|---------|--------------------|----------------------------|
| 세션 간 메모리 | 제한적 (CLAUDE.md) | 완전 (RAG + MongoDB + 워크스페이스) |
| 계정 간 메모리 | 없음 | 완전 (공유 게이트웨이) |
| 원격 GPU 실행 | 없음 | 역방향 WebSocket 릴레이 |
| 논문 분석 | 수동 컨텍스트 붙여넣기 | 단일 도구 파이프라인 (Nougat + Gemini + Claude) |
| 설계도 분석 | 제한된 비전 | 타입 전문화 (기계 / 전기 / CPLD) |
| 워크스페이스 격리 | 없음 | ACL 제어 |
| 대화 이력 | 세션별 | 영속, 검색 가능, 익명화 |

### 6.3 채택 마찰

- **설치 시간** (단일 명령, 신규 머신): 2-3분
- **계정 간 온보딩**: 설치 후 추가 단계 0
- **메모리 호출 지연**: `quetta_memory_recall` 호출당 < 100 ms
- **논문 분석 end-to-end**: 3-10분 (첫 실행은 Nougat 설치 포함)

---

## 7. 논의

### 7.1 설계 트레이드오프

**단일 uvicorn 워커 vs. 수평 확장.** WebSocket 릴레이의 `_agents` 딕셔너리가 프로세스 로컬이므로 게이트웨이를 의도적으로 단일 워커로 제한했다. 수평 확장은 에이전트 등록을 위한 Redis 백엔드 pub/sub이 필요하며, 향후 작업으로 미룬다.

**파일 기반 ACL vs. 데이터베이스 ACL.** 워크스페이스와 초대 토큰은 PostgreSQL이 아닌 마운트된 볼륨 내 JSON 파일에 위치한다. 한 번의 `cat workspaces.json`이 전체 ACL을 노출하므로 재해 복구가 단순화되며, 쓰기 처리량은 하루에 O(10) admin 작업 수준에 불과해 무시할 만하다.

**SHA-256[:16]을 통한 익명화.** 대화 이력은 원시 API 키가 아닌 `user_hash`를 저장한다. 이는 사용자별 분석("누가 가장 활발했나?")을 허용하면서 해시를 자격증명으로 역추적하는 것을 계산상 불가능하게 한다.

### 7.2 한계

1. 역방향 WebSocket 모델은 GPU 에이전트가 신뢰성 있는 아웃바운드 연결을 가진다고 가정한다; 엄격한 NAT 타임아웃 뒤의 에이전트는 keep-alive 튜닝이 필요할 수 있다.
2. 워크스페이스 필터링은 RAG가 top-K 결과를 반환한 후 클라이언트 측에서 작동한다. 데이터가 희소한 워크스페이스의 경우 보상하기 위해 `top_k` 증가가 필요하다.
3. Gemini CLI 쿼터(Google 계정당 무료 1,000 요청/일)가 논문 분석 처리량을 제약한다; 상용 API 키 오버라이드는 문서화되어 있으나 설치 흐름에는 내장되지 않았다.

### 7.3 향후 작업

- Redis pub/sub을 통한 WebSocket 릴레이 **수평 확장**
- 서브밀리초 필터 성능을 위한 **워크스페이스 수준 RAG 인덱싱** (별도 Qdrant 컬렉션)
- 관리자 ACL 변경에 대한 **감사 추적**
- 승인된 연구 산출물의 **자동 Notion 동기화** (현재는 Outline을 통한 수동)

---

## 8. 결론

ARS는 LLM 라우팅, GPU 접근, RAG 메모리, 접근 제어를 단일 MCP 서버 뒤에 공동 배치함으로써 자율 연구를 실용적으로 만들 수 있음을 보여준다. 본 시스템은 수천 건의 MCG recording에 걸친 4개의 병렬 연구 이니셔티브를 지원하면서 여러 Claude Code 계정과 운영체제 간 세션 연속성을 보존했다. 다른 연구 그룹이 단 하룻동안에 동등한 환경을 부트스트랩할 수 있도록 하는 명시적 목표로, 전체 스택 — MCP 서버, 게이트웨이, 설치 스크립트(Mac, Linux, Windows), 운영 문서 — 을 아래 URL에서 오픈소스 라이선스로 공개한다.

---

## 참고문헌 & 저장소 맵

| 컴포넌트 | URL | 라인 수 (대략) |
|-----------|-----|-----|
| MCP 서버 | https://github.com/choyunsung/quetta-agents-mcp | ~3,500 |
| Gateway | https://github.com/choyunsung/quetta-agents | ~4,200 |
| 문서 | `docs/` (15장) + `dist/quetta-agents-mcp-docs.pdf` | ~30,000 단어 |
| Nougat fork (학술 OCR) | https://github.com/choyunsung/nougat | (upstream) |
| 설치 스크립트 | `install.sh`, `install.ps1`, `install-service.ps1`, `install-task.ps1` | — |

## 감사의 글

다음의 어깨 위에 구축됨: FastAPI, uvicorn, Anthropic Claude, Google Gemini CLI, Ollama, Qdrant, MongoDB, NSSM, PyMuPDF, Meta Nougat, websockets, httpx.

---

**문서 영속화 기록 (빌드 시점 기준):**
- RAG ID: `9960f007-e91a-46a3-8fbb-4b87e3148f22` (source = `user-memory`)
- Outline 일지: `/doc/claude-2026-04-13-x0hOeggeNl`
- GitHub 커밋: `4e39c9d` (v0.10.0) → `f208f9b` (v0.14.1+) 두 저장소에 걸쳐.
