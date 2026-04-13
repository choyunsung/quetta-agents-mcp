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

$block = @"

$markerBegin
## Quetta Agents MCP — 공유 메모리 자동 초기화

Quetta MCP가 활성화돼 있으면 **모든 새 Claude Code 세션 시작 직후**에 아래 도구를 **한 번** 호출하세요:

``````
quetta_session_init()
``````

반환된 사용자 메모리 / 최근 맥락 / 활성 문서를 현재 대화의 배경 지식으로 반영합니다. 사용자에게 별도 고지 없이 자연스럽게 진행합니다.

- **중요한 신규 정보**(사용자 선호, 프로젝트 결정, 반복 참조될 사실)는 ``quetta_memory_save(text=...)`` 로 공유 메모리에 저장하세요.
- 모든 ``quetta_ask`` / ``quetta_auto`` 호출은 Gateway RAG harness가 관련 메모리를 자동 주입합니다.
- 멀티 계정 전환 시에도 동일한 Quetta 서버를 사용하는 한 기억이 매끄럽게 이어집니다.
$markerEnd
"@
Add-Content -Path $ClaudeMd -Value $block -Encoding UTF8
Success "CLAUDE.md 자동 초기화 지시 추가 ($ClaudeMd)"

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
