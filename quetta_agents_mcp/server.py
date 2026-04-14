"""
Quetta Agents MCP Server — 씬 클라이언트 버전

▶ 기본 사용법: quetta_auto 하나로 모든 요청을 처리하세요.
  요청을 자동 분석해 의도에 맞는 도구/모델/에이전트로 라우팅합니다.
  개별 도구를 직접 선택할 필요가 없습니다.

아키텍처:
  - MCP는 씬 HTTP 클라이언트 — 모든 비즈니스 로직은 게이트웨이 서버에서 실행
  - 로컬 파일 I/O, GPU 에이전트 릴레이만 MCP에서 처리
  - 모든 LLM 라우팅, 분석, 메모리, RAG는 서버가 담당

Tools:
  quetta_auto             - ★ 기본 진입점: 의도 자동 분류 → 최적 도구/모델로 라우팅
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
  quetta_analyze_file     - 로컬 파일 업로드 → 유형 자동 감지 → AI 분석 (서버)
  quetta_analyze_blueprint - 설계도 분석 (Gemini + Claude + RAG, 서버)
  quetta_analyze_paper    - 논문 분석 (Nougat + Gemini + Claude, 서버)
  quetta_blueprint_query  - 저장된 설계도 RAG 검색
  quetta_paper_query      - 저장된 논문 RAG 검색
  quetta_upload_file      - 로컬 파일을 서버에 업로드
  quetta_upload_list      - 업로드된 파일 목록 조회
  quetta_upload_process   - 업로드된 파일을 RAG에 인제스트
  quetta_upload_process_all - 미처리 파일 전체 RAG 인제스트
  quetta_memory_save      - 공유 메모리 저장
  quetta_memory_recall    - 공유 메모리 검색
  quetta_memory_list      - 저장된 메모리 목록
  quetta_session_init     - 세션 시작 컨텍스트 로드
  quetta_workspace_list   - 워크스페이스 목록
  quetta_workspace_request - 워크스페이스 접근 요청
  quetta_admin_grant      - [관리자] 접근 권한 부여
  quetta_admin_requests   - [관리자] 대기 중인 접근 요청
  quetta_admin_resolve    - [관리자] 요청 승인/거부
  quetta_admin_create_workspace - [관리자] 워크스페이스 생성
  quetta_history_list     - 대화 히스토리 목록
  quetta_history_get      - 특정 세션 이력 조회
  quetta_history_stats    - 히스토리 통계
  quetta_gpu_exec         - GPU 에이전트에서 명령 실행
  quetta_gpu_python       - GPU 에이전트에서 Python 코드 실행
  quetta_gpu_status       - GPU 에이전트 상태 조회
  quetta_version          - 현재 버전 확인
  quetta_update           - 최신 버전으로 업데이트
"""

import asyncio
import base64
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
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

VERSION          = "0.15.0"
REPO_SSH         = "git+ssh://git@github.com/choyunsung/quetta-agents-mcp"
REPO_HTTPS       = "git+https://github.com/choyunsung/quetta-agents-mcp"

GATEWAY_URL      = os.getenv("QUETTA_GATEWAY_URL",      "http://localhost:8701")
ORCHESTRATOR_URL = os.getenv("QUETTA_ORCHESTRATOR_URL", "http://localhost:8700")
TIMEOUT          = float(os.getenv("QUETTA_TIMEOUT",    "300"))
GATEWAY_API_KEY  = os.getenv("QUETTA_API_KEY", "")

REMOTE_AGENT_ID  = os.getenv("QUETTA_REMOTE_AGENT_ID", "")

server = Server("quetta-agents")


# ─── HTTP Helpers ──────────────────────────────────────────────────────────────

def _auth_headers() -> dict:
    if GATEWAY_API_KEY:
        return {"Authorization": f"Bearer {GATEWAY_API_KEY}"}
    return {}


async def _gw_get(path: str, params: dict = {}) -> Any:
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.get(f"{GATEWAY_URL}{path}", params=params, headers=_auth_headers())
        r.raise_for_status()
        return r.json()


async def _gw_post(path: str, body: dict, timeout: float | None = None) -> Any:
    t = timeout or TIMEOUT
    async with httpx.AsyncClient(timeout=t) as c:
        r = await c.post(f"{GATEWAY_URL}{path}", json=body, headers=_auth_headers())
        r.raise_for_status()
        return r.json()


async def orch_get(path: str) -> Any:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{ORCHESTRATOR_URL}{path}", headers=_auth_headers())
        r.raise_for_status()
        return r.json()


async def orch_post(path: str, body: dict) -> Any:
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(f"{ORCHESTRATOR_URL}{path}", json=body, headers=_auth_headers())
        r.raise_for_status()
        return r.json()


async def gateway_chat(
    messages: list[dict],
    model: str = "auto",
    inject_skills: list[str] | None = None,
) -> dict:
    payload: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
    if inject_skills:
        payload["inject_skills"] = inject_skills
    return await _gw_post("/v1/chat/completions", payload)


def format_response(data: dict) -> str:
    text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    routing = data.get("routing", {})
    meta = []
    if routing.get("backend"):
        meta.append(f"모델: {routing['backend']} ({routing.get('model', '')})")
    if routing.get("injected_skills"):
        meta.append(f"스킬: {', '.join(routing['injected_skills'])}")
    if routing.get("multi_agent"):
        meta.append("멀티에이전트 (SCION)")
    if routing.get("is_medical"):
        meta.append(f"의료 도메인: {routing.get('medical_domain','')}")
    if meta:
        text += "\n\n---\n_[Quetta] " + "  |  ".join(meta) + "_"
    return text


# ─── Relay Helpers ────────────────────────────────────────────────────────────

async def _relay(agent_id: str, cmd_type: str, payload: dict = {}, timeout: float = 120) -> dict:
    async with httpx.AsyncClient(timeout=timeout + 5) as c:
        r = await c.post(
            f"{GATEWAY_URL}/agent/{agent_id}/cmd",
            json={"type": cmd_type, "payload": payload},
            headers=_auth_headers(),
            params={"timeout": timeout},
        )
        r.raise_for_status()
        return r.json()


_GPU_KEYWORDS = (
    "nvidia-smi", "cuda", "torch", "tensorflow", "tf.", "cupy",
    "jax.", "transformers", "accelerate", "deepspeed", "vllm",
    "ollama run", "llama.cpp", "onnxruntime-gpu", "mmdet", "yolov",
    "train.py", "inference.py", "finetune", "sd-webui", "comfyui",
    "whisper", "diffusers", "stable-diffusion",
)


def _needs_gpu(command: str) -> bool:
    low = command.lower()
    return any(kw in low for kw in _GPU_KEYWORDS)


def _agent_has_gpu(agent: dict) -> bool:
    gpu = (agent.get("gpu") or "").strip().lower()
    if not gpu:
        return False
    return not any(x in gpu for x in ("없음", "cpu only", "없 ", "none"))


async def _find_gpu_agent() -> dict | None:
    try:
        agents = await _gw_get("/agent/agents")
    except Exception:
        return None
    gpu_agents = [a for a in agents if _agent_has_gpu(a)]
    if not gpu_agents:
        return None
    gpu_agents.sort(key=lambda a: -a.get("connected_sec", 0))
    return gpu_agents[0]


async def _pick_agent(arguments: dict, prefer_gpu: bool = False) -> str:
    aid = arguments.get("agent_id", "").strip()
    if aid:
        return aid

    auto_gpu = prefer_gpu or _needs_gpu(arguments.get("command", ""))
    if auto_gpu:
        gpu_agent = await _find_gpu_agent()
        if gpu_agent:
            return gpu_agent["id"]
        try:
            link = await _gw_get("/agent/install-link", {"os": "linux"})
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

    try:
        agents = await _gw_get("/agent/agents")
    except Exception:
        agents = []
    if len(agents) == 1:
        return agents[0]["id"]

    raise ValueError(
        "agent_id 가 지정되지 않았습니다.\n"
        "`quetta_remote_connect` 를 먼저 실행해 연결된 에이전트 ID를 확인하세요."
    )


# ─── Local File Helpers ────────────────────────────────────────────────────────

def _read_local_file(file_path: str) -> tuple[bytes, str]:
    """로컬 파일을 읽어 (bytes, filename) 반환."""
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_path}")
    return p.read_bytes(), p.name


async def _upload_local_file(file_path: str = "", content: str = "",
                              filename: str = "upload.txt") -> tuple[str, str, int]:
    """로컬 파일 또는 텍스트를 게이트웨이 /v1/upload/file로 업로드.
    Returns (file_id, filename, size_bytes)
    """
    if file_path:
        raw, filename = _read_local_file(file_path)
    elif content:
        raw = content.encode("utf-8")
    else:
        raise ValueError("`file_path` 또는 `content`를 지정하세요.")

    content_b64 = base64.b64encode(raw).decode()
    result = await _gw_post(
        "/v1/upload/file",
        {"filename": filename, "content_b64": content_b64},
        timeout=120,
    )
    return result["file_id"], result["filename"], result["size"]


# ─── Version / Update Helpers ─────────────────────────────────────────────────

def _find_uvx() -> str | None:
    for candidate in ("uvx", os.path.expanduser("~/.local/bin/uvx"), "/usr/local/bin/uvx"):
        try:
            subprocess.run([candidate, "--version"], capture_output=True, check=True)
            return candidate
        except Exception:
            continue
    return None


def _get_latest_remote_version() -> str:
    try:
        import urllib.request
        url = "https://api.github.com/repos/choyunsung/quetta-agents-mcp/commits/master"
        req = urllib.request.Request(url, headers={"User-Agent": "quetta-agents-mcp"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
            sha  = data.get("sha", "")[:7]
            date = data.get("commit", {}).get("author", {}).get("date", "")[:10]
            return f"master@{sha} ({date})"
    except Exception:
        return "확인 불가"


async def _run_update() -> tuple[bool, str]:
    uvx = _find_uvx()
    if not uvx:
        return False, "`uvx`를 찾을 수 없습니다. https://docs.astral.sh/uv/ 에서 설치하세요."
    for repo in (REPO_SSH, REPO_HTTPS):
        cmd = [uvx, "--refresh", "--from", repo, "quetta-agents-mcp", "--version"]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            output = (stdout + stderr).decode().strip()
            if proc.returncode == 0 or "quetta" in output.lower():
                return True, output
        except asyncio.TimeoutError:
            return False, "업데이트 타임아웃 (120s). 네트워크를 확인하세요."
        except Exception:
            continue
    return False, "SSH/HTTPS 모두 실패. GitHub 접근 권한을 확인하세요."


def _extract_shell_command(text: str) -> str:
    m = re.search(r"```(?:\w+)?\s*\n?(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    m = re.search(r"`([^`]+)`", text)
    if m:
        return m.group(1).strip()
    return text.strip()


# ─── Tool Definitions ─────────────────────────────────────────────────────────

_QUETTA_AUTO_TOOL = Tool(
    name="quetta_auto",
    description=(
        "★ **Quetta 기본 진입점** — 어떤 요청이든 이 도구 하나로 처리하세요.\n\n"
        "요청 내용을 자동 분석해 최적 도구/모델/에이전트로 라우팅합니다.\n"
        "quetta_ask, quetta_code, quetta_medical 등 개별 도구를 직접 선택할 필요 없습니다.\n\n"
        "자동 라우팅 규칙:\n"
        "  • 기억 저장 ('기억해줘', 'remember this') → quetta_memory_save\n"
        "  • 기억 검색 ('뭐였지', '저번에') → quetta_memory_recall\n"
        "  • 설계도/도면 분석 → quetta_analyze_blueprint\n"
        "  • 논문 분석 (arxiv, .pdf, 수식) → quetta_analyze_paper\n"
        "  • GPU 계산 (cuda/torch/학습/추론) → quetta_gpu_exec\n"
        "  • 화면 캡처 → quetta_remote_screenshot\n"
        "  • 원격 셸 명령 → quetta_remote_shell\n"
        "  • 파일/문서 분석 → quetta_analyze_file\n"
        "  • 의료 질의 (진단/임상/환자) → quetta_medical (DeepSeek-R1)\n"
        "  • 코드 작업 (구현/리팩토링/버그) → quetta_code (Gemma4 + agent-skills)\n"
        "  • 아키텍처/복잡한 설계 → quetta_multi_agent (SCION 병렬)\n"
        "  • 그 외 일반 질문 → quetta_ask (Gemma4/Claude 자동 라우팅)\n\n"
        "dry_run=true로 실행 전 라우팅 결과만 미리 확인 가능."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "request": {
                "type": "string",
                "description": "자연어 요청 (한글/영문 자유). 원격 실행할 명령어는 백틱으로 감쌀 수 있음.",
            },
            "agent_id": {
                "type": "string",
                "description": "(선택) 원격 에이전트 ID — GPU/remote 의도로 분류될 때 자동 전달",
                "default": "",
            },
            "file_path": {
                "type": "string",
                "description": "(선택) 분석할 로컬 파일 경로 — 파일 분석 의도일 때 자동 업로드 후 서버에 전달",
                "default": "",
            },
            "dry_run": {
                "type": "boolean",
                "description": "true면 실행하지 않고 의도 분류·라우팅 결과만 반환",
                "default": False,
            },
        },
        "required": ["request"],
    },
)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        _QUETTA_AUTO_TOOL,
        Tool(
            name="quetta_ask",
            description=(
                "일반 질문·작업을 Quetta LLM 게이트웨이로 전송합니다. "
                "내용을 자동 분석해 최적 모델로 라우팅합니다.\n\n"
                "⚠ 일반적으로 quetta_auto가 이 도구를 자동으로 호출합니다."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query":         {"type": "string", "description": "질문 또는 작업 내용"},
                    "system_prompt": {"type": "string", "default": ""},
                    "model":         {"type": "string", "default": "auto"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="quetta_code",
            description=(
                "코드 개발 작업 전문 도구. agent-skills 5종 자동 주입.\n\n"
                "⚠ quetta_auto가 코드 의도를 감지하면 자동으로 이 도구를 호출합니다."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task":     {"type": "string"},
                    "language": {"type": "string", "default": ""},
                    "context":  {"type": "string", "default": ""},
                },
                "required": ["task"],
            },
        ),
        Tool(
            name="quetta_medical",
            description=(
                "의료 전문 질의 도구. DeepSeek-R1 임상 추론 모델 사용.\n\n"
                "⚠ quetta_auto가 의료 의도를 감지하면 자동으로 이 도구를 호출합니다."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query":  {"type": "string"},
                    "domain": {"type": "string", "default": "auto",
                               "enum": ["clinical", "diagnostic", "imaging", "research", "auto"]},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="quetta_multi_agent",
            description=(
                "복잡한 멀티스텝 태스크를 SCION 병렬 멀티에이전트로 실행합니다.\n\n"
                "⚠ quetta_auto가 복잡한 의도를 감지하면 자동으로 이 도구를 호출합니다."
            ),
            inputSchema={
                "type": "object",
                "properties": {"task": {"type": "string"}},
                "required": ["task"],
            },
        ),
        Tool(
            name="quetta_routing_info",
            description="특정 쿼리가 어떤 모델로 라우팅될지 미리 확인합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "model": {"type": "string", "default": "auto"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="quetta_list_agents",
            description="등록된 전문 에이전트 목록을 조회합니다.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="quetta_run_agent",
            description="특정 전문 에이전트에게 태스크를 위임합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_name":  {"type": "string"},
                    "title":       {"type": "string"},
                    "description": {"type": "string", "default": ""},
                },
                "required": ["agent_name", "title"],
            },
        ),
        Tool(
            name="quetta_remote_connect",
            description=(
                "연결된 원격 에이전트 목록을 조회하거나 설치 링크를 생성합니다.\n"
                "에이전트는 서버로 역방향 WebSocket을 연결하므로 포트포워딩 불필요."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list", "install-link"], "default": "list"},
                    "os":     {"type": "string", "enum": ["linux", "mac", "windows"], "default": "linux"},
                },
            },
        ),
        Tool(
            name="quetta_remote_screenshot",
            description="원격 PC의 현재 화면을 캡처해서 보여줍니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id":  {"type": "string", "default": ""},
                    "max_width": {"type": "integer", "default": 1280},
                },
            },
        ),
        Tool(
            name="quetta_remote_click",
            description="원격 PC에서 마우스 클릭을 실행합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "x":        {"type": "integer"},
                    "y":        {"type": "integer"},
                    "agent_id": {"type": "string", "default": ""},
                    "button":   {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
                    "double":   {"type": "boolean", "default": False},
                },
                "required": ["x", "y"],
            },
        ),
        Tool(
            name="quetta_remote_type",
            description="원격 PC에서 텍스트를 입력합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "text":     {"type": "string"},
                    "agent_id": {"type": "string", "default": ""},
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="quetta_remote_key",
            description="원격 PC에서 단축키를 입력합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "key":      {"type": "string", "description": "예: ctrl+c, alt+tab, enter"},
                    "agent_id": {"type": "string", "default": ""},
                },
                "required": ["key"],
            },
        ),
        Tool(
            name="quetta_remote_shell",
            description="원격 PC에서 셸 명령을 실행합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "command":   {"type": "string"},
                    "agent_id":  {"type": "string", "default": ""},
                    "timeout":   {"type": "integer", "default": 30},
                    "cwd":       {"type": "string", "default": ""},
                    "prefer_gpu": {"type": "boolean", "default": False},
                },
                "required": ["command"],
            },
        ),
        Tool(
            name="quetta_gpu_exec",
            description=(
                "GPU 에이전트에서 명령을 실행합니다. GPU 키워드 감지 시 자동 선택.\n\n"
                "⚠ quetta_auto가 GPU 의도를 감지하면 자동으로 이 도구를 호출합니다."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "command":  {"type": "string"},
                    "agent_id": {"type": "string", "default": ""},
                    "timeout":  {"type": "integer", "default": 300},
                    "cwd":      {"type": "string", "default": ""},
                },
                "required": ["command"],
            },
        ),
        Tool(
            name="quetta_gpu_python",
            description="Python 코드를 GPU 에이전트에서 직접 실행합니다 (CUDA/torch/ML 작업용).",
            inputSchema={
                "type": "object",
                "properties": {
                    "code":     {"type": "string", "description": "실행할 Python 코드"},
                    "agent_id": {"type": "string", "default": ""},
                    "timeout":  {"type": "integer", "default": 300},
                    "python":   {"type": "string", "default": "python"},
                },
                "required": ["code"],
            },
        ),
        Tool(
            name="quetta_gpu_status",
            description="연결된 모든 GPU 에이전트의 현재 상태를 요약합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "default": ""},
                },
            },
        ),
        Tool(
            name="quetta_analyze_file",
            description=(
                "로컬 파일을 서버에 업로드하고 AI로 분석합니다.\n"
                "파일 유형 자동 감지 → RAG 인제스트 → AI 분석 (의료/신호/문서).\n\n"
                "입력: file_path (로컬 경로) 또는 content + filename"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "default": "",
                                  "description": "분석할 로컬 파일 경로"},
                    "url":       {"type": "string", "default": "",
                                  "description": "파일 URL (MCP가 다운로드)"},
                    "content":   {"type": "string", "default": "",
                                  "description": "텍스트 내용 (file_path/url 미지정 시)"},
                    "filename":  {"type": "string", "default": "upload.txt"},
                    "query":     {"type": "string", "default": ""},
                    "source":    {"type": "string", "default": ""},
                    "tags":      {"type": "array", "items": {"type": "string"}, "default": []},
                },
            },
        ),
        Tool(
            name="quetta_analyze_blueprint",
            description=(
                "설계도/도면 분석:\n"
                "1. 로컬 파일 업로드 (TUS)\n"
                "2. Gemini CLI로 도면 시각 분석 (타입별 전문 프롬프트)\n"
                "3. Claude Sonnet이 두 결과를 통합해 엔지니어링 리포트 생성\n"
                "4. 결과를 RAG에 자동 인제스트 → `quetta_blueprint_query`로 재질의\n\n"
                "drawing_type: mechanical / electrical / cpld / auto"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path":    {"type": "string", "default": ""},
                    "file_id":      {"type": "string", "default": "",
                                     "description": "이미 업로드된 file_id (quetta_upload_file로 확보)"},
                    "query":        {"type": "string", "default": ""},
                    "drawing_type": {"type": "string", "default": "auto",
                                     "enum": ["auto", "mechanical", "electrical", "cpld"]},
                    "skip_gemini":  {"type": "boolean", "default": False},
                    "ingest_to_rag": {"type": "boolean", "default": True},
                    "tags":         {"type": "array", "items": {"type": "string"}, "default": []},
                },
            },
        ),
        Tool(
            name="quetta_analyze_paper",
            description=(
                "논문 PDF 분석:\n"
                "1. 로컬 파일 업로드 (TUS)\n"
                "2. Nougat (GPU 에이전트)으로 수식·텍스트 OCR\n"
                "3. Gemini CLI로 Figure/Table/수식 시각 분석\n"
                "4. Claude Sonnet이 종합해 논문 분석 리포트 생성\n"
                "5. 결과를 RAG에 자동 인제스트"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path":    {"type": "string", "default": ""},
                    "file_id":      {"type": "string", "default": ""},
                    "agent_id":     {"type": "string", "default": ""},
                    "query":        {"type": "string", "default": ""},
                    "skip_claude":  {"type": "boolean", "default": False},
                    "ingest_to_rag": {"type": "boolean", "default": True},
                    "tags":         {"type": "array", "items": {"type": "string"}, "default": []},
                },
            },
        ),
        Tool(
            name="quetta_blueprint_query",
            description=(
                "분석·인제스트된 설계도를 RAG에서 검색/질의.\n"
                "list=true로 인제스트된 설계도 목록 확인."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query":        {"type": "string", "default": ""},
                    "filename":     {"type": "string", "default": ""},
                    "drawing_type": {"type": "string", "default": ""},
                    "top_k":        {"type": "integer", "default": 8},
                    "list":         {"type": "boolean", "default": False},
                },
            },
        ),
        Tool(
            name="quetta_paper_query",
            description=(
                "분석·인제스트된 논문을 RAG에서 검색/질의.\n"
                "list=true로 인제스트된 논문 목록 확인."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query":    {"type": "string", "default": ""},
                    "filename": {"type": "string", "default": ""},
                    "top_k":    {"type": "integer", "default": 8},
                    "list":     {"type": "boolean", "default": False},
                },
            },
        ),
        Tool(
            name="quetta_upload_file",
            description=(
                "로컬 파일 또는 텍스트를 서버에 업로드합니다 (TUS 프로토콜, 대용량 지원).\n"
                "업로드 후 `quetta_upload_process`로 RAG에 인제스트할 수 있습니다."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "default": ""},
                    "content":   {"type": "string", "default": ""},
                    "filename":  {"type": "string", "default": "upload.txt"},
                },
            },
        ),
        Tool(
            name="quetta_upload_list",
            description="서버에 업로드된 파일 목록을 조회합니다.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="quetta_upload_process",
            description=(
                "업로드 완료된 파일을 RAG(지식베이스)에 인제스트합니다.\n"
                "file_id는 `quetta_upload_list`로 확인하세요."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id":    {"type": "string"},
                    "usage_type": {"type": "string", "default": "measurement_data"},
                    "source":     {"type": "string", "default": ""},
                    "tags":       {"type": "array", "items": {"type": "string"}, "default": []},
                    "chunk_size": {"type": "integer", "default": 4000},
                },
                "required": ["file_id"],
            },
        ),
        Tool(
            name="quetta_upload_process_all",
            description="업로드 완료된 모든 파일을 RAG에 인제스트합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "usage_type": {"type": "string", "default": "measurement_data"},
                    "source":     {"type": "string", "default": ""},
                    "tags":       {"type": "array", "items": {"type": "string"}, "default": []},
                    "chunk_size": {"type": "integer", "default": 4000},
                },
            },
        ),
        Tool(
            name="quetta_memory_save",
            description=(
                "**공유 메모리에 기억 저장** — 멀티 계정/세션에서 공유되는 영구 기억을 RAG에 저장합니다."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "text":      {"type": "string"},
                    "tags":      {"type": "array", "items": {"type": "string"}, "default": []},
                    "source":    {"type": "string", "default": "user-memory"},
                    "workspace": {"type": "string", "default": ""},
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="quetta_memory_recall",
            description=(
                "**공유 메모리에서 의미 검색** — 저장된 기억과 모든 인제스트된 문서에서 관련 내용을 찾습니다."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query":         {"type": "string"},
                    "limit":         {"type": "integer", "default": 8},
                    "filter_source": {"type": "string", "default": ""},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="quetta_memory_list",
            description="최근 저장된 사용자 메모리(`source=user-memory`) 목록을 반환합니다.",
            inputSchema={
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 20}},
            },
        ),
        Tool(
            name="quetta_session_init",
            description=(
                "**세션 시작 컨텍스트 로드** — 공유 RAG에서 사용자 프로필/활성 프로젝트/최근 기억을 반환합니다."
            ),
            inputSchema={
                "type": "object",
                "properties": {"max_items": {"type": "integer", "default": 10}},
            },
        ),
        Tool(
            name="quetta_workspace_list",
            description="내 접근 가능 워크스페이스 목록 + 전체 워크스페이스 조회.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="quetta_workspace_request",
            description="새로운 워크스페이스 접근 권한을 요청합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "workspace": {"type": "string"},
                    "reason":    {"type": "string", "default": ""},
                },
                "required": ["workspace"],
            },
        ),
        Tool(
            name="quetta_admin_grant",
            description="[관리자 전용] 특정 사용자에게 워크스페이스 접근 권한 부여.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_hash":  {"type": "string"},
                    "workspaces": {"type": "array", "items": {"type": "string"}},
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
            name="quetta_history_list",
            description="대화 히스토리 세션 목록.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit":     {"type": "integer", "default": 30},
                    "mine_only": {"type": "boolean", "default": True},
                    "unified":   {"type": "boolean", "default": False},
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
            description="저장된 전체 대화 히스토리 통계.",
            inputSchema={"type": "object", "properties": {}},
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
                "업데이트 후 Claude Code를 재시작해야 적용됩니다."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


# ─── Tool Handlers ────────────────────────────────────────────────────────────

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list:

    # ── quetta_auto → /v1/dispatch ────────────────────────────────────────────
    if name == "quetta_auto":
        req_text  = arguments["request"]
        agent_id  = arguments.get("agent_id", "")
        file_path = arguments.get("file_path", "")
        dry_run   = arguments.get("dry_run", False)

        file_id = ""
        if file_path and not dry_run:
            try:
                file_id, _, _ = await _upload_local_file(file_path=file_path)
            except Exception as e:
                return [TextContent(type="text", text=f"❌ 파일 업로드 실패: {e}")]

        data = await _gw_post("/v1/dispatch", {
            "request":  req_text,
            "agent_id": agent_id,
            "file_id":  file_id,
            "dry_run":  dry_run,
        })
        return [TextContent(type="text", text=data.get("text", str(data)))]

    # ── quetta_ask ────────────────────────────────────────────────────────────
    elif name == "quetta_ask":
        messages = []
        if arguments.get("system_prompt"):
            messages.append({"role": "system", "content": arguments["system_prompt"]})
        messages.append({"role": "user", "content": arguments["query"]})
        data = await gateway_chat(messages, model=arguments.get("model", "auto"))
        return [TextContent(type="text", text=format_response(data))]

    # ── quetta_code ───────────────────────────────────────────────────────────
    elif name == "quetta_code":
        content = arguments["task"]
        if arguments.get("language"):
            content = f"[언어: {arguments['language']}]\n\n{content}"
        if arguments.get("context"):
            content += f"\n\n[관련 코드/컨텍스트]\n{arguments['context']}"
        skills = ["plan", "build", "test", "code-review-and-quality", "security-and-hardening"]
        data = await gateway_chat([{"role": "user", "content": content}], model="auto",
                                  inject_skills=skills)
        return [TextContent(type="text", text=format_response(data))]

    # ── quetta_medical ────────────────────────────────────────────────────────
    elif name == "quetta_medical":
        domain = arguments.get("domain", "auto")
        if domain == "imaging":
            model = "claude-opus"
            msgs = [
                {"role": "system", "content": "You are a medical imaging specialist. Analyze radiological findings with clinical precision."},
                {"role": "user", "content": arguments["query"]},
            ]
        else:
            model, msgs = "medical", [{"role": "user", "content": arguments["query"]}]
        data = await gateway_chat(msgs, model=model)
        return [TextContent(type="text", text=format_response(data))]

    # ── quetta_multi_agent ────────────────────────────────────────────────────
    elif name == "quetta_multi_agent":
        msgs = [{"role": "user", "content": arguments["task"]}]
        data = await gateway_chat(msgs, model="auto")
        if not data.get("routing", {}).get("multi_agent"):
            msgs = [{"role": "user", "content": f"[멀티에이전트 병렬 실행 요청]\n\n{arguments['task']}"}]
            data = await gateway_chat(msgs, model="auto")
        return [TextContent(type="text", text=format_response(data))]

    # ── quetta_routing_info ───────────────────────────────────────────────────
    elif name == "quetta_routing_info":
        data = await _gw_get("/v1/routing/explain",
                              {"model": arguments.get("model", "auto"), "text": arguments["query"]})
        lines = [
            "**라우팅 결과**",
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
            lines.append(f"### {ag.get('name','?')}")
            lines.append(f"- 유형: `{ag.get('harness_type','?')}`  |  모델: `{ag.get('model_override') or 'auto'}`")
            if ag.get("skills"):
                lines.append(f"- 스킬: {', '.join(ag['skills'])}")
            if ag.get("description"):
                lines.append(f"- 설명: {ag['description']}")
            lines.append("")
        return [TextContent(type="text", text="\n".join(lines))]

    # ── quetta_run_agent ──────────────────────────────────────────────────────
    elif name == "quetta_run_agent":
        agents_data = await orch_get("/agents")
        agents = agents_data if isinstance(agents_data, list) else agents_data.get("agents", agents_data.get("items", []))
        agent = next((a for a in agents if a.get("name") == arguments["agent_name"]), None)
        if not agent:
            return [TextContent(type="text", text=f"에이전트 '{arguments['agent_name']}'을 찾을 수 없습니다.")]
        task_data = await orch_post("/tasks", {
            "title": arguments["title"],
            "description": arguments.get("description", ""),
            "agent_id": agent["id"],
            "priority": 5,
        })
        task_id = task_data.get("id", "?")
        exec_id = task_data.get("execution_id")
        lines = [f"**태스크 제출 완료**", f"- 에이전트: {arguments['agent_name']}", f"- 태스크 ID: `{task_id}`"]
        if exec_id:
            lines.append(f"- 실행 ID: `{exec_id}`")
            for _ in range(60):
                await asyncio.sleep(5)
                try:
                    edata = await orch_get(f"/executions/{exec_id}/events")
                    events = edata if isinstance(edata, list) else edata.get("events", [])
                    last = next((e for e in reversed(events)
                                 if e.get("event_type") == "state_transition"), None)
                    if last and last.get("payload", {}).get("new_state") in ("COMPLETED", "ERROR"):
                        lines.append(f"- 완료 상태: **{last['payload']['new_state']}**")
                        break
                except Exception:
                    pass
            else:
                lines.append("- 타임아웃: 실행 중 (백그라운드 계속 실행)")
        return [TextContent(type="text", text="\n".join(lines))]

    # ── quetta_remote_connect ─────────────────────────────────────────────────
    elif name == "quetta_remote_connect":
        action  = arguments.get("action", "list")
        os_type = arguments.get("os", "linux")
        if action == "install-link":
            data = await _gw_get(f"/agent/install-link", {"os": os_type})
            url  = data.get("url", "")
            lines = [f"## Quetta Remote Agent 설치 링크 ({os_type})", ""]
            if os_type == "windows":
                lines += ["```", f"# {url}", "# 위 URL을 브라우저에서 다운로드 후 실행", "```"]
            else:
                lines += ["```bash", f'curl -fsSL "{url}" | bash', "```"]
            lines += ["", f"- 링크 유효기간: {data.get('expires_in', '24시간')}", "",
                      "설치 후 에이전트가 자동으로 서버에 연결됩니다.",
                      "연결 확인: `quetta_remote_connect` (action=list)"]
            return [TextContent(type="text", text="\n".join(lines))]
        agents = await _gw_get("/agent/agents")
        if not agents:
            return [TextContent(type="text", text=(
                "## 연결된 원격 에이전트 없음\n\n설치 링크: `quetta_remote_connect(action='install-link')`"
            ))]
        lines = [f"## 연결된 원격 에이전트 ({len(agents)}개)\n"]
        for ag in agents:
            lines += [
                f"### ID: `{ag['id']}`",
                f"- 호스트: {ag.get('hostname','?')}  |  OS: {ag.get('platform','?')}",
                f"- GPU: **{ag.get('gpu','없음')}**",
                f"- 화면 제어: {'✅' if ag.get('has_gui') else '❌'}",
                "",
            ]
        return [TextContent(type="text", text="\n".join(lines))]

    # ── quetta_remote_screenshot ──────────────────────────────────────────────
    elif name == "quetta_remote_screenshot":
        aid  = arguments.get("agent_id", "").strip() or REMOTE_AGENT_ID
        if not aid:
            agents = await _gw_get("/agent/agents")
            if agents: aid = agents[0]["id"]
        if not aid:
            return [TextContent(type="text", text="❌ 연결된 에이전트가 없습니다.")]
        data = await _relay(aid, "screenshot", {"max_width": arguments.get("max_width", 1280)}, timeout=30)
        inner = data.get("data", data)
        img   = inner.get("image", "")
        mime  = inner.get("mime", "image/png")
        w, h  = inner.get("width", 0), inner.get("height", 0)
        return [
            ImageContent(type="image", data=img, mimeType=mime),
            TextContent(type="text", text=f"_화면: {w}×{h}px  |  에이전트: {aid}_"),
        ]

    # ── quetta_remote_click ───────────────────────────────────────────────────
    elif name == "quetta_remote_click":
        aid = await _pick_agent(arguments)
        await _relay(aid, "click", {
            "x": arguments["x"], "y": arguments["y"],
            "button": arguments.get("button", "left"),
            "double": arguments.get("double", False),
        }, timeout=10)
        return [TextContent(type="text", text=f"클릭: ({arguments['x']}, {arguments['y']})")]

    # ── quetta_remote_type ────────────────────────────────────────────────────
    elif name == "quetta_remote_type":
        aid = await _pick_agent(arguments)
        await _relay(aid, "type", {"text": arguments["text"]}, timeout=30)
        return [TextContent(type="text", text=f"입력 완료: {len(arguments['text'])}자")]

    # ── quetta_remote_key ─────────────────────────────────────────────────────
    elif name == "quetta_remote_key":
        aid = await _pick_agent(arguments)
        await _relay(aid, "key", {"key": arguments["key"]}, timeout=10)
        return [TextContent(type="text", text=f"키 입력: `{arguments['key']}`")]

    # ── quetta_remote_shell ───────────────────────────────────────────────────
    elif name == "quetta_remote_shell":
        aid  = await _pick_agent(arguments, prefer_gpu=arguments.get("prefer_gpu", False))
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
        lines  = [f"**[GPU]** `{arguments['command']}` → rc={inner.get('returncode',-1)}  _(agent: {aid})_"]
        if inner.get("stdout"): lines += ["```", inner["stdout"].strip()[-6000:], "```"]
        if inner.get("stderr"): lines += ["_stderr:_", "```", inner["stderr"].strip()[-2000:], "```"]
        return [TextContent(type="text", text="\n".join(lines))]

    # ── quetta_gpu_python ─────────────────────────────────────────────────────
    elif name == "quetta_gpu_python":
        aid    = await _pick_agent(arguments, prefer_gpu=True)
        tout   = arguments.get("timeout", 300)
        py_exe = arguments.get("python", "python")
        b64    = base64.b64encode(arguments["code"].encode("utf-8")).decode()
        runner = (
            f'{py_exe} -c "import base64,os,sys,tempfile;'
            f'd=base64.b64decode(\'{b64}\');'
            f'f=tempfile.NamedTemporaryFile(mode=\'wb\',suffix=\'.py\',delete=False);'
            f'f.write(d);f.close();'
            f'os.system(sys.executable+\' \'+f.name)"'
        )
        data = await _relay(aid, "shell", {"command": runner, "timeout": tout}, timeout=tout + 10)
        inner = data.get("data", data)
        lines = [f"**[GPU Python]** rc={inner.get('returncode',-1)}  _(agent: {aid})_"]
        if inner.get("stdout"): lines += ["```", inner["stdout"].strip()[-6000:], "```"]
        if inner.get("stderr"): lines += ["_stderr:_", "```", inner["stderr"].strip()[-2000:], "```"]
        return [TextContent(type="text", text="\n".join(lines))]

    # ── quetta_gpu_status ─────────────────────────────────────────────────────
    elif name == "quetta_gpu_status":
        try:
            agents = await _gw_get("/agent/agents")
        except Exception as e:
            return [TextContent(type="text", text=f"에이전트 목록 조회 실패: {e}")]
        gpu_agents = [a for a in agents if _agent_has_gpu(a)]
        if not gpu_agents:
            return [TextContent(type="text", text="GPU 에이전트가 없습니다.")]
        lines = ["## GPU 에이전트 상태", ""]
        for ag in gpu_agents:
            aid = ag["id"]
            try:
                r = await _relay(aid, "shell", {
                    "command": "nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu --format=csv,noheader,nounits",
                    "timeout": 15,
                }, timeout=20)
                smi = r.get("data", {}).get("stdout", "").strip()
            except Exception as e:
                smi = f"(조회 실패: {e})"
            lines += [
                f"### {ag.get('hostname','?')} (`{aid}`)",
                f"- GPU: {ag.get('gpu', '?')}",
                f"- 연결 시간: {ag.get('connected_sec', 0)}초",
                "",
                "```",
                "name, mem_used(MiB), mem_total(MiB), util(%), temp(C)",
                smi or "(데이터 없음)",
                "```",
                "",
            ]
        return [TextContent(type="text", text="\n".join(lines))]

    # ── quetta_analyze_file ───────────────────────────────────────────────────
    elif name == "quetta_analyze_file":
        file_path = arguments.get("file_path", "").strip()
        url       = arguments.get("url", "").strip()
        content   = arguments.get("content", "")
        filename  = arguments.get("filename", "upload.txt")

        file_id = ""
        if file_path:
            try:
                file_id, filename, _ = await _upload_local_file(file_path=file_path)
            except Exception as e:
                return [TextContent(type="text", text=f"❌ 파일 업로드 실패: {e}")]
        elif url:
            try:
                async with httpx.AsyncClient(timeout=120) as c:
                    r = await c.get(url)
                    r.raise_for_status()
                    raw = r.content
                filename = url.rsplit("/", 1)[-1] or filename
                content_b64 = base64.b64encode(raw).decode()
                res = await _gw_post("/v1/upload/file", {"filename": filename, "content_b64": content_b64}, timeout=120)
                file_id = res["file_id"]
            except Exception as e:
                return [TextContent(type="text", text=f"❌ URL 다운로드/업로드 실패: {e}")]

        data = await _gw_post("/v1/analyze/file", {
            "query":        arguments.get("query", ""),
            "file_id":      file_id,
            "content":      content if not file_id else "",
            "filename":     filename,
            "ingest_to_rag": True,
            "tags":         arguments.get("tags", []),
        }, timeout=300)
        return [TextContent(type="text", text=data.get("text", str(data)))]

    # ── quetta_analyze_blueprint ──────────────────────────────────────────────
    elif name == "quetta_analyze_blueprint":
        file_path = arguments.get("file_path", "").strip()
        file_id   = arguments.get("file_id", "").strip()

        if file_path and not file_id:
            try:
                file_id, _, _ = await _upload_local_file(file_path=file_path)
            except Exception as e:
                return [TextContent(type="text", text=f"❌ 파일 업로드 실패: {e}")]

        if not file_id and not file_path:
            return [TextContent(type="text", text="❌ `file_path` 또는 `file_id` 중 하나는 필수입니다.")]

        data = await _gw_post("/v1/analyze/blueprint", {
            "query":        arguments.get("query", ""),
            "file_id":      file_id,
            "drawing_type": arguments.get("drawing_type", "auto"),
            "skip_gemini":  arguments.get("skip_gemini", False),
            "ingest_to_rag": arguments.get("ingest_to_rag", True),
            "tags":         arguments.get("tags", []),
        }, timeout=600)
        return [TextContent(type="text", text=data.get("text", str(data)))]

    # ── quetta_analyze_paper ──────────────────────────────────────────────────
    elif name == "quetta_analyze_paper":
        file_path = arguments.get("file_path", "").strip()
        file_id   = arguments.get("file_id", "").strip()
        agent_id  = arguments.get("agent_id", "").strip()

        # GPU 에이전트 자동 선택 (Nougat 실행용)
        if not agent_id:
            try:
                gpu_agent = await _find_gpu_agent()
                if gpu_agent:
                    agent_id = gpu_agent["id"]
            except Exception:
                pass

        if file_path and not file_id:
            try:
                file_id, _, _ = await _upload_local_file(file_path=file_path)
            except Exception as e:
                return [TextContent(type="text", text=f"❌ 파일 업로드 실패: {e}")]

        if not file_id:
            return [TextContent(type="text", text="❌ `file_path` 또는 `file_id` 중 하나는 필수입니다.")]

        data = await _gw_post("/v1/analyze/paper", {
            "query":        arguments.get("query", ""),
            "file_id":      file_id,
            "agent_id":     agent_id,
            "skip_claude":  arguments.get("skip_claude", False),
            "ingest_to_rag": arguments.get("ingest_to_rag", True),
            "tags":         arguments.get("tags", []),
        }, timeout=1800)
        return [TextContent(type="text", text=data.get("text", str(data)))]

    # ── quetta_blueprint_query ────────────────────────────────────────────────
    elif name == "quetta_blueprint_query":
        data = await _gw_post("/v1/analyze/blueprint_query", {
            "query":        arguments.get("query", ""),
            "filename":     arguments.get("filename", ""),
            "drawing_type": arguments.get("drawing_type", ""),
            "limit":        arguments.get("top_k", 8),
        }, timeout=30)
        return [TextContent(type="text", text=data.get("text", str(data)))]

    # ── quetta_paper_query ────────────────────────────────────────────────────
    elif name == "quetta_paper_query":
        data = await _gw_post("/v1/analyze/paper_query", {
            "query":    arguments.get("query", ""),
            "filename": arguments.get("filename", ""),
            "limit":    arguments.get("top_k", 8),
        }, timeout=30)
        return [TextContent(type="text", text=data.get("text", str(data)))]

    # ── quetta_upload_file ────────────────────────────────────────────────────
    elif name == "quetta_upload_file":
        try:
            file_id, filename, size = await _upload_local_file(
                file_path=arguments.get("file_path", ""),
                content=arguments.get("content", ""),
                filename=arguments.get("filename", "upload.txt"),
            )
        except Exception as e:
            return [TextContent(type="text", text=f"❌ 업로드 실패: {e}")]
        return [TextContent(type="text", text=(
            f"**파일 업로드 완료**\n"
            f"- 파일명: `{filename}`\n"
            f"- 크기: {size:,} bytes\n"
            f"- 파일 ID: `{file_id}`\n\n"
            f"`quetta_upload_process` 도구로 RAG에 인제스트할 수 있습니다."
        ))]

    # ── quetta_upload_list ────────────────────────────────────────────────────
    elif name == "quetta_upload_list":
        data = await _gw_get("/v1/upload/list")
        return [TextContent(type="text", text=data.get("text", str(data)))]

    # ── quetta_upload_process ─────────────────────────────────────────────────
    elif name == "quetta_upload_process":
        file_id = arguments["file_id"]
        data = await _gw_post(f"/v1/upload/process/{file_id}", {
            "file_id":    file_id,
            "usage_type": arguments.get("usage_type", "measurement_data"),
            "source":     arguments.get("source", ""),
            "tags":       arguments.get("tags", []),
            "chunk_size": arguments.get("chunk_size", 4000),
        }, timeout=300)
        return [TextContent(type="text", text=data.get("text", str(data)))]

    # ── quetta_upload_process_all ─────────────────────────────────────────────
    elif name == "quetta_upload_process_all":
        data = await _gw_post("/v1/upload/process-all", {
            "usage_type": arguments.get("usage_type", "measurement_data"),
            "source":     arguments.get("source", ""),
            "tags":       arguments.get("tags", []),
            "chunk_size": arguments.get("chunk_size", 4000),
        }, timeout=600)
        return [TextContent(type="text", text=data.get("text", str(data)))]

    # ── quetta_memory_save ────────────────────────────────────────────────────
    elif name == "quetta_memory_save":
        data = await _gw_post("/v1/memory/save", {
            "text":      arguments["text"],
            "tags":      arguments.get("tags", []),
            "source":    arguments.get("source", "user-memory"),
            "workspace": arguments.get("workspace", ""),
        }, timeout=30)
        return [TextContent(type="text", text=data.get("text", str(data)))]

    # ── quetta_memory_recall ──────────────────────────────────────────────────
    elif name == "quetta_memory_recall":
        data = await _gw_post("/v1/memory/recall", {
            "query":         arguments["query"],
            "limit":         arguments.get("limit", 8),
            "filter_source": arguments.get("filter_source", ""),
        }, timeout=30)
        return [TextContent(type="text", text=data.get("text", str(data)))]

    # ── quetta_memory_list ────────────────────────────────────────────────────
    elif name == "quetta_memory_list":
        data = await _gw_get("/v1/memory/list", {"limit": arguments.get("limit", 20)})
        return [TextContent(type="text", text=data.get("text", str(data)))]

    # ── quetta_session_init ───────────────────────────────────────────────────
    elif name == "quetta_session_init":
        data = await _gw_get("/v1/memory/session/init", {"max_items": arguments.get("max_items", 10)})
        return [TextContent(type="text", text=data.get("text", str(data)))]

    # ── 워크스페이스 ─────────────────────────────────────────────────────────────
    elif name == "quetta_workspace_list":
        d = await _gw_get("/workspace/me")
        lines = [
            "## 내 워크스페이스 정보",
            f"- user_hash: `{d.get('user_hash','?')}`",
            f"- 관리자: {'✅' if d.get('is_admin') else '❌'}",
            f"- 기본 워크스페이스: `{d.get('default','(없음)')}`",
            f"- 접근 가능: {d.get('allowed', []) or '(없음)'}",
            "",
            "### 전체 워크스페이스",
        ]
        for w in d.get("all_workspaces", []):
            mark = "✅" if w.get("accessible") else "🔒"
            lines.append(f"- {mark} **{w['name']}**{' (기본)' if w.get('is_default') else ''} — {w.get('label','')}")
        return [TextContent(type="text", text="\n".join(lines))]

    elif name == "quetta_workspace_request":
        data = await _gw_post("/workspace/request", {
            "workspace": arguments["workspace"],
            "reason":    arguments.get("reason", ""),
        }, timeout=10)
        status_map = {
            "already_granted": "✅ 이미 접근 권한이 있습니다.",
            "pending": "⏳ 요청 접수됨 — 관리자 승인 대기 중.",
        }
        return [TextContent(type="text", text=status_map.get(data.get("status"), str(data)))]

    elif name == "quetta_admin_grant":
        data = await _gw_post("/workspace/acl/set", {
            "user_hash":  arguments["user_hash"],
            "workspaces": arguments["workspaces"],
        })
        return [TextContent(type="text", text=(
            f"✅ ACL 설정 완료\n- 사용자: `{data['user_hash']}`\n- 허용: {data['workspaces']}"
        ))]

    elif name == "quetta_admin_requests":
        reqs = await _gw_get("/workspace/requests")
        if not reqs:
            return [TextContent(type="text", text="대기 중인 접근 요청 없음.")]
        import datetime
        lines = [f"## ⏳ 대기 중인 접근 요청 ({len(reqs)}건)\n"]
        for r in reqs:
            ts = datetime.datetime.fromtimestamp(r["requested_at"]).strftime("%Y-%m-%d %H:%M")
            lines.append(f"- `{r['user_hash']}` → **{r['workspace']}** ({ts})")
        return [TextContent(type="text", text="\n".join(lines))]

    elif name == "quetta_admin_resolve":
        data = await _gw_post("/workspace/resolve", {
            "user_hash": arguments["user_hash"],
            "workspace": arguments["workspace"],
            "approve":   arguments["approve"],
            "reason":    arguments.get("reason", ""),
        })
        return [TextContent(type="text", text=(
            ("✅ 승인됨" if data.get("approved") else "❌ 거부됨") +
            f": `{arguments['user_hash']}` → **{arguments['workspace']}**"
        ))]

    elif name == "quetta_admin_create_workspace":
        await _gw_post("/workspace/create", {
            "name":        arguments["name"],
            "label":       arguments.get("label", ""),
            "description": arguments.get("description", ""),
            "is_default":  arguments.get("is_default", False),
        })
        return [TextContent(type="text", text=f"✅ 워크스페이스 생성: `{arguments['name']}`")]

    # ── 대화 히스토리 ─────────────────────────────────────────────────────────────
    elif name == "quetta_history_list":
        params: dict = {"limit": arguments.get("limit", 30)}
        if arguments.get("mine_only", True) and not arguments.get("unified", False) and GATEWAY_API_KEY:
            import hashlib
            params["user_hash"] = hashlib.sha256(GATEWAY_API_KEY.encode()).hexdigest()[:16]
        sessions = await _gw_get("/history/sessions", params)
        if not sessions:
            return [TextContent(type="text", text="저장된 세션 없음.")]
        import datetime
        lines = [f"## 💬 대화 히스토리 ({len(sessions)}개 세션)\n"]
        for s in sessions:
            first = datetime.datetime.fromtimestamp(s["first_ts"]).strftime("%m-%d %H:%M")
            last  = datetime.datetime.fromtimestamp(s["last_ts"]).strftime("%m-%d %H:%M")
            lines.append(f"- `{s['session_id']}`  ({s['count']}개 메시지, {first}~{last})")
            if s.get("preview"):
                lines.append(f"  _\"{s['preview'][:100]}...\"_")
        return [TextContent(type="text", text="\n".join(lines))]

    elif name == "quetta_history_get":
        docs = await _gw_get(f"/history/session/{arguments['session_id']}",
                              {"limit": arguments.get("limit", 100)})
        if not docs:
            return [TextContent(type="text", text=f"세션 `{arguments['session_id']}` 기록 없음.")]
        import datetime
        lines = [f"## 🗂 세션 `{arguments['session_id']}` ({len(docs)}개 메시지)\n"]
        for d in docs:
            ts = datetime.datetime.fromtimestamp(d["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
            lines += [f"### {ts}  [{d.get('backend','?')}]",
                      f"**Q:** {d.get('query','')[:300]}",
                      f"**A:** {d.get('response','')[:400]}", ""]
        return [TextContent(type="text", text="\n".join(lines))]

    elif name == "quetta_history_stats":
        d = await _gw_get("/history/stats")
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

    # ── quetta_version ────────────────────────────────────────────────────────
    elif name == "quetta_version":
        latest = _get_latest_remote_version()
        uvx    = _find_uvx() or "미설치"
        return [TextContent(type="text", text=(
            f"**Quetta Agents MCP 버전 정보**\n"
            f"- 현재 버전: `{VERSION}`\n"
            f"- GitHub 최신: `{latest}`\n"
            f"- uvx 경로: `{uvx}`\n"
            f"- Gateway: `{GATEWAY_URL}`\n"
            f"- 인증: {'API 키 설정됨' if GATEWAY_API_KEY else '없음 (로컬)'}\n\n"
            f"업데이트하려면 `quetta_update` 도구를 실행하세요."
        ))]

    # ── quetta_update ─────────────────────────────────────────────────────────
    elif name == "quetta_update":
        success, output = await _run_update()
        if success:
            return [TextContent(type="text", text=(
                f"✅ 업데이트 완료!\n\n```\n{output}\n```\n\n"
                f"> **Claude Code를 재시작**해야 새 버전이 적용됩니다."
            ))]
        return [TextContent(type="text", text=(
            f"❌ 업데이트 실패\n\n```\n{output}\n```\n\n"
            f"수동 업데이트:\n```bash\nuvx --reinstall --from \"{REPO_SSH}\" quetta-agents-mcp\n```"
        ))]

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
    if len(sys.argv) > 1 and sys.argv[1] == "--version":
        print(f"quetta-agents-mcp {VERSION}")
        return
    asyncio.run(main())


if __name__ == "__main__":
    cli_main()
