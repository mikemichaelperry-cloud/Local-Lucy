# Policy Enforcement Bug Fix Report

**Date**: 2026-04-16  
**Bug**: Evidence mode queries bypass augmentation policy check  
**File**: `tools/router_py/classify.py`  
**Lines**: 214-220

---

## The Bug

News queries (and other `evidence_mode=required` queries) were going online even when `policy=disabled` was set.

### Root Cause

The code checked `evidence_mode` **before** checking `policy`, causing evidence-required queries to bypass the policy check entirely.

### Before (Buggy)

```python
# Evidence mode queries always go augmented
if classification.evidence_mode == "required":
    return _make_augmented_decision(classification, prefer_paid=True)

# Check policy
if policy == "disabled":
    return _make_local_decision(classification)
```

### After (Fixed)

```python
# Check policy first - disabled policy overrides everything
if policy == "disabled":
    return _make_local_decision(classification)

# Evidence mode queries go augmented (if policy allows)
if classification.evidence_mode == "required":
    return _make_augmented_decision(classification, prefer_paid=True)
```

---

## Test Results

### Unit Tests: 7/7 PASSED

| Test | Result |
|------|--------|
| Policy Disabled Overrides Evidence Required | ✓ PASS |
| Policy Disabled Overrides News Query | ✓ PASS |
| Policy Fallback With Evidence Goes Augmented | ✓ PASS |
| Policy Direct Allows Evidence | ✓ PASS |
| Evidence Mode Required With Default Policy | ✓ PASS |
| Non-Evidence Query With Disabled Policy | ✓ PASS |
| All Policy Modes Matrix | ✓ PASS |

### End-to-End Verification: PASSED

```
✓ policy=disabled, evidence='required' -> LOCAL
✓ policy=disabled, evidence=''         -> LOCAL
✓ policy=fallback_only, evidence='required' -> AUGMENTED
✓ policy=fallback_only, evidence=''         -> LOCAL
✓ policy=direct_allowed, evidence='required' -> AUGMENTED
✓ policy=direct_allowed, evidence=''         -> AUGMENTED
```

### Existing Test Suite: 17/17 PASSED

All existing tests in `tools/router_py/test_main.py` continue to pass.

---

## Behavior Matrix

| Policy | Evidence Mode | Route | Notes |
|--------|--------------|-------|-------|
| `disabled` | `required` | **LOCAL** | **BUG FIX: Now stays offline** |
| `disabled` | `` (none) | LOCAL | Unchanged |
| `fallback_only` | `required` | AUGMENTED | Evidence takes precedence |
| `fallback_only` | `` (none) | LOCAL | With fallback capability |
| `direct_allowed` | `required` | AUGMENTED | Unchanged |
| `direct_allowed` | `` (none) | AUGMENTED | Unchanged |

---

## Files Modified

1. **`tools/router_py/classify.py`** (lines 214-220)
   - Moved policy check before evidence mode check
   - Added clarifying comment

2. **`tools/tests/test_policy_enforcement_bug.py`** (new file)
   - Comprehensive unit tests for the fix
   - 7 test cases covering all policy/evidence combinations

---

## Impact

- **Critical bug fixed**: News queries now respect `policy=disabled`
- **No regressions**: All existing tests pass
- **Clear behavior**: Policy hierarchy is now explicit and testable

---

## Verification Commands

```bash
# Run bug fix tests
cd ~/lucy-v8/snapshots/opt-experimental-v8-dev
python3 tools/tests/test_policy_enforcement_bug.py

# Run existing test suite
python3 tools/router_py/test_main.py

# Run augmentation policy toggle tests
python3 tools/tests/test_hmi_runtime_toggles.py augmentation
```
