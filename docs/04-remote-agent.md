# 04. 원격 에이전트 (Remote Agent)

다른 PC(GPU 서버, 개인 컴퓨터)를 원격 제어합니다. 에이전트가 서버로 **역방향 WebSocket**을 연결하므로 포트포워딩/방화벽 설정 불필요.

## 아키텍처

```
[Claude MCP] ──▶ [Quetta Gateway] ──▶ [Remote Agent PC]
                                      (역방향 WebSocket 연결)
```

- 에이전트가 서버로 **역방향 연결**하므로 사용자 PC에 별도 포트 개방 불필요
- 네트워크 단절 시 자동 재연결
- 24시간 유효 설치 링크

## 에이전트 설치

### 방법 1: `/remote-agent` 스킬 (권장)
Claude Code에서:
```
/remote-agent
```
→ 설치 링크 표시 + 연결 자동 감지 (최대 10분 대기)

### 방법 2: 수동
```bash
# Linux/Mac
curl -fsSL "https://rag.quetta-soft.com/agent/download?token=XXX&os=linux" | bash

# Windows (PowerShell 또는 CMD)
# 브라우저에서 install-quetta-agent.bat 다운로드 후 실행
```

### 설치 과정
1. Python 3.9+ 확인
2. `websockets`, `pyautogui`, `mss`, `pillow`, `pyperclip` 설치
3. `~/.quetta-remote-agent/agent.py` 생성 + `.env`에 URL/토큰 저장
4. 에이전트 즉시 실행 (WS 연결)

## 연결된 에이전트 확인

```python
quetta_remote_connect(action="list")
# → ID / 호스트 / OS / GPU / 화면제어 / 스크린샷
```

## 원격 제어 도구

| 도구 | 파라미터 | 설명 |
|------|---------|------|
| `quetta_remote_screenshot` | `agent_id`, `max_width?` | 화면 캡처 (Claude가 이미지 분석) |
| `quetta_remote_click` | `x, y, button?, double?` | 마우스 클릭 |
| `quetta_remote_type` | `text, interval?` | 텍스트 입력 (클립보드 경유) |
| `quetta_remote_key` | `key` (e.g. `ctrl+c`) | 단축키 |
| `quetta_remote_shell` | `command, timeout?, cwd?` | 셸 명령 (GPU 키워드 자동) |

## GPU 자동 라우팅

명령어에 **GPU 키워드**(cuda, torch, nvidia-smi, train.py 등)가 포함되면 agent_id 미지정 시 자동으로 GPU 에이전트 선택:

```python
# agent_id 없이도 GPU 에이전트 자동 선택
quetta_remote_shell(command="nvidia-smi")
quetta_gpu_exec(command="python train.py --epochs 100")
quetta_gpu_python(code="""
import torch
print(torch.cuda.get_device_name(0))
""")
```

**`_pick_agent()` 선택 로직:**
1. `agent_id` 명시 → 사용
2. GPU 키워드 감지 or `prefer_gpu=True` → GPU 에이전트 자동
3. `REMOTE_AGENT_ID` 환경변수 → 사용
4. 연결 에이전트가 1개뿐 → 자동
5. GPU 필요한데 없음 → 설치 링크 반환 후 에러

## Windows 백그라운드 서비스

설치 후 로그온 시 자동 시작되도록 구성할 수 있습니다 (콘솔 창 없이 실행). 설치 스크립트가 자동 생성한 VBS 파일을 시작프로그램 폴더에 복사하면 됩니다.

## 보안

- 설치 링크: **24시간** 유효, 1회성
- 원격 에이전트 연결: 토큰 인증
- 모든 통신: TLS 암호화

## 트러블슈팅

자주 발생하는 문제는 [10. 트러블슈팅](./10-operations.md) 참고.

## 관련 문서

- [스마트 디스패처](./03-smart-dispatcher.md)
- [도구 레퍼런스](./08-tools-reference.md)
