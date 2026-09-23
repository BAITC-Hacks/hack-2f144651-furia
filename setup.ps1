param([string]$PythonExe = '')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

if (-not $PythonExe) {
    $pythonLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pythonLauncher) {
        try {
            $detectedPython = & $pythonLauncher.Source -3.12 -c 'import sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0) { $PythonExe = $detectedPython }
        } catch { $detectedPython = '' }
    }
    if (-not $PythonExe) {
        $bundledPython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
        if (Test-Path -LiteralPath $bundledPython) { $PythonExe = $bundledPython }
    }
}
if (-not $PythonExe) { throw 'Python 3.12 not found. Install Python 3.12 or run setup.ps1 -PythonExe C:\path\to\python.exe' }
& $PythonExe -c 'import sys; assert sys.version_info[:2] == (3, 12), "This release is verified with Python 3.12"'
if ($LASTEXITCODE -ne 0) { throw 'Python version check failed' }

& $PythonExe -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed' }
& .\.venv\Scripts\python.exe -m pip install -r requirements.lock
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
Write-Output 'Ready. Run: .\.venv\Scripts\python.exe -m streamlit run app.py'
