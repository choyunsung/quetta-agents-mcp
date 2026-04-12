# 06. 설계도 분석 (기계 / 전기 / CPLD)

기계·전기·CPLD 설계도(PDF·PNG)를 **Gemini Vision + PyMuPDF + Claude**로 분석하고 RAG에 자동 저장합니다.

## 파이프라인

```
PDF/PNG 입력
   │
   ├─[1] 파일 로드 + 확장자 판별 (pdf/png/jpg)
   │     + TUS 업로드 (RAG 인제스트 연결용)
   │
   ├─[2] PDF면 PyMuPDF로 벡터 텍스트 추출
   │     - 주석, 치수, BOM, 기호, 핀맵 등
   │     - 이미지 파일이면 이 단계 생략
   │
   ├─[3] Gemini CLI Vision 분석 (타입별 전문 프롬프트)
   │     - mechanical / electrical / cpld / auto
   │     - @filepath 구문으로 PDF/PNG 직접 전달
   │
   ├─[4] Claude Sonnet 종합
   │     - 벡터 텍스트 + 시각 분석 통합
   │     - 엔지니어링 실무 리포트 생성
   │
   └─[5] RAG 자동 인제스트
         - type=blueprint, drawing_type=<type>
         - part=pdf_text / vision / synthesis
         - 이후 quetta_blueprint_query로 재질의
```

## 타입별 전문 프롬프트

### 기계 설계 (`mechanical`)

분석 항목:
1. 도면 종류 (조립도/부품도/단면도/상세도)
2. 주요 치수·공차·표면거칠기(Ra)·끼워맞춤 기호
3. 재질·열처리·표면처리 기재사항
4. 각 부품의 기능과 조립 관계
5. **GD&T 기호** 해석 — ⊥, ⌒, ◎, ⊕, ↕ 등
6. 제작/가공 시 주의사항 (가공 순서·기준면)
7. BOM(부품표) 항목별 정리

### 전기 설계 (`electrical`)

분석 항목:
1. 회로 종류 (배전/제어/PLC I/O/시퀀스/단선결선도)
2. 주요 소자 (차단기, 계전기, 인버터, PLC, 센서) 목록·정격
3. 전원 계통 (전압·상·주파수)과 결선
4. 신호 흐름 — 입력/출력/인터록·안전회로
5. 부하/모터 용량·보호장치 설정
6. 단자번호·와이어 번호 규칙
7. 안전 관련 (ESTOP, 접지, 절연) 확인

### CPLD / FPGA / 디지털 논리 (`cpld`)

분석 항목:
1. 설계 유형 (RTL 블록도/스키매틱/타이밍도/상태천이도/핀맵)
2. 주요 모듈·서브 블록과 기능
3. 신호 이름·비트폭·방향(input/output/inout)
4. 클럭·리셋 계통 (동기/비동기, 클럭 도메인)
5. **FSM** 상태와 전이 조건
6. 인터페이스 프로토콜 (I2C/SPI/UART/AXI 등)
7. 타이밍 제약 (setup/hold, tPD) 및 합성 가능 여부
8. 가능하면 **Verilog/VHDL 구조 유추**

### 자동 감지 (`auto`)

입력 도면의 종류를 먼저 판별한 뒤 해당 타입에 맞는 분석 수행.

## 도구

### `quetta_analyze_blueprint`

**입력:**
- `file_path` (string): 서버 로컬 PDF/PNG 경로
- `file_id` (string): 이미 TUS 업로드된 파일 ID
- `drawing_type` (enum): `mechanical` / `electrical` / `cpld` / `auto`
- `query` (string, optional): 집중 분석 포인트
- `tags` (array): RAG 메타 태그
- `ingest_to_rag` (bool, default=True): RAG 자동 저장
- `skip_gemini` (bool, default=False): Gemini 단계 생략 (Claude만)

**출력:**
- 진행 로그 (1/3 ~ 3/3)
- Claude 엔지니어링 리포트 (한글, 타입별 구조화)
- RAG 인제스트 요약
- 접을 수 있는 섹션:
  - Gemini 시각 분석 원본 (8000자)
  - PDF 벡터 텍스트 (6000자)

### `quetta_blueprint_query`

**입력:**
- `query` (string): 질문
- `filename` (string, optional): 특정 도면만
- `drawing_type` (string, optional): 특정 타입만 (`mechanical` 등)
- `list` (bool, default=False): 목록 모드
- `top_k` (int, default=8): 참조 청크 수

**출력:**
- RAG 검색 기반 Claude 답변 (치수/부품번호 원문 인용)

## 사용 예시

### 기본 분석

```python
# 기계 설계도 분석
quetta_analyze_blueprint(
    file_path="/data/drawings/gear_assembly.pdf",
    drawing_type="mechanical",
    tags=["gearbox", "v2.0"],
)

# 전기 단선결선도
quetta_analyze_blueprint(
    file_path="/data/drawings/power_dist.pdf",
    drawing_type="electrical",
)

# CPLD 스키매틱
quetta_analyze_blueprint(
    file_path="/data/drawings/cpld_top.pdf",
    drawing_type="cpld",
    query="FSM 상태와 전이 조건을 Verilog로 유추해줘",
)

# 자동 감지
quetta_analyze_blueprint(file_path="/data/drawings/unknown.png")

# PNG 이미지 도면
quetta_analyze_blueprint(
    file_path="/data/drawings/schematic.png",
    drawing_type="electrical",
)
```

### 자연어 디스패처

```python
# 자동 라우팅 + 타입 추정
quetta_auto(request="이 CPLD 설계도 해석", file_path="/data/cpld.pdf")
# → blueprint_analysis, drawing_type=cpld 자동 선택

quetta_auto(request="기계 조립도 GD&T 분석", file_path="/data/asm.pdf")
# → blueprint_analysis, drawing_type=mechanical

quetta_auto(request="저장된 설계도에서 모터 회로 찾아줘")
# → blueprint_query
```

### 저장된 설계도 질의

```python
# 목록
quetta_blueprint_query(list=True)
# → ## 인제스트된 설계도 (3개)
#    - gear_assembly.pdf [mechanical] 청크 5개, file_id: abc123
#    - power_dist.pdf    [electrical] 청크 3개, file_id: def456
#    - cpld_top.pdf      [cpld]       청크 4개, file_id: ghi789

# 특정 도면
quetta_blueprint_query(
    query="M8 볼트 개수와 체결 토크",
    filename="gear_assembly.pdf",
)

# 특정 타입만
quetta_blueprint_query(
    query="FSM 리셋 조건",
    drawing_type="cpld",
)

# 전체 대상
quetta_blueprint_query(query="ESTOP 회로가 있는 도면?")
```

## 출력 예시 (실제)

```markdown
## 📐 설계도 분석 파이프라인 (drawing_type: cpld)

**1/3**  파일: cpld_top.pdf (456,789 bytes)
  → TUS 업로드: abc123xyz
**2/3**  PDF 텍스트 추출: 3,421 chars
**3/3**  Gemini 시각 분석: 8,945 chars

---

## 🔧 엔지니어링 분석 리포트 (cpld)

### 1. 도면 개요
- 제목: CPLD TOP LEVEL SCHEMATIC
- 도면번호: DSGN-2026-04-12
- 축척: N/A (논리 스키매틱)

### 2. 종류와 용도
RTL 블록도 — I/O 제어용 CPLD (Xilinx XC9572XL-10VQG64C)
... (중략)

### 3. 핵심 사양
| 항목 | 값 |
|------|-----|
| 클럭 | 25 MHz (CLK_MAIN), 1 MHz (CLK_SPI) |
| I/O | 48 (34 available) |
| 전압 | 3.3V I/O, 3.3V core |

### 4. 부품/블록 리스트
| 이름 | 역할 | 포트 |
|------|------|------|
| U1   | CPLD (XC9572XL) | 64pin VQFP |
| Y1   | 25MHz OSC      | → CLK_MAIN |
...

### 5. 신호 흐름
- CLK_MAIN → PLL_DIV → {CLK_25, CLK_5}
- RST_N (비동기) → sync_reset_module → RST_SYNC
- SPI_CS ↔ spi_slave module (state=IDLE→CMD→ADDR→DATA)
...

**RAG 인제스트 완료** (source: `blueprint:cpld_top.pdf`)
- 벡터 텍스트 청크: 2개
- Gemini 시각 분석: 1
- Claude 종합: 1
```

## 저장 구조

- **PDF 텍스트**: 청크 단위 (여러 개)
- **시각 분석**: 1개 (Gemini)
- **종합 리포트**: 1개 (Claude)

각각 `type=blueprint`, `drawing_type` (mechanical/electrical/cpld), `filename`, `tags` 로 식별되어 이후 필터 검색이 가능합니다.

## 필요 환경

| 구성 요소 | 설치 | 비고 |
|----------|------|------|
| **PyMuPDF** | 자동 설치 (pip `pymupdf>=1.24`) | MCP dependency |
| **gemini CLI** | `npm i -g @google/gemini-cli` + OAuth | 미설치 시 Claude만 |
| **Gateway `QUETTA_API_KEY`** | `.env` 설정 | 외부 접근 시 필수 |

**GPU 에이전트 불필요** — 논문 분석과 달리 Nougat를 사용하지 않습니다.

## 지원 파일 형식

| 확장자 | 지원 | 비고 |
|--------|------|------|
| `.pdf` | ✅ | 벡터 텍스트 + Vision |
| `.png` | ✅ | Vision만 |
| `.jpg`/`.jpeg` | ✅ | Vision만 |
| `.dwg`/`.dxf` | ❌ | 별도 변환 필요 (ezdxf) — 추후 추가 예정 |
| `.svg` | ❌ | 추후 추가 예정 |

## 성능

| 작업 | 시간 |
|------|------|
| PDF 텍스트 추출 | <1초 |
| Gemini 시각 분석 | 20–60초 |
| Claude 종합 | 10–30초 |
| RAG 인제스트 | 2–5초 |
| **전체** | **30–90초** |

## 타입 추정 로직 (`quetta_auto`)

자연어 요청에서 `drawing_type` 자동 판단:
- `cpld`, `fpga`, `pcb`, `verilog`, `vhdl`, `rtl` → `cpld`
- `전기`, `회로도`, `결선`, `plc`, `배전`, `control` → `electrical`
- `기계`, `gd&t`, `조립`, `부품도`, `공차`, `치수` → `mechanical`
- 매칭 없음 → `auto`

## 트러블슈팅

### "지원하지 않는 형식"
PDF / PNG / JPG 만 지원됩니다. DWG/DXF 는 사전에 PDF/PNG 로 변환 필요.

### "PDF 텍스트 없음 (이미지 도면으로 처리)"
스캔본 PDF인 경우 정상 동작입니다 — Gemini Vision 만으로도 상세 분석이 이루어집니다.

자세한 내용은 [10. 트러블슈팅](./10-operations.md) 참고.

## 확장 계획

- [ ] `.dwg`/`.dxf` 지원 (ezdxf로 벡터 추출)
- [ ] 대형 A0 도면 자동 타일링 (OpenCV)
- [ ] 회로도 → Verilog 자동 코드 생성 (CPLD)
- [ ] P&ID (공정배관계장도) 특화 프롬프트
- [ ] BOM CSV 자동 추출

## 관련 문서

- [논문 분석](./05-paper-analysis.md)
- [파일 업로드 & RAG](./07-upload-rag.md)
