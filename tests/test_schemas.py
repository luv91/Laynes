"""
Unit tests for output schemas.

Tests:
- Schema validation
- Schema versioning
- Pydantic model behavior
- Default values
"""

import pytest
from app.chat.output_schemas import (
    SourceCitation,
    StructuredAnswer,
    TradeComplianceOutput,
    RequiredDocument,
    TariffInfo,
    PlanStep,
    AgentPlan,
    CURRENT_SCHEMA_VERSION,
    SUPPORTED_VERSIONS,
    validate_schema_version,
)


class TestSchemaVersioning:
    """Test schema versioning functionality."""

    def test_current_version_is_supported(self):
        """Test that current version is in supported versions."""
        assert CURRENT_SCHEMA_VERSION in SUPPORTED_VERSIONS

    def test_validate_schema_version_valid(self):
        """Test validating a supported schema version."""
        output = {"schema_version": "1.0", "answer": "test"}
        assert validate_schema_version(output) is True

    def test_validate_schema_version_missing(self):
        """Test validation when schema_version is missing defaults to 1.0."""
        output = {"answer": "test"}
        assert validate_schema_version(output) is True

    def test_validate_schema_version_invalid(self):
        """Test validation with unsupported version."""
        output = {"schema_version": "99.0", "answer": "test"}
        assert validate_schema_version(output) is False


class TestSourceCitation:
    """Test SourceCitation model."""

    def test_create_with_required_fields(self):
        """Test creating citation with required fields only."""
        citation = SourceCitation(pdf_id="doc-001", snippet="Some text...")
        assert citation.pdf_id == "doc-001"
        assert citation.snippet == "Some text..."
        assert citation.doc_type is None
        assert citation.page is None

    def test_create_with_all_fields(self):
        """Test creating citation with all fields."""
        citation = SourceCitation(
            pdf_id="hts-schedule-001",
            doc_type="hts_schedule",
            page=42,
            snippet="8539.50.00 - LED lamps"
        )
        assert citation.pdf_id == "hts-schedule-001"
        assert citation.doc_type == "hts_schedule"
        assert citation.page == 42
        assert citation.snippet == "8539.50.00 - LED lamps"

    def test_model_to_dict(self):
        """Test converting model to dict."""
        citation = SourceCitation(pdf_id="doc-001", snippet="text")
        d = citation.model_dump()
        assert "pdf_id" in d
        assert "snippet" in d


class TestStructuredAnswer:
    """Test StructuredAnswer model."""

    def test_default_values(self):
        """Test default values are set correctly."""
        answer = StructuredAnswer(answer="The answer is 42.")
        assert answer.answer == "The answer is 42."
        assert answer.schema_version == CURRENT_SCHEMA_VERSION
        assert answer.citations == []
        assert answer.confidence == "medium"
        assert answer.follow_up_questions == []

    def test_with_citations(self):
        """Test creating answer with citations."""
        citation = SourceCitation(pdf_id="doc-001", snippet="text")
        answer = StructuredAnswer(
            answer="Based on the document...",
            citations=[citation],
            confidence="high",
            follow_up_questions=["What about X?", "How does Y work?"]
        )
        assert len(answer.citations) == 1
        assert answer.confidence == "high"
        assert len(answer.follow_up_questions) == 2


class TestRequiredDocument:
    """Test RequiredDocument model."""

    def test_create_document(self):
        """Test creating a required document."""
        doc = RequiredDocument(
            agency="FDA",
            document_name="Certificate of Compliance",
            description="Required for food imports"
        )
        assert doc.agency == "FDA"
        assert doc.document_name == "Certificate of Compliance"
        assert doc.description == "Required for food imports"

    def test_optional_description(self):
        """Test description is optional."""
        doc = RequiredDocument(agency="CBP", document_name="Entry Form")
        assert doc.description is None


class TestTariffInfo:
    """Test TariffInfo model."""

    def test_default_values(self):
        """Test default values."""
        tariff = TariffInfo()
        assert tariff.duty_rate is None
        assert tariff.special_programs == []
        assert tariff.country_specific is None

    def test_with_values(self):
        """Test with all values set."""
        tariff = TariffInfo(
            duty_rate="3.9%",
            special_programs=["Section 301", "AD/CVD"],
            country_specific="Additional 25% tariff from China"
        )
        assert tariff.duty_rate == "3.9%"
        assert "Section 301" in tariff.special_programs
        assert "China" in tariff.country_specific


class TestTradeComplianceOutput:
    """Test TradeComplianceOutput model."""

    def test_default_values(self):
        """Test default values for trade compliance output."""
        output = TradeComplianceOutput(answer="Import LED lamps...")
        assert output.answer == "Import LED lamps..."
        assert output.schema_version == CURRENT_SCHEMA_VERSION
        assert output.hts_codes == []
        assert output.agencies == []
        assert output.required_documents == []
        assert output.tariff_info is None
        assert output.risk_flags == []
        assert output.citations == []

    def test_full_trade_compliance_output(self):
        """Test creating full trade compliance output."""
        output = TradeComplianceOutput(
            answer="LED lamps from China require the following...",
            hts_codes=["8539.50.00"],
            agencies=["DOE", "FCC", "CBP"],
            required_documents=[
                RequiredDocument(agency="DOE", document_name="Energy Certificate")
            ],
            tariff_info=TariffInfo(duty_rate="3.9%", special_programs=["Section 301"]),
            risk_flags=["Additional tariffs may apply from China"],
            citations=[SourceCitation(pdf_id="hts-001", snippet="8539.50...")]
        )

        assert "8539.50.00" in output.hts_codes
        assert "DOE" in output.agencies
        assert len(output.required_documents) == 1
        assert output.tariff_info.duty_rate == "3.9%"
        assert len(output.risk_flags) == 1
        assert len(output.citations) == 1


class TestPlanStep:
    """Test PlanStep model."""

    def test_create_plan_step(self):
        """Test creating a plan step."""
        step = PlanStep(
            step_number=1,
            action="lookup_hts_code",
            description="Find HTS code for LED lamps",
            inputs={"product_description": "LED lamps"}
        )
        assert step.step_number == 1
        assert step.action == "lookup_hts_code"
        assert step.description == "Find HTS code for LED lamps"
        assert step.inputs["product_description"] == "LED lamps"

    def test_default_inputs(self):
        """Test default empty inputs."""
        step = PlanStep(
            step_number=2,
            action="synthesize",
            description="Combine findings"
        )
        assert step.inputs == {}


class TestAgentPlan:
    """Test AgentPlan model."""

    def test_create_plan(self):
        """Test creating an agent plan."""
        steps = [
            PlanStep(step_number=1, action="lookup_hts_code", description="Find HTS"),
            PlanStep(step_number=2, action="check_tariffs", description="Check tariffs"),
            PlanStep(step_number=3, action="synthesize", description="Combine")
        ]
        plan = AgentPlan(
            steps=steps,
            reasoning="User wants to import LED lamps, need HTS and tariffs"
        )

        assert plan.schema_version == CURRENT_SCHEMA_VERSION
        assert len(plan.steps) == 3
        assert plan.reasoning is not None

    def test_empty_plan(self):
        """Test creating empty plan."""
        plan = AgentPlan()
        assert plan.steps == []
        assert plan.reasoning is None
