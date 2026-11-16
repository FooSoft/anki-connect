# Anki-Connect

Anki-Connect lets applications search, create, and update notes and cards in a
running Anki Desktop collection through a local HTTP API.

**Use [API v1](API_V1.md) for new integrations.** It provides JSON-RPC 2.0,
consistent records, structured errors, and explicit completion for long-running
and interactive operations.

**Existing applications can keep using the [legacy API](API_LEGACY.md).** The root
endpoint, version 6 actions, parameter names, API key configuration, and response
formats remain available. Existing clients do not need to migrate to v1. See the
legacy guide for supported actions and compatibility details.

## Install and run

Anki-Connect requires **Anki Desktop 26.08 or later**. Compatibility is tested with
26.08 and 26.09.4. Use `api.describe` to check method availability in your running
Anki instance.

Install [Anki-Connect from AnkiWeb](https://ankiweb.net/shared/info/2055492159):

1. In Anki, open **Tools → Add-ons → Get Add-ons**.
2. Enter add-on code `2055492159` and confirm the installation.
3. Restart Anki and open the profile you want your application to use.

Keep Anki running while your application uses the API; requests operate on the
active profile's collection.

On macOS, Anki-Connect automatically suppresses App Nap after its HTTP listener
starts, keeping API requests responsive while Anki is minimized or in the
background. Suppression lasts until Anki exits and still allows normal system
sleep. No `defaults write` commands or separate App Nap add-on are needed.

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

For an existing integration, send requests to `http://127.0.0.1:8765/` using the
legacy action format:

```bash
curl --request POST http://127.0.0.1:8765/ \
  --header 'Content-Type: application/json' \
  --data '{"action":"deckNames","version":6,"params":{}}'
```

```json
{"result":["Default"],"error":null}
```

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

## Troubleshooting

- **Connection refused:** check that Anki is running, the add-on is enabled, and
  your client uses the configured address and port. Restart Anki after installing
  the add-on or changing listener settings.
- **Authentication or browser access errors:** check your API key and origin
  permissions using the access rules linked above.
- **A write is blocked by an editor:** close editors for the affected notes, then
  retry the request. See the API guide for method-specific requirements.
- **A method is unavailable:** call `api.describe` to inspect runtime capabilities
  and check the method's requirements in the API guide.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for API changes, tests, and review guidelines,
[ARCHITECTURE.md](ARCHITECTURE.md) for runtime structure, and
[api-v1.schema.json](api-v1.schema.json) for the machine-readable contract.

To install from source, download or clone this repository and run
`make package` (or `python tools/package_addon.py` on Windows).
In Anki, choose **Tools → Add-ons → Install from file**, select the generated
`AnkiConnect.zip`, and restart Anki. The ZIP replaces the existing Anki-Connect
add-on code while retaining its saved configuration.

For development on Linux or macOS, `make link` links `plugin/` into an existing
Anki add-ons directory. Use temporary profiles and collections when testing.
Run `make test` or `.\tools\test.ps1` on Windows for the latest Anki version in the matrix,
including GUI scenarios. To skip GUI scenarios, use `make test-unit` or
`.\tools\test.ps1 -NoUI`.
To test the full compatibility matrix, use `make test TEST_ARGS=--all-versions`,
`./tools/test.sh --all-versions`, or `.\tools\test.ps1 -AllVersions`.

Run `make help` for all development commands. Use `make test VERSIONS="26.9.4"`
to select Anki versions. The runners cache dependencies and interpreters in
`.test-cache/` at the repository root. `make check` runs contract, API documentation,
coverage, and syntax checks in your current Python environment; select an
environment with `make check PYTHON=/path/to/python`. Use `make contract` to
regenerate the bundled contract. The Make targets use the scripts in `tools/`,
which can also be run directly without Make.
