#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TMPDIR_TEST="$(mktemp -d)"
trap 'rm -rf "${TMPDIR_TEST}"' EXIT

die() {
  echo "FAIL: $*" >&2
  exit 1
}

pack_dir="${TMPDIR_TEST}/pack"
mkdir -p "${pack_dir}"

cat > "${pack_dir}/item_a.meta" <<'EOF'
KEY=policy_climate_1
DOMAIN=apnews.com
EOF
cat > "${pack_dir}/item_b.meta" <<'EOF'
KEY=policy_climate_2
DOMAIN=iea.org
EOF
cat > "${pack_dir}/item_c.meta" <<'EOF'
KEY=policy_ai_gov_1
DOMAIN=bbc.com
EOF
cat > "${pack_dir}/item_d.meta" <<'EOF'
KEY=policy_ai_gov_2
DOMAIN=gov.uk
EOF
cat > "${pack_dir}/item_e.meta" <<'EOF'
KEY=policy_regulation_1
DOMAIN=ec.europa.eu
EOF

profile_py="${ROOT}/tools/policy_validation_profile.py"

eval "$("${profile_py}" --query "Tell me, with evidence, what the most significant developments in global climate policy and AI safety have been in the past week?" --pack-dir "${pack_dir}")"
[[ "${POLICY_VALIDATION_SHAPE}" == "compound_climate_ai" ]] || die "expected compound_climate_ai shape"
[[ "${POLICY_VALIDATION_ALLOW_BOUNDED}" == "1" ]] || die "expected bounded synthesis for supported compound query"

eval "$("${profile_py}" --query "What are the latest AI safety regulatory developments this week?" --pack-dir "${pack_dir}")"
[[ "${POLICY_VALIDATION_SHAPE}" == "single_ai" ]] || die "expected single_ai shape"
[[ "${POLICY_VALIDATION_ALLOW_BOUNDED}" == "1" ]] || die "expected bounded synthesis for supported ai query"

eval "$("${profile_py}" --query "What are the latest genai developments this past month?" --pack-dir "${pack_dir}")"
[[ "${POLICY_VALIDATION_SHAPE}" == "single_ai" ]] || die "expected single_ai shape for genai developments query"
[[ "${POLICY_VALIDATION_ALLOW_BOUNDED}" == "1" ]] || die "expected bounded synthesis for supported genai query"

eval "$("${profile_py}" --query "What are the latest llm developments this past month?" --pack-dir "${pack_dir}")"
[[ "${POLICY_VALIDATION_SHAPE}" == "single_ai" ]] || die "expected single_ai shape for llm developments query"
[[ "${POLICY_VALIDATION_ALLOW_BOUNDED}" == "1" ]] || die "expected bounded synthesis for supported llm query"

eval "$("${profile_py}" --query "What are the latest foundation model developments this past month?" --pack-dir "${pack_dir}")"
[[ "${POLICY_VALIDATION_SHAPE}" == "single_ai" ]] || die "expected single_ai shape for foundation model developments query"
[[ "${POLICY_VALIDATION_ALLOW_BOUNDED}" == "1" ]] || die "expected bounded synthesis for supported foundation model query"

eval "$("${profile_py}" --query "Summarize all major global policy developments across climate, AI, and financial regulation this week." --pack-dir "${pack_dir}")"
[[ "${POLICY_VALIDATION_SHAPE}" == "cross_domain_policy" ]] || die "expected cross_domain_policy shape"
[[ "${POLICY_VALIDATION_ALLOW_BOUNDED}" == "0" ]] || die "cross-domain policy query should stay strict"

eval "$("${profile_py}" --query "What exact AI safety treaty deadlines were set this week?" --pack-dir "${pack_dir}")"
[[ "${POLICY_VALIDATION_ALLOW_BOUNDED}" == "0" ]] || die "specific treaty/deadline query should stay strict"

echo "PASS: policy validation profile rules"
