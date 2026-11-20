# Run with Windows PowerShell 5.1 or PowerShell 7+.
[CmdletBinding()]
param(
    [switch]$NoUI,
    [switch]$AllVersions,
    [string[]]$Versions,
    [switch]$Help
)

# Anki releases and their pinned environments come from tools/anki_matrix.json;
# tools/anki_env.py selects and prepares them. The latest stable release is the default.

if ($Help) {
    Write-Host 'Usage: .\tools\test.ps1 [-NoUI] [-AllVersions | -Versions 2.1.50,26.9.4]'
    Write-Host 'Test the latest stable release by default; -AllVersions tests every release in'
    Write-Host 'tools/anki_matrix.json that this platform can run.'
    Write-Host 'Run unit and UI tests; -NoUI skips UI scenarios.'
    exit 0
}

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
# Check native exit codes explicitly, including under PowerShell 7.3+.
$PSNativeCommandUseErrorActionPreference = $false
$selectArguments = @()
if ($PSBoundParameters.ContainsKey('Versions')) {
    if ($AllVersions) {
        throw 'Cannot combine -AllVersions with -Versions.'
    }
    if (-not $Versions.Count) {
        throw 'Specify at least one Anki version.'
    }
    foreach ($version in $Versions) {
        if ($version -notmatch '^[0-9][0-9A-Za-z.+-]*$') {
            throw "Invalid Anki version: $version"
        }
    }
    $selectArguments = $Versions
} elseif ($AllVersions) {
    $selectArguments = @('--all')
}

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    $command = Get-Command $Executable -CommandType Application -ErrorAction Stop |
        Select-Object -First 1
    # Windows PowerShell may turn native stderr into error records. The native
    # exit code determines success; diagnostic output must not abort a command.
    $ErrorActionPreference = 'Continue'
    & $command.Source @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Executable exited with status $LASTEXITCODE"
    }
}

$environmentNames = @(
    'UV_CACHE_DIR', 'UV_PYTHON_INSTALL_DIR', 'UV_NO_PROGRESS', 'UV_NO_CONFIG', 'UV_SYSTEM_CERTS',
    'PYTEST_DISABLE_PLUGIN_AUTOLOAD', 'QT_QPA_PLATFORM', 'QTWEBENGINE_DISABLE_SANDBOX'
)
$savedEnvironment = @{}
foreach ($name in $environmentNames) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$exitCode = 0
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    $cache = if ($env:ANKI_TEST_CACHE) { $env:ANKI_TEST_CACHE } else {
        Join-Path $root '.test-cache'
    }
    $null = New-Item -ItemType Directory -Force -Path $cache
    $cache = (Resolve-Path -LiteralPath $cache).Path
    $env:UV_CACHE_DIR = Join-Path $cache 'downloads'
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $cache 'python'
    $env:UV_NO_PROGRESS = '1'
    $env:UV_NO_CONFIG = '1'
    $env:UV_SYSTEM_CERTS = 'true'
    $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'

    $bootstrapArguments = @()
    if ($env:ANKI_TEST_BOOTSTRAP_PYTHON) {
        $bootstrap = $env:ANKI_TEST_BOOTSTRAP_PYTHON
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        $bootstrap = 'py'
        $bootstrapArguments = @('-3')
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        $bootstrap = 'python'
    } elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
        $bootstrap = 'python3'
    } else {
        throw 'Install Python 3.10+ or set ANKI_TEST_BOOTSTRAP_PYTHON to its executable path.'
    }
    Invoke-Checked $bootstrap ($bootstrapArguments + @(
        '-c', 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'
    ))
    $uv = Invoke-Checked $bootstrap ($bootstrapArguments + @('tools/bootstrap_test_uv.py', $cache))
    if (-not ($uv -is [string]) -or -not (Test-Path -LiteralPath $uv -PathType Leaf)) {
        throw 'The uv bootstrap did not return an executable path.'
    }

    $ANKI_VERSIONS = @(Invoke-Checked $bootstrap ($bootstrapArguments + @('tools/anki_env.py', 'select') + $selectArguments))
    function Initialize-AnkiEnvironment([string]$Version) {
        $interpreter = Invoke-Checked $bootstrap ($bootstrapArguments + @('tools/anki_env.py', 'prepare', $cache, $uv, $Version))
        if (-not ($interpreter -is [string]) -or -not (Test-Path -LiteralPath $interpreter -PathType Leaf)) {
            throw "Preparing Anki $Version did not return an interpreter path."
        }
        return $interpreter
    }

    # The repository checks need Python 3.10+ and jsonschema 4.18, not a particular Anki.
    Write-Host 'Checking the API contract, documentation and coverage'
    $latest = Invoke-Checked $bootstrap ($bootstrapArguments + @('tools/anki_env.py', 'select'))
    $checkPython = Initialize-AnkiEnvironment $latest
    Invoke-Checked $checkPython @('tools/build_api_contract.py', '--check')
    Invoke-Checked $checkPython @('tools/check_api_spec.py')
    Invoke-Checked $checkPython @('tools/check_api_docs.py')
    Invoke-Checked $checkPython @('tools/check_api_coverage.py')
    $passed = @()
    $failed = @()
    foreach ($version in $ANKI_VERSIONS) {
        try {
            Write-Host "`nTesting Anki $version"
            $interpreter = Initialize-AnkiEnvironment $version
            try {
                if (-not $env:QT_QPA_PLATFORM) { $env:QT_QPA_PLATFORM = 'offscreen' }
                Invoke-Checked $interpreter @('-m', 'pytest', '-q', '--tb=short', 'tests_api')
            } finally {
                [Environment]::SetEnvironmentVariable('QT_QPA_PLATFORM',
                    $savedEnvironment['QT_QPA_PLATFORM'], 'Process')
            }
            if (-not $NoUI) {
                Write-Host "`nRunning all UI scenarios for Anki $version"
                if (-not $env:QTWEBENGINE_DISABLE_SANDBOX) {
                    $env:QTWEBENGINE_DISABLE_SANDBOX = '1'
                }
                Invoke-Checked $interpreter @('tools/smoke_gui.py', 'all')
            } else {
                Write-Host 'UI scenarios disabled (-NoUI).'
            }
            Invoke-Checked $interpreter @('-m', 'compileall', '-q', 'plugin', 'tools', 'tests_api')
            $passed += $version
        } catch {
            Write-Host "FAIL ${version}: $_" -ForegroundColor Red
            $failed += $version
        }
    }
    Write-Host "`nAnki test matrix"
    foreach ($version in $passed) { Write-Host "PASS $version" }
    foreach ($version in $failed) { Write-Host "FAIL $version" }
    if ($failed.Count) {
        $exitCode = 1
    } else {
        Invoke-Checked 'git' @('diff', 'HEAD', '--check')
    }
} catch {
    Write-Host "Test runner failed: $_" -ForegroundColor Red
    $exitCode = 1
} finally {
    foreach ($name in $environmentNames) {
        [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process')
    }
    Pop-Location
}
exit $exitCode
