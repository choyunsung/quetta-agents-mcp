# 03. 스마트 디스패처 (`quetta_auto`)

사용자의 자연어 요청을 **의도 분류**해 자동으로 적절한 도구로 라우팅합니다.

## 개념

```
User: "이 CPLD 도면 분석" + file_path
        │
        ▼
[quetta_auto] ─ 키워드 매칭 → intent=blueprint_analysis
        │
        ▼
     call_tool("quetta_analyze_blueprint", args)
        │
        ▼
     (pipeline execution)
```

## 의도 분류 (우선순위 순)

| 의도 | 키워드 예시 | 라우팅 |
|------|-----------|-------|
| **blueprint_query** | "저장된 설계도", "인제스트된 도면" | `quetta_blueprint_query` |
| **blueprint_analysis** | "설계도", "도면", "blueprint", "cpld", "회로도" | `quetta_analyze_blueprint` |
| **paper_query** | "저장된 논문", "분석된 논문에서" | `quetta_paper_query` |
| **paper_analysis** | "논문 분석", ".pdf", "arxiv", "학술" | `quetta_analyze_paper` |
| **gpu_compute** | "cuda", "torch", "nvidia-smi", "train.py" | `quetta_gpu_exec` |
| **screenshot** | "스크린샷", "화면 캡처" | `quetta_remote_screenshot` |
| **remote_shell** | "원격 명령", "원격 셸", "원격 실행" | `quetta_remote_shell` |
| **file_analysis** | "파일 분석", "의료 데이터", ".csv" | `quetta_analyze_file` |
| **medical** | "진단", "증상", "ICD", "환자" | `quetta_medical` |
| **code** | "리팩토링", "버그 수정", "코드 작성" | `quetta_code` |
| **multi_agent** | "설계", "아키텍처", "복잡한" | `quetta_multi_agent` |
| **question** (기본값) | 그 외 | `quetta_ask` |

## 파라미터

```python
quetta_auto(
    request="자연어 요청",   # 필수
    agent_id="",            # 선택 - GPU/remote 의도 시 특정 에이전트
    file_path="",           # 선택 - file_analysis/paper/blueprint 의도 시
    dry_run=False,          # true면 실행 없이 분류 결과만
)
```

## 사용 예시

```python
# 논문
quetta_auto(request="이 논문 분석해줘", file_path="/data/paper.pdf")

# 설계도 (타입 자동 추정)
quetta_auto(request="전기 결선도 해석", file_path="/data/power.pdf")
# → blueprint_analysis, drawing_type=electrical

quetta_auto(request="CPLD 스키매틱 분석", file_path="/data/cpld.pdf")
# → blueprint_analysis, drawing_type=cpld

# GPU 작업
quetta_auto(request="nvidia-smi 상태")
quetta_auto(request="python train.py --epochs 100")

# 원격 제어
quetta_auto(request="화면 보여줘")

# 의료
quetta_auto(request="CRP 3.2 의미")

# 저장된 자료 질의
quetta_auto(request="저장된 논문에서 attention 비교")
quetta_auto(request="인제스트된 설계도 목록")

# 분류 확인만
quetta_auto(request="이게 뭐로 갈까?", dry_run=True)
# → **[quetta_auto]** 의도: `question`
```

## 한국어/영어 혼용

키워드는 한글·영문을 모두 포함합니다:
- `"논문 분석"` / `"paper analysis"` → paper_analysis
- `"설계도"` / `"blueprint"` / `"schematic"` → blueprint_analysis
- `"코드 리뷰"` / `"refactor"` → code

## 코드 블록 추출

백틱으로 감싼 명령어/코드는 자동 추출됩니다:
```python
quetta_auto(request="이거 GPU에서 실행: `python -c 'import torch; print(torch.cuda.is_available())'`")
# → gpu_compute → quetta_gpu_exec(command="python -c 'import torch; print(torch.cuda.is_available())'")
```

## 응답 형식

```
**[quetta_auto]** 의도: `blueprint_analysis`  |  매칭: `설계도, cpld`

(하위 도구 실행 결과)
```

dry_run:
```
**[quetta_auto]** 의도: `paper_analysis`  |  매칭: `논문 분석, .pdf`

_(dry_run — 실행 생략)_
```
