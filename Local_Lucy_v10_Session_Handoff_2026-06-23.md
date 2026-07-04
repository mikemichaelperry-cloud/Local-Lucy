# Local Lucy v10 — Session Handoff

**Date:** 2026-06-23
**Status:** Ready for reboot and verification

## Session summary

This session focused on eliminating factual hallucinations by making the router **truth-first**: when a query asks for verifiable real-world facts, Local Lucy now routes it to external sources (Wikipedia / OpenAI / Kimi) instead of relying on the local model's memory.

## Key changes

1. **Architecture prompt sync**
   - All LLM prompts (`system_prompt.txt`, `system_prompt.dev.txt`, and every `Modelfile.local-lucy*`) now share the same canonical `[ARCHITECTURE]` block with correct routes, LLM/router distinction, context sizes, and capabilities.

2. **Anti-hallucination guardrail**
   - Added to every prompt: the model must not invent dates, locations, founders, history, or capabilities for specific real-world entities.

3. **Truth-first discipline**
   - Added to every prompt: every factual claim must be traceable to a source (approved memory, retrieved context, or high-confidence parametric knowledge). Unsupported claims must be omitted or marked unknown.

4. **Policy gates in `tools/router_py/policy_router.py`**
   - `gate_specific_entity_fact` — routes named-entity factual queries (e.g., "Tell me about Kibbutz Magal") to `AUGMENTED`.
   - `gate_factual_lookup` — routes broad factual questions (e.g., "What is the capital of France?", "Why is the sky blue?") to `AUGMENTED`.
   - Local capabilities (translation, coding, math, creative writing, opinion, personal/family) are preserved.

5. **Approved memory note for Kibbutz Magal**
   - `memory/approved/20260623-203700-00001.txt` contains verified facts from Wikipedia. Because the user lives there, it is flagged as a baseline for corrections.

6. **Augmented provider citation requirement**
   - `tools/unverified_context_openai.py` and `tools/unverified_context_kimi.py` now instruct the provider to cite sources for every factual claim and to omit unverified claims.

7. **Condensed validation suite**
   - `tests/test_specific_entity_fact_gate.py` — 20 policy-gate cases, all passing in <1 second.

8. **Ollama models rebuilt**
   - `local-lucy`, `local-lucy-fast`, `local-lucy-llama31`, `local-lucy-mistral`, `local-lucy-memory`, `local-lucy-qwen3`, `local-lucy-stable` recreated from updated Modelfiles.

## Files to know about

- Current report: `Desktop/Local_Lucy_Kibbutz_Magal_Hallucination_Fix.md`
- Current project report: `lucy-v10/reports/kibbutz_magal_hallucination_fix.md`
- Policy gates: `lucy-v10/tools/router_py/policy_router.py`
- Validation: `lucy-v10/tests/test_specific_entity_fact_gate.py`
- Training examples (for next retrain): `lucy-v10/models/router/entity_fact_training_examples.jsonl`
- Approved memory: `lucy-v10/memory/approved/20260623-203700-00001.txt`

## Post-reboot verification checklist

After rebooting:

1. **Ollama is running**
   ```bash
   ollama list
   ```
   You should see all 7 `local-lucy*` models.

2. **Run the condensed policy-gate suite**
   ```bash
   cd /home/mike/lucy-v10
   python3 tests/test_specific_entity_fact_gate.py
   ```
   Expected: `PASS: 20/20 truth-first policy-gate cases passed`

3. **Smoke-test through the Local Lucy UI**

   | Query | Expected route | Expected behavior |
   |---|---|---|
   | "Tell me about Kibbutz Magal" | `AUGMENTED` | Uses Wikipedia or approved memory; correct location/founding; cites source |
   | "What is the capital of France?" | `AUGMENTED` | External lookup; cites source |
   | "Why is the sky blue?" | `AUGMENTED` | External lookup |
   | "Translate 'hello' to French" | `LOCAL` | Answered locally, no external call |
   | "Write a story about a robot" | `LOCAL` | Creative, local |
   | "My dog likes to play" | `LOCAL` | Personal/family, local |

4. **Watch for over-routing**
   - If too many ordinary questions start going to `AUGMENTED`, we can tune `gate_factual_lookup` exclusions.

## Next steps (after reboot)

1. Merge `models/router/entity_fact_training_examples.jsonl` into `comprehensive_examples.json` and retrain the embedding router so the k-NN/classifier layer learns the new patterns, not just the policy gates.
2. Add approved memory notes for any other entities the user cares about.
3. Monitor API usage/cost now that more queries route outward.

## Notes

- The computer has been up for several weeks; a reboot is recommended.
- All stale reports and previous session handoffs have been moved to `Desktop/archive_reports/` and `lucy-v10/reports/archive/`.
