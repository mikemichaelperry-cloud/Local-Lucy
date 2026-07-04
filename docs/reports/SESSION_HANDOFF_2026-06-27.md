# Session Handoff — 2026-06-27

**Project:** Local Lucy v10
**Session focus:** Hebrew first-class support + classifier/router improvement + TTS + veterinary over-classification fix
**Status:** Complete and tested
**Next session:** Ready for user-driven next feature, or continued classifier hardening

---

## What was completed

1. **Hebrew is now a first-class language**
   - STT: Whisper multilingual (`ggml-small.bin`)
   - Routing: same policy gates + embedding router as English
   - LLM: same persona LoRAs; English output translated offline via `Helsinki-NLP/opus-mt-en-he`
   - TTS: local MMS Hebrew default, Edge-TTS cloud fallback
   - Brand names ("Local Lucy", "Lucy V10") preserved in Latin script

2. **Classifier/router improved**
   - Continual fine-tune of MiniLM embedding model on 1,454 examples
   - Replaced linear classifier head with 256-unit MLP
   - Fixed MLP state-dict save/load mismatch in `train_classifier_head.py`
   - Added `gate_ambiguous_local` and expanded Hebrew/English policy gates
   - Combined validation accuracy: **78.5% → 81.3%**

3. **Tests added and stabilized**
   - `tools/router_py/test_hebrew_routing.py` (13 tests)
   - Hebrew cases added to `test_policy_router.py`
   - `tools/voice/tests/test_hebrew_tts_runtime.py` (2 tests)
   - Routing edge cases, response regression, and semantic regression fixtures updated
   - Full suite: **750 passed, 24 skipped, 2 warnings**

4. **Runtime bugs fixed**
   - Hebrew TTS now correctly routes through MMS/Edge-TTS in `runtime_voice._synth_one_chunk()`
   - Hebrew/English dog-walk and other recreational pet queries no longer misroute to veterinary `EVIDENCE`
   - Hebrew/English cultural-adaptation questions ("How do Israelis get by in Japan?") route to `LOCAL` and produce Hebrew output
   - Hebrew recommendation / kibbutz dog-walk queries, including common STT variants, route to `LOCAL`

---

## Key files changed

- `tools/router_py/local_answer.py` — Hebrew detection, translation, brand preservation
- `tools/router_py/classify.py` — Hebrew route-detector patterns
- `tools/router_py/policy_router.py` — new ambiguous-local gate, new recreational-pet gate, new cultural-adaptation gate, Hebrew policy patterns
- `tools/router_py/policy.py` — Hebrew semantic medical/vet/personal anchors
- `tools/router_py/classify.py` — Hebrew personal-family patterns
- `tools/voice/tts_adapter.py` + `tools/voice/backends/` — Hebrew TTS backends
- `tools/runtime_voice.py` — Hebrew chunk bypass of kokoro worker
- `tools/voice/tests/test_hebrew_tts.py` — isolated temp dir, actual WAV synthesis checks
- `tools/router_py/test_response_regression.py` — retry loop for LLM non-determinism
- `models/router/finetuned_minilm/`, `classifier_head.pt`, `comprehensive_embeddings.npy` — retrained
- `models/router/train_classifier_head.py` — MLP save fix
- `tests/response_regression_cases.json`, `tests/golden_semantic_responses.json`, `tools/router_py/test_semantic_regression.py` — regression stabilization

See the full reports for details (both archived under `backups/v10-dev-cleanup/2026-07-04/docs/`):
- `backups/v10-dev-cleanup/2026-07-04/docs/Hebrew_First_Class_Support_Report.md`
- `backups/v10-dev-cleanup/2026-07-04/docs/Classifier_Router_Improvement_Report.md`

---

## Current environment

- Python venv: `/home/mike/lucy-v10/ui-v10/.venv/bin/python`
- GPU: NVIDIA RTX 3060 12 GB
- Ollama running at `127.0.0.1:11434`
- Key packages: `edge-tts`, `transformers`, `sentencepiece`, `sacremoses`, `deep-translator`

---

## Known remaining gaps

1. **Classifier accuracy at 81.3%** — still the weakest link.
2. **AUGMENTED / EPHEMERAL F1 still low** — needs more hard-negative training data.
3. **Hebrew LLM generation is translate-then-speak** — a dedicated Hebrew LoRA would be more natural but costs VRAM.
4. **Local Marian translation** is intelligible but less natural than cloud fallback.
5. **Mixed Hebrew/English utterances** not explicitly trained.

---

## Recommended next steps

Pick one:

1. **Classifier hardening (highest ROI)**
   - Run synthetic data augmentation for AUGMENTED/EPHEMERAL and Hebrew paraphrases.
   - Re-run `finetune_minilm.py` and `train_classifier_head.py`.
   - Target: combined accuracy >85%.

2. **Try a larger embedding model**
   - Evaluate `intfloat/multilingual-e5-base` or `BAAI/bge-m3` if VRAM allows.
   - Requires rebuilding embeddings and retraining the head.

3. **Confidence-triggered LLM arbiter**
   - Add a slow but accurate LLM router that only fires when embedding+classifier confidence is low.

4. **Hebrew LoRA**
   - Fine-tune a Hebrew-speaking LoRA so the model outputs Hebrew directly, removing the translation layer.

---

## How to validate

```bash
cd /home/mike/lucy-v10

# Hebrew routing
/home/mike/lucy-v10/ui-v10/.venv/bin/python -m pytest \
  tools/router_py/test_hebrew_language.py \
  tools/router_py/test_hebrew_routing.py \
  tools/voice/tests/test_hebrew_tts.py -v

# Full router + voice suite
/home/mike/lucy-v10/ui-v10/.venv/bin/python -m pytest \
  tools/router_py/ tools/voice/tests/ -q
```

---

## Notes for next session

- Do **not** revert `classifier_head.pt` or `finetuned_minilm/` — they are now the production checkpoints.
- If retraining the classifier head, ensure `train_classifier_head.py` is used (the MLP save fix is in place).
- Policy gates override the embedding router; add new edge cases there first for immediate stability.
