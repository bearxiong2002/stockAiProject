# StockPanel Windows 启动脚本（桌面快捷方式 → start.bat → 本文件）
#
# 每次启动: 自动更新代码 → 依赖有变化才重装 → 代码有变化才重新构建前端
#           → 启动后端（托管前端页面）→ 自动打开浏览器 http://localhost:18900
# 关闭这个黑色窗口即停止程序。
#   -NoUpdate  跳过 git 更新

param([switch]$NoUpdate)

$ErrorActionPreference = 'Stop'

$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Backend = Join-Path $Repo 'backend'
$Frontend = Join-Path $Repo 'frontend'
$VenvPy = Join-Path $Backend '.venv\Scripts\python.exe'
$Port = if ($env:STOCKPANEL_PORT) { $env:STOCKPANEL_PORT } else { '18900' }
$Url = "http://localhost:$Port"
$PipMirror = 'https://pypi.tuna.tsinghua.edu.cn/simple'
$NpmMirror = 'https://registry.npmmirror.com'

function Say($msg) { Write-Host "`n>>> $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host "`n[错误] $msg" -ForegroundColor Red; exit 1 }

function Invoke-Native($what) {
    # 原生命令失败不会抛异常，统一检查退出码
    if ($LASTEXITCODE -ne 0) { Fail "$what 失败（退出码 $LASTEXITCODE），请把这个窗口截图发给帮你安装的人。" }
}

function Update-PathEnv {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machine;$user"
}

function Find-Python {
    $ErrorActionPreference = 'Continue'
    foreach ($cand in @('py|-3.12', 'py|-3', 'python',
                        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe")) {
        $parts = $cand -split '\|'
        if (-not (Get-Command $parts[0] -ErrorAction SilentlyContinue)) { continue }
        $rest = @($parts | Select-Object -Skip 1)
        $out = & $parts[0] @rest -c 'import sys;print(sys.version_info>=(3,10))' 2>$null
        # 逗号防止单元素数组（如 'python'）被展开成字符串
        if ($LASTEXITCODE -eq 0 -and "$out".Trim() -eq 'True') { return ,$parts }
    }
    return $null
}

function Read-Stamp($path) {
    if (Test-Path $path) { return (Get-Content $path -Raw).Trim() }
    return ''
}

function Write-Stamp($path, $value) { Set-Content -Path $path -Value $value -Encoding ascii }

function Test-Backend {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/health" -UseBasicParsing -TimeoutSec 2
        return $r.StatusCode -eq 200
    } catch { return $false }
}

# 本机探测不走系统代理
[System.Net.WebRequest]::DefaultWebProxy = New-Object System.Net.WebProxy
Update-PathEnv
$Host.UI.RawUI.WindowTitle = 'StockPanel - 关闭此窗口即停止程序'

if (Test-Backend) {
    Write-Host 'StockPanel 已经在运行，直接打开浏览器。'
    Start-Process $Url
    exit 0
}

if (-not (Test-Path (Join-Path $Backend '.env'))) {
    Write-Host '[提醒] 没有找到 backend\.env 密钥文件，行情数据可能无法获取。' -ForegroundColor Yellow
}

# ---- 1. 更新代码 ----
$hasGit = [bool](Get-Command git -ErrorAction SilentlyContinue)
if ($hasGit -and -not $NoUpdate) {
    Say '检查代码更新...'
    $ErrorActionPreference = 'Continue'
    & git -C $Repo pull --ff-only
    if ($LASTEXITCODE -ne 0) { Write-Host '代码更新失败（可能是网络问题），继续使用现有版本。' -ForegroundColor Yellow }
    $ErrorActionPreference = 'Stop'
}
$head = if ($hasGit) { (& git -C $Repo rev-parse HEAD).Trim() } else { 'no-git' }

# ---- 2. Python 依赖 ----
if (-not (Test-Path $VenvPy)) {
    Say '创建 Python 运行环境...'
    $py = Find-Python
    if (-not $py) { Fail '没有找到 Python 3.10 以上版本，请重新运行安装程序 install.bat。' }
    $pyArgs = @($py | Select-Object -Skip 1) + @('-m', 'venv', (Join-Path $Backend '.venv'))
    & $py[0] @pyArgs
    Invoke-Native '创建 Python 运行环境'
}
$reqFile = Join-Path $Backend 'requirements.txt'
$reqStamp = Join-Path $Backend '.venv\.stockpanel_reqs'
$reqHash = (Get-FileHash $reqFile -Algorithm SHA256).Hash
if ((Read-Stamp $reqStamp) -ne $reqHash) {
    Say '安装 Python 依赖...'
    & $VenvPy -m pip install -r $reqFile -i $PipMirror --disable-pip-version-check
    Invoke-Native '安装 Python 依赖'
    Write-Stamp $reqStamp $reqHash
}

# ---- 3. 前端依赖与构建 ----
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Fail '没有找到 Node.js，请重新运行安装程序 install.bat。'
}
$lockFile = Join-Path $Frontend 'package-lock.json'
$lockStamp = Join-Path $Frontend 'node_modules\.stockpanel_lock'
$lockHash = (Get-FileHash $lockFile -Algorithm SHA256).Hash
Push-Location $Frontend
try {
    if ((Read-Stamp $lockStamp) -ne $lockHash) {
        Say '安装前端依赖...'
        & npm ci --registry=$NpmMirror --no-audit --no-fund
        Invoke-Native '安装前端依赖'
        Write-Stamp $lockStamp $lockHash
    }
    $distStamp = Join-Path $Frontend 'dist\.stockpanel_head'
    if (-not (Test-Path (Join-Path $Frontend 'dist\index.html')) -or (Read-Stamp $distStamp) -ne $head) {
        Say '构建前端页面...'
        & npm run build
        Invoke-Native '构建前端页面'
        Write-Stamp $distStamp $head
    }
} finally {
    Pop-Location
}

# ---- 4. 启动 ----
Say "启动 StockPanel: $Url"
$proc = Start-Process -FilePath $VenvPy -WorkingDirectory $Backend -NoNewWindow -PassThru `
    -ArgumentList '-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', $Port

$ready = $false
for ($i = 0; $i -lt 60 -and -not $proc.HasExited; $i++) {
    if (Test-Backend) { $ready = $true; break }
    Start-Sleep 1
}
if (-not $ready) {
    if (-not $proc.HasExited) { $proc.Kill() }
    Fail "程序没能启动（端口 $Port 可能被占用），请把这个窗口截图发给帮你安装的人。"
}

Start-Process $Url
Write-Host ''
Write-Host '========================================' -ForegroundColor Green
Write-Host "  StockPanel 已启动: $Url" -ForegroundColor Green
Write-Host '  浏览器没自动打开的话，手动访问上面的地址' -ForegroundColor Green
Write-Host '  用完直接关闭这个窗口即可' -ForegroundColor Green
Write-Host '========================================' -ForegroundColor Green
$proc.WaitForExit()
