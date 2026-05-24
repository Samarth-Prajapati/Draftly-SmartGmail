from __future__ import annotations

import base64
import logging
from typing import Any
from pathlib import Path
import requests as req_lib
from email.mime.text import MIMEText
from dataclasses import dataclass, field

from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

from src.config import Settings

logger = logging.getLogger(__name__)

_OAUTH_PKCE_CACHE: dict[str, str] = {}

@dataclass
class EmailMessage:
    """
    Normalised representation of a Gmail message.

    Fields
    ------
    id        : Gmail message ID.
    thread_id : Gmail thread ID (used for proper reply threading).
    message_id: RFC 2822 Message-ID header value.
    sender    : "From" header (maybe 'Name <email>').
    subject   : Subject header.
    body      : Decoded plain-text body (first text/plain part).
    date      : Date header as a string.
    """

    id: str = ""
    thread_id: str = ""
    message_id: str = ""
    sender: str = ""
    subject: str = ""
    body: str = ""
    date: str = ""
    labels: list[str] = field(default_factory = list)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict."""

        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "message_id": self.message_id,
            "sender": self.sender,
            "subject": self.subject,
            "body": self.body,
            "date": self.date,
            "labels": self.labels,
        }

class GmailService:
    """
    Provides authenticated access to the Gmail API.

    The class constructs the OAuth2 client config from .env values
    (GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI) so
    that no credentials.json file is needed in the repository.

    Lifecycle
    ---------
    1. Call ``get_authorization_url()`` → redirect user to Google.
    2. Google redirects back to REDIRECT_URI with ``?code=…``.
    3. Call ``exchange_code(code)`` → token written to TOKEN_FILE.
    4. All subsequent API calls reuse / auto-refresh the stored token.
    """

    def __init__(self) -> None:
        self._token_path = Path(Settings().google_token_file)
        self._client_config = {
            "web": {
                "client_id": Settings().google_client_id,
                "client_secret": Settings().google_client_secret,
                "redirect_uris": [Settings().google_redirect_uri],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }

    def is_authenticated(self) -> bool:
        """Return True if a valid (or refreshable) token exists on disk."""

        try:
            if not self._token_path.exists():
                logger.debug("Token file not found")

                return False

            creds = self._load_credentials()

            result = creds is not None and (creds.valid or creds.refresh_token is not None)
            logger.info(f"Authentication check: {result}")

            return result

        except Exception as error:
            logger.error(f"Error checking authentication: {error}", exc_info = True)

            return False

    def get_authorization_url(self) -> str:
        """
        Build the Google OAuth2 consent URL.

        Returns
        -------
        str
            URL the user must visit to grant Gmail permissions.
        """

        try:
            flow = self._build_flow()
            auth_url, state = flow.authorization_url(
                access_type = "offline",
                include_granted_scopes = "true",
                prompt = "consent",
                code_challenge_method = "S256",
            )

            if state and flow.code_verifier:
                _OAUTH_PKCE_CACHE[state] = flow.code_verifier
                logger.info(f"PKCE state cached: {state}")

            logger.info("Authorization URL generated successfully")

            return auth_url

        except Exception as error:
            logger.error(f"Failed to generate authorization URL: {error}", exc_info = True)

            raise

    def exchange_code(self, code: str, state: str | None = None) -> None:
        """
        Exchange an authorization code for tokens and persist them.

        Parameters
        ----------
        code : str
            The ``code`` query parameter returned by Google after consent.
            :param code:
            :param state:
        """

        try:
            verifier = _OAUTH_PKCE_CACHE.pop(state, None) if state else None
            logger.info(f"Exchanging authorization code (state: {state})")

            flow = self._build_flow(state = state, code_verifier = verifier)
            flow.fetch_token(code = code)
            self._save_credentials(flow.credentials)
            logger.info("Token obtained and saved successfully")

        except Exception as error:
            logger.error(f"Failed to exchange authorization code: {error}", exc_info = True)

            raise

    def revoke_token(self) -> None:
        """
        Revoke the stored token and delete the token file.

        After calling this the user must go through OAuth again.
        """

        try:
            creds = self._load_credentials()

            if creds:
                try:
                    req_lib.post(
                        "https://oauth2.googleapis.com/revoke",
                        params = {"token": creds.token},
                        timeout = 10
                    )
                    logger.info("Token revoked successfully")

                except Exception as error:
                    logger.warning(f"Error revoking token: {error}")

            if self._token_path.exists():
                self._token_path.unlink()
                logger.info("Token file deleted")

        except Exception as error:
            logger.error(f"Failed to revoke token: {error}", exc_info = True)

    def fetch_unread_emails(self, max_results: int = 10) -> list[EmailMessage]:
        """
        Fetch unread emails from the user's INBOX.

        Parameters
        ----------
        max_results : int
            Maximum number of messages to return (default 10).

        Returns
        -------
        list[EmailMessage]
            Parsed email objects, newest first.
        """

        try:
            logger.info(f"Fetching unread emails (max_results={max_results})")
            service = self._get_service()
            result = (
                service.users()
                .messages()
                .list(userId = "me", labelIds = ["INBOX", "UNREAD"], maxResults = max_results)
                .execute()
            )

            emails = [
                self._parse_message(service, msg["id"])
                for msg in result.get("messages", [])
            ]
            logger.info(f"Successfully fetched {len(emails)} unread emails")

            return emails

        except Exception as error:
            logger.error(f"Failed to fetch unread emails: {error}", exc_info = True)

            return []

    def fetch_sent_emails(self, max_results: int = 5) -> list[EmailMessage]:
        """
        Fetch recent SENT emails to learn the user's writing style.

        Parameters
        ----------
        max_results : int
            Maximum number of sent messages to fetch (default 5).

        Returns
        -------
        list[EmailMessage]
            Parsed sent email objects.
        """

        try:
            logger.info(f"Fetching sent emails (max_results={max_results})")
            service = self._get_service()
            result = (
                service.users()
                .messages()
                .list(userId = "me", labelIds = ["SENT"], maxResults = max_results)
                .execute()
            )

            emails = [
                self._parse_message(service, msg["id"])
                for msg in result.get("messages", [])
            ]
            logger.info(f"Successfully fetched {len(emails)} sent emails")

            return emails

        except Exception as error:
            logger.error(f"Failed to fetch sent emails: {error}", exc_info = True)

            return []

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        thread_id: str | None = None,
        in_reply_to: str | None = None,
    ) -> dict[str, Any]:
        """
        Send an email via the Gmail API.

        Parameters
        ----------
        to          : Recipient address.
        subject     : Email subject.
        body        : Plain-text body.
        thread_id   : Gmail thread ID – keeps the message in-thread.
        in_reply_to : RFC 2822 Message-ID of the original message.
                      Sets In-Reply-To and References headers.

        Returns
        -------
        dict
            Gmail API response containing at least ``{"id": ..., "threadId": ...}``.
        """

        try:
            logger.info(f"Preparing to send email to: {to}, subject: {subject[:50]}")
            mime = MIMEText(body, "plain", "utf-8")
            mime["To"] = to
            mime["Subject"] = subject

            if in_reply_to:
                mime["In-Reply-To"] = in_reply_to
                mime["References"] = in_reply_to

            raw = base64.urlsafe_b64encode(mime.as_bytes()).decode("utf-8")
            payload: dict[str, Any] = {"raw": raw}

            if thread_id:
                payload["threadId"] = thread_id

            service = self._get_service()

            result = (
                service.users().messages().send(userId = "me", body = payload).execute()
            )

            logger.info(f"Email sent successfully. Message ID: {result.get('id')}")

            return result

        except Exception as error:
            logger.error(f"Failed to send email to {to}: {error}", exc_info = True)

            raise

    def _build_flow(self, state: str | None = None, code_verifier: str | None = None) -> Flow:
        """Construct a google-auth Flow from the in-memory client config."""

        return Flow.from_client_config(
            self._client_config,
            scopes = Settings().gmail_scopes,
            redirect_uri = Settings().google_redirect_uri,
            state = state,
            code_verifier = code_verifier,
            autogenerate_code_verifier = code_verifier is None,
        )

    def get_user_profile(self) -> dict[str, Any]:
        """
        Fetch the authenticated user's profile (name, email).

        Returns
        -------
        dict
            Containing 'email' and 'display_name'.
        """

        try:
            logger.info("Fetching user profile")
            service = self._get_service()
            profile = service.users().getProfile(userId = "me").execute()
            result = {
                "email": profile.get("emailAddress", ""),
                "display_name": profile.get("displayName", ""),
            }
            logger.info(f"User profile retrieved: {result.get('display_name')} ({result.get('email')})")

            return result

        except Exception as error:
            logger.warning(f"Failed to fetch user profile: {error}")

            return {
                "email": "",
                "display_name": ""
            }

    def detect_user_signature(self, max_sent: int = 10) -> str:
        """
        Mine user's signature by analyzing recent sent emails.
        Returns the most common signature block or empty string if none found.

        Parameters
        ----------
        max_sent : int
            Maximum sent emails to scan (default 10).

        Returns
        -------
        str
            Inferred signature block.
        """

        try:
            logger.info(f"Detecting user signature from {max_sent} sent emails")
            sent_emails = self.fetch_sent_emails(max_results = max_sent)
            signatures: dict[str, int] = {}

            for email in sent_emails:
                lines = email.body.strip().split("\n")

                if len(lines) >= 2:
                    potential_sig = "\n".join(lines[-3:]).strip()

                    if 5 < len(potential_sig) < 200:
                        signatures[potential_sig] = signatures.get(potential_sig, 0) + 1

            if signatures:
                most_common_sig = max(signatures, key = signatures.get)
                logger.info(f"Signature detected: {len(most_common_sig)} characters")

                return most_common_sig

            logger.info("No signature pattern detected in sent emails")

            return ""

        except Exception as error:
            logger.warning(f"Error detecting user signature: {error}")

            return ""

    def _load_credentials(self) -> Credentials | None:
        """Load and optionally refresh credentials from the token file."""

        try:
            if not self._token_path.exists():
                logger.debug("Token file does not exist")

                return None

            logger.info("Loading credentials from token file")
            creds = Credentials.from_authorized_user_file(
                str(self._token_path), Settings().gmail_scopes
            )

            if not creds.valid and creds.expired and creds.refresh_token:
                logger.info("Refreshing expired credentials")
                creds.refresh(Request())
                self._save_credentials(creds)

            logger.debug("Credentials loaded successfully")
            return creds

        except Exception as error:
            logger.error(f"Failed to load credentials: {error}", exc_info = True)

            return None

    def _save_credentials(self, creds: Credentials) -> None:
        """Persist credentials to the token file as JSON."""

        try:
            self._token_path.write_text(creds.to_json(), encoding = "utf-8")
            logger.info(f"Credentials saved to {self._token_path}")

        except Exception as error:
            logger.error(f"Failed to save credentials: {error}", exc_info = True)

            raise

    def _get_service(self):
        """Return an authenticated Gmail API resource, refreshing if needed."""

        try:
            creds = self._load_credentials()

            if creds is None or (not creds.valid and not creds.refresh_token):
                error_msg = (
                    "Gmail is not authenticated. "
                    "Visit /auth/connect to complete the OAuth flow first."
                )
                logger.error(error_msg)

                raise RuntimeError(error_msg)

            logger.debug("Gmail API service created successfully")

            return build("gmail", "v1", credentials = creds)

        except Exception as error:
            logger.error(f"Failed to create Gmail service: {error}", exc_info = True)

            raise

    def _parse_message(self, service, message_id: str) -> EmailMessage:
        """
        Fetch a single message by ID and normalize it into an EmailMessage.

        Parameters
        ----------
        service    : Authenticated Gmail API resource.
        message_id : Gmail internal message ID.
        """

        try:
            logger.debug(f"Parsing message: {message_id}")
            detail = (
                service.users()
                .messages()
                .get(userId = "me", id = message_id, format = "full")
                .execute()
            )

            headers = {
                h["name"].lower(): h["value"]
                for h in detail.get("payload", {}).get("headers", [])
            }

            result = EmailMessage(
                id = detail.get("id", ""),
                thread_id = detail.get("threadId", ""),
                message_id = headers.get("message-id", ""),
                sender = headers.get("from", ""),
                subject = headers.get("subject", "(no subject)"),
                body = self._extract_body(detail.get("payload", {})),
                date = headers.get("date", ""),
                labels = detail.get("labelIds", [])
            )
            logger.debug(f"Message parsed successfully: {result.subject[:50]}")

            return result

        except Exception as error:
            logger.error(f"Failed to parse message {message_id}: {error}", exc_info = True)

            raise

    @staticmethod
    def _extract_body(payload: dict) -> str:
        """
        Recursively walk a Gmail message payload and return the first
        text/plain part, URL-safe base64 decoded.

        Parameters
        ----------
        payload : dict
            The 'payload' field from a Gmail messages.get response.
        """

        try:
            mime_type: str = payload.get("mimeType", "")

            if mime_type == "text/plain":
                data = payload.get("body", {}).get("data", "")
                if data:
                    result = base64.urlsafe_b64decode(data).decode("utf-8", errors = "ignore")
                    logger.debug(f"Extracted plain text body: {len(result)} characters")

                    return result

            for part in payload.get("parts", []):
                result = GmailService._extract_body(part)

                if result:
                    return result

            logger.debug("No text/plain part found in message")

            return ""

        except Exception as error:
            logger.warning(f"Error extracting message body: {error}")

            return ""