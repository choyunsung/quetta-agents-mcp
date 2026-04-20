# Quetta Agents MCP — Windows PowerShell Installer
# Usage:
#   iwr -useb https://raw.githubusercontent.com/choyunsung/quetta-agents-mcp/master/install.ps1 | iex
#
# With Gist:
#   $env:QUETTA_GIST_ID="..."; iwr -useb .../install.ps1 | iex
#
# With invite token:
#   $env:QUETTA_INSTALL_TOKEN="..."; iwr -useb .../install.ps1 | iex

$ErrorActionPreference = "Stop"

function Info($msg)    { Write-Host "▶ $msg" -ForegroundColor Cyan }
function Success($msg) { Write-Host "✓ $msg" -ForegroundColor Green }
function Warn($msg)    { Write-Host "⚠ $msg" -ForegroundColor Yellow }
function Fail($msg)    { Write-Host "✗ $msg" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "   Quetta Agents MCP Installer (Windows)" -ForegroundColor Cyan
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host ""

# ── 변수 ────────────────────────────────────────────────────────────────────
$RepoHttps = "git+https://github.com/choyunsung/quetta-agents-mcp"
$GatewayUrl = if ($env:QUETTA_GATEWAY_URL) { $env:QUETTA_GATEWAY_URL } else { "" }
$GistId = $env:QUETTA_GIST_ID
$InstallToken = $env:QUETTA_INSTALL_TOKEN
$ApiKey = $env:QUETTA_API_KEY
$RagUrl = $env:QUETTA_RAG_URL
$TusdUrl = $env:QUETTA_TUSD_URL
$TusdToken = $env:QUETTA_TUSD_TOKEN
$RagKey = if ($env:QUETTA_RAG_KEY) { $env:QUETTA_RAG_KEY } else { "" }
$OrchUrl = $env:QUETTA_ORCHESTRATOR_URL
$Timeout = if ($env:QUETTA_TIMEOUT) { $env:QUETTA_TIMEOUT } else { "300" }

# ── 1. uv/uvx 확인 및 설치 ───────────────────────────────────────────────────
$uvxCmd = Get-Command uvx -ErrorAction SilentlyContinue
if (-not $uvxCmd) {
    Info "uvx 미설치 — 자동 설치 중..."
    try {
        powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
        # PATH 갱신
        $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
    } catch {
        Fail "uv 설치 실패. 수동 설치: https://docs.astral.sh/uv/getting-started/installation/"
    }
    $uvxCmd = Get-Command uvx -ErrorAction SilentlyContinue
    if (-not $uvxCmd) {
        Fail "uv 설치됐으나 PATH에 반영 안됨. 터미널 재시작 후 재실행하세요."
    }
    Success "uv 설치 완료: $(uvx --version 2>&1 | Select-Object -First 1)"
} else {
    Success "uv 발견: $(uvx --version 2>&1 | Select-Object -First 1)"
}
$UvxPath = (Get-Command uvx).Source

# ── 2. claude CLI 확인 ───────────────────────────────────────────────────────
$ClaudeCmd = Get-Command claude -ErrorAction SilentlyContinue
if (-not $ClaudeCmd) {
    Warn "claude CLI 미설치 — 먼저 Claude Code를 설치하세요: https://claude.ai/download"
    Warn "설치 후 이 스크립트를 다시 실행하세요."
    exit 1
}

# ── 3. Config 조회 ───────────────────────────────────────────────────────────
function Load-FromGist($gistId) {
    # 방법 1: gh CLI
    $ghCmd = Get-Command gh -ErrorAction SilentlyContinue
    if ($ghCmd) {
        try {
            $content = gh api "/gists/$gistId" --jq '.files | to_entries[0].value.content' 2>$null
            if ($content) { return $content }
        } catch {}
    }
    # 방법 2: GH_TOKEN
    $tok = if ($env:GH_TOKEN) { $env:GH_TOKEN } else { $env:GITHUB_TOKEN }
    if ($tok) {
        try {
            $resp = Invoke-RestMethod -Uri "https://api.github.com/gists/$gistId" `
                -Headers @{ Authorization = "token $tok"; Accept = "application/vnd.github+json" }
            $firstFile = $resp.files.PSObject.Properties | Select-Object -First 1
            return $firstFile.Value.content
        } catch {}
    }
    # 방법 3: public Gist fallback
    try {
        $resp = Invoke-RestMethod -Uri "https://api.github.com/gists/$gistId"
        $firstFile = $resp.files.PSObject.Properties | Select-Object -First 1
        return $firstFile.Value.content
    } catch {
        return $null
    }
}

# 대화형 입력
if (-not $ApiKey -and -not $GistId -and -not $InstallToken -and -not $env:QUETTA_NONINTERACTIVE) {
    Write-Host ""
    Info "관리자에게 받은 **Gist ID** 또는 **초대 토큰**을 입력하세요."
    $GistId = Read-Host "Gist ID (비우면 skip)"
    if (-not $GistId) {
        $InstallToken = Read-Host "초대 토큰 (QUETTA_INSTALL_TOKEN)"
    }
}

# Gist에서 config 로드
if ($GistId -and -not $ApiKey) {
    Info "GitHub Gist에서 설정 불러오는 중 ($GistId)..."
    $jsonText = Load-FromGist $GistId
    if (-not $jsonText) {
        Fail "Gist 접근 실패. 비공개 Gist면 'gh auth login' 또는 GH_TOKEN 환경변수 설정"
    }
    try {
        $cfg = $jsonText | ConvertFrom-Json
        if ($cfg.gateway_url) { $GatewayUrl = $cfg.gateway_url }
        $ApiKey = $cfg.api_key
        $RagUrl = $cfg.rag_url
        $TusdUrl = $cfg.tusd_url
        $TusdToken = $cfg.tusd_token
        if ($cfg.rag_key) { $RagKey = $cfg.rag_key }
        $OrchUrl = $cfg.orchestrator_url
        if ($cfg.timeout) { $Timeout = [string]$cfg.timeout }
        Success "Gist 설정 로드 완료"
    } catch {
        Fail "Gist JSON 파싱 실패: $_"
    }
}

# 초대 토큰으로 Gateway 조회
if ($InstallToken -and -not $ApiKey) {
    Info "초대 토큰 검증 중..."
    if (-not $GatewayUrl) { $GatewayUrl = "https://rag.quetta-soft.com" }
    try {
        $cfg = Invoke-RestMethod -Uri "$GatewayUrl/install/config?token=$InstallToken" -TimeoutSec 10
        if ($cfg.gateway_url) { $GatewayUrl = $cfg.gateway_url }
        $ApiKey = $cfg.api_key
        $RagUrl = $cfg.rag_url
        $TusdUrl = $cfg.tusd_url
        $TusdToken = $cfg.tusd_token
        if ($cfg.rag_key) { $RagKey = $cfg.rag_key }
        $OrchUrl = $cfg.orchestrator_url
        Success "초대 토큰 검증 완료"
    } catch {
        Fail "초대 토큰 유효하지 않음 또는 Gateway 접근 불가: $_"
    }
}

# 필수값 체크
if (-not $GatewayUrl) { $GatewayUrl = "https://rag.quetta-soft.com" }
if (-not $ApiKey -and $GatewayUrl -like "https://*") {
    Fail "설정 필요: QUETTA_GIST_ID / QUETTA_INSTALL_TOKEN / QUETTA_API_KEY 중 하나"
}

# 기본값 채우기
if (-not $RagUrl) { $RagUrl = $GatewayUrl }
if (-not $TusdUrl) { $TusdUrl = $GatewayUrl }
if (-not $RagKey) { $RagKey = "rag-claude-key-2026" }
if (-not $OrchUrl) { $OrchUrl = "$GatewayUrl/orchestrator" }

# ── 4. Claude Code에 등록 ────────────────────────────────────────────────────
Info "claude mcp add-json 으로 등록 중..."

# 기존 등록 제거 (멱등성)
& claude mcp remove quetta-agents --scope user 2>$null | Out-Null

$configObj = @{
    command = $UvxPath
    args = @("--from", $RepoHttps, "quetta-agents-mcp")
    env = @{
        QUETTA_GATEWAY_URL      = $GatewayUrl
        QUETTA_ORCHESTRATOR_URL = $OrchUrl
        QUETTA_API_KEY          = $ApiKey
        QUETTA_TIMEOUT          = $Timeout
        QUETTA_RAG_URL          = $RagUrl
        QUETTA_TUSD_URL         = $TusdUrl
        QUETTA_TUSD_TOKEN       = $TusdToken
        QUETTA_RAG_KEY          = $RagKey
    }
}
$configJson = ($configObj | ConvertTo-Json -Compress -Depth 10)
# PowerShell → cmd 인자 이스케이프: 홑따옴표로 감싸기 어려워서 stdin 사용
$tempFile = New-TemporaryFile
$configJson | Set-Content -Path $tempFile -Encoding UTF8 -NoNewline

try {
    & claude mcp add-json quetta-agents "$configJson" --scope user
    if ($LASTEXITCODE -eq 0) {
        Success "Claude Code에 등록 완료 (user scope)"
    } else {
        Fail "claude mcp add-json 실패 (exit=$LASTEXITCODE)"
    }
} finally {
    Remove-Item $tempFile -Force -ErrorAction SilentlyContinue
}

# ── 5. CLAUDE.md 자동 초기화 지시 추가 ───────────────────────────────────────
$ClaudeMd = Join-Path $env:USERPROFILE ".claude\CLAUDE.md"
$ClaudeMdDir = Split-Path $ClaudeMd -Parent
if (-not (Test-Path $ClaudeMdDir)) { New-Item -ItemType Directory -Path $ClaudeMdDir -Force | Out-Null }
if (-not (Test-Path $ClaudeMd)) { "" | Set-Content $ClaudeMd -Encoding UTF8 }

$markerBegin = "<!-- quetta-agents-mcp:auto-init BEGIN -->"
$markerEnd = "<!-- quetta-agents-mcp:auto-init END -->"
$currentContent = Get-Content $ClaudeMd -Raw -ErrorAction SilentlyContinue
if ($currentContent -and $currentContent -match [regex]::Escape($markerBegin)) {
    Info "CLAUDE.md 기존 블록 제거 후 재추가..."
    $currentContent = [regex]::Replace($currentContent, "(?s)$([regex]::Escape($markerBegin)).*?$([regex]::Escape($markerEnd))\s*", "")
    $currentContent | Set-Content $ClaudeMd -Encoding UTF8 -NoNewline
}

# single-quoted here-string 으로 리터럴 처리 (backtick/달러 이스케이프 불필요).
# 마커는 Bash 스크립트와 동일 문자열로 하드코딩.
$block = @'

<!-- quetta-agents-mcp:auto-init BEGIN -->
## Quetta Agents MCP — 사용 규칙

### 역할 분리 (최우선 원칙)
**Claude Code 네이티브 기능은 항상 그대로 유지하고 우선 사용한다**:
- Agent / Task / Plan / Subagent 호출 (Explore, feature-dev, general-purpose 등)
- Read / Write / Edit / Grep / Glob / Bash
- 내장 skills: `/codex`, `/plan-ceo-review`, `/plan-eng-review`, `/autoplan`, `/review`, `/qa`, `/ship`, `/investigate` 등 — 코딩·설계·리뷰 어드바이저는 전부 Claude Code native 를 사용

**Quetta MCP는 "로컬에서 불가능한 외부 리소스"가 필요할 때만 호출**한다:
- 원격 Windows/맥 GPU 에이전트 실행
- 공유 RAG 메모리 · 세션간 기억
- 학술 DB 통합 검색 (PubMed/arXiv/Semantic Scholar)
- Nougat + Gemini 기반 PDF 수식 OCR/분석
- 다른 LLM 라우팅 (Gemma4 로컬, DeepSeek-R1 의료, Claude Opus 영상)

일반 코딩·파일 편집·리팩토링·로컬 탐색은 Claude Code 네이티브가 처리한다. Quetta에 위임하지 않는다.

### 진입점 선택
| 상황 | 사용할 도구 |
|------|-----------|
| 파일 편집, 코드 리뷰, 로컬 Grep/Read, 디버깅 | **Claude Code native** (Agent, Edit, Bash, …) |
| 아키텍처/계획 리뷰 | `/plan-ceo-review`, `/plan-eng-review`, `/autoplan` |
| 독립 제2의견 | `/codex` |
| "논문 검색해줘" (파일 없음) | `quetta_paper_search` |
| PDF/file_id 첨부 후 분석 | `quetta_analyze_paper` (파일 제공 시 자동) |
| 원격 GPU 필요 (CUDA/torch/학습) | `quetta_gpu_exec` |
| 원격 PC 스크린샷/셸 | `quetta_remote_screenshot` / `quetta_remote_shell` |
| 의료 임상/진단 질의 | `quetta_medical` (DeepSeek-R1) |
| 공유 메모리 저장/회상 | `quetta_memory_save` / `quetta_memory_recall` |
| 기타 외부 LLM 자유 질의 | `quetta_ask` |

`quetta_auto` 는 위 Quetta 범위 안에서 의도가 애매할 때만 사용 — Claude Code 네이티브로 처리 가능하면 그쪽 먼저 시도.

### 세션 시작
새 세션 첫 응답 전 **두 가지를 순서대로** 호출:
1. `quetta_session_init()` — 사용자 프로필·최근 맥락
2. `quetta_session_list(project_key="<git:orgrepo#branch>", within_hours=48)` — 같은 프로젝트의 최근 세션이 있으면 사용자에게 "어제 다른 기기에서 하던 작업을 이어받을까요?" 확인 후 `quetta_session_resume(session_id=...)` 호출.

### 멀티 세션 이어받기 / 요약 검증
- 실시간 PostToolUse hook 이 자동으로 세션 JSONL을 `/v1/sessions/push` 로 업로드 (debounce 3s, TTL 30일)
- 세션 마무리 시 `quetta_session_summarize(session_id=..., summary_md="...")` — 서버가 원본 대비 핵심 항목 커버리지 점수화. 요약이 부실해도 원본 보존 → 유실 방지.
- 영구 보존은 `quetta_session_pin(session_id=..., pinned=True)`.

### Apple Silicon 분산 추론
- Llama 3.1 405B / DeepSeek-R1 671B 같은 초대형 모델은 Exo 클러스터로 자동 라우팅 (서버 EXO_ENABLED=true)
- `quetta_exo_status` — 클러스터 상태
- `quetta_mlx_distribute` — mpirun 기반 MLX 분산 추론
- 키워드: 405b / 671b / exo / mac cluster / 분산 추론 / mlx / metal

### 원격 에이전트 활용 (Multi-PC)
연결된 Remote Agent 들은 이 PC 의 Claude Code 에서 사용 가능. 먼저 `quetta_remote_connect(action="list")` 로 연결 목록 확인 후:

| 작업 | 도구 | 자동 라우팅 |
|------|-----|-----------|
| CUDA/PyTorch / Whisper / SD | `quetta_gpu_exec` | NVIDIA GPU agent (Windows) |
| Llama 단일 Mac 추론 | `quetta_mlx_distribute(n_hosts=1)` | Apple Silicon agent |
| Mac 분산 추론 | `quetta_mlx_distribute(n_hosts=2~3)` | mpirun + ~/.mlx-hosts |
| Nougat PDF OCR | `quetta_analyze_paper` | NVIDIA GPU agent (Windows) |
| 화면/입력 자동화 | `quetta_remote_screenshot/click/type` | GUI agent |
| GPU 상태 조회 | `quetta_gpu_status` | 전체 GPU agent |
| 임의 shell | `quetta_remote_shell` | agent_id 명시 권장 |

특정 에이전트 강제: `quetta_remote_shell(agent_id="<id>", command="...")`. 연결 끊김 시 `quetta_remote_connect(action="install-link", os="windows"|"linux"|"mac")` 로 재설치 링크 발급. 일괄 업데이트는 `quetta_agent_update()`.

### 하네스 동작 범위 (참고)
- `quetta_ask/code/medical/auto` 호출 시 Gateway가 **원격 LLM 프롬프트**에만 공유 메모리를 자동 주입
- Claude Code 자체의 추론·도구 호출·Agent/Task 흐름엔 영향 없음
- 별도 설정 불필요

### 어드바이저 구분
- **Claude Code native advisors** (`/codex`, `/plan-ceo-review`, `/review` 등) — 계획·리뷰·2차 의견은 모두 이쪽
- **`quetta_code`** — 외부 LLM(Gemma4/Claude)에 코딩 작업을 맡길 때만 사용하며 agent-skills 5종 자동 주입. 일반 Claude Code 코딩 흐름엔 사용하지 않음.

### 파일 유무 분기
- 파일 없이 "논문 검색" → `quetta_paper_search` (PubMed+arXiv+Semantic Scholar)
- `file_path`/`file_id` 제공 → `quetta_analyze_paper` 로 서버가 자동 override (Nougat+Gemini+Claude)

### 메모리 저장 기준
사용자 선호·프로젝트 결정·반복 참조될 사실만 `quetta_memory_save(text=..., tags=[...])`. 진행 중 대화 상태는 저장하지 않는다.

### dry_run
Quetta 라우팅 결과만 미리 보려면 `quetta_auto(..., dry_run=True)`.
<!-- quetta-agents-mcp:auto-init END -->
'@
Add-Content -Path $ClaudeMd -Value $block -Encoding UTF8
Success "CLAUDE.md 자동 초기화 지시 추가 ($ClaudeMd)"

# ── 5.5. PostToolUse hook 자동 등록 (멀티 세션 실시간 push) ────────────────────
$HookDir  = Join-Path $env:USERPROFILE ".claude\hooks"
$HookPs1  = Join-Path $HookDir "quetta-session-push.ps1"
if (-not (Test-Path $HookDir)) { New-Item -ItemType Directory -Force -Path $HookDir | Out-Null }

Info "PostToolUse hook 배포 중..."
$HookRaw = "https://raw.githubusercontent.com/choyunsung/quetta-agents-mcp/master/hooks/quetta-session-push.ps1"
try {
    Invoke-WebRequest -Uri $HookRaw -OutFile $HookPs1 -UseBasicParsing
    Success "hook 스크립트: $HookPs1"
} catch {
    Warn "hook 스크립트 다운로드 실패 ($_) — 수동 복사 필요"
}

$SettingsPath = Join-Path $env:USERPROFILE ".claude\settings.json"
if (Test-Path $HookPs1) {
    try {
        if (Test-Path $SettingsPath) {
            $cfg = Get-Content $SettingsPath -Raw | ConvertFrom-Json -AsHashtable
        } else {
            $cfg = @{}
        }
        if (-not $cfg.ContainsKey("hooks")) { $cfg["hooks"] = @{} }

        $cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$HookPs1`""

        foreach ($event in @("PostToolUse", "Stop")) {
            $existing = @()
            if ($cfg["hooks"].ContainsKey($event)) { $existing = @($cfg["hooks"][$event]) }
            $already = $false
            foreach ($entry in $existing) {
                if ($entry.hooks) {
                    foreach ($h in $entry.hooks) {
                        if ($h.command -eq $cmd) { $already = $true }
                    }
                }
            }
            if (-not $already) {
                $existing += @{
                    hooks = @(@{
                        type    = "command"
                        command = $cmd
                        env     = @{
                            QUETTA_GATEWAY_URL = $GatewayUrl
                            QUETTA_API_KEY     = $ApiKey
                        }
                    })
                }
                $cfg["hooks"][$event] = $existing
            }
        }

        $cfg | ConvertTo-Json -Depth 10 | Set-Content -Path $SettingsPath -Encoding UTF8
        Success "settings.json 에 PostToolUse/Stop hook 등록 완료"
    } catch {
        Warn "settings.json 업데이트 실패: $_"
    }
}

# ── 6. 완료 ──────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
Write-Host "   Installation complete!" -ForegroundColor Green
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
Write-Host ""
Write-Host "  Gateway : $GatewayUrl"
Write-Host "  RAG     : $RagUrl"
Write-Host "  tusd    : $TusdUrl $(if ($TusdToken) { '(token set)' } else { '(no token)' })"
Write-Host ""
Write-Host "  Verify :  claude mcp list | Select-String quetta" -ForegroundColor Yellow
Write-Host "  Restart:  Claude Code 재시작 후 사용 가능" -ForegroundColor Yellow
Write-Host ""
