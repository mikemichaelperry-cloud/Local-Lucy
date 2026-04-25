#!/usr/bin/env python3
"""Test time query detection and routing."""

import sys
sys.path.insert(0, str(__file__).replace('/tools/tests/test_time_queries.py', '/tools'))

from router_py.classify import classify_intent, select_route


def test_time_queries():
    time_queries = [
        ("What time is it in London?", True),
        ("What time is it in Tokyo right now?", True),
        ("What's the time in New York?", True),
        ("Current time in Paris", True),
        ("What is the time in Sydney?", True),
        ("Time in California", True),
        ("what time is it in berlin", True),
        # Negative cases - should NOT trigger time query
        ("What time does the store open?", False),
        ("Time management tips", False),
        ("Tell me about time travel", False),
    ]
    
    print("=" * 70)
    print("TIME QUERY DETECTION TEST")
    print("=" * 70)
    print()
    
    passed = 0
    failed = 0
    
    for query, should_be_time_query in time_queries:
        classification = classify_intent(query, surface="cli")
        decision = select_route(classification, policy="direct_allowed")
        
        subcategory = classification.raw_plan.get("subcategory", "")
        is_time = subcategory == "time_query"
        is_augmented = decision.route == "AUGMENTED"
        
        if should_be_time_query:
            test_passed = is_time and is_augmented
        else:
            test_passed = not is_time
        
        status = "✓" if test_passed else "✗"
        print(f'{status} "{query}"')
        print(f'   subcategory={subcategory}, route={decision.route}')
        
        if test_passed:
            passed += 1
        else:
            failed += 1
    
    print()
    print("=" * 70)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 70)
    
    return failed == 0


if __name__ == "__main__":
    success = test_time_queries()
    sys.exit(0 if success else 1)
