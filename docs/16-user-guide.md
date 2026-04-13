# 자율연구시스템 — 사용자 가이드

> **한 줄 요약** — Claude Code에 quetta-agents-mcp를 설치하면, 어떤 컴퓨터·어떤 계정에서든 자료/기억/원격 GPU를 공유하며 연구를 이어갈 수 있습니다.

---

## 1. 무엇을 하는 시스템인가요?

**자율연구시스템(ARS)**은 Claude Code를 도구로 활용해 연구·업무를 자동화·기록·재사용하도록 돕는 통합 환경입니다.

### 주요 가치

| 항목 | 의미 |
|------|------|
| 🧠 영구 기억 | 어떤 계정으로 접속해도 이전 대화·메모리·문서가 자동으로 따라옴 |
| 🚀 원격 GPU | 인터넷만 되면 연구실 GPU PC에서 학습/추론 자동 실행 |
| 📑 논문 분석 | PDF 한 번 올리면 수식·그림·결론까지 한글 리포트로 자동 정리 |
| 📐 설계도 분석 | 기계/전기/CPLD 도면을 엔지니어 관점으로 자동 해석 |
| 🔐 워크스페이스 | 업무용·개발용·프로젝트용 지식을 분리해 사용자별 접근 제어 |
| 🤝 멀티 계정 공유 | 팀원이 같이 쓰면 서로의 작업이 즉시 검색 가능 |

---

## 2. 한눈에 보는 사용 흐름

```
1. 설치 (한 줄 명령) → Claude Code 재시작
2. 새 채팅 시작 → 자동으로 이전 기억 로드 (quetta_session_init)
3. 자연어로 요청:
   "이 논문 분석해줘"          → 논문 분석 파이프라인
   "원격 PC에 nvidia-smi"      → GPU 에이전트 자동 선택
   "기억해줘: 이 프로젝트 ..." → 영구 메모리 저장
4. 결과는 모두 RAG에 자동 저장 → 다음 세션/계정에서 자동 인용
```

---

## 3. 설치

### 사전 준비 (최초 1회)

| OS | 필요 도구 |
|------|------|
| Mac | `brew install gh uv` |
| Linux | `sudo apt install -y curl python3` + uv 설치 스크립트 |
| Windows | `winget install astral-sh.uv` + `winget install GitHub.cli` |

Claude Code: https://claude.ai/download

### 한 줄 설치 (3가지 방법)

#### A. GitHub Gist (권장) ⭐

관리자가 받은 **Gist ID**가 있으면 가장 간단합니다.

**Mac / Linux:**
```bash
gh auth login   # 최초 1회
QUETTA_GIST_ID="관리자가_준_GIST_ID" \
bash <(curl -fsSL https://raw.githubusercontent.com/choyunsung/quetta-agents-mcp/master/install.sh)
```

**Windows (PowerShell):**
```powershell
gh auth login
$env:QUETTA_GIST_ID="관리자가_준_GIST_ID"
iwr -useb https://raw.githubusercontent.com/choyunsung/quetta-agents-mcp/master/install.ps1 | iex
```

#### B. 초대 토큰 (GitHub 계정 없을 때)

```bash
QUETTA_INSTALL_TOKEN="관리자가_준_토큰" \
bash <(curl -fsSL https://raw.githubusercontent.com/choyunsung/quetta-agents-mcp/master/install.sh)
```

#### C. 직접 API 키 (개발자/CI)

```bash
QUETTA_API_KEY="본인_키" \
bash <(curl -fsSL https://raw.githubusercontent.com/choyunsung/quetta-agents-mcp/master/install.sh)
```

### 설치 확인

```bash
claude mcp list | grep quetta
# quetta-agents: ✓ Connected
```

설치 스크립트가 자동으로:
1. uv 미설치 시 자동 설치
2. Claude Code에 등록
3. CLAUDE.md에 세션 시작 시 자동 메모리 로드 지시 추가

설치 완료 후 **Claude Code 재시작** 한 번이면 끝.

---

## 4. 주요 기능

### 🎯 스마트 디스패처 (가장 추천)

질문/요청을 자연어로 던지면 알아서 적절한 도구로 라우팅:

```
quetta_auto(request="이 논문 분석해줘", file_path="/data/paper.pdf")
quetta_auto(request="GPU 상태 보여줘")
quetta_auto(request="기억해줘: Python 3.11 + FastAPI 사용")
quetta_auto(request="저장된 논문에서 attention mechanism 비교해줘")
```

### 💬 LLM 자동 라우팅

| 질문 유형 | 자동 선택 모델 |
|----------|----------------|
| 코드 작업 | Gemma4 (로컬·무료) + 코딩 스킬 자동 주입 |
| 의료 임상 질의 | DeepSeek-R1 (의료 전문) |
| 의료 영상 | Claude Opus |
| 복잡한 시스템 설계 | Gemma4 ×3 병렬 → Claude 종합 |
| 일반 질문 | Gemma4 (빠르고 무료) 또는 Claude Sonnet (복잡도 자동 판단) |

### 📑 논문 완벽 분석

```
quetta_analyze_paper(file_path="/data/paper.pdf")
```

자동으로:
- GPU 에이전트가 Nougat OCR로 수식·표 보존 추출
- Gemini로 그림·도표 시각 분석
- Claude가 한글 종합 리포트 작성
- 결과를 RAG에 영구 저장

이후:
```
quetta_paper_query(query="이 논문의 attention 수식")
```
저장된 논문에서 즉시 검색.

### 📐 설계도 분석 (기계/전기/CPLD)

```
quetta_analyze_blueprint(file_path="/data/cpld.pdf", drawing_type="cpld")
```

타입별 전문 프롬프트로 도면 해석 → 엔지니어링 리포트 자동 생성.

### 🚀 원격 GPU 사용

원격 PC에 한 번 에이전트를 설치하면, 어디서든 GPU를 사용할 수 있습니다.

```
quetta_gpu_status()                            # 모든 GPU 상태 한눈에
quetta_gpu_exec(command="python train.py")     # GPU에서 학습 실행
quetta_gpu_python(code="import torch; print(torch.cuda.get_device_name())")
```

원격 PC가 없으면 `quetta_remote_connect(action="install-link", os="windows")`로 한 줄 설치 링크를 받을 수 있습니다.

### 🔐 워크스페이스 (업무/개발 분리)

비개발자가 코드 관련 RAG 내용을 보지 못하도록 격리합니다.

```
quetta_workspace_list()                                   # 내 권한 확인
quetta_workspace_request(workspace="business")            # 권한 요청
```

기본 워크스페이스: `development` (개발), `business` (업무). 관리자가 추가 생성 가능.

### 🧠 공유 메모리

```
quetta_memory_save(text="중요한 사실...", tags=["profile"])
quetta_memory_recall(query="검색어")
quetta_memory_list()                  # 내 저장 목록
quetta_session_init()                 # 세션 시작 시 자동 호출 (CLAUDE.md가 자동 처리)
```

### 💾 대화 히스토리 자동 저장

모든 대화가 자동으로 NoSQL에 저장됩니다.

```
quetta_history_list()       # 내 세션 목록
quetta_history_get(session_id="...")
quetta_history_stats()      # 전체 통계
```

---

## 5. 멀티 계정 공유

다른 Claude Code 계정에서 같은 시스템을 사용하면, **별도 작업 없이 자동으로** 이전 기록을 이어 받습니다.

```
[계정 A]                              [계정 B - 다른 OS, 다른 계정]
  quetta_memory_save(...)             설치만 하면 끝
  quetta_ask(...)                     ↓
   ↓                                 새 세션 시작 시
   ↓                                 → 자동으로 quetta_session_init()
   ↓                                 → 계정 A의 메모리·논문·대화 모두 컨텍스트로 로드
   ↓                                 → 이어서 자연스럽게 작업
  공유 RAG 지식베이스
```

---

## 6. 자주 묻는 질문

### Q. 어떤 OS를 지원하나요?
- macOS, Linux, Windows 모두 동일 기능. 한 줄 설치 명령만 OS별로 다름.

### Q. 인터넷이 없으면?
- 게이트웨이 접속이 필요합니다. 로컬 게이트웨이 구성도 가능 (내부 사용용).

### Q. 비용은?
- 기본: Gemma4 / DeepSeek-R1은 로컬 무료. Claude는 기존 Claude Code 구독 활용 (별도 API 비용 없음). Gemini는 OAuth 무료 쿼터 1000회/일.
- 대용량 사용 시 Claude API 키 별도 설정 가능.

### Q. 데이터는 어디에 저장되나요?
- 게이트웨이 서버의 RAG 지식베이스 (벡터 DB) + MongoDB(대화 이력) + 파일 스토리지(업로드 파일).
- 사용자 식별은 API 키의 SHA-256 해시로만 — 원본 키 노출 없음.

### Q. 다른 사람이 내 메모리를 볼 수 있나요?
- 같은 워크스페이스에 접근 권한이 있는 사람만 볼 수 있습니다.
- 관리자(master 키 보유자)는 모든 워크스페이스 접근 가능.
- 개인 메모리는 별도 워크스페이스로 분리해 관리 가능.

### Q. GPU 에이전트를 끄면 어떻게 되나요?
- GPU가 필요한 작업은 실패 (설치 링크 자동 안내).
- 비-GPU 작업(질문, 메모리 조회 등)은 정상 동작.

### Q. Windows 재부팅 후 GPU 에이전트가 자동 시작되나요?
- `install-service.ps1` 실행하면 NSSM Windows Service로 등록 → 재부팅 후 로그인 없이도 자동 시작.

---

## 7. 자율연구시스템의 가치 (개념)

### 두 가지 연구 모드를 동시에

**도메인 연구** — 예: 96채널 SQUID 심자도 임상 연구. 5,620 recording, 2,649 피험자, 3개 병원 데이터를 시스템이 자율적으로 신호 품질 분석 → 전처리 → 분류기 학습 → 변동성 분석으로 처리.

**인프라 연구** — 시스템 자체의 개발도 동일 RAG에 기록되어, "이 기능은 왜 이렇게 설계됐나?"를 질의하면 실제 인시던트 보고서로 답변.

### 핵심 설계 철학

> **엔지니어링 지식 포착 비용은 엔지니어링 프로세스 자체가 지식 포착 시스템을 통해 흐를 때 0에 수렴한다.**

도메인 연구자와 시스템 개발자가 같은 게이트웨이, 같은 RAG, 같은 워크스페이스 분리 메커니즘을 공유하면서 - 워크스페이스 태그만 다르게 해서 - 두 영역 모두에서 작동합니다.

---

## 8. 더 알아보기

| 자료 | 링크 |
|------|------|
| 전체 문서 (PDF, 한글 + 영문) | [GitHub Releases](https://github.com/choyunsung/quetta-agents-mcp/blob/master/dist/quetta-agents-mcp-docs.pdf) |
| MCP 저장소 | https://github.com/choyunsung/quetta-agents-mcp |
| 게이트웨이 저장소 | https://github.com/choyunsung/quetta-agents |
| 학술 논문 (한글) | `docs/15-auto-research-system-paper-ko.md` |
| 학술 논문 (영문) | `docs/15-auto-research-system-paper.md` |

---

**문의**: GitHub Issues → https://github.com/choyunsung/quetta-agents-mcp/issues
