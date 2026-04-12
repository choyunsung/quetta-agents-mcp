# quetta-agents-mcp

[![version](https://img.shields.io/badge/version-0.8.0-blue)](https://github.com/choyunsung/coyun-quetta-agents-mcp)

[Quetta Agents](https://github.com/choyunsung/quetta-agents) 스마트 LLM 게이트웨이 + 원격 PC(GPU) 제어를 Claude에서 바로 사용할 수 있는 MCP 서버.

---

## 핵심 기능

1. **스마트 LLM 라우팅** — 질문 유형에 따라 Gemma4/DeepSeek-R1/Claude 자동 선택
2. **원격 PC 제어** — 역방향 WebSocket 연결로 포트포워딩 없이 다른 PC 제어 (GPU 포함)
3. **GPU 자동 라우팅** — `cuda`/`torch`/`nvidia-smi` 등 키워드 감지 시 GPU 에이전트 자동 선택
4. **스마트 디스패처** — `quetta_auto(request="...")` 한 번으로 MCP가 의도 파악 + 자동 실행
5. **파일 분석 파이프라인** — 업로드 → 유형 자동 감지 → RAG 인제스트 → AI 분석

### 라우팅 테이블

| 질문 유형 | 라우팅 |
|----------|--------|
| 코드 개발/리뷰 | Gemma4 + agent-skills 5종 자동 주입 |
| 의료 임상/진단 | DeepSeek-R1 (로컬, 무료) |
| 의료 영상 분석 | Claude Opus |
| 복잡한 멀티스텝 | Gemma4 3개 병렬 실행 → Claude 종합 (SCION) |
| 일반 질문 | Gemma4 (로컬, 무료, 빠름) |
| GPU 계산 | 연결된 원격 GPU 에이전트로 위임 |

---

## 설치

### 원클릭 설치 (권장, Mac/Linux 모두 지원)

```bash
curl -fsSL https://raw.githubusercontent.com/choyunsung/quetta-agents-mcp/master/install.sh | bash
```

설치 스크립트가 자동으로:
1. `uv` 미설치 시 자동 설치 (Mac Homebrew 경로 포함)
2. GitHub HTTPS 우선으로 패키지 다운로드 (SSH 키 불필요), 실패 시 SSH로 폴백
3. `claude mcp add-json` CLI로 등록 (user scope) — `claude mcp list`에 즉시 표시
4. `claude` CLI 없을 때만 `~/.claude/settings.json` 직접 편집

환경변수로 미리 지정 가능:
```bash
QUETTA_GATEWAY_URL=https://rag.quetta-soft.com \
QUETTA_API_KEY=your_api_key \
bash <(curl -fsSL https://raw.githubusercontent.com/choyunsung/quetta-agents-mcp/master/install.sh)
```

### 설치 확인

```bash
claude mcp list | grep quetta
# quetta-agents: /path/to/uvx --from git+https://... quetta-agents-mcp - ✓ Connected
```

### 수동 설치 (claude CLI 방식)

```bash
claude mcp add-json quetta-agents '{
  "command": "uvx",
  "args": ["--from", "git+https://github.com/choyunsung/quetta-agents-mcp", "quetta-agents-mcp"],
  "env": {
    "QUETTA_GATEWAY_URL": "https://rag.quetta-soft.com",
    "QUETTA_ORCHESTRATOR_URL": "https://rag.quetta-soft.com/orchestrator",
    "QUETTA_API_KEY": "발급받은_API_키",
    "QUETTA_TIMEOUT": "300"
  }
}' --scope user
```

> **로컬 실행 시:** `QUETTA_GATEWAY_URL=http://localhost:8701`, `QUETTA_API_KEY`는 비움

설치 후 Claude Code를 재시작하면 적용됩니다.

---

## 업데이트

### Claude 채팅에서

```
quetta_version  # 현재 버전 및 최신 커밋 확인
quetta_update   # 자동 업데이트 (재시작 필요)
```

### 터미널에서

```bash
curl -fsSL https://raw.githubusercontent.com/choyunsung/quetta-agents-mcp/master/update.sh | bash
```

업데이트 후 **Claude Code를 재시작**해야 새 버전이 적용됩니다.

---

## 사용 가능한 도구

### 🎯 스마트 디스패처 (추천 진입점)

| 도구 | 설명 |
|------|------|
| `quetta_auto` | 요청을 분석해 자동으로 적절한 도구/모델/에이전트로 라우팅 |

**동작 예시:**
```python
quetta_auto(request="nvidia-smi 실행해줘")
  # → gpu_compute → quetta_gpu_exec (GPU 에이전트 자동 선택)

quetta_auto(request="원격 PC 화면 보여줘")
  # → screenshot → quetta_remote_screenshot

quetta_auto(request="CRP 3.2가 의미하는 바는")
  # → medical → DeepSeek-R1 임상 추론

quetta_auto(request="이 React 컴포넌트 리팩토링")
  # → code → Gemma4 + agent-skills

quetta_auto(request="전체 시스템 아키텍처 설계")
  # → multi_agent → SCION 병렬 멀티에이전트

quetta_auto(request="이 파일 분석해줘", file_path="/data/patient.csv")
  # → file_analysis → quetta_analyze_file
```

**분류 우선순위:** `gpu_compute > screenshot > remote_shell > file_analysis > medical > code > multi_agent > question`

`dry_run=true` 옵션으로 분류 결과만 확인 가능 (실행 없음).

### 🧠 LLM 게이트웨이

| 도구 | 설명 |
|------|------|
| `quetta_ask` | 질문을 보내면 최적 모델이 자동으로 응답 |
| `quetta_code` | 코드 개발 작업 (agent-skills 5종 자동 주입) |
| `quetta_medical` | 의료 전문 질의 (DeepSeek-R1 임상 추론) |
| `quetta_multi_agent` | 복잡한 태스크를 병렬 에이전트로 처리 |
| `quetta_routing_info` | 쿼리가 어떤 모델로 라우팅될지 미리 확인 |
| `quetta_list_agents` | 등록된 전문 에이전트 목록 조회 |
| `quetta_run_agent` | 특정 에이전트에게 태스크 위임 |

### 💻 원격 PC 제어

| 도구 | 설명 |
|------|------|
| `quetta_remote_connect` | 연결된 에이전트 목록 조회 또는 설치 링크 생성 |
| `quetta_remote_screenshot` | 원격 PC 화면 캡처 (Claude가 화면을 직접 분석) |
| `quetta_remote_click` | 원격 PC 마우스 클릭 (좌/우/더블클릭) |
| `quetta_remote_type` | 원격 PC 텍스트 입력 (클립보드 경유) |
| `quetta_remote_key` | 원격 PC 단축키 입력 (`ctrl+c`, `alt+tab` 등) |
| `quetta_remote_shell` | 원격 PC 셸 명령 (GPU 키워드 자동 감지 → GPU 에이전트) |

### 🚀 GPU 자동 라우팅

| 도구 | 설명 |
|------|------|
| `quetta_gpu_exec` | GPU 필요 명령을 자동으로 GPU 에이전트에서 실행 |
| `quetta_gpu_python` | Python 코드를 GPU 에이전트에서 직접 실행 (torch/cuda 등) |
| `quetta_gpu_status` | 연결된 GPU 에이전트 전체의 `nvidia-smi` 요약 |

**자동 선택 로직:**
1. `agent_id` 명시 → 해당 에이전트 사용
2. 명령어에 GPU 키워드(`cuda`, `torch`, `nvidia-smi`, `train.py` 등) 포함 → 자동 GPU 에이전트 선택
3. `prefer_gpu=True` → GPU 에이전트 강제 선택
4. GPU 에이전트 없음 → 설치 링크 반환 후 에러
5. 에이전트 1개만 연결 → 자동 선택

### 📁 파일 업로드 & 분석

| 도구 | 설명 |
|------|------|
| `quetta_analyze_file` | 파일 업로드 → 유형 자동 감지 → RAG 인제스트 → AI 분석 |
| `quetta_upload_file` | TUS 프로토콜로 대용량 파일 업로드 |
| `quetta_upload_list` | 업로드된 파일 목록 조회 |
| `quetta_upload_process` | 업로드된 파일을 RAG 지식베이스에 인제스트 |
| `quetta_upload_process_all` | 미처리 파일 전체 일괄 인제스트 |

### 🔧 버전 관리

| 도구 | 설명 |
|------|------|
| `quetta_version` | 현재 버전 및 GitHub 최신 커밋 확인 |
| `quetta_update` | GitHub 최신 버전으로 자동 업데이트 |

---

## 원격 PC 제어 시스템

다른 PC(GPU 서버, 개인 컴퓨터 등)를 원격으로 제어할 수 있습니다.  
에이전트가 서버로 **역방향 WebSocket**을 연결하므로 **포트포워딩/방화벽 설정이 전혀 불필요**합니다.

### 아키텍처

```
[Claude MCP] ──REST──▶ [Quetta Gateway :8701]
                               │
                       WebSocket 릴레이 (/agent/ws)
                               │
                        [Remote Agent PC]
                   (역방향 WebSocket 연결 + 자동 재접속)
```

### Gateway 엔드포인트 (`/agent/*`)

| 엔드포인트 | 인증 | 용도 |
|-----------|------|-----|
| `GET /agent/agents` | 필요 | 연결된 에이전트 목록 |
| `GET /agent/install-link?os=<linux\|windows\|mac>` | 필요 | 24시간 유효 설치 링크 생성 |
| `GET /agent/download?token=T&os=X` | 불필요 | 설치 스크립트 다운로드 |
| `GET /agent/script` | 불필요 | `agent.py` 원본 다운로드 |
| `WS /agent/ws?token=T` | 불필요 | 에이전트 WebSocket 연결 |
| `POST /agent/{id}/cmd` | 필요 | MCP → 에이전트 명령 전달 |

### 빠른 시작

#### 1단계: Claude 채팅에서 `/remote-agent` 실행

```
/remote-agent
```

설치 링크가 생성됩니다 (24시간 유효):

```bash
# Linux/Mac
curl -fsSL "https://rag.quetta-soft.com/agent/download?token=XXX&os=linux" | bash

# Windows (브라우저 다운로드 후 .bat 실행)
https://rag.quetta-soft.com/agent/download?token=XXX&os=windows
```

#### 2단계: 원격 PC에서 설치 실행

설치 스크립트가 자동으로:
- Python 확인 (3.9+)
- 의존성 설치 (`websockets`, `pyautogui`, `mss`, `pillow`, `pyperclip`)
- `agent.py` 다운로드
- `.env`에 WS URL·토큰 저장
- 에이전트 즉시 실행 (역방향 WebSocket 연결)

#### 3단계: 연결 자동 감지

`/remote-agent` 스킬이 새 에이전트 연결을 자동 감지하고 알림:

```
✅ 원격 에이전트 연결됨!
  ID      : 878047e4
  호스트   : WIN-6RP9Q54118T
  OS      : Windows
  GPU     : NVIDIA GeForce RTX 4070 SUPER
  화면제어 : 가능 ✅
  스크린샷 : 가능 ✅
```

### 원격 제어 예시

```python
# 화면 보기 (Claude가 이미지 분석)
quetta_remote_screenshot(agent_id="878047e4")

# GPU 상태 확인
quetta_gpu_status()                                    # 모든 GPU 에이전트 요약

# 명령 실행 (GPU 자동 라우팅)
quetta_gpu_exec(command="nvidia-smi")                  # GPU 에이전트 자동 선택
quetta_gpu_exec(command="python train.py --epochs 100", timeout=3600)

# Python 직접 실행
quetta_gpu_python(code="""
import torch
print(torch.cuda.get_device_name(0))
print(f"VRAM: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")
""")

# 마우스/키보드 제어
quetta_remote_click(agent_id="878047e4", x=500, y=300)
quetta_remote_type(agent_id="878047e4", text="Hello World")
quetta_remote_key(agent_id="878047e4", key="ctrl+s")

# 또는 스마트 디스패처 한 번으로
quetta_auto(request="nvidia-smi 돌려봐")                # 자동 GPU 라우팅
quetta_auto(request="원격 PC 화면 보여줘")              # 자동 screenshot
```

### Windows 백그라운드 서비스 등록

설치된 에이전트를 로그온 시 자동 시작되는 백그라운드 서비스로 등록하려면:

1. `~/.quetta-remote-agent/start-hidden.vbs` 생성 (VBS로 `pythonw.exe` 숨김 실행)
2. 시작프로그램 폴더에 복사:
   ```
   %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\QuettaRemoteAgent.vbs
   ```

이후 재부팅/재로그인 시 자동 연결됩니다 (콘솔 창 없음).

### 자동 재연결

- 네트워크 단절 시 **지수 백오프** (3초 → 60초 최대)로 자동 재시도
- 서버 측 WebSocket 타임아웃: 24시간
- Ping 간격: 30초

### 설치 링크 유효시간

- **24시간** 유효
- 만료 시 `/remote-agent` 재실행으로 새 링크 생성

---

## 파일 분석 파이프라인

대용량 파일을 서버에 올리고 AI가 자동으로 분석합니다.

### 파일 유형 자동 감지

| 파일 유형 | 감지 기준 | 처리 방식 |
|----------|----------|---------|
| `medical` | 의료 키워드 ≥ 2개 (환자, 진단, ICD, FHIR 등) | 의료 AI 분석 (DeepSeek-R1) |
| `signal_data` | EDF/DAT/MAT/HDF5 확장자, ECG/BPM 헤더 | Gemma4 + 신호 처리 분석 |
| `document` | 기타 PDF, DOCX, TXT 등 | Gemma4 + 문서 요약 |

### 파이프라인 흐름

```
파일 입력
  │
  ▼
TUS 업로드 (tusd :1080, 최대 GB급)
  │
  ▼
파일 유형 감지 (_detect_file_type)
  │
  ├── medical     → RAG (medical 네임스페이스)     + 의료 AI 분석
  ├── signal_data → RAG (signal_data 네임스페이스) + 신호 분석
  └── document    → RAG (documents 네임스페이스)   + 문서 요약
  │
  ▼
AnalyzeResponse 반환
  (file_type, type_reason, storage_path, text_excerpt, rag_ids, chunks_ingested)
```

### 사용 예시

```python
# 의료 데이터 분석 (파일 경로)
quetta_analyze_file(file_path="/data/patient_records.csv")

# 텍스트 직접 분석
quetta_analyze_file(content="환자 65세 남성 CRP 3.2...", filename="case.txt")

# 업로드만
quetta_upload_file(file_path="/data/report.pdf")

# 배치 처리
quetta_upload_list()                                   # 업로드된 파일 확인
quetta_upload_process_all()                            # 미처리 파일 일괄 인제스트
```

---

## 환경변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `QUETTA_GATEWAY_URL` | `http://localhost:8701` | 게이트웨이 API 주소 |
| `QUETTA_ORCHESTRATOR_URL` | `http://localhost:8700` | 오케스트레이터 주소 |
| `QUETTA_API_KEY` | _(없음)_ | 외부 접근 시 필요한 API 키 |
| `QUETTA_TIMEOUT` | `300` | 요청 타임아웃 (초) |
| `QUETTA_TUSD_URL` | `http://localhost:1080` | tusd 파일 업로드 서버 |
| `QUETTA_RAG_URL` | `http://localhost:8400` | RAG API 서버 |
| `QUETTA_TUSD_TOKEN` | _(없음)_ | tusd X-API-Token (nginx 경유 외부 접근 시) |
| `QUETTA_RAG_KEY` | `rag-claude-key-2026` | RAG API X-API-Key |
| `QUETTA_REMOTE_AGENT_ID` | _(없음)_ | 기본 원격 에이전트 ID (미지정 시 자동 선택) |

---

## 변경 이력

### v0.8.0 (최신)
- **스마트 디스패처** `quetta_auto` 추가 — 자연어 요청을 자동 분류해 적절한 도구로 라우팅
- 의도 분류 7종: `gpu_compute` / `screenshot` / `remote_shell` / `file_analysis` / `medical` / `code` / `multi_agent` / `question`
- `dry_run` 모드: 실제 실행 없이 분류 결과만 확인
- 백틱 코드 블록 자동 추출

### v0.7.0
- **GPU 자동 라우팅** — `quetta_gpu_exec`, `quetta_gpu_python`, `quetta_gpu_status` 3종 추가
- `_pick_agent()` 헬퍼: GPU 키워드 감지 시 자동으로 GPU 에이전트 선택
- 에이전트 1개 연결 시 자동 선택
- GPU 필요한데 없으면 설치 링크 자동 유도

### v0.6.0
- **WebSocket 릴레이 방식**으로 원격 에이전트 아키텍처 전환 (포트포워딩 불필요)
- Gateway `/agent/*` 엔드포인트 통합
- 24시간 유효 설치 링크 시스템
- Windows bat 파일 CP949 인코딩 문제 해결 (v0.6.0 후속 fix)
- nginx WebSocket `/agent/ws` 라우팅 추가

### v0.5.0
- Quetta Remote Agent — 원격 PC Computer Use 브리지

### v0.4.0
- `quetta_analyze_file` 추가 — 파일 업로드 → 유형 감지 → AI 분석

### v0.3.0
- 파일 업로드 MCP 도구 4종 추가 (TUS 프로토콜)

### v0.2.0
- Quetta Agents Gateway 연동 + 자동 라우팅

### v0.1.0
- 초기 릴리스 — `quetta_ask`, `quetta_code`, `quetta_medical`, `quetta_multi_agent`

---

## 라이선스 & 기여

- Repository: https://github.com/choyunsung/quetta-agents-mcp
- Gateway: https://github.com/choyunsung/quetta-agents

Issue/PR 환영합니다.
