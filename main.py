from __future__ import annotations

import time
import logging
import requests
from typing import Any
import streamlit as st

from src import app

logger = logging.getLogger(__name__)
logging.basicConfig(
    level = logging.INFO,
    format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

API = "http://localhost:8000"

st.set_page_config(
    page_title = "Draftly",
    layout = "wide",
    initial_sidebar_state = "expanded"
)

if "last_inbox_fetch_max" not in st.session_state:
    st.session_state["last_inbox_fetch_max"] = 10

if "last_inbox_fetch_count" not in st.session_state:
    st.session_state["last_inbox_fetch_count"] = 0

def api(method: str, path: str, **kwargs) -> dict[str, Any]:
    """
    Make an API request and return parsed JSON.

    Returns an empty dict (with an 'error' key) on failure so the UI
    never crashes on network issues.
    """

    try:
        logger.info(f"API request: {method} {path}")
        resp = requests.request(method, f"{API}{path}", timeout = 120, **kwargs)

        if resp.ok:
            logger.info(f"API success: {method} {path}")

            return resp.json()

        error_msg = resp.json().get("detail", resp.text)
        logger.warning(f"API error response: {method} {path} - {error_msg}")

        return {
            "error": error_msg
        }

    except Exception as exc:
        logger.error(f"API request failed: {method} {path} - {exc}", exc_info = True)

        return {
            "error": str(exc)
        }

with st.sidebar:
    st.markdown("## Draftly")
    st.caption("Gmail AI Reply Agent")
    st.divider()

    status = api("GET", "/auth/status")
    connected = status.get("connected", False)

    if connected:
        st.success("Gmail Connected")

        if st.button("Disconnect Gmail", use_container_width = True):
            api("POST", "/auth/disconnect")
            st.rerun()

    else:
        st.warning("Gmail Not Connected")
        if st.button("Connect Gmail", use_container_width = True, type = "primary"):
            result = api("GET", "/auth/connect")
            auth_url = result.get("auth_url")

            if auth_url:
                st.markdown(
                    f"**[Click here to authorise Gmail]({auth_url})**\n\n"
                    "After authorising, Google will redirect to the callback URL. "
                    "The app will authenticate automatically."
                )

            else:
                st.error(result.get("error", "Could not get auth URL."))

    st.divider()

    st.markdown("### AI Agent")
    target_generate_count = (
        st.session_state.get("last_inbox_fetch_count")
        or st.session_state.get("last_inbox_fetch_max", 10)
    )
    st.caption(f"Draft generation target: {target_generate_count} email(s)")
    
    if st.button(
        "Generate Draft Replies",
        use_container_width = True,
        type = "primary",
        disabled = not connected,
        help = "Runs the deep agent: fetches inbox, studies your style, generates drafts.",
    ):
        with st.spinner("Agent is working… this may take a minute"):
            result = api("POST", f"/drafts/generate?max_results={target_generate_count}")

        if "error" in result:
            st.error(result["error"])

        else:
            st.success("Draft generation complete!")
            st.caption(result.get("output", ""))
            st.rerun()

    st.divider()
    st.caption("FastAPI → http://localhost:8000/docs")

tab_inbox, tab_drafts, tab_logs = st.tabs(["Inbox", "Drafts", "Activity Log"])

with tab_inbox:
    st.header("Inbox – Unread Emails")
    col_refresh, col_count = st.columns([1, 3])

    with col_refresh:
        max_results = st.number_input(
            "Max emails",
            min_value = 1,
            max_value = 30,
            value = 10,
            step = 1
        )

    with col_count:
        st.write("")

    if st.button("Fetch Unread Emails", disabled = not connected):
        with st.spinner("Fetching…"):
            data = api("GET", f"/emails/inbox?max_results={max_results}")

        if "error" in data:
            st.error(data["error"])

        else:
            emails = data.get("emails", [])
            st.session_state["last_inbox_fetch_max"] = int(max_results or 10)
            st.session_state["last_inbox_fetch_count"] = len(emails)
            st.info(f"Found **{len(emails)}** unread email(s).")

            for e in emails:
                with st.expander(f"{e['subject']}  —  from {e['sender']}"):
                    st.caption(f"Date: {e['date']}  |  Thread: {e['thread_id']}")
                    st.text_area(
                        "Body",
                        value = e["body"],
                        height = 200,
                        disabled = True,
                        key = f"inbox_{e['id']}"
                    )

with tab_drafts:
    st.header("Draft Management")

    filter_col, refresh_col = st.columns([2, 1])

    with filter_col:
        status_filter = st.selectbox(
            "Filter by status",
            ["All", "pending", "approved", "edited", "rejected", "sent", "failed"],
        )

    with refresh_col:
        st.write("")
        refresh = st.button("Refresh", key = "refresh_drafts")

    params = "" if status_filter == "All" else f"?status={status_filter}"
    data = api("GET", f"/drafts{params}")

    if "error" in data:
        st.error(data["error"])

    else:
        drafts = data.get("drafts", [])
        st.caption(f"Showing {len(drafts)} draft(s).")

        STATUS_ICONS = {
            "pending": "🟡",
            "approved": "🔵",
            "edited": "🟣",
            "rejected": "🔴",
            "sent": "🟢",
            "failed": "⚫",
        }

        for d in drafts:
            icon = STATUS_ICONS.get(d["status"], "⚪")
            label = f"{icon} [{d['status'].upper()}]  {d['subject']}  →  {d['sender']}"
            with st.expander(label, expanded=(d["status"] == "pending")):

                st.markdown(f"**Tone:** `{d['tone']}`  |  **ID:** `{d['id']}`")

                if d.get("original_body"):
                    with st.container():
                        st.markdown("**Original Email:**")
                        st.text_area(
                            "",
                            value = d.get("original_body", ""),
                            height = 120,
                            disabled = True,
                            key = f"orig_{d['id']}"
                        )

                new_body = st.text_area(
                    "Draft Reply (editable)",
                    value = d["draft_body"],
                    height = 200,
                    key = f"body_{d['id']}",
                )

                btn_cols = st.columns(4)
                draft_id = d["id"]

                with btn_cols[0]:
                    if st.button(
                            "Approve",
                            key = f"approve_{draft_id}",
                            disabled = d["status"] in ("sent", "rejected"),
                            use_container_width = True,
                    ):
                        r = api("PATCH", f"/drafts/{draft_id}/approve")
                        st.toast("Approved!" if "error" not in r else f"{r['error']}")
                        time.sleep(0.4)
                        st.rerun()

                with btn_cols[1]:
                    if st.button(
                            "Save Edit",
                            key = f"edit_{draft_id}",
                            disabled = d["status"] in ("sent",),
                            use_container_width = True,
                    ):
                        r = api("PATCH", f"/drafts/{draft_id}/edit", json = {"draft_body": new_body})
                        st.toast("Saved!" if "error" not in r else f"{r['error']}")
                        time.sleep(0.4)
                        st.rerun()

                with btn_cols[2]:
                    if st.button(
                        "Send",
                        key = f"send_{draft_id}",
                        disabled = d["status"] not in ("approved", "edited"),
                        use_container_width = True,
                    ):

                        with st.spinner("Sending email…"):
                            r = api("POST", f"/drafts/{draft_id}/send", json = {"thread_id": None})

                        if "error" in r:
                            st.error(r["error"])
                        else:
                            st.toast(r.get("message", "Sent!"))
                            time.sleep(0.4)
                            st.rerun()

                with btn_cols[3]:
                    if st.button(
                            "Reject",
                            key = f"reject_{draft_id}",
                            disabled = d["status"] in ("sent",),
                            use_container_width = True,
                    ):
                        r = api("PATCH", f"/drafts/{draft_id}/reject")
                        st.toast("Rejected." if "error" not in r else f"{r['error']}")
                        time.sleep(0.4)
                        st.rerun()

with tab_logs:
    st.header("Activity Log")
    log_limit = st.slider("Entries to show", 10, 500, 50)

    if st.button("Load Logs"):
        data = api("GET", f"/logs?limit={log_limit}")

        if "error" in data:
            st.error(data["error"])

        else:
            logs = data.get("logs", [])
            st.caption(f"Showing {len(logs)} log entries.")

            for log in logs:
                ts = str(log.get("timestamp", "")).split(".")[0]
                event = log.get("event", "")
                detail = log.get("detail", "")
                colour = {
                    "email_sent": "🟢",
                    "draft_created": "🟡",
                    "draft_approved": "🔵",
                    "draft_rejected": "🔴",
                    "draft_edited": "🟣",
                    "send_rejected": "🟠",
                    "send_failed": "⚫",
                }.get(event, "⚪")
                st.markdown(f"{colour} `{ts}` **{event}** — {detail}")