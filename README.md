# Draftly

---

### Gmail AI Reply Agent

AI-powered assistant that reads your inbox, learns your writing style from sent emails,
generates context-aware reply drafts, and sends them **only after you approve** - powered
by a configurable Ollama model endpoint, FastAPI, LangChain Deep Agents, and Streamlit.

![Python](https://img.shields.io/badge/Python-3.13-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.136-009688?logo=fastapi)
![Streamlit](https://img.shields.io/badge/Streamlit-1.57-FF4B4B?logo=streamlit)
![LangChain](https://img.shields.io/badge/LangChain-DeepAgents-1C3C3C?logo=langchain)
![Ollama](https://img.shields.io/badge/Ollama-Local_LLM-black)
![SQLite](https://img.shields.io/badge/SQLite-Database-003B57?logo=sqlite)

---

## Table of Contents

- [Overview](#overview)
- [How It Works](#how-it-works)
- [Tech Stack](#tech-stack)
- [Folder Structure](#folder-structure)
- [Prerequisites](#prerequisites)
- [Step 1 — Google Cloud Setup](#step-1--google-cloud-setup)
- [Step 2 — Clone & Virtual Environment](#step-2--clone--virtual-environment)
- [Step 3 — Install Dependencies](#step-3--install-dependencies)
- [Step 4 — Configure .env](#step-4--configure-env)
- [Environment Variables](#environment-variables)
- [Step 5 — Pull Ollama Model](#step-5--pull-ollama-model)
- [Step 6 — Run the Application](#step-6--run-the-application)
- [Step 7 — First-Run: Gmail OAuth](#step-7--first-run-gmail-oauth)
- [Docker](#docker)
- [Usage Flow](#usage-flow)
- [API Reference](#api-reference)
- [Human-in-the-Loop (HITL)](#human-in-the-loop-hitl)
- [Database Schema](#database-schema)
- [Design Decisions](#design-decisions)
- [Troubleshooting](#troubleshooting)

---

## Overview

Professionals spend hours each week drafting routine email replies - confirmations, follow-ups, meeting responses, and 
polite acknowledgements. Draftly automates this by:

1. Fetching your unread Gmail inbox
2. Reading your past sent emails to infer your personal writing style, tone, and phrasing
3. Generating a tailored reply draft for each unread email
4. Storing every draft in SQLite for your review
5. Sending **only** the drafts you explicitly approve - with a two-step HITL confirmation before any email is dispatched

No email is ever sent without your review and approval.

---

## How It Works

```
┌────────────────────────────────────────────────────────────────┐
│                        Streamlit UI                            │
│  Connect Gmail → Generate Drafts → Review → Approve → Send     │
└───────────────────────────┬────────────────────────────────────┘
                            │ HTTP (REST)
┌───────────────────────────▼────────────────────────────────────┐
│                       FastAPI Backend                          │
│              /auth  /emails  /drafts  /logs                    │
└──────┬─────────────────────────────────┬───────────────────────┘
       │                                 │
┌──────▼──────────┐            ┌─────────▼──────────┐
│  DraftlyAgent   │            │   GmailService     │
│  (DeepAgents    │            │   (Google API      │
│  + ChatOllama   │            │   OAuth2 wrapper)  │
│  + LangGraph    │            └────────────────────┘
│  MemorySaver)   │
└──────┬──────────┘
       │  Tools
┌──────▼─────────────────────────────────────────────────────────┐
│  fetch_unread_emails  fetch_sent_emails  send_approved_email   │
│  save_draft           list_pending_drafts  get_draft_by_id     │
└──────────────────────────────┬─────────────────────────────────┘
                               │
                    ┌──────────▼───────────┐
                    │   SQLite (draftly.db)│
                    │   drafts  +  logs    │
                    └──────────────────────┘
```

---

## Tech Stack

| Layer    | Technology                        | Purpose                         |
|----------|-----------------------------------|---------------------------------|
| Frontend | Streamlit 1.57                    | Interactive review UI           |
| Backend  | FastAPI 0.136 + Uvicorn           | REST API server                 |
| Agent    | deepagents + LangGraph            | Deep agent orchestration + HITL |
| LLM      | ChatOllama (langchain-ollama)     | Configurable Ollama endpoint    |
| Tools    | Plain Python functions            | Gmail + DB operations           |
| Gmail    | google-api-python-client + OAuth2 | Email read/send                 |
| Database | SQLite + SQLAlchemy 2.0           | Drafts + activity logs          |
| Config   | python-dotenv + os.getenv         | .env management                 |

---

## Folder Structure

```
draftly/
│
├── main.py                        ← Streamlit frontend entry point
├── Dockerfile                     ← Shared image for backend and UI
├── docker-compose.yml             ← Ollama + backend + Streamlit services
├── .env.example                   ← Copy to .env and fill in values
├── requirements.txt               ← All Python dependencies
├── .env                           ← Your credentials (DO NOT COMMIT)
├── token.json                     ← Auto-generated after OAuth (DO NOT COMMIT)
├── draftly.db                     ← Auto-generated SQLite database
│
└── src/                           ← All application source code
    │
    ├── __init__.py
    │
    ├── config/
    │   ├── __init__.py
    │   └── settings.py            ← Environment config helper
    │
    ├── db/
    │   ├── __init__.py
    │   ├── models.py              ← SQLAlchemy ORM models
    │   │                            Classes: Draft, Log, DraftStatus (enum)
    │   └── session.py             ← DB lifecycle: init_db(), get_db(), write_log()
    │
    ├── services/
    │   ├── __init__.py
    │   └── gmail_service.py       ← GmailService class (OOP)
    │                                 OAuth2 flow, fetch inbox/sent, send email
    │                                 No credentials.json — reads from .env
    │                                 Used directly by the API and agent tools
    │
    ├── tools/
    │   ├── __init__.py            ← Exports ALL_TOOLS list
    │   ├── gmail_tools.py         ← Plain functions used as agent tools
    │   │                            fetch_unread_emails()
    │   │                            fetch_sent_emails()
    │   │                            send_approved_email()  ← HITL guarded
    │   └── db_tools.py            ← Plain functions used as agent tools
    │                                save_draft()
    │                                list_pending_drafts()
    │                                get_draft_by_id()
    │
    ├── agent/
    │   ├── __init__.py
    │   └── draftly_agent.py       ← DraftlyAgent class
    │                                 ChatOllama LLM
    │                                 create_deep_agent() with interrupt_on
    │                                 MemorySaver checkpointer
    │                                 run_draft_generation() / run_send() / resume()
    │                                 Instantiated on demand by the API
    │
    └── api/
        ├── __init__.py
        └── routes.py              ← FastAPI app (all routes on app directly)
                                     /auth, /emails, /drafts, /logs
```

### Key File Responsibilities

| File                              | Class / Object                | Responsibility                           |
|-----------------------------------|-------------------------------|------------------------------------------|
| `src/config/settings.py`          | `Settings`                    | Reads env vars, defaults, and scopes     |
| `src/db/models.py`                | `Draft`, `Log`, `DraftStatus` | ORM table definitions                    |
| `src/db/session.py`               | —                             | `init_db()`, `get_db()`, `write_log()`   |
| `src/services/gmail_service.py`   | `GmailService`, `gmail`       | All Gmail API interactions               |
| `src/tools/gmail_tools.py`        | —                             | Agent-callable Gmail tools               |
| `src/tools/db_tools.py`           | —                             | Agent-callable database tools            |
| `src/agent/draftly_agent.py`      | `DraftlyAgent`, `agent`       | Deep agent with HITL via `interrupt_on`  |
| `src/api/routes.py`               | `app`                         | FastAPI application + all route handlers |
| `main.py`                         | —                             | Streamlit UI entry point                 |
| `Dockerfile`                      | —                             | Builds the shared Python image           |
| `docker-compose.yml`              | —                             | Runs Ollama, backend, and Streamlit      |
| `.env.example`                    | —                             | Template for local and Docker variables  |

---

## Prerequisites

| Tool     | Version     | Install                                                                              |
|----------|-------------|--------------------------------------------------------------------------------------|
| Python   | 3.13+       | [python.org](https://www.python.org/downloads/)                                      |
| Ollama   | Latest      | `brew install ollama` or Docker Compose                                              |
| Git      | Any         | -                                                                                    |
| Docker   | Latest      | [Docker Desktop](https://www.docker.com/products/docker-desktop/)                    |

> **macOS users:** Ensure Xcode CLI tools are installed: `xcode-select --install`
>
> **Docker users:** Install and open Docker Desktop before running the Compose workflow.

---

## Step 1 — Google Cloud Setup

> This step is done once. No `credentials.json` file is used - credentials go directly into `.env`.

**1.1 Create a project**

1. Go to [https://console.cloud.google.com](https://console.cloud.google.com)
2. Click the project dropdown at the top → **New Project**
3. Name it `Draftly` → **Create**

**1.2 Enable the Gmail API**

1. Go to **APIs & Services → Library**
2. Search for `Gmail API` → click it → **Enable**

**1.3 Configure OAuth Consent Screen**

1. Go to **APIs & Services → OAuth consent screen**
2. User type: **External** → **Create**
3. Fill in:
   - App name: `Draftly`
   - User support email: your Gmail
   - Developer contact: your Gmail
4. Click **Save and Continue**
5. On **Scopes** page, click **Add or Remove Scopes** and add:
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `https://www.googleapis.com/auth/gmail.send`
   - `https://www.googleapis.com/auth/gmail.compose`
   - `https://www.googleapis.com/auth/gmail.modify`
6. Click **Save and Continue**
7. On **Test Users** page, click **Add Users** → add your Gmail address
8. Click **Save and Continue** → **Back to Dashboard**

**1.4 Create OAuth2 Credentials**

1. Go to **APIs & Services → Credentials**
2. Click **Create Credentials → OAuth 2.0 Client ID**
3. Application type: **Web application**
4. Name: `Draftly Web Client`
5. Under **Authorised redirect URIs**, click **Add URI** and enter:
   ```
   http://localhost:8000/auth/callback
   ```
6. Click **Create**
7. A popup shows your credentials — **copy both values:**
   - `Client ID` → looks like `123456789-abc.apps.googleusercontent.com`
   - `Client Secret` → looks like `GOCSPX-xxxxxxxxxxxxxxxxxxxx`

> Keep this tab open - you'll paste these into `.env` in Step 4.

---

## Step 2 — Clone & Virtual Environment

```bash
# Go to your projects folder
cd ~/Projects

# Create and enter the project folder
# (or git clone your repo here)
mkdir draftly && cd draftly

# Create virtual environment with Python 3.13
python3.13 -m venv .venv

# Activate it (macOS / Linux)
source .venv/bin/activate

# Verify
python --version
# Expected: Python 3.13.x

which python
# Expected: /Users/yourname/Projects/draftly/.venv/bin/python
```

---

## Step 3 — Install Dependencies

```bash
# Always make sure .venv is active first
source .venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install all dependencies
pip install -r requirements.txt
```

---

## Step 4 — Configure .env

Copy the example file and fill in your values:

```bash
cp .env.example .env
```

Open `.env` in your editor and fill in the required values:

```env
# Google OAuth2 
# From Step 1.4 — Google Cloud Console
GOOGLE_CLIENT_ID=123456789-abc.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-your_client_secret_here
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback
GOOGLE_TOKEN_FILE=token.json

# Ollama 
# Must match a model you have pulled (see Step 5)
OLLAMA_CLOUD_MODEL=qwen2.5:7b
OLLAMA_BASE_URL=http://localhost:11434

# Database
DATABASE_URL=sqlite:///./draftly.db

# Streamlit frontend -> backend URL
DRAFTLY_API_BASE_URL=http://localhost:8000
```

> **Important:** Never commit `.env` or `token.json` to Git.
> Both are in `.gitignore` by default.

## Environment Variables

| Variable               | Required         | Default                               | Purpose                         |
|------------------------|------------------|---------------------------------------|---------------------------------|
| `GOOGLE_CLIENT_ID`     | Yes              | —                                     | Google OAuth client ID          |
| `GOOGLE_CLIENT_SECRET` | Yes              | —                                     | Google OAuth client secret      |
| `GOOGLE_REDIRECT_URI`  | Yes              | `http://localhost:8000/auth/callback` | OAuth callback URL              |
| `GOOGLE_TOKEN_FILE`    | No               | `token.json`                          | OAuth token storage path        |
| `OLLAMA_CLOUD_MODEL`   | Yes for drafting | —                                     | Model tag used by `ChatOllama`  |
| `OLLAMA_BASE_URL`      | No               | `http://localhost:11434`              | Ollama server URL               |
| `DATABASE_URL`         | No               | `sqlite:///./draftly.db`              | SQLAlchemy database URL         |
| `DRAFTLY_API_BASE_URL` | No               | `http://localhost:8000`               | Streamlit API base URL          |

### Docker overrides

When you run with Docker Compose, the container environment is overridden automatically:

- `DATABASE_URL=sqlite:////app/data/draftly.db`
- `GOOGLE_TOKEN_FILE=/app/data/token.json`
- `OLLAMA_BASE_URL=http://ollama:11434`
- `DRAFTLY_API_BASE_URL=http://backend:8000`

---

## Step 5 — Pull Ollama Model

Open a **new terminal** and keep it running throughout development:

```bash
# Start Ollama server (keep this running)
ollama serve
```

In another terminal (with .venv active), pull a model:

```bash
# Recommended — best tool-calling support locally
ollama pull qwen2.5:7b

# Alternatives
ollama pull llama3.1        # Meta, good tool calling
ollama pull mistral-nemo    # Mistral, fast
ollama pull qwen2.5:14b     # Better quality, needs more RAM
```

> **Choosing a model:** The agent requires a model with strong **function/tool calling** support.
> `qwen2.5:7b` is the recommended default for 16GB RAM machines.
> For 8GB RAM, try `qwen2.5:3b` and update `OLLAMA_CLOUD_MODEL` in `.env`.

Verify the model is available:

```bash
ollama list
# Should show your pulled model
```

---

## Step 6 — Run the Application

### Local development

You need **3 terminal tabs**, all with `.venv` activated.

**Terminal 1 - Ollama (keep running)**
```bash
ollama serve
```

**Terminal 2 - FastAPI backend**
```bash
cd ~/Projects/draftly
source .venv/bin/activate
uvicorn src.api.routes:app --reload
```

Expected output:
```
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

**Terminal 3 — Streamlit frontend**
```bash
cd ~/Projects/draftly
source .venv/bin/activate
streamlit run main.py
```

Expected output:
```
  You can now view your Streamlit app in your browser.
  Local URL: http://localhost:8501
```

| Service          | URL                          |
|------------------|------------------------------|
| Streamlit UI     | http://localhost:8501        |
| FastAPI backend  | http://localhost:8000        |
| Swagger API Docs | http://localhost:8000/docs   |
| ReDoc API Docs   | http://localhost:8000/redoc  |

> If you prefer Docker, skip to the **Docker** section below.

---

## Step 7 — First-Run: Gmail OAuth

1. Open Streamlit at **http://localhost:8501**
2. In the left sidebar, the status shows **Gmail Not Connected**
3. Click **Connect Gmail**
4. A link appears - click it to open the Google consent page in your browser
5. Select your Gmail account (must be the test user added in Step 1.3)
6. Click **Allow** on the permissions screen
7. Google redirects automatically to `http://localhost:8000/auth/callback`
8. The FastAPI backend exchanges the code for tokens and saves `token.json`
9. Return to Streamlit - the sidebar now shows **Gmail Connected**

> The `token.json` file is auto-refreshed before expiry. If it ever becomes invalid, delete `token.json` and repeat this 
> step.

---

## Docker

You can run the project with Docker Compose instead of local Python processes.

### What runs in Compose

- `ollama` — model server and model storage volume
- `backend` — FastAPI app on port `8000`
- `frontend` — Streamlit UI on port `8501`

### First-time setup

```bash
cp .env.example .env
```

Fill in your Google OAuth values in `.env`, then start the stack:

```bash
docker compose up --build
```

In a second terminal, pull your Ollama model into the container volume if it is not already available:

```bash
docker compose exec ollama ollama pull qwen2.5:7b
```

Check service status if needed:

```bash
docker compose ps
docker compose logs ollama --tail 200
docker compose logs backend --tail 200
```

Then open:

- Streamlit UI: http://localhost:8501
- FastAPI docs: http://localhost:8000/docs
- FastAPI health: http://localhost:8000/health

> Keep `GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback` in your `.env` so the OAuth callback reaches the 
> backend container.

---

## Usage Flow

### 1. Generate Draft Replies

Click **Generate Draft Replies** in the Streamlit sidebar.

The deep agent runs the following workflow automatically:
- Calls `fetch_sent_emails` → learns your writing style from recent sent messages
- Calls `fetch_unread_emails` → retrieves your unread inbox
- Calls `summarize_unread_emails` → builds short summaries and suggested reply intents
- Lets you set per-email intent preferences (`accept`, `reject`, `neutral`) in the Inbox tab
- For each unread email, generates a context-aware reply matching your tone
- Calls `save_draft` for each reply → stored in SQLite as `pending`
- Calls `list_pending_drafts` → confirms all were saved

This may take 30-90 seconds depending on inbox size and model speed.

### 2. Review Drafts

Go to the **Drafts** tab.

Each draft shows:
- Status badge (`🟡 PENDING`, `🔵 APPROVED`, `🟣 EDITED`, etc.)
- The original email body for context
- An editable text area with the AI-generated reply
- Four action buttons

| Button    | Action                             | Result                         |
|-----------|------------------------------------|--------------------------------|
| Approve   | Accept draft as-is                 | Status → `approved`            |
| Save Edit | Save your changes to the text area | Status → `edited`              |
| Send      | Initiate HITL send flow            | Agent pauses for confirmation  |
| Reject    | Discard draft                      | Status → `rejected`            |

### 3. Send with HITL Confirmation

When you click **Send** on an approved or edited draft:

1. The FastAPI backend triggers the deep agent's send flow
2. The agent calls `send_approved_email` - but `interrupt_on` pauses it **before** the Gmail API is called
3. Streamlit shows a **confirmation panel** with the exact email content
4. You can:
   - Click **Confirm Send** → email is dispatched via Gmail (status → `sent`)
   - Click **Cancel Send** → operation is aborted (status unchanged)

### 4. Monitor Activity

Go to the **Activity Log** tab to see every event: draft created, approved, edited, rejected, sent, or failed - with 
timestamps.

---

## API Reference

Full interactive documentation at **http://localhost:8000/docs**

### Health

| Method   | Path      | Description                                     |
|----------|-----------|-------------------------------------------------|
| `GET`    | `/`       | Health check - returns service name and version |
| `GET`    | `/health` | Liveness probe                                  |

### Auth

| Method   | Path                    | Description                                 |
|----------|-------------------------|---------------------------------------------|
| `GET`    | `/auth/status`          | Check if Gmail is connected                 |
| `GET`    | `/auth/connect`         | Get OAuth2 consent URL (Step 1 of flow)     |
| `GET`    | `/auth/callback?code=…` | Exchange auth code for token (Step 2, auto) |
| `POST`   | `/auth/disconnect`      | Revoke access and delete token              |

### Emails

| Method     | Path                | Query Params                        | Description                                   |
|------------|---------------------|-------------------------------------|-----------------------------------------------|
| `GET`      | `/emails/inbox`     | `max_results` (1-50, default 10)    | Fetch unread emails from Gmail directly       |
| `GET`      | `/emails/summaries` | `max_results` (1-50, default 10)    | Fetch short summaries and suggested intents   |

### Drafts

| Method   | Path                   | Body                                            |  Description                                     |
|----------|------------------------|-------------------------------------------------|--------------------------------------------------|
| `POST`   | `/drafts/generate`     | `{"max_results": 10, "intent_preferences": {}}` | Run the AI agent: fetch + generate + save drafts |
| `GET`    | `/drafts`              | `?status=pending\|approved\|…`                  | List drafts, optionally filtered                 |
| `GET`    | `/drafts/{id}`         | -                                               | Get a single draft by UUID                       |
| `PATCH`  | `/drafts/{id}/approve` | -                                               | Mark draft as approved                           |
| `PATCH`  | `/drafts/{id}/edit`    | `{"draft_body": "…"}`                           | Update draft body (sets status to edited)        |
| `PATCH`  | `/drafts/{id}/reject`  | -                                               | Reject draft                                     |
| `POST`   | `/drafts/{id}/send`    | `{"thread_id": null}`                           | Initiate send (triggers HITL interrupt)          |
| `POST`   | `/drafts/{id}/resume`  | `{"thread_id":"…","approved":true,"reason":""}` | Resume after HITL decision                       |

### Logs

| Method   | Path    | Query Params                  | Description                |
|----------|---------|-------------------------------|----------------------------|
| `GET`    | `/logs` | `limit` (1–1000, default 100) | Fetch activity log entries |

### Example: Generate and send a draft (curl)

```bash
# 1. Generate drafts
curl -X POST http://localhost:8000/drafts/generate \
  -H "Content-Type: application/json" \
  -d '{"max_results": 10, "intent_preferences": {}}'

# 2. List pending drafts
curl http://localhost:8000/drafts?status=pending

# 3. Approve a draft (replace UUID)
curl -X PATCH http://localhost:8000/drafts/abc-123/approve

# 4. Initiate send (returns interrupted=true + thread_id)
curl -X POST http://localhost:8000/drafts/abc-123/send \
  -H "Content-Type: application/json" \
  -d '{"thread_id": null}'

# 5. Confirm send (use thread_id from step 4)
curl -X POST http://localhost:8000/drafts/abc-123/resume \
  -H "Content-Type: application/json" \
  -d '{"thread_id": "uuid-from-step-4", "approved": true, "reason": ""}'
```

---

## Human-in-the-Loop (HITL)

Draftly uses deepagents built-in `interrupt_on` parameter - no manual `interrupt()` call inside any tool.

### How it works

```cmd
# In draftly_agent.py - the entire HITL config:
_INTERRUPT_ON = {
    "send_approved_email": {
        "allowed_decisions": ["approve", "edit", "reject"],
    },
}

self._agent = create_deep_agent(
    model=self._llm,
    tools=self._tools,
    interrupt_on=_INTERRUPT_ON,      # ← that's it
    checkpointer=self._checkpointer,
)
```

### Interrupt payload structure

When the agent is interrupted, `result.interrupts[0].value` contains:

```json
{
  "action_requests": [
    {
      "name": "send_approved_email",
      "args": {
        "to": "alice@example.com",
        "subject": "Re: Project Update",
        "body": "Hi Alice,\n\nThank you for the update...",
        "thread_id": "18abc123def",
        "in_reply_to": "<message-id@mail.gmail.com>"
      }
    }
  ],
  "review_configs": [
    {
      "action_name": "send_approved_email",
      "allowed_decisions": ["approve", "edit", "reject"]
    }
  ]
}
```

### Resume options

```cmd
# Approve as-is
agent.resume(thread_id=tid, decision_type="approve")

# Reject
agent.resume(thread_id=tid, decision_type="reject")

# Edit recipient / body then send
agent.resume(
    thread_id=tid,
    decision_type="edit",
    edited_args={
        "name": "send_approved_email",
        "args": {
            "to": "corrected@example.com",
            "subject": "Re: Project Update",
            "body": "Updated reply text here.",
            "thread_id": "18abc123def",
            "in_reply_to": "<message-id@mail.gmail.com>",
        },
    },
)
```

### Why interrupt_on instead of manual interrupt()

`interrupt_on` is the idiomatic deepagents approach:
- Declared at agent construction time - no logic inside tools
- The framework automatically batches multiple tool interrupts
- Compatible with `version="v2"` invoke semantics (`result.interrupts`)
- `MemorySaver` checkpointer freezes the full graph state between pause and resume

---

## Database Schema

### `drafts` table

| Column          | Type        | Description                                                    |
|-----------------|-------------|----------------------------------------------------------------|
| `id`            | TEXT (UUID) | Primary key                                                    |
| `thread_id`     | TEXT        | Gmail thread ID for reply threading                            |
| `message_id`    | TEXT        | RFC 2822 Message-ID of original email (for In-Reply-To header) |
| `sender`        | TEXT        | From address of the original email                             |
| `subject`       | TEXT        | Subject of the original email                                  |
| `original_body` | TEXT        | Full plain-text body of the email being replied to             |
| `draft_body`    | TEXT        | AI-generated reply text                                        |
| `status`        | ENUM        | `pending` → `approved/edited` → `sent` or `rejected`           |
| `tone`          | TEXT        | Tone used: `formal`, `friendly`, `concise`                     |
| `created_at`    | DATETIME    | UTC creation timestamp                                         |
| `updated_at`    | DATETIME    | UTC last-modified timestamp                                    |

### `logs` table

| Column      | Type        | Description                                                       |
|-------------|-------------|-------------------------------------------------------------------|
| `id`        | TEXT (UUID) | Primary key                                                       |
| `event`     | TEXT        | Event code: `draft_created`, `draft_approved`, `email_sent`, etc. |
| `detail`    | TEXT        | Human-readable description                                        |
| `timestamp` | DATETIME    | UTC timestamp                                                     |

### Draft lifecycle

```
[Agent generates]
      │
      ▼
   pending
      │
   ┌──┴──────────┐
   │             │
   ▼             ▼
approved       edited  ←── user edits body
   │             │
   └──────┬──────┘
          │
          ▼
     [HITL confirm]
          │
     ┌────┴────┐
     │         │
     ▼         ▼
   sent      rejected
```

---

## Design Decisions

**No `credentials.json`**
All OAuth2 credentials are read from `.env` via `python-dotenv` and `os.getenv`. `GmailService` builds the client config 
dict at runtime. This avoids committing sensitive files and fits cleanly into any deployment environment.

**`ChatOllama` instead of `init_chat_model`**
`ChatOllama` from `langchain-ollama` is the direct, explicit integration class. It takes `model` and `base_url` as typed
constructor arguments, making the Ollama connection explicit and testable without any string-parsing indirection.

**`interrupt_on` instead of manual `interrupt()`**
Tools stay clean - they are pure functions with no LangGraph primitives inside. HITL is declared once at agent 
construction, making the approval surface easy to audit and extend.

**OOP for services and agents, plain functions for tools**
`GmailService` and `DraftlyAgent` are classes because they manage stateful resources (OAuth credentials, checkpointer, 
compiled graph). Tools are plain functions because deepagents reads their type hints and docstrings to auto-generate 
tool schemas - no decorator needed.

**All routes on `app` directly - no `APIRouter`**
Keeps the entire API surface in one file (`src/api/routes.py`) for straightforward navigation. For a larger project, 
splitting into routers would be appropriate.

**`MemorySaver` checkpointer**
Persists the LangGraph agent state in memory for the lifetime of the FastAPI process. State survives a HITL interrupt 
and can be resumed by thread ID. For production, swap to `langgraph.checkpoint.postgres.PostgresSaver`.

**Docker Compose for local dev**
Compose keeps the backend, UI, and Ollama model server in separate containers while sharing the SQLite/token volume for 
a smoother setup on macOS and Linux.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'src'`**
Always run from the project root (`draftly/`), never from inside `src/`:
```bash
cd ~/Projects/draftly
uvicorn src.api.routes:app --reload
# NOT: cd src && python main.py  ✗
```

**`ConnectionRefusedError` from Ollama**

Ollama server isn't running. Start it:
```bash
ollama serve
```

**`RuntimeError: Gmail is not authenticated`**
Visit http://localhost:8501, click **Connect Gmail**, and complete the OAuth flow.

**`redirect_uri_mismatch` from Google**
The redirect URI in Google Cloud Console must be exactly:
```
http://localhost:8000/auth/callback
```
No trailing slash. Check under **APIs & Services → Credentials → your OAuth client**.

**Agent produces no drafts / tool calling fails**
The Ollama model may not support tool calling. Use `qwen2.5:7b` or `llama3.1`:
```bash
ollama pull qwen2.5:7b
# Update OLLAMA_CLOUD_MODEL=qwen2.5:7b in .env
```

**`model not found (404)`**
The model tag is not available on your Ollama instance. Run:
```bash
ollama list
ollama pull <model-name>
```
Then update `OLLAMA_CLOUD_MODEL` in `.env` to match the installed tag.

**`model requires more system memory`**
The selected model is too large for the available RAM. Use a smaller model such as `qwen2.5:3b` or increase the 
available memory in Docker Desktop / your machine.

**`token.json` expired / invalid**
Delete it and re-authenticate:
```bash
rm token.json
# Then click Connect Gmail in Streamlit again
```

**`service "ollama" is not running`**
Start the Compose stack first:
```bash
docker compose up -d ollama
```
If the container keeps exiting, inspect its logs:
```bash
docker compose logs ollama --tail 200
```

**Gmail 403 `insufficientPermissions`**
All four scopes must be present on the OAuth consent screen AND you must have accepted them during the consent flow. 
Delete `token.json` and re-connect to trigger a fresh consent screen with all scopes.

**Streamlit shows `Connection refused` errors**
The FastAPI backend isn't running. Start it:
```bash
uvicorn src.api.routes:app --reload
```

---

Built with FastAPI · LangChain DeepAgents · LangGraph · Ollama · Streamlit