"""
Conversational RAG Graph using LangGraph.

This replaces the old ConversationalRetrievalChain with a LangGraph-based
implementation that provides:
- Native streaming support
- Built-in memory persistence via checkpointers (SQLite for persistence)
- Thread-based conversation isolation
- Modular node-based architecture
- Source citations for transparency
- Structured JSON output for downstream processing

The graph follows the same pattern as the old chain:
1. Condense: Reformulate follow-up questions using chat history
2. Retrieve: Get relevant documents from Pinecone with scope_filter
3. Generate: Create answer from retrieved context with citations
"""

import os
import json
from typing import TypedDict, List, Optional, Annotated, Sequence
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver
from pinecone import Pinecone as PineconeClient
from langchain_pinecone import PineconeVectorStore

# Import from new modules
from app.chat.output_schemas import (
    SourceCitation,
    StructuredAnswer,
    TradeComplianceOutput,
)
from app.chat.prompts import (
    CONDENSE_SYSTEM_PROMPT,
    ANSWER_SYSTEM_PROMPT,
    STRUCTURED_ANSWER_PROMPT,
    TRADE_COMPLIANCE_PROMPT,
)


# ============================================================================
# Graph State
# ============================================================================

class ConversationState(TypedDict):
    """
    State for the conversational RAG graph.

    Attributes:
        messages: Full conversation history (managed by add_messages)
        question: Current user question
        condensed_question: Reformulated standalone question
        documents: Retrieved documents from vector store
        answer: Generated answer (text)
        structured_output: Structured JSON output for downstream processing
        citations: Source citations for the answer
        scope_filter: Filter for multi-doc retrieval
        pdf_id: Single document ID for backward compatibility
        mode: "user_pdf" or "multi_doc"
        output_format: "text" (default), "structured", or "trade_compliance"
    """
    messages: Annotated[Sequence[BaseMessage], add_messages]
    question: str
    condensed_question: str
    documents: List[Document]
    answer: str
    structured_output: Optional[dict]
    citations: List[dict]
    scope_filter: Optional[dict]
    pdf_id: Optional[str]
    mode: str
    output_format: str


# Note: Prompts and schemas are now imported from app.chat.prompts and app.chat.output_schemas


# ============================================================================
# Helper Functions
# ============================================================================

def _get_vector_store():
    """Initialize and return the Pinecone vector store."""
    pc = PineconeClient(api_key=os.getenv("PINECONE_API_KEY"))
    index = pc.Index(os.getenv("PINECONE_INDEX_NAME", "docs"))
    embeddings = OpenAIEmbeddings()
    return PineconeVectorStore(
        index=index,
        embedding=embeddings,
        text_key="text"
    )


def _get_retrieval_filter(state: ConversationState) -> dict:
    """Build the Pinecone filter based on mode and scope."""
    mode = state.get("mode", "user_pdf")
    scope_filter = state.get("scope_filter")
    pdf_id = state.get("pdf_id")

    if mode == "multi_doc" and scope_filter:
        return scope_filter
    elif pdf_id:
        return {"pdf_id": pdf_id}
    else:
        return {}


def _format_context_with_citations(documents: List[Document]) -> tuple[str, List[dict]]:
    """Format documents into context string and extract citation metadata."""
    context_parts = []
    citations = []

    for i, doc in enumerate(documents):
        pdf_id = doc.metadata.get('pdf_id', 'unknown')
        doc_type = doc.metadata.get('doc_type', 'document')
        page = doc.metadata.get('page')

        # Format context with clear source markers
        source_label = f"[Source {i+1}: {pdf_id}]"
        context_parts.append(f"{source_label}\n{doc.page_content}")

        # Build citation
        citations.append({
            "index": i + 1,
            "pdf_id": pdf_id,
            "doc_type": doc_type,
            "page": page,
            "snippet": doc.page_content[:200] + "..." if len(doc.page_content) > 200 else doc.page_content
        })

    context = "\n\n---\n\n".join(context_parts)
    return context, citations


# ============================================================================
# Graph Nodes
# ============================================================================

def condense_question_node(state: ConversationState) -> dict:
    """
    Condense the user's question using chat history.

    If there's no chat history, returns the question as-is.
    Otherwise, reformulates it to be standalone.
    """
    question = state["question"]
    messages = state.get("messages", [])

    # Filter to only human/ai messages (exclude system)
    chat_history = [m for m in messages if isinstance(m, (HumanMessage, AIMessage))]

    # If no history or only current message, return as-is
    if len(chat_history) <= 1:
        return {"condensed_question": question}

    # Use LLM to reformulate
    llm = ChatOpenAI(model="gpt-4o", temperature=0, max_retries=3)

    condense_prompt = ChatPromptTemplate.from_messages([
        ("system", CONDENSE_SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{question}")
    ])

    chain = condense_prompt | llm | StrOutputParser()

    # Exclude the last message (current question) from history
    history_for_condense = chat_history[:-1] if chat_history else []

    condensed = chain.invoke({
        "chat_history": history_for_condense,
        "question": question
    })

    return {"condensed_question": condensed}


def retrieve_documents_node(state: ConversationState) -> dict:
    """
    Retrieve relevant documents from Pinecone.

    Uses the condensed question and applies scope_filter for multi-doc
    or pdf_id filter for single-doc mode.
    """
    query = state.get("condensed_question") or state["question"]
    retrieval_filter = _get_retrieval_filter(state)

    vector_store = _get_vector_store()

    # Build retriever with filter
    search_kwargs = {"k": 5}
    if retrieval_filter:
        search_kwargs["filter"] = retrieval_filter

    retriever = vector_store.as_retriever(search_kwargs=search_kwargs)
    documents = retriever.invoke(query)

    return {"documents": documents}


def generate_answer_node(state: ConversationState) -> dict:
    """
    Generate answer from retrieved context.

    Supports three output formats:
    - "text": Simple text answer (default)
    - "structured": JSON with answer, citations, confidence, follow-ups
    - "trade_compliance": Specialized JSON for trade/import queries
    """
    question = state.get("condensed_question") or state["question"]
    documents = state.get("documents", [])
    output_format = state.get("output_format", "text")

    # Format context with citations
    context, citations = _format_context_with_citations(documents)

    if not context:
        context = "No relevant documents found."
        citations = []

    llm = ChatOpenAI(model="gpt-4o", temperature=0, max_retries=3)

    if output_format == "trade_compliance":
        # Trade compliance output - formatted text with sections
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a trade compliance expert. Based on the context provided, give a comprehensive, well-formatted answer.

Structure your response with clear sections using markdown:

1. Start with a direct answer to the question
2. **HTS Code(s):** List the relevant codes with descriptions
3. **Regulatory Agencies:** List agencies with their roles
4. **Required Documents:** Bullet list of documents needed
5. **Tariff Information:** Duty rates and special programs
6. **Important Compliance Notes:** Any warnings or requirements

Use bullet points (•) and bold headers. Make it easy to read.
Do NOT output JSON - write natural, formatted text that a business user can understand.

Context from documents:
{context}"""),
            ("human", "{question}")
        ])
        chain = prompt | llm | StrOutputParser()
        answer = chain.invoke({"context": context, "question": question})
        structured = None

    elif output_format == "structured":
        # General structured output
        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a helpful assistant. Respond ONLY with valid JSON."),
            ("human", STRUCTURED_ANSWER_PROMPT)
        ])
        chain = prompt | llm | StrOutputParser()

        response_text = chain.invoke({"context": context, "question": question})

        try:
            structured = json.loads(response_text)
            answer = structured.get("answer", response_text)
        except json.JSONDecodeError:
            structured = {"answer": response_text, "parse_error": True}
            answer = response_text
    else:
        # Default text output with inline citations
        prompt = ChatPromptTemplate.from_messages([
            ("system", ANSWER_SYSTEM_PROMPT),
            ("human", "{question}")
        ])
        chain = prompt | llm | StrOutputParser()

        answer = chain.invoke({"context": context, "question": question})
        structured = None

    return {
        "answer": answer,
        "structured_output": structured,
        "citations": citations,
        "messages": [AIMessage(content=answer)]
    }


# ============================================================================
# Graph Builder
# ============================================================================

def build_rag_graph(
    checkpointer=None,
    scope_filter: dict = None,
    pdf_id: str = None,
    mode: str = "user_pdf"
):
    """
    Build the conversational RAG graph.

    Args:
        checkpointer: LangGraph checkpointer for memory persistence.
                     If None, uses MemorySaver (in-memory).
        scope_filter: Filter for multi-doc retrieval
        pdf_id: Single document ID for backward compatibility
        mode: "user_pdf" (single doc) or "multi_doc" (corpus-based)

    Returns:
        Compiled LangGraph graph ready for invocation.
    """
    workflow = StateGraph(ConversationState)

    # Add nodes
    workflow.add_node("condense", condense_question_node)
    workflow.add_node("retrieve", retrieve_documents_node)
    workflow.add_node("generate", generate_answer_node)

    # Add edges: condense -> retrieve -> generate -> END
    workflow.add_edge(START, "condense")
    workflow.add_edge("condense", "retrieve")
    workflow.add_edge("retrieve", "generate")
    workflow.add_edge("generate", END)

    # Use provided checkpointer or default to MemorySaver
    if checkpointer is None:
        checkpointer = MemorySaver()

    return workflow.compile(checkpointer=checkpointer)


# ============================================================================
# High-Level Wrapper
# ============================================================================

class ConversationalRAG:
    """
    High-level wrapper for the conversational RAG graph.

    Provides a simple interface similar to the old chain-based approach.
    Manages conversation state and thread IDs internally.
    """

    def __init__(
        self,
        conversation_id: str,
        scope_filter: dict = None,
        pdf_id: str = None,
        mode: str = "user_pdf",
        checkpointer=None,
        output_format: str = "text"
    ):
        """
        Initialize the conversational RAG.

        Args:
            conversation_id: Unique ID for this conversation (used as thread_id)
            scope_filter: Filter for multi-doc retrieval
            pdf_id: Single document ID
            mode: "user_pdf" or "multi_doc"
            checkpointer: Optional custom checkpointer
            output_format: "text", "structured", or "trade_compliance"
        """
        self.conversation_id = conversation_id
        self.scope_filter = scope_filter
        self.pdf_id = pdf_id
        self.mode = mode
        self.output_format = output_format
        self.graph = build_rag_graph(
            checkpointer=checkpointer,
            scope_filter=scope_filter,
            pdf_id=pdf_id,
            mode=mode
        )
        self.config = {"configurable": {"thread_id": conversation_id}}

    def invoke(self, question: str, output_format: str = None) -> dict:
        """
        Send a question and get a response.

        Args:
            question: The user's question
            output_format: Override default output format for this query

        Returns:
            Dict with 'answer', 'documents', 'citations', and optionally 'structured_output'
        """
        format_to_use = output_format or self.output_format

        result = self.graph.invoke(
            {
                "question": question,
                "messages": [HumanMessage(content=question)],
                "scope_filter": self.scope_filter,
                "pdf_id": self.pdf_id,
                "mode": self.mode,
                "output_format": format_to_use,
                "condensed_question": "",
                "documents": [],
                "answer": "",
                "structured_output": None,
                "citations": []
            },
            config=self.config
        )

        return {
            "answer": result.get("answer", ""),
            "documents": result.get("documents", []),
            "citations": result.get("citations", []),
            "structured_output": result.get("structured_output"),
            "condensed_question": result.get("condensed_question", "")
        }

    def invoke_structured(self, question: str) -> dict:
        """Convenience method for structured output."""
        return self.invoke(question, output_format="structured")

    def invoke_trade_compliance(self, question: str) -> dict:
        """Convenience method for trade compliance analysis."""
        return self.invoke(question, output_format="trade_compliance")

    def stream(self, question: str):
        """
        Stream the response with state updates after each node.

        Args:
            question: The user's question

        Yields:
            Dict with 'answer', 'citations', 'structured_output', etc.
            Yields after each node completes (condense, retrieve, generate).
        """
        input_state = {
            "question": question,
            "messages": [HumanMessage(content=question)],
            "scope_filter": self.scope_filter,
            "pdf_id": self.pdf_id,
            "mode": self.mode,
            "output_format": self.output_format,
            "condensed_question": "",
            "documents": [],
            "answer": "",
            "structured_output": None,
            "citations": []
        }

        # Use stream_mode="values" for state updates after each node
        for chunk in self.graph.stream(
            input_state,
            config=self.config,
            stream_mode="values"
        ):
            # chunk is the full state dict after each node completes
            yield {
                "answer": chunk.get("answer", ""),
                "citations": chunk.get("citations", []),
                "structured_output": chunk.get("structured_output"),
                "documents": chunk.get("documents", []),
                "condensed_question": chunk.get("condensed_question", "")
            }

    def get_history(self) -> List[BaseMessage]:
        """Get the conversation history."""
        state = self.graph.get_state(self.config)
        return state.values.get("messages", []) if state else []
