"""
Regulatory Update Pipeline - Watchers

Watchers monitor official government sources for new tariff-related documents:
- Federal Register (Section 301, IEEPA notices)
- CBP CSMS (Section 232 bulletins)
- USITC (HTS updates)

Each watcher polls its source on a schedule and enqueues new documents
for processing by the document pipeline.
"""

from app.watchers.base import BaseWatcher, DiscoveredDocument
from app.watchers.federal_register import FederalRegisterWatcher
from app.watchers.cbp_csms import CBPCSMSWatcher
from app.watchers.usitc import USITCWatcher

__all__ = [
    'BaseWatcher',
    'DiscoveredDocument',
    'FederalRegisterWatcher',
    'CBPCSMSWatcher',
    'USITCWatcher',
]
