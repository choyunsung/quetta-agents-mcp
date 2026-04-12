# 05. 논문 분석 (Nougat + Gemini + Claude + RAG)

학술 논문 PDF를 **3단 AI 파이프라인**으로 완벽 분석하고, 결과를 RAG 지식베이스에 자동 저장해 이후 질의할 수 있게 합니다.

## 파이프라인

```
PDF 입력
   │
   ├─ 1. 파일 업로드 (대용량 지원, 재개 가능)
   │
   ├─ 2. Nougat OCR (GPU 가속)
   │    PDF → 수식·표·구조가 보존된 Markdown
   │
   ├─ 3. Gemini Vision
   │    Figure / Table / 수식 시각 해석
   │
   ├─ 4. Claude 종합
   │    Nougat + Gemini 통합 → 한글 엔지니어링 리포트
   │    (제목·저자·초록·방법·결과·한계)
   │
   └─ 5. 지식베이스 자동 저장
        섹션·청크 단위로 나누어 저장 → 이후 질의 시 자동 참조
```

## 도구

### `quetta_analyze_paper`

**입력:**
- `file_path` (string): 서버 로컬 PDF 경로 (또는 `file_id`)
- `file_id` (string): 이미 TUS 업로드된 PDF ID
- `query` (string, optional): 집중 분석할 초점
- `agent_id` (string, optional): 사용할 GPU 에이전트 (미지정 시 자동)
- `install_nougat` (bool, default=True): nougat 미설치 시 자동 설치
- `skip_gemini` (bool, default=False): Gemini 단계 건너뜀
- `skip_claude` (bool, default=False): Claude 종합 건너뜀
- `ingest_to_rag` (bool, default=True): RAG 자동 저장
- `tags` (array): RAG 메타 태그

**출력:**
- 진행 로그 (1/4 ~ 4/4)
- Claude 종합 리포트 (한글)
- RAG 인제스트 요약 (청크 수)
- 접을 수 있는 섹션:
  - Nougat 원본 추출 (처음 8000자)
  - Gemini 시각 분석 (처음 6000자)

### `quetta_paper_query`

**입력:**
- `query` (string): 논문 관련 질문
- `filename` (string, optional): 특정 논문만 필터
- `list` (bool, default=False): 질의 대신 목록만
- `top_k` (int, default=8): 참조할 청크 수

**출력:**
- RAG 검색 결과 기반 Claude 답변 (출처 인용)
- 목록 모드 시: 인제스트된 논문 이름/청크 수/file_id

## 사용 예시

### 기본 흐름

```python
# 1. 로컬 PDF 분석 + RAG 자동 저장
quetta_analyze_paper(file_path="/data/papers/attention.pdf")

# 결과 (요약):
# ## 📄 논문 분석 파이프라인
# **1/4**  파일 로드: attention.pdf (2,134,567 bytes)
# **2/4**  TUS 업로드 완료: a1b2c3d4
# **3/4**  GPU 에이전트 선택: 878047e4
#   → nougat 추출 완료: 45,231 chars
# **4/4**  Gemini CLI 분석 완료: 12,450 chars
#
# ---
#
# ## 🎯 종합 분석 (Claude)
# # Attention Is All You Need (Vaswani et al., 2017)
# ## 제목 / 저자 ...
# ## 초록 한글 요약 ...
# ## 핵심 기여 ...
# ...
#
# **RAG 인제스트 완료**
# - Source 태그: `paper:attention.pdf`
# - Nougat 본문 청크: 42개
# - Claude 종합: 1
# - Gemini 시각분석: 1
```

### 저장된 논문 질의

```python
# 인제스트된 논문 목록
quetta_paper_query(list=True)

# 특정 논문 내 질의 (filename 필터)
quetta_paper_query(
    query="scaled dot-product attention의 수식 유도",
    filename="attention.pdf",
)

# 전체 논문 대상 비교 질의
quetta_paper_query(query="어떤 논문들이 self-attention을 제안했나?")
```

### 자연어 디스패처 활용

```python
# 자동 라우팅
quetta_auto(request="이 논문 분석해줘", file_path="/data/paper.pdf")
# → paper_analysis 의도 감지 → quetta_analyze_paper

quetta_auto(request="저장된 논문에서 Transformer 비교해줘")
# → paper_query 의도 감지 → quetta_paper_query
```

### 옵션별 사용 시나리오

```python
# Gemini 건너뛰고 빠르게 (Nougat + Claude만)
quetta_analyze_paper(
    file_path="/data/paper.pdf",
    skip_gemini=True,
)

# Nougat 설치 생략 (이미 설치된 경우)
quetta_analyze_paper(
    file_path="/data/paper.pdf",
    install_nougat=False,
)

# 분석만 하고 RAG에 저장하지 않음 (1회성)
quetta_analyze_paper(
    file_path="/data/paper.pdf",
    ingest_to_rag=False,
)

# 특정 GPU 에이전트 지정
quetta_analyze_paper(
    file_path="/data/paper.pdf",
    agent_id="878047e4",
)

# 태그와 함께 저장
quetta_analyze_paper(
    file_path="/data/paper.pdf",
    tags=["transformer", "NLP", "2017", "required-reading"],
)
```

## 필요 환경

| 구성 요소 | 설치 | 비고 |
|----------|------|------|
| **GPU 에이전트** | `/remote-agent` 스킬로 설치 | Nougat는 torch + CUDA 필요 |
| **Nougat (choyunsung/nougat)** | 자동 설치 (`install_nougat=True`) | 첫 실행 시 최대 10분 소요 |
| **gemini CLI** | `npm i -g @google/gemini-cli` + `gemini` 로 OAuth 로그인 | 선택 (미설치 시 자동 건너뜀) |
| **Gateway `QUETTA_API_KEY`** | `.env` 에 설정 | 외부 접근 시 필수 |
| **RAG 서비스** | Quetta 서버에서 자동 실행 | `:8400` |

## 저장 구조

인제스트된 논문은 아래와 같이 구분되어 저장됩니다:

- **본문**: 섹션·청크 단위로 여러 개 저장
- **종합 리포트**: 1개 (Claude)
- **시각 분석**: 1개 (Gemini)

각각 `type=paper`, `filename`, `tags` 로 식별 가능해 이후 특정 논문/태그로 필터링된 검색이 가능합니다.

## 성능·비용

| 단계 | 소요 시간 | 비고 |
|------|----------|------|
| TUS 업로드 | 1–5초 | PDF 크기 의존 |
| Nougat (첫 실행) | +5–10분 | pip install + 모델 다운로드 |
| Nougat (2회차+) | 1–5분 | PDF 페이지 수 의존 (~10초/page) |
| Gemini 분석 | 30–90초 | PDF 크기 의존 |
| Claude 종합 | 10–30초 | 본문 길이 의존 |
| RAG 인제스트 | 5–15초 | 청크 수 의존 |

**전체 평균:** 3–10분 (첫 실행은 10–20분)

## 트러블슈팅

### "GPU 에이전트가 없음"
Claude Code 채팅에서 `/remote-agent` 실행 → GPU PC에 에이전트 설치 후 재시도.

### Gemini 건너뛰기 원할 때
```python
quetta_analyze_paper(file_path="...", skip_gemini=True)
```

### 자주 발생하는 문제
[10. 트러블슈팅](./10-operations.md) 참고.

## 관련 문서

- [원격 에이전트](./04-remote-agent.md)
- [설계도 분석](./06-blueprint-analysis.md)
- [파일 업로드 & RAG](./07-upload-rag.md)
