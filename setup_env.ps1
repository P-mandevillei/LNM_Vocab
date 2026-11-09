[CmdletBinding()]
param(
    [switch]$WithImporter
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$uvCommand = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue
$uvExecutable = if ($uvCommand) { $uvCommand.Source } else { $null }
if (-not $uvExecutable) {
    foreach ($candidate in @(
        (Join-Path $env:USERPROFILE '.local\bin\uv.exe'),
        (Join-Path $env:USERPROFILE '.cargo\bin\uv.exe')
    )) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $uvExecutable = $candidate
            break
        }
    }
}
if (-not $uvExecutable) {
    throw 'Install uv from https://docs.astral.sh/uv/getting-started/installation/ and rerun this script.'
}

$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$pythonVersion = (Get-Content -LiteralPath (Join-Path $PSScriptRoot '.python-version') -Raw).Trim()
Push-Location -LiteralPath $PSScriptRoot
try {
    & $uvExecutable venv --allow-existing --python $pythonVersion .venv
    if ($LASTEXITCODE -ne 0) { throw 'uv could not create the virtual environment.' }

    $installArguments = @('pip', 'install', '--python', $venvPython, '--link-mode', 'copy', '-r', 'requirements.txt')
    if ($WithImporter) {
        $installArguments += @('-r', 'quiz/requirements-import.txt')
    }
    & $uvExecutable @installArguments
    if ($LASTEXITCODE -ne 0) { throw 'uv could not install the project dependencies.' }

    & $uvExecutable pip check --python $venvPython
    if ($LASTEXITCODE -ne 0) { throw 'The virtual environment has incompatible dependencies.' }

    Write-Host "Virtual environment ready: $venvPython"
    Write-Host 'Activate: .\.venv\Scripts\Activate.ps1'
    Write-Host 'Run app:  .\.venv\Scripts\python.exe -m streamlit run quiz/streamlit_app.py'
}
finally {
    Pop-Location
}
