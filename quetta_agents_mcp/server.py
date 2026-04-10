"""
Quetta Agents MCP Server

Claude 채팅 중 자동으로 최적 모델을 선택해 질문을 처리합니다:
- 의료 질문 → DeepSeek-R1 (임상/진단) 또는 Claude Opus (영상)
- 코드 작업 → Gemma4 + agent-skills 자동 주입
- 복잡한 멀티스텝 → SCION 병렬 멀티에이전트
- 단순 질문 → Gemma4 (로컬·무료)

Tools:
  quetta_ask          - 질문을 보내면 최적 모델이 자동으로 응답
  quetta_code         - 코드 개발 작업 (agent-skills 5종 자동 주입)
  quetta_medical      - 의료 전문 질의 (DeepSeek-R1 임상 추론)
  quetta_multi_agent  - 복잡한 멀티스텝 태스크 (SCION 병렬 실행)
  quetta_routing_info - 요청이 어떤 모델로 라우팅될지 설명
  quetta_list_agents  - 등록된 전문 에이전트 목록
  quetta_run_agent    - 특정 에이전트에게 태스크 위임
  quetta_version      - 현재 버전 및 GitHub 최신 커밋 확인
  quetta_update       - GitHub 최신 버전으로 자동 업데이트
"""

import asyncio
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
    CallToolResult,
)

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
logger = logging.getLogger(__name__)

VERSION          = "0.2.0"
REPO_SSH         = "git+ssh://git@github.com/choyunsung/quetta-agents-mcp"
REPO_HTTPS       = "git+https://github.com/choyunsung/quetta-agents-mcp"

GATEWAY_URL      = os.getenv("QUETTA_GATEWAY_URL",      "http://localhost:8701")
ORCHESTRATOR_URL = os.getenv("QUETTA_ORCHESTRATOR_URL", "http://localhost:8700")
TIMEOUT          = float(os.getenv("QUETTA_TIMEOUT",    "300"))
GATEWAY_API_KEY  = os.getenv("QUETTA_API_KEY", "")   # Set for external access

server = Server("quetta-agents")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _auth_headers() -> dict:
    """Return auth headers if API key is configured."""
    if GATEWAY_API_KEY:
        return {"Authorization": f"Bearer {GATEWAY_API_KEY}"}
    return {}


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
