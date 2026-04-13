# 11. 공유 메모리 & 멀티 계정

Quetta MCP는 여러 Claude Code 계정이 **동일한 서버의 RAG 지식베이스**를 공유해 기억을 이어가도록 설계되어 있습니다.

## 핵심 개념

```
[계정 A]  ─┐
[계정 B]  ─┼──▶ [공유 Quetta Server] ──▶ [공유 RAG 지식베이스]
[계정 C]  ─┘
```

- 같은 `QUETTA_GATEWAY_URL` + (개인 혹은 공유) API 키를 사용하면 모든 계정이 같은 지식베이스에 접근
- 한 계정에서 저장한 기억은 다른 계정에서 즉시 검색·인용 가능
- 새 세션 시작 시 자동으로 기억이 컨텍스트에 주입됨

## 3가지 기억 레이어

### 1. 자동 Q&A 저장
- `quetta_ask`/`quetta_auto` 호출 시 Q&A가 자동으로 RAG에 저장됨
- 사용자가 별도 조치할 필요 없음
- source 태그: `quetta-gateway`

### 2. 자동 컨텍스트 주입
- 질문할 때마다 Gateway의 RAG harness가 관련 기억을 자동 검색해 LLM 입력에 삽입
- score ≥ 0.35 인 top 4개 청크를 system 메시지로 주입
- 질문·답변이 쌓일수록 컨텍스트 품질 향상

### 3. 명시적 사용자 메모리
| 도구 | 설명 |
|------|------|
| `quetta_memory_save(text, tags?)` | 고정 사실·선호·결정사항 영구 저장 |
| `quetta_memory_recall(query)` | 의미 검색 (LLM 답변 없이) |
| `quetta_memory_list()` | 내가 저장한 메모리 목록 |
| `quetta_session_init()` | 세션 시작 시 컨텍스트 프리앰블 생성 |

## 세션 자동 초기화

install.sh 가 `~/.claude/CLAUDE.md` 에 다음 지시를 **자동으로** 추가합니다:

```markdown
<!-- quetta-agents-mcp:auto-init BEGIN -->
## Quetta Agents MCP — 공유 메모리 자동 초기화

새 Claude Code 세션 시작 직후에 아래 도구를 한 번 호출하세요:
    quetta_session_init()

반환된 사용자 메모리 / 최근 맥락 / 활성 문서를 현재 대화의 배경 지식으로 반영합니다.
- 중요한 신규 정보는 quetta_memory_save(text=...) 로 공유 메모리에 저장하세요.
- 모든 quetta_ask / quetta_auto 호출은 Gateway RAG harness가 관련 메모리를 자동 주입합니다.
<!-- quetta-agents-mcp:auto-init END -->
```

→ Claude Code가 세션 시작 시 이 지시를 읽고 자동으로 공유 메모리 로드.

## 사용 예시

### 계정 A: 기억 저장
```python
quetta_memory_save(
    text="사용자는 MCG 연구자. KRISS 96채널 SQUID 시스템 사용. Python 3.11 + FastAPI 선호.",
    tags=["profile", "mcg"],
)
# 또는 자연어로:
quetta_auto(request="기억해줘: 이 프로젝트는 Python 3.11 + FastAPI 기반이다")
```

### 계정 B: 자동 복원
Claude Code 새 세션 → `quetta_session_init()` 자동 호출 →

```markdown
## 🎯 Quetta 세션 초기화 (공유 메모리 로드)

### 👤 사용자 메모리
- 사용자는 MCG 연구자. KRISS 96채널 SQUID 시스템 사용. Python 3.11 + FastAPI 선호. _[profile, mcg]_

### 💬 최근 대화 맥락
- Q: ECG ischemia 마커 AUC?  A: clin_score 0.929, ensemble_score 0.832...

### 📚 활성 문서
- [paper] attention.pdf
- [blueprint] cpld_top.pdf
```

이제 계정 B에서 별도 설명 없이 이어서 작업 가능.

## 자연어 단축 명령 (quetta_auto)

| 요청 | 자동 라우팅 |
|------|-------------|
| "기억해줘: X" | `quetta_memory_save(text="X")` |
| "전에 뭐였지?" | `quetta_memory_recall` |
| "내 기억 목록" | `quetta_memory_list` |
| "저장된 논문에서 찾아" | `quetta_paper_query` |

## 프라이버시 / 공유 범위

- **같은 API 키 사용 = 같은 지식베이스 공유**
- 개인 데이터가 팀에 공유되지 않기를 원하면 **개인 API 키** 발급 요청
- `quetta_memory_save` 시 `source` 파라미터로 네임스페이스 분리 가능

## 관련 문서

- [도구 레퍼런스](./08-tools-reference.md)
- [설치 & 설정](./09-configuration.md)
- [초대 토큰 설치 시스템](./12-install-token.md)
