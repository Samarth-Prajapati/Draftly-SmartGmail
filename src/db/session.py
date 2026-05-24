import logging
from sqlalchemy.orm import Session
from collections.abc import Generator

from src.db import Base, Log, SessionLocal, engine

logger = logging.getLogger(__name__)

def init_db() -> None:
	"""Create all database tables if they do not already exist."""

	try:
		logger.info("Initializing database tables...")
		Base.metadata.create_all(bind = engine)
		logger.info("Database tables initialized successfully")

	except Exception as error:
		logger.error(f"Failed to initialize database: {error}", exc_info = True)

		raise

def get_db() -> Generator[Session, None, None]:
	"""Yield a SQLAlchemy session for request-scoped DB access."""

	db = SessionLocal()
	logger.debug("Database session created")

	try:
		yield db

	except Exception as error:
		logger.error(f"Database session error: {error}", exc_info = True)

		raise

	finally:
		db.close()
		logger.debug("Database session closed")


def write_log(db: Session, event: str, detail: str = "") -> None:
	"""Append a log event using an existing session/transaction."""

	try:
		db.add(Log(event = event, detail = detail))
		logger.debug(f"Log entry queued: {event}")

	except Exception as error:
		logger.error(f"Failed to write log entry ({event}): {error}", exc_info = True)

