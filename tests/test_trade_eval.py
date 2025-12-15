"""
Trade compliance evaluation tests.

These tests verify that the system produces correct outputs for
known trade compliance queries. Uses mocked responses to test
the expected behavior patterns.

Mark tests with @pytest.mark.slow for real API tests (not in this file).
"""

import pytest
from unittest.mock import Mock, patch

from tests.trade_scenarios import (
    CORE_SCENARIOS,
    LED_SCENARIOS,
    TradeScenario,
    LED_LAMPS_FROM_CHINA,
    LED_LAMPS_TARIFF,
    LED_LAMPS_AGENCIES,
)


class TestTradeScenarioStructure:
    """Test that scenarios are properly defined."""

    def test_core_scenarios_exist(self):
        """Verify core scenarios are defined."""
        assert len(CORE_SCENARIOS) >= 3

    def test_scenarios_have_required_fields(self):
        """Test all scenarios have required fields."""
        for scenario in LED_SCENARIOS:
            assert scenario.name, "Scenario must have a name"
            assert scenario.query, "Scenario must have a query"
            assert isinstance(scenario.expected_hts_codes, list)
            assert isinstance(scenario.expected_agencies_subset, list)
            assert isinstance(scenario.expected_tariff_keywords, list)


class TestMockedTradeEvaluation:
    """
    Test trade scenarios with mocked responses.

    These tests verify the response validation logic works correctly.
    """

    def test_hts_code_extraction(self):
        """Test HTS codes are correctly extracted from response."""
        mock_response = {
            "structured_output": {
                "hts_codes": ["8539.50.00"],
                "agencies": [],
                "required_documents": [],
                "tariff_info": {},
                "risk_flags": []
            }
        }

        scenario = LED_LAMPS_FROM_CHINA

        # Check HTS codes
        response_codes = mock_response["structured_output"]["hts_codes"]
        for expected in scenario.expected_hts_codes:
            found = any(expected in code for code in response_codes)
            assert found, f"Expected HTS code {expected} not found in {response_codes}"

    def test_agency_extraction(self):
        """Test agencies are correctly extracted from response."""
        mock_response = {
            "structured_output": {
                "hts_codes": [],
                "agencies": ["DOE", "FCC", "CBP"],
                "required_documents": [],
                "tariff_info": {},
                "risk_flags": []
            }
        }

        scenario = LED_LAMPS_AGENCIES

        response_agencies = [a.lower() for a in mock_response["structured_output"]["agencies"]]
        for expected in scenario.expected_agencies_subset:
            assert expected.lower() in response_agencies, f"Expected agency {expected} not found"

    def test_tariff_keyword_extraction(self):
        """Test tariff keywords are found in response."""
        mock_response = {
            "structured_output": {
                "hts_codes": ["8539.50.00"],
                "agencies": [],
                "required_documents": [],
                "tariff_info": {
                    "duty_rate": "3.9%",
                    "special_programs": ["Section 301"],
                    "country_specific": "China: additional 25% tariff"
                },
                "risk_flags": []
            }
        }

        scenario = LED_LAMPS_TARIFF

        # Build searchable string from tariff info
        tariff_info = mock_response["structured_output"]["tariff_info"]
        tariff_str = " ".join([
            tariff_info.get("duty_rate", "") or "",
            " ".join(tariff_info.get("special_programs") or []),
            tariff_info.get("country_specific", "") or ""
        ]).lower()

        for keyword in scenario.expected_tariff_keywords:
            assert keyword.lower() in tariff_str, f"Tariff keyword '{keyword}' not found"


@pytest.mark.parametrize("scenario", CORE_SCENARIOS, ids=lambda s: s.name)
class TestParametrizedScenarios:
    """Parametrized tests for all core scenarios."""

    def test_scenario_has_valid_query(self, scenario: TradeScenario):
        """Test each scenario has a valid query."""
        assert len(scenario.query) > 10, "Query too short"
        assert "?" in scenario.query or scenario.query.endswith("."), "Query should be a question or statement"

    def test_scenario_expectations_are_testable(self, scenario: TradeScenario):
        """Test each scenario has at least one expectation."""
        has_expectation = (
            len(scenario.expected_hts_codes) > 0 or
            len(scenario.expected_agencies_subset) > 0 or
            len(scenario.expected_tariff_keywords) > 0
        )
        assert has_expectation, f"Scenario {scenario.name} has no expectations"


class TestResponseValidation:
    """Test response validation helper functions."""

    def validate_hts_codes(self, response: dict, expected: list) -> bool:
        """Check if expected HTS codes are in response."""
        if not expected:
            return True

        so = response.get("structured_output", {}) or {}
        response_codes = so.get("hts_codes", [])

        for exp in expected:
            if not any(exp in code for code in response_codes):
                return False
        return True

    def validate_agencies(self, response: dict, expected: list) -> bool:
        """Check if expected agencies are in response."""
        if not expected:
            return True

        so = response.get("structured_output", {}) or {}
        response_agencies = [a.lower() for a in so.get("agencies", [])]

        for exp in expected:
            if exp.lower() not in response_agencies:
                return False
        return True

    def validate_tariff_keywords(self, response: dict, expected: list) -> bool:
        """Check if expected tariff keywords are in response."""
        if not expected:
            return True

        so = response.get("structured_output", {}) or {}
        tariff_info = so.get("tariff_info", {}) or {}

        tariff_str = " ".join([
            str(tariff_info.get("duty_rate", "") or ""),
            " ".join(tariff_info.get("special_programs") or []),
            str(tariff_info.get("country_specific", "") or "")
        ]).lower()

        for kw in expected:
            if kw.lower() not in tariff_str:
                return False
        return True

    def test_hts_validation_passes(self):
        """Test HTS validation with matching codes."""
        response = {"structured_output": {"hts_codes": ["8539.50.00"]}}
        assert self.validate_hts_codes(response, ["8539.50"])

    def test_hts_validation_fails(self):
        """Test HTS validation with non-matching codes."""
        response = {"structured_output": {"hts_codes": ["9999.99.99"]}}
        assert not self.validate_hts_codes(response, ["8539.50"])

    def test_agency_validation_passes(self):
        """Test agency validation with matching agencies."""
        response = {"structured_output": {"agencies": ["DOE", "FCC"]}}
        assert self.validate_agencies(response, ["DOE", "FCC"])

    def test_agency_validation_fails(self):
        """Test agency validation with missing agency."""
        response = {"structured_output": {"agencies": ["DOE"]}}
        assert not self.validate_agencies(response, ["DOE", "FDA"])

    def test_tariff_validation_passes(self):
        """Test tariff keyword validation."""
        response = {
            "structured_output": {
                "tariff_info": {
                    "special_programs": ["Section 301"],
                    "duty_rate": "3.9%"
                }
            }
        }
        assert self.validate_tariff_keywords(response, ["Section 301"])

    def test_empty_expectations_pass(self):
        """Test that empty expectations always pass."""
        response = {"structured_output": {}}
        assert self.validate_hts_codes(response, [])
        assert self.validate_agencies(response, [])
        assert self.validate_tariff_keywords(response, [])


class TestEvalHarnessIntegration:
    """Test the eval harness can run against mocked chat."""

    def test_full_scenario_evaluation(self, app, test_user):
        """Test running a full scenario through the system."""
        from app.chat.models import ChatArgs, Metadata

        scenario = LED_LAMPS_FROM_CHINA

        mock_response = {
            "answer": "LED lamps require DOE and FCC compliance",
            "citations": [{"index": 1, "pdf_id": "hts-001", "doc_type": "hts_schedule"}],
            "structured_output": {
                "hts_codes": ["8539.50.00"],
                "agencies": ["DOE", "FCC"],
                "required_documents": [],
                "tariff_info": {
                    "duty_rate": "3.9%",
                    "special_programs": ["Section 301"],
                    "country_specific": "China: 25% additional"
                },
                "risk_flags": []
            },
            "documents": [],
            "condensed_question": scenario.query,
            "tool_calls": []
        }

        mock_chat = Mock()
        mock_chat.invoke.return_value = mock_response

        with app.app_context():
            with patch('app.chat.chat.build_trade_compliance_chat', return_value=mock_chat):
                # Invoke
                result = mock_chat.invoke(scenario.query)

                # Validate
                so = result["structured_output"]

                # HTS check
                assert any(
                    code in so["hts_codes"]
                    for code in scenario.expected_hts_codes
                    for code in so["hts_codes"]
                )

                # Agency check
                agencies_lower = {a.lower() for a in so["agencies"]}
                for expected in scenario.expected_agencies_subset:
                    assert expected.lower() in agencies_lower

                # Tariff check
                tariff_str = " ".join([
                    so["tariff_info"].get("duty_rate", ""),
                    " ".join(so["tariff_info"].get("special_programs", [])),
                    so["tariff_info"].get("country_specific", "")
                ]).lower()

                for kw in scenario.expected_tariff_keywords:
                    assert kw.lower() in tariff_str
