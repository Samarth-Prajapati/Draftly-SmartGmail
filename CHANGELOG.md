# Changelog

All notable changes to this project will be documented in this file.

---

## [0.1.1] - 2026-05-28

### Added
- Docker support with `Dockerfile`, `docker-compose.yml`, and `.dockerignore` for running Draftly with Docker Compose.
- `.env.example` with the current configuration keys for local development and Docker.
- README updates covering Docker, environment variables, and the current API / setup flow.

### Changed
- Streamlit now uses a configurable backend URL via `DRAFTLY_API_BASE_URL` instead of a hardcoded localhost API target.
- Ollama settings now use configurable `OLLAMA_BASE_URL` and `OLLAMA_CLOUD_MODEL` values.
- The FastAPI entrypoint was aligned to `src.api.routes:app` for both local and container runs.

### Fixed
- Removed the `src` package import chain that eagerly initialized the API and database during frontend startup.
- Added safe default values for database, Ollama, and backend URLs so missing env vars no longer crash imports.

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