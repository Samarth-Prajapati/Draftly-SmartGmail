# Changelog

All notable changes to this project will be documented in this file.

---

## [0.1.0] - 2026-05-24

### Added
- Initial Draftly application structure with FastAPI backend and Streamlit frontend.
- Gmail OAuth2 integration and Gmail API service wrappers.
- Deep-agent based draft generation flow using Ollama (`ChatOllama`) and LangGraph.
- Intent-aware unread email summarization and per-email intent preference support.
- Draft lifecycle management endpoints (`generate`, `approve`, `edit`, `reject`, `send`, `resume`).
- SQLite persistence for drafts and activity logs using SQLAlchemy models.
- Local development setup with `requirements.txt`, `pyproject.toml`, and Poetry lockfile.