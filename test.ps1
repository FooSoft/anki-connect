# Run with Windows PowerShell 5.1 or PowerShell 7+.
[CmdletBinding()]
param(
    [switch]$NoUI,
    [string[]]$Versions,
    [switch]$Help
)

# Edit this array to define the default Anki compatibility matrix.
$ANKI_VERSIONS = @(
    '26.8'
    '26.9.3'
)

if ($Help) {
    Write-Host 'Usage: .\test.ps1 [-NoUI] [-Versions 26.8,26.9.3]'
    Write-Host 'Run unit and UI tests for each version; -NoUI skips UI scenarios.'
    exit 0
}

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
# Check native exit codes explicitly, including under PowerShell 7.3+.
$PSNativeCommandUseErrorActionPreference = $false
if ($PSBoundParameters.ContainsKey('Versions')) {
    $ANKI_VERSIONS = $Versions
}
if (-not $ANKI_VERSIONS.Count) {
    throw 'Specify at least one Anki version.'
}
foreach ($version in $ANKI_VERSIONS) {
    if ($version -notmatch '^[0-9][0-9A-Za-z.+-]*$') {
        throw "Invalid Anki version: $version"
    }
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
Push-Location $PSScriptRoot
try {
    $cache = if ($env:ANKI_TEST_CACHE) { $env:ANKI_TEST_CACHE } else {
        Join-Path $PSScriptRoot '.test-cache'
    }
    $null = New-Item -ItemType Directory -Force -Path $cache
    $cache = (Resolve-Path -LiteralPath $cache).Path
    $env:UV_CACHE_DIR = Join-Path $cache 'downloads'
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $cache 'python'
    $env:UV_NO_PROGRESS = '1'
    $env:UV_NO_CONFIG = '1'
    $env:UV_SYSTEM_CERTS = 'true'
    $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
    $testPython = if ($env:ANKI_TEST_PYTHON) { $env:ANKI_TEST_PYTHON } else { '3.13' }

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

    $verifyVersions = @'
from importlib.metadata import version
import sys
from packaging.version import Version
requested = Version(sys.argv[1])
for name in ('anki', 'aqt'):
    actual = version(name)
    if Version(actual) != requested:
        raise RuntimeError(f'{name}: expected {requested}, installed {actual}')
    print(f'{name}=={actual}')
'@
    $passed = @()
    $failed = @()
    foreach ($version in $ANKI_VERSIONS) {
        try {
            Write-Host "`nTesting Anki $version"
            $environment = Join-Path $cache "envs/anki-$version"
            if (-not (Test-Path -LiteralPath $environment -PathType Container)) {
                Invoke-Checked $uv @('venv', '--python', $testPython, $environment)
            }
            $interpreter = Join-Path $environment 'Scripts/python.exe'
            if (-not (Test-Path -LiteralPath $interpreter -PathType Leaf)) {
                $interpreter = Join-Path $environment 'bin/python'
            }
            Invoke-Checked $uv @('pip', 'install', '--python', $interpreter,
                "anki==$version", "aqt==$version", 'jsonschema>=4.18', 'pytest>=8')
            Invoke-Checked $uv @('pip', 'check', '--python', $interpreter)
            # Send Python source through stdin to avoid Windows native quote escaping.
            $verifyVersions | & $interpreter - $version
            if ($LASTEXITCODE -ne 0) { throw 'Installed Anki version validation failed.' }
            Invoke-Checked $interpreter @('tools/build_api_contract.py', '--check')
            Invoke-Checked $interpreter @('tools/check_api_spec.py')
            Invoke-Checked $interpreter @('tools/check_api_docs.py')
            Invoke-Checked $interpreter @('tools/check_api_coverage.py')
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
