# Lanes – Stacking Feature Implementation (v4.0 + v5.0)

## 1. Problem & Scope

Customs brokers and self-filing importers must figure out:

1. **Which programs/tariffs apply** (301, 232, IEEPA Fentanyl, IEEPA Reciprocal, etc.)
2. **Whether they apply to the whole product or only metal content**
3. **How to file them in ACE** in the correct **Chapter 99 stack order**, including:
   - claim vs disclaim
   - inclusion/exclusion logic
   - unstacking interactions (e.g., 232 content excluded from Reciprocal base)

Our goal:

> Given **HTS + Country of Origin (+ optional composition)**, output:
> - The **ACE-ready entry stack** (entry slices + 99-codes + claim/disclaim)
> - **Duty calculation** with IEEPA unstacking
> - **Plain English explanation + citations** (audit trail)

### MVP Programs (Phase 1)

1. **Section 301** (China lists + exclusions)
2. **Section 232 – Steel**
3. **Section 232 – Aluminum**
4. **Section 232 – Copper**
5. **IEEPA Fentanyl** (China)
6. **IEEPA Reciprocal** (Annex II, 232-exempt, US-content-exempt)

### Phase 2 (Later)

- AD/CVD
- 232 Automobiles
- Additional trade remedy programs

---

## 2. Laynes Workflow (User-Facing Logic)

### Step 1 – Confirm Section 301 Applicability

**Input:** HTS + Country of Origin (e.g., `8544.42.9090`, China)

1. Check **USTR List 1–4A** PDFs:
   - 34B, 16B, 200B, 120B lists
   - Inclusion is **HTS-based** (8/10 digits)
2. If HTS not found → **no 301**.
3. If found → 301 applies at published rate (e.g., 25%).

### Step 2 – Check Section 301 Exclusions

1. Parse official exclusion PDFs (and extensions) into a DB:
   - `section_301_exclusions` (HTS + **exclusion description** + effective/expiry).
2. For each candidate exclusion:
   - Exact HTS match.
   - **LLM semantic match** on the description (e.g., "pipe brackets of aluminum…").
3. If a likely match is found:
   - Ask user to **confirm** "Does this description match your product?"
   - Only then mark the 301 program as excluded for this entry.

### Step 3 – Section 232 Metal Programs (Steel, Aluminum, Copper)

For each metal program:

1. **Steel**
   - Sources:
     - March 5, 2025 FR notice (Proclamation 10896)
     - August 19, 2025 FR update (derivative products)
   - Ingestion:
     - Extract the HTS list from Annex 1, note 16(j) / Annex updates.
     - Store in `section_232_steel_inclusions`.

2. **Aluminum**
   - Sources:
     - March 5, 2025 FR notice (Proclamation 10895)
     - April 4, 2025 FR update (beer / empty cans)
     - August 19, 2025 FR update (derivatives)
   - Ingestion:
     - Extract Annex 1, note 16(g), and derivative lists.
     - Store in `section_232_aluminum_inclusions`.

3. **Copper**
   - Sources:
     - CBP CSMS #65794272 (July 31, 2025)
     - Proclamation (July 30, 2025) + FR publication
   - Ingestion:
     - Extract list of 74 HTS subheadings (70 Chapter 74 + 4 Chapter 85).
     - Store in `section_232_copper_inclusions`.

**Runtime:**

- For each metal:
  1. Check if HTS is on the 232 list for that metal.
  2. If not → 232 program for that metal **does not apply**.
  3. If yes, ask:
     - "Does this product actually contain [metal]?"
     - "What is the **value** of the [metal] content (not just %)?"

> **Rule (2025):** 232 duty is based on **material content value**, and you must split into **content / non-content** lines. If content value is unknown → fallback: charge 232 **on full product value** (penalty).

### Step 4 – IEEPA Fentanyl

- If **Country ∈ {China, Hong Kong}**:
  - Apply IEEPA Fentanyl at 10% on **full product value**.
  - No HTS list, no exclusions.

### Step 5 – IEEPA Reciprocal

- Country must be in the Reciprocal regime (e.g. China, UK, etc.).
- We must always attach **one** of the following 99-codes per slice:
  - `9903.01.25` – Reciprocal **taxable** (10%)
  - `9903.01.32` – Reciprocal exempt (Annex II)
  - `9903.01.33` – Reciprocal exempt (232 metal content)
  - `9903.01.34` – Reciprocal exempt (US content)

### Step 6 – Filing Order & Duty Interaction

Per CBP CSMS #64018403 (trade remedies sequence per ACE line):

1. Section 301
2. IEEPA Fentanyl
3. IEEPA Reciprocal
4. Section 232 (steel, aluminum, copper)
5. Base HTS (Ch. 1–97)

But for **math**, we must compute:

1. 301 on full value
2. Fentanyl on full value
3. 232 on content values (and shrink `remaining_value`)
4. Reciprocal on `remaining_value` (excluding 232 content)

We solve this with **two sequences**:

- `filing_sequence` – ACE display order.
- `calculation_sequence` – order for the duty engine / unstacking.

### Step 7 – QA / Supervisor Agent

- Before returning to user, a **supervisor agent** re-runs:
  - duty calculations,
  - unstacking math,
  - and stack completeness (claim/disclaim per slice).
- Flags anomalies (e.g., missing disclaim, negative remaining_value).

---

## 3. Architecture Overview

Same 3-layer approach as v3.0, extended for entry slices:

| Layer | What | When | LLM Role |
|-------|------|------|----------|
| 1. Truth Source | USTR PDFs, FR notices, CBP CSMS, HTS | Offline ingestion | Parse → DB rows |
| 2. Rules DB | Programs, inclusions, exclusions, codes | Stored centrally | None (deterministic only) |
| 3. Runtime | Deterministic engine + LLM orchestrator | Per request | Tool selection, explanations |

**Design principle:** Rule templates as code, parameters as data.

---

## 4. Data Model (v4.0)

### 4.1 Master Programs – `tariff_programs`

Defines which programs exist and when they apply.

```sql
CREATE TABLE tariff_programs (
    program_id            VARCHAR PRIMARY KEY,
    program_name          VARCHAR,
    country               VARCHAR,    -- "China", "UK", "ALL", ...
    check_type            VARCHAR,    -- "hts_lookup", "always"
    condition_handler     VARCHAR,    -- "none", "handle_material_composition", ...
    condition_param       VARCHAR,
    inclusion_table       VARCHAR,
    exclusion_table       VARCHAR,
    filing_sequence       INT,        -- ACE display order
    calculation_sequence  INT,        -- duty/unstacking order
    source_document       VARCHAR,
    effective_date        DATE,
    expiration_date       DATE
);
```

**Example:**

| program_id | country | filing_sequence | calculation_sequence |
|------------|---------|-----------------|----------------------|
| section_301 | China | 1 | 1 |
| ieepa_fentanyl | CN/HK | 2 | 2 |
| ieepa_reciprocal | CN/UK/... | 3 | 4 |
| section_232_copper | ALL | 5 | 3 |
| section_232_steel | ALL | 5 | 3 |
| section_232_aluminum | ALL | 5 | 3 |

### 4.2 Section 301 Lists & Exclusions

```sql
CREATE TABLE section_301_inclusions (
    hts_8digit      VARCHAR,
    list_id         VARCHAR,    -- "List1", "List2", "List3", "List4A"
    program_id      VARCHAR,    -- "section_301"
    source_doc      VARCHAR,
    effective_date  DATE,
    expiration_date DATE,
    PRIMARY KEY (hts_8digit, list_id)
);

CREATE TABLE section_301_exclusions (
    hts_8digit       VARCHAR,
    exclusion_id     VARCHAR,
    description      TEXT,
    source_doc       VARCHAR,
    effective_date   DATE,
    expiration_date  DATE,
    PRIMARY KEY (hts_8digit, exclusion_id)
);
```

### 4.3 Section 232 Materials – `section_232_materials`

```sql
CREATE TABLE section_232_materials (
    hts_8digit          VARCHAR,
    material            VARCHAR,    -- "copper", "steel", "aluminum"
    claim_code          VARCHAR,    -- e.g. "9903.78.01"
    disclaim_code       VARCHAR,    -- e.g. "9903.78.02"
    duty_rate           DECIMAL,    -- 0.50, 0.25, ...
    source_doc          VARCHAR,
    content_basis       VARCHAR DEFAULT 'value',  -- "value"
    quantity_unit       VARCHAR DEFAULT 'kg',
    split_policy        VARCHAR DEFAULT 'if_any_content',
    split_threshold_pct DECIMAL,
    PRIMARY KEY (hts_8digit, material)
);
```

**Example rows for 8544.42.90:**

| hts_8digit | material | claim_code | disclaim_code | duty_rate |
|------------|----------|------------|---------------|-----------|
| 85444290 | copper | 9903.78.01 | 9903.78.02 | 0.50 |
| 85444290 | steel | 9903.80.01 | 9903.80.02 | 0.50 |
| 85444290 | aluminum | 9903.85.08 | 9903.85.09 | 0.25 |

### 4.4 IEEPA Annex II – `ieepa_annex_ii_exclusions`

```sql
CREATE TABLE ieepa_annex_ii_exclusions (
    id              INTEGER PRIMARY KEY,
    hts_code        VARCHAR(16) NOT NULL, -- prefix (4, 6, 8, or 10 digits)
    description     TEXT,
    category        VARCHAR(64),          -- 'chemical', 'pharmaceutical', 'critical_mineral', ...
    source_doc      VARCHAR(256),
    effective_date  DATE NOT NULL,
    expiration_date DATE
);

CREATE INDEX idx_annex_ii_hts ON ieepa_annex_ii_exclusions(hts_code);
```

We perform longest-prefix match on the 10-digit HTS.

### 4.5 Program Codes – `program_codes`

Map logical program states → concrete Chapter 99 codes (and duty rates).

```sql
CREATE TABLE program_codes (
    program_id       VARCHAR NOT NULL,
    action           VARCHAR NOT NULL,    -- "apply", "paid", "exempt", "claim", "disclaim"
    variant          VARCHAR(32),         -- 'taxable', 'annex_ii_exempt', 'metal_exempt', 'us_content_exempt', or NULL
    slice_type       VARCHAR(32) DEFAULT 'all',
    chapter_99_code  VARCHAR NOT NULL,
    duty_rate        DECIMAL(6,4),
    PRIMARY KEY (program_id, action, COALESCE(variant, ''), slice_type)
);
```

**Key rows:**

```sql
-- IEEPA Reciprocal
('ieepa_reciprocal', 'paid',   'taxable',           'non_metal',       '9903.01.25', 0.10),
('ieepa_reciprocal', 'exempt', 'annex_ii_exempt',   'all',             '9903.01.32', 0.00),
('ieepa_reciprocal', 'exempt', 'metal_exempt',      'copper_slice',    '9903.01.33', 0.00),
('ieepa_reciprocal', 'exempt', 'metal_exempt',      'steel_slice',     '9903.01.33', 0.00),
('ieepa_reciprocal', 'exempt', 'metal_exempt',      'aluminum_slice',  '9903.01.33', 0.00),
('ieepa_reciprocal', 'exempt', 'us_content_exempt', 'all',             '9903.01.34', 0.00),

-- Section 232 Copper
('section_232_copper', 'claim',    NULL, 'copper_slice',    '9903.78.01', 0.50),
('section_232_copper', 'disclaim', NULL, 'non_metal',       '9903.78.02', 0.00),
('section_232_copper', 'disclaim', NULL, 'steel_slice',     '9903.78.02', 0.00),
('section_232_copper', 'disclaim', NULL, 'aluminum_slice',  '9903.78.02', 0.00),

-- Section 232 Steel
('section_232_steel', 'claim',    NULL, 'steel_slice',     '9903.80.01', 0.50),
('section_232_steel', 'disclaim', NULL, 'non_metal',       '9903.80.02', 0.00),
('section_232_steel', 'disclaim', NULL, 'copper_slice',    '9903.80.02', 0.00),
('section_232_steel', 'disclaim', NULL, 'aluminum_slice',  '9903.80.02', 0.00),

-- Section 232 Aluminum
('section_232_aluminum', 'claim',    NULL, 'aluminum_slice', '9903.85.08', 0.25),
('section_232_aluminum', 'disclaim', NULL, 'non_metal',      '9903.85.09', 0.00),
('section_232_aluminum', 'disclaim', NULL, 'copper_slice',   '9903.85.09', 0.00),
('section_232_aluminum', 'disclaim', NULL, 'steel_slice',    '9903.85.09', 0.00),

-- Section 301 & IEEPA Fentanyl
('section_301',    'apply', NULL, 'all', '9903.88.03', 0.25),
('ieepa_fentanyl', 'apply', NULL, 'all', '9903.01.24', 0.10),
```

### 4.6 Duty Rules – `duty_rules`

Configure how each program is calculated:

```sql
CREATE TABLE duty_rules (
    program_id          VARCHAR,
    calculation_type    VARCHAR,   -- "additive", "on_portion"
    base_on             VARCHAR,   -- "product_value", "content_value", "remaining_value"
    content_key         VARCHAR,   -- "copper", "steel", "aluminum"
    fallback_base_on    VARCHAR,   -- "full_value" for penalty if content unknown
    base_effect         VARCHAR,   -- "subtract_from_remaining" (for 232)
    variant             VARCHAR,
    source_doc          VARCHAR,
    PRIMARY KEY (program_id, COALESCE(variant, ''))
);
```

**Examples:**

| program_id | base_on | content_key | base_effect | variant |
|------------|---------|-------------|-------------|---------|
| section_301 | product_value | NULL | NULL | NULL |
| ieepa_fentanyl | product_value | NULL | NULL | NULL |
| section_232_copper | content_value | copper | subtract_from_remaining | NULL |
| section_232_steel | content_value | steel | subtract_from_remaining | NULL |
| section_232_aluminum | content_value | aluminum | subtract_from_remaining | NULL |
| ieepa_reciprocal | remaining_value | NULL | NULL | taxable |
| ieepa_reciprocal | remaining_value | NULL | NULL | annex_ii_exempt |
| ieepa_reciprocal | remaining_value | NULL | NULL | metal_exempt |
| ieepa_reciprocal | remaining_value | NULL | NULL | us_content_exempt |

---

## 5. Output Schema – Entry Slices

### 5.1 FilingLine

```python
class FilingLine(BaseModel):
    """One Chapter 99 code in an entry stack."""
    sequence: int                # Order within this slice's 99-stack (1,2,3,...)
    chapter_99_code: str         # "9903.78.01"
    program: str                 # "Section 232 Copper"
    program_id: str              # "section_232_copper"
    action: str                  # "apply", "paid", "exempt", "claim", "disclaim"
    variant: Optional[str]       # "taxable", "metal_exempt", "annex_ii_exempt", ...
    duty_rate: Optional[float]   # e.g. 0.10, 0.25, 0.50
    applies_to: str              # "full" or "partial"
    material: Optional[str]      # "copper", "steel", "aluminum"
```

### 5.2 FilingEntry (ACE "slice")

```python
class FilingEntry(BaseModel):
    """One ACE entry line: base HTS + stack of 99-codes."""
    entry_id: str                    # "non_metal", "copper_slice", "steel_slice", ...
    slice_type: str                  # same as entry_id for now
    base_hts_code: str               # "8544.42.9090"
    country_of_origin: str           # "China"
    line_value: float                # value for this slice
    line_quantity: Optional[float]
    materials: Dict[str, MaterialInfo]
    stack: List[FilingLine]
```

### 5.3 StackingOutput (Top-Level)

```python
class StackingOutput(BaseModel):
    schema_version: str = "4.0"

    # Input echo
    hts_code: str
    country_of_origin: str
    product_description: str
    product_value: float
    materials: Dict[str, MaterialInfo]
    import_date: Optional[str]

    # ACE entry slices
    entries: List[FilingEntry]

    # Backwards compatible flat view
    filing_lines: List[FilingLine]   # = flatten(entries[i].stack)

    # Calculations
    total_duty_percent: float
    total_duty_amount: float
    duty_breakdown: List[DutyBreakdown]
    unstacking: Optional[UnstackingInfo]

    # Audit
    decisions: List[Decision]
    citations: List[SourceCitation]
    flags: List[str]                 # e.g. ["copper_fallback_full_value"]
```

---

## 6. Runtime Algorithm (Search → Slices → Duty)

### Step 0 – Input

Collect:
- `hts_code`, `country_of_origin`, `description`
- `product_value`, `import_date`
- Optional `materials` with values (and maybe % / kg).

### Step 1 – Lookup Product History

`lookup_product_history(hts_code, country, description)`:
- See if we already know typical composition.
- If yes, pre-fill materials and ask user to confirm.

### Step 2 – Get Applicable Programs

`get_applicable_programs(country, hts_code, import_date)`:

Query `tariff_programs` where:
- country matches
- date in [effective_date, expiration_date)
- inclusion checks pass (for HTS-based programs).

**For Section 301:**
- Check `section_301_inclusions`.
- Check `section_301_exclusions` (LLM for description similarity + date validity).

**For 232 programs:**
- Check `section_232_materials` / inclusion tables.

**For IEEPA Fentanyl:**
- `check_type = "always"` for CN/HK.

**For IEEPA Reciprocal:**
- Enabled based on country.

Return programs with both `filing_sequence` and `calculation_sequence`.

### Step 2.5 – Plan Entry Slices (with Steel)

We now handle up to three 232 metals: **copper, steel, aluminum**

```python
def plan_entry_slices(
    hts_code: str,
    product_value: float,
    materials: Dict[str, float],  # {"copper": 3000, "steel": 1000, "aluminum": 1000}
    applicable_programs: List[str]
) -> List[EntrySlice]:
    """
    Determine how many ACE entries to create for one product.

    Rules:
    - If no 232 materials apply → 1 slice (full_product)
    - If there are 232 materials → N+1 slices:
        - 1 non_metal slice (value - all 232 metal values)
        - 1 slice per 232 metal with value > 0
    """
    slices = []

    applicable_232 = [p for p in applicable_programs if p.startswith("section_232_")]

    materials_with_232 = {}
    for program_id in applicable_232:
        metal = program_id.replace("section_232_", "")  # "copper", "steel", "aluminum"
        if metal in materials and materials[metal] > 0:
            materials_with_232[metal] = materials[metal]

    if not materials_with_232:
        return [EntrySlice(
            entry_id="full_product",
            slice_type="full",
            base_hts=hts_code,
            value=product_value,
            materials=materials,
        )]

    metal_total = sum(materials_with_232.values())
    non_metal_value = product_value - metal_total

    if non_metal_value > 0:
        slices.append(EntrySlice(
            entry_id="non_metal",
            slice_type="non_metal",
            base_hts=hts_code,
            value=non_metal_value,
            materials={k: v for k, v in materials.items() if k not in materials_with_232}
        ))

    for metal, value in materials_with_232.items():
        slices.append(EntrySlice(
            entry_id=f"{metal}_slice",
            slice_type=f"{metal}_slice",  # "copper_slice", "steel_slice", ...
            base_hts=hts_code,
            value=value,
            materials={metal: value}
        ))

    return slices
```

> **Rule:** On a 232 "split line" entry, the primary HTS must be repeated on every slice (unless classifier intentionally uses a different HTS for a given slice). So `base_hts_code` stays the same for all 232 slices in most cases.

### Step 3 – Per-Slice Stacking

For each entry in `entries`:
1. Sort programs by `filing_sequence`.
2. For each program, decide action and variant.
3. Look up `program_codes` to get `chapter_99_code` and `duty_rate`.
4. Append a `FilingLine` to `entry.stack`.

```python
def resolve_reciprocal_variant(hts_code: str,
                               slice_type: str,
                               us_content_pct: Optional[float]) -> str:
    # Priority 1: Annex II
    if is_in_annex_ii(hts_code):
        return "annex_ii_exempt"

    # Priority 2: US content
    if us_content_pct is not None and us_content_pct >= 0.20:
        return "us_content_exempt"

    # Priority 3: metals (232 content slice)
    if slice_type in ["copper_slice", "steel_slice", "aluminum_slice"]:
        return "metal_exempt"

    return "taxable"


for entry in entries:
    for program in sorted(programs, key=lambda p: p.filing_sequence):
        if program.program_id == "section_301":
            if is_301_included(hts_code, country):
                action = "apply"
                variant = None
            else:
                continue

        elif program.program_id == "ieepa_fentanyl":
            if country in ["China", "Hong Kong"]:
                action = "apply"
                variant = None
            else:
                continue

        elif program.program_id == "ieepa_reciprocal":
            variant = resolve_reciprocal_variant(hts_code, entry.slice_type, us_content_pct)
            action = "paid" if variant == "taxable" else "exempt"

        elif program.program_id.startswith("section_232_"):
            metal = program.program_id.replace("section_232_", "")
            if entry.slice_type == f"{metal}_slice":
                action = "claim"
            else:
                action = "disclaim"
            variant = None

        else:
            # Future programs
            action, variant = handle_other_programs(...)

        # Skip if program not applicable
        if action == "skip":
            continue

        code_row = lookup_program_code(
            program_id=program.program_id,
            action=action,
            variant=variant,
            slice_type=entry.slice_type,
        )

        entry.stack.append(FilingLine(
            sequence=program.filing_sequence,
            chapter_99_code=code_row.chapter_99_code,
            program=program.program_name,
            program_id=program.program_id,
            action=action,
            variant=variant,
            duty_rate=code_row.duty_rate,
            applies_to="full" if program.program_id in ["section_301", "ieepa_fentanyl", "ieepa_reciprocal"]
                         else "partial",
            material=None  # set for 232 lines if desired
        ))

    entry.stack.sort(key=lambda line: line.sequence)
```

### Step 4 – Duty Calculation (Product Level, Unchanged)

We ignore slice layout and compute duties once per product using `calculation_sequence`.

```python
def calculate_duties(programs, product_value, material_values):
    remaining_value = product_value
    total_duty = 0.0
    content_deductions = {}

    for program in sorted(programs, key=lambda p: p.calculation_sequence):
        rule = get_duty_rule(program.program_id, program.variant)

        if rule.base_on == "product_value":
            rate = get_rate_for_program(program.program_id, program.variant)
            duty = product_value * rate

        elif rule.base_on == "content_value":
            content_value = material_values.get(rule.content_key, None)
            if content_value is None and rule.fallback_base_on == "full_value":
                content_value = product_value  # penalty
            rate = get_rate_for_program(program.program_id, program.variant)
            duty = content_value * rate

            if (rule.base_effect == "subtract_from_remaining"
                and content_value is not None
                and content_value > 0):
                remaining_value -= content_value
                content_deductions[rule.content_key] = content_value

        elif rule.base_on == "remaining_value":
            rate = get_rate_for_program(program.program_id, program.variant)
            duty = remaining_value * rate

        total_duty += duty

    return {
        "total_duty": total_duty,
        "unstacking": {
            "initial_value": product_value,
            "content_deductions": content_deductions,
            "remaining_value": remaining_value,
        },
    }
```

### Step 5 – Output

Build `StackingOutput`:
- `entries` = all slices with stacks.
- `filing_lines` = flattened stacks.
- `total_duty_amount`, `total_duty_percent`, `unstacking`.
- `decisions`, `citations`, `flags` for audit trail.

---

## 7. Canonical Scenarios

### 7.1 UK Chemical – Annex II (No Metals)

**Input:**

```json
{
  "hts_code": "2934.99.9050",
  "country_of_origin": "UK",
  "product_value": 1000.0,
  "materials": {}
}
```

**Flow:**
1. No 301.
2. No 232 (not a metal product).
3. No Fentanyl (not China).
4. IEEPA Reciprocal applies (UK under regime).
5. HTS in Annex II → variant = "annex_ii_exempt".

**Entry Slices:**

Only one:

```
Entry: full_product ($1,000)
  Base HTS: 2934.99.9050
  Stack:
    1. 9903.01.32 → IEEPA Reciprocal [EXEMPT – Annex II]
```

**Duty:**
- Reciprocal: $0
- **Total duty: $0**

---

### 7.2 China USB-C Cable – 3 Metals (Copper + Steel + Aluminum)

**Product:**

```
HTS:    8544.42.9090  (USB-C cable with connectors)
Country: China
Value:  $10,000

Materials:
  Copper:   $3,000 (30%)
  Steel:    $1,000 (10%)
  Aluminum: $1,000 (10%)
  Other:    $5,000 (50%)
```

#### 7.2.1 Programs that apply

1. **Section 301** (List 3) – 25% on full value.
2. **IEEPA Fentanyl** – 10% on full value (China).
3. **Section 232 Copper** – 50% on copper content.
4. **Section 232 Steel** – 50% on steel content.
5. **Section 232 Aluminum** – 25% on aluminum content.
6. **IEEPA Reciprocal** – 10% on remaining_value (excluding 232 content).

#### 7.2.2 Slices

From `plan_entry_slices` with 3 metals:

- `non_metal` slice: value = 10000 − 3000 − 1000 − 1000 = **$5,000**
- `copper_slice`: value = **$3,000**
- `steel_slice`: value = **$1,000**
- `aluminum_slice`: value = **$1,000**

#### 7.2.3 Stack per slice (ACE representation)

All slices use `base_hts_code = 8544.42.9090`.

**Entry 1 – Non-metal slice ($5,000)**

```
Stack (by filing_sequence):
1. 9903.88.03 → Section 301           [apply]   (25%)
2. 9903.01.24 → IEEPA Fentanyl        [apply]   (10%)
3. 9903.01.25 → IEEPA Reciprocal      [PAID]    (10%, taxable)
4. 9903.78.02 → 232 Copper            [DISCLAIM]
5. 9903.80.02 → 232 Steel             [DISCLAIM]
6. 9903.85.09 → 232 Aluminum          [DISCLAIM]
```

**Entry 2 – Copper slice ($3,000)**

```
Stack:
1. 9903.88.03 → Section 301           [apply]
2. 9903.01.24 → IEEPA Fentanyl        [apply]
3. 9903.01.33 → IEEPA Reciprocal      [EXEMPT – metal_exempt]
4. 9903.78.01 → 232 Copper            [CLAIM]
5. 9903.80.02 → 232 Steel             [DISCLAIM]
6. 9903.85.09 → 232 Aluminum          [DISCLAIM]
```

**Entry 3 – Steel slice ($1,000)**

```
Stack:
1. 9903.88.03 → Section 301           [apply]
2. 9903.01.24 → IEEPA Fentanyl        [apply]
3. 9903.01.33 → IEEPA Reciprocal      [EXEMPT – metal_exempt]
4. 9903.78.02 → 232 Copper            [DISCLAIM]
5. 9903.80.01 → 232 Steel             [CLAIM]
6. 9903.85.09 → 232 Aluminum          [DISCLAIM]
```

**Entry 4 – Aluminum slice ($1,000)**

```
Stack:
1. 9903.88.03 → Section 301           [apply]
2. 9903.01.24 → IEEPA Fentanyl        [apply]
3. 9903.01.33 → IEEPA Reciprocal      [EXEMPT – metal_exempt]
4. 9903.78.02 → 232 Copper            [DISCLAIM]
5. 9903.80.02 → 232 Steel             [DISCLAIM]
6. 9903.85.08 → 232 Aluminum          [CLAIM]
```

This matches CBP guidance:
- 301 and Fentanyl on all slices
- Reciprocal on all slices (taxable on non-metal, exempt on metal slices)
- Each 232 program claims on its metal slice and disclaims elsewhere.

#### 7.2.4 Product-Level Duty (Math Check)

We compute per program, not per slice:

```
Section 301:        $10,000 × 25% = $2,500
IEEPA Fentanyl:     $10,000 × 10% = $1,000

232 Copper:         $3,000 × 50%  = $1,500
232 Steel:          $1,000 × 50%  =   $500
232 Aluminum:       $1,000 × 25%  =   $250

IEEPA Reciprocal:   remaining_value × 10%
```

Where:

```
remaining_value (for Reciprocal) = 10,000
                                  − 3,000 (copper content)
                                  − 1,000 (steel content)
                                  − 1,000 (aluminum content)
                                = 5,000

IEEPA Reciprocal:  5,000 × 10%  =  $500
```

**Total duty:**

```
  2,500 (301)
+ 1,000 (Fentanyl)
+ 1,500 (232 Copper)
+   500 (232 Steel)
+   250 (232 Aluminum)
+   500 (Reciprocal)
───────────────────────
= $6,250 total duty

Effective rate = 6,250 / 10,000 = 62.5%
```

**Unstacking info:**

```json
{
  "unstacking": {
    "initial_value": 10000.0,
    "content_deductions": {
      "copper": 3000.0,
      "steel": 1000.0,
      "aluminum": 1000.0
    },
    "remaining_value": 5000.0
  }
}
```

#### 7.2.5 10-Line "Flat" Output (Conceptual View)

You can also flatten the logic back into a single conceptual listing:

```
Line 1:  8544.42.9090     Base HTS
Line 2:  9903.88.03       Section 301        (25% on $10,000)
Line 3:  9903.01.24       IEEPA Fentanyl     (10% on $10,000)
Line 4:  9903.78.02       232 Non-Copper     ($7,000 value, 0%)
Line 5:  9903.78.01       232 Copper Content ($3,000 value, 50%)
Line 6:  9903.85.09       232 Non-Aluminum   ($9,000 value, 0%)
Line 7:  9903.85.08       232 Aluminum       ($1,000 value, 25%)
Line 8:  9903.80.02       232 Non-Steel      ($9,000 value, 0%)
Line 9:  9903.80.01       232 Steel Content  ($1,000 value, 50%)
Line 10: 9903.01.33       IEEPA Reciprocal   (10% on $5,000 remaining)
```

The math is identical – the entry slices just mirror how ACE actually wants the data structured.

---

## 8. Mandatory Reporting Rules (CBP)

For any HTS where a program applies:

| Program | When applicable | Per-slice requirement |
|---------|-----------------|----------------------|
| Section 301 | HTS on 301 list for country | Must be `apply` on all slices |
| IEEPA Fentanyl | Products of China/Hong Kong | Must be `apply` on all slices |
| IEEPA Reciprocal | Country under Reciprocal regime | Every slice must have one variant (`paid` or `exempt`) |
| Section 232 Copper | HTS on 232 copper list | `claim` on copper slice, `disclaim` on others |
| Section 232 Steel | HTS on 232 steel list | `claim` on steel slice, `disclaim` on others |
| Section 232 Aluminum | HTS on 232 aluminum list | `claim` on aluminum slice, `disclaim` on others |

> **CBP:** When an article has steel/aluminum/copper content and non-metallic content, you must report metal / non-metal on separate entry lines so that 232 duty is assessed only on metal content.

---

## 9. Implementation Files

| File | Changes |
|------|---------|
| `app/web/db/models/tariff_tables.py` | Add `IeepaAnnexIIExclusion` model, extend `ProgramCode` with `variant`, `slice_type`, `duty_rate` |
| `scripts/populate_tariff_tables.py` | Ingest USTR lists, 232 lists, Annex II; seed `program_codes` rows |
| `app/chat/tools/stacking_tools.py` | Add `plan_entry_slices`, `check_annex_ii_exclusion`, per-slice stacking orchestration |
| `app/chat/output_schemas.py` | Add `FilingEntry`; extend `FilingLine`; update `StackingOutput` to include `entries` |
| `app/chat/graphs/stacking_rag.py` | Insert slice planner node; run duty math separately from ACE stacking |
| `tests/test_stacking_automated.py` | Add Annex II chemical test; 3-metal China USB-C test; Germany cable (no IEEPA); regression on unstacking |

---

## 10. Success Criteria

### Test Case 1: Annex II Chemical (UK)

- **Input:** HTS 2934.99.9050, UK, $1,000, no metals
- **Output:** 1 entry with `9903.01.32` (Annex II exempt)
- **Reciprocal duty:** $0

### Test Case 2: USB-C from China (3 metals)

- **Input:** HTS 8544.42.9090, China, $10,000, {copper: 3000, steel: 1000, aluminum: 1000}
- **Output:** 4 slices (non_metal, copper_slice, steel_slice, aluminum_slice) with correct stacks
- **Total duty:** $6,250 (62.5%), Reciprocal on $5,000 remaining

### Test Case 3: USB-C from Germany (232 only)

- **Input:** Same composition as above, Country = Germany
- **Output:** 4 slices with only 232 programs (no 301, no IEEPA)
- **Duty:** 1,500 (Cu) + 500 (Steel) + 250 (Al) = $2,250 (22.5%)

### Test Case 4: Backwards Compatibility

- `StackingOutput.filing_lines` can be reconstructed by flattening all `entries.stack`.
- For all v3.0 test cases (no Annex II / slices), duty numbers and 99-code sets remain identical.

---

## 11. Test Case Outputs (v4.0 Format)

### Test Case 1: UK Chemical (Annex II Exempt)

**Input:**
```json
{
  "hts_code": "2934.99.9050",
  "country_of_origin": "UK",
  "product_value": 1000.0,
  "materials": {}
}
```

**Output:**
```
═══════════════════════════════════════════════════════════════════════════════
                      TARIFF STACKING RESULT (v4.0)
═══════════════════════════════════════════════════════════════════════════════
HTS Code:           2934.99.9050
Country of Origin:  UK
Product Value:      $1,000.00
Materials:          None

───────────────────────────────────────────────────────────────────────────────
                           ACE ENTRY SLICES
───────────────────────────────────────────────────────────────────────────────

┌─────────────────────────────────────────────────────────────────────────────┐
│ ENTRY 1: full_product                                                       │
│ Base HTS: 2934.99.9050                                                      │
│ Value:    $1,000.00                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ Seq │ Chapter 99  │ Program              │ Action │ Variant         │ Rate  │
├─────┼─────────────┼──────────────────────┼────────┼─────────────────┼───────┤
│  1  │ 9903.01.32  │ IEEPA Reciprocal     │ EXEMPT │ annex_ii_exempt │  0%   │
└─────────────────────────────────────────────────────────────────────────────┘

───────────────────────────────────────────────────────────────────────────────
                           DUTY CALCULATION
───────────────────────────────────────────────────────────────────────────────
Program              │ Base Value  │  Rate  │ Duty Amount
─────────────────────┼─────────────┼────────┼─────────────
IEEPA Reciprocal     │  $1,000.00  │   0%   │      $0.00

═══════════════════════════════════════════════════════════════════════════════
TOTAL DUTY:      $0.00
EFFECTIVE RATE:  0.0%
═══════════════════════════════════════════════════════════════════════════════
```

---

### Test Case 2: China USB-C Cable (3 Metals - Copper + Steel + Aluminum)

**Input:**
```json
{
  "hts_code": "8544.42.9090",
  "country_of_origin": "China",
  "product_value": 10000.0,
  "materials": {
    "copper": 3000.0,
    "steel": 1000.0,
    "aluminum": 1000.0
  }
}
```

**Output:**
```
═══════════════════════════════════════════════════════════════════════════════
                      TARIFF STACKING RESULT (v4.0)
═══════════════════════════════════════════════════════════════════════════════
HTS Code:           8544.42.9090
Country of Origin:  China
Product Value:      $10,000.00
Materials:          copper: $3,000 (30%), steel: $1,000 (10%), aluminum: $1,000 (10%)

───────────────────────────────────────────────────────────────────────────────
                           ACE ENTRY SLICES
───────────────────────────────────────────────────────────────────────────────

┌─────────────────────────────────────────────────────────────────────────────┐
│ ENTRY 1: non_metal                                                          │
│ Base HTS: 8544.42.9090                                                      │
│ Value:    $5,000.00                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ Seq │ Chapter 99  │ Program              │ Action   │ Variant     │ Rate    │
├─────┼─────────────┼──────────────────────┼──────────┼─────────────┼─────────┤
│  1  │ 9903.88.03  │ Section 301          │ apply    │ -           │ 25%     │
│  2  │ 9903.01.24  │ IEEPA Fentanyl       │ apply    │ -           │ 10%     │
│  3  │ 9903.01.25  │ IEEPA Reciprocal     │ PAID     │ taxable     │ 10%     │
│  4  │ 9903.78.02  │ Section 232 Copper   │ DISCLAIM │ -           │  0%     │
│  5  │ 9903.80.02  │ Section 232 Steel    │ DISCLAIM │ -           │  0%     │
│  6  │ 9903.85.09  │ Section 232 Aluminum │ DISCLAIM │ -           │  0%     │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ ENTRY 2: copper_slice                                                       │
│ Base HTS: 8544.42.9090                                                      │
│ Value:    $3,000.00                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ Seq │ Chapter 99  │ Program              │ Action   │ Variant      │ Rate   │
├─────┼─────────────┼──────────────────────┼──────────┼──────────────┼────────┤
│  1  │ 9903.88.03  │ Section 301          │ apply    │ -            │ 25%    │
│  2  │ 9903.01.24  │ IEEPA Fentanyl       │ apply    │ -            │ 10%    │
│  3  │ 9903.01.33  │ IEEPA Reciprocal     │ EXEMPT   │ metal_exempt │  0%    │
│  4  │ 9903.78.01  │ Section 232 Copper   │ CLAIM    │ -            │ 50%    │
│  5  │ 9903.80.02  │ Section 232 Steel    │ DISCLAIM │ -            │  0%    │
│  6  │ 9903.85.09  │ Section 232 Aluminum │ DISCLAIM │ -            │  0%    │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ ENTRY 3: steel_slice                                                        │
│ Base HTS: 8544.42.9090                                                      │
│ Value:    $1,000.00                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ Seq │ Chapter 99  │ Program              │ Action   │ Variant      │ Rate   │
├─────┼─────────────┼──────────────────────┼──────────┼──────────────┼────────┤
│  1  │ 9903.88.03  │ Section 301          │ apply    │ -            │ 25%    │
│  2  │ 9903.01.24  │ IEEPA Fentanyl       │ apply    │ -            │ 10%    │
│  3  │ 9903.01.33  │ IEEPA Reciprocal     │ EXEMPT   │ metal_exempt │  0%    │
│  4  │ 9903.78.02  │ Section 232 Copper   │ DISCLAIM │ -            │  0%    │
│  5  │ 9903.80.01  │ Section 232 Steel    │ CLAIM    │ -            │ 50%    │
│  6  │ 9903.85.09  │ Section 232 Aluminum │ DISCLAIM │ -            │  0%    │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ ENTRY 4: aluminum_slice                                                     │
│ Base HTS: 8544.42.9090                                                      │
│ Value:    $1,000.00                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ Seq │ Chapter 99  │ Program              │ Action   │ Variant      │ Rate   │
├─────┼─────────────┼──────────────────────┼──────────┼──────────────┼────────┤
│  1  │ 9903.88.03  │ Section 301          │ apply    │ -            │ 25%    │
│  2  │ 9903.01.24  │ IEEPA Fentanyl       │ apply    │ -            │ 10%    │
│  3  │ 9903.01.33  │ IEEPA Reciprocal     │ EXEMPT   │ metal_exempt │  0%    │
│  4  │ 9903.78.02  │ Section 232 Copper   │ DISCLAIM │ -            │  0%    │
│  5  │ 9903.80.02  │ Section 232 Steel    │ DISCLAIM │ -            │  0%    │
│  6  │ 9903.85.08  │ Section 232 Aluminum │ CLAIM    │ -            │ 25%    │
└─────────────────────────────────────────────────────────────────────────────┘

───────────────────────────────────────────────────────────────────────────────
                           DUTY CALCULATION
───────────────────────────────────────────────────────────────────────────────
Program              │ Base Value  │  Rate  │ Duty Amount
─────────────────────┼─────────────┼────────┼─────────────
Section 301          │ $10,000.00  │  25%   │  $2,500.00
IEEPA Fentanyl       │ $10,000.00  │  10%   │  $1,000.00
Section 232 Copper   │  $3,000.00  │  50%   │  $1,500.00
Section 232 Steel    │  $1,000.00  │  50%   │    $500.00
Section 232 Aluminum │  $1,000.00  │  25%   │    $250.00
IEEPA Reciprocal     │  $5,000.00  │  10%   │    $500.00
                     │             │        │
                     │             │ TOTAL  │  $6,250.00

───────────────────────────────────────────────────────────────────────────────
                           IEEPA UNSTACKING
───────────────────────────────────────────────────────────────────────────────
Initial Product Value:    $10,000.00
  − Copper content:        −$3,000.00
  − Steel content:         −$1,000.00
  − Aluminum content:      −$1,000.00
                          ───────────
Remaining Value (IEEPA):   $5,000.00

═══════════════════════════════════════════════════════════════════════════════
TOTAL DUTY:      $6,250.00
EFFECTIVE RATE:  62.5%
═══════════════════════════════════════════════════════════════════════════════
```

---

### Test Case 3: Germany USB-C Cable (232 Only, No IEEPA/301)

**Input:**
```json
{
  "hts_code": "8544.42.9090",
  "country_of_origin": "Germany",
  "product_value": 10000.0,
  "materials": {
    "copper": 3000.0,
    "steel": 1000.0,
    "aluminum": 1000.0
  }
}
```

**Output:**
```
═══════════════════════════════════════════════════════════════════════════════
                      TARIFF STACKING RESULT (v4.0)
═══════════════════════════════════════════════════════════════════════════════
HTS Code:           8544.42.9090
Country of Origin:  Germany
Product Value:      $10,000.00
Materials:          copper: $3,000 (30%), steel: $1,000 (10%), aluminum: $1,000 (10%)

───────────────────────────────────────────────────────────────────────────────
                           ACE ENTRY SLICES
───────────────────────────────────────────────────────────────────────────────

┌─────────────────────────────────────────────────────────────────────────────┐
│ ENTRY 1: non_metal                                                          │
│ Base HTS: 8544.42.9090                                                      │
│ Value:    $5,000.00                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ Seq │ Chapter 99  │ Program              │ Action   │ Rate                  │
├─────┼─────────────┼──────────────────────┼──────────┼───────────────────────┤
│  1  │ 9903.78.02  │ Section 232 Copper   │ DISCLAIM │  0%                   │
│  2  │ 9903.80.02  │ Section 232 Steel    │ DISCLAIM │  0%                   │
│  3  │ 9903.85.09  │ Section 232 Aluminum │ DISCLAIM │  0%                   │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ ENTRY 2: copper_slice                                                       │
│ Base HTS: 8544.42.9090                                                      │
│ Value:    $3,000.00                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ Seq │ Chapter 99  │ Program              │ Action   │ Rate                  │
├─────┼─────────────┼──────────────────────┼──────────┼───────────────────────┤
│  1  │ 9903.78.01  │ Section 232 Copper   │ CLAIM    │ 50%                   │
│  2  │ 9903.80.02  │ Section 232 Steel    │ DISCLAIM │  0%                   │
│  3  │ 9903.85.09  │ Section 232 Aluminum │ DISCLAIM │  0%                   │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ ENTRY 3: steel_slice                                                        │
│ Base HTS: 8544.42.9090                                                      │
│ Value:    $1,000.00                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ Seq │ Chapter 99  │ Program              │ Action   │ Rate                  │
├─────┼─────────────┼──────────────────────┼──────────┼───────────────────────┤
│  1  │ 9903.78.02  │ Section 232 Copper   │ DISCLAIM │  0%                   │
│  2  │ 9903.80.01  │ Section 232 Steel    │ CLAIM    │ 50%                   │
│  3  │ 9903.85.09  │ Section 232 Aluminum │ DISCLAIM │  0%                   │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ ENTRY 4: aluminum_slice                                                     │
│ Base HTS: 8544.42.9090                                                      │
│ Value:    $1,000.00                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ Seq │ Chapter 99  │ Program              │ Action   │ Rate                  │
├─────┼─────────────┼──────────────────────┼──────────┼───────────────────────┤
│  1  │ 9903.78.02  │ Section 232 Copper   │ DISCLAIM │  0%                   │
│  2  │ 9903.80.02  │ Section 232 Steel    │ DISCLAIM │  0%                   │
│  3  │ 9903.85.08  │ Section 232 Aluminum │ CLAIM    │ 25%                   │
└─────────────────────────────────────────────────────────────────────────────┘

───────────────────────────────────────────────────────────────────────────────
                           DUTY CALCULATION
───────────────────────────────────────────────────────────────────────────────
Program              │ Base Value  │  Rate  │ Duty Amount
─────────────────────┼─────────────┼────────┼─────────────
Section 232 Copper   │  $3,000.00  │  50%   │  $1,500.00
Section 232 Steel    │  $1,000.00  │  50%   │    $500.00
Section 232 Aluminum │  $1,000.00  │  25%   │    $250.00
                     │             │        │
                     │             │ TOTAL  │  $2,250.00

═══════════════════════════════════════════════════════════════════════════════
TOTAL DUTY:      $2,250.00
EFFECTIVE RATE:  22.5%
═══════════════════════════════════════════════════════════════════════════════
```

---

### Test Case 4: China Cable - Single Metal (Copper Only)

**Input:**
```json
{
  "hts_code": "8544.42.9090",
  "country_of_origin": "China",
  "product_value": 10000.0,
  "materials": {
    "copper": 3000.0
  }
}
```

**Output:**
```
═══════════════════════════════════════════════════════════════════════════════
                      TARIFF STACKING RESULT (v4.0)
═══════════════════════════════════════════════════════════════════════════════
HTS Code:           8544.42.9090
Country of Origin:  China
Product Value:      $10,000.00
Materials:          copper: $3,000 (30%)

───────────────────────────────────────────────────────────────────────────────
                           ACE ENTRY SLICES
───────────────────────────────────────────────────────────────────────────────

┌─────────────────────────────────────────────────────────────────────────────┐
│ ENTRY 1: non_metal                                                          │
│ Base HTS: 8544.42.9090                                                      │
│ Value:    $7,000.00                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ Seq │ Chapter 99  │ Program              │ Action   │ Variant     │ Rate    │
├─────┼─────────────┼──────────────────────┼──────────┼─────────────┼─────────┤
│  1  │ 9903.88.03  │ Section 301          │ apply    │ -           │ 25%     │
│  2  │ 9903.01.24  │ IEEPA Fentanyl       │ apply    │ -           │ 10%     │
│  3  │ 9903.01.25  │ IEEPA Reciprocal     │ PAID     │ taxable     │ 10%     │
│  4  │ 9903.78.02  │ Section 232 Copper   │ DISCLAIM │ -           │  0%     │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ ENTRY 2: copper_slice                                                       │
│ Base HTS: 8544.42.9090                                                      │
│ Value:    $3,000.00                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ Seq │ Chapter 99  │ Program              │ Action   │ Variant      │ Rate   │
├─────┼─────────────┼──────────────────────┼──────────┼──────────────┼────────┤
│  1  │ 9903.88.03  │ Section 301          │ apply    │ -            │ 25%    │
│  2  │ 9903.01.24  │ IEEPA Fentanyl       │ apply    │ -            │ 10%    │
│  3  │ 9903.01.33  │ IEEPA Reciprocal     │ EXEMPT   │ metal_exempt │  0%    │
│  4  │ 9903.78.01  │ Section 232 Copper   │ CLAIM    │ -            │ 50%    │
└─────────────────────────────────────────────────────────────────────────────┘

───────────────────────────────────────────────────────────────────────────────
                           DUTY CALCULATION
───────────────────────────────────────────────────────────────────────────────
Program              │ Base Value  │  Rate  │ Duty Amount
─────────────────────┼─────────────┼────────┼─────────────
Section 301          │ $10,000.00  │  25%   │  $2,500.00
IEEPA Fentanyl       │ $10,000.00  │  10%   │  $1,000.00
Section 232 Copper   │  $3,000.00  │  50%   │  $1,500.00
IEEPA Reciprocal     │  $7,000.00  │  10%   │    $700.00
                     │             │        │
                     │             │ TOTAL  │  $5,700.00

───────────────────────────────────────────────────────────────────────────────
                           IEEPA UNSTACKING
───────────────────────────────────────────────────────────────────────────────
Initial Product Value:    $10,000.00
  − Copper content:        −$3,000.00
                          ───────────
Remaining Value (IEEPA):   $7,000.00

═══════════════════════════════════════════════════════════════════════════════
TOTAL DUTY:      $5,700.00
EFFECTIVE RATE:  57.0%
═══════════════════════════════════════════════════════════════════════════════
```

---

### Canonical Rates (Dec 2025)

| Program                             | Rate | Chapter 99 Code |
|-------------------------------------|------|-----------------|
| Section 301 (List 3)                | 25%  | 9903.88.03      |
| IEEPA Fentanyl                      | 10%  | 9903.01.24      |
| IEEPA Reciprocal (taxable)          | 10%  | 9903.01.25      |
| IEEPA Reciprocal (Annex II exempt)  | 0%   | 9903.01.32      |
| IEEPA Reciprocal (metal exempt)     | 0%   | 9903.01.33      |
| IEEPA Reciprocal (US content exempt)| 0%   | 9903.01.34      |
| Section 232 Copper                  | 50%  | 9903.78.01      |
| Section 232 Steel                   | 50%  | 9903.80.01      |
| Section 232 Aluminum                | 25%  | 9903.85.08      |

> **Note:** All rates are as of Dec 2025. These canonical rates are used consistently throughout this document.

---

## TL;DR

**v4.0 keeps the v3.0 math engine and IEEPA unstacking, but adds:**

1. **Entry slices** (ACE-ready representation) including steel
2. **IEEPA Reciprocal variants** (Annex II, metal_exempt, US-content)
3. **Data-driven mapping** from `(program, variant, slice_type)` → exact Chapter 99 codes

So one HTS + COO + composition can now output:
- **1 Annex II "end code"** (UK chemical), or
- **4 stacked ACE lines** with correct 301/IEEPA/232 interplay (China USB-C with copper + steel + aluminum)

...from the same engine.

---

# v5.0 Extension: Country-Specific Rates & Data Freshness

## 12. The Germany Bug (What Prompted v5.0)

When testing Germany with USB-C cable ($10,000, copper=$3,000, steel=$1,000, aluminum=$1,000), v4.0 returned **$2,750** instead of the correct **$3,120**.

### Root Cause

v4.0 used flat rates per program. Reality requires country-specific rules:

| Country | 232 Steel/Aluminum | IEEPA Reciprocal |
|---------|-------------------|------------------|
| **EU** (Germany, France, etc.) | 50% | `max(0, 15% - MFN_base_rate)` |
| **UK** | 25% (exception) | 10% |
| **All Others** | 50% | 10% |

### Corrected Germany Calculation

```
232 Copper:       $3,000 × 50%   = $1,500
232 Steel:        $1,000 × 50%   = $500
232 Aluminum:     $1,000 × 50%   = $500  ← v5.0: 50% not 25%
IEEPA Reciprocal: $5,000 × 12.4% = $620  ← (15% - 2.6% MFN)
                                  ───────
Total:                            $3,120 (31.2%)
```

---

## 13. Research & Sources (v5.0)

### EU 15% Ceiling Rule (August 7, 2025)

**Source:** CBP CSMS #65829726
- URL: https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ec7b5e
- Effective: August 7, 2025
- Rule: For EU countries, Reciprocal = `max(0, 15% - MFN_base_rate)`
- Example: HTS 8544.42.9090 has 2.6% MFN, so Reciprocal = 15% - 2.6% = 12.4%

**Analysis:** Covington US-EU Trade Framework
- URL: https://www.cov.com/en/news-and-insights/insights/2025/08/us--eu-trade-framework-outcome-and-next-steps

### 232 Steel/Aluminum Increase to 50% (June 4, 2025)

**Source:** White House Fact Sheet
- URL: https://www.whitehouse.gov/fact-sheets/2025/06/fact-sheet-president-donald-j-trump-increases-section-232-tariffs-on-steel-and-aluminum/
- Effective: June 4, 2025
- Change: 232 Steel and Aluminum rates increased from 25% to 50%

### UK Exception (232 Stays at 25%)

**Source:** Thompson Hine SmartTrade Analysis
- URL: https://www.thompsonhinesmartrade.com/2025/06/section-232-aluminum-and-steel-tariffs-increased-to-50-except-for-uk-significant-changes-made-to-calculating-and-stacking-of-tariffs/
- Effective: June 4, 2025
- Exception: UK 232 Steel/Aluminum remains at 25% (not increased to 50%)

### 232 Copper (July 31, 2025)

**Source:** CBP CSMS #65794272
- Effective: July 31, 2025
- Rate: 50% on copper content VALUE (not percentage)
- Applies to all countries (no exceptions)

---

## 14. v5.0 Design Principles

1. **Runtime = DB Lookups Only** - No web searches during stacking calculation
2. **Web Search = Offline Ingestion Only** - Scheduled jobs fetch and parse government docs
3. **Data-Driven** - All rates come from database tables, not hardcoded
4. **Auditable** - Every rate lookup includes source document reference
5. **Time-Bounded** - All rules have effective_date/expiration_date for history

---

## 15. v5.0 New Database Tables

### 15.1 source_documents - Audit trail for government sources

```sql
CREATE TABLE source_documents (
    id              INTEGER PRIMARY KEY,
    url             VARCHAR(512),
    title           VARCHAR(256) NOT NULL,
    doc_type        VARCHAR(64) NOT NULL,     -- 'CSMS', 'FR_notice', 'EO', 'USTR', 'USITC'
    doc_identifier  VARCHAR(128),             -- 'CSMS #65829726', 'FR 2025-10524'
    fetched_at      TIMESTAMP NOT NULL,
    content_hash    VARCHAR(64),              -- SHA256 for change detection
    effective_date  DATE,
    summary         TEXT,
    UNIQUE(doc_type, doc_identifier)
);
```

### 15.2 country_groups - Country groupings for rule application

```sql
CREATE TABLE country_groups (
    id              INTEGER PRIMARY KEY,
    group_id        VARCHAR(32) UNIQUE NOT NULL,  -- 'EU', 'UK', 'CN', 'USMCA'
    description     VARCHAR(256),
    effective_date  DATE NOT NULL,
    expiration_date DATE
);
```

**Sample Data:**
- `EU`: European Union - 15% ceiling rule
- `UK`: United Kingdom - 232 exception
- `CN`: China - Full tariffs
- `USMCA`: Mexico, Canada - FTA treatment
- `default`: All other countries

### 15.3 country_group_members - Map countries to groups

```sql
CREATE TABLE country_group_members (
    id              INTEGER PRIMARY KEY,
    country_code    VARCHAR(64) NOT NULL,  -- 'Germany', 'DE', 'France', 'FR'
    group_id        VARCHAR(32) NOT NULL,  -- FK to country_groups
    effective_date  DATE NOT NULL,
    expiration_date DATE,
    UNIQUE(country_code, group_id)
);
```

**Sample Data:**
- Germany, DE, France, FR, Italy, IT, ... → `EU`
- United Kingdom, UK, GB → `UK`
- China, CN, PRC → `CN`

### 15.4 program_rates - Country-group-specific rates

```sql
CREATE TABLE program_rates (
    id                INTEGER PRIMARY KEY,
    program_id        VARCHAR(64) NOT NULL,    -- 'section_232_steel', 'ieepa_reciprocal'
    group_id          VARCHAR(32) NOT NULL,    -- 'EU', 'UK', 'default'
    rate              DECIMAL(6,4),            -- 0.50, 0.25, NULL for formula
    rate_type         VARCHAR(32) DEFAULT 'fixed',  -- 'fixed', 'formula'
    rate_formula      VARCHAR(64),             -- '15pct_minus_mfn', NULL for fixed
    effective_date    DATE NOT NULL,
    expiration_date   DATE,
    source_doc_id     INTEGER,                 -- FK to source_documents
    UNIQUE(program_id, group_id, effective_date)
);
```

**Sample Data:**

| program_id          | group_id | rate | rate_type | rate_formula      |
|---------------------|----------|------|-----------|-------------------|
| section_232_steel   | default  | 0.50 | fixed     | NULL              |
| section_232_steel   | UK       | 0.25 | fixed     | NULL              |
| section_232_aluminum| default  | 0.50 | fixed     | NULL              |
| section_232_aluminum| UK       | 0.25 | fixed     | NULL              |
| section_232_copper  | default  | 0.50 | fixed     | NULL              |
| ieepa_reciprocal    | default  | 0.10 | fixed     | NULL              |
| ieepa_reciprocal    | EU       | NULL | formula   | 15pct_minus_mfn   |
| ieepa_reciprocal    | UK       | 0.10 | fixed     | NULL              |

### 15.5 hts_base_rates - MFN Column 1 rates

```sql
CREATE TABLE hts_base_rates (
    id              INTEGER PRIMARY KEY,
    hts_code        VARCHAR(12) NOT NULL,     -- '8544.42.9090' or '8544.42.90'
    column1_rate    DECIMAL(6,4) NOT NULL,    -- 0.026 = 2.6%
    description     VARCHAR(512),
    effective_date  DATE NOT NULL,
    expiration_date DATE,
    UNIQUE(hts_code, effective_date)
);
```

**Sample Data:**

| hts_code       | column1_rate | description                           |
|----------------|--------------|---------------------------------------|
| 8544.42.9090   | 0.026        | USB-C cables                          |
| 8539.50.00     | 0.020        | LED lamps                             |
| 8471.30.01     | 0.000        | Laptops (duty-free)                   |
| 2934.99.9050   | 0.064        | Nucleic acids (pharmaceuticals)       |

---

## 16. v5.0 Lookup Functions

### 16.1 get_country_group(country, import_date)

Maps country to its group for rate lookups.

```python
get_country_group("Germany", date.today())  # → "EU"
get_country_group("UK", date.today())       # → "UK"
get_country_group("Vietnam", date.today())  # → "default"
```

### 16.2 get_mfn_base_rate(hts_code, import_date)

Looks up MFN Column 1 rate for EU ceiling formula.

```python
get_mfn_base_rate("8544.42.9090", date.today())  # → 0.026 (2.6%)
```

Supports prefix matching: 8544.42.9090 → 8544.42.90 → 8544.42 → 8544

### 16.3 get_rate_for_program(program_id, country, hts_code, import_date)

Gets country-specific rate with formula support.

```python
# Fixed rate lookup
get_rate_for_program("section_232_steel", "UK", "8544.42.9090", date.today())
# → (0.25, "fixed_rate_UK")

# Formula evaluation
get_rate_for_program("ieepa_reciprocal", "Germany", "8544.42.9090", date.today())
# → (0.124, "EU 15% ceiling: 15% - 2.6% MFN = 12.4%")
```

---

## 17. v5.0 Test Results

All country test cases pass with expected results:

```
============================================================
Testing Program Rates by Country
============================================================
  ✓ section_232_steel / Germany: 50.0% (fixed_rate_default)
  ✓ section_232_steel / UK: 25.0% (fixed_rate_UK)
  ✓ section_232_aluminum / Germany: 50.0% (fixed_rate_default)
  ✓ section_232_aluminum / UK: 25.0% (fixed_rate_UK)
  ✓ section_232_copper / Germany: 50.0% (fixed_rate_default)
  ✓ section_232_copper / UK: 50.0% (fixed_rate_default)
  ✓ ieepa_reciprocal / Germany: 12.4% (EU 15% ceiling: 15% - 2.6% MFN = 12.4%)
  ✓ ieepa_reciprocal / UK: 10.0% (fixed_rate_UK)
  ✓ ieepa_reciprocal / Vietnam: 10.0% (fixed_rate_default)
```

### Test Case: Germany USB-C (v5.0 - EU 15% Ceiling)

**Input:**
```json
{
  "hts_code": "8544.42.9090",
  "country_of_origin": "Germany",
  "product_value": 10000.0,
  "materials": {
    "copper": 3000.0,
    "steel": 1000.0,
    "aluminum": 1000.0
  }
}
```

**Output:**
```
--- Germany ---
  Country Group: EU
  MFN Base Rate: 2.6%
  232 Copper: $3,000 x 50% = $1,500
  232 Steel: $1,000 x 50% = $500
  232 Aluminum: $1,000 x 50% = $500
  IEEPA Reciprocal: $5,000 x 12.4% = $620
    Source: EU 15% ceiling: 15% - 2.6% MFN = 12.4%
  ─────────────────
  TOTAL: $3,120 (31.2%)
```

### Test Case: UK USB-C (v5.0 - 232 Exception)

**Output:**
```
--- UK ---
  Country Group: UK
  232 Copper: $3,000 x 50% = $1,500
  232 Steel: $1,000 x 25% = $250   ← UK exception
  232 Aluminum: $1,000 x 25% = $250   ← UK exception
  IEEPA Reciprocal: $5,000 x 10.0% = $500
    Source: fixed_rate_UK
  ─────────────────
  TOTAL: $2,500 (25.0%)
```

### Test Case: China USB-C (v5.0 - Full Tariffs)

**Output:**
```
--- China ---
  Country Group: CN
  232 Copper: $3,000 x 50% = $1,500
  232 Steel: $1,000 x 50% = $500
  232 Aluminum: $1,000 x 50% = $500
  Section 301: $10,000 x 25% = $2,500
  IEEPA Fentanyl: $10,000 x 10% = $1,000
  IEEPA Reciprocal: $5,000 x 10.0% = $500
    Source: fixed_rate_default
  ─────────────────
  TOTAL: $6,500 (65.0%)
```

### Test Case: Vietnam USB-C (v5.0 - Default Rates)

**Output:**
```
--- Vietnam ---
  Country Group: default
  232 Copper: $3,000 x 50% = $1,500
  232 Steel: $1,000 x 50% = $500
  232 Aluminum: $1,000 x 50% = $500
  IEEPA Reciprocal: $5,000 x 10.0% = $500
    Source: fixed_rate_default
  ─────────────────
  TOTAL: $3,000 (30.0%)
```

---

## 18. v5.0 API Response with Metadata

```json
{
  "total_duty_amount": 3120.0,
  "total_duty_percent": 0.312,
  "effective_rate": 0.312,
  "breakdown": [
    {
      "program_id": "section_232_copper",
      "duty_rate": 0.50,
      "duty_amount": 1500.0,
      "rate_source": "fixed_rate_default"
    },
    {
      "program_id": "ieepa_reciprocal",
      "duty_rate": 0.124,
      "duty_amount": 620.0,
      "rate_source": "EU 15% ceiling: 15% - 2.6% MFN = 12.4%"
    }
  ],
  "v5_metadata": {
    "country": "Germany",
    "country_group": "EU",
    "hts_code": "8544.42.9090",
    "mfn_base_rate": 0.026,
    "rate_sources": {
      "section_232_copper": "fixed_rate_default",
      "ieepa_reciprocal": "EU 15% ceiling: 15% - 2.6% MFN = 12.4%"
    },
    "rates_as_of": "2025-12-10"
  }
}
```

---

## 19. v5.0 Files Changed

| File | Changes |
|------|---------|
| `app/web/db/models/tariff_tables.py` | Added 5 new models: `SourceDocument`, `CountryGroup`, `CountryGroupMember`, `ProgramRate`, `HtsBaseRate` |
| `scripts/populate_tariff_tables.py` | Added v5.0 seed data for country groups, program rates, HTS base rates, source documents |
| `app/chat/tools/stacking_tools.py` | Added `get_country_group()`, `get_rate_for_program()`, `get_mfn_base_rate()`. Updated `calculate_duties()` with v5.0 parameters |
| `app/chat/graphs/stacking_rag.py` | Updated `calculate_duties_node` to pass country/hts_code. Added v5.0 metadata to output |
| `scripts/test_v5_rates.py` | New test script for v5.0 rate lookups |

---

## 20. Scheduled Data Updates (Future)

The v5.0 architecture supports scheduled ingestion jobs for data freshness:

| Job | Frequency | Sources | Tables Updated |
|-----|-----------|---------|----------------|
| CSMS/FR Scan | Daily 03:00 UTC | CBP CSMS, Federal Register | `program_rates`, `section_232_materials` |
| USTR 301 Scan | Daily 03:15 UTC | USTR.gov | `section_301_inclusions/exclusions` |
| HTS Base Rates | Weekly (Sun 04:00) | USITC | `hts_base_rates` |
| Deep Resync | Monthly (1st 05:00) | All sources | All tables |

**Note:** Ingestion scripts (`ingest_csms_updates.py`, `ingest_hts_rates.py`) are planned for future implementation.

---

## 21. Canonical Rates (v5.0 - Dec 2025)

### By Country Group

| Program | Default | EU | UK |
|---------|---------|----|----|
| Section 232 Steel | 50% | 50% | **25%** |
| Section 232 Aluminum | 50% | 50% | **25%** |
| Section 232 Copper | 50% | 50% | 50% |
| IEEPA Reciprocal | 10% | **15% - MFN** | 10% |
| Section 301 | 25% (CN only) | N/A | N/A |
| IEEPA Fentanyl | 10% (CN only) | N/A | N/A |

### MFN Base Rates (Sample)

| HTS Code | MFN Rate | Description |
|----------|----------|-------------|
| 8544.42.9090 | 2.6% | USB-C cables |
| 8539.50.00 | 2.0% | LED lamps |
| 8471.30.01 | 0.0% | Laptops |
| 2934.99.9050 | 6.4% | Nucleic acids |

---

## 22. Running the v5.0 Tests

```bash
# Populate v5.0 tables
pipenv run python scripts/populate_tariff_tables.py --reset

# Run v5.0 rate tests
pipenv run python scripts/test_v5_rates.py
```

---

## TL;DR (v5.0)

**v5.0 extends v4.0 with:**

1. **Country-specific rates** - EU, UK, and default rate groups
2. **EU 15% ceiling rule** - Dynamic formula: `max(0, 15% - MFN_base_rate)`
3. **UK 232 exception** - Steel/Aluminum stays at 25% (not 50%)
4. **MFN base rate lookups** - Required for EU ceiling calculation
5. **Full audit trail** - Every rate lookup includes source document reference
6. **Future-proof architecture** - Ready for scheduled data ingestion jobs