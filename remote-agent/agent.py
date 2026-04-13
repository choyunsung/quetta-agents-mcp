#!/usr/bin/env python3
"""
Quetta Remote Agent — WebSocket 클라이언트
서버(rag.quetta-soft.com)에 역방향 WebSocket으로 연결해서
Claude의 명령(스크린샷/클릭/키보드/셸 등)을 실행한다.

환경변수(.env):
  AGENT_WS_URL   — wss://rag.quetta-soft.com/agent/ws
  AGENT_TOKEN    — 서버에서 발급한 인증 토큰

실행:
  python agent.py
"""

import asyncio
import base64
import io
import json
import os
import platform
import subprocess
import sys

# pythonw / Windows Service Session 0 환경: stdout/stderr가 None
# print() 호출 시 AttributeError로 즉시 종료되는 것 방지
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

# Windows cp949 콘솔에서 이모지/한글 출력 시 UnicodeEncodeError 방지
# (Python 3.7+ — reconfigure 미지원 환경은 silent skip)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── 설정 ────────────────────────────────────────────────────────────────────

AGENT_WS_URL = os.getenv("AGENT_WS_URL", "")
AGENT_TOKEN  = os.getenv("AGENT_TOKEN",  "")

# ── 의존성 자동 설치 ─────────────────────────────────────────────────────────

def _pip_install(*pkgs):
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--upgrade", *pkgs], check=True)

try:
    import websockets
except ImportError:
    print("websockets 설치 중...")
    _pip_install("websockets")
    import websockets

# GUI/스크린샷 모듈 — Service Session 0 등 비대화형 환경에서도 임포트 실패 허용
# (단순 ImportError 가 아닌 RuntimeError, AttributeError 등 모두 catch)
HAS_GUI = False
HAS_SS = False
_USE_MSS = False
try:
    import pyautogui
    pyautogui.FAILSAFE = True
    HAS_GUI = True
except Exception as _e:
    print(f"⚠ pyautogui 초기화 실패 (비대화형 환경 OK): {_e}", flush=True)

try:
    import mss
    from PIL import Image
    HAS_SS = True
    _USE_MSS = True
except Exception as _e:
    print(f"⚠ mss 초기화 실패: {_e}", flush=True)
    try:
        from PIL import ImageGrab, Image
        HAS_SS = True
    except Exception as _e2:
        print(f"⚠ PIL ImageGrab 도 실패: {_e2}", flush=True)


# ── 명령 핸들러 ───────────────────────────────────────────────────────────────

def _health(_p=None):
    gpu = _detect_gpu()
    return {
        "hostname":        platform.node(),
        "platform":        platform.system(),
        "python":          platform.python_version(),
        "gpu":             gpu,
        "has_gui":         HAS_GUI,
        "has_screenshot":  HAS_SS,
    }


def _detect_gpu() -> str:
    for cmd in (
        ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
        ["rocm-smi", "--showproductname"],
    ):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip().split("\n")[0]
        except Exception:
            pass
    return "없음 (CPU only)"


def _screenshot(p):
    if not HAS_SS:
        return {"error": "mss/pillow 미설치 — pip install mss pillow"}
    max_w = p.get("max_width", 1280)

    if _USE_MSS:
        with mss.mss() as s:
            raw = s.grab(s.monitors[0])
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    else:
        img = ImageGrab.grab()

    if img.width > max_w:
        ratio = max_w / img.width
        img = img.resize((max_w, int(img.height * ratio)), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return {
        "image":  base64.b64encode(buf.getvalue()).decode(),
        "mime":   "image/png",
        "width":  img.width,
        "height": img.height,
    }


def _click(p):
    if not HAS_GUI:
        return {"error": "pyautogui 미설치"}
    x, y = p["x"], p["y"]
    btn  = p.get("button", "left")
    if p.get("double"):
        pyautogui.doubleClick(x, y, button=btn)
    else:
        pyautogui.click(x, y, button=btn)
    return {"ok": True, "x": x, "y": y}


def _type(p):
    if not HAS_GUI:
        return {"error": "pyautogui 미설치"}
    text = p["text"]
    try:
        import pyperclip
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
    except ImportError:
        pyautogui.write(text, interval=p.get("interval", 0.03))
    return {"ok": True, "length": len(text)}


def _key(p):
    if not HAS_GUI:
        return {"error": "pyautogui 미설치"}
    keys = [k.strip() for k in p["key"].lower().split("+")]
    if len(keys) > 1:
        pyautogui.hotkey(*keys)
    else:
        pyautogui.press(keys[0])
    return {"ok": True, "key": p["key"]}


def _move(p):
    if not HAS_GUI:
        return {"error": "pyautogui 미설치"}
    pyautogui.moveTo(p["x"], p["y"], duration=p.get("duration", 0.2))
    return {"ok": True}


def _scroll(p):
    if not HAS_GUI:
        return {"error": "pyautogui 미설치"}
    kw = {"clicks": p.get("clicks", 3)}
    if p.get("x") is not None: kw["x"] = p["x"]
    if p.get("y") is not None: kw["y"] = p["y"]
    pyautogui.scroll(**kw)
    return {"ok": True}


def _shell(p):
    try:
        r = subprocess.run(
            p["command"], shell=True,
            capture_output=True, text=True,
            timeout=p.get("timeout", 30),
            cwd=p.get("cwd") or None,
        )
        return {
            "returncode": r.returncode,
            "stdout":     r.stdout[-8000:],
            "stderr":     r.stderr[-2000:],
        }
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": "Timeout"}
    except Exception as e:
        return {"returncode": -2, "stdout": "", "stderr": str(e)}


HANDLERS = {
    "health":     _health,
    "screenshot": _screenshot,
    "click":      _click,
    "type":       _type,
    "key":        _key,
    "move":       _move,
    "scroll":     _scroll,
    "shell":      _shell,
}


# ── WebSocket 연결 루프 ───────────────────────────────────────────────────────

async def run():
    if not AGENT_WS_URL:
        print("AGENT_WS_URL 이 설정되지 않았습니다. .env 파일을 확인하세요.")
        sys.exit(1)

    url = f"{AGENT_WS_URL}?token={AGENT_TOKEN}"
    reconnect_delay = 3

    while True:
        try:
            print(f"→ 연결 중: {AGENT_WS_URL}")
            async with websockets.connect(
                url,
                ping_interval=30,
                ping_timeout=15,
                close_timeout=5,
            ) as ws:
                # Hello: 에이전트 정보 전송
                await ws.send(json.dumps({"type": "hello", "info": _health()}))
                h = _health()
                print(f"✅ 연결 완료! — {h['hostname']} | GPU: {h['gpu']}")
                reconnect_delay = 3  # 성공 시 리셋

                async for raw in ws:
                    cmd     = json.loads(raw)
                    cmd_id  = cmd.get("id")
                    handler = HANDLERS.get(cmd.get("type", ""))

                    try:
                        result = handler(cmd.get("payload", {})) if handler \
                                 else {"error": f"알 수 없는 명령: {cmd.get('type')}"}
                        await ws.send(json.dumps({
                            "id": cmd_id, "status": "ok", "data": result,
                        }))
                    except Exception as e:
                        await ws.send(json.dumps({
                            "id": cmd_id, "status": "error", "error": str(e),
                        }))

        except Exception as e:
            print(f"✗ 연결 끊김: {e}")
            print(f"  {reconnect_delay}초 후 재연결...")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 60)


if __name__ == "__main__":
    print(f"""
╔══════════════════════════════════════════════╗
║         Quetta Remote Agent                  ║
║  서버로 역방향 WebSocket 연결                 ║
╚══════════════════════════════════════════════╝
  서버: {AGENT_WS_URL or '(AGENT_WS_URL 미설정)'}
""")
    asyncio.run(run())
