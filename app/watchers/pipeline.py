"""
Tariff Update Pipeline: End-to-end watcher → extract → verify → write.

This is the orchestration layer that:
1. Polls watchers for new notices (CBP CSMS, Federal Register, USITC)
2. Fetches document content
3. Passes through Write Gate (extract → verify → insert)

Manual trigger: User says "check for tariff updates" and this runs.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import List, Dict, Any, Optional

from app.watchers.base import BaseWatcher, DiscoveredDocument

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Result of running the tariff update pipeline."""

    # Timing
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    duration_seconds: float = 0.0

    # Input parameters
    lookback_hours: int = 24
    since_date: Optional[date] = None

    # Discovery stats
    notices_found: int = 0
    notices_by_source: Dict[str, int] = field(default_factory=dict)

    # Processing stats
    processed: int = 0
    inserted: int = 0
    skipped: int = 0
    failed: int = 0

    # Details
    successes: List[Dict[str, Any]] = field(default_factory=list)
    failures: List[Dict[str, Any]] = field(default_factory=list)
    skipped_details: List[Dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "lookback_hours": self.lookback_hours,
            "since_date": self.since_date.isoformat() if self.since_date else None,
            "notices_found": self.notices_found,
            "notices_by_source": self.notices_by_source,
            "processed": self.processed,
            "inserted": self.inserted,
            "skipped": self.skipped,
            "failed": self.failed,
            "successes": self.successes,
            "failures": self.failures,
            "skipped_details": self.skipped_details,
        }

    def summary(self) -> str:
        """Human-readable summary."""
        return (
            f"Pipeline completed in {self.duration_seconds:.1f}s: "
            f"found {self.notices_found} notices, "
            f"inserted {self.inserted} rows, "
            f"skipped {self.skipped}, "
            f"failed {self.failed}"
        )


class TariffUpdatePipeline:
    """
    End-to-end pipeline: Detect → Fetch → Extract → Verify → Write.

    Usage:
        pipeline = TariffUpdatePipeline()
        result = pipeline.run(lookback_hours=24)
        print(result.summary())

    The pipeline is manually triggered (not scheduled). User says
    "check for tariff updates" and we run the full pipeline.
    """

    def __init__(self):
        # Lazy-load watchers to avoid import issues
        self._watchers = None
        self._write_gate = None

    @property
    def watchers(self) -> Dict[str, BaseWatcher]:
        """Lazy-load watchers."""
        if self._watchers is None:
            from app.watchers.cbp_csms import CBPCSMSWatcher
            from app.watchers.federal_register import FederalRegisterWatcher
            from app.watchers.usitc import USITCWatcher

            self._watchers = {
                "cbp_csms": CBPCSMSWatcher(),
                "federal_register": FederalRegisterWatcher(),
                "usitc": USITCWatcher(),
            }
        return self._watchers

    @property
    def write_gate(self):
        """Lazy-load Write Gate."""
        if self._write_gate is None:
            from app.services.write_gate import get_write_gate
            self._write_gate = get_write_gate()
        return self._write_gate

    def run(self, lookback_hours: int = 24) -> PipelineResult:
        """
        Run the full pipeline.

        Args:
            lookback_hours: Check notices from last N hours (default 24)

        Returns:
            PipelineResult with detailed stats
        """
        result = PipelineResult(lookback_hours=lookback_hours)
        result.since_date = date.today() - timedelta(hours=lookback_hours)

        logger.info(f"Pipeline starting: lookback={lookback_hours}h, since={result.since_date}")

        # Step 1: Discover documents from all watchers
        all_discovered = []
        for watcher_name, watcher in self.watchers.items():
            try:
                discovered = watcher.poll(result.since_date)
                result.notices_by_source[watcher_name] = len(discovered)
                all_discovered.extend(discovered)
                logger.info(f"{watcher_name}: discovered {len(discovered)} documents")
            except Exception as e:
                logger.error(f"{watcher_name} poll failed: {e}")
                result.failures.append({
                    "stage": "discovery",
                    "source": watcher_name,
                    "error": str(e),
                })

        result.notices_found = len(all_discovered)

        if not all_discovered:
            logger.info("No new notices found")
            result.completed_at = datetime.utcnow()
            result.duration_seconds = (result.completed_at - result.started_at).total_seconds()
            return result

        # Step 2: Process each document through Write Gate
        for doc in all_discovered:
            try:
                # Fetch content
                content = self._fetch_document_content(doc)

                if not content:
                    result.skipped += 1
                    result.skipped_details.append({
                        "source": doc.external_id,
                        "reason": "Could not fetch content",
                    })
                    continue

                # Process through Write Gate
                write_result = self.write_gate.process_document(
                    document_text=content,
                    source=doc.external_id,
                )

                result.processed += 1

                if write_result.success:
                    result.inserted += write_result.rows_inserted
                    result.successes.append({
                        "source": doc.external_id,
                        "rows": write_result.rows_inserted,
                        "table": write_result.table,
                        "program": write_result.extraction.program if write_result.extraction else None,
                    })
                else:
                    if write_result.error:
                        result.failed += 1
                        result.failures.append({
                            "stage": "write_gate",
                            "source": doc.external_id,
                            "error": write_result.error,
                        })
                    else:
                        result.skipped += 1
                        result.skipped_details.append({
                            "source": doc.external_id,
                            "reason": write_result.skipped_reason,
                        })

            except Exception as e:
                logger.error(f"Error processing {doc.external_id}: {e}")
                result.failed += 1
                result.failures.append({
                    "stage": "processing",
                    "source": doc.external_id,
                    "error": str(e),
                })

        result.completed_at = datetime.utcnow()
        result.duration_seconds = (result.completed_at - result.started_at).total_seconds()

        logger.info(result.summary())

        return result

    def _fetch_document_content(self, doc: DiscoveredDocument) -> Optional[str]:
        """
        Fetch the content of a discovered document.

        Tries different fetch methods based on source type.
        """
        import requests

        url = doc.preferred_url()
        if not url:
            return None

        try:
            # Use watcher-specific fetch if available
            watcher = self.watchers.get(doc.source)
            if watcher and hasattr(watcher, 'fetch_bulletin_content'):
                return watcher.fetch_bulletin_content(url)

            # Generic fetch
            response = requests.get(url, timeout=30)
            response.raise_for_status()

            # For HTML, extract text
            if 'html' in response.headers.get('content-type', '').lower():
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(response.text, 'html.parser')
                # Remove script and style elements
                for script in soup(["script", "style"]):
                    script.decompose()
                return soup.get_text(separator='\n', strip=True)

            # For plain text
            return response.text

        except Exception as e:
            logger.error(f"Failed to fetch {url}: {e}")
            return None

    def run_for_source(self, source: str, lookback_hours: int = 24) -> PipelineResult:
        """
        Run pipeline for a specific source only.

        Args:
            source: Source name ('cbp_csms', 'federal_register', 'usitc')
            lookback_hours: Check notices from last N hours

        Returns:
            PipelineResult for that source
        """
        result = PipelineResult(lookback_hours=lookback_hours)
        result.since_date = date.today() - timedelta(hours=lookback_hours)

        if source not in self.watchers:
            result.failures.append({
                "stage": "discovery",
                "source": source,
                "error": f"Unknown source: {source}. Valid: {list(self.watchers.keys())}",
            })
            result.completed_at = datetime.utcnow()
            result.duration_seconds = (result.completed_at - result.started_at).total_seconds()
            return result

        watcher = self.watchers[source]

        try:
            discovered = watcher.poll(result.since_date)
            result.notices_found = len(discovered)
            result.notices_by_source[source] = len(discovered)

            for doc in discovered:
                content = self._fetch_document_content(doc)
                if not content:
                    result.skipped += 1
                    continue

                write_result = self.write_gate.process_document(content, doc.external_id)
                result.processed += 1

                if write_result.success:
                    result.inserted += write_result.rows_inserted
                    result.successes.append({
                        "source": doc.external_id,
                        "rows": write_result.rows_inserted,
                    })
                else:
                    result.skipped += 1
                    result.skipped_details.append({
                        "source": doc.external_id,
                        "reason": write_result.skipped_reason or write_result.error,
                    })

        except Exception as e:
            logger.error(f"{source} pipeline error: {e}")
            result.failures.append({
                "stage": "pipeline",
                "source": source,
                "error": str(e),
            })

        result.completed_at = datetime.utcnow()
        result.duration_seconds = (result.completed_at - result.started_at).total_seconds()

        return result


# Singleton instance
_pipeline = None


def get_pipeline() -> TariffUpdatePipeline:
    """Get the singleton TariffUpdatePipeline instance."""
    global _pipeline
    if _pipeline is None:
        _pipeline = TariffUpdatePipeline()
    return _pipeline


def check_for_updates(lookback_hours: int = 24) -> Dict[str, Any]:
    """
    Entry point for "check for tariff updates" command.

    This is what runs when user says "check for tariff updates".

    Args:
        lookback_hours: How far back to check (default 24 hours)

    Returns:
        Dict with results summary
    """
    pipeline = get_pipeline()
    result = pipeline.run(lookback_hours=lookback_hours)

    return {
        "summary": result.summary(),
        **result.as_dict(),
    }
