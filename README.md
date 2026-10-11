# Anki-Connect

Anki-Connect lets applications search, create, and update notes and cards in a
running Anki Desktop collection through a local HTTP API.

**Use [API v1](API_V1.md) for new integrations.** It provides JSON-RPC 2.0,
consistent records, structured errors, and explicit completion for long-running
and interactive operations.

**Existing applications can keep using the [legacy API](API_LEGACY.md).** The root
endpoint, version 6 actions, parameter names, API key configuration, and response
formats remain available. Installing this rewrite does not require clients to
migrate to v1. The legacy guide documents corrected behavior and the limited
restrictions on unsafe historical operations.

## Install and run

This checkout requires **Anki Desktop 26.9.3 or later**. Version 26.9.3 is the tested
baseline; runtime capability checks identify unsupported methods on other versions.
Official Anki Desktop includes `jsonschema`, which this add-on uses for validation.

For this development checkout:

1. Run `./package.sh` to build `AnkiConnect.zip` from the source.
2. In Anki, open **Tools → Add-ons → Install from file**, then select the ZIP.
3. Restart Anki and keep it running while your application uses the API.

For development on Linux or macOS, `./link.sh` links `plugin/` into an existing Anki
add-ons directory. The published add-on at code
[2055492159](https://ankiweb.net/shared/info/2055492159) is the historical release;
it does not install this development rewrite. The ZIP builder preserves untracked
and ignored files.

## Make your first request

The default v1 endpoint is `http://127.0.0.1:8765/api/v1`:

```bash
curl --request POST http://127.0.0.1:8765/api/v1 \
  --header 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","id":1,"method":"decks.list","params":{}}'
```

```json
{"jsonrpc":"2.0","id":1,"result":[{"id":"1","name":"Default","kind":"normal","presetId":"1"}]}
```

Continue with the [v1 quick start and method reference](API_V1.md). It includes
Python and JavaScript clients and request examples for all 94 methods. Entity IDs
are strings. Long-running methods return operation handles; poll `operations.get`
for the final result. `api.describe` reports the available methods and limits.

The [legacy guide](API_LEGACY.md) covers all 122 actions, their existing numeric
IDs and response formats, and corresponding v1 methods. Both endpoints operate on
the same active collection.

## Configuration

Open **Tools → Add-ons → Anki-Connect → Config**, then restart Anki after changing
listener settings.

| Setting | Default | Purpose |
| --- | --- | --- |
| `webBindAddress` | `127.0.0.1` | Listen on the local machine. |
| `webBindPort` | `8765` | HTTP port. |
| `apiKey` | `null` | Optional authentication key. |
| `webCorsOriginList` | `["http://localhost"]` | Allowed browser origins. |
| `ignoreOriginList` | `[]` | Origins for which permission prompts are suppressed. |

When a key is configured, v1 uses `Authorization: Bearer <key>` and legacy requests
use the JSON body’s `key` property. Browser origins require permission separately.
See [v1 access rules](API_V1.md#requests-authentication-and-errors) and
[legacy authentication](API_LEGACY.md#authentication-and-response-versions).

On Windows, allow Anki through the firewall if prompted. Anki must remain running
and responsive for requests to complete.

## Development and tests

Run the current unit suite against isolated Anki environments:

```bash
./test.sh
```

Edit the `ANKI_VERSIONS` array at the top of [test.sh](test.sh) to test several
versions, or supply versions for a single run:

```bash
./test.sh 26.9.3
```

Only list versions published as both `anki` and `aqt` Python packages. Append any additional released versions to the command; availability is checked
when downloading. The script needs Bash, Python 3.10+, and network access on its first run. It downloads a pinned
`uv` tool and dependencies into ignored `.test-cache/`, downloads a cached Python
interpreter when needed, verifies the tool's SHA-256 digest, and creates a separate environment per Anki version. Anki Desktop
does not need to be installed or running. The entire current suite covers native
services, v1 dispatch, legacy forwarding, authentication, HTTP responses, and
ordered completion. Failed versions are reported together and make the script exit
with a failure status.

The runner also checks documentation examples, the source/generated contract,
Python compilation, and whitespace. Native tests use disposable collections and
controlled GUI admission; they do not certify an installed Windows bundle or real
Qt WebEngine timing. For real GUI scenarios, use a cached environment with a
working display:

```bash
.test-cache/envs/anki-26.9.3/bin/python tools/smoke_gui.py all
```

GUI scenarios use temporary profiles. Network sync needs separate testing with a
disposable account. Avoid personal collections for tests.

Read [ARCHITECTURE.md](ARCHITECTURE.md) for runtime structure and
[api-v1.schema.json](api-v1.schema.json) for the machine-readable contract. When
changing methods, update the schema and adapters, regenerate the contract with
`python tools/build_api_contract.py`, and update the appropriate API guide with
valid examples and behavior tests.

See [CONTRIBUTING.md](CONTRIBUTING.md) for change and review guidelines.
