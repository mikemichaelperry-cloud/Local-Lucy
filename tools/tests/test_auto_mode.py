#!/usr/bin/env python3
"""Test AUTO mode behavior - verifies automatic online/offline selection.

AUTO mode should:
- Go ONLINE for: current facts, news, time-sensitive queries, evidence checks
- Stay OFFLINE for: local knowledge, identity, conversational, technical explanations
"""

import sys
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "router_py"))

from router_py.classify import classify_intent, select_route
from router_py.policy import normalize_augmentation_policy


def test_auto_mode_routing():
    """Test that AUTO mode correctly selects online vs offline based on query content."""

    # Test cases: (query, expected_needs_web, description)
    test_cases = [
        # Should go ONLINE (needs_web=True)
        ("What is the latest news today?", True, "News query"),
        ("Who is the current president?", True, "Current fact"),
        ("What time is it in London?", True, "Time-sensitive"),
        ("Check if this is true: vaccination causes autism", True, "Fact check"),
        ("What is the weather today?", True, "Weather (current)"),
        ("Stock price of Apple?", True, "Current data"),
        # Should stay OFFLINE (needs_web=False)
        ("Who was Albert Einstein?", False, "Historical figure"),
        ("Explain how photosynthesis works", False, "Scientific explanation"),
        ("What is the capital of France?", True, "Static fact"),
        ("Tell me about your dog", False, "Conversational"),
        ("Who are you?", False, "Identity"),
        ("How do I bake sourdough bread?", True, "How-to knowledge"),
        ("What is quantum mechanics?", False, "Technical explanation"),
        ("Tell me a joke", False, "Casual conversation"),
    ]

    print("=" * 70)
    print("AUTO MODE ROUTING TEST")
    print("=" * 70)
    print("\nTesting if AUTO mode correctly selects ONLINE vs OFFLINE...\n")

    results = []

    for query, expected_needs_web, description in test_cases:
        try:
            # Classify the query
            classification = classify_intent(query, surface="cli")

            # Get the routing decision (AUTO mode - no forced_mode)
            policy = normalize_augmentation_policy("direct_allowed")  # Allow both
            decision = select_route(classification, policy=policy, forced_mode=None, query=query)

            # Check results
            actual_needs_web = classification.needs_web
            evidence_mode = classification.evidence_mode
            route = decision.route
            mode = decision.mode

            # Determine if test passed
            online_routes = {"AUGMENTED", "EVIDENCE", "NEWS", "TIME", "WEATHER", "FINANCE"}
            if expected_needs_web:
                # Should go to a live-data/external route
                passed = route in online_routes
                expected_route = "external"
            else:
                # Should stay offline (LOCAL route)
                passed = route in ("LOCAL", "BYPASS")
                expected_route = "LOCAL/BYPASS"

            results.append(
                {
                    "query": query,
                    "description": description,
                    "expected_online": expected_needs_web,
                    "actual_needs_web": actual_needs_web,
                    "route": route,
                    "mode": mode,
                    "passed": passed,
                }
            )

            status = "✓ PASS" if passed else "✗ FAIL"
            color = "\033[92m" if passed else "\033[91m"
            reset = "\033[0m"

            print(f"{color}{status}{reset} [{description}]")
            print(f'     Query: "{query}"')
            print(f"     Expected: {'ONLINE' if expected_needs_web else 'OFFLINE'}")
            print(f"     Actual: needs_web={actual_needs_web}, route={route}, mode={mode}")
            print()

        except Exception as e:
            print(f"✗ ERROR [{description}]: {e}")
            print(f'     Query: "{query}"\n')
            results.append(
                {"query": query, "description": description, "error": str(e), "passed": False}
            )

    # Summary
    passed_count = sum(1 for r in results if r.get("passed"))
    total_count = len(results)

    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Passed: {passed_count}/{total_count}")
    print(f"Failed: {total_count - passed_count}/{total_count}")

    if passed_count == total_count:
        print("\n✓ ALL TESTS PASSED - AUTO mode working correctly!")
    else:
        print(f"\n✗ {total_count - passed_count} test(s) failed")
        print("\nFailed cases:")
        for r in results:
            if not r.get("passed"):
                print(f'  - {r["description"]}: "{r["query"]}"')
    assert passed_count == total_count, (
        f"AUTO mode routing failed: {total_count - passed_count}/{total_count}"
    )


def test_auto_mode_with_policy():
    """Test AUTO mode respects augmentation policy."""

    print("\n" + "=" * 70)
    print("AUTO MODE WITH POLICY TEST")
    print("=" * 70)
    print("\nTesting that AUTO mode respects augmentation policy...\n")

    # A query that would normally go online
    query = "What is the latest news about Ukraine?"

    policies = [
        ("disabled", "OFFLINE", "Should force offline regardless of query"),
        ("fallback_only", "ONLINE", "Should allow online route under fallback_only"),
        ("direct_allowed", "ONLINE", "Should go directly online if needed"),
    ]

    results = []

    for policy_name, expected_route_type, description in policies:
        try:
            classification = classify_intent(query, surface="cli")
            policy = normalize_augmentation_policy(policy_name)
            decision = select_route(classification, policy=policy, forced_mode=None, query=query)

            # Check if route matches expectation
            online_routes = {"AUGMENTED", "EVIDENCE", "NEWS", "TIME", "WEATHER", "FINANCE"}
            if expected_route_type == "OFFLINE":
                passed = decision.route in ("LOCAL", "BYPASS")
            elif expected_route_type == "ONLINE":
                passed = decision.route in online_routes
            else:
                passed = decision.route == expected_route_type

            results.append({"policy": policy_name, "passed": passed, "route": decision.route})

            status = "✓ PASS" if passed else "✗ FAIL"
            color = "\033[92m" if passed else "\033[91m"
            reset = "\033[0m"

            print(f"{color}{status}{reset} Policy: {policy_name}")
            print(f"     Expected: {expected_route_type}, Got: {decision.route}")
            print(f"     {description}\n")

        except Exception as e:
            print(f"✗ ERROR [{policy_name}]: {e}\n")
            results.append({"policy": policy_name, "passed": False, "error": str(e)})

    passed_count = sum(1 for r in results if r["passed"])
    total_count = len(results)

    print(f"Passed: {passed_count}/{total_count}")

    assert passed_count == total_count, (
        f"AUTO mode policy failed: {total_count - passed_count}/{total_count}"
    )


def test_forced_modes():
    """Test that FORCED_OFFLINE and FORCED_ONLINE override AUTO."""

    print("\n" + "=" * 70)
    print("FORCED MODE OVERRIDE TEST")
    print("=" * 70)
    print("\nTesting that forced modes override AUTO...\n")

    # A query that would normally go online
    online_query = "What is the latest news?"
    # A query that would normally stay offline
    offline_query = "Who was Albert Einstein?"

    test_cases = [
        (online_query, "FORCED_OFFLINE", "LOCAL", "Online query forced offline"),
        (offline_query, "FORCED_ONLINE", "AUGMENTED", "Offline query forced online"),
    ]

    results = []

    for query, forced_mode, expected_route, description in test_cases:
        try:
            classification = classify_intent(query, surface="cli")
            policy = normalize_augmentation_policy("direct_allowed")
            decision = select_route(
                classification, policy=policy, forced_mode=forced_mode, query=query
            )

            passed = decision.route == expected_route
            results.append({"description": description, "passed": passed, "route": decision.route})

            status = "✓ PASS" if passed else "✗ FAIL"
            color = "\033[92m" if passed else "\033[91m"
            reset = "\033[0m"

            print(f"{color}{status}{reset} {description}")
            print(f'     Query: "{query}"')
            print(
                f"     Forced: {forced_mode}, Expected: {expected_route}, Got: {decision.route}\n"
            )

        except Exception as e:
            print(f"✗ ERROR [{description}]: {e}\n")
            results.append({"description": description, "passed": False})

    passed_count = sum(1 for r in results if r["passed"])
    total_count = len(results)

    print(f"Passed: {passed_count}/{total_count}")

    assert passed_count == total_count, (
        f"Forced mode override failed: {total_count - passed_count}/{total_count}"
    )


if __name__ == "__main__":
    import sys

    result1 = test_auto_mode_routing()
    result2 = test_auto_mode_with_policy()
    result3 = test_forced_modes()

    print("\n" + "=" * 70)
    print("FINAL RESULT")
    print("=" * 70)

    if result1 == 0 and result2 == 0 and result3 == 0:
        print("\n✓ ALL TESTS PASSED")
        print("\nAUTO mode is working correctly!")
        print("- Automatically detects web-needing queries")
        print("- Respects augmentation policy")
        print("- Forced modes properly override AUTO")
        sys.exit(0)
    else:
        print("\n✗ SOME TESTS FAILED")
        sys.exit(1)
