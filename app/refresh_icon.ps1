# app/refresh_icon.ps1
# Makes Windows re-read NgheTruyen.exe's icon instead of showing a cached one.
#
#     powershell -ExecutionPolicy Bypass -File app\refresh_icon.ps1
#
# Explorer caches icons by path and modification time, and the exe is rebuilt
# in place, so after a build the taskbar and Explorer can keep showing the old
# icon -- the Python/PyInstaller default -- even though the new one is in the
# file's resources. Windows only drops the cache when explorer.exe releases the
# icon-cache files, so this stops it, deletes them, and starts it again. Taskbar
# and desktop flash for a second; nothing else is affected.
#
# Needs elevation: the cache files are locked by Explorer and the delete is
# denied without it. If you would rather not restart Explorer, copy the exe to
# a new filename instead -- a path Windows has never cached.
$ErrorActionPreference = 'Stop'

$exe = Join-Path $PSScriptRoot 'NgheTruyen.exe'
if (-not (Test-Path $exe)) {
    Write-Error "not found: $exe (build it first: pyinstaller --noconfirm NgheTruyen.spec)"
}

$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host 'Elevation is needed to stop Explorer and delete its icon cache.' -ForegroundColor Yellow
    Write-Host 'A UAC prompt will follow; accept it and this window closes when done.'
    $arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $PSCommandPath)
    Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -Verb RunAs
    return
}

$explorerDir = Join-Path $env:LOCALAPPDATA 'Microsoft\Windows\Explorer'
$cache = @(Get-ChildItem $explorerDir -Filter 'iconcache*' -Force -ErrorAction SilentlyContinue)
$cache += @(Get-Item (Join-Path $env:LOCALAPPDATA 'IconCache.db') -Force -ErrorAction SilentlyContinue)
Write-Host "Found $($cache.Count) icon-cache files."

Write-Host 'Stopping Explorer...'
Stop-Process -Name explorer -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

$failed = 0
foreach ($file in $cache) {
    try {
        Remove-Item $file.FullName -Force -ErrorAction Stop
    } catch {
        $failed++
        Write-Warning "could not delete $($file.Name): $($_.Exception.Message)"
    }
}
Write-Host "Deleted $($cache.Count - $failed) of $($cache.Count)."

if (-not (Get-Process explorer -ErrorAction SilentlyContinue)) {
    Write-Host 'Starting Explorer...'
    Start-Process explorer.exe
}

# Tell the shell the file changed, so anything still holding the old icon
# redraws now rather than at the next logon.
Add-Type -Namespace Shell -Name Api -MemberDefinition @'
[DllImport("shell32.dll", CharSet = CharSet.Unicode)]
public static extern void SHChangeNotify(int eventId, uint flags, string item1, string item2);
'@
[Shell.Api]::SHChangeNotify(0x08000000, 0x0000, $exe, $null)  # SHCNE_UPDATEITEM, SHCNF_PATHW

Write-Host ''
Write-Host 'Done. The exe now shows:' -ForegroundColor Green
Write-Host '  - the icon in Explorer and on the desktop'
Write-Host '  - the icon in the taskbar when the App runs'
Write-Host '  - the icon in the Alt-Tab switcher'
Write-Host ''
Write-Host 'If a stale icon is still visible, the shell is reading an old copy:'
Write-Host 'copy the exe somewhere new and look at that.'
