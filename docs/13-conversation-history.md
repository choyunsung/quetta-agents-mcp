# 13. 대화 히스토리 (NoSQL)

모든 `quetta_ask` / `quetta_auto` 호출이 자동으로 **MongoDB에 저장**됩니다. 계정별 누적 + 통합 조회 모두 지원.

## 아키텍처

```
Claude Code → quetta_ask / quetta_auto
            ↓
     Quetta Gateway /v1/chat/completions
            ├─ RAG harness (context injection)
            ├─ LLM 응답 생성
            ├─ save_qa  → RAG vector DB (검색용)
            └─ save_conversation → MongoDB (이력용) ← NEW
                                    │
                                    ▼
                          quetta_agents.conversations
                          (계정별 user_hash로 구분)
```

## 저장 데이터 구조

`quetta_agents.conversations` 컬렉션:

```javascript
{
  _id: ObjectId,
  session_id: "default",         // X-Session-Id 헤더 기반
  timestamp: 1776062400.123,
  user_hash: "a3f5b2c1...",      // SHA-256(API_KEY)[:16] — 계정 식별
  query: "사용자 질문",
  response: "LLM 답변",
  backend: "claude-sonnet",
  model: "claude-sonnet-4-6",
  rag_chunks: 4,
  tokens: { input: 150, output: 320 },
  routing: { reason, is_medical, inject_code_skills, multi_agent }
}
```

**인덱스:**
- `(session_id, timestamp)` — 세션별 시간순
- `(user_hash, timestamp DESC)` — 사용자별 최근순
- `(timestamp DESC)` — 전체 최근순

## 개인정보 보호

- API 키는 **SHA-256 해시**로만 저장 (역추적 불가)
- 같은 API 키 → 같은 `user_hash` → 동일 사용자로 그룹핑
- 다른 키 사용 시 다른 사용자로 분리

## MCP 도구

### `quetta_history_list`

| 파라미터 | 기본 | 설명 |
|---------|------|------|
| `mine_only` | true | 내 API 키 세션만 |
| `unified` | false | true면 모든 사용자 통합 |
| `limit` | 30 | 최대 반환 세션 수 |

### `quetta_history_get`

| 파라미터 | 설명 |
|---------|------|
| `session_id` | 조회할 세션 ID (필수) |
| `limit` | 기본 100 |

### `quetta_history_stats`
파라미터 없음 — 전체 통계 요약.

## 사용 예시

```python
# 내 대화 세션 목록
quetta_history_list()
# → ## 💬 대화 히스토리 (내 계정, 12개 세션)
#    - `default`  (47개 메시지, 04-10 09:22~04-13 08:51)
#      "ECG ischemia 마커..."
#    - `project-mcg`  (31개 메시지, ...)

# 전체 사용자 통합 조회
quetta_history_list(unified=True, limit=50)

# 특정 세션 상세
quetta_history_get(session_id="project-mcg")
# → ## 🗂 세션 project-mcg (31개 메시지)
#    ### 2026-04-12 15:30:00 [claude-sonnet]
#    Q: ...
#    A: ...

# 전체 통계
quetta_history_stats()
# → 총 대화 수: 1,247
#    고유 세션 수: 23
#    고유 사용자 수: 4
#    백엔드별: claude-sonnet 842 / gemma4 305 / deepseek-r1 100
```

## 세션 ID 지정

기본 세션 ID는 `default`입니다. 특정 주제별로 분리하려면 HTTP 요청에 `X-Session-Id` 헤더 포함:

```python
# MCP 차원에서 헤더 지정은 아직 미지원 — gateway 직접 호출 시만 가능
# 향후 quetta_ask 에 session_id 파라미터 추가 예정
```

## 계정별 vs 통합 조회

| 시나리오 | 호출 |
|---------|------|
| 내가 전에 뭘 물어봤지? | `quetta_history_list()` (mine_only=True, 기본) |
| 팀 전체 대화 흐름 | `quetta_history_list(unified=True)` |
| 특정 세션 되돌아보기 | `quetta_history_get(session_id="X")` |
| 전체 활동 요약 | `quetta_history_stats()` |

## 관리자 기능

### 세션 삭제
```bash
curl -X DELETE https://rag.quetta-soft.com/history/session/<SID> \
  -H "Authorization: Bearer <MASTER_API_KEY>"
```

### REST API
| Method | Path | Auth |
|--------|------|------|
| GET | `/history/sessions?limit=30&user_hash=X` | API key |
| GET | `/history/session/{sid}?limit=200` | API key |
| DELETE | `/history/session/{sid}` | Master key |
| GET | `/history/stats` | API key |

## 데이터 보관

- **백업 대상**: MongoDB `quetta_agents.conversations` 컬렉션
- **용량 예상**: 대화 1건 ≈ 5KB → 10만건 ≈ 500MB
- **정리 정책**: 수동 (기본은 무기한 보관). 필요 시 TTL 인덱스로 자동 삭제 가능
- **GDPR/개인정보**: `user_hash`는 해시이므로 API 키 자체가 삭제되면 재매칭 불가

## 관련 문서

- [공유 메모리](./11-shared-memory.md)
- [초대 토큰 설치](./12-install-token.md)
- [도구 레퍼런스](./08-tools-reference.md)
