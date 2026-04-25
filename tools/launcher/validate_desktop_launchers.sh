#!/usr/bin/env bash
# ROLE: SUPPORTED ALIAS / WRAPPER
# Validates desktop convenience launchers against the launcher manifest.
# Keep manifest ordering current-first and legacy surfaces grouped below comments.
# Maintenance helper only; not a primary operator entrypoint.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${LUCY_ROOT:-$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)}"
MANIFEST="${1:-${ROOT}/config/launcher/desktop_launchers.tsv}"

err(){ echo "ERR: $*" >&2; }
ok(){ echo "OK: $*"; }

[[ -f "${MANIFEST}" ]] || { err "missing manifest: ${MANIFEST}"; exit 2; }

expected_exec(){
  local target="$1" style="$2"
  case "${style}" in
    raw) printf 'gnome-terminal -- %s' "${target}" ;;
    bash_lc_hold) printf 'gnome-terminal -- bash -lc "%s; exec bash"' "${target}" ;;
    *) return 1 ;;
  esac
}

expected_exec_legacy(){
  local target="$1" style="$2"
  case "${style}" in
    raw) printf 'gnome-terminal -- %s' "${target}" ;;
    bash_lc_hold) printf "gnome-terminal -- bash -lc '%s; exec bash'" "${target}" ;;
    *) return 1 ;;
  esac
}

fail_count=0
row=0

while IFS=$'\t' read -r desktop_path name comment exec_target exec_style; do
  [[ -n "${desktop_path// }" ]] || continue
  [[ "${desktop_path}" == \#* ]] && continue
  row=$((row+1))

  if [[ ! -f "${desktop_path}" ]]; then
    err "row ${row}: desktop file missing: ${desktop_path}"
    fail_count=$((fail_count+1))
    continue
  fi

  if [[ ! -x "${exec_target}" ]]; then
    err "row ${row}: exec target missing or not executable: ${exec_target}"
    fail_count=$((fail_count+1))
  fi

  expected="$(expected_exec "${exec_target}" "${exec_style}" || true)"
  if [[ -z "${expected}" ]]; then
    err "row ${row}: unsupported exec_style in manifest: ${exec_style}"
    fail_count=$((fail_count+1))
    continue
  fi

  got_name="$(sed -n 's/^Name=//p' "${desktop_path}" | head -n1)"
  got_exec="$(sed -n 's/^Exec=//p' "${desktop_path}" | head -n1)"

  if [[ "${got_name}" != "${name}" ]]; then
    err "row ${row}: Name mismatch in ${desktop_path}"
    err "  expected: ${name}"
    err "  got:      ${got_name}"
    fail_count=$((fail_count+1))
  fi

  legacy_expected="$(expected_exec_legacy "${exec_target}" "${exec_style}" || true)"
  if [[ "${got_exec}" != "${expected}" && "${got_exec}" != "${legacy_expected}" ]]; then
    err "row ${row}: Exec mismatch in ${desktop_path}"
    err "  expected: ${expected}"
    err "  legacy:   ${legacy_expected}"
    err "  got:      ${got_exec}"
    fail_count=$((fail_count+1))
  fi

  # Enforce DEV naming accuracy: launcher version must match both snapshot and script basename.
  if [[ "${name}" =~ v([0-9]+)[[:space:]]+DEV ]]; then
    ver="${BASH_REMATCH[1]}"
    base="$(basename -- "${exec_target}")"
    if [[ "${base}" != "start_local_lucy_opt_experimental_v${ver}_dev.sh" ]]; then
      err "row ${row}: DEV script name mismatch (expected v${ver} script)"
      err "  got target basename: ${base}"
      fail_count=$((fail_count+1))
    fi
    if [[ "${exec_target}" != *"/opt-experimental-v${ver}-dev/"* ]]; then
      err "row ${row}: DEV target path does not point to opt-experimental-v${ver}-dev snapshot"
      err "  got target: ${exec_target}"
      fail_count=$((fail_count+1))
    fi
  fi

  ok "row ${row}: ${desktop_path}"
done < "${MANIFEST}"

if [[ "${fail_count}" -ne 0 ]]; then
  err "launcher validation failed with ${fail_count} issue(s)"
  exit 1
fi

echo "PASS: desktop_launcher_validation"
