# Anki-Connect settings

Keep Anki running while applications use the API. Restart Anki after changing
listener settings.

- `webBindAddress`: listener address, normally `127.0.0.1` for local applications.
- `webBindPort`: listener port, normally `8765`.
- `apiKey`: optional authentication key; `null` disables key authentication.
  API v1 uses `Authorization: Bearer <key>`. Legacy requests use the body's `key`.
- `webCorsOriginList`: allowed browser origins, initially `["http://localhost"]`.
  Origin permission is separate from API key authentication.
- `ignoreOriginList`: origins for which permission prompts are suppressed.
- `apiLogPath`: optional log destination; `null` disables logging.

New applications use `POST http://127.0.0.1:8765/api/v1` with JSON-RPC 2.0.
Existing applications continue using the legacy endpoint at `/` with API version 6.
