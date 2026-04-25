# Human Live Test Baseline

## Baseline

Use this v7 state as the next human live-testing baseline.

- Snapshot root: `/home/mike/lucy/snapshots/opt-experimental-v7-dev`
- UI root: `/home/mike/lucy/ui-v7`
- Runtime namespace root: `/home/mike/.codex-api-home/lucy/runtime-v7`
- Milestone note: `/home/mike/lucy/snapshots/opt-experimental-v7-dev/dev_notes/MILESTONE_ADVERSARIAL_AUGMENTED_BEHAVIOR_GATE_2026-03-28.md`

## Operator Conditions At Freeze Point

- `mode=auto`
- `memory=off`
- `evidence=on`
- `voice=off`
- `augmentation_policy=fallback_only`
- `augmented_provider=openai`

## Live Eval References

- Default pack: `/home/mike/lucy/snapshots/opt-experimental-v7-dev/tools/tmp/live_augmented_operator_eval_default_live_v4/20260328T233903+0300/summary.md`
- Adversarial pack: `/home/mike/lucy/snapshots/opt-experimental-v7-dev/tools/tmp/live_augmented_operator_eval_adversarial_live_v4/20260328T233905+0300/summary.md`

## What To Probe Manually

1. Stable background summaries should stay concise and direct.
2. Implicit-current prompts should answer cautiously without drifting into fake evidence tone.
3. `current projects` / `doing now` prompts should prefer short qualified answers.
4. Truly underspecified status prompts should clarify instead of answering too smoothly.
5. Operator view should remain coherent with:
   - answer path
   - trust label
   - clarification-vs-answer behavior

## Suggested Manual Prompts

- `What is OpenAI?`
- `What is OpenAI doing now?`
- `What are his current projects?`
- `What is he doing now?`
- `Compare Microsoft historically and what it is doing now in one short paragraph.`
- `How would you categorize Elon Musk, including what he is doing now?`

## Working Rule

Do not judge this baseline by whether every answer is elegant.

Judge it by whether it is:

- honest about unverified currentness
- concise
- non-misleading
- selective about clarification
- consistent with the operator trust surface
