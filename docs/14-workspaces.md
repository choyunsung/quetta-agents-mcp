# 14. 워크스페이스 (멀티 테넌트)

업무용 / 개발용 지식을 분리해서 사용자별로 접근 권한을 제어하는 기능.

## 핵심 개념

```
[Admin (master API key)]  ─ 모든 워크스페이스 접근
    │
    │ ACL 관리
    ▼
[Workspace: development]  ← 기본 생성
[Workspace: business]     ← 기본 생성
[Workspace: project-X]    ← 관리자가 추가 가능
    │
    ▼
[사용자 A (api_key A)]  ← 관리자가 ["development"] 만 부여
[사용자 B (api_key B)]  ← 관리자가 ["business"] 만 부여
[사용자 C (api_key C)]  ← 관리자가 ["development", "business"] 둘 다 부여
```

## 왜 필요한가

- **비개발자 사용자**는 개발 관련 RAG 내용이 섞이면 혼란스러움
- **업무 기밀**은 개발자에게 불필요하고, 보안상 분리 필요
- 한 RAG 인스턴스에서 **네임스페이스로 격리**하면서도 **관리자는 전체 통합** 뷰 보유

## 자동 동작

| 호출 | 워크스페이스 동작 |
|------|-----------------|
| `quetta_ask(...)` | 사용자 허용 ws에서만 RAG 검색 (harness) |
| `quetta_ask(...)` 저장 | 사용자 기본 ws에 저장 (`X-Workspace` 헤더로 override 가능) |
| `quetta_memory_save(text="...")` | `workspace` 파라미터 또는 기본값 |
| Admin 호출 | 전체 ws 조회/저장 가능 |

## 기본 워크스페이스 (Gateway 최초 실행 시 생성)

| 이름 | 레이블 | 설명 |
|------|--------|------|
| `development` | 개발 지식 | 코드, 아키텍처, 기술 스택, 트러블슈팅 (기본) |
| `business` | 업무 지식 | 프로젝트 결정사항, 회의록, 일정 |

## 사용자 도구

### `quetta_workspace_list`
```python
quetta_workspace_list()
# → ## 내 워크스페이스 정보
#    - user_hash: abc1234567890def
#    - 관리자: ❌
#    - 기본 워크스페이스: development
#    - 접근 가능: ['development']
#
#    ### 전체 워크스페이스
#    - ✅ **development** (기본) — 개발 지식: 코드, 아키텍처, ...
#    - 🔒 **business** — 업무 지식: 프로젝트 결정사항, ...
```

### `quetta_workspace_request`
```python
quetta_workspace_request(workspace="business", reason="프로젝트 A 회의 참여")
# → ⏳ 요청 접수됨 — 관리자 승인 대기 중
```

### `quetta_memory_save` (workspace 지정)
```python
# 업무 메모 (해당 워크스페이스 권한 필요)
quetta_memory_save(
    text="2026-04-15 프로젝트 A 킥오프 미팅: 일정 결정됨 ...",
    workspace="business",
    tags=["meeting", "project-A"],
)

# 개발 메모 (기본)
quetta_memory_save(
    text="Gateway 502 원인: Ollama 바인딩 127.0.0.1 → 0.0.0.0",
    workspace="development",
    tags=["troubleshooting"],
)
```

## 관리자 도구 (master API key 필수)

### `quetta_admin_requests`
```python
quetta_admin_requests()
# → ## ⏳ 대기 중인 접근 요청 (2건)
#    - `abc1234567890def` → **business** (2026-04-13 15:30)
#      이유: 프로젝트 A 회의 참여
```

### `quetta_admin_resolve` (승인/거부)
```python
quetta_admin_resolve(
    user_hash="abc1234567890def",
    workspace="business",
    approve=True,
)
# → ✅ 승인됨
```

### `quetta_admin_grant` (일괄 ACL 설정)
```python
# 특정 사용자의 ACL 전체 교체
quetta_admin_grant(
    user_hash="abc1234567890def",
    workspaces=["development", "business"],  # 전체 허용
)
```

### `quetta_admin_create_workspace` (새 워크스페이스)
```python
quetta_admin_create_workspace(
    name="project-healthcare",
    label="헬스케어 프로젝트",
    description="의료 프로젝트 전용 지식베이스",
)
```

## 흐름 예시

### 시나리오 1: 비개발자 입사
1. Admin: `quetta_admin_create_workspace(name="ops", label="운영")`
2. 신입: Gist로 설치 → `quetta_workspace_request(workspace="ops")`
3. Admin: `quetta_admin_requests()` → 확인
4. Admin: `quetta_admin_resolve(user_hash="X", workspace="ops", approve=True)`
5. 이후 신입의 모든 `quetta_ask` 는 `ops` 워크스페이스에서만 검색/저장

### 시나리오 2: 권한 분리
- 개발자: `development` 만 부여
- 영업: `business` 만 부여
- PM: 두 워크스페이스 모두 부여

각자 quetta_ask 하면 자기 권한 내 데이터만 보임.

### 시나리오 3: Admin이 통합 조회
master API key 사용자는 `quetta_ask` 시 **전체** 워크스페이스에서 검색:
- `X-Workspace: development` 헤더 주면 해당 ws만 한정
- 헤더 없으면 전체 통합

## 저장 메타데이터

모든 RAG 청크에 `workspace` 필드 자동 추가:
```json
{
  "text": "...",
  "source": "quetta-gateway:business",
  "metadata": {
    "workspace": "business",
    "backend": "claude-sonnet",
    ...
  }
}
```

## REST API

| Method | Path | 권한 |
|--------|------|------|
| GET | `/workspace/me` | 누구나 (자기 정보) |
| POST | `/workspace/request` | 누구나 (자기 요청) |
| POST | `/workspace/create` | Admin |
| DELETE | `/workspace/{name}` | Admin |
| POST | `/workspace/acl/set` | Admin |
| GET | `/workspace/acl` | Admin |
| GET | `/workspace/requests?status=pending` | Admin |
| POST | `/workspace/resolve` | Admin |

## 관련 문서

- [공유 메모리](./11-shared-memory.md)
- [설치 시스템](./12-install-token.md)
- [대화 히스토리](./13-conversation-history.md)
