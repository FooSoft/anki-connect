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
4. Run `./test.sh` or `.\test.ps1` on Windows. Add supported published Anki versions to both runners' version arrays when
   expanding the compatibility matrix.

Use temporary collections and profiles for tests. `./test.sh` runs unit tests and
GUI smoke scenarios by default; UI testing requires a display. Use `--no-ui` to
run only unit and contract checks (`-NoUI` with PowerShell). The Windows runner
uses the same tests and cached environments; run UI tests in an interactive
desktop session. Sync testing requires a disposable account.

Describe the resulting behavior and validation in your pull request. Mention any
remaining integration limits. Packaging is optional for validation; `package.sh`
builds the ZIP without cleaning the checkout.
