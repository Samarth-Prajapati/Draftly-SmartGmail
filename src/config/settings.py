import os
import logging
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

try:
    load_dotenv()
    logger.info("Environment variables loaded from .env")

except Exception as exc:
    logger.warning(f"Failed to load .env file: {exc}")

class Settings:
    """
    Application settings.

    All values are read from the .env file (or environment variables).
    Defaults are safe fallbacks for local development only.
    """

    # GOOGLE OAUTH2 CREDENTIALS
    google_client_id = os.getenv("GOOGLE_CLIENT_ID")
    google_token_file = os.getenv("GOOGLE_TOKEN_FILE")
    google_redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")
    google_client_secret = os.getenv("GOOGLE_CLIENT_SECRET")

    # OLLAMA MODELS
    ollama_model = os.getenv("OLLAMA_CLOUD_MODEL")
    ollama_base_url = os.getenv("OLLAMA_BASE_URL")

    # SQLITE DATABASE
    database_url = os.getenv("DATABASE_URL")

    # FASTAPI URL
    draftly_api_base_url = os.getenv("DRAFTLY_API_BASE_URL")

    def __init__(self):
        try:
            if not self.google_client_id:
                logger.warning("GOOGLE_CLIENT_ID not set in environment")

            if not self.google_token_file:
                logger.warning("GOOGLE_TOKEN_FILE not set in environment")

            if not self.google_redirect_uri:
                logger.warning("GOOGLE_REDIRECT_URI not set in environment")

            if not self.database_url:
                logger.warning("DATABASE_URL not set in environment")

            if not self.ollama_model:
                logger.warning("OLLAMA_CLOUD_MODEL not set in environment")

            if not self.ollama_base_url:
                logger.warning("OLLAMA_BASE_URL not set in environment")

            if not self.draftly_api_base_url:
                logger.warning("DRAFTLY_API_BASE_URL not set in environment")

            logger.info("Settings initialized")

        except Exception as error:
            logger.error(f"Error initializing settings: {error}", exc_info = True)

    @property
    def gmail_scopes(self) -> list[str]:
        """Required Gmail OAuth2 scopes."""

        return [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.compose",
            "https://www.googleapis.com/auth/gmail.modify",
        ]