#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
GEN="${ROOT}/tools/launcher/generate_desktop_launchers.sh"
VAL="${ROOT}/tools/launcher/validate_desktop_launchers.sh"

ok(){ echo "OK: $*"; }
die(){ echo "ERR: $*" >&2; exit 1; }

[[ -x "${GEN}" ]] || die "missing executable: ${GEN}"
[[ -x "${VAL}" ]] || die "missing executable: ${VAL}"

TMPD="$(mktemp -d)"
trap 'rm -rf "${TMPD}"' EXIT

desk_good="${TMPD}/Local Lucy — Opt Experimental v9 DEV.desktop"
script_good="${TMPD}/opt-experimental-v9-dev/tools/start_local_lucy_opt_experimental_v9_dev.sh"
mkdir -p "$(dirname -- "${script_good}")"
cat > "${script_good}" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod +x "${script_good}"

manifest_good="${TMPD}/desktop_launchers_good.tsv"
cat > "${manifest_good}" <<EOF
# desktop_path<TAB>name<TAB>comment<TAB>exec_target<TAB>exec_style
${desk_good}	Local Lucy — Opt Experimental v9 DEV	Run Local Lucy from opt-experimental-v9-dev (development)	${script_good}	bash_lc_hold
EOF

"${GEN}" "${manifest_good}" --apply >/dev/null
"${VAL}" "${manifest_good}" >/dev/null
ok "generator+validator pass on good manifest"

manifest_bad="${TMPD}/desktop_launchers_bad.tsv"
cat > "${manifest_bad}" <<EOF
# desktop_path<TAB>name<TAB>comment<TAB>exec_target<TAB>exec_style
${desk_good}	Local Lucy — Opt Experimental v9 DEV	Run Local Lucy from opt-experimental-v9-dev (development)	${TMPD}/opt-experimental-v9-dev/tools/start_local_lucy_opt_experimental_v3_dev.sh	bash_lc_hold
EOF

set +e
"${VAL}" "${manifest_bad}" >/dev/null 2>&1
rc=$?
set -e
[[ "${rc}" -ne 0 ]] || die "validator should fail when DEV script basename is mismatched"
ok "validator rejects DEV naming/path mismatch"

echo "PASS: desktop_launcher_manifest"
