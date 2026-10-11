# Contributing

Use [README.md](README.md) to set up the add-on and [ARCHITECTURE.md](ARCHITECTURE.md)
to understand request admission, native collection work, and GUI completion.

## API changes

New integrations use [API v1](API_V1.md). Existing applications use the
[legacy API](API_LEGACY.md); preserve its public action names, parameters, defaults,
authentication, and versioned response shapes.

For new or changed behavior:

1. Update the source schema in `api-v1.schema.json` and implement the shared service
   or GUI adapter. Keep collection work serialized and GUI access on Qt's main thread.
2. Run `python tools/build_api_contract.py` to regenerate `plugin/contract.py`.
   Do not edit the generated file by hand.
3. Update the appropriate API guide with parameter and result documentation and a
   valid request example. Add behavior tests to `tests_api/`.
   Update the evidence and gaps in `tests_api/api_coverage.json`, then regenerate
   [the coverage inventory](API_TEST_COVERAGE.md) with
   `python tools/check_api_coverage.py --write`. Keep native, mocked, and real GUI
   evidence distinct; shared service coverage does not establish legacy action coverage.
4. Run `./test.sh` or `.\test.ps1` on Windows. Add supported published Anki versions to both runners' version arrays when
   expanding the compatibility matrix.

Use temporary collections and profiles for tests. `./test.sh` runs unit tests and
GUI smoke scenarios by default; UI testing requires a display. Use `--no-ui` to
run only unit and contract checks (`-NoUI` with PowerShell). The Windows runner
uses the same tests and cached environments. Bootstrap downloads use Windows
certificate validation, and uv uses the system certificate store; HTTPS
verification and wheel SHA-256 checks remain enabled. Run UI tests in an interactive
desktop session. Sync testing requires a disposable account.

The ZIP builder checks the generated contract and packages the add-on entry point
and manifest at the archive root. It preserves the checkout and excludes caches,
per-installation `meta.json`, and `user_files/` from the archive.

The primary testing goal is compatibility with changing Anki internals. Prefer
real native collection/service calls and observable effects over mocks of Anki.
Use real GUI scenarios to check widget/editor/reviewer APIs, lifecycle hooks, and
asynchronous completion. Shared native behavior needs one effective compatibility
test; legacy translation needs separate assertions. HTTP coverage is useful but
is not required per method.

Exceedingly difficult GUI effects may be deferred in `ui_deferrals` in the inventory.
State the reason and a practical alternative. Keep the remaining compatibility
gap visible; neither a deferral nor a mocked result proves that Anki's GUI still works.

Describe the resulting behavior and validation in your pull request. Mention any
remaining integration limits. Packaging is optional for validation; `package.sh`
builds the ZIP without cleaning the checkout.
