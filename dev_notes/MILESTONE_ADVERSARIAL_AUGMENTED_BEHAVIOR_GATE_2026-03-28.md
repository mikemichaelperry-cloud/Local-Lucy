# Local Lucy v7 Milestone

## Title

Adversarial Augmented-Behavior Gate Milestone

## Timestamp

2026-03-28T23:45:10+0300

## Scope

- Snapshot root: `/home/mike/lucy/snapshots/opt-experimental-v7-dev`
- UI root: `/home/mike/lucy/ui-v7`
- Authoritative runtime namespace: `/home/mike/.codex-api-home/lucy/runtime-v7`
- Legacy parallel runtime tree: `/home/mike/lucy/runtime-v7`

## Why This Milestone Matters

This is the v7 state where the adversarial augmented-fallback hole appears to be closed in a disciplined way.

The change is not just cosmetic prompt tuning. The runtime now has:

- a compact adversarial-lane behavior contract for augmented fallback
- selective clarify-vs-answer behavior for underspecified currentness-sensitive prompts
- compact cautious shaping for anchored implicit-current prompts
- explicit release-gate tests for the adversarial lane
- live eval evidence that the default and adversarial packs are both passing

## What Was Closed

The remaining weakness before this milestone was:

- adversarial prompts still produced answers that were too slick, too compact, or too smooth for unverified currentness-sensitive cases

What changed:

- `local_answer.sh` now carries compact augmented flags:
  - `implicit_currentness`
  - `entity_status_query`
  - `underspecified_subject`
  - `clarify_preferred`
- augmented answer shaping now separates:
  - `stable_summary`
  - `currentness_cautious`
  - `clarify_question`
- `execute_plan.sh` now promotes clarify-preferred augmented behavior into a real `clarification_requested` outcome instead of presenting it as an unverified answer

## Release-Gate Evidence

Default live pack:

- report: `/home/mike/lucy/snapshots/opt-experimental-v7-dev/tools/tmp/live_augmented_operator_eval_default_live_v4/20260328T233903+0300/summary.md`
- result: `9/9`

Adversarial live pack:

- report: `/home/mike/lucy/snapshots/opt-experimental-v7-dev/tools/tmp/live_augmented_operator_eval_adversarial_live_v4/20260328T233905+0300/summary.md`
- result: `7/7`

Important interpretation:

- this is strong enough to use as a release gate for the adversarial augmented lane
- it is not a claim of total robustness for every future prompt

## Practical Recommendation

- Freeze this v7 state.
- Treat it as the adversarial augmented-behavior gate milestone.
- Do not immediately begin another broad refactor from this point.
- Use this state as the baseline for human live testing.

## Keep Stable

Preserve these properties from this milestone forward:

- typed answer/trust contract
- explicit authority/root contract
- env-contract-based augmented fallback inputs
- no wrapper-driven evidence gating
- no backend scaffolding leakage into operator answers
- selective clarification for underspecified currentness-sensitive augmented prompts

## Do Not Reopen Broadly

Avoid reopening these areas unless a later concrete defect requires it:

- authority/namespace refactors
- broad routing rewrites
- operator UI redesign
- broad prompt-system churn outside the adversarial augmented lane
