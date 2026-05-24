from __future__ import annotations

import uuid
import logging
from typing import Any
from pydantic import BaseModel
from sqlalchemy.orm import Session
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Depends, FastAPI, HTTPException, Query

from src.agent import DraftlyAgent
from src.services import GmailService
from src.db import Draft, DraftStatus, Log, get_db, init_db, write_log

logger = logging.getLogger(__name__)

app = FastAPI(
    title = "Draftly – Gmail AI Reply Agent",
    description = (
        "AI-powered Gmail assistant that generates draft replies, "
        "stores them for human review, and sends only approved emails."
    )
)

app.add_middleware(
    CORSMiddleware,
    allow_origins = ["*"],
    allow_credentials = True,
    allow_methods = ["*"],
    allow_headers = ["*"],
)

@app.on_event("startup")
def on_startup() -> None:
    """Initialize the SQLite database on first launch."""

    try:
        logger.info("Application startup: initializing database")
        init_db()
        logger.info("Database initialization complete")
        
    except Exception as error:
        logger.error(f"Database initialization failed: {error}", exc_info = True)
        
        raise

class EditDraftRequest(BaseModel):
    """Body payload for the PATCH /drafts/{id}/edit endpoint."""

    draft_body: str

class ResumeRequest(BaseModel):
    """Body payload for POST /drafts/{id}/resume (HITL approval / rejection)."""

    thread_id: str
    approved: bool
    reason: str = ""

class SendRequest(BaseModel):
    """Body payload for POST /drafts/{id}/send."""

    thread_id: str | None = None

@app.get("/", tags = ["Health"])
def root() -> dict[str, str]:
    """Health-check endpoint."""

    try:
        logger.debug("Root health check")
        
        return {
            "status": "ok",
            "service": "Draftly API",
            "version": "1.0.0"
        }
    
    except Exception as error:
        logger.error(f"Root endpoint error: {error}", exc_info = True)

        raise

@app.get("/health", tags = ["Health"])
def health() -> dict[str, str]:
    """Liveness probe."""

    try:
        logger.debug("Health check")

        return {
            "status": "healthy"
        }

    except Exception as error:
        logger.error(f"Health endpoint error: {error}", exc_info = True)

        raise

@app.get("/auth/status", tags = ["Auth"])
def auth_status() -> dict[str, Any]:
    """
    Check whether Gmail is currently authenticated.

    Returns
    -------
    JSON
        ``{"connected": bool}``
    """

    try:
        logger.debug("Checking Gmail authentication status")
        connected = GmailService().is_authenticated()
        logger.info(f"Gmail authentication status: {connected}")

        return {
            "connected": connected
        }

    except Exception as error:
        logger.error(f"Auth status check failed: {error}", exc_info = True)

        raise HTTPException(status_code = 500, detail = f"Auth check failed: {error}")

@app.get("/auth/connect", tags = ["Auth"])
def auth_connect() -> dict[str, str]:
    """
    Step 1 of the OAuth2 flow – return the Google consent URL.

    The client should open this URL in a browser.  Google will redirect
    back to GOOGLE_REDIRECT_URI with a ``code`` parameter.

    Returns
    -------
    JSON
        ``{"auth_url": "https://accounts.google.com/…"}``
    """

    try:
        logger.info("Generating OAuth2 authorization URL")
        url = GmailService().get_authorization_url()
        logger.info(f"Authorization URL generated successfully")

        return {
            "auth_url": url
        }

    except Exception as error:
        logger.error(f"Failed to generate authorization URL: {error}", exc_info = True)

        raise HTTPException(status_code = 500, detail = f"Failed to generate auth URL: {error}")

@app.get("/auth/callback", tags = ["Auth"])
def auth_callback(
    code: str = Query(..., description = "OAuth2 authorisation code from Google"),
    state: str | None = Query(None, description = "OAuth2 state for PKCE verification"),
) -> dict[str, str]:
    """
    Step 2 of the OAuth2 flow – exchange the authorization code for tokens.

    Google redirects here automatically after the user grants consent.
    The token is persisted to GOOGLE_TOKEN_FILE for future requests.

    Parameters
    ----------
    code : str  (query param)
        The authorization code provided by Google.
        :param code:
        :param state:
    """

    try:
        logger.info(f"OAuth callback received (state: {state})")
        GmailService().exchange_code(code = code, state = state)
        logger.info("OAuth exchange successful, token saved")

        return {
            "status": "connected",
            "message": "Gmail authenticated successfully."
        }

    except Exception as error:
        logger.error(f"OAuth exchange failed: {error}", exc_info = True)

        raise HTTPException(status_code = 400, detail = f"OAuth exchange failed: {error}") from error

@app.post("/auth/disconnect", tags = ["Auth"])
def auth_disconnect() -> dict[str, str]:
    """
    Revoke Gmail access and delete the stored token.

    After calling this the user must go through /auth/connect again.
    """

    try:
        logger.info("Disconnecting Gmail (revoking token)")
        GmailService().revoke_token()
        logger.info("Gmail disconnected successfully")

        return {
            "status": "disconnected",
            "message": "Gmail access revoked."
        }

    except Exception as error:
        logger.error(f"Failed to disconnect Gmail: {error}", exc_info = True)

        raise HTTPException(status_code = 500, detail = f"Disconnect failed: {error}")

@app.get("/emails/inbox", tags = ["Emails"])
def get_inbox(max_results: int = Query(10, ge=1, le=50)) -> dict[str, Any]:
    """
    Fetch unread emails directly from Gmail (no agent, raw data).

    Parameters
    ----------
    max_results : int  (1-50, default 10)
        Maximum number of unread messages to return.
    """

    try:
        logger.info(f"Fetching inbox emails (max_results={max_results})")
        if not GmailService().is_authenticated():
            logger.warning("Inbox fetch attempted without Gmail authentication")

            raise HTTPException(status_code = 401, detail = "Gmail not authenticated. Call /auth/connect first.")

        emails = GmailService().fetch_unread_emails(max_results)
        logger.info(f"Successfully fetched {len(emails)} inbox emails")

        return {
            "count": len(emails),
            "emails": [e.as_dict() for e in emails]
        }

    except HTTPException:
        raise

    except Exception as error:
        logger.error(f"Failed to fetch inbox: {error}", exc_info = True)

        raise HTTPException(status_code = 500, detail = f"Failed to fetch inbox: {error}")

@app.post("/drafts/generate", tags = ["Drafts"])
def generate_drafts(
    max_results: int = Query(10, ge=1, le=30),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Trigger the deep agent to fetch inbox emails and generate draft replies.

    The agent fetches unread emails, studies the user's writing style
    from sent emails, generates context-aware replies, and persists them
    as 'pending' drafts.  No email is sent – drafts must be approved
    manually via PATCH /drafts/{id}/approve and POST /drafts/{id}/send.

    Returns
    -------
    JSON
        Agent output, thread_id, and whether the run was interrupted.
    """

    try:
        logger.info(f"Draft generation triggered (max_results={max_results})")

        if not GmailService().is_authenticated():
            logger.warning("Draft generation attempted without Gmail authentication")

            raise HTTPException(status_code = 401, detail = "Gmail not authenticated. Call /auth/connect first.")

        before_count = db.query(Draft).count()
        logger.info(f"Draft count before generation: {before_count}")

        result = DraftlyAgent().run_draft_generation(max_results = max_results)
        after_count = db.query(Draft).count()
        logger.info(f"Draft count after generation: {after_count}")

        if after_count == before_count:
            logger.warning("Agent completed without creating drafts, using fallback mechanism")
            fallback_created = _persist_fallback_drafts(db = db, max_results = max_results)
            result["fallback_created"] = fallback_created
            result["mode"] = "fallback" if fallback_created > 0 else "agent"

        else:
            result["created_count"] = after_count - before_count
            result["mode"] = "agent"

        logger.info(f"Draft generation complete: {result}")

        return result

    except HTTPException:
        raise

    except Exception as error:
        logger.error(f"Draft generation failed: {error}", exc_info = True)

        raise HTTPException(status_code = 500, detail = f"Draft generation failed: {error}")

@app.get("/drafts", tags = ["Drafts"])
def list_drafts(
    status: str | None = Query(None,
                               description = "Filter by status: pending, approved, edited, rejected, sent, failed"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    List all draft replies, optionally filtered by status.

    Parameters
    ----------
    status : str | None
        One of: pending, approved, edited, rejected, sent, failed.
        :param status:
        :param db:
    """

    try:
        logger.info(f"Listing drafts (status filter: {status})")
        query = db.query(Draft)

        if status:
            try:
                status_enum = DraftStatus(status)
                logger.debug(f"Filtering by status: {status_enum}")

            except ValueError:
                logger.warning(f"Invalid status filter: {status}")

                raise HTTPException(status_code = 422, detail = f"Invalid status '{status}'.")

            query = query.filter(Draft.status == status_enum)
        drafts = query.order_by(Draft.created_at.desc()).all()

        logger.info(f"Retrieved {len(drafts)} drafts")

        return {
            "count": len(drafts),
            "drafts": [
                {
                    "id": d.id,
                    "subject": d.subject,
                    "sender": d.sender,
                    "draft_body": d.draft_body,
                    "status": d.status,
                    "tone": d.tone,
                    "thread_id": d.thread_id,
                    "message_id": d.message_id,
                    "created_at": d.created_at,
                    "updated_at": d.updated_at
                }
                for d in drafts
            ],
        }

    except HTTPException:
        raise

    except Exception as error:
        logger.error(f"Failed to list drafts: {error}", exc_info = True)

        raise HTTPException(status_code = 500, detail = f"Failed to list drafts: {error}")

@app.get("/drafts/{draft_id}", tags = ["Drafts"])
def get_draft(draft_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """
    Retrieve a single draft by its UUID.

    Parameters
    ----------
    draft_id : str
        The UUID of the draft.
        :param draft_id:
        :param db:
    """

    try:
        logger.info(f"Retrieving draft: {draft_id}")
        draft = db.query(Draft).filter(Draft.id == draft_id).first()

        if not draft:
            logger.warning(f"Draft not found: {draft_id}")

            raise HTTPException(status_code=404, detail=f"Draft '{draft_id}' not found.")

        return {
            "id": draft.id,
            "subject": draft.subject,
            "sender": draft.sender,
            "original_body": draft.original_body,
            "draft_body": draft.draft_body,
            "status": draft.status,
            "tone": draft.tone,
            "thread_id": draft.thread_id,
            "message_id": draft.message_id,
            "created_at": draft.created_at,
            "updated_at": draft.updated_at,
        }

    except HTTPException:
        raise

    except Exception as error:
        logger.error(f"Failed to get draft {draft_id}: {error}", exc_info = True)

        raise HTTPException(status_code=500, detail=f"Failed to get draft: {error}")

@app.patch("/drafts/{draft_id}/approve", tags = ["Drafts"])
def approve_draft(draft_id: str, db: Session = Depends(get_db)) -> dict[str, str]:
    """
    Mark a draft as approved, ready for sending.

    Only drafts with status 'pending' or 'edited' can be approved.
    """

    try:
        logger.info(f"Approving draft: {draft_id}")
        draft = _get_draft_or_404(db, draft_id)

        if draft.status not in (DraftStatus.pending, DraftStatus.edited):
            logger.warning(f"Cannot approve draft {draft_id}: invalid status {draft.status}")

            raise HTTPException(status_code = 409, detail = "Only pending or edited drafts can be approved.")

        draft.status = DraftStatus.approved
        write_log(db, "draft_approved", f"Draft {draft_id} approved by user.")
        db.commit()

        logger.info(f"Draft approved successfully: {draft_id}")

        return {
            "message": "Draft approved.",
            "id": draft_id,
            "status": DraftStatus.approved
        }

    except HTTPException:
        raise

    except Exception as error:
        logger.error(f"Failed to approve draft {draft_id}: {error}", exc_info = True)

        raise HTTPException(status_code = 500, detail = f"Failed to approve draft: {error}")

@app.patch("/drafts/{draft_id}/edit", tags = ["Drafts"])
def edit_draft(
    draft_id: str,
    body: EditDraftRequest,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """
    Update the body text of a draft and set its status to 'edited'.

    Parameters
    ----------
    draft_id : str
        UUID of the draft to update.
    body.draft_body : str
        New draft body text.
        :param draft_id:
        :param body:
        :param db:
    """

    try:
        logger.info(f"Editing draft: {draft_id}")
        draft = _get_draft_or_404(db, draft_id)
        draft.draft_body = body.draft_body
        draft.status = DraftStatus.edited
        write_log(db, "draft_edited", f"Draft {draft_id} body updated by user.")
        db.commit()

        logger.info(f"Draft edited successfully: {draft_id}")

        return {
            "message": "Draft updated.",
            "id": draft_id,
            "status": DraftStatus.edited
        }

    except HTTPException:
        raise

    except Exception as error:
        logger.error(f"Failed to edit draft {draft_id}: {error}", exc_info = True)

        raise HTTPException(status_code = 500, detail = f"Failed to edit draft: {error}")

@app.patch("/drafts/{draft_id}/reject", tags = ["Drafts"])
def reject_draft(draft_id: str, db: Session = Depends(get_db)) -> dict[str, str]:
    """
    Reject a draft – it will not be sent.

    Any draft that has not yet been sent can be rejected.
    """

    try:
        logger.info(f"Rejecting draft: {draft_id}")
        draft = _get_draft_or_404(db, draft_id)

        if draft.status == DraftStatus.sent:
            logger.warning(f"Cannot reject draft {draft_id}: already sent")

            raise HTTPException(status_code = 409, detail = "Cannot reject a draft that has already been sent.")

        draft.status = DraftStatus.rejected
        write_log(db, "draft_rejected", f"Draft {draft_id} rejected by user.")
        db.commit()

        logger.info(f"Draft rejected successfully: {draft_id}")

        return {
            "message": "Draft rejected.",
            "id": draft_id,
            "status": DraftStatus.rejected
        }

    except HTTPException:
        raise

    except Exception as error:
        logger.error(f"Failed to reject draft {draft_id}: {error}", exc_info = True)

        raise HTTPException(status_code = 500, detail = f"Failed to reject draft: {error}")

@app.post("/drafts/{draft_id}/send", tags = ["Drafts"])
def send_draft(
    draft_id: str,
    body: SendRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Ask the deep agent to send an approved/edited draft.

    The agent's send tool includes a LangGraph ``interrupt()`` – the
    response will contain ``"interrupted": true`` and an
    ``"interrupt_payload"`` with the email preview.  The client must
    then call ``POST /drafts/{id}/resume`` to confirm or cancel.

    Only drafts with status 'approved' or 'edited' can be sent.
    """

    try:
        logger.info(f"Send request for draft: {draft_id}")
        draft = _get_draft_or_404(db, draft_id)

        if draft.status not in (DraftStatus.approved, DraftStatus.edited):
            logger.warning(f"Cannot send draft {draft_id}: status is {draft.status}")

            raise HTTPException(
                status_code = 409,
                detail = "Draft must be approved or edited before sending.",
            )

        if not GmailService().is_authenticated():
            logger.warning("Send attempt without Gmail authentication")

            raise HTTPException(status_code = 401, detail = "Gmail not authenticated.")

        logger.info(f"Invoking agent to send draft: {draft_id}")
        result = DraftlyAgent().run_send(draft_id = draft_id, thread_id = body.thread_id)

        if not result.get("interrupted"):
            draft.status = DraftStatus.sent
            write_log(db, "email_sent", f"Draft {draft_id} sent (no interrupt).")
            db.commit()
            logger.info(f"Draft sent successfully (no interrupt): {draft_id}")

        logger.info(f"Send result: {result}")

        return result

    except HTTPException:
        raise

    except Exception as error:
        logger.error(f"Failed to send draft {draft_id}: {error}", exc_info = True)

        raise HTTPException(status_code = 500, detail = f"Failed to send draft: {error}")

@app.post("/drafts/{draft_id}/resume", tags = ["Drafts"])
def resume_send(
    draft_id: str,
    body: ResumeRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Resume an interrupted send-approval workflow.

    After the agent pauses for HITL approval (``/drafts/{id}/send``
    returns ``"interrupted": true``), the client calls this endpoint
    with the human's decision.

    Parameters
    ----------
    body.thread_id : str
        LangGraph thread ID from the interrupted run.
    body.approved  : bool
        True to send the email, False to abort.
    body.reason    : str
        Optional rejection reason recorded in the log.
    """

    try:
        logger.info(f"Resume send for draft: {draft_id} (approved={body.approved})")
        draft = _get_draft_or_404(db, draft_id)
        result = DraftlyAgent().resume(
            thread_id = body.thread_id,
            approved = body.approved,
            reason = body.reason,
        )

        if body.approved:
            draft.status = DraftStatus.sent
            write_log(db, "email_sent", f"Draft {draft_id} sent after human approval.")
            logger.info(f"Draft approved and sent: {draft_id}")

        else:
            write_log(db, "send_rejected", f"Draft {draft_id} send rejected. Reason: {body.reason}")
            logger.info(f"Draft send rejected: {draft_id} - Reason: {body.reason}")
        db.commit()

        return result

    except HTTPException:
        raise

    except Exception as error:
        logger.error(f"Failed to resume send for draft {draft_id}: {error}", exc_info = True)

        raise HTTPException(status_code = 500, detail = f"Failed to resume send: {error}")

@app.get("/logs", tags = ["Logs"])
def get_logs(
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Return activity logs in reverse chronological order.

    Parameters
    ----------
    limit : int  (1-1000, default 100)
        Maximum number of log entries to return.
        :param limit:
        :param db:
    """

    try:
        logger.info(f"Retrieving logs (limit={limit})")
        logs = db.query(Log).order_by(Log.timestamp.desc()).limit(limit).all()

        logger.info(f"Retrieved {len(logs)} log entries")

        return {
            "count": len(logs),
            "logs": [
                {"id": l.id, "event": l.event, "detail": l.detail, "timestamp": l.timestamp}
                for l in logs
            ],
        }

    except Exception as error:
        logger.error(f"Failed to retrieve logs: {error}", exc_info = True)

        raise HTTPException(status_code = 500, detail = f"Failed to retrieve logs: {error}")

def _get_draft_or_404(db: Session, draft_id: str) -> type[Draft]:
    """Fetch a Draft row or raise HTTP 404."""

    try:
        draft = db.query(Draft).filter(Draft.id == draft_id).first()

        if not draft:
            logger.warning(f"Draft not found: {draft_id}")

            raise HTTPException(status_code = 404, detail = f"Draft '{draft_id}' not found.")

        return draft

    except HTTPException:
        raise

    except Exception as error:
        logger.error(f"Error fetching draft {draft_id}: {error}", exc_info = True)

        raise HTTPException(status_code = 500, detail = f"Error fetching draft: {error}")


def _persist_fallback_drafts(db: Session, max_results: int) -> int:
    """Persist simple pending drafts directly from unread emails when agent saving fails."""

    try:
        logger.info(f"Creating fallback drafts (max_results={max_results})")
        emails = GmailService().fetch_unread_emails(max_results)
        user_profile = GmailService().get_user_profile()
        user_signature = GmailService().detect_user_signature(max_sent = 10)
        created = 0

        for email in emails:
            try:
                existing = db.query(Draft).filter(
                    Draft.message_id == (email.message_id or None),
                    Draft.thread_id == (email.thread_id or None),
                ).first()

                if existing:
                    logger.debug(f"Draft already exists, skipping: {email.subject}")

                    continue

                draft = Draft(
                    id = str(uuid.uuid4()),
                    thread_id = email.thread_id,
                    message_id = email.message_id,
                    sender = email.sender,
                    subject = email.subject or "(no subject)",
                    original_body = email.body or "",
                    draft_body = _generate_professional_reply(
                        to_email = email.sender,
                        original_subject = email.subject,
                        user_profile = user_profile,
                        user_signature = user_signature,
                    ),
                    status = DraftStatus.pending,
                    tone = "formal",
                )
                db.add(draft)
                write_log(db, "draft_created", f"Fallback draft {draft.id} created for: {draft.subject}")
                created += 1
                logger.debug(f"Fallback draft created: {draft.id}")

            except Exception as e:
                logger.warning(f"Error creating fallback draft for email {email.subject}: {e}")

                continue

        if created > 0:
            db.commit()
            logger.info(f"Committed {created} fallback drafts")

        return created

    except Exception as error:
        logger.error(f"Error in fallback draft persistence: {error}", exc_info = True)

        return 0


def _generate_professional_reply(
    to_email: str,
    original_subject: str | None,
    user_profile: dict[str, Any],
    user_signature: str,
) -> str:
    """
    Generate a minimal acknowledgment email (fallback only).

    NOTE: The real intelligent email composition should be done by DraftlyAgent.
    This is ONLY used when the agent fails to persist drafts. It provides a basic
    placeholder so the user always has something in the Drafts section for review,
    but the agent should handle all intelligent content generation, context analysis,
    and appropriate tone matching.

    Parameters
    ----------
    to_email : str
        Recipient email address.
    original_subject : str
        Subject of the original email.
    user_profile : dict
        User profile with 'email' and 'display_name'.
    user_signature : str
        Detected signature from sent emails.
    """

    try:
        logger.debug(f"Generating professional reply to: {to_email}")
        recipient_name = to_email.split("@")[0].replace(".", " ").title()
        if "<" in to_email:
            try:
                recipient_name = to_email.split("<")[0].strip()

            except Exception as error:
                logger.error(f"Error parsing recipient name: {error}", exc_info = True)

                pass

        safe_subject = original_subject or "your email"
        user_display_name = user_profile.get("display_name", "") or "Support Team"
        user_email = user_profile.get("email", "")

        body_lines = [
            f"Dear {recipient_name},",
            "",
            f"Thank you for your message regarding '{safe_subject}'.",
            "",
            "I have received your email and will review it thoroughly before providing a detailed response.",
            "",
            "I appreciate you reaching out. Please expect a comprehensive reply soon.",
            "",
        ]

        if user_signature:
            body_lines.append(user_signature)

        else:
            body_lines.extend([
                "Best regards,",
                user_display_name,
                user_email if user_email else "",
            ])

        result = "\n".join(body_lines)
        logger.debug(f"Professional reply generated: {len(result)} characters")

        return result

    except Exception as error:
        logger.error(f"Error generating professional reply: {error}", exc_info = True)

        return "Thank you for your email. I will get back to you soon."