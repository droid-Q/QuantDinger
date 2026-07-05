@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "SERVICE_NAME=QuantDingerBackend"
set "BACKEND_PORT=5000"
set "DB_PORT=5432"
set "REDIS_PORT=6379"
set "FRONTEND_PORT=8888"
set "MOBILE_PORT=8889"
set "PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/"
set "NSSM_PATH="
set "PROJECT_ROOT="
set "DOCKER_ONLY=0"
set "SKIP_PIP_INSTALL=0"
set "RUN_AS_LOCAL_SYSTEM=0"

:parse_args
if "%~1"=="" goto after_args
if /i "%~1"=="--docker-only" set "DOCKER_ONLY=1"& shift & goto parse_args
if /i "%~1"=="--skip-pip-install" set "SKIP_PIP_INSTALL=1"& shift & goto parse_args
if /i "%~1"=="--run-as-local-system" set "RUN_AS_LOCAL_SYSTEM=1"& shift & goto parse_args
if /i "%~1"=="--project-root" set "PROJECT_ROOT=%~2"& shift & shift & goto parse_args
if /i "%~1"=="--service-name" set "SERVICE_NAME=%~2"& shift & shift & goto parse_args
if /i "%~1"=="--backend-port" set "BACKEND_PORT=%~2"& shift & shift & goto parse_args
if /i "%~1"=="--db-port" set "DB_PORT=%~2"& shift & shift & goto parse_args
if /i "%~1"=="--redis-port" set "REDIS_PORT=%~2"& shift & shift & goto parse_args
if /i "%~1"=="--frontend-port" set "FRONTEND_PORT=%~2"& shift & shift & goto parse_args
if /i "%~1"=="--mobile-port" set "MOBILE_PORT=%~2"& shift & shift & goto parse_args
if /i "%~1"=="--nssm-path" set "NSSM_PATH=%~2"& shift & shift & goto parse_args
if /i "%~1"=="--pip-index-url" set "PIP_INDEX_URL=%~2"& shift & shift & goto parse_args
echo Unknown argument: %~1
exit /b 1

:after_args
if not defined PROJECT_ROOT set "PROJECT_ROOT=%~dp0..\.."
for %%I in ("%PROJECT_ROOT%") do set "PROJECT_ROOT=%%~fI"
set "BACKEND_DIR=%PROJECT_ROOT%\backend_api_python"
set "COMPOSE_FILE=%PROJECT_ROOT%\docker-compose.mt5-local.yml"
set "ROOT_ENV=%PROJECT_ROOT%\.env"
set "BACKEND_ENV=%BACKEND_DIR%\.env"
set "VENV_DIR=%BACKEND_DIR%\.venv-windows"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "LOGS_DIR=%BACKEND_DIR%\logs"

if not exist "%COMPOSE_FILE%" (
  call :fail "Missing %COMPOSE_FILE%"
  exit /b 1
)
if not exist "%BACKEND_DIR%\run.py" (
  call :fail "Missing %BACKEND_DIR%\run.py"
  exit /b 1
)
if "%DOCKER_ONLY%"=="0" call :require_admin || exit /b 1

call :prepare_env || exit /b 1
if "%DOCKER_ONLY%"=="1" (
  call :start_docker_services
  exit /b %ERRORLEVEL%
)
call :prepare_python || exit /b 1
call :start_docker_services || exit /b 1
call :install_backend_service || exit /b 1
call :register_docker_task || exit /b 1

echo.
echo QuantDinger MT5 backend service installed.
echo Service: %SERVICE_NAME%
echo Backend: http://127.0.0.1:%BACKEND_PORT%
echo Frontend: http://localhost:%FRONTEND_PORT%
echo Logs: %LOGS_DIR%
echo.
echo Useful commands:
echo   sc query %SERVICE_NAME%
echo   net stop %SERVICE_NAME% ^&^& net start %SERVICE_NAME%
echo   docker compose -f "%COMPOSE_FILE%" ps
exit /b 0

:require_admin
net session >nul 2>&1
if errorlevel 1 (
  call :fail "Run this .bat as Administrator."
  exit /b 1
)
exit /b 0

:prepare_env
if not exist "%BACKEND_ENV%" copy "%BACKEND_DIR%\env.example" "%BACKEND_ENV%" >nul
call :set_env "%ROOT_ENV%" "DB_PORT" "127.0.0.1:%DB_PORT%" || exit /b 1
call :set_env "%ROOT_ENV%" "REDIS_PORT" "127.0.0.1:%REDIS_PORT%" || exit /b 1
call :set_env "%ROOT_ENV%" "FRONTEND_PORT" "%FRONTEND_PORT%" || exit /b 1
call :set_env "%ROOT_ENV%" "MOBILE_PORT" "%MOBILE_PORT%" || exit /b 1
call :set_env "%ROOT_ENV%" "BACKEND_URL" "http://host.docker.internal:%BACKEND_PORT%" || exit /b 1
call :get_env "%ROOT_ENV%" "POSTGRES_PASSWORD" PG_PASSWORD
if not defined PG_PASSWORD set "PG_PASSWORD=quantdinger123"
call :set_env "%ROOT_ENV%" "POSTGRES_PASSWORD" "%PG_PASSWORD%" || exit /b 1

call :set_env "%BACKEND_ENV%" "DATABASE_URL" "postgresql://quantdinger:%PG_PASSWORD%@127.0.0.1:%DB_PORT%/quantdinger" || exit /b 1
call :set_env "%BACKEND_ENV%" "REDIS_HOST" "127.0.0.1" || exit /b 1
call :set_env "%BACKEND_ENV%" "REDIS_PORT" "%REDIS_PORT%" || exit /b 1
call :set_env "%BACKEND_ENV%" "CACHE_ENABLED" "true" || exit /b 1
call :set_env "%BACKEND_ENV%" "PYTHON_API_HOST" "0.0.0.0" || exit /b 1
call :set_env "%BACKEND_ENV%" "PYTHON_API_PORT" "%BACKEND_PORT%" || exit /b 1
call :set_env "%BACKEND_ENV%" "FRONTEND_URL" "http://localhost:%FRONTEND_PORT%,http://localhost:%MOBILE_PORT%" || exit /b 1
call :set_env "%BACKEND_ENV%" "ALLOW_LOCAL_DESKTOP_BROKERS" "true" || exit /b 1
exit /b 0

:prepare_python
if not exist "%VENV_PYTHON%" (
  where py >nul 2>&1
  if not errorlevel 1 (
    py -3 -m venv "%VENV_DIR%" || exit /b 1
  ) else (
    where python >nul 2>&1 || (
      call :fail "Python 3 is not installed or not in PATH."
      exit /b 1
    )
    python -m venv "%VENV_DIR%" || exit /b 1
  )
)
if "%SKIP_PIP_INSTALL%"=="0" (
  "%VENV_PYTHON%" -m pip install --index-url "%PIP_INDEX_URL%" --upgrade pip || exit /b 1
  "%VENV_PYTHON%" -m pip install --index-url "%PIP_INDEX_URL%" -r "%BACKEND_DIR%\requirements.txt" -r "%BACKEND_DIR%\requirements-windows.txt" || exit /b 1
)
"%VENV_PYTHON%" -c "import MetaTrader5 as mt5; print('MetaTrader5', mt5.__version__)" || (
  call :fail "MetaTrader5 import failed in %VENV_PYTHON%."
  exit /b 1
)
exit /b 0

:start_docker_services
where docker >nul 2>&1 || (
  call :fail "Docker is not installed or not in PATH."
  exit /b 1
)
for /l %%I in (1,1,60) do (
  docker info >nul 2>&1
  if not errorlevel 1 goto docker_ready
  timeout /t 2 /nobreak >nul
)
call :fail "Docker daemon is not running."
exit /b 1
:docker_ready
pushd "%PROJECT_ROOT%"
docker compose -f "%COMPOSE_FILE%" stop backend >nul 2>&1
docker compose -f "%COMPOSE_FILE%" up -d postgres redis frontend mobile
set "DOCKER_EXIT=%ERRORLEVEL%"
popd
exit /b %DOCKER_EXIT%

:install_backend_service
call :resolve_nssm || exit /b 1
if not exist "%LOGS_DIR%" mkdir "%LOGS_DIR%"
"%NSSM_EXE%" status "%SERVICE_NAME%" >nul 2>&1
if not errorlevel 1 (
  "%NSSM_EXE%" stop "%SERVICE_NAME%" >nul 2>&1
  "%NSSM_EXE%" remove "%SERVICE_NAME%" confirm >nul 2>&1
)
"%NSSM_EXE%" install "%SERVICE_NAME%" "%VENV_PYTHON%" "run.py" || exit /b 1
"%NSSM_EXE%" set "%SERVICE_NAME%" AppDirectory "%BACKEND_DIR%" || exit /b 1
"%NSSM_EXE%" set "%SERVICE_NAME%" AppStdout "%LOGS_DIR%\windows-service.out.log" || exit /b 1
"%NSSM_EXE%" set "%SERVICE_NAME%" AppStderr "%LOGS_DIR%\windows-service.err.log" || exit /b 1
"%NSSM_EXE%" set "%SERVICE_NAME%" AppRotateFiles 1 >nul
"%NSSM_EXE%" set "%SERVICE_NAME%" AppRotateOnline 1 >nul
"%NSSM_EXE%" set "%SERVICE_NAME%" AppRotateBytes 10485760 >nul
"%NSSM_EXE%" set "%SERVICE_NAME%" AppEnvironmentExtra PYTHONUTF8=1 PYTHONUNBUFFERED=1 >nul
"%NSSM_EXE%" set "%SERVICE_NAME%" AppExit Default Restart >nul
"%NSSM_EXE%" set "%SERVICE_NAME%" AppRestartDelay 5000 >nul
"%NSSM_EXE%" set "%SERVICE_NAME%" Start SERVICE_AUTO_START >nul

if "%RUN_AS_LOCAL_SYSTEM%"=="0" (
  set "DEFAULT_SERVICE_USER=%USERDOMAIN%\%USERNAME%"
  set /p "SERVICE_USER=Windows service account [!DEFAULT_SERVICE_USER!]: "
  if not defined SERVICE_USER set "SERVICE_USER=!DEFAULT_SERVICE_USER!"
  for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=Read-Host 'Password for !SERVICE_USER!' -AsSecureString; $b=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($p); try{[Runtime.InteropServices.Marshal]::PtrToStringBSTR($b)} finally{[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b)}"`) do set "SERVICE_PASS=%%P"
  if defined SERVICE_PASS "%NSSM_EXE%" set "%SERVICE_NAME%" ObjectName "!SERVICE_USER!" "!SERVICE_PASS!" || exit /b 1
)
"%NSSM_EXE%" start "%SERVICE_NAME%" || exit /b 1
exit /b 0

:register_docker_task
set "TASK_CMD=\"%~f0\" --docker-only --project-root \"%PROJECT_ROOT%\" --backend-port %BACKEND_PORT% --db-port %DB_PORT% --redis-port %REDIS_PORT% --frontend-port %FRONTEND_PORT% --mobile-port %MOBILE_PORT%"
schtasks /Create /TN "QuantDingerDockerServices" /SC ONLOGON /TR "%TASK_CMD%" /F >nul
exit /b %ERRORLEVEL%

:resolve_nssm
if defined NSSM_PATH (
  if exist "%NSSM_PATH%" (
    set "NSSM_EXE=%NSSM_PATH%"
    exit /b 0
  )
)
if exist "%~dp0nssm.exe" (
  set "NSSM_EXE=%~dp0nssm.exe"
  exit /b 0
)
where nssm.exe >nul 2>&1
if not errorlevel 1 (
  for /f "delims=" %%N in ('where nssm.exe') do (
    set "NSSM_EXE=%%N"
    exit /b 0
  )
)
set "NSSM_DIR=%PROJECT_ROOT%\.tools\nssm"
set "NSSM_EXE=%NSSM_DIR%\nssm-2.24\win64\nssm.exe"
if exist "%NSSM_EXE%" exit /b 0
if not exist "%NSSM_DIR%" mkdir "%NSSM_DIR%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'https://nssm.cc/release/nssm-2.24.zip' -OutFile '%NSSM_DIR%\nssm-2.24.zip'; Expand-Archive -Path '%NSSM_DIR%\nssm-2.24.zip' -DestinationPath '%NSSM_DIR%' -Force"
if not exist "%NSSM_EXE%" (
  call :fail "NSSM download failed. Put nssm.exe next to this .bat or pass --nssm-path."
  exit /b 1
)
exit /b 0

:set_env
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=$args[0]; $k=$args[1]; $v=$args[2]; if(!(Test-Path $p)){New-Item -ItemType File -Path $p -Force|Out-Null}; $lines=@(Get-Content $p); $found=$false; $out=foreach($line in $lines){if($line -match ('^'+[regex]::Escape($k)+'=')){$found=$true; $k+'='+$v}else{$line}}; if(-not $found){$out += $k+'='+$v}; Set-Content -Path $p -Value $out -Encoding UTF8" "%~1" "%~2" "%~3"
exit /b %ERRORLEVEL%

:get_env
set "%~3="
for /f "usebackq tokens=1,* delims==" %%A in ("%~1") do (
  if /i "%%A"=="%~2" set "%~3=%%B"
)
exit /b 0

:fail
echo Error: %~1
exit /b 1
