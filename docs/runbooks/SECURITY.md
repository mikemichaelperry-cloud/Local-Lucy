# Local Lucy v10 — Security Guide

## Threat Model

Local Lucy is designed as a **single-user desktop application**. It trusts the local user and the local filesystem completely.

| Threat | Mitigation |
|--------|-----------|
| Cloud API key exposure | Keys live only in `.env` (never committed) |
| Local SearXNG secret | Auto-generated per-install; not committed |
| Medical/vet misinformation | Multi-layer safety guard + evidence mode |
| Prompt injection | Input sanitization (control chars, zero-width chars, jailbreak regex) |
| Subprocess injection | Native Python paths preferred; shell inputs allowlisted |
| Database snooping | SQLite files hardened to `0o600` |

## Hardening Checklist

- [ ] Rotate SearXNG secret after install: `cd services/searxng && bash start.sh`
- [ ] Keep `.env` out of git: it is already in `.gitignore`
- [ ] Run `make check-env` after any system update
- [ ] Review `pending_review.jsonl` weekly for high-stakes feedback
- [ ] Enable Ollama API key if multi-user machine: `OLLAMA_API_KEY` in `.env`

## Incident Response

If you suspect a security issue:

1. Stop Lucy: close the HMI window or `killall python3`
2. Check logs: `tail -n 100 ~/.local/share/local-lucy/logs/*.log`
3. Rotate cloud API keys in `.env`
4. Regenerate SearXNG secret: delete `services/searxng/searxng/settings.yml` and re-run `start.sh`
5. Report: open an issue at https://github.com/mikemichaelperry-cloud/Local-Lucy/issues
