"""
Gradio UI for Lanes Trade Compliance Assistant.

Features:
- Documents Tab: Upload and process PDFs with progress feedback
- Chat Tab: Two-pane layout with chat and structured output

Modes:
- Standard RAG: Multi-doc Q&A with citations
- Trade Compliance: Structured output with HTS codes, agencies, documents
- Agentic: Uses planning and tool use for complex queries

Run with:
    python scripts/gradio_app.py
"""

import os
import sys
import uuid
import json

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gradio as gr

from app.chat import (
    build_chat,
    build_trade_compliance_chat,
    build_agentic_chat,
    build_agentic_trade_chat,
)
from app.chat.models import ChatArgs, Metadata
from app.chat.ingest import ingest_multiple_pdfs, format_results_markdown


# ============================================================================
# Configuration
# ============================================================================

DEFAULT_SCOPE_FILTER = {"corpus": "trade_compliance"}
DEFAULT_USER_ID = "gradio-demo-user"


# ============================================================================
# Session State Helpers
# ============================================================================

def get_or_init_state(state: dict | None) -> dict:
    """Ensure we have a conversation_id in this Gradio session."""
    if state is None:
        state = {}
    if "conversation_id" not in state:
        # Always generate a fresh UUID to avoid loading corrupted checkpoint state
        state["conversation_id"] = f"gradio-{uuid.uuid4().hex[:12]}"
    if "documents_loaded" not in state:
        state["documents_loaded"] = False
    if "ingested_docs" not in state:
        state["ingested_docs"] = []
    return state


def reset_conversation(state: dict | None) -> tuple:
    """Reset conversation by generating a new conversation_id."""
    state = state or {}
    state["conversation_id"] = f"gradio-{uuid.uuid4().hex[:12]}"
    return [], "_Ask a question to see structured output and sources here._", state


# ============================================================================
# Document Upload Handlers
# ============================================================================

def handle_upload(files, state, progress=gr.Progress()):
    """
    Handle PDF upload and ingestion with progress bars.

    Args:
        files: List of uploaded file paths
        state: Session state
        progress: Gradio progress tracker

    Returns:
        Tuple of (status_message, doc_list_markdown, state, button_visible)
    """
    state = get_or_init_state(state)

    if not files:
        return (
            "**Status:** No files selected. Please upload PDF files.",
            "_No documents loaded._",
            state,
            gr.update(visible=False)
        )

    # Get file paths
    pdf_paths = [f for f in files if f.endswith('.pdf')]

    if not pdf_paths:
        return (
            "**Status:** No PDF files found. Please upload PDF files.",
            "_No documents loaded._",
            state,
            gr.update(visible=False)
        )

    # Import here to avoid circular imports
    from app.chat.ingest import ingest_pdf, format_results_markdown as fmt_results

    results = []
    total_files = len(pdf_paths)

    progress(0, desc="Starting upload...")

    for i, pdf_path in enumerate(pdf_paths):
        filename = os.path.basename(pdf_path)

        # Update progress for upload phase
        upload_pct = (i / total_files)
        progress(upload_pct, desc=f"Uploading {i+1}/{total_files}: {filename}")

        try:
            # Ingest single PDF (chunking happens inside)
            result = ingest_pdf(
                pdf_path,
                corpus="trade_compliance",
                progress_callback=lambda msg: progress(
                    upload_pct + (0.5 / total_files),
                    desc=f"[{i+1}/{total_files}] {msg}"
                )
            )
            results.append(result)

            # Update progress after chunking
            progress((i + 1) / total_files, desc=f"✓ Completed {filename}")

        except Exception as e:
            results.append({"filename": filename, "error": str(e)})
            progress((i + 1) / total_files, desc=f"✗ Error: {filename}")

    # Final progress
    progress(1.0, desc="Done!")

    # Update state
    state["documents_loaded"] = True
    state["ingested_docs"] = results

    # Format final results
    doc_list = fmt_results(results)

    # Build final status
    total_chunks = sum(r.get("chunks", 0) for r in results if "error" not in r)
    errors = sum(1 for r in results if "error" in r)

    if errors:
        status = f"### ⚠️ Processed {len(results)} files\n\n"
        status += f"**{total_chunks}** chunks created, **{errors}** errors\n\n"
    else:
        status = f"### ✅ Successfully processed {len(results)} files\n\n"
        status += f"**{total_chunks}** chunks indexed and ready for search\n\n"

    status += "Click **Start Chatting** below to ask questions about your documents."

    return status, doc_list, state, gr.update(visible=True)


def use_existing_docs(state):
    """Mark that user wants to use existing documents."""
    state = get_or_init_state(state)
    state["documents_loaded"] = True

    # Check if we have info about existing docs
    if state.get("ingested_docs"):
        from app.chat.ingest import format_results_markdown as fmt_results
        doc_list = fmt_results(state["ingested_docs"])
    else:
        doc_list = "### Loaded Documents\n\n_Using previously ingested documents from Pinecone._"

    status = "### ✅ Ready to chat\n\nClick **Start Chatting** below to ask questions about your documents."

    return status, doc_list, state, gr.update(visible=True)


# ============================================================================
# Markdown Rendering Helpers
# ============================================================================

def render_trade_compliance_md(structured_output: dict | None, citations: list[dict], tool_calls: list[str] | None = None) -> str:
    """Render trade compliance structured output as Markdown."""
    if not structured_output:
        if not citations:
            return "_No structured output available._"
        return render_citations_md(citations)

    so = structured_output
    lines = []

    # HTS Codes (as chips using backticks)
    hts_codes = so.get("hts_codes") or []
    if hts_codes:
        lines.append("### HTS Codes")
        codes_str = "  ".join(f"`{c}`" for c in hts_codes)
        lines.append(codes_str)
        lines.append("")

    # Agencies
    agencies = so.get("agencies") or []
    if agencies:
        lines.append("### Regulatory Agencies")
        lines.append("  ".join(f"**{a}**" for a in agencies))
        lines.append("")

    # Tariff Information
    tariff_info = so.get("tariff_info") or {}
    if tariff_info:
        lines.append("### Tariff Information")
        duty_rate = tariff_info.get("duty_rate")
        if duty_rate:
            lines.append(f"- **Duty Rate:** {duty_rate}")
        special_programs = tariff_info.get("special_programs") or []
        if special_programs:
            lines.append(f"- **Special Programs:** {', '.join(special_programs)}")
        country_specific = tariff_info.get("country_specific")
        if country_specific:
            lines.append(f"- **Country Notes:** {country_specific}")
        lines.append("")

    # Required Documents
    required_docs = so.get("required_documents") or []
    if required_docs:
        lines.append("### Required Documents")
        for doc in required_docs:
            if isinstance(doc, dict):
                agency = doc.get("agency", "Unknown")
                name = doc.get("document_name", "Document")
                desc = doc.get("description", "")
                line = f"- [ ] **[{agency}]** {name}"
                if desc:
                    line += f" - _{desc}_"
                lines.append(line)
            else:
                lines.append(f"- [ ] {doc}")
        lines.append("")

    # Risk Flags
    risk_flags = so.get("risk_flags") or []
    if risk_flags:
        lines.append("### Risk Flags")
        for flag in risk_flags:
            lines.append(f"- {flag}")
        lines.append("")

    # Tool Calls (for agentic mode)
    if tool_calls:
        lines.append("### Agent Actions")
        for tc in tool_calls:
            lines.append(f"- `{tc}`")
        lines.append("")

    # Citations at bottom
    if citations:
        lines.append(render_citations_md(citations))

    return "\n".join(lines) if lines else "_No structured output available._"


def render_citations_md(citations: list[dict]) -> str:
    """Render citations as Markdown."""
    if not citations:
        return ""

    lines = ["### Sources", ""]
    for c in citations:
        idx = c.get("index", "?")
        pdf_id = c.get("pdf_id", "unknown")
        doc_type = c.get("doc_type", "document")
        page = c.get("page")
        snippet = c.get("snippet", "")

        # Main citation line
        main = f"**[{idx}]** `{pdf_id}` ({doc_type}"
        if page is not None:
            main += f", p.{page}"
        main += ")"
        lines.append(main)

        # Snippet as blockquote
        if snippet:
            # Truncate long snippets
            if len(snippet) > 150:
                snippet = snippet[:150] + "..."
            lines.append(f"> {snippet}")
        lines.append("")

    return "\n".join(lines)


def render_plan_md(plan: list[dict] | None, plan_reasoning: str | None) -> str:
    """Render the agent's plan as Markdown."""
    if not plan:
        return ""

    lines = ["### Execution Plan", ""]

    if plan_reasoning:
        lines.append(f"_{plan_reasoning}_")
        lines.append("")

    for step in plan:
        step_num = step.get("step_number", "?")
        action = step.get("action", "unknown")
        description = step.get("description", "")
        lines.append(f"{step_num}. **{action}**: {description}")

    lines.append("")
    return "\n".join(lines)


# ============================================================================
# Chat Handler
# ============================================================================

def chat_handler_streaming(message: str, history: list, mode: str, use_agentic: bool, state: dict):
    """
    Chat handler that shows progress and returns formatted response.

    Args:
        message: User's input message
        history: Chat history as list of message dicts (Gradio 6.x format)
        mode: "trade_compliance" or "standard_rag"
        use_agentic: Whether to use agentic reasoning with tools
        state: Session state with conversation_id

    Yields:
        Tuples of (history, sidebar_md, state) with progress updates
    """
    if not message.strip():
        yield history, "_Please enter a question._", state
        return

    state = get_or_init_state(state)
    conversation_id = state["conversation_id"]

    # Prepare ChatArgs
    metadata = Metadata(
        conversation_id=conversation_id,
        user_id=DEFAULT_USER_ID,
        pdf_id=None,
    )

    chat_args = ChatArgs(
        conversation_id=conversation_id,
        pdf_id=None,
        metadata=metadata,
        streaming=True,
        mode="multi_doc",
        scope_filter=DEFAULT_SCOPE_FILTER,
    )

    # Add user message to history immediately
    history = history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": ""}
    ]

    # Choose the appropriate chat builder
    try:
        if mode == "trade_compliance":
            if use_agentic:
                chat = build_agentic_trade_chat(chat_args)
            else:
                chat = build_trade_compliance_chat(chat_args)
            output_format = "trade_compliance"
        else:
            # Standard RAG mode
            if use_agentic:
                chat = build_agentic_chat(chat_args, output_format="text")
            else:
                chat = build_chat(chat_args, output_format="text")
            output_format = "text"

        # Show initial progress
        if use_agentic:
            history[-1]["content"] = "🔄 Planning approach..."
            yield history, "_Planning query strategy..._", state

        # Use invoke() which is confirmed working
        # The streaming was having issues capturing the final answer
        result = chat.invoke(message)

        # Extract response fields
        full_answer = result.get("answer", "") or result.get("final_answer", "")
        citations = result.get("citations", [])
        structured_output = result.get("structured_output")
        tool_calls = result.get("tool_calls", []) or result.get("tool_outputs", [])
        plan = result.get("plan", [])
        plan_reasoning = result.get("plan_reasoning", "")

        # Final update with complete answer
        if not full_answer:
            full_answer = "I couldn't find relevant information for your query. Please try rephrasing or asking about a different topic."
        history[-1]["content"] = full_answer

        # Build sidebar markdown
        sidebar_parts = []

        # Add plan if agentic mode
        if use_agentic and plan:
            sidebar_parts.append(render_plan_md(plan, plan_reasoning))

        # Add structured output or citations
        if output_format == "trade_compliance":
            sidebar_parts.append(render_trade_compliance_md(structured_output, citations, tool_calls))
        else:
            if citations:
                sidebar_parts.append(render_citations_md(citations))
            if tool_calls and use_agentic:
                sidebar_parts.append("### Agent Actions")
                sidebar_parts.append("\n".join(f"- `{tc}`" for tc in tool_calls))

        sidebar_md = "\n\n".join(sidebar_parts) if sidebar_parts else "_No additional information._"

        yield history, sidebar_md, state

    except Exception as e:
        # Handle errors with user-friendly messages
        error_str = str(e).lower()

        if "rate limit" in error_str or "429" in error_str:
            # Rate limit error - friendly message
            user_message = "Our servers are busy right now. Please wait a moment and try again."
            sidebar_md = "### Please Wait\n\nThe system is processing many requests. Try again in a few seconds."
        elif "timeout" in error_str:
            user_message = "The request took too long. Please try a simpler question or try again."
            sidebar_md = "### Timeout\n\nThe query was too complex. Try breaking it into smaller questions."
        elif "api" in error_str or "openai" in error_str:
            user_message = "There was a temporary issue connecting to our AI service. Please try again."
            sidebar_md = "### Connection Issue\n\nPlease try again in a moment."
        else:
            user_message = "Something went wrong. Please try rephrasing your question."
            import traceback
            sidebar_md = f"### Error\n\n```\n{traceback.format_exc()}\n```"

        history[-1]["content"] = user_message
        yield history, sidebar_md, state


# ============================================================================
# Gradio App
# ============================================================================

def make_app():
    """Create and configure the Gradio app."""

    with gr.Blocks(
        title="Laynes - Trade Compliance Assistant",
    ) as demo:

        gr.Markdown("""
        # Laynes - Trade Compliance Assistant

        Upload trade compliance documents and ask questions about HTS codes, tariffs, and regulatory requirements.
        """)

        # Session state
        state = gr.State({})

        # Tabbed interface
        with gr.Tabs() as tabs:

            # ================================================================
            # Documents Tab
            # ================================================================
            with gr.Tab("Documents", id=0):
                gr.Markdown("""
                ### Upload Trade Documents

                Upload PDF files (HTS schedules, tariff lists, CBP guides, etc.) to build your knowledge base.
                """)

                with gr.Row():
                    file_upload = gr.File(
                        label="Upload Trade Documents (PDF)",
                        file_count="multiple",
                        file_types=[".pdf"],
                        type="filepath",
                    )

                with gr.Row():
                    upload_btn = gr.Button("Upload & Process", variant="primary", scale=2)
                    use_existing_btn = gr.Button("Use Existing Documents", variant="secondary", scale=1)

                status_area = gr.Markdown(
                    value="**Status:** Ready to upload documents. Drag & drop PDF files above, then click 'Upload & Process'.",
                )

                doc_list_area = gr.Markdown(
                    value="_No documents loaded yet._",
                )

                # Start Chatting button (hidden until documents are loaded)
                start_chat_btn = gr.Button(
                    "🚀 Start Chatting",
                    variant="primary",
                    visible=False,
                    size="lg"
                )

                # Wire up document handlers
                upload_btn.click(
                    handle_upload,
                    inputs=[file_upload, state],
                    outputs=[status_area, doc_list_area, state, start_chat_btn],
                )

                use_existing_btn.click(
                    use_existing_docs,
                    inputs=[state],
                    outputs=[status_area, doc_list_area, state, start_chat_btn],
                )

            # ================================================================
            # Chat Tab
            # ================================================================
            with gr.Tab("Chat", id=1) as chat_tab:

                # Controls row
                with gr.Row():
                    mode = gr.Radio(
                        choices=["trade_compliance", "standard_rag"],
                        value="trade_compliance",
                        label="Output Mode",
                        info="Trade Compliance: Structured output with HTS codes, agencies, documents | Standard: Simple Q&A with citations"
                    )
                    use_agentic = gr.Checkbox(
                        value=True,
                        label="Use Agentic Reasoning",
                        info="Enable planning and tool use for complex queries"
                    )
                    reset_btn = gr.Button("New Conversation", variant="secondary", size="sm")

                # Two-pane layout
                with gr.Row():
                    # Left pane: Chat
                    with gr.Column(scale=2):
                        chatbot = gr.Chatbot(
                            label="Chat",
                            height=500,
                        )
                        with gr.Row():
                            user_input = gr.Textbox(
                                label="Your Question",
                                placeholder="e.g., What is the HTS code for LED lamps from China?",
                                lines=2,
                                scale=4,
                            )
                            send_btn = gr.Button("Send", variant="primary", scale=1)

                    # Right pane: Summary / Structured Output
                    with gr.Column(scale=1):
                        gr.Markdown("### Summary & Sources")
                        sidebar_md = gr.Markdown(
                            value="_Ask a question to see structured output and sources here._",
                        )

                # Event handlers for streaming
                def submit_message_streaming(message, history, mode, use_agentic, state):
                    """Handle message submission with streaming."""
                    # Yield the cleared input immediately, then stream responses
                    for hist, sidebar, st in chat_handler_streaming(
                        message, history, mode, use_agentic, state
                    ):
                        yield "", hist, sidebar, st

                # Wire up chat events with streaming
                send_btn.click(
                    submit_message_streaming,
                    inputs=[user_input, chatbot, mode, use_agentic, state],
                    outputs=[user_input, chatbot, sidebar_md, state],
                )

                user_input.submit(
                    submit_message_streaming,
                    inputs=[user_input, chatbot, mode, use_agentic, state],
                    outputs=[user_input, chatbot, sidebar_md, state],
                )

                reset_btn.click(
                    reset_conversation,
                    inputs=[state],
                    outputs=[chatbot, sidebar_md, state],
                )

                # Example queries
                gr.Markdown("### Example Queries")
                gr.Examples(
                    examples=[
                        ["What is the HTS code for LED lamps?"],
                        ["I want to import LED lamps from China. What tariffs apply?"],
                        ["What agencies regulate LED lamp imports?"],
                        ["What documents do I need to import LED lamps from China?"],
                        ["What are the compliance requirements for importing electronics from China?"],
                    ],
                    inputs=user_input,
                    label="Try these examples",
                )

        # Wire up "Start Chatting" button to switch to Chat tab
        start_chat_btn.click(
            lambda: gr.update(selected=1),
            inputs=None,
            outputs=tabs,
        )

    return demo


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    # Check for required environment variables
    required_vars = ["OPENAI_API_KEY", "PINECONE_API_KEY"]
    missing = [v for v in required_vars if not os.getenv(v)]

    if missing:
        print(f"Warning: Missing environment variables: {', '.join(missing)}")
        print("The app may not work correctly without these.")
        print("")

    # Create and launch the app
    app = make_app()

    print("Starting Laynes Trade Compliance Assistant...")
    print("Open http://localhost:7860 in your browser")
    print("")

    # Find available port starting from 7860
    import socket

    def find_free_port(start_port=7860):
        for port in range(start_port, start_port + 100):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(('', port))
                    return port
            except OSError:
                continue
        return start_port + 100

    port = find_free_port()
    print(f"Using port: {port}")

    app.launch(
        server_name="0.0.0.0",
        server_port=port,
        share=False,  # Set to True for public sharing
    )
