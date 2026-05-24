from __future__ import annotations

import uuid
import logging
from typing import Any
from langchain_ollama import ChatOllama
from deepagents import create_deep_agent
from langgraph.types import Command, interrupt
from langgraph.checkpoint.memory import MemorySaver

from src.config import Settings
from src.services import GmailService
from src.tools import (
    fetch_sent_emails,
    fetch_unread_emails,
    get_draft_by_id,
    list_pending_drafts,
    save_draft,
    send_approved_email
)

logger = logging.getLogger(__name__)

def send_email_with_approval(
    to: str,
    subject: str,
    body: str,
    thread_id: str = "",
    in_reply_to: str = "",
) -> str:
    """
    Send an email ONLY after receiving explicit human approval.

    This tool pauses graph execution via LangGraph's interrupt() and
    waits for the human operator to approve or reject send.

    The agent must call this instead of sending emails directly.

    Parameters
    ----------
    to          : Recipient email address.
    subject     : Subject line.
    body        : Full plain-text body of the reply.
    thread_id   : Gmail thread ID for proper threading.
    in_reply_to : RFC 2822 Message-ID of the original email.
    """

    try:
        logger.info(f"Requesting approval to send email to: {to}, subject: {subject[:50]}")
        decision: dict = interrupt(
            {
                "type": "send_approval",
                "message": "Agent wants to send the following email. Approve?",
                "to": to,
                "subject": subject,
                "body": body,
                "thread_id": thread_id,
                "in_reply_to": in_reply_to,
            }
        )

        if not decision.get("approved", False):
            reason = decision.get("reason", "No reason given.")
            logger.warning(f"Send rejected by human. Reason: {reason}")

            return f"Send REJECTED by human. Reason: {reason}"

        logger.info(f"Send approved by human, dispatching email to: {to}")
        result = GmailService().send_email(
            to = to,
            subject = subject,
            body = body,
            thread_id = thread_id or None,
            in_reply_to = in_reply_to or None
        )

        return (
            f"Email sent successfully after human approval.\n"
            f"Gmail Message ID : {result.get('id', 'unknown')}\n"
            f"Thread ID        : {result.get('threadId', 'unknown')}"
        )

    except Exception as error:
        logger.error(f"Error in send_email_with_approval: {error}", exc_info = True)

        raise

_SYSTEM_PROMPT = """
# You are Draftly, a professional Gmail AI assistant. Your role is to intelligently generate personalized email replies.

Your primary workflow:
1. Call fetch_sent_emails to learn the user's personal writing style,
   tone, greeting patterns, sign-off preferences, and signature format.
2. Call fetch_unread_emails to get unread inbox messages.
3. For EACH unread email, generate a thoughtful, contextual reply that:
   - ANALYZES the incoming email to understand what is being asked/stated
   - GENERATES appropriate, relevant content based on email context (not generic templates)
   - MATCHES the user's writing style inferred from sent emails
   - USES the user's detected tone, greeting patterns, and signature
   - ADDRESSES the specific points raised in the original email
   - INCLUDES call-to-action or next steps where appropriate
   - PRESERVES email threading metadata (thread_id, message_id_header)
   - INCLUDES proper business etiquette with greeting and professional sign-off
4. Call save_draft for each generated reply (status: pending).
   NEVER skip this step - save every generated draft.
5. After saving all drafts, call list_pending_drafts to confirm creation.
6. Do NOT send any email autonomously.
   Only call send_email_with_approval when explicitly instructed by the user
   to send a specific draft, and even then the tool will pause for
   human confirmation before dispatching.

Quality guidelines for generated content:
- CONTEXT-AWARE: Each reply must directly address the content and tone of the original email
- PROFESSIONAL: Use proper business email structure with greeting, body, and signature
- PERSONALIZED: Mirror the user's actual writing style, not generic templates
- CONCISE YET COMPLETE: Provide sufficient detail without unnecessary verbosity
- AUTHENTIC: Sound like the user, not an AI assistant
- THREADED PROPERLY: Maintain Gmail thread context with correct metadata
- SKIP INTELLIGENTLY: Only skip newsletters, no-reply addresses, or system notifications

> IMPORTANT: The quality of drafts depends entirely on intelligent content generation based on
email context. Do not use static templates - analyze what needs to be said in each reply.
""".strip()

class DraftlyAgent:
    """
    Orchestrates the Draftly deep agent lifecycle.

    Attributes
    ----------
    _checkpointer : MemorySaver
        Persists agent state so interrupted runs can be resumed.
    _agent : CompiledStateGraph
        The compiled deepagents graph.

    Methods
    -------
    run_draft_generation(thread_id)
        Fetch emails and generate + save draft replies.
    run_send(draft_id, thread_id)
        Instruct the agent to send a specific approved draft.
    resume(thread_id, approved, reason)
        Resume an interrupted send-approval workflow.
    """

    def __init__(self) -> None:
        """Initialize the deep agent with all tools and a checkpointer."""

        try:
            logger.info("Initializing DraftlyAgent")
            self._checkpointer = MemorySaver()

            model = ChatOllama(
                model = Settings().ollama_model,
                temperature = 0.3
            )
            logger.debug(f"ChatOllama model initialized: {Settings().ollama_model}")

            tools = [
                fetch_unread_emails,
                fetch_sent_emails,
                save_draft,
                list_pending_drafts,
                get_draft_by_id,
                send_approved_email
            ]

            self._agent = create_deep_agent(
                model = model,
                tools = tools,
                system_prompt = _SYSTEM_PROMPT,
                checkpointer = self._checkpointer,
            )
            logger.info("DraftlyAgent initialized successfully")

        except Exception as error:
            logger.error(f"Failed to initialize DraftlyAgent: {error}", exc_info = True)

            raise

    def run_draft_generation(
        self,
        thread_id: str | None = None,
        max_results: int = 10,
    ) -> dict[str, Any]:
        """
        Trigger a full inbox scan + draft generation cycle.

        The agent fetches unread emails, studies the user's sent-email
        style, generates reply drafts, and saves them with status
        'pending' for human review.

        Parameters
        ----------
        thread_id : str | None
            LangGraph thread identifier for checkpointing.
            A new UUID is generated if not provided.

        Returns
        -------
        dict
            ``{"output": str, "thread_id": str, "interrupted": bool}``
            :param thread_id:
            :param max_results:
        """

        try:
            tid = thread_id or str(uuid.uuid4())
            logger.info(f"Starting draft generation (thread={tid}, max_results={max_results})")

            config = {
                "configurable": {
                    "thread_id": tid
                }
            }

            payload = {
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            f"Please fetch up to {max_results} unread emails, learn from my sent emails, "
                            "generate thoughtful reply drafts for each fetched unread email (one draft per email), "
                            "and save all drafts as pending for my review. "
                            "Do not stop after one draft if multiple emails were fetched."
                        ),
                    }
                ]
            }

            result = self._agent.invoke(payload, config = config)

            interrupted = "__interrupt__" in result
            output = (
                result["messages"][-1].content
                if result.get("messages")
                else str(result)
            )

            logger.info(f"Draft generation completed (interrupted={interrupted}, thread={tid})")

            return {
                "output": output,
                "thread_id": tid,
                "interrupted": interrupted
            }

        except Exception as error:
            logger.error(f"Error in run_draft_generation: {error}", exc_info = True)
            raise

    def run_send(self, draft_id: str, thread_id: str | None = None) -> dict[str, Any]:
        """
        Ask the agent to send a specific approved draft.

        The agent will call ``send_email_with_approval`` which triggers
        a LangGraph interrupt, pausing execution until ``resume()`` is
        called.

        Parameters
        ----------
        draft_id  : UUID of the Draft row to send.
        thread_id : LangGraph thread ID (new one if not provided).

        Returns
        -------
        dict
            ``{"output": str, "thread_id": str, "interrupted": bool,
               "interrupt_payload": dict | None}``
        """

        try:
            tid = thread_id or str(uuid.uuid4())
            logger.info(f"Starting send workflow (draft={draft_id}, thread={tid})")

            config = {
                "configurable": {
                    "thread_id": tid
                }
            }

            payload = {
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            f"Please send draft ID {draft_id} using send_email_with_approval. "
                            "Fetch the draft details first, then attempt to send."
                        ),
                    }
                ]
            }

            result = self._agent.invoke(payload, config = config)
            interrupted = "__interrupt__" in result
            interrupt_payload = None

            if interrupted:
                interrupts = result.get("__interrupt__", [])

                if interrupts:
                    interrupt_payload = interrupts[0].value if hasattr(interrupts[0], "value") else interrupts[0]

            output = (
                result["messages"][-1].content
                if result.get("messages")
                else str(result)
            )

            logger.info(f"Send workflow result (interrupted={interrupted}, draft={draft_id})")

            return {
                "output": output,
                "thread_id": tid,
                "interrupted": interrupted,
                "interrupt_payload": interrupt_payload,
            }

        except Exception as error:
            logger.error(f"Error in run_send: {error}", exc_info = True)

            raise

    def resume(
        self,
        thread_id: str,
        approved: bool,
        reason: str = "",
    ) -> dict[str, Any]:
        """
        Resume an interrupted send-approval workflow.

        Called after the human has reviewed the email preview and
        made an approval / reject decision.

        Parameters
        ----------
        thread_id : LangGraph thread ID of the interrupted run.
        approved  : True = send the email, False = abort.
        reason    : Optional rejection reason (shown in the log).

        Returns
        -------
        dict
            ``{"output": str, "thread_id": str, "interrupted": bool}``
        """

        try:
            logger.info(f"Resuming workflow (thread={thread_id}, approved={approved})")

            config = {
                "configurable": {
                    "thread_id": thread_id
                }
            }

            resume_payload = {
                "approved": approved,
                "reason": reason
            }

            result = self._agent.invoke(
                Command(resume = resume_payload),
                config = config
            )

            interrupted = "__interrupt__" in result
            output = (
                result["messages"][-1].content
                if result.get("messages")
                else str(result)
            )

            logger.info(f"Workflow resumed (interrupted={interrupted}, thread={thread_id})")

            return {
                "output": output,
                "thread_id": thread_id,
                "interrupted": interrupted
            }

        except Exception as error:
            logger.error(f"Error in resume: {error}", exc_info = True)

            raise
