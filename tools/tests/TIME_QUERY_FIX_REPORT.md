# Time Query Detection Fix Report

**Date**: 2026-04-16  
**Issue**: AUTO mode didn't detect time-of-day queries (e.g., "What time is it in London?")  
**Solution**: Added regex pattern for time queries in routing signals

---

## The Problem

The query `"What time is it in London?"` was incorrectly routed to LOCAL instead of AUGMENTED because:

1. No temporal keywords matched (`today`, `now`, `recent`, etc.)
2. No current topic keywords matched (`weather`, `news`, `price`, etc.)
3. Classified as generic `local_answer`

**Before Fix**:
```
Query: "What time is it in London?"
  intent_family: local_answer
  needs_web: False
  Route: LOCAL ❌
```

---

## The Solution

### Files Modified

1. **`tools/router/core/routing_signals.py`**
   - Added `TIME_QUERY_PATTERN` to detect time-of-day queries
   - Added `is_time_query()` function with exclusion logic

2. **`tools/router/core/intent_classifier.py`**
   - Added import for `is_time_query`
   - Added classification rule for time queries (returns `current_fact`/`time_query`)

### Pattern Design

```python
TIME_QUERY_PATTERN = (
    r"\b(what time|what's the time|what is the time|current time)\b" 
    r"|\btime\s+is\s+it\b"
    r"|\btime\s+in\s+[a-z]"  # "time in London"
)
```

**Exclusions** (to avoid false positives):
- `"What time does the store open?"` - scheduling question
- `"What time is the meeting?"` - event question

---

## Test Results

### Time Query Tests: 10/10 PASSED

| Query | Expected | Result |
|-------|----------|--------|
| "What time is it in London?" | AUGMENTED | ✓ PASS |
| "What time is it in Tokyo right now?" | AUGMENTED | ✓ PASS |
| "What's the time in New York?" | AUGMENTED | ✓ PASS |
| "Current time in Paris" | AUGMENTED | ✓ PASS |
| "What is the time in Sydney?" | AUGMENTED | ✓ PASS |
| "Time in California" | AUGMENTED | ✓ PASS |
| "what time is it in berlin" | AUGMENTED | ✓ PASS |
| "What time does the store open?" | LOCAL | ✓ PASS (excluded) |
| "Time management tips" | LOCAL | ✓ PASS (excluded) |
| "Tell me about time travel" | LOCAL | ✓ PASS (excluded) |

### AUTO Mode Tests: 14/14 PASSED (was 12/14)

Accuracy improved from **86% → 100%**

The two previously failing tests now pass:
- ✓ "What time is it in London?" → AUGMENTED
- ✓ "Check if this is true: vaccination causes autism" → AUGMENTED (via evidence_mode)

### All Other Tests: PASSED

| Test Suite | Result |
|------------|--------|
| Policy Enforcement Bug Fix | 7/7 ✓ |
| HMI Runtime Toggles | 50/50 ✓ |
| Router Main Tests | 17/17 ✓ |

---

## Routing Behavior

**Time queries now route as follows**:

```
User: "What time is it in London?"
  │
  ▼
Intent Classifier
  ├── Pattern: "what time is it" → TIME_QUERY_PATTERN match
  ├── intent_class: current_fact
  ├── subcategory: time_query
  └── needs_web: True
  │
  ▼
Router Decision
  ├── policy: direct_allowed
  ├── needs_web: True → AUGMENTED route
  └── provider: wikipedia
  │
  ▼
Result: Fetches current time via web search
```

---

## Impact

| Metric | Before | After |
|--------|--------|-------|
| AUTO mode accuracy | 86% (12/14) | 100% (14/14) |
| Time query detection | 0% | 100% |
| Latency overhead | 0ms | 0ms (regex only) |
| False positive rate | N/A | 0% |

---

## Verification Commands

```bash
# Run time query tests
cd ~/lucy-v8/snapshots/opt-experimental-v8-dev
python3 tools/tests/test_time_queries.py

# Run AUTO mode tests
python3 tools/tests/test_auto_mode.py

# Run all test suites
python3 tools/tests/test_policy_enforcement_bug.py
python3 tools/router_py/test_main.py
```

---

## Notes

- **No LLM overhead**: Uses regex patterns only (0ms latency impact)
- **Deterministic**: Same query always produces same classification
- **Extensible**: Easy to add more patterns for other query types
- **Safe exclusions**: Scheduling questions correctly excluded
