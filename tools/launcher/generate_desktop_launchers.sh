#!/usr/bin/env bash
# ROLE: SUPPORTED ALIAS / WRAPPER
# Generates desktop convenience launchers from the launcher manifest.
# Keep manifest ordering current-first and legacy surfaces grouped below comments.
# Maintenance helper only; not a primary operator entrypoint.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${LUCY_ROOT:-$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)}"
MANIFEST="${1:-${ROOT}/config/launcher/desktop_launchers.tsv}"
APPLY="${2:-}"

err(){ echo "ERR: $*" >&2; }

[[ -f "${MANIFEST}" ]] || { err "missing manifest: ${MANIFEST}"; exit 2; }

render_exec(){
  local target="$1" style="$2"
  case "${style}" in
    raw)
      printf 'gnome-terminal -- %s' "${target}"
      ;;
    bash_lc_hold)
      printf "gnome-terminal -- bash -lc '%s; exec bash'" "${target}"
      ;;
    *)
      err "unsupported exec_style: ${style}"
      return 1
      ;;
  esac
}

while IFS=$'\t' read -r desktop_path name comment exec_target exec_style; do
  [[ -n "${desktop_path// }" ]] || continue
  [[ "${desktop_path}" == \#* ]] && continue

  exec_line="$(render_exec "${exec_target}" "${exec_style}")"
  out="[Desktop Entry]
Version=1.0
Type=Application
Name=${name}
Comment=${comment}
Exec=${exec_line}
Icon=utilities-terminal
Terminal=false
Categories=Utility;Development;
"

  if [[ "${APPLY}" == "--apply" ]]; then
    mkdir -p "$(dirname -- "${desktop_path}")"
    printf '%s' "${out}" > "${desktop_path}"
    chmod +x "${desktop_path}" || true
    echo "UPDATED ${desktop_path}"
  else
    echo "=== ${desktop_path} ==="
    printf '%s' "${out}"
  fi
done < "${MANIFEST}"
