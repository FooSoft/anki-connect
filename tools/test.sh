#!/usr/bin/env bash
# Anki releases and their pinned environments come from tools/anki_matrix.json;
# tools/anki_env.py selects and prepares them. The latest stable release is the default.
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
CACHE_DIR="${ANKI_TEST_CACHE:-$ROOT_DIR/.test-cache}"
BOOTSTRAP_PYTHON="${ANKI_TEST_BOOTSTRAP_PYTHON:-python3}"
RUN_UI=1
RUN_ALL_VERSIONS=0
RUN_COVERAGE=0
requested_versions=()
for argument in "$@"; do
    case "$argument" in
        --no-ui) RUN_UI=0 ;;
        --all-versions) RUN_ALL_VERSIONS=1 ;;
        --coverage) RUN_COVERAGE=1 ;;
        -h|--help)
            printf 'Usage: ./tools/test.sh [--no-ui] [--coverage] [--all-versions | ANKI_VERSION ...]\n'
            printf 'Test the latest stable release by default; --all-versions tests every release in\n'
            printf 'tools/anki_matrix.json. Versions may be release tags (26.09.4) or PyPI versions (26.9.4).\n'
            printf 'Run unit and UI tests; --no-ui skips UI scenarios.\n'
            printf '%s\n' '--coverage measures plugin/ line and branch coverage (Python 3.9+ releases) and'
            printf 'writes a combined report to coverage-report/ (ANKI_TEST_COVERAGE_DIR overrides).\n'
            exit 0
            ;;
        -*)
            printf 'Unknown option: %s\nUse --help for usage.\n' "$argument" >&2
            exit 2
            ;;
        *) requested_versions+=("$argument") ;;
    esac
done
if (( ${#requested_versions[@]} > 0 && RUN_ALL_VERSIONS )); then
    printf 'Cannot combine --all-versions with explicit Anki versions.\n' >&2
    exit 2
fi
for version in "${requested_versions[@]}"; do
    if [[ ! "$version" =~ ^[0-9][0-9A-Za-z.+-]*$ ]]; then
        printf 'Invalid Anki version: %s\n' "$version" >&2
        exit 2
    fi
done
select_arguments=("${requested_versions[@]}")
if (( RUN_ALL_VERSIONS )); then select_arguments=(--all); fi
selected="$("$BOOTSTRAP_PYTHON" tools/anki_env.py select "${select_arguments[@]}")"
mapfile -t ANKI_VERSIONS <<< "$selected"
mkdir -p "$CACHE_DIR"
CACHE_DIR="$(cd -- "$CACHE_DIR" && pwd)"
export UV_CACHE_DIR="$CACHE_DIR/downloads"
export UV_PYTHON_INSTALL_DIR="$CACHE_DIR/python"
export UV_NO_PROGRESS=1
export UV_NO_CONFIG=1
# All dependencies and interpreters belong to the cache; never use a personal collection.
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
# Early Rust backends request an executable stack, which glibc 2.41+ refuses by default.
export GLIBC_TUNABLES="${GLIBC_TUNABLES:-glibc.rtld.execstack=2}"
UV_BIN="$("$BOOTSTRAP_PYTHON" tools/bootstrap_test_uv.py "$CACHE_DIR")"
prepare() {
    "$BOOTSTRAP_PYTHON" tools/anki_env.py prepare "$CACHE_DIR" "$UV_BIN" "$1"
}
COVERAGE_DIR="${ANKI_TEST_COVERAGE_DIR:-$ROOT_DIR/coverage-report}"
install_coverage() {
    if ! "$1" -c 'import sys; sys.exit(sys.version_info < (3, 9))'; then
        printf 'Coverage measurement needs Python 3.9+; Anki %s uses an older interpreter.\n' "$2" >&2
        return 1
    fi
    # Coverage reads pyproject.toml settings through tomli before Python 3.11.
    "$UV_BIN" pip install --quiet --python "$1" 'coverage[toml]>=7.10'
}

# The repository checks need Python 3.10+ and jsonschema 4.18, not a particular Anki.
printf 'Checking the API contract, documentation and coverage\n'
CHECK_PYTHON="$(prepare "$("$BOOTSTRAP_PYTHON" tools/anki_env.py select)")"
"$CHECK_PYTHON" tools/build_api_contract.py --check
"$CHECK_PYTHON" tools/check_api_spec.py
"$CHECK_PYTHON" tools/check_api_docs.py
"$CHECK_PYTHON" tools/check_api_coverage.py
if (( RUN_COVERAGE )); then
    install_coverage "$CHECK_PYTHON" latest
    rm -rf "$COVERAGE_DIR"
    mkdir -p "$COVERAGE_DIR/data"
    COVERAGE_DIR="$(cd -- "$COVERAGE_DIR" && pwd)"
    # Settings are in pyproject.toml; GUI scenario subprocesses inherit them.
    export COVERAGE_FILE="$COVERAGE_DIR/data/.coverage"
fi

run_version() (
    set -e
    local version="$1"
    printf '\nTesting Anki %s\n' "$version"
    local interpreter
    interpreter="$(prepare "$version")"
    local run_python=("$interpreter")
    if (( RUN_COVERAGE )); then
        install_coverage "$interpreter" "$version"
        run_python+=(-m coverage run)
    fi
    # Early releases share, then delete at exit, a fixed anki_temp folder in the temp directory.
    TMPDIR="$(mktemp -d)"
    export TMPDIR
    trap 'rm -rf "$TMPDIR"' EXIT
    # This is the complete maintained unit suite, including both API protocols.
    QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}" "${run_python[@]}" -m pytest -q --tb=short tests_api
    if (( RUN_UI )); then
        printf '\nRunning all UI scenarios for Anki %s\n' "$version"
        if [[ "$(uname -s)" == Linux && -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" && -z "${QT_QPA_PLATFORM:-}" ]]; then
            printf 'UI tests require a display. Use xvfb-run make test or make test-unit.\n' >&2
            exit 1
        fi
        ui_env=()
        if [[ "${QT_QPA_PLATFORM:-}" == offscreen ]]; then
            # With a display, offscreen Qt 6.2-6.5 renders through GLX and crashes in WebEngine;
            # without one, Qt 5 Quick widgets need the software backend instead of OpenGL.
            ui_env=(-u DISPLAY -u WAYLAND_DISPLAY "QT_QUICK_BACKEND=${QT_QUICK_BACKEND:-software}")
        fi
        # Disposable profiles and trusted test content; allow WebEngine in CI containers.
        env ${ui_env[@]+"${ui_env[@]}"} QTWEBENGINE_DISABLE_SANDBOX="${QTWEBENGINE_DISABLE_SANDBOX:-1}" \
            "${run_python[@]}" tools/smoke_gui.py all
    else
        printf 'UI scenarios disabled (--no-ui).\n'
    fi
    "$interpreter" -m compileall -q plugin tools tests_api
)

# Do not invoke the subshell as an if-condition: Bash would suppress its errexit.
passed=()
failed=()
for version in "${ANKI_VERSIONS[@]}"; do
    set +e
    run_version "$version"
    result=$?
    set -e
    if (( result == 0 )); then
        passed+=("$version")
    else
        failed+=("$version")
    fi
done
printf '\nAnki test matrix\n'
for version in "${passed[@]}"; do printf 'PASS %s\n' "$version"; done
for version in "${failed[@]}"; do printf 'FAIL %s\n' "$version"; done
if (( RUN_COVERAGE )) && compgen -G "$COVERAGE_DIR/data/.coverage.*" > /dev/null; then
    printf '\nCoverage of plugin/ for Anki %s\n' "${ANKI_VERSIONS[*]}"
    "$CHECK_PYTHON" -m coverage combine --quiet
    "$CHECK_PYTHON" -m coverage report
    "$CHECK_PYTHON" -m coverage html --quiet -d "$COVERAGE_DIR/html"
    "$CHECK_PYTHON" -m coverage json --quiet -o "$COVERAGE_DIR/coverage.json"
    printf 'Coverage report: %s\n' "$COVERAGE_DIR/html/index.html"
fi
if (( ${#failed[@]} > 0 )); then exit 1; fi

git diff HEAD --check
