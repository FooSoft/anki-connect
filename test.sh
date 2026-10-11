#!/usr/bin/env bash
# Edit this array to define the default Anki compatibility matrix.
ANKI_VERSIONS=(
    "26.9.3"
)

set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"
CACHE_DIR="${ANKI_TEST_CACHE:-$ROOT_DIR/.test-cache}"
BOOTSTRAP_PYTHON="${ANKI_TEST_BOOTSTRAP_PYTHON:-python3}"
TEST_PYTHON="${ANKI_TEST_PYTHON:-3.13}"
if (( $# > 0 )); then
    ANKI_VERSIONS=("$@")
fi
for version in "${ANKI_VERSIONS[@]}"; do
    if [[ ! "$version" =~ ^[0-9][0-9A-Za-z.+-]*$ ]]; then
        printf 'Invalid Anki version: %s\n' "$version" >&2
        exit 2
    fi
done
mkdir -p "$CACHE_DIR"
CACHE_DIR="$(cd -- "$CACHE_DIR" && pwd)"
export UV_CACHE_DIR="$CACHE_DIR/downloads"
export UV_PYTHON_INSTALL_DIR="$CACHE_DIR/python"
export UV_NO_PROGRESS=1
export UV_NO_CONFIG=1
# All dependencies and interpreters belong to the cache; never use a personal collection.
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
UV_BIN="$("$BOOTSTRAP_PYTHON" tools/bootstrap_test_uv.py "$CACHE_DIR")"

run_version() (
    set -e
    local version="$1"
    local environment="$CACHE_DIR/envs/anki-$version"
    local interpreter="$environment/bin/python"
    printf '\nTesting Anki %s\n' "$version"
    if [[ ! -d "$environment" ]]; then
        "$UV_BIN" venv --python "$TEST_PYTHON" "$environment"
    fi
    if [[ -f "$environment/Scripts/python.exe" ]]; then
        interpreter="$environment/Scripts/python.exe"
    fi
    "$UV_BIN" pip install --python "$interpreter" \
        "anki==$version" "aqt==$version" 'jsonschema>=4.18' 'pytest>=8'
    "$UV_BIN" pip check --python "$interpreter"
    "$interpreter" - "$version" <<'PY'
from importlib.metadata import version
import sys
from packaging.version import Version
requested = Version(sys.argv[1])
for name in ('anki', 'aqt'):
    actual = version(name)
    if Version(actual) != requested:
        raise RuntimeError(f'{name}: expected {requested}, installed {actual}')
    print(f'{name}=={actual}')
PY
    "$interpreter" tools/build_api_contract.py --check
    "$interpreter" tools/check_api_spec.py
    "$interpreter" tools/check_api_docs.py
    # This is the complete maintained unit suite, including both API protocols.
    "$interpreter" -m pytest -q --tb=short tests_api
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
if (( ${#failed[@]} > 0 )); then exit 1; fi

git diff HEAD --check
