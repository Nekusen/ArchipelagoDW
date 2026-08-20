# Launches PCSX-Redux (RE workbench) with the DW1 image and the scripted-RE bootstrap.
#
# Usage examples (from anywhere):
#   powershell -File dw1_redux_launch.ps1                                   # plain boot, web server + debugger on
#   powershell -File dw1_redux_launch.ps1 -Script ...\dw1_redux_watch.lua   # boot with the watchpoint harness
#   powershell -File dw1_redux_launch.ps1 -Gdb                              # also expose the GDB server (port 3333)
#   powershell -File dw1_redux_launch.ps1 -Paused                           # start paused (arm breakpoints first)
#
# The working directory is set to work\dw1_re so every file the Lua side writes
# (logs, dumps, savestates) lands there. See TOOLING.md for the full picture.

[CmdletBinding()]
param(
    [string]$Iso = "",
    [string]$Script = "",
    [switch]$Gdb,
    [switch]$Paused,
    [switch]$NoFastboot,
    [switch]$FreshCards  # delete workbench memory cards first -- required before starting a NEW game:
                         # DW1 auto-saves on new-game creation, and an occupied slot blocks the
                         # "create game" flow at the START SLOT screen on the next boot
)

$exe = "C:\opt\tools\pcsx-redux\pcsx-redux.exe"
if (-not (Test-Path $exe)) { throw "PCSX-Redux not found at $exe (see TOOLING.md)" }

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
if (-not $Iso) { $Iso = Join-Path $repo "Digimon World (USA).bin" }
if (-not (Test-Path $Iso)) { throw "Game image not found: $Iso" }

$work = Join-Path $repo "work\dw1_re"
New-Item -ItemType Directory -Force $work | Out-Null

if ($FreshCards) {
    Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $work "memcard1.mcd"), (Join-Path $work "memcard2.mcd")
    Write-Host "FreshCards: workbench memory cards deleted (redux recreates them formatted)"
}

# Pre-seed the portable settings so the web server (and GDB server, if asked) bind at startup:
# redux only starts them during its SettingsLoaded pass, so flipping them later has no effect.
$settingsPath = Join-Path $work "pcsx.json"
if (Test-Path $settingsPath) {
    $json = Get-Content $settingsPath -Raw | ConvertFrom-Json
} else {
    $json = '{"emulator":{"Debug":{}}}' | ConvertFrom-Json
}
if (-not $json.emulator) { $json | Add-Member -NotePropertyName emulator -NotePropertyValue (@{} | ConvertTo-Json | ConvertFrom-Json) }
if (-not $json.emulator.Debug) { $json.emulator | Add-Member -NotePropertyName Debug -NotePropertyValue (@{} | ConvertTo-Json | ConvertFrom-Json) }
foreach ($pair in @(@("WebServer", $true), @("Debug", $true), @("GdbServer", [bool]$Gdb))) {
    $name, $value = $pair
    if ($null -eq $json.emulator.Debug.$name) {
        $json.emulator.Debug | Add-Member -NotePropertyName $name -NotePropertyValue $value
    } else {
        $json.emulator.Debug.$name = $value
    }
}
$json | ConvertTo-Json -Depth 20 | Set-Content -Path $settingsPath -Encoding utf8

# Compose a single boot script: redux takes one -dofile, so chain from here.
$bootstrap = (Join-Path $PSScriptRoot "dw1_redux_bootstrap.lua") -replace "\\", "/"
$bootLua = Join-Path $work "boot.lua"
$lines = @("Support.extra.dofile('$bootstrap')")
if ($Script) {
    $scriptFwd = (Resolve-Path $Script).Path -replace "\\", "/"
    $lines += "Support.extra.dofile('$scriptFwd')"
}
Set-Content -Path $bootLua -Value ($lines -join "`n") -Encoding utf8

$argv = @(
    "-interpreter", "-debugger",
    "-stdout", "-lua_stdout", "-logfile", (Join-Path $work "redux_log.txt"),
    "-iso", $Iso,
    "-dofile", $bootLua
)
if (-not $NoFastboot) { $argv += "-fastboot" }
if ($Gdb) { $argv += @("-gdb", "-gdb-port", "3333") }
if (-not $Paused) { $argv += "-run" }
$argv += "-portable"  # keep settings inside C:\opt\tools\pcsx-redux; last so its optional arg stays empty

Push-Location $work
try {
    & $exe @argv
} finally {
    Pop-Location
}
