# Local Lucy V11 — Final Requalification Baseline

Generated before beginning the final stabilisation/requalification mandate.

## Starting Git state

- Repository: `/home/mike/lucy-v11`
- Branch: `main`
- Commit: `32490923dd607cd4c3da491ce5e4c8ebc0f29773`
- Working tree: **dirty**
- V10 status: clean (`git -C /home/mike/lucy-v10 status --short` returned empty)

## Environment

- OS: Ubuntu 22.04.5 LTS
- Kernel: `Linux mike-System-Product-Name 6.8.0-136-generic #136~22.04.1-Ubuntu SMP PREEMPT_DYNAMIC Fri Jul  3 16:29:11 UTC  x86_64 x86_64 x86_64 GNU/Linux`
- Python: 3.10.12
- Dependency lock checksum (sha256): `c28dda315c943c619768caf3183d1edb18c893cac714482abd6efe75c9a9c0cd` (`requirements-lock.txt`)
- Installed package freeze checksum (sha256): `c5e1d0a501d1ed3fdd2d349a22787fcabdd05b07e8244dbe58526d964b860353`

## Relevant environment variables at baseline

```text
HOME=/home/mike
LUCY_VOICE_PIPER_VOICE=en_GB-cori-high
PATH=... (see shell env)
USER=mike
USERNAME=mike
XDG_CONFIG_DIRS=/etc/xdg/xdg-ubuntu:/etc/xdg
XDG_CURRENT_DESKTOP=ubuntu:GNOME
XDG_DATA_DIRS=/usr/share/ubuntu:/usr/share/gnome:/usr/local/share/:/usr/share/:/var/lib/snapd/desktop
XDG_MENU_PREFIX=gnome-
XDG_RUNTIME_DIR=/run/user/1000
XDG_SESSION_CLASS=user
XDG_SESSION_DESKTOP=ubuntu
XDG_SESSION_TYPE=x11
```

No `OLLAMA_*` environment variables were set in the qualification shell.

## Model assets

| Model | Ollama tag | Ollama ID | Blob digest |
|---|---|---|---|
| Gemma | `local-lucy-gemma4:latest` | `97b4a7a8de9a` | `sha256-faff1a63667fac17ac5e777f47114688fcefea96e220e211aaa8d62c2c4561f1` plus adapter `sha256-e70b0e5cd80323d5d588b4ed06780356b7b1ba03995a4b8164c6ae9db0ff5989` |
| Llama | `local-lucy-llama31:latest` | `4282cbd85b15` | `sha256-667b0c1932bc6ffc593ed1d03f895bf2dc8dc6df21db3042284a6f4416b06a29` |

## Router assets

| File | SHA-256 |
|---|---|
| `models/router/comprehensive_examples.json` | `b278514c064eac55b0a40f57659901a74b42597cca6c4487121d29431952708f` |
| `models/router/comprehensive_embeddings.npy` | `6166e28af993b0a1638e784bfbbe6da26d6a0493dec36c5995f37c8935a52d56` |
| `models/router/classifier_head.pt` | `12e2c1691459dde696f808122bfd19ba618b97c2ca308b13e8c84d6d353d406d` |
| `models/router/classifier_head_config.json` | `250aea0d02ffa4697c7520ffc0d6776a68bb6bd1a9e0902779a562990316fc18` |

## Current qualification control-file snapshot

- `current_stage`: STAGE_19
- `current_task`: S19-FINAL-001
- `last_completed_task`: S4-MEM-004
- STAGE_00 status: `IN_PROGRESS`
- STAGE_01 status: `IN_PROGRESS`
- STAGE_02 status: `NOT_STARTED`
- STAGE_03 status: `NOT_STARTED`
- STAGE_04–STAGE_19 status: `PASSED` or `IN_PROGRESS`
- `active_defects`: `[]`
- Last baseline metrics claimed: validation 21/21, holdout 13/15, combined 34/36
- Last clean run: stage_19 clean run 7/7 passed

## Known issues at baseline (to be resolved during requalification)

1. `TEST_STATUS.json` shows STAGE_00–STAGE_03 as incomplete while the completion report claims all stages passed.
2. Reported routing metric `0.861` for 34/36 is mathematically inconsistent.
3. Post-STAGE_19 memory changes have not been included in a final clean-run qualification.
4. Holdout result is 13/15; two failures need individual classification.
5. Voice text-display issue is reported but not reproduced or risk-assessed.
6. `LUCY_MEMORY_MAX_CHARS` default (2000) differs from execution-engine caller value (2400).
7. `active_defects: []` conflicts with the existence of accepted limitations.

## Working-tree summary

- 58 modified tracked files (production code, tests, configuration, documentation).
- 49 untracked files/directories, including `qualification/`, new stage scripts, new tests, and temporary artefacts.
- Temporary/ignored artefacts such as `__pycache__`, `.tmp_voice_test/`, and production backups must not be committed.

## Rollback reference

If the requalification work needs to be abandoned, reset to:

```bash
cd /home/mike/lucy-v11
git reset --hard 32490923dd607cd4c3da491ce5e4c8ebc0f29773
```

V10 must remain untouched.
