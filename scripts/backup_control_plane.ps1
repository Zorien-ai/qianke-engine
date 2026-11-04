# 定时备份（Windows 任务计划程序 / PowerShell）
# 用法：pwsh -File scripts/backup_control_plane.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Python venv not found: $python"
}
New-Item -ItemType Directory -Force -Path (Join-Path $root "logs") | Out-Null
& $python "scripts\backup_control_plane.py" --keep 7 *>> (Join-Path $root "logs\backup.log")
if ($LASTEXITCODE -ne 0) {
    throw "backup failed with exit code $LASTEXITCODE"
}
