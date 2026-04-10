#!/usr/bin/env python3
"""
Quetta Remote Agent — Claude Computer Use Bridge
원격 PC를 Claude MCP 도구로 제어할 수 있게 해주는 에이전트.

실행:
  python agent.py                    # 토큰 자동 생성
  python agent.py --token MY_TOKEN   # 토큰 지정
  python agent.py --port 7701        # 포트 지정

환경변수:
  QUETTA_AGENT_TOKEN  — 인증 토큰
  QUETTA_AGENT_PORT   — 포트 (기본 7701)
"""

import argparse
import base64
import io
import os
import platform
import secrets
import subprocess
import sys
import time
from typing import Optional

try:
    from fastapi import FastAPI, HTTPException, Security
    from fastapi.security.api_key import APIKeyHeader
    from pydantic import BaseModel
    import uvicorn
except ImportError:
    print("fastapi/uvicorn 미설치. 설치 중...")
    subprocess.run([sys.executable, "-m", "pip", "install",
                    "fastapi", "uvicorn[standard]", "pillow"], check=True)
    from fastapi import FastAPI, HTTPException, Security
    from fastapi.security.api_key import APIKeyHeader
    from pydantic import BaseModel
    import uvicorn

# GUI 제어 (선택적)
try:
    import pyautogui
    pyautogui.FAILSAFE = True
    HAS_GUI = True
except ImportError:
    HAS_GUI = False

# 스크린샷
try:
    import mss
    from PIL import Image
    HAS_SCREENSHOT = True
except ImportError:
    try:
        from PIL import ImageGrab, Image
        HAS_SCREENSHOT = True
        mss = None
    except ImportError:
        HAS_SCREENSHOT = False

# ── 전역 설정 ───────────────────────────────────────────────────────────────

TOKEN = os.getenv("QUETTA_AGENT_TOKEN", "")
app = FastAPI(
    title="Quetta Remote Agent",
    description="Claude Computer Use Bridge — 원격 PC 제어 에이전트",
    version="1.0.0",
)
api_key_header = APIKeyHeader(name="X-Agent-Token", auto_error=False)


def verify_token(token: str = Security(api_key_header)):
    if TOKEN and token != TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
    return token


# ── Models ─────────────────────────────────────────────────────────────────

class ClickRequest(BaseModel):
    x: int
    y: int
    button: str = "left"       # left / right / middle
    double: bool = False

class TypeRequest(BaseModel):
    text: str
    interval: float = 0.03     # 글자당 딜레이(초)

class KeyRequest(BaseModel):
    key: str                   # "ctrl+c", "enter", "alt+tab", "win" 등

class MoveRequest(BaseModel):
    x: int
    y: int
    duration: float = 0.2

class ScrollRequest(BaseModel):
    x: Optional[int] = None
    y: Optional[int] = None
    clicks: int = 3            # 양수 = 위, 음수 = 아래

class DragRequest(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int
    duration: float = 0.3

class ShellRequest(BaseModel):
    command: str
    timeout: int = 30
    cwd: Optional[str] = None

class ScreenshotRequest(BaseModel):
    max_width: int = 1280      # 리사이즈 최대 폭
    quality: int = 85          # JPEG 품질 (PNG면 무시)
    format: str = "png"        # png / jpeg


# ── Endpoints ──────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "hostname": platform.node(),
        "platform": platform.system(),
        "python": platform.python_version(),
        "has_gui": HAS_GUI,
        "has_screenshot": HAS_SCREENSHOT,
        "gpu": _detect_gpu(),
    }


@app.get("/screenshot")
async def screenshot(
    max_width: int = 1280,
    fmt: str = "png",
    _token=Security(verify_token),
):
    """현재 화면 스크린샷을 base64로 반환."""
    if not HAS_SCREENSHOT:
        raise HTTPException(500, "PIL/mss 미설치 — pip install mss pillow")

    if mss:
        with mss.mss() as sct:
            raw = sct.grab(sct.monitors[0])
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    else:
        img = ImageGrab.grab()

    # 리사이즈
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)

    buf = io.BytesIO()
    if fmt == "jpeg":
        img.save(buf, format="JPEG", quality=85)
        mime = "image/jpeg"
    else:
        img.save(buf, format="PNG")
        mime = "image/png"

    return {
        "image": base64.b64encode(buf.getvalue()).decode(),
        "mime": mime,
        "width": img.width,
        "height": img.height,
    }


@app.post("/click")
async def click(req: ClickRequest, _token=Security(verify_token)):
    _require_gui()
    if req.double:
        pyautogui.doubleClick(req.x, req.y, button=req.button)
    else:
        pyautogui.click(req.x, req.y, button=req.button)
    return {"ok": True, "x": req.x, "y": req.y}


@app.post("/type")
async def type_text(req: TypeRequest, _token=Security(verify_token)):
    _require_gui()
    # 특수문자 포함 텍스트는 pyperclip+paste 방식이 더 안정적
    try:
        import pyperclip
        pyperclip.copy(req.text)
        pyautogui.hotkey("ctrl", "v")
    except ImportError:
        pyautogui.write(req.text, interval=req.interval)
    return {"ok": True, "length": len(req.text)}


@app.post("/key")
async def press_key(req: KeyRequest, _token=Security(verify_token)):
    _require_gui()
    keys = [k.strip() for k in req.key.lower().split("+")]
    if len(keys) > 1:
        pyautogui.hotkey(*keys)
    else:
        pyautogui.press(keys[0])
    return {"ok": True, "key": req.key}


@app.post("/move")
async def move_mouse(req: MoveRequest, _token=Security(verify_token)):
    _require_gui()
    pyautogui.moveTo(req.x, req.y, duration=req.duration)
    return {"ok": True}


@app.post("/scroll")
async def scroll(req: ScrollRequest, _token=Security(verify_token)):
    _require_gui()
    kwargs = {"clicks": req.clicks}
    if req.x is not None:
        kwargs["x"] = req.x
    if req.y is not None:
        kwargs["y"] = req.y
    pyautogui.scroll(**kwargs)
    return {"ok": True}


@app.post("/drag")
async def drag(req: DragRequest, _token=Security(verify_token)):
    _require_gui()
    pyautogui.moveTo(req.x1, req.y1)
    pyautogui.dragTo(req.x2, req.y2, duration=req.duration, button="left")
    return {"ok": True}


@app.post("/shell")
async def shell_cmd(req: ShellRequest, _token=Security(verify_token)):
    """셸 명령어 실행. stdout/stderr 반환."""
    try:
        result = subprocess.run(
            req.command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=req.timeout,
            cwd=req.cwd,
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout[-8000:],
            "stderr": result.stderr[-2000:],
        }
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": f"Timeout ({req.timeout}s)"}
    except Exception as e:
        return {"returncode": -2, "stdout": "", "stderr": str(e)}


@app.get("/cursor")
async def get_cursor(_token=Security(verify_token)):
    """현재 마우스 커서 위치 반환."""
    _require_gui()
    x, y = pyautogui.position()
    return {"x": x, "y": y}


@app.get("/screen_size")
async def screen_size(_token=Security(verify_token)):
    """화면 해상도 반환."""
    _require_gui()
    w, h = pyautogui.size()
    return {"width": w, "height": h}


# ── Helpers ────────────────────────────────────────────────────────────────

def _require_gui():
    if not HAS_GUI:
        raise HTTPException(
            500,
            "pyautogui 미설치 — pip install pyautogui\n"
            "Linux headless: sudo apt install python3-tk python3-dev scrot"
        )


def _detect_gpu() -> str:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip().split("\n")[0]
    except Exception:
        pass
    try:
        out = subprocess.run(
            ["rocm-smi", "--showproductname"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            return "AMD GPU (ROCm)"
    except Exception:
        pass
    return "없음 (CPU only)"


# ── Entry Point ────────────────────────────────────────────────────────────

def main():
    global TOKEN

    parser = argparse.ArgumentParser(description="Quetta Remote Agent")
    parser.add_argument("--port", type=int, default=int(os.getenv("QUETTA_AGENT_PORT", "7701")))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--token", default="")
    args = parser.parse_args()

    if args.token:
        TOKEN = args.token
    if not TOKEN:
        TOKEN = secrets.token_hex(20)
        print(f"\n🔑 자동 생성 토큰: {TOKEN}")

    local_ip = _get_local_ip()

    print(f"""
╔══════════════════════════════════════════════╗
║         Quetta Remote Agent v1.0             ║
╠══════════════════════════════════════════════╣
║  내부 주소: http://{local_ip}:{args.port:<5}         ║
║  토큰: {TOKEN[:20]}...         ║
╠══════════════════════════════════════════════╣
║  Claude Code settings.json 에 추가:          ║
║  QUETTA_REMOTE_AGENT_URL=                    ║
║    http://{local_ip}:{args.port}             ║
║  QUETTA_REMOTE_AGENT_TOKEN={TOKEN[:16]}...   ║
╚══════════════════════════════════════════════╝
""")

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


def _get_local_ip() -> str:
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


if __name__ == "__main__":
    main()
