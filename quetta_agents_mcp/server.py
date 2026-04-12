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

VERSION          = "0.8.0"
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

# ── Intent Classification (스마트 디스패처) ────────────────────────────────────

_INTENT_RULES = {
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
}


def _classify_intent(text: str) -> tuple[str, list[str]]:
    """사용자 요청을 분류. 반환: (best_intent, matched_keywords).

    우선순위: gpu_compute > screenshot > remote_shell > file_analysis
             > medical > code > multi_agent > question (기본값)
    """
    low = text.lower()
    priority = ["gpu_compute", "screenshot", "remote_shell",
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
            if intent == "gpu_compute":
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
