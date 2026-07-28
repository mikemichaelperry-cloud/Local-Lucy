#!/usr/bin/env python3
"""Regression tests for the MedlinePlus fabricated-path failure.

A previous bug caused prompt words like "internal consistency exercise" to be
reassembled into fabricated MedlinePlus URLs and fetched. These tests verify
that the validation layers reject such URLs regardless of provenance.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.deterministic]


FABRICATED_MEDLINEPLUS_URLS = [
    "https://medlineplus.gov/internal.html",
    "https://medlineplus.gov/consistency.html",
    "https://medlineplus.gov/exercise.html",
    "https://medlineplus.gov/tools.html",
    "https://medlineplus.gov/network.html",
    "https://medlineplus.gov/memory.html",
]


class TestValidateFetchUrlRejectsInventedUrls:
    """url_provenance.validate_fetch_url must reject invented-keyword URLs."""

    def test_medlineplus_fabricated_paths_rejected(self):
        from router_py.url_provenance import URLProvenance, validate_fetch_url

        for url in FABRICATED_MEDLINEPLUS_URLS:
            result = validate_fetch_url(url, URLProvenance.INVENTED_KEYWORD)
            assert result is None, f"Expected rejection for {url}"

    def test_medlineplus_real_article_allowed(self):
        from router_py.url_provenance import URLProvenance, validate_fetch_url

        result = validate_fetch_url(
            "https://medlineplus.gov/ency/article/000033.htm",
            URLProvenance.TRUSTED_LINK,
        )
        assert result is not None
        assert result.url == "https://medlineplus.gov/ency/article/000033.htm"

    def test_non_string_input_rejected(self):
        from router_py.url_provenance import URLProvenance, validate_fetch_url

        result = validate_fetch_url(
            {"url": "https://medlineplus.gov/internal.html"},
            URLProvenance.INVENTED_KEYWORD,
        )
        assert result is None


class TestPlannerValidatorRejectsFabricatedUrls:
    """PlannerValidator must reject planner output containing fabricated URLs."""

    def test_plan_with_fabricated_medlineplus_urls_invalid(self):
        from router_py.planner_validator import PlannerValidator

        validator = PlannerValidator()
        plan = {
            "queries": ["internal consistency exercise"],
            "urls": ["https://medlineplus.gov/internal.html"],
        }
        result = validator.validate(plan)
        assert not result.valid
        assert result.error_code == "invalid_url"

    def test_prose_string_rejected(self):
        from router_py.planner_validator import PlannerValidator

        validator = PlannerValidator()
        result = validator.validate("This is an internal consistency exercise. Do not use tools.")
        assert not result.valid

    def test_partial_json_rejected(self):
        from router_py.planner_validator import PlannerValidator

        validator = PlannerValidator()
        result = validator.validate('{"queries": ["internal consistency",')
        assert not result.valid
        assert result.error_code == "malformed_json"

    def test_isolated_word_queries_rejected(self):
        from router_py.planner_validator import PlannerValidator

        validator = PlannerValidator()
        plan = {"queries": ["internal"], "urls": []}
        result = validator.validate(plan)
        assert not result.valid
        assert result.error_code == "invalid_query"

    def test_valid_plan_accepted(self):
        from router_py.planner_validator import PlannerValidator

        validator = PlannerValidator()
        plan = {
            "queries": ["internal consistency exercise SQLite memory"],
            "urls": [],
        }
        result = validator.validate(plan)
        assert result.valid
