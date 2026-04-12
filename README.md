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

### LLM 게이트웨이

| 도구 | 설명 |
|------|------|
| `quetta_ask` | 질문을 보내면 최적 모델이 자동으로 응답 |
| `quetta_code` | 코드 개발 작업 (agent-skills 5종 자동 주입) |
| `quetta_medical` | 의료 전문 질의 (DeepSeek-R1 임상 추론) |
| `quetta_multi_agent` | 복잡한 태스크를 병렬 에이전트로 처리 |
| `quetta_routing_info` | 쿼리가 어떤 모델로 라우팅될지 미리 확인 |
| `quetta_list_agents` | 등록된 전문 에이전트 목록 조회 |
| `quetta_run_agent` | 특정 에이전트에게 태스크 위임 |

### 원격 PC 제어 (Remote Agent)

| 도구 | 설명 |
|------|------|
| `quetta_remote_connect` | 연결된 에이전트 목록 조회 또는 설치 링크 생성 |
| `quetta_remote_screenshot` | 원격 PC 화면 캡처 (Claude가 화면을 직접 분석) |
| `quetta_remote_click` | 원격 PC 마우스 클릭 (좌/우/더블클릭) |
| `quetta_remote_type` | 원격 PC 텍스트 입력 (클립보드 경유) |
| `quetta_remote_key` | 원격 PC 단축키 입력 (`ctrl+c`, `alt+tab` 등) |
| `quetta_remote_shell` | 원격 PC 셸 명령어 실행 (GPU 키워드 자동 감지 → GPU 에이전트) |

### 스마트 디스패처 (자동 의도 파악)

| 도구 | 설명 |
|------|------|
| `quetta_auto` | 요청을 분석해 자동으로 적절한 도구/모델/에이전트로 라우팅 |

**동작 예시:**
- `"nvidia-smi 실행해줘"` → `quetta_gpu_exec` (GPU 에이전트 자동 선택)
- `"화면 캡처해줘"` → `quetta_remote_screenshot`
- `"환자 ICD 코드 알려줘"` → `quetta_medical` (DeepSeek-R1)
- `"리팩토링 해줘"` → `quetta_code` (Gemma4 + skills)
- `"전체 시스템 아키텍처 설계해줘"` → `quetta_multi_agent` (SCION 병렬)
- `"python train.py 돌려줘"` → `quetta_gpu_exec`
- 기타 일반 질문 → `quetta_ask` (Gemma4/Claude 자동)

`dry_run=true` 옵션으로 실제 실행 없이 분류 결과만 확인 가능.

### GPU 자동 라우팅

| 도구 | 설명 |
|------|------|
| `quetta_gpu_exec` | GPU 필요 명령을 자동으로 GPU 에이전트에서 실행 |
| `quetta_gpu_python` | Python 코드를 GPU 에이전트에서 직접 실행 (torch/cuda 등) |
| `quetta_gpu_status` | 연결된 GPU 에이전트 전체의 `nvidia-smi` 요약 |

**자동 선택 로직:**
1. `agent_id` 명시 → 해당 에이전트 사용
2. 명령어에 GPU 키워드(`cuda`, `torch`, `nvidia-smi`, `train.py` 등) 포함 → 자동으로 GPU 에이전트 선택
3. `prefer_gpu=True` → GPU 에이전트 강제 선택
4. GPU 에이전트 없음 → 설치 링크 반환 후 에러
5. 에이전트 1개만 연결 → 자동 선택

### 파일 업로드 & 분석

| 도구 | 설명 |
|------|------|
| `quetta_analyze_file` | 파일 업로드 → 유형 자동 감지(medical/signal/document) → RAG 인제스트 → AI 분석 |
| `quetta_upload_file` | 파일 또는 텍스트를 서버에 업로드 (TUS 프로토콜, 대용량 지원) |
| `quetta_upload_list` | 업로드된 파일 목록 조회 |
| `quetta_upload_process` | 업로드된 파일을 RAG 지식베이스에 인제스트 |
| `quetta_upload_process_all` | 미처리 파일 전체를 RAG에 일괄 인제스트 |

### 버전 관리

| 도구 | 설명 |
|------|------|
| `quetta_version` | 현재 버전 및 GitHub 최신 커밋 확인 |
| `quetta_update` | GitHub 최신 버전으로 자동 업데이트 |

---

## 원격 PC 제어 (Remote Agent)

Claude가 다른 PC(GPU 서버, 개인 컴퓨터 등)를 원격으로 제어할 수 있는 기능입니다.  
에이전트가 서버로 역방향 WebSocket을 연결하므로 **포트포워딩이나 방화벽 설정이 전혀 필요 없습니다.**

### 아키텍처

```
[Claude MCP] ──REST──▶ [Quetta Gateway :8701]
                               │
                          WebSocket 릴레이
                               │
                        [Remote Agent PC]
                     (역방향 WebSocket 연결)
```

### 빠른 시작

**1단계: Claude 채팅에서 `/remote-agent` 실행**

```
/remote-agent
```

설치 링크가 생성됩니다:

```
curl -fsSL "https://rag.quetta-soft.com/agent/download?token=...&os=linux" | bash
```

**2단계: 원격 PC 터미널에서 위 명령어 실행**

설치 스크립트가 자동으로:
- Python 가상환경 생성 (`~/.quetta-agent/`)
- 의존성 설치 (websockets, pyautogui, mss, pillow)
- agent.py 다운로드 및 실행

**3단계: 연결 자동 감지**

Claude가 새 에이전트 연결을 감지하면 자동으로 알림:

```
✅ 원격 에이전트 연결됨!
  ID      : abc12345
  호스트   : my-gpu-server
  OS      : Linux
  GPU     : NVIDIA RTX 4090
  화면제어 : 가능 ✅
  스크린샷 : 가능 ✅
```

### 원격 제어 예시

```
# 화면 보기
quetta_remote_screenshot(agent_id="abc12345")

# GPU 상태 확인
quetta_remote_shell(agent_id="abc12345", command="nvidia-smi")

# Python 학습 스크립트 실행
quetta_remote_shell(agent_id="abc12345", command="python train.py --epochs 100")

# 클릭
quetta_remote_click(agent_id="abc12345", x=500, y=300)

# 텍스트 입력
quetta_remote_type(agent_id="abc12345", text="Hello World")

# 단축키
quetta_remote_key(agent_id="abc12345", key="ctrl+s")
```

### 에이전트 상태 확인

```
# 현재 연결된 에이전트 목록
quetta_remote_connect(action="list")

# 새 설치 링크 생성 (Windows)
quetta_remote_connect(action="install-link", os="windows")
```

### 설치 링크 유효시간

- 설치 링크: **24시간** 유효
- 에이전트 연결: 연결되는 동안 유지, **자동 재연결** (네트워크 단절 시 3~60초 백오프)

### Windows 설치

Windows PC에서는 브라우저로 설치 링크에 접속하거나:

```powershell
# PowerShell에서
Invoke-WebRequest "https://rag.quetta-soft.com/agent/download?token=...&os=windows" -OutFile install.bat
.\install.bat
```

---

## 파일 분석 파이프라인

대용량 파일을 서버에 올리고 AI가 자동으로 분석하는 파이프라인입니다.

### 파일 유형 자동 감지

| 파일 유형 | 감지 기준 | 처리 방식 |
|----------|----------|---------|
| `medical` | 의료 키워드 ≥ 2개 (환자, 진단, ICD, FHIR 등) | 의료 AI 분석 |
| `signal_data` | EDF/DAT/MAT/HDF5 확장자, ECG/BPM 헤더 등 | 신호 처리 분석 |
| `document` | 기타 PDF, DOCX, TXT 등 | RAG 인제스트 |

### 사용 예시

```
# 의료 데이터 분석
quetta_analyze_file(file_path="/data/patient_records.csv")

# 업로드만
quetta_upload_file(file_path="/data/report.pdf")

# 업로드된 파일 목록
quetta_upload_list()

# 특정 파일 RAG 인제스트
quetta_upload_process(file_id="abc123")

# 미처리 파일 전체 인제스트
quetta_upload_process_all()
```

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
| `QUETTA_REMOTE_AGENT_ID` | _(없음)_ | 기본 원격 에이전트 ID (미지정 시 매번 agent_id 입력) |
