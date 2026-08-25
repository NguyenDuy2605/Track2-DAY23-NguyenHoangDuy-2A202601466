# [WIN HELPER] Khoi chay pipeline lab trong tien trinh wsl.exe DOC LAP (an window).
# Tien trinh nay khong gan vao terminal cua tool nen khong bi kill khi terminal dong.
$repo = "D:\Track2-DAY23-NguyenHoangDuy-2A202601466"
if (-not (Test-Path "$repo\run")) { New-Item -ItemType Directory -Path "$repo\run" | Out-Null }
Start-Process -FilePath "wsl.exe" `
  -ArgumentList @("-d","Ubuntu","--","bash","/mnt/d/Track2-DAY23-NguyenHoangDuy-2A202601466/scripts/wsl/lab_all.sh") `
  -WindowStyle Hidden `
  -RedirectStandardOutput "$repo\run\lab_all.log" `
  -RedirectStandardError "$repo\run\lab_all.err.log"
Write-Host "DETACHED-LAUNCHED"