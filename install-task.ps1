# Quetta Remote Agent 사용자 레벨 Task Scheduler 등록
# 관리자 권한 불필요 — 현재 사용자 로그인 시 자동 시작
#
# 자동 로그인 설정과 함께 사용하면 재부팅 후에도 자동 시작 효과
# (자동 로그인: netplwiz → 사용자 자동 로그온 체크해제)
#
# 사용:
#   iwr -useb https://raw.githubusercontent.com/choyunsung/quetta-agents-mcp/master/install-task.ps1 | iex

$ErrorActionPreference = "Stop"
$AgentDir = "$env:USERPROFILE\.quetta-remote-agent"
$TaskName = "QuettaRemoteAgent"

if (-not (Test-Path "$AgentDir\agent.py")) {
    Write-Host "❌ $AgentDir\agent.py 없음. 먼저 일반 에이전트가 설치되어 있어야 합니다." -ForegroundColor Red
    exit 1
}

# .env 로드
$envFile = "$AgentDir\.env"
if (-not (Test-Path $envFile)) {
    Write-Host "❌ $envFile 없음." -ForegroundColor Red
    exit 1
}
$envVars = @{}
Get-Content $envFile | ForEach-Object {
    if ($_ -match "^([A-Z_]+)=(.*)$") { $envVars[$matches[1]] = $matches[2] }
}

# pythonw 경로
$pythonw = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
if (-not $pythonw) {
    Write-Host "❌ pythonw.exe 못 찾음." -ForegroundColor Red
    exit 1
}

# 시작 래퍼 ps1 — env 로드 후 pythonw 실행
$wrapper = @"
Set-Location '$AgentDir'
`$env:AGENT_WS_URL = '$($envVars["AGENT_WS_URL"])'
`$env:AGENT_TOKEN = '$($envVars["AGENT_TOKEN"])'
& '$pythonw' '$AgentDir\agent.py'
"@
$wrapperPath = "$AgentDir\start-task.ps1"
Set-Content -Path $wrapperPath -Value $wrapper -Encoding UTF8

# 기존 task 제거 (멱등)
Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Unregister-ScheduledTask -Confirm:$false -ErrorAction SilentlyContinue

# Task 등록
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$wrapperPath`""

# 트리거: 사용자 로그온 + 시스템 시작 시 (사용자 task는 시스템 시작은 일부 제한)
$triggers = @(
    (New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME),
    (New-ScheduledTaskTrigger -AtStartup)
)

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365) `
    -Hidden

$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

try {
    Register-ScheduledTask -TaskName $TaskName `
        -Action $action -Trigger $triggers -Settings $settings -Principal $principal `
        -Description "Quetta Remote Agent — 자동 시작 (사용자 task)" -Force | Out-Null
    Write-Host "✅ Task Scheduler 등록 완료: $TaskName"
} catch {
    Write-Host "❌ 등록 실패: $_" -ForegroundColor Red
    exit 1
}

# 기존 Startup VBS 제거 (중복 방지)
$startupVbs = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\QuettaRemoteAgent.vbs"
if (Test-Path $startupVbs) {
    Remove-Item $startupVbs -Force
    Write-Host "  ✓ 기존 Startup VBS 제거"
}

# 즉시 1회 실행
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 2
$state = (Get-ScheduledTask -TaskName $TaskName).State
Write-Host ""
Write-Host "  Task 상태: $state"
Write-Host "  실행 파일: $wrapperPath"
Write-Host ""
Write-Host "  관리:"
Write-Host "    Get-ScheduledTask $TaskName"
Write-Host "    Start-ScheduledTask $TaskName"
Write-Host "    Stop-ScheduledTask $TaskName"
Write-Host "    Unregister-ScheduledTask $TaskName -Confirm:`$false"
Write-Host ""
Write-Host "💡 재부팅 시 자동 시작은 [사용자 자동 로그온] 함께 설정 권장:"
Write-Host "   netplwiz → 사용자 → '사용자 이름과 암호를 입력해야' 체크 해제"
