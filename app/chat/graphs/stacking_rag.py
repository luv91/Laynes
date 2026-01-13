"""
Stacking RAG Graph using LangGraph with Tools.

This is a Single Agent + Tools architecture for tariff stacking:
- Data-driven: All logic comes from database tables
- Tool-calling: Uses stacking tools to query tariff tables
- Iterative: Processes programs in filing_sequence order
- Auditable: Logs every decision with source citations

The graph follows this pattern:
1. Initialize: Get applicable programs for country/HTS
2. Process Loop: For each program, check inclusion/exclusion/composition
3. Calculate: Compute final duties
4. Generate: Create human-readable output with audit trail
"""

import json
from typing import TypedDict, List, Optional, Annotated, Sequence, Literal, Dict, Any
from datetime import date

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver

from app.chat.tools.stacking_tools import STACKING_TOOLS, get_mfn_base_rate


# ============================================================================
# Graph State
# ============================================================================

class StackingState(TypedDict):
    """
    State for the stacking graph.

    Attributes:
        messages: Conversation history
        hts_code: Input HTS code (e.g., "8544.42.9090")
        country: Country of origin (e.g., "China")
        product_description: Description for exclusion matching
        product_value: Declared value in USD
        import_date: Date of import (YYYY-MM-DD)
        materials: Material composition dict or None if unknown
        materials_needed: Whether user input is needed for materials
        programs: List of applicable programs from get_applicable_programs
        program_results: Results for each program {program_id: result_dict}
        filing_lines: Final filing lines for CBP (flattened from entries)
        decisions: Audit trail of decisions
        total_duty: Calculated total duty
        current_program_idx: Index of program being processed
        iteration: Iteration count
        final_output: Final stacking output
        awaiting_user_input: Whether we need user input
        user_question: Question to ask user
        # v4.0: Entry Slices
        entries: List of FilingEntry dicts (ACE-ready slices)
        unstacking: IEEPA unstacking audit trail
        slices: Planned slices from plan_entry_slices
        current_slice_idx: Index of slice being processed
        annex_ii_exempt: Whether HTS is Annex II exempt
        # v7.1: Quantity handling
        quantity: Piece count for the line item (duplicated across all slices)
        quantity_uom: Unit of measure for quantity (e.g., "PCS", "KG")
    """
    messages: Annotated[Sequence[BaseMessage], add_messages]
    hts_code: str
    country: str
    product_description: str
    product_value: float
    import_date: Optional[str]
    materials: Optional[Dict[str, float]]
    materials_needed: bool
    applicable_materials: Optional[List[str]]  # Dynamic list from database
    programs: List[dict]
    program_results: Dict[str, Any]
    filing_lines: List[dict]
    decisions: List[dict]
    total_duty: Optional[dict]
    current_program_idx: int
    iteration: int
    final_output: Optional[str]
    awaiting_user_input: bool
    user_question: Optional[str]
    # v4.0: Entry Slices
    entries: List[dict]
    unstacking: Optional[dict]
    slices: List[dict]
    current_slice_idx: int
    annex_ii_exempt: bool
    # v7.1: Quantity handling
    quantity: Optional[int]
    quantity_uom: Optional[str]


# ============================================================================
# Tool Map
# ============================================================================

TOOL_MAP = {t.name: t for t in STACKING_TOOLS}


# ============================================================================
# Graph Nodes
# ============================================================================

def initialize_node(state: StackingState) -> dict:
    """
    Initialize stacking by getting applicable programs.

    This is the entry point - queries the tariff_programs table
    to find all programs that might apply to this country/HTS.
    """
    hts_code = state["hts_code"]
    country = state["country"]
    import_date = state.get("import_date") or date.today().isoformat()

    # Call get_applicable_programs tool
    result = TOOL_MAP["get_applicable_programs"].invoke({
        "country": country,
        "hts_code": hts_code,
        "import_date": import_date
    })

    data = json.loads(result)
    programs = data.get("programs", [])

    # Log the decision
    decision = {
        "step": "initialize",
        "program_id": "all",
        "decision": f"Found {len(programs)} applicable programs",
        "reason": f"Queried tariff_programs for country={country}",
        "source_doc": "tariff_programs table"
    }

    return {
        "programs": programs,
        "decisions": state.get("decisions", []) + [decision],
        "import_date": import_date,
        "current_program_idx": 0
    }


def check_materials_node(state: StackingState) -> dict:
    """
    Check if material composition is needed and collect if possible.

    This node determines if we need to ask the user for material
    composition before processing Section 232 programs.
    """
    hts_code = state["hts_code"]
    product_description = state["product_description"]
    materials = state.get("materials")

    # Call ensure_materials tool
    # FIX: Check for None explicitly, not truthiness - empty dict {} is a valid "no metals" answer
    result = TOOL_MAP["ensure_materials"].invoke({
        "hts_code": hts_code,
        "product_description": product_description,
        "known_materials": json.dumps(materials) if materials is not None else None
    })

    data = json.loads(result)

    if data.get("materials_needed"):
        return {
            "materials_needed": True,
            "awaiting_user_input": True,
            "applicable_materials": data.get("applicable_materials", []),  # Pass through from ensure_materials
            "user_question": data.get("suggested_question", "What is the material composition?"),
            "decisions": state.get("decisions", []) + [{
                "step": "check_materials",
                "program_id": "section_232",
                "decision": "Materials needed",
                "reason": data.get("reason", "Material composition required"),
                "source_doc": None
            }]
        }
    else:
        # Materials known (from user input or history)
        known_materials = data.get("materials", {})
        return {
            "materials": known_materials if isinstance(known_materials, dict) else {},
            "materials_needed": False,
            "awaiting_user_input": False,
            "decisions": state.get("decisions", []) + [{
                "step": "check_materials",
                "program_id": "section_232",
                "decision": "Materials available",
                "reason": data.get("reason", "Materials known"),
                "source_doc": None
            }]
        }


def process_program_node(state: StackingState) -> dict:
    """
    Process a single program - check inclusion, exclusion, conditions.

    This is the main processing node that handles each tariff program
    in filing_sequence order.
    """
    programs = state.get("programs", [])
    idx = state.get("current_program_idx", 0)
    hts_code = state["hts_code"]
    product_description = state["product_description"]
    import_date = state.get("import_date")
    materials = state.get("materials", {})
    program_results = state.get("program_results", {})
    filing_lines = state.get("filing_lines", [])
    decisions = state.get("decisions", [])

    if idx >= len(programs):
        # All programs processed
        return {"current_program_idx": idx}

    program = programs[idx]
    program_id = program["program_id"]
    check_type = program.get("check_type")
    condition_handler = program.get("condition_handler", "none")

    result_data = {"program_id": program_id, "applies": False}

    # Step 1: Check inclusion (unless check_type is "always")
    if check_type == "hts_lookup":
        inclusion_result = TOOL_MAP["check_program_inclusion"].invoke({
            "program_id": program_id,
            "hts_code": hts_code
        })
        inclusion_data = json.loads(inclusion_result)

        decisions.append({
            "step": "check_inclusion",
            "program_id": program_id,
            "decision": "included" if inclusion_data.get("included") else "not_included",
            "reason": inclusion_data.get("reason", f"HTS lookup in {program.get('inclusion_table')}"),
            "source_doc": inclusion_data.get("source_doc")
        })

        if not inclusion_data.get("included"):
            # Not included, skip this program
            program_results[program_id] = {"applies": False, "reason": "not_included"}
            return {
                "program_results": program_results,
                "decisions": decisions,
                "current_program_idx": idx + 1
            }

        result_data.update(inclusion_data)

    elif check_type == "always":
        # Program always applies (e.g., IEEPA Fentanyl for China)
        decisions.append({
            "step": "check_inclusion",
            "program_id": program_id,
            "decision": "always_applies",
            "reason": f"{program.get('program_name')} applies to all qualifying imports",
            "source_doc": program.get("source_document")
        })
        result_data["applies"] = True

    # Step 2: Check exclusion (if applicable)
    if program.get("exclusion_table"):
        exclusion_result = TOOL_MAP["check_program_exclusion"].invoke({
            "program_id": program_id,
            "hts_code": hts_code,
            "product_description": product_description,
            "import_date": import_date
        })
        exclusion_data = json.loads(exclusion_result)

        decisions.append({
            "step": "check_exclusion",
            "program_id": program_id,
            "decision": "excluded" if exclusion_data.get("excluded") else "not_excluded",
            "reason": exclusion_data.get("reason", "Checked exclusion table"),
            "source_doc": exclusion_data.get("source_doc")
        })

        if exclusion_data.get("excluded"):
            # Product is excluded
            program_results[program_id] = {"applies": False, "reason": "excluded", "exclusion": exclusion_data}
            return {
                "program_results": program_results,
                "decisions": decisions,
                "current_program_idx": idx + 1
            }

    # Step 3: Handle conditions based on condition_handler
    if condition_handler == "handle_material_composition":
        # Section 232 - check material composition
        # Phase 6: Pass product_value for content-value-based duties
        product_value = state.get("product_value", 0)
        material_result = TOOL_MAP["check_material_composition"].invoke({
            "hts_code": hts_code,
            "materials": json.dumps(materials),
            "product_value": product_value
        })
        material_data = json.loads(material_result)

        # Find the specific material for this program
        material_name = program.get("condition_param")
        for mat in material_data.get("materials", []):
            if mat["material"] == material_name:
                result_data["material"] = material_name
                result_data["action"] = mat["action"]
                result_data["chapter_99_code"] = mat["chapter_99_code"]
                result_data["duty_rate"] = mat["duty_rate"]
                result_data["applies_to"] = mat["applies_to"]
                result_data["applies"] = True

                decisions.append({
                    "step": "check_material_composition",
                    "program_id": program_id,
                    "decision": mat["action"],
                    "reason": f"{material_name}: {mat['percentage']*100:.1f}% -> {mat['action']}",
                    "source_doc": mat.get("source_doc")
                })

                # Phase 6: Line splitting for content-value-based duties
                # When split_lines=True, generate TWO filing lines:
                # Line A: Non-material content (disclaim code, 0% duty)
                # Line B: Material content (claim code, duty on content value)
                if mat.get("split_lines") and mat.get("action") == "claim":
                    # Line A: Non-material content
                    filing_lines.append({
                        "sequence": len(filing_lines) + 1,
                        "program_id": f"{program_id}_non_content",
                        "program": f"{program.get('program_name')} - Non-{material_name.title()} Content",
                        "chapter_99_code": mat.get("disclaim_code"),
                        "action": "disclaim",
                        "duty_rate": 0.0,
                        "applies_to": "partial",
                        "material": material_name,
                        "material_percent": mat.get("percentage"),
                        "line_value": mat.get("non_content_value"),
                        "split_type": "non_material_content"
                    })

                    # Line B: Material content
                    filing_lines.append({
                        "sequence": len(filing_lines) + 1,
                        "program_id": program_id,
                        "program": f"{program.get('program_name')} - {material_name.title()} Content",
                        "chapter_99_code": mat["chapter_99_code"],
                        "action": mat["action"],
                        "duty_rate": mat["duty_rate"],
                        "applies_to": "partial",
                        "material": material_name,
                        "material_percent": mat.get("percentage"),
                        "line_value": mat.get("content_value"),
                        "material_quantity_kg": mat.get("mass_kg"),
                        "split_type": "material_content"
                    })
                else:
                    # Single line (no split or disclaim action)
                    filing_lines.append({
                        "sequence": len(filing_lines) + 1,
                        "program_id": program_id,
                        "program": program.get("program_name"),
                        "chapter_99_code": mat["chapter_99_code"],
                        "action": mat["action"],
                        "duty_rate": mat["duty_rate"],
                        "applies_to": mat["applies_to"],
                        "material": material_name
                    })
                break

        program_results[program_id] = result_data
        # Also store for dependency checking
        program_results[f"section_232_{material_name}"] = {"any_claims": result_data.get("action") == "claim"}

    elif condition_handler == "handle_dependency":
        # IEEPA Reciprocal - depends on Section 232 results
        dependency_result = TOOL_MAP["resolve_program_dependencies"].invoke({
            "program_id": program_id,
            "previous_results": json.dumps(program_results)
        })
        dependency_data = json.loads(dependency_result)

        result_data["action"] = dependency_data.get("action")
        result_data["chapter_99_code"] = dependency_data.get("chapter_99_code")
        result_data["duty_rate"] = dependency_data.get("duty_rate", 0)
        result_data["applies"] = True

        decisions.append({
            "step": "resolve_dependency",
            "program_id": program_id,
            "decision": dependency_data.get("action"),
            "reason": dependency_data.get("reason"),
            "source_doc": dependency_data.get("source_doc")
        })

        # Add filing line
        filing_lines.append({
            "sequence": len(filing_lines) + 1,
            "program_id": program_id,
            "program": program.get("program_name"),
            "chapter_99_code": dependency_data.get("chapter_99_code"),
            "action": dependency_data.get("action"),
            "duty_rate": dependency_data.get("duty_rate", 0),
            "applies_to": "full"
        })

        program_results[program_id] = result_data

    else:
        # No special condition handler (e.g., Section 301, IEEPA Fentanyl)
        # Get the output code
        output_result = TOOL_MAP["get_program_output"].invoke({
            "program_id": program_id,
            "action": "apply"
        })
        output_data = json.loads(output_result)

        if output_data.get("found"):
            result_data["action"] = "apply"
            result_data["chapter_99_code"] = output_data.get("chapter_99_code")
            result_data["duty_rate"] = output_data.get("duty_rate", 0)
            result_data["applies"] = True

            decisions.append({
                "step": "get_output",
                "program_id": program_id,
                "decision": "apply",
                "reason": f"Program applies, code: {output_data.get('chapter_99_code')}",
                "source_doc": output_data.get("source_doc")
            })

            # Add filing line
            filing_lines.append({
                "sequence": len(filing_lines) + 1,
                "program_id": program_id,
                "program": program.get("program_name"),
                "chapter_99_code": output_data.get("chapter_99_code"),
                "action": "apply",
                "duty_rate": output_data.get("duty_rate", 0),
                "applies_to": output_data.get("applies_to", "full")
            })

        program_results[program_id] = result_data

    return {
        "program_results": program_results,
        "filing_lines": filing_lines,
        "decisions": decisions,
        "current_program_idx": idx + 1
    }


def plan_slices_node(state: StackingState) -> dict:
    """
    v4.0: Plan entry slices based on materials.

    Determines how many ACE entries to create:
    - No 232 materials -> 1 slice (full_product)
    - Has 232 materials -> N+1 slices (non_metal + each material)
    """
    hts_code = state["hts_code"]
    product_value = state.get("product_value", 0)
    materials = state.get("materials", {})
    programs = state.get("programs", [])
    decisions = state.get("decisions", [])

    # Get applicable program IDs
    applicable_programs = [p.get("program_id") for p in programs]

    # Call plan_entry_slices tool
    result = TOOL_MAP["plan_entry_slices"].invoke({
        "hts_code": hts_code,
        "product_value": product_value,
        "materials": json.dumps(materials),
        "applicable_programs": json.dumps(applicable_programs)
    })

    slice_data = json.loads(result)
    slices = slice_data.get("slices", [])

    decisions.append({
        "step": "plan_slices",
        "program_id": "all",
        "decision": f"Planned {len(slices)} entry slice(s)",
        "reason": slice_data.get("reason", "Based on 232 material content"),
        "source_doc": None
    })

    return {
        "slices": slices,
        "decisions": decisions,
        "current_slice_idx": 0
    }


def check_annex_ii_node(state: StackingState) -> dict:
    """
    v4.0: Check if HTS is in Annex II (exempt from IEEPA Reciprocal).
    """
    hts_code = state["hts_code"]
    decisions = state.get("decisions", [])

    # Call check_annex_ii_exclusion tool
    result = TOOL_MAP["check_annex_ii_exclusion"].invoke({
        "hts_code": hts_code
    })

    annex_data = json.loads(result)
    is_exempt = annex_data.get("excluded", False)

    decisions.append({
        "step": "check_annex_ii",
        "program_id": "ieepa_reciprocal",
        "decision": "annex_ii_exempt" if is_exempt else "not_exempt",
        "reason": annex_data.get("reason", "Checked Annex II exclusion table"),
        "source_doc": annex_data.get("source_doc")
    })

    return {
        "annex_ii_exempt": is_exempt,
        "decisions": decisions
    }


def build_entry_stacks_node(state: StackingState) -> dict:
    """
    v4.0: Build Chapter 99 stacks for all entry slices.

    For each slice, for each program, determine the correct action/variant
    and look up the Chapter 99 code.
    """
    hts_code = state["hts_code"]
    country = state["country"]
    programs = state.get("programs", [])
    slices = state.get("slices", [])
    materials = state.get("materials", {})
    product_value = state.get("product_value", 0)
    annex_ii_exempt = state.get("annex_ii_exempt", False)
    decisions = state.get("decisions", [])
    # v7.1: Quantity handling
    quantity = state.get("quantity")
    quantity_uom = state.get("quantity_uom", "PCS")

    entries = []
    all_filing_lines = []

    # Calculate unstacking info
    metal_values = {}
    for material, value in materials.items():
        if material in ["copper", "steel", "aluminum"]:
            # Value could be percentage or dollar amount
            if isinstance(value, (int, float)):
                if value <= 1.0:  # Percentage
                    metal_values[material] = value * product_value
                else:  # Dollar amount
                    metal_values[material] = value

    remaining_value = product_value - sum(metal_values.values())

    unstacking = {
        "initial_value": product_value,
        "content_deductions": metal_values,
        "remaining_value": max(0, remaining_value),
        "note": "232 content excluded from IEEPA Reciprocal base" if metal_values else None
    }

    # Process each slice
    for slice_info in slices:
        slice_type = slice_info.get("slice_type")
        slice_value = slice_info.get("value", 0)

        entry = {
            "entry_id": slice_info.get("entry_id"),
            "slice_type": slice_type,
            "base_hts_code": hts_code,
            "country_of_origin": country,
            "line_value": slice_value,
            # v7.1: Quantity duplicated across all slices
            "quantity": quantity,
            "quantity_uom": quantity_uom if quantity is not None else None,
            "materials": slice_info.get("materials", {}),
            "stack": []
        }

        sequence = 1

        # Sort programs by filing_sequence
        sorted_programs = sorted(programs, key=lambda p: p.get("filing_sequence", 99))

        for program in sorted_programs:
            program_id = program.get("program_id")
            program_name = program.get("program_name")

            # Determine action and variant based on program type
            action = None
            variant = None
            chapter_99_code = None
            duty_rate = 0

            if program_id == "section_301":
                # Section 301 applies to all slices
                # v7.0: Get HTS-specific code from section_301_inclusions
                # v11.0: Use import_date for temporal lookup (exclusion precedence)
                action = "apply"
                import_date = state.get("import_date")
                inclusion_result = json.loads(TOOL_MAP["check_program_inclusion"].invoke({
                    "program_id": program_id,
                    "hts_code": hts_code,
                    "as_of_date": import_date
                }))
                if inclusion_result.get("included"):
                    # Use HTS-specific code from inclusion table
                    chapter_99_code = inclusion_result.get("chapter_99_code")
                    duty_rate = inclusion_result.get("duty_rate", 0.25)
                else:
                    # Fallback to program_codes table
                    output = json.loads(TOOL_MAP["get_program_output"].invoke({
                        "program_id": program_id,
                        "action": "apply",
                        "slice_type": "all"
                    }))
                    if output.get("found"):
                        chapter_99_code = output.get("chapter_99_code")
                        duty_rate = output.get("duty_rate", 0.25)

            elif program_id == "ieepa_fentanyl":
                # IEEPA Fentanyl applies to all slices
                action = "apply"
                output = json.loads(TOOL_MAP["get_program_output"].invoke({
                    "program_id": program_id,
                    "action": "apply",
                    "slice_type": "all"
                }))
                if output.get("found"):
                    chapter_99_code = output.get("chapter_99_code")
                    duty_rate = output.get("duty_rate", 0.10)

            elif program_id == "ieepa_reciprocal":
                # IEEPA Reciprocal - determine variant
                import_date = state.get("import_date")

                # Phase 11: Get article_type for Note 16 full-value exemption
                article_type = None
                hts_8digit = hts_code.replace(".", "")[:8]
                from app.web.db.models.tariff_tables import Section232Material
                from app.chat.tools.stacking_tools import get_flask_app
                app = get_flask_app()
                with app.app_context():
                    mat_232 = Section232Material.query.filter_by(hts_8digit=hts_8digit).first()
                    if mat_232:
                        article_type = getattr(mat_232, 'article_type', 'content') or 'content'

                variant_result = json.loads(TOOL_MAP["resolve_reciprocal_variant"].invoke({
                    "hts_code": hts_code,
                    "slice_type": slice_type,
                    "us_content_pct": None,
                    "import_date": import_date,
                    "article_type": article_type
                }))
                variant = variant_result.get("variant", "taxable")
                action = variant_result.get("action", "paid")

                # Use chapter_99_code and duty_rate directly from resolve_reciprocal_variant
                # This handles note16_full_exempt and other variants that may not be in program_codes table
                chapter_99_code = variant_result.get("chapter_99_code")
                duty_rate = variant_result.get("duty_rate", 0)

                # Fallback to get_program_output lookup if variant_result didn't provide code
                if not chapter_99_code:
                    lookup_slice = slice_type if variant == "metal_exempt" else slice_type
                    output = json.loads(TOOL_MAP["get_program_output"].invoke({
                        "program_id": program_id,
                        "action": action,
                        "variant": variant,
                        "slice_type": lookup_slice
                    }))
                    # Fallback to "all" if not found
                    if not output.get("found") and lookup_slice != "all":
                        output = json.loads(TOOL_MAP["get_program_output"].invoke({
                            "program_id": program_id,
                            "action": action,
                            "variant": variant,
                            "slice_type": "all"
                        }))
                    if output.get("found"):
                        chapter_99_code = output.get("chapter_99_code")
                        duty_rate = output.get("duty_rate", 0)

            elif program_id.startswith("section_232_"):
                # Section 232 - first check if HTS is on the 232 inclusion list
                material = program_id.replace("section_232_", "")

                # Check if HTS is on the 232 list for this metal
                inclusion_result = json.loads(TOOL_MAP["check_program_inclusion"].invoke({
                    "program_id": program_id,
                    "hts_code": hts_code
                }))

                if not inclusion_result.get("included"):
                    # HTS not on 232 list for this metal - skip entirely
                    continue

                # v7.0: Get disclaim_behavior from TariffProgram table
                from app.chat.tools.stacking_tools import get_disclaim_behavior
                disclaim_behavior = get_disclaim_behavior(program_id)

                # HTS IS on the 232 list - determine claim vs disclaim based on slice type
                expected_slice = f"{material}_slice"
                if slice_type == expected_slice:
                    # This is the claim slice for this metal
                    action = "claim"
                    # v7.0: Use HTS-specific claim_code from inclusion data
                    chapter_99_code = inclusion_result.get("claim_code")
                    duty_rate = inclusion_result.get("duty_rate", 0)
                else:
                    # This is NOT the claim slice for this metal
                    # v7.0: Apply disclaim_behavior
                    if disclaim_behavior == "required":
                        # Copper: Must include disclaim code in OTHER slices
                        action = "disclaim"
                        chapter_99_code = inclusion_result.get("disclaim_code")
                        duty_rate = 0
                    elif disclaim_behavior == "omit":
                        # Steel/Aluminum: Omit entirely when not claimed (no disclaim line)
                        continue  # Skip this program for this slice
                    else:
                        # Default: use disclaim (backwards compatibility)
                        action = "disclaim"
                        chapter_99_code = inclusion_result.get("disclaim_code")
                        duty_rate = 0

            if chapter_99_code:
                filing_line = {
                    "sequence": sequence,
                    "chapter_99_code": chapter_99_code,
                    "program": program_name,
                    "program_id": program_id,
                    "action": action,
                    "variant": variant,
                    "duty_rate": duty_rate,
                    "applies_to": "full" if not program_id.startswith("section_232_") else "partial",
                    "material": program.get("condition_param") if program_id.startswith("section_232_") else None
                }
                entry["stack"].append(filing_line)
                all_filing_lines.append({**filing_line, "slice_type": slice_type, "line_value": slice_value})
                sequence += 1

        # Add base HTS code as final line (CBP/ACE requirement)
        # Per Phoebe's guidance: original HTS must appear as last line in every entry stack
        mfn_rate = get_mfn_base_rate(hts_code)
        base_hts_line = {
            "sequence": sequence,
            "chapter_99_code": None,  # Not a Chapter 99 code
            "hts_code": hts_code,     # The base HTS code
            "program": "Base HTS Classification",
            "program_id": "base_hts",
            "action": "classify",
            "variant": None,
            "duty_rate": mfn_rate,
            "applies_to": "full",
            "material": None,
            "is_base_hts": True  # Flag to identify this line
        }
        entry["stack"].append(base_hts_line)
        all_filing_lines.append({**base_hts_line, "slice_type": slice_type, "line_value": slice_value})

        entries.append(entry)

    return {
        "entries": entries,
        "filing_lines": all_filing_lines,
        "unstacking": unstacking,
        "decisions": decisions
    }


def calculate_duties_node(state: StackingState) -> dict:
    """
    Calculate total duties at PRODUCT level (not per-slice).

    v4.0: Entry slices are for ACE filing display only.
    Duty calculation uses product-level programs:
    - Section 301: 25% on full product value
    - IEEPA Fentanyl: 10% on full product value
    - 232 programs: duty on content VALUE (claim lines only)
    - IEEPA Reciprocal: 10% on remaining value (after 232 deductions)

    v5.0: Now passes country and hts_code for dynamic rate lookups:
    - EU countries: 15% ceiling rule for IEEPA Reciprocal
    - UK exception: 232 Steel/Aluminum stays at 25%
    - Formula support for country-specific rates
    """
    entries = state.get("entries", [])
    product_value = state.get("product_value", 0)
    materials = state.get("materials", {})
    unstacking = state.get("unstacking", {})
    # v5.0: Get country and hts_code for dynamic rate lookups
    country = state.get("country", "")
    hts_code = state.get("hts_code", "")
    import_date = state.get("import_date")

    if not entries:
        return {
            "total_duty": {
                "product_value": product_value,
                "total_duty_percent": 0,
                "total_duty_amount": 0,
                "effective_rate": 0,
                "breakdown": [],
                "unstacking": unstacking
            }
        }

    # v4.0: Build product-level filing lines for duty calculation
    # Each program appears ONCE, not repeated per slice
    product_level_lines = []
    seen_programs = set()

    for entry in entries:
        slice_type = entry.get("slice_type")
        line_value = entry.get("line_value", 0)

        for line in entry.get("stack", []):
            program_id = line.get("program_id")
            action = line.get("action")

            # Skip if we've already processed this program (for non-232)
            # For 232 programs, only process the CLAIM line (not disclaims)
            if program_id.startswith("section_232_"):
                if action == "disclaim":
                    continue  # Skip disclaims - they don't contribute duty
                # For claim lines, use the slice value as line_value
                product_level_lines.append({
                    **line,
                    "line_value": line_value,  # Material content value
                    "material": program_id.replace("section_232_", "")
                })
            elif program_id == "ieepa_reciprocal":
                # Only process if paid (taxable on non_metal slice)
                if action == "paid" and program_id not in seen_programs:
                    seen_programs.add(program_id)
                    product_level_lines.append({
                        **line,
                        "line_value": line_value  # Remaining value
                    })
            else:
                # Section 301, IEEPA Fentanyl - process once at full product value
                if program_id not in seen_programs:
                    seen_programs.add(program_id)
                    product_level_lines.append({
                        **line,
                        "line_value": product_value  # Full product value
                    })

    # Call calculate_duties tool with product-level lines
    # v5.0: Pass country and hts_code for dynamic rate lookups
    result = TOOL_MAP["calculate_duties"].invoke({
        "filing_lines": json.dumps(product_level_lines),
        "product_value": product_value,
        "materials": json.dumps(materials),
        "country": country,  # v5.0: For country-specific rates
        "hts_code": hts_code,  # v5.0: For MFN base rate lookup
        "import_date": import_date  # v5.0: For time-bounded rate lookups
    })

    duty_data = json.loads(result)

    # Add unstacking to duty data (override with graph-calculated values)
    duty_data["unstacking"] = unstacking

    return {
        "total_duty": duty_data,
        "decisions": state.get("decisions", []) + [{
            "step": "calculate_duties",
            "program_id": "all",
            "decision": f"Total duty: ${duty_data.get('total_duty_amount', 0):.2f}",
            "reason": f"Effective rate: {duty_data.get('effective_rate', 0)*100:.2f}%",
            "source_doc": "duty_rules table"
        }]
    }


def generate_output_node(state: StackingState) -> dict:
    """
    Generate human-readable output with explanation and audit trail.
    """
    hts_code = state["hts_code"]
    country = state["country"]
    product_description = state["product_description"]
    product_value = state.get("product_value", 0)
    materials = state.get("materials", {})
    filing_lines = state.get("filing_lines", [])
    decisions = state.get("decisions", [])
    total_duty = state.get("total_duty", {})

    # Build the output string
    output_parts = []

    # Header
    output_parts.append(f"## Tariff Stacking Result for HTS {hts_code}")
    output_parts.append(f"**Country of Origin:** {country}")
    output_parts.append(f"**Product:** {product_description}")
    output_parts.append(f"**Product Value:** ${product_value:,.2f}")
    if materials:
        mat_str = ", ".join([f"{k}: {v*100:.1f}%" for k, v in materials.items()])
        output_parts.append(f"**Material Composition:** {mat_str}")
    output_parts.append("")

    # Filing Lines
    output_parts.append("### CBP Filing Lines")
    output_parts.append("```")
    output_parts.append(hts_code)
    for line in filing_lines:
        action_display = line.get("action", "apply")
        rate_display = f" ({line.get('duty_rate', 0)*100:.1f}%)" if line.get("duty_rate") else ""
        output_parts.append(f"├── {line.get('chapter_99_code')} → {line.get('program')} [{action_display}]{rate_display}")
    output_parts.append("```")
    output_parts.append("")

    # Duty Summary
    output_parts.append("### Duty Calculation")
    output_parts.append(f"- **Product Value:** ${product_value:,.2f}")
    output_parts.append(f"- **Total Duty:** ${total_duty.get('total_duty_amount', 0):,.2f}")
    output_parts.append(f"- **Effective Rate:** {total_duty.get('effective_rate', 0)*100:.2f}%")
    output_parts.append("")

    # Breakdown
    if total_duty.get("breakdown"):
        output_parts.append("### Duty Breakdown")
        for b in total_duty.get("breakdown", []):
            if b.get("action") not in ["disclaim", "skip"]:
                output_parts.append(f"- **{b.get('program_id')}:** ${b.get('duty_amount', 0):.2f} ({b.get('calculation')})")
        output_parts.append("")

    # Phase 6.5: IEEPA Unstacking Info
    if total_duty.get("unstacking"):
        unstacking = total_duty["unstacking"]
        output_parts.append("### IEEPA Unstacking (Phase 6.5)")
        output_parts.append(f"- **Initial Value:** ${unstacking.get('initial_value', 0):,.2f}")
        output_parts.append("- **232 Content Deductions:**")
        for material, value in unstacking.get("content_deductions", {}).items():
            output_parts.append(f"  - {material.title()}: -${value:,.2f}")
        output_parts.append(f"- **Remaining Value (IEEPA Base):** ${unstacking.get('remaining_value', 0):,.2f}")
        output_parts.append(f"- *Note: {unstacking.get('note', '')}*")
        output_parts.append("")

    # v5.0: Country-Specific Rate Metadata
    if total_duty.get("v5_metadata"):
        v5_meta = total_duty["v5_metadata"]
        output_parts.append("### Rate Lookup Details (v5.0)")
        output_parts.append(f"- **Country Group:** {v5_meta.get('country_group', 'default')}")
        if v5_meta.get("mfn_base_rate") is not None:
            output_parts.append(f"- **MFN Base Rate:** {v5_meta.get('mfn_base_rate')*100:.1f}%")
        if v5_meta.get("rate_sources"):
            output_parts.append("- **Rate Sources:**")
            for prog_id, source in v5_meta.get("rate_sources", {}).items():
                output_parts.append(f"  - {prog_id}: {source}")
        output_parts.append(f"- **Rates As Of:** {v5_meta.get('rates_as_of', 'today')}")
        output_parts.append("")

    # Decision Audit Trail
    output_parts.append("### Decision Audit Trail")
    for d in decisions:
        output_parts.append(f"- **{d.get('step')}** ({d.get('program_id')}): {d.get('decision')}")
        if d.get("source_doc"):
            output_parts.append(f"  - Source: {d.get('source_doc')}")

    final_output = "\n".join(output_parts)

    return {
        "final_output": final_output,
        "messages": [AIMessage(content=final_output)]
    }


# ============================================================================
# Routing Functions
# ============================================================================

def should_check_materials(state: StackingState) -> Literal["check_materials", "process_programs"]:
    """Determine if we need to check materials first."""
    programs = state.get("programs", [])

    # Check if any Section 232 programs are in the list
    has_232 = any(p.get("condition_handler") == "handle_material_composition" for p in programs)

    if has_232 and not state.get("materials"):
        return "check_materials"
    return "process_programs"


def should_continue_processing(state: StackingState) -> Literal["process_program", "calculate", "await_input"]:
    """Determine next step in processing loop."""
    if state.get("awaiting_user_input"):
        return "await_input"

    programs = state.get("programs", [])
    idx = state.get("current_program_idx", 0)

    if idx < len(programs):
        return "process_program"
    return "calculate"


# ============================================================================
# Graph Builder
# ============================================================================

def should_use_v4_flow(state: StackingState) -> Literal["v4_flow", "legacy_flow"]:
    """Determine if we should use v4.0 entry slices flow."""
    # v4.0 flow is the default now
    return "v4_flow"


def build_stacking_graph(checkpointer=None):
    """
    Build the stacking graph.

    v4.0 Flow:
    START -> initialize -> check_materials -> plan_slices -> check_annex_ii -> build_entry_stacks -> calculate -> generate -> END

    Legacy Flow (deprecated):
    START -> initialize -> (check_materials?) -> process_loop -> calculate -> generate -> END

    Args:
        checkpointer: LangGraph checkpointer for memory persistence

    Returns:
        Compiled LangGraph graph
    """
    workflow = StateGraph(StackingState)

    # Add nodes
    workflow.add_node("initialize", initialize_node)
    workflow.add_node("check_materials", check_materials_node)
    workflow.add_node("process_program", process_program_node)  # Legacy
    workflow.add_node("plan_slices", plan_slices_node)  # v4.0
    workflow.add_node("check_annex_ii", check_annex_ii_node)  # v4.0
    workflow.add_node("build_entry_stacks", build_entry_stacks_node)  # v4.0
    workflow.add_node("calculate", calculate_duties_node)
    workflow.add_node("generate", generate_output_node)

    # Add edges
    workflow.add_edge(START, "initialize")

    # After initialize, check if we need materials
    workflow.add_conditional_edges(
        "initialize",
        should_check_materials,
        {
            "check_materials": "check_materials",
            "process_programs": "plan_slices"  # v4.0: Go to plan_slices instead
        }
    )

    # After check_materials, go to v4.0 flow
    workflow.add_conditional_edges(
        "check_materials",
        should_continue_processing,
        {
            "process_program": "plan_slices",  # v4.0: Go to plan_slices
            "await_input": END,  # Will resume with user input
            "calculate": "calculate"
        }
    )

    # v4.0 flow: plan_slices -> check_annex_ii -> build_entry_stacks -> calculate
    workflow.add_edge("plan_slices", "check_annex_ii")
    workflow.add_edge("check_annex_ii", "build_entry_stacks")
    workflow.add_edge("build_entry_stacks", "calculate")

    # Legacy process loop (kept for backwards compatibility)
    workflow.add_conditional_edges(
        "process_program",
        should_continue_processing,
        {
            "process_program": "process_program",
            "calculate": "calculate",
            "await_input": END
        }
    )

    # After calculate, generate output
    workflow.add_edge("calculate", "generate")
    workflow.add_edge("generate", END)

    # Use provided checkpointer or default to MemorySaver
    if checkpointer is None:
        checkpointer = MemorySaver()

    return workflow.compile(checkpointer=checkpointer)


# ============================================================================
# High-Level Wrapper
# ============================================================================

class StackingRAG:
    """
    High-level wrapper for the stacking RAG graph.

    Provides tariff stacking calculation with data-driven logic.
    """

    def __init__(self, conversation_id: str, checkpointer=None):
        """
        Initialize the stacking RAG.

        Args:
            conversation_id: Unique ID for this conversation
            checkpointer: Optional custom checkpointer
        """
        self.conversation_id = conversation_id
        self.graph = build_stacking_graph(checkpointer=checkpointer)
        self.config = {"configurable": {"thread_id": conversation_id}}

    def calculate_stacking(
        self,
        hts_code: str,
        country: str,
        product_description: str,
        product_value: float,
        materials: Optional[Dict[str, float]] = None,
        import_date: Optional[str] = None,
        quantity: Optional[int] = None,
        quantity_uom: Optional[str] = "PCS"
    ) -> dict:
        """
        Calculate tariff stacking for a product.

        Args:
            hts_code: The 10-digit HTS code (e.g., "8544.42.9090")
            country: Country of origin (e.g., "China")
            product_description: Description for exclusion matching
            product_value: Declared value in USD
            materials: Material composition dict (e.g., {"copper": 0.05, "steel": 0.20})
                       v4.0: Can also be content VALUES (e.g., {"copper": 3000.0})
            import_date: Date of import (YYYY-MM-DD), defaults to today
            quantity: Piece count for the line item (v7.1, duplicated across all slices)
            quantity_uom: Unit of measure (e.g., "PCS", "KG"), defaults to "PCS"

        Returns:
            Dict with stacking results including:
            - entries: List[FilingEntry] (v4.0 ACE entry slices)
            - filing_lines: Flattened list of all stack lines
            - total_duty: Duty calculation with unstacking info
            - unstacking: IEEPA unstacking audit trail (v4.0)
            - decisions: Audit trail
            - programs: Applicable programs

        Raises:
            ValueError: If sum of material values exceeds product_value
        """
        # v7.1: Validate material allocation
        if materials:
            material_sum = sum(materials.values())
            if material_sum > product_value:
                raise ValueError(
                    f"Material values (${material_sum:.2f}) exceed product value (${product_value:.2f}). "
                    f"Sum of material allocations cannot exceed total product value."
                )
        result = self.graph.invoke(
            {
                "messages": [],
                "hts_code": hts_code,
                "country": country,
                "product_description": product_description,
                "product_value": product_value,
                "import_date": import_date,
                "materials": materials,
                "materials_needed": False,
                "applicable_materials": None,  # Populated by check_materials_node
                "programs": [],
                "program_results": {},
                "filing_lines": [],
                "decisions": [],
                "total_duty": None,
                "current_program_idx": 0,
                "iteration": 0,
                "final_output": None,
                "awaiting_user_input": False,
                "user_question": None,
                # v4.0: Entry Slices
                "entries": [],
                "unstacking": None,
                "slices": [],
                "current_slice_idx": 0,
                "annex_ii_exempt": False,
                # v7.1: Quantity handling
                "quantity": quantity,
                "quantity_uom": quantity_uom
            },
            config=self.config
        )

        total_duty = result.get("total_duty") or {}

        return {
            "output": result.get("final_output", ""),
            # v4.0: ACE Entry Slices
            "entries": result.get("entries", []),
            # Flattened filing lines (backwards compatible)
            "filing_lines": result.get("filing_lines", []),
            "total_duty": total_duty,
            # v4.0: Unstacking info (also in total_duty for compatibility)
            "unstacking": result.get("unstacking") or total_duty.get("unstacking", {}),
            "decisions": result.get("decisions", []),
            "programs": result.get("programs", []),
            "awaiting_user_input": result.get("awaiting_user_input", False),
            "user_question": result.get("user_question"),
            # Dynamic materials from database (no hardcoding)
            "applicable_materials": result.get("applicable_materials", [])
        }

    def continue_with_materials(self, materials: Dict[str, float]) -> dict:
        """
        Continue calculation after user provides material composition.

        Args:
            materials: Material composition dict (e.g., {"copper": 3000, "steel": 1000})

        Returns:
            Updated stacking results with v4.0 entry slices

        Raises:
            ValueError: If sum of material values exceeds product_value
        """
        # Get current state and continue
        current_state = self.graph.get_state(self.config)
        product_value = current_state.values.get("product_value", 0)

        # v7.1: Validate material allocation
        if materials:
            material_sum = sum(materials.values())
            if material_sum > product_value:
                raise ValueError(
                    f"Material values (${material_sum:.2f}) exceed product value (${product_value:.2f}). "
                    f"Sum of material allocations cannot exceed total product value."
                )

        # Update with materials and resume
        result = self.graph.invoke(
            {
                **current_state.values,
                "materials": materials,
                "materials_needed": False,
                "awaiting_user_input": False
            },
            config=self.config
        )

        total_duty = result.get("total_duty") or {}

        return {
            "output": result.get("final_output", ""),
            # v4.0: ACE Entry Slices
            "entries": result.get("entries", []),
            # Flattened filing lines (backwards compatible)
            "filing_lines": result.get("filing_lines", []),
            "total_duty": total_duty,
            # v4.0: Unstacking info
            "unstacking": result.get("unstacking") or total_duty.get("unstacking", {}),
            "decisions": result.get("decisions", []),
            "programs": result.get("programs", [])
        }
