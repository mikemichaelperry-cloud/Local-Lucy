# Checkpoint Freeze: 14/14 Pre-Similarity Harness
Date: 2026-02-20T20:11:10+02:00
Root: /home/mike/lucy/snapshots/opt-experimental-v1

## Purpose
Rollback anchor captured before expanding Lucy similarity harness.

## Baseline Result (Pinned)
Prompt integration suite latest passing run:
- Summary: /home/mike/lucy/snapshots/opt-experimental-v1/tmp/test_reports/prompt_integration/20260220T193153+0200/summary.txt
- Results TSV: /home/mike/lucy/snapshots/opt-experimental-v1/tmp/test_reports/prompt_integration/20260220T193153+0200/results.tsv
- Outcome: cases_total=14, cases_passed=14, cases_failed=0

## VCS State
- Git worktree: NO_GIT (snapshot is not a git repository)
- Freeze method: timestamped checkpoint note + file hashes + test artifacts

## Integrity Snapshot
sha_manifest check was run and currently reports expected mismatches for edited files in this session.
Mismatches include:
- config/Modelfile.local-lucy-mem
- config/system_prompt.dev.txt
- lucy_chat.sh
- tools/full_regression_v2.sh
- tools/golden_eval.sh
- tools/local_answer.sh
- tools/router/router_regression_v1.sh

## Key File Hashes (current)
- e7d21de125ec4423cd9423aa7a265197c100c5c01d8240364e50ee78c2d72f22  config/system_prompt.dev.txt
- 98d36e5d800af36ac41ae2d0d32eb01235bf870f51867332b81e082e7ef68324  config/Modelfile.local-lucy-mem
- 31878e65184f146940c9a0822100d877755b478aa9e9a965131765123806b60e  lucy_chat.sh
- d45808b212f0c5a67ddf5717311166862a351f03833529dab14ffae9af16a9a3  tools/local_answer.sh
- 9ed7d95f0536ea7a1c074ae71f5163e916cbc3b617668f37d9fcc2b6cd1bdb3b  tools/run_prompt_integration_suite.sh
- 02326c00ea1f02533e7cf99dbdcfc5ed103c613b91f8b84257fdc5e5f2c10805  tools/golden_eval.sh
- 1f275d11f1761646479d926e0dd71326bd1708070bd62db5ae7d3ec1fec74a62  tools/full_regression_v2.sh
- c4b7e1e106663b9cb84d772f2f2e89bba67df0e1ad40514aee0f47baf9560a10  tools/router/router_regression_v1.sh

## Scope of Session Changes (high level)
1. Determinism hardening:
   - Pinned memory env state in golden/full/router regression scripts.
2. Prompt migration:
   - Implemented v1.1-soft in system_prompt.dev.txt and Modelfile.local-lucy-mem.
3. Runtime activation:
   - Rebuilt local-lucy-mem model.
4. Integration harness:
   - Added tools/run_prompt_integration_suite.sh.
5. Follow-up continuity fixes:
   - local_answer: quantity follow-up handling and gate refinement.
   - lucy_chat: memory truncation now preserves most recent context.

## Recommended Next Step
Proceed with Lucy similarity harness expansion on top of this checkpoint.
If regression appears, revert to this checkpoint by restoring file contents from this date/time and revalidating against the 14/14 suite artifact above.
