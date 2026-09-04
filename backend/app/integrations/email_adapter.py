import re
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class EmailMessage:
    sender: str
    subject: str
    body: str
    received_at: datetime
    is_trusted_sender: bool


class EmailAdapter:
    """Parses incoming academic emails and newsletters into sanitized message structures."""

    TRUSTED_DOMAINS = {"edu", "ac.uk", "university.edu", "canvas.edu", "gradescope.com"}

    @classmethod
    def parse_raw_email(
        cls,
        raw_text: str,
        sender: str = "professor@university.edu",
        subject: str = "Course Announcement",
        received_at: datetime | None = None,
    ) -> EmailMessage:
        # Check domain trustworthiness
        domain = sender.split("@")[-1].lower() if "@" in sender else ""
        is_trusted = any(domain.endswith(td) for td in cls.TRUSTED_DOMAINS)

        # Extract headers if formatted like raw RFC email
        subject_match = re.search(r"^Subject:\s*(.+)$", raw_text, re.MULTILINE | re.IGNORECASE)
        from_match = re.search(r"^From:\s*(.+)$", raw_text, re.MULTILINE | re.IGNORECASE)

        clean_subject = subject_match.group(1).strip() if subject_match else subject
        clean_sender = from_match.group(1).strip() if from_match else sender

        # Strip header lines if present
        body = re.sub(r"^(From|To|Subject|Date):\s*.*$\n?", "", raw_text, flags=re.MULTILINE | re.IGNORECASE).strip()
        if not body:
            body = raw_text.strip()

        return EmailMessage(
            sender=clean_sender,
            subject=clean_subject,
            body=body,
            received_at=received_at or datetime.now(timezone.utc),
            is_trusted_sender=is_trusted,
        )
