#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../../.." && pwd)"
SUITE_FILE="${SCRIPT_DIR}/governor_migration_cases.yaml"
EVALUATOR="${SCRIPT_DIR}/evaluate_governor_migration_results.py"
ARTIFACT_ROOT="${SCRIPT_DIR}/artifacts"
TIMESTAMP="$(date +%Y-%m-%dT%H-%M-%S%z)-$$"
ARTIFACT_DIR="${ARTIFACT_ROOT}/${TIMESTAMP}"

usage() {
  cat <<'USAGE'
Usage:
  bash tools/tests/governor_migration/run_governor_migration_pack.sh
  bash tools/tests/governor_migration/run_governor_migration_pack.sh --category followup_freshness
  bash tools/tests/governor_migration/run_governor_migration_pack.sh --case medical_offline_001
  bash tools/tests/governor_migration/run_governor_migration_pack.sh --artifact-dir /tmp/custom
USAGE
}

category_filter=""
case_filter=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --category)
      [[ $# -ge 2 ]] || { echo "ERROR: --category requires a value" >&2; exit 2; }
      category_filter="$2"
      shift 2
      ;;
    --case)
      [[ $# -ge 2 ]] || { echo "ERROR: --case requires a value" >&2; exit 2; }
      case_filter="$2"
      shift 2
      ;;
    --artifact-dir)
      [[ $# -ge 2 ]] || { echo "ERROR: --artifact-dir requires a value" >&2; exit 2; }
      ARTIFACT_DIR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

mkdir -p "${ARTIFACT_DIR}"

cmd=(
  python3
  "${EVALUATOR}"
  --suite "${SUITE_FILE}"
  --artifacts-dir "${ARTIFACT_DIR}"
)

if [[ -n "${category_filter}" ]]; then
  cmd+=(--category "${category_filter}")
fi
if [[ -n "${case_filter}" ]]; then
  cmd+=(--case "${case_filter}")
fi

(
  cd "${ROOT}"
  "${cmd[@]}"
)

echo "Artifacts: ${ARTIFACT_DIR}"
