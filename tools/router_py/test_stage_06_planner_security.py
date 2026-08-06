#!/usr/bin/env python3
"""STAGE_06 planner URL-security tests."""

from __future__ import annotations

import pytest

from unittest.mock import patch

from router_py.planner import cli as planner_cli
from router_py.planner_validator import PlannerValidationResult, PlannerValidator


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://localhost/admin",
        "https://localhost/path/to/resource",
        "https://127.0.0.1/secret",
        "https://192.168.1.1/path/to/resource",
        "https://10.0.0.1/api/v1/data",
        "https://172.16.0.1/config",
        "https://[::1]/admin",
        "https://169.254.169.254/latest/meta-data/",
        "file:///etc/passwd",
    ],
)
def test_s06_uw_002_private_network_url_rejected(bad_url: str):
    """S06-UW-002: Planner URLs pointing to private networks are rejected."""
    validator = PlannerValidator()
    plan = {"queries": ["query one"], "urls": [bad_url]}
    result = validator.validate(plan)
    assert isinstance(result, PlannerValidationResult)
    assert result.valid is False
    assert result.error_code == "invalid_url"


def test_s06_uw_003_malformed_plan_json_produces_zero_http_requests():
    """S06-UW-003: Malformed planner JSON exits before any HTTP request."""
    with patch("urllib.request.urlopen") as mock_urlopen:
        exit_code = planner_cli.run_cli(
            ["--plan-json", "not valid json {", "--question", "what is 2+2"]
        )

    assert exit_code == 2
    mock_urlopen.assert_not_called()
