"""
Quetta Agents MCP Server

Claude 채팅 중 자동으로 최적 모델을 선택해 질문을 처리합니다:
- 의료 질문 → DeepSeek-R1 (임상/진단) 또는 Claude Opus (영상)
- 코드 작업 → Gemma4 + agent-skills 자동 주입
- 복잡한 멀티스텝 → SCION 병렬 멀티에이전트
- 단순 질문 → Gemma4 (로컬·무료)

Tools:
  quetta_ask              - 질문을 보내면 최적 모델이 자동으로 응답
  quetta_code             - 코드 개발 작업 (agent-skills 5종 자동 주입)
  quetta_medical          - 의료 전문 질의 (DeepSeek-R1 임상 추론)
  quetta_multi_agent      - 복잡한 멀티스텝 태스크 (SCION 병렬 실행)
  quetta_routing_info     - 요청이 어떤 모델로 라우팅될지 설명
  quetta_list_agents      - 등록된 전문 에이전트 목록
  quetta_run_agent        - 특정 에이전트에게 태스크 위임
  quetta_remote_connect   - 원격 에이전트 연결 확인 (설치 링크 제공)
  quetta_remote_screenshot - 원격 PC 화면 캡처
  quetta_remote_click     - 원격 PC 마우스 클릭
  quetta_remote_type      - 원격 PC 텍스트 입력
  quetta_remote_key       - 원격 PC 단축키 입력
  quetta_remote_shell     - 원격 PC 셸 명령어 실행
  quetta_analyze_file     - 파일 업로드 → 유형 자동 감지 → RAG 인제스트 → AI 분석 (의료/신호/문서)
  quetta_upload_file      - 파일 또는 텍스트를 서버에 업로드 (TUS 프로토콜)
  quetta_upload_list      - 업로드된 파일 목록 조회
  quetta_upload_process   - 업로드된 파일을 RAG에 인제스트
  quetta_upload_process_all - 미처리 파일 전체 RAG 인제스트
  quetta_version          - 현재 버전 및 GitHub 최신 커밋 확인
  quetta_update           - GitHub 최신 버전으로 자동 업데이트
"""

import asyncio
import base64
import json
import logging
import os
import subprocess
import sys
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
    ImageContent,
    CallToolResult,
)

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
logger = logging.getLogger(__name__)

VERSION          = "0.14.1"
REPO_SSH         = "git+ssh://git@github.com/choyunsung/quetta-agents-mcp"
REPO_HTTPS       = "git+https://github.com/choyunsung/quetta-agents-mcp"

GATEWAY_URL      = os.getenv("QUETTA_GATEWAY_URL",      "http://localhost:8701")
ORCHESTRATOR_URL = os.getenv("QUETTA_ORCHESTRATOR_URL", "http://localhost:8700")
TIMEOUT          = float(os.getenv("QUETTA_TIMEOUT",    "300"))
GATEWAY_API_KEY  = os.getenv("QUETTA_API_KEY", "")   # Set for external access

# 대용량 파일 업로드 (tusd TUS 프로토콜 + RAG 인제스트)
TUSD_URL         = os.getenv("QUETTA_TUSD_URL",   "http://localhost:1080")   # tusd
RAG_URL          = os.getenv("QUETTA_RAG_URL",    "http://localhost:8400")   # RAG API
TUSD_TOKEN       = os.getenv("QUETTA_TUSD_TOKEN", "")                        # X-API-Token for tusd
RAG_KEY          = os.getenv("QUETTA_RAG_KEY",    "rag-claude-key-2026")     # X-API-Key for RAG

# 원격 에이전트 (릴레이 방식 — 에이전트가 게이트웨이에 역방향 WebSocket 연결)
# QUETTA_REMOTE_AGENT_ID: 연결된 에이전트 ID (quetta_remote_connect 로 확인)
REMOTE_AGENT_ID = os.getenv("QUETTA_REMOTE_AGENT_ID", "")

# 논문 분석 (Nougat + Gemini Vision)
GEMINI_CLI      = os.getenv("GEMINI_CLI",      "gemini")                        # Gemini CLI path
GEMINI_MODEL    = os.getenv("GEMINI_MODEL",    "gemini-2.5-pro")                # CLI 기본 모델
NOUGAT_REPO     = os.getenv("NOUGAT_REPO",     "git+https://github.com/choyunsung/nougat")

server = Server("quetta-agents")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _auth_headers() -> dict:
    """Return auth headers if API key is configured."""
    if GATEWAY_API_KEY:
        return {"Authorization": f"Bearer {GATEWAY_API_KEY}"}
    return {}


async def _relay(agent_id: str, cmd_type: str, payload: dict = {}, timeout: float = 120) -> dict:
    """게이트웨이 릴레이를 통해 원격 에이전트에 명령 전송."""
    async with httpx.AsyncClient(timeout=timeout + 5) as client:
        resp = await client.post(
            f"{GATEWAY_URL}/agent/{agent_id}/cmd",
            json={"type": cmd_type, "payload": payload},
            headers=_auth_headers(),
            params={"timeout": timeout},
        )
        resp.raise_for_status()
        return resp.json()


async def _relay_get(path: str) -> Any:
    """게이트웨이 릴레이 REST GET."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{GATEWAY_URL}{path}",
            headers=_auth_headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def _relay_post_raw(path: str, body: dict) -> Any:
    """게이트웨이 릴레이 REST POST."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{GATEWAY_URL}{path}",
            json=body,
            headers=_auth_headers(),
        )
        resp.raise_for_status()
        return resp.json()


def _active_agent_id(arguments: dict) -> str:
    """인수 또는 환경변수에서 agent_id 반환. 없으면 예외."""
    aid = arguments.get("agent_id", "").strip() or REMOTE_AGENT_ID
    if not aid:
        raise ValueError(
            "agent_id 가 지정되지 않았습니다.\n"
            "`quetta_remote_connect` 를 먼저 실행해 연결된 에이전트 ID를 확인하세요."
        )
    return aid


# GPU 감지 키워드 (명령어에 포함되면 GPU 에이전트로 자동 라우팅)
_GPU_KEYWORDS = (
    "nvidia-smi", "cuda", "torch", "tensorflow", "tf.", "cupy",
    "jax.", "transformers", "accelerate", "deepspeed", "vllm",
    "ollama run", "llama.cpp", "onnxruntime-gpu", "mmdet", "yolov",
    "train.py", "inference.py", "finetune", "sd-webui", "comfyui",
    "whisper", "diffusers", "stable-diffusion",
)


def _needs_gpu(command: str) -> bool:
    """명령어가 GPU 작업인지 추정."""
    low = command.lower()
    return any(kw in low for kw in _GPU_KEYWORDS)


def _agent_has_gpu(agent: dict) -> bool:
    """에이전트가 실제 GPU를 보유했는지 판별."""
    gpu = (agent.get("gpu") or "").strip().lower()
    if not gpu:
        return False
    # "없음 (CPU only)", "none", "cpu only" 제외
    return not any(x in gpu for x in ("없음", "cpu only", "없 ", "none"))


async def _find_gpu_agent() -> dict | None:
    """연결된 에이전트 중 GPU 보유 에이전트 1개 선택 (가장 오래 연결된 것)."""
    try:
        agents = await _relay_get("/agent/agents")
    except Exception:
        return None
    gpu_agents = [a for a in agents if _agent_has_gpu(a)]
    if not gpu_agents:
        return None
    # 가장 오래 연결된 (안정적인) 에이전트 우선
    gpu_agents.sort(key=lambda a: -a.get("connected_sec", 0))
    return gpu_agents[0]


async def _pick_agent(arguments: dict, prefer_gpu: bool = False) -> str:
    """에이전트 ID 선택. prefer_gpu=True면 자동으로 GPU 에이전트 선택.

    우선순위:
      1. arguments.agent_id (명시적 지정)
      2. prefer_gpu=True 또는 명령어에 GPU 키워드가 있으면 GPU 에이전트 자동 선택
      3. REMOTE_AGENT_ID 환경변수
      4. 예외
    """
    aid = arguments.get("agent_id", "").strip()
    if aid:
        return aid

    auto_gpu = prefer_gpu or _needs_gpu(arguments.get("command", ""))
    if auto_gpu:
        gpu_agent = await _find_gpu_agent()
        if gpu_agent:
            return gpu_agent["id"]
        # GPU 요구인데 GPU 에이전트가 없음 → 설치 링크 유도
        try:
            link = await _relay_get("/agent/install-link?os=linux")
            url = link.get("url", "")
        except Exception:
            url = ""
        raise ValueError(
            "GPU가 필요한 작업이지만 연결된 GPU 에이전트가 없습니다.\n"
            + (f"설치 링크: {url}\n" if url else "")
            + "원격 PC에서 설치 후 재시도하세요 (`quetta_remote_connect` 로 상태 확인)."
        )

    if REMOTE_AGENT_ID:
        return REMOTE_AGENT_ID

    # 연결된 에이전트가 1개뿐이면 자동 선택
    try:
        agents = await _relay_get("/agent/agents")
    except Exception:
        agents = []
    if len(agents) == 1:
        return agents[0]["id"]

    raise ValueError(
        "agent_id 가 지정되지 않았습니다.\n"
        "`quetta_remote_connect` 를 먼저 실행해 연결된 에이전트 ID를 확인하세요."
    )


def _rag_headers() -> dict:
    """Return RAG API auth headers."""
    return {"X-API-Key": RAG_KEY}


def _tusd_headers() -> dict:
    """Return tusd X-API-Token header if set."""
    if TUSD_TOKEN:
        return {"X-API-Token": TUSD_TOKEN}
    return {}


async def _tus_upload(filename: str, content: bytes) -> str:
    """Upload content via TUS protocol to tusd. Returns file ID."""
    upload_length = len(content)
    metadata_filename = base64.b64encode(filename.encode()).decode()

    tusd_base = TUSD_URL.rstrip("/")

    create_headers = {
        "Tus-Resumable": "1.0.0",
        "Upload-Length": str(upload_length),
        "Upload-Metadata": f"filename {metadata_filename}",
        "Content-Length": "0",
    }
    create_headers.update(_tusd_headers())

    async with httpx.AsyncClient(timeout=600) as client:
        # Step 1: Create upload slot
        resp = await client.post(f"{tusd_base}/files/", headers=create_headers)
        resp.raise_for_status()
        location = resp.headers.get("Location", "")
        if not location:
            raise ValueError("tusd: Location 헤더가 없습니다")

        # Step 2: Upload content
        patch_headers = {
            "Tus-Resumable": "1.0.0",
            "Content-Type": "application/offset+octet-stream",
            "Upload-Offset": "0",
            "Content-Length": str(upload_length),
        }
        patch_headers.update(_tusd_headers())

        resp = await client.patch(location, content=content, headers=patch_headers)
        resp.raise_for_status()

        # Extract file ID from Location URL
        file_id = location.rstrip("/").split("/")[-1]
        return file_id


async def gateway_chat(
    messages: list[dict],
    model: str = "auto",
    inject_skills: list[str] | None = None,
    stream: bool = False,
) -> dict:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    if inject_skills:
        payload["inject_skills"] = inject_skills

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(
            f"{GATEWAY_URL}/v1/chat/completions",
            json=payload,
            headers=_auth_headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def orch_get(path: str) -> Any:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{ORCHESTRATOR_URL}{path}", headers=_auth_headers())
        resp.raise_for_status()
        return resp.json()


async def orch_post(path: str, body: dict) -> Any:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(
            f"{ORCHESTRATOR_URL}{path}",
            json=body,
            headers=_auth_headers(),
        )
        resp.raise_for_status()
        return resp.json()


def format_response(data: dict) -> str:
    """Extract text + append routing metadata."""
    text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    routing = data.get("routing", {})

    meta_parts = []
    if routing.get("backend"):
        meta_parts.append(f"모델: {routing['backend']} ({routing.get('model', '')})")
    if routing.get("reason"):
        meta_parts.append(f"이유: {routing['reason']}")
    if routing.get("injected_skills"):
        meta_parts.append(f"스킬: {', '.join(routing['injected_skills'])}")
    if routing.get("multi_agent"):
        info = data.get("multi_agent_info", {})
        meta_parts.append(f"멀티에이전트: {info.get('sub_agents', 3)}개 병렬 → Claude 종합")
    if routing.get("is_medical"):
        meta_parts.append(f"의료 도메인: {routing.get('medical_domain', '')}")

    if meta_parts:
        text += "\n\n---\n_[Quetta] " + "  |  ".join(meta_parts) + "_"

    return text


# ─── Update helpers ───────────────────────────────────────────────────────────

# ── 논문 분석 파이프라인 (Nougat + Gemini + Claude) ────────────────────────────

async def _nougat_is_installed(agent_id: str) -> bool:
    r = await _relay(agent_id, "shell", {
        "command": 'python -c "import nougat; print(nougat.__version__)" 2>&1 || python -c "from nougat_ocr import predict" 2>&1',
        "timeout": 30,
    }, timeout=35)
    stdout = (r.get("data", {}).get("stdout", "") + r.get("data", {}).get("stderr", "")).lower()
    return "error" not in stdout and "traceback" not in stdout and "no module" not in stdout


async def _install_nougat_on_agent(agent_id: str) -> str:
    """GPU 에이전트에 nougat 설치. 결과 로그 반환."""
    # nougat-ocr 패키지(사용자 fork) 설치 — GPU torch 가정
    cmd = f"python -m pip install -q --upgrade {NOUGAT_REPO}"
    r = await _relay(agent_id, "shell", {"command": cmd, "timeout": 900}, timeout=910)
    out = r.get("data", {})
    return f"rc={out.get('returncode','?')}  stderr={out.get('stderr','')[:500]}"


async def _run_nougat_on_agent(agent_id: str, pdf_url: str, pdf_token: str = "") -> str:
    """GPU 에이전트에서 PDF URL 다운로드 → nougat 실행 → 결과 mmd 반환."""
    # 작업 디렉토리 준비 + PDF 다운로드
    tok_hdr = f'-H "X-API-Token: {pdf_token}"' if pdf_token else ""
    setup = (
        "mkdir -p /tmp/quetta_paper && cd /tmp/quetta_paper && "
        "rm -rf input output && mkdir input output && "
        f'curl -fsSL {tok_hdr} "{pdf_url}" -o input/paper.pdf && '
        "ls -la input/"
    )
    r = await _relay(agent_id, "shell", {"command": setup, "timeout": 300}, timeout=310)
    data = r.get("data", {})
    if data.get("returncode") != 0:
        raise RuntimeError(f"PDF 다운로드 실패: {data.get('stderr','')}")

    # nougat 실행 (CLI: nougat <pdf> -o <out_dir>)
    run = (
        "cd /tmp/quetta_paper && "
        "nougat input/paper.pdf -o output/ --no-skipping 2>&1 | tail -30 && "
        "echo --- && "
        "ls output/ && echo --- && "
        "cat output/paper.mmd 2>/dev/null || cat output/*.mmd 2>/dev/null"
    )
    r = await _relay(agent_id, "shell", {"command": run, "timeout": 1800}, timeout=1810)
    data = r.get("data", {})
    out = data.get("stdout", "")
    # '---' 이후의 내용이 mmd 본문
    parts = out.split("---")
    return parts[-1].strip() if len(parts) >= 3 else out


# ── 설계도 분석 (기계/전기/CPLD PDF·PNG) ────────────────────────────────────

_DRAWING_PROMPTS = {
    "mechanical": (
        "이 기계 설계도를 엔지니어 관점에서 상세히 분석하세요.\n"
        "1. 도면 종류 (조립도/부품도/단면도/상세도)\n"
        "2. 주요 치수·공차·표면거칠기(Ra)·끼워맞춤 기호\n"
        "3. 재질·열처리·표면처리 기재사항\n"
        "4. 각 부품의 기능과 조립 관계\n"
        "5. GD&T(기하공차) 기호 해석 — ⊥, ⌒, ◎, ⊕, ↕ 등\n"
        "6. 제작/가공 시 주의사항 (가공 순서·기준면)\n"
        "7. BOM(부품표)이 있으면 항목별 정리\n"
    ),
    "electrical": (
        "이 전기 설계도를 전기/제어 엔지니어 관점에서 상세히 분석하세요.\n"
        "1. 회로 종류 (배전/제어/PLC I/O/시퀀스/단선결선도)\n"
        "2. 주요 소자 (차단기, 계전기, 인버터, PLC, 센서) 목록·정격\n"
        "3. 전원 계통 (전압·상·주파수)과 결선\n"
        "4. 신호 흐름 — 입력/출력/인터록·안전회로\n"
        "5. 부하/모터 용량·보호장치 설정\n"
        "6. 단자번호·와이어 번호 규칙\n"
        "7. 안전 관련 (ESTOP, 접지, 절연) 확인\n"
    ),
    "cpld": (
        "이 CPLD/FPGA/디지털 설계도를 논리 설계자 관점에서 상세히 분석하세요.\n"
        "1. 설계 유형 (RTL 블록도/스키매틱/타이밍도/상태천이도/핀맵)\n"
        "2. 주요 모듈·서브 블록과 기능\n"
        "3. 신호 이름·비트폭·방향(input/output/inout)\n"
        "4. 클럭·리셋 계통 (동기/비동기, 클럭 도메인)\n"
        "5. FSM 상태와 전이 조건 (있다면)\n"
        "6. 인터페이스 프로토콜 (I2C/SPI/UART/AXI 등)\n"
        "7. 타이밍 제약 (setup/hold, tPD) 및 합성 가능 여부\n"
        "8. 가능하면 Verilog/VHDL 구조 유추\n"
    ),
    "auto": (
        "이 설계도의 종류를 먼저 판별하고(기계/전기/CPLD/기타), "
        "종류에 맞는 엔지니어 관점에서 상세히 분석하세요.\n"
        "치수·기호·결선·신호·부품·주석 등 중요한 정보를 빠짐없이 추출하세요.\n"
    ),
}


async def _gemini_analyze_file(file_path: str, prompt: str, timeout: int = 300) -> str:
    """Gemini CLI로 임의 파일 분석 (PDF/PNG/JPG 모두 지원, @filepath 구문)."""
    import shutil
    if not shutil.which(GEMINI_CLI):
        return f"_(Gemini CLI '{GEMINI_CLI}' 미설치)_"

    full_prompt = prompt + f"\n\n분석 대상: @{file_path}\n\n한글로 상세히 답하세요."
    proc = await asyncio.create_subprocess_exec(
        GEMINI_CLI, "-m", GEMINI_MODEL, "-p", full_prompt,
        "--approval-mode", "yolo",
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return f"_(Gemini CLI 타임아웃 {timeout}s)_"

    if proc.returncode != 0:
        err = (stderr or b"").decode(errors="replace")[:500]
        return f"_(Gemini CLI 실패 rc={proc.returncode}: {err})_"

    out = (stdout or b"").decode(errors="replace")
    lines = [ln for ln in out.splitlines() if not ln.startswith("Loaded cached")]
    return "\n".join(lines).strip()


def _pdf_extract_text(pdf_bytes: bytes) -> str:
    """PyMuPDF로 PDF 벡터 텍스트 추출 (주석·치수 텍스트). 설치 없으면 빈 문자열."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        parts = []
        for i, page in enumerate(doc):
            txt = page.get_text("text") or ""
            if txt.strip():
                parts.append(f"--- Page {i+1} ---\n{txt.strip()}")
        doc.close()
        return "\n\n".join(parts)
    except Exception as e:
        return f"_(PDF 텍스트 추출 실패: {e})_"


async def _claude_synthesize_blueprint(
    vision_out: str,
    extracted_text: str,
    drawing_type: str,
    query: str = "",
) -> str:
    """Gemini 시각 분석 + 벡터 텍스트 → Claude 엔지니어링 리포트."""
    type_label = {
        "mechanical": "기계 설계도",
        "electrical": "전기 설계도",
        "cpld":       "CPLD/FPGA 디지털 설계도",
        "auto":       "설계도",
    }.get(drawing_type, "설계도")

    focus = f"\n사용자 추가 초점: {query}" if query else ""
    text_clip = extracted_text[:40_000] if extracted_text else "_(벡터 텍스트 없음 — 이미지 도면이거나 pymupdf 미설치)_"
    vision_clip = vision_out[:60_000]

    system = (
        f"당신은 {type_label} 해석 전문 엔지니어입니다. "
        "제공된 시각 분석과 벡터 텍스트를 통합해 실무자가 바로 활용할 수 있는 분석 리포트를 작성하세요."
    )
    user = f"""다음 자료를 종합해 {type_label}를 분석하세요.

=== 1. Gemini 시각 분석 (이미지/도형/기호) ===
{vision_clip}

=== 2. PDF 벡터 텍스트 (주석·치수·표) ===
{text_clip}

=== 분석 요구사항 ===
1. **도면 개요** — 제목, 도면번호, 작성자, 개정일, 축척
2. **종류와 용도** — 무엇을 위한 설계인지
3. **핵심 사양** — 치수/정격/신호/인터페이스 등 타입별 핵심 데이터
4. **부품/블록/소자 리스트** — 표로 정리 (이름, 역할, 수량/수치)
5. **주요 관계·동작 설명** — 조립/결선/신호 흐름
6. **잠재 이슈 또는 검토 필요 지점** — 제작/시공/합성 시 주의사항
7. **이 도면을 100% 이해하려면 함께 확인할 자료**{focus}

한글로 상세하게, 엔지니어가 바로 참조할 수 있도록 작성하세요."""

    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": user},
    ]
    data = await gateway_chat(messages, model="claude-sonnet")
    return format_response(data)


async def _ingest_blueprint_to_rag(
    file_id: str,
    filename: str,
    drawing_type: str,
    vision_out: str,
    extracted_text: str,
    synthesis: str,
    tags: list[str] | None = None,
) -> dict:
    """설계도 분석 결과를 RAG에 저장. 논문과 유사한 구조."""
    tags = tags or []
    source = f"blueprint:{filename}"
    base_meta = {
        "type":         "blueprint",
        "drawing_type": drawing_type,
        "file_id":      file_id,
        "filename":     filename,
        "tags":         tags,
    }
    results = {"source": source, "chunks_text": 0, "chunk_vision": 0, "chunk_synthesis": 0, "failed": 0}

    # 1. PDF 벡터 텍스트 (있을 때)
    if extracted_text and "실패" not in extracted_text[:30] and "없음" not in extracted_text[:30]:
        for i, c in enumerate(_chunk_markdown(extracted_text, chunk_size=3000)):
            rid = await _rag_ingest(c, source, {**base_meta, "part": "pdf_text", "chunk_idx": i})
            if rid: results["chunks_text"] += 1
            else:   results["failed"] += 1

    # 2. Gemini 시각 분석
    if vision_out and "실패" not in vision_out[:30] and "미설치" not in vision_out[:30]:
        rid = await _rag_ingest(vision_out, f"{source}#vision", {**base_meta, "part": "vision"})
        if rid: results["chunk_vision"] = 1
        else:   results["failed"] += 1

    # 3. Claude 종합
    if synthesis and "실패" not in synthesis[:30]:
        rid = await _rag_ingest(synthesis, f"{source}#synthesis", {**base_meta, "part": "synthesis"})
        if rid: results["chunk_synthesis"] = 1
        else:   results["failed"] += 1

    return results


async def _gemini_analyze_pdf(pdf_bytes: bytes, query: str = "") -> str:
    """Gemini CLI로 PDF 분석 (subprocess, API 키 불필요 — OAuth 캐시 사용)."""
    import shutil, tempfile

    if not shutil.which(GEMINI_CLI):
        return f"_(Gemini CLI('{GEMINI_CLI}') 미설치 — `npm i -g @google/gemini-cli` 후 `gemini` 실행해 OAuth 로그인)_"

    # PDF를 임시 파일에 저장 (Gemini CLI의 @filepath 구문 사용)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        pdf_path = f.name

    try:
        prompt = (
            f"다음 논문 PDF(@{pdf_path})의 **그림·도표·수식·알고리즘 다이어그램**을 중심으로 분석해주세요.\n\n"
            "- 각 Figure/Table의 제목과 핵심 메시지\n"
            "- 주요 수식의 의미와 변수 정의\n"
            "- 시각적 요소(아키텍처, 플로우차트, 결과 그래프)의 해석\n"
            "- 본문과 그림의 관계\n"
            "한글로 답해주세요.\n"
        )
        if query:
            prompt += f"\n추가 초점: {query}\n"

        # gemini -m MODEL -p "prompt" — stdout이 응답
        proc = await asyncio.create_subprocess_exec(
            GEMINI_CLI, "-m", GEMINI_MODEL, "-p", prompt,
            "--approval-mode", "yolo",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        except asyncio.TimeoutError:
            proc.kill()
            return "_(Gemini CLI 타임아웃 5분)_"

        if proc.returncode != 0:
            err = (stderr or b"").decode(errors="replace")[:500]
            return f"_(Gemini CLI 실패 rc={proc.returncode}: {err})_"

        out = (stdout or b"").decode(errors="replace").strip()
        # "Loaded cached credentials." 같은 첫 줄 제거
        lines = [ln for ln in out.splitlines() if not ln.startswith("Loaded cached")]
        return "\n".join(lines).strip() or "_(Gemini CLI 응답 비어있음)_"
    finally:
        try: os.unlink(pdf_path)
        except: pass


def _chunk_markdown(md: str, chunk_size: int = 3000, overlap: int = 200) -> list[str]:
    """마크다운을 섹션/줄 경계를 존중하며 청킹."""
    if not md or len(md) <= chunk_size:
        return [md] if md else []

    # 1차: '# ' 헤딩 단위로 분리
    sections: list[str] = []
    cur: list[str] = []
    for line in md.splitlines(keepends=True):
        if line.startswith("# ") and cur:
            sections.append("".join(cur))
            cur = [line]
        else:
            cur.append(line)
    if cur:
        sections.append("".join(cur))

    # 2차: 섹션 길이가 chunk_size 초과하면 다시 분할
    chunks: list[str] = []
    for sec in sections:
        if len(sec) <= chunk_size:
            chunks.append(sec)
            continue
        # 줄 단위로 쪼개며 chunk_size 초과 시 분할
        buf = ""
        for line in sec.splitlines(keepends=True):
            if len(buf) + len(line) > chunk_size:
                if buf:
                    chunks.append(buf)
                    buf = buf[-overlap:] if overlap else ""
            buf += line
        if buf.strip():
            chunks.append(buf)
    return [c for c in chunks if c.strip()]


async def _rag_ingest(text: str, source: str, metadata: dict) -> str | None:
    """RAG /ingest 호출. 성공 시 document id, 실패 시 None."""
    async with httpx.AsyncClient(timeout=60) as client:
        try:
            resp = await client.post(
                f"{RAG_URL}/ingest",
                json={
                    "text": text[:49_000],  # 50K 한도 보호
                    "source": source,
                    "metadata": metadata,
                    "update_mode": "add",
                },
                headers=_rag_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("id") or data.get("document_id") or "ok"
        except Exception as e:
            logger.warning(f"RAG ingest 실패: {e}")
            return None


async def _ingest_paper_to_rag(
    file_id: str,
    filename: str,
    nougat_md: str,
    synthesis: str,
    gemini_out: str = "",
    tags: list[str] | None = None,
) -> dict:
    """논문 분석 결과를 RAG에 청킹해서 인제스트.
    반환: {source, chunks_nougat, chunk_synthesis, chunk_gemini, failed}
    """
    tags = tags or []
    source = f"paper:{filename}"
    base_meta = {
        "type":      "paper",
        "file_id":   file_id,
        "filename":  filename,
        "tags":      tags,
    }

    results = {"source": source, "chunks_nougat": 0, "chunk_synthesis": 0, "chunk_gemini": 0, "failed": 0}

    # 1. Nougat 본문 청킹 & 인제스트
    if nougat_md and "실패" not in nougat_md[:30]:
        chunks = _chunk_markdown(nougat_md, chunk_size=3000)
        for i, c in enumerate(chunks):
            meta = {**base_meta, "part": "body", "chunk_idx": i, "chunk_total": len(chunks)}
            rid = await _rag_ingest(c, source, meta)
            if rid: results["chunks_nougat"] += 1
            else:   results["failed"] += 1

    # 2. Claude 종합 (단일)
    if synthesis and "실패" not in synthesis[:30] and "건너뜀" not in synthesis[:30]:
        meta = {**base_meta, "part": "synthesis"}
        rid = await _rag_ingest(synthesis, f"{source}#synthesis", meta)
        if rid: results["chunk_synthesis"] = 1
        else:   results["failed"] += 1

    # 3. Gemini 시각 분석 (단일)
    if gemini_out and "건너뜀" not in gemini_out[:30] and "실패" not in gemini_out[:30]:
        meta = {**base_meta, "part": "gemini_vision"}
        rid = await _rag_ingest(gemini_out, f"{source}#gemini", meta)
        if rid: results["chunk_gemini"] = 1
        else:   results["failed"] += 1

    return results


async def _claude_synthesize_paper(
    nougat_md: str,
    gemini_analysis: str,
    query: str = "",
) -> str:
    """Nougat 본문 + Gemini 시각 분석을 Claude로 종합 (게이트웨이 경유)."""
    focus = f"\n사용자 초점: {query}" if query else ""
    max_md = 120_000  # Claude 입력 한도 보호
    nougat_clip = nougat_md[:max_md]
    if len(nougat_md) > max_md:
        nougat_clip += "\n\n[...본문 중 일부만 포함됨...]"

    system = (
        "당신은 학술 논문 심층 분석 전문가입니다. "
        "Nougat(OCR)로 추출된 본문과 Gemini의 시각 분석을 통합해 "
        "독자가 논문을 완벽히 이해할 수 있도록 설명하세요."
    )
    user = f"""다음 자료를 종합해 논문을 분석하세요.

=== 1. Nougat 추출 본문 (수식·구조 보존) ===
{nougat_clip}

=== 2. Gemini 시각 분석 (그림·수식·도표) ===
{gemini_analysis}

=== 분석 요구사항 ===
1. **제목 / 저자 / 소속 / 학회지**
2. **초록 한글 요약**
3. **핵심 기여(Contributions)** — 3~5개 불릿
4. **방법론(Method)** — 수식과 함께 단계별 설명
5. **실험 / 결과** — 주요 수치와 비교 대상
6. **한계 / 향후 연구**
7. **이 논문을 100% 이해하려면 주목할 부분**{focus}

한글로 상세하게 작성하세요."""

    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": user},
    ]
    data = await gateway_chat(messages, model="claude-sonnet")
    return format_response(data)


# ── Intent Classification (스마트 디스패처) ────────────────────────────────────

_INTENT_RULES = {
    "blueprint_query": [
        "저장된 설계도", "인제스트된 도면", "업로드한 설계도", "도면에서 찾",
        "저장한 blueprint",
    ],
    "blueprint_analysis": [
        "설계도", "도면", "blueprint", "schematic", "회로도", "단선결선도",
        "cpld", "fpga", "pcb", "gd&t", "기계 도면", "전기 도면", "조립도",
        "부품도", "결선도", "배치도", "p&id", "wiring", "drawing 분석",
    ],
    "paper_query": [
        "저장된 논문", "인제스트된 논문", "업로드한 논문", "논문 검색",
        "분석된 논문에서", "논문에서 찾아", "저장한 paper",
    ],
    "paper_analysis": [
        "논문 분석", "논문을 분석", "논문 해석", "paper analysis",
        "pdf 분석", ".pdf", "arxiv", "학술 논문", "paper review",
        "nougat", "수식 포함", "학술지", "figure 분석", "table 해석",
    ],
    "gpu_compute": [
        "gpu", "cuda", "torch", "tensorflow", "pytorch", "nvidia-smi",
        "학습", "훈련", "추론", "finetune", "fine-tune", "epoch",
        "train.py", "inference.py", "transformers", "diffusers",
        "stable diffusion", "whisper", "llama.cpp", "vllm",
        "모델 돌", "모델을 돌", "ml 작업", "딥러닝",
    ],
    "screenshot": [
        "스크린샷", "screenshot", "화면 캡처", "화면캡처", "화면 보여",
        "화면 좀", "screen capture", "화면을 보",
    ],
    "remote_shell": [
        "원격에서", "원격 pc에서", "원격에 ", "원격 셸", "원격 명령",
        "원격 실행", "remote shell", "ssh 로", "원격 컴퓨터",
    ],
    "file_analysis": [
        "파일 분석", "문서 분석", "의료 데이터", "분석해", "업로드해",
        "analyze file", ".pdf", ".csv", ".xlsx", ".edf", ".mat",
        "환자 데이터", "리포트 분석",
    ],
    "medical": [
        "진단", "임상", "icd", "fhir", "의학", "증상", "처방", "약물",
        "diagnosis", "clinical", "patient", "환자", "병력", "치료",
    ],
    "code": [
        "코드 리뷰", "리팩토링", "refactor", "버그 수정", "fix bug",
        "구현해", "함수 작성", "class ", "알고리즘 구현",
        "코드 작성", "작성해줘 .*코드", "코딩", "프로그래밍",
    ],
    "multi_agent": [
        "설계", "architecture", "아키텍처", "전체 구성", "시스템 설계",
        "복잡한", "여러 관점", "multi-step", "step by step 깊이",
    ],
    "memory_save": [
        "기억해줘", "기억해", "저장해줘", "메모해", "메모 저장", "외워줘",
        "remember this", "save this", "note this",
    ],
    "memory_recall": [
        "뭐였지", "전에 뭐", "기억나?", "저번에", "지난번", "저장된 기억",
        "내 메모", "recall memory", "what did i",
    ],
    "memory_list": [
        "기억 목록", "저장된 메모", "내 기억", "memory list",
    ],
}


def _classify_intent(text: str) -> tuple[str, list[str]]:
    """사용자 요청을 분류. 반환: (best_intent, matched_keywords).

    우선순위: gpu_compute > screenshot > remote_shell > file_analysis
             > medical > code > multi_agent > question (기본값)
    """
    low = text.lower()
    priority = ["memory_save", "memory_recall", "memory_list",
                "blueprint_query", "blueprint_analysis", "paper_query", "paper_analysis",
                "gpu_compute", "screenshot", "remote_shell",
                "file_analysis", "medical", "code", "multi_agent"]
    for intent in priority:
        matched = [kw for kw in _INTENT_RULES[intent] if kw in low]
        if matched:
            return intent, matched
    return "question", []


def _extract_shell_command(text: str) -> str:
    """요청 텍스트에서 실행할 명령어 후보 추출.
    1. 백틱 코드 블록
    2. ``` 코드 펜스
    3. 원본 그대로 반환
    """
    import re
    m = re.search(r"```(?:\w+)?\s*\n?(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    m = re.search(r"`([^`]+)`", text)
    if m:
        return m.group(1).strip()
    return text.strip()


async def _run_update() -> tuple[bool, str]:
    """
    Force-reinstall the package via uvx --reinstall.
    Returns (success, output_text).
    SSH URL 실패 시 HTTPS로 자동 폴백.
    """
    uvx = _find_uvx()
    if not uvx:
        return False, "`uvx`를 찾을 수 없습니다. https://docs.astral.sh/uv/ 에서 설치하세요."

    for repo in (REPO_SSH, REPO_HTTPS):
        cmd = [uvx, "--refresh", "--from", repo, "quetta-agents-mcp", "--version"]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            output = (stdout + stderr).decode().strip()
            if proc.returncode == 0 or "quetta" in output.lower():
                return True, output
        except asyncio.TimeoutError:
            return False, "업데이트 타임아웃 (120s). 네트워크를 확인하세요."
        except Exception as e:
            continue  # try next repo URL

    return False, "SSH/HTTPS 모두 실패. GitHub 접근 권한을 확인하세요."


def _find_uvx() -> str | None:
    """Find uvx binary path."""
    for candidate in ("uvx", os.path.expanduser("~/.local/bin/uvx"), "/usr/local/bin/uvx"):
        try:
            subprocess.run([candidate, "--version"], capture_output=True, check=True)
            return candidate
        except Exception:
            continue
    return None


def _get_latest_remote_version() -> str:
    """Fetch latest version tag from GitHub API (best-effort)."""
    try:
        import urllib.request
        url = "https://api.github.com/repos/choyunsung/quetta-agents-mcp/commits/master"
        req = urllib.request.Request(url, headers={"User-Agent": "quetta-agents-mcp"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
            sha = data.get("sha", "")[:7]
            date = data.get("commit", {}).get("author", {}).get("date", "")[:10]
            return f"master@{sha} ({date})"
    except Exception:
        return "확인 불가"


# ─── Tool Definitions ─────────────────────────────────────────────────────────

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="quetta_ask",
            description=(
                "질문이나 작업을 Quetta 시스템에 보냅니다. "
                "내용을 자동 분석해 최적 모델로 라우팅합니다:\n"
                "- 의료 질문 → DeepSeek-R1 (임상/진단) / Claude Opus (영상)\n"
                "- 코드 작업 → Gemma4 + agent-skills 자동 주입\n"
                "- 복잡한 분석 → Claude Sonnet\n"
                "- 단순 질문 → Gemma4 (로컬·무료)\n\n"
                "언제 사용?: Claude가 직접 답하기보다 로컬 모델에 위임하고 싶을 때, "
                "또는 의료·코드·복잡한 작업을 전문 모델로 처리하고 싶을 때."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "질문 또는 작업 내용",
                    },
                    "system_prompt": {
                        "type": "string",
                        "description": "선택적 시스템 프롬프트 (없으면 자동 감지)",
                        "default": "",
                    },
                    "model": {
                        "type": "string",
                        "description": "모델 명시 (auto/gemma4/claude/claude-opus/medical). 기본값: auto",
                        "default": "auto",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="quetta_code",
            description=(
                "코드 개발 작업 전문 도구. "
                "agent-skills 5종(plan/build/test/code-review/security)을 자동 주입하고 "
                "복잡도에 따라 Gemma4 또는 Claude로 라우팅합니다.\n\n"
                "언제 사용?: 함수/클래스 구현, 버그 수정, 리팩토링, 테스트 작성, "
                "코드 리뷰, 보안 점검 등 코드 관련 모든 작업."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "코드 작업 내용 (구현할 기능, 버그 설명 등)",
                    },
                    "language": {
                        "type": "string",
                        "description": "프로그래밍 언어 (python/typescript/go 등)",
                        "default": "",
                    },
                    "context": {
                        "type": "string",
                        "description": "관련 기존 코드 또는 추가 컨텍스트",
                        "default": "",
                    },
                },
                "required": ["task"],
            },
        ),
        Tool(
            name="quetta_medical",
            description=(
                "의료 전문 질의 도구. DeepSeek-R1 임상 추론 모델 사용.\n"
                "- clinical: 감별진단, 임상 추론, 치료 가이드\n"
                "- diagnostic: 증상 분석, 검사 결과 해석\n"
                "- imaging: 방사선/MRI/CT 영상 분석 (Claude Opus 사용)\n"
                "- research: 문헌 검토, 근거 기반 의학\n\n"
                "언제 사용?: 의료·임상·약학 관련 질문, 진단 추론, 의학 연구."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "의료 질문 내용",
                    },
                    "domain": {
                        "type": "string",
                        "description": "의료 도메인: clinical/diagnostic/imaging/research",
                        "enum": ["clinical", "diagnostic", "imaging", "research", "auto"],
                        "default": "auto",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="quetta_multi_agent",
            description=(
                "복잡한 멀티스텝 태스크를 SCION 병렬 멀티에이전트로 실행합니다.\n"
                "Gemma4 3개를 병렬로 실행(분석/구현/리뷰)한 후 Claude가 결과를 종합합니다.\n\n"
                "언제 사용?: '조사 후 구현', '비교 분석 후 추천', "
                "여러 관점이 필요한 복잡한 작업."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "복잡한 멀티스텝 태스크 내용",
                    },
                },
                "required": ["task"],
            },
        ),
        Tool(
            name="quetta_routing_info",
            description=(
                "특정 쿼리가 어떤 모델로 라우팅될지 미리 확인합니다. "
                "라우팅 결정 이유, 복잡도 점수, 스킬 주입 여부 등을 반환합니다."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "라우팅을 확인할 쿼리"},
                    "model": {"type": "string", "default": "auto"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="quetta_list_agents",
            description="등록된 전문 에이전트 목록을 조회합니다. 각 에이전트의 유형, 모델, 스킬, 용도를 확인할 수 있습니다.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="quetta_run_agent",
            description=(
                "특정 전문 에이전트에게 태스크를 위임합니다. "
                "에이전트별로 최적화된 스킬과 모델로 처리됩니다.\n\n"
                "에이전트 예시: code-assistant, medical-researcher, "
                "security-auditor, multi-agent-orchestrator"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_name": {
                        "type": "string",
                        "description": "에이전트 이름 (quetta_list_agents로 확인)",
                    },
                    "title": {
                        "type": "string",
                        "description": "태스크 제목",
                    },
                    "description": {
                        "type": "string",
                        "description": "태스크 상세 내용",
                        "default": "",
                    },
                },
                "required": ["agent_name", "title"],
            },
        ),
        Tool(
            name="quetta_remote_connect",
            description=(
                "연결된 원격 에이전트 목록을 조회하거나 설치 링크를 생성합니다.\n\n"
                "에이전트 미설치 시: OS를 지정하면 설치 URL을 생성합니다.\n"
                "연결 성공 시: 에이전트 ID, GPU 정보, OS, 화면 제어 가능 여부 반환\n\n"
                "에이전트는 서버로 역방향 WebSocket을 연결하므로 포트포워딩 불필요."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "install-link"],
                        "description": "list: 연결된 에이전트 목록 | install-link: 설치 링크 생성",
                        "default": "list",
                    },
                    "os": {
                        "type": "string",
                        "enum": ["linux", "mac", "windows"],
                        "description": "설치 링크 생성 시 대상 OS",
                        "default": "linux",
                    },
                },
            },
        ),
        Tool(
            name="quetta_remote_screenshot",
            description="원격 PC의 현재 화면을 캡처해서 보여줍니다. Claude가 화면을 보고 다음 액션을 결정할 때 사용합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "에이전트 ID (quetta_remote_connect로 확인)", "default": ""},
                    "max_width": {"type": "integer", "description": "최대 폭 픽셀 (기본 1280)", "default": 1280},
                },
            },
        ),
        Tool(
            name="quetta_remote_click",
            description="원격 PC에서 마우스 클릭을 수행합니다. 좌표는 quetta_remote_screenshot으로 확인하세요.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "에이전트 ID", "default": ""},
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "button": {"type": "string", "enum": ["left","right","middle"], "default": "left"},
                    "double": {"type": "boolean", "default": False},
                },
                "required": ["x", "y"],
            },
        ),
        Tool(
            name="quetta_remote_type",
            description="원격 PC에 텍스트를 입력합니다. 클릭으로 포커스를 먼저 맞추세요.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "default": ""},
                    "text": {"type": "string", "description": "입력할 텍스트"},
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="quetta_remote_key",
            description="원격 PC에서 키보드 단축키를 누릅니다. 예: 'enter', 'ctrl+c', 'alt+tab'",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "default": ""},
                    "key": {"type": "string", "description": "키 조합 (+ 로 구분, 예: ctrl+c)"},
                },
                "required": ["key"],
            },
        ),
        Tool(
            name="quetta_remote_shell",
            description=(
                "원격 PC에서 셸 명령어를 실행하고 결과를 반환합니다.\n\n"
                "**자동 GPU 라우팅**: 명령어에 GPU 키워드(nvidia-smi, cuda, torch, train.py 등)가 포함되면\n"
                "agent_id 미지정 시 자동으로 GPU 보유 에이전트를 선택합니다.\n\n"
                "예시:\n"
                "  - `nvidia-smi` → 자동으로 GPU 에이전트 선택\n"
                "  - `python train.py` → 자동으로 GPU 에이전트 선택\n"
                "  - 일반 셸 명령 → 기본 에이전트 (단일 연결 시 자동)"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "default": ""},
                    "command": {"type": "string", "description": "실행할 명령어"},
                    "timeout": {"type": "integer", "default": 30},
                    "cwd": {"type": "string", "default": ""},
                    "prefer_gpu": {
                        "type": "boolean",
                        "description": "GPU 에이전트 우선 선택 (true면 키워드 없이도 강제 선택)",
                        "default": False,
                    },
                },
                "required": ["command"],
            },
        ),
        Tool(
            name="quetta_gpu_exec",
            description=(
                "GPU가 필요한 명령을 자동으로 GPU 에이전트에서 실행합니다.\n\n"
                "- agent_id 미지정 시: 연결된 GPU 에이전트 중 자동 선택\n"
                "- GPU 에이전트가 없으면: 설치 링크 반환 후 에러\n"
                "- `quetta_remote_shell` 과 동일하지만 GPU 필수\n\n"
                "ML 학습, 추론, CUDA 샘플 실행 등에 사용하세요."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "실행할 셸 명령"},
                    "agent_id": {"type": "string", "default": ""},
                    "timeout": {"type": "integer", "default": 300},
                    "cwd": {"type": "string", "default": ""},
                },
                "required": ["command"],
            },
        ),
        Tool(
            name="quetta_gpu_python",
            description=(
                "Python 코드를 GPU 에이전트에서 직접 실행합니다 (CUDA/torch/ML 작업용).\n\n"
                "입력 코드는 원격 PC의 임시 파일로 저장된 뒤 python으로 실행됩니다.\n"
                "stdout/stderr 를 모두 반환합니다.\n\n"
                "예시 코드:\n"
                "  import torch\n"
                "  print(torch.cuda.is_available(), torch.cuda.device_count())\n"
                "  print(torch.cuda.get_device_name(0))"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "실행할 Python 코드"},
                    "agent_id": {"type": "string", "default": ""},
                    "timeout": {"type": "integer", "default": 300},
                    "python": {
                        "type": "string",
                        "description": "Python 실행 파일 (기본: 'python')",
                        "default": "python",
                    },
                },
                "required": ["code"],
            },
        ),
        Tool(
            name="quetta_gpu_status",
            description=(
                "연결된 모든 GPU 에이전트의 현재 상태를 요약합니다.\n"
                "각 에이전트에서 `nvidia-smi` 를 실행해 GPU 이름·메모리·온도·사용률을 표로 반환.\n\n"
                "GPU 자원 계획/모니터링 용도."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="quetta_analyze_paper",
            description=(
                "**학술 논문 완벽 분석** — Nougat (OCR, GPU) + Gemini Vision + Claude 종합 파이프라인.\n\n"
                "1. **Nougat**: PDF → 수식·표·구조가 보존된 고품질 Markdown (GPU 에이전트에서 실행)\n"
                "2. **Gemini CLI**: 서버에 설치된 `gemini` CLI(OAuth 기반, API 키 불필요)로 시각 분석\n"
                "3. **Claude**: 두 결과를 통합해 논문을 완전히 이해할 수 있는 한글 분석 리포트 생성\n\n"
                "입력 방법 (둘 중 하나):\n"
                "  - `file_path`: 서버 로컬 PDF 경로\n"
                "  - `file_id`: `quetta_upload_file` 로 이미 업로드된 PDF ID\n\n"
                "GPU 에이전트 미연결 시 자동으로 설치 링크 유도.\n"
                "`gemini` CLI 미설치/미로그인 시 Gemini 단계는 자동 건너뜀."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "default": "",
                                  "description": "서버 로컬 PDF 경로 (또는 file_id 사용)"},
                    "file_id":   {"type": "string", "default": "",
                                  "description": "업로드된 PDF의 TUS file_id"},
                    "query":     {"type": "string", "default": "",
                                  "description": "(선택) 집중해서 분석할 초점 (예: '저자의 데이터셋 구성법')"},
                    "agent_id":  {"type": "string", "default": "",
                                  "description": "(선택) 사용할 GPU 에이전트 ID — 미지정 시 자동 선택"},
                    "install_nougat": {"type": "boolean", "default": True,
                                        "description": "nougat 미설치 시 자동 설치 여부"},
                    "skip_gemini":    {"type": "boolean", "default": False,
                                        "description": "Gemini 단계 건너뛰기"},
                    "skip_claude":    {"type": "boolean", "default": False,
                                        "description": "Claude 종합 단계 건너뛰기 (nougat + gemini만)"},
                    "ingest_to_rag":  {"type": "boolean", "default": True,
                                        "description": "분석 결과를 RAG 지식베이스에 자동 인제스트 (이후 quetta_ask로 참조 가능)"},
                    "tags":           {"type": "array",
                                        "items": {"type": "string"},
                                        "default": [],
                                        "description": "(선택) RAG 태그"},
                },
            },
        ),
        Tool(
            name="quetta_analyze_blueprint",
            description=(
                "**설계도 분석** — 기계/전기/CPLD 설계도(PDF·PNG)를 Gemini Vision + Claude 종합으로 완전 해석.\n\n"
                "1. PDF면 PyMuPDF로 벡터 텍스트(주석·치수·BOM) 추출\n"
                "2. Gemini CLI로 도면 시각 분석 (타입별 전문 프롬프트)\n"
                "3. Claude Sonnet이 두 결과를 통합해 엔지니어링 리포트 생성\n"
                "4. 결과를 RAG에 자동 인제스트 → `quetta_blueprint_query`로 재질의\n\n"
                "drawing_type:\n"
                "  - `mechanical`: 기계 설계 (GD&T, 치수, 공차, 조립도)\n"
                "  - `electrical`: 전기 설계 (배전/제어/PLC/단선결선도)\n"
                "  - `cpld`: CPLD/FPGA/디지털 논리 (RTL, 타이밍, FSM)\n"
                "  - `auto`: 자동 감지 (기본값)"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path":    {"type": "string", "default": "",
                                     "description": "서버 로컬 PDF/PNG 경로"},
                    "file_id":      {"type": "string", "default": "",
                                     "description": "이미 TUS 업로드된 파일 ID"},
                    "drawing_type": {"type": "string",
                                     "enum": ["mechanical", "electrical", "cpld", "auto"],
                                     "default": "auto"},
                    "query":        {"type": "string", "default": "",
                                     "description": "(선택) 집중 분석 포인트"},
                    "tags":         {"type": "array", "items": {"type": "string"}, "default": []},
                    "ingest_to_rag":{"type": "boolean", "default": True},
                    "skip_gemini":  {"type": "boolean", "default": False},
                },
            },
        ),
        Tool(
            name="quetta_blueprint_query",
            description=(
                "분석·인제스트된 설계도를 RAG에서 검색/질의.\n"
                "- 특정 도면: `filename` 지정\n"
                "- 특정 타입: `drawing_type` 지정 (mechanical/electrical/cpld)\n"
                "- 목록: `list=true`"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query":        {"type": "string", "default": ""},
                    "filename":     {"type": "string", "default": ""},
                    "drawing_type": {"type": "string", "default": ""},
                    "list":         {"type": "boolean", "default": False},
                    "top_k":        {"type": "integer", "default": 8},
                },
            },
        ),
        Tool(
            name="quetta_paper_query",
            description=(
                "업로드·분석된 논문들을 RAG에서 검색/질의합니다.\n"
                "`quetta_analyze_paper` 로 인제스트된 논문 본문·종합·그림 분석이 대상입니다.\n\n"
                "- 특정 논문만 대상: `filename` 지정\n"
                "- 전체 논문 대상: `filename` 생략\n"
                "- 질문 없이 `list=true`: 인제스트된 논문 목록만 반환"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query":    {"type": "string", "default": "",
                                 "description": "논문에 대한 질문"},
                    "filename": {"type": "string", "default": "",
                                 "description": "(선택) 특정 논문 파일명으로 필터"},
                    "list":     {"type": "boolean", "default": False,
                                 "description": "true면 질의 대신 인제스트된 논문 목록 반환"},
                    "top_k":    {"type": "integer", "default": 8,
                                 "description": "RAG 검색 반환 개수"},
                },
            },
        ),
        Tool(
            name="quetta_history_list",
            description=(
                "**대화 히스토리 세션 목록** — MongoDB에 저장된 최근 대화 세션 조회.\n\n"
                "파라미터:\n"
                "  - `mine_only` (기본 true): 내 API 키로 생성된 세션만\n"
                "  - `unified` (기본 false): true면 모든 사용자의 세션 통합 조회\n"
                "  - `limit`: 최대 반환 개수 (기본 30)"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "mine_only": {"type": "boolean", "default": True},
                    "unified":   {"type": "boolean", "default": False},
                    "limit":     {"type": "integer", "default": 30},
                },
            },
        ),
        Tool(
            name="quetta_history_get",
            description="특정 세션의 전체 대화 이력을 시간순으로 조회.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "limit":      {"type": "integer", "default": 100},
                },
                "required": ["session_id"],
            },
        ),
        Tool(
            name="quetta_history_stats",
            description="저장된 전체 대화 히스토리 통계 (대화 수, 사용자 수, 백엔드별 분포 등).",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="quetta_session_init",
            description=(
                "**세션 시작 컨텍스트 로드** — 공유 RAG에서 사용자 프로필/활성 프로젝트/최근 기억을\n"
                "압축된 형태로 반환합니다. Claude Code 세션 시작 시 **자동 호출**되어 멀티 계정 간\n"
                "대화를 매끄럽게 이어갑니다.\n\n"
                "반환:\n"
                "  - 사용자 메모리 (고정 사실)\n"
                "  - 최근 활성 프로젝트 (대화 로그에서 추출)\n"
                "  - 인제스트된 주요 문서 요약 (논문·설계도·데이터)"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "max_items": {"type": "integer", "default": 10},
                },
            },
        ),
        Tool(
            name="quetta_workspace_list",
            description=(
                "내 접근 가능 워크스페이스 목록 + 전체 워크스페이스 조회.\n\n"
                "워크스페이스 개념:\n"
                "  - 'development' (코드/기술)와 'business' (업무) 등으로 지식 분리\n"
                "  - 내 계정은 관리자가 허용한 워크스페이스만 접근 가능\n"
                "  - 관리자(master API key)는 모든 워크스페이스 접근"
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="quetta_workspace_request",
            description=(
                "새로운 워크스페이스 접근 권한을 요청합니다.\n"
                "관리자가 승인하면 ACL에 반영되어 다음 요청부터 검색/저장 가능."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "workspace": {"type": "string", "description": "접근 원하는 워크스페이스 이름"},
                    "reason":    {"type": "string", "default": ""},
                },
                "required": ["workspace"],
            },
        ),
        Tool(
            name="quetta_admin_grant",
            description=(
                "[관리자 전용] 특정 사용자에게 워크스페이스 접근 권한 부여 (기존 ACL 덮어씀).\n"
                "user_hash 는 `quetta_workspace_list` 또는 `quetta_admin_requests` 로 확인."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_hash":  {"type": "string"},
                    "workspaces": {"type": "array", "items": {"type": "string"},
                                   "description": "허용할 워크스페이스 리스트 (전체 교체)"},
                },
                "required": ["user_hash", "workspaces"],
            },
        ),
        Tool(
            name="quetta_admin_requests",
            description="[관리자 전용] 대기 중인 워크스페이스 접근 요청 목록.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="quetta_admin_resolve",
            description="[관리자 전용] 접근 요청 승인/거부.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_hash": {"type": "string"},
                    "workspace": {"type": "string"},
                    "approve":   {"type": "boolean"},
                    "reason":    {"type": "string", "default": ""},
                },
                "required": ["user_hash", "workspace", "approve"],
            },
        ),
        Tool(
            name="quetta_admin_create_workspace",
            description="[관리자 전용] 새 워크스페이스 생성.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name":        {"type": "string"},
                    "label":       {"type": "string", "default": ""},
                    "description": {"type": "string", "default": ""},
                    "is_default":  {"type": "boolean", "default": False},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="quetta_memory_save",
            description=(
                "**공유 메모리에 기억 저장** — 멀티 계정/세션에서 공유되는 영구 기억을 RAG에 저장합니다.\n"
                "여러 Claude Code 계정에서 동일한 Quetta 서버를 쓰면 모든 계정이 이 기억을 조회할 수 있습니다.\n\n"
                "사용 예:\n"
                "  - '사용자는 MCG 연구자이며 KRISS 96채널 시스템 사용' 같은 고정 사실 저장\n"
                "  - 프로젝트 결정사항, 선호 사항, 자주 쓰는 명령어 등\n"
                "  - 세션 간 컨텍스트 유지용"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "text":      {"type": "string", "description": "저장할 내용 (필수)"},
                    "tags":      {"type": "array", "items": {"type": "string"}, "default": []},
                    "source":    {"type": "string", "default": "user-memory"},
                    "workspace": {"type": "string", "default": "",
                                  "description": "저장할 워크스페이스 (미지정 시 기본값 — development). 'business' 등 구분 가능"},
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="quetta_memory_recall",
            description=(
                "**공유 메모리에서 의미 검색** — 저장된 기억과 모든 인제스트된 문서에서 관련 내용을 찾습니다.\n"
                "Claude Code 어느 계정에서 저장했든 동일한 Quetta 서버 사용 시 자동 공유.\n\n"
                "참고: `quetta_ask`도 내부적으로 RAG harness를 통해 자동 검색하지만,\n"
                "이 도구는 **명시적으로 검색 결과만 반환** (LLM 답변 없이)하여 빠른 확인 용도."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "검색 쿼리 (필수)"},
                    "limit": {"type": "integer", "default": 8},
                    "filter_source": {"type": "string", "default": "",
                                       "description": "(선택) 특정 source만 필터 (e.g. user-memory)"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="quetta_memory_list",
            description=(
                "최근 저장된 사용자 메모리(`source=user-memory`) 목록을 반환합니다.\n"
                "다른 문서나 자동 저장된 Q&A는 제외, 사용자가 명시적으로 저장한 것만."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 20},
                },
            },
        ),
        Tool(
            name="quetta_auto",
            description=(
                "**스마트 디스패처** — 사용자의 요청을 분석해 자동으로 적절한 도구/모델/에이전트로 라우팅합니다.\n\n"
                "어떤 요청이든 이 도구에 넘기면 MCP가 자동 판단합니다:\n"
                "  • GPU 계산 (CUDA/torch/학습/추론) → GPU 에이전트에서 실행\n"
                "  • 화면 캡처 요청 → quetta_remote_screenshot\n"
                "  • 원격 셸 명령 → quetta_remote_shell (GPU 키워드면 GPU 에이전트)\n"
                "  • 파일/문서 분석 → quetta_analyze_file\n"
                "  • 의료 질의 → DeepSeek-R1 임상 추론\n"
                "  • 코드 작업 → Gemma4 + agent-skills\n"
                "  • 아키텍처/복잡한 설계 → 멀티에이전트 (SCION)\n"
                "  • 그 외 일반 질문 → Gemma4/Claude 자동 라우팅\n\n"
                "불확실할 때의 기본 동작: LLM 게이트웨이의 자동 라우팅(`quetta_ask`)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "request": {
                        "type": "string",
                        "description": "자연어 요청 (한글/영문 자유). 원격 실행할 명령어를 백틱에 감쌀 수 있음.",
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "(선택) 원격 에이전트 ID - GPU/remote 의도로 분류될 때 사용",
                        "default": "",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "(선택) 파일 분석 의도일 때의 파일 경로",
                        "default": "",
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "true면 실행하지 않고 분류 결과·라우팅만 반환",
                        "default": False,
                    },
                },
                "required": ["request"],
            },
        ),
        Tool(
            name="quetta_analyze_file",
            description=(
                "파일을 서버에 업로드하고 유형을 자동 감지한 뒤 AI로 분석합니다.\n\n"
                "처리 흐름:\n"
                "  1. 파일 업로드 (TUS 프로토콜 → /storage/uploads/tusd/)\n"
                "  2. 파일 유형 자동 감지: medical / signal_data / document\n"
                "  3. RAG 지식베이스에 인제스트 (usage_type 자동 매핑)\n"
                "  4. 적합한 AI 모델로 분석:\n"
                "     - medical → DeepSeek-R1 임상 추론\n"
                "     - signal_data → Gemma4 + 측정 데이터 분석\n"
                "     - document → Gemma4 + 문서 요약\n\n"
                "입력 방법:\n"
                "  - file_path: 서버 로컬 파일 경로\n"
                "  - content + filename: 텍스트 직접 입력"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "분석할 파일 경로 (서버 로컬 경로)",
                        "default": "",
                    },
                    "content": {
                        "type": "string",
                        "description": "분석할 텍스트 내용 (file_path 미지정 시)",
                        "default": "",
                    },
                    "filename": {
                        "type": "string",
                        "description": "파일명 (content 사용 시 확장자로 유형 감지)",
                        "default": "upload.txt",
                    },
                    "query": {
                        "type": "string",
                        "description": "분석 요청 질문 (없으면 전체 요약)",
                        "default": "",
                    },
                    "source": {
                        "type": "string",
                        "description": "출처/프로젝트명 (RAG 메타데이터)",
                        "default": "",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "추가 태그",
                        "default": [],
                    },
                },
            },
        ),
        Tool(
            name="quetta_upload_file",
            description=(
                "파일 또는 텍스트를 서버에 업로드합니다 (TUS 프로토콜, 대용량 지원).\n"
                "업로드 후 `quetta_upload_process`로 RAG에 인제스트할 수 있습니다.\n\n"
                "입력 방법 (둘 중 하나):\n"
                "  1. file_path: 서버에 있는 파일 경로\n"
                "  2. content + filename: 텍스트 내용과 파일명"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "업로드할 파일 경로 (서버 로컬 경로)",
                        "default": "",
                    },
                    "content": {
                        "type": "string",
                        "description": "업로드할 텍스트 내용 (file_path 미지정 시 사용)",
                        "default": "",
                    },
                    "filename": {
                        "type": "string",
                        "description": "저장할 파일명 (content 사용 시 필수)",
                        "default": "upload.txt",
                    },
                },
            },
        ),
        Tool(
            name="quetta_upload_list",
            description="서버에 업로드된 파일 목록을 조회합니다. 파일 ID, 이름, 크기, 업로드 완료 여부를 확인할 수 있습니다.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="quetta_upload_process",
            description=(
                "업로드 완료된 파일을 RAG(지식베이스)에 인제스트합니다.\n"
                "텍스트 파일은 청크로 분할되어 의미 검색에 활용됩니다.\n\n"
                "file_id는 `quetta_upload_list`로 확인하세요."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": "업로드된 파일 ID (quetta_upload_list로 확인)",
                    },
                    "usage_type": {
                        "type": "string",
                        "description": "RAG 저장 용도 (measurement_data/project_knowledge/clinical_record/document)",
                        "default": "measurement_data",
                    },
                    "source": {
                        "type": "string",
                        "description": "출처 (프로젝트명 등)",
                        "default": "",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "태그 목록",
                        "default": [],
                    },
                    "chunk_size": {
                        "type": "integer",
                        "description": "텍스트 분할 크기 (500-50000 chars)",
                        "default": 4000,
                    },
                },
                "required": ["file_id"],
            },
        ),
        Tool(
            name="quetta_upload_process_all",
            description=(
                "업로드 완료된 모든 파일을 RAG(지식베이스)에 인제스트합니다.\n"
                "미처리 파일을 일괄 처리할 때 사용합니다."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "usage_type": {
                        "type": "string",
                        "description": "RAG 저장 용도 (measurement_data/project_knowledge/clinical_record/document)",
                        "default": "measurement_data",
                    },
                    "source": {
                        "type": "string",
                        "description": "출처 (프로젝트명 등)",
                        "default": "",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "태그 목록",
                        "default": [],
                    },
                    "chunk_size": {
                        "type": "integer",
                        "description": "텍스트 분할 크기 (500-50000 chars)",
                        "default": 4000,
                    },
                },
            },
        ),
        Tool(
            name="quetta_version",
            description="현재 설치된 quetta-agents-mcp 버전과 GitHub 최신 커밋을 확인합니다.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="quetta_update",
            description=(
                "quetta-agents-mcp를 GitHub 최신 버전으로 업데이트합니다.\n"
                "uvx --reinstall로 패키지를 재설치합니다.\n"
                "업데이트 후 Claude Code를 재시작해야 적용됩니다."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


# ─── Tool Handlers ────────────────────────────────────────────────────────────

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:

    # ── quetta_ask ────────────────────────────────────────────────────────────
    if name == "quetta_ask":
        query = arguments["query"]
        model = arguments.get("model", "auto")
        system_prompt = arguments.get("system_prompt", "")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": query})

        data = await gateway_chat(messages, model=model)
        return [TextContent(type="text", text=format_response(data))]

    # ── quetta_code ───────────────────────────────────────────────────────────
    elif name == "quetta_code":
        task = arguments["task"]
        language = arguments.get("language", "")
        context = arguments.get("context", "")

        content = task
        if language:
            content = f"[언어: {language}]\n\n{content}"
        if context:
            content += f"\n\n[관련 코드/컨텍스트]\n{context}"

        messages = [{"role": "user", "content": content}]
        skills = ["plan", "build", "test", "code-review-and-quality", "security-and-hardening"]

        data = await gateway_chat(messages, model="auto", inject_skills=skills)
        return [TextContent(type="text", text=format_response(data))]

    # ── quetta_medical ────────────────────────────────────────────────────────
    elif name == "quetta_medical":
        query = arguments["query"]
        domain = arguments.get("domain", "auto")

        # imaging은 Claude Opus로, 나머지는 medical 모델
        if domain == "imaging":
            model = "claude-opus"
            messages = [
                {"role": "system", "content": "You are a medical imaging specialist. Analyze radiological findings, MRI, CT, and X-ray images with clinical precision."},
                {"role": "user", "content": query},
            ]
        else:
            model = "medical"
            messages = [{"role": "user", "content": query}]

        data = await gateway_chat(messages, model=model)
        return [TextContent(type="text", text=format_response(data))]

    # ── quetta_multi_agent ────────────────────────────────────────────────────
    elif name == "quetta_multi_agent":
        task = arguments["task"]
        messages = [{"role": "user", "content": task}]
        data = await gateway_chat(messages, model="auto")
        # Force multi-agent by appending keywords if not already detected
        routing = data.get("routing", {})
        if not routing.get("multi_agent"):
            # Retry with explicit multi-agent hint
            messages = [{"role": "user", "content": f"[멀티에이전트 병렬 실행 요청]\n\n{task}"}]
            data = await gateway_chat(messages, model="auto")
        return [TextContent(type="text", text=format_response(data))]

    # ── quetta_routing_info ───────────────────────────────────────────────────
    elif name == "quetta_routing_info":
        query = arguments["query"]
        model = arguments.get("model", "auto")

        async with httpx.AsyncClient(timeout=10) as client:
            params = {"model": model, "text": query}
            resp = await client.get(f"{GATEWAY_URL}/v1/routing/explain", params=params)
            resp.raise_for_status()
            data = resp.json()

        lines = [
            f"**라우팅 결과**",
            f"- 요청 모델: `{data['input_model']}`",
            f"- 실제 라우팅: **{data['routed_to']}** (`{data['actual_model']}`)",
            f"- 이유: {data['reason']}",
            f"- 복잡도 점수: {data['complexity_score']:.2f}",
        ]
        if data.get("is_medical"):
            lines.append(f"- 의료 도메인: {data['medical_domain']}")
        if data.get("inject_code_skills"):
            lines.append("- agent-skills 5종 자동 주입 예정")
        if data.get("multi_agent"):
            lines.append("- SCION 병렬 멀티에이전트 모드")

        return [TextContent(type="text", text="\n".join(lines))]

    # ── quetta_list_agents ────────────────────────────────────────────────────
    elif name == "quetta_list_agents":
        data = await orch_get("/agents")
        agents = data if isinstance(data, list) else data.get("agents", data.get("items", []))

        if not agents:
            return [TextContent(type="text", text="등록된 에이전트가 없습니다.")]

        lines = ["**등록된 Quetta 에이전트**\n"]
        for ag in agents:
            name_str   = ag.get("name", "?")
            htype      = ag.get("harness_type", "?")
            model_ov   = ag.get("model_override") or "auto"
            skills     = ag.get("skills") or []
            desc       = ag.get("description", "")
            lines.append(f"### {name_str}")
            lines.append(f"- 유형: `{htype}`  |  모델: `{model_ov}`")
            if skills:
                lines.append(f"- 스킬: {', '.join(skills)}")
            if desc:
                lines.append(f"- 설명: {desc}")
            lines.append("")

        return [TextContent(type="text", text="\n".join(lines))]

    # ── quetta_run_agent ──────────────────────────────────────────────────────
    elif name == "quetta_run_agent":
        agent_name  = arguments["agent_name"]
        title       = arguments["title"]
        description = arguments.get("description", "")

        # Find agent by name
        agents_data = await orch_get("/agents")
        agents = agents_data if isinstance(agents_data, list) else agents_data.get("agents", agents_data.get("items", []))
        agent = next((a for a in agents if a.get("name") == agent_name), None)

        if not agent:
            return [TextContent(type="text",
                text=f"에이전트 '{agent_name}'을 찾을 수 없습니다. quetta_list_agents로 목록을 확인하세요.")]

        # Submit task
        task_data = await orch_post("/tasks", {
            "title": title,
            "description": description,
            "agent_id": agent["id"],
            "priority": 5,
        })

        task_id = task_data.get("id", "?")
        exec_id = task_data.get("execution_id")

        result_lines = [
            f"**태스크 제출 완료**",
            f"- 에이전트: {agent_name}",
            f"- 태스크 ID: `{task_id}`",
            f"- 상태: {task_data.get('status', 'PENDING')}",
        ]

        # Poll for result (up to 5 minutes)
        if exec_id:
            result_lines.append(f"- 실행 ID: `{exec_id}`")
            for _ in range(60):  # 60 × 5s = 300s
                await asyncio.sleep(5)
                try:
                    exec_data = await orch_get(f"/executions/{exec_id}/events")
                    events = exec_data if isinstance(exec_data, list) else exec_data.get("events", [])
                    # Check if completed
                    statuses = [e.get("event_type") for e in events if e.get("event_type")]
                    if "state_transition" in statuses:
                        last = next(
                            (e for e in reversed(events)
                             if e.get("event_type") == "state_transition"), None
                        )
                        if last:
                            new_state = last.get("payload", {}).get("new_state", "")
                            if new_state in ("COMPLETED", "ERROR"):
                                result_lines.append(f"- 완료 상태: **{new_state}**")
                                break
                except Exception:
                    pass
            else:
                result_lines.append("- 타임아웃: 실행 중 (백그라운드 계속 실행)")

        return [TextContent(type="text", text="\n".join(result_lines))]

    # ── quetta_remote_connect ─────────────────────────────────────────────────
    elif name == "quetta_remote_connect":
        action = arguments.get("action", "list")
        os_type = arguments.get("os", "linux")

        if action == "install-link":
            data = await _relay_get(f"/agent/install-link?os={os_type}")
            url  = data.get("url", "")
            lines = [
                f"## Quetta Remote Agent 설치 링크 ({os_type})",
                "",
                "**원격 PC에서 아래 명령어를 실행하세요:**",
                "",
            ]
            if os_type == "windows":
                lines += [
                    f"```",
                    f"# {url}",
                    f"# 위 URL을 브라우저에서 다운로드 후 실행",
                    "```",
                ]
            else:
                lines += [
                    "```bash",
                    f'curl -fsSL "{url}" | bash',
                    "```",
                ]
            lines += [
                "",
                f"- 링크 유효기간: {data.get('expires_in', '24시간')}",
                "",
                "설치 후 에이전트가 자동으로 서버에 연결됩니다.",
                "연결 확인: `quetta_remote_connect` (action=list)",
            ]
            return [TextContent(type="text", text="\n".join(lines))]

        # action == "list"
        agents = await _relay_get("/agent/agents")
        if not agents:
            lines = [
                "## 연결된 원격 에이전트 없음",
                "",
                "설치 링크를 생성하려면:",
                "```",
                'quetta_remote_connect(action="install-link", os="linux")',
                "```",
            ]
            return [TextContent(type="text", text="\n".join(lines))]

        lines = [f"## 연결된 원격 에이전트 ({len(agents)}개)\n"]
        for ag in agents:
            lines += [
                f"### ID: `{ag['id']}`",
                f"- 호스트: {ag.get('hostname','?')}  |  OS: {ag.get('platform','?')}",
                f"- GPU: **{ag.get('gpu','없음')}**",
                f"- 화면 제어: {'✅' if ag.get('has_gui') else '❌'}  |  스크린샷: {'✅' if ag.get('has_screenshot') else '❌'}",
                f"- 연결 경과: {ag.get('connected_sec',0)}초",
                "",
            ]
        lines.append("_agent_id를 복사해서 다른 도구에 사용하세요._")
        return [TextContent(type="text", text="\n".join(lines))]

    # ── quetta_remote_screenshot ──────────────────────────────────────────────
    elif name == "quetta_remote_screenshot":
        aid  = _active_agent_id(arguments)
        data = await _relay(aid, "screenshot", {"max_width": arguments.get("max_width", 1280)}, timeout=30)
        inner = data.get("data", data)
        img_b64 = inner.get("image", "")
        mime    = inner.get("mime", "image/png")
        w, h    = inner.get("width", 0), inner.get("height", 0)
        return [
            ImageContent(type="image", data=img_b64, mimeType=mime),
            TextContent(type="text", text=f"_화면: {w}×{h}px  |  에이전트: {aid}_"),
        ]

    # ── quetta_remote_click ───────────────────────────────────────────────────
    elif name == "quetta_remote_click":
        aid = _active_agent_id(arguments)
        await _relay(aid, "click", {
            "x": arguments["x"], "y": arguments["y"],
            "button": arguments.get("button", "left"),
            "double": arguments.get("double", False),
        }, timeout=10)
        return [TextContent(type="text", text=f"클릭: ({arguments['x']}, {arguments['y']}) [{arguments.get('button','left')}]")]

    # ── quetta_remote_type ────────────────────────────────────────────────────
    elif name == "quetta_remote_type":
        aid = _active_agent_id(arguments)
        text = arguments["text"]
        await _relay(aid, "type", {"text": text}, timeout=30)
        return [TextContent(type="text", text=f"입력 완료: {len(text)}자")]

    # ── quetta_remote_key ─────────────────────────────────────────────────────
    elif name == "quetta_remote_key":
        aid = _active_agent_id(arguments)
        key = arguments["key"]
        await _relay(aid, "key", {"key": key}, timeout=10)
        return [TextContent(type="text", text=f"키 입력: `{key}`")]

    # ── quetta_remote_shell ───────────────────────────────────────────────────
    elif name == "quetta_remote_shell":
        prefer_gpu = arguments.get("prefer_gpu", False)
        aid  = await _pick_agent(arguments, prefer_gpu=prefer_gpu)
        tout = arguments.get("timeout", 30)
        data = await _relay(aid, "shell", {
            "command": arguments["command"],
            "timeout": tout,
            "cwd": arguments.get("cwd") or None,
        }, timeout=tout + 10)
        inner  = data.get("data", data)
        rc     = inner.get("returncode", -1)
        stdout = inner.get("stdout", "")
        stderr = inner.get("stderr", "")
        lines  = [f"**`{arguments['command']}`** → rc={rc}  _(agent: {aid})_"]
        if stdout: lines += ["```", stdout.strip()[-4000:], "```"]
        if stderr: lines += ["_stderr:_", "```", stderr.strip()[-1000:], "```"]
        return [TextContent(type="text", text="\n".join(lines))]

    # ── quetta_gpu_exec ───────────────────────────────────────────────────────
    elif name == "quetta_gpu_exec":
        aid  = await _pick_agent(arguments, prefer_gpu=True)
        tout = arguments.get("timeout", 300)
        data = await _relay(aid, "shell", {
            "command": arguments["command"],
            "timeout": tout,
            "cwd": arguments.get("cwd") or None,
        }, timeout=tout + 10)
        inner  = data.get("data", data)
        rc     = inner.get("returncode", -1)
        stdout = inner.get("stdout", "")
        stderr = inner.get("stderr", "")
        lines  = [f"**[GPU]** `{arguments['command']}` → rc={rc}  _(agent: {aid})_"]
        if stdout: lines += ["```", stdout.strip()[-6000:], "```"]
        if stderr: lines += ["_stderr:_", "```", stderr.strip()[-2000:], "```"]
        return [TextContent(type="text", text="\n".join(lines))]

    # ── quetta_gpu_python ─────────────────────────────────────────────────────
    elif name == "quetta_gpu_python":
        aid     = await _pick_agent(arguments, prefer_gpu=True)
        tout    = arguments.get("timeout", 300)
        py_exe  = arguments.get("python", "python")
        code    = arguments["code"]

        # 원격 PC에 임시 파일로 저장 후 실행 (inline -c는 따옴표 이스케이프 지옥)
        b64 = base64.b64encode(code.encode("utf-8")).decode()
        # 모든 주요 OS에서 동작하는 단일 한 줄 스크립트
        runner = (
            f'{py_exe} -c "import base64,os,sys,tempfile;'
            f'd=base64.b64decode(\'{b64}\');'
            f'f=tempfile.NamedTemporaryFile(mode=\'wb\',suffix=\'.py\',delete=False);'
            f'f.write(d);f.close();'
            f'os.system(sys.executable+\' \'+f.name)"'
        )
        data = await _relay(aid, "shell", {
            "command": runner,
            "timeout": tout,
        }, timeout=tout + 10)
        inner  = data.get("data", data)
        rc     = inner.get("returncode", -1)
        stdout = inner.get("stdout", "")
        stderr = inner.get("stderr", "")
        lines  = [f"**[GPU Python]** rc={rc}  _(agent: {aid})_"]
        if stdout: lines += ["```", stdout.strip()[-6000:], "```"]
        if stderr: lines += ["_stderr:_", "```", stderr.strip()[-2000:], "```"]
        return [TextContent(type="text", text="\n".join(lines))]

    # ── quetta_analyze_paper (Nougat + Gemini + Claude) ───────────────────────
    elif name == "quetta_analyze_paper":
        file_path = arguments.get("file_path", "").strip()
        file_id   = arguments.get("file_id", "").strip()
        query     = arguments.get("query", "")
        do_install = arguments.get("install_nougat", True)
        skip_gemini = arguments.get("skip_gemini", False)
        skip_claude = arguments.get("skip_claude", False)

        if not file_path and not file_id:
            return [TextContent(type="text", text="❌ `file_path` 또는 `file_id` 중 하나는 필수입니다.")]

        # 1) 파일 준비 → file_id 확보 (로컬 경로면 업로드)
        pdf_bytes: bytes = b""
        progress = ["## 📄 논문 분석 파이프라인"]

        if file_path:
            try:
                with open(file_path, "rb") as f:
                    pdf_bytes = f.read()
            except Exception as e:
                return [TextContent(type="text", text=f"❌ 파일 읽기 실패: {e}")]
            fname = file_path.rsplit("/", 1)[-1]
            progress.append(f"**1/4**  파일 로드: `{fname}` ({len(pdf_bytes):,} bytes)")
            # TUS 업로드 → file_id
            file_id = await _tus_upload(fname, pdf_bytes)
            progress.append(f"**2/4**  TUS 업로드 완료: `{file_id}`")
        else:
            # file_id만 있음 → RAG에서 파일 정보 조회 + 다운로드
            async with httpx.AsyncClient(timeout=60) as c:
                info = await c.get(f"{RAG_URL}/upload/files/{file_id}", headers=_rag_headers())
                info.raise_for_status()
                meta = info.json()
            progress.append(f"**1/4**  기존 파일: `{meta.get('filename','?')}` ({meta.get('size',0):,} bytes)")
            # tusd 원본 다운로드 (Gemini 전달용)
            dl_url = f"{TUSD_URL.rstrip('/')}/files/{file_id}"
            async with httpx.AsyncClient(timeout=120) as c:
                resp = await c.get(dl_url, headers=_tusd_headers())
                resp.raise_for_status()
                pdf_bytes = resp.content
            progress.append(f"**2/4**  파일 내려받음 ({len(pdf_bytes):,} bytes)")

        # 2) Nougat on GPU agent
        aid = await _pick_agent({"agent_id": arguments.get("agent_id", "")}, prefer_gpu=True)
        progress.append(f"**3/4**  GPU 에이전트 선택: `{aid}`")

        # PDF URL (에이전트가 다운로드할 경로) — TUSD_URL 사용
        pdf_url   = f"{TUSD_URL.rstrip('/')}/files/{file_id}"
        pdf_token = TUSD_TOKEN

        # nougat 설치 확인/설치
        if do_install:
            if not await _nougat_is_installed(aid):
                progress.append(f"  → nougat 미설치 → 설치 중... (최대 15분)")
                log = await _install_nougat_on_agent(aid)
                progress.append(f"  → 설치 완료: {log}")

        # 실행
        try:
            nougat_md = await _run_nougat_on_agent(aid, pdf_url, pdf_token)
            progress.append(f"  → nougat 추출 완료: {len(nougat_md):,} chars")
        except Exception as e:
            nougat_md = f"_(Nougat 실행 실패: {e})_"
            progress.append(f"  → ❌ nougat 실패: {e}")

        # 3) Gemini Vision (CLI subprocess)
        gemini_out = ""
        import shutil
        if not skip_gemini and shutil.which(GEMINI_CLI):
            try:
                gemini_out = await _gemini_analyze_pdf(pdf_bytes, query)
                progress.append(f"**4/4**  Gemini CLI 분석 완료: {len(gemini_out):,} chars")
            except Exception as e:
                gemini_out = f"_(Gemini 실패: {e})_"
                progress.append(f"**4/4**  ❌ Gemini 실패: {e}")
        elif skip_gemini:
            progress.append(f"**4/4**  Gemini 건너뜀 (skip_gemini=True)")
        else:
            progress.append(f"**4/4**  Gemini 건너뜀 (CLI '{GEMINI_CLI}' 미설치)")

        # 4) Claude 종합
        if skip_claude:
            synthesis = "_(Claude 종합 건너뜀)_"
        else:
            try:
                synthesis = await _claude_synthesize_paper(nougat_md, gemini_out, query)
            except Exception as e:
                synthesis = f"_(Claude 종합 실패: {e})_"

        # 5) RAG 인제스트 (분석 결과를 지식베이스에 저장)
        ingest_summary = ""
        if arguments.get("ingest_to_rag", True):
            try:
                fname = file_path.rsplit("/", 1)[-1] if file_path else f"paper_{file_id}.pdf"
                r = await _ingest_paper_to_rag(
                    file_id=file_id,
                    filename=fname,
                    nougat_md=nougat_md,
                    synthesis=synthesis,
                    gemini_out=gemini_out,
                    tags=arguments.get("tags", []),
                )
                ingest_summary = (
                    f"\n**RAG 인제스트 완료**  \n"
                    f"- Source 태그: `{r['source']}`\n"
                    f"- Nougat 본문 청크: {r['chunks_nougat']}개\n"
                    f"- Claude 종합: {r['chunk_synthesis']}\n"
                    f"- Gemini 시각분석: {r['chunk_gemini']}\n"
                    + (f"- 실패: {r['failed']}\n" if r['failed'] else "")
                    + f"\n이후 `quetta_paper_query(query=\"...\", filename=\"{fname}\")`로 질의하세요.\n"
                )
            except Exception as e:
                ingest_summary = f"\n_(RAG 인제스트 실패: {e})_\n"
        else:
            ingest_summary = "\n_(RAG 인제스트 건너뜀 — ingest_to_rag=False)_\n"

        # 6) 최종 출력
        final = "\n".join(progress) + "\n\n---\n\n"
        final += "## 🎯 종합 분석 (Claude)\n\n" + synthesis + "\n\n---\n"
        final += ingest_summary + "\n---\n\n"
        final += "<details><summary>🔍 Nougat 원본 추출 (접어서 보기)</summary>\n\n```markdown\n"
        final += nougat_md[:8000] + ("\n\n[...이하 생략...]" if len(nougat_md) > 8000 else "")
        final += "\n```\n</details>\n\n"
        if gemini_out and "건너뜀" not in gemini_out[:30]:
            final += "<details><summary>👁 Gemini 시각 분석 (접어서 보기)</summary>\n\n"
            final += gemini_out[:6000] + "\n\n</details>\n"

        return [TextContent(type="text", text=final)]

    # ── quetta_analyze_blueprint (설계도 분석) ────────────────────────────────
    elif name == "quetta_analyze_blueprint":
        import tempfile, pathlib
        file_path = arguments.get("file_path", "").strip()
        file_id   = arguments.get("file_id", "").strip()
        dtype     = arguments.get("drawing_type", "auto")
        query     = arguments.get("query", "")
        skip_gem  = arguments.get("skip_gemini", False)
        ingest    = arguments.get("ingest_to_rag", True)
        tags      = arguments.get("tags", [])

        if not file_path and not file_id:
            return [TextContent(type="text", text="❌ `file_path` 또는 `file_id` 필요.")]

        # 1) 파일 바이트 확보 + 임시 경로 (Gemini CLI @filepath 용)
        progress = [f"## 📐 설계도 분석 파이프라인 (drawing_type: {dtype})"]
        raw: bytes = b""
        fname = ""
        if file_path:
            p = pathlib.Path(file_path)
            if not p.exists():
                return [TextContent(type="text", text=f"❌ 파일 없음: {file_path}")]
            raw = p.read_bytes()
            fname = p.name
            progress.append(f"**1/3**  파일: `{fname}` ({len(raw):,} bytes)")
            # TUS 업로드로 file_id 획득 (RAG 인제스트 링크용)
            if ingest and not file_id:
                try:
                    file_id = await _tus_upload(fname, raw)
                    progress.append(f"  → TUS 업로드: `{file_id}`")
                except Exception as e:
                    progress.append(f"  → _(TUS 업로드 실패 — RAG 저장은 계속: {e})_")
        else:
            async with httpx.AsyncClient(timeout=120) as c:
                info = await c.get(f"{RAG_URL}/upload/files/{file_id}", headers=_rag_headers())
                info.raise_for_status()
                meta = info.json()
                fname = meta.get("filename", f"blueprint_{file_id}")
                dl = await c.get(f"{TUSD_URL.rstrip('/')}/files/{file_id}", headers=_tusd_headers())
                dl.raise_for_status()
                raw = dl.content
            progress.append(f"**1/3**  파일: `{fname}` ({len(raw):,} bytes) — file_id: `{file_id}`")

        # 파일 확장자 판별
        ext = fname.lower().rsplit(".", 1)[-1] if "." in fname else ""
        if ext not in ("pdf", "png", "jpg", "jpeg"):
            return [TextContent(type="text", text=f"❌ 지원하지 않는 형식: .{ext} (PDF/PNG/JPG만)")]

        # 2) PDF 벡터 텍스트 추출 (PDF일 때만)
        extracted_text = ""
        if ext == "pdf":
            extracted_text = _pdf_extract_text(raw)
            if extracted_text and "실패" not in extracted_text[:30]:
                progress.append(f"**2/3**  PDF 텍스트 추출: {len(extracted_text):,} chars")
            else:
                progress.append(f"**2/3**  PDF 텍스트 없음 (이미지 도면으로 처리)")
        else:
            progress.append(f"**2/3**  이미지 파일 — 텍스트 추출 생략")

        # 3) Gemini Vision (타입별 프롬프트)
        vision_out = ""
        if not skip_gem:
            with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tf:
                tf.write(raw)
                tmp_path = tf.name
            try:
                prompt = _DRAWING_PROMPTS.get(dtype, _DRAWING_PROMPTS["auto"])
                if query:
                    prompt += f"\n추가 초점: {query}\n"
                vision_out = await _gemini_analyze_file(tmp_path, prompt, timeout=300)
                progress.append(f"**3/3**  Gemini 시각 분석: {len(vision_out):,} chars")
            finally:
                try: os.unlink(tmp_path)
                except: pass
        else:
            progress.append(f"**3/3**  Gemini 건너뜀")

        # 4) Claude 종합
        try:
            synthesis = await _claude_synthesize_blueprint(vision_out, extracted_text, dtype, query)
        except Exception as e:
            synthesis = f"_(Claude 종합 실패: {e})_"

        # 5) RAG 인제스트
        ingest_summary = ""
        if ingest and file_id:
            try:
                r = await _ingest_blueprint_to_rag(
                    file_id=file_id, filename=fname, drawing_type=dtype,
                    vision_out=vision_out, extracted_text=extracted_text,
                    synthesis=synthesis, tags=tags,
                )
                ingest_summary = (
                    f"\n**RAG 인제스트 완료** (source: `{r['source']}`)\n"
                    f"- 벡터 텍스트 청크: {r['chunks_text']}개\n"
                    f"- Gemini 시각 분석: {r['chunk_vision']}\n"
                    f"- Claude 종합: {r['chunk_synthesis']}\n"
                    + (f"- 실패: {r['failed']}\n" if r['failed'] else "")
                    + f"\n이후 `quetta_blueprint_query(query=\"...\", filename=\"{fname}\")`로 질의하세요.\n"
                )
            except Exception as e:
                ingest_summary = f"\n_(RAG 인제스트 실패: {e})_\n"

        # 6) 최종 출력
        final  = "\n".join(progress) + "\n\n---\n\n"
        final += f"## 🔧 엔지니어링 분석 리포트 ({dtype})\n\n{synthesis}\n\n---\n"
        final += ingest_summary + "\n---\n\n"
        if vision_out:
            final += "<details><summary>👁 Gemini 시각 분석 원본</summary>\n\n"
            final += vision_out[:8000] + "\n\n</details>\n\n"
        if extracted_text and len(extracted_text) > 30:
            final += "<details><summary>📄 PDF 벡터 텍스트 (주석·치수)</summary>\n\n```\n"
            final += extracted_text[:6000] + ("\n\n[...]" if len(extracted_text) > 6000 else "")
            final += "\n```\n</details>\n"
        return [TextContent(type="text", text=final)]

    # ── quetta_blueprint_query ────────────────────────────────────────────────
    elif name == "quetta_blueprint_query":
        q        = arguments.get("query", "").strip()
        filename = arguments.get("filename", "").strip()
        dtype    = arguments.get("drawing_type", "").strip()
        do_list  = arguments.get("list", False)
        top_k    = arguments.get("top_k", 8)

        def _bp_hits(results: list) -> list:
            out = []
            for h in results:
                meta = h.get("metadata", {}) or {}
                if meta.get("type") != "blueprint": continue
                if filename and meta.get("filename") != filename: continue
                if dtype and meta.get("drawing_type") != dtype: continue
                out.append(h)
            return out

        if do_list or not q:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    f"{RAG_URL}/search",
                    json={"query": "blueprint drawing schematic diagram 설계도", "limit": 50, "mode": "rag"},
                    headers=_rag_headers(),
                )
            if resp.status_code != 200:
                return [TextContent(type="text", text=f"RAG 조회 실패 ({resp.status_code})")]
            body = resp.json()
            hits = body if isinstance(body, list) else body.get("results", [])
            bps = _bp_hits(hits)
            seen = {}
            for h in bps:
                meta = h.get("metadata", {}) or {}
                fn = meta.get("filename", "")
                dt = meta.get("drawing_type", "?")
                if fn and fn not in seen:
                    seen[fn] = {"dt": dt, "file_id": meta.get("file_id", ""), "chunks": 0}
                if fn: seen[fn]["chunks"] += 1
            if not seen:
                return [TextContent(type="text", text="인제스트된 설계도가 없습니다. `quetta_analyze_blueprint` 먼저 실행.")]
            lines = [f"## 인제스트된 설계도 ({len(seen)}개)\n"]
            for fn, info in seen.items():
                lines.append(f"- **{fn}**  [{info['dt']}]  청크 {info['chunks']}개, file_id: `{info['file_id']}`")
            return [TextContent(type="text", text="\n".join(lines))]

        # 질의
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{RAG_URL}/search",
                json={"query": q, "limit": max(top_k * 3, 20), "mode": "rag"},
                headers=_rag_headers(),
            )
            resp.raise_for_status()
            body = resp.json()
            all_hits = body if isinstance(body, list) else body.get("results", [])
            hits = _bp_hits(all_hits)[:top_k]

        if not hits:
            return [TextContent(type="text", text=f"관련 설계도 내용을 찾지 못했습니다.")]

        context = "\n\n".join(
            f"[출처: {h.get('source','?')}  type={h.get('metadata',{}).get('drawing_type','?')}  part={h.get('metadata',{}).get('part','?')}]\n"
            f"{h.get('text', h.get('content',''))[:1500]}"
            for h in hits[:top_k]
        )
        messages = [
            {"role": "system", "content": "당신은 설계도 분석 전문 엔지니어입니다. 제공된 도면 발췌를 근거로 한글로 정확히 답하세요. 치수·부품번호·신호명·핀번호 등은 원문 그대로 인용하세요."},
            {"role": "user", "content": f"질문: {q}\n\n=== 도면 발췌 ({len(hits)}개) ===\n{context}"},
        ]
        data = await gateway_chat(messages, model="claude-sonnet")
        answer = format_response(data)

        return [TextContent(type="text", text=(
            f"## 📐 설계도 질의 결과\n\n**질문:** {q}\n**필터:** {filename or '(전체)'} / {dtype or '모든 타입'}  |  참조: {len(hits)}개\n\n---\n\n{answer}"
        ))]

    # ── quetta_paper_query (RAG에 저장된 논문 검색/질의) ───────────────────────
    elif name == "quetta_paper_query":
        q        = arguments.get("query", "").strip()
        filename = arguments.get("filename", "").strip()
        do_list  = arguments.get("list", False)
        top_k    = arguments.get("top_k", 8)

        def _paper_hits(results: list) -> list:
            """RAG 결과에서 paper 타입만 필터, 선택적으로 filename 일치."""
            out = []
            for h in results:
                meta = h.get("metadata", {}) or {}
                if meta.get("type") != "paper": continue
                if filename and meta.get("filename") != filename: continue
                out.append(h)
            return out

        # 1) 인제스트된 논문 목록
        if do_list or not q:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    f"{RAG_URL}/search",
                    json={"query": "paper abstract title", "limit": 50, "mode": "rag"},
                    headers=_rag_headers(),
                )
            if resp.status_code != 200:
                return [TextContent(type="text", text=f"RAG 조회 실패 ({resp.status_code}): {resp.text[:300]}")]
            body = resp.json()
            hits = body if isinstance(body, list) else body.get("results", [])
            papers = _paper_hits(hits)
            seen: dict[str, dict] = {}
            for h in papers:
                meta = h.get("metadata", {}) or {}
                fn = meta.get("filename", "")
                if fn and fn not in seen:
                    seen[fn] = {"file_id": meta.get("file_id", ""), "chunks": 0}
                if fn: seen[fn]["chunks"] += 1
            if not seen:
                return [TextContent(type="text", text="인제스트된 논문이 없습니다. `quetta_analyze_paper`를 먼저 실행하세요.")]
            lines = [f"## 인제스트된 논문 ({len(seen)}개)\n"]
            for fn, info in seen.items():
                lines.append(f"- **{fn}**  (청크 {info['chunks']}개, file_id: `{info['file_id']}`)")
            return [TextContent(type="text", text="\n".join(lines))]

        # 2) 실제 질의
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{RAG_URL}/search",
                json={"query": q, "limit": max(top_k * 3, 20), "mode": "rag"},
                headers=_rag_headers(),
            )
            resp.raise_for_status()
            body = resp.json()
            all_hits = body if isinstance(body, list) else body.get("results", [])
            hits = _paper_hits(all_hits)[:top_k]

        if not hits:
            return [TextContent(type="text", text=f"관련 내용을 찾지 못했습니다 (filename={filename or '(전체)'}).")]

        context = "\n\n".join(
            f"[출처: {h.get('source','?')}  part={h.get('metadata',{}).get('part','?')}  chunk={h.get('metadata',{}).get('chunk_idx','?')}]\n"
            f"{h.get('text', h.get('content',''))[:1500]}"
            for h in hits[:top_k]
        )

        messages = [
            {"role": "system", "content": "당신은 학술 논문 분석 전문가입니다. 제공된 논문 발췌본을 근거로 한글로 정확히 답하세요. 인용할 때는 출처를 명시하세요."},
            {"role": "user", "content": f"질문: {q}\n\n=== 관련 논문 발췌 ({len(hits)}개) ===\n{context}"},
        ]
        data = await gateway_chat(messages, model="claude-sonnet")
        answer = format_response(data)

        return [TextContent(type="text", text=(
            f"## 📚 논문 질의 결과\n\n"
            f"**질문:** {q}\n"
            f"**필터:** {filename or '전체 논문'}  |  참조: {len(hits)}개 청크\n\n"
            f"---\n\n{answer}"
        ))]

    # ── 워크스페이스 (멀티 테넌트) ──────────────────────────────────────────────
    elif name == "quetta_workspace_list":
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{GATEWAY_URL}/workspace/me", headers=_auth_headers())
            resp.raise_for_status()
            d = resp.json()
        lines = [
            f"## 내 워크스페이스 정보",
            f"- user_hash: `{d.get('user_hash','?')}`",
            f"- 관리자: {'✅' if d.get('is_admin') else '❌'}",
            f"- 기본 워크스페이스: `{d.get('default','(없음)')}`",
            f"- 접근 가능: {d.get('allowed', []) or '(없음 — 관리자에게 요청)'}",
            "",
            "### 전체 워크스페이스",
        ]
        for w in d.get("all_workspaces", []):
            mark = "✅" if w.get("accessible") else "🔒"
            def_mark = " (기본)" if w.get("is_default") else ""
            lines.append(f"- {mark} **{w['name']}**{def_mark} — {w.get('label','')}: {w.get('description','')}")
        return [TextContent(type="text", text="\n".join(lines))]

    elif name == "quetta_workspace_request":
        ws = arguments["workspace"]
        reason = arguments.get("reason", "")
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{GATEWAY_URL}/workspace/request",
                headers=_auth_headers(),
                json={"workspace": ws, "reason": reason},
            )
            if resp.status_code != 200:
                return [TextContent(type="text", text=f"❌ 요청 실패: {resp.text[:300]}")]
            d = resp.json()
        status_map = {
            "already_granted": "✅ 이미 접근 권한이 있습니다.",
            "pending": f"⏳ 요청 접수됨 — 관리자 승인 대기 중.",
        }
        return [TextContent(type="text", text=status_map.get(d.get("status"), str(d)))]

    elif name == "quetta_admin_grant":
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{GATEWAY_URL}/workspace/acl/set",
                headers=_auth_headers(),
                json={"user_hash": arguments["user_hash"], "workspaces": arguments["workspaces"]},
            )
        if resp.status_code == 403:
            return [TextContent(type="text", text="❌ 관리자 권한이 필요합니다 (master API key).")]
        resp.raise_for_status()
        d = resp.json()
        return [TextContent(type="text", text=(
            f"✅ ACL 설정 완료\n"
            f"- 사용자: `{d['user_hash']}`\n"
            f"- 허용된 워크스페이스: {d['workspaces']}"
        ))]

    elif name == "quetta_admin_requests":
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{GATEWAY_URL}/workspace/requests", headers=_auth_headers())
        if resp.status_code == 403:
            return [TextContent(type="text", text="❌ 관리자 권한 필요")]
        resp.raise_for_status()
        reqs = resp.json()
        if not reqs:
            return [TextContent(type="text", text="대기 중인 접근 요청 없음.")]
        import datetime
        lines = [f"## ⏳ 대기 중인 접근 요청 ({len(reqs)}건)\n"]
        for r in reqs:
            ts = datetime.datetime.fromtimestamp(r["requested_at"]).strftime("%Y-%m-%d %H:%M")
            reason = f"\n  이유: {r.get('reason','-')}" if r.get("reason") else ""
            lines.append(f"- `{r['user_hash']}` → **{r['workspace']}** ({ts}){reason}")
        lines.append("\n승인: `quetta_admin_resolve(user_hash=..., workspace=..., approve=True)`")
        return [TextContent(type="text", text="\n".join(lines))]

    elif name == "quetta_admin_resolve":
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{GATEWAY_URL}/workspace/resolve",
                headers=_auth_headers(),
                json={
                    "user_hash": arguments["user_hash"],
                    "workspace": arguments["workspace"],
                    "approve":   arguments["approve"],
                    "reason":    arguments.get("reason", ""),
                },
            )
        if resp.status_code == 403:
            return [TextContent(type="text", text="❌ 관리자 권한 필요")]
        if resp.status_code != 200:
            return [TextContent(type="text", text=f"실패: {resp.text[:300]}")]
        d = resp.json()
        status = "✅ 승인됨" if d.get("approved") else "❌ 거부됨"
        return [TextContent(type="text", text=f"{status}: `{arguments['user_hash']}` → **{arguments['workspace']}**")]

    elif name == "quetta_admin_create_workspace":
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{GATEWAY_URL}/workspace/create",
                headers=_auth_headers(),
                json={
                    "name": arguments["name"],
                    "label": arguments.get("label", ""),
                    "description": arguments.get("description", ""),
                    "is_default": arguments.get("is_default", False),
                },
            )
        if resp.status_code == 403:
            return [TextContent(type="text", text="❌ 관리자 권한 필요")]
        if resp.status_code != 200:
            return [TextContent(type="text", text=f"실패: {resp.text[:300]}")]
        return [TextContent(type="text", text=f"✅ 워크스페이스 생성: `{arguments['name']}`")]

    # ── 대화 히스토리 (MongoDB) ────────────────────────────────────────────────
    elif name == "quetta_history_list":
        mine_only = arguments.get("mine_only", True)
        unified = arguments.get("unified", False)
        limit = arguments.get("limit", 30)

        params: dict = {"limit": limit}
        # mine_only이고 unified 아니면 내 키 hash 필터
        if mine_only and not unified and GATEWAY_API_KEY:
            import hashlib
            params["user_hash"] = hashlib.sha256(GATEWAY_API_KEY.encode()).hexdigest()[:16]

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{GATEWAY_URL}/history/sessions",
                params=params,
                headers=_auth_headers(),
            )
        if resp.status_code != 200:
            return [TextContent(type="text", text=f"히스토리 조회 실패: {resp.status_code}")]

        sessions = resp.json()
        if not sessions:
            scope = "전체" if unified else "내 계정"
            return [TextContent(type="text", text=f"{scope} 저장된 세션 없음.")]

        import datetime
        scope = "전체 사용자 통합" if unified else "내 계정"
        lines = [f"## 💬 대화 히스토리 ({scope}, {len(sessions)}개 세션)\n"]
        for s in sessions:
            first = datetime.datetime.fromtimestamp(s["first_ts"]).strftime("%m-%d %H:%M")
            last  = datetime.datetime.fromtimestamp(s["last_ts"]).strftime("%m-%d %H:%M")
            preview = s.get("preview", "")[:100]
            lines.append(f"- `{s['session_id']}`  ({s['count']}개 메시지, {first}~{last})")
            if preview: lines.append(f"  _\"{preview}...\"_")
        return [TextContent(type="text", text="\n".join(lines))]

    elif name == "quetta_history_get":
        sid = arguments["session_id"]
        limit = arguments.get("limit", 100)
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{GATEWAY_URL}/history/session/{sid}",
                params={"limit": limit},
                headers=_auth_headers(),
            )
        if resp.status_code != 200:
            return [TextContent(type="text", text=f"세션 조회 실패 {resp.status_code}: {resp.text[:200]}")]
        docs = resp.json()
        if not docs:
            return [TextContent(type="text", text=f"세션 `{sid}` 기록 없음.")]
        import datetime
        lines = [f"## 🗂 세션 `{sid}` ({len(docs)}개 메시지)\n"]
        for d in docs:
            ts = datetime.datetime.fromtimestamp(d["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
            backend = d.get("backend", "?")
            q = d.get("query", "")[:300]
            a = d.get("response", "")[:400]
            lines.append(f"### {ts}  [{backend}]")
            lines.append(f"**Q:** {q}")
            lines.append(f"**A:** {a}")
            lines.append("")
        return [TextContent(type="text", text="\n".join(lines))]

    elif name == "quetta_history_stats":
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{GATEWAY_URL}/history/stats", headers=_auth_headers())
        if resp.status_code != 200:
            return [TextContent(type="text", text=f"통계 조회 실패 {resp.status_code}")]
        d = resp.json()
        lines = [
            "## 📊 대화 히스토리 통계",
            f"- 총 대화 수: **{d.get('total_conversations', 0):,}**",
            f"- 고유 세션 수: **{d.get('unique_sessions', 0):,}**",
            f"- 고유 사용자 수: **{d.get('unique_users', 0):,}**",
            "",
            "### 백엔드별 분포",
        ]
        for bk, cnt in (d.get("by_backend") or {}).items():
            lines.append(f"- {bk}: {cnt:,}")
        return [TextContent(type="text", text="\n".join(lines))]

    # ── 공유 메모리 (멀티 계정 간 동기화) ──────────────────────────────────────
    elif name == "quetta_session_init":
        max_items = arguments.get("max_items", 10)
        sections: list[str] = []

        async with httpx.AsyncClient(timeout=20) as client:
            # 1) 사용자 메모리 (source=user-memory)
            try:
                r = await client.post(
                    f"{RAG_URL}/search", headers=_rag_headers(),
                    json={"query": "user profile preferences context",
                          "limit": 30, "mode": "hybrid"},
                )
                if r.status_code == 200:
                    body = r.json()
                    hits = body if isinstance(body, list) else body.get("sources") or body.get("results") or []
                    user_mem = [h for h in hits if h.get("source", "") == "user-memory"][:max_items]
                    if user_mem:
                        sections.append("### 👤 사용자 메모리")
                        for h in user_mem:
                            txt = (h.get("text") or "")[:300]
                            tags = (h.get("metadata", {}) or {}).get("tags", [])
                            tag_s = f"  _[{', '.join(tags)}]_" if tags else ""
                            sections.append(f"- {txt}{tag_s}")
            except Exception as e:
                sections.append(f"_(사용자 메모리 로드 실패: {e})_")

            # 2) 최근 저장된 Q&A (대화 이력)
            try:
                r = await client.post(
                    f"{RAG_URL}/search", headers=_rag_headers(),
                    json={"query": "최근 작업 recent project current task",
                          "limit": 10, "mode": "hybrid"},
                )
                if r.status_code == 200:
                    body = r.json()
                    hits = body if isinstance(body, list) else body.get("sources") or body.get("results") or []
                    qa_mem = [h for h in hits if h.get("source", "") == "quetta-gateway"][:5]
                    if qa_mem:
                        sections.append("\n### 💬 최근 대화 맥락")
                        for h in qa_mem:
                            txt = (h.get("text") or "")[:250]
                            sections.append(f"- {txt}")
            except Exception:
                pass

            # 3) 인제스트된 주요 문서 (type=paper/blueprint)
            try:
                r = await client.post(
                    f"{RAG_URL}/search", headers=_rag_headers(),
                    json={"query": "paper blueprint document 논문 설계도",
                          "limit": 30, "mode": "hybrid"},
                )
                if r.status_code == 200:
                    body = r.json()
                    hits = body if isinstance(body, list) else body.get("sources") or body.get("results") or []
                    docs = {}
                    for h in hits:
                        meta = h.get("metadata", {}) or {}
                        t = meta.get("type")
                        fn = meta.get("filename")
                        if t in ("paper", "blueprint") and fn and fn not in docs:
                            docs[fn] = t
                        if len(docs) >= max_items: break
                    if docs:
                        sections.append("\n### 📚 활성 문서")
                        for fn, t in docs.items():
                            sections.append(f"- [{t}] {fn}")
            except Exception:
                pass

        if not sections:
            return [TextContent(type="text", text=(
                "## 🎯 Quetta 세션 초기화\n\n"
                "_저장된 공유 메모리 없음._ `quetta_memory_save`로 사용자 메모리를 저장하면 "
                "다음 세션부터 자동 로드됩니다."
            ))]

        return [TextContent(type="text", text=(
            "## 🎯 Quetta 세션 초기화 (공유 메모리 로드)\n\n"
            + "\n".join(sections)
            + "\n\n_이 컨텍스트는 모든 Claude Code 계정에서 동일하게 공유됩니다._"
        ))]

    elif name == "quetta_memory_save":
        text = arguments["text"].strip()
        tags = arguments.get("tags", [])
        source = arguments.get("source", "user-memory")
        workspace = arguments.get("workspace", "").strip()
        if not text:
            return [TextContent(type="text", text="❌ text가 비어있습니다.")]

        # workspace 자동 추정 (사용자 기본값 조회)
        if not workspace:
            try:
                async with httpx.AsyncClient(timeout=5) as c:
                    r = await c.get(f"{GATEWAY_URL}/workspace/me", headers=_auth_headers())
                    if r.status_code == 200:
                        workspace = r.json().get("default", "development")
            except Exception:
                workspace = "development"

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{RAG_URL}/ingest",
                headers=_rag_headers(),
                json={
                    "text": text,
                    "source": source,
                    "metadata": {
                        "tags": tags,
                        "kind": "user-memory",
                        "workspace": workspace,
                    },
                    "update_mode": "extend",
                    "update_threshold": 0.90,
                },
            )
            resp.raise_for_status()
        return [TextContent(type="text", text=(
            f"✅ **메모리 저장 완료**\n\n"
            f"- workspace: `{workspace}`\n"
            f"- source: `{source}`\n"
            f"- tags: {tags or '(없음)'}\n"
            f"- 길이: {len(text):,} chars\n\n"
            f"이 워크스페이스에 접근 권한이 있는 사용자만 이 기억을 참조할 수 있습니다."
        ))]

    elif name == "quetta_memory_recall":
        q = arguments["query"].strip()
        limit = arguments.get("limit", 8)
        filter_source = arguments.get("filter_source", "").strip()
        if not q:
            return [TextContent(type="text", text="❌ query가 비어있습니다.")]

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{RAG_URL}/search",
                headers=_rag_headers(),
                json={"query": q, "limit": max(limit * 2, 15), "mode": "hybrid"},
            )
            resp.raise_for_status()
            body = resp.json()
            hits = body if isinstance(body, list) else body.get("sources") or body.get("results") or []

        if filter_source:
            hits = [h for h in hits if h.get("source", "") == filter_source]
        hits = hits[:limit]

        if not hits:
            return [TextContent(type="text", text=f"관련 기억을 찾지 못했습니다.")]

        lines = [f"## 🧠 메모리 검색 결과 ({len(hits)}개)\n"]
        for i, h in enumerate(hits, 1):
            score = h.get("score", 0)
            src = h.get("source", "?")
            text = (h.get("text") or h.get("content") or "")[:400]
            meta = h.get("metadata", {}) or {}
            tags = meta.get("tags", [])
            lines.append(f"### {i}. [{src}] score={score:.2f}")
            if tags: lines.append(f"_tags: {', '.join(tags)}_")
            lines.append(f"{text}")
            lines.append("")
        return [TextContent(type="text", text="\n".join(lines))]

    elif name == "quetta_memory_list":
        limit = arguments.get("limit", 20)
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{RAG_URL}/search",
                headers=_rag_headers(),
                json={"query": "사용자 메모리 user memory", "limit": 100, "mode": "hybrid"},
            )
            resp.raise_for_status()
            body = resp.json()
            hits = body if isinstance(body, list) else body.get("sources") or body.get("results") or []

        mine = [h for h in hits if h.get("source", "") == "user-memory"][:limit]
        if not mine:
            return [TextContent(type="text", text="저장된 사용자 메모리가 없습니다. `quetta_memory_save`로 저장하세요.")]

        lines = [f"## 내 메모리 ({len(mine)}개)\n"]
        for i, h in enumerate(mine, 1):
            text = (h.get("text") or "")[:200]
            meta = h.get("metadata", {}) or {}
            tags = meta.get("tags", [])
            lines.append(f"**{i}.** {text}")
            if tags: lines.append(f"   _tags: {', '.join(tags)}_")
            lines.append("")
        return [TextContent(type="text", text="\n".join(lines))]

    # ── quetta_auto (스마트 디스패처) ─────────────────────────────────────────
    elif name == "quetta_auto":
        req       = arguments["request"]
        agent_id  = arguments.get("agent_id", "")
        file_path = arguments.get("file_path", "")
        dry_run   = arguments.get("dry_run", False)

        intent, matched = _classify_intent(req)
        route_info = f"**[quetta_auto]** 의도: `{intent}`" + (
            f"  |  매칭: `{', '.join(matched)}`" if matched else ""
        )

        if dry_run:
            return [TextContent(type="text", text=route_info + "\n\n_(dry_run — 실행 생략)_")]

        # 의도별 내부 dispatch
        try:
            if intent == "memory_save":
                # "기억해줘: X" 패턴에서 X 추출
                body = req
                for prefix in ("기억해줘", "기억해", "저장해줘", "메모해", "외워줘", "remember this", "save this", "note this"):
                    if body.lower().startswith(prefix):
                        body = body[len(prefix):].strip(":：， ").strip()
                        break
                result = await call_tool("quetta_memory_save", {"text": body or req})
                return [TextContent(type="text", text=route_info), *result]

            elif intent == "memory_recall":
                result = await call_tool("quetta_memory_recall", {"query": req})
                return [TextContent(type="text", text=route_info), *result]

            elif intent == "memory_list":
                result = await call_tool("quetta_memory_list", {})
                return [TextContent(type="text", text=route_info), *result]

            elif intent == "blueprint_query":
                result = await call_tool("quetta_blueprint_query", {"query": req})
                return [TextContent(type="text", text=route_info), *result]

            elif intent == "blueprint_analysis":
                # 타입 추정
                low = req.lower()
                dt = "auto"
                if any(k in low for k in ["cpld", "fpga", "pcb", "verilog", "vhdl", "rtl"]):
                    dt = "cpld"
                elif any(k in low for k in ["전기", "회로도", "결선", "plc", "배전", "control"]):
                    dt = "electrical"
                elif any(k in low for k in ["기계", "gd&t", "조립", "부품도", "공차", "치수"]):
                    dt = "mechanical"
                inner_args = {"query": req, "drawing_type": dt}
                if file_path: inner_args["file_path"] = file_path
                result = await call_tool("quetta_analyze_blueprint", inner_args)
                return [TextContent(type="text", text=route_info), *result]

            elif intent == "paper_query":
                result = await call_tool("quetta_paper_query", {"query": req})
                return [TextContent(type="text", text=route_info), *result]

            elif intent == "paper_analysis":
                inner_args = {"query": req}
                if file_path: inner_args["file_path"] = file_path
                if agent_id:  inner_args["agent_id"]  = agent_id
                result = await call_tool("quetta_analyze_paper", inner_args)
                return [TextContent(type="text", text=route_info), *result]

            elif intent == "gpu_compute":
                cmd = _extract_shell_command(req)
                # agent_id 전달 시 해당 에이전트에 실행, 없으면 자동 GPU 선택
                inner_args = {"command": cmd, "timeout": 600}
                if agent_id:
                    inner_args["agent_id"] = agent_id
                result = await call_tool("quetta_gpu_exec", inner_args)
                return [TextContent(type="text", text=route_info), *result]

            elif intent == "screenshot":
                inner_args = {}
                if agent_id: inner_args["agent_id"] = agent_id
                result = await call_tool("quetta_remote_screenshot", inner_args)
                return [TextContent(type="text", text=route_info), *result]

            elif intent == "remote_shell":
                cmd = _extract_shell_command(req)
                inner_args = {"command": cmd, "timeout": 60}
                if agent_id: inner_args["agent_id"] = agent_id
                result = await call_tool("quetta_remote_shell", inner_args)
                return [TextContent(type="text", text=route_info), *result]

            elif intent == "file_analysis":
                inner_args = {"query": req}
                if file_path: inner_args["file_path"] = file_path
                else:         inner_args["content"]   = req
                result = await call_tool("quetta_analyze_file", inner_args)
                return [TextContent(type="text", text=route_info), *result]

            elif intent == "medical":
                result = await call_tool("quetta_medical", {"query": req})
                return [TextContent(type="text", text=route_info), *result]

            elif intent == "code":
                result = await call_tool("quetta_code", {"task": req})
                return [TextContent(type="text", text=route_info), *result]

            elif intent == "multi_agent":
                result = await call_tool("quetta_multi_agent", {"task": req})
                return [TextContent(type="text", text=route_info), *result]

            else:  # question (기본값)
                result = await call_tool("quetta_ask", {"query": req})
                return [TextContent(type="text", text=route_info), *result]

        except Exception as e:
            return [TextContent(
                type="text",
                text=f"{route_info}\n\n**실행 실패:** {e}"
            )]

    # ── quetta_gpu_status ─────────────────────────────────────────────────────
    elif name == "quetta_gpu_status":
        try:
            agents = await _relay_get("/agent/agents")
        except Exception as e:
            return [TextContent(type="text", text=f"에이전트 목록 조회 실패: {e}")]

        gpu_agents = [a for a in agents if _agent_has_gpu(a)]
        if not gpu_agents:
            return [TextContent(
                type="text",
                text="GPU 에이전트가 없습니다. `quetta_remote_connect(action='install-link')` 로 설치 링크를 받으세요."
            )]

        lines = ["## GPU 에이전트 상태", ""]
        for ag in gpu_agents:
            aid  = ag["id"]
            host = ag.get("hostname", "?")
            try:
                r = await _relay(aid, "shell", {
                    "command": "nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu --format=csv,noheader,nounits",
                    "timeout": 15,
                }, timeout=20)
                smi = r.get("data", {}).get("stdout", "").strip()
            except Exception as e:
                smi = f"(조회 실패: {e})"

            lines += [
                f"### {host} (`{aid}`)",
                f"- 선언된 GPU: {ag.get('gpu', '?')}",
                f"- 연결 시간: {ag.get('connected_sec', 0)}초",
                "",
                "```",
                "name, mem_used(MiB), mem_total(MiB), util(%), temp(C)",
                smi or "(출력 없음)",
                "```",
                "",
            ]
        return [TextContent(type="text", text="\n".join(lines))]

    # ── quetta_analyze_file ───────────────────────────────────────────────────
    elif name == "quetta_analyze_file":
        file_path_str = arguments.get("file_path", "").strip()
        content_str   = arguments.get("content", "")
        filename      = arguments.get("filename", "upload.txt")
        query         = arguments.get("query", "")
        source        = arguments.get("source", "")
        tags          = arguments.get("tags", [])

        # 1. 파일 읽기
        if file_path_str:
            import pathlib
            p = pathlib.Path(file_path_str)
            if not p.exists():
                return [TextContent(type="text", text=f"파일을 찾을 수 없습니다: `{file_path_str}`")]
            raw = p.read_bytes()
            filename = p.name
        elif content_str:
            raw = content_str.encode("utf-8")
        else:
            return [TextContent(type="text", text="`file_path` 또는 `content`를 지정하세요.")]

        # 2. TUS 업로드
        file_id = await _tus_upload(filename, raw)

        # 3. RAG 분석 엔드포인트 호출 (유형 감지 + 인제스트)
        analyze_body = {
            "usage_type": "measurement_data",  # analyze endpoint가 자동 결정
            "source": source or filename,
            "tags": tags,
            "chunk_size": 4000,
        }
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{RAG_URL}/upload/analyze/{file_id}",
                json=analyze_body,
                headers=_rag_headers(),
            )
            resp.raise_for_status()
            analyze = resp.json()

        file_type   = analyze.get("file_type", "document")
        type_reason = analyze.get("type_reason", "")
        excerpt     = analyze.get("text_excerpt", "")
        storage_path = analyze.get("storage_path", "")
        chunks_n    = analyze.get("chunks_ingested", 0)

        # 4. 분석 쿼리 작성
        type_labels = {
            "medical":     "의료 데이터",
            "signal_data": "신호/측정 데이터",
            "document":    "문서",
        }
        label = type_labels.get(file_type, "파일")
        user_query = query or f"이 {label}의 내용을 분석하고 핵심 정보를 요약해주세요."

        system_map = {
            "medical": (
                "You are a clinical AI assistant specializing in medical data analysis. "
                "Analyze the provided medical file content with clinical precision. "
                "Identify patient data, diagnoses, medications, lab results, or clinical findings. "
                "Provide structured clinical insights."
            ),
            "signal_data": (
                "You are a biomedical signal analysis expert. "
                "Analyze the provided measurement/signal data. "
                "Identify patterns, anomalies, statistical properties, and clinical relevance if applicable."
            ),
            "document": (
                "You are a document analysis assistant. "
                "Summarize the key information, main topics, and important findings from the document."
            ),
        }

        model_map = {
            "medical":     "medical",
            "signal_data": "auto",
            "document":    "auto",
        }

        ai_messages = [
            {"role": "system", "content": system_map.get(file_type, system_map["document"])},
            {"role": "user", "content": (
                f"파일: {filename}\n"
                f"유형: {label} ({type_reason})\n"
                f"저장 위치: {storage_path}\n\n"
                f"--- 파일 내용 (발췌) ---\n{excerpt[:1500]}\n--- 끝 ---\n\n"
                f"{user_query}"
            )},
        ]

        ai_data = await gateway_chat(ai_messages, model=model_map[file_type])
        ai_text = format_response(ai_data)

        lines = [
            f"## 파일 분석 결과: `{filename}`",
            "",
            f"| 항목 | 값 |",
            f"|------|-----|",
            f"| 파일 유형 | **{label}** ({type_reason}) |",
            f"| 저장 위치 | `{storage_path}` |",
            f"| 파일 ID | `{file_id}` |",
            f"| RAG 인제스트 | {chunks_n}청크 완료 |",
            f"| 크기 | {len(raw):,} bytes |",
            "",
            "---",
            "",
            ai_text,
        ]
        return [TextContent(type="text", text="\n".join(lines))]

    # ── quetta_upload_file ────────────────────────────────────────────────────
    elif name == "quetta_upload_file":
        file_path = arguments.get("file_path", "").strip()
        content_str = arguments.get("content", "")
        filename = arguments.get("filename", "upload.txt")

        if file_path:
            import pathlib
            p = pathlib.Path(file_path)
            if not p.exists():
                return [TextContent(type="text", text=f"파일을 찾을 수 없습니다: `{file_path}`")]
            raw = p.read_bytes()
            filename = p.name
        elif content_str:
            raw = content_str.encode("utf-8")
        else:
            return [TextContent(type="text", text="`file_path` 또는 `content`를 지정하세요.")]

        file_id = await _tus_upload(filename, raw)

        lines = [
            "**파일 업로드 완료**",
            f"- 파일명: `{filename}`",
            f"- 크기: {len(raw):,} bytes",
            f"- 파일 ID: `{file_id}`",
            "",
            f"`quetta_upload_process` 도구로 RAG에 인제스트할 수 있습니다.",
        ]
        return [TextContent(type="text", text="\n".join(lines))]

    # ── quetta_upload_list ────────────────────────────────────────────────────
    elif name == "quetta_upload_list":
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{RAG_URL}/upload/files", headers=_rag_headers())
            resp.raise_for_status()
            files = resp.json()

        if not files:
            return [TextContent(type="text", text="업로드된 파일이 없습니다.")]

        lines = [f"**업로드된 파일 목록** ({len(files)}개)\n"]
        for f in files:
            size = f.get("size", 0)
            offset = f.get("offset", 0)
            complete = f.get("complete", False)
            status = "완료" if complete else f"진행중 ({offset}/{size})"
            lines.append(f"- `{f['id']}` — **{f.get('filename') or '(이름없음)'}**")
            lines.append(f"  크기: {size:,} bytes  |  상태: {status}")
        return [TextContent(type="text", text="\n".join(lines))]

    # ── quetta_upload_process ─────────────────────────────────────────────────
    elif name == "quetta_upload_process":
        file_id = arguments["file_id"]
        body = {
            "usage_type": arguments.get("usage_type", "measurement_data"),
            "source": arguments.get("source", ""),
            "tags": arguments.get("tags", []),
            "chunk_size": arguments.get("chunk_size", 4000),
        }

        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{RAG_URL}/upload/process/{file_id}",
                json=body,
                headers=_rag_headers(),
            )
            resp.raise_for_status()
            data = resp.json()

        lines = [
            "**RAG 인제스트 완료**",
            f"- 파일: `{data.get('filename', file_id)}`",
            f"- 청크 수: {data.get('chunks_ingested', 0)}개",
            f"- 처리 시간: {data.get('processing_ms', 0):.0f}ms",
            f"- 상태: {data.get('status', '?')}",
        ]
        if data.get("message"):
            lines.append(f"- {data['message']}")
        return [TextContent(type="text", text="\n".join(lines))]

    # ── quetta_upload_process_all ─────────────────────────────────────────────
    elif name == "quetta_upload_process_all":
        body = {
            "usage_type": arguments.get("usage_type", "measurement_data"),
            "source": arguments.get("source", ""),
            "tags": arguments.get("tags", []),
            "chunk_size": arguments.get("chunk_size", 4000),
        }

        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{RAG_URL}/upload/process-all",
                json=body,
                headers=_rag_headers(),
            )
            resp.raise_for_status()
            data = resp.json()

        processed = data.get("processed", 0)
        files = data.get("files", [])

        lines = [f"**전체 파일 인제스트 완료** — {processed}개 처리\n"]
        for f in files:
            if "error" in f:
                lines.append(f"- `{f['file_id']}` — ❌ {f['error']}")
            else:
                lines.append(
                    f"- `{f.get('file_id', '?')}` **{f.get('filename', '')}** "
                    f"— {f.get('chunks', 0)}청크"
                )
        return [TextContent(type="text", text="\n".join(lines))]

    # ── quetta_version ───────────────────────────────────────────────────────────
    elif name == "quetta_version":
        latest = _get_latest_remote_version()
        uvx = _find_uvx() or "미설치"
        lines = [
            "**Quetta Agents MCP 버전 정보**",
            f"- 현재 버전: `{VERSION}`",
            f"- GitHub 최신: `{latest}`",
            f"- uvx 경로: `{uvx}`",
            f"- Gateway: `{GATEWAY_URL}`",
            f"- 인증: {'API 키 설정됨' if GATEWAY_API_KEY else '없음 (로컬)'}",
            "",
            "업데이트하려면 `quetta_update` 도구를 실행하세요.",
        ]
        return [TextContent(type="text", text="\n".join(lines))]

    # ── quetta_update ─────────────────────────────────────────────────────────
    elif name == "quetta_update":
        lines = ["**Quetta Agents MCP 업데이트 중...**", ""]
        success, output = await _run_update()
        if success:
            lines += [
                "✅ 업데이트 완료!",
                "",
                f"```\n{output}\n```" if output else "",
                "",
                "> **Claude Code를 재시작**해야 새 버전이 적용됩니다.",
            ]
        else:
            lines += [
                "❌ 업데이트 실패",
                "",
                f"```\n{output}\n```",
                "",
                "수동 업데이트:",
                "```bash",
                f'uvx --reinstall --from "{REPO_SSH}" quetta-agents-mcp',
                "```",
            ]
        return [TextContent(type="text", text="\n".join(lines))]

    return [TextContent(type="text", text=f"알 수 없는 도구: {name}")]


# ─── Main ─────────────────────────────────────────────────────────────────────

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def cli_main():
    """Sync entry point for uvx/pip install."""
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--version":
        print(f"quetta-agents-mcp {VERSION}")
        return
    asyncio.run(main())


if __name__ == "__main__":
    cli_main()
