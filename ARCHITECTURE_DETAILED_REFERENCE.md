# Lanes Architecture - Detailed Reference & Line-by-Line Analysis

This document provides detailed code references, line numbers, and specific implementation details for the Lanes tariff compliance system.

---

## 1. TARIFF STACKING CALCULATION - DETAILED FLOW

### 1.1 Tool Call Sequence (with line numbers)

**File:** `app/chat/tools/stacking_tools.py`

```
CALL CHAIN WITH LINE NUMBERS:
┌─────────────────────────────────────────────────────────────┐
│ get_applicable_programs() (lines 1076-1146)               │
│ • Input: country, hts_code, import_date                   │
│ • Query: TariffProgram.query.filter_by(country=...) +     │
│          effective_date <= import_date                     │
│ • Output: ["section_301", "ieepa_fentanyl", ...]          │
│ • Decision logged: line 1135-1145                          │
└────────────────────┬────────────────────────────────────────┘
                     │
    FOR EACH PROGRAM (in filing_sequence order):
    │
    ├─ check_program_inclusion() (lines 1147-1355)
    │  ├─ Temporal lookup: Section301Rate.get_rate_as_of()  │
    │  │  (lines 1200-1220)                                 │
    │  ├─ Validates temporal window: effective_start <=      │
    │  │  check_date < effective_end (lines 1207-1208)      │
    │  ├─ Role precedence: exclusions > impose codes         │
    │  │  (lines 1226-1240)                                 │
    │  ├─ Semiconductors: evaluate_semiconductor_predicates()│
    │  │  (lines 1295-1330) for technical attributes        │
    │  └─ Output: {"included": bool, "code": "9903.XX.XX"}  │
    │
    ├─ check_program_exclusion() (lines 1356-1457)
    │  ├─ Query: Section301Exclusion.query.filter_by(      │
    │  │          hts_8digit=..., effective_date<=...)      │
    │  │  (lines 1385-1405)                                 │
    │  ├─ Semantic match: product_description vs            │
    │  │  exclusion_description (lines 1410-1440)           │
    │  └─ Output: {"excluded": bool, "reason": str}         │
    │
    ├─ check_material_composition() (lines 1497-1647)
    │  ├─ Query: Section232Material.query.filter_by(        │
    │  │          hts_8digit=...) (lines 1550-1560)         │
    │  ├─ Evaluate material percentages (lines 1575-1620):  │
    │  │  material_value / product_value >= min_percent     │
    │  ├─ Retrieve claim/disclaim codes:                    │
    │  │  claim_code = material.claim_code (line 1600)      │
    │  │  disclaim_code = material.disclaim_code (line 1601)│
    │  └─ Phase 6: Convert % to $: content_value =         │
    │     material_pct * product_value (lines 1630-1640)    │
    │
    ├─ resolve_program_dependencies() (lines 1648-1735)
    │  ├─ Check: TariffProgram.condition_handler (line 1680)│
    │  ├─ If 'handle_dependency': check condition_param     │
    │  │  (lines 1690-1710)                                 │
    │  ├─ Example: IEEPA depends on section_232 (line 1705) │
    │  └─ Output: {"skip": bool, "reason": str}             │
    │
    └─ get_program_output() (lines 1736-1811)
       ├─ Query: ProgramCode.query.filter_by(              │
       │          program_id=..., action=...,               │
       │          variant=..., slice_type=...)              │
       │  (lines 1760-1800)                                 │
       ├─ v7.0: Check TariffProgram.disclaim_behavior:     │
       │        'required', 'omit', 'none' (line 1785)      │
       └─ Output: {"code": "9903.XX.XX", "rate": float}     │
```

### 1.2 Duty Calculation (Phase 6 & 6.5)

**File:** `app/chat/tools/stacking_tools.py` (lines 1834-2200)

```python
def calculate_duties(filing_lines, product_value, materials, ...):
    """
    PHASE 6: Content-Value-Based Duties
    PHASE 6.5: IEEPA Unstacking
    v5.0: Country-Specific Rates
    """

    # Line 1877-1894: Parse inputs
    lines = json.loads(filing_lines)
    composition = json.loads(materials) or {}
    check_date = date.fromisoformat(import_date) or date.today()

    # Line 1902-1906: PHASE 6.5 SETUP - Unstacking tracking
    remaining_value = product_value              # Start with full value
    content_deductions = {}                       # Track what was deducted
    processed_materials = set()                   # Prevent double-subtraction

    # Line 1908: Main loop - FOR EACH LINE IN FILING_LINES
    for line in lines:
        program_id = line.get("program_id")
        action = line.get("action")
        duty_rate = line.get("duty_rate", 0)
        material = line.get("material")

        # Line 1914-1924: v5.0 - Country-Specific Rate Lookup
        # EXCEPT Section 301 (uses HTS-specific rates only)
        if country and hts_code and program_id != "section_301":
            dynamic_rate, rate_source = get_rate_for_program(
                program_id, country, hts_code, check_date
            )
            if rate_source != "no_rate_found":
                duty_rate = dynamic_rate
                rate_sources[program_id] = rate_source

        # Line 1926-1939: Get duty rule
        rule = DutyRule.query.filter_by(program_id=program_id).first()
        calculation_type = rule.calculation_type if rule else "additive"
        base_on = rule.base_on if rule else "product_value"
        content_key = rule.content_key if rule else None
        base_effect = rule.base_effect if rule else None  # PHASE 6.5

        # Line 1942-1971: CALCULATE DUTY BASED ON BASE_ON

        if action in ["disclaim", "skip"]:
            # Line 1948-1950
            duty_amount = 0.0

        elif base_on == "product_value":
            # Line 1952-1955: Standard - full product
            duty_amount = product_value * duty_rate
            base_value = product_value

        elif base_on == "remaining_value":
            # Line 1957-1970: PHASE 6.5 - IEEPA uses remaining after 232
            # Check for line_value from entry slice (Phase 4.0)
            line_value_from_line = line.get("line_value")
            if line_value_from_line is not None and line_value_from_line > 0:
                # Use slice value directly
                duty_amount = line_value_from_line * duty_rate
                base_value = line_value_from_line
                value_source = "from_entry_slice"
            else:
                # Fall back to calculated remaining_value
                duty_amount = remaining_value * duty_rate
                base_value = remaining_value
                value_source = "remaining_after_232"

        elif base_on == "content_value" and content_key:
            # Line 1972-2030: PHASE 6 - Content-value-based (232)
            line_value_from_line = line.get("line_value")
            if line_value_from_line is not None and line_value_from_line > 0:
                # Use slice value for this material
                content_value = line_value_from_line
                material_percent = content_value / product_value
                value_source = "from_entry_slice"
            else:
                # Fall back to looking up material composition
                if isinstance(composition, dict):
                    if content_key in composition:
                        # Handle both % and $ formats
                        val = composition[content_key]
                        if isinstance(val, dict):
                            content_value = val.get("value", val.get("percentage", 0) * product_value)
                        else:
                            # Assume $ if numeric
                            content_value = float(val)
                    else:
                        content_value = 0
                        fallback = True  # Will use product_value as fallback

                # Phase 6 fallback: if content unknown, use full product
                if content_value is None or content_value == 0:
                    if fallback_base_on == "product_value":
                        duty_amount = product_value * duty_rate
                        base_value = product_value
                        value_source = "fallback_to_product"
                else:
                    duty_amount = content_value * duty_rate
                    base_value = content_value
                    value_source = "from_material_composition"

        # Line 2040-2080: PHASE 6.5 - Update remaining_value for IEEPA
        # 232 programs subtract from remaining if base_effect='subtract_from_remaining'
        if base_effect == "subtract_from_remaining" and content_value > 0:
            if material not in processed_materials:
                # Track deduction
                content_deductions[material] = content_value
                processed_materials.add(material)
                # Reduce remaining_value
                remaining_value -= content_value

        # Line 2085-2100: ADD DUTIES
        total_duty_percent += duty_rate
        total_duty_amount += duty_amount

        # Add to breakdown for audit trail
        breakdown.append({
            "program": program_id,
            "action": action,
            "material": material,
            "base_value": base_value,
            "value_source": value_source,
            "rate": duty_rate,
            "rate_source": rate_source,
            "amount": duty_amount
        })

    # Line 2100-2150: CALCULATE EFFECTIVE RATE
    # Effective rate = total_duty / product_value (NOT sum of rates)
    effective_rate = (total_duty_amount / product_value) if product_value > 0 else 0

    # Line 2150-2200: BUILD RESPONSE
    return json.dumps({
        "total_duty_amount": total_duty_amount,
        "total_duty_percent": total_duty_percent,
        "effective_rate": effective_rate,
        "breakdown": breakdown,
        "unstacking": {
            "232_content_value": sum(content_deductions.values()),
            "remaining_value": remaining_value,
            "reciprocal_applies_to": remaining_value
        },
        "rate_sources": rate_sources
    })
```

### 1.3 Material Composition Evaluation

**File:** `app/chat/tools/stacking_tools.py` (lines 1497-1647)

```python
def check_material_composition(hts_code, materials, product_value):
    """
    Evaluates if material percentages meet Section 232 thresholds.
    Returns claim/disclaim codes per material.
    """

    # Line 1550-1570: Load material definitions from database
    material_records = Section232Material.query.filter_by(
        hts_8digit=hts_code[:8]
    ).all()

    if not material_records:
        return json.dumps({
            "error": f"No material records for {hts_code}",
            "material_claims": {},
            "fallback": False
        })

    # Line 1575-1620: For each material in composition
    material_claims = {}
    split_lines = []

    for material_record in material_records:
        material_type = material_record.material_type  # copper/steel/aluminum
        min_threshold = material_record.min_percent_threshold  # e.g., 0.05

        # Get material amount from user input
        if materials and material_type in materials:
            val = materials[material_type]
            if isinstance(val, dict):
                material_pct = val.get("percentage", 0)
                material_value = val.get("value", 0)
            else:
                # Assume percentage if numeric < 1, else $
                material_pct = float(val) if float(val) < 1 else float(val) / product_value
                material_value = material_pct * product_value
        else:
            material_pct = 0
            material_value = 0

        # Line 1600-1610: Check threshold
        if material_pct >= min_threshold:
            # CLAIM the duty code
            material_claims[material_type] = {
                "action": "claim",
                "code": material_record.claim_code,
                "percent": material_pct,
                "value": material_value,
                "threshold_met": True
            }
            split_lines.append({
                "material": material_type,
                "slice_type": f"{material_type}_slice",
                "value": material_value,
                "code": material_record.claim_code
            })
        else:
            # DISCLAIM the duty code
            material_claims[material_type] = {
                "action": "disclaim",
                "code": material_record.disclaim_code,
                "percent": material_pct,
                "value": material_value,
                "threshold_met": False
            }
            split_lines.append({
                "material": material_type,
                "slice_type": f"{material_type}_slice_disclaim",
                "value": 0,  # Don't allocate value if disclaimed
                "code": material_record.disclaim_code
            })

    # Line 1630-1647: Build response
    return json.dumps({
        "material_claims": material_claims,
        "split_lines": split_lines,
        "fallback": False,
        "materials_processed": list(material_claims.keys()),
        "total_material_value": sum(v.get("value", 0) for v in material_claims.values())
    })
```

---

## 2. DATABASE SCHEMA - DETAILED

### 2.1 Temporal Rate Lookup Pattern

**File:** `app/web/db/models/tariff_tables.py` (lines 131-280)

```python
class Section301Rate(BaseModel):
    """Temporal rates for Section 301 tariffs."""

    # KEY FIELDS FOR TEMPORAL LOOKUP
    hts_8digit = db.Column(db.String(10), index=True)  # First 8 digits
    chapter_99_code = db.Column(db.String(16))         # Filing code
    duty_rate = db.Column(db.Numeric(5, 4))            # Rate (0-1.00)

    # TEMPORAL VALIDITY
    effective_start = db.Column(db.Date)               # Inclusive
    effective_end = db.Column(db.Date, nullable=True)  # Exclusive (NULL = active)

    # DATASET VERSIONING (v22.0)
    dataset_tag = db.Column(db.String(32), index=True)    # "FR_2018", "USITC_CH99_CURRENT"
    is_archived = db.Column(db.Boolean, default=False)    # Archived versions

    # ROLE-BASED PRECEDENCE
    role = db.Column(db.String(16), default='impose')    # 'impose' or 'exclude'

    # AUDIT TRAIL
    supersedes_id = db.Column(db.Integer, db.ForeignKey('section_301_rates.id'))
    superseded_by_id = db.Column(db.Integer, db.ForeignKey('section_301_rates.id'))
    source_doc = db.Column(db.String(256))
    created_by = db.Column(db.String(64))

    @classmethod
    def get_rate_as_of(cls, hts_8digit, as_of_date):
        """
        Get rate applicable on a specific date.

        QUERY LOGIC (lines 246-279):
        1. Base filter:
           - hts_8digit = X
           - effective_start <= as_of_date
           - effective_end IS NULL OR effective_end > as_of_date

        2. Precedence:
           a) Active datasets first (is_archived=False OR NULL)
           b) Exclusions before impose codes (role='exclude' → 0, else 1)
           c) Most recent first (effective_start DESC)

        3. Fallback to archived datasets if needed
        """
        from sqlalchemy import or_, case

        # BASE TEMPORAL FILTER
        temporal_filter = [
            cls.hts_8digit == hts_8digit,
            cls.effective_start <= as_of_date,
            or_(
                cls.effective_end.is_(None),
                cls.effective_end > as_of_date
            )
        ]

        # TIER 1: ACTIVE DATASETS
        result = cls.query.filter(
            *temporal_filter,
            or_(cls.is_archived == False, cls.is_archived.is_(None))
        ).order_by(
            # Role precedence: exclusions (0) > impose (1)
            case((cls.role == 'exclude', 0), else_=1),
            # Temporal: most recent first
            cls.effective_start.desc()
        ).first()

        if result:
            return result

        # TIER 2: ARCHIVED DATASETS (fallback)
        return cls.query.filter(
            *temporal_filter,
            cls.is_archived == True
        ).order_by(
            case((cls.role == 'exclude', 0), else_=1),
            cls.effective_start.desc()
        ).first()
```

### 2.2 Country-Group-Specific Rates (EU Formula)

**File:** `app/web/db/models/tariff_tables.py` (lines 1550-1650)

```python
class ProgramRate(BaseModel):
    """Country-group-specific rates with formula support."""

    program_id = db.Column(db.String(64))        # "ieepa_reciprocal"
    country_group = db.Column(db.String(64))     # "EU", "UK", "CN"
    chapter_99_code = db.Column(db.String(16))   # "9903.01.25"
    duty_rate = db.Column(db.Numeric(5, 4))      # Base rate (0.10 for 10%)

    # FORMULA SUPPORT (v5.0)
    formula = db.Column(db.String(256))          # "15% - MFN", "25%", etc.
    effective_date = db.Column(db.Date)
    expiration_date = db.Column(db.Date, nullable=True)
```

**EU 15% Ceiling Calculation (stacking_tools.py, lines 900-950):**

```python
def get_rate_for_program(program_id, country, hts_code, check_date):
    """
    Resolves country-specific rates, including formula support.

    LOGIC FOR EU 15% CEILING:
    1. Get country group: normalize("Germany") → "EU"
    2. Query ProgramRate for (program_id, country_group="EU")
    3. Check if formula field exists
    4. If formula = "15% - MFN":
       a) Get MFN rate: get_mfn_base_rate(hts_code)
       b) Calculate: duty_rate = max(0, 0.15 - mfn_rate)
       c) Example: MFN=0.05 → duty_rate = 10%
    5. Return (duty_rate, source="formula")
    """

    # Line 900-920: Get country group
    country_group = get_country_group(country, check_date)

    # Line 920-950: Query program rate
    program_rate = ProgramRate.query.filter_by(
        program_id=program_id,
        country_group=country_group,
        effective_date <= check_date
    ).filter(
        or_(
            ProgramRate.expiration_date.is_(None),
            ProgramRate.expiration_date > check_date
        )
    ).first()

    if not program_rate:
        return (None, "no_rate_found")

    # Line 950-970: Handle formula
    if program_rate.formula and "-" in program_rate.formula:
        # Extract formula: "15% - MFN"
        formula = program_rate.formula
        # Get MFN base rate
        mfn_rate = get_mfn_base_rate(hts_code, check_date)
        # Calculate: 15% - MFN
        ceiling_pct = 0.15  # Parse from formula
        calculated_rate = max(0, ceiling_pct - mfn_rate)
        return (calculated_rate, "formula_15_percent_minus_mfn")
    else:
        # Simple rate
        return (float(program_rate.duty_rate), f"country_group_{country_group}")
```

---

## 3. LANGGRAPH STATE MACHINE - DETAILED FLOW

### 3.1 Graph Node Execution

**File:** `app/chat/graphs/stacking_rag.py`

```python
# GRAPH CONSTRUCTION (lines 1000-1110)

def build_stacking_graph(checkpointer=None):
    """Build the LangGraph state graph for stacking."""

    graph_builder = StateGraph(StackingState)

    # ADD NODES (11 total)
    graph_builder.add_node("initialize", initialize_node)      # Line 1010
    graph_builder.add_node("check_materials", check_materials_node)
    graph_builder.add_node("check_annex_ii", check_annex_ii_node)
    graph_builder.add_node("plan_slices", plan_slices_node)
    graph_builder.add_node("process_programs", process_programs_loop_node)
    graph_builder.add_node("build_entry_stacks", build_entry_stacks_node)
    graph_builder.add_node("calculate_duties", calculate_duties_node)
    graph_builder.add_node("generate_output", generate_output_node)

    # ADD EDGES (DAG structure)
    graph_builder.add_edge(START, "initialize")               # Line 1050
    graph_builder.add_edge("initialize", "check_materials")
    graph_builder.add_edge("check_materials", "check_annex_ii")
    graph_builder.add_edge("check_annex_ii", "plan_slices")
    graph_builder.add_edge("plan_slices", "process_programs")
    graph_builder.add_edge("process_programs", "build_entry_stacks")
    graph_builder.add_edge("build_entry_stacks", "calculate_duties")
    graph_builder.add_edge("calculate_duties", "generate_output")
    graph_builder.add_edge("generate_output", END)            # Line 1095

    # COMPILE WITH CHECKPOINTING
    checkpointer = checkpointer or MemorySaver()              # Line 1105
    return graph_builder.compile(checkpointer=checkpointer)   # Line 1110

# NODE IMPLEMENTATIONS

def initialize_node(state: StackingState) -> dict:
    """
    Entry point: Get applicable programs.
    Lines 110-145
    """
    hts_code = state["hts_code"]
    country = state["country"]
    import_date = state.get("import_date") or date.today().isoformat()

    # Line 122-126: Call stacking tool
    result = TOOL_MAP["get_applicable_programs"].invoke({
        "country": country,
        "hts_code": hts_code,
        "import_date": import_date
    })

    data = json.loads(result)
    programs = data.get("programs", [])

    # Line 135-145: Log decision and return
    return {
        "programs": programs,
        "decisions": [{"step": "initialize", "programs_found": len(programs)}],
        "import_date": import_date
    }


def check_materials_node(state: StackingState) -> dict:
    """
    Check if material composition is needed.
    Lines 148-250
    """
    hts_code = state["hts_code"]
    product_value = state["product_value"]
    materials = state.get("materials")

    # Line 160-180: Call ensure_materials tool
    result = TOOL_MAP["ensure_materials"].invoke({
        "hts_code": hts_code,
        "product_description": state["product_description"],
        "known_materials": json.dumps(materials) if materials else None
    })

    data = json.loads(result)
    applicable_materials = data.get("applicable_materials", [])
    materials_needed = data.get("needs_input", False)

    # Line 190-210: If materials needed, ask user
    if materials_needed and not materials:
        return {
            "materials_needed": True,
            "applicable_materials": applicable_materials,
            "user_question": f"This HTS code may contain 232 metals ({', '.join(applicable_materials)}). Please provide values.",
            "awaiting_user_input": True
        }

    # Line 220: Otherwise continue
    return {
        "materials": data.get("materials"),
        "applicable_materials": applicable_materials
    }


def build_entry_stacks_node(state: StackingState) -> dict:
    """
    Build Chapter 99 stack for each entry slice.
    Lines 527-700
    """
    hts_code = state["hts_code"]
    programs = state.get("programs", [])
    slices = state.get("slices", [])
    program_results = state.get("program_results", {})
    annex_ii_exempt = state.get("annex_ii_exempt", False)
    materials = state.get("materials", {})

    entries = []

    # Line 550-560: Calculate unstacking for IEEPA
    copper_value = materials.get("copper", {}).get("value", 0) if isinstance(materials.get("copper"), dict) else 0
    steel_value = materials.get("steel", {}).get("value", 0) if isinstance(materials.get("steel"), dict) else 0
    aluminum_value = materials.get("aluminum", {}).get("value", 0) if isinstance(materials.get("aluminum"), dict) else 0
    material_total = copper_value + steel_value + aluminum_value

    unstacking = {
        "section_232_applies": material_total > 0,
        "material_content_value": material_total,
        "ieepa_reciprocal_base_reduced_by": material_total
    }

    # Line 580-650: For each slice, build entry
    for slice_idx, slice_info in enumerate(slices):
        entry = {
            "entry_number": slice_idx + 1,
            "slice_type": slice_info.get("slice_type"),
            "material": slice_info.get("material"),
            "slice_value": slice_info.get("value"),
            "stack": []
        }

        # Line 600-650: For each program, add to stack in calculation_sequence order
        for program in sorted(programs, key=lambda p: p.get("calculation_sequence", p.get("filing_sequence"))):
            program_id = program["program_id"]
            program_result = program_results.get(program_id, {})

            # Line 620-640: Determine action (apply/claim/disclaim)
            if program_result.get("excluded"):
                action = "exclude"
            elif program_result.get("included"):
                action = "apply"
            elif "material_claims" in program_result:
                material_type = slice_info.get("material")
                if material_type:
                    claim_info = program_result["material_claims"].get(material_type, {})
                    action = claim_info.get("action", "skip")
                else:
                    action = "skip"
            else:
                action = "skip"

            # Line 640-660: Get variant (for IEEPA reciprocal)
            if program_id == "ieepa_reciprocal":
                if annex_ii_exempt:
                    variant = "annex_ii_exempt"
                elif material_total > 0 and slice_info.get("material") in ["copper", "steel", "aluminum"]:
                    variant = "section_232_exempt"
                else:
                    variant = "standard"

                # Resolve variant → code
                result = TOOL_MAP["resolve_reciprocal_variant"].invoke({
                    "hts_code": hts_code,
                    "variant": variant
                })
                variant_data = json.loads(result)
                code = variant_data.get("code")
                rate = variant_data.get("rate")
            else:
                code = program_result.get("code")
                rate = program_result.get("rate", 0)

            # Line 670-700: Add to stack
            entry["stack"].append({
                "program_id": program_id,
                "program": program.get("program_name"),
                "action": action,
                "code": code,
                "rate": rate,
                "duty": slice_info.get("value", 0) * rate
            })

        entries.append(entry)

    return {
        "entries": entries,
        "unstacking": unstacking
    }
```

### 3.2 Tool Invocation & Message Handling

**File:** `app/chat/graphs/stacking_rag.py` (lines 800-900)

```python
def tool_edge(state: StackingState) -> str:
    """
    Routes to appropriate node based on messages.
    Uses tool_calls from LLM to determine next action.
    Lines 850-900
    """
    messages = state.get("messages", [])

    # Line 860-870: Check if last message has tool_calls
    if messages and hasattr(messages[-1], "tool_calls"):
        last_message = messages[-1]
        if last_message.tool_calls:
            # Line 875-885: Process each tool call
            tool_results = []
            for tool_call in last_message.tool_calls:
                tool_name = tool_call.get("name")
                tool_input = tool_call.get("args", {})

                # Execute tool
                tool = TOOL_MAP.get(tool_name)
                if tool:
                    result = tool.invoke(tool_input)
                    tool_results.append(
                        ToolMessage(
                            content=result,
                            tool_call_id=tool_call.get("id")
                        )
                    )

            # Add results to messages
            return {
                "messages": messages + tool_results
            }

    # Line 890-900: No tool calls, continue to next node
    return {}
```

---

## 4. DATA FILES - STRUCTURE & ROW COUNTS

### 4.1 Master Configuration Files

**Location:** `data/`

```
tariff_programs.csv (19 rows)
├─ program_id: section_301, ieepa_fentanyl, ieepa_reciprocal, section_232
├─ program_name: Human-readable name
├─ country: China, HK, MO, EU, UK, etc.
├─ check_type: hts_lookup (check inclusion table) or always (applies to all)
├─ condition_handler: none, handle_material_composition, handle_dependency
├─ inclusion_table: section_301_inclusions, section_301_rates, or NULL
├─ exclusion_table: section_301_exclusions or NULL
├─ filing_sequence: Order for ACE filing (1=first, 4=last)
├─ calculation_sequence: Order for duty math (may differ from filing_sequence)
├─ disclaim_behavior: required (copper), omit (steel/aluminum), none (others)
└─ effective_date, expiration_date: Temporal validity

country_groups.csv (6 rows)
├─ EU
├─ UK
├─ CN
└─ (3 others)

country_group_members.csv (50 rows)
├─ EU: Germany, France, Italy, Spain, Netherlands, Belgium, Austria, etc.
├─ UK: England, Scotland, Wales, Northern Ireland
└─ CN: China mainland, Hong Kong (HK), Macau (MO)
```

### 4.2 Rate Tables

**Location:** `data/current/`

```
section_301_rates.csv (10,811 rows)
├─ hts_8digit, hts_10digit: Product code
├─ chapter_99_code: Filing code (9903.88.01, etc.)
├─ duty_rate: 0.25 (25%), 0.50 (50%), etc.
├─ effective_start: 2020-02-14
├─ effective_end: NULL (active) or future date
├─ list_name: list_1, list_2, list_3, list_4a, list_4b
├─ role: impose (add duty) or exclude (remove duty)
├─ dataset_tag: FR_2018, USITC_CH99_CURRENT, etc.
├─ is_archived: true (old) or false (current)
└─ source_doc: PDF name for audit trail

section_301_inclusions.csv (11,372 rows) [LEGACY - use section_301_rates]
├─ hts_8digit, chapter_99_code, duty_rate
├─ list_name, effective_start, effective_end
└─ source_doc

section_232_rates.csv (1,638 rows)
├─ hts_8digit: Product code
├─ material_type: copper, steel, aluminum
├─ country_code: NULL (global), GBR (UK exception), etc.
├─ duty_rate: 0.50 (steel/aluminum), 0.25 (copper)
├─ article_type: primary or derivative
├─ effective_start, effective_end
└─ source_doc

ieepa_rates.csv (46 rows)
├─ program_type: ieepa_fentanyl, ieepa_reciprocal
├─ country_code: CN, HK, MO, DE, FR, GB, etc.
├─ variant: standard, annex_ii_exempt, section_232_exempt, us_content_exempt
├─ chapter_99_code: 9903.01.24 (fentanyl), 9903.01.25 (reciprocal standard), etc.
├─ duty_rate: 0.10 (10%)
└─ effective_start, effective_end

mfn_base_rates_8digit.csv (15,263 rows)
├─ hts_8digit: Product code
├─ mfn_rate: 0.026 (2.6%), 0.08 (8%), etc.
└─ effective_date

exclusion_claims.csv (179 rows)
├─ hts_8digit, hts_10digit: Product code
├─ product_description: "Facemask", "USB cable", etc.
├─ exclusion_reason: "Published in Federal Register XXXX-XX-XX"
├─ effective_start, effective_end
├─ status: pending, approved, rejected, expired
└─ source_doc

annex_ii_exemptions.csv (48 rows)
├─ hts_prefix: Product code prefix
├─ description: "Propane", "Natural gas", etc.
├─ exemption_code: 9903.01.32
├─ category: energy, pharmaceutical, chemical
└─ effective_date
```

---

## 5. CRITICAL HARDCODED VALUES

### 5.1 IEEPA Code Constants

**File:** `stacking_tools.py` (lines 46-82)

```python
IEEPA_CODES = {
    'fentanyl': {
        'code': '9903.01.24',      # ⚠️ NOT 9903.01.25!
        'rate': 0.10,
        'applies_to': ['CN', 'HK']
    },
    'reciprocal': {
        'standard': {'code': '9903.01.25', 'rate': 0.10},
        'annex_ii_exempt': {'code': '9903.01.32', 'rate': 0.00},
        'section_232_exempt': {'code': '9903.01.33', 'rate': 0.00},
        'us_content_exempt': {'code': '9903.01.34', 'rate': 0.00}
    }
}
```

### 5.2 Feature Flags

**File:** `stacking_tools.py` (lines 167-172)

```python
# v21.0: Feature flag for Annex II energy check implementation
USE_DB_ENERGY_CHECK = os.getenv("USE_DB_ENERGY_CHECK", "false").lower() == "true"

# If true: Uses check_annex_ii_exclusion() (database lookup)
# If false: Uses _legacy_is_annex_ii_energy_exempt() (CSV + hardcoded)
```

---

## 6. ERROR HANDLING & VALIDATION

### 6.1 Material Value Validation

**File:** `stacking_rag.py` (lines 1167-1174)

```python
def calculate_stacking(self, ..., materials=None, ...):
    # v7.1: Validate material allocation
    if materials:
        material_sum = sum(materials.values())
        if material_sum > product_value:
            raise ValueError(
                f"Material values (${material_sum:.2f}) exceed product value "
                f"(${product_value:.2f}). Sum of material allocations cannot "
                f"exceed total product value."
            )
```

### 6.2 HTS Code Normalization

**File:** `stacking_tools.py` (lines 1076-1090)

```python
def get_applicable_programs(country, hts_code, import_date):
    # Normalize HTS: "8544.42.9090" → "8544429090" (remove dots)
    hts_8digit = hts_code.replace(".", "")[:8]

    # Query with 8-digit prefix
    programs = TariffProgram.query.filter(...)

    # LIMITATION: No fallback to HTS6/4/2
    # Section 301 requires exact HTS8 match (per design)
```

---

## 7. AUDIT TRAIL & LOGGING

### 7.1 Decision Logging

**File:** `stacking_tools.py` throughout

```python
# Every tool logs decisions
decision = {
    "step": "initialize",
    "program_id": "all",
    "decision": f"Found {len(programs)} applicable programs",
    "reason": f"Queried tariff_programs for country={country}",
    "source_doc": "tariff_programs table",
    "timestamp": datetime.now().isoformat()
}

decisions.append(decision)
```

### 7.2 Calculation Logging

**File:** `tariff_tables.py` (lines 1380-1420)

```python
class TariffCalculationLog(db.Model):
    """Append-only audit log for all tariff calculations."""

    __tablename__ = "tariff_calculation_logs"

    id = db.Column(db.Integer, primary_key=True)
    request_hash = db.Column(db.String(64), unique=True)  # MD5 of inputs
    hts_code = db.Column(db.String(12))
    country = db.Column(db.String(64))
    materials = db.Column(db.JSON)
    import_date = db.Column(db.Date)
    program_results = db.Column(db.JSON)                  # Full result
    total_duty = db.Column(db.Numeric(12, 2))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
```

---

## 8. VERSIONING & HISTORY

### 8.1 Major Version Timeline

| Version | Date | Key Change |
|---------|------|-----------|
| v1.0 | 2025-07 | Initial stacking engine |
| v3.0 | 2025-09 | IEEPA unstacking |
| v4.0 | 2025-12 | Entry slices, Annex II exclusions |
| v5.0 | 2025-12 | Country-specific rates, EU 15% formula |
| v6.0 | 2025-12 | Data-driven country scope |
| v7.0 | 2026-01 | Phoebe-aligned ACE filing, disclaim_behavior |
| v10.0 | 2026-01 | Temporal Section301Rate table |
| v12.0 | 2026-01 | IEEPA code corrections (Fentanyl: 9903.01.24) |
| v13.0 | 2026-01 | Temporal IEEPA rate fallback |
| v17.0 | 2026-01 | DB as Source of Truth (--seed-if-empty) |
| v21.0 | 2026-02 | Feature flag for Annex II check (DB vs CSV) |
| v22.0 | 2026-02 | Dataset versioning + archival |

### 8.2 Section301Rate Migration Path

```
LEGACY: Section301Inclusion (static)
  └─ 11,372 HTS codes with fixed rates
  └─ No temporal tracking
  └─ All rates treated as current

v10.0 UPGRADE: Section301Rate (temporal)
  └─ 10,811 HTS codes
  └─ effective_start <= date < effective_end
  └─ dataset_tag + is_archived for versioning
  └─ role='impose' vs 'exclude' with precedence
  └─ supersedes_id for rate change tracking

v17.0 UPDATE: --seed-if-empty flag
  └─ Only populate Section301Rate if < 10K rows
  └─ Preserves pipeline-discovered rates
  └─ Railway deploys preserve data across restarts
```

---

## 9. INTEGRATION POINTS

### 9.1 External Services

| Service | Purpose | Config |
|---------|---------|--------|
| OpenAI API | GPT-4 for LLM, embeddings | OPENAI_API_KEY |
| Pinecone | Vector store for document retrieval | PINECONE_API_KEY, PINECONE_INDEX_NAME |
| Langfuse | Tracing & monitoring | LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY |
| Google Gemini | HTS scope verification | GEMINI_API_KEY |
| Gmail IMAP | CSMS watcher (automated ingestion) | GMAIL_CSMS_EMAIL, GMAIL_CSMS_APP_PASSWORD |
| PostgreSQL | Production database | DATABASE_URL_REMOTE |
| Redis | Job queue (Celery) | REDIS_URI |

### 9.2 MCP Servers

**Path:** `mcp_servers/`

Custom Model Context Protocol servers for external tools (details in separate config).

---

## 10. QUICK REFERENCE

### Test the Stacking Engine

```bash
# Test with example HTS codes
cd /sessions/hopeful-ecstatic-darwin/mnt/lanes

# Load data
python scripts/populate_tariff_tables.py --seed-if-empty

# Test calculation
python -c "
from app.web import create_app
from app.chat.graphs.stacking_rag import StackingRAG

app = create_app()
with app.app_context():
    rag = StackingRAG('test-session')
    result = rag.calculate_stacking(
        hts_code='8544.42.9090',
        country='China',
        product_description='USB-C cables',
        product_value=10000,
        materials={'copper': 500}
    )
    print(result)
"
```

### Monitor Database

```bash
# Connect to SQLite
sqlite3 /sessions/hopeful-ecstatic-darwin/mnt/lanes/lanes.db

# Check row counts
SELECT COUNT(*) FROM section_301_rates;           # Should be ~10,811
SELECT COUNT(*) FROM section_301_inclusions;      # Should be ~11,372
SELECT COUNT(*) FROM section_232_rates;           # Should be ~1,638

# Check latest rates
SELECT hts_8digit, chapter_99_code, duty_rate, effective_start
FROM section_301_rates
WHERE effective_end IS NULL
ORDER BY hts_8digit
LIMIT 10;
```

### Deploy to Production

```bash
# Railway deployment (automatic via railway.toml)
git push origin main

# Manual database reset
python scripts/populate_tariff_tables.py --reset

# Preserve runtime data
python scripts/populate_tariff_tables.py --seed-if-empty
```

