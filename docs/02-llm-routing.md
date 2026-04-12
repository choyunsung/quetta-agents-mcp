# 02. LLM 라우팅

Quetta Gateway(`:8701`)는 OpenAI 호환 `/v1/chat/completions` 엔드포인트를 제공하면서 **자동으로 최적 LLM**을 선택합니다.

## 라우팅 엔진

| 질문 특성 | 선택 모델 | 이유 |
|----------|----------|------|
| 단순 질문, 짧은 프롬프트 | **Gemma4 (Ollama)** | 로컬·무료·빠름 |
| 코드 작업 | **Gemma4 + agent-skills** | 5가지 skill 자동 주입 |
| 의료 임상/진단 | **DeepSeek-R1** | 의학 추론 특화 |
| 의료 영상 (CT/MRI/X-ray) | **Claude Opus** | 비전 + 의학 |
| 복잡한 설계·아키텍처 | **SCION 멀티에이전트** | Gemma4 × 3 병렬 → Claude 종합 |
| 4000+ 토큰, 논리적 복잡도 높음 | **Claude Sonnet** | 정확도 |

## MCP 도구

### `quetta_ask` — 만능 진입점
```python
quetta_ask(query="React useEffect와 useLayoutEffect 차이?")
# → Gemma4 (일반 질문)

quetta_ask(query="복잡한 분산 시스템 설계...")
# → Claude Sonnet (복잡도 기준)
```

**옵션:**
- `model`: `"auto"` (기본), `"gemma4"`, `"local"`, `"claude"`, `"claude-opus"`
- `system_prompt`: 시스템 프롬프트 커스텀

### `quetta_code` — 코드 작업 특화
agent-skills 5종 자동 주입 (plan/build/test/review/document)

```python
quetta_code(
    task="이 함수를 TypeScript로 리팩토링",
    language="typescript",
    context="...원본 코드...",
)
```

### `quetta_medical` — 의료 전문
```python
quetta_medical(query="CRP 3.2, WBC 12000 패혈증 의심?")
quetta_medical(query="CT영상 분석", domain="imaging")  # Claude Opus
```

### `quetta_multi_agent` — 복잡 태스크
```python
quetta_multi_agent(task="ERP 마이크로서비스 아키텍처 설계")
# → Gemma4 × 3 에이전트 병렬 실행 → Claude 종합
```

### `quetta_routing_info` — 미리 보기
```python
quetta_routing_info(query="이 질문이 어디로 가는지 미리 알려줘")
# → 실제 호출 없이 라우팅 결정만 반환
```

## 응답 포맷

```json
{
  "choices": [{"message": {"content": "..."}}],
  "routing": {
    "backend": "ollama",
    "model": "gemma4:27b",
    "reason": "short query, no code complexity",
    "injected_skills": ["plan", "build"],
    "multi_agent": false,
    "is_medical": false
  }
}
```

MCP는 이 routing 정보를 응답 하단에 메타로 표시:
```
---
_[Quetta] 모델: ollama (gemma4:27b)  |  이유: short query  |  스킬: plan, build_
```

## 모델 별칭

| 요청 | 실제 백엔드 |
|------|------------|
| `"auto"` (기본) | 복잡도 기반 자동 |
| `"gemma4"` / `"local"` | Ollama gemma4:27b |
| `"claude"` / `"claude-sonnet"` | claude-sonnet-4-6 |
| `"claude-opus"` | claude-opus-4-6 |
| `"deepseek-r1"` | DeepSeek-R1 (의료) |

## 관련

- [스마트 디스패처](./03-smart-dispatcher.md) — 자연어 → 도구 자동 선택
- [도구 레퍼런스](./08-tools-reference.md)
