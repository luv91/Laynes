"""
Email-based CSMS Watcher

Monitors a Gmail inbox for CBP CSMS bulletins via IMAP.
This captures real-time CSMS notices that the archive-based watcher misses.

Configuration:
    GMAIL_CSMS_EMAIL: Gmail address subscribed to CBP notifications
    GMAIL_CSMS_APP_PASSWORD: Gmail App Password (NOT regular password)

The email watcher looks for emails from CBP@info.cbp.dhs.gov with
subject lines containing "CSMS #" and extracts the bulletin information.
"""

import logging
import os
import re
from datetime import date, datetime, timedelta
from typing import List, Optional
from email.utils import parsedate_to_datetime

from app.watchers.base import BaseWatcher, DiscoveredDocument

logger = logging.getLogger(__name__)


class EmailCSMSWatcher(BaseWatcher):
    """
    Watches a Gmail inbox for CBP CSMS bulletins.

    CBP sends CSMS notifications via email from CBP@info.cbp.dhs.gov.
    This watcher polls the inbox and discovers new bulletins.

    Requires:
        - Gmail account with 2FA enabled
        - App Password created for "Tariff Watcher"
        - Environment variables: GMAIL_CSMS_EMAIL, GMAIL_CSMS_APP_PASSWORD
    """

    SOURCE_NAME = "email_csms"
    POLL_INTERVAL_HOURS = 1  # Check hourly for real-time bulletins

    # IMAP Configuration
    IMAP_SERVER = "imap.gmail.com"
    IMAP_PORT = 993

    # Email filter criteria
    SENDER_FILTERS = [
        "CBP@info.cbp.dhs.gov",
        "noreply@public.govdelivery.com",
        "CBP-CSMSNotifications@cbp.dhs.gov",
    ]

    # Pattern to extract CSMS number from subject
    CSMS_PATTERN = re.compile(r'CSMS\s*#\s*(\d+)', re.IGNORECASE)

    def __init__(self):
        super().__init__()
        self.email = os.environ.get("GMAIL_CSMS_EMAIL")
        self.app_password = os.environ.get("GMAIL_CSMS_APP_PASSWORD")

        if not self.email or not self.app_password:
            logger.warning(
                "Email CSMS watcher not configured. "
                "Set GMAIL_CSMS_EMAIL and GMAIL_CSMS_APP_PASSWORD environment variables."
            )

    def poll(self, since_date: Optional[date] = None) -> List[DiscoveredDocument]:
        """
        Poll Gmail inbox for new CSMS bulletins.

        Args:
            since_date: Only return emails received after this date.
                       If None, defaults to 30 days ago.

        Returns:
            List of DiscoveredDocument objects for processing.
        """
        if not self.email or not self.app_password:
            logger.error("Email CSMS watcher not configured - skipping")
            return []

        if since_date is None:
            since_date = date.today() - timedelta(days=30)

        discovered = []

        try:
            from imap_tools import MailBox, AND

            logger.info(f"Connecting to Gmail IMAP for {self.email}")

            with MailBox(self.IMAP_SERVER).login(self.email, self.app_password) as mailbox:
                # Build search criteria
                # Search for emails since the date with CSMS in subject
                search_criteria = AND(
                    date_gte=since_date,
                    subject="CSMS"
                )

                logger.info(f"Searching for CSMS emails since {since_date}")

                for msg in mailbox.fetch(search_criteria, limit=100):
                    # Check if sender matches our filters
                    sender = msg.from_ or ""
                    if not any(f.lower() in sender.lower() for f in self.SENDER_FILTERS):
                        # Also check the actual From header
                        if not any(f.lower() in (msg.headers.get('from', [''])[0] or '').lower()
                                   for f in self.SENDER_FILTERS):
                            continue

                    # Extract CSMS number from subject
                    subject = msg.subject or ""
                    csms_match = self.CSMS_PATTERN.search(subject)

                    if not csms_match:
                        logger.debug(f"No CSMS number found in subject: {subject}")
                        continue

                    csms_number = csms_match.group(1)

                    # Extract title (everything after "CSMS # XXXXX - ")
                    title_match = re.search(r'CSMS\s*#\s*\d+\s*[-–]\s*(.+)', subject)
                    title = title_match.group(1).strip() if title_match else subject

                    # Get email date
                    email_date = msg.date
                    if email_date:
                        pub_date = email_date.date()
                    else:
                        pub_date = date.today()

                    # Extract any URLs from email body (GovDelivery links)
                    body = msg.text or msg.html or ""
                    html_url = self._extract_govdelivery_url(body)

                    # Create discovered document
                    doc = DiscoveredDocument(
                        source=self.SOURCE_NAME,
                        external_id=csms_number,
                        title=title,
                        html_url=html_url,
                        publication_date=pub_date,
                        discovered_by=f"{self.SOURCE_NAME}_watcher",
                        metadata={
                            "email_uid": str(msg.uid),
                            "sender": sender,
                            "received_at": email_date.isoformat() if email_date else None,
                            "csms_number": csms_number,
                            "subject": subject,
                            "has_attachments": len(msg.attachments) > 0,
                        }
                    )

                    discovered.append(doc)
                    logger.info(f"Discovered CSMS #{csms_number}: {title[:50]}...")

        except ImportError:
            logger.error("imap-tools not installed. Run: pipenv install imap-tools")
            return []
        except Exception as e:
            logger.exception(f"Email CSMS watcher failed: {e}")
            raise

        # Deduplicate by CSMS number
        discovered = self.deduplicate(discovered)

        logger.info(f"Email CSMS watcher found {len(discovered)} bulletins")
        return discovered

    def _extract_govdelivery_url(self, body: str) -> Optional[str]:
        """
        Extract GovDelivery bulletin URL from email body.

        GovDelivery emails typically contain links like:
        https://content.govdelivery.com/accounts/USDHSCBP/bulletins/XXXXX
        """
        if not body:
            return None

        # Look for GovDelivery bulletin URLs
        govdelivery_pattern = re.compile(
            r'https?://content\.govdelivery\.com/accounts/USDHSCBP/bulletins/[a-zA-Z0-9]+',
            re.IGNORECASE
        )

        match = govdelivery_pattern.search(body)
        if match:
            return match.group(0)

        # Fallback: look for any CBP gov link
        cbp_pattern = re.compile(
            r'https?://[a-zA-Z0-9.-]*cbp\.gov[^\s<>"\']*',
            re.IGNORECASE
        )

        match = cbp_pattern.search(body)
        if match:
            return match.group(0)

        return None

    def _is_tariff_related(self, subject: str, body: str) -> bool:
        """
        Check if the email is related to tariffs/duties.

        Useful for filtering if you want to be more selective.
        """
        keywords = [
            "section 232",
            "section 301",
            "tariff",
            "duty",
            "duties",
            "steel",
            "aluminum",
            "copper",
            "semiconductor",
            "9903",
            "htsus",
            "chapter 99",
        ]

        text = f"{subject} {body}".lower()
        return any(kw in text for kw in keywords)
