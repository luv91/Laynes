"""
Unit tests for the planning node in agentic RAG.

Tests:
- Plan generation for various queries
- JSON parsing and fallback behavior
- Plan structure validation
"""

import pytest
import json
from unittest.mock import Mock, patch, MagicMock
from langchain_core.messages import AIMessage

from app.chat.graphs.agentic_rag import (
    plan_node,
    AgentState,
)
from app.chat.output_schemas import AgentPlan, PlanStep


class TestPlanNode:
    """Test the plan_node function."""

    @pytest.fixture
    def mock_llm_response_valid(self):
        """Create a valid JSON response from LLM."""
        plan = {
            "schema_version": "1.0",
            "reasoning": "User wants to import LED lamps. Need HTS code and tariff info.",
            "steps": [
                {
                    "step_number": 1,
                    "action": "lookup_hts_code",
                    "description": "Find HTS code for LED lamps",
                    "inputs": {"product_description": "LED lamps"}
                },
                {
                    "step_number": 2,
                    "action": "check_tariffs",
                    "description": "Check tariff rates from China",
                    "inputs": {"hts_code": "<from step 1>", "country_of_origin": "China"}
                },
                {
                    "step_number": 3,
                    "action": "synthesize",
                    "description": "Combine findings into answer",
                    "inputs": {}
                }
            ]
        }
        return AIMessage(content=json.dumps(plan))

    @pytest.fixture
    def mock_llm_response_invalid(self):
        """Create an invalid (non-JSON) response from LLM."""
        return AIMessage(content="I'll help you find the HTS code for LED lamps...")

    def test_plan_node_valid_response(self, mock_llm_response_valid):
        """Test plan_node with valid JSON response."""
        state = {
            "question": "What is the HTS code for LED lamps from China?"
        }

        mock_llm = Mock()
        mock_llm.invoke.return_value = mock_llm_response_valid

        with patch('app.chat.graphs.agentic_rag.ChatOpenAI', return_value=mock_llm):
            result = plan_node(state)

        assert "plan" in result
        assert "plan_reasoning" in result
        assert "current_step" in result

        assert len(result["plan"]) == 3
        assert result["plan"][0]["action"] == "lookup_hts_code"
        assert result["current_step"] == 0

    def test_plan_node_invalid_json_fallback(self, mock_llm_response_invalid):
        """Test plan_node falls back to default plan on JSON error."""
        state = {
            "question": "What is the HTS code for LED lamps?"
        }

        mock_llm = Mock()
        mock_llm.invoke.return_value = mock_llm_response_invalid

        with patch('app.chat.graphs.agentic_rag.ChatOpenAI', return_value=mock_llm):
            result = plan_node(state)

        # Should have fallback plan
        assert len(result["plan"]) == 1
        assert result["plan"][0]["action"] == "search_documents"
        assert "Fallback" in result["plan_reasoning"]

    def test_plan_node_sets_current_step_to_zero(self, mock_llm_response_valid):
        """Test plan_node always starts at step 0."""
        state = {
            "question": "Import requirements"
        }

        mock_llm = Mock()
        mock_llm.invoke.return_value = mock_llm_response_valid

        with patch('app.chat.graphs.agentic_rag.ChatOpenAI', return_value=mock_llm):
            result = plan_node(state)

        assert result["current_step"] == 0


class TestPlanStructure:
    """Test plan structure validation."""

    def test_plan_step_structure(self):
        """Test PlanStep has correct structure."""
        step = PlanStep(
            step_number=1,
            action="search_documents",
            description="Search for info",
            inputs={"query": "test"}
        )

        assert step.step_number == 1
        assert step.action == "search_documents"
        assert step.description == "Search for info"
        assert step.inputs == {"query": "test"}

    def test_plan_step_default_inputs(self):
        """Test PlanStep default inputs is empty dict."""
        step = PlanStep(
            step_number=1,
            action="synthesize",
            description="Final synthesis"
        )

        assert step.inputs == {}

    def test_agent_plan_structure(self):
        """Test AgentPlan has correct structure."""
        steps = [
            PlanStep(step_number=1, action="search_documents", description="Search"),
            PlanStep(step_number=2, action="synthesize", description="Synthesize")
        ]
        plan = AgentPlan(
            steps=steps,
            reasoning="Simple search and answer"
        )

        assert len(plan.steps) == 2
        assert plan.reasoning == "Simple search and answer"
        assert plan.schema_version == "1.0"


class TestPlanIntegrationWithAgent:
    """Test plan integration with agent node."""

    def test_agent_uses_plan_context(self):
        """Test that agent node receives and uses plan context."""
        from app.chat.graphs.agentic_rag import agent_node

        state = {
            "question": "Import LED lamps from China",
            "messages": [],
            "iteration": 0,
            "plan": [
                {"step_number": 1, "action": "lookup_hts_code", "description": "Find HTS code", "inputs": {}},
                {"step_number": 2, "action": "check_tariffs", "description": "Check tariffs", "inputs": {}}
            ],
            "current_step": 0,
            "tool_outputs": []
        }

        mock_llm = Mock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.invoke.return_value = AIMessage(content="Let me look up the HTS code...")

        with patch('app.chat.graphs.agentic_rag.ChatOpenAI', return_value=mock_llm):
            result = agent_node(state)

        # Agent should return updated state
        assert "messages" in result
        assert "iteration" in result
        # Current step should advance
        assert result["current_step"] == 1

    def test_agent_advances_step_correctly(self):
        """Test that agent advances to next step."""
        from app.chat.graphs.agentic_rag import agent_node

        # State at step 1 of 3
        state = {
            "question": "Import LED lamps",
            "messages": [],
            "iteration": 1,
            "plan": [
                {"step_number": 1, "action": "a", "description": "A", "inputs": {}},
                {"step_number": 2, "action": "b", "description": "B", "inputs": {}},
                {"step_number": 3, "action": "c", "description": "C", "inputs": {}}
            ],
            "current_step": 1,
            "tool_outputs": []
        }

        mock_llm = Mock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.invoke.return_value = AIMessage(content="...")

        with patch('app.chat.graphs.agentic_rag.ChatOpenAI', return_value=mock_llm):
            result = agent_node(state)

        # Should advance to step 2
        assert result["current_step"] == 2

    def test_agent_stays_at_last_step(self):
        """Test that agent stays at last step when complete."""
        from app.chat.graphs.agentic_rag import agent_node

        # State at last step
        state = {
            "question": "Import LED lamps",
            "messages": [],
            "iteration": 2,
            "plan": [
                {"step_number": 1, "action": "a", "description": "A", "inputs": {}}
            ],
            "current_step": 0,  # Only one step, index 0
            "tool_outputs": []
        }

        mock_llm = Mock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.invoke.return_value = AIMessage(content="...")

        with patch('app.chat.graphs.agentic_rag.ChatOpenAI', return_value=mock_llm):
            result = agent_node(state)

        # Should stay at step 0 (only one step)
        assert result["current_step"] == 0


class TestPlanQueries:
    """Test plan generation for different query types."""

    def _create_mock_llm_for_query(self, expected_action):
        """Create a mock LLM that returns a plan with the expected action."""
        plan = {
            "steps": [
                {"step_number": 1, "action": expected_action, "description": "Execute action", "inputs": {}}
            ],
            "reasoning": f"Plan for {expected_action}"
        }
        mock_llm = Mock()
        mock_llm.invoke.return_value = AIMessage(content=json.dumps(plan))
        return mock_llm

    def test_hts_query_uses_lookup(self):
        """Test HTS query results in lookup_hts_code action."""
        state = {"question": "What is the HTS code for LED lamps?"}
        mock_llm = self._create_mock_llm_for_query("lookup_hts_code")

        with patch('app.chat.graphs.agentic_rag.ChatOpenAI', return_value=mock_llm):
            result = plan_node(state)

        assert result["plan"][0]["action"] == "lookup_hts_code"

    def test_tariff_query_uses_check_tariffs(self):
        """Test tariff query results in check_tariffs action."""
        state = {"question": "What tariff applies to LED lamps from China?"}
        mock_llm = self._create_mock_llm_for_query("check_tariffs")

        with patch('app.chat.graphs.agentic_rag.ChatOpenAI', return_value=mock_llm):
            result = plan_node(state)

        assert result["plan"][0]["action"] == "check_tariffs"

    def test_agency_query_uses_check_agency(self):
        """Test agency query results in check_agency_requirements action."""
        state = {"question": "What FDA requirements apply to food imports?"}
        mock_llm = self._create_mock_llm_for_query("check_agency_requirements")

        with patch('app.chat.graphs.agentic_rag.ChatOpenAI', return_value=mock_llm):
            result = plan_node(state)

        assert result["plan"][0]["action"] == "check_agency_requirements"
