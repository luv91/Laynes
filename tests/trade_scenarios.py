"""
Trade compliance evaluation scenarios.

Defines expected behavior for common trade compliance queries.
Used by test_trade_eval.py to verify system correctness.
"""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class TradeScenario:
    """
    A trade compliance scenario for evaluation.

    Attributes:
        name: Unique identifier for the scenario
        query: The user's question
        expected_hts_codes: HTS codes that should appear in the response
        expected_agencies_subset: Agencies that should be mentioned
        expected_tariff_keywords: Keywords that should appear in tariff info
        expected_doc_types: Document types that should be in citations
        description: Human-readable description of the scenario
    """
    name: str
    query: str
    expected_hts_codes: List[str]
    expected_agencies_subset: List[str]
    expected_tariff_keywords: List[str]
    expected_doc_types: Optional[List[str]] = None
    description: Optional[str] = None


# ============================================================================
# LED Lamps Scenarios
# ============================================================================

LED_LAMPS_BASIC = TradeScenario(
    name="LED_lamps_basic",
    query="What is the HTS code for LED lamps?",
    expected_hts_codes=["8539.50"],
    expected_agencies_subset=[],
    expected_tariff_keywords=[],
    expected_doc_types=["hts_schedule"],
    description="Basic HTS code lookup for LED lamps"
)

LED_LAMPS_FROM_CHINA = TradeScenario(
    name="LED_lamps_from_China",
    query="I want to import LED lamps from China. What do I need?",
    expected_hts_codes=["8539.50"],
    expected_agencies_subset=["DOE", "FCC"],
    expected_tariff_keywords=["Section 301", "25%"],
    expected_doc_types=["hts_schedule", "tariff_notice", "agency_regulation"],
    description="Comprehensive import requirements for LED lamps from China"
)

LED_LAMPS_TARIFF = TradeScenario(
    name="LED_lamps_tariff",
    query="What tariffs apply to LED lamps from China?",
    expected_hts_codes=["8539.50"],
    expected_agencies_subset=[],
    expected_tariff_keywords=["Section 301", "3.9%"],
    expected_doc_types=["tariff_notice"],
    description="Tariff rates for LED lamps from China"
)

LED_LAMPS_AGENCIES = TradeScenario(
    name="LED_lamps_agencies",
    query="What agencies regulate LED lamps?",
    expected_hts_codes=[],
    expected_agencies_subset=["DOE", "FCC"],
    expected_tariff_keywords=[],
    expected_doc_types=["agency_regulation"],
    description="Regulatory agencies for LED lamps"
)

LED_LAMPS_DOCUMENTS = TradeScenario(
    name="LED_lamps_documents",
    query="What documents do I need to import LED lamps from China?",
    expected_hts_codes=[],
    expected_agencies_subset=["DOE", "FCC"],
    expected_tariff_keywords=[],
    expected_doc_types=["agency_regulation"],
    description="Required documentation for LED lamp imports"
)


# ============================================================================
# Additional Product Scenarios (for future expansion)
# ============================================================================

# Electronics general
ELECTRONICS_GENERAL = TradeScenario(
    name="electronics_general",
    query="What are the import requirements for electronic devices?",
    expected_hts_codes=[],
    expected_agencies_subset=["FCC"],
    expected_tariff_keywords=[],
    expected_doc_types=["agency_regulation"],
    description="General electronics import requirements"
)


# ============================================================================
# Scenario Collections
# ============================================================================

# All LED lamp scenarios
LED_SCENARIOS = [
    LED_LAMPS_BASIC,
    LED_LAMPS_FROM_CHINA,
    LED_LAMPS_TARIFF,
    LED_LAMPS_AGENCIES,
    LED_LAMPS_DOCUMENTS,
]

# Core scenarios (most important to pass)
CORE_SCENARIOS = [
    LED_LAMPS_FROM_CHINA,
    LED_LAMPS_TARIFF,
    LED_LAMPS_AGENCIES,
]

# All scenarios
ALL_SCENARIOS = LED_SCENARIOS + [ELECTRONICS_GENERAL]


# ============================================================================
# Helper functions
# ============================================================================

def get_scenario_by_name(name: str) -> Optional[TradeScenario]:
    """Find a scenario by name."""
    for scenario in ALL_SCENARIOS:
        if scenario.name == name:
            return scenario
    return None


def get_scenarios_by_product(product: str) -> List[TradeScenario]:
    """Get all scenarios related to a product."""
    product_lower = product.lower()
    return [s for s in ALL_SCENARIOS if product_lower in s.query.lower()]
