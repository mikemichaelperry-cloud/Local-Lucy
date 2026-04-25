# PHASE1 INTENT ROUTER REPORT

Timestamp: 2026-03-12T19:38:05+0200
Active root: /home/mike/lucy/snapshots/opt-experimental-v5-dev

## Failure-first summary

- What changed:
  - Added a new Phase 1 router core with explicit input normalization, intent classification, and policy routing.
  - Kept `execute_plan.sh`, `classify_intent.py`, and `plan_to_pipeline.py` as the stable integration seam.
  - Added explicit `CLARIFY` routing for ambiguous prompts such as `tell me about bali`.
  - Added classifier/router trace hooks so voice and text can be verified against the same decision path.
- What was hard:
  - Preserving legacy behavior while introducing the new coarse intent classes required a compatibility layer, not a rewrite.
  - Several fake-root router tests copied only top-level router scripts, so the new `tools/router/core/` modules had to be carried into those fixtures.
  - A few old heuristics needed tightening after the first pass:
    - finance prompts were briefly misread as local-shopping clarification
    - pet-food prompts were briefly swallowed by the high-risk pet medical branch
    - strict Israeli-source news prompts were briefly caught by the generic evidence/source branch
    - some conversational prompts needed broader detection to preserve `CONVERSATION`
- What remains unresolved:
  - `style_mode` is structured and classified, but still only metadata; it does not yet drive downstream answer formatting.
  - `CLARIFY` is intentionally minimal and prompt-based; there is no multi-turn clarification state machine yet.
  - Legacy `intent` / `output_mode` compatibility is still maintained inside the wrapper layer, so this is not yet a clean removal of the old plan shape.

## Files changed

- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/router/classify_intent.py`
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/router/plan_to_pipeline.py`
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/router/execute_plan.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/router/core/__init__.py`
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/router/core/input_normalizer.py`
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/router/core/intent_classifier.py`
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/router/core/policy_router.py`
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/schemas/intent_schema.json`
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/schemas/routing_schema.json`
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/tests/test_phase1_classifier_output.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/tests/test_phase1_routing_output.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/tests/test_execute_plan_phase1_clarify.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/tests/test_voice_text_shared_classifier_path.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/tests/test_router_vs_fallback_mode_drift_monitor.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/tests/test_execute_plan_allow_domains_passthrough.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/tests/test_execute_plan_pet_food_knowledge_short_circuit.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/tests/test_news_israel_specificity_no_warning_leak.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/tests/test_lucy_chat_router_forced_mode_strict.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/tests/test_execute_plan_route_reason_passthrough.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/tests/test_news_region_filter_au_enforcement.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/SHA256SUMS`

## New tests added

- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/tests/test_phase1_classifier_output.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/tests/test_phase1_routing_output.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/tests/test_execute_plan_phase1_clarify.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/tests/test_voice_text_shared_classifier_path.sh`

## Example classifier outputs

`who is oscar`

```json
{
  "intent_class": "identity_personal",
  "confidence": 0.96,
  "needs_current_info": false,
  "needs_personal_context": true,
  "style_mode": "conversational",
  "mixed_intent": false,
  "candidate_routes": ["LOCAL"],
  "needs_clarification": false,
  "clarification_question": null
}
```

`latest world news`

```json
{
  "intent_class": "current_fact",
  "confidence": 0.95,
  "needs_current_info": true,
  "needs_personal_context": false,
  "style_mode": "brief",
  "mixed_intent": false,
  "candidate_routes": ["NEWS", "EVIDENCE"],
  "needs_clarification": false,
  "clarification_question": null
}
```

`tell me about bali`

```json
{
  "intent_class": "mixed",
  "confidence": 0.46,
  "needs_current_info": false,
  "needs_personal_context": false,
  "style_mode": "informational",
  "mixed_intent": true,
  "candidate_routes": ["CLARIFY", "EVIDENCE", "LOCAL"],
  "needs_clarification": true,
  "clarification_question": "Do you want general information, current news, or travel safety information?"
}
```

## Example routing outputs

`who is oscar`

```json
{
  "route_mode": "LOCAL",
  "offline_action": "allow",
  "needs_clarification": false,
  "clarification_question": null
}
```

`latest world news`

```json
{
  "route_mode": "NEWS",
  "offline_action": "allow",
  "needs_clarification": false,
  "clarification_question": null
}
```

`tell me about bali`

```json
{
  "route_mode": "CLARIFY",
  "offline_action": "allow",
  "needs_clarification": true,
  "clarification_question": "Do you want general information, current news, or travel safety information?"
}
```

## Not implemented yet

- No cloud execution integration
- No full router rewrite
- No memory redesign
- No broad Bash-to-Python migration
- No separate voice router; voice still shares the same decision path
- No downstream `style_mode` rendering behavior beyond metadata

