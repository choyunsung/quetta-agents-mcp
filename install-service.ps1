# Quetta Remote Agent를 Windows Service로 설치
# 관리자 권한 PowerShell에서 실행 필요
#
# 동작:
#   1. NSSM 다운로드 (없으면)
#   2. 기존 시작프로그램 VBS 비활성화 (선택)
#   3. "QuettaRemoteAgent" Windows Service 생성
#   4. 자동 시작 + 즉시 시작
#   5. 재부팅/로그아웃 후에도 동작

$ErrorActionPreference = "Stop"

$AgentDir = "$env:USERPROFILE\.quetta-remote-agent"
$NssmExe  = "$AgentDir\nssm.exe"
$ServiceName = "QuettaRemoteAgent"

Write-Host "▶ Quetta Remote Agent → Windows Service 설치"

# 관리자 체크
$IsAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $IsAdmin) {
    Write-Host "❌ 관리자 권한 필요. PowerShell을 관리자로 실행 후 재시도하세요." -ForegroundColor Red
    exit 1
}

# .env 로드
$envFile = "$AgentDir\.env"
if (-not (Test-Path $envFile)) {
    Write-Host "❌ $envFile 없음. 먼저 일반 에이전트가 설치되어 있어야 합니다." -ForegroundColor Red
    exit 1
}
$envVars = @{}
Get-Content $envFile | ForEach-Object {
    if ($_ -match "^([A-Z_]+)=(.*)$") { $envVars[$matches[1]] = $matches[2] }
}
$wsUrl = $envVars["AGENT_WS_URL"]
$token = $envVars["AGENT_TOKEN"]
if (-not $wsUrl -or -not $token) {
    Write-Host "❌ .env 에 AGENT_WS_URL / AGENT_TOKEN 누락" -ForegroundColor Red
    exit 1
}

# pythonw 경로
$pythonw = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
if (-not $pythonw) {
    Write-Host "❌ pythonw.exe 못 찾음. Python 설치 확인" -ForegroundColor Red
    exit 1
}
Write-Host "  pythonw: $pythonw"

# NSSM 설치
if (-not (Test-Path $NssmExe)) {
    Write-Host "▶ NSSM 다운로드 중..."
    $tempZip = "$env:TEMP\nssm.zip"
    Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile $tempZip -UseBasicParsing
    $tempDir = "$env:TEMP\nssm-extract"
    Expand-Archive -Path $tempZip -DestinationPath $tempDir -Force
    # 64비트 우선
    $arch = if ([Environment]::Is64BitOperatingSystem) { "win64" } else { "win32" }
    Copy-Item "$tempDir\nssm-2.24\$arch\nssm.exe" $NssmExe -Force
    Remove-Item $tempZip,$tempDir -Recurse -Force
    Write-Host "  ✓ NSSM 설치: $NssmExe"
}

# 기존 서비스 제거 (멱등성)
$existing = & sc.exe query $ServiceName 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "▶ 기존 서비스 제거 중..."
    & $NssmExe stop $ServiceName confirm 2>$null | Out-Null
    & $NssmExe remove $ServiceName confirm | Out-Null
    Start-Sleep -Seconds 2
}

# 서비스 설치
Write-Host "▶ Windows Service 등록..."
& $NssmExe install $ServiceName $pythonw "`"$AgentDir\agent.py`""
& $NssmExe set $ServiceName AppDirectory $AgentDir
& $NssmExe set $ServiceName DisplayName "Quetta Remote Agent"
& $NssmExe set $ServiceName Description "Quetta MCP 원격 에이전트 - WebSocket 역방향 연결"
& $NssmExe set $ServiceName Start SERVICE_AUTO_START
& $NssmExe set $ServiceName AppEnvironmentExtra "AGENT_WS_URL=$wsUrl" "AGENT_TOKEN=$token"
& $NssmExe set $ServiceName AppStdout "$AgentDir\service.log"
& $NssmExe set $ServiceName AppStderr "$AgentDir\service-err.log"
& $NssmExe set $ServiceName AppRotateFiles 1
& $NssmExe set $ServiceName AppRotateBytes 10485760
# 실패 시 자동 재시작
& $NssmExe set $ServiceName AppExit Default Restart
& $NssmExe set $ServiceName AppRestartDelay 5000

# 기존 Startup 폴더 VBS 제거 (서비스와 중복 방지)
$startupVbs = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\QuettaRemoteAgent.vbs"
if (Test-Path $startupVbs) {
    Remove-Item $startupVbs -Force
    Write-Host "  ✓ 기존 Startup VBS 제거 (서비스가 대신 동작)"
}

# 기존 사용자 세션 pythonw 종료
Get-Process pythonw -ErrorAction SilentlyContinue | ForEach-Object {
    $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine
    if ($cmd -like "*agent.py*") {
        Write-Host "  ▶ 기존 pythonw 종료: PID $($_.Id)"
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Seconds 2

# 서비스 시작
Write-Host "▶ 서비스 시작..."
& $NssmExe start $ServiceName
Start-Sleep -Seconds 3

# 상태 확인
$status = & sc.exe query $ServiceName | Select-String "STATE"
Write-Host ""
Write-Host "✅ 설치 완료" -ForegroundColor Green
Write-Host "   서비스명: $ServiceName"
Write-Host "   상태: $status"
Write-Host ""
Write-Host "   재부팅 후 자동 시작됩니다 (로그인 불필요)"
Write-Host "   로그: $AgentDir\service.log"
Write-Host ""
Write-Host "   관리 명령:"
Write-Host "     net start $ServiceName"
Write-Host "     net stop $ServiceName"
Write-Host "     sc.exe query $ServiceName"
Write-Host "     nssm edit $ServiceName  (GUI 설정)"
