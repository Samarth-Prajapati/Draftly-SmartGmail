import logging
from src.services import GmailService

logger = logging.getLogger(__name__)

def fetch_unread_emails(max_results: int = 10) -> str:
    """
    Fetch unread emails from the user's Gmail INBOX.

    Returns a formatted string listing each email's ID, thread ID,
    sender, subject, date, and a preview of the body.  Use this to
    discover which emails need a reply draft.

    Parameters
    ----------
    max_results : int
        Maximum number of emails to retrieve (default: 10).
    """

    try:
        logger.info(f"Fetching unread emails (max_results={max_results})")
        emails = GmailService().fetch_unread_emails(max_results)

        if not emails:
            logger.info("No unread emails found")

            return "Inbox is empty – no unread emails found."

        lines: list[str] = []
        for e in emails:
            preview = (e.body[:400] + "…") if len(e.body) > 400 else e.body
            lines.append(
                f"EMAIL_ID: {e.id}\n"
                f"THREAD_ID: {e.thread_id}\n"
                f"MESSAGE_ID_HEADER: {e.message_id}\n"
                f"FROM: {e.sender}\n"
                f"SUBJECT: {e.subject}\n"
                f"DATE: {e.date}\n"
                f"BODY_PREVIEW:\n{preview}\n"
                f"{'─' * 60}"
            )

        logger.info(f"Successfully formatted {len(emails)} unread emails")

        return "\n".join(lines)

    except Exception as error:
        logger.error(f"Error fetching unread emails: {error}", exc_info = True)

        return f"Error fetching unread emails: {error}"

def fetch_sent_emails(max_results: int = 5) -> str:
    """
    Fetch recent sent emails to learn the user's writing style.

    Analyze the returned emails to infer the user's preferred tone,
    phrasing, greeting style, sign-off, and level of formality.  Use
    this insight when generating reply drafts so they sound authentically
    like the user.

    Parameters
    ----------
    max_results : int
        Number of sent emails to fetch (default: 5).
    """

    try:
        logger.info(f"Fetching sent emails (max_results={max_results})")
        emails = GmailService().fetch_sent_emails(max_results)

        if not emails:
            logger.info("No sent emails found")

            return "No sent emails found – cannot infer writing style."

        lines: list[str] = []
        for e in emails:
            preview = (e.body[:400] + "…") if len(e.body) > 400 else e.body
            lines.append(
                f"SENT_SUBJECT: {e.subject}\n"
                f"SENT_BODY:\n{preview}\n"
                f"{'─' * 60}"
            )
        logger.info(f"Successfully formatted {len(emails)} sent emails")

        return "\n".join(lines)

    except Exception as error:
        logger.error(f"Error fetching sent emails: {error}", exc_info = True)

        return f"Error fetching sent emails: {error}"

def send_approved_email(
    to: str,
    subject: str,
    body: str,
    thread_id: str = "",
    in_reply_to: str = "",
) -> str:
    """
    Send a HUMAN-APPROVED email reply via Gmail.

    IMPORTANT: Only call this tool AFTER the human has explicitly
    approved the draft.  Never call this autonomously.

    Parameters
    ----------
    to          : Recipient email address.
    subject     : Subject line (prefix 'Re: ' if replying).
    body        : Full plain-text body of the reply.
    thread_id   : Gmail thread ID to keep the reply in the same thread.
    in_reply_to : RFC 2822 Message-ID header of the original email.
    """

    try:
        logger.info(f"Sending approved email to: {to}, subject: {subject[:50]}")
        result = GmailService().send_email(
            to = to,
            subject = subject,
            body = body,
            thread_id = thread_id or None,
            in_reply_to = in_reply_to or None,
        )

        logger.info(f"Email sent successfully: {result.get('id')}")

        return (
            f"Email sent successfully.\n"
            f"Gmail Message ID : {result.get('id', 'unknown')}\n"
            f"Thread ID        : {result.get('threadId', 'unknown')}"
        )

    except Exception as error:
        logger.error(f"Error sending approved email to {to}: {error}", exc_info = True)
        return f"Error sending email: {error}"