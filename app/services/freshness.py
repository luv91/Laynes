"""
Data Freshness Service

Provides freshness information for tariff data sources.
Used by UI to show when data was last updated and watcher status.
"""

from datetime import datetime, date, timedelta
from typing import Dict, Optional
import logging

from sqlalchemy import func, text
from app.web.db import db

logger = logging.getLogger(__name__)


class FreshnessService:
    """
    Tracks and reports data freshness for tariff programs.

    Provides:
    - Last update timestamps per program
    - Watcher status (running, current, stale)
    - Data source information
    """

    # Staleness thresholds (days)
    STALE_THRESHOLDS = {
        "section_301": 7,      # Weekly updates expected
        "section_232": 14,     # Bi-weekly
        "ieepa_fentanyl": 30,  # Monthly
        "ieepa_reciprocal": 30,
        "mfn_base_rates": 365, # Annual
    }

    # Data sources by program
    DATA_SOURCES = {
        "section_301": {
            "name": "Section 301 (China)",
            "source": "Federal Register",
            "watcher": "federal_register",
            "table": "section_301_rates",
        },
        "section_232": {
            "name": "Section 232 (Steel/Aluminum/Copper)",
            "source": "CBP CSMS",
            "watcher": "cbp_csms",
            "table": "section_232_rates",
        },
        "ieepa_fentanyl": {
            "name": "IEEPA Fentanyl",
            "source": "Federal Register",
            "watcher": "federal_register",
            "table": "ieepa_rates",
        },
        "ieepa_reciprocal": {
            "name": "IEEPA Reciprocal",
            "source": "Federal Register",
            "watcher": "federal_register",
            "table": "ieepa_rates",
        },
        "mfn_base_rates": {
            "name": "MFN Base Rates",
            "source": "USITC HTS",
            "watcher": "usitc",
            "table": "hts_base_rates",
        },
    }

    def get_all_freshness(self) -> Dict[str, dict]:
        """
        Get freshness info for all data sources.

        Returns:
            Dict mapping program_id to freshness info
        """
        result = {}
        for program_id in self.DATA_SOURCES:
            result[program_id] = self.get_program_freshness(program_id)
        return result

    def get_program_freshness(self, program_id: str) -> dict:
        """
        Get freshness info for a specific program.

        Args:
            program_id: Program identifier (section_301, section_232, etc.)

        Returns:
            Dict with freshness details
        """
        config = self.DATA_SOURCES.get(program_id)
        if not config:
            return {"error": f"Unknown program: {program_id}"}

        # Get last update time
        last_updated = self._get_last_update(config["table"])

        # Calculate staleness
        stale_days = self.STALE_THRESHOLDS.get(program_id, 30)
        status = self._calculate_status(last_updated, stale_days)

        # Get watcher status
        watcher_status = self._get_watcher_status(config["watcher"])

        # Get record count
        record_count = self._get_record_count(config["table"])

        return {
            "program_id": program_id,
            "name": config["name"],
            "source": config["source"],
            "last_updated": last_updated.isoformat() if last_updated else None,
            "last_updated_display": self._format_relative_time(last_updated) if last_updated else "Never",
            "status": status,
            "status_class": self._status_to_class(status),
            "watcher": config["watcher"],
            "watcher_status": watcher_status,
            "record_count": record_count,
            "stale_threshold_days": stale_days,
        }

    def _get_last_update(self, table_name: str) -> Optional[datetime]:
        """Get the most recent update timestamp for a table."""
        try:
            # Try to get max of created_at or updated_at
            result = db.session.execute(text(f"""
                SELECT MAX(COALESCE(updated_at, created_at))
                FROM {table_name}
            """)).scalar()

            if result:
                return result if isinstance(result, datetime) else datetime.combine(result, datetime.min.time())

            # Fallback: check if table exists and has data
            count = db.session.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar()
            if count and count > 0:
                # Table has data but no timestamps - assume it was populated at startup
                return datetime.utcnow() - timedelta(days=1)

            return None

        except Exception as e:
            logger.debug(f"Could not get last update for {table_name}: {e}")
            return None

    def _get_record_count(self, table_name: str) -> int:
        """Get the number of records in a table."""
        try:
            result = db.session.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar()
            return result or 0
        except Exception as e:
            logger.debug(f"Could not get count for {table_name}: {e}")
            return 0

    def _get_watcher_status(self, watcher_name: str) -> dict:
        """Get status of a watcher."""
        try:
            # Check ingest_jobs for this source
            from app.models.ingest_job import IngestJob

            # Last poll time (most recent discovered_at)
            last_discovery = db.session.query(
                func.max(IngestJob.discovered_at)
            ).filter(
                IngestJob.source == watcher_name
            ).scalar()

            # Pending jobs
            pending_count = db.session.query(
                func.count(IngestJob.id)
            ).filter(
                IngestJob.source == watcher_name,
                IngestJob.status == "queued"
            ).scalar() or 0

            # Failed jobs (last 7 days)
            week_ago = datetime.utcnow() - timedelta(days=7)
            failed_count = db.session.query(
                func.count(IngestJob.id)
            ).filter(
                IngestJob.source == watcher_name,
                IngestJob.status == "failed",
                IngestJob.created_at >= week_ago
            ).scalar() or 0

            return {
                "last_poll": last_discovery.isoformat() if last_discovery else None,
                "pending_jobs": pending_count,
                "failed_jobs_7d": failed_count,
                "status": "running" if pending_count == 0 and failed_count == 0 else "issues"
            }

        except Exception as e:
            logger.debug(f"Could not get watcher status for {watcher_name}: {e}")
            return {
                "last_poll": None,
                "pending_jobs": 0,
                "failed_jobs_7d": 0,
                "status": "unknown"
            }

    def _calculate_status(self, last_updated: Optional[datetime], stale_days: int) -> str:
        """
        Calculate freshness status.

        Returns: 'current', 'stale', or 'outdated'
        """
        if not last_updated:
            return "unknown"

        age = datetime.utcnow() - last_updated
        days_old = age.days

        if days_old <= stale_days:
            return "current"
        elif days_old <= stale_days * 2:
            return "stale"
        else:
            return "outdated"

    def _status_to_class(self, status: str) -> str:
        """Convert status to CSS class name."""
        return {
            "current": "freshness-current",
            "stale": "freshness-stale",
            "outdated": "freshness-outdated",
            "unknown": "freshness-unknown",
        }.get(status, "freshness-unknown")

    def _format_relative_time(self, dt: Optional[datetime]) -> str:
        """Format datetime as relative time string."""
        if not dt:
            return "Never"

        now = datetime.utcnow()
        diff = now - dt

        if diff.days == 0:
            hours = diff.seconds // 3600
            if hours == 0:
                minutes = diff.seconds // 60
                return f"{minutes} minutes ago" if minutes != 1 else "1 minute ago"
            return f"{hours} hours ago" if hours != 1 else "1 hour ago"
        elif diff.days == 1:
            return "Yesterday"
        elif diff.days < 7:
            return f"{diff.days} days ago"
        elif diff.days < 30:
            weeks = diff.days // 7
            return f"{weeks} weeks ago" if weeks != 1 else "1 week ago"
        elif diff.days < 365:
            months = diff.days // 30
            return f"{months} months ago" if months != 1 else "1 month ago"
        else:
            years = diff.days // 365
            return f"{years} years ago" if years != 1 else "1 year ago"


# Singleton instance
_freshness_service = None


def get_freshness_service() -> FreshnessService:
    """Get the singleton FreshnessService instance."""
    global _freshness_service
    if _freshness_service is None:
        _freshness_service = FreshnessService()
    return _freshness_service
