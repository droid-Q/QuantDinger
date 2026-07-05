param(
    [string]$ProjectRoot = "",
    [string]$ServiceName = "QuantDingerBackend",
    [int]$BackendPort = 5000,
    [int]$DbPort = 5432,
    [int]$RedisPort = 6379,
    [int]$FrontendPort = 8888,
    [int]$MobilePort = 8889,
    [string]$NssmPath = "",
    [string]$PipIndexUrl = "https://mirrors.aliyun.com/pypi/simple/",
    [switch]$DockerOnly,
    [switch]$SkipPipInstall,
    [switch]$RunAsLocalSystem
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

if (-not $ProjectRoot) {
    $ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
}
$ProjectRoot = (Resolve-Path $ProjectRoot).Path
$BackendDir = Join-Path $ProjectRoot "backend_api_python"
$ComposeFile = Join-Path $ProjectRoot "docker-compose.mt5-local.yml"
$RootEnv = Join-Path $ProjectRoot ".env"
$BackendEnv = Join-Path $BackendDir ".env"
$VenvDir = Join-Path $BackendDir ".venv-windows"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$LogsDir = Join-Path $BackendDir "logs"

function Fail($Message) {
    Write-Host "Error: $Message" -ForegroundColor Red
    exit 1
}

function Require-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Fail "Run PowerShell as Administrator."
    }
}

function Set-EnvValue($Path, $Key, $Value) {
    if (-not (Test-Path $Path)) { New-Item -ItemType File -Path $Path -Force | Out-Null }
    $lines = @(Get-Content $Path)
    $found = $false
    $next = foreach ($line in $lines) {
        if ($line -match "^$([regex]::Escape($Key))=") {
            "$Key=$Value"
            $found = $true
        } else {
            $line
        }
    }
    if (-not $found) { $next += "$Key=$Value" }
    Set-Content -Path $Path -Value $next -Encoding UTF8
}

function Get-EnvValue($Path, $Key) {
    if (-not (Test-Path $Path)) { return "" }
    $line = Get-Content $Path | Where-Object { $_ -match "^$([regex]::Escape($Key))=" } | Select-Object -Last 1
    if (-not $line) { return "" }
    return $line.Substring($Key.Length + 1)
}

function Wait-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Fail "Docker is not installed or not in PATH."
    }
    for ($i = 1; $i -le 60; $i++) {
        docker info *> $null
        if ($LASTEXITCODE -eq 0) { return }
        Start-Sleep -Seconds 2
    }
    Fail "Docker daemon is not running."
}

function Start-DockerServices {
    Wait-Docker
    Push-Location $ProjectRoot
    try {
        docker compose -f $ComposeFile stop backend *> $null
        docker compose -f $ComposeFile up -d postgres redis frontend mobile
    } finally {
        Pop-Location
    }
}

function Resolve-Nssm {
    if ($NssmPath -and (Test-Path $NssmPath)) { return (Resolve-Path $NssmPath).Path }
    $local = Join-Path $PSScriptRoot "nssm.exe"
    if (Test-Path $local) { return (Resolve-Path $local).Path }
    $existing = Get-Command nssm.exe -ErrorAction SilentlyContinue
    if ($existing) { return $existing.Source }

    $tools = Join-Path $ProjectRoot ".tools\nssm"
    $exe = Join-Path $tools "nssm-2.24\win64\nssm.exe"
    if (Test-Path $exe) { return $exe }

    New-Item -ItemType Directory -Force -Path $tools | Out-Null
    $zip = Join-Path $tools "nssm-2.24.zip"
    Write-Host "Downloading NSSM..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath $tools -Force
    if (-not (Test-Path $exe)) { Fail "NSSM download failed. Put nssm.exe next to this script or pass -NssmPath." }
    return $exe
}

function Invoke-Nssm($Nssm, [string[]]$Args) {
    & $Nssm @Args
    if ($LASTEXITCODE -ne 0) { Fail "nssm $($Args -join ' ') failed." }
}

function Prepare-Env {
    if (-not (Test-Path $BackendEnv)) {
        Copy-Item (Join-Path $BackendDir "env.example") $BackendEnv
    }
    Set-EnvValue $RootEnv "DB_PORT" "127.0.0.1:$DbPort"
    Set-EnvValue $RootEnv "REDIS_PORT" "127.0.0.1:$RedisPort"
    Set-EnvValue $RootEnv "FRONTEND_PORT" "$FrontendPort"
    Set-EnvValue $RootEnv "MOBILE_PORT" "$MobilePort"
    Set-EnvValue $RootEnv "BACKEND_URL" "http://host.docker.internal:$BackendPort"
    $pgPassword = Get-EnvValue $RootEnv "POSTGRES_PASSWORD"
    if (-not $pgPassword) { $pgPassword = "quantdinger123" }
    Set-EnvValue $RootEnv "POSTGRES_PASSWORD" $pgPassword

    Set-EnvValue $BackendEnv "DATABASE_URL" "postgresql://quantdinger:$pgPassword@127.0.0.1:$DbPort/quantdinger"
    Set-EnvValue $BackendEnv "REDIS_HOST" "127.0.0.1"
    Set-EnvValue $BackendEnv "REDIS_PORT" "$RedisPort"
    Set-EnvValue $BackendEnv "CACHE_ENABLED" "true"
    Set-EnvValue $BackendEnv "PYTHON_API_HOST" "0.0.0.0"
    Set-EnvValue $BackendEnv "PYTHON_API_PORT" "$BackendPort"
    Set-EnvValue $BackendEnv "FRONTEND_URL" "http://localhost:$FrontendPort,http://localhost:$MobilePort"
    Set-EnvValue $BackendEnv "ALLOW_LOCAL_DESKTOP_BROKERS" "true"
}

function Prepare-Python {
    if (-not (Test-Path $VenvPython)) {
        if (Get-Command py -ErrorAction SilentlyContinue) {
            py -3 -m venv $VenvDir
        } elseif (Get-Command python -ErrorAction SilentlyContinue) {
            python -m venv $VenvDir
        } else {
            Fail "Python 3 is not installed or not in PATH."
        }
    }
    if (-not $SkipPipInstall) {
        $pipIndexArgs = @("--index-url", $PipIndexUrl)
        & $VenvPython -m pip install @pipIndexArgs --upgrade pip
        & $VenvPython -m pip install @pipIndexArgs -r (Join-Path $BackendDir "requirements.txt") -r (Join-Path $BackendDir "requirements-windows.txt")
    }
    & $VenvPython -c "import MetaTrader5 as mt5; print('MetaTrader5', mt5.__version__)"
    if ($LASTEXITCODE -ne 0) { Fail "MetaTrader5 import failed in $VenvPython." }
}

function Install-BackendService {
    $nssm = Resolve-Nssm
    New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null

    & $nssm status $ServiceName *> $null
    if ($LASTEXITCODE -eq 0) {
        & $nssm stop $ServiceName *> $null
        & $nssm remove $ServiceName confirm *> $null
    }

    Invoke-Nssm $nssm @("install", $ServiceName, $VenvPython, "run.py")
    Invoke-Nssm $nssm @("set", $ServiceName, "AppDirectory", $BackendDir)
    Invoke-Nssm $nssm @("set", $ServiceName, "AppStdout", (Join-Path $LogsDir "windows-service.out.log"))
    Invoke-Nssm $nssm @("set", $ServiceName, "AppStderr", (Join-Path $LogsDir "windows-service.err.log"))
    Invoke-Nssm $nssm @("set", $ServiceName, "AppRotateFiles", "1")
    Invoke-Nssm $nssm @("set", $ServiceName, "AppRotateOnline", "1")
    Invoke-Nssm $nssm @("set", $ServiceName, "AppRotateBytes", "10485760")
    Invoke-Nssm $nssm @("set", $ServiceName, "AppEnvironmentExtra", "PYTHONUTF8=1", "PYTHONUNBUFFERED=1")
    Invoke-Nssm $nssm @("set", $ServiceName, "AppExit", "Default", "Restart")
    Invoke-Nssm $nssm @("set", $ServiceName, "AppRestartDelay", "5000")
    Invoke-Nssm $nssm @("set", $ServiceName, "Start", "SERVICE_AUTO_START")

    if (-not $RunAsLocalSystem) {
        $defaultUser = "$env:USERDOMAIN\$env:USERNAME"
        $serviceUser = Read-Host "Windows service account [$defaultUser]"
        if (-not $serviceUser) { $serviceUser = $defaultUser }
        $secure = Read-Host "Password for $serviceUser" -AsSecureString
        $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try {
            $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
            if ($plain) { Invoke-Nssm $nssm @("set", $ServiceName, "ObjectName", $serviceUser, $plain) }
        } finally {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
        }
    }

    Invoke-Nssm $nssm @("start", $ServiceName)
}

function Register-DockerStartupTask {
    $script = $PSCommandPath
    $quote = { param($v) "'" + ($v -replace "'", "''") + "'" }
    $args = "-NoProfile -ExecutionPolicy Bypass -File $(& $quote $script) -DockerOnly -ProjectRoot $(& $quote $ProjectRoot) -BackendPort $BackendPort -DbPort $DbPort -RedisPort $RedisPort -FrontendPort $FrontendPort -MobilePort $MobilePort"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $args
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
    Register-ScheduledTask -TaskName "QuantDingerDockerServices" -Action $action -Trigger $trigger -Description "Start QuantDinger MT5 Docker services at logon." -Force | Out-Null
}

if (-not (Test-Path $ComposeFile)) { Fail "Missing $ComposeFile." }
if (-not (Test-Path (Join-Path $BackendDir "run.py"))) { Fail "Missing backend_api_python\run.py." }

if ($DockerOnly) {
    Prepare-Env
    Start-DockerServices
    exit 0
}

Require-Admin
Prepare-Env
Prepare-Python
Start-DockerServices
Install-BackendService
Register-DockerStartupTask

Write-Host ""
Write-Host "QuantDinger MT5 backend service installed." -ForegroundColor Green
Write-Host "Service: $ServiceName"
Write-Host "Backend: http://127.0.0.1:$BackendPort"
Write-Host "Frontend: http://localhost:$FrontendPort"
Write-Host "Logs: $LogsDir"
Write-Host ""
Write-Host "Useful commands:"
Write-Host "  Get-Service $ServiceName"
Write-Host "  Restart-Service $ServiceName"
Write-Host "  docker compose -f `"$ComposeFile`" ps"
