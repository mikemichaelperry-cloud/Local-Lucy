# Local Lucy Web Interface

A minimal, optional HTTP input/output surface for Local Lucy v10. It does **not**
replace the PyQt HMI and does not duplicate routing, search, memory, model
execution, or response formatting. The web interface is a thin adapter around
the existing `execute_plan_python()` pipeline entry point.

---

## Architecture

```text
PyQt HMI ───┐
            ├── tools/router_py/main.py::execute_plan_python()
Web UI ─────┘
```

- The PyQt HMI submits text through `ui-v10/app/services/runtime_bridge.py`.
- The web adapter submits text through the same `execute_plan_python()`
  function with `surface="api"`.
- Routing, memory recall, web search/evidence, model selection, generation, and
  formatting remain inside `tools/router_py/`.

---

## Files

| File | Purpose |
|---|---|
| `web_adapter/__init__.py` | Package marker and version. |
| `web_adapter/__main__.py` | Enables `python -m web_adapter`. |
| `web_adapter/server.py` | aioHTTP server, auth, endpoints, pipeline calls. |
| `web_adapter/static.py` | Single dependency-free HTML/CSS/JS page. |
| `web_adapter/test_web_adapter.py` | Focused tests for the adapter. |
| `docs/web_interface.md` | This document. |

---

## Enabling and starting

The web server is **disabled by default**. Start it explicitly:

```bash
cd /home/mike/lucy-v10
source ui-v10/.venv/bin/activate
LUCY_WEB_ENABLED=1 python -m web_adapter
```

Then open:

```text
http://127.0.0.1:8765
```

---

## Configuration

All settings are environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `LUCY_WEB_ENABLED` | `false` | Must be `1`/`true`/`yes` to start the server. |
| `LUCY_WEB_HOST` | `127.0.0.1` | Bind address. Use a LAN/Tailscale IP only with auth. |
| `LUCY_WEB_PORT` | `8765` | Bind port. |
| `LUCY_WEB_AUTH_TOKEN` | *(none)* | Secret token or password. **Required** for non-loopback binds. |
| `LUCY_WEB_MAX_QUESTION` | `4000` | Maximum question length in characters. |

Example with authentication for Tailscale/LAN access:

```bash
export LUCY_WEB_ENABLED=1
export LUCY_WEB_HOST=100.64.0.1
export LUCY_WEB_PORT=8765
export LUCY_WEB_AUTH_TOKEN=$(openssl rand -hex 32)
python -m web_adapter
```

The browser will prompt for the token (Basic auth password; username is ignored).
You can also send it as a `Bearer` token:

```bash
curl -H "Authorization: Bearer $LUCY_WEB_AUTH_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"question": "Who was Ada Lovelace?"}' \
     http://100.64.0.1:8765/api/ask
```

---

## Remote access from Windows, Android, or Linux

No Local Lucy software needs to be installed on the device you browse from — only a web browser is required.

### Same LAN

1. On the host, bind to all interfaces and set a token:
   ```bash
   export LUCY_WEB_ENABLED=1
   export LUCY_WEB_HOST=0.0.0.0
   export LUCY_WEB_AUTH_TOKEN=$(openssl rand -hex 32)
   python -m web_adapter
   ```
2. Find the host's LAN IP, e.g. `192.168.1.42`.
3. From the other device, open:
   ```text
   http://192.168.1.42:8765
   ```

### Tailscale (recommended for remote access)

1. Install Tailscale on the Linux host and on the remote device: https://tailscale.com/download
2. On the host, bind to the Tailscale IP (or `0.0.0.0`) and set a token:
   ```bash
   export LUCY_WEB_ENABLED=1
   export LUCY_WEB_HOST=0.0.0.0   # or the Tailscale IP, e.g. 100.64.0.1
   export LUCY_WEB_AUTH_TOKEN=$(openssl rand -hex 32)
   python -m web_adapter
   ```
3. From the remote device, open:
   ```text
   http://<lucy-tailscale-ip>:8765
   ```

### Public internet (temporary only)

For short tests across the internet, use a tunnel such as [ngrok](https://ngrok.com/download) or [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/). Do not expose port 8765 directly to the public internet.

---

## Security

- **Loopback by default.** The server binds to `127.0.0.1` unless explicitly
  changed.
- **Mandatory authentication for remote binds.** If `LUCY_WEB_HOST` is not a
  loopback address, `LUCY_WEB_AUTH_TOKEN` must be set or the server will refuse
  to start.
- **No hardcoded secrets.** The token is read from the environment only.
- **No stack traces in responses.** Errors return a safe JSON message; details
  are logged server-side.
- **Not for public internet exposure.** This is intended for private LAN,
  Tailscale, or local testing.

---

## Sessions and memory

The web adapter is **stateless**.

- It does not pass a `session_id` to the pipeline.
- It sets `LUCY_SESSION_MEMORY=0` in its own process so web turns are not
  written to or recalled from the shared session-memory store.
- The **New conversation** button in the UI only clears the browser display.
  There is no server-side conversation history for the web interface.

This means web chats are isolated from the PyQt HMI's memory and from each
other, without redesigning Local Lucy's memory subsystem.

---

## Model selection

- `GET /api/models` returns the list of configured models and the locally
  active default model.
- The UI shows the active default and lets the user pick a different model for
  the current request.
- `POST /api/ask` accepts an optional `model` field. If provided, it is
  validated against the supported model list and passed as a request-scoped
  override to `execute_plan_python(model=...)`.
- The override applies **only** to that request. It does **not** modify
  `runtime/state/current_state.json` or the PyQt HMI's global active model.

Supported models: `local-lucy`, `local-lucy-fast`, `local-lucy-llama31`,
`local-lucy-mistral`.

---

## API

### `GET /`

Serves the single-page web interface.

### `GET /api/status`

```json
{
  "ok": true,
  "available": true,
  "active_model": "local-lucy-llama31",
  "default_model": "local-lucy-llama31",
  "memory_enabled": false
}
```

### `GET /api/models`

```json
{
  "ok": true,
  "models": ["local-lucy", "local-lucy-fast", "local-lucy-llama31", "local-lucy-mistral"],
  "active_model": "local-lucy-llama31"
}
```

### `POST /api/ask`

Request:

```json
{
  "question": "Who was Ada Lovelace?",
  "model": "local-lucy-fast"
}
```

Response:

```json
{
  "ok": true,
  "answer": "Ada Lovelace was ...",
  "route": "LOCAL",
  "provider": "local",
  "model": "local-lucy-fast",
  "elapsed_ms": 1234
}
```

Errors return `ok: false` and a safe `error` string.

---

## Disabling

Do not set `LUCY_WEB_ENABLED` (or set it to `0`/`false`). The server will not
start and Local Lucy's existing behaviour is unchanged.

---

## Known limitations

- The web adapter runs in the same Python process as Local Lucy when started
  standalone; it does not spawn a second LLM runtime. It relies on the same
  `LUCY_*` environment variables and Ollama instance as the rest of Local Lucy.
- Concurrent requests are serialized by the pipeline's existing `fcntl` file
  lock unless `LUCY_SHARED_STATE_PARALLEL_ALLOW=1` is set.
- No voice, TTS, file upload, memory editing, or administration controls.
