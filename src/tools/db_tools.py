import uuid
import logging

from src.db import Draft, DraftStatus, SessionLocal, write_log

logger = logging.getLogger(__name__)

def save_draft(
    sender: str,
    subject: str,
    original_body: str,
    draft_body: str,
    thread_id: str = "",
    message_id_header: str = "",
    tone: str = "formal",
) -> str:
    """
    Save an AI-generated reply draft to the SQLite database.

    Call this after you have generated a draft reply for an email.
    The draft is saved with status 'pending' and must be approved by
    the human before it can be sent.

    Parameters
    ----------
    sender           : "From" address of the original email.
    subject          : Subject of the original email.
    original_body    : Full body text of the email being replied to.
    draft_body       : The AI-generated reply text.
    thread_id        : Gmail thread ID (for threading when sending).
    message_id_header: RFC 2822 Message-ID of the original email.
    tone             : Tone used: 'formal', 'friendly', or 'concise'.

    Returns
    -------
    str
        Confirmation string with the new draft's UUID.
    """

    db = SessionLocal()

    try:
        draft_id = str(uuid.uuid4())
        logger.info(f"Creating draft: {draft_id} for subject: {subject[:50]}")

        draft = Draft(
            id = draft_id,
            thread_id = thread_id or None,
            message_id = message_id_header or None,
            sender = sender,
            subject = subject,
            original_body = original_body,
            draft_body = draft_body,
            status = DraftStatus.pending,
            tone = tone
        )

        db.add(draft)
        write_log(db, "draft_created", f"Draft {draft_id} created for: {subject}")
        db.commit()

        logger.info(f"Draft saved successfully: {draft_id}")

        return f"Draft saved successfully. DRAFT_ID: {draft_id}"

    except Exception as error:
        logger.error(f"Error saving draft: {error}", exc_info = True)
        db.rollback()

        return f"Error saving draft: {error}"

    finally:
        db.close()

def list_pending_drafts() -> str:
    """
    Return all draft replies with status 'pending', awaiting human review.

    Use this to check how many drafts are queued for user approval after
    a draft-generation run.

    Returns
    -------
    str
        Formatted list of pending drafts with their IDs and subjects,
        or a message if none are found.
    """

    db = SessionLocal()

    try:
        logger.info("Listing pending drafts")
        drafts = (
            db.query(Draft).filter(Draft.status == DraftStatus.pending).all()
        )

        if not drafts:
            logger.info("No pending drafts found")

            return "No pending drafts found."

        lines = ["Pending drafts waiting for human review:"]
        for d in drafts:
            lines.append(
                f"  DRAFT_ID : {d.id}\n"
                f"  Subject  : {d.subject}\n"
                f"  To       : {d.sender}\n"
                f"  Tone     : {d.tone}\n"
                f"  Preview  : {d.draft_body[:200]}…\n"
                f"  {'─' * 50}"
            )

        logger.info(f"Found {len(drafts)} pending drafts")
        return "\n".join(lines)

    except Exception as error:
        logger.error(f"Error listing pending drafts: {error}", exc_info = True)

        return f"Error retrieving pending drafts: {error}"

    finally:
        db.close()

def get_draft_by_id(draft_id: str) -> str:
    """
    Retrieve a single draft by its UUID.

    Parameters
    ----------
    draft_id : str
        The UUID of the draft (returned by save_draft).

    Returns
    -------
    str
        Full draft details or an error message if not found.
    """

    db = SessionLocal()

    try:
        logger.info(f"Retrieving draft: {draft_id}")
        draft = db.query(Draft).filter(Draft.id == draft_id).first()

        if not draft:
            logger.warning(f"Draft not found: {draft_id}")

            return f"No draft found with ID: {draft_id}"

        logger.info(f"Draft retrieved: {draft_id}")
        return (
            f"DRAFT_ID : {draft.id}\n"
            f"Status   : {draft.status}\n"
            f"Subject  : {draft.subject}\n"
            f"To       : {draft.sender}\n"
            f"Tone     : {draft.tone}\n"
            f"Body     :\n{draft.draft_body}"
        )

    except Exception as error:
        logger.error(f"Error retrieving draft {draft_id}: {error}", exc_info = True
                     )
        return f"Error retrieving draft: {error}"

    finally:
        db.close()