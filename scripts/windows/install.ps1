# StockPanel Windows 一键安装
#
# 由 install.bat 调用。与 stockpanel.env（密钥文件，scripts/make_windows_package.sh 打包）放在同一目录。
# 流程: 缺什么装什么（Git/Python/Node，直接下载，国内镜像优先，无需 winget、无需管理员）
#       → 克隆代码到 install.bat 同级的 StockPanel 文件夹 → 写入 backend\.env
#       → 创建桌面快捷方式 → 调用仓库内 start.ps1（装依赖、构建前端、启动并打开浏览器）。
# 可重复运行: 已安装的部分会跳过，已有代码会更新。

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # PS 5.1 的下载进度条会让下载慢几十倍
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$RepoUrl = 'https://github.com/bearxiong2002/stockAiProject.git'
# 代码放在安装包同级目录，方便找到；安装后这个文件夹不能删
$Repo = Join-Path $PSScriptRoot 'StockPanel'
$EnvSource = Join-Path $PSScriptRoot 'stockpanel.env'
$Tools = Join-Path $env:LOCALAPPDATA 'StockPanel-tools'   # Git / Node 便携版安装位置

# 下载地址按顺序尝试: 国内镜像 → 官方
$PythonUrls = @(
    'https://registry.npmmirror.com/-/binary/python/3.12.10/python-3.12.10-amd64.exe',
    'https://mirrors.huaweicloud.com/python/3.12.10/python-3.12.10-amd64.exe',
    'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe')
$NodeUrls = @(
    'https://registry.npmmirror.com/-/binary/node/v20.19.5/node-v20.19.5-win-x64.zip',
    'https://nodejs.org/dist/v20.19.5/node-v20.19.5-win-x64.zip')
$NodeExeRel = 'node-v20.19.5-win-x64\node.exe'
$GitUrls = @(
    'https://registry.npmmirror.com/-/binary/git-for-windows/v2.47.1.windows.1/MinGit-2.47.1-64-bit.zip',
    'https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.1/MinGit-2.47.1-64-bit.zip')
$GitExeRel = 'cmd\git.exe'

function Say($msg) { Write-Host "`n>>> $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host "`n[错误] $msg" -ForegroundColor Red; exit 1 }

function Update-PathEnv {
    # 新装的程序写在注册表 PATH 里，当前窗口需要重新读取
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machine;$user"
}

function Add-UserPath($dir) {
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    if (-not $user) { $user = '' }
    if (($user -split ';') -notcontains $dir) {
        [Environment]::SetEnvironmentVariable('Path', "$dir;$user".TrimEnd(';'), 'User')
    }
    Update-PathEnv
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

function Get-Download($urls, $fileName) {
    $dest = Join-Path $env:TEMP $fileName
    foreach ($u in $urls) {
        Write-Host "下载 $fileName ..."
        try {
            Invoke-WebRequest -Uri $u -OutFile $dest -UseBasicParsing
            return $dest
        } catch {
            Write-Host "  这个地址下载失败，换下一个: $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
    Fail "$fileName 下载失败，请检查网络后重新运行。"
}

function Install-PortableZip($urls, $name, $exeRel) {
    $target = Join-Path $Tools $name
    $zip = Get-Download $urls "$name.zip"
    Say "解压 $name（需要一两分钟）..."
    if (Test-Path $target) { Remove-Item $target -Recurse -Force }
    New-Item -ItemType Directory -Path $target -Force | Out-Null
    # 系统自带 tar（Win10 1803+）解压快得多；没有就用 Expand-Archive
    $tar = Join-Path $env:SystemRoot 'System32\tar.exe'
    if (Test-Path $tar) { & $tar -xf $zip -C $target }
    if (-not (Test-Path $tar) -or $LASTEXITCODE -ne 0) {
        Expand-Archive -Path $zip -DestinationPath $target -Force
    }
    Remove-Item $zip -Force
    $exe = Join-Path $target $exeRel
    if (-not (Test-Path $exe)) { Fail "$name 解压后没有找到 $exeRel" }
    Add-UserPath (Split-Path $exe -Parent)
}

function Install-Python {
    $exe = Get-Download $PythonUrls 'python-3.12.10-amd64.exe'
    Say '安装 Python（静默安装，需要一两分钟）...'
    $p = Start-Process -FilePath $exe -Wait -PassThru -ArgumentList `
        '/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_launcher=0', 'Include_test=0'
    Remove-Item $exe -Force -ErrorAction SilentlyContinue
    if ($p.ExitCode -ne 0 -and $p.ExitCode -ne 3010) { Fail "Python 安装失败（退出码 $($p.ExitCode)）。" }
    Update-PathEnv
}

Write-Host '========================================' -ForegroundColor Green
Write-Host '   StockPanel 股票分析 - 一键安装' -ForegroundColor Green
Write-Host '========================================' -ForegroundColor Green

if ([Environment]::OSVersion.Version.Major -lt 10 -or $PSVersionTable.PSVersion.Major -lt 5) {
    Fail '需要 Windows 10 或更高版本（Win7/Win8 无法运行新版 Python 和 Node.js）。'
}
if (-not [Environment]::Is64BitOperatingSystem) {
    Fail '需要 64 位 Windows。'
}
if (-not (Test-Path $EnvSource) -and -not (Test-Path "$Repo\backend\.env")) {
    Fail "没找到密钥文件 stockpanel.env。请把整个安装包解压后再运行，不要直接在压缩包里双击。"
}

Update-PathEnv

# ---- 1. 基础软件 ----
Say '检查基础软件（Git / Python / Node.js）...'
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Install-PortableZip $GitUrls 'git' $GitExeRel
}
if (-not (Test-Python)) {
    Install-Python
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Install-PortableZip $NodeUrls 'node' $NodeExeRel
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
