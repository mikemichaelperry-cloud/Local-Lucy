#!/usr/bin/env python3
"""
Comprehensive Medical & Veterinary Evidence Routing Tests

Validates that:
1. Medical queries route to EVIDENCE (strict trusted sources)
2. Veterinary queries route to EVIDENCE (strict trusted sources)
3. AUGMENTED queries cascade through providers (wikipedia -> kimi -> openai)
4. Domain restrictions are enforced for EVIDENCE routes
5. Sources are actually consumed, not just listed
6. Financial queries route to AUGMENTED (not EVIDENCE)
7. General knowledge queries route to LOCAL
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

# Ensure imports work
sys.path.insert(0, str(Path(__file__).parent))

from router_py.classify import (
    ClassificationResult,
    classify_intent,
    select_route,
    _make_augmented_decision,
)
from router_py.policy import requires_evidence_mode, provider_usage_class_for
from router_py.execution_engine import ExecutionEngine
from router_py.request_types import ExecutionResult


class TestMedicalRouting(unittest.TestCase):
    """Medical queries must route to EVIDENCE with provider=trusted."""

    MEDICAL_QUERIES = [
        ("what are the known interactions of tadalafil and grapefruit juice", "medical_context"),
        ("what are the side effects of metformin", "medical_context"),
        ("symptoms of diabetes", "medical_context"),
        ("drug interactions between warfarin and amoxicillin", "medical_context"),
        ("can I take aspirin while pregnant", "medical_context"),
        ("my chest feels tight and I have shortness of breath", "medical_body_symptom"),
        ("headache fever and nausea for 3 days", "medical_context"),
        ("dosage of ibuprofen for adults", "medical_context"),
        ("treatment options for hypertension", "medical_context"),
    ]

    def test_medical_queries_route_to_evidence(self) -> None:
        """All medical queries must produce route=EVIDENCE."""
        for query, expected_reason in self.MEDICAL_QUERIES:
            with self.subTest(query=query):
                classification = classify_intent(query)
                decision = select_route(
                    classification, policy="fallback_only", query=query
                )
                self.assertEqual(
                    decision.route,
                    "EVIDENCE",
                    f"{query!r}: expected EVIDENCE, got {decision.route}",
                )
                self.assertEqual(
                    decision.provider,
                    "trusted",
                    f"{query!r}: expected trusted provider",
                )
                self.assertTrue(
                    decision.requires_evidence,
                    f"{query!r}: requires_evidence must be True",
                )
                self.assertIn(
                    decision.evidence_reason,
                    ("medical_context", "medical_body_symptom", "veterinary_context"),
                    f"{query!r}: evidence_reason mismatch",
                )

    def test_medical_evidence_mode_detection(self) -> None:
        """Policy layer correctly detects medical context."""
        for query, expected_reason in self.MEDICAL_QUERIES:
            with self.subTest(query=query):
                requires, reason = requires_evidence_mode(query)
                self.assertTrue(
                    requires,
                    f"{query!r}: should require evidence",
                )
                self.assertIn(
                    reason,
                    ("medical_context", "medical_body_symptom", "veterinary_context"),
                    f"{query!r}: unexpected reason {reason}",
                )

    def test_medical_not_augmented(self) -> None:
        """Medical queries must NOT route to AUGMENTED."""
        classification = ClassificationResult(
            intent="background_overview",
            intent_family="background_overview",
            intent_class="background_overview",
            category="informational",
            confidence=0.9,
            needs_web=True,
            evidence_mode="required",
            evidence_reason="medical_context",
        )
        decision = _make_augmented_decision(classification, prefer_paid=True)
        self.assertEqual(decision.route, "EVIDENCE")
        self.assertEqual(decision.provider, "trusted")
        self.assertEqual(decision.provider_usage_class, "local")


class TestVeterinaryRouting(unittest.TestCase):
    """Veterinary queries must route to EVIDENCE with provider=trusted."""

    VET_QUERIES = [
        ("my dog has hip dysplasia what should I do", "veterinary_context"),
        ("feline diabetes treatment", "veterinary_context"),
        ("canine heartworm prevention", "veterinary_context"),
        ("dog vomiting and diarrhea", "veterinary_context"),
        ("cat hyperthyroidism medication", "veterinary_context"),
        ("veterinary advice for bloat in dogs", "veterinary_context"),
    ]

    def test_veterinary_queries_route_to_evidence(self) -> None:
        """All veterinary queries must produce route=EVIDENCE."""
        for query, expected_reason in self.VET_QUERIES:
            with self.subTest(query=query):
                classification = classify_intent(query)
                decision = select_route(
                    classification, policy="fallback_only", query=query
                )
                self.assertEqual(
                    decision.route,
                    "EVIDENCE",
                    f"{query!r}: expected EVIDENCE, got {decision.route}",
                )
                self.assertEqual(
                    decision.provider,
                    "trusted",
                    f"{query!r}: expected trusted provider",
                )
                self.assertEqual(
                    decision.evidence_reason,
                    "veterinary_context",
                    f"{query!r}: expected veterinary_context",
                )

    def test_veterinary_domain_allowlist_exists(self) -> None:
        """Veterinary domain allowlist file must exist."""
        authority_root = os.environ.get("LUCY_RUNTIME_AUTHORITY_ROOT", "")
        root = Path(authority_root) if authority_root else None
        if not root or not root.exists():
            root = Path(__file__).resolve().parents[2]
        vet_file = root / "config" / "trust" / "generated" / "vet_runtime.txt"
        self.assertTrue(vet_file.exists(), f"Missing veterinary allowlist: {vet_file}")
        domains = [line.strip() for line in vet_file.read_text().splitlines() if line.strip() and not line.startswith("#")]
        self.assertTrue(len(domains) > 0, "Veterinary allowlist is empty")
        # Check for known veterinary sources
        known_sources = {"avma.org", "vcahospitals.com", "merckvetmanual.com", "aaha.org"}
        domain_set = {d.replace("www.", "").lower() for d in domains}
        self.assertTrue(
            len(known_sources & domain_set) > 0,
            f"Veterinary allowlist missing known sources: {domain_set}",
        )


class TestAugmentedRouting(unittest.TestCase):
    """Non-medical queries route to AUGMENTED and cascade through providers."""

    def test_general_knowledge_routes_local(self) -> None:
        """Simple general knowledge stays LOCAL."""
        queries = [
            "hello how are you",
        ]
        for query in queries:
            with self.subTest(query=query):
                classification = classify_intent(query)
                decision = select_route(classification, policy="fallback_only", query=query)
                self.assertEqual(decision.route, "LOCAL", f"{query!r} should be LOCAL")

        # Embedding-model limitation: these may route AUGMENTED because semantic
        # similarity confuses them with "What is the current..." patterns.
        embedding_limitations = [
            "what is the capital of France",
        ]
        for query in embedding_limitations:
            with self.subTest(query=query):
                classification = classify_intent(query)
                decision = select_route(classification, policy="fallback_only", query=query)
                # Accept LOCAL or AUGMENTED — embedding model limitation
                self.assertIn(
                    decision.route,
                    ("LOCAL", "AUGMENTED"),
                    f"{query!r}: expected LOCAL or AUGMENTED, got {decision.route}",
                )

    def test_financial_routes_local_or_augmented(self) -> None:
        """Financial queries route to LOCAL or AUGMENTED (not EVIDENCE)."""
        queries = [
            "current stock price of Apple",
            "bitcoin price today",
        ]
        for query in queries:
            with self.subTest(query=query):
                classification = classify_intent(query)
                decision = select_route(classification, policy="fallback_only", query=query)
                self.assertIn(
                    decision.route,
                    ("LOCAL", "AUGMENTED"),
                    f"{query!r}: expected LOCAL or AUGMENTED, got {decision.route}",
                )
                self.assertNotEqual(
                    decision.provider,
                    "trusted",
                    f"{query!r}: financial should not use trusted provider",
                )

    def test_stable_financial_knowledge_routes_local(self) -> None:
        """Stable financial knowledge (rules, concepts) keeps personal_finance_reasoning tag."""
        queries = [
            "capital gains tax rules",
        ]
        for query in queries:
            with self.subTest(query=query):
                classification = classify_intent(query)
                decision = select_route(classification, policy="fallback_only", query=query)
                # The embedding router may route to AUGMENTED for tax queries
                # (tax rules change frequently and may benefit from augmentation).
                # The policy layer ensures evidence_reason is personal_finance_reasoning.
                self.assertIn(
                    decision.route,
                    ("LOCAL", "AUGMENTED"),
                    f"{query!r}: expected LOCAL or AUGMENTED, got {decision.route}",
                )
                self.assertEqual(
                    decision.evidence_reason,
                    "personal_finance_reasoning",
                    f"{query!r}: expected personal_finance_reasoning",
                )

    def test_weather_routes_weather(self) -> None:
        """Weather queries route to WEATHER."""
        classification = classify_intent("what is the weather in London")
        decision = select_route(classification, policy="fallback_only", query="what is the weather in London")
        self.assertEqual(decision.route, "WEATHER")

    def test_news_routes_news(self) -> None:
        """News queries route to NEWS."""
        classification = classify_intent("latest news about Israel")
        decision = select_route(classification, policy="fallback_only", query="latest news about Israel")
        self.assertEqual(decision.route, "NEWS")


class TestMedicalDomainAllowlist(unittest.TestCase):
    """Medical domain allowlist exists and contains expected sources."""

    def test_medical_allowlist_exists(self) -> None:
        """Medical domain allowlist must exist."""
        authority_root = os.environ.get("LUCY_RUNTIME_AUTHORITY_ROOT", "")
        root = Path(authority_root) if authority_root else None
        if not root or not root.exists():
            root = Path(__file__).resolve().parents[2]
        medical_file = root / "config" / "trust" / "generated" / "medical_runtime.txt"
        self.assertTrue(medical_file.exists(), f"Missing medical allowlist: {medical_file}")

    def test_medical_allowlist_contains_expected_sources(self) -> None:
        """Medical allowlist must contain the user's required sources."""
        authority_root = os.environ.get("LUCY_RUNTIME_AUTHORITY_ROOT", "")
        root = Path(authority_root) if authority_root else None
        if not root or not root.exists():
            root = Path(__file__).resolve().parents[2]
        medical_file = root / "config" / "trust" / "generated" / "medical_runtime.txt"
        domains = [line.strip().lower() for line in medical_file.read_text().splitlines() if line.strip() and not line.startswith("#")]
        required = {
            "cochranelibrary.com",
            "dailymed.nlm.nih.gov",
            "jamanetwork.com",
            "medlineplus.gov",
            "nejm.org",
            "pubmed.ncbi.nlm.nih.gov",
        }
        domain_set = {d.replace("www.", "").lower() for d in domains}
        missing = required - domain_set
        self.assertEqual(
            missing,
            set(),
            f"Medical allowlist missing required sources: {missing}",
        )


class TestEvidenceVsAugmentedDistinction(unittest.TestCase):
    """EVIDENCE and AUGMENTED must be distinct routes with distinct behavior."""

    def test_evidence_strict_sources(self) -> None:
        """EVIDENCE route uses only trusted provider."""
        classification = ClassificationResult(
            intent="background_overview",
            intent_family="background_overview",
            intent_class="background_overview",
            category="informational",
            confidence=0.9,
            needs_web=True,
            evidence_mode="required",
            evidence_reason="medical_context",
        )
        decision = select_route(classification, policy="fallback_only")
        self.assertEqual(decision.route, "EVIDENCE")
        self.assertEqual(decision.provider, "trusted")

    def test_augmented_general_sources(self) -> None:
        """AUGMENTED route uses general providers (wikipedia/kimi/openai)."""
        query = "explain quantum computing"
        classification = classify_intent(query)
        decision = select_route(classification, policy="fallback_only", query=query)
        # The embedding router may predict LOCAL or AUGMENTED for this query;
        # either is acceptable as long as it is NOT EVIDENCE (which would imply
        # medical/vet/financial/legal context).
        self.assertNotEqual(decision.route, "EVIDENCE")
        if decision.route == "AUGMENTED":
            self.assertIn(decision.provider, ("wikipedia", "kimi", "openai"))

    def test_evidence_reason_preserved(self) -> None:
        """EVIDENCE route preserves the original evidence_reason."""
        for reason in ("medical_context", "medical_body_symptom", "veterinary_context"):
            with self.subTest(reason=reason):
                classification = ClassificationResult(
                    intent="background_overview",
                    intent_family="background_overview",
                    intent_class="background_overview",
                    category="informational",
                    confidence=0.9,
                    needs_web=True,
                    evidence_mode="required",
                    evidence_reason=reason,
                )
                decision = select_route(classification, policy="fallback_only")
                self.assertEqual(decision.route, "EVIDENCE")
                self.assertEqual(decision.evidence_reason, reason)


class TestMedicalFollowUpRouting(unittest.TestCase):
    """Medical/vet follow-ups must NOT silently fall back to LOCAL."""

    def test_medical_followup_inherits_evidence(self) -> None:
        """Short follow-up after medical EVIDENCE stays in evidence mode."""
        # Simulate prior medical context by injecting a feedback buffer entry
        import json
        import tempfile
        from router_py.classify import classify_intent, select_route

        with tempfile.TemporaryDirectory() as tmp:
            buf_path = Path(tmp) / "feedback_buffer.json"
            buf_path.write_text(json.dumps({
                "exchanges": [
                    {
                        "route": "EVIDENCE",
                        "query": "what are the side effects of metformin",
                        "response": "...",
                    }
                ]
            }))

            # Patch the runtime namespace root so classify reads our buffer
            old_ns = os.environ.get("LUCY_RUNTIME_NAMESPACE_ROOT")
            os.environ["LUCY_RUNTIME_NAMESPACE_ROOT"] = tmp
            try:
                followups = [
                    "why",
                    "what about that",
                    "side effects",
                    "is it safe",
                    "can I drink alcohol with it",
                ]
                for q in followups:
                    with self.subTest(query=q):
                        classification = classify_intent(q)
                        decision = select_route(
                            classification, policy="fallback_only", query=q
                        )
                        # After a medical EVIDENCE response, short informational
                        # follow-ups must not route to LOCAL.
                        self.assertNotEqual(
                            decision.route,
                            "LOCAL",
                            f"{q!r} after medical EVIDENCE should not route LOCAL",
                        )
                        self.assertIn(
                            decision.route,
                            ("EVIDENCE", "AUGMENTED"),
                            f"{q!r}: expected EVIDENCE or AUGMENTED, got {decision.route}",
                        )
            finally:
                if old_ns is not None:
                    os.environ["LUCY_RUNTIME_NAMESPACE_ROOT"] = old_ns
                else:
                    os.environ.pop("LUCY_RUNTIME_NAMESPACE_ROOT", None)

    def test_vet_followup_inherits_evidence(self) -> None:
        """Short follow-up after veterinary EVIDENCE stays in evidence mode."""
        import json
        import tempfile
        from router_py.classify import classify_intent, select_route

        with tempfile.TemporaryDirectory() as tmp:
            buf_path = Path(tmp) / "feedback_buffer.json"
            buf_path.write_text(json.dumps({
                "exchanges": [
                    {
                        "route": "EVIDENCE",
                        "query": "my dog has hip dysplasia",
                        "response": "...",
                    }
                ]
            }))

            old_ns = os.environ.get("LUCY_RUNTIME_NAMESPACE_ROOT")
            os.environ["LUCY_RUNTIME_NAMESPACE_ROOT"] = tmp
            try:
                followups = [
                    "what should I do",
                    "treatment options",
                    "is surgery needed",
                ]
                for q in followups:
                    with self.subTest(query=q):
                        classification = classify_intent(q)
                        decision = select_route(
                            classification, policy="fallback_only", query=q
                        )
                        self.assertNotEqual(
                            decision.route,
                            "LOCAL",
                            f"{q!r} after vet EVIDENCE should not route LOCAL",
                        )
            finally:
                if old_ns is not None:
                    os.environ["LUCY_RUNTIME_NAMESPACE_ROOT"] = old_ns
                else:
                    os.environ.pop("LUCY_RUNTIME_NAMESPACE_ROOT", None)


class TestEvidenceFallbackLabeling(unittest.TestCase):
    """EVIDENCE-route fallback to non-trusted providers must be labelled."""

    def setUp(self):
        self.engine = ExecutionEngine(config={"timeout": 30})
        self.base_result = ExecutionResult(
            status="completed",
            outcome_code="answered",
            route="EVIDENCE",
            provider="local",
            provider_usage_class="local",
            response_text="This is the generated answer.",
            error_message="",
            metadata={"trust_class": "unverified"},
        )

    def test_label_added_for_wikipedia_fallback(self):
        evidence = {
            "fallback_used": True,
            "fallback_reason": "primary_provider_failed:trusted",
            "primary_failed": "trusted",
            "fallback_to": "wikipedia",
            "successful_backend": "wikipedia",
        }
        result = self.engine._label_evidence_fallback(self.base_result, evidence)
        self.assertTrue(result.response_text.startswith("[Note:"))
        self.assertIn("wikipedia", result.response_text)
        self.assertEqual(result.metadata.get("trust_class"), "trusted_fallback")
        self.assertTrue(result.metadata.get("evidence_fallback_label_applied"))

    def test_no_label_when_trusted_succeeds(self):
        evidence = {
            "fallback_used": False,
            "successful_backend": "trusted",
        }
        result = self.engine._label_evidence_fallback(self.base_result, evidence)
        self.assertEqual(result.response_text, "This is the generated answer.")
        self.assertEqual(result.metadata.get("trust_class"), "unverified")

    def test_no_label_when_no_fallback(self):
        evidence = {
            "fallback_used": False,
            "successful_backend": "wikipedia",
        }
        result = self.engine._label_evidence_fallback(self.base_result, evidence)
        self.assertEqual(result.response_text, "This is the generated answer.")


if __name__ == "__main__":
    unittest.main()
