"""
Output schemas for structured responses.

Provides Pydantic models for:
- Source citations
- Structured answers with confidence levels
- Trade compliance output with HTS codes, agencies, documents

All schemas include schema_version for backwards compatibility.
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Union


# ============================================================================
# Schema Versioning
# ============================================================================

CURRENT_SCHEMA_VERSION = "4.0"  # v4.0: Entry slices, Annex II, variant/slice_type
SUPPORTED_VERSIONS = ["1.0", "2.0", "4.0"]


def validate_schema_version(output: dict) -> bool:
    """Check if output schema version is supported."""
    version = output.get("schema_version", "1.0")
    return version in SUPPORTED_VERSIONS


# ============================================================================
# Citation Models
# ============================================================================

class SourceCitation(BaseModel):
    """A citation to a source document."""
    pdf_id: str = Field(description="ID of the source document")
    doc_type: Optional[str] = Field(default=None, description="Type of document (e.g., hts_schedule, regulation)")
    page: Optional[int] = Field(default=None, description="Page number if available")
    snippet: str = Field(description="Relevant snippet from the source")


# ============================================================================
# Structured Answer Models
# ============================================================================

class StructuredAnswer(BaseModel):
    """Structured response with answer and metadata."""
    schema_version: str = Field(default=CURRENT_SCHEMA_VERSION, description="Schema version for compatibility")
    answer: str = Field(description="The main answer text for the user")
    citations: List[SourceCitation] = Field(default=[], description="Source citations for the answer")
    confidence: str = Field(default="medium", description="Confidence level: high, medium, low")
    follow_up_questions: List[str] = Field(default=[], description="Suggested follow-up questions")


# ============================================================================
# Trade Compliance Models
# ============================================================================

class RequiredDocument(BaseModel):
    """A required document or certificate for compliance."""
    agency: str = Field(description="Regulatory agency requiring the document")
    document_name: str = Field(description="Name of the required document")
    description: Optional[str] = Field(default=None, description="Description of the document's purpose")


class TariffInfo(BaseModel):
    """Tariff and duty rate information."""
    duty_rate: Optional[str] = Field(default=None, description="Base duty rate (e.g., '3.9%')")
    special_programs: List[str] = Field(default=[], description="Special tariff programs (e.g., 'Section 301')")
    country_specific: Optional[str] = Field(default=None, description="Country-specific tariff notes")


class TradeComplianceOutput(BaseModel):
    """Structured output specifically for trade compliance queries."""
    schema_version: str = Field(default=CURRENT_SCHEMA_VERSION, description="Schema version for compatibility")
    answer: str = Field(description="The main answer text")
    hts_codes: List[str] = Field(default=[], description="Relevant HTS codes mentioned")
    agencies: List[str] = Field(default=[], description="Regulatory agencies involved")
    required_documents: List[RequiredDocument] = Field(default=[], description="Required documents/certificates")
    tariff_info: Optional[TariffInfo] = Field(default=None, description="Tariff rates and special programs")
    risk_flags: List[str] = Field(default=[], description="Potential compliance risks or warnings")
    citations: List[SourceCitation] = Field(default=[], description="Source citations")


# ============================================================================
# Plan Step Model (for agentic planning)
# ============================================================================

class PlanStep(BaseModel):
    """A single step in an agent's execution plan."""
    step_number: int = Field(description="Step number in sequence")
    action: str = Field(description="Tool name or 'synthesize' for final step")
    description: str = Field(description="What this step accomplishes")
    inputs: dict = Field(default={}, description="Parameters for the tool")


class AgentPlan(BaseModel):
    """A complete execution plan for an agent."""
    schema_version: str = Field(default=CURRENT_SCHEMA_VERSION, description="Schema version for compatibility")
    steps: List[PlanStep] = Field(default=[], description="Ordered list of plan steps")
    reasoning: Optional[str] = Field(default=None, description="Agent's reasoning for the plan")


# ============================================================================
# Stacking Output Models
# ============================================================================

# ----------------------------------------------------------------------------
# Phase 6: Material Info for Content-Value-Based Duties
# ----------------------------------------------------------------------------

class MaterialInfo(BaseModel):
    """
    Material composition with both percentage and value.

    Phase 6 Update (Dec 2025):
    - CBP now requires duty on material content VALUE, not percentage
    - We store both percentage and value to support either calculation
    - value_source tracks where the value came from for audit purposes
    """
    percentage: float = Field(description="Material percentage (0.05 = 5%)")
    value: Optional[float] = Field(default=None, description="Dollar value of material content")
    mass_kg: Optional[float] = Field(default=None, description="Mass in kg (for CBP reporting)")
    value_source: str = Field(
        default="estimated",
        description="Source of value: 'user_provided', 'estimated_from_percentage', 'fallback'"
    )


class FilingLine(BaseModel):
    """
    A single filing line in the CBP filing sequence.

    Phase 6 Update (Dec 2025):
    - Added line_value for content-value-based duties
    - Added line_quantity and material_quantity_kg for CBP reporting
    - Added split_type to identify line splitting

    v4.0 Update (Dec 2025):
    - Added variant for IEEPA Reciprocal variants (taxable, annex_ii_exempt, metal_exempt)
    """
    sequence: int = Field(description="Order in the filing (1, 2, 3...)")
    chapter_99_code: str = Field(description="Chapter 99 code (e.g., '9903.88.03')")
    program: str = Field(description="Program name (e.g., 'Section 301', 'IEEPA Fentanyl')")
    program_id: str = Field(description="Program ID for lookups")
    action: str = Field(description="Action taken: 'apply', 'claim', 'disclaim', 'paid', 'exempt'")
    # v4.0: Variant for programs with multiple outcomes
    variant: Optional[str] = Field(default=None, description="Variant: 'taxable', 'annex_ii_exempt', 'metal_exempt', 'us_content_exempt'")
    applies_to: str = Field(default="full", description="'full' or 'partial'")
    duty_rate: Optional[float] = Field(default=None, description="Duty rate as decimal (0.25 = 25%)")
    material: Optional[str] = Field(default=None, description="Material for 232 programs")
    material_percent: Optional[float] = Field(default=None, description="Material percentage if partial")
    # Phase 6: Content-value-based duty fields
    line_value: Optional[float] = Field(default=None, description="Value for THIS specific line (for split lines)")
    line_quantity: Optional[float] = Field(default=None, description="Product quantity (0 for material content lines)")
    material_quantity_kg: Optional[float] = Field(default=None, description="kg of material for 9903 line")
    split_type: Optional[str] = Field(default=None, description="'non_material_content' or 'material_content' for split lines")


class Decision(BaseModel):
    """A single decision in the stacking process with audit trail."""
    step: str = Field(description="Step name (e.g., 'check_301_inclusion')")
    program_id: str = Field(description="Program being evaluated")
    decision: str = Field(description="Decision made (e.g., 'included', 'excluded', 'claim')")
    reason: str = Field(description="Explanation for the decision")
    source_doc: Optional[str] = Field(default=None, description="Government document source")
    source_page: Optional[int] = Field(default=None, description="Page number in source")
    source_snippet: Optional[str] = Field(default=None, description="Relevant text from source")


class UserInput(BaseModel):
    """User input collected during stacking."""
    question: str = Field(description="Question asked")
    answer: str = Field(description="User's response")
    timestamp: Optional[str] = Field(default=None, description="When answered")


class DutyBreakdown(BaseModel):
    """
    Breakdown of duty calculation for a single program.

    Phase 6 Update (Dec 2025):
    - Added base_value to show what value the duty was calculated on
    - Added value_source to track whether content value was user-provided or estimated
    """
    program_id: str = Field(description="Program ID")
    chapter_99_code: str = Field(description="Chapter 99 code")
    action: str = Field(description="Action taken")
    duty_rate: float = Field(description="Duty rate applied")
    duty_amount: float = Field(description="Calculated duty amount in USD")
    calculation: str = Field(description="How calculated (e.g., 'additive on product_value')")
    material: Optional[str] = Field(default=None, description="Material if 232")
    material_percent: Optional[float] = Field(default=None, description="Material percentage if partial")
    # Phase 6: Content-value-based duty fields
    base_value: Optional[float] = Field(default=None, description="Value duty was calculated on")
    value_source: Optional[str] = Field(default=None, description="'user_provided', 'estimated', 'fallback'")


# ============================================================================
# v4.0: Entry Slice Models
# ============================================================================

class FilingEntry(BaseModel):
    """
    v4.0: One ACE entry line - base HTS + stack of Chapter 99 codes.

    When a product has 232 metal content, it must be split into multiple
    ACE entries:
    - non_metal: Non-metal portion with disclaims for all 232 programs
    - copper_slice: Copper content with claim for 232 copper
    - steel_slice: Steel content with claim for 232 steel
    - aluminum_slice: Aluminum content with claim for 232 aluminum

    Each entry has the same base HTS but different values and 99-code stacks.
    """
    entry_id: str = Field(description="Entry identifier: 'full_product', 'non_metal', 'copper_slice', etc.")
    slice_type: str = Field(description="Slice type: 'full', 'non_metal', 'copper_slice', 'steel_slice', 'aluminum_slice'")
    base_hts_code: str = Field(description="Base HTS code (e.g., '8544.42.9090')")
    country_of_origin: str = Field(description="Country of origin")
    line_value: float = Field(description="Value for this slice in USD")
    line_quantity: Optional[float] = Field(default=None, description="Quantity for this slice")
    materials: Dict = Field(default={}, description="Materials in this slice")
    stack: List[FilingLine] = Field(default=[], description="Chapter 99 codes for this entry")


class UnstackingInfo(BaseModel):
    """
    v4.0: IEEPA unstacking audit trail.

    Tracks how remaining_value is calculated for IEEPA Reciprocal:
    - Start with full product value
    - Subtract 232 content values (copper, steel, aluminum)
    - IEEPA Reciprocal applies only to remaining_value

    This implements CBP rule: "Content subject to 232 is NOT subject to Reciprocal IEEPA"
    """
    initial_value: float = Field(description="Starting product value")
    content_deductions: Dict[str, float] = Field(default={}, description="232 content deductions: {'copper': 3000, 'steel': 1000}")
    remaining_value: float = Field(description="Value after 232 deductions (IEEPA Reciprocal base)")
    note: Optional[str] = Field(default=None, description="Explanation of unstacking")


class StackingOutput(BaseModel):
    """
    Complete output from tariff stacking calculation.

    Phase 6 Update (Dec 2025):
    - materials field now supports MaterialInfo with value, mass_kg, value_source
    - Filing lines may include split lines for 232 content-value duties
    - flags includes warnings like 'fallback_applied_for_copper' if content value unknown

    v4.0 Update (Dec 2025):
    - Added entries: List[FilingEntry] for ACE entry slices
    - Added unstacking: UnstackingInfo for IEEPA unstacking audit trail
    - filing_lines is now a flattened view of all entries.stack (backwards compatible)
    """
    schema_version: str = Field(default=CURRENT_SCHEMA_VERSION, description="Schema version")

    # Input echoed back
    hts_code: str = Field(description="Input HTS code")
    country_of_origin: str = Field(description="Country of origin")
    product_description: str = Field(description="Product description")
    product_value: float = Field(description="Declared product value in USD")
    # Phase 6: Materials can be simple dict or Dict[str, MaterialInfo]
    # Simple dict: {"copper": 0.05, "steel": 0.20}
    # MaterialInfo dict: {"copper": {"percentage": 0.05, "value": 500.00, ...}}
    materials: Dict = Field(default={}, description="Material composition")
    import_date: Optional[str] = Field(default=None, description="Import date (YYYY-MM-DD)")

    # v4.0: ACE Entry Slices (primary output)
    entries: List[FilingEntry] = Field(default=[], description="ACE entry slices with Chapter 99 stacks")

    # Main output: Filing lines (flattened view for backwards compatibility)
    filing_lines: List[FilingLine] = Field(default=[], description="CBP filing lines in order (flattened from entries)")

    # Calculations
    base_duty_rate: Optional[float] = Field(default=None, description="Base HTS duty rate")
    total_duty_percent: float = Field(default=0.0, description="Total duty as percentage of value")
    total_duty_amount: float = Field(default=0.0, description="Total duty in USD")
    duty_breakdown: List[DutyBreakdown] = Field(default=[], description="Per-program duty breakdown")

    # v4.0: IEEPA Unstacking audit trail
    unstacking: Optional[UnstackingInfo] = Field(default=None, description="IEEPA unstacking info")

    # Audit trail
    decisions: List[Decision] = Field(default=[], description="Decision log with reasons")
    user_inputs: List[UserInput] = Field(default=[], description="User inputs collected")
    citations: List[SourceCitation] = Field(default=[], description="Source document citations")

    # Explanation
    explanation: Optional[str] = Field(default=None, description="Plain English explanation")

    # QA
    confidence: str = Field(default="medium", description="Confidence: high, medium, low")
    flags: List[str] = Field(default=[], description="Warnings like 'fallback_applied_for_copper'")
