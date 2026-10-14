# Bootstrap claude-toolkit on Windows: install the `ctk` command, then run `ctk setup`.
# Asks before every change. Usage: .\install.ps1 [-Yes] [-DryRun]
# The same steps as install.sh; Claude Code runs the plugin's hooks in Git Bash.
[CmdletBinding()]
param(
    [Alias('y')][switch]$Yes,
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'

$RepoDir = $PSScriptRoot

function Test-Command([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Confirm-Step([string]$Question) {
    if ($Yes) { return $true }
    if ([Console]::IsInputRedirected -or -not [Environment]::UserInteractive) {
        [Console]::Error.WriteLine("confirmation required: $Question (no terminal; rerun with -Yes after reviewing the plan)")
        exit 3
    }
    $answer = Read-Host "$Question [y/N]"
    return @('y', 'yes', 's', 'sim') -contains $answer.Trim().ToLower()
}

Write-Output 'claude-toolkit installer'
Write-Output 'plan:'
if (-not (Test-Command 'uv')) { Write-Output '  0. install uv (https://docs.astral.sh/uv/)' }
Write-Output "  1. uv tool install --editable $RepoDir   (provides ``ctk`` in ~\.local\bin)"
Write-Output '  2. ctk setup   (shows its own plan and asks before each change)'
if (-not (Test-Command 'bash')) {
    Write-Output '  note: Git Bash not found; Claude Code needs it for the Bash tool and the ctk plugin hooks (https://git-scm.com)'
}
if ($DryRun) { exit 0 }

if (-not (Test-Command 'uv')) {
    if (Confirm-Step 'uv is missing. Install it with the official installer (irm https://astral.sh/uv/install.ps1 | iex)?') {
        powershell -NoProfile -ExecutionPolicy ByPass -Command 'irm https://astral.sh/uv/install.ps1 | iex'
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        $env:Path = "$HOME\.local\bin;$env:Path"
    } else {
        [Console]::Error.WriteLine('uv is required; install it and rerun .\install.ps1')
        exit 1
    }
}

if (Confirm-Step "Install the ctk command from $RepoDir?") {
    uv tool install --editable --force "$RepoDir"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
    Write-Output 'skipped: ctk was not installed'
    exit 0
}

$bin = Join-Path $HOME '.local\bin'
if (-not (($env:Path -split ';') -contains $bin)) {
    Write-Output 'note: ~\.local\bin is not on PATH; run `uv tool update-shell` and restart the shell'
    $env:Path = "$bin;$env:Path"
}

if ($Yes) { ctk setup --yes } else { ctk setup }
exit $LASTEXITCODE
