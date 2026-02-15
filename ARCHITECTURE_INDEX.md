# Lanes Tariff Compliance Chatbot - Architecture Analysis Index

**Analysis Date:** February 10, 2026  
**Analysis Type:** Comprehensive Architectural Deep Dive (RESEARCH ONLY)  
**Analyst Notes:** This is a production tariff stacking engine with ~8,000 lines of core logic across database, graph orchestration, and tool layer.

---

## 📚 Documentation Files

This analysis generates **3 comprehensive documents**:

### 1. **ARCHITECTURE_ANALYSIS.md** (67 KB, 1,543 lines)
The definitive guide to the entire system architecture.

**Sections:**
1. **Executive Summary** - System overview, key principles
2. **Overall Architecture** - Technology stack, component diagram, file overview
3. **Data Flow** - User query → processing → response with detailed diagrams
4. **Stacking Engine Deep Dive** - 50 tool functions with detailed explanations
   - 301/232/IEEPA interaction example with actual numbers
   - Material composition evaluation
   - Dependency resolution
   - Duty calculation (Phase 6 & 6.5)
5. **Data Models** - All ~30 SQLAlchemy tables explained
   - Temporal rate lookups
   - Country-specific rates with formula support
   - Database schema diagram
6. **RAG Pipeline** - Pinecone vector store integration
7. **LLM Integration** - LangGraph architecture, 11 graph nodes, tool calling
8. **Data Ingestion Pipeline** - CSV → database flow, validation scripts
9. **Web UI Architecture** - React frontend, Flask API endpoints
10. **Configuration & Environment** - .env variables, deployment config
11. **Known Limitations & Gaps** - Documented issues, feature gaps, edge cases
12. **Deployment & Operations** - Railway.app, scaling considerations
13. **Architecture Summary** - Component interaction, design principles
14. **Key Files Reference** - Complete file organization with line counts

**Use this when:** You need comprehensive understanding of how the entire system works.

---

### 2. **ARCHITECTURE_DETAILED_REFERENCE.md** (37 KB, 1,050 lines)
Code-level reference with specific line numbers and implementation details.

**Sections:**
1. **Tariff Stacking Calculation** - Detailed flow with line numbers
   - Tool call chain with exact line references
   - Duty calculation algorithm (Phase 6 & 6.5) with code snippets
   - Material composition evaluation logic
2. **Database Schema** - Detailed table explanations
   - Temporal rate lookup pattern (Section301Rate)
   - Country-group-specific rates with EU 15% formula
3. **LangGraph State Machine** - Graph node execution
   - Graph construction code
   - Node implementations with line numbers
   - Tool invocation & message handling
4. **Data Files** - CSV structure and row counts
   - Master config files
   - Rate tables
   - All data file formats
5. **Critical Hardcoded Values** - IEEPA codes, feature flags
6. **Error Handling & Validation** - Material value checks, HTS normalization
7. **Audit Trail & Logging** - Decision logging, calculation logging
8. **Versioning & History** - Version timeline, migration paths
9. **Integration Points** - External services, MCP servers
10. **Quick Reference** - Testing, monitoring, deployment commands

**Use this when:** You need to find specific code, understand exact logic, or debug issues.

---

### 3. **ARCHITECTURE_SUMMARY.txt** (16 KB, 454 lines)
Quick reference guide for the entire architecture.

**Sections:**
- System overview (what it does, core architecture)
- 5 key components with line counts
- Data flow diagram
- Critical calculation logic (Phase 6, Phase 6.5, EU formula)
- Database schema (30 tables listed)
- CSV data files with row counts
- Hardcoded values
- Known limitations
- Deployment info
- Technology stack
- Quick start commands
- Versioning timeline
- Key files reference

**Use this when:** You need a quick overview or reference during development.

---

## 🎯 Quick Navigation by Use Case

### "I need to understand the entire system"
→ Start with **ARCHITECTURE_SUMMARY.txt** (5 min read)  
→ Then **ARCHITECTURE_ANALYSIS.md** Section 1-3 (data flow)

### "How does tariff calculation work?"
→ **ARCHITECTURE_ANALYSIS.md** Section 3-4 (data flow + stacking engine)  
→ **ARCHITECTURE_DETAILED_REFERENCE.md** Section 1 (line-by-line logic)

### "What database tables exist and how do they relate?"
→ **ARCHITECTURE_ANALYSIS.md** Section 4 (data models)  
→ **ARCHITECTURE_DETAILED_REFERENCE.md** Section 2 (schema details)

### "How does the LangGraph orchestration work?"
→ **ARCHITECTURE_ANALYSIS.md** Section 6 (LLM integration)  
→ **ARCHITECTURE_DETAILED_REFERENCE.md** Section 3 (graph node code)

### "What are the data files and how are they loaded?"
→ **ARCHITECTURE_ANALYSIS.md** Section 7 (data ingestion)  
→ **ARCHITECTURE_DETAILED_REFERENCE.md** Section 4 (CSV formats with row counts)

### "I need to find a specific piece of code"
→ **ARCHITECTURE_DETAILED_REFERENCE.md** (has specific line numbers)  
→ **ARCHITECTURE_SUMMARY.txt** (key files reference section)

### "What are the known bugs and limitations?"
→ **ARCHITECTURE_ANALYSIS.md** Section 10 (known limitations & gaps)  
→ **ARCHITECTURE_DETAILED_REFERENCE.md** Section 6 (error handling)

### "How do I deploy or operate this?"
→ **ARCHITECTURE_ANALYSIS.md** Section 12 (deployment & operations)  
→ **ARCHITECTURE_SUMMARY.txt** (deployment section + quick start)

---

## 📊 Key Statistics

### Code Size
- **Stacking engine:** 2,743 lines (stacking_tools.py) - 50 tool functions
- **Data models:** 1,811 lines (tariff_tables.py) - ~30 SQLAlchemy tables
- **Graph orchestration:** 1,300+ lines (stacking_rag.py) - 11 graph nodes
- **API endpoints:** 1,000+ lines (tariff_views.py)
- **Data ingestion:** 2,000+ lines (populate_tariff_tables.py)
- **Total analyzed:** ~8,000+ lines of core logic

### Database
- **Tables:** ~30 SQLAlchemy models
- **Temporal tables:** Section301Rate (10,811), Section232Rate (1,638), IeepaRate (46)
- **Audit tables:** TariffCalculationLog, SourceVersion, IngestionRun
- **Total rows:** ~50,000+ records

### Data Files
- **CSV files:** 10 files in data/ and data/current/
- **Total rows:** ~50,000+ (mostly MFN rates and rate tables)
- **Key files:**
  - section_301_rates.csv: 10,811 rows (temporal rates)
  - mfn_base_rates_8digit.csv: 15,263 rows (for formula calculations)
  - section_232_rates.csv: 1,638 rows
  - section_301_inclusions.csv: 11,372 rows (legacy)
  - exclusion_claims.csv: 179 rows

### External Dependencies
- **LLM:** OpenAI GPT-4 (gpt-4-turbo)
- **Vector Store:** Pinecone (us-east-1, docs index)
- **Database:** PostgreSQL (production), SQLite (development)
- **Job Queue:** Celery + Redis
- **Framework:** Flask + LangChain + LangGraph

---

## 🔑 Key Architectural Principles

1. **Data-Driven Core**
   - All tariff logic in database tables, not hardcoded
   - Non-technical users update rates via CSV files
   - No hardcoded country lists or HTS rules

2. **Temporal Tracking**
   - Effective date ranges for all rates
   - Historical queries supported (as_of_date)
   - Supersession tracking (rate migrations)

3. **Deterministic Calculation**
   - No LLM in critical tariff math path
   - Repeatable results (audit trail included)
   - Full source citations for compliance

4. **Multi-Program Stacking**
   - Simultaneous Section 301, 232, IEEPA processing
   - Filing sequence respected (ACE compliance)
   - Separate calculation sequence (for unstacking)

5. **Entry Slicing**
   - Products split by material type
   - Separate claim/disclaim codes per slice
   - CBP Phoebe-aligned structure

6. **Comprehensive Auditing**
   - Every decision logged with source
   - SourceVersion table for compliance audit trail
   - TariffCalculationLog for replay capability

---

## ⚠️ Critical Implementation Details

### PHASE 6: Content-Value-Based Duties (Section 232)
```
If material % >= min_threshold:
  content_value = material% × product_value
  duty = content_value × rate  (NOT percentage of product)
```

### PHASE 6.5: IEEPA Unstacking
```
remaining_value = product_value
For each 232 material:
  remaining_value -= material_content_value
IEEPA_Reciprocal_duty = remaining_value × rate
(NOT product_value × rate)
```

### v5.0 EU 15% Ceiling Formula
```
Query: ProgramRate with country_group="EU"
If formula = "15% - MFN":
  mfn_rate = HtsBaseRate.mfn_rate for HTS
  duty_rate = max(0, 0.15 - mfn_rate)
```

### IEEPA Code Corrections (v12.0)
```
Fentanyl: 9903.01.24  (NOT 9903.01.25!)
Reciprocal:
  standard: 9903.01.25 (10%)
  annex_ii_exempt: 9903.01.32 (0%)
  section_232_exempt: 9903.01.33 (0%)
  us_content_exempt: 9903.01.34 (0%)
```

---

## 🐛 Known Issues & Gaps

### Critical Bugs
- ❌ Material value validation: sum(materials.values()) must be <= product_value
- ❌ No HTS6/4/2 fallback: Section 301 requires exact HTS8/10 match
- ❌ Semantic exclusion match may fail for product description variations

### Architecture Limitations
- ❌ In-memory sessions lost on server restart (use database session store in production)
- ❌ No temporal filter in RAG vector search (manual document curation)
- ❌ IEEPA codes partially hardcoded (v13.0 migration started)

### Data Quality Issues
- ❌ Rates last updated 2026-02-07 (manual ingestion dependency)
- ❌ Country alias coverage: 50 entries (may miss variations)
- ❌ Coverage gaps in Section 301 lists (false negatives possible)

### Feature Gaps
- ❌ No batch calculations (single HTS per request)
- ❌ No rate history comparison UI (temporal queries exist but not exposed)
- ❌ No exclusion approval workflow (UI missing)
- ❌ No "what-if" scenario modeling

---

## 🚀 Getting Started

### Load Data
```bash
python scripts/populate_tariff_tables.py --seed-if-empty
```

### Test Calculation
```bash
python scripts/test_stacking.py
```

### Start Web Server
```bash
FLASK_APP=app.web FLASK_ENV=development flask run
```

### Query Database
```bash
sqlite3 lanes.db
SELECT COUNT(*) FROM section_301_rates;  # Should be ~10,811
```

---

## 📖 File Locations (Absolute Paths)

**Analysis Documents:**
- `/sessions/hopeful-ecstatic-darwin/mnt/lanes/ARCHITECTURE_ANALYSIS.md`
- `/sessions/hopeful-ecstatic-darwin/mnt/lanes/ARCHITECTURE_DETAILED_REFERENCE.md`
- `/sessions/hopeful-ecstatic-darwin/mnt/lanes/ARCHITECTURE_SUMMARY.txt`
- `/sessions/hopeful-ecstatic-darwin/mnt/lanes/ARCHITECTURE_INDEX.md` (this file)

**Core Code:**
- `/sessions/hopeful-ecstatic-darwin/mnt/lanes/app/chat/tools/stacking_tools.py` (2,743 lines)
- `/sessions/hopeful-ecstatic-darwin/mnt/lanes/app/web/db/models/tariff_tables.py` (1,811 lines)
- `/sessions/hopeful-ecstatic-darwin/mnt/lanes/app/chat/graphs/stacking_rag.py` (1,300+ lines)
- `/sessions/hopeful-ecstatic-darwin/mnt/lanes/app/web/views/tariff_views.py` (1,000+ lines)
- `/sessions/hopeful-ecstatic-darwin/mnt/lanes/scripts/populate_tariff_tables.py` (2,000+ lines)

**Configuration:**
- `/sessions/hopeful-ecstatic-darwin/mnt/lanes/railway.toml`
- `/sessions/hopeful-ecstatic-darwin/mnt/lanes/wsgi.py`
- `/sessions/hopeful-ecstatic-darwin/mnt/lanes/requirements.txt`
- `/sessions/hopeful-ecstatic-darwin/mnt/lanes/.env`

**Data Files:**
- `/sessions/hopeful-ecstatic-darwin/mnt/lanes/data/current/` (6 CSV files)
- `/sessions/hopeful-ecstatic-darwin/mnt/lanes/data/` (reference/master files)

---

## 📋 Table of Contents Quick Links

**ARCHITECTURE_ANALYSIS.md:**
1. Executive Summary
2. Overall Architecture
3. Data Flow
4. Stacking Engine Deep Dive
5. Data Models
6. RAG Pipeline
7. LLM Integration
8. Data Ingestion Pipeline
9. Web UI Architecture
10. Configuration & Environment
11. Known Limitations & Gaps
12. Deployment & Operations
13. Architecture Summary
14. Key Files Reference

**ARCHITECTURE_DETAILED_REFERENCE.md:**
1. Tariff Stacking Calculation (with line numbers)
2. Database Schema (detailed patterns)
3. LangGraph State Machine (node code)
4. Data Files (CSV structures)
5. Critical Hardcoded Values
6. Error Handling & Validation
7. Audit Trail & Logging
8. Versioning & History
9. Integration Points
10. Quick Reference

**ARCHITECTURE_SUMMARY.txt:**
- System Overview
- Key Components
- Data Flow (ASCII diagram)
- Critical Calculation Logic
- Database Schema (30 tables)
- Data Files (CSV list with row counts)
- Hardcoded Values
- Known Limitations & Gaps
- Deployment
- Technology Stack
- Quick Start
- Versioning
- Key Files Reference

---

## 🎓 Recommended Reading Order

1. **New to the system?**
   - Read ARCHITECTURE_SUMMARY.txt (15 min)
   - Then ARCHITECTURE_ANALYSIS.md sections 1-3 (30 min)

2. **Need to understand tariff calculations?**
   - Read ARCHITECTURE_ANALYSIS.md section 4 (30 min)
   - Then ARCHITECTURE_DETAILED_REFERENCE.md section 1 (30 min)

3. **Debugging or extending the system?**
   - Use ARCHITECTURE_DETAILED_REFERENCE.md as reference (line numbers!)
   - Check ARCHITECTURE_ANALYSIS.md section 10 for known issues
   - Review ARCHITECTURE_SUMMARY.txt section "Known Limitations & Gaps"

4. **Deep dive (researcher/architect)?**
   - Read all 3 documents front-to-back
   - Total reading time: ~2-3 hours
   - Provides complete understanding of architecture, data flow, and design decisions

---

**Analysis completed:** February 10, 2026  
**Status:** COMPREHENSIVE - All major components analyzed  
**Modification Status:** RESEARCH ONLY - No code modifications made

