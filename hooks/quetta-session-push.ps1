# Claude Code PostToolUse / Stop hook (Windows) — 세션 JSONL 증분 push.
# 환경변수: QUETTA_GATEWAY_URL, QUETTA_API_KEY, QUETTA_MACHINE_ID (선택)

$ErrorActionPreference = "SilentlyContinue"

$GatewayUrl = if ($env:QUETTA_GATEWAY_URL) { $env:QUETTA_GATEWAY_URL } else { "https://rag.quetta-soft.com" }
$ApiKey     = $env:QUETTA_API_KEY
$MachineId  = if ($env:QUETTA_MACHINE_ID) { $env:QUETTA_MACHINE_ID } else { $env:COMPUTERNAME }
$Debounce   = if ($env:QUETTA_SESSION_DEBOUNCE) { [int]$env:QUETTA_SESSION_DEBOUNCE } else { 3 }

if (-not $ApiKey) { exit 0 }

$StateDir = Join-Path $env:LOCALAPPDATA "quetta-session-push"
if (-not (Test-Path $StateDir)) { New-Item -ItemType Directory -Force -Path $StateDir | Out-Null }
$LastFile = Join-Path $StateDir "last_push"

# debounce
if (Test-Path $LastFile) {
    $prev = [int](Get-Content $LastFile -Raw -ErrorAction SilentlyContinue)
    $now = [int][math]::Floor((Get-Date -UFormat %s))
    if (($now - $prev) -lt $Debounce) { exit 0 }
}

# 세션 JSONL 찾기
$ClaudeDir = if ($env:CLAUDE_HOME) { $env:CLAUDE_HOME } else { Join-Path $env:USERPROFILE ".claude" }
$ProjectDir = Join-Path $ClaudeDir "projects"
if (-not (Test-Path $ProjectDir)) { exit 0 }

$Cwd = (Get-Location).Path
# Claude Code 폴더 명명 규칙 — 경로 특수문자 → '-'
$CwdHash = $Cwd -replace '[\\/:]','-' -replace '^-',''
$SessionDir = Join-Path $ProjectDir $CwdHash
$SessionFile = $null
if (Test-Path $SessionDir) {
    $SessionFile = Get-ChildItem -Path $SessionDir -Filter *.jsonl -ErrorAction SilentlyContinue |
                   Sort-Object LastWriteTime -Descending | Select-Object -First 1
}
if (-not $SessionFile) {
    # fallback — 5분 내 수정된 JSONL 중 하나
    $SessionFile = Get-ChildItem -Path $ProjectDir -Recurse -Filter *.jsonl -ErrorAction SilentlyContinue |
                   Where-Object { $_.LastWriteTime -gt (Get-Date).AddMinutes(-5) } |
                   Sort-Object LastWriteTime -Descending | Select-Object -First 1
}
if (-not $SessionFile) { exit 0 }

$SessionId = $SessionFile.BaseName

# git 메타
$ProjectKey = ""
$GitRemote = ""
$GitHead = ""
$Diff = ""
if (git -C $Cwd rev-parse --git-dir 2>$null) {
    $GitRemote = (git -C $Cwd config --get remote.origin.url 2>$null).Trim()
    $GitHead   = (git -C $Cwd rev-parse HEAD 2>$null).Trim()
    $Branch    = (git -C $Cwd symbolic-ref --short HEAD 2>$null).Trim()
    if (-not $Branch) { $Branch = "DETACHED" }
    $diffRaw = (git -C $Cwd diff HEAD 2>$null | Out-String)
    if ($diffRaw.Length -gt 30000) { $Diff = $diffRaw.Substring(0, 30000) } else { $Diff = $diffRaw }
    if ($GitRemote) {
        $m = [regex]::Match($GitRemote, '[:/]([^/]+/[^/.]+)(\.git)?$')
        if ($m.Success) { $ProjectKey = "git:$($m.Groups[1].Value)#$Branch" }
    }
}
if (-not $ProjectKey) { $ProjectKey = "cwd:$(Split-Path $Cwd -Leaf)" }

# JSONL → messages + open_files (Python 한 줄)
$PythonExe = "python"
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    $PythonExe = "py"
}

$ParsePy = @'
import json, sys, pathlib, re
path = pathlib.Path(sys.argv[1])
messages = []
open_files = set()
for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
    if not ln.strip():
        continue
    try:
        obj = json.loads(ln)
    except Exception:
        continue
    t = obj.get("type") or obj.get("role")
    if t in ("user", "assistant", "system"):
        messages.append({
            "role":    t,
            "content": obj.get("message", {}).get("content") or obj.get("content") or "",
            "ts":      obj.get("timestamp") or obj.get("ts"),
        })
    elif obj.get("toolUseResult"):
        messages.append({"role": "tool", "content": obj.get("toolUseResult"), "ts": obj.get("timestamp")})
    txt = json.dumps(obj)[:5000]
    for m in re.finditer(r'"file_path":\s*"([^"]+)"', txt):
        open_files.add(m.group(1))
print(json.dumps({"messages": messages, "open_files": sorted(open_files)[:20]}))
'@

$TempPy = Join-Path $StateDir "parse.py"
$ParsePy | Set-Content -Path $TempPy -Encoding UTF8
$ParsedJson = & $PythonExe $TempPy $SessionFile.FullName 2>$null
if (-not $ParsedJson) { exit 0 }

$Parsed = $ParsedJson | ConvertFrom-Json

$Body = @{
    session_id       = $SessionId
    project_key      = $ProjectKey
    machine_id       = $MachineId
    cwd              = $Cwd
    messages         = $Parsed.messages
    open_files       = $Parsed.open_files
    git_remote       = $GitRemote
    git_head         = $GitHead
    uncommitted_diff = $Diff
} | ConvertTo-Json -Depth 10 -Compress

try {
    Invoke-RestMethod -Uri "$GatewayUrl/v1/sessions/push" `
        -Method Post `
        -Headers @{ Authorization = "Bearer $ApiKey"; "Content-Type" = "application/json" } `
        -Body $Body -TimeoutSec 5 | Out-Null
} catch {}

[int][math]::Floor((Get-Date -UFormat %s)) | Set-Content -Path $LastFile -Encoding ASCII
exit 0
