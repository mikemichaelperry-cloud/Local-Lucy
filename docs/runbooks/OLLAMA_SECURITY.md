# Ollama Localhost Security Hardening

## Threat model

Local Lucy runs Ollama on `127.0.0.1:11434` with **no authentication** by default. On a single-user workstation this is acceptable. On a shared or multi-user machine, any local user can connect to that port and send prompts using your model weights and VRAM.

## Recommended mitigations

### 1. Bind Ollama to localhost only

Ensure Ollama is not listening on `0.0.0.0`. On Linux:

```bash
systemctl edit ollama.service
```

Add:

```ini
[Service]
Environment="OLLAMA_HOST=127.0.0.1:11434"
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

Verify:

```bash
ss -tlnp | grep 11434
# Expected: 127.0.0.1:11434 only
```

### 2. Block outbound exposure with a firewall

If you never need remote access:

```bash
sudo ufw deny 11434/tcp
```

### 3. Run Ollama under a dedicated user

Avoid running the Ollama daemon as your primary login user. A dedicated `ollama` user limits file-system exposure if the service is compromised.

### 4. Keep Ollama updated

```bash
sudo apt update && sudo apt upgrade ollama
```

### 5. Monitor local access

Watch for unexpected connections:

```bash
lsof -i :11434
```

## What Local Lucy does not do today

- No API-key or token authentication to Ollama.
- No TLS on the localhost connection.

These are acceptable only when the host is physically controlled by one trusted user.

## References

- Ollama docs: https://github.com/ollama/ollama/blob/main/docs/faq.md
- `LUCY_OLLAMA_API_URL` in `SESSION_CONTEXT.md`
