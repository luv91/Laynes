"""
Agentic RAG Graph using LangGraph with Tool Use.

This extends the basic conversational RAG with:
- Explicit Planning: Generate step-by-step plan before execution
- Tool use: Search, retrieve specific documents, calculate tariffs
- Iteration: Can retrieve more info if initial results are insufficient
- Reflection: Agent evaluates if it has enough info to answer

The graph follows this pattern:
1. Plan: Generate explicit step-by-step plan (NEW)
2. Agent: Execute plan using tools
3. Tools: Run selected tools
4. Generate: Create final answer (or loop back to Agent)
"""

import json
from typing import TypedDict, List, Optional, Annotated, Sequence, Literal
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver

# Import from new modules
from app.chat.tools import TRADE_TOOLS
from app.chat.prompts import PLANNER_PROMPT, PLANNING_PROMPT
from app.chat.output_schemas import AgentPlan, PlanStep


# ============================================================================
# Graph State
# ============================================================================

class AgentState(TypedDict):
    """
    State for the agentic RAG graph.

    Attributes:
        messages: Full conversation history with tool calls/results
        question: Current user question
        plan: The agent's plan for answering (list of step dicts)
        plan_reasoning: Agent's reasoning for the plan
        current_step: Index of current step in plan (0-based)
        tool_outputs: Results from tool executions
        reflection: Agent's assessment of whether it has enough info
        final_answer: The generated answer
        iteration: Current iteration count (to prevent infinite loops)
        scope_filter: Filter for document retrieval
        output_format: "text", "structured", or "trade_compliance"
    """
    messages: Annotated[Sequence[BaseMessage], add_messages]
    question: str
    plan: Optional[List[dict]]
    plan_reasoning: Optional[str]
    current_step: int
    tool_outputs: List[str]
    reflection: Optional[str]
    final_answer: Optional[str]
    iteration: int
    scope_filter: Optional[dict]
    output_format: str


# Note: Prompts are now imported from app.chat.prompts


# ============================================================================
# Graph Nodes
# ============================================================================

def _format_chat_history(messages: Sequence[BaseMessage], max_messages: int = 10) -> str:
    """Format conversation history for prompts."""
    # Filter to only human/ai messages (exclude system, tool messages)
    chat_messages = [m for m in messages if isinstance(m, (HumanMessage, AIMessage))]

    # Take only recent messages to avoid context overflow
    recent_messages = chat_messages[-max_messages:] if len(chat_messages) > max_messages else chat_messages

    if not recent_messages:
        return "No previous conversation."

    # Format as readable text
    formatted = []
    for m in recent_messages:
        role = "User" if isinstance(m, HumanMessage) else "Assistant"
        # Truncate long messages
        content = m.content[:500] + "..." if len(m.content) > 500 else m.content
        formatted.append(f"{role}: {content}")

    return "\n".join(formatted)


def plan_node(state: AgentState) -> dict:
    """
    Generate an explicit step-by-step plan before executing tools.

    This node creates a visible plan that shows:
    - What tools will be used
    - In what order
    - What each step accomplishes

    The plan is stored in state and used to guide agent execution.
    """
    question = state["question"]
    messages = state.get("messages", [])

    # Format conversation history for context
    chat_history = _format_chat_history(messages)

    llm = ChatOpenAI(model="gpt-4o", temperature=0, max_retries=3)

    response = llm.invoke([
        SystemMessage(content="You are a planning assistant. Output ONLY valid JSON, no other text."),
        HumanMessage(content=PLANNING_PROMPT.format(question=question, chat_history=chat_history))
    ])

    try:
        plan_data = json.loads(response.content)
        steps = plan_data.get("steps", [])
        reasoning = plan_data.get("reasoning", "")
    except json.JSONDecodeError:
        # Fallback to single-step plan if JSON parsing fails
        steps = [{
            "step_number": 1,
            "action": "search_documents",
            "description": "Search for relevant information",
            "inputs": {"query": question}
        }]
        reasoning = "Fallback plan due to parsing error"

    return {
        "plan": steps,
        "plan_reasoning": reasoning,
        "current_step": 0
    }


def agent_node(state: AgentState) -> dict:
    """
    Main agent node that decides actions using tool-calling.

    Uses the plan (if available) to guide tool selection.
    Uses OpenAI function calling to let the LLM decide which tools to use.
    """
    question = state["question"]
    messages = list(state.get("messages", []))
    iteration = state.get("iteration", 0)
    plan = state.get("plan", [])
    current_step = state.get("current_step", 0)

    # Format conversation history for context
    chat_history = _format_chat_history(messages)

    # Create LLM with tools bound
    llm = ChatOpenAI(model="gpt-4o", temperature=0, max_retries=3)
    llm_with_tools = llm.bind_tools(TRADE_TOOLS)

    # Build prompt with context including plan
    tool_results = "\n".join(state.get("tool_outputs", [])) or "No tools called yet."

    # Include plan context in the prompt
    plan_context = ""
    if plan:
        plan_text = "\n".join([
            f"  {s.get('step_number', i+1)}. [{s.get('action', 'unknown')}] {s.get('description', '')}"
            for i, s in enumerate(plan)
        ])
        current = plan[current_step] if current_step < len(plan) else None
        if current:
            plan_context = f"""

Your execution plan:
{plan_text}

CURRENT STEP: {current_step + 1} - {current.get('action', 'unknown')}: {current.get('description', '')}
Suggested inputs: {json.dumps(current.get('inputs', {}))}

Execute the current step, then we'll move to the next."""

    system_content = PLANNER_PROMPT.format(
        question=question,
        chat_history=chat_history,
        tool_results=tool_results[:2000]
    ) + plan_context

    system_message = SystemMessage(content=system_content)

    # Add system message at the start if not present
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [system_message] + [m for m in messages if not isinstance(m, SystemMessage)]

    # Invoke LLM
    response = llm_with_tools.invoke(messages)

    # Advance to next step after tool execution
    next_step = current_step + 1 if current_step < len(plan) - 1 else current_step

    return {
        "messages": [response],
        "iteration": iteration + 1,
        "current_step": next_step
    }


def tool_executor_node(state: AgentState) -> dict:
    """
    Execute tools called by the agent.

    Processes tool calls from the last AI message and returns results.
    """
    messages = state.get("messages", [])
    if not messages:
        return {"tool_outputs": []}

    last_message = messages[-1]

    # Check if there are tool calls
    if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
        return {"tool_outputs": []}

    tool_outputs = []
    tool_messages = []

    # Map tool names to functions
    tool_map = {t.name: t for t in TRADE_TOOLS}

    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]

        if tool_name in tool_map:
            try:
                result = tool_map[tool_name].invoke(tool_args)
                tool_outputs.append(f"[{tool_name}]: {result}")
                tool_messages.append(ToolMessage(
                    content=result,
                    tool_call_id=tool_call["id"]
                ))
            except Exception as e:
                error_msg = f"Error calling {tool_name}: {str(e)}"
                tool_outputs.append(error_msg)
                tool_messages.append(ToolMessage(
                    content=error_msg,
                    tool_call_id=tool_call["id"]
                ))

    return {
        "tool_outputs": state.get("tool_outputs", []) + tool_outputs,
        "messages": tool_messages
    }


def should_continue(state: AgentState) -> Literal["tools", "generate"]:
    """
    Determine if we should continue with tools or generate final answer.

    Routes to 'tools' if the last message has tool calls,
    otherwise routes to 'generate' for final answer.
    """
    messages = state.get("messages", [])
    iteration = state.get("iteration", 0)

    # Prevent infinite loops
    if iteration >= 5:
        return "generate"

    if not messages:
        return "generate"

    last_message = messages[-1]

    # If there are tool calls, continue to tool executor
    if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        return "tools"

    return "generate"


def generate_answer_node(state: AgentState) -> dict:
    """
    Generate the final answer based on gathered information.
    """
    question = state["question"]
    messages = state.get("messages", [])
    tool_outputs = state.get("tool_outputs", [])
    output_format = state.get("output_format", "text")

    # Format conversation history for context
    chat_history = _format_chat_history(messages)

    # Combine all tool outputs as context
    context = "\n\n---\n\n".join(tool_outputs) if tool_outputs else "No information gathered."

    llm = ChatOpenAI(model="gpt-4o", temperature=0, max_retries=3)

    if output_format == "trade_compliance":
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a trade compliance expert. Based on the research gathered, provide a comprehensive, well-formatted answer.

Structure your response with clear sections using markdown:

1. Start with a direct answer to the question
2. **HTS Code(s):** List the relevant codes with descriptions
3. **Regulatory Agencies:** List agencies with their roles
4. **Required Documents:** Bullet list of documents needed
5. **Tariff Information:** Duty rates and special programs
6. **Important Compliance Notes:** Any warnings or requirements

Use bullet points (•) and bold headers. Make it easy to read.
Do NOT output JSON - write natural, formatted text that a business user can understand.

Research gathered:
{context}

Previous conversation:
{chat_history}

IMPORTANT: If the current question is a follow-up, use the conversation history to provide relevant context."""),
            ("human", "{question}")
        ])
    elif output_format == "structured":
        prompt = ChatPromptTemplate.from_messages([
            ("system", """Based on the conversation history and research gathered, provide a structured answer in JSON format:
- answer: Main answer text with citations
- citations: List of {{pdf_id, doc_type, snippet}}
- confidence: high/medium/low
- follow_up_questions: List of suggested follow-ups

Previous conversation:
{chat_history}

Research gathered:
{context}

IMPORTANT: If the current question is a follow-up, use the conversation history to provide relevant context."""),
            ("human", "{question}")
        ])
    else:
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a helpful trade compliance assistant.
Based on the conversation history and research gathered, provide a clear, accurate answer with source citations.
Always cite the source document when providing specific information.

Previous conversation:
{chat_history}

Research gathered:
{context}

IMPORTANT: If the current question is a follow-up (like "what is it?", "tell me more"),
use the conversation history to understand what the user is referring to and provide a contextual answer."""),
            ("human", "{question}")
        ])

    chain = prompt | llm | StrOutputParser()
    answer = chain.invoke({"context": context, "question": question, "chat_history": chat_history})

    # For "structured" mode only, parse JSON (trade_compliance now outputs text directly)
    if output_format == "structured":
        try:
            structured_output = json.loads(answer)
            if isinstance(structured_output, dict) and "answer" in structured_output:
                answer = structured_output["answer"]
        except json.JSONDecodeError:
            pass  # Keep original answer if not valid JSON

    return {
        "final_answer": answer,
        "messages": [AIMessage(content=answer)]
    }


# ============================================================================
# Graph Builder
# ============================================================================

def build_agentic_graph(checkpointer=None, scope_filter: dict = None):
    """
    Build the agentic RAG graph with explicit planning and tool use.

    The graph flow is:
    START -> plan -> agent -> (tools <-> agent) -> generate -> END

    Args:
        checkpointer: LangGraph checkpointer for memory persistence
        scope_filter: Filter for document retrieval scope

    Returns:
        Compiled LangGraph graph
    """
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("plan", plan_node)  # NEW: explicit planning node
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_executor_node)
    workflow.add_node("generate", generate_answer_node)

    # Add edges: START -> plan -> agent -> (conditional) -> generate -> END
    workflow.add_edge(START, "plan")  # NEW: start with planning
    workflow.add_edge("plan", "agent")  # NEW: plan feeds into agent
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            "generate": "generate"
        }
    )
    workflow.add_edge("tools", "agent")  # Loop back after tool execution
    workflow.add_edge("generate", END)

    # Use provided checkpointer or default to MemorySaver
    if checkpointer is None:
        checkpointer = MemorySaver()

    return workflow.compile(checkpointer=checkpointer)


# ============================================================================
# High-Level Wrapper
# ============================================================================

class AgenticRAG:
    """
    High-level wrapper for the agentic RAG graph.

    Provides planning and tool use capabilities for complex queries.
    """

    def __init__(
        self,
        conversation_id: str,
        scope_filter: dict = None,
        checkpointer=None,
        output_format: str = "text"
    ):
        """
        Initialize the agentic RAG.

        Args:
            conversation_id: Unique ID for this conversation
            scope_filter: Filter for document retrieval
            checkpointer: Optional custom checkpointer
            output_format: "text", "structured", or "trade_compliance"
        """
        self.conversation_id = conversation_id
        self.scope_filter = scope_filter
        self.output_format = output_format
        self.graph = build_agentic_graph(
            checkpointer=checkpointer,
            scope_filter=scope_filter
        )
        self.config = {"configurable": {"thread_id": conversation_id}}

    def invoke(self, question: str, output_format: str = None) -> dict:
        """
        Send a question and get a response using agentic reasoning.

        Args:
            question: The user's question
            output_format: Override default output format

        Returns:
            Dict with 'answer', 'tool_calls', 'plan', and optionally 'structured_output'
        """
        format_to_use = output_format or self.output_format

        result = self.graph.invoke(
            {
                "question": question,
                "messages": [HumanMessage(content=question)],
                "scope_filter": self.scope_filter,
                "output_format": format_to_use,
                "plan": None,
                "plan_reasoning": None,
                "current_step": 0,
                "tool_outputs": [],
                "reflection": None,
                "final_answer": None,
                "iteration": 0
            },
            config=self.config
        )

        return {
            "answer": result.get("final_answer", ""),
            "tool_calls": result.get("tool_outputs", []),
            "plan": result.get("plan", []),
            "plan_reasoning": result.get("plan_reasoning", ""),
            "messages": result.get("messages", [])
        }

    def stream(self, question: str):
        """
        Stream the agentic response with state updates after each node.

        Yields state updates as the agent plans, executes tools, and generates answer.
        Properly handles tool calls by using stream_mode="values".
        """
        input_state = {
            "question": question,
            "messages": [HumanMessage(content=question)],
            "scope_filter": self.scope_filter,
            "output_format": self.output_format,
            "plan": None,
            "plan_reasoning": None,
            "current_step": 0,
            "tool_outputs": [],
            "reflection": None,
            "final_answer": None,
            "iteration": 0
        }

        # Use stream_mode="values" for state updates after each node
        # This properly handles tool calls without breaking message sequence
        for chunk in self.graph.stream(
            input_state,
            config=self.config,
            stream_mode="values"
        ):
            # chunk is the full state dict after each node completes
            yield {
                "answer": chunk.get("final_answer", ""),
                "final_answer": chunk.get("final_answer", ""),
                "plan": chunk.get("plan", []),
                "plan_reasoning": chunk.get("plan_reasoning", ""),
                "tool_outputs": chunk.get("tool_outputs", [])
            }
