# StockPanel Windows 一键安装
#
# 由 install.bat 调用。与 stockpanel.env（密钥文件，scripts/make_windows_package.sh 打包）放在同一目录。
# 流程: 安装 Git/Python/Node（winget）→ 克隆代码到 %USERPROFILE%\StockPanel → 写入 backend\.env
#       → 创建桌面快捷方式 → 调用仓库内 start.ps1（装依赖、构建前端、启动并打开浏览器）。
# 可重复运行: 已安装的部分会跳过，已有代码会更新。

$ErrorActionPreference = 'Stop'

$RepoUrl = 'https://github.com/bearxiong2002/stockAiProject.git'
$Repo = Join-Path $env:USERPROFILE 'StockPanel'
$EnvSource = Join-Path $PSScriptRoot 'stockpanel.env'

function Say($msg) { Write-Host "`n>>> $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host "`n[错误] $msg" -ForegroundColor Red; exit 1 }

function Update-PathEnv {
    # winget 装完的程序写在注册表 PATH 里，当前窗口需要重新读取
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machine;$user"
}

function Test-Python {
    $ErrorActionPreference = 'Continue'
    foreach ($cand in @('py|-3.12', 'py|-3', 'python',
                        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe")) {
        $parts = $cand -split '\|'
        if (-not (Get-Command $parts[0] -ErrorAction SilentlyContinue)) { continue }
        $rest = @($parts | Select-Object -Skip 1)
        $out = & $parts[0] @rest -c 'import sys;print(sys.version_info>=(3,10))' 2>$null
        if ($LASTEXITCODE -eq 0 -and "$out".Trim() -eq 'True') { return $true }
    }
    return $false
}

function Install-WithWinget($id, $name, [string[]]$extra = @()) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Fail "这台电脑没有 winget，无法自动安装 $name。请手动安装后重新运行本脚本:`n  Git:    https://git-scm.com/download/win`n  Python: https://www.python.org/downloads/ （安装时勾选 Add python.exe to PATH）`n  Node:   https://nodejs.org/ （选 LTS 版本）"
    }
    Say "正在安装 $name（如弹出“是否允许更改”请点“是”）..."
    & winget install -e --id $id --source winget --accept-package-agreements --accept-source-agreements --silent @extra
    Update-PathEnv
}

Write-Host '========================================' -ForegroundColor Green
Write-Host '   StockPanel 股票分析 - 一键安装' -ForegroundColor Green
Write-Host '========================================' -ForegroundColor Green

if (-not (Test-Path $EnvSource) -and -not (Test-Path "$Repo\backend\.env")) {
    Fail "没找到密钥文件 stockpanel.env。请把整个安装包解压后再运行，不要直接在压缩包里双击。"
}

Update-PathEnv

# ---- 1. 基础软件 ----
Say '检查基础软件（Git / Python / Node.js）...'
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Install-WithWinget 'Git.Git' 'Git'
}
if (-not (Test-Python)) {
    Install-WithWinget 'Python.Python.3.12' 'Python 3.12' @(
        '--override', '/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1')
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Install-WithWinget 'OpenJS.NodeJS.LTS' 'Node.js'
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Fail 'Git 安装失败，请重启电脑后再运行一次。' }
if (-not (Test-Python)) { Fail 'Python 安装失败，请重启电脑后再运行一次。' }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Fail 'Node.js 安装失败，请重启电脑后再运行一次。' }
Write-Host '基础软件已就绪。'

# ---- 2. 拉取代码 ----
if (Test-Path "$Repo\.git") {
    Say "更新代码: $Repo"
    & git -C $Repo pull --ff-only
    if ($LASTEXITCODE -ne 0) { Write-Host '代码更新失败，继续使用现有版本。' -ForegroundColor Yellow }
} else {
    Say "下载代码到: $Repo"
    $ok = $false
    for ($i = 1; $i -le 3 -and -not $ok; $i++) {
        if (Test-Path $Repo) { Remove-Item $Repo -Recurse -Force }
        & git clone --depth 1 $RepoUrl $Repo
        $ok = ($LASTEXITCODE -eq 0)
        if (-not $ok) { Write-Host "下载失败，第 $i 次重试..." -ForegroundColor Yellow; Start-Sleep 3 }
    }
    if (-not $ok) { Fail '无法从 GitHub 下载代码，请检查网络后重新运行。' }
}

# ---- 3. 写入密钥 ----
if (Test-Path $EnvSource) {
    Say '写入密钥配置...'
    Copy-Item $EnvSource "$Repo\backend\.env" -Force
}

# ---- 4. 桌面快捷方式 ----
Say '创建桌面快捷方式...'
$desktop = [Environment]::GetFolderPath('Desktop')
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut((Join-Path $desktop 'StockPanel 股票分析.lnk'))
$lnk.TargetPath = "$Repo\scripts\windows\start.bat"
$lnk.WorkingDirectory = $Repo
$lnk.Description = '启动 StockPanel 股票分析'
$lnk.Save()

# ---- 5. 安装依赖并启动 ----
Say '安装完成，接下来安装运行依赖并启动（第一次需要几分钟）...'
& "$Repo\scripts\windows\start.ps1"
exit $LASTEXITCODE
