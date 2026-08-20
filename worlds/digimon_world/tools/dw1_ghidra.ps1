# Standard wrapper for headless Ghidra runs against the DW1 project.
#
#   powershell -File dw1_ghidra.ps1 -ReadOnly -Script DW1ExportFunc.java 8010643C work\dw1_re\decomp\isTriggerSet
#   powershell -File dw1_ghidra.ps1 -ReadOnly -Script DW1FunctionStats.java
#
# Everything after -Script <name> is passed to the Ghidra script as its arguments.
# Scripts are looked up in worlds\digimon_world\tools\ghidra_scripts. Output goes to stdout
# (filtered to script lines) and the full log to work\dw1_re\ghidra_last.log.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Script,
    [switch]$ReadOnly,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$ScriptArgs = @()
)

$env:JAVA_HOME = "C:\opt\java\Java21"
$ghidra = "C:\opt\tools\ghidra\ghidra_12.1.2_PUBLIC\support\analyzeHeadless.bat"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$proj = Join-Path $repo "work\dw1_re\ghidra"
$scripts = Join-Path $PSScriptRoot "ghidra_scripts"
$log = Join-Path $repo "work\dw1_re\ghidra_last.log"

$argv = @($proj, "DW1", "-process", "SLUS_010.32", "-noanalysis",
          "-scriptPath", $scripts, "-postScript", $Script) + $ScriptArgs
if ($ReadOnly) { $argv += "-readOnly" }

& $ghidra @argv *> $log
$exit = $LASTEXITCODE
Get-Content $log | Where-Object { $_ -match [regex]::Escape($Script) + ">" } | ForEach-Object {
    $_ -replace "^INFO\s+$([regex]::Escape($Script))>\s*", "" -replace "\s*\(GhidraScript\)\s*$", ""
}
if ($exit -ne 0) { Write-Warning "headless exit=$exit -- see $log" }
exit $exit
