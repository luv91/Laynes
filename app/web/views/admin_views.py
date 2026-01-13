"""
Admin Views for Regulatory Pipeline

Provides endpoints for:
1. Viewing pending candidate changes (needs_review)
2. Approving/rejecting candidates
3. Viewing regulatory run history
4. Manual trigger of pipeline stages
"""

from datetime import datetime
from flask import Blueprint, request, jsonify
from sqlalchemy import desc

from app.web.db import db
from app.models import (
    CandidateChangeRecord,
    RegulatoryRun,
    RegulatoryRunDocument,
    RegulatoryRunChange,
    TariffAuditLog,
    IngestJob,
    OfficialDocument,
    EvidencePacket,
)
from app.workers.commit_engine import CommitEngine
from app.workers.extraction_worker import CandidateChange

bp = Blueprint("admin", __name__, url_prefix="/admin")


# ─────────────────────────────────────────────────────────────────────────────
# Needs Review Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/needs-review", methods=["GET"])
def list_needs_review():
    """
    List all pending candidate changes awaiting review.

    Query params:
        status: Filter by status (pending, approved, rejected)
        limit: Max results (default 50)
        offset: Pagination offset
    """
    try:
        status = request.args.get("status", "pending")
        limit = min(int(request.args.get("limit", 50)), 200)
        offset = int(request.args.get("offset", 0))

        query = CandidateChangeRecord.query

        if status != "all":
            query = query.filter(CandidateChangeRecord.status == status)

        # Order by created_at desc (newest first)
        query = query.order_by(desc(CandidateChangeRecord.created_at))

        total = query.count()
        candidates = query.offset(offset).limit(limit).all()

        return jsonify({
            "success": True,
            "total": total,
            "offset": offset,
            "limit": limit,
            "candidates": [_serialize_candidate(c) for c in candidates],
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/needs-review/<candidate_id>", methods=["GET"])
def get_candidate_detail(candidate_id: str):
    """Get detailed view of a single candidate change."""
    try:
        candidate = CandidateChangeRecord.query.get(candidate_id)
        if not candidate:
            return jsonify({"success": False, "error": "Candidate not found"}), 404

        # Get related document and evidence
        doc = OfficialDocument.query.get(candidate.document_id) if candidate.document_id else None
        job = IngestJob.query.get(candidate.job_id) if candidate.job_id else None

        return jsonify({
            "success": True,
            "candidate": _serialize_candidate(candidate),
            "document": {
                "id": str(doc.id) if doc else None,
                "source": doc.source if doc else None,
                "external_id": doc.external_id if doc else None,
                "title": doc.title if doc else None,
                "publication_date": doc.publication_date.isoformat() if doc and doc.publication_date else None,
            } if doc else None,
            "job": {
                "id": str(job.id) if job else None,
                "status": job.status if job else None,
                "discovered_at": job.discovered_at.isoformat() if job and job.discovered_at else None,
            } if job else None,
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/needs-review/<candidate_id>/approve", methods=["POST"])
def approve_candidate(candidate_id: str):
    """
    Approve a candidate change and commit it to tariff tables.

    Body:
        reviewed_by: Name of reviewer (required)
        notes: Optional review notes
        chapter_99_code: Override Chapter 99 code if needed
        duty_rate: Override duty rate if needed
    """
    try:
        candidate = CandidateChangeRecord.query.get(candidate_id)
        if not candidate:
            return jsonify({"success": False, "error": "Candidate not found"}), 404

        if candidate.status != "pending":
            return jsonify({
                "success": False,
                "error": f"Candidate already {candidate.status}"
            }), 400

        data = request.json or {}
        reviewed_by = data.get("reviewed_by", "admin")

        # Allow overrides
        if data.get("chapter_99_code"):
            candidate.chapter_99_code = data["chapter_99_code"]
        if data.get("duty_rate"):
            candidate.duty_rate = data["duty_rate"]
        if data.get("effective_date"):
            candidate.effective_date = datetime.fromisoformat(data["effective_date"]).date()

        # Get related document and job
        doc = OfficialDocument.query.get(candidate.document_id) if candidate.document_id else None
        job = IngestJob.query.get(candidate.job_id) if candidate.job_id else None

        if not doc:
            return jsonify({"success": False, "error": "Source document not found"}), 400

        # Create evidence packet for approved change
        evidence = EvidencePacket(
            doc_id=doc.id,
            quote=candidate.evidence_quote or "",
            line_start=candidate.evidence_line_start or 0,
            line_end=candidate.evidence_line_end or 0,
            resolution_method="manual_review",
            confidence_score=1.0,
        )
        db.session.add(evidence)
        db.session.flush()

        # Convert back to CandidateChange for commit engine
        change = CandidateChange(
            document_id=str(doc.id),
            hts_code=candidate.hts_code,
            new_chapter_99_code=candidate.chapter_99_code,
            rate=float(candidate.duty_rate) if candidate.duty_rate else None,
            effective_date=candidate.effective_date,
            program=candidate.program or "",
            evidence_quote=candidate.evidence_quote or "",
            evidence_line_start=candidate.evidence_line_start or 0,
            evidence_line_end=candidate.evidence_line_end or 0,
            extraction_method="manual_review",
        )

        # Commit via engine
        engine = CommitEngine()
        success, record_id, error = engine.commit_candidate(
            candidate=change,
            evidence=evidence,
            doc=doc,
            job=job,
            run_id=candidate.run_id,
        )

        if success:
            candidate.status = "approved"
            candidate.reviewed_by = reviewed_by
            candidate.reviewed_at = datetime.utcnow()
            candidate.review_notes = data.get("notes")
            candidate.committed_record_id = record_id
            db.session.commit()

            return jsonify({
                "success": True,
                "message": f"Approved and committed as record {record_id}",
                "record_id": record_id,
            })
        else:
            db.session.rollback()
            return jsonify({
                "success": False,
                "error": f"Commit failed: {error}",
            }), 500

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/needs-review/<candidate_id>/reject", methods=["POST"])
def reject_candidate(candidate_id: str):
    """
    Reject a candidate change.

    Body:
        reviewed_by: Name of reviewer (required)
        notes: Reason for rejection (required)
    """
    try:
        candidate = CandidateChangeRecord.query.get(candidate_id)
        if not candidate:
            return jsonify({"success": False, "error": "Candidate not found"}), 404

        if candidate.status != "pending":
            return jsonify({
                "success": False,
                "error": f"Candidate already {candidate.status}"
            }), 400

        data = request.json or {}
        reviewed_by = data.get("reviewed_by", "admin")
        notes = data.get("notes", "")

        if not notes:
            return jsonify({
                "success": False,
                "error": "Rejection reason (notes) is required"
            }), 400

        candidate.status = "rejected"
        candidate.reviewed_by = reviewed_by
        candidate.reviewed_at = datetime.utcnow()
        candidate.review_notes = notes
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Candidate rejected",
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Regulatory Runs Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/runs", methods=["GET"])
def list_runs():
    """
    List regulatory runs.

    Query params:
        status: Filter by status
        limit: Max results (default 20)
        offset: Pagination offset
    """
    try:
        limit = min(int(request.args.get("limit", 20)), 100)
        offset = int(request.args.get("offset", 0))
        status = request.args.get("status")

        query = RegulatoryRun.query

        if status:
            query = query.filter(RegulatoryRun.status == status)

        query = query.order_by(desc(RegulatoryRun.started_at))

        total = query.count()
        runs = query.offset(offset).limit(limit).all()

        return jsonify({
            "success": True,
            "total": total,
            "offset": offset,
            "limit": limit,
            "runs": [_serialize_run(r) for r in runs],
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/runs/<run_id>", methods=["GET"])
def get_run_detail(run_id: str):
    """Get detailed view of a regulatory run."""
    try:
        run = RegulatoryRun.query.get(run_id)
        if not run:
            return jsonify({"success": False, "error": "Run not found"}), 404

        # Get documents processed in this run
        docs = RegulatoryRunDocument.query.filter_by(run_id=run_id).all()

        # Get changes made in this run
        changes = RegulatoryRunChange.query.filter_by(run_id=run_id).all()

        return jsonify({
            "success": True,
            "run": _serialize_run(run),
            "documents": [{
                "id": str(d.id),
                "source": d.source,
                "external_id": d.external_id,
                "title": d.title,
                "status": d.status,
                "publication_date": d.publication_date.isoformat() if d.publication_date else None,
            } for d in docs],
            "changes": [{
                "id": str(c.id),
                "program": c.program,
                "hts_8digit": c.hts_8digit,
                "chapter_99_code": c.chapter_99_code,
                "duty_rate": float(c.duty_rate) if c.duty_rate else None,
                "change_action": c.change_action,
                "effective_start": c.effective_start.isoformat() if c.effective_start else None,
            } for c in changes],
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Audit Log Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/audit-log", methods=["GET"])
def list_audit_log():
    """
    List tariff audit log entries.

    Query params:
        table_name: Filter by table (section_301_rates, etc.)
        action: Filter by action (INSERT, SUPERSEDE, etc.)
        limit: Max results (default 50)
        offset: Pagination offset
    """
    try:
        limit = min(int(request.args.get("limit", 50)), 200)
        offset = int(request.args.get("offset", 0))
        table_name = request.args.get("table_name")
        action = request.args.get("action")

        query = TariffAuditLog.query

        if table_name:
            query = query.filter(TariffAuditLog.table_name == table_name)
        if action:
            query = query.filter(TariffAuditLog.action == action)

        query = query.order_by(desc(TariffAuditLog.created_at))

        total = query.count()
        entries = query.offset(offset).limit(limit).all()

        return jsonify({
            "success": True,
            "total": total,
            "offset": offset,
            "limit": limit,
            "entries": [{
                "id": str(e.id),
                "table_name": e.table_name,
                "record_id": e.record_id,
                "action": e.action,
                "performed_by": e.performed_by,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "old_values": e.old_values,
                "new_values": e.new_values,
            } for e in entries],
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline Control Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/pipeline/status", methods=["GET"])
def pipeline_status():
    """Get current pipeline status and queue depth."""
    try:
        # Count jobs by status
        queued = IngestJob.query.filter_by(status="queued").count()
        processing = IngestJob.query.filter_by(status="processing").count()
        needs_review = CandidateChangeRecord.query.filter_by(status="pending").count()

        # Get last run
        last_run = RegulatoryRun.query.order_by(desc(RegulatoryRun.completed_at)).first()

        return jsonify({
            "success": True,
            "queue": {
                "queued": queued,
                "processing": processing,
                "needs_review": needs_review,
            },
            "last_run": _serialize_run(last_run) if last_run else None,
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/freshness", methods=["GET"])
def freshness():
    """
    Get data freshness status per source.

    Returns last successful run for each source (federal_register, cbp_csms)
    with documents processed and changes committed.

    PRC-5: Freshness UI reads from regulatory_runs table.
    """
    try:
        from datetime import datetime, timedelta

        sources = ["federal_register", "cbp_csms"]
        freshness_data = {}

        for source in sources:
            # Find last successful run that polled this source
            # sources_polled is a JSON field, so we need to check if source key exists
            last_run = RegulatoryRun.query.filter(
                RegulatoryRun.status.in_(["success", "partial"]),
                RegulatoryRun.completed_at.isnot(None),
            ).order_by(desc(RegulatoryRun.completed_at)).all()

            # Filter to runs that polled this source
            source_run = None
            for run in last_run:
                if run.sources_polled and run.sources_polled.get(source):
                    source_run = run
                    break

            if source_run:
                # Calculate age
                age_seconds = (datetime.utcnow() - source_run.completed_at).total_seconds()
                age_hours = age_seconds / 3600

                # Determine freshness status
                if age_hours < 6:
                    status = "fresh"
                elif age_hours < 24:
                    status = "stale"
                else:
                    status = "outdated"

                freshness_data[source] = {
                    "last_run_id": str(source_run.id),
                    "last_run_at": source_run.completed_at.isoformat(),
                    "age_hours": round(age_hours, 1),
                    "status": status,
                    "trigger": source_run.trigger,
                    "docs_discovered": source_run.summary_counts.get("discovered", 0) if source_run.summary_counts else 0,
                    "docs_queued": source_run.summary_counts.get("queued", 0) if source_run.summary_counts else 0,
                    "docs_skipped": source_run.summary_counts.get("skipped", 0) if source_run.summary_counts else 0,
                }
            else:
                freshness_data[source] = {
                    "last_run_id": None,
                    "last_run_at": None,
                    "age_hours": None,
                    "status": "never_synced",
                    "trigger": None,
                    "docs_discovered": 0,
                    "docs_queued": 0,
                    "docs_skipped": 0,
                }

        # Also include overall pipeline health
        queue_depth = IngestJob.query.filter_by(status="queued").count()
        pending_review = CandidateChangeRecord.query.filter_by(status="pending").count()

        # Get today's changes
        today = datetime.utcnow().date()
        today_changes = RegulatoryRunChange.query.filter(
            RegulatoryRunChange.created_at >= datetime(today.year, today.month, today.day)
        ).count()

        return jsonify({
            "success": True,
            "sources": freshness_data,
            "pipeline": {
                "queue_depth": queue_depth,
                "pending_review": pending_review,
                "changes_today": today_changes,
            },
            "timestamp": datetime.utcnow().isoformat(),
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/pipeline/trigger-watcher", methods=["POST"])
def trigger_watcher():
    """
    Manually trigger a watcher run.

    Body:
        source: Source to poll (federal_register, cbp_csms)
        since_date: Optional date to poll from (YYYY-MM-DD)
    """
    try:
        data = request.json or {}
        source = data.get("source", "federal_register")

        from datetime import timedelta, date as date_type
        from app.watchers.base import enqueue_discovered_documents

        since_date = None
        if data.get("since_date"):
            since_date = date_type.fromisoformat(data["since_date"])
        else:
            since_date = date_type.today() - timedelta(days=7)

        # Create run record
        run = RegulatoryRun(
            trigger="manual",
            status="running",
            started_at=datetime.utcnow(),
            sources_polled={source: True},
        )
        db.session.add(run)
        db.session.commit()

        # Run watcher
        if source == "federal_register":
            from app.watchers.federal_register import FederalRegisterWatcher
            watcher = FederalRegisterWatcher()
            docs = watcher.poll(since_date)
            stats = enqueue_discovered_documents(run.id, docs)
        else:
            return jsonify({
                "success": False,
                "error": f"Unknown source: {source}"
            }), 400

        # Update run
        run.completed_at = datetime.utcnow()
        run.status = "success"
        run.summary_counts = stats
        db.session.commit()

        return jsonify({
            "success": True,
            "run_id": run.id,
            "discovered": stats.get("queued", 0),
            "skipped": stats.get("skipped", 0),
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/pipeline/process-queue", methods=["POST"])
def process_queue():
    """
    Manually trigger queue processing.

    Body:
        max_jobs: Max jobs to process (default 10)
        source: Optional source filter
    """
    try:
        data = request.json or {}
        max_jobs = min(int(data.get("max_jobs", 10)), 50)
        source_filter = data.get("source")

        from app.workers.pipeline import DocumentPipeline
        pipeline = DocumentPipeline()
        results = pipeline.process_queue(max_jobs=max_jobs, source_filter=source_filter)

        return jsonify({
            "success": True,
            "processed": len(results),
            "results": [{
                "job_id": r.get("job_id"),
                "status": r.get("status"),
                "changes_extracted": r.get("changes_extracted", 0),
                "changes_committed": r.get("changes_committed", 0),
            } for r in results],
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Health and Monitoring Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/health", methods=["GET"])
def health_check():
    """
    Health check endpoint for load balancers and monitoring.

    Returns 200 if system is healthy, 503 if degraded.
    """
    try:
        from datetime import timedelta

        issues = []
        warnings = []

        # Check database connectivity
        try:
            db.session.execute(db.text("SELECT 1"))
        except Exception as e:
            issues.append(f"Database unreachable: {e}")

        # Check queue depth (warning if > 100)
        queue_depth = IngestJob.query.filter_by(status="queued").count()
        if queue_depth > 100:
            warnings.append(f"High queue depth: {queue_depth}")

        # Check for stuck jobs (processing for > 1 hour)
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)
        stuck_jobs = IngestJob.query.filter(
            IngestJob.status == "processing",
            IngestJob.updated_at < one_hour_ago
        ).count()
        if stuck_jobs > 0:
            warnings.append(f"Stuck jobs: {stuck_jobs}")

        # Check for failed runs in last 24h
        one_day_ago = datetime.utcnow() - timedelta(hours=24)
        failed_runs = RegulatoryRun.query.filter(
            RegulatoryRun.status == "failed",
            RegulatoryRun.completed_at >= one_day_ago
        ).count()
        if failed_runs > 0:
            warnings.append(f"Failed runs in 24h: {failed_runs}")

        # Check data freshness (warning if no run in 24h)
        last_run = RegulatoryRun.query.filter(
            RegulatoryRun.status.in_(["success", "partial"])
        ).order_by(desc(RegulatoryRun.completed_at)).first()

        if last_run:
            age_hours = (datetime.utcnow() - last_run.completed_at).total_seconds() / 3600
            if age_hours > 24:
                warnings.append(f"No successful run in {int(age_hours)}h")

        # Determine overall status
        if issues:
            status = "unhealthy"
            http_status = 503
        elif warnings:
            status = "degraded"
            http_status = 200
        else:
            status = "healthy"
            http_status = 200

        return jsonify({
            "status": status,
            "timestamp": datetime.utcnow().isoformat(),
            "checks": {
                "database": "ok" if "Database" not in str(issues) else "failed",
                "queue_depth": queue_depth,
                "stuck_jobs": stuck_jobs,
                "failed_runs_24h": failed_runs,
                "last_run_hours_ago": round(age_hours, 1) if last_run else None,
            },
            "issues": issues,
            "warnings": warnings,
        }), http_status

    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }), 503


@bp.route("/metrics", methods=["GET"])
def metrics():
    """
    Prometheus-style metrics endpoint.

    Returns key metrics in a format suitable for monitoring systems.
    """
    try:
        from datetime import timedelta

        # Queue metrics
        queued = IngestJob.query.filter_by(status="queued").count()
        processing = IngestJob.query.filter_by(status="processing").count()
        pending_review = CandidateChangeRecord.query.filter_by(status="pending").count()

        # Today's metrics
        today = datetime.utcnow().date()
        today_start = datetime(today.year, today.month, today.day)

        jobs_completed_today = IngestJob.query.filter(
            IngestJob.status.in_(["committed", "completed_no_changes"]),
            IngestJob.completed_at >= today_start
        ).count()

        changes_committed_today = RegulatoryRunChange.query.filter(
            RegulatoryRunChange.created_at >= today_start
        ).count()

        docs_processed_today = RegulatoryRunDocument.query.filter(
            RegulatoryRunDocument.created_at >= today_start
        ).count()

        # Run metrics
        runs_today = RegulatoryRun.query.filter(
            RegulatoryRun.started_at >= today_start
        ).count()

        failed_runs_today = RegulatoryRun.query.filter(
            RegulatoryRun.status == "failed",
            RegulatoryRun.started_at >= today_start
        ).count()

        # Last run timing
        last_run = RegulatoryRun.query.filter(
            RegulatoryRun.status.in_(["success", "partial"])
        ).order_by(desc(RegulatoryRun.completed_at)).first()

        last_run_seconds_ago = None
        if last_run and last_run.completed_at:
            last_run_seconds_ago = int((datetime.utcnow() - last_run.completed_at).total_seconds())

        # Return Prometheus-compatible text format
        metrics_text = f"""# HELP pipeline_queue_depth Number of jobs in queue
# TYPE pipeline_queue_depth gauge
pipeline_queue_depth{{status="queued"}} {queued}
pipeline_queue_depth{{status="processing"}} {processing}

# HELP pipeline_pending_review Number of candidates pending review
# TYPE pipeline_pending_review gauge
pipeline_pending_review {pending_review}

# HELP pipeline_jobs_completed_total Jobs completed today
# TYPE pipeline_jobs_completed_total counter
pipeline_jobs_completed_total {jobs_completed_today}

# HELP pipeline_changes_committed_total Changes committed today
# TYPE pipeline_changes_committed_total counter
pipeline_changes_committed_total {changes_committed_today}

# HELP pipeline_docs_processed_total Documents processed today
# TYPE pipeline_docs_processed_total counter
pipeline_docs_processed_total {docs_processed_today}

# HELP pipeline_runs_total Runs today
# TYPE pipeline_runs_total counter
pipeline_runs_total{{status="total"}} {runs_today}
pipeline_runs_total{{status="failed"}} {failed_runs_today}

# HELP pipeline_last_run_seconds_ago Seconds since last successful run
# TYPE pipeline_last_run_seconds_ago gauge
pipeline_last_run_seconds_ago {last_run_seconds_ago if last_run_seconds_ago is not None else -1}
"""

        return metrics_text, 200, {'Content-Type': 'text/plain; charset=utf-8'}

    except Exception as e:
        return f"# Error: {e}\n", 500, {'Content-Type': 'text/plain; charset=utf-8'}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _serialize_candidate(c: CandidateChangeRecord) -> dict:
    """Serialize a CandidateChangeRecord to dict."""
    return {
        "id": str(c.id),
        "hts_code": c.hts_code,
        "chapter_99_code": c.chapter_99_code,
        "duty_rate": float(c.duty_rate) if c.duty_rate else None,
        "effective_date": c.effective_date.isoformat() if c.effective_date else None,
        "program": c.program,
        "status": c.status,
        "review_reason": c.review_reason,
        "evidence_quote": c.evidence_quote[:200] + "..." if c.evidence_quote and len(c.evidence_quote) > 200 else c.evidence_quote,
        "extraction_method": c.extraction_method,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "reviewed_by": c.reviewed_by,
        "reviewed_at": c.reviewed_at.isoformat() if c.reviewed_at else None,
        "review_notes": c.review_notes,
    }


def _serialize_run(r: RegulatoryRun) -> dict:
    """Serialize a RegulatoryRun to dict."""
    return {
        "id": str(r.id),
        "trigger": r.trigger,
        "status": r.status,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        "sources_polled": r.sources_polled,
        "summary_counts": r.summary_counts,
    }
