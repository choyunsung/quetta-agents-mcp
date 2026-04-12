# 10. 트러블슈팅

사용자가 자주 마주치는 문제와 해결 방법.

## 설치 관련

### "claude mcp list에 quetta-agents가 안 나옴"
```bash
# 1. 기존 설정 제거 후 재설치
claude mcp remove quetta-agents
curl -fsSL https://raw.githubusercontent.com/choyunsung/quetta-agents-mcp/master/install.sh | bash

# 2. 설치 확인
claude mcp list | grep quetta

# 3. Claude Code 완전 재시작
```

### "401 Unauthorized"
`QUETTA_API_KEY` 값이 잘못됐거나 누락됐습니다. 서비스 관리자에게 올바른 키를 요청하세요.

## 원격 제어 관련

### "원격 에이전트 미연결"
```python
# 연결 상태 확인
quetta_remote_connect(action="list")

# 없으면 설치 링크 받기
quetta_remote_connect(action="install-link", os="windows")
```

### "WebSocket 연결 끊김 → 자동 재연결"
에이전트는 자동으로 재연결합니다 (3초 → 60초 지수 백오프). 5~10초 후 다시 명령을 시도하세요.

### "화면 제어 불가"
→ `pyautogui` 미설치 가능성. 원격 PC에서:
```python
import pyautogui
print(pyautogui.size())
```

## 논문 분석 관련

### "GPU 에이전트가 없음"
Nougat OCR은 GPU가 필요합니다. Claude 채팅에서:
```
/remote-agent
```
→ GPU PC에 에이전트 설치 후 재시도.

### "Nougat 실행 실패"
```python
# 수동 설치 확인
quetta_remote_shell(command="pip show nougat-ocr")

# 재설치
quetta_analyze_paper(file_path="...", install_nougat=True)
```

### "Gemini 건너뛰어짐"
```bash
# Gemini CLI 설치 및 OAuth 로그인
npm i -g @google/gemini-cli
gemini
```

## 설계도 분석 관련

### "지원하지 않는 형식"
PDF / PNG / JPG만 지원됩니다. DWG는 사전 변환 필요:
```bash
# 예시 도구
libreoffice --headless --convert-to png drawing.dwg
```

### "PDF 텍스트 없음 (이미지 도면)"
스캔본 PDF인 경우 정상입니다. Gemini Vision만으로 분석 진행됩니다.

## 업로드 관련

### "upload_list 실패"
설정이 불완전할 수 있습니다. 재설치를 권장합니다:
```bash
claude mcp remove quetta-agents
QUETTA_GATEWAY_URL=https://rag.quetta-soft.com \
QUETTA_API_KEY=발급받은_키 \
bash <(curl -fsSL https://raw.githubusercontent.com/choyunsung/quetta-agents-mcp/master/install.sh)
```
install.sh 가 내부 설정을 자동으로 완성해줍니다.

### "업로드 후 file_id 분실"
```python
quetta_upload_list()   # 전체 업로드 목록 조회
```

## RAG 질의 관련

### "인제스트된 논문/설계도가 없음"
```python
# 확인
quetta_paper_query(list=True)
quetta_blueprint_query(list=True)

# 없으면 먼저 분석
quetta_analyze_paper(file_path="...")
quetta_analyze_blueprint(file_path="...")
```

### "관련 내용을 찾지 못함"
- 질문을 좀 더 구체적으로
- `top_k` 값 증가 (기본 8 → 15)
- `filename` 필터로 특정 파일 지정

## 일반

### "Claude Code 재시작 후 도구가 안 보임"
1. `claude mcp list`로 등록 상태 확인
2. Claude Code 완전 종료 후 재실행 (단순 새 창 열기 아님)
3. 그래도 안 되면:
   ```bash
   claude mcp remove quetta-agents
   # 재설치
   ```

### "버전 업데이트 후에도 옛날 도구만 보임"
```
quetta_version     # 현재 버전 확인
quetta_update      # 최신으로 업데이트
```
→ **Claude Code 재시작 필수.**

### 그 외 문제
GitHub Issues로 제보:
https://github.com/choyunsung/quetta-agents-mcp/issues

로그 첨부 시 개인정보·민감 정보는 마스킹해주세요.
