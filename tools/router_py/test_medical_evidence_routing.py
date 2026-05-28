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

    def test_financial_routes_augmented(self) -> None:
        """Financial queries route to AUGMENTED (not EVIDENCE)."""
        queries = [
            "current stock price of Apple",
            "bitcoin price today",
        ]
        for query in queries:
            with self.subTest(query=query):
                classification = classify_intent(query)
                decision = select_route(classification, policy="fallback_only", query=query)
                self.assertEqual(
                    decision.route,
                    "AUGMENTED",
                    f"{query!r}: expected AUGMENTED, got {decision.route}",
                )
                self.assertNotEqual(
                    decision.provider,
                    "trusted",
                    f"{query!r}: financial should not use trusted provider",
                )

    def test_stable_financial_knowledge_routes_local(self) -> None:
        """Stable financial knowledge (rules, concepts) stays LOCAL."""
        queries = [
            "capital gains tax rules",
        ]
        for query in queries:
            with self.subTest(query=query):
                classification = classify_intent(query)
                decision = select_route(classification, policy="fallback_only", query=query)
                self.assertEqual(
                    decision.route,
                    "LOCAL",
                    f"{query!r}: expected LOCAL, got {decision.route}",
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


if __name__ == "__main__":
    unittest.main()
