"""
Regulatory Run Models

Tracks each polling/ingestion run with:
- RegulatoryRun: Top-level run metadata
- RegulatoryRunDocument: Documents discovered/processed in run
- RegulatoryRunChange: Changes committed during run
"""

from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import uuid4

from app.web.db import db
from app.web.db.models.base import BaseModel


class RegulatoryRun(BaseModel):
    """
    Tracks a single regulatory update polling cycle.

    Each run:
    - Polls one or more sources (Federal Register, CBP, USITC)
    - Discovers new documents
    - Processes and commits changes
    - Produces a JSON manifest for audit

    Status workflow:
    running → success | partial | failed
    """
    __tablename__ = "regulatory_runs"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))

    # Timing
    started_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)

    # Trigger
    trigger = db.Column(db.String(50), nullable=False, default="manual")  # cron, manual, backfill
    triggered_by = db.Column(db.String(100), nullable=True)  # scheduler, user:email, api

    # Status
    status = db.Column(db.String(50), nullable=False, default="running")
    # running → success, partial, failed

    # Scope
    sources_polled = db.Column(db.JSON, nullable=True)  # ["federal_register", "cbp_csms"]
    since_date = db.Column(db.Date, nullable=True)  # Poll since this date

    # Summary counts (updated as run progresses)
    summary_counts = db.Column(db.JSON, default=lambda: {
        "docs_discovered": 0,
        "docs_processed": 0,
        "docs_failed": 0,
        "changes_extracted": 0,
        "changes_validated": 0,
        "changes_committed": 0,
        "changes_rejected": 0,
        "needs_review": 0,
    })

    # Error tracking
    error_summary = db.Column(db.Text, nullable=True)
    warnings = db.Column(db.JSON, default=list)

    # Manifest export
    manifest_path = db.Column(db.String(256), nullable=True)  # data/regulatory_runs/YYYY-MM-DD_run_xxx.json
    manifest_exported_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    documents = db.relationship("RegulatoryRunDocument", backref="run", lazy="dynamic",
                               cascade="all, delete-orphan")
    changes = db.relationship("RegulatoryRunChange", backref="run", lazy="dynamic",
                             cascade="all, delete-orphan")

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "trigger": self.trigger,
            "status": self.status,
            "sources_polled": self.sources_polled,
            "since_date": self.since_date.isoformat() if self.since_date else None,
            "summary_counts": self.summary_counts,
            "error_summary": self.error_summary,
            "manifest_path": self.manifest_path,
        }

    def increment_count(self, key: str, amount: int = 1):
        """Increment a summary count."""
        if self.summary_counts is None:
            self.summary_counts = {}
        current = self.summary_counts.get(key, 0)
        self.summary_counts[key] = current + amount
        # SQLAlchemy needs to detect the mutation
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(self, "summary_counts")

    def add_warning(self, warning: str):
        """Add a warning message."""
        if self.warnings is None:
            self.warnings = []
        self.warnings.append(warning)
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(self, "warnings")

    def mark_completed(self, status: str = "success"):
        """Mark run as completed."""
        self.status = status
        self.completed_at = datetime.utcnow()


class RegulatoryRunDocument(BaseModel):
    """
    Tracks a document discovered/processed in a run.

    Links regulatory runs to official documents for traceability.
    """
    __tablename__ = "regulatory_run_documents"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id = db.Column(db.String(36), db.ForeignKey("regulatory_runs.id", ondelete="CASCADE"),
                      nullable=False, index=True)

    # Source identification
    source = db.Column(db.String(50), nullable=False)  # federal_register, cbp_csms, usitc
    external_id = db.Column(db.String(100), nullable=False)  # document_number, bulletin_id

    # Document reference (set after processing)
    document_id = db.Column(db.String(36), db.ForeignKey("official_documents.id"), nullable=True)
    ingest_job_id = db.Column(db.String(36), db.ForeignKey("ingest_jobs.id"), nullable=True)

    # Document metadata
    publication_date = db.Column(db.Date, nullable=True)
    effective_date = db.Column(db.Date, nullable=True)
    title = db.Column(db.String(500), nullable=True)

    # URLs
    url_xml = db.Column(db.String(500), nullable=True)
    url_pdf = db.Column(db.String(500), nullable=True)
    url_html = db.Column(db.String(500), nullable=True)

    # Processing status
    status = db.Column(db.String(50), default="discovered")
    # discovered → fetched → rendered → extracted → committed
    # OR → skipped (already processed), failed, needs_review

    content_hash = db.Column(db.String(64), nullable=True)
    error_message = db.Column(db.Text, nullable=True)

    # Counts for this document
    changes_extracted = db.Column(db.Integer, default=0)
    changes_committed = db.Column(db.Integer, default=0)

    # Timestamps
    discovered_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed_at = db.Column(db.DateTime, nullable=True)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "source": self.source,
            "external_id": self.external_id,
            "document_id": self.document_id,
            "publication_date": self.publication_date.isoformat() if self.publication_date else None,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "title": self.title,
            "url_xml": self.url_xml,
            "url_pdf": self.url_pdf,
            "status": self.status,
            "content_hash": self.content_hash,
            "changes_extracted": self.changes_extracted,
            "changes_committed": self.changes_committed,
        }


class RegulatoryRunChange(BaseModel):
    """
    Tracks individual tariff changes made during a run.

    Provides the audit trail: "What changed and why?"
    """
    __tablename__ = "regulatory_run_changes"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id = db.Column(db.String(36), db.ForeignKey("regulatory_runs.id", ondelete="CASCADE"),
                      nullable=False, index=True)
    run_doc_id = db.Column(db.String(36), db.ForeignKey("regulatory_run_documents.id"),
                          nullable=True, index=True)

    # Program identification
    program = db.Column(db.String(50), nullable=False)  # section_301, section_232_steel, ieepa_fentanyl
    country_scope = db.Column(db.String(50), nullable=True)  # CHN, HKG, MAC, ALL
    material_type = db.Column(db.String(20), nullable=True)  # steel, aluminum, copper (for 232)

    # What changed
    hts_8digit = db.Column(db.String(10), nullable=False, index=True)
    chapter_99_code = db.Column(db.String(16), nullable=True)
    duty_rate = db.Column(db.Numeric(5, 4), nullable=True)
    effective_start = db.Column(db.Date, nullable=True)
    effective_end = db.Column(db.Date, nullable=True)

    # Action type
    change_action = db.Column(db.String(20), nullable=False)
    # INSERT: New rate created
    # SUPERSEDE: Old rate closed, new rate opened
    # END: Rate ended (no replacement)
    # NOOP: No change needed
    # REJECTED: Failed validation
    # NEEDS_REVIEW: Requires human review

    # Why
    reason = db.Column(db.Text, nullable=True)  # "Four-Year Review staged schedule"

    # References
    source_doc_id = db.Column(db.String(36), db.ForeignKey("official_documents.id"), nullable=True)
    evidence_id = db.Column(db.String(36), db.ForeignKey("evidence_packets.id"), nullable=True)
    target_record_id = db.Column(db.String(36), nullable=True)  # ID of the created/updated record

    # Supersession tracking
    supersedes_record_id = db.Column(db.String(36), nullable=True)  # Record that was superseded

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "program": self.program,
            "country_scope": self.country_scope,
            "material_type": self.material_type,
            "hts_8digit": self.hts_8digit,
            "chapter_99_code": self.chapter_99_code,
            "duty_rate": float(self.duty_rate) if self.duty_rate else None,
            "effective_start": self.effective_start.isoformat() if self.effective_start else None,
            "effective_end": self.effective_end.isoformat() if self.effective_end else None,
            "change_action": self.change_action,
            "reason": self.reason,
            "source_doc_id": self.source_doc_id,
            "evidence_id": self.evidence_id,
        }


class TariffAuditLog(BaseModel):
    """
    Audit log for all tariff table changes.

    Records every INSERT, UPDATE, SUPERSEDE with:
    - Before/after values
    - Source document proof
    - Evidence packet reference
    """
    __tablename__ = "tariff_audit_log"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))

    # What changed
    table_name = db.Column(db.String(50), nullable=False, index=True)  # section_301_rates, etc.
    record_id = db.Column(db.String(36), nullable=False, index=True)
    action = db.Column(db.String(20), nullable=False)  # INSERT, UPDATE, SUPERSEDE, DELETE

    # Before/after state
    old_values = db.Column(db.JSON, nullable=True)
    new_values = db.Column(db.JSON, nullable=True)

    # Why (references)
    source_doc_id = db.Column(db.String(36), db.ForeignKey("official_documents.id"), nullable=True)
    evidence_id = db.Column(db.String(36), db.ForeignKey("evidence_packets.id"), nullable=True)
    change_reason = db.Column(db.Text, nullable=True)

    # Processing context
    job_id = db.Column(db.String(36), db.ForeignKey("ingest_jobs.id"), nullable=True)
    run_id = db.Column(db.String(36), db.ForeignKey("regulatory_runs.id"), nullable=True)

    # Who/when
    performed_by = db.Column(db.String(100), nullable=False, default="system")
    performed_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "table_name": self.table_name,
            "record_id": self.record_id,
            "action": self.action,
            "old_values": self.old_values,
            "new_values": self.new_values,
            "source_doc_id": self.source_doc_id,
            "evidence_id": self.evidence_id,
            "change_reason": self.change_reason,
            "performed_by": self.performed_by,
            "performed_at": self.performed_at.isoformat() if self.performed_at else None,
        }


class CandidateChangeRecord(BaseModel):
    """
    Persisted candidate changes awaiting review.

    When extraction succeeds but validation fails or Chapter 99 can't be resolved,
    candidates are stored here for human review.
    """
    __tablename__ = "candidate_changes"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))

    # Processing context
    job_id = db.Column(db.String(36), db.ForeignKey("ingest_jobs.id"), nullable=True, index=True)
    document_id = db.Column(db.String(36), db.ForeignKey("official_documents.id"), nullable=True)
    run_id = db.Column(db.String(36), db.ForeignKey("regulatory_runs.id"), nullable=True)

    # Extracted data
    hts_code = db.Column(db.String(12), nullable=False, index=True)
    chapter_99_code = db.Column(db.String(16), nullable=True)
    duty_rate = db.Column(db.Numeric(5, 4), nullable=True)
    effective_date = db.Column(db.Date, nullable=True)
    program = db.Column(db.String(50), nullable=True)

    # Evidence
    evidence_quote = db.Column(db.Text, nullable=True)
    evidence_line_start = db.Column(db.Integer, nullable=True)
    evidence_line_end = db.Column(db.Integer, nullable=True)
    extraction_method = db.Column(db.String(50), nullable=True)  # xml_table, llm_rag

    # Why it needs review
    review_reason = db.Column(db.String(256), nullable=True)  # chapter_99_unresolved, validation_failed
    validation_errors = db.Column(db.JSON, nullable=True)

    # Review status
    status = db.Column(db.String(50), default="pending", index=True)
    # pending → approved, rejected, corrected

    # Review outcome
    reviewed_by = db.Column(db.String(100), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    review_notes = db.Column(db.Text, nullable=True)

    # Corrections made by reviewer
    corrected_chapter_99 = db.Column(db.String(16), nullable=True)
    corrected_rate = db.Column(db.Numeric(5, 4), nullable=True)
    corrected_effective_date = db.Column(db.Date, nullable=True)

    # Result of approval
    committed_record_id = db.Column(db.String(36), nullable=True)  # ID of record created on approval

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "hts_code": self.hts_code,
            "chapter_99_code": self.chapter_99_code,
            "duty_rate": float(self.duty_rate) if self.duty_rate else None,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "program": self.program,
            "evidence_quote": self.evidence_quote[:200] + "..." if self.evidence_quote and len(self.evidence_quote) > 200 else self.evidence_quote,
            "review_reason": self.review_reason,
            "status": self.status,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
