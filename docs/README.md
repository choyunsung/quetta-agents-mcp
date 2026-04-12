# Quetta Agents MCP — 상세 문서

Quetta Agents MCP는 **LLM 스마트 라우팅 + 원격 PC(GPU) 제어 + 문서/도면 분석 + RAG 지식베이스**를 하나의 MCP로 통합한 시스템입니다.

## 📚 문서 목차

1. [아키텍처 개요](./01-architecture.md) — 시스템 구성도, 데이터 흐름, 컴포넌트 관계
2. [LLM 라우팅](./02-llm-routing.md) — `quetta_ask/code/medical/multi_agent`
3. [스마트 디스패처](./03-smart-dispatcher.md) — `quetta_auto` 의도 분류
4. [원격 에이전트](./04-remote-agent.md) — WebSocket 릴레이, GPU 자동 라우팅
5. [논문 분석](./05-paper-analysis.md) — Nougat + Gemini + Claude + RAG
6. [설계도 분석](./06-blueprint-analysis.md) — 기계/전기/CPLD PDF·PNG + RAG
7. [파일 업로드 & RAG](./07-upload-rag.md) — TUS + 파일 유형 감지 + 인제스트
8. [도구 레퍼런스](./08-tools-reference.md) — 전체 도구 상세 파라미터
9. [환경변수 & 설정](./09-configuration.md) — env 변수, 설치, 업데이트
10. [운영 가이드](./10-operations.md) — 로그, 트러블슈팅, 모니터링

---

## 빠른 시작

```bash
# 1. 설치 (Mac/Linux 공통)
QUETTA_GATEWAY_URL=https://rag.quetta-soft.com \
QUETTA_API_KEY=your_api_key \
bash <(curl -fsSL https://raw.githubusercontent.com/choyunsung/quetta-agents-mcp/master/install.sh)

# 2. Claude Code 재시작

# 3. 사용
quetta_auto(request="이 논문 분석해줘", file_path="/data/paper.pdf")
quetta_auto(request="CPLD 설계도 해석", file_path="/data/cpld.pdf")
quetta_gpu_status()
```

---

## 전체 기능 맵

```
┌────────────────────────────────────────────────────────────────┐
│                      Quetta Agents MCP                         │
└────────────────────────────────────────────────────────────────┘
                            │
    ┌───────────────────────┼───────────────────────┐
    │                       │                       │
    ▼                       ▼                       ▼
┌────────┐           ┌────────────┐          ┌──────────────┐
│ LLM    │           │ Remote     │          │ Document     │
│ Gateway│           │ Agent      │          │ Analysis     │
└────────┘           └────────────┘          └──────────────┘
    │                       │                       │
    ├─ quetta_ask            ├─ install-link         ├─ paper (Nougat+Gemini+Claude)
    ├─ quetta_code            ├─ screenshot          ├─ blueprint (Gemini+Claude)
    ├─ quetta_medical         ├─ click/type/key      ├─ file_analysis (type-aware)
    ├─ quetta_multi_agent     ├─ shell (GPU auto)    ├─ auto RAG ingest
    └─ quetta_routing_info    ├─ gpu_exec/python     └─ upload_* (TUS)
                              └─ gpu_status

          ▲                                           │
          │                                           │
          └──────── quetta_auto (의도 자동 분류) ─────┘
                            │
                            ▼
                    ┌───────────────┐
                    │   RAG Store   │
                    │ (type=paper,  │
                    │  blueprint,   │
                    │  document,…)  │
                    └───────────────┘
                            │
                ┌───────────┴──────────┐
                ▼                      ▼
        quetta_paper_query    quetta_blueprint_query
```

---

## 버전

현재: **v0.11.0** (2026-04)

변경 이력은 [../README.md](../README.md)의 변경 이력 섹션 참고.

---

## 라이선스 & 링크

- Repository: https://github.com/choyunsung/quetta-agents-mcp
- Gateway: https://github.com/choyunsung/quetta-agents
