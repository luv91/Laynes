import uuid
from flask import Blueprint, g, request, Response, jsonify, stream_with_context
from app.web.hooks import login_required, load_model
from app.web.db.models import Pdf, Conversation
from app.chat import build_chat, build_trade_compliance_chat, build_agentic_chat, ChatArgs
from app.chat.models import Metadata

bp = Blueprint("conversation", __name__, url_prefix="/api/conversations")


@bp.route("/", methods=["GET"])
@login_required
def list_conversations():
    """
    List conversations.

    Query params:
        pdf_id: Filter by specific PDF (for user_pdf mode)
        mode: Filter by mode ("user_pdf" | "multi_doc")
    """
    pdf_id = request.args.get("pdf_id")
    mode = request.args.get("mode")

    query = Conversation.query.filter_by(user_id=g.user.id)

    if pdf_id:
        query = query.filter_by(pdf_id=pdf_id)
    if mode:
        query = query.filter_by(mode=mode)

    conversations = query.order_by(Conversation.created_on.desc()).all()
    return [c.as_dict() for c in conversations]


@bp.route("/", methods=["POST"])
@login_required
def create_conversation():
    """
    Create a new conversation.

    For single-doc mode (default):
        Query param: pdf_id (required)

    For multi-doc mode:
        JSON body: {
            "mode": "multi_doc",
            "scope_filter": {"corpus": "gov_trade"}
        }
    """
    # Check for multi-doc mode in request body
    data = request.json or {}
    mode = data.get("mode", "user_pdf")
    scope_filter = data.get("scope_filter")

    if mode == "multi_doc":
        # Multi-doc mode: create conversation with scope_filter
        conversation = Conversation.create(
            user_id=g.user.id,
            mode="multi_doc",
            pdf_id=None  # No single PDF in multi-doc mode
        )
        if scope_filter:
            conversation.set_scope_filter(scope_filter)
            conversation.save()
    else:
        # Single-doc mode: require pdf_id
        pdf_id = request.args.get("pdf_id")
        if not pdf_id:
            return jsonify({"error": "pdf_id is required for user_pdf mode"}), 400

        pdf = Pdf.find_by(id=pdf_id)
        if not pdf:
            return jsonify({"error": "PDF not found"}), 404

        conversation = Conversation.create(
            user_id=g.user.id,
            pdf_id=pdf.id,
            mode="user_pdf"
        )

    return conversation.as_dict()


@bp.route("/<string:conversation_id>/messages", methods=["POST"])
@login_required
@load_model(Conversation)
def create_message(conversation):
    """
    Send a message to a conversation and get a response.

    Request body:
        {
            "input": "User's question",
            "output_format": "text" | "structured" | "trade_compliance" (optional, default: "text"),
            "use_agent": false (optional, use agentic RAG if true)
        }

    Query params:
        stream: true/false (optional, default: false)

    Returns standardized response:
        {
            "success": true,
            "error": null,
            "message_id": "uuid",
            "role": "assistant",
            "mode": "multi_doc" | "user_pdf",
            "output_format": "text" | "structured" | "trade_compliance",
            "answer": "The response text",
            "citations": [...],
            "structured_output": {...} | null,
            "tool_calls": [...],
            "condensed_question": "..."
        }
    """
    try:
        data = request.json or {}
        user_input = data.get("input")
        output_format = data.get("output_format", "text")
        use_agent = data.get("use_agent", False)
        streaming = request.args.get("stream", "false").lower() == "true"

        if not user_input:
            return jsonify({
                "success": False,
                "error": {"code": "MISSING_INPUT", "message": "input is required"},
                "message_id": None,
                "role": "assistant",
                "mode": conversation.mode,
                "output_format": output_format,
                "answer": None,
                "citations": [],
                "structured_output": None,
                "tool_calls": [],
                "condensed_question": None
            }), 400

        # Build chat args based on conversation mode
        if conversation.mode == "multi_doc":
            metadata = Metadata(
                conversation_id=conversation.id,
                user_id=g.user.id,
                pdf_id=None
            )
            chat_args = ChatArgs(
                conversation_id=conversation.id,
                pdf_id=None,
                streaming=streaming,
                mode="multi_doc",
                scope_filter=conversation.get_scope_filter(),
                metadata=metadata
            )
        else:
            pdf = conversation.pdf
            metadata = Metadata(
                conversation_id=conversation.id,
                user_id=g.user.id,
                pdf_id=pdf.id if pdf else None
            )
            chat_args = ChatArgs(
                conversation_id=conversation.id,
                pdf_id=pdf.id if pdf else None,
                streaming=streaming,
                mode="user_pdf",
                scope_filter=None,
                metadata=metadata
            )

        # Select appropriate chat builder based on options
        if use_agent:
            chat = build_agentic_chat(chat_args, output_format=output_format)
        elif output_format == "trade_compliance":
            chat = build_trade_compliance_chat(chat_args)
        else:
            chat = build_chat(chat_args, output_format=output_format)

        if not chat:
            return jsonify({
                "success": False,
                "error": {"code": "CHAT_NOT_AVAILABLE", "message": "Chat not available"},
                "message_id": None,
                "role": "assistant",
                "mode": conversation.mode,
                "output_format": output_format,
                "answer": None,
                "citations": [],
                "structured_output": None,
                "tool_calls": [],
                "condensed_question": None
            }), 500

        if streaming:
            # Stream responses (LangGraph native streaming)
            def generate():
                for chunk in chat.stream(user_input):
                    if "answer" in chunk:
                        yield f"data: {chunk['answer']}\n\n"
            return Response(
                stream_with_context(generate()), mimetype="text/event-stream"
            )
        else:
            # Non-streaming: invoke and return standardized response
            result = chat.invoke(user_input)

            return jsonify({
                "success": True,
                "error": None,
                "message_id": str(uuid.uuid4()),
                "role": "assistant",
                "mode": conversation.mode,
                "output_format": output_format,
                "answer": result.get("answer", ""),
                "citations": result.get("citations", []),
                "structured_output": result.get("structured_output"),
                "tool_calls": result.get("tool_calls", []),
                "condensed_question": result.get("condensed_question", "")
            })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": {"code": "INTERNAL_ERROR", "message": str(e)},
            "message_id": None,
            "role": "assistant",
            "mode": conversation.mode if conversation else None,
            "output_format": output_format if 'output_format' in dir() else "text",
            "answer": None,
            "citations": [],
            "structured_output": None,
            "tool_calls": [],
            "condensed_question": None
        }), 500
