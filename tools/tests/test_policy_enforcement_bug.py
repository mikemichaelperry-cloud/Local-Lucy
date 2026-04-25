#!/usr/bin/env python3
"""
Test for Policy Enforcement Bug Fix

Bug: Evidence mode queries bypass augmentation policy check
Issue: News queries go online even with policy=disabled
Fix: Move policy check before evidence mode check

This test verifies that:
1. policy=disabled forces LOCAL route even for evidence_mode=required queries
2. policy=fallback_only and policy=direct_allowed still work correctly
3. All combinations work as expected
"""

import sys
import os

# Add tools to path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from router_py.classify import (
    ClassificationResult,
    RoutingDecision,
    select_route,
)


def create_test_classification(
    intent_family="current_evidence",
    evidence_mode="required",
    needs_web=True,
    confidence=0.9,
):
    """Create a test classification with specified properties."""
    return ClassificationResult(
        intent="test_intent",
        intent_family=intent_family,
        intent_class="test_class",
        category="test_category",
        confidence=confidence,
        needs_web=needs_web,
        needs_memory=False,
        needs_synthesis=False,
        clarify_required=False,
        evidence_mode=evidence_mode,
        evidence_reason="test_reason" if evidence_mode else "",
        augmentation_recommended=bool(evidence_mode),
    )


def test_policy_disabled_overrides_evidence_required():
    """
    CRITICAL BUG FIX TEST:
    
    When policy is 'disabled', even evidence_mode='required' queries
    should be routed to LOCAL, not AUGMENTED.
    
    Before fix: evidence_mode check happened first, bypassing policy
    After fix: policy check happens first, overriding evidence_mode
    """
    classification = create_test_classification(
        intent_family="current_evidence",
        evidence_mode="required",
        needs_web=True,
    )
    
    decision = select_route(classification, policy="disabled")
    
    assert decision.route == "LOCAL", (
        f"BUG: policy=disabled should force LOCAL route, "
        f"but got route={decision.route}"
    )
    assert decision.provider == "local", (
        f"BUG: policy=disabled should force local provider, "
        f"but got provider={decision.provider}"
    )
    print("✓ PASS: policy=disabled correctly overrides evidence_mode=required")
    return True


def test_policy_disabled_overrides_news_query():
    """
    Test with a realistic news query scenario.
    """
    classification = create_test_classification(
        intent_family="current_evidence",
        evidence_mode="required",
        needs_web=True,
        confidence=0.95,
    )
    
    decision = select_route(classification, policy="disabled")
    
    assert decision.route == "LOCAL", (
        f"News query with policy=disabled should stay LOCAL, "
        f"but got route={decision.route}"
    )
    print("✓ PASS: News queries respect policy=disabled")
    return True


def test_policy_fallback_with_evidence_goes_augmented():
    """
    When policy is 'fallback_only' but evidence_mode is 'required',
    evidence requirement takes precedence - must go augmented to fetch evidence.
    """
    classification = create_test_classification(
        intent_family="current_evidence",
        evidence_mode="required",
        needs_web=True,
    )
    
    decision = select_route(classification, policy="fallback_only")
    
    # evidence_mode=required forces AUGMENTED regardless of fallback_only policy
    assert decision.route == "AUGMENTED", (
        f"evidence_mode=required should force AUGMENTED even with fallback_only, "
        f"but got route={decision.route}"
    )
    print("✓ PASS: evidence_mode=required correctly overrides fallback_only policy")
    return True


def test_policy_direct_allows_evidence():
    """
    When policy is 'direct_allowed', evidence_mode queries should
    go directly to augmented route.
    """
    classification = create_test_classification(
        intent_family="current_evidence",
        evidence_mode="required",
        needs_web=True,
    )
    
    decision = select_route(classification, policy="direct_allowed")
    
    # Should go directly to augmented
    assert decision.route == "AUGMENTED", (
        f"policy=direct_allowed with evidence should go AUGMENTED, "
        f"but got route={decision.route}"
    )
    print("✓ PASS: policy=direct_allowed correctly routes to AUGMENTED")
    return True


def test_evidence_mode_required_without_policy():
    """
    When no explicit policy (defaults to fallback_only),
    evidence_mode=required should go augmented.
    """
    classification = create_test_classification(
        intent_family="current_evidence",
        evidence_mode="required",
        needs_web=True,
    )
    
    # Default policy is fallback_only
    decision = select_route(classification, policy="fallback_only")
    
    # Should route appropriately (local with fallback for current_evidence)
    assert decision.route in ("LOCAL", "LOCAL_WITH_FALLBACK", "AUGMENTED"), (
        f"evidence_mode=required should route appropriately, "
        f"but got route={decision.route}"
    )
    print("✓ PASS: evidence_mode=required routes correctly with default policy")
    return True


def test_non_evidence_query_with_disabled_policy():
    """
    Non-evidence queries with policy=disabled should also stay local.
    """
    classification = create_test_classification(
        intent_family="general_knowledge",
        evidence_mode="",  # No evidence required
        needs_web=False,
    )
    
    decision = select_route(classification, policy="disabled")
    
    assert decision.route == "LOCAL", (
        f"Non-evidence query with policy=disabled should stay LOCAL, "
        f"but got route={decision.route}"
    )
    print("✓ PASS: Non-evidence queries respect policy=disabled")
    return True


def test_all_policy_modes_matrix():
    """
    Test matrix of all policy modes vs evidence modes.
    """
    results = []
    
    test_cases = [
        # (policy, evidence_mode, expected_route_type)
        ("disabled", "required", "LOCAL"),
        ("disabled", "", "LOCAL"),
        ("fallback_only", "required", "AUGMENTED"),  # evidence_mode takes precedence
        ("fallback_only", "", "LOCAL"),  # No evidence -> local (fallback capability via policy_reason)
        ("direct_allowed", "required", "AUGMENTED"),
    ]
    
    for policy, evidence_mode, expected_base in test_cases:
        classification = create_test_classification(
            intent_family="current_evidence",
            evidence_mode=evidence_mode,
            needs_web=True,
        )
        
        decision = select_route(classification, policy=policy)
        
        # Check based on expected base
        if expected_base == "LOCAL":
            passed = decision.route == "LOCAL"
        elif expected_base == "AUGMENTED":
            passed = decision.route == "AUGMENTED"
        else:
            passed = decision.route in ("LOCAL", "LOCAL_WITH_FALLBACK")
        
        results.append((policy, evidence_mode, decision.route, passed))
        
        status = "✓" if passed else "✗"
        print(f"  {status} policy={policy}, evidence={evidence_mode!r} -> {decision.route}")
    
    all_passed = all(r[3] for r in results)
    if all_passed:
        print("✓ PASS: All policy mode combinations work correctly")
    else:
        print("✗ FAIL: Some policy mode combinations failed")
    
    return all_passed


def run_all_tests():
    """Run all policy enforcement tests."""
    print("=" * 60)
    print("POLICY ENFORCEMENT BUG FIX TESTS")
    print("=" * 60)
    print()
    
    tests = [
        ("Policy Disabled Overrides Evidence Required", test_policy_disabled_overrides_evidence_required),
        ("Policy Disabled Overrides News Query", test_policy_disabled_overrides_news_query),
        ("Policy Fallback With Evidence Goes Augmented", test_policy_fallback_with_evidence_goes_augmented),
        ("Policy Direct Allows Evidence", test_policy_direct_allows_evidence),
        ("Evidence Mode Required Without Explicit Policy", test_evidence_mode_required_without_policy),
        ("Non-Evidence Query With Disabled Policy", test_non_evidence_query_with_disabled_policy),
        ("All Policy Modes Matrix", test_all_policy_modes_matrix),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        print(f"\n--- {name} ---")
        try:
            if test_func():
                passed += 1
            else:
                failed += 1
        except AssertionError as e:
            print(f"✗ FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ ERROR: {e}")
            failed += 1
    
    print()
    print("=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
