# 07. 파일 업로드 & RAG 통합

대용량 파일 업로드 (TUS) + 유형 자동 감지 + RAG 지식베이스 인제스트.

## 데이터 흐름

```
로컬 파일
   │
   ├─[1] quetta_upload_file
   │     ├─ TUS 프로토콜로 tusd에 청크 업로드
   │     └─ file_id 반환
   │
   ├─[2] quetta_analyze_file (자동 유형 감지)
   │     ├─ RAG /upload/analyze/{file_id}
   │     ├─ 유형 분기:
   │     │     - medical → DeepSeek-R1 분석
   │     │     - signal_data → Gemma4 분석
   │     │     - document → Gemma4 요약
   │     └─ 자동 RAG 인제스트
   │
   ├─[3] quetta_upload_process (수동 인제스트)
   │     ├─ RAG /upload/process/{file_id}
   │     └─ usage_type 명시 지정
   │
   └─[4] quetta_upload_process_all
         └─ 미처리 파일 일괄 인제스트
```

## 유형 자동 감지

RAG 서비스가 파일명·내용 기반으로 판별:

| 유형 | 감지 기준 | 처리 |
|------|----------|------|
| `medical` | 의료 키워드 ≥2개 (환자/진단/ICD/FHIR 등) | medical 네임스페이스 + DeepSeek-R1 |
| `signal_data` | EDF/DAT/MAT/HDF5 확장자, ECG/BPM 헤더 | signal_data 네임스페이스 |
| `document` | PDF/DOCX/TXT 등 | documents 네임스페이스 |

## 도구

### `quetta_upload_file`
```python
# 로컬 파일
quetta_upload_file(file_path="/data/report.pdf")
# → file_id: abc123, size: 2MB

# 텍스트 직접
quetta_upload_file(
    content="환자 65세 남성, CRP 3.2...",
    filename="case.txt",
)
```

### `quetta_upload_list`
```python
quetta_upload_list()
# → **업로드된 파일 목록** (12개)
#    - `abc123` — report.pdf
#      크기: 2,345,678 bytes | 상태: 완료
#    ...
```

### `quetta_upload_process`
```python
quetta_upload_process(
    file_id="abc123",
    usage_type="measurement_data",  # 또는 medical/document
    source="실험1 결과",
    tags=["v2.0"],
    chunk_size=4000,
)
```

### `quetta_upload_process_all`
```python
quetta_upload_process_all()
# 미처리 파일 전체 자동 인제스트
```

### `quetta_analyze_file` (올인원)
업로드 + 유형 감지 + RAG + AI 분석을 한 번에:
```python
quetta_analyze_file(file_path="/data/patient.csv")

# 결과:
# **파일 유형:** medical (환자, ICD 등 5개 키워드 매칭)
# **저장 경로:** /storage/uploads/tusd/abc123
# **RAG 인제스트:** 8개 청크
#
# ## 🩺 의료 데이터 분석 (DeepSeek-R1)
# ...
```

## 저장 구조

모든 인제스트는 공통 분류 체계를 가집니다:

- `type`: `paper` / `blueprint` / `medical` / `document` / `signal_data`
- `filename`: 원본 파일명
- `tags`: 사용자 지정 태그 (검색용)
- `part`: 내용 종류 (본문 / 종합 / 시각 분석)

이 메타데이터 덕분에 이후 `quetta_paper_query`, `quetta_blueprint_query` 등으로 **특정 파일·타입·태그** 필터 검색이 가능합니다.

## 질의 계층

| 도구 | 용도 |
|------|------|
| `quetta_paper_query` | `type=paper` 필터 |
| `quetta_blueprint_query` | `type=blueprint` 필터 |
| `quetta_ask` | RAG harness (gateway 내부 통합) — 전체 검색 |

**Gateway RAG Harness:**
`quetta_ask`는 gateway의 RAG harness를 통해 답변에 RAG 컨텍스트를 자동 주입합니다 (필요 시). 즉 논문·도면 인제스트만으로도 `quetta_ask("X 논문의 Y는?")`로 답변 가능.

## 대용량 파일 업로드

업로드는 **재개 가능한 프로토콜**로 처리됩니다:
- 네트워크 중단 시 중단 지점부터 이어서 업로드
- 수 GB 파일도 안정적으로 전송
- 클라이언트에서 내부적으로 자동 처리 — 사용자는 `quetta_upload_file` 만 호출하면 됨

## 트러블슈팅

자주 발생하는 문제는 [10. 트러블슈팅](./10-operations.md) 참고.

## 관련 문서

- [논문 분석](./05-paper-analysis.md)
- [설계도 분석](./06-blueprint-analysis.md)
- [도구 레퍼런스](./08-tools-reference.md)
